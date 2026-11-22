# Adult trade shuffle

For a newly generated room, enable **Adult Trade Shuffle**:

```yaml
shuffle_rewards: supported
adult_trade_shuffle: true
```

This adds Anju's first adult gift and the ten item hand-ins, including Biggoron's
final Claim Check exchange, as **eleven Archipelago checks**. Each completed check gives only its assigned
Archipelago reward. For example, Anju does not append the next vanilla quest
item to her randomized reward.

The multiworld pool contains one of each of these ten quest items:

- Pocket Cucco, already hatched;
- Cojiro;
- Odd Mushroom;
- Odd Potion;
- Poachers Saw;
- Broken Sword;
- Prescription;
- Eyeball Frog;
- Eyedrops;
- Claim Check.

They can appear at any eligible AP location, including another player's game.
The final exchange stays an AP check even when `shuffle_rewards_extra` is
disabled. Biggoron's usual Sword joins the native OOTRR shuffle; like other
non-quest rewards, it enters AP when its generated source is a network check.

Items can arrive out of order, and several trade items can be owned at once.
An NPC automatically accepts the particular item needed for its exchange;
receiving a later item does not require completing the earlier exchanges.
Completing an exchange consumes its required item and records that check once.
Returning to an already completed exchange does not give or send another reward.

Physical access still matters. You must wake adult Talon before trading the
Pocket Cucco to Anju, and thaw King Zora before exchanging the Prescription.
The Mushroom, Frog and Eyedrops do not expire or revert, and Biggoron's final
Claim Check exchange has no three-day wait. Using an already hatched Pocket Cucco avoids
the vanilla Egg-hatching stage; this mode does not add a separate Pocket Egg
to the pool.

Loading an older save uses the same AP history recovery as the other network
checks. Completed trade checks restore their completion and consumption, and
personal rewards are recovered without sending a friend's reward twice. Save
normally before quitting.

With the updated mod prepared, loading an older save silently acknowledges
remote quest items which a completed exchange has already consumed. Their
receipt animation and notification are not shown again. The exchange's own
reward and completion still recover normally, and another player's reward is
not sent twice. Reconfigure an existing player file and rebuild Triforce when
upgrading the native library to enable this behavior.

## Existing rooms and the old bonus option

The old native `shuffle_trade_checks` setting meant **extra local rewards**:
the normal quest item plus a randomized bonus. Existing generated player files
keep that behavior. The native engine retains its old setting number and
meaning so those seeds remain compatible.

New YAML files use `adult_trade_shuffle` instead. An enabled
`shuffle_trade_checks` in a new YAML is rejected with migration instructions;
an old disabled value is accepted and ignored. With full shuffle disabled,
new rooms keep the ordinary adult trade quest.

An existing room cannot acquire this new item pool by changing its YAML or
reconnecting. Generate a new room with the matching APWorld and client, install
its new player file, and start a fresh save. The configuration process prepares
the portable OOTRR base and the independent AP hand-ins automatically.

## Generation and validation scope

The generator uses item-by-item OoTR access rules, with trade reversion disabled.
Its intermediate native proof reserves the ten trade items at the ten trade
checks so every one enters the AP pool. Archipelago then redistributes them
normally across the multiworld; this intermediate reservation does not restrict
their final location or owner.

Focused private gameplay tests verify Anju's first gift and Pocket Cucco exchange,
Talon's wake-up with the Cucco hidden behind another menu item, concurrent quest
stocks, Grog's Cojiro exchange for a personal reward, repeated dialogue without a
second reward, and older-save recovery. Grog and Fado appear together without
removing the nearby Skull Kids.
They do not cover every NPC hand-in.

Automated checks cover all ten isolated item requirements, complete generated
access proofs for all eleven checks, the item counts, and compatibility of the
derived base seed with portable OOTRR settings. These generation checks do not
replace gameplay validation of every NPC hand-in.

See [multiworld distribution](MULTIWORLD-DISTRIBUTION.md) and
[settings compatibility](SETTINGS-COMPATIBILITY.md) for the other source families.
