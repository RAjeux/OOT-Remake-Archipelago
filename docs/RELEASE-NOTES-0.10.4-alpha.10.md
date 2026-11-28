# 0.10.4 alpha 10: clean launcher updates

Launcher updates no longer leave an empty `.archipelago-update.lock` beside
the executable. Windows removes the verified, exclusively held lock when the
helper closes, including when a process is interrupted. Older update helpers
continue to use the same lock identity, preserving mutual exclusion.

The incoming launcher also cleans verified empty locks belonging to completed
older updates, including transactions whose backup has already moved into
private app data. Modified files, links and active transactions are preserved.
The previous executable stays in private rollback data.

Windows tests cover normal and exceptional exits, a terminated helper, competing
processes, legacy-helper exclusion, unrelated files and completed-update history.
An actual frozen alpha 9 helper also updated to alpha 10 in an isolated profile,
restarted under its canonical name and left no adjacent lock or temporary file.
The game, settings, APWorld generator and room placements are unchanged from
alpha 9. Keep your existing YAML, player file and save; no game preparation is
needed for this launcher-only patch.
