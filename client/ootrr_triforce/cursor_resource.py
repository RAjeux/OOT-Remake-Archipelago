"""Append AP markers without reserializing the game's existing BYML values."""
from .i18n import tr
import struct


def append_saved_index(raw, key, baseline):
    return _append_saved_value(raw,key,baseline,"Int",0xd1)


def append_saved_bool(raw, key, value=False):
    return _append_saved_value(raw,key,int(bool(value)),"Bool",0xd0)


def append_saved_bools(raw, marker_keys, value=False):
    """Append saved Bool markers with one array copy and one save-size update."""
    marker_keys = list(marker_keys)
    if (any(type(key) is not int or not 0 <= key < 2**32 for key in marker_keys)
            or len(set(marker_keys)) != len(marker_keys)):
        raise ValueError(tr('Invalid GameData or receipt index.'))
    if not marker_keys:
        return raw
    return _append_saved_values(raw, marker_keys, int(bool(value)), "Bool", 0xd0, strict_collisions=True)


def register_chest_flags(raw, actor_hashes):
    """Give converted chests their actual qualified, persistent Bool keys.

    The native engine may allocate a chest Struct member using a spare Bool.
    AP host readers address ``IsTreasureBoxOpen.<actor>`` directly instead.
    Keep every spare/native save slot intact, append only missing qualified
    Bools, and redirect a small cloned Struct-member array. Existing nodes can
    be shared by BYML; none of their member words are changed in place.
    """
    from .network_catalog import murmur3
    actor_hashes = list(actor_hashes)
    def invalid(detail):
        return ValueError(tr('Invalid GameData or receipt index.') + " " + detail)
    if (any(type(actor) is not int or not 0 < actor < 2**64 for actor in actor_hashes)
            or len(set(actor_hashes)) != len(actor_hashes)):
        raise invalid("Invalid converted chest identities.")
    if not actor_hashes:
        return raw
    wanted = [(murmur3(str(actor)), murmur3("IsTreasureBoxOpen." + str(actor)))
              for actor in actor_hashes]
    if (len({member for member, _ in wanted}) != len(wanted)
            or len({qualified for _, qualified in wanted}) != len(wanted)):
        raise invalid("Converted chest hashes collide.")
    if raw[:2] not in (b"YB", b"BY"):
        raise invalid("Missing BYML header.")
    endian = "<" if raw[:2] == b"YB" else ">"
    order = "little" if endian == "<" else "big"
    word = struct.Struct(endian + "I")
    def bounded(at, length):
        if type(at) is not int or at < 0 or length < 0 or at + length > len(raw):
            raise invalid("Truncated chest GameData.")
        return at
    def read(at):
        return word.unpack_from(raw, bounded(at, 4))[0]
    def small(at):
        bounded(at, 3)
        return int.from_bytes(raw[at:at + 3], order)
    def fields(node):
        bounded(node, 4)
        if raw[node] != 0xc1:
            raise invalid("Expected a chest GameData dictionary.")
        count = small(node + 1)
        bounded(node + 4, count * 8)
        result = {}
        for index in range(count):
            at = node + 4 + index * 8
            key = small(at)
            if key in result:
                raise invalid("Duplicate chest GameData field.")
            result[key] = at + 4
        return result
    def field(node, name):
        at = fields(node).get(keys.get(name))
        if at is None:
            raise invalid("Missing chest GameData field: " + name)
        return at
    def child(node, name, kind):
        at = field(node, name)
        target = read(at)
        bounded(target, 4)
        if raw[at - 1] != kind or raw[target] != kind:
            raise invalid("Unexpected chest GameData type: " + name)
        return target
    def array(node):
        bounded(node, 4)
        if raw[node] != 0xc0:
            raise invalid("Expected a chest GameData array.")
        count = small(node + 1)
        bounded(node + 4, count)
        first = (node + 4 + count + 3) & ~3
        bounded(first, 4 * count)
        return [(raw[node + 4 + index], read(first + 4 * index)) for index in range(count)]
    def number(node, name):
        at = field(node, name)
        if raw[at - 1] not in (0xd1, 0xd3):
            raise invalid("Expected a 32-bit chest GameData hash: " + name)
        return read(at)

    table = read(4)
    bounded(table, 4)
    if not table or raw[table] != 0xc2:
        raise invalid("Missing chest GameData name table.")
    count = small(table + 1)
    bounded(table + 4, count * 4)
    keys = {}
    for index in range(count):
        at = table + read(table + 4 + 4 * index)
        bounded(at, 1)
        end = raw.find(b"\0", at)
        if end < 0:
            raise invalid("Unterminated chest GameData name.")
        name = raw[at:end].decode("utf-8")
        if name in keys:
            raise invalid("Duplicate chest GameData name.")
        keys[name] = index
    data = child(read(12), "Data", 0xc1)
    names = {index: name for name, index in keys.items()}
    # Index all 32-bit key spaces so a same-hash Int/Struct cannot be silently
    # mistaken for an existing Bool. Native 64-bit actor keys are independent.
    registered = {}
    for key, at in fields(data).items():
        if raw[at - 1] != 0xc0:
            continue
        for kind, row in array(read(at)):
            if kind != 0xc1:
                continue
            hashed = fields(row).get(keys.get("Hash"))
            if hashed is None or raw[hashed - 1] not in (0xd1, 0xd3):
                continue
            registered.setdefault(read(hashed), []).append((names.get(key), row))
    opened = registered.get(murmur3("IsTreasureBoxOpen"), [])
    if len(opened) != 1 or opened[0][0] != "Struct":
        raise invalid("Opened chest Struct is missing or ambiguous.")
    member_array = child(opened[0][1], "DefaultValue", 0xc0)
    member_items = array(member_array)
    member_first = (member_array + 4 + len(member_items) + 3) & ~3
    members = {}
    for index, (kind, row) in enumerate(member_items):
        if kind != 0xc1:
            raise invalid("Invalid opened chest member.")
        members.setdefault(number(row, "Hash"), []).append((row, member_first + index * 4))

    def saved_bool(key, *, qualified):
        rows = registered.get(key, [])
        if len(rows) != 1 or rows[0][0] != "Bool":
            raise invalid("Chest Bool is missing, duplicated or has a typed hash collision.")
        row = rows[0][1]
        default = field(row, "DefaultValue")
        if (raw[default - 1] != 0xd0 or read(default) != 0
                or number(row, "SaveFileIndex") != 0
                or (qualified and number(row, "ResetTypeValue") != 8)):
            raise invalid("Chest Bool does not have the expected saved-false schema.")

    missing, edits = [], []
    for member, qualified in wanted:
        rows = members.get(member, [])
        if len(rows) != 1:
            raise invalid("Selected chest Struct member is missing or ambiguous.")
        row, pointer = rows[0]
        at = field(row, "Value")
        old = number(row, "Value")
        saved_bool(old, qualified=old == qualified)
        if qualified in registered:
            saved_bool(qualified, qualified=True)
        else:
            missing.append(qualified)
        if old != qualified:
            edits.append((row, pointer, at, qualified))
    result = append_saved_bools(raw, missing)
    if not edits:
        return result
    out = bytearray(result)
    def append(blob):
        out.extend(bytes(-len(out) % 4))
        at = len(out)
        out.extend(blob)
        return at
    cloned_array = bytearray(raw[member_array:member_first + 4 * len(member_items)])
    for row, pointer, at, qualified in edits:
        clone = bytearray(raw[row:row + 4 + 8 * small(row + 1)])
        word.pack_into(clone, at - row, qualified)
        word.pack_into(cloned_array, pointer - member_array, append(clone))
    word.pack_into(out, field(opened[0][1], "DefaultValue"), append(cloned_array))
    return bytes(out)


def append_transient_string64(raw, key):
    """Add an empty, unsaved pickup argument without enlarging any save table."""
    return _append_saved_value(raw,key,0,"String64",0xa0,save_file=-1)


def append_transient_index(raw, key):
    """Add an unsaved zero Int without enlarging or relocating save tables."""
    return _append_saved_value(raw,key,0,"Int",0xd1,save_file=-1)


def _append_saved_value(raw, key, baseline, group, default_type, *, save_file=0):
    # Preserve the historical single-value byte layout and duplicate rejection.
    return _append_saved_values(raw, [key], baseline, group, default_type, save_file=save_file)


def _append_saved_values(raw, marker_keys, baseline, group, default_type, *, save_file=0, strict_collisions=False):
    if raw[:2] not in (b'YB', b'BY') or not 0<=baseline<2**31:
        raise ValueError(tr('Invalid GameData or receipt index.'))
    out=bytearray(raw)
    wanted=set(marker_keys)
    endian='<' if raw[:2]==b'YB' else '>'
    order='little' if endian=='<' else 'big'
    word=struct.Struct(endian+'I')
    def read(at): return word.unpack_from(out,at)[0]
    def put(at,value): word.pack_into(out,at,value)
    def small(at):return int.from_bytes(out[at:at+3],order)
    def append(blob):
        out.extend(bytes((-len(out))%4))
        at=len(out)
        out.extend(blob)
        return at
    table=read(4)
    if not table or out[table]!=0xc2:raise ValueError(tr('GameData name table is missing.'))
    keys={}
    for i in range(small(table+1)):
        pos=table+read(table+4+4*i)
        keys[raw[pos:raw.index(b'\0',pos)].decode()]=i
    def field(node,name,required=True):
        if out[node]!=0xc1:raise ValueError(tr('Expected a GameData dictionary.'))
        key_id=keys.get(name)
        for i in range(small(node+1)):
            at=node+4+8*i
            if small(at)==key_id:return at+4
        if required:raise ValueError(tr('Missing GameData field: ')+name)
        return None
    def get_node(node,name,kind):
        at=field(node,name)
        if out[at-1]!=kind:raise ValueError(tr('Unexpected GameData type: ')+name)
        child=read(at)
        if out[child]!=kind:raise ValueError(tr('Invalid GameData container: ')+name)
        return child
    def array(node):
        n=small(node+1);first=(node+4+n+3)&~3
        if first+4*n>len(out):raise ValueError(tr('Truncated GameData table.'))
        return n,first
    root=read(12)
    data=get_node(root,'Data',0xc1)
    meta=get_node(root,'MetaData',0xc1)
    ints=get_node(data,group,0xc0)
    count,first=array(ints)
    if strict_collisions:
        for index in range(small(data+1)):
            position=data+4+8*index
            if out[position+3]!=0xc0:continue
            values=read(position+4)
            size,items=array(values)
            for offset in range(size):
                if out[values+4+offset]!=0xc1:continue
                row=read(items+4*offset)
                hashed=field(row,'Hash',False)
                # Actor-ID Bool64bitKey rows are a separate native key space.
                if hashed is not None and out[hashed-1] in (0xd1,0xd3) and read(hashed) in wanted:
                    raise ValueError(tr('The Archipelago marker already exists.'))
    ids=[];template=None
    for i in range(count):
        if out[ints+4+i]!=0xc1:raise ValueError(tr('Unknown saved-integer type.'))
        row=read(first+4*i);h=read(field(row,'Hash'));ids.append(h)
        if h in wanted:raise ValueError(tr('The Archipelago marker already exists.'))
        if template is None:
            default=field(row,'DefaultValue',False)
            reset=field(row,'ResetTypeValue',False)
            save=field(row,'SaveFileIndex',False)
            empty = default is not None and read(default)==0
            if default is not None and default_type==0xa0:
                strings=read(8)
                index=read(default)
                empty=bool(strings and out[strings]==0xc2 and index<small(strings+1)
                           and out[strings+read(strings+4+4*index)]==0)
            if (default and save and reset and out[default-1]==default_type and empty
                    and read(save)==(save_file&0xffffffff) and read(reset)==8):template=row
    if template is None:raise ValueError(tr('Unknown game saved-integer schema.'))
    rows=[read(first+4*i) for i in range(count)]
    # Preserve the existing order; maintain it if it was hash-sorted.
    ordered=ids==sorted(ids)
    added=[]
    for key in marker_keys:
        new_row=append(out[template:template+4+8*small(template+1)])
        put(field(new_row,'Hash'),key)
        if default_type!=0xa0:put(field(new_row,'DefaultValue'),baseline)
        added.append((key,new_row))
    if ordered:
        original=list(zip(ids,rows))
        additions=sorted(added,key=lambda pair:pair[0])
        rows=[];i=j=0
        while i<len(original) and j<len(additions):
            if original[i][0]<additions[j][0]:
                rows.append(original[i][1]);i+=1
            else:
                rows.append(additions[j][1]);j+=1
        rows.extend(row for _,row in original[i:])
        rows.extend(row for _,row in additions[j:])
    else:
        rows.extend(row for _,row in added)
    payload=b'\xc0'+len(rows).to_bytes(3,order)+b'\xc1'*len(rows)
    payload+=bytes((-len(payload))%4)+b''.join(word.pack(v) for v in rows)
    put(field(data,group),append(payload))
    if save_file<0:
        return bytes(out)
    for name in ('SaveDataSize','SaveDataOffsetPos'):
        arr=get_node(meta,name,0xc0);n,first=array(arr)
        if not n or out[arr+4] not in (0xd1,0xd3):raise ValueError(tr('Invalid save size: ')+name)
        clone=append(out[arr:first+4*n]);put(clone+first-arr,read(first)+8*len(marker_keys));put(field(meta,name),clone)
    for name in ('AllDataSaveSize','AllDataSaveOffset'):
        at=field(meta,name)
        if out[at-1] not in (0xd1,0xd3):raise ValueError(tr('Invalid save size: ')+name)
        put(at,read(at)+8*len(marker_keys))
    return bytes(out)
