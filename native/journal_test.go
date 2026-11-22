package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

func readJournal(t *testing.T, root string) journal {
	t.Helper()
	raw, err := os.ReadFile(filepath.Join(root, "native-checks.json"))
	if err != nil {
		t.Fatal(err)
	}
	var result journal
	if err := json.Unmarshal(raw, &result); err != nil {
		t.Fatal(err)
	}
	return result
}

func TestObservedChecksAreDurableAndNeverRemovedByOlderSave(t *testing.T) {
	s := deathClient(t, false)
	s.opened([]uint32{30}, true)
	j := readJournal(t, s.root) // No background timer is needed to commit it.
	if len(j.Locations) != 1 || j.Locations[0] != 20 || !j.Won {
		t.Fatalf("observed check/goal was not durable: %+v", j)
	}
	s.opened(nil, false) // A loaded older save has neither check nor goal.
	restarted, err := newClient(s.cfg, s.root, s.logger)
	if err != nil {
		t.Fatal(err)
	}
	if !restarted.seen[20] || !restarted.won {
		t.Fatal("a complete process restart lost checks after save rollback")
	}
}

func TestServerChecksRebuildDurableJournalWithoutResendingRewards(t *testing.T) {
	s := connectionFixture(t)
	var arrivals atomic.Int32
	checks := make(chan int, 8)
	server := connectionServer(t, s, "checked", &arrivals, checks)
	startConnectionManager(t, s)
	if result := s.connect("ws"+strings.TrimPrefix(server.URL, "http"), "", 0, 1); result != 1 {
		t.Fatal(result)
	}
	waitConnection(t, s, "connected")
	j := readJournal(t, s.root)
	if len(j.Locations) != 1 || j.Locations[0] != 20 {
		t.Fatalf("authenticated Connected did not rebuild the scoped journal: %+v", j)
	}
	s.opened(nil, false)
	s.opened([]uint32{30}, false) // Rediscovering an old check cannot send it again.
	select {
	case <-checks:
		t.Fatal("already confirmed check was sent after rollback")
	case <-time.After(400 * time.Millisecond):
	}
	s.disconnect()
	restarted, err := newClient(s.cfg, s.root, s.logger)
	if err != nil || !restarted.seen[20] || restarted.seen[999999] {
		t.Fatalf("restart lost scoped server confirmation: %v", err)
	}
}

func TestRoomUpdateConfirmationSurvivesProcessRestart(t *testing.T) {
	s := deathClient(t, false)
	peer, _ := nativePeer(t, s, nil)
	if err := peer.WriteJSON([]packet{{"cmd": "RoomUpdate", "checked_locations": []int{20, 999999}}}); err != nil {
		t.Fatal(err)
	}
	deadline := time.Now().Add(time.Second)
	for {
		s.mu.Lock()
		durable := s.seen[20] && s.revision == s.persistedRevision
		s.mu.Unlock()
		if durable {
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("RoomUpdate was not durably remembered")
		}
		time.Sleep(time.Millisecond)
	}
	restarted, err := newClient(s.cfg, s.root, s.logger)
	if err != nil || !restarted.seen[20] || restarted.seen[999999] {
		t.Fatalf("RoomUpdate journal did not survive restart: %v", err)
	}
}

func TestJournalConcurrentWritersKeepUnionAndFailedWritesCanRetry(t *testing.T) {
	s := deathClient(t, false)
	for id := 21; id < 29; id++ {
		s.cfg.Checks[id] = Location{Flags: []uint32{uint32(id + 10)}}
		s.byFlag[uint32(id+10)] = []int{id}
	}
	var workers sync.WaitGroup
	for flag := uint32(30); flag < 39; flag++ {
		workers.Add(1)
		go func(flag uint32) {
			defer workers.Done()
			s.opened([]uint32{flag}, false)
		}(flag)
	}
	workers.Wait()
	if got := readJournal(t, s.root); len(got.Locations) != 9 {
		t.Fatalf("concurrent journal lost a check: %+v", got)
	}
	s.root = filepath.Join(t.TempDir(), "not-created-yet")
	s.opened(nil, true) // Write failure must leave the new revision pending.
	if s.revision == s.persistedRevision || !s.won {
		t.Fatal("failed journal write was treated as committed")
	}
	if err := os.Mkdir(s.root, 0700); err != nil {
		t.Fatal(err)
	}
	if err := s.persistChecks(); err != nil {
		t.Fatal(err)
	}
	if got := readJournal(t, s.root); len(got.Locations) != 9 || !got.Won {
		t.Fatalf("retry lost the monotone journal: %+v", got)
	}
	if files, _ := filepath.Glob(filepath.Join(s.root, ".native-checks-*.tmp")); len(files) != 0 {
		t.Fatal("journal left temporary files behind")
	}
}
