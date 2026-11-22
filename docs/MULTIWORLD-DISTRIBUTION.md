# Multiworld item distribution

The randomizer first creates an OOTRR seed. Archipelago then moves the rewards
from this integration's network locations: the catalogued chests, the selected
special deals across all eight shops, the supported enabled Gold Skulltula drops, and the
eleven adult trade checks when `adult_trade_shuffle` is enabled.

Rewards from sources outside that catalogue remain local to Zelda. This
includes other supported shuffled NPC rewards, songs at native lesson events,
freestanding items and other local sources. They retain their seed-assigned
OOTRR reward, even while the network locations can contain another game's
items. Turning on a native-local shuffle therefore does not put all of that
source family's rewards into Archipelago.

With `shuffle_shops: random_deals`, each shop rolls zero to four special deals,
including Kokiri. The native item's eligibility can reduce that number when
the selected shuffles provide fewer items a shop can sell safely. AP exports
exactly those generated deals; ordinary shop goods retain native purchases.
There is no forced Kokiri purchase or required remote recipient. Earlier rooms
keep their original eight Kokiri checks and cannot adopt the new selection by
reconnecting; generate a new room instead.

Select Random Deals explicitly. Archipelago's reserved `random` value chooses
an entire shop mode, while the APWorld maps `random_deals` to OOTRR's native
`random` mode for per-shop counts.

Full adult trade shuffle is an explicitly integrated exception. Its ten quest
items enter the AP pool and can be received from any player's game. The ten
hand-ins and the final Biggoron exchange give only their AP assignment, while
the old additive trade mode remains native-local in already generated rooms.

The APWorld adds one item to the global AP pool per exported location and uses
Archipelago's fill and access rules. It does not force a local or remote owner,
reserve foreign-only test shops, or impose a 50/50 split. Games can have very
different numbers of locations; access rules and progression balancing also
affect the result. A single game's local/remote count is not a fixed quota.

The adult trade generator first reserves its ten quest items at its ten hand-in
locations to build a native access proof and ensure all ten are exported.
Archipelago then mixes those exported items with the rest of the multiworld
pool. The intermediate reservation does not force a quest item to stay at a
trade NPC, in Zelda, or with another player.

To inspect a generated room, distinguish:

- Zelda-owned AP items placed in Zelda and Zelda-owned AP items placed in
  another player's game;
- the same counts restricted to the native advancement items;
- native-local rewards, which never entered the AP pool;
- unchanged vanilla quest and starting grants, including the ordinary adult
  trade chain when full adult trade shuffle is disabled.

The slot-data field `local_items: true` controls delivery: personal rewards at
Zelda's network locations are granted physically, avoiding a second network
grant. It does not force those locations to contain Zelda items. The separate
common YAML `local_items` and `non_local_items` lists can constrain placement
when a player explicitly populates them.

Broader exchange of the remaining NPC and freestanding rewards requires
integrating their locations, checks and grants into AP. A forced ownership quota
would not add those missing location families or their progression rules.

See [settings compatibility](SETTINGS-COMPATIBILITY.md) and
[adult trade rewards](ADULT-TRADE-REWARDS.md) for their current scope.
