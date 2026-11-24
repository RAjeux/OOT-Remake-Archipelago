# Port compatibility

The Windows x64 application provides native setup for **Triforce** and an **experimental Hookshot 3.0.1 adapter**. Loading a RomFS mod is a separate capability from connecting to Archipelago and safely granting its items.

## Current external backend (0.12.0-alpha.1)

**Other ports and emulators…** provides a separate experimental setup/runtime for full-network rooms. It accepts a supported RomFS directory or NUP, dedicated mods folder, exact host/game executable, and optional ROM and save path. Profiles are separate from both native hosts. It never moves an original save, and opening a library profile does not automatically connect.

The external window owns the AP runtime and must remain open while connected. Tracker and chat share that connection. The runtime verifies the seed and receipt-readiness markers before delivery; live inventory tracking can start before the first save when the process seed is verified. Windows and Linux process adapters exist in source, but the distributed desktop application is Windows x64. Prepared full-network rooms now support external DeathLink when enabled in the player file.

On 24 November 2026, a private portable Fritchii 5.8.4 installation ran game 1.1.1 with the full-network overlay, the actual external runtime, Archipelago 0.6.8 and a second player in a different game. Original saves and configuration were preserved: all nine original configuration/save hashes and the original file set were unchanged after cleanup.

This actual gameplay test verified title-screen connection, items sent while the game was closed, native rupee and Bow effects, and deferral on a ladder. Bomb ammunition received without a bomb bag produced no ammunition, equipment or substitute reward. An incoming DeathLink waited during the inventory pause, then caused native Game Over after unpausing without an outgoing echo. Declarations of death use fresh native Player AI and live life, never a previously saved health value.

Own-check rollback and natural outgoing DeathLink were also executed in the actual emulator, using an explicitly isolated map fixture. The existing Kokiri Sword Chest was relocated without changing its actor identity or its Fire Medallion AP placement; cloned vanilla Dekubabas supplied ordinary contact damage. After collecting the chest, loading a precheck save through Zelda's own Load menu restored the owned reward, its source and its open-chest state. The server still recorded one check. Six ordinary enemy hits then caused one outgoing DeathLink received by the real second client. No player health, position, inventory or save editing was used. The temporary private map was restored afterward; these fixture tests do not establish that the original physical routes were traversed.

These observations are separate from automated resource/process tests and the modeled integration test below. They do not claim a complete catalogue playthrough, every action/item presentation, Linux gameplay or universal emulator compatibility. Other emulator builds must pass their own exact process/resource checks.

Older full mods need **Update prepared room** using the **same player file**. This installs corrected resource allocations and the version 2 native readiness gate while retaining the room token, placements and saves. Opening an older profile offers that update and blocks Play/Connect until it is prepared; it does not silently launch outdated resources. A new seed is needed for changed settings or new locations, not for this same-room resource repair.

## Current native-host gameplay checks

Full-network generation and preparation currently require a Child start.
Actual Triforce testing found a stall in the adult opening transition; adult
player files remain readable, but that starting mode is blocked in this release.
This restriction concerns the initial age, not ordinary age changes during play.

The 0.12.0-alpha.1 native helpers were also exercised on actual private native hosts with historical 1,104-check full rooms. Triforce connected at the title screen, loaded a new four-heart save, held twenty rupees through pause, delivered a native Bow facing the camera, committed its receipt and deferred an incoming DeathLink through item/tutorial events before native Game Over without echo. Original hashes remained unchanged and the private game exited normally. This smoke test is distinct from validation of a newly generated 1,106-check room.

Hookshot loaded the full resource set after the allocation repair and ran actual receipt, crawl and natural outgoing DeathLink tests. Its latest native helper was checked with child/adult player components and an adult fishing session: a major item waited during the cast and while the rod remained ready between casts, then arrived after putting the rod away. Travel and age-switch assistance were used to reach that private scenario, without editing health or inventory.

A separate Spirit Temple fixture verified the child route's two native key doors and an actual AP reward at the Silver Gauntlets source. It restored vanilla Spirit map resources and used explicit position/combat assistance around non-key obstacles; neither key door was bypassed and no keys/ring/gauntlets were granted as a shortcut. This proves the tested key-gate/source transactions, not a complete unassisted dungeon playthrough.

Individual AP keys were then received on actual private Hookshot through a real AP server, outside their target dungeon. Two Forest copies advanced held/found counts from zero to one to two while other dungeon counts stayed unchanged. Child and adult presentations kept the whole native key model in frame without overriding the camera. Duplicate checks did not grant another key. These observations complement per-copy resource/network tests; playing every one of the new catalogue's checks is not claimed.

The private 0.11 external integration test uses the actual runtime and Archipelago 0.6.8 server with a generated 1,104-check Zelda room and a second game. It verifies offline receipts, server synchronization with no remote items, personal and foreign older-save recovery, exact ammunition amounts, and quiet acknowledgements for spent trade items. The game-side EVFL/GameData execution is modeled explicitly; no emulator or port gameplay session is implied by that result.

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

## Historical gameplay observations

Local tests were performed on 21 November 2026 with game version 1.1.1. Each host used a separate test profile; existing game saves and host configurations were preserved.

| Host | Verified behavior | Distribution status |
| --- | --- | --- |
| Triforce 0.6.0, Windows | Native title-screen connection, item delivery, reconnection, checks and DeathLink; see the main README for the gameplay coverage and remaining presentation issues. | Supported by the published installer. |
| Hookshot 3.0.1, Windows | An experimental rebuilt host connects before the title screen. Real remote item delivery, saving, incoming DeathLink, and receiving an item sent while the game was closed were verified in a new game. | Experimental adapter in the 0.9.0 installer; prerequisites and validation scope above. |
| Fritchii 5.8.4, Windows | The supplied NUP boots to the French title screen and loads the AP overlay through LayeredFS. | Historical asset-loading test on 21 November; actual external gameplay validation on 24 November is described above. |

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

The earlier gameplay test used a new private save and a copied local room with a second test player. It did not establish that every physical chest, all eight shop purchases, or every item presentation had been replayed on Hookshot. Natural outgoing DeathLink was not part of that earlier prototype test.

The first remote check granted five rupees and saved received index 1. An incoming DeathLink then changed Link's life from 12 to 0 without an outgoing echo. A second five-rupee item was sent while no Hookshot game process was running. After restarting and loading the same private save, the game reached ten rupees and saved received index 2, with exactly one new receipt event. The first item and the previous DeathLink were not replayed.

## Fritchii scope

Fritchii's NUP loader handles the standalone update container directly; conversion to NSP or XCI was not required. The portable test profile used this layout:

```text
<portable-app>/user/load/0400486024DEC000/Archipelago/romfs/
```

Only RomFS resources are installed for the external path. No Windows AP DLL, native-host include or ExeFS patch is required in the emulator. The game's normal native texts remain localized by the game. The earlier title badge observation proved asset loading; the later actual gameplay tests above separately establish connection, grants, recovery and DeathLink for this exact tested revision.

The external runtime observes verified GameData and requests the game's registered native receipt events. Native Player AI publishes unsaved readiness and live-death flags. Incoming DeathLink requests use the game's own live-life query and native life-subtraction action. Pause, loading, events, unknown actions, fishing and missing seed/native heartbeat prevent unsafe activation. The desktop client must stay open; the emulator alone does not own an AP socket.

## Legacy save bridge limitations

The old save-only bridge supports a subset of equipment and currency, not the complete catalogue, shop purchases or DeathLink. It remains separate from the guarded 0.11 full-network runtime. Removing its `all_locations`/native-host guards would consume unsupported items without their effects; those guards remain in place.

The common AP backend has separate server/DLL tests for all 204 item IDs, the original 136 chest/shop location IDs, offline history, reconnection and bidirectional DeathLink. The later shop catalogue adds 56 location identities and resource/flow coverage; it does not add emulator support. These tests exercise the protocol and simulated host callbacks; they must not be presented as gameplay validation for an emulator or a newly adapted port. The 0.5.0 Gold Skulltula path has separate generation, resource and flow coverage and has not been tested in-game on these hosts.
