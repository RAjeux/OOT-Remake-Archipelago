package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"sort"
	"time"
)

func (s *Client) rememberCheckLocked(id int) {
	if _, known := s.cfg.Checks[id]; known && !s.seen[id] {
		s.seen[id] = true
		s.revision++
	}
}

// All writers share one atomic, durable journal replacement. A later snapshot
// always includes previous checks, including those learned from the server.
func (s *Client) persistChecks() error {
	s.journalMu.Lock()
	defer s.journalMu.Unlock()
	s.mu.Lock()
	revision := s.revision
	if revision == s.persistedRevision {
		s.mu.Unlock()
		return nil
	}
	j := journal{Won: s.won}
	for id := range s.seen {
		j.Locations = append(j.Locations, id)
	}
	s.mu.Unlock()
	sort.Ints(j.Locations)
	raw, err := json.Marshal(j)
	if err != nil {
		return err
	}
	file, err := os.CreateTemp(s.root, ".native-checks-*.tmp")
	if err != nil {
		return err
	}
	defer os.Remove(file.Name())
	if _, err = file.Write(append(raw, '\n')); err == nil {
		err = file.Sync()
	}
	closeErr := file.Close()
	if err != nil {
		return err
	}
	if closeErr != nil {
		return closeErr
	}
	if err := os.Rename(file.Name(), filepath.Join(s.root, "native-checks.json")); err != nil {
		return err
	}
	s.mu.Lock()
	s.persistedRevision = revision
	s.mu.Unlock()
	return nil
}

func (s *Client) saveChecks() {
	for range time.Tick(250 * time.Millisecond) {
		_ = s.persistChecks()
	}
}
