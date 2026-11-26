# Contributing

This repository contains the Archipelago integration, desktop launcher and an
adapted OOTRR engine. Start with [development setup](docs/DEVELOPMENT.md), then
use the [architecture guide](docs/ARCHITECTURE.md) to find the relevant layer.
The upstream guide in `moteur/ootrr-ap/CONTRIBUTING.md` describes OOTRR itself;
the instructions here apply to this integration.

## Start with a source checkout

Use Windows x64 Python **3.13 with Tcl/Tk** for the supported development loop.
Python 3.13 is the CI baseline; the source launcher is also checked locally
with Python 3.14. From the repository root:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe tools/dev.py
```

The first preparation downloads the verified, pinned Node runtime. The app then
runs the Python files in your checkout directly. Close it, edit the source and
run the same command again; rebuilding the executable is unnecessary.
Application data is isolated under `build/development`, so this entry point
does not reuse your normal room profiles or saves. It does not install a global
APWorld or prepare a game automatically. See [development setup](docs/DEVELOPMENT.md)
for the resource-only and self-test modes.

## Choose a focused change

Keep a pull request focused on one behavior and base it on `main`. Describe the
problem, the resulting behavior and the checks you actually ran. For visual
changes, include a screenshot with synthetic room/player data. For gameplay
changes, distinguish generated-resource tests, simulated execution and observed
gameplay; a successful build is not a completed playthrough.

Do not bump `VERSION`, create a release, or replace a published
`tests/reference-*.json` for an ordinary contribution. Pull-request CI checks
the candidate against its current source; release tags separately check their
immutable references. `main` can legitimately differ from the latest release
while `VERSION` still names that release. Run immutable release verification
only from the exact tagged sources. Maintainers handle release versions and
publication through the [release procedure](docs/RELEASING.md).

## Preserve compatibility

- Existing AP item/location IDs and released completion flags are stable.
  Append new IDs through the versioned registry; do not reorder an old list to
  generate replacement IDs. Add a regression proving old identities remain
  unchanged.
- Previously generated `.apootrr` files keep their catalogue, placements and
  delivery mode. Introduce new behavior through generation and compatible
  preparation paths; do not silently reinterpret an old room or convert its
  save format.
- A new check needs a physical identity, collection condition, replacement of
  the original reward, access rule and older-save recovery. An extra AP popup
  beside an unchanged native reward is not a complete replacement. See
  [extending network coverage](docs/ITEMS-AND-SAVES.md#extending-network-coverage).
- Item delivery and DeathLink must respect the game's actual readiness. Keep
  pending work until it can run safely, and keep grants and acknowledgement
  consistent. Include reconnect, replay or older-save cases when affected.
- Keep host-specific profiles separate. Development and tests must not migrate
  a player's existing saves or overwrite another installed mod.

Use English source messages with `tr()` and add their French translations to
`client/ootrr_triforce/i18n_fr.json`, preserving placeholders. AP names, YAML
keys and protocol IDs remain canonical; translate display text rather than
identifiers. Settings have one shared schema, not a parallel UI-only schema.

## Validate the changed layer

The [testing guide](docs/TESTING.md) gives commands and prerequisites for the
portable suite, C bridge models, Go, Rust, real AP generation and optional game
resource checks. Run focused checks while developing, then the relevant suite
before submitting. Report required checks you could not run.

Python edits load directly in the source launcher. Changes to the Rust engine
need a freshly built WASM for local runtime testing; native Go changes need a
matching DLL and digest. [Development setup](docs/DEVELOPMENT.md#rebuild-components)
explains those commands. The shipping application uses the supplied compiled
components: source tests alone do not update them. Identify required generated
artifact updates in the PR so maintainers can verify them before release.

## Source and diagnostic data

Do not submit game dumps, keys, extracted commercial resources, actual saves,
connection passwords or personal paths. Use the repository's synthetic fixtures
and private test copies. Remove secrets and identifying data from logs and
screenshots. The bug-report template describes useful reproduction details.

Contributions to the integration use GPL-3.0-or-later. Retain attribution and
third-party license notices when adapting code; see [LICENSE](LICENSE),
[NOTICE](NOTICE) and [REFERENCES.md](REFERENCES.md).
