# Stability fixes and upgrade scope

## 0.10.4-alpha.9: large catalogues, native rewards and lifecycle

Long AP pickup selectors now use local function boundaries after each group of
64 comparisons. The native binder recursively visits switch branches; very
large chains could crash before the title screen even with valid file indices.
The same large room started with these boundaries and its original heap
budgets. Existing matches, fallback, arguments and reward effects are preserved.
Quiet recovery also shares identical item cores while each source keeps its
own flags, stock, deferred status and save.

Personal shop rewards retain their unique AP actor identity through the native
shelf's actor-name reference. Previously, selecting the displayed original
actor could bypass AP check reporting and progressive grant logic. The display
mesh, native purchase event and price remain separate from that identity.

A room-bound quiet reconciliation event repairs consumed personal shelves
whose AP flag was missing, or a completed AP shelf with incomplete native
stock counters. It updates only the canonical check and stock fields and saves
only when those fields changed. The stock repair never grants inventory,
charges rupees or advances the network receipt cursor. It cannot infer or compensate
uncertain historical inventory effects.

Presented heart grants record ownership with `IsGetEvent=True`, then need the
game's separate cure action to apply the container or piece. Quiet restoration
and physical pickups use `False`: the pouch command already applies that effect.
Repeating the cure there could grow a container twice or recreate a quarter
after the fourth-piece conversion. The shared recipe follows this native
distinction and waits for the full effect before committing its AP source or
receipt. Copied presentations relinquish their duplicate refresh.

Native comparisons verified the fourth physical piece, four remote pieces,
and an older save recovering a personal container, including the missing and
duplicate effects of the incorrect variants. Save/reload controls retain the
correct result. The broader transaction tests remain models, not an all-items
playthrough.

Skipping the castle visit also used to give the constructor's local Zelda
letter and Impa-song donor items, even when those checks belonged to another
player. Selected donors are now removed from the opening. The ready-player
reconciliation gives the actual personal AP reward or completes the foreign
check, using the existing source flag for once-per-save recovery. Unselected
native gifts and story state remain intact. This also catches up an older
save; uncertain old donor inventory is not removed.

The Triforce bridge observes native pause/loading writes even while inventory
suspends Link's update. It retains a paused DeathLink, invalidates it at a
loading boundary and blocks new item requests until fresh player state has
been read. Its SDK installer validates and caches the observer together with
the host build. See [delivery safety](DELIVERY-SAFETY.md).

Generation also handles the specific native token-capacity refusal when all
Skulltulas are shuffled with chests disabled. A validated native vanilla donor
preserves the original items and tokens; AP still performs the final fill.
Separate provenance prevents mixing that construction with an older room.
An omitted native catalogue entry is admitted only when its unchanged AP
access rules and actual pool prove a route. Unknown failures remain errors.

Existing rooms retain their placements, options, IDs and player files. Close
the game and prepare the same `.apootrr` when updated resources are requested.
The lifecycle change requires rebuilding the supported Triforce host. New
generation fixes affect newly generated rooms, not an existing room's fill.
See the [validation record](OVERNIGHT-VALIDATION.md) for the separate network,
resource, modeled transaction and observed gameplay evidence.

## 0.10.4 alpha 6: portable construction of progressive AP pickups

A valid room could fail before installation because the pinned OOTRR 0.8.1
constructor rejected a fixed pickup's progressive tier. Its historical local
reachability proof can differ from the embedded AP engine's proof, especially
after deriving a base without the independent adult trade exchanges.

Preparation first tries the original native input. Only that constructor's
precise tier-order refusal, naming a validated physical AP source, authorizes a
bounded retry. Disposable input swaps the rejected progressive reward with a
safe filler in a supported AP chest, preserving native item counts and every
uncovered location. The original AP seed, checksum, access graph, roster and
settings are retained. Native validation remains enabled for every attempt;
unrelated failures propagate. Failed partial attempts are never reused or
published.

The exact native tier actor reported by the constructor is validated before
restoring pickup height. Canonical chest and keep-away models are restored when
content-based chest sizing is enabled. The AP postpasses then apply the actual
room rewards. Separate construction provenance records the temporary changes.
Previously successful construction keeps its original path. Native bridge,
AP identities and generation semantics are unchanged; no reroll is required.

Validation reproduced the exact failure with the pinned constructor, then
completed the same 460-check room through the normal preparation pipeline.
Audits checked 218 chest variants, 122 physical sources (148 variants), all
64 shop shelves, 460 restoration entries and ten strict sealed trade receipts.
All 167 supported model actors passed validation. Concrete traversal of 626 AP
event roots found no missing known dependencies; existing dynamic native
message dispatches remain explicitly unresolved. A separate real constructor
run with content-based chest sizing enabled verified donor chest/keep-away
models, exact pickup height, unchanged rewards/events and byte idempotence.
The portable suite passes 706 tests with 63 environment skips; 44 native engine
binary tests and the connected installer regression also pass. These are
preparation and graph/resource checks, not a full gameplay traversal.

## 0.10.4 alpha 5: chest preloads and visible local rewards

The shared pickup dispatcher now propagates newly introduced concrete subflow
and child-event dependencies to existing native callers. This repairs foreign
chests whose Open prompt previously returned without completing the get event.
The repair retains native message dispatch metadata and all reward identities.

Chest display proxies now cover shop actors and incompatible world pickups,
including Deku Sticks. Their models use a native pouch guest performer; actual
grants, progressive tiers and quantities still use the original reward actors.
Preparation validates registry identities, pouch performers, selected meshes
and animation resources for all 167 supported actors (166 distinct guests).
Inner resources retain immutable native peer allocation allowances.

The portable suite passes 699 tests, with 63 environment-dependent skips.
Additional tests using private native 1.1.1 resources pass the model, chest-route
and bundle-quantity checks. A Triforce 0.8.3 gameplay comparison reproduced the
foreign-chest refusal and restored both Mido foreign rewards by changing only
the missing preload metadata. The isolated AP server received each check once.
A remote Bow sent while crawling remained queued until the normal tunnel exit,
then played its native receipt and restored player control.

Dependency propagation uses the exact entry for a changed event's own chart,
preserving silent adult trade replay acknowledgements. Final resources must
still pass their strict graph validation before their capability is sealed.
A fresh private preparation of the reported 460-check room completed the real
chest, 64 shop-shelf, 200 callback, restoration and localization stages, then
sealed all ten quiet replay receipts. Existing quiet entries remained unchanged.

These checks cover the reported paths and representative rewards; they do not
constitute a complete playthrough of every location or setting. Existing rooms
and saves remain compatible; prepare the same player file when requested. See
the [patch notes](RELEASE-NOTES-0.10.4-alpha.5.md).

## 0.10.4 alpha 4: new-game opening handover

The optional dungeon-key tracker now updates its quests locally inside the
opening, preserving the original fade-in and handover to player control.
An undeclared cross-file event call previously stalled this sequence while
forest audio and Archipelago receipts could continue behind a black screen.
Prepare the same player file again when requested. Room settings, placements
and saves remain compatible. See the [patch notes](RELEASE-NOTES-0.10.4-alpha.4.md).

## 0.10.4 alpha 3: dungeon-key tracker startup

The expanded quest menu now reserves memory for the native parser's additional
panels and metadata, alongside the serialized BYML. Original quest panels and
the optional key tracker are retained. Existing prepared mods require one
preparation with the same player file and save; room generation and placements
remain unchanged. See the [patch notes](RELEASE-NOTES-0.10.4-alpha.3.md).

## 0.10.4 alpha 2: launcher replacement and filenames

Successful updates use the new release's canonical versioned EXE name in the
same folder and keep the previous executable in private LocalAppData rollback
storage. Older 0.10.4 launchers use their normal update action; a shortcut to
the old filename may need retargeting. Game integration and APWorld generation
rules are unchanged; its optional refresh includes updated shared translations.
See the [patch notes](RELEASE-NOTES-0.10.4-alpha.2.md).

## 0.10.4 alpha 1: selective upstream additions

Reviewed access rules, 17 additional physical sources and optional gameplay,
cosmetic and difficulty settings extend newly generated rooms. The compatible
constructor remains OOTRR 0.8.1; the project's native AP client, menu, branding
and receipt/recovery system remain in place. Existing native 0.10 rooms retain
their player files, saves and generated catalogue. New options and checks need
the matching APWorld and a newly generated room with a dedicated save.

This remains an alpha; new difficulty settings are experimental and Longshot
is not a supported launcher host. See the
[release notes](RELEASE-NOTES-0.10.4-alpha.1.md) and
[scoped validation results](UPSTREAM-VALIDATION.md). Historical records follow.

## 0.10.3 alpha 1: desktop interface refresh

The launcher, settings editor, connection controls and updater share a dark
theme and clearer action hierarchy. Persistent sidebar navigation preserves
draft values; scrollable forms keep actions accessible on small windows, and
keyboard focus reveals fields below the fold. The settings summary is
collapsible on compact windows. Native DLL/WASM, AP identities, generation rules
and prepared-resource revision remain unchanged. A current 0.10.2 room can
continue immediately after the launcher update. See the
[desktop release notes](RELEASE-NOTES-0.10.3-alpha.1.md).

## 0.10.2 alpha 1: updates and exact consumable bundles

The launcher can check the project's GitHub releases, prepare a verified update,
replace itself through a separate helper and restart. An optional APWorld update
is applied by the new application, with its matching Node runtime and backups.
Older experimental releases are not chosen by their higher numeric version.
An unsuccessful helper launch allows a new download and retry. Windows product
metadata identifies the actual executable, including its prerelease version.
See [the update guide](UPDATING.md).

Bombs (10), Bombs (20), Arrows (30), Deku Seeds (30), Deku Nuts (5) and Deku
Nuts (10) now use the six existing native bundles with those exact quantities.
The game still performs the grant and capacity checks; no quantity multiplier,
new native ABI, item ID or engine change is introduced. Missing ammunition
equipment remains a silent acknowledgement. Older player metadata is accepted;
normal legacy-gear rooms do not transfer these six ammunition packs.

The installer records the room's prepared resource revision and checks the
active mod before offering Play. Older prepared resources require preparation
with the same player file and save. An installation failure restores the old
mod marker and preferences. This resource revision is separate from the app's
version, preserving reuse across future interface-only updates.

APWorld installation now rejects malformed packages before replacing anything.
Other active copies of the same package are backed up and restored on a failed
replacement. Other games are preserved, and successful installation paths are
remembered for the optional update flow.

Validation includes a real two-version frozen Windows replacement/restart with
an optional APWorld update, native consumable-resource inspection and event
tests, plus a private Triforce 0.8.3 build and real local AP startup/reconnection.
It does not establish a full manual playthrough of every randomized check.

## 0.10.1 alpha 3: Triforce 0.8.0 setup compatibility

The installer now supports Triforce 0.8.0's menu hooks, including resolution
editing and tuning overlays. The adapter preserves the native menu pages and
text-input paths while adding the Archipelago page. Older supported menu
layouts retain their existing patch path; unknown or ambiguous layouts are
still rejected before room preparation.

Compiled-host detection also checks the host source and optional tool-version
metadata. Replacing these with newer files no longer allows a retained older
AP executable or renderer to be treated as current. A valid current build is
still reused; older tool folders without optional version metadata remain
compatible.

Existing native 0.10 player files, placements and saves are unchanged. Close
Zelda and Triforce Setup, finish the host update, then prepare the same
`.apootrr` in the new application. The required host rebuild runs during setup.
**No new room or new save is required for this compatibility fix.** The expanded
catalogue still needs a new room when upgrading from a room that did not
already contain those checks.

Validation covers menu patching, idempotence, original text-input preservation,
read-only installation preflight, source/version cache invalidation, and private
compilation of the actual updated host C source. These are automated and build
checks, not a complete manual gameplay traversal of Triforce 0.8.0. Existing
presentation and gameplay-observation limits remain in effect.

## 0.10.1 alpha 2: settings clarity and broader interaction checks

The YAML editor adds bilingual search, ordered categories, optional advanced
and inactive controls, an explanation for the current choice and a selection
summary. Hiding a control or temporarily disabling its parent no longer loses
its pending selection. Applying still validates and normalizes inactive
subsettings using the shared schema; native option keys and defaults remain
unchanged.

Configurations without ordinary shuffled chests no longer need the old
shop-deal/Skulltula/trade subset. The native source export already includes
ground heart pieces, NPCs, ordinary shop stock and destructibles. Existing
dungeon-item constraints remain enforced. This changes new-room validation,
not the contents of existing player files or saves.

Expanded checks combine real local AP connections and the shipped DLL with
event-graph/native-memory models. These include offline delivery, old-save
recovery, duplicate protection, DeathLink, busy player states and a reproducible
matrix of source families, doors, economy, dungeon-item scopes and starting
inventory. They complement, rather than replace, a manual gameplay traversal.
See [test coverage](TEST-COVERAGE.md) for the scope and remaining visual checks.

## 0.10.1: selected native sources become AP checks

The existing native engine and settings format are retained. New generation
exports every source selected by that engine instead of keeping shuffled NPCs,
ordinary shop stock, ground items and destructibles outside AP. A maximum
configuration has 1,211 selected checks, or 1,212 with the Master Sword; the
default configuration has 169. Fixed and unselected rewards stay native.

All 100 selected Skulltulas and all 64 purchases in an enabled shop shuffle are
networked. Their previous reward is replaced, not granted alongside an AP item.
Collection commits the check; killing an enemy or breaking a container does
not. Uncollected containers reset on an area change so their dropped reward
can be retried. A collected source stays hidden through its saved AP presence
flag, including supported age/layout variants and old-save restoration.

Native filler-only restrictions are preserved for 35 possible sources: 23
Skulltulas, nine chests and three ground pickups. Their final AP contents cannot
be progression from any game or Zelda tokens. A known list of native optional
sources receives conservative late access rules; unknown missing proofs fail
generation. The 100-token reward separately requires every moved token.

The engine exports its actual logical item set. AP access rules retain counts
for those items, including repeated keys, but do not demand unrelated rupees,
maps or bottle refills to unlock every later sphere. Scarce placement-only
items use AP's restrictive phase with progression balancing disabled. Explicit
dungeon-item, song-only, end-of-dungeon and LACS restrictions survive the final
AP fill, including when the candidate location belongs to another game.
AP's standard prefill reserves these narrow pools before unrestricted rewards;
compatible songs and dungeon rewards can cross between Zelda players.

The application adds an English/French editor driven by the same 97-control
schema as YAML/APWorld. Applied values and the UI language are used for export.
`shops_always_open` opens the eight item shops and Mask Shop at either time of
day, while retaining quest requirements and minigame hours. Native enum values
and all previous defaults remain intact. The 0.10 title and cinematic behavior
are retained: automatic introduction skipping and manual skip permissions are
separate controls.

All 205 item IDs and 304 location IDs/flags released in 0.10.0 are unchanged.
New IDs use an append-only registry; the protocol is unchanged. Existing
`.apootrr` files keep their original catalogue, placements and internal
compatibility path. Generate a new room and use a dedicated new save for the
expanded sources. Updating an old player file does not convert its rewards.

Older-save recovery shares one native adult-trade settlement subflow instead
of copying its body into every location. The two write/query waits and each
location's own save/result continuation are preserved. The native-resource
stress test with 1,212 personal rewards from the normal generated pool, 968
source callbacks and all 205 remote receipt entries uses about 30,600 events
before the separate mastered trade/sword adapters, leaving ample room within
the native 65,535-event format. This is a composition test; the final prepared
room is checked separately. See [the capacity test](../tests/test_restoration_capacity.py).

Validation includes real Archipelago 0.6.8 solo and mixed generations, combined
song/end-of-dungeon/LACS settings, and Zelda with Bloodborne and Dark Souls
Remastered. Audits verify exact source/item conservation, final placement
rules, serialized native item IDs and filler-only flags. Native resource and
event tests complement these checks. The expanded catalogue has not been
manually completed in the game; earlier 0.10 gameplay evidence is not a manual
test of every new source, option or presentation.

## 0.10.0: safe delivery, empty ammunition rewards and optional Master Sword

Incoming AP items and older-save restoration now use the native player's
action state as well as the event manager. Only ordinary locomotion can start
a grant. Crawling, fishing, item use, combat, swimming, climbing, pause and
unknown actions defer it. The drawn fishing-rod state also blocks delivery
between casts. No animation, camera or input is forced to make Link ready.
Temporary busy states do not reset an accepted receipt's delivery epoch.

DeathLink retains a queued death across a long explicitly observed busy or
paused state. It waits for normal control instead of requiring an NPC event.
Loading, a changed gameplay context and connection replacement invalidate the
hold. One inventory edge case remains to be verified in-game: if the menu
suspends every Link callback before pause is observed, the bridge cannot
distinguish that stale state from a title screen. See
[delivery safety](DELIVERY-SAFETY.md) for the native evidence and limits.

Ammunition without its required bag, quiver or seed bag now has no item effect
and no substitute rupee or presentation. The AP transaction still commits once
and permits the next reward. Local AP chests retain their authored opening and
cleanup; shops, Skulltulas, trades and restoration retain their location flags.
Required trade inputs are still consumed. Actual native resource tests cover
all 205 recipes, 72 ammunition cases and both chest presentation variants.

The new `shuffle_master_sword` extension defaults to false. When true, generation
adds a Master Sword item and a pedestal check without changing the pinned native
seed or time-travel event. The native Rauru reward remains a separate reward.
Later AP spheres conservatively require the sword, and victory requires it
explicitly. The native era swap cannot create a missing sword; final-battle
recovery requires its legitimate acquisition flag. See
[Master Sword shuffle](MASTER-SWORD.md) for the scope and gameplay limits.

The delivery and ammunition fixes can be installed with an existing player
file after closing the game. This update requires rebuilding the host and
preparing the mod because both the DLL and gameplay bridge changed. Saves,
placements and the existing room's sword behavior are retained. Enabling the
Master Sword shuffle needs a newly generated room and a new save. The engine
now exports the pedestal's access sphere as separate proof metadata, including
when Rauru stays vanilla; existing native seed bytes and sphere lists are
unchanged. All earlier AP identities are retained; one item and one location
are appended to the catalogue.

In these older generated rooms, native-local rewards remain tied to the loaded
save. They are not silently converted into extra AP checks by a client update.
See [items, checks and saves](ITEMS-AND-SAVES.md) for the distinction between
existing rooms and the expanded catalogue in newly generated 0.10.1 rooms.

## 0.9.2: ammunition requires its equipment

Native bomb, arrow and seed grants can create usable equipment when called
without its capacity upgrade. Ordinary OOTRR rewards guard these pickups, but
AP receipts previously bypassed that guard. AP now selects a native green rupee
before the presentation when the required bag, quiver or seed bag is absent.
Owning any supported tier keeps the original ammunition reward. Bombchus retain
OOTRR's separate behavior. Receipts still acknowledge once and do not block the
next item in the queue.

The same selection applies to catalogued personal physical rewards and
older-save restoration. The displayed pickup, native effect and sound use the
selected actor. Prepare an existing player file again to install the corrected
event flows; no new room or native host rebuild is required. Previously created
equipment is not removed automatically from saves.

## 0.9.1: Triforce 0.7.0 menu compatibility

Triforce 0.7.0 adds an Achievements page before the options fallback and gates
Mods input on its native transition state. The earlier AP installer required
both older dispatch blocks verbatim and rejected these tools after preparing
the room's resources. The renderer patch now attaches to the unique options
fallback and input branch, preserving both native changes. Already patched
older renderers remain accepted without changes.

The desktop preflight now validates the host, renderer, notification and game
language hooks before connecting to AP or preparing the mod. Unsupported tools
produce an actionable message at that stage. This check is read-only.

Player files, AP identities, gameplay resources, the native DLL and the engine
are unchanged. A room generated with the preceding compatible APWorld can be
prepared again; regenerating its placements is unnecessary.

## 0.9.0: setup and independent option rolls

Archipelago's Random? control rolls each field separately. Previously an unused
fixed price, goal count or song-color choice could reject generation even though
its parent setting did not use it. AP generation now resets only inactive
sub-options to their defaults. Active prices, progression choices and dependency
checks are preserved. The native settings-string validator remains strict.

Setup also retains the prepared room's automatic-connection preference. Selecting
a host checks its game files and build tools before installation, on a worker
thread so the window remains responsive. Changing the selected folder invalidates
an older check result.

Hookshot and Triforce use independent application profiles and saves. Selecting
Hookshot does not reuse the save or connection history of the same room in
Triforce. The shared AP protocol, item IDs and native received-item transactions
are unchanged. See [port compatibility](PORT-COMPATIBILITY.md) for the tested
versions and remaining limits.

The option changes were checked with Archipelago 0.6.8's real option classes and
two isolated generations: one with the player's unchanged YAML, and one with two
players, deliberately inconsistent inactive settings and an active fixed fairy
price. Both generated successfully and the active price remained exact. These
checks do not establish that every possible randomized combination is valid.

The behavior was compared with the disabled-option handling in
[OoT Randomizer](https://github.com/OoTRandomizer/OoT-Randomizer/blob/Dev/Settings.py)
and the public-to-native option translation in
[Archipelago's OoT world](https://github.com/ArchipelagoMW/Archipelago/blob/0.6.8/worlds/oot/__init__.py).

## Earlier gameplay and logic fixes

Version 0.6.1-alpha.1 retains the portable **OOTRR 0.8.1** builder and the
integration's existing AP identities. It adapts selected fixes from
[OOTRR 0.8.2](https://github.com/ootrando/ootrr/releases/tag/v0.8.2), revision
`0fa64f44b5e689f39bcf98a151fc32cb019d538e`. This is not a migration to that
builder or its renamed location catalogue.

## Connection and older-save recovery

A DeathLink packet from a replaced connection is rejected before it can enter
the current connection's death queue or duplicate filter.

Prepared adult-trade rooms can silently acknowledge a remote quest item already
spent by a completed exchange. Only a confirmed server check or durable local
history permits this route. If local history cannot be saved and the server has
not confirmed the exchange, the ordinary receipt remains available. The quiet
event advances only the received-item index; the exchange's completion and
personal reward still recover separately. Missing native flag data also uses
the ordinary receipt rather than bypassing recovery.

Granny's blue-potion shop follows the completed AP Mushroom exchange, preserving
the native purchase, price and empty-bottle requirement.

## Story and dungeon progression

The prepared mod repairs the Door of Time escape step together with the moat
Ocarina's availability. It retains the windmill's post-song action and gives the
Nocturne reward before changing the village, with the native loading wait and
fade at the lesson's start.

Native-local gifts from adult King Zora and Link the Goron stay available after
later temple progress. Story conversations do not move the Fire or Spirit quest
back to an earlier step. The Gerudo Fortress follows the Membership Card while
the carpenters retain their own rescue state. The monotonic Spirit comparison
is kept separate from the fortress's Card condition.

Generation uses corrected Forest, Fire, Water, Shadow and Well access rules.
Water's river access requires the Longshot, and basement pots require their real
keys and song. Two fixed Fire rewards and 31 pot regions are corrected without
changing physical actors or AP IDs. Existing catalogue names remain attached to
their original actor hashes, including the researched Skulltula aliases.

## Updating

Prepare the player file again and rebuild Triforce: this version changes the
native library. Existing rooms remain readable and retain their placements.
Generate a new room to use the corrected access rules; an old placement cannot
be repaired by changing its YAML. Keep a save dedicated to each room.

Use the official portable 0.8.1 builder selected during configuration. The
configuration checks its settings protocol before a build. The 0.8.2 builder
renames some locations and can assign the same old seed name to another actor;
it must not silently interpret this integration's frozen seed catalogue.

## Validation boundaries

The engine has 1,455 passing core tests, including direct dungeon gates,
multiple generated profiles, preserved key totals and old-seed round trips.
Python resource tests cover the native story flows, fortress modules and
schedules, registration, allocation budgets and idempotence. Go race tests and
the compiled C scheduler cover connection replacement and receipt/recovery
ordering, including failed journal writes.

Focused private Triforce tests cover silent spent-token replay, ordinary later
receipts, restoration of a personal check reward and Granny's native purchase.
The reports distinguish these gameplay results from resource-model checks.
They do not establish a complete playthrough of every dungeon, NPC or option
combination. Experimental native destructibles still keep their one-time break
state; collect their drop before leaving the area. Native-local rewards outside
the AP catalogue continue to follow the loaded save.
