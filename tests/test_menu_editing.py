"""Run the actual C++ editor transitions without the renderer or game assets."""
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
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
