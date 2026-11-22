# Stability fixes and upgrade scope

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
