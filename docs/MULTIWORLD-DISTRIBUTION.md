# Multiworld item distribution

The randomizer first creates an OOTRR seed. Archipelago then moves the rewards
from this integration's network locations: the catalogued chests, the eight
enabled Kokiri purchases, and the supported enabled Gold Skulltula drops.

Rewards from sources outside that catalogue remain local to Zelda. This
includes supported shuffled NPC rewards, songs at native lesson events,
freestanding items and other local sources. They retain their seed-assigned
OOTRR reward, even while the network locations can contain another game's
items. Turning on a native-local shuffle therefore does not put all of that
source family's rewards into Archipelago.

The APWorld adds one item to the global AP pool per exported location and uses
Archipelago's fill and access rules. It does not force a local or remote owner,
reserve foreign-only test shops, or impose a 50/50 split. Games can have very
different numbers of locations; access rules and progression balancing also
affect the result. A single game's local/remote count is not a fixed quota.

To inspect a generated room, distinguish:

- Zelda-owned AP items placed in Zelda and Zelda-owned AP items placed in
  another player's game;
- the same counts restricted to the native advancement items;
- native-local rewards, which never entered the AP pool;
- unchanged vanilla quest and starting grants.

The slot-data field `local_items: true` controls delivery: personal rewards at
Zelda's network locations are granted physically, avoiding a second network
grant. It does not force those locations to contain Zelda items. The separate
common YAML `local_items` and `non_local_items` lists can constrain placement
when a player explicitly populates them.

Broader exchange of NPC and freestanding rewards requires integrating their
locations, checks and grants into AP. A forced ownership quota would not add
those missing location families or their progression rules.

See [settings compatibility](SETTINGS-COMPATIBILITY.md) and
[adult trade rewards](ADULT-TRADE-REWARDS.md) for their current scope.
