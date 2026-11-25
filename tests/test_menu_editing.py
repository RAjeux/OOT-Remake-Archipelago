"""Run the actual C++ editor transitions without the renderer or game assets."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from ootrr_triforce.menu_setup import _edits_080

source = (ROOT / "native/ootrr_ap_menu.inc").read_text(encoding="utf-8")
erase = source[source.index("void erase("):source.index("bool french(")]
editing = source[source.index("void finish("):source.index("void action(")]
header = r'''
#include <atomic>
#include <cassert>
#include <string>
namespace ap_menu {
std::string server, password, previous, local_error;
bool editing=false, dirty=false, previous_dirty=false, capitals=false, symbols=false;
int field=0, mode=0, previous_mode=0, key_row=0, key_col=0;
std::atomic<bool> text_wanted{false};
'''
checks = r'''
}
int main() {
    using namespace ap_menu;
    server="ws://127.0.0.1:38281";
    begin(1);
    assert(editing && text_wanted.load());
    finish(true);
    assert(!editing && !text_wanted.load() && mode==0 && !dirty);
    begin(1);
    password="replacement";
    finish(true);
    assert(mode==1 && dirty && password=="replacement");
    begin(1);
    password="discarded";
    finish(false);
    assert(mode==1 && dirty && password=="replacement");
    begin(1);
    finish(true);
    assert(mode==1 && dirty && password=="replacement");
    begin(1);
    password.clear();
    finish(true);
    assert(mode==1 && dirty && password.empty());
    mode=2;
    begin(1);
    finish(true);
    assert(mode==2 && dirty);
    leave();
    assert(password.empty() && previous.empty() && mode==0 && !dirty);
    begin(0);
    finish(true);
    assert(!dirty);
    begin(0);
    server="other.example:1234";
    finish(false);
    assert(server=="ws://127.0.0.1:38281" && !dirty);
    begin(0);
    server="other.example:1234";
    finish(true);
    assert(server=="other.example:1234" && dirty && mode==0);
    begin(1);
    password="cancel on close";
    leave();
    assert(!editing && !text_wanted.load() && password.empty() && previous.empty());
    return 0;
}
'''
folder = ROOT / "build/tests"
folder.mkdir(parents=True, exist_ok=True)
cpp = folder / "check_menu_editing.cpp"
cpp.write_text(header + erase + editing + checks, encoding="utf-8")
executable = folder / ("check_menu_editing.exe" if os.name == "nt" else "check_menu_editing")
compiler = os.environ.get("CXX")
if not compiler and os.environ.get("CC"):
    cc = Path(os.environ["CC"])
    for name in (cc.name.replace("gcc", "g++"), cc.name.replace("clang", "clang++")):
        candidate = cc.with_name(name)
        if candidate != cc and candidate.is_file():
            compiler = str(candidate)
            break
compiler = compiler or shutil.which("g++") or shutil.which("clang++") or "c++"
runtime_flags = ["-static"] if os.name == "nt" else []
subprocess.run([compiler, "-std=c++17", "-Wall", "-Werror", *runtime_flags,
                str(cpp), "-o", str(executable)], check=True)
subprocess.run([str(executable.resolve())], check=True)
print("PASS menu editing: no-op keeps saved credentials, replacement, explicit clear, cancel, close and input ownership.")

# Compile the exact v0.8 adapter's routing block alongside the real AP edit and
# close functions. Native output dimensions, Mods search and AP credentials use
# the same host text queue, so they must retain distinct ownership.
routing_header = r'''
#include <mutex>
#include <vector>
constexpr int TAB_ARCHIPELAGO=5, kModsPage=3;
std::atomic<bool> open_now{true}, mods_text_wanted{false}, size_text_wanted{false};
int page=0, cur_tab=0, width=1280;
int* size_edit=nullptr;
std::string size_text;
std::vector<int> mods_typed, size_typed;
std::mutex mods_typed_mu;
'''
lifecycle = source[source.index("bool ap_menu_editing()"):
                   source.index("void ap_menu_tick(")]
route = _edits_080()[14][1]
wanted = "int menu_text_wanted() { " + _edits_080()[12][1] + " }\n"
tuning = ("bool native_tuning(bool tune_mode, bool embed_open, bool row) { "
          + _edits_080()[-1][1] + " return tuning; }\n")
native_tabs = r'''
namespace native_tab_contract {
enum MenuTab {
    TAB_DISPLAY=0, TAB_GRAPHICS=1, TAB_AUDIO=2, TAB_CONTROLS=3, TAB_SYSTEM=4,
    TAB_ARCHIPELAGO=5, TAB_DEBUG=6, TAB_COUNT=7, TAB_MOTION=TAB_COUNT,
    TAB_PAGE=TAB_MOTION+1, TAB_N64=TAB_PAGE+1, TAB_SIM_TURF=TAB_N64+1,
    TAB_HIDDEN=TAB_SIM_TURF+1
};
'''
native_tabs += _edits_080()[3][1] + "\n"
native_tabs += next(after for before, after in _edits_080()
                    if before.startswith('static const char* const tabs[]')) + "\n"
native_tabs += r'''
static_assert(sizeof scrolled_to/sizeof scrolled_to[0]==TAB_SIM_TURF+1);
static_assert(sizeof tabs/sizeof tabs[0]==TAB_HIDDEN+1);
}
'''
routing_checks = r'''
int main() {
    // Every native bridge name follows the shifted enum, including the hidden
    // rows and the new upstream subpages. The AP insertion adds exactly a slot.
    using native_tab_contract::tabs;
    assert(std::string(tabs[native_tab_contract::TAB_ARCHIPELAGO])=="archipelago");
    assert(std::string(tabs[native_tab_contract::TAB_DEBUG])=="debug");
    assert(std::string(tabs[native_tab_contract::TAB_MOTION])=="motion");
    assert(std::string(tabs[native_tab_contract::TAB_PAGE])=="controls");
    assert(std::string(tabs[native_tab_contract::TAB_N64])=="graphics");
    assert(std::string(tabs[native_tab_contract::TAB_SIM_TURF])=="graphics");
    assert(std::string(tabs[native_tab_contract::TAB_HIDDEN])=="hidden");
    // Native width typing still receives the queue in order and retains its
    // editor, including the native 64-character buffering rule.
    size_text_wanted=true; size_edit=&width; size_text="12";
    size_typed={'3'}; mods_typed={'4','5'};
    route_text();
    assert(size_text_wanted && size_edit==&width && size_text=="12");
    assert((size_typed==std::vector<int>{'3','4','5'}));
    assert(mods_typed.empty() && menu_text_wanted()==1);
    size_typed.assign(64,'8'); mods_typed={'9'};
    route_text();
    assert(size_typed.size()==64 && mods_typed.empty());
    // Entering AP drops only the native dimension edit buffer. Subsequent AP
    // text is left for the AP editor, with no password copied into size_typed.
    cur_tab=TAB_ARCHIPELAGO; mods_typed={'0'};
    route_text();
    assert(!size_text_wanted && !size_edit && size_text.empty());
    assert(size_typed.empty() && mods_typed.empty() && menu_text_wanted()==0);
    ap_menu::begin(1);
    size_text_wanted=true; size_edit=&width; size_typed={'1'};
    mods_typed={'s','e','c','r','e','t'};
    route_text();
    assert(ap_menu::editing && ap_menu_editing() && menu_text_wanted()==1);
    assert((mods_typed==std::vector<int>{'s','e','c','r','e','t'}));
    assert(!size_text_wanted && !size_edit && size_typed.empty());
    // The native tuning bar is suppressed only on AP, whose rows have their
    // own renderer. Moving back to a host tab keeps its native mode intact.
    assert(!native_tuning(true,false,false));
    cur_tab=0;
    assert(native_tuning(true,false,false));
    assert(!native_tuning(true,true,false));
    // Closing cancels AP input and clears pending host text.
    open_now=false;
    route_text();
    assert(!ap_menu::editing && !ap_menu_editing());
    assert(ap_menu::password.empty() && mods_typed.empty());
    // Mods' search remains handled by the native Mods branch.
    open_now=true; page=kModsPage; mods_text_wanted=true;
    mods_typed={'f','i','n','d'};
    route_text();
    assert(mods_text_wanted && menu_text_wanted()==1);
    assert((mods_typed==std::vector<int>{'f','i','n','d'}));
    return 0;
}
'''
cpp = folder / "check_menu_input_080.cpp"
cpp.write_text(header + erase + editing + "\n}\n" + routing_header + lifecycle
               + "void route_text() {\n" + route + "\n}\n" + wanted + tuning
               + native_tabs + routing_checks, encoding="utf-8")
executable = folder / ("check_menu_input_080.exe" if os.name == "nt" else "check_menu_input_080")
subprocess.run([compiler, "-std=c++17", "-Wall", "-Werror", *runtime_flags,
                str(cpp), "-o", str(executable)], check=True)
subprocess.run([str(executable.resolve())], check=True)
print("PASS Triforce v0.8 input: native dimensions, Mods search, AP credentials, close and tuning-bar ownership.")
