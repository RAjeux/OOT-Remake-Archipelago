"""Native item-get text naming the dungeon of each Archipelago dungeon item.

The display is independent of inventory credit and has no key counter: the
native window may open before the queued credit has settled. Quiet recovery
does not call this module's window helper.
"""
from pathlib import Path
from collections.abc import Mapping
import re

from .catalog import ITEM_DATA

MESSAGE_FILE = "EventFlowMsg/Dm_SY_Get.msbt"
MESSAGE_GROUP = "EventFlowMsg/Dm_SY_Get"
NAMES_FILE = "ActorMsg/PouchContent.msbt"
PLACES_FILE = "LocationMsg/Location.msbt"
PREFIX = "OOTRR_APDungeon_"
REST = "System/Resource/ResourceSizeTable.Product.111.Nin_Ounce_NVN2.rsizetable.zs"
KINDS = {"SmallKey": "SmallKey", "HideoutSmallKey": "SmallKey",
         "BossKey": "BossKey", "GanonBossKey": "BossKey",
         "Map": "Map", "Compass": "Compass"}
FALLBACK_NAMES = {"SmallKey": "Small Key", "BossKey": "Boss Key",
                  "Map": "Map", "Compass": "Compass"}


def message_id(metadata):
    """Return a dungeon-specific native message, or None for ordinary items."""
    if metadata.get("mode") != "generic" or not metadata.get("dungeon"):
        return None
    tag = KINDS.get(metadata.get("kind"))
    if tag is None:
        return None
    from .receipt_events import DUNGEONS
    dungeon = DUNGEONS.get(metadata["dungeon"])
    if dungeon is None:
        raise ValueError("Unknown Archipelago dungeon-item destination.")
    return MESSAGE_GROUP + ":" + PREFIX + tag + "_" + dungeon


def append_window(editor, metadata, stem, *, flow="", entry="DisplayGetByActorName", params=None):
    """Replace only the item window; retain native continuations and effects."""
    identity = message_id(metadata)
    if identity is None:
        return editor.subflow(stem + "_Window", flow, entry, params)
    if not any(str(actor.identifier) == "SystemTextNPC" for actor in editor.chart.actors):
        from evfl.actor import Actor
        from evfl.common import ActorIdentifier
        from evfl.container import Container
        from oot_rando.patching.event_patch import GAMEDATA_ACTOR_PARAMS
        # Native v1.1.1 GetPouchContent's SystemTextNPC has precisely this same
        # parameter block. A named actor without it is unsafe in the game.
        owner = Actor()
        owner.identifier = ActorIdentifier("SystemTextNPC")
        owner.concurrent_clips = 1
        owner.params = Container()
        owner.params.data = dict(GAMEDATA_ACTOR_PARAMS)
        editor.chart.actors.append(owner)
    # Exact native dungeon_credit::talk ABI, including its item-get style.
    # No new actor model, camera movement, inventory grant or save occurs here.
    parameters = {
        "IsWaitEnd": True, "IsCloseDialog": True, "EndDialogOption": 0,
        "ASName": "", "IsAnimeDriven": False, "IsPlayASAllSlot": False,
        "ChoiceNumber": 0, "ChoiceLabel1": 0, "ChoiceLabel2": 0,
        "ChoiceLabel3": 0, "ChoiceLabel4": 0, "ChoiceDefaultNo": 0,
        "ChoiceCancelNo": 0, "IsNotBecomeSpeaker": False,
        "ChangeMstxtForActor": False, "IsAnonymous": False,
        "NotPlayLipSyncAnim": False, "IsNotOpenIfSkipedMostRecent": False,
        "IsOverrideStyle": True, "OverrideStyle": 4, "MessageId": identity,
        "MaintainPerformanceState": 0,
    }
    return editor.action(stem + "_Window", "SystemTextNPC", "EventTalk", parameters)


def _definitions():
    """All supported AP dungeon items, independently of a native donor pool."""
    from .receipt_events import DUNGEONS
    definitions = {}
    for name, metadata in sorted(ITEM_DATA.items()):
        identity = message_id(metadata)
        if identity is None:
            continue
        dungeon = DUNGEONS[metadata["dungeon"]]
        place = "GanonCastle" if dungeon in {"InsideGanonCastle", "FinalBattleField"} else dungeon
        tag = KINDS[metadata["kind"]]
        definitions[identity.split(":", 1)[1]] = (
            metadata["actor"] + "_Name", place, FALLBACK_NAMES[tag], metadata["dungeon"])
    return definitions


def _name(messages, label, fallback):
    value = messages.get(label)
    if value is None or value == b"\0":
        return fallback.encode("utf-8")
    if not value.endswith(b"\0"):
        raise ValueError("The native dungeon-item name is not NUL-terminated.")
    # Remove exactly the terminal byte. Grammar/control-code arguments can
    # themselves end in NUL bytes and must remain intact.
    return value[:-1]


def _dungeon_aliases(aliases):
    """Accept named AP aliases only, never rewrite a canonical native actor."""
    if aliases is None:
        return {}
    if not isinstance(aliases, Mapping):
        raise ValueError("Invalid Archipelago dungeon-item aliases.")
    selected = {}
    for actor, metadata in aliases.items():
        if not isinstance(metadata, Mapping):
            raise ValueError("Invalid Archipelago dungeon-item alias metadata.")
        if message_id(metadata) is None:
            continue
        if (not isinstance(actor, str) or not re.fullmatch(r"Item_AP_[A-Za-z0-9_]+", actor)
                or actor == metadata.get("actor")):
            raise ValueError("Invalid Archipelago dungeon-item alias actor.")
        selected[actor] = metadata
    return selected


def _put_raw(messages, label, content):
    if messages.get(label) == content:
        return False
    # Native and AP labels can share an existing text index. Append a private
    # entry rather than changing any other label that points to the same text.
    messages.labels[label] = len(messages.texts)
    messages.texts.append(content)
    return True


def patch_message_archive(raw, aliases=None):
    """Keep native names and binary grammar tags, without changing other text."""
    from oot_rando.formats.byml_codec import build_sarc
    from oot_rando.formats.inspect_resources import sarc
    from oot_rando.formats.msbt import dump, load

    aliases = _dungeon_aliases(aliases)
    members = sarc(raw)
    if not {MESSAGE_FILE, NAMES_FILE, PLACES_FILE} <= members.keys():
        raise ValueError("The game text archive has no native dungeon-item names.")
    messages = load(members[MESSAGE_FILE])
    names, places = load(members[NAMES_FILE]), load(members[PLACES_FILE])
    changed = False
    for label, (item, dungeon, fallback_item, fallback_dungeon) in _definitions().items():
        content = (_name(names, item, fallback_item) + b"\n"
                   + _name(places, dungeon, fallback_dungeon) + b"\0")
        changed = _put_raw(messages, label, content) or changed
    aliases_changed = False
    from .receipt_events import DUNGEONS
    for actor, metadata in sorted(aliases.items()):
        # These aliases were already created by the AP item/shop preparation.
        # A missing label means the native preparation contract changed; do
        # not fabricate an incomplete actor or modify a donor's native text.
        labels = (actor + "_Name", actor + "_GetMessage")
        if any(label not in names.labels for label in labels):
            raise ValueError("Missing Archipelago dungeon-item alias message: " + actor)
        dungeon = DUNGEONS[metadata["dungeon"]]
        place = "GanonCastle" if dungeon in {"InsideGanonCastle", "FinalBattleField"} else dungeon
        item = _name(names, metadata["actor"] + "_Name", FALLBACK_NAMES[KINDS[metadata["kind"]]])
        destination = _name(places, place, metadata["dungeon"])
        title = item + b" (" + destination + b")\0"
        message = item + b"\n" + destination + b"\0"
        aliases_changed = _put_raw(names, labels[0], title) or aliases_changed
        aliases_changed = _put_raw(names, labels[1], message) or aliases_changed
    if not changed and not aliases_changed:
        return raw
    if changed:
        members[MESSAGE_FILE] = dump(messages)
    if aliases_changed:
        members[NAMES_FILE] = dump(names)
    return build_sarc(members)


def prepare_messages(romfs, mod, aliases=None):
    """Write localized windows into a staged mod, reserving Mals allocations."""
    from oot_rando.game.resource_allocations import grow_resources
    from .mod_codec import Codec

    aliases = _dungeon_aliases(aliases)
    romfs, mod = Path(romfs), Path(mod)
    if (mod.name != "romfs" or mod.parent.name != "Archipelago"
            or mod.resolve() == romfs.resolve()):
        raise ValueError("Invalid Archipelago dungeon-message staging folder.")

    def source(path):
        staged = mod / path
        return (staged if staged.is_file() else romfs / path).read_bytes()

    archives = sorted({"Mals/" + path.name for home in (romfs, mod)
                       for path in (home / "Mals").glob("*.Product.110.sarc.zs") if path.is_file()})
    if not archives:
        raise ValueError("Game text archives were not found in Mals.")
    codec = Codec(source("Pack/ZsDic.pack.zs"))
    changed, growths = {}, {}
    for path in archives:
        frame = source(path)
        before = codec.decode(frame)
        after = patch_message_archive(before, aliases=aliases)
        if after != before:
            changed[path] = codec.encode(after, frame)
            growths[path] = max(0, len(after) - len(before))
    if not changed:
        return {"messages": len(_definitions()), "archives": 0, "allocations": []}
    frame = source(REST)
    table, allocations = grow_resources(codec.decode(frame), growths)
    changed[REST] = codec.encode(table, frame)
    for path, content in changed.items():
        target = mod / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return {"messages": len(_definitions()), "archives": len(changed) - 1,
            "allocations": allocations}
