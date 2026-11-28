# Updating the launcher and APWorld

**[Download the current Windows launcher, 0.10.4-alpha.12](https://github.com/RAjeux/OOT-Remake-Archipelago/releases/download/v0.10.4-alpha.12/OOT-Remake-Archipelago-0.10.4-alpha.12.exe)**
if your older launcher does not have an update button. The [versioned release
page](https://github.com/RAjeux/OOT-Remake-Archipelago/releases/tag/v0.10.4-alpha.12)
identifies the supported native release. Prepared rooms, connection preferences
and saves remain in LocalAppData when the executable is replaced.

**The discontinued 0.11/0.12 Full experiment is a different format.** Its higher
version number does not make it the current release. Updating the launcher or
APWorld does not convert Full player files: export a fresh YAML with the current
editor, generate a new room with the current APWorld and keep old Full saves
separate. The existing-room instructions
below apply to supported **native 0.10** player files.

For a first installation, follow [the player and organizer guide](INSTALLATION.md)
or [the French quickstart](INSTALLATION.fr.md).

## Choose the right kind of update

| What changed? | What to do |
| --- | --- |
| Launcher application | Update the EXE; continue the same supported room and save, preparing again only when requested. |
| The organizer's installed APWorld differs | Opt into its update or use **Install APWorld**, then restart Archipelago before generating. Existing rooms keep their placements. |
| The launcher reports old prepared mod resources or host tools | Close Zelda and its builder; prepare the same supported `.apootrr` with the same room save. |
| You want different settings or expanded sources | Generate a new room and use its new player file and dedicated save. |
| Your player file belongs to Full 0.11/0.12 | Export a fresh YAML in the current editor and generate a new room with the current APWorld; it is not an in-place conversion. |

## Update the launcher

Version 0.10.4-alpha.12 restores the destination dungeon in key, boss-key, map
and compass messages. Close Zelda and prepare the **same player file** again
when requested, keeping the same room and save. Receipt events and localized
messages are regenerated together; placements and generation rules stay the
same. See the [patch notes](RELEASE-NOTES-0.10.4-alpha.12.md).

Version 0.10.4-alpha.11 adds **Create YAML → Import YAML…** to edit an existing
configuration while keeping untouched options and weighted selections. Saving
proposes a separate copy. This launcher-only feature needs no game preparation
or new room. See [the import guide](INSTALLATION.md#reuse-an-existing-yaml).

Version 0.10.4-alpha.10 removes updater lock leftovers beside the executable.
Windows deletes the exclusively held lock when its helper closes, including
after an interrupted process. Completion also retires verified empty locks
from completed older updates. A changed file or an active helper is preserved.
This launcher-only patch needs no new room or game preparation.

Version 0.10.4-alpha.9 corrects personal shop checks and displays, native heart
effects, skipped-story rewards, and inventory-pause/loading safety on Triforce.
The matching APWorld also fixes specific generation failures. The earlier NPC
handover and visible medallion/Spiritual Stone fixes remain included.
Close Zelda and prepare the same player file when the launcher requests
updated resources. The Triforce host must rebuild for its lifecycle observer.
No new room or YAML is needed for these runtime corrections; saves and item
history stay with their existing room. Updating the organizer's APWorld affects
future generations. See the [patch notes](RELEASE-NOTES-0.10.4-alpha.9.md) and
[validation record](OVERNIGHT-VALIDATION.md) for the test scope.

Version 0.10.4 adds reviewed source, access-logic and optional gameplay changes
for newly generated rooms. Existing native 0.10 player files, YAMLs and saves
remain supported. A launcher update does not reroll an existing room or add new
checks to it. Keep its original `.apootrr` and save; prepare it again only when
the application requests updated resources. Launchers with the updater can
obtain this release through their update button.

To use the new catalogue or options, install the matching APWorld on the
generation PC, restart Archipelago and generate a new room. Its player files
and saves stay separate from earlier rooms. See the
[0.10.4 release notes](RELEASE-NOTES-0.10.4-alpha.1.md) for additions and limits.

The application checks GitHub in the background. **Update available** appears
when a newer publication is found. **Help → Check for launcher updates** retries the
check manually. A missing connection does not prevent normal preparation or play.
An alpha build follows prereleases; a stable build follows stable releases.
The most recently published eligible release is considered, so older abandoned
experiments with higher version numbers are not selected over newer releases.

Choose the update button, download the replacement, then choose **Install and
restart**. The downloaded files and the Windows product/version information
are verified before replacement. The launcher closes only after its separate
update helper is ready. After a successful update, the new executable has the
release's canonical versioned filename in the same folder, for example
`OOT-Remake-Archipelago-0.10.4-alpha.12.exe`. The previous executable is retained
for rollback in private update data under `%LOCALAPPDATA%\OOTRR-Archipelago`,
rather than alongside the launcher. Failures before a successful handoff retain
or restore the previous version. Helper failures are written to the application
log accessible from **Help**.

The updated application restarts automatically. User-created shortcuts which
point to the old filename may need retargeting. **About**, the executable name
and Windows file properties identify the installed version.

The update window also checks your installed `ootrr_remake.apworld`. If the
new file differs, you can select **Also update APWorld**. Pick the Archipelago
installation if it has not been detected. This option is never applied without
your selection, and an identical APWorld is not replaced. The new application
installs its matching APWorld and persistent Node runtime after restarting.

The previous APWorld is backed up. Renamed copies of the same `ootrr_remake`
package are also backed up and removed from the active directory to avoid
loading an older duplicate; other games are left in place. If APWorld
replacement fails, the updated launcher stays usable and offers the usual
**Install APWorld** action for retrying. Restart Archipelago before generating.

Updating an APWorld does not rerandomize an existing room. Existing native
0.10 player files and YAMLs remain supported. When the launcher reports that
a room needs preparation, close Zelda and its setup application and prepare
the **same `.apootrr`** again with the **same save**. This applies newer mod
resources without generating a new room. Resource revisions are independent
of launcher versions, so a future interface-only update need not rebuild a room.

The 0.10.2 consumable correction affects newly prepared receipts. It does not
retroactively add extra ammunition for packs already acknowledged by the game.
The existing equipment and capacity requirements still apply.

The update helper uses an independent frozen process as described in
[PyInstaller's restart documentation](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html#using-sys-executable-to-spawn-subprocesses-that-outlive-the-application-process-implementing-application-restart).
No Python, console script or manual checksum comparison is required by players.
