# Full-network engine in 0.11

The full-network engine adapts Mozencaz/OotrR at revision
`72198c684ac8b98a243e2a7040086fbe6de87049`. Its original MIT attribution and
file hashes are retained. The historical OOTRR engine remains available as
`generation_mode: legacy`; existing player files keep their original path.

## Checks and settings

The default full-network configuration has **1,104 AP locations**. Examples
include 188 shuffled chest locations, 98 Gold Skulltulas, all 64 shelves in
eight shops, 11 adult-trade handovers, 12 songs, nine boss rewards, eight boss
hearts, six great fairies, eight first cow rewards and ten separate bean
purchases. Selected pots, rocks, trees, crates, beehives, bushes and ground
items also participate. Counts depend on the enabled options and the physical
sources present in this remake.

Enabled checks replace their native reward with the AP placement. A personal
placement keeps its game item; another player's placement shows the AP medal.
Purchases use the native shop interaction. Cows can give ordinary milk after
their first AP reward. Refillable native resources outside the selected
catalogue remain ordinary resources.

There are 995 default checks with precise progression rules and 109 with
approximate access. Approximate checks cannot hold progression. Unsupported
physical sources are excluded, rather than invented from a location name.

The full and historical settings schemas differ. Full-network uses the
supported remake goal rules: the vanilla Shadow/Spirit bridge, six Ganon
trials and the native Ganon boss key. Other bridge/trial/Ganon-key settings
remain available in the historical engine. A vanilla dungeon-item setting
intentionally retains that native reward. The full editor exposes adapted
values; it does not claim that every historical OoTR setting has a full-mode
equivalent. Importing an old YAML in the editor preserves its engine.

Use [Full-Network.yaml](../examples/Full-Network.yaml) as a small new-room
example, or the application's settings editor. Both historical examples now
explicitly select `legacy`, so new APWorld defaults cannot reinterpret them.

## Delivery and old saves

Native Triforce/Hookshot delivery uses the existing bridge and registered game
events. Remote receipts commit their inventory effect with the received index.
Physical personal rewards use a remote-only AP stream, avoiding a second copy.
Saved source flags and durable server/check history support old-save recovery.
Recovery also reconciles consumed trade items, progressive source tokens,
chest state, frogs and bean-purchase state.

The experimental external runtime uses authenticated `Sync/Get` fences and
native mailbox events. It supports an empty initial item history, missed
remote items and server-confirmed physical-check recovery. It prevents a spent
trade item being refunded after rewind. Its session gate is explicitly cleared
during loading/pause. External DeathLink remains unavailable.

Received ammunition uses the named quantity. Missing required ammunition
equipment consumes the receipt without granting ammunition or substitute
rupees. Real bows/slingshots initialize their capacity when obtained. Native
small pickups keep the game's display; important receipts use its authored
presentation and camera-facing turn. Constrained player actions defer delivery.

## Validation

The release was checked with Archipelago 0.6.8. The complete suite ran 95
scripts/commands and 561 unittest cases without failures or skips. A final
YAML-parser correction additionally passed 49 targeted cases, including the
new construction-bound test. Go and C models, real resource round trips,
actual local servers and standalone application checks are included.

Fresh full mod builds were made from the supported game resources for both
child and adult starts. The final native build and preparation kept the same
source fingerprint and verified 1,104 recovery records, 21 personal progressive
source bindings, ten trade replay events, 120 item recipes, 1,295 saved flags
and 2,352 generated resources. Its DLL/server test covered offline items,
reconnection, no double personal reward, no repeated foreign send, recovery
snapshots and both DeathLink directions. Inventory effects in that network
test were modeled; Zelda was not being played.

The external runtime was tested against an actual AP server and generated mod,
with game memory and native effects explicitly interpreted. This is evidence
for protocol/resource behavior, not a successful emulator or port playthrough.
The frozen executable passed with only Windows System32 on PATH, isolated
Unicode data folders, no separate Python/Node installation, and a responsive
Tk window during child-process work.

Three Zelda/DS3 generations and a room with two identical Zelda players
verified cross-world placement. The identical pair placed 122 progression
items locally and 123 in the other world for each player. This demonstrates
mixing; it is not a promise of equal progression counts or timing between
different games. No local-item quota was added.

This remains an alpha. The full new catalogue has not had a human playthrough;
animations, individual checks and other-host behavior still need gameplay
regression reports. Original player saves, game installations and the global
APWorld were not modified by these release tests.
