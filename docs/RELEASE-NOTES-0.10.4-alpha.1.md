# 0.10.4 alpha 1: more AP checks and selective upstream improvements

**Windows x64 prerelease.** This keeps the native 0.10 integration and adds
reviewed OOTRR access rules, 17 physical sources and optional settings for new
rooms. It remains an alpha with experimental difficulty settings.

## Download and install

- **Players:** [download the Windows launcher](https://github.com/RAjeux/OOT-Remake-Archipelago/releases/download/v0.10.4-alpha.1/OOT-Remake-Archipelago-0.10.4-alpha.1.exe). The single EXE includes the AP client, APWorld, Python and Node runtimes.
- **Organizers:** use the launcher's **Install APWorld** action to install the matching world and generation runtime, then restart Archipelago before generating. The [standalone APWorld](https://github.com/RAjeux/OOT-Remake-Archipelago/releases/download/v0.10.4-alpha.1/ootrr_remake.apworld) is also available.
- You need your own **game 1.1.1 files** and a compatible host with its build tools. No Nintendo game files or prebuilt Zelda executable are included. The compatible OOTRR **0.8.1** constructor is downloaded when first needed.

[Installation guide](https://github.com/RAjeux/OOT-Remake-Archipelago/blob/v0.10.4-alpha.1/docs/INSTALLATION.md) · [Installation en français](https://github.com/RAjeux/OOT-Remake-Archipelago/blob/v0.10.4-alpha.1/docs/INSTALLATION.fr.md)

## Changes for new rooms

- **17 additional physical checks**, including six converted frozen chests, other reviewed chests and the separately selected underwater Ruto's Letter pickup. The demonstrated default room has **185 checks**; tested broad coverage reaches **1,229 including the optional Master Sword**. Selected options determine the count.
- Current remake access rules exported to AP, with the selected source's AP reward replacing its donor reward in logic and gameplay.
- **130 settings** with English/French help: medallion-based goals and song triggers, Skulltula timing, free Scarecrow, dungeon key tracking, owned-equipment shortcuts, minigame/travel options and other quality-of-life controls.
- Optional native **Ice Traps**, individual colours, music/SFX shuffles and personal-item plando. Trap substitutions consume eligible filler; plando consumes existing item copies and validates restrictions and reachability.
- Reviewed **experimental difficulty options** in a separate native pass. Selected AP source actors remain protected. Known broken enemy sizing, size-based health and roaming Volvagia stay unavailable.

The project's AP connection, in-game menu, title branding, native presentations,
save cursor, older-save recovery and DeathLink remain in place. See the
[integration details and deliberate differences](https://github.com/RAjeux/OOT-Remake-Archipelago/blob/v0.10.4-alpha.1/docs/UPSTREAM-INTEGRATION.md).

## Existing rooms and saves

**You can continue a supported native 0.10 room.** Update the launcher and keep
the same `.apootrr` and save. If preparation is requested, close Zelda and its
builder and prepare that same player file again. Existing catalogue, settings
and placements do not change; native 0.10 YAMLs remain supported.

**New sources and options require the matching APWorld and a newly generated
room**, with its new player file and a dedicated save. Updating the EXE or
APWorld does not add them to an existing room. The discontinued Full 0.11/0.12
player-file format is not converted.

## Validation and limits

The recorded checks include **2,212 Rust tests passed** with six ignored,
**659 portable Python/Node/Tk tests passed** with 64 skipped, native Go and
C/C++ checks, 13 local-server scenarios, official AP 0.6.8 generation and
two maximum 1,229-check resource overlays. Skipped checks do not establish
gameplay coverage. Native Triforce 0.8.3 observations include actual Bow/quiver
and five-rupee receipts, saved-cursor persistence, stable rupee camera and
normal movement. The catalogue and all option combinations have not received
a complete in-game playthrough.

**Triforce Windows x64 is the main route. Hookshot 3.0.1 remains experimental.
Longshot is an internal prototype, not a supported launcher host.** Emulator AP
gameplay and Linux are unsupported by this installer.

See [scoped validation](https://github.com/RAjeux/OOT-Remake-Archipelago/blob/v0.10.4-alpha.1/docs/UPSTREAM-VALIDATION.md),
[host compatibility](https://github.com/RAjeux/OOT-Remake-Archipelago/blob/v0.10.4-alpha.1/docs/PORT-COMPATIBILITY.md)
and the [update guide](https://github.com/RAjeux/OOT-Remake-Archipelago/blob/v0.10.4-alpha.1/docs/UPDATING.md).
