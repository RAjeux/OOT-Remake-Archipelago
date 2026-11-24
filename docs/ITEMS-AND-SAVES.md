# Items, checks and saves

An AP check is a location exported when the room is generated. Its reward can
belong to Zelda or another player. A personal physical reward applies the native
item effect in Zelda; a remote reward is sent to its owner. The old reward at
that source is replaced. The AP item pool is filled by Archipelago under each
game's access rules, without a Zelda recipient quota.

New full-network rooms export the supported randomized sources into the AP
pool, including personal rewards found in Zelda. The default catalogue has
1,106 checks; the chosen settings determine the active set. An item found in
your own world is still an AP item with its own location identity and server
history. It is not an extra local reward. Sources disabled by the settings
retain their native behavior.

Historical OOTRR rooms retain their original generated catalogue. Depending on
their settings, non-exported sources can still contain native-local randomized
rewards. An update does not retroactively add those locations to the room.
The displayed item model alone does not determine whether a source is an AP
check; the generated location table does.

## Loading an older save

Full-network rooms use the loaded save's saved per-receipt and per-source
flags. After the current AP connection has authenticated and synchronized its
history, remote items missing from that save are queued again. Previously
checked personal sources recover their native item effect and collection state
once. A foreign source restores only its completed state; its item is not
granted to Zelda or sent to the other player twice. A busy action, event or
inventory pause delays execution without discarding the pending item.

The external backend uses the real source flags as the recovery receipt. Chest
open state and related native counters are restored with the source. Own
progressive rewards use their saved source tokens to avoid counting the same
upgrade twice. Authenticated consumed-trade state prevents an older save from
refunding an item already consumed in that room. Manual tracker marks do not
become completed checks. Historical `all_locations` rooms keep their original
received-index/journal recovery path.

Native-local rewards follow the selected save, like ordinary game progress.
Loading a save from before a local reward means that source and reward can be
collected again in that save. The mod does not inject those gains from a later
save. This keeps the inventory and the native quests, counters and consumed
items consistent with the loaded save.

Keep a save dedicated to each room. A different room has different placements;
its saves and reward history are independent. Triforce and Hookshot also keep
separate profiles and do not transfer game saves through Archipelago.

## Tracker observations and consumed equipment

An obtained-item flag records progression; it does not always prove an item is
still in the pouch. In actual Hookshot gameplay, fire burned the Deku Shield
and emptied its equipment slot while `IsGet.Weapon_Shield_Deku` stayed true.
The supported game's saved `PouchData.Weapon_Shield_Deku.StockNum` changed from
one to zero. Newly prepared tracking metadata therefore reads the saved native
stock for Deku, Hylian and Mirror Shields. It verifies each key and integer type
against the game's saved schema before including it.

The tracker identifies these rows as **Observed stock**. Other obtained-item
rules, including historical metadata, are identified as **Recorded
progression**. A live-only snapshot cannot read pouch stock through the current
bool-only process adapter, so a stock-aware shield row is **Stock unavailable**
with an unknown amount until a save is selected. Stock values describe that
saved snapshot; they are not inferred from AP history. Burning or consuming an
item does not clear its AP receipt or refund it. This observation change does
not modify saves, checks, room placements or older-save recovery.

## Actual external recovery validation

On 24 November 2026, a private Fritchii 5.8.4/game 1.1.1 session used the actual
external client, an AP 0.6.8 server and a second player. Five and twenty rupees
sent while Zelda was inactive were delivered after loading. Bow reception used
the native presentation and initialized thirty arrows. Bomb ammunition without
a bomb bag acknowledged the receipt and granted nothing, including no
substitute rupee. Reloading saved receipts did not grant them again.

An additional private map fixture relocated the existing Kokiri Sword Chest
without changing its actor/hash, native event or owned Fire Medallion
placement. Opening it normally reported one real AP check. Zelda's own Load
menu then loaded a precheck save whose source, chest-open and medallion flags
were all false. The remote Bow and owned medallion recovered through native
events; the real source and chest-open flags became true, and revisiting the
chest showed it open. The server retained one check/five total received items,
and the rupee count stayed at twenty-five. A later normal reload produced no
additional receipt animation. No inventory or save editing was used. This
fixture verifies the actual actor/event/network/recovery transaction, not a
playthrough of the chest's original physical route.

## Extending network coverage

A native source needs a researched location identity, a reliable collection
flag, an event that replaces the original reward, an access rule and older-save
recovery before it can join the AP pool. It must be exported during generation.
Simply reporting an already granted native item as a check can grant a second
reward and cannot retroactively change a room's placements.

Existing rooms keep their generated catalogue and placements after a mod
update. Updates can fix delivery and presentation without rerolling a room;
new shuffle choices and added network locations require a newly generated room.

Older full mods require **Update prepared room** with the **same player file**
to receive corrected resource allocations and, for external hosts, the native
readiness and DeathLink resources. Room identity, placements and saves are
preserved. Updating only the application does not update an already installed
RomFS overlay. Keep the desktop external window open while playing; it owns the
AP connection and supplies the authenticated recovery history.
