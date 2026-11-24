"""Generation-local actor prototypes preserve bytes and never share mutations."""
import copy
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from ootrr_full.formats import byml_codec
from ootrr_full.game import item_forms as forms
from ootrr_full.patching.repeatable_adapter import _AliasTemplates, _alias_rows, _AINBTemplates


def tables():
    names = {forms.WORLD_TEMPLATE, forms.SHOP_TEMPLATE, forms.DROP_TEMPLATE,
             "Item_Hammer", "Item_Hookshot", "Item_BombBag_Small"}
    return {table: [{"__RowId": name, "ActorName": name, "ModelProjectName": "Model_" + name,
                     "InstanceHeapSize": 4096, "Preserved": {"nested": [1, 2, 3]}}
                    for name in sorted(names)] for table in forms.RSDB_TABLES}


def encoded(value):
    return {name: byml_codec.dump({"endian": "<", "version": 7, "root": rows})
            for name, rows in value.items()}


class AliasCacheTests(unittest.TestCase):
    def test_prototypes_match_existing_implementation_with_and_without_standard_rows(self):
        for existing in (False, True):
            with self.subTest(existing=existing):
                before = tables()
                standards = [forms.DROP_PREFIX + "Item_Hammer", forms.SHOP_PREFIX + "Item_Hookshot"]
                if existing:
                    forms.add_rsdb_rows(before, standards)
                legacy, optimized = copy.deepcopy(before), copy.deepcopy(before)
                cache = _AliasTemplates(optimized)
                for index in range(12):
                    standard, actor = standards[index % 2], "UniqueCheck_" + str(index)
                    _alias_rows(legacy, standard, actor)
                    cache.append(standard, actor)
                cache.finish()
                self.assertEqual(encoded(legacy), encoded(optimized))
                self.assertEqual(tables(), {name: [row for row in rows if row["__RowId"] in {
                    forms.WORLD_TEMPLATE, forms.SHOP_TEMPLATE, forms.DROP_TEMPLATE,
                    "Item_Hammer", "Item_Hookshot", "Item_BombBag_Small"}] for name, rows in before.items()})

    def test_alias_changes_cannot_mutate_another_alias_or_canonical_template(self):
        target = tables()
        original = copy.deepcopy(target)
        cache = _AliasTemplates(target)
        standard = forms.DROP_PREFIX + "Item_Hammer"
        cache.append(standard, "First")
        first = next(row for row in target["ActorInfo"] if row["__RowId"] == "First")
        first["Preserved"]["nested"].append(99)
        cache.append(standard, "Second")
        second = next(row for row in target["ActorInfo"] if row["__RowId"] == "Second")
        self.assertEqual(second["Preserved"]["nested"], [1, 2, 3])
        self.assertEqual(original["ActorInfo"], [row for row in target["ActorInfo"] if row["__RowId"] not in {"First", "Second"}])

    def test_cache_is_bounded_and_discarded_between_generations(self):
        first = _AliasTemplates(tables())
        with patch.object(_AliasTemplates, "LIMIT", 2):
            for index, canonical in enumerate(("Item_Hammer", "Item_Hookshot", "Item_BombBag_Small")):
                first.append(forms.DROP_PREFIX + canonical, "Actor" + str(index))
            self.assertEqual(len(first.cache), 2)
        second = _AliasTemplates(tables())
        self.assertFalse(second.cache)
        with self.assertRaisesRegex(ValueError, "already exists"):
            first.append(forms.DROP_PREFIX + "Item_Hammer", "Actor0")


@unittest.skipUnless(os.environ.get("OOT_NUP"), "OOT_NUP not set")
class NativeAINBCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from ootrr_full.formats.inspect_nup import Nup
        from ootrr_full.game.world_maps import effective_members
        from ootrr_full.formats.inspect_resources import decompress, dictionaries, sarc
        from ootrr_full.patching import repeatable_adapter as repeatable
        cls.repeatable = repeatable
        nup = Nup(os.environ["OOT_NUP"])
        try:
            members = effective_members(nup)
            cls.files = sarc(decompress(nup.read(members[repeatable.EVENT_PACK]), dictionaries(nup)))
        finally:
            nup.stream.close()

    def test_native_template_cache_cannot_leak_another_checks_flag(self):
        r = self.repeatable
        raw, event, restore = self.files[r.DROP_AI_MEMBER], self.files[r.EVENT_MEMBER], self.files[r.HANDOVER_AI_MEMBER]
        cache = _AINBTemplates()
        original = copy.deepcopy(cache.get(raw, faithful=True)["document"])
        for index in range(2):
            flag = "Rando.Perf.Check" + str(index)
            args = (raw, flag, "RandoCached" + str(index), event)
            expected = r.instrument_drop_ai(*args, mark_on_spawn="TBox_Rupee_Green", restore_raw=restore)
            actual = r.instrument_drop_ai(*args, mark_on_spawn="TBox_Rupee_Green", restore_raw=restore,
                                          source_cache=cache)
            self.assertEqual(actual, expected)
            self.assertIn(flag.encode(), actual)
            self.assertNotIn(("Rando.Perf.Check" + str(1 - index)).encode(), actual)
            self.assertEqual(cache.get(raw)["document"], original)

    def test_native_input_cache_is_bounded_and_generation_local(self):
        r = self.repeatable
        cache = _AINBTemplates()
        source = [self.files[name] for name in (r.DROP_AI_MEMBER, r.EVENT_MEMBER, r.HANDOVER_AI_MEMBER)]
        with patch.object(_AINBTemplates, "LIMIT", 2):
            for raw in source:
                cache.get(raw)
            self.assertEqual(len(cache.cache), 2)
            self.assertNotIn(source[0], cache.cache)
        self.assertFalse(_AINBTemplates().cache)


if __name__ == "__main__":
    unittest.main()
