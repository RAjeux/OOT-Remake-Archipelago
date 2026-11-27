# 0.10.4 alpha 4: restore control after starting a new game

With the optional dungeon-key tracker, a new game could reach Kokiri Forest
with a black screen, forest sounds and no player control. Archipelago items
could still arrive, but the opening never reached its native cleanup.

The tracker called an event in another file that the opening did not preload.
Its ten native update actions now run inside the opening itself, then resume
the original fade-in and control handover. The key tracker and the previous
menu-memory fix are retained.

Close Zelda, update the launcher and prepare the **same `.apootrr` player file**
again when requested. Keep the existing room and save. Item placements,
settings, inventory history and Archipelago IDs are unchanged; a new seed is
not required. The launcher rejects old prepared resources until this
preparation has completed.

The APWorld's generation rules are unchanged. Organizers do not need to
regenerate an existing room.

Validation reproduced the freeze offline on Triforce 0.8.3 (`9d450f5f`),
without any received items. Changing only the opening flow and its allocation
restored the visible game, normal HUD, player movement and native saving.
Graph tests also verify that all nine tracker quests update before the
original cleanup, with no new external event dependency. This covers the
opening failure; it is not a complete gameplay traversal of every option.
