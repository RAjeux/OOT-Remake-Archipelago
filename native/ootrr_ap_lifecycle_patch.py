"""Add a passive AP observer to the supported game's own Bool-write entry.

Installed beside the host's lift patches. It changes neither guest arguments
nor game data and must find exactly one native SetBool implementation in a
complete lift. All files are validated before an atomic replacement.
"""
from pathlib import Path
import os
import re
import tempfile

MARKER = "OOTRR-AP native lifecycle Bool hook 1"
DECLARATION = "extern void ootrr_ap_gamedata_bool16(uint64_t, uint32_t, uint32_t, const char *);"
CALL = ('    ootrr_ap_gamedata_bool16(c->x[0], (uint32_t)c->x[2], (uint32_t)c->x[1], '
        '"' + MARKER + '");')
# 0.8.3 uses the plain argument; 0.8.4's lift annotates the same native ABI.
ENTRY = re.compile(r"(?m)^void f_806a2b20\(Ctx \*(?:__restrict A64_NOESC )?c\) \{\r?\n")


def patch_source(raw):
    text = raw.decode("utf-8")
    matches = list(ENTRY.finditer(text))
    if not matches:
        if MARKER in text or CALL in text:
            raise ValueError("The AP lifecycle observer is outside its native function.")
        return raw, 0
    if len(matches) != 1:
        raise ValueError("The native Bool-write implementation is ambiguous.")
    newline = "\r\n" if "\r\n" in text else "\n"
    at = matches[0].end()
    if MARKER in text:
        if (text.count(MARKER) != 1 or text.count(DECLARATION) != 1
                or not text[at:].startswith(CALL + newline)):
            raise ValueError("The AP lifecycle observer has an unknown layout.")
        return raw, 1
    if text.count('#include "a64.h"') != 1 or DECLARATION in text:
        raise ValueError("The lifted Bool-write source has no unique native header.")
    text = text[:at] + CALL + newline + text[at:]
    text = text.replace('#include "a64.h"', '#include "a64.h"' + newline + DECLARATION, 1)
    return text.encode("utf-8"), 1


def apply(gen, *, required=False):
    outputs, found = [], 0
    for path in sorted(Path(gen).glob("code_*.c")):
        before = path.read_bytes()
        after, count = patch_source(before)
        found += count
        if after != before:
            outputs.append((path, after))
    if found > 1 or (required and found != 1):
        raise ValueError("The AP lifecycle observer requires exactly one native Bool-write function.")
    for path, raw in outputs:
        descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".ap-", dir=path.parent)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(raw)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return found
