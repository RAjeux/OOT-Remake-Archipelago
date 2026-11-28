"""Bind the AP pause observer to the host's supported native-lift pipeline."""
import ast

from .i18n import tr

LIFT_FILES = ("ootrr_ap_lifecycle_patch.py",)
BUILD_MARK = b"OOTRR-AP native lifecycle Bool hook 1"
INJECTION = ("    # OOTRR_AP_LIFECYCLE_BEGIN\n"
             "    from ootrr_ap_lifecycle_patch import apply as _ootrr_ap_lifecycle_apply\n"
             "    _ootrr_ap_lifecycle_apply(gen, required=bool(locals().get('required', False)))\n"
             "    # OOTRR_AP_LIFECYCLE_END\n")


def patch_lift_driver(raw):
    """Install one idempotent call after the original apply() docstring."""
    def invalid():
        return ValueError(tr("Triforce tools are incompatible with the native client."))
    try:
        original = raw.decode("utf-8")
        text = original.replace("\r\n", "\n")
        tree = ast.parse(text)
    except (UnicodeError, SyntaxError) as exc:
        raise invalid() from exc
    found = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "apply"]
    if len(found) != 1 or not found[0].args.args or found[0].args.args[0].arg != "gen":
        raise invalid()
    function = found[0]
    body = function.body
    if (isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)):
        body = body[1:]
    if not body:
        raise invalid()
    lines = text.splitlines(keepends=True)
    if "OOTRR_AP_LIFECYCLE" in text or "_ootrr_ap_lifecycle_apply" in text:
        segment = "".join(lines[function.lineno - 1:function.end_lineno])
        if (text.count(INJECTION) != 1 or INJECTION not in segment
                or not isinstance(body[0], ast.ImportFrom)
                or body[0].module != "ootrr_ap_lifecycle_patch"
                or len(body) < 2 or not isinstance(body[1], ast.Expr)
                or not isinstance(body[1].value, ast.Call)
                or not isinstance(body[1].value.func, ast.Name)
                or body[1].value.func.id != "_ootrr_ap_lifecycle_apply"):
            raise invalid()
        return raw
    at = body[0].lineno - 1
    lines.insert(at, INJECTION)
    result = "".join(lines)
    ast.parse(result)
    if "\r\n" in original:
        result = result.replace("\n", "\r\n")
    return result.encode("utf-8")
