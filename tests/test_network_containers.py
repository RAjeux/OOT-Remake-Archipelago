"""A broken AP holder is recoverable; only its collected drop completes it."""
import copy
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from oot_rando.formats import byml_codec as byml
from ootrr_triforce import network_containers as containers
from ootrr_triforce.network_catalog import SOURCES, flag_name, murmur3


def record_of(metadata, number=1):
    name = metadata["name"]
    return {"name": name, "actor": "Item_AP_Source_Test_" + str(number),
            "pickup": "Obj_AP_Source_Test_" + str(number) + "_GH",
            "flag_name": flag_name(name), "flag_hash": murmur3(flag_name(name)),
            "network_source": 1, "metadata": copy.deepcopy(metadata)}


def sample_records():
    return [record_of(next(row for row in SOURCES.values()
                           if row["kind"] == "container" and row["native_kind"] == kind), index)
            for index, kind in enumerate(containers.CLASSES, 1)]


def document(root, version=2, endian="<"):
    return {"endian": endian, "version": version, "root": root}


def gamedata(records, *, permanent=True, existing=False, endian="<"):
    flags = [{"Hash": byml.U32(1), "DefaultValue": False, "ResetTypeValue": 8, "SaveFileIndex": 0}]
    if existing:
        flags += [{"Hash": byml.U32(record["flag_hash"]), "DefaultValue": False,
                   "ResetTypeValue": 8, "SaveFileIndex": 0} for record in records]
    rows = []
    for value in sorted(containers._hashes(records)):
        row = {"Hash": byml.U64(value), "ResetTypeValue": 24 if permanent else 88, "SaveFileIndex": 0}
        if not permanent:
            row["ExtraByte"] = 7
        rows.append(row)
    rows.append({"Hash": byml.U64(2), "ResetTypeValue": 88, "ExtraByte": 3, "SaveFileIndex": 0})
    return byml.dump(document({"Data": {"Bool": flags, "BoolExp": [], "Bool64bitKey": rows,
                                       "Int": [{"Hash": byml.U32(3), "DefaultValue": 15}]},
                               "MetaData": {"SaveDataSize": [64], "SaveDataOffsetPos": [64],
                                            "AllDataSaveSize": 64, "AllDataSaveOffset": 64,
                                            "OtherNativeMetadata": "preserve"}}, endian=endian))


def bancs(records):
    native, staged = {}, {}
    for record in records:
        kind = record["metadata"]["native_kind"]
        for variant in record["metadata"]["variants"]:
            path = variant["file"]
            actor = {"Hash": byml.U64(int(variant["actor"])), "Gyaml": sorted(containers.CLASSES[kind])[0],
                     "Dynamic": {"Drop__DropActor": variant["expected_actor"], "OtherNativeParameter": 7}}
            native.setdefault(path, []).append(copy.deepcopy(actor))
            actor["Dynamic"]["Drop__DropActor"] = record["pickup"]
            staged.setdefault(path, []).append(actor)
    for actors in [*native.values(), *staged.values()]:
        actors.append({"Hash": byml.U64(3), "Gyaml": "Obj_TBox_Field_Wood", "Dynamic": {"NativeReward": "keep"}})
    encode = lambda rows: {path: byml.dump(document({"Actors": actors, "OtherBancData": [1, 2, 3]}, 7))
                           for path, actors in rows.items()}
    return encode(native), encode(staged)


class ContainerPersistenceTests(unittest.TestCase):
    def test_no_containers_or_legacy_calls_have_no_io(self):
        with patch.object(Path, "read_bytes", side_effect=AssertionError("unexpected I/O")), \
                patch.object(Path, "mkdir", side_effect=AssertionError("unexpected I/O")):
            self.assertEqual(containers.prepare_network_containers("missing", "missing", []),
                             {"version": 1, "containers": 0, "files": 0})

    def test_only_holder_rows_change_and_missing_bools_add_exact_save_budgets(self):
        records = sample_records()
        for endian in ("<", ">"):
            for permanent in (False, True):
                with self.subTest(endian=endian, permanent=permanent):
                    raw = gamedata(records, permanent=permanent, endian=endian)
                    before = byml.load(raw)
                    result = containers.patch_container_gamedata(raw, records)
                    after = byml.load(result)
                    old_rows = containers._row_index(before, containers.TABLE)
                    new_rows = containers._row_index(after, containers.TABLE)
                    self.assertEqual(set(old_rows), set(new_rows))
                    for actor_hash in containers._hashes(records):
                        expected = dict(old_rows[actor_hash], ResetTypeValue=280)
                        expected.pop("ExtraByte", None)
                        self.assertEqual(new_rows[actor_hash], expected)
                    self.assertEqual(old_rows[2], new_rows[2])
                    self.assertEqual(after["root"]["Data"]["Int"], before["root"]["Data"]["Int"])
                    self.assertEqual(len(after["root"]["Data"]["Bool"]), 1 + len(records))
                    for record in records:
                        self.assertEqual(containers._row_index(after, "Bool")[record["flag_hash"]],
                                         {"Hash": record["flag_hash"], "DefaultValue": False,
                                          "ResetTypeValue": 8, "SaveFileIndex": 0})
                    metadata = after["root"]["MetaData"]
                    self.assertEqual(metadata["SaveDataSize"], [64 + 8 * len(records)])
                    self.assertEqual(metadata["SaveDataOffsetPos"], [64 + 8 * len(records)])
                    self.assertEqual(metadata["AllDataSaveSize"], 64 + 8 * len(records))
                    self.assertEqual(metadata["AllDataSaveOffset"], 64 + 8 * len(records))
                    self.assertEqual(metadata["OtherNativeMetadata"], "preserve")
                    self.assertEqual(containers.patch_container_gamedata(result, records), result)

    def test_existing_bools_leave_save_metadata_and_every_existing_parameter_exact(self):
        records = sample_records()
        raw = gamedata(records, existing=True)
        result = containers.patch_container_gamedata(raw, records)
        before, after = byml.load(raw), byml.load(result)
        self.assertEqual(before["root"]["MetaData"], after["root"]["MetaData"])
        self.assertEqual(before["root"]["Data"]["Bool"], after["root"]["Data"]["Bool"])
        self.assertEqual(containers.patch_container_gamedata(result, records), result)

    def test_only_trusted_containers_get_presence_not_chests_or_drops(self):
        records = sample_records()
        native, staged = bancs(records)
        for path, raw in staged.items():
            with self.subTest(path=path):
                result = containers.patch_container_banc(raw, native[path], path, records)
                expected = byml.load(raw)
                for record in records:
                    for variant in record["metadata"]["variants"]:
                        if variant["file"] == path:
                            actor = containers._actor(expected, int(variant["actor"]))
                            actor["Presence"] = {"FlagName": record["flag_name"], "IsCheckLazy": False, "IsNegation": True}
                self.assertEqual(byml.load(result), expected)
                self.assertEqual(containers.patch_container_banc(result, native[path], path, records), result)

    def test_leaving_before_pickup_recovers_the_holder_and_pickup_hides_all_layouts(self):
        metadata = next(row for row in SOURCES.values() if row["kind"] == "container" and len(row["variants"]) > 1)
        records = [record_of(metadata)]
        data = byml.load(containers.patch_container_gamedata(gamedata(records), records))
        rows = containers._row_index(data, containers.TABLE)
        native, staged = bancs(records)
        prepared = {path: byml.load(containers.patch_container_banc(raw, native[path], path, records))
                    for path, raw in staged.items()}
        collected, acknowledgements = False, []
        def available(variant, *, broken=False):
            actor = containers._actor(prepared[variant["file"]], int(variant["actor"]))
            presence = actor["Presence"]
            self.assertEqual(presence["FlagName"], records[0]["flag_name"])
            return (not collected if presence["IsNegation"] else collected) and not broken
        for variant in metadata["variants"]:
            self.assertTrue(available(variant))
            self.assertFalse(available(variant, broken=True))
            self.assertEqual(acknowledgements, [])  # No pickup event, no AP ACK.
            self.assertTrue(rows[int(variant["actor"])]["ResetTypeValue"] & 0x100)
            self.assertTrue(available(variant))  # Native scene reset after exit.
        # Successful pickup commits the single AP flag, independent of which
        # child/adult/dungeon layout supplied the physical holder.
        collected = True
        acknowledgements.append(records[0]["flag_name"])
        self.assertTrue(all(not available(variant) for variant in metadata["variants"]))
        self.assertEqual(acknowledgements, [records[0]["flag_name"]])

    def test_wrong_flags_actor_class_other_presence_and_unprepared_drop_fail_closed(self):
        records = sample_records()[:1]
        bad = copy.deepcopy(records)
        bad[0]["flag_hash"] ^= 1
        with self.assertRaises(ValueError):
            containers.container_records(bad)
        with self.assertRaises(ValueError):
            containers.container_records(records * 2)
        data = byml.load(gamedata(records, existing=True))
        containers._row_index(data, "Bool")[records[0]["flag_hash"]]["DefaultValue"] = True
        with self.assertRaises(ValueError):
            containers.patch_container_gamedata(byml.dump(data), records)
        native, staged = bancs(records)
        path = next(iter(staged))
        for edit in (lambda actor: actor.update(Gyaml="Obj_TBox_Field_Wood"),
                     lambda actor: actor.update(Presence={"FlagName": "NativeQuest", "IsNegation": False}),
                     lambda actor: actor["Dynamic"].update(Drop__DropActor="Obj_Rupee_Green")):
            doc = byml.load(staged[path])
            edit(doc["root"]["Actors"][0])
            with self.assertRaises(ValueError):
                containers.patch_container_banc(byml.dump(doc), native[path], path, records)


def presence_fixture(records, *, vanilla=None):
    native, staged = {}, {}
    for record in records:
        for variant in record["metadata"]["variants"]:
            path = variant["file"]
            actor = {"Hash": byml.U64(int(variant["actor"])),
                     "Gyaml": "Enemy_Skulltula_Gold" if record["metadata"]["kind"] == "skull" else variant["expected_actor"],
                     "Dynamic": {"NativeParameter": True}, "Links": [{"Dst": byml.U64(42), "Name": "NativeBossLink"}]}
            if vanilla is not None:
                actor["Presence"] = dict(vanilla)
            native.setdefault(path, []).append(copy.deepcopy(actor))
            if variant["via"] == "actor":
                actor["Gyaml"] = record["pickup"]
            else:
                actor["Dynamic"]["Drop__DropActor"] = record["pickup"]
            staged.setdefault(path, []).append(actor)
    encode = lambda rows: {path: byml.dump(document({"Actors": actors,
                           "AiGroups": [{"Hash": byml.U64(42), "NativeBossCondition": "DefeatBoss"}]}, 7))
                           for path, actors in rows.items()}
    return encode(native), encode(staged)


def expression_value(row, values):
    stack = []
    for instruction in row["Values"]:
        opcode = int(instruction[0])
        if opcode in (0, 10):
            stack.append(values[int(instruction[1])])
        elif opcode == 5:
            stack.append(not stack.pop())
        elif opcode == 3:
            right, left = stack.pop(), stack.pop()
            stack.append(left and right)
        else:
            raise AssertionError(opcode)
    assert len(stack) == 1
    return stack[0]


class NetworkPresenceTests(unittest.TestCase):
    def test_pickup_and_skull_presence_preserve_boss_links_and_all_layouts(self):
        records = [record_of(next(row for row in SOURCES.values() if row["kind"] == kind
                                  and len(row["variants"]) > 1), index)
                   for index, kind in enumerate(("pickup", "skull"), 1)]
        native, staged = presence_fixture(records)
        for path, raw in staged.items():
            result, programs = containers.patch_network_presence_banc(raw, native[path], path, records)
            self.assertEqual(programs, {})
            expected = byml.load(raw)
            for record in records:
                for variant in record["metadata"]["variants"]:
                    if variant["file"] == path:
                        containers._actor(expected, int(variant["actor"]))["Presence"] = {
                            "FlagName": record["flag_name"], "IsCheckLazy": False, "IsNegation": True}
            self.assertEqual(byml.load(result), expected)
            self.assertEqual(containers.patch_network_presence_banc(result, native[path], path, records)[0], result)
        data = gamedata(records, existing=True)
        self.assertEqual(containers.patch_network_presence_gamedata(data, records, {}), data)

    def test_quest_positive_negative_and_expression_conditions_remain_required(self):
        import itertools
        record = record_of(next(row for row in SOURCES.values() if row["kind"] == "skull"))
        records = [record]
        gate_name, gate_hash = "NativeQuestGate", murmur3("NativeQuestGate")
        for kind, negated, lazy in itertools.product(("Bool", "BoolExp"), (False, True), (False, True)):
            with self.subTest(kind=kind, negated=negated, lazy=lazy):
                vanilla = {"FlagName": gate_name, "IsNegation": negated, "IsCheckLazy": lazy}
                native, staged = presence_fixture(records, vanilla=vanilla)
                programs = {}
                for path, raw in staged.items():
                    changed, requested = containers.patch_network_presence_banc(raw, native[path], path, records)
                    programs.update(requested)
                    target = byml.load(changed)["root"]["Actors"][0]["Presence"]
                    self.assertFalse(target["IsNegation"])
                    self.assertEqual(target["IsCheckLazy"], lazy)
                raw_data = byml.load(gamedata(records, existing=True))
                native_row = {"Hash": byml.U32(gate_hash), "DefaultValue": False,
                              "ResetTypeValue": 8, "SaveFileIndex": 0} if kind == "Bool" else {
                                  "Hash": byml.U32(gate_hash), "ResetTypeValue": 0, "SaveFileIndex": -1,
                                  "Values": [[byml.U64(0), byml.U64(1)]]}
                raw_data["root"]["Data"][kind].append(native_row)
                original = byml.dump(raw_data)
                result = containers.patch_network_presence_gamedata(original, records, programs)
                data = byml.load(result)
                self.assertEqual(raw_data["root"]["MetaData"], data["root"]["MetaData"])
                for expression in programs:
                    row = containers._row_index(data, "BoolExp")[murmur3(expression)]
                    self.assertEqual(row["SaveFileIndex"], -1)
                    self.assertEqual(row["ResetTypeValue"], 0)
                    for collected, gate in itertools.product((False, True), repeat=2):
                        actual = expression_value(row, {record["flag_hash"]: collected, gate_hash: gate})
                        self.assertEqual(actual, not collected and (not gate if negated else gate))
                self.assertEqual(containers.patch_network_presence_gamedata(result, records, programs), result)

    def test_unknown_presence_program_or_source_identity_is_rejected(self):
        records = [record_of(next(row for row in SOURCES.values() if row["kind"] == "skull"))]
        vanilla = {"FlagName": "NativeQuest", "IsNegation": False, "IsCheckLazy": False}
        native, staged = presence_fixture(records, vanilla=vanilla)
        path = next(iter(staged))
        _, programs = containers.patch_network_presence_banc(staged[path], native[path], path, records)
        with self.assertRaises(ValueError):
            containers.patch_network_presence_gamedata(gamedata(records, existing=True), records, programs)
        wrong = byml.load(staged[path])
        wrong["root"]["Actors"][0]["Gyaml"] = "Enemy_Skulltula"
        with self.assertRaises(ValueError):
            containers.patch_network_presence_banc(byml.dump(wrong), native[path], path, records)
        wrong = byml.load(staged[path])
        wrong["root"]["Actors"][0]["Presence"] = {"FlagName": "AnotherQuest", "IsNegation": False}
        with self.assertRaises(ValueError):
            containers.patch_network_presence_banc(byml.dump(wrong), native[path], path, records)

    def test_other_source_kinds_and_legacy_presence_calls_have_no_io(self):
        with patch.object(Path, "read_bytes", side_effect=AssertionError("unexpected I/O")):
            self.assertEqual(containers.prepare_network_presence("missing", "missing", sample_records())["files"], 0)
            self.assertEqual(containers.prepare_network_presence("missing", "missing", [])["files"], 0)


@unittest.skipUnless(os.environ.get("OOTRR_ROMFS"), "requires a private native v1.1.1 RomFS")
class NativeContainerPersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from ootrr_triforce import app_runtime
        from ootrr_triforce.mod_codec import Codec
        cls.romfs = Path(os.environ["OOTRR_ROMFS"])
        runtime = os.environ.get("OOTRR_CODEC_RESOURCES")
        cls.override = patch.object(app_runtime, "_resource_override", Path(runtime)) if runtime else \
            patch.object(sys, "argv", [os.environ.get("OOTRR_CODEC_APP", str(ROOT / "dist/Client-OOT-Remake.pyz"))])
        cls.override.start()
        cls.addClassCleanup(cls.override.stop)
        cls.codec = Codec((cls.romfs / "Pack/ZsDic.pack.zs").read_bytes())
        cls.data = cls.codec.decode((cls.romfs / containers.DATA).read_bytes())
        cls.raws = {}

    @classmethod
    def native(cls, path):
        if path not in cls.raws:
            cls.raws[path] = cls.codec.decode((cls.romfs / path).read_bytes())
        return cls.raws[path]

    def test_every_exported_container_has_a_native_scene_resettable_row_and_no_quest_presence(self):
        records = [record_of(row, index) for index, row in enumerate(SOURCES.values(), 1) if row["kind"] == "container"]
        self.assertGreaterEqual(len(records), 642)
        rows = containers._row_index(byml.load(self.data), containers.TABLE)
        maps = {}
        for record in containers.container_records(records):
            kind = record["metadata"]["native_kind"]
            for variant in record["metadata"]["variants"]:
                path = variant["file"]
                if path not in maps:
                    maps[path] = byml.load(self.native(path))
                actor_hash = int(variant["actor"])
                actor = containers._actor(maps[path], actor_hash)
                self.assertIn(actor["Gyaml"], containers.CLASSES[kind])
                self.assertNotIn("Presence", actor)
                self.assertEqual(actor.get("Dynamic", {}).get("Drop__DropActor", ""), variant["expected_actor"])
                self.assertEqual(rows[actor_hash]["ResetTypeValue"], 280 if kind == "flying_pot" else 88)
                self.assertEqual(rows[actor_hash]["SaveFileIndex"], 0)

    def stage(self, mod, records):
        from oot_rando.game.resource_allocations import grow_resources
        by_path = {}
        growth = {}
        for record in records:
            for variant in record["metadata"]["variants"]:
                by_path.setdefault(variant["file"], []).append((record, variant))
        for path, variants in by_path.items():
            doc = byml.load(self.native(path))
            for record, variant in variants:
                actor = containers._actor(doc, int(variant["actor"]))
                if variant["via"] == "actor":
                    actor["Gyaml"] = record["pickup"]
                else:
                    actor.setdefault("Dynamic", {})["Drop__DropActor"] = record["pickup"]
            target = mod / path
            target.parent.mkdir(parents=True, exist_ok=True)
            prepared = byml.dump(doc)
            growth[path] = max(0, len(prepared) - len(self.native(path)))
            target.write_bytes(self.codec.encode(prepared, (self.romfs / path).read_bytes()))
        # Reproduce the released OOTRR holder transformation without invoking
        # or changing the generator: permanent reset24 with no ExtraByte.
        data = byml.load(self.data)
        rows = containers._row_index(data, containers.TABLE)
        for actor_hash in containers._hashes([record for record in records if record["metadata"]["kind"] == "container"]):
            rows[actor_hash]["ResetTypeValue"] = 24
            rows[actor_hash].pop("ExtraByte", None)
        target = mod / containers.DATA
        target.parent.mkdir(parents=True, exist_ok=True)
        prepared = byml.dump(data)
        growth[containers.DATA] = max(0, len(prepared) - len(self.data))
        target.write_bytes(self.codec.encode(prepared, (self.romfs / containers.DATA).read_bytes()))
        native_table = (self.romfs / containers.REST).read_bytes()
        table, _ = grow_resources(self.codec.decode(native_table), growth)
        target = mod / containers.REST
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(self.codec.encode(table, native_table))

    def test_private_native_bundle_preserves_other_sources_and_save_metadata(self):
        from oot_rando.game.resource_allocations import allocation
        records = sample_records()
        multi = next(row for row in SOURCES.values() if row["kind"] == "container" and len(row["variants"]) >= 3)
        if multi["name"] not in {record["name"] for record in records}:
            records.append(record_of(multi, len(records) + 1))
        with tempfile.TemporaryDirectory() as root:
            mod = Path(root) / "Archipelago/romfs"
            self.stage(mod, records)
            base_data = self.codec.decode((mod / containers.DATA).read_bytes())
            before = byml.load(base_data)
            result = containers.prepare_network_containers(self.romfs, mod, records)
            self.assertEqual(result["containers"], len(records))
            after = byml.load(self.codec.decode((mod / containers.DATA).read_bytes()))
            old_rows, new_rows = containers._row_index(before, containers.TABLE), containers._row_index(after, containers.TABLE)
            self.assertEqual(set(old_rows), set(new_rows))
            selected = containers._hashes(records)
            self.assertTrue(all(new_rows[key] == value for key, value in old_rows.items() if key not in selected))
            self.assertTrue(all(new_rows[key]["ResetTypeValue"] == 280 and "ExtraByte" not in new_rows[key] for key in selected))
            native_meta, new_meta = before["root"]["MetaData"], after["root"]["MetaData"]
            self.assertEqual(new_meta["AllDataSaveSize"], native_meta["AllDataSaveSize"] + 8 * len(records))
            self.assertEqual(new_meta["SaveDataSize"][1:], native_meta["SaveDataSize"][1:])
            states = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in mod.rglob("*") if path.is_file()}
            self.assertEqual(containers.prepare_network_containers(self.romfs, mod, records)["files"], 0)
            self.assertEqual(states, {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in mod.rglob("*") if path.is_file()})
            table = self.codec.decode((mod / containers.REST).read_bytes())
            for path in states:
                rel = path.relative_to(mod).as_posix()
                if rel != containers.REST:
                    size = len(self.codec.decode(path.read_bytes()))
                    self.assertGreater(allocation(table, rel), size)
            self.assertEqual(self.codec.decode((self.romfs / containers.DATA).read_bytes()), self.data)

    def test_failed_late_variant_validation_writes_nothing(self):
        records = sample_records()
        with tempfile.TemporaryDirectory() as root:
            mod = Path(root) / "Archipelago/romfs"
            self.stage(mod, records)
            record = records[-1]
            variant = record["metadata"]["variants"][-1]
            path = mod / variant["file"]
            frame = path.read_bytes()
            doc = byml.load(self.codec.decode(frame))
            containers._actor(doc, int(variant["actor"]))["Presence"] = {"FlagName": "UnknownQuest"}
            path.write_bytes(self.codec.encode(byml.dump(doc), frame))
            before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in mod.rglob("*") if path.is_file()}
            with self.assertRaises(ValueError):
                containers.prepare_network_containers(self.romfs, mod, records)
            self.assertEqual(before, {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in mod.rglob("*") if path.is_file()})

    def test_all_136_pickups_and_100_skulls_preserve_native_gates_and_map_affiliation(self):
        from oot_rando.game.resource_allocations import allocation
        records = [record_of(row, index) for index, row in enumerate(SOURCES.values(), 1)
                   if row["kind"] in ("pickup", "skull")]
        self.assertEqual(sum(record["metadata"]["kind"] == "pickup" for record in records), 136)
        self.assertEqual(sum(record["metadata"]["kind"] == "skull" for record in records), 100)
        self.assertEqual(len(containers.presence_records(records)), 236)
        with tempfile.TemporaryDirectory() as root:
            mod = Path(root) / "Archipelago/romfs"
            self.stage(mod, records)
            expected = {path.relative_to(mod).as_posix(): byml.load(self.codec.decode(path.read_bytes()))
                        for path in mod.rglob("*.byml.zs") if path.relative_to(mod).as_posix().startswith("Banc/")}
            before = byml.load(self.codec.decode((mod / containers.DATA).read_bytes()))
            result = containers.prepare_network_presence(self.romfs, mod, records)
            self.assertEqual(result["sources"], 236)
            self.assertEqual(result["variants"], 311)
            self.assertEqual(result["expressions"], 10)
            data = byml.load(self.codec.decode((mod / containers.DATA).read_bytes()))
            self.assertEqual(before["root"]["Data"]["Bool64bitKey"], data["root"]["Data"]["Bool64bitKey"])
            self.assertEqual(data["root"]["MetaData"]["AllDataSaveSize"],
                             before["root"]["MetaData"]["AllDataSaveSize"] + 8 * len(records))
            expressions = containers._row_index(data, "BoolExp")
            for record in records:
                for variant in record["metadata"]["variants"]:
                    path, actor_hash = variant["file"], int(variant["actor"])
                    native = containers._actor(byml.load(self.native(path)), actor_hash)
                    actor = containers._actor(expected[path], actor_hash)
                    vanilla = native.get("Presence")
                    if vanilla is None:
                        actor["Presence"] = {"FlagName": record["flag_name"], "IsCheckLazy": False, "IsNegation": True}
                    else:
                        name = containers.presence_expression(record["flag_name"], vanilla)
                        actor["Presence"] = {"FlagName": name, "IsCheckLazy": vanilla["IsCheckLazy"], "IsNegation": False}
                        row = expressions[murmur3(name)]
                        # Beans remain required while uncollected; collecting a
                        # remote item hides the skull without an IsGet.Token.
                        for collected in (False, True):
                            for quest in (False, True):
                                values = {record["flag_hash"]: collected, murmur3(vanilla["FlagName"]): quest}
                                self.assertEqual(expression_value(row, values), not collected and quest)
            for path, doc in expected.items():
                self.assertEqual(byml.load(self.codec.decode((mod / path).read_bytes())), doc)
            # Banc Links/AiGroups, boss-heart spawn affiliation, unrelated actors
            # and original native conditions are all included in that comparison.
            table = self.codec.decode((mod / containers.REST).read_bytes())
            for path in expected.keys() | {containers.DATA}:
                self.assertGreater(allocation(table, path), len(self.codec.decode((mod / path).read_bytes())))
            mtimes = {path: path.stat().st_mtime_ns for path in mod.rglob("*") if path.is_file()}
            self.assertEqual(containers.prepare_network_presence(self.romfs, mod, records)["files"], 0)
            self.assertEqual(mtimes, {path: path.stat().st_mtime_ns for path in mod.rglob("*") if path.is_file()})

    def test_presence_bundle_rejects_a_changed_quest_before_any_write(self):
        record = record_of(SOURCES["Colossus GS Bean Patch"])
        records = [record]
        with tempfile.TemporaryDirectory() as root:
            mod = Path(root) / "Archipelago/romfs"
            self.stage(mod, records)
            path = mod / record["metadata"]["variants"][0]["file"]
            frame = path.read_bytes()
            doc = byml.load(self.codec.decode(frame))
            actor = containers._actor(doc, int(record["metadata"]["variants"][0]["actor"]))
            actor["Presence"]["IsNegation"] = True
            path.write_bytes(self.codec.encode(byml.dump(doc), frame))
            before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in mod.rglob("*") if path.is_file()}
            with self.assertRaises(ValueError):
                containers.prepare_network_presence(self.romfs, mod, records)
            self.assertEqual(before, {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in mod.rglob("*") if path.is_file()})


if __name__ == "__main__":
    unittest.main()
