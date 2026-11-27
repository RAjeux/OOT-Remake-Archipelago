# 0.10.4 alpha 5: chest opening and item models

Chests containing another player's item could display an Open prompt but fail
to open. The shared pickup dispatcher introduced a concrete ice-trap subflow
dependency without adding it to existing native event preloads. Preparation
now merges new subflow and child-event dependencies into every affected event,
including ordinary chest, shop and NPC callers. Native message dispatch
metadata is retained.

The merge uses each owning chart's exact entry so silent acknowledgements for
already consumed adult trade items retain their original contract. Final trade
resources still pass strict validation and receive a matching capability seal.

Some local chest rewards, including shop versions of Deku Sticks, used actors
without a compatible get-demo performer. Chest presentation now uses safe
native guest actors with the actual item's model. The real reward, quantity,
progressive tier and Archipelago identity remain separate from this display
actor. Generated actor-pack components also retain their native resource
allocation allowances.

Close Zelda, update the launcher and prepare the **same `.apootrr` file** when
requested. Your room, save, settings, collected checks and item placements
remain compatible. There is no need to generate another seed or reinstall the
APWorld for these fixes. Previous menu-memory and opening fixes are included.

Validation and its gameplay coverage are recorded in [STABILITY.md](STABILITY.md).
