# Port compatibility

Use the [current 0.10.3-alpha.1 launcher](https://github.com/RAjeux/OOT-Remake-Archipelago/releases/tag/v0.10.3-alpha.1) and the [installation guide](INSTALLATION.md). This page separates current setup requirements from the historical tests supporting them.

## Current support

| Host | Installation status | What has been checked |
| --- | --- | --- |
| **Triforce, Windows x64** | Main supported route, with game version **1.1.1** and the host's build tools. The installer checks source hooks and tool metadata before preparing. | **0.8.3:** actual title-screen connection and same-process reconnect. **0.8.1:** actual startup/reconnect. **0.8.0:** menu/source compatibility and private compilation. Earlier **0.6.0** gameplay evidence is separate. |
| **Hookshot 3.0.1, Windows x64** | **Experimental**, pinned to exact host/menu sources with original tools and retained build files. Other revisions are rejected. | Adapter/menu compilation and installer checks; earlier prototype gameplay observations below. No complete current-installer playthrough is claimed. |
| **Fritchii 5.8.4** | **No AP gameplay backend.** Not an installation target for this launcher. | RomFS overlay loading and the title badge only. |
| Other hosts, other Hookshot revisions or Linux | Unsupported by this installer. | Loading a mod or running a host on another platform does not establish AP item/check support. |

Triforce 0.8.3's startup/reconnect result is not an inventory, DeathLink or full-playthrough result. The expanded AP catalogue has automated generation/resource coverage but has not been manually completed in the game. See [testing](TESTING.md) and [delivery safety](DELIVERY-SAFETY.md).

## Triforce setup

Follow the [official Triforce installation guide](https://triforceproject.com/#install), keep its build tools and first confirm that the base game launches. Then close Zelda and Triforce Setup before preparing the AP room in the current launcher. The compatible OOTRR builder used by this integration is downloaded separately by the launcher; it does not replace the host's own setup instructions.

After updating Triforce, let its update finish and use the same native 0.10 `.apootrr` and room save if the AP launcher requests preparation again. The updated host/tool metadata invalidates an older AP-enabled build when a rebuild is needed. Unknown or ambiguous layouts are rejected; newer host versions are not automatically certified by an older runtime check.

## Hookshot setup

The [official Hookshot source and installation instructions](https://github.com/ItsNotRexed/Hookshot#install-and-play) and [3.0.1 release page](https://github.com/ItsNotRexed/Hookshot/releases/tag/v3.0.1) identify the host project. This adapter requires **3.0.1**, even if upstream has newer releases. For a first installation, the Triforce route above is the main supported choice.

Choose **Set up a room → Game host → Hookshot (experimental)** in the current launcher. Supply the completed 3.0.1 installation, its original tools and retained build files. Exact host/menu source hashes are checked before a private tool copy is prepared. The launcher does not download Hookshot or game files. Close Zelda and its builder before installation.

Preparation builds the host/menu and installs the AP mod. **F1/Insert → Gameplay** contains **AP Server**, **AP Password**, **AP Password action**, **AP Automatic connection**, **AP Connect** and **AP Disconnect**. These use Hookshot's text editor, controller navigation and paste support. Its native editor accepts printable ASCII; use the launcher's **Connection** window for passwords containing other characters. The saved password can then be kept in the game menu. Triforce retains **Options → Archipelago**.

Hookshot profiles are under `%LOCALAPPDATA%\OOTRR-Archipelago\hosts\hookshot`. Saves and room history stay separate from Triforce, even for the same player file. Original tools are retained; adapted copies live in the application's data folder. Run only one host at a time for the same AP player slot: separate profiles do not create another server slot. Hookshot AP host notices currently go to its log; item messages and receipt effects belong to the game.

The packaged adapter was introduced in 0.9.0. Its compilation and installer checks are distinct from the earlier gameplay prototype documented below.

## Historical validation records

The versions and executable names below identify what was tested. **Use the current launcher for installation**, not an older binary mentioned as historical evidence.

### Triforce 0.8.3 runtime check

Verified on Windows x64 with the 0.10.2-alpha.1 native integration source.
The original host/menu hooks and local menu headers remain compatible;
no additional C or menu patch was needed. The private SDK build completed,
then the actual game connected automatically to an official local AP 0.6.8
server in 6.34 seconds. A second test AP client joined and disconnect/reconnect
succeeded in the same Triforce process. The title screen with New Game and
Settings was inspected from a real rendered frame.

No user save was loaded and no private progress save was created. The game,
SDK and saved options were preserved in the original installation. The
headless fixture was ended by its owner after a window-close timeout; this
does not establish a native clean-quit or gameplay/inventory/DeathLink test.

### Triforce 0.8.1 runtime check

Verified on Windows x64 on 2026-11-25 using the unchanged native integration
shipped in `OOT-Remake-Archipelago-0.10.1-alpha.3.exe`. The installed 0.8.1
host and menu sources retain the supported hooks. A private copy of its SDK
successfully rebuilt and linked both AP-enabled game binaries.

The actual Triforce process then ran with real offscreen GPU rendering and a
fresh private profile. Its native AP module connected automatically to the
official Archipelago 0.6.8 server on loopback, using the repository's two-player
Zelda/DS3 room fixture. A second AP test client joined as Ami; the DS3 game
itself was not run. Disconnect and reconnect through the launcher's existing
connection controller succeeded in the same running Triforce process.

Opening cinematics were inspected from rendered frames. The exact title logo,
in-game AP menu interaction, item/check delivery, DeathLink and a complete
gameplay traversal were not verified in this run. No user save was loaded or
changed, and no private progress save was created. The original Triforce
installation, sources and saved options were preserved.

This check used the historical alpha.3 build. For preparation today, use the
[current launcher](INSTALLATION.md#download-the-current-launcher), finish the
host update and prepare the same supported native 0.10 player file when prompted.
No new room is required for this host compatibility update.

### Triforce 0.8.0 in 0.10.1-alpha.3

The installer supports the updated menu hooks while preserving native
resolution editing and tuning overlays. Its source preflight still rejects
unknown or ambiguous layouts. Newer host-source or tool-version files
invalidate an older compiled AP host; current builds remain reusable.

The compatibility fix originally shipped in 0.10.1-alpha.3 and remains in the
current native 0.10 line. Use the [current preparation instructions](INSTALLATION.md#player-prepare-and-play)
with the current launcher; the historical executable name is not a download
recommendation. A host compatibility rebuild changes neither placements nor saves
and requires no new room.

Automated menu, installer and cache checks plus private host-C compilation
cover this update. The earlier gameplay observations below remain separate
evidence; they do not establish a complete manual playthrough on 0.8.0.
See [the compatibility release note](RELEASE-NOTES-0.10.1-alpha.3.md).

### Earlier gameplay and overlay observations

Local tests were performed on 21 November 2026 with game version 1.1.1. Each host used a separate test profile; existing game saves and host configurations were preserved.

| Host | Verified behavior | Distribution status |
| --- | --- | --- |
| Triforce 0.6.0, Windows | Native title-screen connection, item delivery, reconnection, checks and DeathLink; see the main README for the gameplay coverage and remaining presentation issues. | Historical native gameplay evidence; current setup still checks host compatibility. |
| Hookshot 3.0.1, Windows | An experimental rebuilt host connects before the title screen. Real remote item delivery, saving, incoming DeathLink, and receiving an item sent while the game was closed were verified in a new game. | The adapter was introduced in 0.9.0 and remains experimental in the current launcher; prerequisites above. |
| Fritchii 5.8.4, Windows | The supplied NUP boots to the French title screen. The AP RomFS overlay loads through LayeredFS and displays the Archipelago title badge; both title-screen tests ran at 60 FPS. | RomFS loading verified. No emulator AP runtime is implemented or validated. |

### Earlier Hookshot gameplay prototype

The unmodified Hookshot installation does not expose all the helper names and notification functions expected by the Triforce adapter. The experiment added compatible GameData helpers and the AP bridge to a private host build. The two installed hosts used identical guest `image.bin` contents, and both the syntax probe and full isolated build succeeded.

The prototype uses the same AP DLL and registered receipt events as the released client. AP item IDs, canonical names, room token, and save cursor are preserved. These gameplay results predate the packaged 0.9.0 adapter and its new menu; they do not constitute a complete playthrough of the current installer.

The separate **Connect-Archipelago.pyw** window was also tested with Hookshot
3.0.1 and the 0.4.0-alpha.1 native bridge in an isolated build. At Zelda's title
screen it displayed the running client's status, handled a wrong then corrected
room password, disconnected, and reconnected through the actual desktop buttons.
Closing the window left the game connected. Socket ownership confirmed that
Hookshot owned Zelda's only AP connection. This interface needs no Hookshot menu
patch; it still requires the experimental gameplay bridge and its matching host
build. The 0.9.0 installer now prepares the pinned adapter; this earlier desktop
test remains separate evidence from the new installer tests.

The gameplay test used a new private save and a copied local room with a second test player. It does not establish that every physical chest, all eight shop purchases, or every item presentation has been replayed on Hookshot. A natural outgoing DeathLink has not been tested in this host.

The first remote check granted five rupees and saved received index 1. An incoming DeathLink then changed Link's life from 12 to 0 without an outgoing echo. A second five-rupee item was sent while no Hookshot game process was running. After restarting and loading the same private save, the game reached ten rupees and saved received index 2, with exactly one new receipt event. The first item and the previous DeathLink were not replayed.

### Longshot internal prototype

The separate [Longshot source prototype](LONGSHOT-PROTOTYPE.md) has actual
Windows title-screen AP connection, reconnection and isolated incoming-DeathLink
evidence at one pinned source revision. It remains internal: there is no
Longshot launcher option or claim of complete receipt, rollback or gameplay
compatibility.

### Fritchii scope

Fritchii's NUP loader handles the standalone update container directly; conversion to NSP or XCI was not required. The portable test profile used this layout:

```text
<portable-app>/user/load/0400486024DEC000/Archipelago/romfs/
```

Only RomFS resources were copied for the overlay test. No Windows AP DLL, host include, existing save, or ExeFS patch was installed in the emulator. The observed AP title badge proves asset loading, not an AP connection or an inventory grant. The game's normal native texts remain localized by the game.

A complete emulator backend must detect checks, request receipt events on the game thread, commit the saved received-item cursor, and integrate life/death state. Fritchii has a debugger interface, but a memory debugger alone is not a validated implementation of these transactions.

### Why the external save bridge is not a full fallback

The legacy save bridge only supports a subset of equipment and currency. It does not implement the complete item catalogue, shop purchases, or DeathLink. Removing the `all_locations`/native-host guards would allow unsupported items to be consumed without their effects. Those guards remain in place.

The common AP backend has separate server/DLL tests for all 204 item IDs, the original 136 chest/shop location IDs, offline history, reconnection and bidirectional DeathLink. The later shop catalogue adds 56 location identities and resource/flow coverage; it does not add emulator support. These tests exercise the protocol and simulated host callbacks; they must not be presented as gameplay validation for an emulator or a newly adapted port. The 0.5.0 Gold Skulltula path has separate generation, resource and flow coverage and has not been tested in-game on these hosts.

### Triforce 0.7.0 installer history

Version 0.9.1 added compatibility for Triforce 0.7.0's Achievements page and Mods input transition. Required source hooks are checked before room preparation. That installer correction retained existing native player files and did not require a new room. Use the current launcher for setup today.
