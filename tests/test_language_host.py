"""Compile the actual native startup bridge with a synthetic game language API."""
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / "native/ootrr_archipelago.inc").read_text(encoding="utf-8")
helper = source[source.index("static void ap_boot_error16("):source.index("static int ap_boot16(")]
header = r'''
#include <assert.h>
#include <stddef.h>
#include <string.h>
#include <wchar.h>

static const char *game_language;
static int stage, language_calls, start_calls, result;
static int boxes, box_french, logs;
static char *expected_root, *expected_token;
#define MB_OK 0
#define MB_ICONERROR 16
static void hos_log(const char *format, ...) {
    assert(strstr(format, "activation failed") != NULL);
    logs++;
}
static int MessageBoxW(void *window, const wchar_t *text, const wchar_t *title, unsigned flags) {
    assert(!window && !wcscmp(title, L"Archipelago") && flags == MB_ICONERROR && stage == 1);
    box_french = wcsstr(text, L"Le mod Archipelago") != NULL;
    assert(box_french || wcsstr(text, L"The Archipelago mod") != NULL);
    boxes++;
    return 0;
}
const char *hos_desired_language(void) {
    assert(stage == 0);
    stage = 1;
    return game_language;
}
static void set_language(char *language) {
    assert(stage == 1 && language == game_language);
    language_calls++;
    stage = 2;
}
static int start_client(char *root, char *token) {
    assert(stage == 2 && root == expected_root && token == expected_token);
    start_calls++;
    stage = 3;
    return result;
}
'''
checks = r'''
int main(void) {
    char root[] = "isolated-room", token[] = "unchanged-room-token";
    expected_root = root;
    expected_token = token;
    const char *languages[] = {"fr", "fr-CA", "en-US", "de", NULL};
    for (unsigned i = 0; i < sizeof languages / sizeof *languages; ++i) {
        game_language = languages[i];
        for (result = 0; result <= 1; ++result) {
            stage = language_calls = start_calls = 0;
            assert(ap_start_client16(start_client, set_language, root, token) == result);
            assert(stage == 3 && language_calls == 1 && start_calls == 1);
            assert(!strcmp(root, "isolated-room") && !strcmp(token, "unchanged-room-token"));
        }
    }
    stage = language_calls = start_calls = 0;
    assert(!ap_start_client16(NULL, set_language, root, token));
    assert(!ap_start_client16(start_client, NULL, root, token));
    assert(!ap_start_client16(NULL, NULL, root, token));
    assert(!stage && !language_calls && !start_calls);
    for (unsigned i = 0; i < sizeof languages / sizeof *languages; ++i) {
        stage = boxes = logs = 0;
        game_language = languages[i];
        ap_boot_error16();
        const int french = game_language && (!strcmp(game_language, "fr") || !strcmp(game_language, "fr-CA"));
        assert(boxes == 1 && logs == 1 && box_french == french);
        assert(!language_calls && !start_calls);
    }
    return 0;
}
'''
folder = ROOT / "build/tests"
folder.mkdir(parents=True, exist_ok=True)
c_file = folder / "check_language_host.c"
c_file.write_text(header + helper + checks, encoding="utf-8")
executable = folder / ("check_language_host.exe" if os.name == "nt" else "check_language_host")
compiler = os.environ.get("CC") or shutil.which("gcc") or "clang"
subprocess.run([compiler, "-std=c11", "-Wall", "-Werror", str(c_file), "-o", str(executable)], check=True)
subprocess.run([str(executable.resolve())], check=True)
print("PASS native language bridge: actual game API before startup, French/English/other/null codes, missing exports, localized error dialog/English diagnostics, startup failure and unchanged profile/token.")
