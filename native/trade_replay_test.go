package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestTradeReplayFallsBackUntilConsumptionProofIsDurable(t *testing.T) {
	s := tradeReplayClient(t)
	b := tradeReceiptBindings[0]
	s.ready = true
	s.history = []networkItem{{Item: b.ItemID, Player: 2}}
	journalPath := filepath.Join(s.root, "native-checks.json")
	// A directory at the journal's file path causes a real atomic-replace
	// failure while leaving observation and ordinary receipt delivery usable.
	if err := os.Mkdir(journalPath, 0700); err != nil {
		t.Fatal(err)
	}
	s.opened([]uint32{b.Flag}, false)
	if !s.seen[b.LocationID] || s.revision == s.persistedRevision {
		t.Fatal("test did not leave an observed exchange pending on disk")
	}
	s.checked[b.LocationID] = false // Presence in the map is not confirmation.
	if s.replayTradeReceipt(0, b.ItemID) {
		t.Fatal("an uncommitted exchange could silently discard an earned token")
	}
	previous := active
	defer func() { active = previous }()
	active = s
	AP_Applied(0)
	if len(s.notices) != 1 {
		t.Fatal("ordinary fallback receipt lost its physical-item notification")
	}
	if len(s.history) != 1 || len(s.seen) != 1 || s.checked[b.LocationID] ||
		s.revision == s.persistedRevision {
		t.Fatal("receipt query/application changed consumption or history state")
	}
	if err := os.Remove(journalPath); err != nil {
		t.Fatal(err)
	}
	if err := s.persistChecks(); err != nil {
		t.Fatal(err)
	}
	if !s.replayTradeReceipt(0, b.ItemID) {
		t.Fatal("a repaired durable journal did not permit quiet replay")
	}
	AP_Applied(0)
	if len(s.notices) != 1 {
		t.Fatal("a durably spent token announced another physical item")
	}
	if got := readJournal(t, s.root); len(got.Locations) != 1 || got.Locations[0] != b.LocationID {
		t.Fatal("persisted exchange differs from the observed consumption")
	}
}

func TestTradeReplayAcceptsServerConfirmationWithPendingJournal(t *testing.T) {
	s := tradeReplayClient(t)
	b := tradeReceiptBindings[0]
	s.ready = true
	s.history = []networkItem{{Item: b.ItemID}}
	s.rememberCheckLocked(b.LocationID)
	if s.replayTradeReceipt(0, b.ItemID) {
		t.Fatal("memory-only consumption proof allowed quiet replay")
	}
	s.checked[b.LocationID] = true
	if !s.replayTradeReceipt(0, b.ItemID) {
		t.Fatal("server-confirmed exchange did not allow quiet replay")
	}
	// Server history is independently durable, even if a local journal write
	// has not completed. Synchronization is still required for either route.
	s.ready = false
	if s.replayTradeReceipt(0, b.ItemID) {
		t.Fatal("server confirmation bypassed authenticated synchronization")
	}
	if !s.seen[b.LocationID] || s.revision == s.persistedRevision || len(s.history) != 1 {
		t.Fatal("quiet receipt query mutated consumption or history state")
	}
}

func tradeReplayClient(t *testing.T) *Client {
	t.Helper()
	base := deathClient(t, false)
	cfg := base.cfg
	cfg.Token = strings.Repeat("ab", 32)
	cfg.LocalItems, cfg.RewardMode = true, "all_locations"
	cfg.Checks = map[int]Location{}
	cfg.TradeReplayReceipts = map[int]int{}
	for _, b := range tradeReceiptBindings {
		cfg.Items[b.ItemID] = b.ItemName
		cfg.Checks[b.LocationID] = Location{Name: b.LocationName, Flags: []uint32{b.Flag},
			Recipient: 1, ItemID: 10, Item: "Shield", Owner: cfg.Slot}
		cfg.RecoveryLocations = append(cfg.RecoveryLocations, b.LocationID)
		cfg.TradeReplayReceipts[b.ItemID] = b.LocationID
	}
	s, err := newClient(cfg, base.root, base.logger)
	if err != nil {
		t.Fatal(err)
	}
	return s
}

func TestTradeReplayUsesEarnedHistoryWithoutMarkingRecoveredReward(t *testing.T) {
	s := tradeReplayClient(t)
	b := tradeReceiptBindings[0]
	s.history = []networkItem{{Item: b.ItemID, Player: 2, Location: 999}, {Item: 11, Player: 2}}
	s.opened([]uint32{b.Flag}, false)
	restarted, err := newClient(s.cfg, s.root, s.logger)
	if err != nil {
		t.Fatal(err)
	}
	restarted.history = append([]networkItem(nil), s.history...)
	if restarted.replayTradeReceipt(0, b.ItemID) {
		t.Fatal("receipt replay enabled before authenticated synchronization")
	}
	restarted.ready = true
	for range 3 {
		if !restarted.replayTradeReceipt(0, b.ItemID) {
			t.Fatal("spent token was not recognized from the durable completed exchange")
		}
	}
	if restarted.replayTradeReceipt(1, 11) || restarted.replayTradeReceipt(-1, b.ItemID) ||
		restarted.replayTradeReceipt(2, b.ItemID) || restarted.replayTradeReceipt(0, 11) {
		t.Fatal("wrong cursor/item or ordinary reward used a quiet trade entry")
	}
	states := []byte(strings.Repeat("0", len(restarted.flags)))
	if restarted.restoreLocation(states) != b.LocationID || len(restarted.history) != 2 ||
		len(restarted.seen) != 1 || len(restarted.checked) != 0 {
		t.Fatal("quiet receipt selection consumed or marked the still-missing check/reward")
	}
	previous := active
	defer func() { active = previous }()
	active = nil
	if AP_ReceiptReplay(0, 7303486) != 0 {
		t.Fatal("receipt replay available without an active profile")
	}
	active = restarted
	if AP_ReceiptReplay(0, 7303486) != 1 || AP_ReceiptReplay(1, 7303486) != 0 {
		t.Fatal("receipt replay ABI did not preserve the exact history index")
	}
	AP_Applied(0)
	if len(restarted.notices) != 0 {
		t.Fatal("quiet history replay announced a second physical item")
	}
	AP_Applied(1)
	if len(restarted.notices) != 1 {
		t.Fatal("ordinary receipt notification was suppressed")
	}
}

func TestTradeReplayRequiresCompletedExchangeAndPreparedCapability(t *testing.T) {
	s := tradeReplayClient(t)
	b := tradeReceiptBindings[0]
	s.ready = true
	s.history = []networkItem{{Item: b.ItemID}}
	if s.replayTradeReceipt(0, b.ItemID) {
		t.Fatal("unspent token was suppressed")
	}
	s.opened([]uint32{b.Flag}, false)
	if !s.replayTradeReceipt(0, b.ItemID) {
		t.Fatal("completed exchange did not suppress its spent token")
	}
	s.cfg.TradeReplayReceipts = nil
	if s.replayTradeReceipt(0, b.ItemID) {
		t.Fatal("older mod requested an unregistered event")
	}
	s.cfg.RecoveryLocations = nil
	if _, err := newClient(s.cfg, t.TempDir(), s.logger); err != nil {
		t.Fatal("legacy profile was rejected without an optional capability", err)
	}
}

func TestTradeReplayRejectsIncompleteOrUnboundConfiguration(t *testing.T) {
	s := tradeReplayClient(t)
	b := tradeReceiptBindings[0]
	encoded, _ := json.Marshal(s.cfg)
	cases := map[string]func(*Config){
		"partial":     func(c *Config) { delete(c.TradeReplayReceipts, b.ItemID) },
		"wrong item":  func(c *Config) { delete(c.TradeReplayReceipts, b.ItemID); c.TradeReplayReceipts[999] = b.LocationID },
		"wrong check": func(c *Config) { c.TradeReplayReceipts[b.ItemID] = 999 },
		"wrong name": func(c *Config) {
			row := c.Checks[b.LocationID]
			row.Name = "Another check"
			c.Checks[b.LocationID] = row
		},
		"wrong flag": func(c *Config) {
			row := c.Checks[b.LocationID]
			row.Flags = []uint32{123}
			c.Checks[b.LocationID] = row
		},
		"wrong item name":  func(c *Config) { c.Items[b.ItemID] = "Another item" },
		"no recovery":      func(c *Config) { c.RecoveryLocations = nil },
		"wrong room token": func(c *Config) { c.Token = "unbound" },
		"legacy mode":      func(c *Config) { c.LocalItems = false; c.RewardMode = "all_chest_rewards"; c.RecoveryLocations = nil },
	}
	for name, mutate := range cases {
		t.Run(name, func(t *testing.T) {
			var cfg Config
			if err := json.Unmarshal(encoded, &cfg); err != nil {
				t.Fatal(err)
			}
			mutate(&cfg)
			if _, err := newClient(cfg, t.TempDir(), s.logger); err == nil {
				t.Fatal("invalid quiet receipt metadata was accepted")
			}
		})
	}
}
