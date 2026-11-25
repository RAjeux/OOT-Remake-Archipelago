# Port compatibility

The Windows x64 installer supports **Triforce** and an **experimental Hookshot 3.0.1 adapter**. Loading the RomFS mod on another host is a separate capability from connecting to Archipelago and applying received items.

## Triforce 0.8.1 runtime check

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

No new launcher, APWorld, YAML or room is needed for 0.8.1. After updating
Triforce, prepare the same native 0.10-line `.apootrr` again with alpha.3 to
restore the AP-enabled executable and renderer.

## Triforce 0.8.0 in 0.10.1-alpha.3

The installer supports the updated menu hooks while preserving native
resolution editing and tuning overlays. Its source preflight still rejects
unknown or ambiguous layouts. Newer host-source or tool-version files
invalidate an older compiled AP host; current builds remain reusable.

Close Zelda and Triforce Setup, finish the Triforce update, then prepare the
same native 0.10-line `.apootrr` again with
`OOT-Remake-Archipelago-0.10.1-alpha.3.exe`. This rebuilds the host when needed.
The compatibility fix changes neither placements nor saves and requires no
new room.

Automated menu, installer and cache checks plus private host-C compilation
cover this update. The earlier gameplay observations below remain separate
evidence; they do not establish a complete manual playthrough on 0.8.0.
See [the compatibility release note](RELEASE-NOTES-0.10.1-alpha.3.md).

## Hookshot setup in 0.9.0

Choose **Set up a room → Game host → Hookshot (experimental)** in the same
application. Supply a completed Hookshot 3.0.1 installation, its original tools
and retained build files. The adapter checks the exact host and menu source
hashes before preparing a private tool copy. Other revisions are rejected instead
of receiving a guessed patch. It does not download or redistribute Hookshot or
game files.

Preparation builds the host and menu automatically and installs the AP mod. The
connection controls are available in **F1/Insert → Gameplay** as **AP Server**,
**AP Password**, **AP Password action**, **AP Automatic connection**, **AP
Connect** and **AP Disconnect**. They use Hookshot's existing text editor,
controller navigation and paste support. The desktop **Connection** window uses
the same AP connection. Triforce keeps its existing **Options → Archipelago**
page.

Hookshot's native editor accepts printable ASCII. For a password containing
accents or other non-ASCII characters, use **Connection** in the desktop
application instead; the saved password can then be retained by the game menu.

Hookshot profiles live under `%LOCALAPPDATA%\OOTRR-Archipelago\hosts\hookshot`.
Their saves and room history are independent from Triforce, including when both
hosts prepare the same player file. Original tool sources remain unchanged;
adapted copies are stored in the application's data folder. Close Zelda and its
builder before installation.

Run one host at a time for the same Archipelago player slot. Separate profiles
do not create a second slot on the server. Hookshot's AP host notices currently
go to its log; native item messages and receipt effects still belong to the game.

The 0.9.0 adapter has separate host/menu compilation and installer regression
checks. The gameplay observations below belong to the earlier prototype, using
the same network DLL and receipt bridge. They do not establish complete gameplay
coverage for the new installer or its menu.

## Tested hosts

Local tests were performed on 21 November 2026 with game version 1.1.1. Each host used a separate test profile; existing game saves and host configurations were preserved.

| Host | Verified behavior | Distribution status |
| --- | --- | --- |
| Triforce 0.6.0, Windows | Native title-screen connection, item delivery, reconnection, checks and DeathLink; see the main README for the gameplay coverage and remaining presentation issues. | Supported by the published installer. |
| Hookshot 3.0.1, Windows | An experimental rebuilt host connects before the title screen. Real remote item delivery, saving, incoming DeathLink, and receiving an item sent while the game was closed were verified in a new game. | Experimental adapter in the 0.9.0 installer; prerequisites and validation scope above. |
| Fritchii 5.8.4, Windows | The supplied NUP boots to the French title screen. The AP RomFS overlay loads through LayeredFS and displays the Archipelago title badge; both title-screen tests ran at 60 FPS. | RomFS loading verified. No emulator AP runtime is implemented or validated. |

## Earlier Hookshot gameplay prototype

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

## Fritchii scope

Fritchii's NUP loader handles the standalone update container directly; conversion to NSP or XCI was not required. The portable test profile used this layout:

```text
<portable-app>/user/load/0400486024DEC000/Archipelago/romfs/
```

Only RomFS resources were copied for the overlay test. No Windows AP DLL, host include, existing save, or ExeFS patch was installed in the emulator. The observed AP title badge proves asset loading, not an AP connection or an inventory grant. The game's normal native texts remain localized by the game.

A complete emulator backend must detect checks, request receipt events on the game thread, commit the saved received-item cursor, and integrate life/death state. Fritchii has a debugger interface, but a memory debugger alone is not a validated implementation of these transactions.

## Why the external save bridge is not a full fallback

The legacy save bridge only supports a subset of equipment and currency. It does not implement the complete item catalogue, shop purchases, or DeathLink. Removing the `all_locations`/native-host guards would allow unsupported items to be consumed without their effects. Those guards remain in place.

The common AP backend has separate server/DLL tests for all 204 item IDs, the original 136 chest/shop location IDs, offline history, reconnection and bidirectional DeathLink. The later shop catalogue adds 56 location identities and resource/flow coverage; it does not add emulator support. These tests exercise the protocol and simulated host callbacks; they must not be presented as gameplay validation for an emulator or a newly adapted port. The 0.5.0 Gold Skulltula path has separate generation, resource and flow coverage and has not been tested in-game on these hosts.
