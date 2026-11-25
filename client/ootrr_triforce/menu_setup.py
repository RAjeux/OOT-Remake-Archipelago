"""Validate and install the optional embedded connection-page hooks as one patch."""
from .i18n import tr

MARK = "// OOTRR Archipelago embedded connection menu v1"


def _edits():
    return [
        ("namespace {\n\n// (Triforce) The tabs across the Options screen's header,", "void tab_move(int dir);\nvoid mods_sound(int id);\n\nnamespace {\n\n" + MARK + "\n// (Triforce) The tabs across the Options screen's header,"),
        ("    TAB_DEBUG = 5,", "    TAB_ARCHIPELAGO = 5,\n    TAB_DEBUG = 6,"),
        ("    TAB_COUNT = 6,", "    TAB_COUNT = 7,"),
        ("int scrolled_to[TAB_MOTION + 2] = {-1, -1, -1, -1, -1, -1, -1, -1};", "int scrolled_to[TAB_MOTION + 2] = {-1, -1, -1, -1, -1, -1, -1, -1, -1};"),
        ('static_assert(TAB_MOTION + 2 == 8, "scrolled_to:', 'static_assert(TAB_MOTION + 2 == 9, "scrolled_to:'),
        ("struct Row {", "bool ap_menu_available();\nbool ap_menu_editing();\n\nstruct Row {"),
        ('{"Display", "Graphics", "Audio", "Controls", "System", "Debug"}', '{"Display", "Graphics", "Audio", "Controls", "System", "Archipelago", "Debug"}'),
        ("for (int t = 0; t < TAB_DEBUG; t++) entry[tabs++] = t;", "for (int t = 0; t < TAB_DEBUG; t++) if (t != TAB_ARCHIPELAGO || ap_menu_available()) entry[tabs++] = t;"),
        ("for (int t = 0; t < TAB_DEBUG; t++) entry[n++] = t;", "for (int t = 0; t < TAB_DEBUG; t++) if (t != TAB_ARCHIPELAGO || ap_menu_available()) entry[n++] = t;"),
        ("bool menu_mods_typing() { return open_now.load() && page == kModsPage && mods_text_wanted.load(std::memory_order_relaxed); }", "bool menu_mods_typing() { return ap_menu_editing() || (open_now.load() && page == kModsPage && mods_text_wanted.load(std::memory_order_relaxed)); }"),
        ("void draw_menu(ui::Ctx& c, bool perf_under = false);", '#include "ootrr_ap_menu.inc"\n\nvoid draw_menu(ui::Ctx& c, bool perf_under = false);'),
        # Attach to the options fallback, leaving host pages such as the
        # Achievements page ahead of it in their native dispatch order.
        ("    else draw_options(k);", "    else if (cur_tab == TAB_ARCHIPELAGO) ap_menu::draw(k);\n    else draw_options(k);"),
        ("int menu_text_wanted() { return mods_text_wanted.load(std::memory_order_relaxed) ? 1 : 0; }", "int menu_text_wanted() { return ap_menu_editing() || mods_text_wanted.load(std::memory_order_relaxed) ? 1 : 0; }"),
        ("    if (page == 0) {   // (a tab's rows: the row chosen and what it is set to; a debug tool's and a mod's cheat's as they show it)", "    if (page == 0 && cur_tab == TAB_ARCHIPELAGO) {\n        s.cursor = ap_menu::editing ? 10 + ap_menu::key_row * 10 + ap_menu::key_col : ap_menu::selected;\n        s.mode = ap_menu::editing ? menu_sound::kModeEdit : menu_sound::kModeNone;\n        s.value = ap_menu::selected == 2 ? ap_menu::mode : ap_menu::selected == 3 ? ap_menu::automatic : 0;\n        return s;\n    }\n    if (page == 0) {   // (a tab's rows: the row chosen and what it is set to; a debug tool's and a mod's cheat's as they show it)"),
        ("    if (!open_now.load() || page != kModsPage) {   // ((Triforce) no text taken off the Mods screen: none kept for it either)\n        mods_text_wanted.store(false, std::memory_order_relaxed);\n        std::lock_guard<std::mutex> g(mods_typed_mu);\n        mods_typed.clear();\n    }", "    ap_menu_watch();\n    if (!open_now.load() || page != kModsPage) {\n        mods_text_wanted.store(false, std::memory_order_relaxed);\n        if (!ap_menu_editing()) {\n            std::lock_guard<std::mutex> g(mods_typed_mu);\n            mods_typed.clear();\n        }\n    }"),
        # The preceding Mods branch may gate its input on a native transition.
        # Keep that entire branch intact and intercept only options input.
        ("    } else if (open_now.load()) {", "    } else if (open_now.load() && page == 0 && cur_tab == TAB_ARCHIPELAGO) {\n        ap_menu_tick(press, tab_left, tab_right, mouse, moved, ptr, mx, my, changed);\n    } else if (open_now.load()) {"),
        ("        const int tab_count = tab_row_count(cur_tab);\n        int& selected = tab_selected[cur_tab];", "        if (cur_tab != TAB_ARCHIPELAGO) {\n        const int tab_count = tab_row_count(cur_tab);\n        int& selected = tab_selected[cur_tab];"),
        ("        const int64_t now = prof_now();\n        if (changed) {   // (a new row or value: its name from the start, after a rest)", "        } // Archipelago has its own rows, including on the tick that opens its tab.\n        const int64_t now = prof_now();\n        if (changed) {   // (a new row or value: its name from the start, after a rest)"),
    ]


def _edits_080():
    """The v0.8 renderer retains its extra pages, tuning bar and size editor."""
    edits = _edits()
    edits[3] = (
        "int scrolled_to[TAB_SIM_TURF + 1] = {-1, -1, -1, -1, -1, -1, -1, -1, -1, -1};",
        "int scrolled_to[TAB_SIM_TURF + 1] = {-1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1};")
    edits[4] = (
        'static_assert(TAB_SIM_TURF + 1 == 10, "scrolled_to:',
        'static_assert(TAB_SIM_TURF + 1 == 11, "scrolled_to:')
    # These captions now occur in two different native views. Match each full
    # declaration so a new or duplicated upstream array still fails closed.
    captions = '{"Display", "Graphics", "Audio", "Controls", "System", "Debug"}'
    updated = '{"Display", "Graphics", "Audio", "Controls", "System", "Archipelago", "Debug"}'
    edits[6] = (f"static const char* const ours[TAB_COUNT] = {captions};",
                f"static const char* const ours[TAB_COUNT] = {updated};")
    edits[12] = (
        "return mods_text_wanted.load(std::memory_order_relaxed) || size_text_wanted.load(std::memory_order_relaxed) ? 1 : 0;",
        "return ap_menu_editing() || mods_text_wanted.load(std::memory_order_relaxed) || size_text_wanted.load(std::memory_order_relaxed) ? 1 : 0;")
    edits[14] = (
        "    if (!open_now.load() || page != kModsPage) {   // ((Triforce) no text taken off the Mods screen: none kept for it either)\n"
        "        mods_text_wanted.store(false, std::memory_order_relaxed);\n"
        "        std::lock_guard<std::mutex> g(mods_typed_mu);\n"
        "        // ((Triforce) but the Output width and height rows' digits, while one of them is selected: size_edit)\n"
        "        if (size_text_wanted.load(std::memory_order_relaxed) && size_typed.size() < 64)\n"
        "            size_typed.insert(size_typed.end(), mods_typed.begin(), mods_typed.end());\n"
        "        mods_typed.clear();\n"
        "    }",
        "    ap_menu_watch();\n"
        "    if (open_now.load() && page == 0 && cur_tab == TAB_ARCHIPELAGO) {\n"
        "        // The native size editor must not retain ownership of AP text.\n"
        "        size_text_wanted.store(false, std::memory_order_relaxed);\n"
        "        size_edit = nullptr;\n"
        "        size_text.clear();\n"
        "        std::lock_guard<std::mutex> g(mods_typed_mu);\n"
        "        size_typed.clear();\n"
        "    }\n"
        "    if (!open_now.load() || page != kModsPage) {\n"
        "        mods_text_wanted.store(false, std::memory_order_relaxed);\n"
        "        if (!ap_menu_editing()) {\n"
        "            std::lock_guard<std::mutex> g(mods_typed_mu);\n"
        "            // Keep the native output-size input outside Archipelago.\n"
        "            if (size_text_wanted.load(std::memory_order_relaxed) && size_typed.size() < 64)\n"
        "                size_typed.insert(size_typed.end(), mods_typed.begin(), mods_typed.end());\n"
        "            mods_typed.clear();\n"
        "        }\n"
        "    }")
    edits.extend([
        (f"static const char* const names[TAB_COUNT] = {captions};",
         f"static const char* const names[TAB_COUNT] = {updated};"),
        # The native control bridge also names the auxiliary/hidden tabs.
        ('static const char* const tabs[] = {"display", "graphics", "audio", "controls", "system", "debug", "motion", "controls",\n'
         '                                       "graphics", "graphics", "hidden"};',
         'static const char* const tabs[] = {"display", "graphics", "audio", "controls", "system", "archipelago", "debug", "motion", "controls",\n'
         '                                       "graphics", "graphics", "hidden"};'),
        # The native tuning bar requires a native Row. AP supplies its own view
        # and rows; returning to a native tab restores the bar unchanged.
        ("const bool tuning = tune_mode && page == 0 && !embed_open && !row;",
         "const bool tuning = tune_mode && page == 0 && !embed_open && !row && cur_tab != TAB_ARCHIPELAGO;"),
    ])
    return edits


def patch_renderer(original):
    """Return a complete idempotent patch; reject drift before changing anything."""
    text = original.decode("utf-8")
    newline = "\r\n" if "\r\n" in text else "\n"
    normalized = text.replace("\r\n", "\n")
    edits = _edits_080() if "int scrolled_to[TAB_SIM_TURF + 1]" in normalized else _edits()
    if MARK in normalized:
        if normalized.count(MARK) != 1 or any(normalized.count(after) != 1 for before, after in edits):
            raise ValueError(tr('Triforce tools are incompatible with the native client.'))
        return original
    if any(normalized.count(before) != 1 for before, after in edits):
        raise ValueError(tr('Triforce tools are incompatible with the native client.'))
    for before, after in edits:
        normalized = normalized.replace(before, after, 1)
    return normalized.replace("\n", newline).encode("utf-8")
