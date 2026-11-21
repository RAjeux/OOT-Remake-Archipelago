# Ocarina of Time Remake × Archipelago

**0.2.0-alpha.1 — intégration native pour Triforce Windows 64 bits.** Le jeu se connecte à la salle Archipelago dès l’écran titre lorsque le mod est actif. Cette alpha utilise OOTRR 0.8.1 et les fichiers du jeu en version 1.1.1.

Les connexions, objets reçus hors ligne, coffres personnels et distants, un achat Kokiri et DeathLink dans les deux sens ont été essayés sur **Triforce 0.6.0**. **Les animations de réception et certains mouvements de caméra restent à améliorer.** Les huit achats Kokiri sont couverts par les tests automatisés ; ils n’ont pas tous été rejoués en jeu. Hookshot et Fritchii ne sont pas pris en charge par cette intégration native.

## Jouer

Télécharge le ZIP Windows dans les [publications du projet](https://github.com/RAjeux/OOT-Remake-Archipelago/releases) et extrais-le entièrement. Il faut :

- Windows 64 bits et Triforce, avec ses outils de construction compatibles ;
- ta propre extraction du jeu **1.1.1**, avec son dossier `romfs`, et **OOTRR portable 0.8.1** ;
- **Python 3.11 ou plus récent** et **Node.js 22 ou 24** ;
- une salle Archipelago générée avec l’APWorld fourni. La version de référence du serveur est **Archipelago 0.6.7**.

1. Sur la machine qui génère la salle, installe `ootrr_remake.apworld` dans Archipelago. Prépare ton YAML avec `Creer-YAML.cmd` ou les fichiers d’[exemple](exemples/), puis génère la salle avec les YAML des autres joueurs.
2. Sur le PC de Zelda, lance `Configurer-le-mod-Archipelago.cmd` et choisis ton fichier joueur `.apootrr`, les dossiers demandés et l’adresse du serveur. Le programme prépare le mod et son profil de salle.
3. Active **Archipelago** dans Triforce Setup, puis reconstruis le jeu avec l’action **Build again**. Cette reconstruction est nécessaire au premier usage et après un remplacement des outils du port.
4. Lance ensuite Zelda normalement depuis Triforce. La console de configuration peut être fermée. `Observer-Archipelago.cmd` permet de consulter l’état de la connexion et les notifications.

Le [guide joueur](distribution/Guide.txt) détaille l’installation, les mises à jour et les vérifications. Aucun fichier du jeu n’est fourni dans ce dépôt ou dans le pack.

## Ce que fait le mod

Un coffre destiné à Zelda montre et donne l’objet natif assigné par Archipelago. Un coffre destiné à un autre joueur montre son médaillon AP et transmet son objet. L’ancienne récompense du coffre n’est pas ajoutée en supplément.

Les emplacements réseau se limitent aux coffres du catalogue et, si l’option est activée, aux huit achats Kokiri. Certaines récompenses locales hors AP, notamment les pièces de cœur, conservent le traitement d’OOTRR. Leur présence hors du réseau ne garantit donc pas un comportement identique au jeu non modifié.

Les objets venant d’autres mondes sont remis dans l’ordre, en partie active, avec les effets du jeu. Les objets envoyés pendant la fermeture de Zelda restent sur le serveur et sont repris après reconnexion. Le gain et son compteur de réception sont enregistrés ensemble ; sauvegarde avant de quitter normalement la partie.

`kokiri_shop_checks: true` ajoute huit achats uniques à la boutique Kokiri. Ils vendent des objets pour les autres joueurs, au prix de la seed OOTRR. Le paiement et l’état épuisé utilisent les mécanismes du jeu. `death_link: true` partage les morts avec les autres participants DeathLink ; une mort distante attend la fin d’un événement actif, notamment un achat ou une réception.

Le YAML expose les réglages OOTRR pris en charge par l’APWorld, avec leurs valeurs et descriptions. Les options absentes ne doivent pas être ajoutées en supposant qu’elles sont compatibles : certains réglages du randomizer local ne correspondent pas encore aux emplacements et à la logique AP.

Les nouvelles salles utilisent `reward_mode: all_locations`, `local_items: true` et `items_handling=5` : les objets personnels sont accordés physiquement, le réseau fournit les objets distants et l’inventaire initial. Les anciennes salles `all_chest_rewards` ou `legacy_gear` conservent leur protocole `7`. Il faut générer une nouvelle salle pour changer de mode, sans modifier manuellement les drapeaux d’une salle existante.

## Développer

Le client Python se trouve dans `client/`, l’APWorld dans `apworld/`, la liaison native dans `native/` et le moteur Rust adapté dans `moteur/ootrr-ap/`. Les noms de package historiques `ootrr_triforce` et `nx2navi` sont conservés en interne.

| Partie | Fichiers principaux |
| --- | --- |
| Options, logique AP et fichier joueur | `apworld/ootrr_remake/`, `client/ootrr_triforce/catalog.py` |
| Préparation et installation | `player.py`, `native_setup.py`, `install_mod.py` dans `client/ootrr_triforce/` |
| Connexion, objets, checks et DeathLink | `native/client.go`, `game.go`, `deathlink.go` |
| Liaison au gameplay Triforce | `native/ootrr_archipelago.inc`, `ootrr_ap_items.inc` |
| Coffres, médaillons, réceptions et boutiques | `medallions.py`, `receipt_events.py`, `shop_events.py`, `ap_shops.py` dans `client/ootrr_triforce/` |
| Moteur OOTRR et génération | `moteur/ootrr-ap/randomizer/core/src/bin/ootrr_ap.rs`, `slice/generate.rs` |
| Ressources et formats du jeu | `client/oot_rando/` |
| Vérifications | `tests/`, `tests/fixtures/`, `tools/test.py` |

### Construire le pack

Depuis la racine, sous Windows :

```powershell
py -3 tools/build.py
py -3 tools/verify_release.py --version 0.2.0-alpha.1
```

Le résultat est `dist/Archipelago-OOT-Remake-0.2.0-alpha.1.zip`, avec le client `.pyz`, l’APWorld et leurs sources. La version du pack est déclarée dans `VERSION`. L’assemblage par défaut utilise la DLL et le moteur WebAssembly fournis et ne télécharge rien. Il ne reconstruit pas le jeu Triforce.

Pour reconstruire les composants fournis :

- `py -3 tools/build.py --native` : Go, un compilateur C x64 compatible cgo et `CGO_ENABLED=1`. `CC` peut indiquer le compilateur. Il faut ensuite réinstaller le mod et reconstruire Triforce avec la nouvelle empreinte de DLL.
- `py -3 tools/build.py --engine` : Rust compatible avec la cible `wasm32-wasip1` installée. Cette copie a été compilée avec **Rust 1.99.0** ; les dépendances sont fournies dans `moteur/ootrr-ap/vendor/`.

Les tables se vérifient avec `tools/check_catalog.py` et se régénèrent avec `tools/generate_item_header.py`. `tools/generate_art.py` régénère les données du titre à partir des visuels du dépôt. Le manifeste de référence d’une nouvelle version se crée avec `tools/verify_release.py --version <version> --record-reference`, après validation du contenu ; les anciens manifestes restent des références historiques.

### Exécuter les tests

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe tools/test.py
```

La suite assemble le pack puis vérifie la génération, les ressources et les graphes d’événements avec des données synthétiques. Node.js est nécessaire aux tests du moteur. `--c` ajoute les tests de liaison gameplay sur un modèle C, avec GCC ou Clang disponible via `PATH` ou `CC`.

Les tests réseau utilisent un vrai serveur Archipelago temporaire sur la machine locale :

```powershell
$env:AP_SERVER = 'C:\ProgramData\Archipelago\ArchipelagoServer.exe'
.\.venv\Scripts\python.exe tools/test.py --c --network
```

Adapte le chemin, ou utilise `AP_SOURCE` pour un dépôt Archipelago avec ses dépendances installées. Sous Windows, les tests chargent la DLL fournie dans un processus de test ; sous Linux, ils construisent son équivalent avec Go et C. Tk et libzstd sont également nécessaires sous Linux. Les tests couvrent l’historique après arrêt complet, la reconnexion, le mode `5` sans doublon des objets personnels et DeathLink, y compris son report pendant un événement. Les tests Go se lancent depuis `native/` avec `go test -mod=vendor ./...`.

Les salles de `tests/fixtures/` sont dédiées aux régressions locales. Les états de vie des tests sont simulés : ces contrôles ne remplacent pas une vérification des animations, de l’inventaire et de la mort de Link dans le jeu.

## Licences et crédits

Le code d’intégration est distribué sous **GPL-3.0-or-later**, avec les licences propres aux composants tiers. Les visuels Archipelago conservent leurs conditions distinctes, dont **CC BY-NC 4.0** pour l’icône colorée et ses adaptations. Le lettrage du titre est rendu pour ce projet avec la police Cinzel sous OFL 1.1. Voir [LICENSE](LICENSE), [NOTICE](NOTICE) et [REFERENCES.md](REFERENCES.md).
