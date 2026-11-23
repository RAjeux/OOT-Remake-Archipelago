/* Hookshot 3.0.1 adapter for the shared Archipelago bridge.
   GameData helpers derived from GPL-3.0-or-later Triforce host/hos_main.c.
   Native setters and saved receipt transactions are unchanged. */
static uint32_t oot_murmur3(const char *text) {
    const size_t n = strlen(text);
    uint32_t h = 0;
    size_t i = 0;
    for (; i + 4 <= n; i += 4) {
        uint32_t k;
        memcpy(&k, text + i, 4);
        k *= 0xcc9e2d51u, k = k << 15 | k >> 17, k *= 0x1b873593u;
        h ^= k, h = h << 13 | h >> 19, h = h * 5 + 0xe6546b64u;
    }
    uint32_t k = 0;
    switch (n & 3) {
    case 3: k ^= (uint32_t)(uint8_t)text[i + 2] << 16;   /* fall through */
    case 2: k ^= (uint32_t)(uint8_t)text[i + 1] << 8;    /* fall through */
    case 1: k ^= (uint8_t)text[i], k *= 0xcc9e2d51u, k = k << 15 | k >> 17, k *= 0x1b873593u, h ^= k;
    }
    h ^= (uint32_t)n;
    h ^= h >> 16, h *= 0x85ebca6bu, h ^= h >> 13, h *= 0xc2b2ae35u, h ^= h >> 16;
    return h;
}

/* the index a (hash, index) table of size cells gives for hash, -1 none (open addressing from hash % size) */
static int64_t oot_gd_lookup(Ctx *c, uint64_t table, uint32_t size, uint32_t hash) {
    if (!table || !size || size > (1u << 22) || !hash) return -1;
    for (uint32_t probe = 0, slot = hash % size; probe < size; probe++, slot = slot + 1 == size ? 0 : slot + 1) {
        const uint32_t key = recomp_load32(c, table + slot * 8ULL);
        if (!key) return -1;
        if (key == hash) return recomp_load32(c, table + slot * 8ULL + 4);
    }
    return -1;
}

/* a struct's entry by its hash, 0 none */
static uint64_t oot_gd_struct(Ctx *c, uint64_t mgr, uint32_t hash) {
    const int64_t i = oot_gd_lookup(c, recomp_load64(c, mgr + 0xc20), recomp_load32(c, mgr + 0xc2c), hash);
    const uint64_t entries = recomp_load64(c, mgr + 0xc18);
    return i < 0 || !entries || (uint64_t)i >= recomp_load32(c, mgr + 0xc10) ? 0 : entries + (uint64_t)i * 0x20;
}

/* the value hash of a struct's member, 0 none (the members' table is searched whole: a few dozen pairs) */
static uint32_t oot_gd_member(Ctx *c, uint64_t entry, uint32_t member) {
    const uint64_t table = entry ? recomp_load64(c, entry + 8) : 0;
    const uint32_t size = entry ? recomp_load32(c, entry + 0x14) : 0;
    if (!table || !size || size > 65536) return 0;
    for (uint32_t i = 0; i < size; i++)
        if (recomp_load32(c, table + 8ULL * i) == member) return recomp_load32(c, table + 8ULL * i + 4);
    return 0;
}

/* an Int's entry by its hash, 0 none */
static uint64_t oot_gd_int(Ctx *c, uint64_t mgr, uint32_t hash) {
    const int64_t i = oot_gd_lookup(c, recomp_load64(c, mgr + 0xc8 + 0x18), recomp_load32(c, mgr + 0xc8 + 0x24), hash);
    const uint64_t entries = recomp_load64(c, mgr + 0xc8 + 0x10);
    return i < 0 || !entries || (uint64_t)i >= recomp_load32(c, mgr + 0xc8 + 8) ? 0 : entries + (uint64_t)i * 0x28;
}

/* the hash of an item's count (its Pouch struct's Stock), 0 when the Pouch has no such item */
static uint32_t oot_item_stock_hash(Ctx *c, uint64_t mgr, const char *name) {
    const uint32_t item = oot_gd_member(c, oot_gd_struct(c, mgr, 0x3da094e3u), oot_murmur3(name));
    return item ? oot_gd_member(c, oot_gd_struct(c, mgr, item), 0x22344481u) : 0;
}

/* the game's own SetInt / SetBool: 1 when called */
static int oot_gd_set(Ctx *c, uint64_t mgr, uint32_t hash, uint32_t value, int is_bool) {
    A64Fn set = a64_lookup(is_bool ? 0x806a2b20ULL : 0x80183b70ULL);
    if (!set || !mgr || !hash) return 0;
    const Ctx saved = *c;
    c->x[31] = (c->x[31] - 0x100) & ~0xfULL;
    c->x[0] = mgr, c->x[1] = value, c->x[2] = hash;
    set(c);
    *c = saved;
    return 1;
}

/* a Bool's entry by its hash, 0 none (24-byte entries, the current value at +22, as oot_gamedata_set_bool has them) */
static uint64_t oot_gd_bool(Ctx *c, uint64_t mgr, uint32_t hash) {
    const int64_t i = oot_gd_lookup(c, recomp_load64(c, mgr + 32), recomp_load32(c, mgr + 44), hash);
    const uint64_t entries = recomp_load64(c, mgr + 24);
    return i < 0 || !entries || (uint64_t)i >= recomp_load32(c, mgr + 16) ? 0 : entries + (uint64_t)i * 24;
}

/* An item's count as GameData has it: its Pouch struct's Stock, or 1 / 0 of its "got it once" flag where it has only
   that (the songs). -1: the save data has no such item */
static int oot_item_get(Ctx *c, const char *name) {
    const uint64_t mgr = oot_singleton(c, OOT_GAMEDATA_SLOT);
    if (!mgr) return -1;
    const uint32_t stock = oot_item_stock_hash(c, mgr, name);
    uint64_t entry = stock ? oot_gd_int(c, mgr, stock) : 0;
    if (entry) return (int)recomp_load32(c, entry + 0x1c);
    const uint32_t first = oot_gd_member(c, oot_gd_struct(c, mgr, 0xade0ef78u), oot_murmur3(name));
    entry = first ? oot_gd_bool(c, mgr, first) : 0;
    return entry ? recomp_load8(c, entry + 22) & 1 : -1;
}

/* What the bags hold, as the game's files have it (each bag's GameParameter/ExpansionMaxNumActor: "GameData" the name of
   the size in the capacity struct 0xf80f8077, "MaxNum" the size). The game raises the size when it gives a bag; a bag or
   ammunition set from here does the same, so that what is given can be carried and used. */
static const struct { const char *bag, *what; int max; } oot_bags[] = {
    {"Item_BombBag_Small", "Bomb", 20},      {"Item_BombBag_Medium", "Bomb", 30},      {"Item_BombBag_Large", "Bomb", 40},
    {"Item_Quiver_Small", "Arrow", 30},      {"Item_Quiver_Medium", "Arrow", 40},      {"Item_Quiver_Large", "Arrow", 50},
    {"Item_BulletBag_Small", "DekuSeed", 30}, {"Item_BulletBag_Medium", "DekuSeed", 40}, {"Item_BulletBag_Large", "DekuSeed", 50},
    {"Item_NutBag_Small", "DekuNut", 20},    {"Item_NutBag_Medium", "DekuNut", 30},    {"Item_NutBag_Large", "DekuNut", 40},
    {"Item_StickBag_Small", "DekuStick", 10}, {"Item_StickBag_Medium", "DekuStick", 20}, {"Item_StickBag_Large", "DekuStick", 30},
    {"Item_Wallet_Medium", "Rupee", 500},    {"Item_Wallet_Large", "Rupee", 1000},
};
static const struct { const char *item, *what; } oot_ammo[] = {
    {"Item_Bomb", "Bomb"}, {"Item_Bombchu", "Bomb"}, {"Item_Arrow_Normal", "Arrow"}, {"Item_DekuSeed", "DekuSeed"},
    {"Item_DekuNut", "DekuNut"}, {"Item_DekuStick", "DekuStick"},
};
#define OOT_BAGS (sizeof oot_bags / sizeof oot_bags[0])

/* a size of the capacity struct: its Int's hash (0 none), and its value now through *value */
static uint32_t oot_capacity(Ctx *c, uint64_t mgr, const char *what, int *value) {
    const uint32_t hash = oot_gd_member(c, oot_gd_struct(c, mgr, 0xf80f8077u), oot_murmur3(what));
    const uint64_t entry = hash ? oot_gd_int(c, mgr, hash) : 0;
    if (value) *value = entry ? (int)recomp_load32(c, entry + 0x1c) : 0;
    return entry ? hash : 0;
}

/* a count of the Pouch set (and the item marked as got once), 1 when the Pouch has the item */
static int oot_pouch_set(Ctx *c, uint64_t mgr, const char *name, int count) {
    const uint32_t stock = oot_item_stock_hash(c, mgr, name);
    if (!stock || !oot_gd_int(c, mgr, stock)) return 0;
    oot_gd_set(c, mgr, stock, (uint32_t)(count < 0 ? 0 : count), 0);
    const uint32_t first = oot_gd_member(c, oot_gd_struct(c, mgr, 0xade0ef78u), oot_murmur3(name));
    if (count > 0 && first) oot_gd_set(c, mgr, first, 1, 1);   /* ("got it once": as the game marks what was got) */
    return 1;
}

/* An item's count set, through the game's own setters: 1 done, 0 the save data has no such item */
static int oot_item_give(Ctx *c, const char *name, int count) {
    const uint64_t mgr = oot_singleton(c, OOT_GAMEDATA_SLOT);
    if (!mgr) return 0;
    for (unsigned i = 0; i < OOT_BAGS; i++) {   /* a bag: the size it gives, or without it the largest bag left */
        if (strcmp(name, oot_bags[i].bag)) continue;
        int size = 0, best = count > 0 ? oot_bags[i].max : !strcmp(oot_bags[i].what, "Rupee") ? 200 : 0;
        const uint32_t hash = oot_capacity(c, mgr, oot_bags[i].what, &size);
        for (unsigned k = 0; k < OOT_BAGS; k++)
            if (k != i && !strcmp(oot_bags[k].what, oot_bags[i].what) && oot_bags[k].max > best && oot_item_get(c, oot_bags[k].bag) > 0)
                best = oot_bags[k].max;
        if (hash && best != size) oot_gd_set(c, mgr, hash, (uint32_t)best, 0);
    }
    for (unsigned i = 0; count > 0 && i < sizeof oot_ammo / sizeof oot_ammo[0]; i++) {   /* ammunition: a bag that holds it */
        if (strcmp(name, oot_ammo[i].item)) continue;
        int size = 0, fits = -1, largest = -1;
        const uint32_t hash = oot_capacity(c, mgr, oot_ammo[i].what, &size);
        for (unsigned k = 0; k < OOT_BAGS; k++) {
            if (strcmp(oot_bags[k].what, oot_ammo[i].what)) continue;
            if (largest < 0 || oot_bags[k].max > oot_bags[largest].max) largest = (int)k;
            if (oot_bags[k].max >= count && (fits < 0 || oot_bags[k].max < oot_bags[fits].max)) fits = (int)k;
        }
        if (largest >= 0 && count > oot_bags[largest].max) count = oot_bags[largest].max, fits = largest;
        if (hash && fits >= 0 && count > size) {
            oot_pouch_set(c, mgr, oot_bags[fits].bag, 1);
            oot_gd_set(c, mgr, hash, (uint32_t)oot_bags[fits].max, 0);
        }
    }
    if (oot_pouch_set(c, mgr, name, count)) return 1;
    const uint32_t first = oot_gd_member(c, oot_gd_struct(c, mgr, 0xade0ef78u), oot_murmur3(name));
    if (first && oot_gd_bool(c, mgr, first)) return oot_gd_set(c, mgr, first, count > 0, 1);   /* (a song: its flag) */
    return 0;
}

static char oot_flag_state(Ctx *c, int loaded, uint32_t hash) {
    const uint64_t mgr = loaded ? oot_singleton(c, OOT_GAMEDATA_SLOT) : 0;
    if (!mgr) return '?';
    const uint64_t entry = oot_gd_bool(c, mgr, hash);
    return !entry ? '-' : recomp_load8(c, entry + 22) & 1 ? '1' : '0';
}


#define HOS_SHARE_NOTICE 0
static void hos_save_share_say(int row,const char *text) {
    (void)row; hos_log("Archipelago: %s",text);
}
const char *hos_desired_language(void) {
    extern const char *hos_game_language(void); return hos_game_language();
}
