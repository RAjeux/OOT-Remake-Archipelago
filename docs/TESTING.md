# Testing and evidence

Use the [development setup](DEVELOPMENT.md) for Python, Node and the isolated
source launcher. All commands below start at the repository root and use that
guide's Python virtual environment. [Architecture](ARCHITECTURE.md) explains
the boundaries these tests exercise. A successful resource or protocol test is
not evidence that every native animation or full playthrough works.

## Choose a useful test

| Check | Inputs | What it establishes | What it does not establish |
| --- | --- | --- | --- |
| Portable Python/Node/Tk suite | Checkout, Python/Tk, development dependencies, Node 22/24 | Packaging, option parity, event graph structure, IDs, recovery plans and actual desktop widgets | A running game, real AP fill or every game resource |
| Native Go tests | Go and vendored dependencies | Socket/history ordering, journal persistence, reconnects, rollback, local control and DeathLink state | Native inventory or Link's animation |
| C/C++ bridge models | GCC/Clang and a C++ compiler | Host guards, cursor transactions, restoration, menu editing and modeled deaths | The actual host/game object layout or camera |
| Rust source and fresh WASM tests | Rust 1.99.0, WASI target, Node | Adapted generation/access logic and a newly compiled WASM through the Python adapter | Actual AP placement or game preparation |
| Local AP protocol integration | Official AP server executable or source checkout | Real local WebSocket packets, history, ACKs, reconnects and two-client DeathLink | Gameplay or another commercial game |
| Official AP generation | Windows AP 0.6.8 and a private dependency snapshot | Actual AP fill, source/pool conservation, ownership and placement restrictions | Completion of a seed in-game |
| Real-resource build | Own supported game dump, compatible OOTRR builder and compression library | Offline preparation of native assets, event paths, registrations and recovery data | Launch, inputs, native effects, animation or full progression |
| Manual private play | Supported host/game and a separate test profile | Inputs, HUD, camera, native inventory, lifecycle and playable behavior | Every seed and settings combination |

The detailed source-family matrix and remaining observations are in
[TEST-COVERAGE.md](TEST-COVERAGE.md). Delivery-specific guards and limitations
are in [DELIVERY-SAFETY.md](DELIVERY-SAFETY.md). Keep a regression's evidence at
the level actually tested; a graph path to an item action alone does not prove
the game granted that item.

## Ordinary checks

Start with the test for the affected component, then run the portable suite:

```powershell
.\.venv\Scripts\python.exe tests/test_restoration.py
.\.venv\Scripts\python.exe tests/test_ap_test_env.py
.\.venv\Scripts\python.exe tools/test.py
.\.venv\Scripts\python.exe tools/verify_candidate.py
```

`tools/test.py` first assembles the candidate distribution from the checkout.
It does not compile the Rust engine or native Go DLL. It checks the supplied
artifacts and synthetic fixtures. Tests requiring real game data or a real AP
server remain opt-in; skipped tests are not proof for those layers. Several Tk
checks open real windows briefly and require a desktop session.

`verify_candidate.py` checks the candidate against current source inputs. Use
it for an ordinary PR without changing a published release's reference or
incrementing a version simply to satisfy CI. `verify_release.py` instead checks
an immutable published reference; recording one is a maintainer release action.

`tests/test_reward_matrix.py` runs every AP item through recovery, including
all progressive ownership masks, ammunition equipment prerequisites, full
bottle deferral and the separate dungeon counters. It also recovers every
registered foreign location twice, retaining the received-item cursor and
checking that no inventory or payment effect occurs. Its pouch-command model
does not establish native animation, stock clamping or a physical playthrough.
The quantity fixture records selected v1.1.1 metadata for all reward actors;
`tests/test_native_bundle_quantities.py` can compare it with read-only original
resources when `OOTRR_ROMFS` and `OOTRR_CODEC_RESOURCES` are supplied.

`tests/test_dispatch_banks.py` checks long pickup selectors independently of
reward effects. It compares every identity and the native fallback, typed
argument forwarding, entry-scoped participants, exact bank preload indices,
idempotence and rejection before resource writes. Native EventFlow traverses
switch branches recursively during binding, so a valid binary round-trip and
indices within the format's bounds do not establish safe native loading.
Large-room checks must include title/new-game loading and a real collection
that crosses bank boundaries, with the original heap budgets retained.

### Native Go and C/C++

```powershell
Push-Location native
go test -mod=vendor -race ./...
Pop-Location
.\.venv\Scripts\python.exe tools/test_bridge.py --cc gcc --cxx g++
```

Go's race detector and cgo need a supported platform and C compiler. CI runs
the race checks on Linux. `tools/test.py --c` invokes the same bridge runner;
use `CC`/`CXX` or its flags to select compilers. The bridge entry points are
`test_restore_host`, `test_menu_bridge`, `test_menu_editing`,
`test_language_host`, `test_link` and `test_deathlink_host`; the runner also
checks the isolated, experimental Longshot adapter.

### Rust source and a fresh WASM

Run Cargo from the engine directory so its vendored dependency configuration is
used. Leave `OOTRR_ROMFS`, `OOTRR_TEST_ROMFS` and `OOTRR_TEST_SAVES` unset for
the ordinary source tests. A fake path can opt into dump-dependent checks and
then fail; it does not simulate a game installation.

```powershell
rustup toolchain install 1.99.0 --profile minimal --target wasm32-wasip1
Push-Location moteur/ootrr-ap
cargo +1.99.0 test --locked --offline --profile ci -p ootrr-core -p ootrr-game -p ootrr-logic -p ootrr-cosmetics
cargo +1.99.0 build --locked --offline --release --target wasm32-wasip1 -p ootrr-core --bin ootrr_ap --target-dir ../../build/rust-ci
Pop-Location
.\.venv\Scripts\python.exe tools/test_built_engine.py --engine build/rust-ci/wasm32-wasip1/release/ootrr_ap.wasm
```

The last command runs the real settings and network-catalogue tests against
the selected WASM in temporary resources. It leaves the tracked
`client/ootrr_triforce/engine.wasm` unchanged. `--node` selects an explicit
Node 22/24 executable. Building that module does not update the distributed
engine; see [component builds](DEVELOPMENT.md#rebuild-components) when that is
intended.

## Local AP protocol tests

Select an official server, then run the separate network suite:

```powershell
$env:AP_SERVER = 'C:\path\to\Archipelago\ArchipelagoServer.exe'
.\.venv\Scripts\python.exe tools/test.py --c --network
```

Alternatively, unset `AP_SERVER` and set `AP_SOURCE` to an official Archipelago
source checkout containing `MultiServer.py`, with its dependencies installed
for the selected Python. `AP_SERVER` takes precedence. This suite starts local
temporary servers and clients with repository fixtures; it does not connect
to your hosted room. On Linux, the runner builds a separate native test
library when needed. Protocol tests are different from official generation:
the Windows generator harness below does **not** support `AP_SOURCE`.

### Keep private gameplay history consistent

When reusing a private room and game save, preserve both the server's item
history and the game's saved receipt cursor. Request an explicit server save,
wait for confirmation and shut the server down gracefully before copying or
restarting the fixture. Abruptly terminating the process can leave its
`.apsave` behind the game's autosave.

Before testing another receipt, verify that the server's ordered history
contains the exact item and origin prefix already consumed by the saved cursor.
A completed connection handshake alone does not establish this consistency.
For example, a game at cursor 3 cannot receive a newly sent item at server
index 1; it has already consumed that index. Such a fixture cannot diagnose a
delivery failure.

If known test history was lost, restore that exact prefix through ordinary AP
server commands, or start a fresh matched room and profile. Do not edit the
game's receipt cursor, set inventory flags or force a grant to make the probe
pass. Record the initial history length, saved cursor, new item index and final
saved cursor alongside the observed inventory and animation.

## Official Archipelago generation from a fresh checkout

This optional harness runs the **Windows Archipelago 0.6.8 frozen generator**.
Install your own official copy first; the repository neither downloads nor
redistributes it. Node 22/24 must be on `PATH` for generation. No game, SDK,
existing randomizer room or previous developer build directory is required.

First copy the generator dependencies into a fresh private directory:

```powershell
.\.venv\Scripts\python.exe tools/prepare_ap_test_env.py --ap-root 'C:\path\to\Archipelago' --output build/ap-test-dependencies
```

The bootstrap validates the exact AP version, frozen Python layout, Windows
runtime headers, required generator modules and size/count/depth bounds.
It copies only `ArchipelagoGenerate.exe`, the matching Python DLLs,
`manifest.json`, `lib/` and `data/`. It excludes installed custom worlds,
player YAMLs, room outputs, preferences and saves. Source hashes and timestamps
are checked before and after copying. Child symlinks and junctions are refused.

`ap-test-env.json` records the independent snapshot. An interrupted or changed
copy keeps an incomplete marker and cannot be used for generation. The tool
never overwrites an existing destination; choose a new name if you need a new
snapshot. Prepared dependencies can be reused across fresh result directories.
Both snapshot and result directories must resolve below this checkout's
`build/`, separately from the AP installation. A pre-existing private `lib/`
and `data/` from another workflow is not a substitute for this bootstrap.

Run one baseline generation:

```powershell
.\.venv\Scripts\python.exe tests/test_network_generation.py --ap-root 'C:\path\to\Archipelago' --dependencies build/ap-test-dependencies --output-root build/ap-generation-quick --quick
```

The harness validates the snapshot, copies its runtime into the new private
host and links only its private dependency directories. It builds and installs
the candidate APWorld from current checkout sources **inside that private
host**. It then uses fixed seeds and inspects the actual generated multidata
and Zelda player manifests. Your installed APWorld and preferences are hashed
and checked for changes; they are not used as the candidate world.

For the default, broad-settings, mixed-game and restricted-placement cases:

```powershell
.\.venv\Scripts\python.exe tests/test_network_generation.py --ap-root 'C:\path\to\Archipelago' --dependencies build/ap-test-dependencies --output-root build/ap-generation-full --restricted
```

The mixed room contains two Zelda players and a synthetic Dark Souls III peer
world. It tests actual multiworld item ownership and restrictions without
requiring that commercial game. It cannot establish a uniform distribution for
all seeds: AP logic, item groups and selected placement scopes constrain fill.

The settings-interaction matrix adds independent source families, economy,
starting inventory, progression gates and restricted pools:

```powershell
.\.venv\Scripts\python.exe tests/test_generation_matrix.py --run --ap-root 'C:\path\to\Archipelago' --dependencies build/ap-test-dependencies --output-root build/ap-generation-matrix --seeds-per-case 1
```

Without `--run`, that file only validates the matrix's typed settings. For a
larger campaign, select two or three seeds per case in a fresh result folder.
The base harness also accepts `--engine` to stage a freshly compiled WASM only
inside its private APWorld.

Each campaign writes `report.json`, generator logs and generated rooms beneath
its output directory. Check generator exit codes, pool/check conservation,
placement and recipe assertions, and the original-files-unchanged result.
Those generated rooms contain spoilers and identities from the test; attach
only the relevant sanitized evidence to an issue. Nothing under `build/` is a
release input merely because one campaign passed.

## Two OOT Remake players through every enabled check

The [28 November validation record](OVERNIGHT-VALIDATION.md) separates the
frozen campaign results from resource models and native gameplay controls.

After preparing the isolated AP dependencies described above, run:

```powershell
.\.venv\Scripts\python.exe tools/test_two_player_campaign.py --ap-root 'C:\path\to\Archipelago' --dependencies build/ap-test-dependencies --output build/two-oot-campaign --cases all --seeds-per-case 2
```

Use a new output directory. This generates 36 private two-player rooms across
18 configuration families. Each check is compared with the authoritative
multiworld's item, owner and location. Two separate processes load the shipped
native DLL and exercise collection reporting, exact filtered item histories,
duplicates, index gaps, conflicting packets, offline checks/items, restart,
lost journals, older-save recovery, deferred restoration and completion.
Enabled DeathLink configurations are checked in both directions. The audit
also checks joint progression, pool conservation and wallet-price gates.

The runner freezes its code, APWorld, DLL and Python adapter and records their
hashes with the results. `--cases default,broad` selects a shorter campaign;
`--generate-only` omits the network phase. To replay a generated two-player
room without rerolling, use `--room path/to/AP_room.zip` with a fresh output
directory. The two players must both use OOT Remake's `all_locations` mode.

The DLLs and local server are real. Native collection flags, saved receipt
cursors and completed restoration effects are explicit test models. Passing
this campaign establishes protocol behavior for every selected source; it does
not establish physical access, native inventory effects or a full playthrough.
Use separate gameplay tests for those boundaries. The ten Treasure Chest Game
puzzle chests are not exposed by the public source settings and are not silently
added to this test's reachable catalogue.

## Optional real-resource preparation

Use your own supported game 1.1.1 dump and the compatible OOTRR 0.8.1 builder.
Supply all paths explicitly, rather than relying on local defaults:

```powershell
$env:OOTRR_RUN_NETWORK_BUILD = '1'
$env:OOTRR_TEST_ROMFS = 'C:\path\to\your\romfs'
$env:OOTRR_TEST_BUILDER = 'C:\path\to\ootrr.exe'
$env:OOTRR_TEST_ZSTD_DLL = 'C:\path\to\libzstd.dll'
.\.venv\Scripts\python.exe tests/test_network_build.py
```

This Windows-only test reads the dump and prepares a separate overlay below
`build/MAX-e2e-*`. It uses the current native DLL and an intentionally synthetic
roster, then audits the prepared resources. It never installs that overlay,
launches a game or opens an AP connection. `OOTRR_NETWORK_BUILD_ALL_LOCAL=1`
adds a worst-case native-callback-size variant; it is a test roster and does
not force production items to stay in their own world. Unset these opt-in
variables after use. Do not commit or upload game dumps, saves, generated mods
or game-derived audit resources.

For a genuine ownership upper bound, also generate a separate one-player room
with the same maximum source settings. Derive its roster from its authoritative
multidata: all rewards then belong to that player naturally. Keep the original
seed, player file, roster and constructor proof together. This complements the
synthetic stress fixture; it does not replace the two-player ownership tests.

## Manual private gameplay and CI boundaries

Use a separate profile and two local AP clients for gameplay checks. Record
the host/game versions, candidate hashes, seed options and observed native
inventory rather than treating an item model as its effect. In particular,
check remote and physical local receipts, important/consumable animations,
capacity clamps, missing-equipment ammunition, source completion, shop stock,
quest replacement and both directions of DeathLink. Test reconnect with items
sent while offline, then reload an older save and confirm recovery without
duplicate foreign sends. Repeat safe-state checks while paused, crawling,
fishing, talking and changing scenes. Do not perform these experiments on an
active player's only copy of a save.

The public [checks workflow](../.github/workflows/checks.yml) runs the portable
suite and candidate validation on main/PRs, Go race checks, C/C++ bridge models,
and Rust source plus freshly built WASM checks. It also builds and inspects the
standalone Windows application in an isolated profile. A `v*` release tag must
match `VERSION` and additionally passes strict immutable-reference validation.
Normal CI has no game dump, SDK, personal save or AP installation. It therefore
does not claim real-resource preparation, official AP generation or in-game
playthrough coverage; those require the explicit procedures above.
