# Native item-delivery safety

The shared Windows gameplay bridge defers network receipts and restoration
events until Link is alive, the save is loaded, the native event manager is
idle, the game is unpaused and the current native action permits ordinary
movement. The check applies to Triforce and Hookshot. It also gates the old
direct-grant fallback.

The supported OOT 1.1.1 action controller is read using the same path as the
native `SelectorEventQueryCheckPlayerState`: actor components at `+0x270`,
action controller at components `+0x188`, current action at controller
`+0x1c0`, and action verb at `+0x28`. The native wrapper verb `0x11a` uses
its saved verb at `+0x4c`. The ordinary movement whitelist is Walk,
WalkBackwards, Strafe, Run, TurnAround, Turn, Wait, LockOnWait, LockOnMove and
Idle. All unknown verbs and missing controllers defer delivery.

The native action-verb string/offset table confirms, among others,
`Wait=0x28`, `Fishing=0x34`, `Climb=0x46`, `ClimbLadder=0x47` and
`Crawl=0xea`. These are excluded through a whitelist, rather than a list
which assumes every unrecognised state is safe. `Sequence_IsPause`
(`0x604aebe1`) must also be readable and false. The native
`QueryNaviIsWaitPlayerStateDrawnFishingRod` checks the game's Player extension,
`+0xa38` bit `0x400`; this is a different object from the generic movement
core. The bridge follows the native player's component-manager table to that
extension. This additional guard keeps items from interrupting
fishing between casts, even when the verb temporarily returns to Wait.

This uses the game's actual states and normal receipt events. It does not
change Link's action, input, camera or position to make an item deliverable.
The native actor/controller paths were checked against the user's original
OOT 1.1.1 image; no original game files were changed or added to the project.

Temporary busy states keep the same delivery epoch. A receipt accepted by the
native queue remains pending until its saved cursor commits or the actual
gameplay context changes. The actor, GameData manager, player component and
life-object identities all participate in context changes. No timeout, pause, crawl or fishing transition
permits requesting that same receipt again. Check reporting and observing a
committed receipt remain available while Link is busy; no new grant starts.

DeathLink uses the same safe-state decision. A death received during an
explicitly observed busy or paused state is held until normal control resumes.
An inventory pause may suspend Link's callbacks longer than two seconds; this
does not discard an already held death, and a death received during that
observed pause can still be queued. Observed loading, a changed actor/manager/
player/life identity, a local death, a replaced connection or a full client
restart invalidates the hold.

One inventory edge case still needs an in-game check: if the native menu stops
all Link callbacks before the bridge can observe `Sequence_IsPause`, the DLL
only knows the previous gameplay state. It continues to reject deaths against
that stale state, as it does at the title screen. Automated tests cannot prove
that every inventory transition exposes a paused callback; an independent
main-thread lifecycle hook would be required if the supported hosts omit it.
Likewise, an entirely unobserved title/load transition which reuses every
tracked guest identity cannot be distinguished from that paused life by this
movement hook alone. This lifecycle case remains unverified in-game.

`tests/test_deathlink_host.py` compiles the real native gate against bounded
guest memory and exercises all verbs through `0x12f`, the wrapper, missing
controllers, pause/fishing/event states, actor changes and life writes.
`tests/test_restore_host.py` compiles the real scheduler and checks that busy
states neither advance the receipt cursor nor retry an accepted transaction,
while committed receipts can still be acknowledged. The Go DeathLink tests
exercise long callback-free observed pauses, exactly-once consumption, echo
suppression and invalidation boundaries. These tests do not replace a gameplay
test of crawling, fishing and the inventory on each supported host.

## External ports and emulators

The external full-network runtime requests registered native receipt events;
it does not rewrite the player's action, camera, position or saved health.
Before signaling, it verifies the exact room's seed marker, current authenticated
AP history, an idle native event manager, pause/load flags, and a native
readiness publication from the Player's own AI. Unknown or missing state keeps
the pending item queued. Observing committed receipts and reporting checks
continues while Link is busy.

Readiness version 2 uses `QueryBSAGetActionVerb` with the owning player's action
slot. The older `QueryPlayerGetCurrentActionVerb` queries an NPC's BSA target;
in the Player brain it can return zero indefinitely. Actual Fritchii gameplay
exposed that error, and the native-owning-actor query fixes it. The same normal
movement whitelist, drawn-fishing-rod query, minigame, pause and load guards are
applied in the generated native graph. Resource allocations include the new
Player brain and packed members; missing allocations previously prevented the
full mod from finishing its load on an actual host.

External DeathLink adds five unsaved flags bound to the room token. Native
Player AI publishes a fresh heartbeat and death state using
`QueryActorLife.Now`. The client requires two fresh publications before arming a
life; attaching to an already dead player never sends a death. A request uses
`OneShotLifeSetOwnLife`, subtraction mode 3, with the current native life as its
value. The game checks the seed, armed/request/fired flags, its current event,
receipt-pending state and current movement/fishing/minigame/pause/load guards
again at execution. No guessed kill address or saved-life value participates.

A death received during an explicitly observed pause or temporary busy state
waits. Loading, a changed gameplay context, a missing seed/arm flag, loss of
authenticated history or disconnection discards it. DeathLink messages are
bounded and deduplicated, exclude the local player and alias, and are never
persisted or replayed from AP item history. A native fired acknowledgement
suppresses the outgoing echo. A natural live-to-dead transition sends once per
armed life. The AP `DeathLink` tag is advertised only for a prepared artifact
whose player file enables it. The unsaved live-life publisher also keeps item
delivery closed while dead when DeathLink itself is disabled.

On 24 November 2026, actual portable Fritchii 5.8.4 gameplay with game 1.1.1 and
a real AP 0.6.8 second player verified inventory-pause holding, incoming native
Game Over without echo, no stale death after loading, ladder receipt deferral,
normal native Bow presentation, and ammunition acknowledgement without a bomb
bag or substitute. Natural outgoing death was separately tested with cloned
vanilla Dekubabas in a private map fixture: ordinary contact damage reduced
three hearts to zero and the second AP client received one death. The fixture
did not edit Link's health or position and was removed after the test.

`test_upgrade_readiness.py`, `test_upgrade_deathlink.py` and
`test_upgrade_recovery.py` also round-trip the supported game's actual native
resources. The DeathLink graph test evaluates 1,664 combinations of native
constraints. These resource/interpreter tests supplement actual gameplay; they
do not establish that every fishing/minigame/action state has been traversed on
every emulator. Old prepared external rooms require a same-player-file update
to install the corrected native graph; updating only the desktop executable
cannot replace resources already installed in a game.
