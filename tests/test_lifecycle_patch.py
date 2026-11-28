"""Native Bool-write hooks are bounded, passive and part of a whole lift."""
import importlib.util
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from ootrr_triforce.native_lifecycle import patch_lift_driver
spec = importlib.util.spec_from_file_location("native_lifecycle_patch", ROOT / "native/ootrr_ap_lifecycle_patch.py")
lift = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lift)

NATIVE = b'#include "a64.h"\nvoid f_806a2b20(Ctx *c) {\n    c->x[9] = c->x[0];\n}\n'


class LifecyclePatchTests(unittest.TestCase):
    def test_lifted_entry_keeps_all_native_instructions_and_arguments(self):
        for signature in (b"Ctx *c", b"Ctx *__restrict A64_NOESC c"):
            for newline in (b"\n", b"\r\n"):
                source = NATIVE.replace(b"Ctx *c", signature).replace(b"\n", newline)
                result, found = lift.patch_source(source)
                self.assertEqual(found, 1)
                self.assertIn(lift.CALL.encode() + newline + b"    c->x[9] = c->x[0];", result)
                restored = result.replace(lift.DECLARATION.encode() + newline, b"").replace(lift.CALL.encode() + newline, b"")
                self.assertEqual(restored, source)
                self.assertEqual(lift.patch_source(result), (result, 1))

    def test_complete_lift_requires_one_implementation_and_never_partially_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            first, second = home / "code_0.c", home / "code_1.c"
            first.write_bytes(NATIVE)
            second.write_bytes(NATIVE)
            with self.assertRaises(ValueError):
                lift.apply(home, required=True)
            self.assertEqual(first.read_bytes(), NATIVE)
            self.assertEqual(second.read_bytes(), NATIVE)
            second.write_bytes(b"unrelated native source")
            self.assertEqual(lift.apply(home, required=True), 1)
            once = first.read_bytes()
            self.assertEqual(lift.apply(home, required=True), 1)
            self.assertEqual(first.read_bytes(), once)
            self.assertEqual(second.read_bytes(), b"unrelated native source")

    def test_partial_lift_is_not_mistaken_for_a_supported_complete_lift(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.assertEqual(lift.apply(temporary), 0)
            with self.assertRaises(ValueError):
                lift.apply(temporary, required=True)

    def test_crossed_or_moved_observer_is_rejected(self):
        fixed = lift.patch_source(NATIVE)[0]
        for source in (fixed.replace(b"f_806a2b20", b"f_806a2b21"),
                       fixed.replace(lift.CALL.encode(), b"    /* observer removed */"),
                       fixed + b"\n// " + lift.MARKER.encode()):
            with self.subTest(source=source), self.assertRaises(ValueError):
                lift.patch_source(source)

    def test_sdk_pipeline_preserves_docstring_original_result_and_required_flag(self):
        original = ('def apply(gen, *, required=False):\n'
                    '    """Original native patch docstring."""\n'
                    '    calls.append(("original", gen))\n'
                    '    return "native result"\n')
        for newline in ("\n", "\r\n"):
            source = original.replace("\n", newline).encode()
            updated = patch_lift_driver(source)
            self.assertEqual(patch_lift_driver(updated), updated)
            calls = []
            fake = SimpleNamespace(apply=lambda gen, **kw: calls.append(("lifecycle", gen, kw)))
            namespace = {"calls": calls}
            with patch.dict(sys.modules, {"ootrr_ap_lifecycle_patch": fake}):
                exec(compile(updated, "synthetic_sdk.py", "exec"), namespace)
                self.assertEqual(namespace["apply"]("private-gen", required=True), "native result")
            self.assertEqual(namespace["apply"].__doc__, "Original native patch docstring.")
            self.assertEqual(calls, [("lifecycle", "private-gen", {"required": True}), ("original", "private-gen")])

    def test_unknown_or_duplicated_sdk_pipeline_fails_before_any_edit(self):
        for raw in (b"def apply(other):\n    pass\n", b"def another(gen):\n    pass\n",
                    b"def apply(gen):\n    pass\ndef apply(gen):\n    pass\n", b"broken python :"):
            with self.subTest(source=raw), self.assertRaises(ValueError):
                patch_lift_driver(raw)


if __name__ == "__main__":
    unittest.main()
