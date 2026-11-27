/* Included in place of the shared host's direct-context request helper.
   EventRequestArg and cleanup follow pinned Longshot game/oot_tools.c's native
   request. Refuse a non-guest caller through game_call, never copy a Ctx. */
static int ap_request_item16(Ctx *c, uint64_t actor, const char *name) {
    if (!c || !ap_delivery_ready16 || actor != ap_delivery_actor16 || !actor || !name) return 0;
    const uint64_t events = oot_singleton(c, OOT_EVENTMGR_SLOT);
    if (!events || !game_has(0x80d99f10ULL) || !game_has(0x80d9a820ULL) ||
        !game_has(0x802dc440ULL) || !game_has(0x8022b6f0ULL)) return 0;
    if (recomp_load64(c, events + 104)) return 0;
    if (teleport.requested_at && hos_now_ns() - teleport.requested_at < 8000000000LL) return 0;
    if (c->x[31] < OOT_EVENT_ARG_SIZE + 0x100) return 0;
    const uint64_t arg = (c->x[31] - OOT_EVENT_ARG_SIZE - 0x100) & ~0xfULL;
    if (!hos_guest_range(arg, OOT_EVENT_ARG_SIZE)) return 0;
    /* A refused constructor has built nothing, so no cleanup is attempted. */
    if (!game_call(c, 0x80d99f10ULL, arg, 1, (const uint64_t[]){arg}, NULL)) return 0;
    const uint64_t buf = recomp_load64(c, arg + 6800);
    const uint32_t cap = recomp_load32(c, arg + 6808);
    const size_t length = strlen(name);
    void *to = buf && length < cap ? hos_guest_range(buf, length + 1) : NULL;
    int ok = to != NULL;
    uint64_t result = 0;
    if (ok) {
        memcpy(to, name, length + 1);
        ok = game_call(c, 0x802dc440ULL, arg, 3, (const uint64_t[]){arg + 0x1950, actor, 0}, NULL);
        if (ok) ok = game_call(c, 0x80d9a820ULL, arg, 2, (const uint64_t[]){events, arg}, &result);
    }
    for (unsigned i = 0; i < 2; i++) {
        const uint64_t link = arg + (i ? 0x1950 : 0x1968);
        recomp_store64(c, link, 0x84994b20ULL);
        /* A request already accepted must remain pending even if a later
           cleanup call is refused; retrying an accepted event could duplicate
           a grant before its saved ReceivedIndex becomes visible. */
        game_call(c, 0x8022b6f0ULL, arg, 1, (const uint64_t[]){link}, NULL);
    }
    if (ok && result) {
        if (ap_death16) ap_death16(2);
        hos_log("OOTRR-AP receipt: event %s accepted", name);
    }
    return ok && result != 0;
}
