# Multiworld item distribution

The existing native randomizer creates the seed and its access proof.
Archipelago then fills every supported source selected by that randomization
in a new room. A maximum configuration has 1,211 checks, plus the optional
Master Sword. The default configuration has 169.

Enabled families include chests, shops, all 100 Skulltulas in Matched mode,
NPCs, songs, dungeon rewards, adult trades, cows, merchants, Scrubs, minigames,
boss hearts, ground pickups and destructibles. Fixed/unselected native rewards
keep their normal behavior. Older generated rooms retain any native-local
shuffles outside their original AP catalogue; a client update does not convert
them into additional network checks.

Every enabled shop mode exports all 64 purchases across eight shops. Native
stock/deal choices determine the preliminary pool and price layout before the
final AP placement. `random_deals` rolls zero to four special deals per shop;
it does not change the AP check count to zero to four. Ordinary purchases can
also contain your item or another player's. Kokiri has no forced recipient.

Select Random Deals explicitly. Archipelago's reserved `random` value chooses
an entire shop mode, while the APWorld maps `random_deals` to OOTRR's native
`random` mode for per-shop counts.

Adult trade shuffle puts its ten quest items in the AP pool. They can be
received from any player's game. The ten
hand-ins and the final Biggoron exchange give only their AP assignment, while
the old additive trade mode remains native-local in already generated rooms.

The APWorld adds one item to the global AP pool per exported location and uses
Archipelago's fill and access rules. It has no general local/remote quota,
foreign-only test shops, or imposed 50/50 split. Games can have very
different numbers of locations; access rules and progression balancing also
affect the result. A single game's local/remote count is not a fixed quota.

Explicit settings remain enforced: dungeon-only keys/maps use the recipient's
requested dungeon or region, while keysanity can send them outside Zelda.
Song-only and end-of-dungeon pools accept compatible songs or Stones/Medallions
from either Zelda player. LACS reserves that player's Light Arrows scene for
their Ganon Boss Key. Standard AP restrictive prefill reserves these narrow
domains before filling unrestricted rewards; it does not reroll the native seed
or impose a per-owner allocation on song/dungeon-reward pools.

Native junk-only guards are also retained. The 35 protected possible sources
can hold filler from any game, but not progression or Zelda tokens. Other AP
locations can still contain your own important equipment by chance.

The adult trade generator first reserves its ten quest items at its ten hand-in
locations to build a native access proof and ensure all ten are exported.
Archipelago then mixes those exported items with the rest of the multiworld
pool. The intermediate reservation does not force a quest item to stay at a
trade NPC, in Zelda, or with another player.

To inspect a generated room, distinguish:

- Zelda-owned AP items placed in Zelda and Zelda-owned AP items placed in
  another player's game;
- the same counts restricted to the native advancement items;
- fixed/unselected native rewards, and older rooms' native-local shuffles;
- unchanged vanilla quest and starting grants, including the ordinary adult
  trade chain when full adult trade shuffle is disabled.

The slot-data field `local_items: true` controls delivery: personal rewards at
Zelda's network locations are granted physically, avoiding a second network
grant. It does not force those locations to contain Zelda items. The separate
common YAML `local_items` and `non_local_items` lists can constrain placement
when a player explicitly populates them.

Actual Archipelago 0.6.8 generation tests cover maximum-coverage solo and mixed
rooms, explicit song/end-of-dungeon/LACS restrictions, and Zelda together with
Bloodborne and Dark Souls Remastered. The serialized item pool, recipient IDs,
native delivery recipes and filler-only flags are checked. This evidence does
not replace a manual collection of every original source.

The optional [Master Sword shuffle](MASTER-SWORD.md) adds one more network
reward in newly generated rooms, independently of Rauru's separate reward and
time travel. It uses the same AP fill without a recipient restriction.

See [settings compatibility](SETTINGS-COMPATIBILITY.md),
[adult trade rewards](ADULT-TRADE-REWARDS.md) and
[items and saves](ITEMS-AND-SAVES.md) for their current scope and recovery rules.
