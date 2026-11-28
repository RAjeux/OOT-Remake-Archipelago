# OOT Remake Archipelago 0.10.4 alpha 13: dungeon names on received keys

Personal dungeon items previously used the generic native item name during
some Archipelago presentations, making it hard to identify where a key belonged.
Small keys, boss keys, maps and compasses now display both the item name and
the destination dungeon in the native item dialog.

The fix covers personal chests, network receipts, NPC rewards routed through
the shared item dispatcher, and ground pickups. Personal shop aliases name their destination in both
shelf names and get-item messages; their native descriptions are preserved. Foreign items keep their recipient text.
The dialog uses the existing native text command and item style, with the
game's localized item and dungeon names. It replaces the generic window once;
models, camera, sounds and dungeon credits retain their existing routes.
Quiet restoration and skipped-story reconciliation remain silent.

Tests cover all 35 dungeon items, separate destinations, one dialog and one
credit, normal and guest pickup routes, original native actions, localized
French/English resource labels, text preservation and resource allocations.
Resource checks use the real v1.1.1 files without changing their originals;
these are distinct from manually observing every reward in gameplay.

After updating, close Zelda and prepare the **same `.apootrr`** again when the
launcher requests it. This regenerates the receipt events and text together;
older prepared resources are no longer reused. Keep the same room and save.
The generator, item placements, AP item IDs and saved progress are unchanged.
No new YAML or room is needed. The YAML import from alpha 11 remains available.
