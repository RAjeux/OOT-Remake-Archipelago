#include <algorithm>
#include <cassert>
#include <cstdint>
#include <cstring>
#include <string>
#include <utility>

struct TextField { char text[1025]{}; int len=0,caret=0,max=1024; bool(*allow)(char)=nullptr; const char*(*pad_chars)(const TextField&)=nullptr; };
struct Row { const char* name; };
static int64_t clock_now=1000000000;
int64_t prof_now() { return clock_now; }
void text_set(TextField& field,const char* value) {
    std::snprintf(field.text,sizeof field.text,"%.*s",field.max,value);
    field.len=field.caret=(int)std::strlen(field.text);
}
static std::string response;
static std::string sent_server,sent_password;
static int result=1,last_action=0,last_mode=-1,last_auto=-1;
int fixture_bridge(int action,const char* server,const char* password,int mode,int automatic,char* out,int cap) {
    if(action) {
        last_action=action;sent_server=server?server:"";sent_password=password?password:"";last_mode=mode;last_auto=automatic;
        return result;
    }
    if((int)response.size()>=cap) return 0;
    std::memcpy(out,response.c_str(),response.size()+1);return (int)response.size();
}
void* fixture_module(void*) { return nullptr; }
void* fixture_lookup(void*,const char*) { return (void*)&fixture_bridge; }
#ifndef _WIN32
#define _WIN32
#endif
#define GetModuleHandleW fixture_module
#define GetProcAddress fixture_lookup
#include "ootrr_ap_hookshot_menu.inc"

void fixture_status(const char* server,bool automatic,const char* language="en") {
    response=std::string("{\"server\":\"")+server+"\",\"slot\":\"Link\",\"room\":\"Fixture\",\"state\":\"connected\",\"error_code\":\"\",\"language\":\""+language+"\",\"has_password\":true,\"auto_connect\":"+(automatic?"true":"false")+"}";
    hookshot_ap::next_poll=0;
}
int main() {
    using namespace hookshot_ap;
    fixture_status("localhost:1234",false);poll(false);
    assert(available && std::string(server_field.text)=="localhost:1234" && auto_connect==0);
    assert(state.phase=="connected" && state.password);
    // A separate desktop connection window changes the running client's settings.
    fixture_status("localhost:4321",true);poll(false);
    assert(std::string(server_field.text)=="localhost:4321" && auto_connect==1);
    text_set(server_field,"edited:5555");auto_connect=0;dirty=true;
    fixture_status("desktop:6666",true);poll(false);
    assert(std::string(server_field.text)=="edited:5555" && auto_connect==0);
    dirty=false;fixture_status("desktop:7777",true);poll(true);
    assert(std::string(server_field.text)=="edited:5555");
    text_set(password_field,"temporary secret");password_apply();
    assert(password_mode==1 && dirty);
    action(1);
    assert(last_action==1 && sent_server=="edited:5555" && sent_password=="temporary secret" && last_mode==1 && last_auto==0);
    assert(password_mode==0 && !dirty && password_field.len==0);
    for(char byte:password_field.text) assert(byte==0);
    // Immediate input errors are shown without waiting for a network failure.
    result=-1;fixture_status("desktop:7777",true,"fr");action(1);
    assert(local_error=="invalid_server" && hookshot_ap::status.find("valides")!=std::string::npos);
    assert(std::string(mode_text(0))=="Conserver");
    assert(std::string(row_hint(Row{"AP Password"})).find("accentué")!=std::string::npos);
    assert(std::strlen(chars(server_field))==95);
    for(int character=32;character<=126;character++) assert(std::strchr(chars(server_field),character));
    State malformed;
    const char broken[]={"{\"state\":\"connected\""};
    assert(!parse(broken,sizeof broken-1,malformed));
    result=1;action(2);assert(last_action==2 && sent_password.empty());
}
