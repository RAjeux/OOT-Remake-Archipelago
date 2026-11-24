"""Compile the actual DeathLink host helper against bounded synthetic guest memory."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

from support import triforce_root


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from ootrr_triforce.native_setup import patch_source


def check_source_upgrade():
    original = (triforce_root() / "host/hos_main.c").read_bytes()
    old_hook = "    oot_inventory_refresh(c, now);\n    ap_tick16(c, now);"
    new_hook = "    oot_inventory_refresh(c, now);\n    if (ap_player16(c, actor, components, now)) ap_tick16(c, now);"
    # Start from the upstream source even when TRIFORCE_SOURCE is already patched.
    text = original.decode("utf-8").replace("\r\n", "\n")
    if "ap_boot16(" in text:
        pristine = sorted((triforce_root() / "host").glob("hos_main.before-archipelago-*.bak"))
        assert pristine, "Use upstream sources or retain the installer's source backup."
        text = pristine[0].read_text(encoding="utf-8")
    for newline in ("\n", "\r\n"):
        raw = text.replace("\n", newline).encode("utf-8")
        current = patch_source(raw)
        normalized = current.decode("utf-8").replace("\r\n", "\n")
        assert normalized.count(new_hook) == 1
        assert normalized.count('#include "ootrr_archipelago.inc"') == 1
        assert normalized.count("if (!ap_boot16())") == 1
        assert patch_source(current) == current
        previous = normalized.replace(new_hook, old_hook).replace("\n", newline).encode("utf-8")
        assert patch_source(previous) == current
        assert patch_source(patch_source(previous)) == current
        partial = normalized.replace(new_hook, old_hook + "\n    ap_tick16(c, now);")
        try:
            patch_source(partial.replace("\n", newline).encode("utf-8"))
        except ValueError:
            pass
        else:
            raise AssertionError("An ambiguous previous hook must not be upgraded.")
    print("PASS source hook: fresh install, exact previous-hook migration, LF/CRLF, idempotence and ambiguous-hook rejection.")


source = (ROOT / "native/ootrr_archipelago.inc").read_text(encoding="utf-8")
helper = source[source.index("static void ap_invalidate_delivery16("):source.index("static void ap_tick16(")]
header = r'''
#include <stdint.h>
#include <string.h>
#include <assert.h>
#include <stdarg.h>
#include <stddef.h>

typedef int Ctx;
enum { OOT_GAMEDATA_SLOT = 20, OOT_EVENTMGR_SLOT = 21 };
static uint64_t core[1024], components_memory[128], controller_memory[64], action_memory[16], actor_memory, event_manager[16];
static uint64_t player_manager[256], player_table[16], player_entries[48], player_extension[512];
static struct Life { uint64_t type; int32_t current; uint32_t hash; } life, max_life;
static int manager_exists, save_exists, pouch_count, loading, valid_core, paused, pause_known;
static int remote_pending, states[32], state_count, gd_count, marks, log_count;
static int model_death_state, model_outgoing_deaths, model_remote_suppress;
static uint32_t gd_hash, gd_value;
static uint64_t marked_address;
static int ap_cursor16;
static uint32_t ap_seed_marker16;
static int seed_known, seed_matches;
static uint64_t ap_delivery_actor16;
static uint64_t ap_delivery_epoch16;
static uint64_t ap_delivery_mgr16, ap_delivery_core16, ap_delivery_life16;
static int ap_delivery_ready16;
static const char *const oot_item_names[] = {"Item_Test"};

static int contains(const void *base, size_t size, uint64_t address, size_t length) {
    const uintptr_t start = (uintptr_t)base;
    return length <= size && address >= start && address - start <= size - length;
}
static void *guest_pointer(uint64_t address, size_t length) {
    assert(contains(core, sizeof core, address, length) ||
           contains(components_memory, sizeof components_memory, address, length) ||
           contains(controller_memory, sizeof controller_memory, address, length) ||
           contains(action_memory, sizeof action_memory, address, length) ||
           contains(event_manager, sizeof event_manager, address, length) ||
           contains(player_manager, sizeof player_manager, address, length) ||
           contains(player_table, sizeof player_table, address, length) ||
           contains(player_entries, sizeof player_entries, address, length) ||
           contains(player_extension, sizeof player_extension, address, length) ||
           contains(&life, sizeof life, address, length) ||
           contains(&max_life, sizeof max_life, address, length));
    return (void *)(uintptr_t)address;
}
#define A64_PTR(address) guest_pointer((address), 4)
#define A64_MARK(address, length) mark_write((address), (length))
static void mark_write(uint64_t address, size_t length) {
    assert(address == (uintptr_t)&life.current && length == 4);
    marked_address = address;
    marks++;
}
static uint64_t recomp_load64(Ctx *c, uint64_t address) {
    uint64_t value; (void)c;
    memcpy(&value, guest_pointer(address, sizeof value), sizeof value);
    return value;
}
static uint32_t recomp_load32(Ctx *c, uint64_t address) {
    uint32_t value; (void)c;
    memcpy(&value, guest_pointer(address, sizeof value), sizeof value);
    return value;
}
static uint64_t oot_singleton(Ctx *c, uint64_t slot) {
    (void)c;
    if (slot == 0x84c9e178ULL) return (uintptr_t)player_manager;
    if (slot == OOT_EVENTMGR_SLOT) return (uintptr_t)event_manager;
    assert(slot == OOT_GAMEDATA_SLOT);
    return manager_exists ? 123 : 0;
}
static uint64_t oot_gd_int(Ctx *c, uint64_t mgr, uint32_t hash) {
    (void)c; assert(mgr == 123 && hash == (uint32_t)ap_cursor16);
    return save_exists ? 456 : 0;
}
static int oot_pouch_count(Ctx *c, const char *name) {
    (void)c; assert(!strcmp(name, "Item_Test")); return pouch_count;
}
static int oot_gamedata_bool(Ctx *c, uint32_t hash, int *value) {
    (void)c;
    if (hash == 0xef2b60c2u) { *value = loading; return 1; }
    if (hash == 0x1234abcd) { *value = seed_matches; return seed_known; }
    assert(hash == 0x604aebe1u); *value = paused; return pause_known;
}
static int hos_oot_is_player(Ctx *c, uint64_t address) {
    (void)c; return valid_core && address == (uintptr_t)core;
}
static int oot_gd_set(Ctx *c, uint64_t mgr, uint32_t hash, uint32_t value, int boolean) {
    (void)c; assert(mgr == 123 && !boolean);
    gd_count++; gd_hash = hash; gd_value = value;
    return 1;
}
static void hos_log(const char *format, ...) { (void)format; log_count++; }
static int death_api(int state) {
    assert(state_count < 32 && state >= -1 && state <= 2);
    states[state_count++] = state;
    const int previous=model_death_state;
    model_death_state=state;
    if (state==-1) { remote_pending=0;model_remote_suppress=0; }
    if (state==1) {
        if ((previous==0 || previous==2) && !model_remote_suppress) model_outgoing_deaths++;
        remote_pending=0;model_remote_suppress=0;
    }
    if (state == 0 && remote_pending) { remote_pending = 0;model_remote_suppress=1; return 1; }
    return 0;
}
static int (*ap_death16)(int) = death_api;

static void reset(void) {
    memset(core, 0, sizeof core);
    memset(components_memory, 0, sizeof components_memory);
    memset(controller_memory, 0, sizeof controller_memory);
    memset(action_memory, 0, sizeof action_memory);
    memset(event_manager, 0, sizeof event_manager);
    memset(player_manager, 0, sizeof player_manager);
    memset(player_table, 0, sizeof player_table);
    memset(player_entries, 0, sizeof player_entries);
    memset(player_extension, 0, sizeof player_extension);
    player_manager[0] = 0x84c89f98ULL;
    player_manager[0x1f0 / 8] = (uintptr_t)player_table;
    player_table[0x50 / 8] = 41;
    player_table[0x58 / 8] = (uintptr_t)player_entries;
    player_entries[0x110 / 8] = (uintptr_t)player_extension;
    player_extension[0] = 0x84bc16e0ULL;
    life = (struct Life){0x84b83438ULL, 12, 0x31ab5580u};
    max_life = (struct Life){0x84b83438ULL, 20, 0xfbe01da1u};
    core[7184 / 8] = (uintptr_t)&life;
    core[7192 / 8] = (uintptr_t)&max_life;
    components_memory[800 / 8] = (uintptr_t)core + 0x1d50;
    components_memory[0x188 / 8] = (uintptr_t)controller_memory;
    controller_memory[0x1c0 / 8] = (uintptr_t)action_memory;
    action_memory[0x28 / 8] = 0x28; /* native Wait */
    manager_exists = save_exists = valid_core = 1;
    pause_known = 1; paused = 0;
    pouch_count = loading = remote_pending = state_count = gd_count = marks = log_count = 0;
    gd_hash = gd_value = 0xffffffffu; marked_address = 0;
    ap_cursor16 = 33; ap_death16 = death_api;
    ap_seed_marker16 = 0; seed_known = seed_matches = 1;
    ap_delivery_actor16 = ap_delivery_epoch16 = 0;
    ap_delivery_mgr16 = ap_delivery_core16 = ap_delivery_life16 = 0;
    ap_delivery_ready16 = 0;
    model_death_state=-1;model_outgoing_deaths=model_remote_suppress=0;
}
'''
checks = r'''
static void blocked(Ctx *c, uint64_t actor, uint64_t components) {
    uint64_t before_core[1024], before_components[128];
    struct Life before_life = life, before_max = max_life;
    memcpy(before_core, core, sizeof core);
    memcpy(before_components, components_memory, sizeof components_memory);
    assert(!ap_player16(c, actor, components, 1000000000));
    assert(!ap_delivery_actor16);
    assert(!memcmp(before_core, core, sizeof core));
    assert(!memcmp(before_components, components_memory, sizeof components_memory));
    assert(!memcmp(&before_life, &life, sizeof life));
    assert(!memcmp(&before_max, &max_life, sizeof max_life));
    assert(!gd_count && !marks && !log_count);
    if (ap_cursor16 && ap_death16) assert(state_count == 1 && states[0] == -1);
    else assert(!state_count);
}
int main(void) {
    Ctx c = 0;
    const uint64_t actor = (uintptr_t)&actor_memory, components = (uintptr_t)components_memory;
    reset(); ap_cursor16 = 0; blocked(&c, actor, components);
    reset(); ap_death16 = NULL; blocked(&c, actor, components);
    reset(); blocked(&c, 0, components);
    reset(); blocked(&c, actor, 0);
    reset(); manager_exists = 0; blocked(&c, actor, components);
    reset(); save_exists = 0; blocked(&c, actor, components);
    reset(); pouch_count = -1; blocked(&c, actor, components);
    reset(); loading = 1; blocked(&c, actor, components);
    reset(); components_memory[800 / 8] = 0x1d4f; blocked(&c, actor, components);
    reset(); valid_core = 0; blocked(&c, actor, components);
    reset(); core[7184 / 8] = 0; blocked(&c, actor, components);
    reset(); life.type = 0x12345678; blocked(&c, actor, components);
    reset(); ap_seed_marker16=0x1234abcd; seed_known=0; blocked(&c,actor,components);
    reset(); ap_seed_marker16=0x1234abcd; seed_matches=0; blocked(&c,actor,components);
    reset(); ap_seed_marker16=0x1234abcd;
    assert(ap_player16(&c,actor,components,1000000000));
    assert(ap_delivery_ready16 && states[0]==0);

    reset();
    assert(ap_player16(&c, actor, components, 1000000000));
    assert(ap_delivery_actor16 == actor);
    assert(ap_delivery_ready16);
    assert(state_count == 1 && states[0] == 0);
    assert(life.current == 12 && max_life.current == 20 && !gd_count && !marks);
    loading = 1;
    assert(!ap_player16(&c, actor, components, 1010000000));
    assert(ap_delivery_epoch16 == 1 && !ap_delivery_actor16);
    assert(!ap_player16(&c, actor, components, 1020000000));
    assert(ap_delivery_epoch16 == 1); /* one invalidation, not one per loading tick */
    loading = 0; state_count = 1;
    assert(ap_player16(&c, actor, components, 1030000000));
    assert(ap_delivery_epoch16 == 1 && ap_delivery_actor16 == actor);
    state_count = 1;
    life.current = 0;
    assert(!ap_player16(&c, actor, components, 1100000000));
    assert(state_count == 2 && states[1] == 1);
    assert(ap_delivery_epoch16 == 2 && !ap_delivery_actor16);
    assert(!gd_count && !marks && max_life.current == 20);
    life.current = -1;
    assert(!ap_player16(&c, actor, components, 1200000000));
    assert(states[2] == 1 && !gd_count && !marks);

    reset(); life.type = 0x84b6c400ULL; life.hash = 0;
    assert(ap_player16(&c, actor, components, 1000000000));
    assert(state_count == 1 && states[0] == 0 && !gd_count && !marks);

    reset(); remote_pending = 1;
    event_manager[104 / 8] = 1;
    assert(ap_player16(&c, actor, components, 900000000));
    assert(!ap_delivery_ready16);
    assert(state_count == 1 && states[0] == 2 && remote_pending);
    assert(life.current == 12 && !gd_count && !marks && !log_count);
    assert(ap_player16(&c, actor, components, 950000000));
    assert(state_count == 2 && states[1] == 2 && remote_pending);
    event_manager[104 / 8] = 0; state_count = 0;
    assert(!ap_player16(&c, actor, components, 1000000000));
    assert(life.current == 0 && life.hash == 0x31ab5580u && max_life.current == 20);
    assert(core[7184 / 8] == (uintptr_t)&life && core[7192 / 8] == (uintptr_t)&max_life);
    assert(gd_count == 1 && gd_hash == 0x31ab5580u && gd_value == 0);
    assert(marks == 1 && marked_address == (uintptr_t)&life.current && log_count == 1);
    /* The host reports state 1 immediately after receiving a remote death.
       The DLL owns suppression of this acknowledgement's network echo. */
    assert(state_count == 2 && states[0] == 0 && states[1] == 1 && !remote_pending);
    assert(!ap_player16(&c, actor, components, 1100000000));
    assert(state_count == 3 && states[2] == 1 && gd_count == 1 && marks == 1);

    /* Every constrained verb is deferred, not only the reported crawl/fishing.
       Keep the live context/epoch: a pause must not retry an accepted receipt. */
    for (unsigned verb=0;verb<0x130;verb++) {
        reset();
        action_memory[0x28 / 8] = verb;
        const int safe=verb==1||verb==2||verb==3||verb==4||verb==0x15||verb==0x16||
                       verb==0x28||verb==0x41||verb==0x42||verb==0xd1;
        assert(ap_player16(&c,actor,components,1000000000));
        assert(ap_delivery_ready16==safe && states[0]==(safe?0:2));
        assert(ap_delivery_actor16==actor && !ap_delivery_epoch16 && !gd_count && !marks);
    }
    reset();
    assert(ap_player16(&c,actor,components,1000000000));
    paused=1; remote_pending=1;
    assert(ap_player16(&c,actor,components,1100000000));
    assert(!ap_delivery_ready16 && states[1]==2 && remote_pending && !ap_delivery_epoch16);
    paused=0;
    assert(!ap_player16(&c,actor,components,5000000000));
    assert(!remote_pending && life.current==0 && gd_count==1);
    reset(); pause_known=0;
    assert(ap_player16(&c,actor,components,1000000000) && !ap_delivery_ready16 && states[0]==2);
    reset(); components_memory[0x188 / 8]=0;
    assert(ap_player16(&c,actor,components,1000000000) && !ap_delivery_ready16 && states[0]==2);
    reset(); controller_memory[0x1c0 / 8]=0;
    assert(ap_player16(&c,actor,components,1000000000) && !ap_delivery_ready16 && states[0]==2);
    reset(); player_extension[0xa38 / 8]=0x400; /* rod drawn even between casts */
    assert(ap_player16(&c,actor,components,1000000000) && !ap_delivery_ready16 && states[0]==2);
    reset(); core[0xa38 / 8]=0x400; /* movement/life core is not the fishing extension */
    assert(ap_player16(&c,actor,components,1000000000) && ap_delivery_ready16 && states[0]==0);
    reset(); player_extension[0]=0;
    assert(ap_player16(&c,actor,components,1000000000) && !ap_delivery_ready16 && states[0]==2);
    reset(); player_table[0x50 / 8]=0x22;
    assert(ap_player16(&c,actor,components,1000000000) && !ap_delivery_ready16 && states[0]==2);
    reset(); action_memory[0x28 / 8]=0x11a;
    ((uint32_t*)action_memory)[0x4c / 4]=0x28;
    assert(ap_player16(&c,actor,components,1000000000) && ap_delivery_ready16 && states[0]==0);
    ((uint32_t*)action_memory)[0x4c / 4]=0xea;
    assert(ap_player16(&c,actor,components,1100000000) && !ap_delivery_ready16 && states[1]==2);

    reset();
    assert(ap_player16(&c,actor,components,1000000000));
    assert(ap_player16(&c,actor+8,components,1100000000));
    assert(states[1]==-1 && states[2]==0 && ap_delivery_epoch16==1 && ap_delivery_actor16==actor+8);
    for (int identity=0;identity<3;identity++) {
        reset();
        assert(ap_player16(&c,actor,components,1000000000));
        if(identity==0) ap_delivery_mgr16++;
        if(identity==1) ap_delivery_core16++;
        if(identity==2) ap_delivery_life16++;
        assert(ap_player16(&c,actor,components,1100000000));
        assert(states[1]==-1 && states[2]==0 && ap_delivery_epoch16==1);
        assert(ap_delivery_mgr16==123 && ap_delivery_core16==(uintptr_t)core && ap_delivery_life16==(uintptr_t)&life);
    }
    /* An already-dead replacement context must invalidate the old held life
       before reporting dead. Otherwise state2 -> state1 sends a false death. */
    for (int identity=0;identity<4;identity++) {
        reset(); action_memory[0x28 / 8]=0xea;
        assert(ap_player16(&c,actor,components,1000000000));
        assert(states[0]==2 && model_death_state==2);
        remote_pending=1;
        if(identity==0) ap_delivery_mgr16++;
        if(identity==1) ap_delivery_core16++;
        if(identity==2) ap_delivery_life16++;
        life.current=0;
        assert(!ap_player16(&c,identity==3?actor+8:actor,components,1100000000));
        assert(state_count==3 && states[1]==-1 && states[2]==1);
        assert(!remote_pending && !model_outgoing_deaths && !gd_count && !marks);
    }
    return 0;
}
'''

check_source_upgrade()
home = ROOT / "build/tests"
home.mkdir(parents=True, exist_ok=True)
c_file = home / "check_deathlink_host.c"
c_file.write_text(header + helper + checks, encoding="utf-8")
executable = home / ("check_deathlink_host.exe" if os.name == "nt" else "check_deathlink_host")
compiler = os.environ.get("CC") or shutil.which("gcc") or "clang"
subprocess.run([compiler, "-std=c11", "-Wall", "-Werror", str(c_file), "-o", str(executable)], check=True)
subprocess.run([str(executable)], check=True)
print("PASS actual host helpers: title/save/loading/type/context guards; native action whitelist, pause/unknown/fishing/crawl/animation deferral; no temporary-state epoch reset; atomic remote life zero, MaxLife preservation and acknowledgement.")
