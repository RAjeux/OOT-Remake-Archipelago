# Changelog

## 0.12.0-alpha.3

Fix the native fishing-rod handover freezing Link with a hidden HUD. Native C
hosts now preserve the original Player AI instead of installing the external
readiness publisher. Their existing game-thread receipt guards remain active.
Known older native caches are repaired with verified resource hashes; unknown
Player graphs are rejected. Update the same player file to preserve the room,
placements and save. External readiness behavior is unchanged.

An isolated actual-host A/B reproduced the freeze offline and restored the
native handover, HUD, movement and rod use by changing only the Player brain
member in three actor packs. The user's running game and save were untouched.

## 0.12.0-alpha.2

Fix APWorld installation through Archipelago: the adapted engine is now nested
inside the world package, leaving the single root directory required by the
launcher. The standalone archive and the application use the same packaging
function. Gameplay settings, IDs, placements and saved games are unchanged.


## 0.12.0-alpha.1

- Full-network configuration expands to 119 configuration controls. The default
  catalogue grows from 1,104 to 1,106 checks with two researched loose dungeon
  keys. Individual AP keys use the remake's actual 39-key supply; optional
  rings, spent-key behavior and historical player files retain explicit rules.
  Imported Water/Well/Ganon key minimums are bounded by the real 4/2/1 supplies
  in every mode, without adding keys or changing lower requirements.
- Bridge, trial and Ganon boss-key/LACS conditions now share matching native
  checks and AP logic. Heart goals use the real native health supply and put
  any missing heart pieces into the normal multiworld pool.
- Economy follows the remake's 200/500/1,000-rupee wallets, final AP shop/
  merchant placements, advertised prices and debits. Scrub hints name the final
  item and recipient. Paired dungeon entrances, independent story settings,
  supported native quality-of-life and challenge adapters receive additional
  consistency checks.
- Native equipment acquisition is checked when shuffling dungeon entrances;
  unsafe equipment/ocarina cycles retry without invented starting gear. Whole-
  shop shuffle transfers a displaced essential shield into the ordinary AP
  pool only when no copy already exists. No recipient quota is introduced.
- Validation rejects permanent heart loss with an active heart goal above
  three, and no random ammunition drops with every shop slot shuffled.
  Numbered Shopsanity retains renewable ammunition stock; logic removes the
  corresponding disabled native drop credits while retaining AP sticks/nuts.
- Complete resource budgets include modified packed members, fixing full-mod
  loading that could stall on an actual host. Native host-helper revision
  checks and external readiness version 2 detect an outdated prepared install.
  Update the same player file to keep the room, placements and saves.
- The external runtime supports native live-state DeathLink with safe deferral,
  fresh-life handshakes and no echo/stale replay. Actual Fritchii gameplay now
  covers offline receipts, native presentation, pause/ladder safety, owned-item
  old-save recovery and both DeathLink directions. Relocated source/enemy
  fixtures are identified separately from original physical routes.
- Actual private Triforce smoke and Hookshot Spirit/fishing regressions add
  gameplay evidence. The fishing guard now follows the correct Player
  extension and waits between casts as well as during the cast.
- Actual Hookshot receives individual AP Forest keys outside the dungeon,
  updates only their native dungeon counters and avoids duplicate grants.
  Child/adult key presentations use native animation and camera framing.
- Shield tracking reads verified saved pouch stock instead of assuming an
  obtained-item flag still means ownership. Translated observation labels
  distinguish stock, unavailable stock and recorded progression. AP receipts
  and consumed-item recovery are unchanged.
- French labels/help cover all 119 Full controls; damaged accents and obsolete
  malformed wallet labels are repaired, with UTF-8 and coverage regressions.
- Full adult start is temporarily blocked in generation and preparation after
  an actual native opening stall. Choose Child for new rooms; existing adult
  player files remain readable for diagnosis without changing their identities.

The complete source run passed 109 commands and 684 unittest cases without
failures or skips. Another 309 compatible settings combinations passed.
Go race tests and Rust regressions passed, including five normally ignored
core resource tests; three interactive Rust process/picker tests remain
outside automation. Fresh native/external 1,106-check artifacts were verified.
The final executable passed payload inspection covering 526 Python modules and
an isolated selftest with a Unicode profile and only Windows System32 on PATH
in 10.94 seconds. That selftest starts neither a game nor a server. Adult start
remains blocked; original-route pickup of the two added loose-key checks still
needs gameplay confirmation. No full playthrough of every check or every
emulator is claimed. Published 0.11 artifacts/tags/references are not replaced.

## 0.11.0-alpha.1 — historical published baseline

Introduced the full-network engine, 1,104 default AP checks, a single Windows
application, full/legacy settings editing, room profiles, tracker/chat and
signed-update tooling. Its original validation and limitations remain in
[Full-network engine](FULL-NETWORK.md#011-release-validation--historical-baseline)
and the immutable published release.
