/* Run the actual adapter, checking request refusal/cleanup and scheduler API. */
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef struct { uint64_t x[32]; unsigned poll; } Ctx;
static unsigned char memory[65536];
static int ap_delivery_ready16 = 1;
static uint64_t ap_delivery_actor16 = 77;
static struct { int64_t requested_at; } teleport;
static int made, linked, requested, released, deaths, logs;
static uint64_t missing, refused;
static uint32_t capacity = 128;
static int busy;
static int (*ap_death16)(int);
#define OOT_EVENT_ARG_SIZE 0x1b20ULL
#define OOT_EVENTMGR_SLOT 0x84c9e090ULL
static uint64_t oot_singleton(Ctx *c, uint64_t slot) { (void)c; assert(slot == OOT_EVENTMGR_SLOT); return 1024; }
static void *hos_guest_range(uint64_t address, size_t size) {
    return address && address <= sizeof memory && size <= sizeof memory - address ? memory + address : NULL;
}
static uint64_t recomp_load64(Ctx *c, uint64_t at) {
    (void)c;
    if (at == 1128) return busy;
    uint64_t n; assert(hos_guest_range(at, 8)); memcpy(&n, memory + at, 8); return n;
}
static uint32_t recomp_load32(Ctx *c, uint64_t at) {
    (void)c; uint32_t n; assert(hos_guest_range(at, 4)); memcpy(&n, memory + at, 4); return n;
}
static void recomp_store64(Ctx *c, uint64_t at, uint64_t n) {
    (void)c; assert(hos_guest_range(at, 8)); memcpy(memory + at, &n, 8);
}
static int64_t hos_now_ns(void) { return 10000000000LL; }
static void hos_log(const char *format, const char *name) { assert(strstr(format,"accepted")); assert(!strcmp(name,"OOTRR_APReceived_1")); logs++; }
static int game_has(uint64_t function) { return function != missing; }
static int game_call(Ctx *c, uint64_t function, uint64_t sp, int n, const uint64_t *args, uint64_t *result) {
    assert(c->poll == 1); /* The adapter never overwrites a pending scheduler kick. */
    assert(sp % 16 == 0 && c->x[31] == 60000);
    if (function == refused) return 0;
    switch (function) {
    case 0x80d99f10ULL:
        assert(n == 1 && args[0] == sp); made++;
        recomp_store64(c,sp+6800,45000); memcpy(memory+sp+6808,&capacity,4); break;
    case 0x802dc440ULL:
        assert(n == 3 && args[0] == sp+0x1950 && args[1] == 77 && !args[2]); linked++; break;
    case 0x80d9a820ULL:
        assert(n == 2 && args[0] == 1024 && args[1] == sp);
        assert(!strcmp((char *)memory+45000,"OOTRR_APReceived_1")); requested++; *result = 1; break;
    case 0x8022b6f0ULL:
        assert(n == 1 && (args[0] == sp+0x1950 || args[0] == sp+0x1968));
        assert(recomp_load64(c,args[0]) == 0x84994b20ULL); released++; break;
    default: assert(0);
    }
    return 1;
}
static int death(int state) { assert(state == 2); deaths++; return 0; }
#include "ootrr_ap_longshot_event.inc"
static void reset(void) {
    made=linked=requested=released=deaths=logs=busy=0;
    missing=refused=0; capacity=128; ap_delivery_ready16=1; teleport.requested_at=0;
}
int main(void) {
    Ctx c={0}; c.x[31]=60000; c.poll=1; ap_death16=death;
    assert(ap_request_item16(&c,77,"OOTRR_APReceived_1"));
    assert(made==1 && linked==1 && requested==1 && released==2 && deaths==1 && logs==1);
    assert(c.x[31]==60000 && c.poll==1);
    reset(); ap_delivery_ready16=0; assert(!ap_request_item16(&c,77,"OOTRR_APReceived_1")); assert(!made);
    reset(); busy=1; assert(!ap_request_item16(&c,77,"OOTRR_APReceived_1")); assert(!made);
    reset(); missing=0x802dc440; assert(!ap_request_item16(&c,77,"OOTRR_APReceived_1")); assert(!made);
    reset(); refused=0x80d99f10; assert(!ap_request_item16(&c,77,"OOTRR_APReceived_1")); assert(!made && !released);
    reset(); capacity=2; assert(!ap_request_item16(&c,77,"OOTRR_APReceived_1")); assert(made==1 && !requested && released==2 && !deaths);
    reset(); refused=0x802dc440; assert(!ap_request_item16(&c,77,"OOTRR_APReceived_1")); assert(!requested && released==2 && !deaths);
    reset(); refused=0x80d9a820; assert(!ap_request_item16(&c,77,"OOTRR_APReceived_1")); assert(linked==1 && released==2 && !deaths);
    reset(); refused=0x8022b6f0; assert(ap_request_item16(&c,77,"OOTRR_APReceived_1")); assert(requested==1 && deaths==1);
    reset(); c.x[31]=100; assert(!ap_request_item16(&c,77,"OOTRR_APReceived_1")); assert(!made);
    return 0;
}
