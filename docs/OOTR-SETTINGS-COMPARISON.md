# OoTR and remake settings

This project does not have complete setting parity with the separate N64
randomizer. The comparison below uses [OoTR 9.1 settings at revision
e07c384](https://github.com/OoTRandomizer/OoT-Randomizer/blob/e07c384de02c16e987652e357b6094fb895adc58/SettingsList.py)
and this integration's OOTRR 0.8.1 base. OoTR's 282 setting declarations include
desktop, file and cosmetic controls; 162 are shared seed settings. They should
not be compared directly with the remake's 118 native setting keys.

The [native compatibility table](SETTINGS-COMPATIBILITY.md) accounts for all 118
keys: 94 are exposed, and each omitted key has a specific implementation or
compatibility reason. The 36 integration controls include adult trades, the
Master Sword, DeathLink, shop hours and the [selective upstream additions](UPSTREAM-INTEGRATION.md).
Some concepts have different names or narrower scopes:

| Concept | Integration control or scope |
| --- | --- |
| Songs and shops | `shuffle_songs`, `shuffle_shops` |
| Gold Skulltulas | `shuffle_skulltulas`: 44-site subset or all 100 native sites; no separate N64 tokensanity scopes |
| Dungeon entrances | `shuffle_entrances: dungeons`; no boss or mixed entrance shuffle |
| Maps and Compasses | One combined `shuffle_mapcompass` control |
| Starting equipment | `starting_items`, `starting_songs` and AP `start_inventory` |
| Faster chests, Epona and masks | `faster_chests`, `skip_epona_race`, `skip_mask_quest` |
| Cuccos and Big Poes | `anju_one_cucco` and `big_poe_one`; fixed shortcuts, not arbitrary counts |
| Damage and health drops | `enemy_damage` affects enemy attacks; `no_heart_drops` affects random drops |

Master Quest, pre-completed dungeons, starting as adult, advanced tricks, child
trade shuffle, key rings, the Triforce Hunt and Ice Traps require further remake
implementation. They are not enabled by adding a YAML key. Silver Rupee shuffle
also needs AP item IDs and delivery effects. Native hints and chest appearances
must be based on the final AP placements before they can be exposed safely.

## Settings already handled by Archipelago

Player count, the spoiler log and weighted YAML choices belong to AP generation.
The world inherits AP's common options, including `accessibility`,
`progression_balancing`, `start_inventory`, `start_hints`,
`start_location_hints`, `exclude_locations`, `priority_locations`, `local_items`,
`non_local_items`, `item_links` and `plando_items`. See the
[AP common option definitions](https://github.com/ArchipelagoMW/Archipelago/blob/debe4cf035c7c15efe6fb95f72343af0d420c68c/Options.py).
These operate on this integration's AP items and locations; they do not add
uncatalogued native checks. The preset YAML writer lists game-specific controls;
the AP generator also accepts its common options.

## Open Rainbow Bridge

`bridge: open` is supported as a convenience choice. The bridge opens on approach
without requiring Stones or Medallions. It uses the existing native reward gate
with a zero threshold, so the generated seed stores `bridge: dungeons` and
`bridge_rewards: 0`. Leave `bridge_rewards` at its default or set it to zero;
other explicit counts conflict with `open`. This preserves the existing native
event and does not add a new game patch. The default remains `vanilla`.

The real engine test generates the alias and its explicit zero-threshold form
with the same seed, and requires identical placements and access proofs. This
does not establish gameplay coverage for every combination of settings.

## Corrected access proofs

The integration backports selected dungeon-logic fixes from [OOTRR 0.8.2,
revision 0fa64f4](https://github.com/ootrando/ootrr/releases/tag/v0.8.2), while
retaining the portable 0.8.1 builder. The five corrected dungeon files retain
their location-name sets. Frozen actor identities are preserved through the
existing AP names, including the researched Skulltula mappings. Two fixed Fire
Temple rewards and 31 pot-region assignments are corrected without changing
their physical sources or AP IDs.

These corrections affect newly generated placements and access proofs. Existing
seed files remain readable and retain their stored placements; their old
placement proof cannot be repaired by reconnecting. Generate a new room to
benefit from the corrected logic. Historical generation baselines are retained
alongside separate corrected baselines and a synthetic old-seed readback test.
This is a targeted backport, not support for every new 0.8.2 setting.
