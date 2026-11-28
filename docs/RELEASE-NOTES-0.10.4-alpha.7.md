# 0.10.4 alpha 7: finish native NPC reward animations

Talon's Super Cucco reward could leave Link holding an invisible item with no
HUD or controls, or crash Triforce while executing the same handover. The
copied native presentation requested an NPC action absent from the bound
participant's registered methods.

Preparation now carries native action and query requirements through local
actor arguments, including shared native entry bodies and nested handovers.
It extends the existing participant declarations and retains the authored
animation, camera, reward callback and cleanup. No replacement animation or
forced return to gameplay is added.

Keep your existing room, `.apootrr`, YAML and save. Close Zelda and prepare the
same player file with the updated launcher when it requests updated resources.
No regeneration is needed. Room placements, settings, checks and item history
remain unchanged.

The native bridge, generation engine and AP item/location IDs are unchanged.
The earlier constructor, chest-model, opening and menu fixes are included.
