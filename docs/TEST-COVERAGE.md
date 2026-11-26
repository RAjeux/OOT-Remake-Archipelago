# Test coverage and remaining gameplay checks

This describes the selective 0.10.2 native integration. The existing OOTRR
engine still chooses the seed; the adapter converts its enabled randomized
rewards to AP checks. No Full-network engine is involved.

Tests run against isolated files and profiles. They do not modify the player's
installed mod or saves. **A successful generated mod is not a completed visual
playthrough.** The following distinctions apply throughout this document:

- **Protocol execution:** a real native DLL communicates with a local AP test
  server, including disconnections and replay. A test peer is not another game
  being played.
- **Graph execution:** generated events or native event graphs are interpreted
  over controlled inventory, flags and branches.
- **Resource validation:** actual game resources are read, patched privately,
  decoded again and checked for the intended changes.
- **Manual gameplay:** Link, the camera, controller, HUD and physical route are
  observed in a running game. The expanded catalogue has not been traversed
  manually in its entirety.

## Coverage matrix

The 0.10.2 update was exercised with two actual frozen Windows executables:
old app, independent helper, new app, then optional APWorld replacement.
All 22 recorded invariants passed, including real Python/bootloader process
identities, paths with spaces, executable and APWorld backups, execution of
the persistent Node runtime, unchanged profile/save sentinels and idempotent
completion. Private entry-point probes drove the delivered updater/runtime
code; the shipping GUI was tested separately with real Tk widgets. No private
probe flags or alternate update endpoints are shipped.

The real frozen test found a collision between the Windows `version` library
name and the embedded `VERSION` file. Explicit System32 `version.dll` loading
has a regression test. A separate widget regression reproduces failed helper
handoff and confirms that a retry uses a fresh staging directory.

Six exact-consumable mappings were checked against the game's original
PouchActorInfo, actual receipt flows and chest preparations. Native bundle
sizes are 10/20 bombs, 30 arrows/seeds and 5/10 nuts. Tests exercise one native
grant, acknowledgement, missing equipment, restoration and shop flags.
Actual in-game full-capacity behavior of these six packs was not observed;
capacity clamping remains native to the selected bundle.

| Interaction | Checks and evidence | What this establishes |
|---|---|---|
| Settings and generation | `test_ap_options.py`, `test_network_generation.py`, `test_network_placement.py`, official AP generation fixtures | Supported settings produce the native selection, pool and access rules; inactive settings and placement scopes are handled explicitly. This does not prove every possible YAML combination. |
| All selected source families | `test_network_catalog.py`, `test_network_rewards.py`, Rust `network_sources` tests | Selected native placements and enabled shop stock have trusted physical/event identities. Existing protocol IDs remain stable; unknown sources fail rather than quietly becoming local. |
| Chests | `test_chest_presentation_models.py`, `test_presented_receipts.py`, native chest census | Own and foreign prizes retain real inventory/window actors. Small, big and fast chest presentations use suitable guests. Native chest actors and each exported variant are checked. Camera appearance still needs observation in game. |
| Pots, crates, grass, rocks, hives and flying pots | `test_network_containers.py`, real source-kit fixture | Breaking a holder does not acknowledge its AP check. The holder can return until collection; its native condition is preserved. A completed source is hidden by its saved AP flag. |
| Skulltulas and freestanding pickups | `test_network_containers.py`, `test_skull_events.py`, native source-kit fixture | AP completion follows the get event, not enemy death. Native presence and multi-age variants share the appropriate check. Physical placement names that the engine marks uncertain retain conservative item restrictions. |
| NPC, song and dungeon gifts | `test_network_flows.py`, `test_network_rewards.py` | Source-bound presentations, actor arguments and cleanup survive replacement. Superseded native dungeon credits, starter-kit companions, song and ocarina compensation are removed only at validated replacement boundaries. |
| Incoming items and progressive families | `test_receipt_events.py`, `test_presented_receipts.py`, `test_starter_equipment.py`, `test_key_presentations.py` | Recipes, quantities, progressive tiers, ammunition requirements and acknowledgement order are exercised. Dungeon-qualified keys credit the correct dungeon; a key model does not add Treasure Chest Game keys. |
| Important-item models | `test_presentation_models.py`, `test_chest_presentation_models.py` | Native animation resources and real pouch identity are separated. The MAX fixture contains 16 receipt visuals and 25 chest guests. This is an asset/command check, not a visual assessment of every item. |
| Shops and prices | `test_shop_records.py`, `test_shop_events.py`, `test_shop_flags.py`, `test_shop_hours.py` | All eight shops use their own slots, native payment and sold-out state. Own and foreign items are supported. Optional opening hours preserve unrelated native schedules and conditions. |
| Bean merchant | `test_network_merchant_preflight.py`, real `SimpleShop` audit | Before the AP check, capacity is checked against its AP reward. Afterwards native bean stock limits and repeat handovers return. Eight native caller arguments and prices remain unchanged. |
| Business Scrub offers | `test_network_offer_texts.py`, final prepared-archive audit | Six enabled offer sources in the MAX fixture have room-consistent messages in all 16 archives. Native price variables, question/answer control codes and voice data remain. The previously reported blank choices have not been reproduced visually. |
| Cow rewards | Rust `flow_extra::cows` tests, new-schema native flow preparation | Eighteen focused tests cover all eight cows, their age gates, first reward and continued vanilla milk route. These are graph/resource checks; singing, bottle animation and every physical cow still need gameplay observation. |
| Market Potion Shop tutorial | Rust `flow_extra::potion` tests | Eight tests align its native bottle prerequisite with logic and verify one-time bottle/bug rewards without an extra original potion. The bottle requirement is intentional in this native mode. Bug-catching controls and dialogue timing are not visually tested here. |
| Frogs | Rust `flow_extra::frogs` tests | Twelve tests cover first wins, retries, separate song rewards, the song counter and later vanilla blue-rupee payouts. Rhythm/input and timing remain manual checks. |
| Adult exchanges and consumed quest items | `test_ap_trade.py`, `test_trade_events.py`, `test_trade_state.py`, `test_trade_receipts.py`, native Rust trade tests | Independent AP exchanges and legacy native-chain mode have separate contracts. Consumption, spoil/retry, saved completion and silent spent-item replay are checked. Eleven additional native-chain tests preserve the original engine's exchange behavior. |
| Master Sword and age change | `test_master_sword.py`, specialized native adapters | Shuffled and unshuffled sword modes preserve their own state and native story cleanup. Temple transitions and equipment appearance still require a running-game check. |
| Fishing rod and bowling equipment | `test_native_gameplay_audit.py` | The three native Player brains remain byte-identical. All 31 authored player commands in fishing and bowling retain their parameters, including rental equipment and restoration. This does not test the controller's ZR button or a completed fishing session. |
| Safe receipt and DeathLink timing | `test_deathlink_host.py`, `test_offline_deathlink.py`, compiled native host models | Ordinary locomotion is distinguished from pause, loading, constrained actions, combat and fishing. Pending work survives deferral. These models are not measurements of visual frame timing. |
| Disconnect, offline items and older saves | `test_offline_deathlink.py`, `test_restore_host.py`, `test_restoration.py`, native rollback fixture | Real-DLL/local-server execution and staged host lifetimes cover queue/history recovery, rebuilt journals and no double sends. Own rewards restore separately from another player's used check. Original saves are not used as writable fixtures. |
| Event dependencies and exits | `test_native_gameplay_audit.py`, `test_receipt_registration.py`, `test_event_analysis_cache.py` | The MAX audit checks 2,729 registered events, all new call targets and 1,212 quiet restoration routes. Bounded parameter/string propagation distinguishes native contents from AP dispatch identities. No missing new dependency or child event was found in the audited fixture. |
| Native event capacity | `test_restoration_capacity.py`, opt-in `test_network_build.py` | The actual all-own MAX preparation has 31,208 events in its largest flow, below the 65,535 limit. The former all-own overflow has a reproducing test and shared-reconciliation fix. |
| Installation and application | Packaging, frozen `--self-test`, native setup and installation service tests | Packaged resources, private setup paths and EN/FR controls are exercised. A frozen application test does not imply a game was launched. |

The 0.10.1-alpha.3 compatibility update adds Triforce 0.8.0 menu-layout and
text-input checks, private host-C compilation and a regression for retained AP
binaries after host-source or tool-version updates. Read-only probes verify
installation discovery and original-file preservation. These checks do not
constitute a complete gameplay traversal on the new host version.

Fixed utility rewards can intentionally remain repeatable: milk after a cow's
one AP reward, ordinary beans after the merchant's AP reward, and the frogs'
repeat-win rupees are examples. They are not additional randomized AP checks.

## Integrated fixtures

The maximal native source profile selects 1,211 source locations plus the
optional Master Sword check. It contains 642 containers, 101 flow rewards,
168 chests, 100 Skulltulas, 136 pickups and 64 shop slots.

The private end-to-end tests prepared both 606 own / 606 foreign rewards and
1,212 own rewards. The latter exercises 160 native item types and all 1,212
restoration registrations. The all-own ownership pattern is a test stress
case; it does not impose an ownership quota in generated multiworlds.

The final preparation also verifies all 16 offer archives, the staged bean
preflight and repeat branch, model assets, event capacity and compact saved
GameData. It reuses no user's live profile. These integration fixtures do not
replace an actual multiplayer playthrough.

The independent dependency audit propagates constant item arguments and string
scratch values. Unknown values retain both branches; subflow return side effects
are not assumed. In the audited fixture it used 14,893 prepared and 7,568 base
contexts without reaching its bounds. A context-free union initially reported
unreachable AP branches; parameter-aware analysis cleared those candidates
without production changes.

Actor AINB/C++ command internals and runtime-supplied actor fields are outside
this event-call model. Its clean result does not eliminate the manual checks.

## Reproducing resource checks

Ordinary tests run with `python tools/test.py`. Native asset checks require a
legally supplied, compatible game RomFS. The opt-in variables are:

| Variable | Meaning |
|---|---|
| `OOTRR_ROMFS` | Read-only original RomFS. |
| `OOTRR_CODEC_RESOURCES` | Client resource folder containing the compression runtime. |
| `OOTRR_AUDIT_MOD` | Private prepared `Archipelago/romfs` to inspect. |
| `OOTRR_AUDIT_BASE` | Private generated base `Archipelago/romfs`, before room preparation. |
| `OOTRR_AUDIT_REPORT` | Optional output JSON for the independent audit. |

Run `python -B tests/test_native_gameplay_audit.py` after setting these paths.
The audit does not launch a game or connect to a server. Without asset paths,
its portable tests run and its native tests explicitly skip.

`test_network_build.py` is a separate, slower opt-in integration test. Its fixed
settings are embedded in the test; developer-generated seed files are not
required. It documents the additional builder/runtime variables itself.

## Remaining manual checks

The following observations from `bug.txt` must not be marked resolved solely
because an offline test passes:

- Play fishing from rental to casting, catch, reward and return of the rod.
- Play child/adult bowling with different normal equipment on ZR; test the
  controller and keyboard, including a queued AP reward.
- Inspect small-pickup HUD/counter animation and frame timing, and major-item
  camera/turning behavior, both locally and from another player.
- Buy own and foreign rewards from Scrubs and every shop; inspect visible
  choices, prices, full-wallet/inventory cases, reload and sold-out state.
- Revisit collected Skulltulas and destructibles after age/area changes and
  after restoring an older save.
- Traverse Lake Hylia exits and relevant Hyrule Field routes in both ages; no
  offline resource check establishes that scenery renders correctly in play.
- Play every warp song, lesson and interrupted dialogue state, then check HUD,
  controls and loading transitions.
- Confirm configured Mido/forest behavior and the requested cinematic settings
  in game. Source/native-flow preservation is not a visual skip-policy test.
- Complete expanded dungeon/NPC routes and a real multiworld on each supported
  host. Native data, automated logic and protocol tests cannot establish that
  every physical source, timing edge and option combination is completable.

No additional gameplay bug was established by the latest read-only interaction
audit. That statement is limited to the cases above; it is not a claim that the
game or expanded catalogue is bug-free.
