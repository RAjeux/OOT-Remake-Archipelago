# Items, checks and saves

An AP check is a location exported when the room is generated. Its reward can
belong to Zelda or another player. A personal physical reward applies the native
item effect in Zelda; a remote reward is sent to its owner. The old reward at
that source is replaced. The AP item pool is filled by Archipelago under each
game's access rules, without a Zelda recipient quota.

Other sources remain native-local. Depending on the selected settings, OOTRR can
shuffle their rewards among its own locations, including songs, NPC gifts,
dungeon rewards and ground pickups. They do not become network checks just
because their item model also exists in the AP catalogue. These local rewards
can explain why a player finds important Zelda equipment in Zelda even while
the exported AP items are spread across the multiworld.

## Loading an older save

For a prepared `all_locations` room with personal physical rewards, incoming AP
items replay from that save's received-item index. Previously completed exported
locations also recover from the room journal and server history. Personal
rewards restore once to that save; another player's reward restores only the
completed location and is not sent twice.

Native-local rewards follow the selected save, like ordinary game progress.
Loading a save from before a local reward means that source and reward can be
collected again in that save. The mod does not inject those gains from a later
save. This keeps the inventory and the native quests, counters and consumed
items consistent with the loaded save.

Keep a save dedicated to each room. A different room has different placements;
its saves and reward history are independent. Triforce and Hookshot also keep
separate profiles and do not transfer game saves through Archipelago.

## Extending network coverage

A native source needs a researched location identity, a reliable collection
flag, an event that replaces the original reward, an access rule and older-save
recovery before it can join the AP pool. It must be exported during generation.
Simply reporting an already granted native item as a check can grant a second
reward and cannot retroactively change a room's placements.

Existing rooms keep their generated catalogue and placements after a mod
update. Updates can fix delivery and presentation without rerolling a room;
new shuffle choices and added network locations require a newly generated room.
