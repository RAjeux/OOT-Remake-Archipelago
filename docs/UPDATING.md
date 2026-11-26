# Updating the launcher and APWorld

**[Download the current Windows launcher, 0.10.3-alpha.1](https://github.com/RAjeux/OOT-Remake-Archipelago/releases/download/v0.10.3-alpha.1/OOT-Remake-Archipelago-0.10.3-alpha.1.exe)**
if your older launcher does not have an update button. The [versioned release
page](https://github.com/RAjeux/OOT-Remake-Archipelago/releases/tag/v0.10.3-alpha.1)
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
| Launcher interface, including 0.10.2 → 0.10.3 | Update the EXE. A room with current 0.10.2 resources needs no new preparation. |
| The organizer's installed APWorld differs | Opt into its update or use **Install APWorld**, then restart Archipelago before generating. Existing rooms keep their placements. |
| The launcher reports old prepared mod resources or host tools | Close Zelda and its builder; prepare the same supported `.apootrr` with the same room save. |
| You want different settings or expanded sources | Generate a new room and use its new player file and dedicated save. |
| Your player file belongs to Full 0.11/0.12 | Export a fresh YAML in the current editor and generate a new room with the current APWorld; it is not an in-place conversion. |

## Update the launcher

Version 0.10.3 refreshes the desktop interface. A room already prepared with
current 0.10.2 resources remains ready to play; this UI update does not raise
the mod's prepared-resource revision. YAML values and generation rules are
unchanged. The 0.10.2 launcher can obtain this release through its update button.

The application checks GitHub in the background. **Update available** appears
when a newer publication is found. **Help → Check for launcher updates** retries the
check manually. A missing connection does not prevent normal preparation or play.
An alpha build follows prereleases; a stable build follows stable releases.
The most recently published eligible release is considered, so older abandoned
experiments with higher version numbers are not selected over newer releases.

Choose the update button, download the replacement, then choose **Install and
restart**. The downloaded files and the Windows product/version information
are verified before replacement. The launcher closes only after its separate
update helper is ready. Its previous executable remains backed up, and failures
before a successful handoff retain or restore that version. Helper failures are
written to the application log accessible from **Help**.
The executable keeps its current path so existing shortcuts continue to work.
**About** and the Windows file properties show the installed version even if
the filename still contains an older version number.

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
