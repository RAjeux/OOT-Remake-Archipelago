# 0.10.4 alpha 8: native NPC handovers and visible quest rewards

NPC reward sequences could request an animation callback missing from a bound
participant. This caused an empty-handed get pose, missing HUD and blocked
controls, or an invalid callback crash. The fix includes Talon's Super Cucco
reward and the Market Potion Shop reward after returning the escaped insect.

Preparation completes native callback declarations across typed actor aliases,
including an earlier actor provider reused by a later handover. It preserves
the authored scene graph, camera, NPC targets, inventory effects and cleanup.
No substitute bottle or potion is granted.

Medallions and Spiritual Stones received from Archipelago now use native
held-item models instead of inventory-menu actors. Their actual pouch
item, message, ownership flag and received-item index remain unchanged. A
validated migration also repairs the nine known display arguments in a
compatible previously built base; repeating it makes no further changes.

Keep your existing room, `.apootrr`, YAML and save. Close Zelda and prepare the
same player file with this launcher when updated resources are requested. No
new room or regeneration is needed. Existing items and AP history are retained.

The APWorld, generation engine and native bridge are unchanged from alpha 6.
This release also includes the earlier constructor, chest, opening and menu
repairs.
