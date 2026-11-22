package main

import (
	"testing"
	"time"
)

func recoveryClient(t *testing.T) *Client {
	t.Helper()
	base := deathClient(t, false)
	cfg := base.cfg
	cfg.LocalItems, cfg.RewardMode = true, "all_locations"
	cfg.Checks = map[int]Location{
		20: {Flags: []uint32{30, 31}, Owner: cfg.Slot, Recipient: 1, ItemID: 10, Item: "Shield"}, // Two map variants share one reward.
		21: {Flags: []uint32{40}, Owner: "Ami", Recipient: 2, ItemID: 50, Item: "Other game reward"},
		22: {Flags: []uint32{50}, Owner: cfg.Slot, Recipient: 1, ItemID: 11, Item: "Rupee"},
	}
	cfg.RecoveryLocations = []int{20, 21, 22}
	s, err := newClient(cfg, base.root, base.logger)
	if err != nil {
		t.Fatal(err)
	}
	return s
}

func TestLocalRecoveryUsesDurableChecksAndLiveFlagsWithoutAPCursor(t *testing.T) {
	s := recoveryClient(t)
	s.opened([]uint32{30, 40}, false)
	restarted, err := newClient(s.cfg, s.root, s.logger)
	if err != nil {
		t.Fatal(err)
	}
	if restarted.ready {
		t.Fatal("fixture unexpectedly connected")
	}
	// Rewinding a save removes its flags. The journal survives restart, while
	// item recovery waits for the authenticated room's synchronization fence.
	if restarted.restoreLocation([]byte("0000")) != 0 {
		t.Fatal("recovery was enabled before authenticated synchronization")
	}
	nativePeer(t, restarted, nil)
	if got := restarted.restoreLocation([]byte("0000")); got != 20 {
		t.Fatalf("missing own reward was not recoverable: %d", got)
	}
	if got := restarted.restoreLocation([]byte("0000")); got != 20 {
		t.Fatal("request consumed recovery before the native flag committed")
	}
	if got := restarted.restoreLocation([]byte("1000")); got != 21 {
		t.Fatalf("committed own flag did not advance to the foreign flag-only event: %d", got)
	}
	if got := restarted.restoreLocation([]byte("0110")); got != 0 {
		t.Fatalf("alternate map flag or unearned location produced a second reward: %d", got)
	}
	if restarted.cfg.CursorHash != 17 || len(restarted.history) != 0 || len(restarted.seen) != 2 {
		t.Fatal("local recovery changed the AP cursor/history/check journal")
	}
	if got := restarted.restoreLocation([]byte("0000")); got != 20 {
		t.Fatal("a second actual save rollback was not recoverable")
	}
}

func TestLocalRecoveryRefusesMissingUnknownOrPartialSnapshots(t *testing.T) {
	s := recoveryClient(t)
	s.opened([]uint32{30}, false)
	s.ready = true
	for _, states := range []string{"", "0", "000", "00000", "?000", "0-00", "0020", "000\x00", "000\xff"} {
		if got := s.restoreLocation([]byte(states)); got != 0 {
			t.Fatalf("invalid live state %q produced recovery %d", states, got)
		}
	}
	s.cfg.LocalItems = false
	if s.restoreLocation([]byte("0000")) != 0 {
		t.Fatal("legacy room selected local recovery")
	}
	previous := active
	defer func() { active = previous }()
	active = nil
	if AP_Restore(nil, 0) != 0 {
		t.Fatal("recovery was exposed without an active room")
	}
	active = s
	if AP_Restore(nil, 4) != 0 || AP_Restore(nil, -1) != 0 || AP_Restore(nil, 4097) != 0 {
		t.Fatal("recovery accepted an invalid ABI buffer")
	}
}

func TestOldConfigsDoNotRequestUnregisteredRecoveryEvents(t *testing.T) {
	s := recoveryClient(t)
	cfg := s.cfg
	cfg.RecoveryLocations = nil
	legacy, err := newClient(cfg, s.root, s.logger)
	if err != nil {
		t.Fatal(err)
	}
	legacy.opened([]uint32{30}, false)
	legacy.ready = true
	if legacy.restoreLocation([]byte("0000")) != 0 {
		t.Fatal("old mod requested an event that was never registered")
	}
	for _, ids := range [][]int{{20, 20}, {999}, {-1}, {0x80000000}, {20, 21, 22, 23}} {
		cfg.RecoveryLocations = ids
		if _, err := newClient(cfg, t.TempDir(), s.logger); err == nil {
			t.Fatalf("accepted unknown or duplicate recovery event IDs: %v", ids)
		}
	}
	cfg = s.cfg
	cfg.RecoveryLocations = []int{22}
	cfg.Checks[22] = Location{}
	if _, err := newClient(cfg, t.TempDir(), s.logger); err == nil {
		t.Fatal("accepted a recovery event without its live completion flag")
	}
}

func TestExplicitDeferredResultSkipsOnlyThatLocationForTwoSeconds(t *testing.T) {
	s := recoveryClient(t)
	s.opened([]uint32{30, 40}, false)
	s.ready = true
	now := time.Now()
	if s.restoreLocationAt([]byte("0000"), now) != 20 ||
		s.restoreLocationAt([]byte("0000"), now.Add(time.Hour)) != 20 {
		t.Fatal("time alone consumed or deferred a recovery request")
	}
	s.deferRestore(20, now)
	if got := s.restoreLocationAt([]byte("0000"), now.Add(1999*time.Millisecond)); got != 21 {
		t.Fatalf("deferred refill blocked another available location: %d", got)
	}
	s.deferRestore(21, now)
	if got := s.restoreLocationAt([]byte("0000"), now.Add(1999*time.Millisecond)); got != 0 {
		t.Fatalf("deferred location retried before two seconds: %d", got)
	}
	if got := s.restoreLocationAt([]byte("0000"), now.Add(2*time.Second)); got != 20 {
		t.Fatalf("explicitly deferred location never became available: %d", got)
	}
	s.deferRestore(999, now)
	s.deferRestore(22, now) // Registered but never earned.
	if _, ok := s.recoveryDeferred[999]; ok {
		t.Fatal("unknown location acquired a cooldown")
	}
	if _, ok := s.recoveryDeferred[22]; ok {
		t.Fatal("unearned location acquired a cooldown")
	}
	previous := active
	defer func() { active = previous }()
	active = nil
	AP_RestoreDeferred(20)
}

func TestRecoveryMetadataIsOptionalForOldConfigsAndRequiredForRegisteredEvents(t *testing.T) {
	s := recoveryClient(t)
	cfg := s.cfg
	cfg.RecoveryLocations = nil
	cfg.Checks = map[int]Location{20: {Flags: []uint32{30}}}
	if _, err := newClient(cfg, t.TempDir(), s.logger); err != nil {
		t.Fatalf("legacy metadata-less configuration was rejected: %v", err)
	}
	cfg.RecoveryLocations = []int{20}
	for _, location := range []Location{
		{Flags: []uint32{30}},
		{Flags: []uint32{30}, Recipient: cfg.Player, ItemID: 999, Item: "Shield"},
		{Flags: []uint32{30}, Recipient: cfg.Player, ItemID: 10, Item: "Wrong item"},
	} {
		cfg.Checks[20] = location
		if _, err := newClient(cfg, t.TempDir(), s.logger); err == nil {
			t.Fatalf("registered recovery accepted incomplete or incorrect item metadata: %+v", location)
		}
	}
}
