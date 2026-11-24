# Master Sword shuffle

`shuffle_master_sword: false` keeps the native Master Sword at the first draw.
The separate reward from Rauru still exists, as in the base game. With shuffled
native NPC rewards it can be any supported native item. Sheik's Temple of Time
song is another independent reward when its normal conditions are met.

`shuffle_master_sword: true` adds one **ToT Master Sword** AP check and one
**Master Sword** item to the multiworld. Drawing the pedestal gives its assigned
reward instead of adding a free sword. The reward can belong to any player,
and the real Master Sword can be placed in any player's world by AP. Receiving
the sword before drawing it does not consume the pedestal check.

The pedestal reward commits after Rauru and the first-draw quest writes, just
before the native age transition. Later draws check the same saved AP flag, so
interrupting the first draw after Rauru's native save cannot lose its AP reward.

Time travel remains a separate native event. Returning to the pedestal changes
age without requiring or creating a Master Sword. The native era equipment
swap only equips a Master Sword that is actually owned. Ganon's knocked-away
sword recovery requires the native saved flag recording its legitimate receipt.
No replacement cutscene, camera or model renderer is introduced.

The AP generator exports the sword at the native proof's pedestal access
sphere, observed even when NPC and dungeon rewards stay vanilla. The engine
returns this observation separately without changing the native seed or sphere
list. All later AP spheres require that sword through the existing counted
sphere gates; victory requires it explicitly. This rule is conservative: some adult locations
may be physically reachable earlier with another weapon. The supported public
configuration starts Link as a child; starting adult is not exposed.

This option requires a newly generated room and a new save. Existing player
files omit it and keep their original sword, Rauru reward and placements. It
does not remove an already earned Master Sword from an existing save. AP
location restoration restores the pedestal's saved check and personal reward
without resending another player's item.

Automated tests cover source replacement, one-time callbacks, unchanged Rauru
and time-travel routes, AP pool conservation, the conservative sword access
gate, old manifests and restoration metadata. These checks do not establish
that every sword acquisition and age change has been played through in-game.
