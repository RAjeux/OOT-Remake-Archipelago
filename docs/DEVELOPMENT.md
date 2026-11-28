# Development setup

This guide covers a fresh source checkout, the local GUI loop and component
builds. Players should use the [installation guide](INSTALLATION.md) and the
published Windows executable. For contribution rules, read
[CONTRIBUTING.md](../CONTRIBUTING.md).

## Prerequisites

The application development loop targets **Windows x64**, using standard
**Python 3.13 with Tcl/Tk**. This matches Python CI. Python 3.14 is also used in
local validation. The commands below use an explicit virtual-environment Python
and do not require activating PowerShell scripts.

Python dependencies are listed in `requirements-dev.txt`. The source loop does
not require PyInstaller, Go, Rust or a game installation. Its resource bootstrap
downloads the exact Windows x64 Node runtime pinned in `tools/build_app.py`,
checks its archive, executable and license hashes, and caches it in
`build/app-dependencies`. It does not install Node system-wide.

For engine tests outside this launcher, install **Node.js 22 or 24** on `PATH`,
or set `OOTRR_NODE` to a compatible executable. CI uses Node 22. Go and Rust are
needed only for their source tests or rebuilding the supplied components.

## Fresh clone and source GUI

```powershell
git clone https://github.com/RAjeux/OOT-Remake-Archipelago.git
cd OOT-Remake-Archipelago
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe tools/dev.py
```

`tools/dev.py` prepares the APWorld and required runtime resources, then runs
`client/app.py` from this checkout. It never freezes an executable. After a
Python UI change, close the development app and repeat the last command. An
APWorld-affecting source change rebuilds that private APWorld on the next run;
unchanged resources are kept.

The default workspace is `build/development`:

| Path | Purpose |
|---|---|
| `resources/` | Private APWorld, native bridge, compression library, host includes and pinned Node. |
| `local/`, `roaming/` | Child process `LOCALAPPDATA` and `APPDATA`. Rooms, preferences, downloaded tools and development saves use this isolated namespace. |
| `pycache/` | Source application's Python bytecode cache. |
| `source-resources.json` | Input and output hashes used to reuse the private APWorld. |
| `self-test.json` | Result written by the optional runtime self-test. |

Normal OS `TEMP` and `TMP` are preserved. Application-owned temporary folders
can therefore appear outside `build/`; deep Windows temporary paths can exceed
the WASI resource reader's path limit. Starting the harness does not change your
normal application data, install an APWorld into Archipelago or launch Zelda.
Game preparation, APWorld installation and Play still require explicit actions
in the UI: use dedicated test installations and player files for those actions.

To keep several isolated development rooms or branches, choose another
dedicated subfolder of this checkout's `build/` directory:

```powershell
.\.venv\Scripts\python.exe tools/dev.py --workspace "build/my UI test"
```

The script rejects a workspace outside `build/` and destinations redirected
outside that private workspace. It does not reset or delete an existing profile.

### Prepare or verify without a normal GUI session

```powershell
.\.venv\Scripts\python.exe tools/dev.py --prepare-only
.\.venv\Scripts\python.exe tools/dev.py --self-test
.\.venv\Scripts\python.exe tools/dev.py --help
```

`--prepare-only` stages resources and prints their paths without executing Node
or opening Tk. It can download the pinned runtime on first use. `--self-test`
runs the real source entry point's runtime checks and exits: native DLL exports,
WASM settings/catalogue, compression, both-language settings widgets and a
temporary APWorld installation are checked in private test directories. It
does not start a game or connect to an AP server. A successful result contains
`result: PASS` and `frozen: false`; it does not validate a packaged EXE.

To reuse a previously downloaded runtime, supply both existing files:

```powershell
.\.venv\Scripts\python.exe tools/dev.py --prepare-only --node "C:\path\node.exe" --node-license "C:\path\LICENSE"
```

These must match the exact pinned runtime and original license from
`tools/build_app.py`, rather than an arbitrary Node 24 installation. Supplied
files are read and copied into the private workspace; they are not changed.

## Repository map

Read [architecture](ARCHITECTURE.md) for the complete generation, preparation,
network and save flow. Historical internal names such as `ootrr_triforce` and
`nx2navi` remain for compatibility.

| Area | Main files |
|---|---|
| Options, AP logic and player files | `apworld/ootrr_remake/`, `client/ootrr_triforce/settings.py`, `catalog.py` |
| Desktop application | `client/app.py`; `app_window.py`, `ui_theme.py`, `settings_window.py`, `app_runtime.py`, `install_service.py` in `client/ootrr_triforce/` |
| Preparation and installation | `player.py`, `native_setup.py`, `hookshot_setup.py`, `install_mod.py` |
| Connections, items, checks and DeathLink | `native/client.go`, `connection.go`, `game.go`, `deathlink.go` |
| Triforce gameplay bridge | `native/ootrr_archipelago.inc`, `ootrr_ap_items.inc` |
| Embedded connection menus | `native/ootrr_ap_menu.inc`, `ootrr_ap_hookshot_menu.inc`; `menu_setup.py`, `hookshot_setup.py` |
| Desktop connection control | `connection_window.py`, `connection_control.py`; `native/control.go` |
| Application updates | `update_window.py`, `update_service.py`; `client/app.py` helper entry points |
| Language and translations | `i18n.py`, `i18n_fr.json`, `settings_labels.py`, `settings_fr.json`, `item_names.py`; `native/localization.go` |
| Physical rewards and shops | `medallions.py`, `receipt_events.py`, `shop_events.py`, `ap_shops.py` |
| Gold Skulltulas | `skull_catalog.py`, `ap_skulls.py`; adapted engine `ootrr_ap/skulls.rs` |
| Adult trades and quest inventory | `trade_catalog.py`, `trade_events.py`, `ap_trade.py`, `trade_state.py`, `trade_receipts.py`; engine `adult_trade.rs` |
| Native generation and engine entry | `moteur/ootrr-ap/randomizer/core/src/bin/ootrr_ap.rs`, `slice/generate.rs` |
| Game resource formats | `client/oot_rando/` |
| Tests and packaging | `tests/`, `tests/fixtures/`, `tools/test.py`, `tools/build.py`, `tools/build_app.py` |

Python filenames without a full prefix above are in `client/ootrr_triforce/`.
The shared settings schema drives YAML and the editor. English source messages
use `tr()` with matching French entries, preserving placeholders. Translate
display labels, not AP identifiers or YAML keys. The engine's `localize` pass
updates generated messages in the staged mod; it does not rebuild gameplay
flows.

## Tests

Start with a focused file for the changed area, for example:

```powershell
.\.venv\Scripts\python.exe tests/test_settings_window.py
.\.venv\Scripts\python.exe tests/test_dev_setup.py
.\.venv\Scripts\python.exe tools/test.py
```

The ordinary suite assembles a candidate and checks synthetic generation,
resources, event graphs and actual desktop widgets. It needs Node 22/24 on
`PATH` or `OOTRR_NODE`; the source launcher itself selects its private pinned
Node. To reuse the development runtime for these tests without a system Node
installation:

```powershell
.\.venv\Scripts\python.exe tools/dev.py --prepare-only
$env:OOTRR_NODE = (Resolve-Path build/development/resources/runtime/node/node.exe).Path
.\.venv\Scripts\python.exe tools/test.py
```

`--c` adds C gameplay models, with GCC or Clang selected through `PATH` or `CC`.

For local protocol integration:

```powershell
$env:AP_SERVER = 'C:\ProgramData\Archipelago\ArchipelagoServer.exe'
.\.venv\Scripts\python.exe tools/test.py --c --network
```

Adjust that path, or set `AP_SOURCE` to an official Archipelago source checkout
with its dependencies available to this Python. These tests start temporary
servers; they do not run another commercial game. **Real AP generation is a
separate harness**, with a private dependency snapshot. Follow [testing](TESTING.md)
for its reproducible setup, source tests and opt-in game-resource checks.

Tests under `tests/fixtures/` use dedicated regression rooms. Simulated
inventory, event graphs and deaths cannot replace observation of the actual
camera, controller, item animation or a completed multiworld. See
[coverage and remaining gameplay checks](TEST-COVERAGE.md).

## Rebuild components

The default source launcher and packaging use the supplied
`prebuilt/windows-x64/archipelago.dll` and `client/ootrr_triforce/engine.wasm`.
Editing their source does not change those compiled files. Rebuild the relevant
component before testing its runtime behavior.

### Native DLL

Install Go and an x64 C compiler compatible with cgo. Go CI uses 1.24.9; the
module declares its minimum in `native/go.mod`. Set `CC` if the appropriate
GCC/Clang executable is not already on `PATH`:

```powershell
$env:CC = 'C:\path\to\clang.exe'
.\.venv\Scripts\python.exe tools/build.py --native
Push-Location native
go test -mod=vendor -race ./...
Pop-Location
```

The build enables `CGO_ENABLED=1`, replaces the supplied DLL and regenerates
`native/ootrr_ap_digest.h`. Keep them matched. Reprepare a private test mod and
rebuild its host to exercise that new DLL; replacing only the source GUI does
not change an already prepared game's bridge.

### Rust WASM engine

This adapted engine was built with Rust **1.99.0**. Dependencies are vendored.
Install the WASI target, then rebuild:

```powershell
rustup toolchain install 1.99.0 --profile minimal --target wasm32-wasip1
rustup run 1.99.0 .\.venv\Scripts\python.exe tools/build.py --engine
```

That command builds the `ootrr_ap` entry point offline and updates
`client/ootrr_triforce/engine.wasm`. For Rust source tests, run Cargo from
`moteur/ootrr-ap/` so it finds that directory's vendored dependency configuration:

```powershell
Push-Location moteur/ootrr-ap
cargo +1.99.0 test --locked --offline --profile ci -p ootrr-core -p ootrr-game -p ootrr-logic -p ootrr-cosmetics
Pop-Location
```

CI also builds and executes a fresh WASM in its build directory without
overwriting the tracked engine. A PR need not change a release version or
reference; identify compiled artifact updates that maintainers must verify.

### Generated tables and artwork

`tools/check_catalog.py` checks the protocol tables against the adapted engine
data. `tools/generate_item_header.py` regenerates the native item table, and
`tools/generate_art.py` regenerates title artwork data from repository assets.
Existing AP IDs and flags remain append-only. Do not regenerate fixtures or
registries merely to make a failing compatibility check pass.

### Review shop display measurements

The optional `tools/generate_shop_layout_profiles.py` maintainer tool reads an
original supported RomFS and produces numeric mesh/pose bounds and resource
hashes. It requires NumPy; the measurement environment used CPython 3.14 and
NumPy 2.5.3. Neither NumPy nor extracted meshes or animation keys are required
by the player application. Keep new measurements below `build/` for review:

```powershell
python tools/generate_shop_layout_profiles.py --romfs 'C:\path\to\romfs' --output build/shop-layout-candidate.json
```

Use `--codec-resources` when the compression runtime is in a separate prepared
resource directory. The tool never writes to the original RomFS. Review the
native shop animation commands, their actual fallback poses and selected-item
rotation before accepting a profile. A rest-mesh bound or a get-item pose alone
does not establish the shape the shop displays. Repeat the measurement and
compare its output, run the layout/pose tests, then inspect the original game
render for every supported model and the narrower Kokiri grid.

The runtime validates the measured native resource hashes and changes only
reviewed display properties. Purchase identity, prices, stock, item effects and
AP callbacks require separate tests with a coherent generated room; a gallery
which substitutes display models cannot prove those transactions. Do not
publish copied game resources or their rendered screenshots with the report.

## Build a distributable application

Install the additional packaging dependencies, then build and inspect the
Windows x64 executable:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-app.txt
.\.venv\Scripts\python.exe tools/build_app.py
$version = (Get-Content VERSION -Raw).Trim()
.\.venv\Scripts\python.exe tools/verify_app.py "dist/OOT-Remake-Archipelago-$version.exe"
```

The single windowed executable contains Python/Tk, the pinned Node runtime,
APWorld, supplied native bridge and WASM, both host adapters and notices. This
build does not compile a user's game. The application downloads the compatible
OOTRR builder when the player first needs it; game files and the selected host
remain player prerequisites.

For advanced CLI development, `tools/build.py` assembles the separate
`dist/Archipelago-OOT-Remake-<VERSION>.zip`, including the Python zipapp, command
wrappers, APWorld and engine sources. This is not the normal player download.
Maintainers record a new reference after validating a release with
`tools/verify_release.py --version <version> --record-reference`; existing
published references are never overwritten. Candidate validation and release
verification have separate CI roles described in [testing](TESTING.md).
An untagged `main` checkout may legitimately differ while `VERSION` still names
the latest release; immutable `verify_release.py` is for the exact tagged
sources. See the maintainer [release procedure](RELEASING.md).
