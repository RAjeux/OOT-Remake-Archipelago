"""Append-only AP identities for the independently shuffled adult trades."""

TALON_AWAKE = "KakarikoVillage_CrowedCucco_Npc_Hylia_Talon_Adult"
TRADE_ROWS = (
    ("Kak Anju as Adult", "Npc_Hylia_049_Adult", None),
    ("Kak Anju Trade Pocket Cucco", "Npc_Hylia_049_Adult", "Item_PocketCucco"),
    ("LW Trade Cojiro", "Npc_Hylia_017_Adult", "Item_CojiroCucco"),
    ("Kak Granny Trade Odd Mushroom", "Npc_Hylia_053_Adult", "Item_OddMushroom"),
    ("LW Trade Odd Potion", "Npc_Kokiri_Fado_Adult", "Item_OddPowder"),
    ("GV Trade Poachers Saw", "Npc_Hylia_012_Adult", "Item_PoacherSaw"),
    ("DMT Trade Broken Sword", "Npc_Goron_Biggoron_Adult", "Item_BrokenSword"),
    ("ZD Trade Prescription", "Npc_Zora_KingZora_adult", "Item_Prescription"),
    ("LH Trade Eyeball Frog", "Npc_Hylia_045_Adult", "Item_EyeballFrog"),
    ("DMT Trade Eyedrops", "Npc_Goron_Biggoron_Adult", "Item_EyeDrop"),
    ("DMT Biggoron", "Npc_Goron_Biggoron_Adult", "Item_ClaimCheck"),
)

# IDs after the original 128 chests, eight shops and 100 reserved Skulltulas.
TRADE_FIRST_ID = 0x6F72EC
TRADE_FLAGS = (871549555, 3753071489, 1958497851, 598682940, 2561926672,
               2917022404, 3077600440, 3553804453, 2509098768, 1573822383,
               3358687849)
TRADE_CHECKS = {
    name: dict(id=TRADE_FIRST_ID + index, flow=flow, required_actor=required,
               flag_name="Archipelago.Trade." + str(TRADE_FIRST_ID + index),
               flag=TRADE_FLAGS[index], wake_talon=index == 1)
    for index, (name, flow, required) in enumerate(TRADE_ROWS)
}
TRADE_ITEMS = frozenset({"Pocket Cucco", "Cojiro", "Odd Mushroom", "Odd Potion",
                         "Poachers Saw", "Broken Sword", "Prescription",
                         "Eyeball Frog", "Eyedrops", "Claim Check"})


def event_name(location_id):
    return "OOTRR_APTradeReward_" + str(location_id)
