# Adult trade rewards

The **Extra Adult Trade Rewards** control keeps the existing YAML key
`shuffle_trade_checks` for compatibility.

With `shuffle_rewards: supported` and `shuffle_trade_checks: true`, the first
successful completion of each supported adult trade hand-in gives a shuffled
local reward **in addition to** its normal quest item. Anju can therefore give
the Pocket Egg or Cojiro and a separate randomized reward. Subsequent dialogue
does not award the bonus again. These hand-ins remain native-local, rather than
Archipelago network checks.

Setting `shuffle_trade_checks: false` removes the extra randomized rewards and
keeps the ordinary trade quest. Neither value replaces the quest item with only
a random reward. Existing generated rooms retain their original assignments.

A full adult trade shuffle needs more than removing the vanilla gift. The
remake presents the chain's items through a shared inventory slot, while NPCs
check the held item and the quest's current stage. The Mushroom, Frog and
Eyedrops also have timed failure and retry paths. Receiving these items out of
order would need persistent ownership of every unconsumed item, a way to select
or expose the correct item, and matching NPC, retry and access-logic changes.
Until those pieces are implemented together, full replacement is not exposed
as an active YAML option.

See [settings compatibility](SETTINGS-COMPATIBILITY.md) for the distinction
between native-local randomization and Archipelago network locations.
