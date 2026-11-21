# Port compatibility

The published installer and native integration currently target **Triforce Windows x64**. Loading the RomFS mod on another host is a separate capability from connecting to Archipelago and applying received items.

## Tested hosts

Local tests were performed on 21 November 2026 with game version 1.1.1. Each host used a separate test profile; existing game saves and host configurations were preserved.

| Host | Verified behavior | Distribution status |
| --- | --- | --- |
| Triforce 0.6.0, Windows | Native title-screen connection, item delivery, reconnection, checks and DeathLink; see the main README for the gameplay coverage and remaining presentation issues. | Supported by the published installer. |
| Hookshot 3.0.1, Windows | An experimental rebuilt host connects before the title screen. Real remote item delivery, saving, incoming DeathLink, and receiving an item sent while the game was closed were verified in a new game. | Private compatibility prototype. The published installer does not configure this host. |
| Fritchii 5.8.4, Windows | The supplied NUP boots to the French title screen. The AP RomFS overlay loads through LayeredFS and displays the Archipelago title badge; both title-screen tests ran at 60 FPS. | RomFS loading verified. No emulator AP runtime is implemented or validated. |

## Hookshot prototype scope

The unmodified Hookshot installation does not expose all the helper names and notification functions expected by the Triforce adapter. The experiment added compatible GameData helpers and the AP bridge to a private host build. The two installed hosts used identical guest `image.bin` contents, and both the syntax probe and full isolated build succeeded.

The prototype uses the same AP DLL and registered receipt events as the released client. AP item IDs, canonical names, room token, and save cursor are preserved. Host notifications currently go to the log rather than an in-game host toast. The experimental host changes, automatic setup, upgrade handling, and notification integration are not part of the published package.

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

The legacy save bridge only supports a subset of equipment and currency. It does not implement the complete item catalogue, the eight shop checks, or DeathLink. Removing the `all_locations`/native-host guards would allow unsupported items to be consumed without their effects. Those guards remain in place.

The common AP backend has separate server/DLL tests for all 204 item IDs, all 136 locations, offline history, reconnection and bidirectional DeathLink. Those tests exercise the protocol and simulated host callbacks; they must not be presented as gameplay validation for an emulator or a newly adapted port.
