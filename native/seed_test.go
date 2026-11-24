package main

import (
	"encoding/binary"
	"testing"
)

func seedSave(rows [][2]uint32) []byte {
	end := 40 + 8*len(rows) + 8
	raw := make([]byte, end+8)
	put := func(offset int, value uint32) { binary.LittleEndian.PutUint32(raw[offset:], value) }
	put(0, 0x01020304)
	put(8, uint32(end))
	for i, row := range rows {
		put(40+8*i, row[0])
		put(44+8*i, row[1])
	}
	put(end-8, 0xa3db7114)
	put(end-4, uint32(end))
	return raw
}

func TestFullSaveRequiresBothCursorAndSeed(t *testing.T) {
	s := deathClient(t, false)
	s.cfg.SeedMarker = 777
	cursor, check := s.cfg.CursorHash, uint32(30)
	tests := []struct {
		name    string
		rows    [][2]uint32
		belongs bool
	}{
		{"matching", [][2]uint32{{cursor, 3}, {777, 1}, {check, 1}}, true},
		{"missing marker", [][2]uint32{{cursor, 3}, {check, 1}}, false},
		{"marker false", [][2]uint32{{cursor, 3}, {777, 0}, {check, 1}}, false},
		{"other seed", [][2]uint32{{cursor, 3}, {778, 1}, {check, 1}}, false},
		{"missing cursor", [][2]uint32{{777, 1}, {check, 1}}, false},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			_, _, belongs := s.saved(seedSave(tc.rows))
			if belongs != tc.belongs {
				t.Fatalf("save fence=%v, want %v", belongs, tc.belongs)
			}
		})
	}
	s.cfg.SeedMarker = 0
	if _, _, belongs := s.saved(seedSave([][2]uint32{{cursor, 3}, {check, 1}})); !belongs {
		t.Fatal("legacy cursor-only save was rejected")
	}
}
