"""Generate legacy pouch names and the full receipt-event whitelist from frozen AP IDs."""
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root/"client"))
from ootrr_triforce.catalog import FILLER, ITEM_IDS, ITEM_DATA
from ootrr_triforce.live import POUCH

if not POUCH.keys() <= ITEM_IDS.keys() or ITEM_IDS.keys() != ITEM_DATA.keys():
    raise ValueError("Les recettes et identifiants Archipelago ne couvrent pas les mêmes objets.")
rows = [f"#define AP_RUPEE_ID {ITEM_IDS[FILLER]}", "static const char *ap_item_name16(int item) {", "    switch (item) {"]
rows.extend(f'    case {ITEM_IDS[name]}: return "{actor}";' for name, actor in POUCH.items())
rows.extend(["    default: return NULL;", "    }", "}", ""])
rows.extend(["/* Full conversion: the registered receipt event applies the vanilla effect", "   and commits the saved cursor. Unknown IDs are never silently acknowledged. */", "static const char *ap_eventname16(int item) {", "    switch (item) {"])
rows.extend(f'    case {identifier}: return "OOTRR_APReceive_{identifier}";' for _, identifier in sorted(ITEM_IDS.items(), key=lambda row: row[1]))
rows.extend(["    default: return NULL;", "    }", "}", ""])
(root/"native/ootrr_ap_items.inc").write_bytes("\n".join(rows).encode("ascii"))
