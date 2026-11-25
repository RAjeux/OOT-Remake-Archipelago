# Ocarina of Time Remake × Archipelago

**0.10.1-alpha.3 — one Windows application for Triforce and experimental Hookshot support.** The player package is `OOT-Remake-Archipelago-0.10.1-alpha.3.exe`. It prepares the mod, configures your connection and launches the game. Python and Node.js are included; setup downloads the compatible OOTRR 0.8.1 builder when needed and rebuilds the selected compatible host.

New rooms turn every source selected by the existing randomizer into an AP check: up to **1,212 checks with the optional Master Sword**, including all 100 Gold Skulltulas and all 64 shop purchases when enabled. Fixed and unselected native rewards keep their normal handling. A bilingual settings editor exports the chosen values directly to YAML.

The 0.10 baseline has in-game evidence for title-screen connections, offline items, personal and foreign chests, a Kokiri purchase and DeathLink on **Triforce 0.6.0**. The expanded catalogue has automated generation and resource coverage; it has **not been manually completed in the game**. Item presentation and some camera movements still need improvement. This update retains the 0.10 title, cinematic and presentation behavior.

[Port compatibility tests](docs/PORT-COMPATIBILITY.md) describe the experimental **Hookshot 3.0.1 Windows** adapter and its prerequisites. Fritchii 5.8.4 can load the RomFS overlay but has no AP gameplay backend. Other host versions, Linux and emulators are not supported by this installer.

Version 0.10.1-alpha.3 supports **Triforce 0.8.0's menu hooks**, preserving its resolution editing and tuning overlays. Updated host sources or tool-version metadata now invalidate an older compiled AP host. Close Zelda and Triforce Setup, then prepare the same native 0.10-line `.apootrr` again with the new app; **no new room or save is required for this compatibility fix**. Automated checks and private host-C compilation verify the update; they do not establish a complete gameplay playthrough. See the [compatibility note](docs/RELEASE-NOTES-0.10.1-alpha.3.md).

The native integration shipped with alpha.3 was also verified with **Triforce 0.8.1**: a private build of the actual game connected automatically to a local two-player Archipelago room, then disconnected and reconnected through the launcher's controller without restarting. This startup check used a fresh private profile and does not establish a full gameplay playthrough. See the [0.8.1 runtime check](docs/PORT-COMPATIBILITY.md#triforce-081-runtime-check).

Version 0.9.1 fixes setup with **Triforce 0.7.0**: its Achievements page and Mods transition remain intact when adding the AP menu. Setup checks the required source hooks before connecting or preparing resources. Existing player files remain compatible; this installer fix does not require a new room.

AP ammunition cannot grant its missing equipment. Bombs, arrows and seeds received without their required capacity upgrade are consumed without an inventory change, popup or substitute rupee. The received-item index still advances, so the next item can arrive normally.

## Play

Use **`OOT-Remake-Archipelago-0.10.1-alpha.3.exe`**. Published builds are listed in the [project releases](https://github.com/RAjeux/OOT-Remake-Archipelago/releases). Keep this one file wherever you prefer; no archive extraction or separate Python, Node.js or OOTRR installation is required.

You need Windows x64, a working **Triforce installation with its build tools**, your own **version 1.1.1 game files**, and an active Archipelago room with your `.apootrr` player file. Hookshot users need the supported **3.0.1 installation, original build tools and retained build files** instead. An internet connection is needed for the first download of the compatible randomizer builder. No Nintendo game files are supplied.

1. Open the application and choose **Set up a room**. Select your `.apootrr` file and **Game host**. The application finds the selected installation when possible; choose its game folder if it is not found. Its files and tools are checked before installation.
2. Enter the **room address** and its password if required, then choose **Install and prepare**. Preparation and any necessary game build run in the same window.
3. When setup finishes, choose **Play**. Zelda connects from the title screen. Use a save dedicated to this room.

After setup, open the same application and choose **Play** for later sessions. You can close the application while playing. **Connection** changes the prepared room's server and password without a console. Triforce's **Options → Archipelago** menu remains available. Hookshot provides **F1/Insert → Gameplay → AP Server / AP Connect**. These interfaces control the same connection in the selected host. See the [connection guide](docs/CONNECTION-WINDOW.md).

On the computer generating the room, choose **Create YAML**, enter your name, then choose **Choose settings…**. Search in English, French or by YAML key, choose a category and read the explanation of the current selection. Advanced and inactive controls can be hidden; their values are retained while editing. Review the summary, apply your choices and use **Save YAML**. The file contains those values with comments in the app's English or French language. **Install APWorld** installs `ootrr_remake.apworld` into an existing Archipelago installation. Restart Archipelago, then generate and host the room with the players' YAMLs as usual. Manual weighted YAMLs remain supported. The application does not generate or host rooms. The APWorld requires **Archipelago 0.6.7 or later**; generation has been tested with **0.6.8**.

Room profiles, connection settings, downloaded tools and saves are kept in `%LOCALAPPDATA%\OOTRR-Archipelago`, outside the executable's temporary files. Hookshot has a separate `hosts\hookshot` namespace; switching hosts does not transfer a save or its history. Moving or replacing the downloaded application keeps this data. Existing saves and the automatic-connection preference are preserved during setup. To update, close Zelda, let any host update finish, then prepare the same `.apootrr` file again in the new application. A different room needs its own player file and dedicated save.

Existing `.apootrr` files from the **0.10 native integration** retain their catalogue, placements and compatibility path. Generate a **new room and use a dedicated new save** to enable the expanded AP sources or change randomizer settings. Files from the superseded **0.11/0.12 Full-network experiment** are a different format and are not converted by this release; use this APWorld to generate a new room and keep the old saves separate. Updating a client or YAML does not reroll an existing room. See the [stability notes](docs/STABILITY.md).

The [player guide](distribution/Guide.txt) covers setup, updates and troubleshooting. Optional logs and embedded licenses are available under **Help**. Source code and advanced command-line tools remain available for developers in this repository.

## What the mod does

A chest containing an item for Zelda shows and grants the native item assigned by Archipelago. A chest containing another player's item shows an AP medal and sends the item to that player. The chest's previous local reward is not granted a second time.

Enabled network sources include supported chests, ordinary shop purchases and special deals, Skulltulas, NPCs, songs, dungeon rewards, adult trades, cows, merchants, Scrubs, minigames, boss hearts, ground pickups and destructibles. Only sources actually selected by the native randomizer enter the room. A maximum-coverage configuration has 1,211 such checks; the Master Sword adds one. The default configuration has 169.

Items from other worlds are delivered in order while a save is active, using the game's effects. Items sent while Zelda is closed remain on the server and are recovered after reconnection. Each grant and its received-item index are committed together; save before quitting normally.

In a prepared `all_locations` room, loading an older save also restores previously checked AP sources from the room journal and server history. Your reward is granted once to that save; another player's reward only restores the completed source, without sending it again. Fixed or unselected native rewards follow the loaded save and have no additional AP history. Existing rooms retain the restoration scope of their own generated catalogue.

Archipelago fills the selected sources without a general Zelda recipient quota. Explicit placement choices still apply: dungeon-only keys/maps remain in the recipient's Hyrule, while keysanity can send them to another game. Song-only and end-of-dungeon pools can exchange compatible rewards between Zelda players. Native filler-only guards protect 35 possible sources, including 23 uncertain Skulltulas: they cannot hold progression from any game or Zelda tokens. See [items, checks and saves](docs/ITEMS-AND-SAVES.md).

Major received items use the game's native turn toward the player camera and item presentation pose. Ordinary pickups retain their native central display and sounds.

New receipts and older-save restorations wait for normal player control. Crawling, fishing, climbing, swimming, combat, active events and pause defer delivery; unknown actions also defer it. Observed paused or busy DeathLink states retain a pending death until normal control returns. An inventory transition which suspends all callbacks before pause is observed still needs a gameplay check. See [delivery safety and validation limits](docs/DELIVERY-SAFETY.md).

Reprepared adult-trade rooms silently recover remote quest items which a completed exchange has already consumed. The corresponding check and its personal reward still recover normally. A DeathLink packet from a replaced connection is discarded. See the [stability and update notes](docs/STABILITY.md) for the targeted story fixes and validation scope.

Every non-Off `shuffle_shops` mode includes **all 64 purchases across eight shops**, including ordinary goods. `shuffle` mixes the native stock; `deals_1` through `deals_4` add special deals to the native pool and price layout, and `random_deals` rolls zero to four per shop. AP then fills the selected checks. These choices do not force foreign items or reserve Kokiri for another player. Shopsanity Prices controls the special-deal price layout. Old rooms retain their original shop selection.

`shops_always_open: true` keeps the eight item shops and the Happy Mask Shop open by day and night. Quest requirements still apply. Minigames keep their normal hours; this option is separate from the day/night cycle.

Archipelago reserves `random` (and the Random? control) for choosing a whole option value at random, which can select Off or another shop mode. Choose **Random Deals** explicitly for a variable number of deals per shop. The APWorld translates `random_deals` to OOTRR's native `random` value; native settings strings keep their original format.

`death_link: true` shares deaths with other DeathLink participants. A remote death waits for an active event, such as a purchase or item receipt, to finish.

`adult_trade_shuffle: true` replaces the adult trade rewards with AP items and puts the ten quest items in the multiworld. Talk to the appropriate NPC while owning their requested item; hidden items in the shared inventory slot are accepted automatically, and other owned trade items are retained. This mode starts with a hatched Pocket Cucco, disables trade-item expiry and removes the final three-day wait. It requires `shuffle_rewards: supported` and a newly generated room. The old additive `shuffle_trade_checks` control has been removed from new YAMLs; previously generated rooms retain their original behavior. See the [adult trade guide](docs/ADULT-TRADE-REWARDS.md).

`shuffle_master_sword: true` puts the Master Sword in the multiworld and replaces its first pedestal grant with an AP reward. Time travel and Rauru's separate reward remain available; the dungeon-reward setting controls whether his reward is shuffled. The default is `false`, retaining the native sword. This option needs a newly generated room and save; it does not change an existing room's sword. See the [Master Sword guide](docs/MASTER-SWORD.md).

For all Gold Skulltulas, choose **All 100 native sites** (`shuffle_skulltulas: matched`). **44-site subset** retains the `pinned` key; `off` leaves them unchanged. All selected sites become checks, including the filler-only sites. Collect the reward to complete its check; killing the enemy or receiving a token does not complete it. See the [Gold Skulltula guide](docs/GOLD-SKULLTULAS.md).

The app, settings labels, YAML comments and mod follow the known game language: French uses French text, and other languages fall back to English. YAML keys remain unchanged. Other players' names, chat and foreign item names retain their server wording. Developer documentation uses English.

Restart the game after changing its language. Both translations are installed together, so changing language does not require generating a new seed.

The shared schema exposes **93 native OOTRR settings, adult trades, the Master Sword, DeathLink and shop hours**: 97 controls, with one engine and no duplicate generation mode. Disabled dependent controls show their requirements. Uncollected shuffled containers can be retried after reloading the area; breaking them alone never sends their check.

**Ground pickups and heart pieces** uses the native `shuffle_freestanding_items` setting. `off` and `pieces` are aliases that both shuffle supported heart pieces; `all` adds ordinary rupees and recovery hearts, while `dungeons` and `overworld` limit those extra pickups by area. Other heart pieces may come from separately controlled chests or NPCs.

The default closed forest keeps Mido's sword-and-shield requirement. **Deku Tree and forest access: Open** opens both the Tree and forest exit. **Skip introduction automatically** skips the opening movie and Link waking up. **Manual cutscene skipping** unlocks the existing skip action; it does not automatically remove every cinematic. These retain the 0.10 behavior.

Independently randomized sub-options are ignored while their parent setting is inactive. For example, a random fixed price does not affect a sale using Cheap prices. Active settings still follow their documented dependencies; Random? on every field can produce an invalid combination.

The [complete comparison of all 118 native settings](docs/SETTINGS-COMPATIBILITY.md) explains the 25 omitted native controls, including the replaced additive trade setting, unavailable native features, Silver Rupee delivery, AP-aware hints, chest sizes and location exclusions. Do not add omitted YAML keys expecting them to enable those features.

The [OoTR comparison](docs/OOTR-SETTINGS-COMPARISON.md) distinguishes the N64 randomizer's settings from those available in the remake. `bridge: open` provides the existing zero-reward bridge condition directly in the YAML.

New rooms use `reward_mode: all_locations`, `local_items: true`, and `items_handling=5`: personal items are granted physically, while the network supplies remote items and AP starting inventory. Older `all_chest_rewards` and `legacy_gear` rooms keep mode `7`. Generate a new room to change modes; do not edit an existing room's flags to convert it.

## Develop

Python client code is in `client/`, the APWorld in `apworld/`, the native bridge in `native/`, and the adapted Rust engine in `moteur/ootrr-ap/`. Historical internal names such as `ootrr_triforce` and `nx2navi` are retained for compatibility.

| Area | Main files |
| --- | --- |
| Options, AP logic, and player files | `apworld/ootrr_remake/`, `client/ootrr_triforce/settings.py`, `catalog.py` |
| Windows application | `client/app.py`, `app_window.py`, `app_runtime.py`, `install_service.py`; `tools/build_app.py` |
| Mod preparation and installation | `player.py`, `native_setup.py`, `hookshot_setup.py`, `install_mod.py` in `client/ootrr_triforce/` |
| Connections, items, checks, and DeathLink | `native/client.go`, `connection.go`, `game.go`, `deathlink.go` |
| Triforce gameplay bridge | `native/ootrr_archipelago.inc`, `ootrr_ap_items.inc` |
| Embedded connection menu | `native/ootrr_ap_menu.inc`, `client/ootrr_triforce/menu_setup.py` |
| Hookshot host and menu adapter | `native/ootrr_ap_hookshot.inc`, `ootrr_ap_hookshot_menu.inc`; `hookshot_setup.py` |
| Desktop connection window | `client/ootrr_triforce/connection_window.py`, `connection_control.py`; `native/control.go` |
| Language discovery and translations | `i18n.py`, `i18n_fr.json`, `item_names.py` in `client/ootrr_triforce/`; `native/localization.go` |
| Chests, medals, item receipts, and shops | `medallions.py`, `receipt_events.py`, `shop_events.py`, `ap_shops.py` in `client/ootrr_triforce/` |
| Gold Skulltula identities and pickup flows | `skull_catalog.py`, `ap_skulls.py` in `client/ootrr_triforce/`; `ootrr_ap/skulls.rs` in the adapted engine |
| Full adult trades and quest inventory | `trade_catalog.py`, `trade_events.py`, `ap_trade.py`, `trade_state.py`, `trade_receipts.py`; engine `adult_trade.rs` |
| OOTRR engine and generation | `moteur/ootrr-ap/randomizer/core/src/bin/ootrr_ap.rs`, `slice/generate.rs` |
| Game resources and formats | `client/oot_rando/` |
| Validation | `tests/`, `tests/fixtures/`, `tools/test.py` |

Use English source messages with `tr()` and add the matching French entry to `i18n_fr.json`, preserving format placeholders. AP item names and IDs are protocol identifiers: translate display labels only, and retain the owning game's namespace. The engine's `localize` pass updates existing OOTRR-generated text inside the staged mod; it does not rebuild gameplay flows. Localization tests check catalogue coverage, language selection, legacy profiles, and cache upgrades.

### Build the Windows application

Use Windows x64 Python with Tcl/Tk support and install the packaging dependencies:

```powershell
py -3 -m pip install -r requirements-app.txt
py -3 tools/build_app.py
py -3 tools/verify_app.py dist/OOT-Remake-Archipelago-0.10.1-alpha.3.exe
```

`tools/build_app.py` creates the single windowed executable in `dist/`. It bundles the Python runtime, Tk, the pinned Node.js runtime, the APWorld, native bridge, both host adapters and notices. The compatible OOTRR builder is downloaded by the application on first use; game files and the selected host are supplied by the player. `VERSION` declares the release version. The build uses the supplied native DLL and WebAssembly engine and does not build a user's game.

For advanced CLI development, `py -3 tools/build.py` assembles `dist/Archipelago-OOT-Remake-0.10.1-alpha.3.zip`, including `Client-OOT-Remake.pyz`, command wrappers, APWorld and engine sources. This is separate from the normal player download. After validating a ZIP, record its reference with `tools/verify_release.py --version <version> --record-reference`; retain older manifests unchanged.

To rebuild the supplied components:

- `py -3 tools/build.py --native` requires Go and an x64 C compiler compatible with cgo. The script enables `CGO_ENABLED=1`; set `CC` to select a compiler. Reinstall the mod and rebuild Triforce with the new DLL digest afterward.
- `py -3 tools/build.py --engine` requires Rust with the `wasm32-wasip1` target installed. This copy was built with **Rust 1.99.0**. Dependencies are vendored in `moteur/ootrr-ap/vendor/`.

Use `tools/check_catalog.py` to check the protocol tables and `tools/generate_item_header.py` to regenerate the native item table. `tools/generate_art.py` regenerates title artwork data from repository assets. Application logs and corresponding-source notices can be opened through **Help** in the executable.

### Run tests

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe tools/test.py
```

The suite assembles the release and checks generation, resources, and event graphs using synthetic data. Node.js is required for engine tests. `--c` adds gameplay bridge tests using a C model, with GCC or Clang available through `PATH` or `CC`.

Network tests start a real temporary Archipelago server on the local machine:

```powershell
$env:AP_SERVER = 'C:\ProgramData\Archipelago\ArchipelagoServer.exe'
.\.venv\Scripts\python.exe tools/test.py --c --network
```

Adjust the path, or set `AP_SOURCE` to an Archipelago source checkout with its dependencies installed. On Windows, tests load the supplied DLL in a test process. On Linux, they build its equivalent with Go and C; Tk and libzstd are also required. Coverage includes history after a complete shutdown, reconnection, mode `5` without duplicate personal rewards, and DeathLink deferred during an event. Run Go tests from `native/` with `go test -mod=vendor ./...`.

Rooms in `tests/fixtures/` are dedicated regression fixtures. Test life states are simulated: these checks do not replace in-game validation of animations, inventory, or Link's death.

Real Archipelago 0.6.8 generation checks cover two default solo seeds, maximum-coverage solo and mixed rooms, and combined song-only/end-of-dungeon/LACS restrictions. A separate room combines Zelda, Bloodborne and Dark Souls Remastered. Audits compare exact source and item counts, final placement restrictions, serialized native delivery IDs and filler-only protection. These are generation and resource checks, not a manual playthrough of every source.

## Licenses and credits

Integration code is distributed under **GPL-3.0-or-later**, with separate licenses for third-party components. Archipelago artwork retains its own terms, including **CC BY-NC 4.0** for the colored icon and its adaptations. The title lettering is rendered for this project using the Cinzel font under OFL 1.1. See [LICENSE](LICENSE), [NOTICE](NOTICE), and [REFERENCES.md](REFERENCES.md).
