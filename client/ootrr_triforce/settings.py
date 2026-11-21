"""Public AP settings, shared by the YAML writer and APWorld without AP imports.

Only tracked chest/shop shuffles are exposed. Native item strings remain an
internal seed-file format, so old player files still build with OOTRR 0.8.1.
"""
import copy
import json
import textwrap


def _spec(name, kind, default, description, group, **extra):
    return dict(id=name, kind=kind, default=default, description=description, group=group,
                label=name.replace("_", " ").title(), **extra)


def _choice(name, default, choices, description, group="World"):
    return _spec(name, "choice", default, description, group, choices=tuple(choices))


def _toggle(name, default, description, group="Quality of life"):
    return _spec(name, "toggle", default, description, group)


def _range(name, default, low, high, description, group="Difficulty", step=1):
    return _spec(name, "range", default, description, group, min=low, max=high, step=step)


STARTING_ITEMS = (
    "ocarina", "slingshot", "boomerang", "bow", "bomb_bag", "bombchus", "hookshot", "longshot",
    "megaton_hammer", "lens_of_truth", "magic_meter", "dins_fire", "farores_wind", "nayrus_love",
    "fire_arrows", "ice_arrows", "light_arrows", "iron_boots", "hover_boots", "goron_tunic", "zora_tunic",
    "mirror_shield", "bottle", "magic_beans", "stone_of_agony", "gerudo_card", "goron_bracelet",
    "silver_scale", "adult_wallet", "kokiri_sword", "deku_shield", "big_bullet_bag", "biggest_bullet_bag",
    "big_quiver", "biggest_quiver", "big_bomb_bag", "biggest_bomb_bag", "deku_sticks", "big_stick_bag",
    "biggest_stick_bag", "deku_nuts", "big_nut_bag", "biggest_nut_bag", "silver_gauntlets", "golden_gauntlets",
    "golden_scale", "giant_wallet", "double_magic", "ocarina_of_time", "two_bottles", "three_bottles",
    "four_bottles", "hylian_shield",
)
STARTING_SONGS = (
    "zeldas_lullaby", "eponas_song", "sarias_song", "suns_song", "song_of_time", "song_of_storms",
    "minuet_of_forest", "bolero_of_fire", "serenade_of_water", "requiem_of_spirit", "nocturne_of_shadow",
    "prelude_of_light",
)
SMALL_KEYS = ("vanilla", "dungeon", "any_dungeon", "keysanity")
BOSS_KEYS = ("remove", "vanilla", "dungeon", "regional", "overworld", "any_dungeon", "keysanity")
MAP_COMPASS = ("remove", "startwith", "vanilla", "dungeon", "regional", "any_dungeon", "keysanity")

_BASE_SPECS = (
    _toggle("death_link", False, "Partager les morts avec les autres joueurs DeathLink.", "Archipelago"),
    _toggle("kokiri_shop_checks", False,
            "Ajouter les huit achats uniques de Kokiri aux checks AP, pour les autres joueurs uniquement. "
            "Nécessite une salle avec au moins deux joueurs ; les prix restent natifs.", "Archipelago"),
    _choice("shuffle_chests", "all", ("all", "overworld", "dungeons"),
            "Coffres mélangés : partout, hors donjons ou dans les donjons. Seuls les coffres du catalogue AP "
            "deviennent des checks réseau.", "Shuffle"),
    _choice("shuffle_smallkeys", "dungeon", SMALL_KEYS,
            "Petites clés : emplacement habituel, donjon d'origine, n'importe quel donjon ou partout. "
            "Les deux derniers choix exigent les coffres de donjon mélangés.", "Dungeon items"),
    _choice("shuffle_bosskeys", "dungeon", BOSS_KEYS,
            "Placement des clés de boss. remove donne leur accès dès le début. Les placements hors du "
            "donjon d'origine exigent les coffres de donjon mélangés.", "Dungeon items"),
    _choice("shuffle_ganon_bosskey", "dungeon", BOSS_KEYS,
            "Placement de la clé de Ganon. remove donne l'accès dès le début. Les variantes de récompense "
            "ou de cinématique LACS ne sont pas proposées.", "Dungeon items"),
    _choice("shuffle_mapcompass", "dungeon", MAP_COMPASS,
            "Placement des cartes et boussoles ; remove ou startwith accorde leurs effets dès le début.",
            "Dungeon items"),
    _choice("open_forest", "closed", ("closed", "open"),
            "closed conserve Mido et le départ de la quête ; open ouvre la sortie et l'Arbre Mojo."),
    _choice("open_kakariko", "closed", ("closed", "open"),
            "open ouvre la grille du Mont du Péril et saute la visite à Zelda. Exige open_forest: open ; "
            "la lettre de Zelda et le chant d'Impa sont accordés au départ."),
    _choice("zora_fountain", "closed", ("closed", "open"),
            "Le roi Zora bloque le passage normalement, ou ne le bloque jamais."),
    _toggle("jabu_open", False, "Entrer dans Jabu-Jabu sans poisson, une fois le passage du roi Zora libre.", "World"),
    _toggle("time_always_passes", True, "Le cycle jour/nuit fonctionne dès le début de la partie.", "World"),
    _toggle("early_beds", False, "Dormir jusqu'au matin ou au soir avant Zelda ; exige time_always_passes.", "World"),
    _choice("gerudo_fortress", "normal", ("normal", "fast", "open"),
            "Secourir quatre charpentiers, un seul, ou commencer avec la forteresse ouverte."),
    _choice("door_of_time_condition", "vanilla", ("vanilla", "stones", "song", "open"),
            "Porte du Temps : terminer Dodongo et Jabu-Jabu, posséder les trois pierres, jouer seulement "
            "le Chant du Temps, ou commencer porte ouverte."),
    _choice("door_of_time_escape", "moat", ("vanilla", "stones", "moat"),
            "Avec la porte ouverte ou le Chant seul : la fuite de Zelda attend les deux donjons, les trois "
            "pierres, ou est supprimée avec l'Ocarina dans les douves dès le départ (moat)."),
    _toggle("door_of_time_song", True,
            "Avec les conditions vanilla ou stones, jouer aussi le Chant du Temps pour ouvrir la porte.", "World"),
    _choice("bridge", "vanilla", ("vanilla", "dungeons"),
            "Pont de Ganon : condition native, ou nombre total de pierres et médaillons fixé par bridge_rewards.", "Goal"),
    _range("bridge_rewards", 9, 0, 9,
           "Nombre de pierres et médaillons requis seulement avec bridge: dungeons.", "Goal"),
    _toggle("skip_ganon_trials", False, "Accéder à la tour de Ganon sans terminer les épreuves.", "Goal"),
    _range("trials", 6, 0, 6, "Nombre d'épreuves à terminer si skip_ganon_trials est désactivé.", "Goal"),
    _range("starting_hearts", 3, 1, 20, "Nombre de cœurs au début de la partie.", "Starting inventory"),
    _spec("starting_items", "set", [],
          "Équipement initial natif, retiré du pool local. Pour les améliorations, le plus haut niveau "
          "sélectionné l'emporte. Bombchus exige aussi un sac de bombes ; la lettre de Zelda n'est pas disponible.",
          "Starting inventory", choices=STARTING_ITEMS),
    _spec("starting_songs", "set", [], "Chants connus au départ ; une ocarina reste nécessaire pour les jouer.",
          "Starting inventory", choices=STARTING_SONGS),
    _choice("start_reward", "off", ("off", "stone", "medal", "any"),
            "Commencer avec une pierre ou un médaillon natif aléatoire. La récompense habituelle existe toujours.",
            "Starting inventory"),
    _toggle("faster_chests", False, "Raccourcir les scènes natives de coffres et de remise d'objet."),
    _toggle("faster_blocks", False, "Les blocs à pousser et tirer glissent deux fois plus vite."),
    _toggle("skip_intro", True, "Sauter le film d'ouverture et le réveil dans la maison de Link."),
    _toggle("skip_first_pickup_text", False, "Supprimer le premier texte de ramassage des petits consommables."),
    _choice("skip_cutscenes", "off", ("off", "story", "all"),
            "Déverrouiller le saut des cinématiques : aucun, ouverture/générique, ou aussi les démos du titre.",
            "Quality of life"),
    _toggle("anju_one_cucco", False, "Un seul cocotte suffit pour la bouteille d'Anju ; la logique suit ce réglage."),
    _toggle("big_poe_one", False, "Un seul grand esprit suffit pour la bouteille du marchand d'âmes."),
    _choice("navi_return", "everywhere", ("off", "dungeons", "everywhere"),
            "Navi propose de revenir à l'entrée du donjon, ou aussi à la forêt/au Temple du Temps hors donjons.",
            "Quality of life"),
    _choice("bunny_hood", "off", ("off", "speed", "jump"),
            "Masque du Lapin : effet habituel, course accélérée, ou course et sauts amplifiés. Expérimental.",
            "Quality of life"),
    _toggle("skip_epona_race", True, "Le Chant d'Epona suffit à obtenir Epona, sans course contre Ingo.", "World"),
    _toggle("skip_mask_quest", False, "Tous les masques sont disponibles lorsque la boutique ouvre.", "World"),
    _toggle("plant_beans", False, "Les haricots magiques sont déjà plantés ; leurs plateformes adultes sont disponibles.", "World"),
    _toggle("gerudo_bridge_open", False, "Le pont de la vallée Gerudo est réparé dès le début.", "World"),
    _toggle("deku_bridge_safe", False, "Le pont de la salle du lance-pierre de l'Arbre Mojo ne se casse pas.", "Quality of life"),
    _range("enemy_health", 100, 50, 500, "Vie des ennemis et boss en pourcentage (100 = normale). Expérimental.", step=25),
    _range("enemy_damage", 100, 50, 500, "Dégâts des attaques ennemies en pourcentage ; pièges et chutes inchangés. Expérimental.", step=25),
    _range("enemy_speed", 100, 75, 200, "Vitesse des ennemis en pourcentage ; certaines animations gardent leur rythme. Expérimental.", step=5),
    _range("more_enemies", 100, 100, 1000, "Densité ennemie en pourcentage (100 = normale), avec limites natives par zone. Expérimental.", step=50),
)
_DIFFICULTY = (
    ("enemy_regen", "Les ennemis vivants récupèrent de la vie après dix secondes sans subir de coup."),
    ("enemy_backup", "Certains ennemis appellent un renfort après un combat prolongé."),
    ("no_heart_drops", "Les drops aléatoires ne donnent plus de cœurs de récupération."),
    ("no_gossip_fairies", "Les pierres à potins ne font plus apparaître de fées."),
    ("no_ammo_drops", "Les drops aléatoires ne donnent plus de munitions ; boutiques et coffres restent disponibles."),
    ("lose_heart_on_death", "Perdre un réceptacle après un Game Over, sans descendre sous trois cœurs."),
    ("no_bottles_in_combat", "Interdire l'utilisation des bouteilles pendant la musique de combat."),
    ("no_z_targeting", "Désactiver le verrouillage des ennemis ; les interactions restent utilisables."),
    ("no_dupe_items", "Les captures et recharges natives refusent un contenu déjà présent dans une autre bouteille."),
    ("enemies_respawn_sooner", "Les ennemis ordinaires reviennent après avoir quitté leur salle ou zone."),
    ("boss_minibosses", "Ajouter un mini-boss dans les arènes natives compatibles."),
    ("boss_minions", "Ajouter des ennemis mineurs dans les arènes de boss compatibles."),
    ("bean_pitch", "Le marchand de haricots propose parfois une réplique sur les mods de difficulté."),
    ("zora_ambush", "Ajouter une embuscade de Skulltulas dans les grottes du Domaine Zora."),
    ("enemy_gates", "Bloquer le passage vers l'Arbre Mojo jusqu'à la défaite des deux Babas, forêt fermée seulement."),
    ("cucco_revenge", "Un seul coup sur un cocotte déclenche la revanche de la volaille."),
    ("enemy_spawn_combo", "Autoriser le raccourci natif des deux sticks et de la croix pour invoquer des ennemis d'entraînement."),
    ("fairy_helps_enemies", "Une fée libérée d'une bouteille soigne aussi les ennemis et boss éveillés."),
)
OPTION_SPECS = _BASE_SPECS + tuple(_toggle(name, False, description + " Expérimental.", "Difficulty")
                                  for name, description in _DIFFICULTY)
SPEC_BY_ID = {spec["id"]: spec for spec in OPTION_SPECS}
AP_ONLY = frozenset({"death_link", "kokiri_shop_checks"})

# These are internal constraints, never free-form YAML options. In particular,
# bosses, pots, NPCs and other untracked rewards retain their native sources.
FIXED_SETTINGS = {
    "logic_rules": "glitchless", "starting_age": "child", "triforce_hunt": False,
    "shuffle_pots": "off", "shuffle_crates": "off", "shuffle_rocks": "off", "shuffle_grass": "off",
    "shuffle_beehives": False, "shuffle_freestanding_items": "off", "shuffle_skulltulas": "off",
    "shuffle_scrubs": "off", "shuffle_hideoutkeys": "vanilla", "shuffle_rewards": "off",
    "shuffle_rewards_extra": False, "shuffle_dungeon_rewards": "vanilla", "shuffle_boss_hearts": False,
    "shuffle_songs": "off", "shuffle_ocarinas": False, "shuffle_kokiri_sword": False,
    "shuffle_trade_checks": False, "shuffle_cows": False, "shuffle_cows_other": False,
    "shuffle_frog_songs": False, "shuffle_frog_bug_heart": False, "shuffle_silver_rupees": False,
    "shuffle_potion_shop": False, "shuffle_scrubs_a": False, "shuffle_scrubs_b": False,
    "shuffle_merchants": "off",
    "shuffle_treasure_reward": False, "shuffle_entrances": "off", "bombchus_in_logic": False,
    "gossip_hints": False, "misc_hints": [], "chests_match_contents": False,
}


def default_options():
    """Independent, explicit defaults for every supported public option."""
    return {spec["id"]: copy.deepcopy(spec["default"]) for spec in OPTION_SPECS}


def validate_options(values):
    """Validate public values and combinations before calling the native engine."""
    unknown = set(values).difference(SPEC_BY_ID)
    if unknown:
        raise ValueError("Réglage Archipelago non pris en charge : " + ", ".join(sorted(unknown)))
    result = default_options()
    for name, value in values.items():
        spec = SPEC_BY_ID[name]
        kind = spec["kind"]
        if kind == "toggle":
            if not isinstance(value, (bool, int)) or value not in (False, True):
                raise ValueError(name + " doit être true ou false.")
            value = bool(value)
        elif kind == "choice":
            if value not in spec["choices"]:
                raise ValueError(name + " doit être : " + ", ".join(spec["choices"]))
        elif kind == "range":
            if type(value) is not int or not spec["min"] <= value <= spec["max"]:
                raise ValueError(f"{name} doit être un entier entre {spec['min']} et {spec['max']}.")
            if (value - spec["min"]) % spec["step"]:
                raise ValueError(f"{name} utilise des pas de {spec['step']} depuis {spec['min']}.")
        elif kind == "set":
            if not isinstance(value, (list, tuple, set, frozenset)) or any(item not in spec["choices"] for item in value):
                raise ValueError(name + " contient un objet initial non pris en charge.")
            value = [item for item in spec["choices"] if item in value]
        result[name] = value
    if result["open_kakariko"] == "open":
        if result["open_forest"] != "open":
            raise ValueError("open_kakariko: open exige open_forest: open.")
        if "zeldas_lullaby" in result["starting_songs"]:
            raise ValueError("open_kakariko: open accorde déjà le chant d'Impa ; retire zeldas_lullaby de starting_songs.")
    if result["early_beds"] and not result["time_always_passes"]:
        raise ValueError("early_beds exige time_always_passes: true.")
    if result["bridge"] != "dungeons" and result["bridge_rewards"] != 9:
        raise ValueError("bridge_rewards n'est utilisé qu'avec bridge: dungeons.")
    if result["skip_ganon_trials"] and result["trials"] != 6:
        raise ValueError("trials n'est utilisé que si skip_ganon_trials est false.")
    if result["door_of_time_condition"] in {"open", "song"}:
        if not result["door_of_time_song"]:
            raise ValueError("door_of_time_song n'est utilisé qu'avec la condition vanilla ou stones.")
    elif result["door_of_time_escape"] != "moat":
        raise ValueError("door_of_time_escape n'est utilisé qu'avec la condition open ou song.")
    if result["enemy_gates"] and result["open_forest"] != "closed":
        raise ValueError("enemy_gates exige open_forest: closed.")
    if "bombchus" in result["starting_items"] and not set(result["starting_items"]).intersection(
            {"bomb_bag", "big_bomb_bag", "biggest_bomb_bag"}):
        raise ValueError("Les Bombchus initiaux exigent aussi un sac de bombes dans starting_items.")
    for name in ("shuffle_smallkeys", "shuffle_bosskeys", "shuffle_ganon_bosskey", "shuffle_mapcompass"):
        roaming = result[name] in {"regional", "overworld", "any_dungeon", "keysanity"}
        if roaming and result["shuffle_chests"] == "overworld":
            raise ValueError(name + " exige shuffle_chests: dungeons ou all pour déplacer les objets de donjon.")
        if result[name] == "overworld" and result["shuffle_chests"] == "dungeons":
            raise ValueError(name + ": overworld exige shuffle_chests: all.")
    return result


def engine_settings(values):
    """A typed OOTRR JSON object; a settings string is never needed from players."""
    options = validate_options(values)
    result = copy.deepcopy(FIXED_SETTINGS)
    result.update({name: value for name, value in options.items() if name not in AP_ONLY})
    # The native shop shuffle exports all eight Kokiri shelves and their actual
    # goods/prices. No unrelated shopsanity/deal setting is exposed to AP players.
    result["shuffle_shops"] = "shuffle" if options["kokiri_shop_checks"] else "off"
    return result


def yaml_options(indent="  "):
    """OOTRR-only YAML block; the caller writes the two AP toggles separately."""
    lines = [indent + "# Objectif fixe : vaincre Ganon. Réglages compatibles AP uniquement."]
    previous = None
    for spec in OPTION_SPECS:
        if spec["id"] in AP_ONLY:
            continue
        if spec["group"] != previous:
            lines += ["", indent + "# " + spec["group"]]
            previous = spec["group"]
        lines += [indent + "# " + line for line in textwrap.wrap(spec["description"], width=94)]
        if spec["kind"] in ("choice", "set"):
            lines += [indent + "# " + line for line in textwrap.wrap("Valeurs : " + ", ".join(spec["choices"]), width=94)]
        elif spec["kind"] == "range":
            step = f", pas de {spec['step']}" if spec["step"] > 1 else ""
            lines.append(indent + f"# Entier : {spec['min']} à {spec['max']}{step}.")
        lines.append(indent + spec["id"] + ": " + json.dumps(spec["default"], ensure_ascii=False))
    return "\n".join(lines) + "\n"
