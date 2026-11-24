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
`QueryNaviIsWaitPlayerStateDrawnFishingRod` checks player component
`+0xa38` bit `0x400`; this additional guard keeps items from interrupting
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
