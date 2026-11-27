# Installation and first room

[Guide rapide en français](INSTALLATION.fr.md) · [Compatibility](PORT-COMPATIBILITY.md) · [Updates](UPDATING.md)

## Download the current launcher

**[Download OOT-Remake-Archipelago-0.10.4-alpha.1.exe](https://github.com/RAjeux/OOT-Remake-Archipelago/releases/download/v0.10.4-alpha.1/OOT-Remake-Archipelago-0.10.4-alpha.1.exe)**

The [versioned release page](https://github.com/RAjeux/OOT-Remake-Archipelago/releases/tag/v0.10.4-alpha.1) contains the release notes and other assets. A player needs only the EXE; its AP client, Python, Node.js and APWorld are included. The compatible OOTRR 0.8.1 builder is downloaded when preparation first needs it.

**Do not choose the discontinued 0.11/0.12 Full-network experiment because its version number is higher.** Its generated player files use a different format and are not converted. Export a fresh YAML with the current editor, generate a new room with the current APWorld and keep the Full saves separate. Native 0.10 rooms follow the [update guide](UPDATING.md).

## Choose your role

| You want to… | What to do |
| --- | --- |
| Join a room that already exists | Get **your `.apootrr`** and connection details from the organizer, then follow [Player: prepare and play](#player-prepare-and-play). |
| Choose your settings for the next room | [Create your YAML](#each-zelda-player-create-a-yaml) and send it to the organizer. |
| Generate the group's room | Install Archipelago and this APWorld on the generation PC, collect everyone's YAMLs, then [generate and host](#organizer-generate-and-host). |

A player joining a generated room does **not** need an Archipelago installation. The organizer uses Archipelago to generate; hosting can use a local server or the Archipelago website afterward.

## Files you will encounter

| File | Meaning | Where it goes |
| --- | --- | --- |
| `OOT-Remake-Archipelago-0.10.4-alpha.1.exe` | This project's desktop application. | Keep it in a convenient folder and open it to set up or play. |
| `Player-name.yaml` | A player's options before generation. | Send it to the organizer. It is not the file selected in **Set up a room**. |
| `ootrr_remake.apworld` | Archipelago's custom game integration. | The organizer uses this launcher's **Install APWorld** action; no separate download is needed. |
| `AP_…_P…_name.apootrr` | The generated Zelda player file for one slot and room. | That player selects it in **Set up a room**. Keep it to prepare that room again later. |
| `AP_….zip` / `.archipelago` | Archipelago's generated room output and server data. | The organizer hosts it and distributes the individual player files. |

Changing a YAML later does not reroll an existing room. Generate a new room to change its settings or placements.

## Prepare the base game first

For playing Zelda you need Windows x64, your own game files at **version 1.1.1**, and a working compatible host with its build tools. First build and launch the base game successfully with that host. Keep its tools available: the AP launcher rebuilds the host to add the native connection.

- **Triforce is the main route.** Follow the [official installation instructions](https://triforceproject.com/#install). Triforce Setup obtains its own tools and builds from your files. This integration has a title-screen connection and reconnect check on Triforce **0.8.3**; see the [bounded validation record](PORT-COMPATIBILITY.md#triforce-083-runtime-check).
- **Hookshot is experimental and pinned to 3.0.1.** Consult the [official Hookshot source and setup instructions](https://github.com/ItsNotRexed/Hookshot#install-and-play) and [3.0.1 release page](https://github.com/ItsNotRexed/Hookshot/releases/tag/v3.0.1). The AP adapter needs the matching original tools and retained build files. A newer upstream release is not automatically compatible; setup rejects other source revisions. If you are starting from scratch, use the Triforce route above.

Hardware and base-game setup requirements belong to those host projects. This launcher supplies neither game data nor a prebuilt Zelda executable. Linux and emulator AP gameplay are not supported by this installer; Fritchii overlay loading alone does not provide an AP connection.

## Each Zelda player: create a YAML

Do this before the organizer generates the room:

1. Open the launcher and choose **Create YAML**.
2. Enter the name of your player slot. It must be unique within the group.
3. Open **Choose settings…**. Search in English, French or by YAML key, choose categories and review each selection's explanation. **DeathLink** is one of these options.
4. Apply your settings, then choose **Save YAML**.
5. Send the exported `.yaml` to the organizer. Each player of another game supplies that game's own YAML.

The editor exports the selected values. **Random?** rolls an option value independently and can produce incompatible combinations; it does not guarantee a valid configuration. Inactive sub-options keep their saved values but do not affect generation. The [settings compatibility guide](SETTINGS-COMPATIBILITY.md) lists the supported controls.

## Organizer: generate and host

1. Install [Archipelago from its official releases](https://github.com/ArchipelagoMW/Archipelago/releases), including the generator and, if hosting locally, the server. This APWorld requires **0.6.7 or later** and has generation coverage on **0.6.8**.
2. In the **OOT Remake launcher**, choose **Install APWorld** and select your Archipelago installation folder. Run this under the Windows account that will generate the room: it installs `ootrr_remake.apworld` and that user's persistent generation runtime. Restart Archipelago afterward. Use this action rather than setting up a separate Node.js installation.
3. Install any additional custom worlds required by the group's other games, following their own instructions. Collect one YAML for each player slot and put the files in Archipelago's `Players` folder. Keep unrelated old YAMLs out of that generation's input.
4. In Archipelago Launcher, choose **Generate**, or run `ArchipelagoGenerate.exe`. Its generated ZIP is placed in the `output` folder. **Generate this custom APWorld locally**; it is not included in the public website's generator.
5. Host the generated room with Archipelago Server, or upload the generated output to [Archipelago's hosting page](https://archipelago.gg/uploads). The [official Archipelago setup guide](https://archipelago.gg/tutorial/Archipelago/setup_en) explains both hosting routes.
6. Give each Zelda player **their own generated `.apootrr`**, the room address and the password if one was set. The file identifies the room and slot; the launcher does not ask the player to recreate that identity by typing a name.

The OOT Remake launcher exports YAMLs and prepares games. **Archipelago generates and hosts the room.** These are separate steps.

## Player: prepare and play

Before preparation, finish any host update and close Zelda and its setup/builder application.

1. Open the launcher and choose **Set up a room**.
2. Select **your `.apootrr`**, received after generation. A YAML, APWorld or room ZIP is a different kind of file.
3. Choose **Game host**. If the installation was not detected, choose the folder containing your installed game. Setup checks the game and its tools. **Change detected folders…** exposes the separate game-data and tools folders when needed.
4. Enter the room address from your organizer and its password only if required. Choose **Install and prepare**. Wait for preparation and any required game build to finish; progress stays in the same window.
5. Choose **Play**. Zelda connects from the title screen. Create a dedicated save for a new room. When continuing an existing native 0.10 room, use that room's existing save.

For later sessions, open the same launcher and choose **Play**. Closing the launcher while playing leaves Zelda and its AP connection running.

The address can be `host:port`, `ws://host:port` or `wss://host:port`; `archipelago.gg` uses TLS automatically. `127.0.0.1:38281` refers to a server on **your own PC**. For a room hosted elsewhere, use the address the organizer gives you.

## Connection, saves and updates

**Connection** changes the prepared room's server or password without a console. Triforce also has **Options → Archipelago**; Hookshot has **F1/Insert → Gameplay → AP Server / AP Connect**. Run only one host at a time for the same AP player slot. See the [connection guide](CONNECTION-WINDOW.md) for password actions and automatic connection.

Profiles, connection settings, tools and saves are kept in `%LOCALAPPDATA%\OOTRR-Archipelago`. Hookshot uses a separate `hosts\hookshot` namespace. Moving or updating the EXE keeps these files; switching hosts does not transfer a save or item history.

Existing native 0.10 rooms keep their player file, save, settings and placements. If preparation is requested, close Zelda and prepare the same compatible `.apootrr` again. To use the new 0.10.4 options and sources, the organizer installs the matching APWorld and generates a new room; each player uses its new player file and a dedicated save. See the [update guide](UPDATING.md).

## If a step fails

| What you see | What to check |
| --- | --- |
| Archipelago does not recognize **Ocarina of Time Remake** | Use this launcher's **Install APWorld** on the generation PC, select the correct Archipelago installation and restart Archipelago. |
| Setup rejects the player file | Select the generated `.apootrr` for your Zelda slot. Discontinued Full 0.11/0.12 files need a newly generated room with the current APWorld. |
| Game files or tools are not ready | Confirm that the base game runs in the supported host, retain its original tools and check the selected folders. Read [compatibility](PORT-COMPATIBILITY.md) for Hookshot's exact revision requirement. |
| The server cannot be reached | Check the organizer's current address, whether the room is running and whether a password was set. |
| The launcher says the room needs preparation | Close Zelda and its builder, then prepare the same supported `.apootrr` again. Keep the same room save. |

Open **Help → Open log** for details. When reporting a problem, include launcher and host versions, the failed step and the visible error. Review logs for participant names before sharing; do not attach game files or saves. This remains an alpha with the [documented gameplay validation limits](PORT-COMPATIBILITY.md).
