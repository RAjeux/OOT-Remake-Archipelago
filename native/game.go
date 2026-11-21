package main

/*
#include <stdint.h>
*/
import "C"
import (
	"encoding/binary"
	"log"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"time"
	"unicode/utf8"
	"unsafe"
)

var active *Client
var tokenForm = regexp.MustCompile("^[a-f0-9]{64}$")

//export AP_SetLanguage
func AP_SetLanguage(code *C.char) {
	if code == nil {
		setHostLanguage("")
		return
	}
	setHostLanguage(C.GoString(code))
}

//export AP_Start
func AP_Start(rootText, tokenText *C.char) C.int {
	root, token := C.GoString(rootText), C.GoString(tokenText)
	if active != nil || !tokenForm.MatchString(token) {
		return 0
	}
	out, e := os.OpenFile(filepath.Join(root, "archipelago-jeu.log"), os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0600)
	if e != nil {
		return 0
	}
	logbook := log.New(out, "", log.LstdFlags)
	c, e := loadConfig(root, token)
	if e != nil {
		logbook.Print(e)
		out.Close()
		return 0
	}
	c.Language = runtimeLanguage(c.Language)
	s, e := newClient(c, root, logbook)
	if e != nil {
		logbook.Print(e)
		out.Close()
		return 0
	}
	pw, e := password(c.ProtectedPassword)
	if e != nil {
		logbook.Print("Cannot read the local password; update it in the Archipelago menu.")
	}
	s.initializePassword(pw, e)
	if e = lockProfile(root); e != nil {
		logbook.Print("Another client is already using this room.")
		out.Close()
		return 0
	}
	active = s
	if e = saveLanguage(root, s.cfg.Language); e != nil {
		logbook.Print("Cannot publish the display language: ", e)
	}
	s.notice("active", c.Slot)
	go s.run()
	go s.readSaves()
	return 1
}

//export AP_Flags
func AP_Flags(dest *C.uint32_t, cap C.int) C.int {
	if active == nil || dest == nil || int(cap) < len(active.flags) {
		return 0
	}
	b := unsafe.Slice((*uint32)(unsafe.Pointer(dest)), int(cap))
	copy(b, active.flags)
	return C.int(len(active.flags))
}

//export AP_Opened
func AP_Opened(a *C.uint32_t, n C.int, goal C.int) {
	if active != nil && a != nil && n >= 0 && n <= 4096 {
		active.opened(unsafe.Slice((*uint32)(unsafe.Pointer(a)), int(n)), goal != 0)
	}
}

//export AP_DeathLink
func AP_DeathLink(state C.int) C.int {
	if active != nil && active.deathState(int(state), time.Now()) {
		return 1
	}
	return 0
}

//export AP_EventDelivery
func AP_EventDelivery() C.int {
	if active != nil && (active.cfg.RewardMode == "all_chest_rewards" || active.cfg.RewardMode == "all_locations") {
		return 1
	}
	return 0
}

//export AP_Next
func AP_Next(cursor C.int) C.int {
	s := active
	if s == nil {
		return 0
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	i := int(cursor)
	if !s.ready || i < 0 || i >= len(s.history) {
		return 0
	}
	return C.int(s.history[i].Item)
}

//export AP_Applied
func AP_Applied(index C.int) {
	s := active
	if s == nil {
		return
	}
	s.mu.Lock()
	i := int(index)
	if i < 0 || i >= len(s.history) {
		s.mu.Unlock()
		return
	}
	it := s.history[i]
	who := s.names[it.Player]
	if who == "" {
		who = "Archipelago"
	}
	s.mu.Unlock()
	s.noticeReceived(it.Item, who)
}

//export AP_Cursor
func AP_Cursor() C.uint32_t {
	if active == nil {
		return 0
	}
	return C.uint32_t(active.cfg.CursorHash)
}

//export AP_Note
func AP_Note(dest *C.char, cap C.int) C.int {
	s := active
	if s == nil || dest == nil || cap < 4 || cap > 4096 {
		return 0
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if len(s.notices) == 0 {
		return 0
	}
	msg := s.notices[0]
	if len(msg) >= int(cap) {
		cut := int(cap) - 1
		for cut > 0 && !utf8.ValidString(msg[:cut]) {
			cut--
		}
		if word := strings.LastIndexByte(msg[:cut], ' '); word > cut/2 {
			cut = word
		}
		s.notices[0] = strings.TrimSpace(msg[cut:])
		msg = msg[:cut]
	} else {
		s.notices = s.notices[1:]
	}
	dst := unsafe.Slice((*byte)(unsafe.Pointer(dest)), int(cap))
	copy(dst, msg)
	dst[len(msg)] = 0
	return 1
}

// Read only committed files in the seed's own profile. This also recovers checks
// collected before a disconnect or in a version that only exposed them on save.
func (s *Client) readSaves() {
	type stamp struct {
		size int64
		time time.Time
	}
	last := map[string]stamp{}
	for range time.Tick(2 * time.Second) {
		paths, _ := filepath.Glob(filepath.Join(s.root, "user", "save", "*", "slot_??", "progress.sav"))
		for _, p := range paths {
			st, e := os.Stat(p)
			if e != nil || st.Size() > 64<<20 {
				continue
			}
			sig := stamp{st.Size(), st.ModTime()}
			if last[p] == sig {
				continue
			}
			b, e := os.ReadFile(p)
			if e != nil {
				continue
			}
			fs, win, ok := s.saved(b)
			if ok {
				s.opened(fs, win)
				last[p] = sig
			}
		}
	}
}
func (s *Client) saved(b []byte) ([]uint32, bool, bool) {
	if len(b) < 56 || binary.LittleEndian.Uint32(b) != 0x01020304 {
		return nil, false, false
	}
	word := func(i int) uint32 { return binary.LittleEndian.Uint32(b[i:]) }
	end := int(word(8))
	if end < 48 || end > len(b)-8 || (end-40)%8 != 0 || word(end-8) != 0xa3db7114 {
		return nil, false, false
	}
	k := int(word(end - 4))
	if k < end || k > len(b)-8 {
		return nil, false, false
	}
	complete, belongs := false, false
	var fs []uint32
	for i := 40; i < end-8; i += 8 {
		h, v := word(i), word(i+4)
		if h == s.cfg.CursorHash {
			belongs = true
		}
		if _, ok := s.byFlag[h]; ok && v == 1 {
			fs = append(fs, h)
		}
		if h == 0x746f47c0 && v == 0x4c0a63f4 || h == 0x641e0375 && v > 0 && v < 0x80000000 {
			complete = true
		}
	}
	return fs, complete, belongs
}
func main() {}
