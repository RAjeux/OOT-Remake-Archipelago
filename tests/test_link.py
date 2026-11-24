import os,shutil
from pathlib import Path
import subprocess
home=Path("build/tests")
home.mkdir(parents=True,exist_ok=True)
src=Path("native/ootrr_archipelago.inc").read_text()
tick=src[src.index("static void ap_tick16("):src.index("\n#else\n#define ap_boot16")]
header='''
#include <stdint.h>
#include <string.h>
#include <assert.h>
#include <stdio.h>
typedef int Ctx;
static int active, loading, save_exists, owned, cursor, coins, reward_request, pending_index, queued_balance, won, opened, notice, ack;
static int ap_event_mode16, ap_delivery_ready16=1, event_busy, event_accept=1, receipt_requests, last_receipt;
static int (*ap_restore16)(uint8_t *,int);
static void (*ap_restore_deferred16)(int);
static uint64_t ap_delivery_actor16=77;
static uint64_t ap_delivery_epoch16;
static int ap_cursor16=33, ap_flag_count16=2, ap_flags16[]={101,102};
enum {HOS_SHARE_NOTICE=10,OOT_GAMEDATA_SLOT=20,OOT_EVENTMGR_SLOT=21};
static int ap_note16(char *text,int cap){if(!notice)return 0;snprintf(text,cap,"note");notice=0;return 1;}
void hos_save_share_say(int row,const char *text){assert(row==10&&!strcmp(text,"note"));}
static uint64_t oot_singleton(Ctx *ctx,int k){return !active?0:k==OOT_EVENTMGR_SLOT?400:1;}
static uint64_t oot_gd_int(Ctx *ctx,uint64_t mgr,uint32_t key){if(!mgr)return 0;if(key==33)return save_exists?100:0;if(key==0x641e0375u)return 200;if(key==0xa77921d7u)return 300;return 0;}
static int oot_gamedata_bool(Ctx *c,uint32_t h,int *v){*v=loading;return 1;}
static char oot_flag_state(Ctx *c,int loaded,uint32_t h){return h==102?'1':'0';}
static uint32_t recomp_load32(Ctx *c,uint64_t ptr){if(ptr==100+0x1c)return cursor;if(ptr==200+0x1c)return won;if(ptr==300+0x1c)return coins;assert(0);return 0;}
static uint64_t recomp_load64(Ctx *c,uint64_t ptr){assert(ptr==400+104);return event_busy;}
static uint32_t oot_murmur3(const char *name){assert(!strcmp(name,"Archipelago.RestoreResult"));return 44;}
static void ap_opened16(uint32_t *f,int n,int goal){assert(n==1&&f[0]==102&&goal==won);opened++;}
static int ap_next16(int i){return reward_request==2?(i>=2&&i<=7?1998+i:i==8?9999:0):!reward_request?0:i==0?1000:i==1?1001:0;}
static const char *ap_eventname16(int id){static const char *names[]={"OOTRR_APReceive_Token","OOTRR_APReceive_HeartPiece","OOTRR_APReceive_Bundle","OOTRR_APReceive_Map","OOTRR_APReceive_Progressive","OOTRR_APReceive_SmallKey"};return id>=2000&&id<=2005?names[id-2000]:NULL;}
static int (*ap_receipt_replay16)(int,int);
static int ap_request_item16(Ctx *c,uint64_t actor,const char *name){assert(actor==77);if(event_busy||!event_accept)return 0;receipt_requests++;for(int id=2000;id<=2005;id++)if(!strcmp(name,ap_eventname16(id)))last_receipt=id;return 1;}
#define AP_RUPEE_ID 1001
static const char *ap_item_name16(int id){return id==1000?"Shield":NULL;}
static int oot_item_get(Ctx *c,const char *n){return owned;}
static int oot_item_give(Ctx *c,const char *n,int amount){assert(!strcmp("Shield",n)&&amount==1);owned=1;return 1;}
static int oot_capacity(Ctx *c,uint64_t mgr,const char *name,int *v){*v=99;return 1;}
static int oot_gd_set(Ctx *c,int mgr,uint32_t key,uint32_t val,int f){if(key==33)pending_index=val;else if(key==0xa77921d7u){assert(queued_balance<0);queued_balance=val;}else assert(0);return 1;}
static void ap_applied16(int i){assert(i==ack++);}
'''
test='''
int main(void){
    Ctx ctx=0;int64_t t=1000000000LL;
    pending_index=queued_balance=-1;
#define TICK ap_tick16(&ctx,t+=400000000LL)
    TICK;active=1;TICK;assert(!opened);
    save_exists=1;loading=1;TICK;assert(!opened);
    loading=0;TICK;assert(opened==1&&!owned);
    reward_request=1;TICK;assert(owned&&pending_index==1);
    TICK;assert(!ack&&pending_index==1);
    cursor=pending_index;coins=97;TICK;assert(ack==1&&pending_index==2&&queued_balance==99);
    TICK;assert(queued_balance==99&&ack==1);
    coins=queued_balance;cursor=pending_index;queued_balance=-1;TICK;assert(ack==2&&queued_balance==-1);
    won=1;TICK;assert(opened>1);
    /* The converted pool has counted, non-gear rewards too. Their registered
       event owns the entire grant and the saved cursor: the host only requests
       it and waits, including when it takes longer than the retry interval. */
    ap_event_mode16=1;reward_request=2;pending_index=-1;
    event_accept=0;TICK;assert(!receipt_requests&&pending_index==-1&&cursor==2);
    event_accept=1;TICK;assert(receipt_requests==1&&last_receipt==2000&&cursor==2&&pending_index==-1);
    TICK;assert(receipt_requests==1&&ack==2);
    event_busy=1;t+=6000000000LL;TICK;assert(receipt_requests==1&&ack==2);
    /* An accepted event can stay queued while the manager looks idle. Even a
       long pause never resends it: only an explicit gameplay-context change
       permits retry when the saved cursor still proves no commit. */
    event_busy=0;t+=60000000000LL;TICK;assert(receipt_requests==1&&cursor==2);
    loading=1;TICK;assert(receipt_requests==1);
    ap_delivery_epoch16++;loading=0;TICK;assert(receipt_requests==2&&cursor==2);
    cursor=3;event_busy=1;TICK;assert(ack==3&&receipt_requests==2);
    event_busy=0;TICK;assert(receipt_requests==3&&last_receipt==2001&&pending_index==-1);
    for(int committed=4;committed<=7;committed++) {
        cursor=committed;TICK;assert(ack==committed&&last_receipt==1998+committed&&pending_index==-1);
        TICK;assert(ack==committed&&cursor==committed);
    }
    cursor=8;TICK;assert(ack==8&&receipt_requests==7&&pending_index==-1);
    /* Unknown IDs stall visibly instead of advancing past a lost reward. */
    TICK;assert(cursor==8&&receipt_requests==7&&ack==8);
    /* A save rollback also rolls back ReceivedIndex, so the committed token
       can be delivered once to the restored inventory. */
    cursor=2;TICK;assert(receipt_requests==8&&last_receipt==2000&&cursor==2);
    return 0;
}
'''
c=home/'check_tick.c';c.write_text(header+tick+test)
exe=home/('check_tick.exe' if os.name=='nt' else 'check_tick')
subprocess.run([os.environ.get('CC') or shutil.which('gcc') or 'clang','-std=c11','-Wall','-Werror',str(c),'-o',str(exe)],check=True)
subprocess.run([str(exe.resolve())],check=True)
print("PASS actual host callback: legacy shield/rupees, wallet cap and frame acknowledgements; converted non-gear receipt events, no host-side cursor/grant, long event wait, refusal/retry, commit acknowledgement, unknown IDs and save rollback.")

# The actual event request helper gets a bounded guest stack, the same callback
# ABI as the port, and a real Ctx restored after every success/failure branch.
request=src[src.index("static int ap_request_item16("):src.index("static void ap_invalidate_delivery16(")]
request_header=r'''
#include <stdint.h>
#include <string.h>
#include <assert.h>
#include <stdarg.h>
typedef struct { uint64_t x[32]; } Ctx;
typedef void (*A64Fn)(Ctx*);
static unsigned char memory[65536];
static int event_busy, reject, no_functions, small_buffer, requests, released, held_deaths;
static int ap_delivery_ready16=1;
static uint64_t ap_delivery_actor16=77;
static int death_api(int state){assert(state==2);held_deaths++;return 0;}
static int (*ap_death16)(int)=death_api;
static int64_t wall_time=10000000000LL;
static struct { int64_t requested_at; } teleport;
enum { OOT_EVENTMGR_SLOT=21, OOT_EVENT_ARG_SIZE=7000 };
#define A64_PTR(a) (assert((a)<sizeof memory),memory+(a))
static uint64_t recomp_load64(Ctx*c,uint64_t a){uint64_t n;assert(a+8<=sizeof memory);memcpy(&n,memory+a,8);return n;}
static uint32_t recomp_load32(Ctx*c,uint64_t a){uint32_t n;assert(a+4<=sizeof memory);memcpy(&n,memory+a,4);return n;}
static void recomp_store64(Ctx*c,uint64_t a,uint64_t n){assert(a+8<=sizeof memory);memcpy(memory+a,&n,8);}
static void make_arg(Ctx*c){uint64_t a=c->x[0],p=1000;uint32_t size=small_buffer?1:128;memcpy(memory+a+6800,&p,8);memcpy(memory+a+6808,&size,4);}
static void set_link(Ctx*c){assert(c->x[1]==77);recomp_store64(c,c->x[0],77);}
static void release_link(Ctx*c){assert(recomp_load64(c,c->x[0])==0x84994b20ULL);released++;}
static void request_event(Ctx*c){assert(c->x[0]==500);assert(!strcmp((char*)memory+1000,"OOTRR_APReceive_2000"));assert(recomp_load64(c,c->x[1]+0x1950)==77);requests++;c->x[0]=!reject;}
static A64Fn a64_lookup(uint64_t a){return no_functions?NULL:a==0x80d99f10ULL?make_arg:a==0x80d9a820ULL?request_event:a==0x802dc440ULL?set_link:a==0x8022b6f0ULL?release_link:NULL;}
static uint64_t oot_singleton(Ctx*c,int slot){assert(slot==21);uint64_t b=event_busy;memcpy(memory+500+104,&b,8);return 500;}
static int64_t hos_now_ns(void){return wall_time;}
static void hos_log(const char *format,...){(void)format;}
'''
request_test=r'''
int main(void){
    Ctx c={{0}},saved;c.x[31]=50000;c.x[1]=123;saved=c;
    ap_delivery_ready16=0;assert(!ap_request_item16(&c,77,"OOTRR_APReceive_2000"));
    ap_delivery_ready16=1;assert(!ap_request_item16(&c,78,"OOTRR_APReceive_2000"));
    assert(!requests&&!released&&!held_deaths&&!memcmp(&c,&saved,sizeof c));
    assert(ap_request_item16(&c,77,"OOTRR_APReceive_2000"));assert(requests==1&&released==2&&held_deaths==1&&!memcmp(&c,&saved,sizeof c));
    event_busy=1;assert(!ap_request_item16(&c,77,"OOTRR_APReceive_2000"));assert(requests==1&&released==2);
    event_busy=0;teleport.requested_at=wall_time-1000000000LL;assert(!ap_request_item16(&c,77,"OOTRR_APReceive_2000"));
    teleport.requested_at=0;reject=1;assert(!ap_request_item16(&c,77,"OOTRR_APReceive_2000"));assert(requests==2&&released==4&&!memcmp(&c,&saved,sizeof c));
    reject=0;small_buffer=1;assert(!ap_request_item16(&c,77,"OOTRR_APReceive_2000"));assert(requests==2&&released==6&&!memcmp(&c,&saved,sizeof c));
    no_functions=1;assert(!ap_request_item16(&c,77,"OOTRR_APReceive_2000"));assert(released==6&&held_deaths==1&&!memcmp(&c,&saved,sizeof c));
    return 0;
}
'''
request_c=home/'check_receipt_request.c';request_c.write_text(request_header+request+request_test,encoding='utf-8')
request_exe=home/('check_receipt_request.exe' if os.name=='nt' else 'check_receipt_request')
subprocess.run([os.environ.get('CC') or shutil.which('gcc') or 'clang','-std=c11','-Wall','-Werror',str(request_c),'-o',str(request_exe)],check=True)
subprocess.run([str(request_exe.resolve())],check=True)
print("PASS actual receipt event request: idle/starter ABI, accepted vs refused result, immediate DeathLink hold on acceptance, event/teleport guards, undersized request, missing functions, actor link cleanup and Ctx restoration.")
