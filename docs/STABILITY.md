# Stability fixes and upgrade scope

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
