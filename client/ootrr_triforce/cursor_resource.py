"""Append one saved Int to the v1.1.1 GameData BYML without reserializing other types."""
import struct


def append_saved_index(raw, key, baseline):
    return _append_saved_value(raw,key,baseline,"Int",0xd1)


def append_saved_bool(raw, key, value=False):
    return _append_saved_value(raw,key,int(bool(value)),"Bool",0xd0)


def _append_saved_value(raw, key, baseline, group, default_type):
    if raw[:2] not in (b'YB', b'BY') or not 0<=baseline<2**31:
        raise ValueError("GameData ou index de réception invalide.")
    out=bytearray(raw)
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
    if not table or out[table]!=0xc2:raise ValueError("Table des noms GameData absente.")
    keys={}
    for i in range(small(table+1)):
        pos=table+read(table+4+4*i)
        keys[raw[pos:raw.index(b'\0',pos)].decode()]=i
    def field(node,name,required=True):
        if out[node]!=0xc1:raise ValueError("Dictionnaire GameData attendu.")
        key_id=keys.get(name)
        for i in range(small(node+1)):
            at=node+4+8*i
            if small(at)==key_id:return at+4
        if required:raise ValueError("Champ GameData absent : "+name)
        return None
    def get_node(node,name,kind):
        at=field(node,name)
        if out[at-1]!=kind:raise ValueError("Type GameData inattendu : "+name)
        child=read(at)
        if out[child]!=kind:raise ValueError("Conteneur GameData invalide : "+name)
        return child
    def array(node):
        n=small(node+1);first=(node+4+n+3)&~3
        if first+4*n>len(out):raise ValueError("Table GameData tronquée.")
        return n,first
    root=read(12)
    data=get_node(root,'Data',0xc1)
    meta=get_node(root,'MetaData',0xc1)
    ints=get_node(data,group,0xc0)
    count,first=array(ints)
    ids=[];template=None
    for i in range(count):
        if out[ints+4+i]!=0xc1:raise ValueError("Type d’entier sauvegardé inconnu.")
        row=read(first+4*i);h=read(field(row,'Hash'));ids.append(h)
        if h==key:raise ValueError("Le marqueur Archipelago existe déjà.")
        if template is None:
            default=field(row,'DefaultValue',False)
            reset=field(row,'ResetTypeValue',False)
            save=field(row,'SaveFileIndex',False)
            if default and save and reset and out[default-1]==default_type and read(default)==0 and read(save)==0 and read(reset)==8:template=row
    if template is None:raise ValueError("Schéma des entiers sauvegardés du jeu inconnu.")
    new_row=append(out[template:template+4+8*small(template+1)])
    put(field(new_row,'Hash'),key);put(field(new_row,'DefaultValue'),baseline)
    rows=[read(first+4*i) for i in range(count)]
    # Preserve the existing order; maintain it if it was hash-sorted.
    at=next((i for i,v in enumerate(ids) if v>key),count) if ids==sorted(ids) else count
    rows.insert(at,new_row)
    payload=b'\xc0'+len(rows).to_bytes(3,order)+b'\xc1'*len(rows)
    payload+=bytes((-len(payload))%4)+b''.join(word.pack(v) for v in rows)
    put(field(data,group),append(payload))
    for name in ('SaveDataSize','SaveDataOffsetPos'):
        arr=get_node(meta,name,0xc0);n,first=array(arr)
        if not n or out[arr+4] not in (0xd1,0xd3):raise ValueError("Taille de sauvegarde invalide : "+name)
        clone=append(out[arr:first+4*n]);put(clone+first-arr,read(first)+8);put(field(meta,name),clone)
    for name in ('AllDataSaveSize','AllDataSaveOffset'):
        at=field(meta,name)
        if out[at-1] not in (0xd1,0xd3):raise ValueError("Taille de sauvegarde invalide : "+name)
        put(at,read(at)+8)
    return bytes(out)
