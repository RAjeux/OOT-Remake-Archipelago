package main

import (
	"bytes"
	"encoding/json"
	"log"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
	"unicode/utf8"
)

func localizedClient(t *testing.T, language string) (*Client, *bytes.Buffer) {
	t.Helper()
	cfg := deathClient(t, true).cfg
	cfg.Language = language
	cfg.ItemNames = map[int]map[string]string{
		10: {"en": "Shield", "fr": "Bouclier"},
		11: {"en": "Rupee", "fr": "Rubis"},
	}
	var diagnostic bytes.Buffer
	s, err := newClient(cfg, t.TempDir(), log.New(&diagnostic, "", 0))
	if err != nil {
		t.Fatal(err)
	}
	return s, &diagnostic
}

func TestDisplayLanguageSelectionAndFallback(t *testing.T) {
	for _, test := range []struct{ input, want string }{
		{"fr", "fr"}, {"fr-FR", "fr"}, {"fr-CA", "fr"}, {"FR_ca", "fr"},
		{"EUfr", "fr"}, {"USfr", "fr"}, {" en-US ", "en"}, {"en-GB", "en"},
		{"de", "en"}, {"ja", "en"}, {"", "en"}, {"unknown", "en"}, {"fr-invalid", "en"},
	} {
		if got := normalizeLanguage(test.input); got != test.want {
			t.Errorf("language %q: got %q, want %q", test.input, got, test.want)
		}
	}
	previous := hostLanguage.Load()
	defer hostLanguage.Store(previous)
	hostLanguage.Store(0)
	if runtimeLanguage("fr-CA") != "fr" || runtimeLanguage("") != "en" {
		t.Fatal("the legacy configuration fallback was lost")
	}
	setHostLanguage("en-US")
	if runtimeLanguage("fr") != "en" {
		t.Fatal("the game's actual English language did not override setup French")
	}
	setHostLanguage("fr")
	if runtimeLanguage("en") != "fr" {
		t.Fatal("the game's actual French language did not override setup English")
	}
	setHostLanguage("unsupported")
	if runtimeLanguage("fr") != "en" {
		t.Fatal("an unsupported game language did not fall back to English")
	}
	t.Setenv("LANG", "fr_FR.UTF-8")
	s, _ := localizedClient(t, "")
	if s.cfg.Language != "en" {
		t.Fatal("the operating system locale overrode the game/configuration language")
	}
}

func TestLocalizedNoticesKeepEnglishDiagnosticsAndProtocolNames(t *testing.T) {
	for _, language := range []string{"en", "fr", "ja"} {
		s, diagnostic := localizedClient(t, language)
		s.notice("active", s.cfg.Slot)
		s.noticeReceived(10, "Ami")
		s.noticeLocation(Location{Item: "Rupee", Owner: "Ami", Game: s.cfg.Game})
		s.noticeLocation(Location{Item: "Foreign Game Sword", Owner: "Ami", Game: "Other Game"})
		want := []string{"Archipelago mod active · Zelda", "Shield received from Ami", "Rupee sent to Ami", "Foreign Game Sword sent to Ami"}
		if language == "fr" {
			want = []string{"Mod Archipelago actif · Zelda", "Bouclier reçu de Ami", "Rubis envoyé à Ami", "Foreign Game Sword envoyé à Ami"}
		}
		for index, notice := range s.notices {
			if notice != want[index] || !utf8.ValidString(notice) {
				t.Fatalf("language %q notice %d: got %q, want %q", language, index, notice, want[index])
			}
		}
		if s.cfg.Items[10] != "Shield" || s.cfg.Items[11] != "Rupee" || s.cfg.Token != "token" || s.cfg.CursorHash != 17 {
			t.Fatal("display localization changed protocol names, the room or cursor")
		}
		if !strings.Contains(diagnostic.String(), "Shield received from Ami") ||
			strings.Contains(diagnostic.String(), "Bouclier") || strings.Contains(diagnostic.String(), "envoyé") {
			t.Fatalf("developer diagnostics were translated: %s", diagnostic.String())
		}
		delete(s.cfg.ItemNames[10], "fr")
		if s.itemName(10) != "Shield" {
			t.Fatal("a missing French item name did not fall back to English")
		}
		s.cfg.ItemNames = nil
		if s.itemName(10) != "Shield" {
			t.Fatal("a legacy session without localized labels lost its item name")
		}
	}
}

func TestOutgoingItemNamesRequireRecipientGame(t *testing.T) {
	s, _ := localizedClient(t, "fr")
	s.cfg.Items[10] = "Bow"
	s.cfg.ItemNames[10] = map[string]string{"en": "Bow", "fr": "Arc"}
	for _, test := range []struct {
		game, owner, want string
	}{
		{"Dark Souls III", "Ami", "Bow"}, {"Other Game", "Ami", "Bow"}, {"", "Ami", "Bow"},
		{"Ocarina of Time Remake", "Ami", "Arc"}, {"Ocarina of Time Remake (Triforce)", "Ami", "Arc"},
		{"", s.cfg.Slot, "Arc"},
	} {
		s.noticeLocation(Location{Item: "Bow", Owner: test.owner, Game: test.game})
		want := test.want + " envoyé à " + test.owner
		if got := s.notices[len(s.notices)-1]; got != want {
			t.Errorf("recipient game %q / slot %q: got %q, want %q", test.game, test.owner, got, want)
		}
	}
	if s.cfg.Items[10] != "Bow" {
		t.Fatal("outgoing display names changed the canonical item catalogue")
	}
}

func TestDeathLinkUsesGameLanguageAndPreservesRemoteCauses(t *testing.T) {
	for _, language := range []string{"en", "fr"} {
		s, _ := localizedClient(t, language)
		s.ready = true
		now := time.Now()
		s.deathState(0, now)
		s.deathState(1, now)
		want := "Zelda died in Zelda."
		if language == "fr" {
			want = "Zelda est mort dans Zelda."
		}
		if s.death.outgoing == nil || s.death.outgoing.Source != "Zelda" || s.death.outgoing.Cause != want {
			t.Fatalf("wrong localized DeathLink payload: %+v", s.death.outgoing)
		}
		s.deathState(0, now)
		s.receiveDeath(bounced("Ami", 103), now)
		if !s.deathState(0, now) || s.notices[len(s.notices)-1] != s.text("death_received", "Ami") {
			t.Fatal("a remote death without a cause did not use the game language")
		}
		s.deathState(1, now)
		s.deathState(0, now)
		remote := bounced("Ami", 104)
		remote.Data = json.RawMessage(`{"time":104,"source":"Ami","cause":"Ami: original player message"}`)
		s.receiveDeath(remote, now)
		if !s.deathState(0, now) || s.notices[len(s.notices)-1] != "DeathLink · Ami: original player message" {
			t.Fatal("a remote player's custom cause was rewritten")
		}
	}
}

func TestLanguageMarkerIsNormalizedAndReplaceable(t *testing.T) {
	root := t.TempDir()
	for _, language := range []string{"fr-CA", "de"} {
		if err := saveLanguage(root, language); err != nil {
			t.Fatal(err)
		}
		raw, err := os.ReadFile(filepath.Join(root, "language.json"))
		if err != nil {
			t.Fatal(err)
		}
		var marker map[string]string
		if json.Unmarshal(raw, &marker) != nil || len(marker) != 1 || marker["language"] != normalizeLanguage(language) {
			t.Fatalf("wrong language marker: %s", raw)
		}
	}
}

func TestLocalizedReconnectRetainsCursorAndItemIDs(t *testing.T) {
	previous := active
	defer func() { active = previous }()
	for _, language := range []string{"en", "fr"} {
		s, _ := localizedClient(t, language)
		active = s
		history := []networkItem{{Item: 10, Player: 2, Location: 21}, {Item: 11, Player: 2, Location: 22}}
		peer, _ := nativePeer(t, s, history)
		if AP_Cursor() != 17 || AP_Next(0) != 10 || AP_Next(1) != 11 || AP_Next(2) != 0 {
			t.Fatal("localized synchronization changed the cursor or delivery indices")
		}
		AP_Applied(0)
		s.mu.Lock()
		last := s.notices[len(s.notices)-1]
		s.mu.Unlock()
		if !strings.Contains(last, s.itemName(10)) {
			t.Fatal("the applied receipt did not use its localized display name")
		}
		peer.Close()
		deadline := time.Now().Add(time.Second)
		for {
			s.mu.Lock()
			ready := s.ready
			s.mu.Unlock()
			if !ready {
				break
			}
			if time.Now().After(deadline) {
				t.Fatal("localized session did not disconnect")
			}
			time.Sleep(time.Millisecond)
		}
		_, _ = nativePeer(t, s, history)
		if s.cfg.Language != language || AP_Cursor() != 17 || AP_Next(1) != 11 || AP_Next(2) != 0 {
			t.Fatal("reconnection changed language or replayed an additional delivery")
		}
	}
}
