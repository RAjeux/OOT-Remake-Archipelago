"""Compile the real restore scheduler against queued, bounded guest callbacks.

The model supplies explicit native results; no game, DLL or AP server is loaded.
The real player/title/loading/death gate is exercised by test_deathlink_host.py.
"""
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / "native/ootrr_archipelago.inc").read_text(encoding="utf-8")
tick = source[source.index("static void ap_tick16("):source.index("\n#else\n#define ap_boot16")]

header = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <limits.h>
typedef int Ctx;
enum { OOT_GAMEDATA_SLOT=20, OOT_EVENTMGR_SLOT=21, HOS_SHARE_NOTICE=10 };
static uint32_t ap_cursor16=33,ap_flags16[]={101,102,103};
static int ap_flag_count16=3,ap_event_mode16=1;
static uint64_t ap_delivery_actor16=77,ap_delivery_epoch16,manager=1;
static int ap_delivery_ready16=1;
static int active,save_exists,loading,event_exists,event_busy,ready,whitelist;
static int cursor,status,status_exists,queued_clear,clear_ok,request_ok;
static int clear_calls,restore_calls,restore_requests,remote_requests,request_attempts;
static int quiet_requests,replay_allowed,replay_calls;
static int deferred,last_deferred,acks,next_calls,network_item,want_second,unknown_snapshots;
static char flag_states[3];
static int64_t now=1000000000LL,deferred_until;
static uint64_t oot_singleton(Ctx*c,int slot){(void)c;return !active?0:slot==OOT_GAMEDATA_SLOT?manager:event_exists?500:0;}
static uint64_t oot_gd_int(Ctx*c,uint64_t mgr,uint32_t key){(void)c;assert(mgr==manager);return key==33?(save_exists?100:0):key==44?(status_exists?400:0):key==0x641e0375u?200:0;}
static int oot_gamedata_bool(Ctx*c,uint32_t key,int*v){(void)c;assert(key==0xef2b60c2u);*v=loading;return 1;}
static char oot_flag_state(Ctx*c,int loaded,uint32_t key){(void)c;assert(loaded&&key>=101&&key<=103);return flag_states[key-101];}
static uint32_t recomp_load32(Ctx*c,uint64_t ptr){(void)c;if(ptr==100+0x1c)return cursor;if(ptr==200+0x1c)return 0;if(ptr==400+0x1c)return (uint32_t)status;assert(0);return 0;}
static uint64_t recomp_load64(Ctx*c,uint64_t ptr){(void)c;assert(ptr==500+104);return event_busy;}
static uint32_t oot_murmur3(const char*s){assert(!strcmp(s,"Archipelago.RestoreResult"));return 44;}
static int oot_gd_set(Ctx*c,uint64_t mgr,uint32_t key,uint32_t value,int boolean){(void)c;assert(mgr==manager&&key==44&&value==0&&!boolean);clear_calls++;if(!clear_ok)return 0;queued_clear=0;return 1;}
static int ap_note16(char*s,int n){(void)s;(void)n;return 0;}
static void hos_save_share_say(int row,const char*s){(void)row;(void)s;assert(0);}
static void ap_opened16(uint32_t*flags,int count,int won){assert(!won);for(int i=0;i<count;i++)assert(flag_states[flags[i]-101]=='1');}
static int ap_next16(int index){assert(index==cursor);next_calls++;return network_item&&index==0?1000:0;}
static void ap_applied16(int index){assert(index==0&&cursor==1);acks++;}
static const char *ap_eventname16(int item){return item==1000?"OOTRR_APReceive_1000":NULL;}
static int (*ap_receipt_replay16)(int,int);
static int replay_api(int cursor_value,int item){assert(cursor_value==0&&item==1000);replay_calls++;return replay_allowed;}
static int restore_api(uint8_t*states,int count){
    restore_calls++;assert(count==3);
    for(int i=0;i<count;i++){
        const uint8_t expected=flag_states[i]=='0'||flag_states[i]=='1'?(uint8_t)flag_states[i]:255;
        assert(states[i]==expected);
        if(states[i]!='0'&&states[i]!='1'){unknown_snapshots++;return 0;}
    }
    if(!ready||!whitelist)return 0;
    if(flag_states[0]=='0'&&now>=deferred_until)return 501;
    if(want_second&&flag_states[1]=='0')return 502;
    return 0;
}
static void defer_api(int id){assert(id==501||id==502);deferred++;last_deferred=id;if(id==501)deferred_until=now+2000000000LL;}
static int (*ap_restore16)(uint8_t*,int)=restore_api;
static void (*ap_restore_deferred16)(int)=defer_api;
static int ap_request_item16(Ctx*c,uint64_t actor,const char*name){
    (void)c;assert(actor==77);request_attempts++;
    if(event_busy||!event_exists||!request_ok)return 0;
    if(!strcmp(name,"OOTRR_APReceive_1000")){remote_requests++;return 1;}
    if(!strcmp(name,"OOTRR_APTradeReplay_1000")){quiet_requests++;return 1;}
    assert(!strcmp(name,"OOTRR_APRestore_501")||!strcmp(name,"OOTRR_APRestore_502"));
    restore_requests++;return 1;
}
#define AP_RUPEE_ID 1001
static const char *ap_item_name16(int item){(void)item;assert(0);return NULL;}
static int oot_item_get(Ctx*c,const char*s){(void)c;(void)s;assert(0);return 0;}
static int oot_item_give(Ctx*c,const char*s,int n){(void)c;(void)s;(void)n;assert(0);return 0;}
static int oot_capacity(Ctx*c,uint64_t mgr,const char*s,int*n){(void)c;(void)mgr;(void)s;(void)n;assert(0);return 0;}
static void reset(void){
    manager++;ap_delivery_epoch16++;ap_delivery_actor16=77;ap_cursor16=33;ap_event_mode16=1;
    ap_delivery_ready16=1;
    active=save_exists=event_exists=ready=whitelist=status_exists=clear_ok=request_ok=1;
    loading=event_busy=cursor=status=0;queued_clear=INT_MIN;deferred_until=0;
    clear_calls=restore_calls=restore_requests=remote_requests=request_attempts=deferred=last_deferred=acks=next_calls=network_item=want_second=unknown_snapshots=0;
    quiet_requests=replay_allowed=replay_calls=0;ap_receipt_replay16=NULL;
    memcpy(flag_states,"000",3);now+=61000000000LL;
}
static void commit_clear(void){assert(queued_clear==0);status=queued_clear;queued_clear=INT_MIN;}
static void tick(Ctx*c){now+=400000000LL;ap_tick16(c,now);}
'''

checks = r'''
int main(void){
    Ctx c=0;
    reset();network_item=1;ap_receipt_replay16=replay_api;replay_allowed=1;
    tick(&c);assert(quiet_requests==1&&remote_requests==0&&restore_requests==0&&replay_calls==1&&cursor==0&&!acks);
    now+=61000000000LL;tick(&c);assert(quiet_requests==1&&replay_calls==1&&!restore_requests);
    cursor=1;tick(&c);assert(acks==1&&restore_requests==1&&cursor==1);
    assert(!memcmp(flag_states,"000",3)); /* Quiet receipt leaves missing check/reward recoverable. */
    reset();network_item=1;ap_receipt_replay16=replay_api;
    tick(&c);assert(quiet_requests==0&&remote_requests==1&&replay_calls==1);
    reset();network_item=1;ap_receipt_replay16=replay_api;replay_allowed=1;flag_states[2]='?';
    tick(&c);assert(quiet_requests==0&&remote_requests==1&&replay_calls==0);
    reset();whitelist=0;status_exists=0;tick(&c);
    assert(!restore_requests&&!clear_calls);
    network_item=1;tick(&c);assert(remote_requests==1&&!restore_requests);

    reset();ap_cursor16=0;tick(&c);assert(!restore_calls);
    ap_cursor16=33;active=0;tick(&c);assert(!restore_calls);
    active=1;save_exists=0;tick(&c);assert(!restore_calls);
    save_exists=1;loading=1;tick(&c);assert(!restore_calls);
    loading=0;ap_delivery_actor16=0;tick(&c);assert(!restore_calls);
    ap_delivery_actor16=77;event_busy=1;tick(&c);assert(!restore_calls&&!clear_calls);
    event_busy=0;event_exists=0;tick(&c);assert(!restore_calls);
    event_exists=1;ready=0;tick(&c);assert(!restore_requests&&!clear_calls);
    ready=1;flag_states[2]='-';tick(&c);assert(unknown_snapshots==1&&!restore_requests&&!clear_calls);
    flag_states[2]='?';tick(&c);assert(unknown_snapshots==2&&!restore_requests&&!clear_calls);
    flag_states[2]='0';status_exists=0;tick(&c);assert(!restore_requests&&!clear_calls);

    /* ReceivedItems replay runs first, with its existing committed cursor. */
    reset();network_item=1;ap_delivery_ready16=0;
    tick(&c);assert(!next_calls&&!remote_requests&&!restore_calls&&!request_attempts&&cursor==0&&!acks);
    ap_delivery_ready16=1;tick(&c);assert(remote_requests==1&&cursor==0&&!acks);
    ap_delivery_ready16=0;cursor=1;tick(&c);
    assert(acks==1&&!restore_calls&&!restore_requests); /* commit ACK stays observable while busy */
    ap_delivery_ready16=1;tick(&c);assert(restore_requests==1&&acks==1&&cursor==1);
    reset();ap_delivery_ready16=0;tick(&c);assert(!restore_calls&&!clear_calls&&!request_attempts);
    ap_delivery_ready16=1;tick(&c);assert(restore_requests==1&&!acks&&cursor==0);
    ap_delivery_ready16=0;now+=61000000000LL;tick(&c);
    assert(restore_requests==1&&!remote_requests); /* accepted transaction stays pending */
    ap_delivery_ready16=1;tick(&c);assert(restore_requests==1);

    /* ReceivedItems replay runs first, with its existing committed cursor. */
    reset();network_item=1;tick(&c);assert(remote_requests==1&&!restore_calls&&!restore_requests);
    now+=61000000000LL;tick(&c);assert(remote_requests==1&&!restore_requests);
    cursor=1;tick(&c);assert(acks==1&&restore_requests==1&&cursor==1);
    flag_states[0]='1';status=501;tick(&c);assert(restore_requests==1&&cursor==1&&acks==1);

    /* An accepted restore blocks another event until its explicit result.
       Even an idle manager, a long pause and a newly received item do not retry. */
    reset();tick(&c);assert(restore_requests==1&&clear_calls==1);commit_clear();
    const int calls=next_calls;now+=3600000000000LL;tick(&c);
    assert(restore_requests==1&&next_calls==calls);
    network_item=1;tick(&c);assert(!remote_requests&&restore_requests==1);
    status=502;tick(&c);assert(!remote_requests&&!deferred&&restore_requests==1);
    status=-502;tick(&c);assert(!remote_requests&&!deferred&&restore_requests==1);
    status=-501;tick(&c);assert(deferred==1&&last_deferred==501&&remote_requests==1&&cursor==0);

    /* A negative refill result permits other locations, then a later retry. */
    reset();want_second=1;tick(&c);assert(restore_requests==1);
    status=-501;tick(&c);assert(deferred==1&&restore_requests==1&&queued_clear==0);
    commit_clear();tick(&c);assert(restore_requests==2&&now<deferred_until);
    flag_states[1]='1';status=502;tick(&c);assert(restore_requests==2&&deferred==1);
    now=deferred_until+1;tick(&c);assert(restore_requests==2&&queued_clear==0);
    commit_clear();tick(&c);assert(restore_requests==3);
    flag_states[0]='1';status=501;tick(&c);assert(restore_requests==3&&cursor==0&&!acks);

    /* An old +sameID must be visibly cleared before reusing the result field. */
    reset();status=501;tick(&c);assert(!restore_requests&&clear_calls==1&&queued_clear==0);
    now+=61000000000LL;tick(&c);assert(!restore_requests&&clear_calls==1);
    commit_clear();tick(&c);assert(restore_requests==1);
    flag_states[0]='1';status=501;tick(&c);assert(restore_requests==1);

    reset();clear_ok=0;tick(&c);assert(!request_attempts&&!restore_requests);
    clear_ok=1;request_ok=0;tick(&c);assert(request_attempts==1&&!restore_requests);
    request_ok=1;tick(&c);assert(restore_requests==1);
    tick(&c);assert(restore_requests==1);

    /* Only a real manager/gameplay epoch change invalidates an accepted job. */
    reset();tick(&c);assert(restore_requests==1);
    manager++;tick(&c);assert(restore_requests==2);
    ap_delivery_epoch16++;tick(&c);assert(restore_requests==3);
    loading=1;ap_delivery_actor16=0;ap_delivery_epoch16++;tick(&c);assert(restore_requests==3);
    loading=0;tick(&c);assert(restore_requests==3);
    ap_delivery_actor16=77;tick(&c);assert(restore_requests==4);
    ap_delivery_actor16=0;ap_delivery_epoch16++;tick(&c);assert(restore_requests==4);
    ap_delivery_actor16=77;tick(&c);assert(restore_requests==5&&cursor==0&&!acks);
    return 0;
}
'''

home = ROOT / "build/tests"
home.mkdir(parents=True, exist_ok=True)
path = home / "check_restore_tick.c"
# tick() is below the actual function so its prototype is visible in C11.
header, wrapper = header.split("static void tick(Ctx*c)", 1)
path.write_text(header + tick + "\nstatic void tick(Ctx*c)" + wrapper + checks, encoding="utf-8")
exe = path.with_suffix(".exe" if os.name == "nt" else "")
subprocess.run([os.environ.get("CC") or shutil.which("gcc") or "clang", "-std=c11", "-Wall", "-Werror",
                str(path), "-o", str(exe)], check=True)
subprocess.run([str(exe)], check=True)
print("PASS actual restore scheduler: remote priority, exact result/epoch gating, no timeout retry, queued status clear, explicit refill deferral, subsequent checks, committed flags, no AP cursor change, legacy and unloaded-state guards.")
