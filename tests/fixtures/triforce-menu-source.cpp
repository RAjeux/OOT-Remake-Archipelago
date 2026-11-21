// Synthetic renderer hook fixture. It is not a game or host renderer.
namespace {

// (Triforce) The tabs across the Options screen's header,

    TAB_DEBUG = 5,

    TAB_COUNT = 6,

int scrolled_to[TAB_MOTION + 2] = {-1, -1, -1, -1, -1, -1, -1, -1};

static_assert(TAB_MOTION + 2 == 8, "scrolled_to:

struct Row {

{"Display", "Graphics", "Audio", "Controls", "System", "Debug"}

for (int t = 0; t < TAB_DEBUG; t++) entry[tabs++] = t;

for (int t = 0; t < TAB_DEBUG; t++) entry[n++] = t;

bool menu_mods_typing() { return open_now.load() && page == kModsPage && mods_text_wanted.load(std::memory_order_relaxed); }

void draw_menu(ui::Ctx& c, bool perf_under = false);

    else if (page == kModsPage) draw_mods(k);
    else draw_options(k);

int menu_text_wanted() { return mods_text_wanted.load(std::memory_order_relaxed) ? 1 : 0; }

    if (page == 0) {   // (a tab's rows: the row chosen and what it is set to; a debug tool's and a mod's cheat's as they show it)

    if (!open_now.load() || page != kModsPage) {   // ((Triforce) no text taken off the Mods screen: none kept for it either)
        mods_text_wanted.store(false, std::memory_order_relaxed);
        std::lock_guard<std::mutex> g(mods_typed_mu);
        mods_typed.clear();
    }

        mods_tick(press, tab_left, tab_right, mouse, moved, ptr, mx, my, changed);
    } else if (open_now.load()) {

        const int tab_count = tab_row_count(cur_tab);
        int& selected = tab_selected[cur_tab];

        const int64_t now = prof_now();
        if (changed) {   // (a new row or value: its name from the start, after a rest)
