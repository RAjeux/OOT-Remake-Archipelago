# Full-network engine — 0.12.0-alpha.1

The full-network engine adapts Mozencaz/OotrR at revision
`72198c684ac8b98a243e2a7040086fbe6de87049`. Its original MIT attribution and
file hashes are retained. The historical OOTRR engine remains available as
`generation_mode: legacy`; existing player files keep their original path.
Published 0.11 artifacts and references remain unchanged. This page describes
0.12.0-alpha.1; the historical release evidence is retained below.

## Checks and settings

The new default full-network configuration has **1,106 AP locations**. Examples
include 188 shuffled chest locations, 98 Gold Skulltulas, all 64 shelves in
eight shops, 11 adult-trade handovers, 12 songs, nine boss rewards, eight boss
hearts, six great fairies, eight first cow rewards and ten separate bean
purchases. Selected pots, rocks, trees, crates, beehives, bushes and ground
items also participate. Counts depend on the enabled options and the physical
sources present in this remake.
Two newly researched loose-key checks extend the previous 1,104-check
catalogue. Older player files retain their original checks and identities.
Their native actors, AI and saved completion flags have resource-test coverage;
pickup through their original physical routes still needs gameplay confirmation.

Enabled checks replace their native reward with the AP placement. A personal
placement keeps its game item; another player's placement shows the AP medal.
Purchases use the native shop interaction. Cows can give ordinary milk after
their first AP reward. Refillable native resources outside the selected
catalogue remain ordinary resources.

There are 997 default checks with precise progression rules and 109 with
approximate access. Approximate checks cannot hold progression. Unsupported
physical sources are excluded, rather than invented from a location name.

The full editor exposes **119 configuration controls**, with English/French labels
and help. The full and historical schemas differ; importing an old YAML
preserves its engine. A vanilla dungeon-item setting intentionally retains the
native reward. The [parity report](full-settings-parity.md) maps every historical
control and identifies partial, always-enabled and AP-common alternatives.

Full network currently requires **Child** as the starting age. Actual host
testing found that the adult opening transition can stall, so generation and
preparation reject adult-start rooms in this release. Existing adult player
files remain readable for diagnosis; changing their starting age needs a new
room and fresh save.

Use [Full-Network.yaml](../examples/Full-Network.yaml) as a small new-room
example, or the application's settings editor. Both historical examples now
explicitly select `legacy`, so new APWorld defaults cannot reinterpret them.

## Individual dungeon keys

`full_individual_smallkeys` lets small keys travel through Archipelago. Each
key credits its own dungeon, wherever it is found or received. Selected
key-ring dungeons use a complete ring; unselected dungeons use individual keys
when enabled. Dungeon-local placement restrictions still apply.

The native supply contains **39 keys**: Forest 5, Fire 8, Water 4, Shadow 5,
Spirit 5, Bottom of the Well 2, Gerudo Training Ground 9 and Ganon's Castle 1.
No synthetic keys imitate N64 counts. Imported Water/Well/Ganon key minimums
above the proven native 4/2/1-key supplies are reduced to those actual totals
for every delivery mode, including vanilla keys and rings. Lower requirements
are unchanged; no extra key is granted. Per-copy and
per-source saved receipts prevent duplication on spending, retry, reconnection
and older-save recovery; recovery does not refund an already spent key.

Older player files missing this option retain their historical native-key
behavior and 1,104-check catalogue. A same-room repair does not convert them.

## Goals, economy and entrances

Bridge modes use the selected stones, medallions, total rewards, tokens or
hearts. Zero to six Ganon trials and the offered Ganon boss-key/LACS conditions
have matching native game checks and AP logic. Threshold comparisons still
succeed when the player exceeds the required count.

Heart goals use the real native health supply: 33 Pieces of Heart, eight Heart
Containers and the selected starting hearts. With three starting hearts this
reaches nineteen full hearts. A twenty-heart goal replaces filler with three
missing Pieces of Heart; a one-heart start needs eleven. These required pieces
use ordinary global AP placement. Obsolete N64-only heart-piece credits no
longer contribute to the logic.

Economy uses the native 200/500/1,000-rupee wallets. Shop tiers and
scrub/merchant/fairy prices have consistent wallet requirements, offer text and
debit. A fixed-price value matters when its price mode is Fixed. Scrub hints
name the final AP item, recipient and price in the game's language. Finite AP
purchases and ordinary repeatable native refills remain distinct behaviors.
If shuffling every shop slot would remove the last unshuffled Deku or Hylian
Shield, that displaced shield enters the ordinary AP pool only when no AP copy
already exists. Existing shield copies and final placements are preserved;
there is no free grant or forced Zelda recipient.

Dungeon entrance shuffle preserves paired doors, age conditions and return
routes; the generator and native adapter share the same mapping. Overworld and
interior entrance shuffle are not exposed. Independent Door of Time, Zelda
escape, fortress/carpenter and Membership Card settings retain their own state
and AP rules. Supported native quality-of-life and difficulty settings require
their adapted resources on native hosts and external emulators alike.

Free Scarecrow, silver-rupee shuffle, Triforce Hunt and a developer enemy-spawn
shortcut are not claimed as supported full-network features. See the parity
report for the exact supported values and remaining limitations.

Entrance layouts must permit both all-item traversal and actual acquisition of
unshuffled native equipment/ocarinas. Layouts with a native-item cycle retry
deterministically; the generator does not silently fall back to unshuffled
entrances or invent starting equipment. Native-item access and AP progression
remain separate evidence about the real sources.

Two challenge combinations are explicitly incompatible. Losing a heart on
Game Over cannot accompany an active bridge/LACS heart requirement above three
hearts. Removing random ammunition drops requires renewable vendor stock:
leave shops unshuffled or use a numbered Shopsanity mode instead of shuffling
every shop slot. That option also removes the corresponding native drop credits
from logic while preserving placed AP ammunition, sticks and nuts. Validation
explains the conflict instead of generating an impossible room.

## Delivery and old saves

Native Triforce/Hookshot delivery uses the existing bridge and registered game
events. Remote receipts commit their inventory effect with the received index.
Physical personal rewards use a remote-only AP stream, avoiding a second copy.
Saved source flags and durable server/check history support old-save recovery.
Recovery also reconciles consumed trade items, progressive source tokens,
chest state, frogs and bean-purchase state.

The experimental external runtime uses authenticated `Sync/Get` fences and
native mailbox events. It supports an empty initial item history, missed
remote items and server-confirmed physical-check recovery. It prevents a spent
trade item being refunded after rewind. Its session gate is explicitly cleared
during loading/pause. External DeathLink is available in newly prepared rooms
when enabled in the player file. It observes fresh native Player AI and live
life, then requests the native life-subtraction action. An observed pause or
busy action holds a death; loading or a changed connection/context discards it.
It does not infer death from saved health or replay old deaths.

Received ammunition uses the named quantity. Missing required ammunition
equipment consumes the receipt without granting ammunition or substitute
rupees. Real bows/slingshots initialize their capacity when obtained. Native
small pickups keep the game's display; important receipts use its authored
presentation and camera-facing turn. Constrained player actions defer delivery.

The tracker distinguishes recorded obtained-item progression from saved shield
stock. A burned Deku Shield remains obtained historically but has zero pouch
stock. New metadata reads that saved stock; a bool-only live snapshot leaves it
unknown. Observation never refunds an item or changes AP recovery.

## Updating an existing room

Save and close Zelda, then use **Update prepared room** with the **same player
file**. This refreshes complete resource allocations, native host helpers and
external readiness/DeathLink resources. Outdated prepared resources are
detected before supported launching. Room identity, placements and saves are
preserved. New settings, new checks or another engine require a newly generated
room and fresh save.

The resource-allocation pass accounts for changed packed members as well as
top-level files. Actual host testing found that a missing Player-brain budget
could leave the full mod loading indefinitely. Updating only the desktop
application cannot repair resources already installed in a game.

## Current gameplay validation

Private actual Triforce gameplay in a historical 1,104-check full room verified
title-screen connection, a new four-heart save, rupees held through pause,
native Bow presentation facing the camera, committed receipts and incoming
DeathLink deferred through item/tutorial events before native Game Over,
without echo. The private process exited normally and originals were preserved.

Private actual Hookshot tests cover full-mod loading, native grants,
constrained-action deferral, natural outgoing DeathLink, Spirit Temple route
regressions and the corrected native fishing guard. The latest fishing test
holds a major receipt during a cast and between casts, then releases it after
putting the rod away. This is individual gameplay evidence, not a playthrough
of every dungeon or setting.
The Spirit route used restored vanilla map resources and explicit geometry/
combat assistance inside a private fixture; its two key doors still consumed
native keys normally. Fishing used private travel/age-switch assistance to
reach the scenario. These assists are excluded from playthrough claims.

Actual Hookshot also received two individual Forest keys through a real AP
server outside the Forest Temple. Held/found counts advanced 0 to 1 to 2,
other dungeon counts stayed unchanged and duplicate checks gave no extra key.
Both child and adult native models fit the item presentation without camera
overrides. Resource tests separately cover all 39 native key copies.

Portable Fritchii 5.8.4/game 1.1.1 ran the actual external runtime with a real
AP 0.6.8 server and second player. Tests verified offline rupees, native Bow
reception, no-bag ammunition behavior, ladder deferral, pause-held incoming
DeathLink without echo and native Load-menu recovery. Owned-check recovery and
natural outgoing death used an explicitly private relocated native chest and
cloned vanilla enemies; no player health, position, inventory or save patching
was used. [Port evidence](PORT-COMPATIBILITY.md) details that scope.

Native-resource, real-server, schema, key, goal, economy, entrance and UI tests
complement gameplay. The complete source run passed 109 commands and 684
unittest cases without failures or skips. A separate matrix passed 309
compatible boundary/mixed configurations. Go race tests and Rust regressions
passed, including the five normally ignored core resource tests; three
interactive Rust process/picker tests remain outside automation.

Fresh 1,106-check native and external artifacts were generated and verified
with the full 39-key supply. The final 0.12.0-alpha.1 executable passed payload
inspection covering 526 Python modules and an isolated selftest with a Unicode
profile and only Windows System32 on PATH in 10.94 seconds. The selftest verified
the catalogue, APWorld installation, codecs, native exports, translations and
worker/Tk responsiveness without starting a game or server. Adult start remains
blocked. No complete playthrough of all 1,106 checks, every action or every
emulator is claimed.

## 0.11 release validation — historical baseline

The release was checked with Archipelago 0.6.8. The complete suite ran 95
scripts/commands and 561 unittest cases without failures or skips. A final
YAML-parser correction additionally passed 49 targeted cases, including the
new construction-bound test. Go and C models, real resource round trips,
actual local servers and standalone application checks are included.

Fresh full mod builds were made from the supported game resources for both
child and adult starts. The final native build and preparation kept the same
source fingerprint and verified 1,104 recovery records, 21 personal progressive
source bindings, ten trade replay events, 120 item recipes, 1,295 saved flags
and 2,352 generated resources. Its DLL/server test covered offline items,
reconnection, no double personal reward, no repeated foreign send, recovery
snapshots and both DeathLink directions. Inventory effects in that network
test were modeled; Zelda was not being played.

The external runtime was tested against an actual AP server and generated mod,
with game memory and native effects explicitly interpreted. This is evidence
for protocol/resource behavior, not a successful emulator or port playthrough.
The frozen executable passed with only Windows System32 on PATH, isolated
Unicode data folders, no separate Python/Node installation, and a responsive
Tk window during child-process work.

Three Zelda/DS3 generations and a room with two identical Zelda players
verified cross-world placement. The identical pair placed 122 progression
items locally and 123 in the other world for each player. This demonstrates
mixing; it is not a promise of equal progression counts or timing between
different games. No local-item quota was added.

This remains an alpha. The full new catalogue has not had a human playthrough;
animations, individual checks and other-host behavior still need gameplay
regression reports. Original player saves, game installations and the global
APWorld were not modified by these release tests.
