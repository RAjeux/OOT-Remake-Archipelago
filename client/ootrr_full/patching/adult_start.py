"""Adult start through the native first-pedestal and Rauru prologue.

The new game still loads Kokiri Forest (the engine's start banc) and its opening flow
runs as usual: seed marker, starting items and start values are written by the
``Opening_LoadingKokiriForest`` entry. In ``Opening_Introduction``, right after its own
quest request (``Event8``), Link leaves for the child Temple of Time instead of
playing the forest introduction. Its original first-sword event then performs
the whole native age transition, both real rewards and quest initialization:

* first draw, the original pedestal reward (shuffled or native);
* SageRoom_MeetGanondorf, which sets Sequence_IsChildhood=false;
* SageRoom_MeetRauru, including the original Light Medallion reward source;
* Market_Adult_AllSage_Start, initializing the native sage quests and returning
  gameplay control in the adult Temple of Time.

The Door of Time is open from the start (``open_door_of_time`` is forced on by
:func:`ootrr_full.logic.rando_options.validate`), so time travel works both ways at the
pedestal. An unshuffled adult start holds the native Master Sword. When its
shuffle is enabled, the adapted pedestal accepts time travel without owning it,
so the sword stays in Archipelago's pool instead of becoming free equipment.
Other starting items are the player's choice (``start_inventory_from_pool``).
Gameplay confirmation of adult start is still required.
"""
OPTION = 'starting_age'
VALUE = 'adult'
ANCHOR = 'Event8'                    # Opening_Introduction: after its quest request
ERA_FLAG = 'Sequence_IsChildhood'
ERA_EVENT = 'RandoAdultStart_Era'
WARP_EVENT = 'RandoAdultStart_Warp'
START_ACTORS = ()  # the original pedestal hands over its own native or AP reward
# Native EventReserveBancChange contract, pointing at the unchanged first-draw
# event and a native StartPos with the original pedestal's exact world transform.
SPAWN_MAP = 'Banc/Market/Market_Child_Static.bcett.byml.zs'
SPAWN_NAME = 'RandoAdultStart_Pedestal'
WARP_PARAMS = {'IsWaitEnd': True, 'IsStartOnEvent': False, 'NextStartPos': '', 'NextBanc': 'Market_Child',
               'BootEventName': 'Market_Child_DoorOfTime_Draw', 'FadePattern': 2, 'EventStarterName': SPAWN_NAME,
               'IsItemWarp': False, 'NextPosition': [137.20840454101562, 106.12010192871094, -34.0],
               'NextStartRot': [0.0, 90.0, 0.0]}


def enabled(options):
    return (options or {}).get(OPTION) == VALUE


def starting_actors(options):
    """The prologue hands over its real reward; no sword is added separately."""
    return ()


def event_params():
    """{event name: parameters} added to the opening flow."""
    return {ERA_EVENT: {'GameDataName': ERA_FLAG, 'Value': True, 'Index': -1},
            WARP_EVENT: dict(WARP_PARAMS)}


def add_start_marker(raw):
    """A native StartPos supplies the original sword event's StarterPos origin.

    Keep every source actor and its native position unchanged. The new invisible
    anchor borrows the actual pedestal's transform and the native StartPos shape.
    """
    import copy
    import hashlib
    from ootrr_full.formats import byml_codec
    document = byml_codec.load(raw)
    actors = document['root']['Actors']
    swords = [row for row in actors if row.get('Gyaml') == 'Obj_TimeTemple_MasterSword_A_01']
    template = next((row for row in actors if row.get('Gyaml') == 'StartPos'), None)
    if len(swords) != 1 or template is None or any(row.get('Name') == SPAWN_NAME for row in actors):
        raise ValueError('The native adult-start pedestal anchor layout changed.')
    key = int.from_bytes(hashlib.sha256(SPAWN_NAME.encode()).digest()[:8], 'big')
    if any(int(row['Hash']) == key for row in actors):
        raise ValueError('The adult-start pedestal anchor identity collides with a game actor.')
    marker = copy.deepcopy(template)
    marker.update(Name=SPAWN_NAME, Hash=byml_codec.U64(key),
                  Phive={'Placement': {'ID': byml_codec.U64(key)}})
    for field in ('Translate', 'Rotate', 'SRTHash'):
        marker[field] = copy.deepcopy(swords[0][field])
    actors.append(marker)
    return byml_codec.dump(document)


def patch_opening(raw, after=ANCHOR):
    """Opening flow bytes where ``after`` leads to the era flag, then the Temple of Time.

    The forest introduction that followed ``after`` no longer plays. Returns (bytes, report)."""
    from evfl.util import make_index
    from ootrr_full.patching.story_fixes import _Chart
    flow = _Chart(raw)
    anchor = flow.event(after, 'ActionEvent')
    warp = flow.action(WARP_EVENT, 'GameSystemActor', 'EventReserveBancChange', WARP_PARAMS, None)
    era = flow.set_bool(ERA_EVENT, ERA_FLAG, True, warp)
    anchor.data.nxt = make_index(era)
    result, events = flow.write()
    chain = events[after].data.nxt.v
    if (chain is None or chain.name != ERA_EVENT or chain.data.nxt.v is None
            or chain.data.nxt.v.name != WARP_EVENT or chain.data.nxt.v.data.nxt.v is not None):
        raise ValueError('Adult start wrongly chained.')
    return result, {'after': after, 'events': [ERA_EVENT, WARP_EVENT], 'banc': WARP_PARAMS['NextBanc']}
