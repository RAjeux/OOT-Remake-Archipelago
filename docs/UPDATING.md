# Updating the launcher and APWorld

Download `OOT-Remake-Archipelago-0.10.3-alpha.1.exe` once if your older launcher
does not have an update button. Prepared rooms, connection preferences and saves
remain in LocalAppData when the executable is replaced.

Version 0.10.3 refreshes the desktop interface. A room already prepared with
current 0.10.2 resources remains ready to play; this UI update does not raise
the mod's prepared-resource revision. YAML values and generation rules are
unchanged. The 0.10.2 launcher can obtain this release through its update button.

The application checks GitHub in the background. **Update available** appears
when a newer publication is found. **Help → Check for updates** retries the
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
