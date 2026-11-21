package main

import (
	"testing"
	"time"
)

func TestEventDeliveryRequiresExplicitRoomMode(t *testing.T) {
	previous := active
	defer func() { active = previous }()
	active = nil
	if AP_EventDelivery() != 0 {
		t.Fatal("no active room selected event delivery")
	}
	active = deathClient(t, false)
	for _, mode := range []string{"", "legacy", "invalid", "all_chest_rewards", "all_locations"} {
		active.cfg.RewardMode = mode
		want := mode == "all_chest_rewards" || mode == "all_locations"
		if (AP_EventDelivery() == 1) != want {
			t.Fatalf("wrong delivery mode for %q", mode)
		}
	}
}

func TestRoomRewardModeMustMatchInstalledMod(t *testing.T) {
	s := deathClient(t, false)
	m := wire{Slot: 1}
	m.SlotData.Token, m.SlotData.Protocol, m.SlotData.Checks = "token", 1, []int{20}
	for _, test := range []struct {
		mod, room string
		want      bool
	}{
		{"", "", true}, {"legacy_gear", "", true}, {"", "legacy_gear", true},
		{"all_chest_rewards", "all_chest_rewards", true},
		{"legacy_gear", "all_chest_rewards", false}, {"all_chest_rewards", "", false},
		{"all_chest_rewards", "legacy_gear", false}, {"legacy_gear", "unknown", false},
		{"all_locations", "all_chest_rewards", false}, {"all_chest_rewards", "all_locations", false},
	} {
		s.cfg.RewardMode, m.SlotData.RewardMode = test.mod, test.room
		if s.valid(m) != test.want {
			t.Fatalf("mod %q / server %q: want valid=%v", test.mod, test.room, test.want)
		}
	}
	s.cfg.RewardMode, m.SlotData.RewardMode = "all_locations", "all_locations"
	s.cfg.LocalItems = true
	if s.valid(m) {
		t.Fatal("a room missing the local-items flag accepted a new local-reward mod")
	}
	m.SlotData.LocalItems = true
	if !s.valid(m) {
		t.Fatal("matching new local-reward room was rejected")
	}
}

func TestLocalItemsConnectUsesFilteredHistory(t *testing.T) {
	for _, local := range []bool{false, true} {
		s := deathClient(t, false)
		if local {
			s.cfg.RewardMode, s.cfg.LocalItems = "all_locations", true
		}
		history := []networkItem{{Item: 10, Player: 2, Location: 21}}
		var handling int
		peer, _ := nativePeerHandling(t, s, history, &handling)
		want := 7
		if local {
			want = 5
		}
		if handling != want {
			t.Fatalf("LocalItems=%v advertised handling=%d, want %d", local, handling, want)
		}
		peer.Close()
		// The filtered stream has its own index. A fresh host reconstructs that
		// exact prefix; it must not reserve holes for locally granted items.
		restarted := deathClient(t, false)
		restarted.cfg.RewardMode, restarted.cfg.LocalItems = s.cfg.RewardMode, local
		history = append(history, networkItem{Item: 11, Player: 2, Location: 22})
		_, _ = nativePeerHandling(t, restarted, history, &handling)
		restarted.mu.Lock()
		if len(restarted.history) != 2 || restarted.history[1].Item != 11 {
			t.Fatal("filtered history acquired a cursor hole after restart")
		}
		restarted.mu.Unlock()
	}
}

func TestShopPurchaseFlagUsesGenericLocationChecks(t *testing.T) {
	cfg := deathClient(t, false).cfg
	cfg.RewardMode, cfg.LocalItems = "all_locations", true
	cfg.Checks[148] = Location{Name: "KF Shop Item 8", Flags: []uint32{9918}}
	s, err := newClient(cfg, t.TempDir(), deathClient(t, false).logger)
	if err != nil {
		t.Fatal(err)
	}
	peer, _ := nativePeer(t, s, nil)
	s.opened([]uint32{9918}, false)
	var packets []struct {
		Cmd       string
		Locations []int
	}
	if err := peer.ReadJSON(&packets); err != nil {
		t.Fatal(err)
	}
	if len(packets) != 1 || packets[0].Cmd != "LocationChecks" || len(packets[0].Locations) != 1 || packets[0].Locations[0] != 148 {
		t.Fatalf("a shop flag did not produce the expected check: %+v", packets)
	}
	if err := peer.WriteJSON([]packet{{"cmd": "RoomUpdate", "checked_locations": []int{148}}}); err != nil {
		t.Fatal(err)
	}
	deadline := time.Now().Add(time.Second)
	for {
		s.mu.Lock()
		checked := s.checked[148]
		s.mu.Unlock()
		if checked {
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("shop check acknowledgement was not consumed")
		}
		time.Sleep(time.Millisecond)
	}
}
