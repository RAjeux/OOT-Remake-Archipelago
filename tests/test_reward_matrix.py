"""Execute every recovery recipe over saved flags and modeled pouch commands.

This matrix checks AP event effects, not native rendering, stock clamping or
the implementation of the game's pouch commands. Generic legacy keys record
their native context-dependent command without pretending to select a dungeon.
"""
from collections import Counter
from itertools import product
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from ootrr_triforce import restoration
from ootrr_triforce.catalog import CHESTS, ITEM_DATA, ITEM_IDS, LOCATION_IDS, MASTER_SWORD_LOCATION
from ootrr_triforce.native_presentations import AMMO_BAGS, BOTTLE_ITEMS, STARTER_KITS
from ootrr_triforce.network_catalog import SOURCES
from ootrr_triforce.receipt_events import DUNGEONS, OWNERS
from test_restoration import SaveRun, pouch, reward

CHECK = next(name for name, references in CHESTS.items() if len(references) > 1)
NATIVE = json.loads((ROOT / "tests/fixtures/native-bundle-quantities.json").read_bytes())["actors"]


class NativeRewardContractTests(unittest.TestCase):
    def test_every_catalogue_actor_exists_and_uses_one_exact_native_bundle(self):
        for name, meta in ITEM_DATA.items():
            with self.subTest(item=name):
                for actor in meta.get("tiers", [meta["actor"]]):
                    self.assertIn(actor, NATIVE)
                self.assertEqual(NATIVE[meta["actor"]]["BundleActorNum"], meta["quantity"])

    def test_every_native_ammunition_prerequisite_has_a_matching_delivery_guard(self):
        guarded = set()
        actors = {meta["actor"] for meta in ITEM_DATA.values()} | set(AMMO_BAGS)
        for actor in actors:
            base, visited = actor, set()
            while "BundleActor" in NATIVE[base]:
                self.assertNotIn(base, visited)
                visited.add(base)
                base = NATIVE[base]["BundleActor"].removeprefix("Work/Actor/").removesuffix(
                    ".engine__actor__ActorParam.gyml")
            native = NATIVE[base]
            # Native SmallBagActor is also present on rupees and Bombchus.
            # Wallets exist at the start; Bombchus are an independent randomizer
            # item. Neither implies a bomb/arrow/seed equipment prerequisite.
            if base not in {"Item_Bomb", "Item_Arrow_Normal", "Item_DekuSeed"}:
                continue
            with self.subTest(actor=actor):
                expected = native["SmallBagActor"].removeprefix("Work/Actor/").removesuffix(
                    ".engine__actor__ActorParam.gyml")
                self.assertTrue(actor in AMMO_BAGS, "Missing ammo equipment guard: " + actor)
                self.assertEqual(AMMO_BAGS[actor][0], expected)
                guarded.add(actor)
        self.assertEqual(guarded, set(AMMO_BAGS))

    def test_bottle_metadata_matches_the_native_contents_and_special_handling(self):
        for name, meta in ITEM_DATA.items():
            native = NATIVE[meta["actor"]]
            with self.subTest(item=name):
                if meta.get("bottle_item"):
                    self.assertEqual(meta["bottle_item"], native["BottleItem"])
                if "pouch_special" in meta:
                    self.assertEqual(meta["pouch_special"], native["PouchSpecialDeal"])
                if "pouch_category" in meta:
                    self.assertEqual(meta["pouch_category"], native["PouchCategory"])


class RewardMatrixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graphs = {}
        cls.records = {}
        for name in ITEM_DATA:
            roster = {CHECK: reward(name)}
            cls.graphs[name] = restoration.build_restoration_flow(pouch(), roster)[0]
            cls.records[name] = restoration.restoration_records(roster)[0]

    def fresh(self, name, owned=()):
        run = SaveRun(self.graphs[name])
        run.empty_bottle = True
        run.inventory.update(owned)
        return run

    def collect(self, run):
        run.steps = 0
        run.restore(CHECK)
        self.assertEqual(run.values[restoration.RESULT], LOCATION_IDS[CHECK])
        return run

    def assert_committed(self, run, name):
        flags = self.records[name]["flags"]
        self.assertTrue(all(run.values[flag] for flag in flags))
        self.assertTrue(run.saves)
        values, inventory = run.saves[-1]
        self.assertTrue(all(values[flag] for flag in flags))
        self.assertEqual(inventory, run.inventory)
        self.assertFalse(any(key.startswith("Archipelago.ReceivedIndex.") for key in values))

    def test_every_item_commits_one_recovery_and_repeated_collection_has_no_effect(self):
        self.assertEqual(set(self.graphs), set(ITEM_IDS))
        for name, meta in ITEM_DATA.items():
            with self.subTest(item=name):
                bag = AMMO_BAGS.get(meta["actor"], ())
                run = self.fresh(name, bag[:1])
                self.collect(run)
                self.assert_committed(run, name)
                inventory = run.inventory.copy()
                dungeon = run.dungeon_commands.copy()
                self.collect(run)
                self.assertEqual(run.inventory, inventory)
                self.assertEqual(run.dungeon_commands, dungeon)
                self.assert_committed(run, name)

    def test_all_progressive_ownership_masks_choose_the_next_tier_without_downgrading(self):
        for name, meta in ITEM_DATA.items():
            if meta["mode"] != "tiers":
                continue
            tiers = meta["tiers"]
            for mask in product((False, True), repeat=len(tiers)):
                with self.subTest(item=name, owned=mask):
                    held = [OWNERS.get(actor, actor) for actor, yes in zip(tiers, mask) if yes]
                    run = self.fresh(name, held)
                    self.collect(run)
                    highest = max((i for i, yes in enumerate(mask) if yes), default=-1)
                    expected = tiers[min(highest + 1, len(tiers) - 1)]
                    grants = [(params["Actor"], params["Num"]) for action, params in run.trace
                              if action == "EventTriggerAddOrRemovePouchContent"]
                    companions = []
                    if expected in STARTER_KITS and not held:
                        bags, ammo, amount = STARTER_KITS[expected]
                        companions = [(bags[0], 1), (ammo, amount)]
                    self.assertEqual(grants, companions + [(expected, 1)])

    def test_every_ammunition_family_requires_any_one_of_its_bags_and_never_substitutes(self):
        for name, meta in ITEM_DATA.items():
            bags = AMMO_BAGS.get(meta["actor"])
            if not bags:
                continue
            for bag in (None, *bags):
                with self.subTest(item=name, bag=bag):
                    run = self.fresh(name, [bag] if bag else ())
                    self.collect(run)
                    grants = [(params["Actor"], params["Num"]) for action, params in run.trace
                              if action == "EventTriggerAddOrRemovePouchContent"]
                    self.assertEqual(grants, [(meta["actor"], 1)] if bag else [])
                    self.assert_committed(run, name)
    def test_all_bottle_refills_defer_unchanged_until_a_bottle_becomes_empty(self):
        for name, meta in ITEM_DATA.items():
            if not meta.get("bottle_item") or meta.get("pouch_special") != "NotPushToPouch":
                continue
            with self.subTest(item=name):
                run = self.fresh(name)
                run.empty_bottle = False
                run.restore(CHECK)
                self.assertEqual(run.values[restoration.RESULT], -LOCATION_IDS[CHECK])
                self.assertFalse(run.saves)
                self.assertFalse(run.inventory)
                self.assertTrue(all(not run.values.get(f) for f in self.records[name]["flags"]))
                run.empty_bottle = True
                self.collect(run)
                self.assertEqual(run.inventory, Counter({"Bottle:" + str(BOTTLE_ITEMS[meta["bottle_item"]]): 1}))
                self.assertFalse(run.empty_bottle)
                self.assert_committed(run, name)

    def test_dungeon_items_credit_only_their_named_dungeon_or_keep_the_legacy_command(self):
        for name, meta in ITEM_DATA.items():
            if meta["mode"] != "generic":
                continue
            with self.subTest(item=name):
                run = self.fresh(name)
                self.collect(run)
                dungeon = meta.get("dungeon")
                if not dungeon:
                    expected = {"SmallKey": "EventGetDungeonSmallKey", "BossKey": "EventGetDungeonBossKey",
                                "Map": "EventGetDungeonMap", "Compass": "EventGetDungeonCompass"}[meta["kind"]]
                    self.assertEqual(run.dungeon_commands, Counter({expected: 1}))
                    continue
                prefix = "DungeonInfo." + DUNGEONS[dungeon] + "."
                fields = {k: v for k, v in run.values.items() if k.startswith("DungeonInfo.")}
                if meta["kind"] in {"SmallKey", "HideoutSmallKey"}:
                    expected = {prefix + "SmallKeyNum": 1, prefix + "SmallKeyTotalNum": 1,
                                prefix + "IsGetSmallKeyOnce": True}
                else:
                    suffix = {"BossKey": "IsGetBossKey", "GanonBossKey": "IsGetBossKey",
                              "Map": "IsGetMap", "Compass": "IsGetCompass"}[meta["kind"]]
                    expected = {prefix + suffix: True}
                self.assertEqual(fields, expected)
                self.assertFalse(run.inventory)
                self.assertFalse(run.dungeon_commands)

    def test_every_existing_physical_reference_prevents_a_second_reward(self):
        for name, raw in self.graphs.items():
            for flag in self.records[name]["flags"]:
                with self.subTest(item=name, existing=flag):
                    run = SaveRun(raw)
                    run.values[flag] = True
                    self.collect(run)
                    self.assertFalse(run.inventory)
                    self.assertFalse(run.dungeon_commands)
                    self.assert_committed(run, name)


class ForeignLocationMatrixTests(unittest.TestCase):
    def test_every_registered_source_recovers_without_inventory_payment_or_receipt_changes(self):
        roster = {name: reward(local=False) for name in (*SOURCES, MASTER_SWORD_LOCATION)}
        settings = {"network_sources_schema": 2}
        raw, entries = restoration.build_restoration_flow(pouch(), roster, settings)
        self.assertEqual(set(entries), {LOCATION_IDS[name] for name in roster})
        records = restoration.restoration_records(roster, settings)
        run = SaveRun(raw)
        cursor = "Archipelago.ReceivedIndex." + "b" * 64
        run.values[cursor] = 27
        run.values["Fixture.UnrelatedState"] = 123
        physical = {}
        for record in records:
            for flag in record["flags"]:
                self.assertNotIn(flag, physical, "Two independent checks share a completion flag: " + flag)
                physical[flag] = record["name"]
        for ordered in (records, list(reversed(records))):
            for record in ordered:
                with self.subTest(source=record["name"]):
                    run.steps = 0
                    run.trace.clear()
                    run.saves.clear()
                    run.run(entries[record["id"]])
                    self.assertEqual(run.values[restoration.RESULT], record["id"])
                    self.assertTrue(all(run.values[f] for f in record["flags"]))
                    self.assertTrue(all(run.values[c] == 1 for c in record["counters"]))
                    self.assertFalse(run.inventory)
                    self.assertFalse(run.dungeon_commands)
                    self.assertEqual(run.values[cursor], 27)
                    self.assertEqual(run.values["Fixture.UnrelatedState"], 123)
                    self.assertEqual(len(run.saves), 1)
                    self.assertTrue(all(run.saves[-1][0][f] for f in record["flags"]))


if __name__ == "__main__":
    unittest.main()
