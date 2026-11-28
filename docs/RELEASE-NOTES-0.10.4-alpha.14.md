# OOT Remake Archipelago 0.10.4 alpha 14: held item framing

Some AP display models retained their mesh but lost the game's authored body
pose or display offset. This could make a chest reward too large, leave an
ocarina in its raw orientation, or place a received reward at the wrong height.

Generated display actors now retain the native item animation resources that
provide their body pose, scale and orientation. Compatible native display
actors supply matching stick, ocarina, bomb and heart poses. Chest guests retain
their item display offset; isolated receipt models forward their missing vertical
offset through the existing native `ItemPos` parameter. Personal NPC gifts,
adult trades and the randomized Master Sword pedestal use the same correction.
The native small-key model already supplies its offset and is not offset twice.

The Master Sword has no ordinary native get-item actor. Its two isolated AP
display actors use the native Kokiri Sword orientation with a measured static
scale and center. Its full rotation envelope is approximately 0.606 m wide and
0.650 m high. The original sword mesh, weapon actor and pedestal are unchanged.
The Bow could also extend beyond the top of the frame with child Link, including
in a physical chest. Its isolated display model has a measured pose and display
height that fit the native cameras. The progressive quiver models keep their
native pose and height. Receipts, NPC rewards and chests use these display
actors; the usable Bow, actual grants and native camera routes are unchanged.

The read-only geometry audit covers all 167 supported native actor/tier
identities, their receipt and chest variants, and the foreign AP token. It uses
skinned vertices and native body/rotation masks, with continuous full-turn
envelopes for static bodies and fractional-frame samples for animated bodies.
Resource comparisons identify the affected presentation cases, with overlapping
pose and offset corrections. Chest guest offsets retain the native values,
except for the reviewed Bow display profile;
the foreign AP token's geometry is unchanged.

Private Triforce rendering checks cover all 167 native actor/tier identities
with child and adult Link, plus 50 alternative chest display models at both
ages. The display gallery exercises native held poses, message completion and
return of player control; it does not grant inventory items or reproduce every
physical chest and NPC camera. Separate physical chest tests check the Bow's
framing and one-time native inventory grant. These observations complement the
geometry audit; they are not a complete playthrough of every reward source.

Automated checks cover native pose retention, matching meshes, offset
inheritance, progressive tiers, one-time migration from alpha 13, resource
allocation budgets and refusal of unrecognized overrides. Geometry and asset
checks are distinct from native rendering and complete item transactions.
The optional maintainer audit and its limits are described in
[the development guide](DEVELOPMENT.md#review-held-item-presentations).

After updating, close Zelda and prepare the **same `.apootrr`** when requested.
Prepared resources are regenerated together. Keep the same room and save;
generation rules, AP IDs, placements, inventory effects and saved item history
are unchanged. No new YAML or room is needed. Dungeon names from alpha 13 and
YAML import from alpha 11 remain included.
