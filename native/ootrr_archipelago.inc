/* Linked into the Windows port at build time. Only the resolved, enabled RomFS
   marker can opt a game into its room. All Zelda calls stay on Link's thread. */
#ifdef _WIN32
#include <wchar.h>
#include <wincrypt.h>
#include "ootrr_ap_digest.h"
static int (*ap_next16)(int);
static void (*ap_applied16)(int);
static int (*ap_note16)(char *,int);
static void (*ap_opened16)(uint32_t *,int,int);
static int (*ap_death16)(int);
static int (*ap_connection_info16)(char *,int);
static int (*ap_connect16)(char *,char *,int,int);
static int (*ap_disconnect16)(void);
static int (*ap_restore16)(uint8_t *,int);
static void (*ap_restore_deferred16)(int);
static int (*ap_receipt_replay16)(int,int);
static uint32_t ap_cursor16, ap_flags16[4096];
static int ap_flag_count16;
static int ap_event_mode16;
static uint64_t ap_delivery_actor16;
static uint64_t ap_delivery_epoch16;
static uint64_t ap_delivery_mgr16, ap_delivery_core16, ap_delivery_life16;
static int ap_delivery_ready16;
static char ap_profile16[4096];

/* The renderer's Options tab discovers this narrow host entry point without
   changing Triforce's rendering ABI. Connection work stays in the verified
   network DLL; no menu call touches guest state or restarts the save worker. */
__declspec(dllexport) int ootrr_ap_menu16(int action,const char *server,const char *password,
                                       int password_mode,int automatic,char *out,int cap) {
    if (out && cap>0) out[0]=0;
    if (!ap_connection_info16 || !ap_connect16 || !ap_disconnect16) return 0;
    if (action==0) return ap_connection_info16(out,cap);
    int result;
    if (action==1) {
        if (!server || !password) return -2;
        result=ap_connect16((char*)server,(char*)password,password_mode,automatic);
    } else if (action==2) {
        result=ap_disconnect16();
    } else {
        return -2;
    }
    if (out && cap>0) ap_connection_info16(out,cap);
    return result;
}

/* Only the packaged AP DLL may run. Keep the verified file open without
   sharing writes/deletes until the Windows loader has mapped the same file. */
static HANDLE ap_verify16(const wchar_t *path) {
    HANDLE file=CreateFileW(path,GENERIC_READ,FILE_SHARE_READ,NULL,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,NULL);
    if (file==INVALID_HANDLE_VALUE) return file;
    HCRYPTPROV prov=0; HCRYPTHASH hash=0;
    BYTE block[32768],digest[32]; DWORD n=0,size=sizeof digest;
    LARGE_INTEGER length;
    int ok=GetFileSizeEx(file,&length) && length.QuadPart>0 && length.QuadPart<=32*1024*1024
           && CryptAcquireContextW(&prov,NULL,NULL,PROV_RSA_AES,CRYPT_VERIFYCONTEXT)
           && CryptCreateHash(prov,CALG_SHA_256,0,0,&hash);
    while(ok) {
        if(!ReadFile(file,block,sizeof block,&n,NULL)){ok=0;break;}
        if(!n) break;
        ok=CryptHashData(hash,block,n,0)!=0;
    }
    if(ok) ok=CryptGetHashParam(hash,HP_HASHVAL,digest,&size,0) && size==32 && !memcmp(digest,ap_dll_sha16,32);
    if(hash) CryptDestroyHash(hash);
    if(prov) CryptReleaseContext(prov,0);
    if(!ok){CloseHandle(file);return INVALID_HANDLE_VALUE;}
    return file;
}

static void ap_boot_error16(void) {
    extern const char *hos_desired_language(void);
    const char *language=hos_desired_language();
    const int french=language && (!strcmp(language,"fr") || !strcmp(language,"fr-CA"));
    hos_log("OOTRR-AP native ABI 1: activation failed. See archipelago-jeu.log or run the mod configuration again.");
    MessageBoxW(NULL,french
        ? L"Le mod Archipelago est actif, mais sa salle ou son module est indisponible. Ferme l'ancien client et relance la configuration du mod."
        : L"The Archipelago mod is active, but its room or module is unavailable. Close any previous client and run the mod configuration again.",
        L"Archipelago",MB_OK|MB_ICONERROR);
}

static int ap_start_client16(int (*start)(char*,char*),void (*set_language)(char*),char *root,char *token) {
    if (!start || !set_language) return 0;
    /* This is the same cached language used by nn::oe and the game's Mals.
       HOS_LANGUAGE overrides language.txt; unsupported codes fall back to English. */
    extern const char *hos_desired_language(void);
    set_language((char*)hos_desired_language());
    return start(root,token);
}

static int ap_boot16(void) {
    extern int hos_mods_romfs(const char *, char *, size_t);
    char marker[1024],token[80];
    if (!hos_mods_romfs("Archipelago/room-v1.txt",marker,sizeof marker)) return 1;
    FILE *f=fopen(marker,"rb");
    if (!f) return 0;
    size_t n=fread(token,1,sizeof(token)-1,f); fclose(f);
    while (n && (token[n-1]=='\r'||token[n-1]=='\n')) --n;
    token[n]=0;
    if (n!=64||strspn(token,"0123456789abcdef")!=64) return 0;
    wchar_t base[1024],dll[1600],room[1400],physical[1400];
    if (!MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,marker,-1,physical,1400)) return 0;
    DWORD full=GetFullPathNameW(physical,1600,dll,NULL);
    if (!full || full>=1600) return 0;
    for (DWORD i=0;i<full;i++) if(dll[i]==L'/') dll[i]=L'\\';
    const wchar_t suffix[]=L"\\romfs\\Archipelago\\room-v1.txt";
    size_t tail=wcslen(suffix);
    if(full<=tail || _wcsicmp(dll+full-tail,suffix)) return 0;
    wcscpy(dll+full-tail,L"\\archipelago.dll");
    DWORD got=GetEnvironmentVariableW(L"LOCALAPPDATA",base,1024);
    if (!got||got>=1024) return 0;
    wchar_t wt[65];
    for (int i=0;i<=64;i++) wt[i]=(unsigned char)token[i];
    swprintf(room,1400,L"%ls\\OOTRR-Archipelago\\%ls",base,wt);
    char utf8[4000];
    if (!WideCharToMultiByte(CP_UTF8,0,room,-1,utf8,sizeof utf8,NULL,NULL)) return 0;
    HANDLE verified=ap_verify16(dll);
    if (verified==INVALID_HANDLE_VALUE) {
        hos_log("OOTRR-AP native ABI 1: archipelago.dll is missing or incompatible in the active mod");
        return 0;
    }
    HMODULE lib=LoadLibraryExW(dll,NULL,LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR|LOAD_LIBRARY_SEARCH_SYSTEM32);
    CloseHandle(verified);
    if (!lib) { hos_log("OOTRR-AP native ABI 1: module missing, Windows error %lu",(unsigned long)GetLastError()); return 0; }
    void (*set_language)(char*)=(void(*)(char*))GetProcAddress(lib,"AP_SetLanguage");
    int (*start)(char*,char*)=(int(*)(char*,char*))GetProcAddress(lib,"AP_Start");
    int (*flags)(uint32_t*,int)=(int(*)(uint32_t*,int))GetProcAddress(lib,"AP_Flags");
    uint32_t (*cursor)(void)=(uint32_t(*)(void))GetProcAddress(lib,"AP_Cursor");
    ap_applied16=(void(*)(int))GetProcAddress(lib,"AP_Applied");
    ap_next16=(int(*)(int))GetProcAddress(lib,"AP_Next");
    ap_note16=(int(*)(char*,int))GetProcAddress(lib,"AP_Note");
    ap_opened16=(void(*)(uint32_t*,int,int))GetProcAddress(lib,"AP_Opened");
    ap_death16=(int(*)(int))GetProcAddress(lib,"AP_DeathLink");
    ap_connection_info16=(int(*)(char*,int))GetProcAddress(lib,"AP_ConnectionInfo");
    ap_connect16=(int(*)(char*,char*,int,int))GetProcAddress(lib,"AP_Connect");
    ap_disconnect16=(int(*)(void))GetProcAddress(lib,"AP_Disconnect");
    ap_restore16=(int(*)(uint8_t*,int))GetProcAddress(lib,"AP_Restore");
    ap_restore_deferred16=(void(*)(int))GetProcAddress(lib,"AP_RestoreDeferred");
    ap_receipt_replay16=(int(*)(int,int))GetProcAddress(lib,"AP_ReceiptReplay");
    int (*event_delivery)(void)=(int(*)(void))GetProcAddress(lib,"AP_EventDelivery");
    if (!flags||!cursor||!ap_next16||!ap_applied16||!ap_note16||!ap_opened16||!ap_death16||!event_delivery||
        !ap_connection_info16||!ap_connect16||!ap_disconnect16||!ap_restore16||!ap_restore_deferred16) return 0;
    if (!ap_start_client16(start,set_language,utf8,token)) return 0;
    snprintf(ap_profile16,sizeof ap_profile16,"%s\\user",utf8);
    hos_user_dir=ap_profile16;
    ap_flag_count16=flags(ap_flags16,4096);ap_cursor16=cursor();
    ap_event_mode16=event_delivery();
    hos_log("OOTRR-AP native ABI 1: mod active, Archipelago profile loaded");
    return 1;
}

#include "ootrr_ap_items.inc"
/* Request the seed's registered receipt event on Link's thread. The vanilla
   pouch/event actions own all item effects (including upgrades, bottles, magic
   and dungeon credit); the flow commits ReceivedIndex after its grant. */
static int ap_request_item16(Ctx *c,uint64_t actor,const char *name) {
    if (!ap_delivery_ready16 || actor!=ap_delivery_actor16) return 0;
    const uint64_t events=oot_singleton(c,OOT_EVENTMGR_SLOT);
    A64Fn make_arg=a64_lookup(0x80d99f10ULL),request=a64_lookup(0x80d9a820ULL);
    A64Fn set_link=a64_lookup(0x802dc440ULL),release_link=a64_lookup(0x8022b6f0ULL);
    if (!actor || !name || !events || !make_arg || !request || !set_link || !release_link) return 0;
    if (recomp_load64(c,events+104)) return 0;
    if (teleport.requested_at && hos_now_ns()-teleport.requested_at<8000000000LL) return 0;
    const Ctx saved=*c;
    const uint64_t arg=(c->x[31]-OOT_EVENT_ARG_SIZE-0x100)&~0xfULL;
    c->x[31]=arg;c->x[0]=arg;make_arg(c);
    const uint64_t buf=recomp_load64(c,arg+6800);
    const uint32_t cap=recomp_load32(c,arg+6808);
    const int ok=buf && strlen(name)+1<=cap;
    uint64_t result=0;
    if (ok) {
        memcpy(A64_PTR(buf),name,strlen(name)+1);
        c->x[31]=arg;c->x[0]=arg+0x1950;c->x[1]=actor;c->x[2]=0;set_link(c);
        c->x[31]=arg;c->x[0]=events;c->x[1]=arg;request(c);result=c->x[0];
    }
    for (unsigned i=0;i<2;i++) {
        const uint64_t link=arg+(i?0x1950:0x1968);
        recomp_store64(c,link,0x84994b20ULL);
        c->x[31]=arg;c->x[0]=link;release_link(c);
    }
    *c=saved;
    if (result) {
        if (ap_death16) ap_death16(2); /* hold a death arriving before the event becomes visible */
        hos_log("OOTRR-AP receipt: event %s accepted",name);
    }
    return ok && result!=0;
}

static void ap_invalidate_delivery16(void) {
    ap_delivery_ready16=0;
    if (ap_delivery_actor16) {
        ap_delivery_actor16=0;
        ap_delivery_mgr16=ap_delivery_core16=ap_delivery_life16=0;
        ap_delivery_epoch16++;
    }
}

/* OOT 1.1.1's SelectorEventQueryCheckPlayerState (0x807672d0 /
   0x80233970) reads this native action controller. ActionVerb's own enum table
   identifies Wait=0x28, Fishing=0x34 and Crawl=0xea. Only ordinary locomotion
   is interruptible here: an idle event manager alone does not mean Link can
   play a get animation. Unknown and transitional states fail closed.
   QueryNaviIsWaitPlayerStateDrawnFishingRod (0x82a95c90) also checks bit 10
   at Player+0xa38; keep the whole fishing session intact even between casts. */
static int ap_can_receive16(Ctx *c,uint64_t components,uint64_t core) {
    int paused=0;
    if (!oot_gamedata_bool(c,0x604aebe1u,&paused) || paused) return 0; /* Sequence_IsPause */
    if (recomp_load32(c,core+0xa38)&0x400u) return 0;
    const uint64_t controller=recomp_load64(c,components+0x188);
    const uint64_t action=controller?recomp_load64(c,controller+0x1c0):0;
    if (!action) return 0;
    uint32_t verb=recomp_load32(c,action+0x28);
    if (verb==0x11au) verb=recomp_load32(c,action+0x4c);
    switch (verb) {
    case 0x01: /* Walk */
    case 0x02: /* WalkBackwards */
    case 0x03: /* Strafe */
    case 0x04: /* Run */
    case 0x15: /* TurnAround */
    case 0x16: /* Turn */
    case 0x28: /* Wait */
    case 0x41: /* LockOnWait */
    case 0x42: /* LockOnMove */
    case 0xd1: /* Idle */
        return 1;
    default:
        return 0;
    }
}

/* Link's life object is separate from the saved PlayerStatus.Life value. The
   supported port identifies this core actor in hos_oot_lift_player too. Only
   this gameplay thread may touch it; title/loading/death also gate item grants. */
static int ap_player16(Ctx *c,uint64_t actor,uint64_t components,int64_t now) {
    (void)now;
    if (!ap_cursor16 || !ap_death16) { ap_invalidate_delivery16(); return 0; }
    uint64_t mgr=oot_singleton(c,OOT_GAMEDATA_SLOT);
    int loading=0;
    if (!actor || !components || !mgr || !oot_gd_int(c,mgr,ap_cursor16) ||
        oot_pouch_count(c,oot_item_names[0])<0 ||
        (oot_gamedata_bool(c,0xef2b60c2u,&loading)&&loading)) {
        ap_invalidate_delivery16();
        ap_death16(-1);
        return 0;
    }
    uint64_t movement=recomp_load64(c,components+800);
    uint64_t core=movement>=0x1d50 ? movement-0x1d50 : 0;
    if (!core || !hos_oot_is_player(c,core)) { ap_invalidate_delivery16(); ap_death16(-1); return 0; }
    uint64_t life=recomp_load64(c,core+7184);
    uint64_t type=life?recomp_load64(c,life):0;
    if (type!=0x84b83438ULL && type!=0x84b6c400ULL) { ap_invalidate_delivery16(); ap_death16(-1); return 0; }
    if (ap_delivery_actor16 && (ap_delivery_actor16!=actor || ap_delivery_mgr16!=mgr ||
            ap_delivery_core16!=core || ap_delivery_life16!=life)) {
        ap_invalidate_delivery16();
        ap_death16(-1); /* another context must not inherit a held death or report the old life's death */
    }
    int current=(int32_t)recomp_load32(c,life+8);
    if (current<=0) { ap_invalidate_delivery16(); ap_death16(1); return 0; }
    const uint64_t events=oot_singleton(c,OOT_EVENTMGR_SLOT);
    ap_delivery_ready16=events && !recomp_load64(c,events+104) && ap_can_receive16(c,components,core);
    const int death_state=ap_delivery_ready16 ? 0 : 2;
    if (ap_death16(death_state)) {
        ap_invalidate_delivery16();
        __atomic_store_n((uint32_t*)A64_PTR(life+8),0,__ATOMIC_SEQ_CST);
        A64_MARK(life+8,4);
        oot_gd_set(c,mgr,0x31ab5580u,0,0); /* PlayerStatus.Life, never MaxLife */
        ap_death16(1); /* acknowledge the received death without bouncing it back */
        hos_log("OOTRR-AP DeathLink: Link's life %d -> 0",current);
        return 0;
    }
    ap_delivery_actor16=actor;
    ap_delivery_mgr16=mgr;ap_delivery_core16=core;ap_delivery_life16=life;
    return 1;
}

static void ap_tick16(Ctx *c,int64_t now) {
    static int64_t next, next_notice;
    if (!ap_cursor16 || now<next) return;
    next=now+300000000;
    if (now>=next_notice) {
        char text[62];
        if(ap_note16(text,sizeof text)) {
            extern void hos_save_share_say(int row,const char *text);
            hos_save_share_say(HOS_SHARE_NOTICE,text);
            next_notice=now+4000000000LL;
        }
    }
    uint64_t mgr=oot_singleton(c,OOT_GAMEDATA_SLOT);
    uint64_t entry=mgr?oot_gd_int(c,mgr,ap_cursor16):0;
    if (!entry) return;
    int loading=0;
    if (oot_gamedata_bool(c,0xef2b60c2u,&loading)&&loading) return;
    uint32_t opened[4096]; uint8_t states[4096]; int count=0,snapshot_valid=1;
    for(int i=0;i<ap_flag_count16;i++) {
        const char state=oot_flag_state(c,1,ap_flags16[i]);
        states[i]=(state=='0'||state=='1')?(uint8_t)state:255;
        if(states[i]==255) snapshot_valid=0;
        if(state=='1') opened[count++]=ap_flags16[i];
    }
    uint64_t final_boss=oot_gd_int(c,mgr,0x641e0375u);
    int won=final_boss && (int32_t)recomp_load32(c,final_boss+0x1c)>0;
    if(count || won) ap_opened16(opened,count,won);
    int index=(int)recomp_load32(c,entry+0x1c);
    if (index<0) return;
    static int restore_pending,restore_clearing;
    static uint64_t restore_mgr,restore_epoch;
    const uint32_t restore_key=ap_event_mode16 && ap_restore16 && ap_restore_deferred16
        ? oot_murmur3("Archipelago.RestoreResult") : 0;
    if (restore_mgr!=mgr || restore_epoch!=ap_delivery_epoch16) {
        restore_pending=restore_clearing=0;
        restore_mgr=mgr;restore_epoch=ap_delivery_epoch16;
    }
    if (restore_pending) {
        const uint64_t result=restore_key?oot_gd_int(c,mgr,restore_key):0;
        if (!result) return;
        const int status=(int32_t)recomp_load32(c,result+0x1c);
        if (status==restore_pending) {
            /* The native flow has committed all effects and location flags.
               Its result never changes ReceivedIndex or sends an AP item. */
            restore_pending=0;
        } else if (status==-restore_pending) {
            ap_restore_deferred16(restore_pending);
            restore_pending=0;
        } else {
            /* Accepted does not mean started. Even a long idle-looking queue
               cannot justify another request without a result/context change. */
            return;
        }
    }
    static int pending=-1;
    static uint64_t pending_mgr,pending_epoch;
    static int64_t pending_at;
    if (pending>=0 && pending_mgr==mgr) {
        if (index==pending+1) ap_applied16(pending);
        if (index==pending) {
            /* An accepted event may still be queued while the event manager
               looks idle. Time alone never proves that its grant failed.
               Only a changed gameplay context permits re-requesting an
               uncommitted receipt; the saved cursor remains authoritative. */
            if (ap_event_mode16 && pending_epoch==ap_delivery_epoch16) return;
            if (!ap_event_mode16 && now-pending_at<5000000000LL) return;
        }
    }
    pending=-1;
    /* Reporting checks and observing a committed receipt are safe while Link
       is busy. Starting another grant (including quiet/legacy restoration) is
       not; leave its index and network queue untouched until normal control. */
    if (!ap_delivery_ready16) return;
    int item=ap_next16(index);
    if (!item) {
        /* Network receipts have priority, including bottles/upgrades that can
           unblock a local refill. Old profiles have no registered whitelist. */
        if (!restore_key || !ap_delivery_actor16) return;
        const uint64_t events=oot_singleton(c,OOT_EVENTMGR_SLOT);
        if (!events || recomp_load64(c,events+104)) return;
        const int location=ap_restore16(states,ap_flag_count16);
        if (location<=0) return;
        const uint64_t result=oot_gd_int(c,mgr,restore_key);
        if (!result) return;
        const int status=(int32_t)recomp_load32(c,result+0x1c);
        if (status) {
            if (!restore_clearing && oot_gd_set(c,mgr,restore_key,0,0)) restore_clearing=1;
            return;
        }
        /* A queued clear is not a visible clear: observe zero before reusing
           an old +/-location result. A fresh zero can be cleared and used now. */
        if (!restore_clearing && !oot_gd_set(c,mgr,restore_key,0,0)) return;
        restore_clearing=0;
        char event[64];
        snprintf(event,sizeof event,"OOTRR_APRestore_%d",location);
        if (ap_request_item16(c,ap_delivery_actor16,event)) restore_pending=location;
        return;
    }
    if (ap_event_mode16) {
        const char *event=ap_eventname16(item);
        char replay[64];
        if (event && snapshot_valid && ap_receipt_replay16 && ap_receipt_replay16(index,item)) {
            snprintf(replay,sizeof replay,"OOTRR_APTradeReplay_%d",item);
            event=replay;
        }
        if (event && ap_request_item16(c,ap_delivery_actor16,event)) {
            pending=index;pending_mgr=mgr;pending_epoch=ap_delivery_epoch16;pending_at=now;
        }
        return;
    }
    if (item==AP_RUPEE_ID) {
        const uint32_t key=0xa77921d7u;
        uint64_t money=oot_gd_int(c,mgr,key);
        if (!money) return;
        int current=(int)recomp_load32(c,money+0x1c),capacity=0;
        oot_capacity(c,mgr,"Rupee",&capacity);
        if(capacity<=0) capacity=99;
        if(current<0) return;
        if(current<capacity && !oot_gd_set(c,mgr,key,current+(capacity-current<5?capacity-current:5),0)) return;
    } else {
        const char *name=ap_item_name16(item);
        if (!name) return;
        int previous=oot_item_get(c,name);
        if (previous<0 || (previous==0 && !oot_item_give(c,name,1))) return;
    }
    /* Both values go through the same GameData update queue and save. A rollback
       also restores the index, so ReceivedItems replay can deliver it again. */
    if (oot_gd_set(c,mgr,ap_cursor16,(uint32_t)(index+1),0)) {
        pending=index;pending_mgr=mgr;pending_at=now;
    }
}
#else
#define ap_boot16() 1
#define ap_player16(c,actor,components,now) 1
#define ap_tick16(c,now) ((void)0)
#endif
