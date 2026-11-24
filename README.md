# Ocarina of Time Remake × Archipelago

**0.12.0-alpha.3 — a Windows application with a full-network randomizer, 119 configuration controls and isolated room profiles.** Prepare the mod, connect to Archipelago and launch Zelda from one executable. Triforce keeps its in-game connection menu; the experimental Hookshot adapter has native controls too.

The **Full network** engine adapts [Mozencaz/OotrR](https://github.com/Mozencaz/OotrR), retaining its attribution and MIT notice. The new default catalogue has **1,106 real AP checks**, including 98 Gold Skulltulas, 64 shop slots across eight shops and two newly supported loose dungeon keys. Enabled source families participate in the multiworld instead of receiving a separate local randomizer reward. Individual dungeon keys can travel through AP, alongside optional key rings. The previous OOTRR engine remains available for existing configurations and player files.

This is an alpha. Current private gameplay tests cover Triforce title-screen connection, rupees, native Bow reception and deferred incoming DeathLink; Hookshot includes Spirit Temple and fishing regressions; Fritchii includes actual external delivery, older-save recovery and bidirectional DeathLink. These tests used historical 1,104-check rooms where stated. Automated generation/resource tests cover additional settings and the new catalogue; no complete playthrough of all 1,106 checks is claimed. See [compatibility and evidence](docs/PORT-COMPATIBILITY.md).

## Play

Download **`OOT-Remake-Archipelago-0.12.0-alpha.3.exe`** from [Releases](https://github.com/RAjeux/OOT-Remake-Archipelago/releases). Python and Node.js are included; normal setup needs no console or separate runtime installation.

If Archipelago rejected the 0.12.0-alpha.1 APWorld with "expected a single directory", replace the application with this version and install its APWorld again.

Supply Windows x64, your own **game version 1.1.1**, a working **Triforce installation with its build tools**, an active Archipelago room and your `.apootrr` player file. The experimental native Hookshot adapter requires **3.0.1**, its original tools and retained build files. No Nintendo files or game hosts are distributed here.

1. Choose **Set up a room**, select the `.apootrr` file and game host, then confirm the detected installation.
2. Enter the room address and password if needed. Choose **Install and prepare** and wait for preparation and any host build to finish.
3. Choose **Play** and use a save dedicated to this room. The native client can connect at the title screen; item delivery waits for a loaded save and suitable player control.

For later sessions, choose **Play** again. **Connection** changes the prepared room's address and password without a console. In Triforce, **Options → Archipelago** controls the same connection. Hookshot provides **F1/Insert → Gameplay → AP Server / AP Connect**; use the desktop window for passwords outside printable ASCII. See the [connection guide](docs/CONNECTION-WINDOW.md).

The English [player guide](distribution/Guide.txt) and [guide français](distribution/Guide-FR.txt) explain configuration, rooms, tracking, chat, updates and troubleshooting.

## Configure a multiworld

The organizer uses **Create YAML → Settings** to edit the configuration. Choose **Full network** for a new room, adjust the supported settings, or start from **Standard**, **Maximum AP** or **Quick start**. Import/export supports YAML and JSON; imported legacy configurations retain their engine. Advanced AP common options, unknown fields and weighted settings are preserved on export.

Choose **Install APWorld** on the generating computer, restart Archipelago, save the YAML and generate with the other players' configurations as usual. The application prepares Zelda; **Archipelago still generates and hosts the multiworld**. The APWorld requires Archipelago 0.6.7 or later and has been tested with 0.6.8.

Full-network options use `generation_mode: full_network` and `full_*` keys. The 119 controls cover supported source families, dungeon items, entrances, goals, economy, starting state, quality-of-life and difficulty settings. `death_link` remains a separate AP option. Labels and help follow English/French game language; YAML keys retain their stable English spelling. A disabled or unadapted source retains native behavior; enabling a family does not make every object of that type a check.

The default catalogue has 997 locations with precise progression access and 109 with approximate access. Approximate locations are excluded from progression placement and may hold filler. Dungeon-local item modes retain their explicit restrictions. Ordinary progression can be placed in other players' games; no rule forces a share into Zelda. Randomization does not promise equal counts or progression timing between players.

Bridge conditions, zero to six trials and Ganon boss-key/LACS conditions now have matching native and AP logic. Heart goals use the remake's real heart supply and add any missing heart pieces to the normal AP pool. Economy uses the native 200/500/1,000-rupee wallets; shop and merchant prices match the advertised and charged amount. Dungeon entrance shuffle keeps paired doors, age restrictions and return routes. Overworld/interior entrance shuffle, Triforce Hunt and unimplemented silver-rupee modes are not offered. See the [catalogue and validation](docs/FULL-NETWORK.md) and [setting parity report](docs/full-settings-parity.md).

Settings validation rejects incompatible challenges: permanent heart loss with an active heart goal above three, or no random ammunition drops with every shop slot shuffled. Numbered Shopsanity retains renewable ammunition stock. Entrance layouts also check that unshuffled native equipment remains obtainable. Displaced essential shields join the ordinary AP pool when necessary; no artificial starting equipment or recipient quota is added.

Full-network preparation uses the bundled Python engine. **Legacy** uses the pinned OOTRR 0.8.1 builder, downloaded when first needed. Legacy retains its native setting names and narrower AP catalogue; the [legacy setting comparison](docs/SETTINGS-COMPATIBILITY.md) and [OoTR comparison](docs/OOTR-SETTINGS-COMPARISON.md) describe that engine. The schemas are distinct. Renaming keys does not convert a room.

Settings are fixed at generation. Use a **new room and fresh save** to adopt the full-network engine or change placements. An application update or reconnection cannot convert an existing seed. Existing `.apootrr` files and legacy room identities remain readable.

For bug fixes in an existing full room, use **Update prepared room** with the **same player file** after saving and closing Zelda. It refreshes resource allocations, native host helpers and external readiness/DeathLink resources while preserving the room identity, placements and saves. Older 0.11 rooms keep their 1,104-check catalogue and historical key behavior. New settings and the two added checks require a new generation.

Version 0.12.0-alpha.3 fixes a native-host freeze when the fisherman hands over the rod. Native hosts keep the original Player AI and their C receipt guards; the external runtime retains its separate readiness gate. Update an existing room with the same player file to apply the fix without changing the seed or save.

Choose **Child** as the starting age in Full network. Adult start is temporarily unavailable because its native opening transition can stall. Generation and preparation reject that mode; existing adult player files remain readable for diagnosis. Changing the starting age requires a new room and fresh save.

## Items, checks and saves

A personal reward uses its native model and effect. Another player's reward uses the AP medal and is sent to its recipient. An enabled AP source replaces its original local grant, including quest exchanges. Some sources retain repeatable native refills after their one-time check, such as milk from cows.

Remote items remain on the server while Zelda is closed and arrive in order after reconnection. The native bridge records the received index with each grant. Personal physical rewards are not granted again through a second network delivery. A prepared room's recovery metadata and durable history restore completed AP locations when loading an older save: personal rewards recover once to that save, while another player's check recovers without another send. Ordinary native rewards outside the catalogue still follow that save. See [items and saves](docs/ITEMS-AND-SAVES.md) for legacy details.

Major received items use the game's presentation pose and turn toward the camera. Small pickups use native displays and sounds. Receipts and recovery wait while Link is busy, including crawling, fishing, pause and events. Ammunition without its required equipment gives no ammunition, substitute reward or popup; the index still advances. Presentation and constrained-action behavior remain areas for gameplay regression testing.

`death_link: true` shares deaths through the native Triforce/Hookshot bridge or a newly prepared external runtime. A received death waits for suitable control after observed pause or constrained actions. External deaths use fresh native Player AI and live life, with no saved-health inference or death replay after reconnection. See [delivery safety](docs/DELIVERY-SAFETY.md).

## Rooms, tracker and chat

**My rooms** lists prepared native and external profiles. Name them, reopen their configuration, or activate a cached native room while Zelda is closed. A profile copy of the player file survives moving the original download. Switching hosts does not transfer saves or received-item history.

**Back up save** creates a verified copy without editing the original. Native backups cover the profile's user data and relevant history. External backups cover the explicitly selected save. Backups exclude connection passwords; automatic restore is not provided.

**Archipelago tracker** shows known checks and, for verified full-network artifacts, inventory, keys, souls and estimated access from an observed save. Select a save when there are several. Estimates are informational; the tracker does not send manual checks or expose planned rewards. The external tracker observes its existing runtime and can operate before the first save when the running seed can be verified.

The inventory tab distinguishes **Observed stock** from **Recorded progression**. New shield tracking reads saved pouch stock, so a burned Deku Shield no longer appears owned merely because it was obtained earlier. Live-only stock is unknown until a save is available. Observation never refunds a consumed item or changes AP history.

**Archipelago chat** shows recent server messages and sends only when you choose **Send**. Native chat uses Zelda's existing authenticated connection, without a second AP login. History is bounded and kept in memory. External chat shares the external runtime.

## Other ports and emulators

**Other ports and emulators…** is a separate experimental path for compatible Windows/Linux processes. Supply a supported RomFS tree or NUP, dedicated mods folder, exact game/host executable, and optionally the ROM and `progress.sav`. The application prepares a full-network artifact and uses its desktop runtime for connection, observed checks and supported receipt signaling. Keep its window open while connected. Original saves are never imported or moved.

The backend checks the seed and native runtime readiness before delivery. Actual Fritchii 5.8.4/game 1.1.1 tests now verify offline items, native presentation, pause/ladder deferral, incoming DeathLink without echo and one natural outgoing death. Other emulator revisions still need their own validation; no Linux application is packaged. See [port compatibility](docs/PORT-COMPATIBILITY.md).

The external runtime also recovers server-confirmed checks into older saves: personal rewards recover once, foreign checks restore completion without resending, and already-spent adult trade items are acknowledged quietly. Actual Fritchii native Load-menu recovery restored a personal Fire Medallion and its open chest once. That source and natural enemy death used an explicitly private relocated chest/enemy fixture; the original physical route was not a playthrough.

## Updates, data and language

Profiles, tools and settings live under `%LOCALAPPDATA%\OOTRR-Archipelago`, outside the executable. Native Hookshot uses `hosts\hookshot`; external sessions use `hosts\external\profiles`. Original host saves are not moved into another profile.

**Help → Check for updates** checks compatible releases. A signed release can be downloaded and verified using the publisher's Ed25519 key and SHA-256 checksum. A separate **Install and restart** action retains the previous executable and rolls back an immediate restart failure. Unsigned historical releases open their download page. Updating the application does not reprepare a room or modify its save; close Zelda and prepare the same player file again to install mod changes. See [signed updates](docs/SIGNED-UPDATES.md).

French game language selects French application/mod text; other languages fall back to English. Restart Zelda after changing its language. YAML keys and source messages stay English. Names, chat and foreign-game items retain server wording. Both game translations are installed together.

## Develop

The vendored engine is `client/ootrr_full/`, with its pinned revision and original hashes in `UPSTREAM.json`. Our adapters preserve old protocol identities and player files. The original codec remains in `client/oot_rando/`; the legacy Rust engine remains in `moteur/ootrr-ap/`.

| Area | Main files |
| --- | --- |
| APWorld, full schema and identities | `apworld/ootrr_remake/`, `client/ootrr_triforce/full_ap.py`, `full_catalog.json` |
| Full logic, generation and resources | `client/ootrr_full/`; `full_mod.py`, `full_events.py`, `full_extra_recovery.py`, `full_cows.py` |
| Legacy engine and catalogues | `moteur/ootrr-ap/`, `settings.py`, `catalog.py`, `ap_shops.py`, `ap_skulls.py`, `ap_trade.py` |
| Application and settings editor | `client/app.py`, `app_window.py`, `settings_editor.py`, `app_runtime.py` |
| Isolated preparation | `full_worker.py`; `full_mod.py` stages and the frozen `client/app.py` selftest |
| Profiles, backups and tracking | `room_library.py`, `room_windows.py`, `tracker_service.py` |
| Native setup and menus | `install_service.py`, `native_setup.py`, `hookshot_setup.py`, `menu_setup.py`; `native/ootrr_ap_*` |
| Native network, delivery and DeathLink | `native/client.go`, `game.go`, `connection.go`, `deathlink.go`, `ootrr_archipelago.inc` |
| Desktop controls and chat | `connection_control.py`, `connection_window.py`, `chat_window.py`; `native/control.go`, `chat.go` |
| Experimental external runtime | `external_setup.py`, `external_window.py`, `upgrade_runtime.py`, `upgrade_readiness.py`, `upgrade_deathlink.py` |
| Signed updates | `update_service.py`, `update_key.py`, `tools/sign_release.py` |
| French display text | `i18n.py`, `i18n_fr.json`, `settings_fr.json`; `native/localization.go` |
| Validation | `tests/`, `tests/fixtures/`, `tools/test.py` |

Unprefixed table paths are under `client/ootrr_triforce/`. Use English messages with `tr()` and add French entries without changing placeholders. Translate display labels, not AP identifiers or another game's item namespace.

### Build

Use Windows x64 Python with Tcl/Tk support:

```powershell
py -3 -m pip install -r requirements-app.txt
py -3 tools/build_app.py
py -3 tools/verify_app.py dist/OOT-Remake-Archipelago-0.12.0-alpha.3.exe
```

The single executable bundles Python, Tk, Node.js, both engines, APWorld, bridge, adapters and notices. `VERSION` declares its version. The 0.12.0-alpha.1 executable passed payload inspection covering 526 Python modules and its isolated selftest in 10.94 seconds with a Unicode profile and only Windows System32 on PATH. The selftest checks hashes, a real child-process Codec and Tk responsiveness while the child holds its GIL; it does not launch a game or server. Full preparation uses isolated workers with bounded progress/log transport and cancellation confined to private build caches.

`py -3 tools/build.py` makes the separate advanced CLI ZIP. `--native` needs Go and a cgo-compatible x64 compiler (`CC`); reinstall and rebuild the host after changing its DLL. `--engine` needs Rust and `wasm32-wasip1`; legacy dependencies are vendored. `tools/check_catalog.py` checks protocol tables and `tools/generate_item_header.py` regenerates the item table. [Signing instructions](docs/SIGNED-UPDATES.md) keep private keys outside the repository.

### Test

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe tools/test.py
```

The suite assembles the CLI release and checks generation, schemas, resources, receipt flows, profile transactions, YAML preservation, signatures, process workers and real Tk widgets. Node.js is required for legacy tests. `--c` adds C gameplay models with GCC or Clang through `PATH` or `CC`.

Real local-server tests require Archipelago:

```powershell
$env:AP_SERVER = 'C:\ProgramData\Archipelago\ArchipelagoServer.exe'
.\.venv\Scripts\python.exe tools/test.py --c --network
```

Alternatively set `AP_SOURCE` with dependencies installed. Windows tests load the supplied DLL in a test process; Linux builds the equivalent with Go and C. Tk and libzstd are required where relevant. From `native/`, run `go test -mod=vendor ./...`; `-race` adds concurrency checks with a suitable compiler. Fixtures and simulated states do not replace gameplay validation of inventories, animations or deaths.

## Licenses and credits

Integration code is **GPL-3.0-or-later**. Adapted [Mozencaz/OotrR](https://github.com/Mozencaz/OotrR) code and UI ideas retain their **MIT** attribution; its notices also credit imported logic data. Third-party notices include PyYAML MIT and bundled runtimes. Archipelago artwork retains its terms, including **CC BY-NC 4.0** for the colored icon and adaptations. Cinzel lettering uses OFL 1.1. See [LICENSE](LICENSE), [NOTICE](NOTICE), [REFERENCES.md](REFERENCES.md) and `client/credits/`.
