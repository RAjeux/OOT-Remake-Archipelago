package main

import (
	"encoding/json"
	"math"
	"strconv"
	"strings"
	"time"
)

// DeathLink follows Archipelago's Bounce protocol. These events are deliberately
// kept only in memory; an event received at the title must not kill the next life.
type deathData struct {
	Time   float64 `json:"time"`
	Source string  `json:"source"`
	Cause  string  `json:"cause,omitempty"`
}

type deathLink struct {
	state             int // -1: inactive, 0: alive, 1: dead, 2: alive in an event (hold remote death)
	tick              time.Time
	pending, outgoing *deathData
	suppress          bool // the game accepted a remote death; its dead transition is not sent
	seen              []string
}

func (s *Client) rememberDeath(d deathData) bool {
	key := strconv.FormatFloat(d.Time, 'g', -1, 64) + "\x00" + d.Source
	for _, old := range s.death.seen {
		if key == old {
			return false
		}
	}
	if len(s.death.seen) == 128 {
		s.death.seen = s.death.seen[1:]
	}
	s.death.seen = append(s.death.seen, key)
	return true
}

func (s *Client) receiveDeath(m wire, now time.Time) {
	s.receiveDeathEpoch(m, now, 0)
}

func (s *Client) receiveDeathEpoch(m wire, now time.Time, epoch uint64) {
	if !s.cfg.DeathLink {
		return
	}
	tagged := false
	for _, tag := range m.Tags {
		tagged = tagged || tag == "DeathLink"
	}
	var d deathData
	if !tagged || json.Unmarshal(m.Data, &d) != nil || d.Time <= 0 || math.IsNaN(d.Time) || math.IsInf(d.Time, 0) || strings.TrimSpace(d.Source) == "" || len(d.Source) > 256 || len(d.Cause) > 2048 {
		return
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	// Parsing happens outside the lock. A connection can be replaced between
	// the session's packet gate and this mutation, even after the next session
	// has already synchronized. Do not carry an old live event or its dedupe
	// key into that replacement session.
	if !s.connectionCurrentLocked(epoch) {
		return
	}
	if !s.rememberDeath(d) || d.Source == s.cfg.Slot || d.Source == s.names[s.cfg.Player] {
		return
	}
	if !s.ready || (s.death.state != 0 && s.death.state != 2) || s.death.tick.IsZero() || now.Sub(s.death.tick) > 2*time.Second || s.death.suppress {
		return
	}
	// Several linked players dying together still kill this life only once.
	if s.death.pending == nil {
		s.death.pending = &d
	}
}

func (s *Client) deathState(state int, now time.Time) bool {
	s.mu.Lock()
	if !s.cfg.DeathLink || state < 0 || state > 2 {
		s.death.state, s.death.tick = -1, now
		s.death.pending = nil
		s.death.suppress = false
		s.mu.Unlock()
		return false
	}
	previous := s.death.state
	// A title/menu transition can stop Link's callbacks entirely. Treat the
	// first callback after that gap as a new life even without an explicit -1.
	if s.death.tick.IsZero() || now.Sub(s.death.tick) > 2*time.Second {
		previous = -1
		s.death.pending = nil
		s.death.suppress = false
	}
	s.death.state, s.death.tick = state, now
	if state == 1 {
		s.death.pending = nil
		if (previous == 0 || previous == 2) && !s.death.suppress && s.ready {
			d := deathData{Time: float64(now.UnixNano()) / 1e9, Source: s.cfg.Slot, Cause: s.text("death_local", s.cfg.Slot)}
			s.rememberDeath(d)
			s.death.outgoing = &d
		}
		s.death.suppress = false
		s.mu.Unlock()
		return false
	}
	if state == 2 {
		// Native get scenes and shop purchases can span multiple frames between
		// payment/presentation and their committed grant. Keep the event while
		// callbacks stay fresh, then kill only after the transaction finishes.
		s.mu.Unlock()
		return false
	}
	d := s.death.pending
	s.death.pending = nil
	if d == nil || !s.ready {
		s.mu.Unlock()
		return false
	}
	s.death.suppress = true
	s.mu.Unlock()
	if d.Cause == "" {
		s.notice("death_received", d.Source)
	} else {
		// A cause supplied by another game is player content; preserve it.
		s.queueNotice("DeathLink received · "+d.Source, "DeathLink · "+d.Cause)
	}
	return true
}
