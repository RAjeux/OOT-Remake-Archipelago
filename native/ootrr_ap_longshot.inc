/* Longshot e8fce995 adapter for our native AP receipt bridge.
   Longshot's game/flags.h owns bounded flag reads; ALL guest calls go through
   game_call, which preserves scheduler polling and virtual-core ownership.
   No inventory debugger or legacy direct grant is used to deliver AP items. */
#define OOT_GAMEDATA_SLOT GAME_FLAGS_SLOT
extern const char *hos_user_dir;
extern const char *hos_desired_language(void);

static uint32_t oot_murmur3(const char *name) {
    return game_flag_hash(name, strlen(name));
}
static uint64_t oot_gd_int(Ctx *c, uint64_t mgr, uint32_t hash) {
    (void)c;
    return game_flag_entry(mgr, GAME_FLAG_INT, hash);
}
static int oot_gamedata_bool(Ctx *c, uint32_t hash, int *value) {
    (void)c;
    return game_flag_bool(game_flags_mgr(), hash, value);
}
static char oot_flag_state(Ctx *c, int loaded, uint32_t hash) {
    int value;
    (void)c;
    if (!loaded || !game_flags_mgr()) return '?';
    return game_flag_bool(game_flags_mgr(), hash, &value) ? value ? '1' : '0' : '-';
}
static int oot_gd_set(Ctx *c, uint64_t mgr, uint32_t hash, uint32_t value, int is_bool) {
    if (!mgr || !hash) return 0;
    return game_call(c, is_bool ? 0x806a2b20ULL : 0x80183b70ULL, 0, 3,
                     (const uint64_t[]){mgr, value, hash}, NULL);
}
/* These names satisfy the shared bridge's old direct-delivery branch at link
   time. The staged bridge rejects that mode at bootstrap and before its tick.
   Returning failure here provides a second guard, never a debugger mutation. */
static uint32_t oot_capacity(Ctx *c, uint64_t mgr, const char *what, int *value) {
    (void)c; (void)mgr; (void)what;
    if (value) *value = 0;
    return 0;
}
static int oot_item_get(Ctx *c, const char *name) { (void)c; (void)name; return -1; }
static int oot_item_give(Ctx *c, const char *name, int count) {
    (void)c; (void)name; (void)count; return 0;
}
#define HOS_SHARE_NOTICE 0
void hos_save_share_say(int row, const char *text) {
    (void)row;
    hos_log("Archipelago: %s", text);
}
