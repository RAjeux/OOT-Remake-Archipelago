"""Compile the real Options-menu bridge and check its bounded DLL dispatch."""
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / "native/ootrr_archipelago.inc").read_text(encoding="utf-8")
bridge = source[source.index("__declspec(dllexport) int ootrr_ap_menu16("):
                source.index("/* Only the packaged AP DLL")]
header = r'''
#include <assert.h>
#include <string.h>
#ifndef _WIN32
#define __declspec(x)
#endif
static int (*ap_connection_info16)(char *,int);
static int (*ap_connect16)(char *,char *,int,int);
static int (*ap_disconnect16)(void);
static int reads, connects, disconnects, answer=1;
static int info(char *out,int cap) {
    ++reads;
    const char text[]="{\"state\":\"connected\",\"has_password\":true}";
    if (!out || cap<(int)sizeof text) return 0;
    memcpy(out,text,sizeof text);
    return sizeof text-1;
}
static int connect_now(char *server,char *password,int mode,int automatic) {
    assert(!strcmp(server,"127.0.0.1:38281"));
    assert(!strcmp(password,"private test password"));
    assert(mode==1 && automatic==0);
    ++connects;
    return answer;
}
static int disconnect_now(void) { ++disconnects; return 1; }
'''
checks = r'''
int main(void) {
    char out[256]="stale state";
    assert(ootrr_ap_menu16(0,0,0,0,0,out,sizeof out)==0 && !out[0]);
    assert(!reads && !connects && !disconnects);
    ap_connection_info16=info;
    ap_connect16=connect_now;
    ap_disconnect16=disconnect_now;
    assert(ootrr_ap_menu16(0,0,0,0,0,out,sizeof out)>0);
    assert(reads==1 && !connects && !disconnects);
    assert(!strstr(out,"private test password"));
    for (answer=1;answer>=-4;--answer) {
        assert(ootrr_ap_menu16(1,"127.0.0.1:38281","private test password",1,0,out,sizeof out)==answer);
        assert(out[0] && !strstr(out,"private test password"));
    }
    assert(connects==6 && !disconnects);
    assert(ootrr_ap_menu16(2,0,0,0,0,out,sizeof out)==1 && disconnects==1);
    assert(ootrr_ap_menu16(8,0,0,0,0,out,sizeof out)==-2 && !out[0]);
    assert(ootrr_ap_menu16(1,0,"",0,0,out,sizeof out)==-2);
    assert(ootrr_ap_menu16(1,"",0,0,0,out,sizeof out)==-2);
    assert(connects==6 && disconnects==1);
    assert(ootrr_ap_menu16(0,0,0,0,0,0,0)==0);
    char short_buffer[3]={'x','x','x'};
    assert(ootrr_ap_menu16(0,0,0,0,0,short_buffer,2)==0);
    assert(short_buffer[0]==0 && short_buffer[2]=='x');
    return 0;
}
'''
folder = ROOT / "build/tests"
folder.mkdir(parents=True, exist_ok=True)
c_file = folder / "check_menu_bridge.c"
c_file.write_text(header + bridge + checks, encoding="utf-8")
executable = folder / ("check_menu_bridge.exe" if os.name == "nt" else "check_menu_bridge")
compiler = os.environ.get("CC") or shutil.which("gcc") or "clang"
subprocess.run([compiler, "-std=c11", "-Wall", "-Werror", str(c_file), "-o", str(executable)], check=True)
subprocess.run([str(executable.resolve())], check=True)
print("PASS Options bridge: inactive mod, bounded snapshots, connect/disconnect dispatch, errors, no password disclosure.")
