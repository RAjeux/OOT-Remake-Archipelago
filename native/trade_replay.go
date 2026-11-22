package main

/*
#include <stdint.h>
*/
import "C"

import "errors"

// Only an explicitly prepared full-trade mod can request these quiet events.
// A legacy profile has no capability and retains its ordinary receipt route.
func validateTradeReplay(c Config, recovery []int) error {
	if len(c.TradeReplayReceipts) == 0 {
		return nil
	}
	invalid := func() error { return errors.New("invalid adult trade replay configuration") }
	if !c.LocalItems || c.RewardMode != "all_locations" || !tokenForm.MatchString(c.Token) ||
		len(c.TradeReplayReceipts) != len(tradeReceiptBindings) {
		return invalid()
	}
	registered := make(map[int]bool, len(recovery))
	for _, id := range recovery {
		registered[id] = true
	}
	for _, binding := range tradeReceiptBindings {
		location := c.Checks[binding.LocationID]
		if c.TradeReplayReceipts[binding.ItemID] != binding.LocationID ||
			c.Items[binding.ItemID] != binding.ItemName || !registered[binding.LocationID] ||
			location.Name != binding.LocationName || len(location.Flags) != 1 || location.Flags[0] != binding.Flag {
			return invalid()
		}
	}
	return nil
}

// The journal describes completed exchanges even while an older save's flags
// are still absent. A spent token need not be granted again just to remove it
// later. Its separate ACK-only event leaves check/reward recovery untouched.
func (s *Client) replayTradeReceipt(cursor, item int) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.replayTradeReceiptLocked(cursor, item)
}

func (s *Client) replayTradeReceiptLocked(cursor, item int) bool {
	if !s.ready || cursor < 0 || cursor >= len(s.history) || item != s.history[cursor].Item {
		return false
	}
	location, supported := s.cfg.TradeReplayReceipts[item]
	// A memory-only observation can disappear if the process exits while an
	// older save is loaded. Advancing that save's receipt cursor silently is
	// safe only once the server or the local journal preserves consumption.
	return supported && (s.checked[location] || s.seen[location] && s.persistedRevision == s.revision)
}

//export AP_ReceiptReplay
func AP_ReceiptReplay(cursor, item C.int) C.int {
	if active != nil && active.replayTradeReceipt(int(cursor), int(item)) {
		return 1
	}
	return 0
}
