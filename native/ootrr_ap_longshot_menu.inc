/* Longshot pinned native text fields, controller navigation and paste input.
   Connection actions reuse the verified ootrr_ap_menu16 host bridge. */
namespace longshot_ap {
void utf8_add(std::string& out, int cp) {
if(cp<0x80) out+=(char)cp; else if(cp<0x800) out+=(char)(0xc0|(cp>>6)),out+=(char)(0x80|(cp&63));
else if(cp<0x10000) out+=(char)(0xe0|(cp>>12)),out+=(char)(0x80|((cp>>6)&63)),out+=(char)(0x80|(cp&63));
else out+=(char)(0xf0|(cp>>18)),out+=(char)(0x80|((cp>>12)&63)),out+=(char)(0x80|((cp>>6)&63)),out+=(char)(0x80|(cp&63));
}

using Bridge = int (*)(int, const char*, const char*, int, int, char*, int);
struct State {
    std::string server, slot, room, phase = "disconnected", error, language = "en";
    bool password = false, automatic = true;
};
State state;
std::string local_error;
bool available = false, loaded = false, dirty = false;
int64_t next_poll = 0;

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


TextField server_field, password_field;
int password_mode=0, auto_connect=1;
std::string status;
const char* chars(const TextField&) { return " !\"#$%&'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`abcdefghijklmnopqrstuvwxyz{|}~"; }
Bridge bridge() {
#ifdef _WIN32
    static Bridge fn=(Bridge)(void*)GetProcAddress(GetModuleHandleW(nullptr),"ootrr_ap_menu16");
    return fn;
#else
    return nullptr;
#endif
}
void poll(bool active_edit) {
    auto now=prof_now(); if(now<next_poll) return; next_poll=now+250000000LL;
    char data[16384]={}; Bridge fn=bridge(); int n=fn?fn(0,nullptr,nullptr,0,0,data,sizeof data):0;
    State fresh; available=n>0 && n<(int)sizeof data && parse(data,(size_t)n,fresh);
    if(!available) {status=text("Enable a prepared Archipelago mod.","Active un mod Archipelago préparé.");return;}
    state=std::move(fresh);
    if(!loaded) {
        server_field.max=password_field.max=1024;
        server_field.pad_chars=password_field.pad_chars=chars;
        text_set(server_field,state.server.c_str()); auto_connect=state.automatic?1:0; loaded=true;
    }
    if(!active_edit && !dirty) {text_set(server_field,state.server.c_str());auto_connect=state.automatic?1:0;}
    const char* phase=state.phase=="connected"?text("Connected","Connecté"):
        state.phase=="connecting"?text("Connecting…","Connexion…"):
        state.phase=="authenticating"?text("Signing in…","Identification…"):
        state.phase=="synchronizing"?text("Synchronizing…","Synchronisation…"):
        state.phase=="retrying"?text("Reconnecting…","Reconnexion…"):text("Disconnected","Déconnecté");
    status=std::string(phase)+" | "+text("Player: ","Joueur : ")+state.slot+" | "+text("Room: ","Salle : ")+state.room;
    const auto& code=local_error.empty()?state.error:local_error;
    if(!code.empty()) {
        const char* why=code=="wrong_room"?text("Different room.","Salle différente."):
            code=="wrong_slot"?text("Different player.","Joueur différent."):
            code=="invalid_password" || code=="connection_refused"?text("Connection refused. Check the room password.","Connexion refusée. Vérifie le mot de passe."):
            code=="invalid_server"?text("Enter a valid server address and port.","Entre une adresse serveur et un port valides."):
            code=="credential_error"?text("The password could not be saved.","Le mot de passe n’a pas pu être enregistré."):
            code=="settings_error"?text("Connection settings could not be saved.","Les paramètres de connexion n’ont pas pu être enregistrés."):
            code=="unknown_item"?text("This room requires a newer client.","Cette salle demande un client plus récent."):
            text("Server unavailable. Check the address and connection.","Serveur indisponible. Vérifie l’adresse et la connexion.");
        status+=" | "+std::string(why);
    }
}
const char* server_apply() { dirty=true;local_error.clear();return nullptr; }
const char* password_apply() { if(password_field.len) password_mode=1;dirty=true;local_error.clear();return nullptr; }
const char* mode_text(int value) {return value==1?text("Save new","Remplacer"):value==2?text("Remove saved","Supprimer"):text("Keep saved","Conserver");}
const char* hint(int,int variant) { return variant>0?nullptr:status.c_str(); }
const char* row_hint(const Row& row) {
    if(strcmp(row.name,"AP Password")) return status.c_str();
    static std::string note;
    note=status+" | "+text("For non-ASCII passwords, use Connection in the app.","Pour un mot de passe accentué, utilise Connexion dans l’app.");
    return note.c_str();
}
void clear_password() { memset(password_field.text,0,sizeof password_field.text); password_field.len=password_field.caret=0; }
void action(int action) {
    Bridge fn=bridge(); if(!fn) return; char data[16384]={};
    int answer=fn(action,server_field.text,password_mode==1?password_field.text:"",password_mode,auto_connect,data,sizeof data);
    local_error=answer==-1?"invalid_server":answer==-2?"invalid_password":answer==-3?"credential_error":answer==-4?"settings_error":"";
    if(answer>0) {clear_password();password_mode=0;dirty=false;}
    next_poll=0;poll(false);
}
bool action_row(const Row& row) {return !strcmp(row.name,"AP Connect") || !strcmp(row.name,"AP Disconnect");}
void invoke(const Row& row) { action(!strcmp(row.name,"AP Connect")?1:2); }
} // namespace longshot_ap

/* The current Longshot menu model owns every AP row. Only the native text
   presenter is registered by the renderer shim; no monolithic row table. */
MENU_MODULE(archipelago) {
    menu::tab("gameplay").heading("archipelago", "Archipelago", menu::last())
        .row({.key="ootrr_ap_server", .label="AP Server",
              .help="Address of the prepared Archipelago room. Enter edits; controller and paste supported.",
              .kind=menu::Kind::Action, .shown=[] { return longshot_ap::available; },
              .hint=longshot_ap::hint, .verb="Edit", .unsaved=true})
        .row({.key="ootrr_ap_password", .label="AP Password",
              .help="Optional room password. Saved passwords are never shown. Use the application for non-ASCII passwords.",
              .kind=menu::Kind::Action, .shown=[] { return longshot_ap::available; },
              .hint=longshot_ap::hint, .verb="Edit", .unsaved=true})
        .row({.key="ootrr_ap_password_action", .label="AP Password action",
              .help="Keep, replace or remove the saved password when connecting.",
              .value=&longshot_ap::password_mode, .lo=0, .hi=2,
              .shown=[] { return longshot_ap::available; },
              .text=[](int v) { return std::string(longshot_ap::mode_text(v)); },
              .on_change=[](int) { longshot_ap::dirty=true; }, .unsaved=true})
        .row({.key="ootrr_ap_automatic", .label="AP Automatic connection",
              .help="Connect at startup. Saved when you choose AP Connect.",
              .kind=menu::Kind::Toggle, .value=&longshot_ap::auto_connect,
              .shown=[] { return longshot_ap::available; },
              .on_change=[](int) { longshot_ap::dirty=true; }, .unsaved=true})
        .row({.key="ootrr_ap_connect", .label="AP Connect",
              .help="Save these settings and connect to the prepared room.", .kind=menu::Kind::Action,
              .shown=[] { return longshot_ap::available; }, .hint=longshot_ap::hint,
              .on_activate=[] { longshot_ap::action(1); }, .verb="Connect", .unsaved=true})
        .row({.key="ootrr_ap_disconnect", .label="AP Disconnect",
              .help="Disconnect from this room.", .kind=menu::Kind::Action,
              .shown=[] { return longshot_ap::available; }, .hint=longshot_ap::hint,
              .on_activate=[] { longshot_ap::action(2); }, .verb="Disconnect", .unsaved=true});
}
