# Ocarina of Time Remake × Archipelago

**0.2.1-alpha.1 — native integration for Triforce on Windows x64.** When the mod is enabled, the game connects to its Archipelago room from the title screen. This alpha uses OOTRR 0.8.1 and game version 1.1.1.

Title-screen connections, items received while the game was closed, local and remote chests, one Kokiri purchase, and DeathLink in both directions have been tested on **Triforce 0.6.0**. **Item presentation animations and some camera movements still need improvement.** All eight Kokiri purchases have automated coverage; they have not all been purchased in the game. Hookshot and Fritchii are not supported by this native integration.

[Port compatibility tests](docs/PORT-COMPATIBILITY.md) cover an experimental Hookshot 3.0.1 host and Fritchii 5.8.4 RomFS loading. These results do not add either host to the published installer.

## Play

Download the Windows ZIP from the [project releases](https://github.com/RAjeux/OOT-Remake-Archipelago/releases) and extract the entire archive. You need:

- Windows x64 and Triforce, including compatible build tools;
- your own **1.1.1** game dump, including its `romfs` directory, and **OOTRR portable 0.8.1**;
- **Python 3.11 or later** and **Node.js 22 or 24**;
- an Archipelago room generated with the included APWorld. The APWorld requires **Archipelago 0.6.7 or later**; direct YAML generation has been tested with **0.6.8**.

1. On the machine generating the room, install `ootrr_remake.apworld` in Archipelago. Use `Create-YAML.cmd` or the [examples](examples/) to prepare your YAML, then generate the room with the other players' YAML files.
2. On the Zelda player's PC, run `Configure-Archipelago.cmd`. Select your `.apootrr` player file, the requested directories, and the server address. The program prepares the mod and its room profile.
3. Enable **Archipelago** in Triforce Setup, then rebuild the game with **Build again**. This is required on first installation and when the native library or host tools change.
4. Launch Zelda normally from Triforce. You can close the configuration console. `Observe-Archipelago.cmd` displays connection status and notifications.

The [player guide](distribution/Guide.txt) covers installation, updates, and troubleshooting. The older French command filenames remain available for compatibility. No Nintendo game files are included in the repository or release.

## What the mod does

A chest containing an item for Zelda shows and grants the native item assigned by Archipelago. A chest containing another player's item shows an AP medal and sends the item to that player. The chest's previous local reward is not granted a second time.

Network locations are limited to the catalogued chests and, when enabled, eight Kokiri purchases. Some local rewards outside AP, including freestanding heart pieces, retain OOTRR's handling. Their exclusion from the network does not imply unchanged vanilla behavior.

Items from other worlds are delivered in order while a save is active, using the game's effects. Items sent while Zelda is closed remain on the server and are recovered after reconnection. Each grant and its received-item index are committed together; save before quitting normally.

`kokiri_shop_checks: true` adds eight one-time Kokiri purchases. Each shelf sells another player's item at its OOTRR seed price, using the game's payment and sold-out state. `death_link: true` shares deaths with other DeathLink participants. A remote death waits for an active event, such as a purchase or item receipt, to finish.

The mod automatically follows Triforce's selected game language: French uses French text, and other languages fall back to English. There is no YAML language setting. Other players' names, chat, and item names from other games retain their server wording. Configuration tools default to English and may reuse the known game language. YAML descriptions and developer documentation use English.

Restart the game after changing Triforce's language. Both translations are installed together, so changing language does not require generating a new seed.

The YAML lists the OOTRR settings supported by this APWorld, with descriptions and allowed values. Do not add omitted settings on the assumption that they work with AP: some local randomizer settings do not yet match the supported network locations or logic. Archipelago may ignore unknown YAML keys; their presence does not enable an unsupported feature.

New rooms use `reward_mode: all_locations`, `local_items: true`, and `items_handling=5`: personal items are granted physically, while the network supplies remote items and AP starting inventory. Older `all_chest_rewards` and `legacy_gear` rooms keep mode `7`. Generate a new room to change modes; do not edit an existing room's flags to convert it.

## Develop

Python client code is in `client/`, the APWorld in `apworld/`, the native bridge in `native/`, and the adapted Rust engine in `moteur/ootrr-ap/`. Historical internal names such as `ootrr_triforce` and `nx2navi` are retained for compatibility.

| Area | Main files |
| --- | --- |
| Options, AP logic, and player files | `apworld/ootrr_remake/`, `client/ootrr_triforce/settings.py`, `catalog.py` |
| Mod preparation and installation | `player.py`, `native_setup.py`, `install_mod.py` in `client/ootrr_triforce/` |
| Connections, items, checks, and DeathLink | `native/client.go`, `game.go`, `deathlink.go` |
| Triforce gameplay bridge | `native/ootrr_archipelago.inc`, `ootrr_ap_items.inc` |
| Language discovery and translations | `i18n.py`, `i18n_fr.json`, `item_names.py` in `client/ootrr_triforce/`; `native/localization.go` |
| Chests, medals, item receipts, and shops | `medallions.py`, `receipt_events.py`, `shop_events.py`, `ap_shops.py` in `client/ootrr_triforce/` |
| OOTRR engine and generation | `moteur/ootrr-ap/randomizer/core/src/bin/ootrr_ap.rs`, `slice/generate.rs` |
| Game resources and formats | `client/oot_rando/` |
| Validation | `tests/`, `tests/fixtures/`, `tools/test.py` |

Use English source messages with `tr()` and add the matching French entry to `i18n_fr.json`, preserving format placeholders. AP item names and IDs are protocol identifiers: translate display labels only, and retain the owning game's namespace. The engine's `localize` pass updates existing OOTRR-generated text inside the staged mod; it does not rebuild gameplay flows. Localization tests check catalogue coverage, language selection, legacy profiles, and cache upgrades.

### Build a release

From the repository root on Windows:

```powershell
py -3 tools/build.py
py -3 tools/verify_release.py --version 0.2.1-alpha.1
```

The output is `dist/Archipelago-OOT-Remake-0.2.1-alpha.1.zip`, including the `.pyz` client, APWorld, and their sources. `VERSION` declares the release version. The default assembly uses the supplied native DLL and WebAssembly engine without downloading dependencies. It does not rebuild Triforce.

To rebuild the supplied components:

- `py -3 tools/build.py --native` requires Go and an x64 C compiler compatible with cgo. The script enables `CGO_ENABLED=1`; set `CC` to select a compiler. Reinstall the mod and rebuild Triforce with the new DLL digest afterward.
- `py -3 tools/build.py --engine` requires Rust with the `wasm32-wasip1` target installed. This copy was built with **Rust 1.99.0**. Dependencies are vendored in `moteur/ootrr-ap/vendor/`.

Use `tools/check_catalog.py` to check the protocol tables and `tools/generate_item_header.py` to regenerate the native item table. `tools/generate_art.py` regenerates title artwork data from repository assets. After validating a new release, record its reference manifest with `tools/verify_release.py --version <version> --record-reference`; retain older manifests as historical references.

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
