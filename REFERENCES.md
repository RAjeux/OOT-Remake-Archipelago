# Code and resource provenance

Integration code and its modifications are licensed under **GPL-3.0-or-later**; the full text is in [LICENSE](LICENSE). Third-party components and artwork retain the licenses below and their original notices. The root [NOTICE](NOTICE) summarizes these distinctions.

## Code

| Component | Reference and location | Retained license and credits |
| --- | --- | --- |
| [OOTRR 0.8.1](https://github.com/ootrando/ootrr/releases/tag/v0.8.1) | Revision `3ee77a632fb7c5ed2ccdc33db129f659bc23419f`; adapted engine in `moteur/ootrr-ap/`, shared export in `client/ootrr_triforce/` | GPL-3.0-or-later; `moteur/ootrr-ap/LICENSE`, `NOTICE`, and `LICENSE-MIT`. Upstream MIT components and contributions remain credited in these notices. |
| [Selected OOTRR 0.8.2 fixes](https://github.com/ootrando/ootrr/releases/tag/v0.8.2) | Revision `0fa64f44b5e689f39bcf98a151fc32cb019d538e`; dungeon logic in `moteur/ootrr-ap/data/logic/World/`, native story/quest/fortress adapters in `client/ootrr_triforce/` | GPL-3.0-or-later; existing OOTRR notices retained. The integration preserves its frozen AP identities and adds regression tests. The external builder remains 0.8.1. |
| [Reviewed OOTRR nightly additions](https://github.com/ootrando/ootrr/tree/4fa6e5a6da839b4766bcedafb718c241a25bdd77) | Revision `4fa6e5a6da839b4766bcedafb718c241a25bdd77`; rules and provenance in `moteur/ootrr-ap/data/ap_logic_v2/`, selected QOL, difficulty, tracker, frost and resource modules in the adapted engine | GPL-3.0-or-later with retained OOTRR/OoT Randomizer notices. [Integration boundaries](docs/UPSTREAM-INTEGRATION.md) document AP adaptations and unavailable features. The constructor remains 0.8.1; AP source IDs and the native client are preserved. |
| [Mozencaz/OotrR](https://github.com/Mozencaz/OotrR/tree/e291a1b103bd52d8878207ba7800bf670418144c) | Revision `e291a1b103bd52d8878207ba7800bf670418144c`; resource tools and adaptations in `client/oot_rando/` | MIT; `client/credits/OotrR-MIT.txt`, `ARCHIPELAGO.txt`, and `Visuels.txt`. |
| [Archipelago](https://github.com/ArchipelagoMW/Archipelago/tree/debe4cf035c7c15efe6fb95f72343af0d420c68c) | Reference revision `debe4cf035c7c15efe6fb95f72343af0d420c68c`; protocol/server baseline 0.6.7, direct YAML generation tested with 0.6.8 | Upstream project and reference protocol; its artwork has terms separate from its code. |
| [Archipelago-SoH 1.4.2](https://github.com/HarbourMasters/Archipelago-SoH/releases/tag/Soh_1.4.2) | Consulted revision `cd9179cb4f5890f8a977e6cac59c54cda48a9df6` | Multiworld integration reference; this repository does not redistribute the SoH game. |
| [Triforce](https://git.triforceproject.com/triforce/source) | Reference revision `b0e46adb484681a34ece82bbace9ec085a4eae1f`; test excerpts in `references/triforce/` | Original GPL notices and provenance are retained, including `references/triforce/host/PROVENANCE.md`. The mod's bridge is in `native/`, with its installer in `native_setup.py`. |
| [Hookshot source lineage](https://github.com/tailin/hookshot) | Experimental Windows adapter targets the locally installed 3.0.1 host and renderer using exact source hashes in `hookshot_setup.py`. The linked repository is a publicly accessible fork of NotRexed/Hookshot. | Hookshot and game binaries are not redistributed. The new adapter and menu live in `native/ootrr_ap_hookshot*.inc`; adapted Triforce GameData helpers retain their GPL-3.0-or-later attribution. Original Hookshot sources are copied locally before patching. |
| [Longshot native APIs](https://git.magicbean.dev/MagicBeanDev/Longshot/src/commit/e8fce9956e2a42972deb9b1274f705ecbb414c84) | Audited revision `e8fce9956e2a42972deb9b1274f705ecbb414c84`; internal Windows source adapter in `longshot_setup.py` and `native/ootrr_ap_longshot*.inc`, using its bounded flag readers, `game_call` scheduler and menu model. [Prototype scope](docs/LONGSHOT-PROTOTYPE.md). | GPL-3.0-or-later; MagicBeanDev and the retained Longshot/Hookshot lineage notices. Source is staged privately before patching; no Longshot/game binaries or generated game resources are redistributed. Title connection, reconnection and one incoming DeathLink are verified; outgoing deaths, received items and rollback remain unverified on this host. |

The independent option-roll audit also consulted disabled-setting normalization
in [OoT Randomizer's Settings.py](https://github.com/OoTRandomizer/OoT-Randomizer/blob/Dev/Settings.py)
and public-to-native option translation in
[Archipelago 0.6.8's OoT world](https://github.com/ArchipelagoMW/Archipelago/blob/0.6.8/worlds/oot/__init__.py).
These are design references; the remake adapter does not imply N64 OoT or
Ship of Harkinian host compatibility.

Python dependencies retain their licenses in `client/credits/` and `client/websockets/`, including the ainb, evfl, and Zstandard notices. Rust dependencies and licenses are vendored in `moteur/ootrr-ap/vendor/`. Go licenses and third-party DLL sources are in `distribution/sources/` and `native/vendor/`. The installer's x64 Zstandard library is accompanied by `distribution/runtime/LICENSE.txt`.

The root license does not replace any third-party license. Changes made for this integration must not be attributed to the authors of upstream versions.

## Artwork

- **Colored Archipelago icon**, Krista Corkos and Christopher Wilson, 2022: [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/). `assets/icon.png`, its title integration, and the in-game AP medal retain this attribution. Adaptations include resizing, texture conversion, and in-game presentation.
- **Title lettering**: rendered for this project by `tools/generate_art.py` using **Cinzel**, Copyright 2020 The Cinzel Project Authors. The font is licensed under **SIL Open Font License 1.1**, with its notice in `moteur/ootrr-ap/web/assets/fonts/OFL-Cinzel.txt`. The restricted Archipelago website wordmark has been replaced and is not distributed with this alpha.
- Texture conversion routines derived from Mozencaz/OotrR retain their MIT notice. Bundled attributions are in `client/credits/Titre-Archipelago.txt` and `Visuels.txt`.

Artwork does not acquire a uniform GPL license merely by accompanying the code. The release contains no files extracted from the Nintendo game; players provide those files locally when generating their mods.
