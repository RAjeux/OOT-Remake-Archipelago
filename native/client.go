package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"net/url"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/gorilla/websocket"
)

type Location struct {
	Name      string
	Flags     []uint32
	Item      string
	Owner     string
	Game      string
	ItemID    int
	Recipient int
}
type Config struct {
	Room, Slot, Game, Token, Server, ProtectedPassword, UUID string
	Language                                                 string
	Player, Protocol                                         int
	CursorHash                                               uint32
	DeathLink                                                bool
	AutoConnect                                              *bool
	RewardMode                                               string
	LocalItems                                               bool
	Items                                                    map[int]string
	ItemNames                                                map[int]map[string]string
	Checks                                                   map[int]Location
	RecoveryLocations                                        []int
	TradeReplayReceipts                                      map[int]int
}
type Client struct {
	cfg                       Config
	root                      string
	logger                    *log.Logger
	mu                        sync.Mutex
	journalMu                 sync.Mutex
	flags                     []uint32
	byFlag                    map[uint32][]int
	recoveryIDs               []int
	recoveryDeferred          map[int]time.Time
	seen                      map[int]bool
	checked                   map[int]bool
	history                   []networkItem
	names                     map[int]string
	ready, won, goalConfirmed bool
	notices                   []string
	revision                  uint64
	persistedRevision         uint64
	death                     deathLink
	connection                *connectionControl
}
type packet map[string]any
type wire struct {
	Cmd         string
	Seed        string `json:"seed_name"`
	Slot, Index int
	Players     []struct {
		Slot        int
		Alias, Name string
	}
	Errors   []string
	SlotData struct {
		Token      string
		Protocol   int
		Checks     []int
		RewardMode string `json:"reward_mode"`
		LocalItems bool   `json:"local_items"`
	} `json:"slot_data"`
	Checked []int `json:"checked_locations"`
	Items   []networkItem
	Keys    map[string]json.RawMessage
	Tags    []string
	Data    json.RawMessage
}
type networkItem struct{ Item, Player, Location int }

func (n *networkItem) UnmarshalJSON(b []byte) error {
	if len(b) > 0 && b[0] == '[' {
		var a []int
		if err := json.Unmarshal(b, &a); err != nil {
			return err
		}
		if len(a) < 3 {
			return errors.New("incomplete AP item")
		}
		n.Item, n.Location, n.Player = a[0], a[1], a[2]
		return nil
	}
	type fields networkItem
	return json.Unmarshal(b, (*fields)(n))
}

type journal struct {
	Locations []int
	Won       bool
}

func newClient(c Config, root string, logger *log.Logger) (*Client, error) {
	if c.RewardMode != "" && c.RewardMode != "legacy_gear" && c.RewardMode != "all_chest_rewards" && c.RewardMode != "all_locations" {
		return nil, errors.New("unknown reward mode")
	}
	if c.LocalItems != (c.RewardMode == "all_locations") {
		return nil, errors.New("local rewards do not match the room reward mode")
	}
	uri, e := url.Parse(c.Server)
	if e != nil || (uri.Scheme != "ws" && uri.Scheme != "wss") || uri.Hostname() == "" || uri.User != nil || c.Room == "" || c.Slot == "" || c.Player < 1 || c.Protocol != 1 || c.CursorHash == 0 || len(c.Checks) > 2000 || len(c.Checks) == 0 {
		return nil, errors.New("invalid room configuration")
	}
	c.Language = normalizeLanguage(c.Language)
	s := &Client{cfg: c, root: root, logger: logger, byFlag: map[uint32][]int{}, seen: map[int]bool{}, checked: map[int]bool{}, death: deathLink{state: -1}}
	s.connection = newConnectionControl(c)
	for id, loc := range c.Checks {
		for _, flag := range loc.Flags {
			if _, ok := s.byFlag[flag]; !ok {
				s.flags = append(s.flags, flag)
			}
			s.byFlag[flag] = append(s.byFlag[flag], id)
		}
	}
	if len(s.flags) > 4096 {
		return nil, errors.New("too many location flags")
	}
	sort.Slice(s.flags, func(i, j int) bool { return s.flags[i] < s.flags[j] })
	if len(c.RecoveryLocations) > 0 {
		if !c.LocalItems || c.RewardMode != "all_locations" || len(c.RecoveryLocations) > len(c.Checks) {
			return nil, errors.New("invalid recovery event configuration")
		}
		unique := map[int]bool{}
		for _, id := range c.RecoveryLocations {
			location, known := c.Checks[id]
			if !known || id <= 0 || id > 0x7fffffff || unique[id] || len(location.Flags) == 0 || location.Recipient < 1 {
				return nil, errors.New("invalid recovery event configuration")
			}
			if location.Recipient == c.Player {
				if name, known := c.Items[location.ItemID]; !known || name == "" || name != location.Item {
					return nil, errors.New("invalid recovery event configuration")
				}
			}
			unique[id] = true
			s.recoveryIDs = append(s.recoveryIDs, id)
		}
	}
	if err := validateTradeReplay(c, s.recoveryIDs); err != nil {
		return nil, err
	}
	raw, e := os.ReadFile(filepath.Join(root, "native-checks.json"))
	if e == nil {
		var j journal
		if e = json.Unmarshal(raw, &j); e != nil {
			return nil, e
		}
		for _, id := range j.Locations {
			if _, ok := c.Checks[id]; ok {
				s.seen[id] = true
			}
		}
		s.won = j.Won
	} else if !os.IsNotExist(e) {
		return nil, e
	}
	return s, nil
}
func (s *Client) opened(flags []uint32, goal bool) {
	s.mu.Lock()
	before := s.revision
	for _, f := range flags {
		for _, id := range s.byFlag[f] {
			s.rememberCheckLocked(id)
		}
	}
	if goal && !s.won {
		s.won = true
		s.revision++
	}
	changed := s.revision != before
	s.mu.Unlock()
	if changed {
		// Persist what was actually observed before another save can roll back
		// its flags. Failures retain the in-memory revision for the retry loop.
		if err := s.persistChecks(); err != nil {
			s.logger.Print("Cannot save location journal; retrying.")
		}
	}
}
func (s *Client) valid(m wire) bool {
	roomMode, modMode := m.SlotData.RewardMode, s.cfg.RewardMode
	if roomMode == "" {
		roomMode = "legacy_gear"
	}
	if modMode == "" {
		modMode = "legacy_gear"
	}
	if roomMode != modMode || m.SlotData.LocalItems != s.cfg.LocalItems {
		return false
	}
	if m.Slot != s.cfg.Player || m.SlotData.Token != s.cfg.Token || m.SlotData.Protocol != s.cfg.Protocol || len(m.SlotData.Checks) != len(s.cfg.Checks) {
		return false
	}
	unique := map[int]bool{}
	for _, id := range m.SlotData.Checks {
		if _, ok := s.cfg.Checks[id]; !ok || unique[id] {
			return false
		}
		unique[id] = true
	}
	return true
}
func (s *Client) session(conn *websocket.Conn, password string) error {
	return s.sessionEpoch(conn, password, 0)
}

func (s *Client) sessionEpoch(conn *websocket.Conn, password string, epoch uint64) error {
	defer conn.Close()
	conn.SetReadLimit(40 << 20)
	refresh := func() error { return conn.SetReadDeadline(time.Now().Add(85 * time.Second)) }
	if err := refresh(); err != nil {
		return err
	}
	conn.SetPongHandler(func(string) error { return refresh() })
	// Only the reader parses packets. All WebSocket writes are serialized.
	var writer sync.Mutex
	send := func(p ...packet) error {
		writer.Lock()
		defer writer.Unlock()
		_ = conn.SetWriteDeadline(time.Now().Add(10 * time.Second))
		return conn.WriteJSON(p)
	}
	done := make(chan struct{})
	var worker sync.WaitGroup
	defer func() {
		close(done)
		conn.Close()
		worker.Wait()
		s.mu.Lock()
		if s.connectionCurrentLocked(epoch) {
			s.ready = false
			// DeathLink is a live event: neither direction is replayed on reconnect.
			s.death.pending, s.death.outgoing = nil, nil
		}
		s.mu.Unlock()
	}()
	auth := false
	syncing := true
	fenced := false
	var history []networkItem
	var fence string
	synchronize := func() error {
		fence = "ootrr-native-" + strconv.FormatInt(time.Now().UnixNano(), 16)
		syncing = true
		fenced = false
		history = nil
		s.mu.Lock()
		if !s.connectionCurrentLocked(epoch) {
			s.mu.Unlock()
			return errConnectionReplaced
		}
		s.ready = false
		s.connection.state = "synchronizing"
		s.mu.Unlock()
		return send(packet{"cmd": "Sync"}, packet{"cmd": "Get", "keys": []string{fence}})
	}
	var names = map[int]string{}
	workerStarted := false
	for {
		var batch []wire
		if e := conn.ReadJSON(&batch); e != nil {
			return e
		}
		for _, m := range batch {
			if !s.connectionCurrent(epoch) {
				return errConnectionReplaced
			}
			switch m.Cmd {
			case "RoomInfo":
				if m.Seed != s.cfg.Room {
					return errors.New("wrong room for this mod")
				}
				tags := []string{"AP"}
				if s.cfg.DeathLink {
					tags = append(tags, "DeathLink")
				}
				handling := 7
				if s.cfg.LocalItems {
					handling = 5
				}
				if e := send(packet{"cmd": "Connect", "name": s.cfg.Slot, "game": s.cfg.Game, "uuid": s.cfg.UUID, "password": password, "version": packet{"major": 0, "minor": 6, "build": 7, "class": "Version"}, "items_handling": handling, "tags": tags, "slot_data": true}); e != nil {
					return e
				}
			case "ConnectionRefused":
				return fmt.Errorf("connection refused: %s", strings.Join(m.Errors, ", "))
			case "Connected":
				if auth || !s.valid(m) {
					return errors.New("this mod does not match the room slot")
				}
				auth = true
				for _, p := range m.Players {
					names[p.Slot] = p.Alias
					if names[p.Slot] == "" {
						names[p.Slot] = p.Name
					}
				}
				s.mu.Lock()
				if !s.connectionCurrentLocked(epoch) {
					s.mu.Unlock()
					return errConnectionReplaced
				}
				s.names = names
				s.checked = map[int]bool{}
				for _, id := range m.Checked {
					s.checked[id] = true
					s.rememberCheckLocked(id)
				}
				s.goalConfirmed = false
				s.mu.Unlock()
				if err := s.persistChecks(); err != nil {
					s.logger.Print("Cannot save location journal; retrying.")
				}
				s.notice("connected", s.cfg.Slot)
				if e := synchronize(); e != nil {
					return e
				}
			case "ReceivedItems":
				if !auth {
					continue
				}
				for _, it := range m.Items {
					if _, ok := s.cfg.Items[it.Item]; !ok {
						return errors.New("unknown item for this mod version")
					}
				}
				if syncing && m.Index == 0 {
					history = nil
				}
				mismatch := m.Index < 0 || m.Index > len(history)
				if !mismatch {
					for i, v := range m.Items {
						if m.Index+i < len(history) && history[m.Index+i] != v {
							mismatch = true
							break
						}
					}
				}
				if mismatch {
					if e := synchronize(); e != nil {
						return e
					}
					continue
				}
				old := len(history)
				for i, v := range m.Items {
					if m.Index+i >= old {
						history = append(history, v)
					}
				}
				if fenced {
					s.mu.Lock()
					if !s.connectionCurrentLocked(epoch) {
						s.mu.Unlock()
						return errConnectionReplaced
					}
					s.history = append([]networkItem(nil), history...)
					s.mu.Unlock()
					for _, it := range history[old:] {
						s.logger.Print("Item queued in Zelda · " + s.cfg.Items[it.Item])
					}
				}
			case "Retrieved":
				if _, ok := m.Keys[fence]; !auth || !ok {
					continue
				}
				syncing = false
				fenced = true
				s.mu.Lock()
				if !s.connectionCurrentLocked(epoch) {
					s.mu.Unlock()
					return errConnectionReplaced
				}
				s.history = append([]networkItem(nil), history...)
				s.ready = true
				s.connection.state, s.connection.errorCode = "connected", ""
				s.mu.Unlock()
				if !workerStarted {
					workerStarted = true
					worker.Add(1)
					go func() {
						defer worker.Done()
						t := time.NewTicker(300 * time.Millisecond)
						defer t.Stop()
						last := map[int]time.Time{}
						var lastGoal, lastPing time.Time
						for {
							select {
							case <-done:
								return
							case now := <-t.C:
								if now.Sub(lastPing) > 25*time.Second {
									lastPing = now
									if err := conn.WriteControl(websocket.PingMessage, nil, now.Add(8*time.Second)); err != nil {
										conn.Close()
										return
									}
								}
								// No newly observed check is sent before its journal
								// revision has reached disk. Server acknowledgements
								// can rebuild this same journal after a fresh start.
								_ = s.persistChecks()
								s.mu.Lock()
								var missing []int
								ready := s.ready && s.connectionCurrentLocked(epoch)
								durable := s.persistedRevision == s.revision
								if ready && durable {
									for id := range s.seen {
										if !s.checked[id] && now.Sub(last[id]) > 5*time.Second {
											missing = append(missing, id)
											last[id] = now
										}
									}
								}
								goal := ready && durable && s.won && !s.goalConfirmed && now.Sub(lastGoal) > 10*time.Second
								death := s.death.outgoing
								s.death.outgoing = nil
								s.mu.Unlock()
								var ps []packet
								if ready && death != nil {
									ps = append(ps, packet{"cmd": "Bounce", "tags": []string{"DeathLink"}, "data": death})
								}
								if len(missing) > 0 {
									sort.Ints(missing)
									ps = append(ps, packet{"cmd": "LocationChecks", "locations": missing})
								}
								if goal {
									lastGoal = now
									ps = append(ps, packet{"cmd": "StatusUpdate", "status": 30})
								}
								if len(ps) > 0 {
									if e := send(ps...); e != nil {
										conn.Close()
										return
									}
									if ready && death != nil {
										s.logger.Print("DeathLink sent · " + death.Source)
									}
									if goal {
										s.mu.Lock()
										s.goalConfirmed = true
										s.mu.Unlock()
									}
								}
							}
						}
					}()
				}
			case "Bounced":
				if auth {
					s.receiveDeathEpoch(m, time.Now(), epoch)
				}
			case "RoomUpdate":
				if !auth {
					continue
				}
				for _, id := range m.Checked {
					s.mu.Lock()
					if !s.connectionCurrentLocked(epoch) {
						s.mu.Unlock()
						return errConnectionReplaced
					}
					first := !s.checked[id]
					s.checked[id] = true
					s.rememberCheckLocked(id)
					ownName := s.names[s.cfg.Player]
					s.mu.Unlock()
					if loc, ok := s.cfg.Checks[id]; ok && first {
						if loc.Owner != "" && (!s.cfg.LocalItems || (loc.Owner != s.cfg.Slot && loc.Owner != ownName)) {
							s.noticeLocation(loc)
						} else {
							s.logger.Print("Location checked · " + loc.Name)
						}
					}
				}
				if err := s.persistChecks(); err != nil {
					s.logger.Print("Cannot save location journal; retrying.")
				}
			}
		}
	}
}
func loadConfig(root, token string) (Config, error) {
	var c Config
	raw, e := os.ReadFile(filepath.Join(root, "native-session.json"))
	if e != nil {
		return c, e
	}
	d := json.NewDecoder(bytes.NewReader(raw))
	e = d.Decode(&c)
	if c.Token != token {
		return c, errors.New("room token mismatch")
	}
	return c, e
}
