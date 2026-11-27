# 0.10.4 alpha 3: dungeon-key tracker startup fix

The optional dungeon-key tracker could crash Triforce before the title screen.
Keeping the original quest panels alongside the nine tracker panels required
more memory than the resource table reserved for the native menu parser.

The menu now reserves memory for the additional panels and their parsed data.
The original quests, Archipelago menu and key tracker remain available.

After updating, close Zelda and prepare the **same `.apootrr` player file**
again when requested. Existing prepared resources are deliberately marked as
outdated so that the crashing resource cannot be reused. Keep the same room
and save: this fix does not reroll items, change settings or require a new seed.

The launcher includes the corrected engine. The APWorld's generation rules,
item IDs and location IDs are unchanged; organizers do not need to regenerate
an existing room.

Validation reproduced the original access violation on Triforce 0.8.3
(`9d450f5f`) in an isolated profile. Changing only the menu's resource-table
allowance from 17,648 to 31,120 bytes reached the title screen, remained there
for 30 seconds and exited normally. Resource tests verify that the original
20 quest panels and nine tracker panels are retained, and that allocation
reserves are checked, monotonic and safe to apply again. This verifies the
startup fix; it does not imply a complete gameplay traversal of every option.
