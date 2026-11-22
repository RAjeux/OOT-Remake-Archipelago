# Ocarina of Time Remake × Archipelago

**0.7.0-alpha.1 — one Windows application for Triforce.** Download `OOT-Remake-Archipelago-0.7.0-alpha.1.exe` to prepare the mod, configure your room and launch the game. The application includes Python and Node.js, downloads the compatible OOTRR 0.8.1 builder when needed, and rebuilds Triforce automatically during setup.

Title-screen connections, items received while the game was closed, local and remote chests, one Kokiri purchase, and DeathLink in both directions have been tested on **Triforce 0.6.0**. **Item presentation animations and some camera movements still need improvement.** All eight Kokiri purchases have automated coverage; they have not all been purchased in the game. Hookshot and Fritchii are not supported by this native integration.

[Port compatibility tests](docs/PORT-COMPATIBILITY.md) cover an experimental Hookshot 3.0.1 host and Fritchii 5.8.4 RomFS loading. These results do not add either host to the published installer.

## Play

Download **`OOT-Remake-Archipelago-0.7.0-alpha.1.exe`** from the [project releases](https://github.com/RAjeux/OOT-Remake-Archipelago/releases). Keep this one file wherever you prefer; no archive extraction or separate Python, Node.js or OOTRR installation is required.

You need Windows x64, a working **Triforce installation with its build tools**, your own **version 1.1.1 game files**, and an active Archipelago room with your `.apootrr` player file. An internet connection is needed for the first download of the compatible builder. No Nintendo game files are supplied.

1. Open the application and choose **Set up a room**. Select your `.apootrr` file. The application finds your Triforce installation when possible; choose its game folder if it is not found.
2. Enter the **room address** and its password if required, then choose **Install and prepare**. Preparation and any necessary game build run in the same window.
3. When setup finishes, choose **Play**. Zelda connects from the title screen. Use a save dedicated to this room.

After setup, open the same application and choose **Play** for later sessions. You can close the application while playing. **Connection** changes the prepared room's server and password without a console. Zelda's **Options → Archipelago** menu remains available and controls the same connection. See the [connection guide](docs/CONNECTION-WINDOW.md).

On the computer generating the room, choose **Create YAML** in the same application. **Install APWorld** installs the world into an existing Archipelago installation; **Save YAML** writes your player configuration with all supported settings. Edit that YAML, then generate and host the room with Archipelago and the other players' YAML files as usual. The application does not generate or host rooms. The APWorld requires **Archipelago 0.6.7 or later**; generation has been tested with **0.6.8**.

Room profiles, connection settings, downloaded tools and saves are kept in `%LOCALAPPDATA%\OOTRR-Archipelago`, outside the executable's temporary files. Moving or replacing the downloaded application keeps this data. Existing saves are preserved during setup. To update, close Zelda, let any Triforce update finish, then prepare the same `.apootrr` file again in the new application. A different room needs its own player file and dedicated save.

Existing rooms retain their placements. Generate a new room to use the corrected dungeon access rules described in the [stability notes](docs/STABILITY.md); an existing room's placement proof cannot be changed by reconnecting. Enabling the full adult trade shuffle also requires a new room and a fresh save.

The [player guide](distribution/Guide.txt) covers setup, updates and troubleshooting. Optional logs and embedded licenses are available under **Help**. Source code and advanced command-line tools remain available for developers in this repository.

## What the mod does

A chest containing an item for Zelda shows and grants the native item assigned by Archipelago. A chest containing another player's item shows an AP medal and sends the item to that player. The chest's previous local reward is not granted a second time.

Network locations cover the catalogued chests and, when enabled, eight Kokiri purchases, up to 77 supported Gold Skulltula drops and eleven adult trade rewards. Other sources, including other shuffled NPC rewards and freestanding items, retain OOTRR's local handling. Their exclusion from the network does not imply unchanged vanilla behavior.

Items from other worlds are delivered in order while a save is active, using the game's effects. Items sent while Zelda is closed remain on the server and are recovered after reconnection. Each grant and its received-item index are committed together; save before quitting normally.

In a newly prepared `all_locations` room with personal physical rewards, loading an older save also restores previously checked AP locations. Your reward is granted once to that save; another player's reward only restores the completed location, without sending it again. A durable room journal and the server's checked locations supply this history. This covers AP chests, enabled Kokiri purchases, supported Gold Skulltulas and shuffled adult trades. OOTRR's native-local rewards outside that catalogue still follow the selected save; they do not have an AP check history. Reconfigure an existing player file to prepare the restoration events before using this feature.

Major received items use the game's native turn toward the player camera and item presentation pose. Ordinary pickups retain their native central display and sounds.

Reprepared adult-trade rooms silently recover remote quest items which a completed exchange has already consumed. The corresponding check and its personal reward still recover normally. A DeathLink packet from a replaced connection is discarded. See the [stability and update notes](docs/STABILITY.md) for the targeted story fixes and validation scope.

`shuffle_shops: shuffle` uses OOTRR's normal shop shuffle and adds eight one-time Kokiri purchases to the AP pool. Each can contain your own item or another player's item, at its OOTRR seed price. Your items use their native appearance and effects; remote items use the AP medal. Single-player rooms work too. Native `deals_1` through `deals_4` and `random` shop modes are also available; shops outside the Kokiri catalogue keep their native local rewards. `shuffle_shops: off` keeps shops outside the AP pool. The former `kokiri_shop_checks` test option has been removed; old generated rooms retain their existing placements.

`death_link: true` shares deaths with other DeathLink participants. A remote death waits for an active event, such as a purchase or item receipt, to finish.

`adult_trade_shuffle: true` replaces the adult trade rewards with AP items and puts the ten quest items in the multiworld. Talk to the appropriate NPC while owning their requested item; hidden items in the shared inventory slot are accepted automatically, and other owned trade items are retained. This mode starts with a hatched Pocket Cucco, disables trade-item expiry and removes the final three-day wait. It requires `shuffle_rewards: supported` and a newly generated room. The old additive `shuffle_trade_checks` control has been removed from new YAMLs; previously generated rooms retain their original behavior. See the [adult trade guide](docs/ADULT-TRADE-REWARDS.md).

`shuffle_skulltulas` offers `off`, `pinned` for 44 firmly identified native locations, and `matched` for the supported researched matches. The AP check completes on collecting the reward, not on killing the enemy or receiving a token. `matched` normally has 76 eligible checks, or 77 with supported planted/starting beans; 23 uncertain matches remain native-local. Tests cover generation, resources and event flows, plus private in-game pickup sequences and older-save recovery. Every original site and reward has not been played through. See the [Gold Skulltula guide](docs/GOLD-SKULLTULAS.md) and [example YAML](examples/Gold-Skulltulas.yaml) for the coverage and remaining presentation limits.

The mod automatically follows Triforce's selected game language: French uses French text, and other languages fall back to English. There is no YAML language setting. Other players' names, chat, and item names from other games retain their server wording. Configuration tools default to English and may reuse the known game language. YAML descriptions and developer documentation use English.

Restart the game after changing Triforce's language. Both translations are installed together, so changing language does not require generating a new seed.

The YAML exposes **93 native OOTRR settings, the adult trade extension and DeathLink**, with descriptions, allowed values and dependency checks. Native-local shuffles include supported NPC and song rewards, cows, ground pickups, destructibles, dungeon entrances, and prices. OOTRR builds those rewards from the same seed that proves the AP access rules; AP moves only its catalogued rewards. Experimental destructibles retain OOTRR's one-time break persistence: leaving their drop behind can lose it.

The [complete comparison of all 118 native settings](docs/SETTINGS-COMPATIBILITY.md) explains the 25 omitted native controls, including the replaced additive trade setting, unavailable native features, Silver Rupee delivery, AP-aware hints, chest sizes and location exclusions. Do not add omitted YAML keys expecting them to enable those features.

The [OoTR comparison](docs/OOTR-SETTINGS-COMPARISON.md) distinguishes the N64 randomizer's settings from those available in the remake. `bridge: open` provides the existing zero-reward bridge condition directly in the YAML.

New rooms use `reward_mode: all_locations`, `local_items: true`, and `items_handling=5`: personal items are granted physically, while the network supplies remote items and AP starting inventory. Older `all_chest_rewards` and `legacy_gear` rooms keep mode `7`. Generate a new room to change modes; do not edit an existing room's flags to convert it.

## Develop

Python client code is in `client/`, the APWorld in `apworld/`, the native bridge in `native/`, and the adapted Rust engine in `moteur/ootrr-ap/`. Historical internal names such as `ootrr_triforce` and `nx2navi` are retained for compatibility.

| Area | Main files |
| --- | --- |
| Options, AP logic, and player files | `apworld/ootrr_remake/`, `client/ootrr_triforce/settings.py`, `catalog.py` |
| Windows application | `client/app.py`, `app_window.py`, `app_runtime.py`, `install_service.py`; `tools/build_app.py` |
| Mod preparation and installation | `player.py`, `native_setup.py`, `install_mod.py` in `client/ootrr_triforce/` |
| Connections, items, checks, and DeathLink | `native/client.go`, `connection.go`, `game.go`, `deathlink.go` |
| Triforce gameplay bridge | `native/ootrr_archipelago.inc`, `ootrr_ap_items.inc` |
| Embedded connection menu | `native/ootrr_ap_menu.inc`, `client/ootrr_triforce/menu_setup.py` |
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
py -3 tools/verify_app.py dist/OOT-Remake-Archipelago-0.7.0-alpha.1.exe
```

`tools/build_app.py` creates the single windowed executable in `dist/`. It bundles the Python runtime, Tk, the pinned Node.js runtime, the APWorld, native bridge and notices. The compatible OOTRR builder is downloaded by the application on first use; game files and Triforce are supplied by the player. `VERSION` declares the release version. The build uses the supplied native DLL and WebAssembly engine and does not build a user's game.

For advanced CLI development, `py -3 tools/build.py` still assembles `dist/Archipelago-OOT-Remake-0.7.0-alpha.1.zip`, including `Client-OOT-Remake.pyz`, command wrappers, APWorld and engine sources. This is separate from the normal player download. After validating a legacy ZIP, record a new reference with `tools/verify_release.py --version <version> --record-reference`; retain older manifests unchanged.

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

## Licenses and credits

Integration code is distributed under **GPL-3.0-or-later**, with separate licenses for third-party components. Archipelago artwork retains its own terms, including **CC BY-NC 4.0** for the colored icon and its adaptations. The title lettering is rendered for this project using the Cinzel font under OFL 1.1. See [LICENSE](LICENSE), [NOTICE](NOTICE), and [REFERENCES.md](REFERENCES.md).
