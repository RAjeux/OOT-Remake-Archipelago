# Settings compatibility

This comparison uses the **OOTRR remake 0.8.1** schema vendored by this project. It does not claim parity with every setting of the separate N64 OoT Randomizer or Ship of Harkinian. The remake's menu also contains placeholder controls which its own engine cannot apply.

The native schema has **118 keys**. The current AP catalogue exposes **93 native keys**, the integration extension `adult_trade_shuffle`, and `death_link`, `shops_always_open`, `shuffle_master_sword`. Some native choice lists are deliberately restricted to implemented values.

Archipelago rolls each Random? control independently. Before generation, unused sub-options are reset to their native defaults: for example, `scrub_price_fixed` is ignored unless enabled Scrub sales use `scrub_prices: fixed`. The same rule applies to inactive shop prices, merchant prices, goal counts and song colors. Active prices, goals and progression settings are preserved. Invalid combinations of active settings still report an error; choosing Random? for every option does not guarantee a valid combination.

New rooms export every supported source selected by the existing native randomizer as an AP check. Fixed and unselected rewards retain native handling. Known optional sources use conservative late requirements; unknown missing proofs are rejected. Access rules count the engine's actual logical items, not unrelated filler. Existing player files retain their generated catalogue and any older native-local rewards.

Explicit dungeon-item, song-only, end-of-dungeon and LACS choices are enforced on final AP placements, including foreign-game locations. Standard AP restrictive prefill reserves scarce categories without a general owner quota; compatible songs and dungeon rewards can cross between Zelda players. Built-in native junk-only guards remain enforced. User-defined exclusions, hint text and chest sizing still need their own final-placement adapters; Silver Rupee shuffling needs additional AP item IDs and receipt effects.

The `adult_trade_shuffle` integration extension replaces the legacy additive trade control. It shuffles ten quest items and exports eleven trade checks, with independent inventory guards and native item delivery. It is implemented by this project's engine and client rather than the unmodified portable OOTRR 0.8.1 application. See [adult trade rewards](ADULT-TRADE-REWARDS.md). For local versus remote item ownership and the scope of the network pool, see [multiworld distribution](MULTIWORLD-DISTRIBUTION.md).

The AP-only `shuffle_master_sword` extension adds the pedestal's sword grant to the network pool while retaining Rauru's separate reward and time travel. It defaults to false. Enabling it requires a new room and save; later AP spheres and victory conservatively require the actual sword. The native engine and settings protocol are retained. `shops_always_open` separately opens the eight item shops and Mask Shop at either time of day, retaining quest locks and minigame hours. See [Master Sword shuffle](MASTER-SWORD.md).

The machine-readable companion is [settings-compatibility.json](settings-compatibility.json). Regenerate both files with `python tools/audit_settings.py --write-docs`; use `--ootrr <ootrr.exe>` to audit another installed native schema. These comparisons validate catalogue coverage, not gameplay for every combination.

| Native key | AP status | Details |
| --- | --- | --- |
| `logic_rules` | `native_unavailable` | OOTRR's native planner accepts only the default; the schema marks alternate values unsupported. |
| `starting_age` | `native_unavailable` | OOTRR's native planner accepts only the default; the schema marks alternate values unsupported. |
| `open_forest` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `open_kakariko` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `open_door_of_time` | `legacy_alias` | The legacy boolean is superseded by door_of_time_condition and its related controls. |
| `zora_fountain` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. Omitted native choices: `adult`. The native world-opening code implements Closed and Open, not the advertised child-only blockage variant. |
| `gerudo_fortress` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `shuffle_chests` | `public_network` | Every supported source selected by the native engine becomes an AP check in new rooms; fixed or unselected rewards remain native. Existing player files retain their generated catalogue. |
| `shuffle_pots` | `public_network` | Every supported source selected by the native engine becomes an AP check in new rooms; fixed or unselected rewards remain native. Existing player files retain their generated catalogue. An AP source completes only on pickup. Uncollected containers can be retried after an area reload; collected sources remain hidden through their saved AP presence flag. |
| `shuffle_crates` | `public_network` | Every supported source selected by the native engine becomes an AP check in new rooms; fixed or unselected rewards remain native. Existing player files retain their generated catalogue. An AP source completes only on pickup. Uncollected containers can be retried after an area reload; collected sources remain hidden through their saved AP presence flag. |
| `shuffle_scrubs` | `native_rejected` | The native planner accepts only off for this old selector; shuffle_scrubs_a and shuffle_scrubs_b implement the available subsets. |
| `shuffle_freestanding_items` | `public_network` | Every supported source selected by the native engine becomes an AP check in new rooms; fixed or unselected rewards remain native. Existing player files retain their generated catalogue. Native Off and Pieces are aliases which both shuffle supported heart pieces. |
| `disabled_locations` | `placement_adapter_missing` | Custom disabled locations need a validated AP exclusion selector and matching filler allocation. The native engine's built-in junk-only guards already survive the final AP fill. |
| `shuffle_smallkeys` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. Omitted native choices: `overworld`, `regional`, `remove`. The native dungeon-item planner implements only vanilla, dungeon, any_dungeon and keysanity for Small Keys. |
| `shuffle_bosskeys` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `shuffle_mapcompass` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. Omitted native choices: `overworld`. The native dungeon-item planner rejects Overworld-only Maps/Compasses; its other supported placement modes remain available. |
| `shuffle_hideoutkeys` | `native_rejected` | The native planner accepts only vanilla; roaming hideout-key placement is not implemented. |
| `shuffle_ganon_bosskey` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. Omitted native choices: `dungeons`, `hearts`, `medallions`, `stones`, `tokens`. The native planner supports the regular key-placement modes and lacs_dungeons, but not the other schema-advertised reward triggers. |
| `ganon_bosskey_stones` | `native_unavailable` | OOTRR's native planner accepts only the default; the schema marks alternate values unsupported. |
| `ganon_bosskey_medallions` | `native_unavailable` | OOTRR's native planner accepts only the default; the schema marks alternate values unsupported. |
| `ganon_bosskey_rewards` | `native_unavailable` | OOTRR's native planner accepts only the default; the schema marks alternate values unsupported. |
| `ganon_bosskey_tokens` | `native_unavailable` | OOTRR's native planner accepts only the default; the schema marks alternate values unsupported. |
| `ganon_bosskey_hearts` | `native_unavailable` | OOTRR's native planner accepts only the default; the schema marks alternate values unsupported. |
| `bridge` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. Omitted native choices: `hearts`, `medallions`, `random`, `stones`, `tokens`. The native bridge code implements Vanilla and the combined dungeon-reward threshold. AP's open choice maps to that threshold at zero rewards; the remaining schema goal variants are not implemented. The integration's `open` choice uses `bridge: dungeons` with `bridge_rewards: 0`; the bridge opens on approach without requiring dungeon rewards. |
| `bridge_stones` | `native_unavailable` | OOTRR's native planner accepts only the default; the schema marks alternate values unsupported. |
| `bridge_medallions` | `native_unavailable` | OOTRR's native planner accepts only the default; the schema marks alternate values unsupported. |
| `bridge_rewards` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `bridge_tokens` | `native_unavailable` | OOTRR's native planner accepts only the default; the schema marks alternate values unsupported. |
| `bridge_hearts` | `native_unavailable` | OOTRR's native planner accepts only the default; the schema marks alternate values unsupported. |
| `skip_ganon_trials` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `trials` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `triforce_hunt` | `native_unavailable` | OOTRR's native planner accepts only the default; the schema marks alternate values unsupported. |
| `triforce_count_per_world` | `native_unavailable` | OOTRR's native planner accepts only the default; the schema marks alternate values unsupported. |
| `triforce_goal_per_world` | `native_unavailable` | OOTRR's native planner accepts only the default; the schema marks alternate values unsupported. |
| `starting_hearts` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `starting_items` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. Omitted native choices: `zeldas_letter`. Zelda's Letter cannot be granted as an isolated starting pouch item; the supported open Kakariko story state grants it together with the corresponding quest progress. |
| `starting_songs` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `shuffle_rewards` | `public_network` | Every supported source selected by the native engine becomes an AP check in new rooms; fixed or unselected rewards remain native. Existing player files retain their generated catalogue. |
| `shuffle_boss_hearts` | `public_network` | Every supported source selected by the native engine becomes an AP check in new rooms; fixed or unselected rewards remain native. Existing player files retain their generated catalogue. |
| `shuffle_songs` | `public_network` | Every supported source selected by the native engine becomes an AP check in new rooms; fixed or unselected rewards remain native. Existing player files retain their generated catalogue. |
| `gossip_hints` | `ap_mapping_missing` | Native hints describe OOTRR's pre-AP placements. They need the final AP item and owner mapping to avoid misleading hints. |
| `faster_chests` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `start_reward` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `skip_intro` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `chests_match_contents` | `ap_mapping_missing` | Native chest size is selected before AP replaces chest contents. Sizes must be recalculated from the final AP reward. |
| `shuffle_potion_shop` | `public_network` | Every supported source selected by the native engine becomes an AP check in new rooms; fixed or unselected rewards remain native. Existing player files retain their generated catalogue. |
| `shuffle_rewards_extra` | `public_network` | Every supported source selected by the native engine becomes an AP check in new rooms; fixed or unselected rewards remain native. Existing player files retain their generated catalogue. |
| `shuffle_skulltulas` | `public_network` | Every supported source selected by the native engine becomes an AP check in new rooms; fixed or unselected rewards remain native. Existing player files retain their generated catalogue. Pinned selects 44 sites; Matched selects all 100. The 23 uncertain sites retain filler-only guards. |
| `shuffle_trade_checks` | `legacy_additive_replaced` | This portable OOTRR setting adds a bonus while retaining vanilla quest items. New AP rooms use the integration's adult_trade_shuffle extension for complete replacement; old generated rooms retain their additive behavior. |
| `shuffle_scrubs_a` | `public_network` | Every supported source selected by the native engine becomes an AP check in new rooms; fixed or unselected rewards remain native. Existing player files retain their generated catalogue. |
| `shuffle_scrubs_b` | `public_network` | Every supported source selected by the native engine becomes an AP check in new rooms; fixed or unselected rewards remain native. Existing player files retain their generated catalogue. |
| `bombchus_in_logic` | `known_native_gameplay_gap` | The native source documents Bombchus being unusable without a Bomb Bag even though this option's logic assumes they work. A logic-only toggle can therefore produce an unusable required explosive. |
| `shuffle_shops` | `public_network` | Every supported source selected by the native engine becomes an AP check in new rooms; fixed or unselected rewards remain native. Existing player files retain their generated catalogue. Every enabled mode includes all 64 purchases; deal modes affect the native pool and price layout, not recipient quotas. |
| `shuffle_cows` | `public_network` | Every supported source selected by the native engine becomes an AP check in new rooms; fixed or unselected rewards remain native. Existing player files retain their generated catalogue. |
| `shuffle_cows_other` | `derived_alias` | The native reward plan derives cows_other from shuffle_cows and does not read this independent flag. |
| `shuffle_beehives` | `public_network` | Every supported source selected by the native engine becomes an AP check in new rooms; fixed or unselected rewards remain native. Existing player files retain their generated catalogue. An AP source completes only on pickup. Uncollected containers can be retried after an area reload; collected sources remain hidden through their saved AP presence flag. |
| `skip_cutscenes` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `anju_one_cucco` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `big_poe_one` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `shuffle_treasure_reward` | `public_network` | Every supported source selected by the native engine becomes an AP check in new rooms; fixed or unselected rewards remain native. Existing player files retain their generated catalogue. |
| `shuffle_dungeon_rewards` | `public_network` | Every supported source selected by the native engine becomes an AP check in new rooms; fixed or unselected rewards remain native. Existing player files retain their generated catalogue. |
| `jabu_open` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `time_always_passes` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `early_beds` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `navi_return` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `bunny_hood` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `misc_hints` | `ap_mapping_missing` | Character hints may reference locations whose items AP moves later. An AP-aware hint pass is required. |
| `skip_epona_race` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `skip_mask_quest` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `plant_beans` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `gerudo_bridge_open` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `shuffle_entrances` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. Omitted native choices: `everything`, `overworld`. Only dungeon entrance pairing is implemented. Native overworld/everything modes are explicitly rejected because age/return/story transition handling is incomplete. |
| `shuffle_rocks` | `public_network` | Every supported source selected by the native engine becomes an AP check in new rooms; fixed or unselected rewards remain native. Existing player files retain their generated catalogue. An AP source completes only on pickup. Uncollected containers can be retried after an area reload; collected sources remain hidden through their saved AP presence flag. |
| `shuffle_grass` | `public_network` | Every supported source selected by the native engine becomes an AP check in new rooms; fixed or unselected rewards remain native. Existing player files retain their generated catalogue. An AP source completes only on pickup. Uncollected containers can be retried after an area reload; collected sources remain hidden through their saved AP presence flag. |
| `shuffle_silver_rupees` | `delivery_missing` | The native shuffle introduces dungeon-specific Silver Rupee items which have no AP item IDs or native AP receipt recipes. |
| `shuffle_frog_songs` | `public_network` | Every supported source selected by the native engine becomes an AP check in new rooms; fixed or unselected rewards remain native. Existing player files retain their generated catalogue. |
| `shuffle_frog_bug_heart` | `public_network` | Every supported source selected by the native engine becomes an AP check in new rooms; fixed or unselected rewards remain native. Existing player files retain their generated catalogue. |
| `shopsanity_prices` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `deku_bridge_safe` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `shuffle_merchants` | `public_network` | Every supported source selected by the native engine becomes an AP check in new rooms; fixed or unselected rewards remain native. Existing player files retain their generated catalogue. |
| `scrub_prices` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `scrub_price_fixed` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `scrub_hint_text` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `merchant_prices` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `merchant_price_fixed` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `lacs_rewards` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `song_harp_colors` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `shuffle_ocarinas` | `public_network` | Every supported source selected by the native engine becomes an AP check in new rooms; fixed or unselected rewards remain native. Existing player files retain their generated catalogue. |
| `fairy_prices` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `fairy_price_fixed` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `door_of_time_condition` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `enemy_health` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `enemy_damage` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `enemy_speed` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `no_heart_drops` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `no_gossip_fairies` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `no_ammo_drops` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `lose_heart_on_death` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `no_bottles_in_combat` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `enemy_regen` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `more_enemies` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `boss_minibosses` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `boss_minions` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `no_dupe_items` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `enemies_respawn_sooner` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `no_z_targeting` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `fairy_helps_enemies` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `enemy_backup` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `zora_ambush` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `bean_pitch` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `enemy_gates` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `cucco_revenge` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `enemy_spawn_combo` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `door_of_time_escape` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `door_of_time_song` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `shuffle_kokiri_sword` | `public_network` | Every supported source selected by the native engine becomes an AP check in new rooms; fixed or unselected rewards remain native. Existing player files retain their generated catalogue. |
| `skip_first_pickup_text` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `faster_blocks` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |

## Native menu placeholders

These controls appear as unavailable placeholders in OOTRR itself; listing them in a YAML would not add their engine implementation.

- Blue Fire Arrows (win / Logic).
- Sunlight Arrows (win / Logic).
- Full Wallets (win / Logic).
- Triforce Hunt Total Pieces (win / Goal).
- Triforce Hunt Pieces Location (win / Goal).
- GBK Reward Options (win / Goal).
- Ganon's Soul (win / Goal).
- Win Condition (win / Goal).
- Sleeping Waterfall (world / Area Access).
- Lock Overworld Doors (world / Area Access).
- Shuffle Boss Souls (dungeon / Dungeon Items).
- Keyrings (dungeon / Keyrings).
