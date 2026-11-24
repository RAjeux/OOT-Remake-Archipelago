"""Restore native quest state accompanying the additional full-network checks."""
from .ap_skulls import _after_writes

FROG_FLAGS = tuple('MiniGame_FrogTenors_' + suffix for suffix in
                   ('ZeldaLullaby', 'EponaSong', 'SariaSong', 'SunSong', 'TimeSong', 'StormSong'))
FROG_ENTRY = "OOTRR_APFrogReconcile"
BEAN_ENTRY = "OOTRR_APBeanReconcile"
BEAN_FLAGS = tuple("RandoFullBeanPurchase." + str(index + 1) for index in range(10))
FROG_NAMES = frozenset(("ZR Frogs Zeldas Lullaby", "ZR Frogs Eponas Song", "ZR Frogs Sarias Song",
                        "ZR Frogs Suns Song", "ZR Frogs Song of Time", "ZR Frogs Bug Game",
                        "ZR Frogs Ocarina Game", "ZR Frogs in the Rain"))


def additional_flags(name):
    """Native completion effects of the existing Song of Storms handover."""
    return [FROG_FLAGS[-1]] if name in {"ZR Frogs Ocarina Game", "ZR Frogs in the Rain"} else []


def append_progressive_reconcile(editor, record, after):
    """Consume this source's stale token only after its missing reward is restored.

    Never call this on the already-checked path: a still-pending physical token
    there belongs to the normal converter, which must remain able to run.
    """
    token = record.get("progressive_token")
    if not token:
        return after
    from evfl.util import make_index
    from ootrr_full.patching.progressive import applied_flag, is_token
    if (not isinstance(token, dict) or not isinstance(token.get("actor"), str) or not is_token(token["actor"])
            or token.get("applied") != applied_flag(token["actor"])):
        raise ValueError("Invalid full-network source token recovery metadata.")
    stem = "OOTRR_APProgressiveRestore_" + str(record["id"])
    committed = _after_writes(editor, stem + "_Committed", after)
    take = editor.action(stem + "_Take", "PouchSystemActor", "EventTriggerAddOrRemovePouchContent",
                         {"Actor": token["actor"], "Num": -1, "IsEquipDIrect": False,
                          "IsSetMessageTargetActorName": False, "IsGetEvent": False})
    take.data.nxt = make_index(committed)
    held = editor.switch(stem + "_Held", "PouchSystemActor", "EventQueryIsExistInPouch",
                         {"Actor": token["actor"], "Num": 1}, take, committed)
    applied = editor.action(stem + "_Applied", "GameDataActor", "EventTriggerSetGameDataBool",
                            {"GameDataName": token["applied"], "Index": -1, "Value": True})
    applied.data.nxt = make_index(held)
    return applied


def _frog_entry(editor):
    from evfl.entry_point import EntryPoint
    from evfl.util import make_index
    if any(point.name == FROG_ENTRY for point in editor.chart.entry_points):
        return

    def action(suffix, command, params, after=None):
        event = editor.action(FROG_ENTRY + suffix, "GameDataActor", command, params)
        if after is not None:
            event.data.nxt = make_index(after)
        return event

    committed = _after_writes(editor, FROG_ENTRY + "_Committed", None)
    complete = action("_AllSongs", "EventTriggerSetGameDataBool",
                      {"GameDataName": "MiniGame_FrogTenors_SongClear", "Index": -1, "Value": True}, committed)
    incomplete = action("_NotAllSongs", "EventTriggerSetGameDataBool",
                        {"GameDataName": "MiniGame_FrogTenors_SongClear", "Index": -1, "Value": False}, committed)
    tail = complete
    for index, flag in reversed(list(enumerate(FROG_FLAGS))):
        tail = editor.switch(FROG_ENTRY + "_All" + str(index), "GameDataActor", "EventQueryIsGameDataBool",
                             {"GameDataName": flag, "Index": -1}, tail, incomplete)
    for index, flag in reversed(list(enumerate(FROG_FLAGS))):
        add = action("_Add" + str(index), "EventTriggerAddOrSubGameDataInt",
                     {"GameDataName": "MiniGame_FrogTenors_GetCount", "Value": 1, "Index": -1}, tail)
        tail = editor.switch(FROG_ENTRY + "_Count" + str(index), "GameDataActor", "EventQueryIsGameDataBool",
                             {"GameDataName": flag, "Index": -1}, add, tail)
    reset = action("_ResetCount", "EventTriggerSetGameDataInt",
                   {"GameDataName": "MiniGame_FrogTenors_GetCount", "Value": 0, "Index": -1}, tail)
    point = EntryPoint(FROG_ENTRY)
    point.main_event = make_index(reset)
    editor.chart.entry_points.append(point)


def append_reconcile(editor, record, after):
    """Return a native chain to run after restored flags, before the commit save."""
    from evfl.util import make_index
    stem = "OOTRR_APExtraRestore_" + str(record["id"])
    if record["name"].startswith("ZR Magic Bean Salesman "):
        from evfl.entry_point import EntryPoint
        if not any(point.name == BEAN_ENTRY for point in editor.chart.entry_points):
            tail = _after_writes(editor, BEAN_ENTRY + "_Committed", None)
            for index, flag in reversed(list(enumerate(BEAN_FLAGS))):
                add = editor.action(BEAN_ENTRY + "_Add" + str(index), "GameDataActor", "EventTriggerAddOrSubGameDataInt",
                                    {"GameDataName": "Get_MagicBeans", "Value": 1, "Index": 0})
                if tail is not None:
                    add.data.nxt = make_index(tail)
                tail = editor.switch(BEAN_ENTRY + "_Count" + str(index), "GameDataActor", "EventQueryIsGameDataBool",
                                     {"GameDataName": flag, "Index": -1}, add, tail)
            reset = editor.action(BEAN_ENTRY + "_Reset", "GameDataActor", "EventTriggerSetGameDataInt",
                                  {"GameDataName": "Get_MagicBeans", "Value": 0, "Index": 0})
            reset.data.nxt = make_index(tail)
            point = EntryPoint(BEAN_ENTRY)
            point.main_event = make_index(reset)
            editor.chart.entry_points.append(point)
        restore = editor.subflow(stem + "_BeanStock", "", BEAN_ENTRY, None)
        restore.data.nxt = make_index(after)
        return _after_writes(editor, stem + "_BeanFlagsReady", restore)
    if record["name"] in FROG_NAMES:
        _frog_entry(editor)
        restore = editor.subflow(stem + "_Frogs", "", FROG_ENTRY, None)
        restore.data.nxt = make_index(after)
        return _after_writes(editor, stem + "_FlagsReady", restore)
    return after
