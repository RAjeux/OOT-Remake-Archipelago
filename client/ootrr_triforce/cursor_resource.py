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
