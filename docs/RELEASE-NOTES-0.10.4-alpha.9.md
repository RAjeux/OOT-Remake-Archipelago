# 0.10.4 alpha 9: native rewards, shop displays and lifecycle safety

Personal shop purchases now retain their Archipelago identity through native
selection. This fixes checks which consumed stock while bypassing AP reporting
or the progressive reward recipe. Existing consumed personal shelves recover
their missing tracking without another payment or inventory grant.

Shop displays use reviewed native pose measurements, including the engine's
fallback and retained poses. Height, uniform size and selected facing are fitted
to the original shelves, with a separate clearance cap for Kokiri's narrower
grid. The plain Deku Stick uses its existing native shop animation. The
measurement tool respects the declared number of skin influences; unused
padding previously made gauntlets and several other displays too small.
Purchase prices, recipients and item models are preserved.

Large pickup catalogues now split long AP selection chains into local function
calls. Native binding could crash before the title screen on those chains even
when the serialized file indices were valid. The same seed starts with the
bounded dispatch and its original memory budgets. Quiet restoration also shares
identical item effects while each check retains its own guards, stock and save.

Heart Containers and Pieces follow the native grant context. Presented gifts
apply their separate cure action; quiet restoration and physical pickups retain
the pouch's automatic effect. This prevents both missing hearts and duplicate
growth. Receipt and chest commits follow the complete effect and settling waits.

With the castle visit skipped, the opening no longer gives the old local Zelda
letter and Impa-song donor rewards for selected AP checks. Once Link is ready,
a quiet transaction gives the actual personal reward or completes the foreign
check. It also catches up older saves, without removing uncertain old donor
inventory. Original story state and unselected native gifts are preserved.

Triforce observes native pause and loading transitions even while inventory
suspends Link's callbacks. A DeathLink or item received in inventory waits for
normal control; loading invalidates a held death. Fresh player state is required
before another event request. Hookshot retains its existing movement gate;
the independent lifecycle observer is a Triforce integration.

Generation fixes handle the specific native token-capacity failure with all
Skulltulas shuffled and chests disabled. Missing donor catalogue entries are
admitted only when their actual AP rules and pool prove a route. Native token
counts and final AP placement remain intact.

Validation includes 36 real local two-player generations and native-client
protocol simulations, every selected check in those rooms, and separate native
gameplay, resource and shop-display controls. These are distinct from a complete
manual playthrough. See the [validation record](OVERNIGHT-VALIDATION.md).

Keep your existing native 0.10 room, YAML, `.apootrr` and save. Close Zelda and
prepare the same player file when the launcher requests updated resources.
The native Triforce host must rebuild for the lifecycle fix. The matching
APWorld is needed for the new-generation fixes; updating it does not alter
an existing room's placements. This remains an alpha release.
