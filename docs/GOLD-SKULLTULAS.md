# Gold Skulltula shuffle

Use this in a new room's YAML:

```yaml
shuffle_skulltulas: matched
```

In the English/French editor, select **All 100 native sites / Tous les 100**.
Its YAML key remains `matched` for compatibility. **44-site subset / Sélection
de 44** uses `pinned`; `off` keeps the native unshuffled handling. This port does
not add separate N64 overworld/dungeon Skulltula modes.

All 100 selected sites become AP checks in a new `matched` room. The native
filler-only restrictions are retained at 23 uncertain `lean`/`tour` sites.
Those sites can hold filler for Zelda or another player, but never progression
from any game or Zelda tokens. They are no longer silently left outside AP.

Known bean-route sites which the native conservative search does not prove
remain networked with late AP access requirements. Unrecognized missing proofs
still fail generation. This does not change the selected bean settings or grant
beans artificially. The native 100-token reward has a separate final gate which
requires every AP token in its pool; a last token cannot be placed behind itself.

A Skulltula check completes when its dropped reward is collected. Killing the
enemy or receiving a Gold Skulltula Token from the network does not complete
that location. The pickup retains the native Skulltula persistence protocol;
leaving the drop behind does not commit its AP location flag.

A local reward uses native item text and effects. A foreign reward shows the AP
medal and recipient. The original Gold Skulltula Token is replaced by that
reward; the token count rises only when the assigned or received item is itself
a Gold Skulltula Token. Local bottle refills are excluded from these drops
because the native pickup cannot defer them while waiting for an empty bottle.
Bottle containers and other supported rewards remain eligible.

Prepare the room with `OOT-Remake-Archipelago-0.10.1-alpha.2.exe`. The APWorld is
installed through the same app. A new room and dedicated save are required for
the expanded source selection. Existing generated rooms keep their original
settings, AP catalogue and native-local exclusions; updating their client does
not add checks or reroll their rewards. Triforce's connection menu is retained.

Automated tests cover native source identities, generation, collection/presence
flags and filler-only restrictions. Actual Archipelago 0.6.8 mixed generations
include 100 Skulltulas per enabled Zelda world and verify the serialized rewards
and progression flags. This is not a manual playthrough of all original sites;
the expanded catalogue has not been completely collected in-game.

See [items, checks and saves](ITEMS-AND-SAVES.md) for personal rewards,
reconnection, old-save recovery and compatibility with older rooms.
