"""The visible native item must not become a shop's AP purchase identity."""
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from oot_rando.formats import byml_codec as by
from oot_rando.formats.inspect_resources import sarc
from ootrr_triforce import shop_identity as identity
from ootrr_triforce.catalog import ITEM_DATA
from ootrr_triforce.shop_events import patch_shop_flow
from test_receipt_events import native_flow
from test_receipt_registration import IdentityCodec
from test_shop_events import Purchase, native_shop, records

AP = "Item_AP_" + "a" * 12
SHELF = "Shop_OOTRR_" + AP + "_10"
NATIVE = "Item_Hookshot"


def reference(actor):
    return "?ActorSystem/ActorName/" + actor + ".engine__actor__ActorName.bgyml"


def document(root):
    return by.dump(dict(root=root, endian="<", version=7))


def actor_path(actor):
    return "Actor/" + actor + ".engine__actor__ActorParam.bgyml"


def native_pack(actor, name):
    return by.build_sarc({actor_path(actor): document({"Components": {"ActorNameRef": reference(name)}})})


def shelf_pack():
    return by.build_sarc({actor_path(SHELF): document({
        "$parent": "Work/Actor/Shop_Item_Base.engine__actor__ActorParam.gyml",
        "Components": {"ActorNameRef": reference(NATIVE),
            "PouchContentRef": "?Component/PouchContentParam/" + SHELF + ".game__component__PouchContentParam.bgyml",
            "GameParameterTableRef": "?GameParameter/GameParameterTable/" + SHELF + ".engine__actor__GameParameterTable.bgyml",
            "ModelInfoRef": "?Component/ModelInfo/Native_Hookshot.engine__component__ModelInfo.bgyml",
            "AnimationRef": "?Component/AnimationParam/Native_Hookshot.engine__component__AnimationParam.bgyml"}}),
        "Model/Native_Hookshot.bfres": b"unchanged synthetic model",
        "Component/PouchContentParam/untouched.bgyml": b"unchanged synthetic pouch",
        "GameParameter/PriceParam/untouched.bgyml": b"unchanged synthetic price"})


def repair(raw):
    return identity.repair_shelf_pack(raw, shelf=SHELF, ap_actor=AP,
                                     native_reference=reference(NATIVE), ap_reference=reference(AP))


class ShopIdentityTests(unittest.TestCase):
    def test_only_actor_identity_changes_and_repeating_preserves_exact_bytes(self):
        raw = shelf_pack()
        after, growth, old = repair(raw)
        self.assertEqual(old, reference(NATIVE))
        self.assertGreaterEqual(growth, 0)
        before_files, after_files = sarc(raw), sarc(after)
        self.assertEqual(before_files.keys(), after_files.keys())
        expected = by.load(before_files[actor_path(SHELF)])
        expected["root"]["Components"]["ActorNameRef"] = reference(AP)
        self.assertEqual(by.load(after_files[actor_path(SHELF)]), expected)
        for path in before_files.keys() - {actor_path(SHELF)}:
            self.assertEqual(before_files[path], after_files[path])
        self.assertEqual(repair(after), (after, 0, reference(AP)))

    def test_unknown_or_crossed_purchase_identity_is_rejected(self):
        files = sarc(shelf_pack())
        for wrong in (reference("Item_AP_" + "b" * 12), reference("Item_Bomb"), None, 1):
            with self.subTest(identity=wrong):
                doc = by.load(files[actor_path(SHELF)])
                doc["root"]["Components"]["ActorNameRef"] = wrong
                altered = dict(files, **{actor_path(SHELF): document(doc["root"])})
                with self.assertRaises(ValueError):
                    repair(by.build_sarc(altered))

    def test_unrelated_actor_parent_and_pouch_are_rejected(self):
        for key in ("$parent", "PouchContentRef", "GameParameterTableRef"):
            with self.subTest(field=key):
                files = sarc(shelf_pack())
                doc = by.load(files[actor_path(SHELF)])
                target = doc["root"] if key == "$parent" else doc["root"]["Components"]
                target[key] = "unexpected native resource"
                files[actor_path(SHELF)] = by.dump(doc)
                with self.assertRaises(ValueError):
                    repair(by.build_sarc(files))

    def test_decoded_selection_drives_the_exact_local_progressive_recipe_and_check(self):
        row = records()[0]
        row.update(actor=AP, price=10, local_item="Progressive Hookshot", native_actor=NATIVE)
        flow = patch_shop_flow(native_shop(), [row], pouch_raw=native_flow())
        original = sarc(shelf_pack())
        fixed = sarc(repair(shelf_pack())[0])
        for files, expected in ((original, False), (fixed, True)):
            name = by.load(files[actor_path(SHELF)])["root"]["Components"]["ActorNameRef"]
            selected = name.split("/")[-1].split(".")[0]
            # The first tier is already held; a working AP shelf must choose
            # Longshot rather than asking the native shop to sell Hookshot again.
            run = Purchase(flow, selected, money=31, rewards=[row], owned={NATIVE})
            run.run("FirstBuy")
            self.assertEqual(bool(run.values.get(row["flag_name"])), expected)
            self.assertEqual("Item_Longshot" in run.owned, expected)
            self.assertEqual(run.money, 21 if expected else 31)

    def stage(self, folder):
        game, mod = Path(folder) / "game", Path(folder) / "mods/Archipelago/romfs"
        def write(home, path, raw):
            target = home / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        write(game, "Pack/ZsDic.pack.zs", b"identity codec fixture")
        write(game, "Pack/Actor/" + NATIVE + ".pack.zs", native_pack(NATIVE, NATIVE))
        write(mod, "Pack/Actor/" + AP + ".pack.zs", native_pack(AP, AP))
        write(mod, "Pack/Actor/" + SHELF + ".pack.zs", shelf_pack())
        table = [{"__RowId": actor, "ActorName": name} for actor, name in
                 ((AP, AP), (NATIVE, NATIVE), (SHELF, NATIVE), ("Unrelated", "Unrelated"))]
        write(mod, identity.ACTORS, document(table))
        paths = ["Pack/Actor/" + SHELF + ".pack", actor_path(SHELF), identity.ACTORS.removesuffix(".zs")]
        rest = b"RESTBL" + struct.pack("<IIII", 1, 160, len(paths), 0)
        rest += b"".join(struct.pack("<II", zlib.crc32(p.encode()), 65536) for p in sorted(paths))
        write(mod, identity.REST, rest)
        write(mod, "Mals/EUfr.Product.110.sarc.zs", b"native localized aliases remain unchanged")
        row = records()[0]
        row.update(actor=AP, price=10, local_item="Progressive Hookshot", native_actor=NATIVE)
        return game, mod, row

    @staticmethod
    def snapshot(root):
        return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}

    def test_staged_registry_matches_the_fixed_pack_and_preserves_every_other_resource(self):
        with tempfile.TemporaryDirectory() as folder, patch("ootrr_triforce.mod_codec.Codec", IdentityCodec):
            game, mod, row = self.stage(folder)
            before = self.snapshot(mod)
            self.assertEqual(identity.prepare_shop_identities(game, mod, [row]), {"shops": 1, "written": 3})
            after = self.snapshot(mod)
            changed = {p for p in before if before[p] != after[p]}
            self.assertEqual(changed, {"Pack/Actor/" + SHELF + ".pack.zs", identity.ACTORS, identity.REST})
            table = by.load(after[identity.ACTORS])["root"]
            self.assertEqual(next(r["ActorName"] for r in table if r["__RowId"] == SHELF), AP)
            self.assertEqual(identity.prepare_shop_identities(game, mod, [row]), {"shops": 0, "written": 0})
            self.assertEqual(self.snapshot(mod), after)

    def test_a_later_invalid_shelf_cannot_partially_write_an_earlier_valid_one(self):
        with tempfile.TemporaryDirectory() as folder, patch("ootrr_triforce.mod_codec.Codec", IdentityCodec):
            game, mod, row = self.stage(folder)
            other = records()[1]
            other.update(actor="Item_AP_" + "b" * 12, local_item="Bow", native_actor=ITEM_DATA["Bow"]["actor"])
            before = self.snapshot(mod)
            with self.assertRaises(ValueError):
                identity.prepare_shop_identities(game, mod, [row, other])
            self.assertEqual(self.snapshot(mod), before)

    def test_foreign_shelves_need_no_dictionary_or_identity_rewrite(self):
        with patch("ootrr_triforce.mod_codec.Codec", side_effect=AssertionError("unexpected codec")):
            self.assertEqual(identity.prepare_shop_identities("absent", "absent", records()), {"shops": 0, "written": 0})


if __name__ == "__main__":
    unittest.main()
