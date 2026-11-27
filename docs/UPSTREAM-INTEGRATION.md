# Selective OOTRR integration

This branch integrates reviewed additions from
[OOTRR revision `4fa6e5a`](https://github.com/ootrando/ootrr/tree/4fa6e5a6da839b4766bcedafb718c241a25bdd77),
the nightly source reviewed on 27 November 2026. That source identifies itself
as an upcoming 0.9.0; there is no 0.8.4 tag in the reviewed repository.
This work does not replace the integration with upstream's AP implementation.

## Compatibility boundary

The downloaded native constructor remains **OOTRR 0.8.1**. Its seed, settings
string and checksum remain unchanged. Player files made by the released native
0.10 integration retain their original preparation path and source selection.
The discontinued Full 0.11/0.12 format remains unsupported.

New rooms carry a validated `features` envelope, the current access graph and
source schema 2. Additional native edits run on a private staged mod after the
compatible constructor. Old source IDs are retained; 17 new IDs are appended.
Feature choices and the access graph participate in the room identity, preventing
a different ruleset from silently sharing a save profile. A new setting or
expanded catalogue requires a new room and a dedicated save.

The existing native AP client, durable receipt cursor, recovery journal,
DeathLink, title-screen connection, AP menu, item presentation and launcher remain
the integration's own. Received items still wait until Link can execute their
native effect. Cosmetic shuffles never reroll gameplay placements or replace
the Archipelago title artwork.

## Adapted additions

| Upstream addition | Archipelago adaptation |
| --- | --- |
| Revised remake access logic | Current region, age, event, time and item rules are exported to AP. Fixed native events are retained; a randomized source does not also grant its donor reward in logic. Historical source names, including renamed shelves, map to their existing physical AP identity. |
| Additional dungeon rewards | Six frozen chests and ten other chests become genuine AP sources when selected. The separate underwater Ruto's Letter pickup is included when its source selector is active. Frozen chests grant the AP reward instead of an additional native trap. |
| Small-key information | Optional native dungeon-map tracker uses the recipient's actual key totals, including keys placed in another world, fixed keys and starting keys. |
| Gear shortcuts | Optional D-pad cycling checks current pouch stock and age. It never grants masks or equips a mask borrowed or returned earlier. |
| Scarecrow, Skulltulas and goals | Free Scarecrow; daytime Skulltulas; optional Sun's Song requirement for night-only sites; medallion-only bridge and Light Arrows-scene thresholds; classic Medallion-based Prelude and Nocturne triggers. Native resource edits and AP access rules change together. |
| Minigames and travel | Any handed-in fish can qualify; shorter Skull Kid memory game; first-race Dampe reward; guaranteed first correct dig; reusable owl rides; optional tower-escape skip and area-introduction skip. Reward completion still uses the room's AP callback. |
| Interface and first pickups | Low-health warning control; additional first-pickup fixes; safe Navi travel cleanup; current child tunic purchase behavior; Lake Hylia tree-wall correction and field sunlight palette repair. |
| Ice Traps | Optional 1–10 traps replace eligible filler copies, never progression. A dedicated native cold event grants no pouch item. Receipt acknowledgements and recovery guards use the normal AP transaction; loading an older save does not trigger an already collected local trap again. |
| Cosmetics | Individual colours for 27 parts, random/shared colour modes, music and sound-effect shuffles. The room provides a deterministic cosmetic seed; appearance does not change the AP pool. |
| Plandomizer | Planned personal rewards consume existing pool copies and obey source restrictions and reachability. Invalid, unavailable or circular plans fail before the pool is changed. |
| Difficulty | The reviewed difficulty modules run once in a separate pass. Selected AP actor identities are protected from enemy replacement and density edits. Replacement enemies require no additional equipment beyond a sword; combat barriers check the sword for Link's age. |
| Performance and Windows support | BYML writer optimization; correct dictionary-frame header handling; private file enumeration for Windows WASI; constructor and native-cache isolation. |

All supported additional options have English and French labels and help in the
YAML editor. Their YAML keys remain language independent. The native settings
audit and the versioned feature envelope are separate: these additions are not
injected into an old OOTRR settings string.

For hand-written YAML, `cosmetic_color_mode: random_colors` explicitly randomizes
each supported colour. Archipelago reserves `random` to choose a whole mode,
which can also be Off or Custom. The editor writes the explicit key for you;
this is the same distinction as `shuffle_shops: random_deals`.

## Deliberate differences and unavailable features

The upstream native stock layout is not imposed on AP rewards. Every enabled
shop shuffle still exports all 64 purchases, which can contain personal or
foreign rewards. Native-only rules about leftover stock moving to the same
shelf, right-side special deals or prices based on a donor tunic must not
constrain the final AP fill. Unshuffled native shops keep their own stock.

Upstream's debug pickup watcher and detection backend are not substituted for
the room-bound AP source callbacks. The launcher tracker already identifies
the selected AP checks. This avoids converting automatic pickups into manual
interactions or confusing a donor item's flag with the collected AP source.

**Enemy size edits, size-dependent health and roaming Volvagia are unavailable.**
The reviewed source documents ignored placement-scale edits and an incomplete
boss death sequence. Their non-default values are rejected, rather than offering
controls with a known broken effect. Source retained for investigation is not
evidence of a supported option.

Existing limitations such as AP-aware native gossip hints, Silver Rupee
delivery, broader entrance shuffle and emulator gameplay backends are unchanged.
They are not enabled by copying an upstream setting. See
[settings compatibility](SETTINGS-COMPATIBILITY.md) and
[host compatibility](PORT-COMPATIBILITY.md).

## Validation

The integration is checked at several independent levels: Rust and Python
regressions, the newly compiled WASM through Node on Windows, official AP 0.6.8
generation, native bridge/protocol models and complete offline mod preparation
against a supported game dump. Real-resource tests use read-only inputs and
private output directories; no game data is distributed.

These checks do not constitute a complete in-game playthrough of every option
combination. New difficulty and presentation paths still need gameplay feedback.
See [candidate validation](UPSTREAM-VALIDATION.md) for measured results and
[testing](TESTING.md) for reproducible commands and the distinction between
resource validation, protocol integration and observed gameplay.
