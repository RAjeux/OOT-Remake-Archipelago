# Validation of the selective upstream candidate

Candidate: **0.10.4-alpha.1**, reviewed OOTRR source
`4fa6e5a6da839b4766bcedafb718c241a25bdd77`, compatible native constructor 0.8.1.
These results describe automated checks and explicitly scoped native observations.
They do not certify every game area or option combination.

## Automated checks

| Layer | Result and scope |
| --- | --- |
| Rust | 2,212 passed, 6 explicitly ignored; core, game, logic, cosmetics and AP export. Dump-dependent tests which return without a dump are separate from these ignored tests. |
| Portable Python/Node/Tk | 659 passed, 64 skipped in the complete portable run. Includes actual EN/FR editor widgets, aliases, source identity, event graphs, quantities, persistence and packaging. Skipped resource/platform cases are not counted as proof. |
| Native bridge | C/C++ behavioral models pass, including request scheduling, safe delivery, restoration, input ownership, menus and DeathLink. Longshot's portable request model also passes. |
| Go | Native client's race-enabled test suite passes. The distributed DLL is unchanged; the new item uses the existing event-delivery protocol. |
| Real local AP server | 13 driver scenarios pass, including offline history across four host lifetimes, reconnects, both directions of DeathLink without echo, old-save rollback and journal reconstruction, and connection UIs. These use local fixtures, not commercial peer gameplay. |
| Official AP generation | Eight scenarios pass: default, broad solo/mixed, all shops, feature/plando/trap combinations, medallion goals, night Skulltulas and explicit random colours. Two additional final-engine scenarios verify starting/removed maps and compasses. All generated Zelda manifests pass the real launcher reader and exact pool/access checks. |
| Unoptimized AP options | 25 checks pass against the official 0.6.8 option metaclass. This separately catches reserved names such as `random`, which an optimized frozen generator can hide. |
| Maximum resource builds | Both 1,229-check overlays pass: 615 personal/614 foreign rewards, and 1,229 personal rewards. They include all supported source families, QOL/difficulty features, six traps, music/SFX and custom colours. |

The demonstrated default room has **185 AP checks**. Broad coverage reaches
**1,229 including the optional Master Sword**. This is not a promise that every
configuration enables that many checks. A mixed official fill assigned one
Zelda world's checks to 399 personal, 433 other-Zelda and 397 synthetic DS3
rewards, without a general recipient quota.

The final maximum-build checks include:

- All 16 additional chests have the expected persistent flat Bool and native
  Struct mapping; all six converted frozen chests have ordinary chest actors
  with their trap AI removed.
- All 1,229 restoration routes are prepared. Native trap effects have no pouch
  grant; repeat restoration does not refreeze a previously collected local trap.
- Fourteen generated Navi travel paths retain leave-safety, timer cleanup and
  warp ordering. Cosmetics preserve the Archipelago branding.
- Largest get-item flow: 27,161 events in the mixed case, 31,399 in the personal
  case, both below the native 65,535-event limit.
- Original **186,587 RomFS files and 1,152 SDK files are unchanged**. Native
  overlays, saves and screenshots remain private and are not distributed.

The maximum overlays reused their successfully prepared native/cosmetic bases
after the final, surgical chest registration repair. The repair was applied to
base and completed overlays through the production helper; a second application
was byte-identical. The final full assertions were rerun. This is recorded as a
resumed build, not misrepresented as another fresh full constructor run.

Two separate fresh constructor/resource cases prove that `startwith` and
`remove` retain all 20 native map/compass startup setters, remove their pool
copies and replace the extra Fire Compass with filler. They preserve the
physical AP check instead of granting an already owned compass again.

## Native observations and limits

An isolated AP-enabled **Triforce 0.8.3** process loaded the final schema-2 room
resources and a copied test save. A real AP Bow gift changed the saved cursor
from 3 to 4, Bow ownership from 0 to 1 and the small quiver from 0 to 1. A
subsequent five-rupee gift changed the cursor to 5 and the balance from 0 to 5;
the measured camera angle remained unchanged and normal movement resumed.
The host used the already verified AP calling code and unchanged DLL; no game
memory, ownership flag or delivery guard was overridden to obtain these effects.

Private Longshot tests use the exact experimental source pin documented in
[the prototype notes](LONGSHOT-PROTOTYPE.md). They establish title connectivity,
reconnection and incoming DeathLink. A fully prepared new room also demonstrates
actual native ice and thaw on child Link, an acknowledged receipt with no Bow or
  quiver grant, and delivery deferred while Link descends a ladder. The first
  indoor trial did not visibly freeze Link; its cause has not been established.
  Later outdoor trials showed native ice and thaw without a code change or an
  artificial damage/animation override. These observations do not make Longshot
  a supported launcher host.

There has been no complete new-candidate playthrough on Triforce or Hookshot,
nor a complete manual tour of every source. Existing host and gameplay evidence
is separated in [host compatibility](PORT-COMPATIBILITY.md). In particular,
new difficulty settings remain experimental. Broken upstream enemy sizing and
roaming Volvagia are deliberately unavailable.

## Reproduce and inspect

Use [TESTING.md](TESTING.md) for clean-checkout commands and opt-in prerequisites.
Private evidence from this run is kept under `build/`, notably:

- `upstream-final-all-rust-maps.log`
- `upstream-final-validation-chest-summary.json`
- `upstream-private-validation-chest-final.log`
- `upstream-ap-access-campaign-final-alias/report.json`
- `upstream-map-start-campaign-final-v2/report.json`
- `MAX-e2e-0a2e560e7e/result.json` and `MAX-e2e-257aed7f99/result.json`
- `extra-compass-resource-4f64437474/result.json`
- `longshot-ice-runtime-private/` for the native receipt observations
- `triforce-major-smoke-private/major-receipts-proof.json`

The final engine is 6,417,433 bytes, SHA-256
`e9f2ce7426afbec3fc101bea374ed4b550ec9ebbe9870a3f9769122a44301c6c`.
Earlier eight-case generation/resource proofs used the private equivalent
generation build before the two map-start corrections; those corrections have
their own final-engine generation and real-resource cases above. The native
client DLL remains
`94157d944ddb153db8db08e02e11a5fc40ea9a4e06fbb66d21357534384af286`.
