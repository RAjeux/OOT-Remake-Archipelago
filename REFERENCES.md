# Origine du code et des ressources

Le code d’intégration et ses modifications sont sous **GPL-3.0-or-later** ; le texte complet est dans [LICENSE](LICENSE). Les composants tiers et les visuels conservent les licences décrites ci-dessous et leurs notices d’origine. Le [NOTICE](NOTICE) racine résume cette répartition.

## Code

| Composant | Référence et emplacement | Licence et crédits conservés |
| --- | --- | --- |
| [OOTRR 0.8.1](https://github.com/ootrando/ootrr/releases/tag/v0.8.1) | Révision `3ee77a632fb7c5ed2ccdc33db129f659bc23419f`, moteur adapté dans `moteur/ootrr-ap/`, export partagé dans `client/ootrr_triforce/` | GPL-3.0-or-later ; `moteur/ootrr-ap/LICENSE`, `NOTICE` et `LICENSE-MIT`. Les contributions et composants MIT en amont restent crédités dans ces notices. |
| [Mozencaz/OotrR](https://github.com/Mozencaz/OotrR/tree/e291a1b103bd52d8878207ba7800bf670418144c) | Révision `e291a1b103bd52d8878207ba7800bf670418144c`, outils de ressources et adaptations dans `client/oot_rando/` | MIT ; `client/credits/OotrR-MIT.txt`, `ARCHIPELAGO.txt` et `Visuels.txt`. |
| [Archipelago](https://github.com/ArchipelagoMW/Archipelago/tree/debe4cf035c7c15efe6fb95f72343af0d420c68c) | Révision de référence `debe4cf035c7c15efe6fb95f72343af0d420c68c` ; serveur 0.6.7 utilisé pour les tests de développement | Projet amont et protocole de référence ; ses visuels ont des conditions distinctes du code. |
| [Archipelago-SoH 1.4.2](https://github.com/HarbourMasters/Archipelago-SoH/releases/tag/Soh_1.4.2) | Révision consultée `cd9179cb4f5890f8a977e6cac59c54cda48a9df6` | Exemple étudié pour l’intégration multiworld ; ce dépôt ne redistribue pas le jeu SoH. |
| [Triforce](https://git.triforceproject.com/triforce/source) | Révision de référence `b0e46adb484681a34ece82bbace9ec085a4eae1f`, extraits pour les tests dans `references/triforce/` | Notices GPL et provenance amont conservées, notamment `references/triforce/host/PROVENANCE.md`. La liaison propre au mod se trouve dans `native/` et son installation dans `native_setup.py`. |

Les dépendances Python gardent leurs licences dans `client/credits/` et `client/websockets/`, dont les notices ainb, evfl et Zstandard. Les dépendances Rust et leurs licences sont fournies dans `moteur/ootrr-ap/vendor/`. Les licences Go et les sources tierces de la DLL se trouvent dans `distribution/sources/` et `native/vendor/`. La bibliothèque Zstandard x64 de l’installateur est accompagnée de `distribution/runtime/LICENSE.txt`.

La licence racine ne remplace aucune licence tierce. Les changements de cette intégration ne doivent pas être attribués aux auteurs des versions amont.

## Visuels

- **Icône Archipelago colorée**, Krista Corkos et Christopher Wilson, 2022 : [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/). `assets/icon.png`, son intégration au titre et le médaillon AP conservent cette attribution. Les adaptations comprennent le redimensionnement, la conversion des textures et la présentation dans le jeu.
- **Lettrage du titre** : rendu typographique réalisé pour ce projet dans `tools/generate_art.py`, avec **Cinzel**, Copyright 2020 The Cinzel Project Authors. La police est sous **SIL Open Font License 1.1**, dont le texte est conservé dans `moteur/ootrr-ap/web/assets/fonts/OFL-Cinzel.txt`. Le lettrage réservé du site Archipelago a été remplacé ; il n’est pas distribué avec cette alpha.
- Les recettes de conversion de texture dérivées de Mozencaz/OotrR conservent leur notice MIT. Les attributions embarquées sont dans `client/credits/Titre-Archipelago.txt` et `Visuels.txt`.

Les visuels ne reçoivent pas une licence GPL uniforme du seul fait d’accompagner le code. Le pack ne contient aucun fichier extrait du jeu Nintendo ; ces fichiers sont fournis localement par le joueur pour générer son mod.
