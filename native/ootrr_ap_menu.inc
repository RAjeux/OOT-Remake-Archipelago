/* Optional Archipelago page for Triforce's embedded Zelda Options screen.
   Included inside vk_menu.cpp's private namespace. UI work stays on its
   presentation thread; the verified host bridge owns connection operations. */
namespace ap_menu {
using Bridge = int (*)(int, const char*, const char*, int, int, char*, int);
struct State {
    std::string server, slot, room, phase = "disconnected", error, language = "en";
    bool password = false, automatic = true;
};
State state;
std::string server, password, previous;
std::string local_error;
bool available = false, loaded = false, dirty = false, editing = false;
bool previous_dirty = false, automatic = true, capitals = false, symbols = false;
std::atomic<bool> text_wanted{false};
int selected = 0, field = 0, mode = 0, previous_mode = 0, key_row = 1, key_col = 0;
int64_t next_poll = 0;

void erase(std::string& text) { for (char& c : text) c = 0; text.clear(); }
bool french() { return state.language == "fr"; }
const char* text(const char* en, const char* fr) { return french() ? fr : en; }

/* The backend emits a flat, bounded JSON object. Read all JSON string escapes,
   including surrogate pairs, without accepting control characters or silently
   consuming partial values. Unknown scalar keys remain forwards compatible. */
void space(const char*& p, const char* end) { while (p < end && (*p == ' ' || *p == '\r' || *p == '\n' || *p == '\t')) ++p; }
bool hex4(const char*& p, const char* end, unsigned& value) {
    value = 0;
    for (int i = 0; i < 4; ++i) {
        if (p == end) return false;
        unsigned char c = (unsigned char)*p++;
        int n = c >= '0' && c <= '9' ? c - '0' : c >= 'a' && c <= 'f' ? c - 'a' + 10 : c >= 'A' && c <= 'F' ? c - 'A' + 10 : -1;
        if (n < 0) return false;
        value = value * 16 + (unsigned)n;
    }
    return true;
}
bool string(const char*& p, const char* end, std::string& value) {
    if (p == end || *p++ != '"') return false;
    value.clear();
    while (p < end && value.size() <= 4096) {
        unsigned char c = (unsigned char)*p++;
        if (c == '"') return true;
        if (c < 32) return false;
        if (c != '\\') { value += (char)c; continue; }
        if (p == end) return false;
        char escaped = *p++;
        if (escaped == '"' || escaped == '\\' || escaped == '/') value += escaped;
        else if (escaped == 'b') value += '\b';
        else if (escaped == 'f') value += '\f';
        else if (escaped == 'n') value += '\n';
        else if (escaped == 'r') value += '\r';
        else if (escaped == 't') value += '\t';
        else if (escaped == 'u') {
            unsigned cp;
            if (!hex4(p, end, cp)) return false;
            if (cp >= 0xd800 && cp <= 0xdbff) {
                if (end - p < 2 || *p++ != '\\' || *p++ != 'u') return false;
                unsigned low;
                if (!hex4(p, end, low) || low < 0xdc00 || low > 0xdfff) return false;
                cp = 0x10000 + ((cp - 0xd800) << 10) + low - 0xdc00;
            } else if (cp >= 0xdc00 && cp <= 0xdfff) return false;
            if (cp == 0) return false;
            utf8_add(value, (int)cp);
        } else return false;
    }
    return false;
}
bool parse(const char* data, size_t size, State& out) {
    if (!data || size > 16384) return false;
    const char* p = data;
    const char* end = p + size;
    State value;
    space(p, end);
    if (p == end || *p++ != '{') return false;
    bool first = true;
    while (true) {
        space(p, end);
        if (p < end && *p == '}') { ++p; break; }
        if (!first) { if (p == end || *p++ != ',') return false; space(p, end); }
        first = false;
        std::string key, content;
        if (!string(p, end, key)) return false;
        space(p, end);
        if (p == end || *p++ != ':') return false;
        space(p, end);
        if (p < end && *p == '"') {
            if (!string(p, end, content)) return false;
            if (key == "server") value.server = content;
            else if (key == "slot") value.slot = content;
            else if (key == "room") value.room = content;
            else if (key == "state") value.phase = content;
            else if (key == "error_code") value.error = content;
            else if (key == "language") value.language = content;
        } else {
            const char* start = p;
            while (p < end && *p != ',' && *p != '}' && *p != ' ' && *p != '\n' && *p != '\r' && *p != '\t') ++p;
            std::string scalar(start, p);
            if (scalar != "true" && scalar != "false" && scalar != "null") return false;
            if (key == "has_password") value.password = scalar == "true";
            else if (key == "auto_connect") value.automatic = scalar == "true";
        }
    }
    space(p, end);
    if (p != end) return false;
    out = std::move(value);
    return true;
}

Bridge bridge() {
#ifdef _WIN32
    static Bridge fn = (Bridge)(void*)GetProcAddress(GetModuleHandleW(nullptr), "ootrr_ap_menu16");
    return fn;
#else
    return nullptr;
#endif
}
void poll(bool force = false) {
    const int64_t now = prof_now();
    if (!force && now < next_poll) return;
    next_poll = now + 250000000LL;
    Bridge fn = bridge();
    char buffer[16384] = {};
    int length = fn ? fn(0, nullptr, nullptr, 0, 0, buffer, sizeof buffer) : 0;
    State fresh;
    available = length > 0 && length < (int)sizeof buffer && parse(buffer, (size_t)length, fresh);
    if (!available) return;
    state = std::move(fresh);
    if (!loaded || (!dirty && !editing)) server = state.server, automatic = state.automatic;
    loaded = true;
}
const char* phase() {
    if (state.phase == "connected") return text("Connected", "Connecté");
    if (state.phase == "connecting") return text("Connecting…", "Connexion…");
    if (state.phase == "authenticating") return text("Signing in…", "Identification…");
    if (state.phase == "synchronizing") return text("Synchronizing…", "Synchronisation…");
    if (state.phase == "retrying") return text("Reconnecting…", "Reconnexion…");
    return text("Disconnected", "Déconnecté");
}
const char* error_text() {
    const std::string& code = local_error.empty() ? state.error : local_error;
    if (code == "wrong_room") return text("This server is hosting a different room.", "Ce serveur héberge une autre salle.");
    if (code == "wrong_slot") return text("The player does not match this prepared mod.", "Le joueur ne correspond pas à ce mod préparé.");
    if (code == "connection_refused" || code == "invalid_password") return text("Connection refused. Check the room and password.", "Connexion refusée. Vérifie la salle et le mot de passe.");
    if (code == "invalid_server") return text("Enter a server address and a port from 1 to 65535.", "Entre une adresse serveur et un port de 1 à 65535.");
    if (code == "credential_error") return text("The password could not be saved on this PC.", "Le mot de passe n’a pas pu être enregistré sur ce PC.");
    if (code == "settings_error") return text("Connection settings could not be saved.", "Les paramètres de connexion n’ont pas pu être enregistrés.");
    if (code == "unknown_item") return text("This room requires a newer client.", "Cette salle demande un client plus récent.");
    if (code == "connection_lost" || code == "connection_failed") return text("Server unavailable. Check its address and connection.", "Serveur indisponible. Vérifie son adresse et la connexion.");
    return "";
}
void finish(bool accept) {
    if (!accept) {
        if (field == 0) server = previous;
        else password = previous;
        dirty = previous_dirty;
        mode = previous_mode;
    } else {
        // Accepting an untouched empty password field must keep the encrypted
        // credential. A replacement is requested only by an actual edit.
        const bool modified = (field == 0 ? server : password) != previous;
        dirty = previous_dirty || modified;
        if (field == 1) mode = modified ? 1 : previous_mode;
    }
    erase(previous);
    editing = false;
    text_wanted.store(false, std::memory_order_relaxed);
}
void begin(int which) {
    field = which;
    previous = which == 0 ? server : password;
    previous_dirty = dirty;
    previous_mode = mode;
    editing = true;
    text_wanted.store(true, std::memory_order_relaxed);
    capitals = symbols = false;
    key_row = 1, key_col = 0;
    local_error.clear();
}
void leave() {
    if (editing) finish(false);
    erase(password);
    erase(previous);
    mode = 0;
    dirty = false;
}
void action(int which) {
    Bridge fn = bridge();
    if (!fn) return;
    char unused[16384] = {};
    int result = fn(which, server.c_str(), mode == 1 ? password.c_str() : "", mode, automatic ? 1 : 0, unused, sizeof unused);
    local_error = result == -1 ? "invalid_server" : result == -2 ? "invalid_password" : result == -3 ? "credential_error" : result == -4 ? "settings_error" : "";
    if (result > 0) {
        erase(password);
        mode = 0, dirty = false;
    }
    poll(true);
}

const char* key_chars(int row) {
    static const char* const letters[] = {"1234567890", "qwertyuiop", "asdfghjkl-", "zxcvbnm._:"};
    static const char* const marks[] = {"~!@#$%^&*(", ")-_=+[]{}\\", ":;'\",.<>/?", "`|01234567"};
    return symbols ? marks[row] : letters[row];
}
void key(int row, int col) {
    std::string& value = field == 0 ? server : password;
    if (row < 4) {
        unsigned char cp = (unsigned char)key_chars(row)[col];
        if (capitals && cp >= 'a' && cp <= 'z') cp -= 'a' - 'A';
        if (value.size() < (field == 0 ? 1024u : 1024u)) utf8_add(value, cp);
    } else {
        switch (col / 2) {
        case 0: capitals = !capitals; break;
        case 1: symbols = !symbols; break;
        case 2: if (value.size() < 1024) value += ' '; break;
        case 3: utf8_pop(value); break;
        case 4: finish(true); break;
        }
    }
}
void keyboard(ui::Ctx& c) {
    const float s = c.s, key_w = 62 * s, key_h = 48 * s, gap = 7 * s, pad = 24 * s;
    const float w = 10 * key_w + 9 * gap + 2 * pad, h = 5 * (key_h + gap) + 100 * s;
    const float x = (c.w - w) * 0.5f, y = std::max(banner_h(c) + 8 * s, ui::prompt_bar_top(c) - h - 12 * s);
    dim_page(c, ui::rgba(8, 5, 2, 120));
    ui::box(c, ImVec2(x, y), ImVec2(x + w, y + h));
    const std::string& value = field == 0 ? server : password;
    const std::string shown = field == 0 ? value : std::string(std::min(value.size(), size_t(48)), '*');
    const ImVec2 a(x + pad, y + pad), b(x + w - pad, y + 70 * s);
    ui::value_plate(c, a, b, true);
    c.d->PushClipRect(a, b, true);
    ui::text_mid(c, c.f.body, 20 * s, a.x + 12 * s, (a.y + b.y) * 0.5f, ui::kInk, shown.empty() ? text("Enter text", "Saisir du texte") : shown.c_str());
    c.d->PopClipRect();
    for (int row = 0; row < 5; ++row) {
        for (int col = 0; col < 10; col += row == 4 ? 2 : 1) {
            const float width = (row == 4 ? 2 : 1) * (key_w + gap) - gap;
            const ImVec2 ka(x + pad + col * (key_w + gap), y + 82 * s + row * (key_h + gap));
            const ImVec2 kb(ka.x + width, ka.y + key_h);
            bool active = key_row == row && (row < 4 ? key_col == col : key_col / 2 == col / 2);
            ui::value_plate(c, ka, kb, active);
            char label[2] = {row < 4 ? key_chars(row)[col] : 0, 0};
            if (capitals && label[0] >= 'a' && label[0] <= 'z') label[0] -= 'a' - 'A';
            const char* actions[] = {"Aa", "#+=", text("Space", "Espace"), text("Erase", "Effacer"), text("Done", "Valider")};
            ui::text_mid_centre(c, row < 4 ? c.f.strong : c.f.body, (row < 4 ? 21 : 16) * s,
                                (ka.x + kb.x) * 0.5f, (ka.y + kb.y) * 0.5f, active ? ui::kValueOnInk : ui::kInk,
                                row < 4 ? label : actions[col / 2]);
            if (active) ui::glow(c, ka, kb);
            hits.add(ka.x, ka.y, kb.x, kb.y, menu_hit::kKey, row * 10 + col);
        }
    }
}
void draw(ui::Ctx& c) {
    poll();
    header_layer(c, true);
    ui::banner(c, banner_h(c));
    draw_tabs(c, TAB_ARCHIPELAGO, embed_open, true);
    header_layer(c, false);
    float cx0, cx1, hx0, hx1;
    bool narrow;
    columns(c, &cx0, &cx1, &hx0, &hx1, &narrow);
    std::string details = text("Player: ", "Joueur : ") + state.slot + "\n" + text("Room: ", "Salle : ") + state.room;
    std::string status = std::string(phase()) + (error_text()[0] ? "\n" + std::string(error_text()) : "");
    const char* help[] = {
        text("Server address, for example archipelago.gg:38281 or 127.0.0.1:38281.", "Adresse serveur, par exemple archipelago.gg:38281 ou 127.0.0.1:38281."),
        text("Enter a room password only when required. The saved password is never displayed.", "Entre un mot de passe seulement si la salle en demande un. Le mot de passe enregistré reste masqué."),
        text("Keep the saved password, replace it with your entry, or remove it.", "Conserver le mot de passe enregistré, le remplacer par la saisie ou le supprimer."),
        text("Connect at game startup. Changes are saved when you choose Connect.", "Se connecter au démarrage du jeu. Les changements sont enregistrés avec Connexion."),
        text("Save these settings and connect to this prepared room.", "Enregistrer ces paramètres et se connecter à cette salle préparée."),
        text("Disconnect from the server. Your save and received items are retained.", "Se déconnecter du serveur. La sauvegarde et les objets reçus sont conservés.")};
    caption(c, hx0, hx1, "Archipelago", available ? help[selected] : text("Enable a prepared Archipelago mod to connect.", "Active un mod Archipelago préparé pour te connecter."),
            status.c_str(), details.c_str(), 180 * c.s, false);
    const char* names[] = {text("Server", "Serveur"), text("Password", "Mot de passe"), text("Password action", "Mot de passe enregistré"),
                           text("Automatic connection", "Connexion automatique"), text("Connect", "Connexion"), text("Disconnect", "Déconnexion")};
    const char* modes[] = {text("Keep saved", "Conserver"), text("Save new", "Remplacer"), text("Remove saved", "Supprimer")};
    std::string values[] = {server.empty() ? text("Enter address", "Saisir l’adresse") : server,
        mode == 1 ? (password.empty() ? text("Enter password", "Saisir le mot de passe") : "********") : mode == 0 && state.password ? text("Saved ••••", "Enregistré ••••") : text("None", "Aucun"),
        modes[mode], automatic ? text("On", "Oui") : text("Off", "Non"), text("Connect", "Connexion"), text("Disconnect", "Déconnexion")};
    const float mid = ui::at(c, kListX, 0).x, x0 = mid - ui::lu(c, 912), x1 = mid + ui::lu(c, 912);
    const float h = ui::lu(c, 124), step = ui::lu(c, 170), top = ui::at(c, 0, 650).y;
    for (int i = 0; i < 6; ++i) {
        float y = top + i * step;
        bool on = i == selected;
        name_cell(c, ImVec2(x0, y), ImVec2(x1, y + h), names[i], on, false);
        ImVec2 a(mid + ui::lu(c, 98), y + ui::lu(c, 8)), b(mid + ui::lu(c, 902), y + h - ui::lu(c, 8));
        if (i >= 4) action_cell(c, a, b, values[i], on, !available);
        else choice_cell(c, a, b, values[i], on, i == 2 || i == 3, i == 2 || i == 3, !available);
        hits.add(x0, y, x1, y + h, menu_hit::kRow, i);
    }
    ui::Prompt prompts[] = {{ui::kConfirm, editing ? text("Type", "Saisir") : text("Select", "Choisir")},
                            {editing ? ui::kUpDown : ui::kTabs, editing ? text("Choose key", "Choisir une touche") : text("Category", "Catégorie")},
                            {ui::kBack, editing ? text("Cancel", "Annuler") : text("Back", "Retour")}};
    ui::prompt_bar(c, prompts, 3);
    if (editing) keyboard(c);
}
} // namespace ap_menu

bool ap_menu_available() { ap_menu::poll(); return ap_menu::available; }
bool ap_menu_editing() { return ap_menu::text_wanted.load(std::memory_order_relaxed); }
void ap_menu_watch() {
    if ((!open_now.load() || page != 0 || cur_tab != TAB_ARCHIPELAGO) && (ap_menu::editing || !ap_menu::password.empty() || ap_menu::dirty)) ap_menu::leave();
}
void ap_menu_tick(bool* press, bool& left, bool& right, bool mouse, bool moved, const MkwVkPointer& pointer, int mx, int my, bool& changed) {
    using namespace ap_menu;
    poll();
    menu_hit::Hit hit = mouse ? hits.at((float)mx, (float)my) : menu_hit::Hit{};
    if (editing) {
        std::vector<int> typed;
        { std::lock_guard<std::mutex> lock(mods_typed_mu); typed.swap(mods_typed); }
        std::string& value = field == 0 ? server : password;
        for (int cp : typed) {
            if (cp == 8) utf8_pop(value);
            else if (cp == 127) erase(value);
            else if (cp >= 32 && cp != 127 && value.size() < 1024) utf8_add(value, cp);
            changed = true;
        }
        bool clicked = mouse && (pointer.pressed & HOS_MOUSE_LEFT) && hit.part == menu_hit::kKey;
        if (mouse && (moved || clicked) && hit.part == menu_hit::kKey) key_row = hit.index / 10, key_col = hit.index % 10, changed = true;
        if (press[5] || (mouse && (pointer.pressed & HOS_MOUSE_RIGHT))) finish(false), changed = true;
        else if (clicked) key(key_row, key_col), changed = true;
        else if (press[7] && !pad_last) finish(true), changed = true;
        else {
            if (press[1] || press[2]) key_row = (key_row + (press[2] ? 1 : 4)) % 5, changed = true;
            int step = key_row == 4 ? 2 : 1;
            if (press[3] || press[4]) key_col = (key_col + (press[4] ? step : 10 - step)) % 10, changed = true;
            if (key_row == 4) key_col = key_col / 2 * 2;
            if (press[7]) key(key_row, key_col), changed = true;
        }
        left = right = false;
        return;
    }
    if (mouse) {
        if ((moved || pointer.pressed) && hit.part == menu_hit::kRow && hit.index >= 0 && hit.index < 6) selected = hit.index, changed = true;
        if (pointer.pressed & HOS_MOUSE_RIGHT) press[5] = true;
        if (pointer.pressed & HOS_MOUSE_LEFT) {
            if (hit.part == menu_hit::kTabPrev) left = true;
            else if (hit.part == menu_hit::kTabNext) right = true;
            else if (hit.part == menu_hit::kTab && hit.index == kGameTab) open_now = false, changed = true;
            else if (hit.part == menu_hit::kTab && hit.index >= 0 && hit.index < TAB_COUNT) cur_tab = hit.index, changed = true;
            else if (hit.part == menu_hit::kRow) press[7] = true;
        }
    }
    if (press[5]) { leave(); open_now = false; changed = true; return; }
    if (left || right) { leave(); tab_move(left ? -1 : 1); changed = true; return; }
    if (cur_tab != TAB_ARCHIPELAGO || !open_now.load()) return;
    if (press[1] || press[2]) selected = (selected + (press[2] ? 1 : 5)) % 6, changed = true;
    if (!available) return;
    if (press[7] || ((press[3] || press[4]) && (selected == 2 || selected == 3))) {
        if (selected < 2) begin(selected);
        else if (selected == 2) mode = (mode + (press[3] ? 2 : 1)) % 3, dirty = true;
        else if (selected == 3) automatic = !automatic, dirty = true;
        else action(selected == 4 ? 1 : 2);
        changed = true;
    }
}
