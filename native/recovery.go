package main

/*
#include <stdint.h>
*/
import "C"

import (
	"time"
	"unsafe"
)

// A recovery event is registered for an exact room/location. Its native recipe
// restores that location's flags and, when owned locally, its reward together.
// It never advances the filtered ReceivedItems cursor. The game owns pending
// requests and only retries an accepted event after a real context change.
func (s *Client) restoreLocation(states []byte) int {
	return s.restoreLocationAt(states, time.Now())
}

func (s *Client) restoreLocationAt(states []byte, now time.Time) int {
	s.mu.Lock()
	defer s.mu.Unlock()
	if !s.ready || !s.cfg.LocalItems || s.cfg.RewardMode != "all_locations" || len(s.recoveryIDs) == 0 || len(states) != len(s.flags) {
		return 0
	}
	opened := map[int]bool{}
	for index, value := range states {
		if value != '0' && value != '1' {
			return 0 // Missing/unloaded flags never mean an old unopened check.
		}
		if value == '1' {
			for _, id := range s.byFlag[s.flags[index]] {
				opened[id] = true
			}
		}
	}
	for _, id := range s.recoveryIDs {
		if until := s.recoveryDeferred[id]; until.After(now) {
			continue
		}
		delete(s.recoveryDeferred, id)
		if s.seen[id] && !opened[id] {
			return id
		}
	}
	return 0
}

func (s *Client) deferRestore(id int, now time.Time) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if !s.cfg.LocalItems || s.cfg.RewardMode != "all_locations" || !s.seen[id] {
		return
	}
	for _, registered := range s.recoveryIDs {
		if id == registered {
			if s.recoveryDeferred == nil {
				s.recoveryDeferred = map[int]time.Time{}
			}
			s.recoveryDeferred[id] = now.Add(2 * time.Second)
			return
		}
	}
}

//export AP_Restore
func AP_Restore(states *C.uint8_t, count C.int) C.int {
	if active == nil || states == nil || count <= 0 || count > 4096 || int(count) != len(active.flags) {
		return 0
	}
	return C.int(active.restoreLocation(unsafe.Slice((*byte)(unsafe.Pointer(states)), int(count))))
}

//export AP_RestoreDeferred
func AP_RestoreDeferred(location C.int) {
	if active != nil {
		active.deferRestore(int(location), time.Now())
	}
}
