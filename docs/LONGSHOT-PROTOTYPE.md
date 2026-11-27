# Internal Longshot adapter prototype

Longshot is **not selectable in the player launcher**. This is Windows source
integration for developers, not a supported player installation.

The adapter accepts only a clean checkout of the official
[Longshot repository](https://git.magicbean.dev/MagicBeanDev/Longshot) at
`e8fce9956e2a42972deb9b1274f705ecbb414c84`. It checks the exact source revision,
critical file hashes and patch anchors before creating a private copy. This pin
does not certify other commits, a published Longshot version, or Linux support.

`client/ootrr_triforce/longshot_setup.py` stages the source. The new
`native/ootrr_ap_longshot*.inc` helpers retain our verified Go DLL and native
receipt protocol, with these host-specific adaptations:

- Guest event requests and saved flag setters use Longshot's `game_call` API,
  preserving its virtual-core scheduler and asynchronous context polling.
- The AP update runs on Link's guest thread. The existing safe-action gate stays
  in effect. The old direct inventory-grant mode is refused.
- Connection fields use Longshot's native text editor, controller navigation and
  paste input. AP rows belong to its menu model. Passwords are masked and cleared
  when the menu closes; AP settings stay outside Longshot's ordinary settings.
- `launch_environment()` supplies a separate AP profile before the host chooses
  its save root. Native bootstrap rejects another profile's save directory.

## Validation on 2026-11-27

The exact Windows compiler, SDL and dependency archives from the pin's
`tools.lock` were downloaded and SHA-256 checked in an isolated workspace. All
905 native compile units and the game's Rust library compiled; both the patched
game executable and renderer linked. The renderer also passed a separate build.
Longshot's own scheduler tests passed, including pending polling requests and
virtual-core ownership. Our portable C request model checks refusal, argument
cleanup and retaining an already accepted request instead of delivering it twice.

An actual private game process reached Zelda's title screen with no save loaded
and connected to a copied, historical two-player AP fixture on `127.0.0.1`.
This bootstrap proof loaded the opt-in room marker and native DLL; it did not
install a complete randomized RomFS overlay.
The server accepted the AP and DeathLink tags. The native controller API found
the new AP menu setting. A tagged death sent at the title left the title active;
restarting the local server reconnected the same game at the title. The title
image was inspected, rather than inferred from a connection log.

Private evidence is under `build/longshot-session-private/runtime-proof.json`
and its `run-title-2/shots/` directory. Generated executables, game resources,
profiles and screenshots stay local and are not release assets.

A separate incoming-DeathLink smoke test used Longshot's scrubbed `kokiri-start`
test save in a new private profile. The normal `bind_romfs` preparation added the
room's saved cursor and resource-size table; the player gate correctly refused
the earlier marker-only setup. With Link idle and no event playing, a death from
the local Ami client changed native life from 12 to 0 while maximum life stayed
12. The host and DLL logs recorded the received death and no outgoing echo.
`build/longshot-session-private/incoming-deathlink-proof.json` records the native
before/after state. The tests used the linked binaries from the private build
folder; the official builder also completed its separate game-folder finalizer.

A further private test prepared a complete schema-2 room from an actual solo AP
generation: 185 checks and six Ice Traps substituted in its item pool. The normal
constructor, feature pass, native receipts, physical rewards, restoration and
saved-flag registration prepared all 322 mod resources; the roster came from the
generated AP multidata. No game resource, inventory flag or receipt index was
changed through the controller or debugger.

Real server gifts then exercised the native Ice Trap receipt. Outside Link's
house, screenshots show the child's blue ice shell and the native shards as it
thaws. Native life fell from 8 to 4, the saved receipt cursor advanced exactly
once from 2 to 3, and Bow and all quiver ownership flags remained zero. Ordinary
controller movement worked again after thawing. An earlier gift stayed queued
while Link descended the house's ladder and delivered on reaching the ground.
The indoor starting-house case committed its receipt without a visible freeze;
the cause of that native difference has not been established.

A subsequent Bow probe used an inconsistent restarted test fixture: the server
had persisted only one earlier trap, while the game had saved receipt cursor 3.
The newly sent Bow was therefore below that cursor and correctly remained
unapplied. This invalid probe does not establish a Longshot request or readiness
bug. `item-receipts-proof.json` retains its original observations.

The same prepared mod was then tested on the primary Triforce adapter with the
exact missing history restored through ordinary server commands. The Bow
advanced the cursor from 3 to 4 and granted native Bow and small-quiver ownership;
five rupees advanced it to 5 and increased the balance by five with a stable
camera. The saved game retained cursor 5 and both equipment flags. No game
cursor or inventory flag was edited. These important-item and rupee cases still
need direct validation on Longshot with a consistent server history.

Evidence is in `build/longshot-ice-runtime-private/prepared.json` and
`outside-ice-proof.json`, with inspected screenshots under
`run-tutorial-77fd1368/shots/`. The final engine used for this test has SHA-256
`e9f2ce7426afbec3fc101bea374ed4b550ec9ebbe9870a3f9769122a44301c6c`.

This establishes title connectivity, reconnection, one real incoming death and
one native item-receipt family. It does **not** establish the other received-item
families, natural outgoing DeathLink, rollback recovery, every pickup source, or
a full playthrough on Longshot. Those need further private gameplay tests before
exposing this host to players. The existing Triforce and pinned Hookshot adapters
keep their own validation boundaries.

Run `python tests/test_longshot_setup.py` for source and request-model checks.
Set `LONGSHOT_TEST_SOURCE` to the clean pinned checkout to enable its source-pin
test. No game is launched by that test. The C model also runs through
`python tools/test_bridge.py --cc <compiler>`.
