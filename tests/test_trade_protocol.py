"""The Go replay admission table must match the frozen Python AP identities."""
import json
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from ootrr_triforce.catalog import ITEM_DATA, ITEM_IDS, TRADE_CHECKS
from ootrr_triforce.trade_catalog import TRADE_ITEMS


class TradeProtocolTests(unittest.TestCase):
    def test_native_replay_bindings_match_items_locations_and_saved_flags(self):
        source = (ROOT / "native/ootrr_ap_trade.go").read_text(encoding="utf-8")
        rows = re.findall(r'\{(\d+), ("[^"]+"), (\d+), ("[^"]+"), (\d+)\}', source)
        actual = {(int(item), json.loads(name), int(check), json.loads(location), int(flag))
                  for item, name, check, location, flag in rows}
        by_actor = {row["required_actor"]: (name, row) for name, row in TRADE_CHECKS.items() if row["required_actor"]}
        expected = set()
        for name in TRADE_ITEMS:
            location, row = by_actor[ITEM_DATA[name]["actor"]]
            expected.add((ITEM_IDS[name], name, row["id"], location, row["flag"]))
        self.assertEqual(len(rows), 10)
        self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
