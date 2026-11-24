"""Opt-in AP pedestal reward; native time travel remains a separate event.

The pinned builder has no Master Sword option. Its seed is kept byte-for-byte
and the AP world exports one extra reward at the native proof's pedestal sphere.
Every later AP sphere consequently requires the sword, even though the native
OoTR logic assumes that adult Link has it. This intentionally conservative rule
also keeps the final boss behind the real sword rather than the time-travel flag.
"""
from .i18n import tr

SETTING = "shuffle_master_sword"
LOCATION = "ToT Master Sword"
ITEM = "Master Sword"
ACTOR = "Weapon_Sword_Master"
PROOF_LOCATION = "ToT Reward from Rauru"
_NO_OBSERVATION = object()
LOCATION_ID = 0x6F9038  # appended after the original 303 location identities
FLAG_NAME = "Archipelago.MasterSword.Pedestal"


def token_material(room, player, checksum, enabled=False):
    """Salt only this extension, preserving every released room's identity."""
    original = f"{room}/{player}/{checksum}"
    return original + "/master-sword-v1" if enabled else original


def proof_wave(waves, observed=_NO_OBSERVATION):
    """Use the engine's non-mutating pedestal observer, independent of shuffles.

    Older engine responses only exposed shuffled locations. Their Rauru sphere
    is usable when present, but never guess a wave when neither proof exists.
    """
    if observed is not _NO_OBSERVATION:
        if type(observed) is not int or not 0 <= observed < len(waves):
            raise ValueError(tr("Master Sword shuffle requires a proved pedestal access sphere."))
        return observed
    found = [index for index, names in enumerate(waves) if PROOF_LOCATION in names]
    if len(found) != 1:
        raise ValueError(tr("Master Sword shuffle requires a proved pedestal access sphere."))
    return found[0]


def manifest_reward(data):
    """Resolve this extension explicitly; absent metadata keeps old rooms inert."""
    enabled = data.get(SETTING, False)
    if type(enabled) is not bool:
        raise ValueError(tr("Invalid Master Sword shuffle metadata."))
    if enabled:
        if data.get("reward_mode") != "all_locations" or data.get("local_items") is not True:
            raise ValueError(tr("Master Sword shuffle requires physical all_locations rewards."))
        if LOCATION not in data.get("checks", ()):
            raise ValueError(tr("The Master Sword pedestal check is missing."))
        seed_settings = data.get("seed_file", {}).get("settings", {})
        if isinstance(seed_settings, dict) and seed_settings.get("starting_age", "child") != "child":
            raise ValueError(tr("Master Sword shuffle requires starting as child Link."))
        return {LOCATION: ITEM}
    if LOCATION in data.get("checks", ()):
        raise ValueError(tr("The Master Sword pedestal requires shuffle_master_sword."))
    return {}
