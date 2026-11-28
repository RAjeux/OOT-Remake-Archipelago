# Installation rapide en français

[Guide complet en anglais](INSTALLATION.md) · [Compatibilité](PORT-COMPATIBILITY.md) · [Mises à jour](UPDATING.md)

## Le bon téléchargement

**[Télécharger le launcher Windows 0.10.4-alpha.8](https://github.com/RAjeux/OOT-Remake-Archipelago/releases/download/v0.10.4-alpha.8/OOT-Remake-Archipelago-0.10.4-alpha.8.exe)** · [Page de cette release](https://github.com/RAjeux/OOT-Remake-Archipelago/releases/tag/v0.10.4-alpha.8)

Un seul EXE suffit : le client AP, Python, Node.js et l'APWorld sont inclus. Le builder OOTRR compatible est téléchargé au premier besoin.

**Les anciennes versions 0.11/0.12 « Full » sont une expérimentation abandonnée.** Leur numéro plus élevé ne signifie pas qu'il faut les choisir. Leurs fichiers joueur ne sont pas convertis : exporte un nouveau YAML avec l'éditeur actuel, génère une nouvelle salle avec l'APWorld actuel et conserve les anciennes sauvegardes séparément. Les salles de la branche native 0.10 restent prises en charge.

## Rôles et fichiers

| Fichier | Utilisation |
| --- | --- |
| `.yaml` | Tes réglages avant la génération. Tu l'envoies à l'organisateur. |
| `ootrr_remake.apworld` | L'intégration installée dans Archipelago sur le PC qui génère la salle. Le launcher l'installe avec son bouton **Installer l'APWorld**. |
| `.apootrr` | Ton fichier Zelda créé après génération, pour ton joueur et ta salle. Tu le sélectionnes dans **Configurer une salle**. |

Chaque joueur choisit ses réglages et transmet son YAML. Un organisateur rassemble les YAML, génère la salle avec Archipelago et l'héberge. Il remet ensuite à chaque joueur Zelda **son `.apootrr`**, l'adresse de la salle et le mot de passe éventuel.

Si tu rejoins une salle déjà générée, tu n'as pas besoin d'installer Archipelago ou un APWorld séparément sur ton PC.

## Avant de jouer

Il faut Windows x64, tes propres fichiers du jeu en **version 1.1.1**, et une installation fonctionnelle de **Triforce avec ses outils de compilation**. Commence par [l'installation officielle de Triforce](https://triforceproject.com/#install) et vérifie que le jeu de base se lance. Le mod ne fournit aucun fichier du jeu.

L'intégration a été vérifiée au démarrage et en reconnexion avec Triforce **0.8.3**. Hookshot **3.0.1** est une alternative expérimentale qui exige ses outils d'origine et les fichiers de compilation conservés ; les autres révisions sont refusées. Fritchii n'a pas de backend AP pour les objets et les checks. Consulte la [compatibilité et les limites des tests](PORT-COMPATIBILITY.md).

## Choisir tes réglages avant la génération

1. Ouvre le launcher, puis **Créer un YAML** (*Create YAML*).
2. Saisis un nom de joueur unique dans le groupe.
3. Ouvre **Choisir les réglages…** (*Choose settings…*), sélectionne tes options, puis applique-les. DeathLink se règle aussi ici.
4. **Enregistre le YAML** (*Save YAML*) et envoie-le à l'organisateur.

Le launcher et les descriptions suivent la langue connue du jeu ; les clés YAML restent identiques. Modifier le YAML après génération ne change pas une salle existante.

## Pour l'organisateur

Installe [Archipelago officiel](https://github.com/ArchipelagoMW/Archipelago/releases), version **0.6.7 minimum** ; la génération est testée en **0.6.8**. Dans le launcher OOT Remake, utilise **Installer l'APWorld** (*Install APWorld*) et sélectionne le dossier d'Archipelago, avec le compte Windows qui générera la salle. L'action installe aussi le runtime de génération. Redémarre Archipelago.

Rassemble les YAML des joueurs et génère **en local** : cet APWorld custom n'est pas inclus dans le générateur du site public. Héberge ensuite le résultat en local ou sur le site d'Archipelago. Envoie à chaque joueur Zelda son `.apootrr` et les informations de connexion. Les [étapes détaillées](INSTALLATION.md#organizer-generate-and-host) et le [guide officiel Archipelago](https://archipelago.gg/tutorial/Archipelago/setup_en) expliquent cette partie.

## Configurer et lancer ta partie

Termine la mise à jour éventuelle du port, puis ferme Zelda et son application de compilation avant la préparation.

1. Ouvre **Configurer une salle** (*Set up a room*).
2. Sélectionne **ton `.apootrr`**, puis le port du jeu. Indique le dossier du jeu s'il n'a pas été détecté.
3. Entre l'adresse donnée par l'organisateur et le mot de passe seulement s'il en existe un.
4. Choisis **Installer et préparer** (*Install and prepare*) et attends la fin de la préparation et de la compilation éventuelle.
5. Choisis **Jouer** (*Play*). La connexion démarre dès l'écran titre. Crée une sauvegarde dédiée pour une nouvelle salle ; reprends celle de la salle si tu continues une partie native 0.10 existante.

Pour les sessions suivantes, ouvre le même launcher et clique sur **Jouer**. Tu peux fermer le launcher pendant que Zelda tourne. Le bouton **Connexion** (*Connection*) et le menu AP du jeu permettent ensuite de changer l'adresse ou le mot de passe.

`127.0.0.1:38281` désigne un serveur sur ton propre PC. Pour une salle distante, utilise l'adresse exacte de l'organisateur. Lance un seul port à la fois pour le même joueur AP.

## Sauvegardes, mises à jour et aide

Les données sont conservées dans `%LOCALAPPDATA%\OOTRR-Archipelago`, indépendamment de l'EXE. Hookshot possède un espace séparé : changer de port ne transfère pas la sauvegarde.

Après une mise à jour réussie, le launcher porte le nom de la version téléchargée dans le même dossier. L'ancien EXE est conservé dans les données privées de mise à jour, sans rester à côté du nouveau. Un raccourci que tu avais créé vers l'ancien nom peut devoir être modifié. La version 0.10.4-alpha.8 corrige les remises de récompenses de Talon et de la boutique de potions, ainsi que les médaillons et pierres invisibles pendant leur animation. Ferme Zelda et prépare le même fichier joueur si le launcher le demande : tu conserves ta salle, tes réglages, tes objets et tes sauvegardes. Les correctifs précédents de préparation, des coffres, des modèles et du démarrage sont inclus.

Tu peux continuer une salle native 0.10 avec son `.apootrr` et sa sauvegarde après avoir mis le launcher à jour. Si une préparation est demandée, ferme Zelda et prépare **le même fichier joueur compatible** : ses réglages, checks et placements restent identiques.

Pour les nouveaux réglages et checks de 0.10.4, l'organisateur doit installer l'APWorld correspondant, redémarrer Archipelago et générer une nouvelle salle. Utilise alors son nouveau `.apootrr` et une sauvegarde dédiée. Mettre le launcher ou l'APWorld à jour ne transforme pas une salle existante. Hookshot reste expérimental ; Longshot n'est pas proposé comme port pris en charge.

**Aide → Ouvrir le journal** (*Help → Open log*) donne les détails d'une erreur. Pour un signalement, précise les versions du launcher et du port ainsi que l'étape qui échoue. Vérifie les noms de participants dans les logs avant de les publier ; ne joins pas de fichiers du jeu ou de sauvegarde. Le projet reste en alpha et ses limites de validation sont documentées.
