# Two-player validation record — 28 November 2026

The development campaign passed **36 local rooms with two OOT Remake
players**, covering 18 configuration families. The official Archipelago 0.6.8
generator and server and two separate native-client DLL processes were used.

The campaign models game collection flags, receipt cursors and completed
restoration effects. Its results establish generation and protocol behavior;
physical access, inventory effects and presentation require separate game
tests. The native controls below have their own scope and status.

## Frozen campaign results

| Measurement | Result |
| --- | ---: |
| Generated rooms | 36 / 36 passed |
| Authoritative checks, both players combined | 66,366 |
| Remote receipts observed through the native DLLs | 32,846 |
| Older-save restorations through the explicit flag/effect model | 66,366 |
| Wallet affordability assertions | 193 |
| DeathLink-enabled rooms, tested in both directions | 26 / 26 passed |
| DeathLink-disabled rooms | 10; DeathLink behavior was not exercised |

The first 34 cases repeat the original seeds and settings: all 68 player YAML
files are byte-identical to their original inputs. Two additional cases cover
asymmetric ground/skull settings. All four original generation failures pass
in the final campaign.

The frozen engine SHA-256 is
`26a2d4cdad22434960862a53406a421486269925f4cfe0c05b36fe37433dd3d8`.
The campaign APWorld SHA-256 is
`94b0b7522dcd3cef0a853b09900faaeaeb8edf604216dba35127946e3d2c8647`.
The native DLL SHA-256 is
`94157d944ddb153db8db08e02e11a5fc40ea9a4e06fbb66d21357534384af286`.
Later translation or launcher changes can change a package hash independently
of the generator tested here.

Every selected check is compared with the authoritative multiworld's item,
owner and location. The network phase covers offline checks and receipts,
reconnection, process restart, duplicate packets, index gaps, conflicting
history, lost-journal reconstruction, deferred restoration, both players'
completion and completion after restart. Receipt bundles remain separate
transactions even when their item IDs are equal.

The settings families include default and broad pools, ground/skull and
container shuffles, shops and merchants, adult trades and potion tutorials,
dungeon-item scopes, keysanity, dungeon rewards and LACS, dungeon entrances,
starting inventory, traps, quality-of-life options, difficulty, open-world
access, map removal and wallet-price ranges. The largest selected catalogue
has 1,229 checks per player. The ten Treasure Chest Game puzzle chests remain
outside the public source selection.

## Current source checks

The final portable run passed 836 cases and explicitly skipped 64 optional
cases: 900 cases across 101 suites, plus five standalone check scripts. The
Rust source run passed 2,236 tests with six ignored tests. These counts describe
source, model and packaging checks; the native gameplay controls below remain
separate evidence.

## Findings and corrections

### Generation and access proof

With ordinary chests disabled, all skulls shuffled and ground pickups enabled,
the standalone constructor could reject the token pool before AP placement.
The bounded AP fallback uses a genuine vanilla native donor when that exact
token-capacity failure occurs. Native token counts and constructor validation
remain intact; AP subsequently places the real pool through its access graph.

Two other failures came from an older donor sphere list omitting a legitimate
Gerudo Fortress skull and a Goron City shelf. The supplementary proof removes
selected sources from fixed rewards, supplies their exact AP pool, and uses
the modern native rules to prove the missing source reachable. This changes
catalogue admission, while AP retains its actual access rules. Healthy default
generation retained identical semantic seed, pool and graph data.

The default progression audit found 104 of 148 assignments constrained to
their owner's Hyrule by the selected dungeon-item scopes. The other 44 split
22 local and 22 remote. Broad keysanity controls also mix progression across
players. Placement follows the configured restrictions and varies by seed;
the audit found no additional global rule forcing ordinary progression home.

### Shop selection and previous purchases

Some local shelf actors exposed their displayed native item as the selection
identity. The purchase could award inventory and consume stock while bypassing
the location-bound AP callback. The shelf now retains its AP identity and its
native visual model separately.

The quiet tracking event reconciles selected local shelves from persistent
native stock and AP flags. It preserves inventory, rupees and the received-item
cursor, repairs the exact age/keeper stock counters, and saves once when a
repair occurs. Completed shelves take a read-only path with no save. The
read-only resource audit validated all 64 selected shelves and their 96
canonical age/keeper counters. The tracking validator rejects unknown field
types, persistence and collisions before writing resources.

### Heart effects and acknowledgement ordering

Life values in this record use native quarter-heart units: 16 to 20 means
four hearts to five.

The native pouch's heart behavior depends on its authored grant context.
Presented grants (`IsGetInEvent=true`), including shops and remote receipts,
require the native cure action after the pouch add. Physical and quiet grants
(`false`), including restoration, apply the life or piece conversion in the
pouch operation itself and must not apply it again. The shared recipe preserves
that distinction, waits for queued writes, and commits the source or receipt
cursor after the complete effect. Applying a second cure in a physical grant
could recreate a piece after the fourth-piece conversion or add a second heart
container. Copied presentations relinquish their duplicate heart refresh. The
legacy receipt path retains the authored `CheckHeart` flow and acknowledges
after it.

The review also found early commits inside shared base grants. Receipt ACKs
and chest-open commits now follow the complete recipe, including heart and
starter-equipment wrappers. The independent heart tests exercise receipts,
chests, shops, restoration and physical pickup callbacks, including retries
and the original outer pickup's marker identity. Their piece and life-cap
calculations are explicitly a test model.

### Skipped-story gifts

The fresh-game heart control exposed another independent leak: opening the
Kakariko gate makes the portable constructor silently give the donor rewards
from Zelda's Letter and Impa's song. Those checks may hold foreign AP rewards.
The opening adapter removes only selected donor gifts and their native
ownership writes, preserving the story state and unselected gifts. The existing
ready-player tracking transaction then resolves the actual room rewards and
commits their AP source flags before its single conditional save. This also
covers older saves in which the opening has already played; historical donor
inventory is not removed. Focused queued-effect and resource tests pass. A
native new-game control with two foreign rewards suppressed both donor items
and sent exactly the two checks. A separate native control granted the actual
owned Minuet, preserved it through save/reload, and did not advance the remote
receipt cursor. An unedited historical save also caught up through the same
quiet entry, preserving its earlier Letter and rupee. Reconnection recovered
its missed Bomb Bag and location state; a second save/reload retained the
starter bag, source flags and cursor without a repeated grant or higher upgrade.

### Pause and loading lifecycle

Inventory pause can suspend Link's update callbacks. A bounded observer at the
native Bool-write entry records pause/loading intent and protects pending
DeathLink state. A synchronized intent latch also gates item requests and
tracking/recovery work until a fresh player-state read; closing a menu alone
cannot rearm an old readiness snapshot. Native event requests run outside the
observer lock, and an aborted request still releases its links and restores its context.

The lift integration preserves native instructions, validates a unique hook
location and participates in the SDK's lift cache key. Installation rollback
includes the new lift helper and modified SDK driver. The compiled-host check
requires the observer marker, expected DLL digest and current helper inputs.

### Native dispatcher binding

Large pickup catalogues produced consecutive identity-switch chains more than
1,900 nodes deep. Two maximum-room preparations passed resource audits but
crashed during native resident-event loading before the title. A control that
split only those chains into local banks of at most 64 identity switches reached a
normal new game with the original heap budgets and slightly larger flow files.
The match order, true branches, native fallback, reward effects and arguments
remain unchanged.

The banked native room also opened a foreign chest through all 30 fallback
boundaries and collected an owned Bomb Bag across 16 pouch-bank boundaries
and 15 ground-bank boundaries. Both paths displayed the expected item, committed
their location once and returned normal control; the foreign reward did not
grant local inventory. Native SDK positioning was used only for navigation in
these collection fixtures; opening and collecting used the ordinary controls.

The native [EventFlow binding implementation](https://github.com/open-ead/EventFlow/blob/6a631380b975718eb2a1b79991ef4be8066e5f62/src/evfl/FlowchartObj.cpp)
recursively traverses switch branches. Stack exhaustion is therefore a plausible
explanation; the exact failing guest stack boundary has not been measured.
The control does not establish a 256-subflow or eight-megabyte format limit.
Focused regressions compare every identity in a long selector, typed argument
forwarding, native fallbacks and idempotence, and reject modified bank metadata.

## Separate native and resource controls

Resource controls use the supported 1.1.1 game assets; final primary-host
controls target Triforce 0.8.4. Source and C-fixture checks for the internal
Longshot prototype remain separate from that gameplay coverage.

| Control | Status and scope |
| --- | --- |
| Token-capacity fallback | A 232-source room passed the pinned 0.8.1 constructor and complete AP preparation. A fresh native game collected an own token at an authored underwater pickup, then saved and reloaded with count/source flag still 1, no repeated grant and exactly one local-server check. Navigation used a disclosed native SDK fixture; collection used ordinary diving. |
| Local shop identity | Targeted native purchases confirmed price, AP flag and sold-out commits. This also exposed the separate missing heart-growth effect. |
| Heart effects | Native presented-container and shop controls confirmed 16 to 20 life. Four real remote pieces counted 0, 1, 2, 3, 0 and increased maximum life from 12 to 16 on the fourth, then saved and reloaded. The fourth physical piece performed the same conversion without a cure and retained its source flag and AP cursor through reload. Quiet older-save container recovery restored 16 to 20 without a second cure. Eighteen container receipts reached the 20-heart cap on the sixteenth and retained it for two extra receipts. The final combined 460-source preparation passed its native startup, receipt and older-save controls. |
| Old-stock reconciliation | Native re-entry repaired the old purchase's AP tracking and retained sold-out stock, currency and receipt cursor, with no inventory grant. A retry retained that state. Resource and queued-effect tests also passed. |
| Lifecycle | The final Triforce 0.8.4 bridge held a real five-rupee receipt through inventory pause; closing the menu without an NPC interaction delivered exactly five rupees and one cursor increment with normal control. A separate paused DeathLink applied one death on closing the menu, reached Game Over and produced no echo. Scene/title controls prevented a held death from entering the next loaded context; cached title state is cleared on the next load. This native observer validation applies to Triforce. |
| Shop geometry | Twenty-one accepted native gallery batches cover the 167 native item actors and the foreign AP token. Final profile regeneration reproduced all resources used by those captures byte-for-byte: 28,770 file comparisons across 21 fixtures. Measurements include native shop-pose retention, rotation envelopes and active skin-weight counts. These display fixtures establish geometry; reward ownership and upgrades require separate coherent generated-room purchases. |
| Progressive shop purchase | A genuine two-player room places the remaining own Hookshot upgrade on a ten-rupee shelf, with the first Hookshot and an empty bottle in native starting inventory. Native purchase granted Longshot, charged 10 rupees, set the source/stock once and left the receipt cursor unchanged. Save, restart and re-entry retained sold-out stock and exactly one AP check. The private fixture supplied wallet funds for the purchase; ownership and the item under test came from the generated room. |
| Maximum-room final preparation | Fresh pinned construction and complete current-source preparation passed for two-player 1,229- and 1,228-source rooms and a genuine solo 1,229-source room. Each preserves every authoritative reward and source, all 64 shelves, 206 receipt roots and ten validated trade replay capabilities. The broad room audits 992 physical variants, 218 chest variants and 2,302 concrete dependency entries with none missing. Final native broad and solo preparations passed stable title, new game and normal control with the original budgets. The solo room naturally contains only its own items; its native test covers boot and control, with no solo network or inventory claim. The banked native controls also passed owned-start persistence, a foreign chest, an owned ground pickup and older-save recovery. All final banks validate without rewriting. |

These controls do not amount to a complete physical walkthrough of every
selected source or every combination of settings.

Shop camera checks covered the Market Potion and Kokiri shops. The 120
placement/keeper combinations have numerical and resource coverage; every
keeper has not been played individually. Native sword thinness, materials
and lighting are preserved. Blue Fire's separate flame/particle visibility
issue remains unresolved by the mesh-fit work.

## Reproduce and extend

Use the isolated dependency setup in [the testing guide](TESTING.md), then run:

```powershell
python tools/test_two_player_campaign.py --ap-root 'C:\path\to\Archipelago' --dependencies build/ap-test-dependencies --output build/two-oot-campaign --cases all --seeds-per-case 2
```

Choose a new output directory. `--room` replays an existing two-player archive
without rerolling; `--generate-only` omits network execution. The runner records
and freezes its inputs and distinguishes its models from native gameplay.

Focused regressions include `test_constructor_donor`, `test_two_player_campaign`,
`test_shop_identity`, `test_shop_tracking`, `test_opening_rewards`, `test_heart_effects`,
`test_dispatch_banks`, `test_lifecycle_patch`, `test_link`, `test_restore_host` and
`test_deathlink_host`. Run them through `tools/test.py`; the testing guide
describes the optional native-resource and C toolchain requirements.

Keep private room data, copied game resources, profiles, saves and extracted
media outside published validation artifacts. Public reports should describe
the fixture, source revision, settings, observed behavior and limitations.
