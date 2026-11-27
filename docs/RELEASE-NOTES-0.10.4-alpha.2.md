# 0.10.4 alpha 2: updater replacement and correct EXE names

**[Download the Windows launcher](https://github.com/RAjeux/OOT-Remake-Archipelago/releases/download/v0.10.4-alpha.2/OOT-Remake-Archipelago-0.10.4-alpha.2.exe)**

This launcher-only patch fixes replacement of the previous executable and the
updated application's filename.

- A successful update installs `OOT-Remake-Archipelago-0.10.4-alpha.2.exe` in the same folder as the old launcher and restarts it automatically.
- The previous EXE and verified backups from earlier managed updates are archived in private LocalAppData update storage. Unregistered manual copies are preserved.
- An older 0.10.4 launcher can use its normal **Check for launcher updates → Install and restart** flow; no manual rename is needed.
- User-created shortcuts targeting the previous versioned filename may need retargeting.

**Game integration and APWorld generation/seed rules are unchanged.** Keep your existing
player file, room and save. This patch does not require replacing the APWorld
or regenerating a room. The optional APWorld refresh includes updated shared
translations. The 0.10.4 catalogue and experimental gameplay limits
remain those documented for
[alpha 1](https://github.com/RAjeux/OOT-Remake-Archipelago/blob/v0.10.4-alpha.2/docs/RELEASE-NOTES-0.10.4-alpha.1.md).
No game files or prebuilt Zelda executable are included.

An isolated frozen Windows test using the unchanged updater from
0.10.4-alpha.1 and the production alpha 2 executable passed **23/23 end-to-end
checks**. It exercised both helpers, installed and restarted
the correctly named EXE, archived the original and two verified historical
backups, and preserved an unregistered manual copy, profiles, saves and
settings. The optional APWorld update ran once; replaying completion was
idempotent. Focused updater, entry-point, packaging and actual Tk UI checks,
plus frozen-executable inspection and self-test, also passed.
A second isolated future-update test confirmed the same behavior when the
initiating updater already contains this fix.

[Update guide](https://github.com/RAjeux/OOT-Remake-Archipelago/blob/v0.10.4-alpha.2/docs/UPDATING.md) ·
[Installation](https://github.com/RAjeux/OOT-Remake-Archipelago/blob/v0.10.4-alpha.2/docs/INSTALLATION.md)
