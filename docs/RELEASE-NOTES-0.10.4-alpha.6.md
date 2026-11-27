# 0.10.4 alpha 6: build progressive Archipelago rewards reliably

Some valid rooms could not be prepared because the portable OOTRR constructor
rejected a fixed pickup's upgrade tier. Its local tier-order proof can change
when the native adult trade chain is replaced by independent AP exchanges.
AP rewards instead resolve the next upgrade level when the item is received.

Preparation now derives disposable constructor input for validated physical AP
sources. It uses count-preserving substitutions into supported AP chests, keeps
native upgrade guards enabled, and restores canonical pickup/chest geometry.
The normal AP passes then install the room's actual rewards. Constructor
substitutions are recorded separately and never become Archipelago placements.

Keep your existing generated `.apootrr` file, YAML and room. No regeneration is
needed. Previous saves and room settings are preserved. Existing correctly
prepared rooms do not require preparation solely for this change. A previously
failed room can be prepared with the updated launcher.

Generation rules, AP item/location IDs and the native bridge are unchanged.
This version includes the alpha 5 chest-opening and item-model fixes.
