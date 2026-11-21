# Settings compatibility

This comparison uses the **OOTRR remake 0.8.1** schema vendored by this project. It does not claim parity with every setting of the separate N64 OoT Randomizer or Ship of Harkinian. The remake's menu also contains placeholder controls which its own engine cannot apply.

The native schema has **118 keys**. The current AP catalogue exposes **94 native keys**, plus `death_link`. Some native choice lists are deliberately restricted to implemented values.

A local shuffle can be compatible with AP without turning all of its locations into network checks: OOTRR builds the complete canonical seed, then the AP pass changes only catalogued locations. The native search collects reachable local rewards before recording each AP sphere. Requiring every earlier AP reward preserves that conservative reachability proof. Local pickups and NPC rewards must remain present and must not receive an additional AP grant.

Settings which depend on the *final placement* need extra care. Native hint text, chest sizing and junk-only exclusions cannot simply be copied before AP replaces a reward. Silver Rupee shuffling also adds new item types that need AP IDs and receipt effects.

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
| `shuffle_chests` | `public_network` | The supported AP location family is connected to native checks and rewards; see the setting description for its exact scope. |
| `shuffle_pots` | `public_native_local` | OOTRR keeps these non-catalogued rewards local; AP moves only its separately catalogued locations. The native search settles local rewards before each counted AP sphere. These experimental native drops persist when their container is broken. Leaving before collecting a required drop can lose it; save before breaking containers. |
| `shuffle_crates` | `public_native_local` | OOTRR keeps these non-catalogued rewards local; AP moves only its separately catalogued locations. The native search settles local rewards before each counted AP sphere. These experimental native drops persist when their container is broken. Leaving before collecting a required drop can lose it; save before breaking containers. |
| `shuffle_scrubs` | `native_rejected` | The native planner accepts only off for this old selector; shuffle_scrubs_a and shuffle_scrubs_b implement the available subsets. |
| `shuffle_freestanding_items` | `public_native_local` | OOTRR keeps these non-catalogued rewards local; AP moves only its separately catalogued locations. The native search settles local rewards before each counted AP sphere. |
| `disabled_locations` | `placement_adapter_missing` | Native disabled locations receive junk rather than disappearing. AP refill would have to preserve that constraint, including its filler pool and counted access rules. |
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
| `bridge` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. Omitted native choices: `hearts`, `medallions`, `open`, `random`, `stones`, `tokens`. The native bridge code implements Vanilla and the combined dungeon-reward threshold; the other schema goal variants are not implemented. |
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
| `shuffle_rewards` | `public_native_local` | OOTRR keeps these non-catalogued rewards local; AP moves only its separately catalogued locations. The native search settles local rewards before each counted AP sphere. |
| `shuffle_boss_hearts` | `public_native_local` | OOTRR keeps these non-catalogued rewards local; AP moves only its separately catalogued locations. The native search settles local rewards before each counted AP sphere. |
| `shuffle_songs` | `public_native_local` | OOTRR keeps these non-catalogued rewards local; AP moves only its separately catalogued locations. The native search settles local rewards before each counted AP sphere. |
| `gossip_hints` | `ap_mapping_missing` | Native hints describe OOTRR's pre-AP placements. They need the final AP item and owner mapping to avoid misleading hints. |
| `faster_chests` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `start_reward` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `skip_intro` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `chests_match_contents` | `ap_mapping_missing` | Native chest size is selected before AP replaces chest contents. Sizes must be recalculated from the final AP reward. |
| `shuffle_potion_shop` | `public_native_local` | OOTRR keeps these non-catalogued rewards local; AP moves only its separately catalogued locations. The native search settles local rewards before each counted AP sphere. |
| `shuffle_rewards_extra` | `public_native_local` | OOTRR keeps these non-catalogued rewards local; AP moves only its separately catalogued locations. The native search settles local rewards before each counted AP sphere. |
| `shuffle_skulltulas` | `public_network` | The supported AP location family is connected to native checks and rewards; see the setting description for its exact scope. |
| `shuffle_trade_checks` | `public_native_local` | OOTRR keeps these non-catalogued rewards local; AP moves only its separately catalogued locations. The native search settles local rewards before each counted AP sphere. |
| `shuffle_scrubs_a` | `public_native_local` | OOTRR keeps these non-catalogued rewards local; AP moves only its separately catalogued locations. The native search settles local rewards before each counted AP sphere. |
| `shuffle_scrubs_b` | `public_native_local` | OOTRR keeps these non-catalogued rewards local; AP moves only its separately catalogued locations. The native search settles local rewards before each counted AP sphere. |
| `bombchus_in_logic` | `known_native_gameplay_gap` | The native source documents Bombchus being unusable without a Bomb Bag even though this option's logic assumes they work. A logic-only toggle can therefore produce an unusable required explosive. |
| `shuffle_shops` | `public_network` | The supported AP location family is connected to native checks and rewards; see the setting description for its exact scope. |
| `shuffle_cows` | `public_native_local` | OOTRR keeps these non-catalogued rewards local; AP moves only its separately catalogued locations. The native search settles local rewards before each counted AP sphere. |
| `shuffle_cows_other` | `derived_alias` | The native reward plan derives cows_other from shuffle_cows and does not read this independent flag. |
| `shuffle_beehives` | `public_native_local` | OOTRR keeps these non-catalogued rewards local; AP moves only its separately catalogued locations. The native search settles local rewards before each counted AP sphere. These experimental native drops persist when their container is broken. Leaving before collecting a required drop can lose it; save before breaking containers. |
| `skip_cutscenes` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `anju_one_cucco` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `big_poe_one` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `shuffle_treasure_reward` | `public_native_local` | OOTRR keeps these non-catalogued rewards local; AP moves only its separately catalogued locations. The native search settles local rewards before each counted AP sphere. |
| `shuffle_dungeon_rewards` | `public_native_local` | OOTRR keeps these non-catalogued rewards local; AP moves only its separately catalogued locations. The native search settles local rewards before each counted AP sphere. |
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
| `shuffle_entrances` | `public_native_local` | OOTRR keeps these non-catalogued rewards local; AP moves only its separately catalogued locations. The native search settles local rewards before each counted AP sphere. Omitted native choices: `everything`, `overworld`. Only dungeon entrance pairing is implemented. Native overworld/everything modes are explicitly rejected because age/return/story transition handling is incomplete. |
| `shuffle_rocks` | `public_native_local` | OOTRR keeps these non-catalogued rewards local; AP moves only its separately catalogued locations. The native search settles local rewards before each counted AP sphere. These experimental native drops persist when their container is broken. Leaving before collecting a required drop can lose it; save before breaking containers. |
| `shuffle_grass` | `public_native_local` | OOTRR keeps these non-catalogued rewards local; AP moves only its separately catalogued locations. The native search settles local rewards before each counted AP sphere. These experimental native drops persist when their container is broken. Leaving before collecting a required drop can lose it; save before breaking containers. |
| `shuffle_silver_rupees` | `delivery_missing` | The native shuffle introduces dungeon-specific Silver Rupee items which have no AP item IDs or native AP receipt recipes. |
| `shuffle_frog_songs` | `public_native_local` | OOTRR keeps these non-catalogued rewards local; AP moves only its separately catalogued locations. The native search settles local rewards before each counted AP sphere. |
| `shuffle_frog_bug_heart` | `public_native_local` | OOTRR keeps these non-catalogued rewards local; AP moves only its separately catalogued locations. The native search settles local rewards before each counted AP sphere. |
| `shopsanity_prices` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `deku_bridge_safe` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `shuffle_merchants` | `public_native_local` | OOTRR keeps these non-catalogued rewards local; AP moves only its separately catalogued locations. The native search settles local rewards before each counted AP sphere. |
| `scrub_prices` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `scrub_price_fixed` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `scrub_hint_text` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `merchant_prices` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `merchant_price_fixed` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `lacs_rewards` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `song_harp_colors` | `public` | The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation. |
| `shuffle_ocarinas` | `public_native_local` | OOTRR keeps these non-catalogued rewards local; AP moves only its separately catalogued locations. The native search settles local rewards before each counted AP sphere. |
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
| `shuffle_kokiri_sword` | `public_native_local` | OOTRR keeps these non-catalogued rewards local; AP moves only its separately catalogued locations. The native search settles local rewards before each counted AP sphere. |
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
