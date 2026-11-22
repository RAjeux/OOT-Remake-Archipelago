# Gold Skulltula shuffle

Use this in a new room's YAML:

```yaml
shuffle_skulltulas: matched
```

`off` retains the native unshuffled handling. `pinned` uses the 44 firmly
identified native locations; `matched` adds the supported researched matches
implemented by OOTRR 0.8.1. This port does not implement the N64 randomizer's
separate overworld/dungeon Skulltula modes.

The AP catalogue reserves IDs for all 100 physical Skulltula identities. At most
77 have the native placement and access support needed for network rewards. The
23 uncertain `lean`/`tour` matches retain OOTRR's local handling and restrictions.
They never hold an AP reward for another game.

In `matched` mode with the default bean settings, the Zora River raised-grotto Skulltula also
remains local: OOTRR explicitly cannot prove that bean route. `plant_beans: true`
or native starting Magic Beans allows the full set of 77. Otherwise there are
76 possible AP Skulltula checks. The generated player file and slot data list
the native-only exclusions in `local_skulltulas`. Other missing access proofs
are rejected instead of silently dropping locations.

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

Prepare the room with the matching client ZIP. Old clients do not know these
new check IDs. Existing generated rooms keep their original settings and
placements. Triforce's native connection menu and desktop window are unchanged.

Generation, native resource and event-flow tests cover this integration.
Private in-game tests exercised real pickup packs in sequence: a personal Bomb
Bag, a foreign reward, and five rupees. Their inventory effects, text and saved
location flags were verified, followed by restoration from an older save. These
tests used a private scene placement; every original Skulltula site and reward
has not been played through. The foreign medal's 3D visibility was not confirmed
by the dark test capture.

See [the complete settings comparison](SETTINGS-COMPATIBILITY.md) for the other
OOTRR options and the distinction between network checks and native-local
randomization.
