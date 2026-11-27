"""Presentation for the public settings schema; identifiers remain language independent."""
from functools import lru_cache
from importlib import resources
import json
import re

from .settings import OPTION_SPECS, SPEC_BY_ID
from .feature_settings import QUARANTINED_DEFAULTS


LABELS = {
    "death_link": ("DeathLink", "DeathLink"),
    "shops_always_open": ("Shops open day and night", "Boutiques ouvertes jour et nuit"),
    "shuffle_chests": ("Chests", "Coffres"),
    "shuffle_shops": ("Shop purchases", "Achats en boutique"),
    "shuffle_skulltulas": ("Gold Skulltulas", "Skulltulas d'or"),
    "shuffle_smallkeys": ("Small keys", "Petites clés"),
    "shuffle_bosskeys": ("Boss keys", "Clés des boss"),
    "shuffle_ganon_bosskey": ("Ganon's Boss Key", "Clé du boss de Ganon"),
    "shuffle_mapcompass": ("Maps and compasses", "Cartes et boussoles"),
    "open_forest": ("Deku Tree and forest access", "Accès à l'Arbre Mojo et sortie de la forêt"),
    "open_kakariko": ("Death Mountain gate", "Grille du mont du Péril"),
    "zora_fountain": ("King Zora's passage", "Passage du roi Zora"),
    "jabu_open": ("Enter Jabu-Jabu without a fish", "Entrer dans Jabu-Jabu sans poisson"),
    "time_always_passes": ("Day/night cycle from the start", "Cycle jour/nuit dès le départ"),
    "early_beds": ("Use beds before meeting Zelda", "Dormir avant de rencontrer Zelda"),
    "gerudo_fortress": ("Gerudo Fortress", "Forteresse Gerudo"),
    "door_of_time_condition": ("Door of Time requirement", "Condition de la porte du Temps"),
    "door_of_time_escape": ("Zelda's escape", "Fuite de Zelda"),
    "door_of_time_song": ("Also require the Song of Time", "Exiger aussi le Chant du Temps"),
    "bridge": ("Ganon's bridge requirement", "Condition du pont de Ganon"),
    "bridge_rewards": ("Rewards required for the bridge", "Récompenses requises pour le pont"),
    "skip_ganon_trials": ("Skip Ganon's trials", "Passer les épreuves de Ganon"),
    "trials": ("Number of trials", "Nombre d'épreuves"),
    "starting_hearts": ("Starting hearts", "Cœurs au départ"),
    "starting_items": ("Starting equipment", "Équipement initial"),
    "starting_songs": ("Starting songs", "Chants connus au départ"),
    "start_reward": ("Extra starting dungeon reward", "Récompense de donjon supplémentaire au départ"),
    "faster_chests": ("Faster chest and item scenes", "Animations de coffre et d'objet plus rapides"),
    "faster_blocks": ("Faster block pushing", "Déplacer les blocs plus vite"),
    "skip_intro": ("Skip introduction automatically", "Passer automatiquement l'introduction"),
    "skip_first_pickup_text": ("Hide first small-pickup message", "Masquer le premier message des petits objets"),
    "skip_cutscenes": ("Manual cutscene skipping", "Saut manuel des cinématiques"),
    "anju_one_cucco": ("One Cucco for Anju", "Une seule cocotte pour Anju"),
    "big_poe_one": ("One Big Poe for the bottle", "Un seul Grand Esprit pour la bouteille"),
    "navi_return": ("Navi's return shortcut", "Raccourci de retour de Navi"),
    "bunny_hood": ("Bunny Hood effect", "Effet du Masque du Lapin"),
    "skip_epona_race": ("Skip Epona's race", "Passer la course d'Epona"),
    "skip_mask_quest": ("Skip the mask trading quest", "Passer la quête des masques"),
    "plant_beans": ("Beans already planted", "Haricots déjà plantés"),
    "gerudo_bridge_open": ("Gerudo bridge already repaired", "Pont Gerudo déjà réparé"),
    "deku_bridge_safe": ("Stable Deku Tree bridge", "Pont stable dans l'Arbre Mojo"),
    "enemy_health": ("Enemy health (%)", "Vie des ennemis (%)"),
    "enemy_damage": ("Enemy damage (%)", "Dégâts des ennemis (%)"),
    "enemy_speed": ("Enemy speed (%)", "Vitesse des ennemis (%)"),
    "more_enemies": ("Enemy density (%)", "Densité des ennemis (%)"),
    "shuffle_pots": ("Pots", "Pots"),
    "shuffle_crates": ("Crates", "Caisses"),
    "shuffle_rocks": ("Rocks", "Rochers"),
    "shuffle_grass": ("Grass", "Herbes"),
    "shuffle_beehives": ("Beehives", "Ruches"),
    "shuffle_freestanding_items": ("Ground pickups and heart pieces", "Objets au sol et quarts de cœur"),
    "shuffle_rewards": ("NPC, fairy and minigame rewards", "Récompenses des PNJ, fées et mini-jeux"),
    "shuffle_rewards_extra": ("Extra NPC rewards", "Récompenses supplémentaires des PNJ"),
    "shuffle_boss_hearts": ("Boss heart containers", "Réceptacles de cœur des boss"),
    "shuffle_songs": ("Song lessons", "Apprentissage des chants"),
    "shuffle_potion_shop": ("Potion Shop rewards", "Récompenses de l'apothicaire"),
    "adult_trade_shuffle": ("Adult trading quest", "Échanges de la quête adulte"),
    "shuffle_scrubs_a": ("Deku Scrubs: Woods and Crater", "Pestes : Bois Perdus et cratère"),
    "shuffle_scrubs_b": ("Deku Scrubs: Jabu and rear grotto", "Pestes : Jabu et fond de la grotte"),
    "shuffle_cows": ("Cows", "Vaches"),
    "shuffle_treasure_reward": ("Treasure Chest Game heart piece", "Quart de cœur de la chasse aux trésors"),
    "shuffle_dungeon_rewards": ("Spiritual Stones and Medallions", "Pierres ancestrales et médaillons"),
    "shuffle_frog_songs": ("Frog song rewards", "Récompenses des chants des grenouilles"),
    "shuffle_frog_bug_heart": ("Frog bug game heart piece", "Quart de cœur du jeu des insectes des grenouilles"),
    "shuffle_ocarinas": ("Ocarinas", "Ocarinas"),
    "shuffle_kokiri_sword": ("Kokiri Sword", "Épée Kokiri"),
    "shuffle_master_sword": ("Master Sword", "Épée de Légende"),
    "shuffle_entrances": ("Dungeon entrances", "Entrées des donjons"),
    "shuffle_merchants": ("Merchants", "Marchands"),
    "shopsanity_prices": ("Special-deal wallet tier", "Bourse requise pour les offres spéciales"),
    "scrub_prices": ("Deku Scrub prices", "Prix des pestes marchandes"),
    "scrub_price_fixed": ("Fixed Deku Scrub price", "Prix fixe des pestes marchandes"),
    "scrub_hint_text": ("Reveal Deku Scrub offers", "Afficher les objets des pestes marchandes"),
    "merchant_prices": ("Merchant prices", "Prix des marchands"),
    "merchant_price_fixed": ("Fixed merchant price", "Prix fixe des marchands"),
    "fairy_prices": ("Great Fairy offerings", "Offrandes aux Grandes Fées"),
    "fairy_price_fixed": ("Fixed Great Fairy offering", "Offrande fixe aux Grandes Fées"),
    "lacs_rewards": ("Rewards required at the Light Arrows scene", "Récompenses requises pour la scène des Flèches de Lumière"),
    "song_harp_colors": ("Song-colored pickup harps", "Harpes de ramassage aux couleurs des chants"),
    "enemy_regen": ("Enemy health regeneration", "Régénération des ennemis"),
    "enemy_backup": ("Enemy reinforcements", "Renforts ennemis"),
    "no_heart_drops": ("No recovery-heart drops", "Aucun cœur de soin dans les butins"),
    "no_gossip_fairies": ("No fairies from gossip stones", "Aucune fée des pierres à potins"),
    "no_ammo_drops": ("No ammunition drops", "Aucune munition dans les butins"),
    "lose_heart_on_death": ("Lose a heart container on death", "Perdre un réceptacle de cœur en mourant"),
    "no_bottles_in_combat": ("No bottles during combat", "Pas de bouteille en combat"),
    "no_z_targeting": ("Disable enemy targeting", "Désactiver le ciblage des ennemis"),
    "no_dupe_items": ("No duplicate bottle contents", "Pas de contenu de bouteille en double"),
    "enemies_respawn_sooner": ("Enemies respawn sooner", "Réapparition plus rapide des ennemis"),
    "boss_minibosses": ("Minibosses in boss arenas", "Mini-boss dans les arènes des boss"),
    "boss_minions": ("Extra enemies in boss arenas", "Ennemis supplémentaires chez les boss"),
    "bean_pitch": ("Bean Seller difficulty dialogue", "Dialogue de difficulté du vendeur de haricots"),
    "zora_ambush": ("Zora's Domain Skulltula ambush", "Embuscade de Skulltulas au domaine Zora"),
    "enemy_gates": ("Combat gates on overworld paths", "Barrières de combat sur les chemins"),
    "cucco_revenge": ("Cucco attack after one hit", "Attaque des cocottes dès le premier coup"),
    "enemy_spawn_combo": ("Practice-enemy input shortcut", "Raccourci pour faire apparaître des ennemis d'entraînement"),
    "fairy_helps_enemies": ("Released fairies also heal enemies", "Les fées libérées soignent aussi les ennemis"),
}

LABELS.update({
    "nocturne_trigger": ("Nocturne requirement", "Condition du Nocturne"),
    "prelude_trigger": ("Prelude requirement", "Condition du Prélude"),
    "bridge_medallions": ("Medallions needed for the bridge", "Médaillons requis pour le pont"),
    "lacs_medallions": ("Medallions needed for Zelda's key", "Médaillons requis pour la clé de Zelda"),
    "skulls_by_day": ("Night Skulltulas also appear by day", "Skulltulas nocturnes présentes aussi le jour"),
    "night_skulls_suns_song": ("Require Sun's Song for night Skulltulas", "Exiger le Chant du Soleil pour les Skulltulas nocturnes"),
    "free_scarecrow": ("Scarecrow without the child song lesson", "Épouvantail sans la leçon enfant"),
    "skip_tower_escape": ("Skip the tower escape", "Passer la fuite de la tour"),
    "skip_area_intros": ("Skip first-visit area camera tours", "Passer les présentations des zones"),
    "dungeon_key_tracker": ("Dungeon key information", "Informations sur les clés de donjon"),
    "dpad_gear_cycle": ("Cycle masks and boots with the D-pad", "Changer de masque et de bottes avec la croix"),
    "fishing_any_fish": ("Fishing prizes for any fish", "Récompenses de pêche avec n'importe quel poisson"),
    "faster_ocarina_minigame": ("Shorter Skull Kids' memory game", "Jeu de mémoire des Skull Kids raccourci"),
    "dampe_one_race": ("Both Dampe prizes in one race", "Deux récompenses d'Igor en une course"),
    "dampe_first_dig": ("Dampe's first correct dig wins", "Récompense au premier bon trou d'Igor"),
    "disable_low_health_warnings": ("Silence low-health warnings", "Désactiver les alertes de vie faible"),
    "owl_warps": ("Reusable owl rides", "Voyages répétés avec le hibou"),
    "starting_bunny_hood": ("Start with the Bunny Hood", "Commencer avec le Masque du Lapin"),
    "shuffle_ice_traps": ("Mix Ice Traps into the item pool", "Ajouter des pièges de glace au mélange"),
    "ice_trap_count": ("Number of Ice Traps", "Nombre de pièges de glace"),
    "cosmetic_color_mode": ("Colour mode", "Mode des couleurs"),
    "cosmetic_colors": ("Individual colours", "Couleurs détaillées"),
    "shuffle_music": ("Music shuffle", "Mélange des musiques"),
    "shuffle_sfx": ("Sound-effect shuffle", "Mélange des effets sonores"),
    "item_plando": ("Planned local placements", "Placements d'objets choisis"),
    "damage_taken": ("Global damage taken", "Dégâts subis globaux"),
    "enemy_sizes": ("Random enemy sizes", "Tailles aléatoires des ennemis"),
    "enemy_sizes_health": ("Health follows random enemy size", "Vie liée à la taille aléatoire des ennemis"),
    "shorter_timers": ("Shorter challenge timers", "Chronomètres des défis raccourcis"),
    "unbreakable_bowling_grass": ("Unbreakable Bombchu Bowling obstacles", "Obstacles indestructibles au bowling Teigneux"),
    "harder_talon_cuccos": ("Harder Super Cucco game", "Jeu des super cocottes plus difficile"),
    "fireball_storms": ("Falling fire-rock storms", "Pluies de rochers enflammés"),
    "volvagia_roams": ("Volvagia in adult Hyrule Field", "Volcania dans la plaine d'Hyrule adulte"),
    "mega_like_likes": ("Giant Like Likes", "Like Likes géants"),
    "random_fuses": ("Random explosive fuses", "Mèches d'explosifs aléatoires"),
    "enemy_randomizer": ("Shuffle supported enemy types", "Mélanger les types d'ennemis pris en charge"),
})

GROUPS = {
    "Archipelago": "Archipelago", "Shuffle": "Mélange", "Dungeon items": "Objets de donjon",
    "World": "Monde", "Goal": "Objectif", "Starting inventory": "Inventaire initial",
    "Quality of life": "Confort", "Difficulty": "Difficulté", "Economy": "Économie",
    "Cosmetics": "Apparence et sons", "Planned placements": "Placements choisis",
}

# Display order and visibility only: the single public schema still owns every
# value, default and validation rule used by the editor and APWorld.
GROUP_ORDER = ("Archipelago", "Shuffle", "Dungeon items", "World", "Goal", "Economy",
               "Starting inventory", "Quality of life", "Cosmetics", "Planned placements", "Difficulty")
ESSENTIAL_SETTINGS = frozenset({
    "death_link", "shops_always_open", "shuffle_chests", "shuffle_shops", "shuffle_skulltulas",
    "shuffle_freestanding_items", "shuffle_rewards", "shuffle_songs", "shuffle_dungeon_rewards",
    "adult_trade_shuffle", "shuffle_master_sword", "shuffle_smallkeys", "shuffle_bosskeys",
    "shuffle_ganon_bosskey", "shuffle_mapcompass", "open_forest", "open_kakariko",
    "door_of_time_condition", "shuffle_entrances", "bridge", "bridge_rewards",
    "skip_ganon_trials", "trials", "starting_hearts", "starting_items", "skip_intro", "navi_return",
})


def is_advanced(name):
    """Whether a control starts under Advanced; this never changes its value."""
    if name not in SPEC_BY_ID:
        raise KeyError(name)
    return name not in ESSENTIAL_SETTINGS

CHOICES = {
    "off": ("Off", "Désactivé"), "all": ("All", "Tout"),
    "overworld": ("Overworld", "Monde extérieur"), "dungeons": ("Dungeons", "Donjons"),
    "dungeon": ("Own dungeon", "Donjon d'origine"), "any_dungeon": ("Any dungeon", "Tous les donjons"),
    "keysanity": ("Anywhere", "Partout"), "vanilla": ("Original game", "Jeu d'origine"),
    "regional": ("Own region", "Région d'origine"), "startwith": ("Granted at the start", "Disponibles dès le départ"),
    "remove": ("Remove the requirement", "Supprimer le prérequis"),
    "closed": ("Closed", "Fermé"), "open": ("Open from the start", "Ouvert dès le départ"),
    "normal": ("Four carpenters", "Quatre ouvriers"), "fast": ("One carpenter", "Un ouvrier"),
    "stones": ("Three Spiritual Stones", "Trois pierres ancestrales"), "song": ("Song of Time only", "Chant du Temps seul"),
    "moat": ("Skip; Ocarina in the moat", "Passer ; ocarina dans les douves"),
    "stone": ("Spiritual Stone", "Pierre ancestrale"), "medal": ("Medallion", "Médaillon"),
    "any": ("Stone or Medallion", "Pierre ou médaillon"),
    "everywhere": ("Dungeons and overworld", "Donjons et monde extérieur"),
    "speed": ("Faster running", "Course plus rapide"), "jump": ("Faster running and higher jumps", "Course rapide et sauts améliorés"),
    "supported": ("Enabled", "Activé"), "own": ("Song lessons only", "Chants entre eux"),
    "anywhere": ("Anywhere", "Partout"), "beans": ("Beans only", "Haricots seulement"),
    "no_beans": ("Other merchants, no beans", "Autres marchands, sans haricots"),
    "shuffle": ("Shuffle ordinary goods", "Mélanger les marchandises ordinaires"),
    "random": ("0–4 special deals per shop", "0 à 4 offres spéciales par boutique"),
    "affordable": ("Affordable", "Abordables"), "starting": ("Starting wallet", "Bourse initiale"),
    "adult": ("Adult's Wallet", "Bourse d'adulte"), "giant": ("Giant's Wallet", "Bourse de géant"),
    "cheap": ("Low random prices (0–95)", "Petits prix aléatoires (0–95)"), "fixed": ("Fixed amount below", "Montant fixe ci-dessous"),
    "pinned": ("44-site subset", "Sélection de 44"), "matched": ("All 100 native sites", "Tous les 100"),
    "lacs_dungeons": ("Light Arrows scene: reward count", "Scène des Flèches de Lumière : nombre de récompenses"),
}
for _count in range(1, 5):
    CHOICES["deals_" + str(_count)] = (f"{_count} special deals per shop", f"{_count} offres spéciales par boutique")

CHOICE_OVERRIDES = {
    ("damage_taken", "normal"): ("Normal damage", "Dégâts normaux"),
    ("damage_taken", "double"): ("Double damage", "Dégâts doublés"),
    ("damage_taken", "quadruple"): ("Quadruple damage", "Dégâts quadruplés"),
    ("damage_taken", "one_hit"): ("One-hit knockout", "Un coup mortel"),
    ("enemy_sizes", "mild"): ("Moderate size changes", "Variations de taille modérées"),
    ("enemy_sizes", "wild"): ("Large size changes", "Grandes variations de taille"),
    ("shorter_timers", "three_quarters"): ("75% of normal time", "75 % du temps normal"),
    ("shorter_timers", "half"): ("50% of normal time", "50 % du temps normal"),
    ("cosmetic_color_mode", "off"): ("Original colours", "Couleurs d'origine"),
    ("cosmetic_color_mode", "custom"): ("Individual picks below", "Choix détaillés ci-dessous"),
    ("cosmetic_color_mode", "random"): ("Random colour for each part", "Une couleur aléatoire par élément"),
    ("cosmetic_color_mode", "shared"): ("Shades of one random hue", "Nuances d'une teinte aléatoire"),
    ("shuffle_music", "grouped"): ("Shuffle within music categories", "Mélanger par catégorie musicale"),
    ("shuffle_music", "anywhere"): ("Mix music categories", "Mélanger les catégories musicales"),
    ("shuffle_sfx", "grouped"): ("Shuffle similar sounds", "Mélanger les sons similaires"),
    ("shuffle_sfx", "anywhere"): ("Mix sound categories", "Mélanger les catégories de sons"),
    ("nocturne_trigger", "vanilla"): ("Clear Forest, Fire and Water Temples", "Terminer les temples de la Forêt, du Feu et de l'Eau"),
    ("nocturne_trigger", "classic"): ("Hold the Forest, Fire and Water Medallions", "Posséder les médaillons de la Forêt, du Feu et de l'Eau"),
    ("prelude_trigger", "vanilla"): ("Clear Forest Temple", "Terminer le temple de la Forêt"),
    ("prelude_trigger", "classic"): ("Hold the Forest Medallion", "Posséder le médaillon de la Forêt"),
    ("bridge", "medallions"): ("Count Medallions only", "Compter seulement les médaillons"),
    ("shuffle_ganon_bosskey", "lacs_medallions"): ("Zelda's key: Medallion count", "Clé de Zelda : nombre de médaillons"),
    ("skip_cutscenes", "off"): ("Native manual skipping", "Saut manuel d'origine"),
    ("skip_cutscenes", "story"): ("Opening and credits", "Introduction et générique"),
    ("skip_cutscenes", "all"): ("Also title-screen demos", "Inclure les démonstrations du titre"),
    ("shuffle_freestanding_items", "off"): ("Heart pieces (default)", "Quarts de cœur (par défaut)"),
    ("shuffle_freestanding_items", "pieces"): ("Heart pieces (same as Off)", "Quarts de cœur (identique à Off)"),
    ("bridge", "dungeons"): ("Count Stones and Medallions", "Compter les pierres et médaillons"),
    ("shuffle_dungeon_rewards", "dungeons"): ("Dungeon reward checks only", "Récompenses de fin de donjon seulement"),
}

STARTING_LABELS = {
    "hookshot": ("Hookshot", "Grappin"), "longshot": ("Longshot", "Super Grappin"),
    "goron_bracelet": ("Goron Bracelet", "Bracelet Goron"), "silver_scale": ("Silver Scale", "Écaille d'argent"),
    "golden_scale": ("Golden Scale", "Écaille d'or"), "silver_gauntlets": ("Silver Gauntlets", "Gantelets d'argent"),
    "golden_gauntlets": ("Golden Gauntlets", "Gantelets d'or"),
    "adult_wallet": ("Adult's Wallet", "Bourse d'adulte"), "giant_wallet": ("Giant's Wallet", "Bourse de géant"),
    "big_bullet_bag": ("Big Bullet Bag", "Grand sac de graines"),
    "biggest_bullet_bag": ("Biggest Bullet Bag", "Très grand sac de graines"),
    "big_quiver": ("Big Quiver", "Grand carquois"), "biggest_quiver": ("Biggest Quiver", "Très grand carquois"),
    "big_bomb_bag": ("Big Bomb Bag", "Grand sac de bombes"),
    "biggest_bomb_bag": ("Biggest Bomb Bag", "Très grand sac de bombes"),
    "deku_sticks": ("Deku Sticks", "Bâtons Mojo"), "deku_nuts": ("Deku Nuts", "Noix Mojo"),
    "big_stick_bag": ("Big Stick Bag", "Grande capacité de bâtons"),
    "biggest_stick_bag": ("Biggest Stick Bag", "Très grande capacité de bâtons"),
    "big_nut_bag": ("Big Nut Bag", "Grande capacité de noix"),
    "biggest_nut_bag": ("Biggest Nut Bag", "Très grande capacité de noix"),
    "double_magic": ("Double Magic", "Double magie"), "magic_beans": ("Magic Beans", "Haricots magiques"),
    "gerudo_card": ("Gerudo Membership Card", "Carte Gerudo"),
    "ocarina_of_time": ("Ocarina of Time", "Ocarina du Temps"),
    "two_bottles": ("Two Bottles", "Deux bouteilles"), "three_bottles": ("Three Bottles", "Trois bouteilles"),
    "four_bottles": ("Four Bottles", "Quatre bouteilles"),
}


def is_french(language):
    return str(language).lower().replace("_", "-").startswith("fr")


def setting_label(name, language="en"):
    return LABELS.get(name, (SPEC_BY_ID[name]["label"],) * 2)[int(is_french(language))]


def group_label(group, language="en"):
    return GROUPS.get(group, group) if is_french(language) else group


def choice_label(name, value, language="en"):
    if name in {"starting_items", "starting_songs"}:
        if value in STARTING_LABELS:
            return STARTING_LABELS[value][int(is_french(language))]
        from .item_names import item_name
        canonical = value.replace("_", " ").title().replace(" Of ", " of ").replace(" The ", " the ")
        return item_name(canonical, "fr" if is_french(language) else "en")
    labels = CHOICE_OVERRIDES.get((name, value), CHOICES.get(value))
    if labels:
        return labels[int(is_french(language))]
    return value.replace("_", " ").title()


@lru_cache(maxsize=1)
def _french_descriptions():
    return json.loads(resources.files(__package__).joinpath("settings_fr.json").read_text(encoding="utf-8"))


def description(name, language="en"):
    return _french_descriptions().get(name, SPEC_BY_ID[name]["description"]) if is_french(language) else SPEC_BY_ID[name]["description"]


# Per-choice explanations supplement the setting's overall help. They are
# display text, never a second set of defaults or an alternative YAML schema.
CHOICE_HELP = {
    ("shuffle_chests", "off"): ("Keep ordinary chest rewards unchanged. Heart-piece chests still follow Ground pickups and heart pieces.", "Conserver les coffres ordinaires. Les coffres contenant un quart de cœur suivent le réglage des objets au sol."),
    ("shuffle_shops", "off"): ("Keep native shop stock and purchases; no shop AP checks are added.", "Conserver les marchandises et achats d'origine ; aucun check AP de boutique ajouté."),
    ("shuffle_shops", "shuffle"): ("Make all 64 purchases AP checks, using the native ordinary-stock pool and prices. Rewards can belong to any player.", "Les 64 achats deviennent des checks AP, avec le stock ordinaire et les prix natifs comme base. Les gains peuvent appartenir à n'importe quel joueur."),
    ("shuffle_shops", "random"): ("Roll zero to four special deals in each shop's native stock/price layout. All 64 purchases are AP checks; this does not roll who receives them.", "Tirer zéro à quatre offres spéciales par boutique pour composer le stock et les prix natifs. Les 64 achats sont des checks AP ; ce choix ne fixe pas leur destinataire."),
    ("shuffle_skulltulas", "off"): ("Gold Skulltulas give their original tokens and do not send an AP check.", "Les Skulltulas d'or donnent leurs symboles habituels, sans check AP."),
    ("shuffle_skulltulas", "pinned"): ("Shuffle the fixed 44-site subset. The other 56 sites retain their normal rewards.", "Mélanger la sélection fixe de 44 emplacements. Les 56 autres gardent leur récompense habituelle."),
    ("shuffle_skulltulas", "matched"): ("Enable all 100 native Skulltula sites. Collect their drops; the 23 less certain sites accept filler only, never progression or Zelda tokens.", "Activer les 100 emplacements natifs. Ramasser leurs gains ; les 23 sites moins certains ne reçoivent ni progression ni symbole Zelda."),
    ("open_forest", "closed"): ("Mido still asks for the Kokiri Sword and Deku Shield; the forest's opening quest stays in place.", "Mido demande toujours l'Épée Kokiri et le Bouclier Mojo ; le début de la quête de la forêt est conservé."),
    ("open_forest", "open"): ("Reach the Deku Tree and leave Kokiri Forest from the start, without Mido's equipment requirement.", "Accéder à l'Arbre Mojo et quitter la forêt dès le départ, sans fournir l'équipement demandé par Mido."),
    ("open_kakariko", "closed"): ("Keep the Death Mountain gate's normal quest requirement.", "Conserver la condition de quête habituelle de la grille du mont du Péril."),
    ("open_kakariko", "open"): ("Open the gate, skip the Zelda visit, and start with Zelda's Letter and Impa's song. Requires an open forest.", "Ouvrir la grille, passer la visite à Zelda et commencer avec sa lettre et le chant d'Impa. Exige la forêt ouverte."),
    ("zora_fountain", "closed"): ("Move King Zora through his normal quest before passing behind him.", "Accomplir la quête habituelle du roi Zora pour passer derrière lui."),
    ("zora_fountain", "open"): ("King Zora no longer blocks the route to Zora's Fountain.", "Le roi Zora ne bloque plus le passage vers la fontaine Zora."),
    ("gerudo_fortress", "normal"): ("Rescue all four carpenters to clear the fortress.", "Secourir les quatre ouvriers pour libérer la forteresse."),
    ("gerudo_fortress", "fast"): ("Three carpenters start free; rescue the remaining one to clear the fortress and obtain the native Membership Card reward.", "Trois ouvriers sont déjà libres ; secourir le dernier pour libérer la forteresse et obtenir la récompense de la Carte Gerudo."),
    ("gerudo_fortress", "open"): ("Start with all carpenters rescued and the Membership Card; the fortress is friendly.", "Commencer avec tous les ouvriers sauvés et la Carte Gerudo ; les Gerudos sont pacifiques."),
    ("door_of_time_condition", "vanilla"): ("Clear Dodongo's Cavern and Jabu-Jabu's Belly. Play the Song of Time too if Also require the Song of Time is enabled.", "Terminer la caverne Dodongo et Jabu-Jabu. Jouer aussi le Chant du Temps si le réglage correspondant est activé."),
    ("door_of_time_condition", "stones"): ("Hold all three Spiritual Stones. The additional Song of Time requirement is controlled separately.", "Posséder les trois pierres ancestrales. L'exigence du Chant du Temps se règle séparément."),
    ("door_of_time_condition", "song"): ("Play the Song of Time at the altar, without needing the Stones or dungeon clears. Zelda's escape has its own setting.", "Jouer le Chant du Temps devant l'autel, sans exiger les pierres ni les deux donjons. La fuite de Zelda se règle séparément."),
    ("door_of_time_condition", "open"): ("The door is open from the start. The Song of Time is unnecessary for this door; Zelda's escape has its own setting.", "La porte est ouverte dès le départ. Le Chant du Temps n'est pas nécessaire pour cette porte ; la fuite de Zelda se règle séparément."),
    ("door_of_time_escape", "vanilla"): ("Trigger Zelda's escape after clearing Dodongo's Cavern and Jabu-Jabu's Belly.", "Déclencher la fuite de Zelda après la caverne Dodongo et Jabu-Jabu."),
    ("door_of_time_escape", "stones"): ("Trigger Zelda's escape when you hold the three Spiritual Stones instead of checking the two dungeon clears.", "Déclencher la fuite de Zelda en possédant les trois pierres, plutôt qu'en vérifiant les deux donjons."),
    ("door_of_time_escape", "moat"): ("Skip Zelda's escape. The moat Ocarina reward and its following Song of Time reward are accessible from the start.", "Passer la fuite de Zelda. La récompense de l'Ocarina dans les douves et celle du Chant du Temps qui suit sont accessibles dès le départ."),
    ("bridge", "vanilla"): ("Build the bridge after completing the native Light Arrows scene. The reward-count slider is ignored.", "Construire le pont après la scène native des Flèches de Lumière. Le curseur du nombre de récompenses n'est pas utilisé."),
    ("bridge", "dungeons"): ("Count any mix of your three Stones and six Medallions, using Rewards required for the bridge. Dungeon clears alone do not count.", "Compter n'importe quel mélange de vos trois pierres et six médaillons, selon le curseur du pont. Terminer un donjon ne suffit pas sans sa récompense."),
    ("bridge", "open"): ("The bridge appears when approached, without Stones, Medallions or the Light Arrows scene. Its effective reward count is zero.", "Le pont apparaît à l'approche, sans pierre, médaillon ni scène des Flèches de Lumière. Son nombre effectif de récompenses est zéro."),
    ("start_reward", "off"): ("Do not add an extra starting Stone or Medallion.", "Ne pas ajouter de pierre ou de médaillon au départ."),
    ("start_reward", "stone"): ("Start with one randomly chosen Spiritual Stone. Its regular pool reward is not removed.", "Commencer avec une pierre ancestrale tirée au sort. Sa récompense habituelle n'est pas retirée du pool."),
    ("start_reward", "medal"): ("Start with one randomly chosen Medallion. Its regular pool reward is not removed.", "Commencer avec un médaillon tiré au sort. Sa récompense habituelle n'est pas retirée du pool."),
    ("start_reward", "any"): ("Start with one randomly chosen reward among the three Stones and six Medallions, in addition to its regular pool copy.", "Commencer avec une récompense tirée au sort parmi les trois pierres et six médaillons, en plus de sa copie habituelle."),
    ("skip_cutscenes", "off"): ("Keep the game's usual manual cutscene skipping. Automatic introduction skipping is a separate setting.", "Conserver le saut manuel habituel du jeu. Le saut automatique de l'introduction se règle séparément."),
    ("skip_cutscenes", "story"): ("Also allow manually skipping the opening and credits. This does not automatically skip story scenes.", "Autoriser aussi le saut manuel de l'introduction et du générique. Les scènes de l'histoire ne sont pas toutes passées automatiquement."),
    ("skip_cutscenes", "all"): ("Also allow manually skipping title-screen demos, in addition to the opening and credits.", "Autoriser aussi le saut manuel des démonstrations du titre, en plus de l'introduction et du générique."),
    ("navi_return", "off"): ("Keep ordinary Navi hints without a return-travel question.", "Conserver les indices habituels de Navi, sans proposition de retour."),
    ("navi_return", "dungeons"): ("Call Navi with the D-pad to return to a dungeon entrance. Boss and miniboss arenas do not offer this shortcut.", "Appeler Navi avec la croix directionnelle pour revenir à l'entrée du donjon. Le raccourci est désactivé dans les arènes de boss et mini-boss."),
    ("navi_return", "everywhere"): ("Navi also offers a return to Kokiri Forest as a child or the Temple of Time as an adult outside dungeons; boss arenas are excluded.", "Hors donjons, Navi propose aussi la forêt Kokiri enfant ou le Temple du Temps adulte ; les arènes de boss sont exclues."),
    ("bunny_hood", "off"): ("Keep the Bunny Hood's original movement speed.", "Conserver la vitesse de déplacement habituelle du Masque du Lapin."),
    ("bunny_hood", "speed"): ("Run about 1.5 times as fast while actually wearing the Bunny Hood.", "Courir environ 1,5 fois plus vite en portant réellement le Masque du Lapin."),
    ("bunny_hood", "jump"): ("Run faster and jump farther while wearing the Bunny Hood. It does not grant the mask.", "Courir plus vite et sauter plus loin en portant le Masque du Lapin. Le masque n'est pas offert par ce réglage."),
    ("shuffle_freestanding_items", "off"): ("Shuffle supported heart pieces, including their three dedicated chests. This is the engine's default and is identical to Pieces, not a complete disable.", "Mélanger les quarts de cœur pris en charge, dont leurs trois coffres dédiés. C'est le réglage natif par défaut, identique à Pieces, pas une désactivation complète."),
    ("shuffle_freestanding_items", "pieces"): ("The same heart-piece selection as Off; no ordinary rupee or recovery-heart pickups are added.", "Même sélection de quarts de cœur que Off ; aucun rubis ordinaire ni cœur de soin supplémentaire."),
    ("shuffle_freestanding_items", "all"): ("Keep the heart-piece checks and also shuffle supported ordinary rupees and recovery hearts in both dungeons and the overworld.", "Conserver les checks de quarts de cœur et ajouter les rubis ordinaires et cœurs de soin pris en charge, en donjon et hors donjons."),
    ("shuffle_freestanding_items", "dungeons"): ("Keep heart-piece checks everywhere; add ordinary ground rupees and recovery hearts only inside dungeons.", "Conserver les quarts de cœur partout ; ajouter les rubis et cœurs de soin ordinaires au sol uniquement en donjon."),
    ("shuffle_freestanding_items", "overworld"): ("Keep heart-piece checks everywhere; add ordinary ground rupees and recovery hearts only outside dungeons.", "Conserver les quarts de cœur partout ; ajouter les rubis et cœurs de soin ordinaires au sol uniquement hors donjons."),
    ("shuffle_rewards", "off"): ("Keep the supported NPC, fairy, minigame and story gifts unchanged. Dependent NPC-source options are inactive.", "Conserver les cadeaux habituels des PNJ, fées, mini-jeux et scènes concernés. Les options de récompenses PNJ dépendantes sont inactives."),
    ("shuffle_rewards", "supported"): ("Make supported NPC, fairy, minigame and story gifts AP checks. Extra source sets still have their own switches.", "Transformer les cadeaux PNJ, fées, mini-jeux et scènes pris en charge en checks AP. Les groupes supplémentaires ont leurs propres interrupteurs."),
    ("shuffle_songs", "off"): ("Keep ordinary song lessons unchanged. The Scarecrow's Song always stays native.", "Conserver l'apprentissage habituel des chants. Le Chant de l'Épouvantail reste toujours natif."),
    ("shuffle_songs", "own"): ("Song lessons receive songs, and songs stay at song lessons. Compatible Zelda players can exchange them; other items do not enter these checks.", "Les leçons donnent des chants, et les chants restent dans les leçons. Ils peuvent circuler entre joueurs Zelda compatibles ; les autres objets n'occupent pas ces checks."),
    ("shuffle_songs", "anywhere"): ("Mix songs with other AP items across all games; lessons may give any eligible reward.", "Mélanger les chants avec les autres objets AP entre tous les jeux ; les leçons peuvent donner toute récompense compatible."),
    ("shuffle_dungeon_rewards", "vanilla"): ("Keep Stones and Medallions at their usual rewards. They are not added to the AP item pool.", "Conserver les pierres et médaillons dans leurs récompenses habituelles, sans les ajouter au pool AP."),
    ("shuffle_dungeon_rewards", "anywhere"): ("Mix Stones and Medallions into the AP pool across all games; boss and Rauru checks can give other items.", "Mélanger pierres et médaillons dans le pool AP de tous les jeux ; les checks des boss et de Rauru peuvent donner d'autres objets."),
    ("shuffle_dungeon_rewards", "dungeons"): ("Keep Stones and Medallions among the boss/Rauru reward checks. Compatible Zelda owners can mix; ordinary items stay out of these checks.", "Réserver les pierres et médaillons aux récompenses des boss et de Rauru. Les joueurs Zelda compatibles peuvent les échanger ; les objets ordinaires sont exclus de ces checks."),
    ("shuffle_entrances", "off"): ("Keep dungeon entrances and exits at their original destinations.", "Conserver les destinations habituelles des entrées et sorties de donjon."),
    ("shuffle_entrances", "dungeons"): ("Pair and shuffle the supported dungeon entrances and their return exits. Overworld passages are unchanged.", "Mélanger les entrées de donjon prises en charge avec leurs sorties de retour associées. Les passages du monde extérieur sont conservés."),
    ("shuffle_merchants", "off"): ("Do not add merchant checks through this selector. Other enabled selectors, such as Extra NPC rewards, may still include Medigoron.", "Ne pas ajouter de checks marchands par ce réglage. D'autres options activées, comme les récompenses PNJ supplémentaires, peuvent encore inclure Medigoron."),
    ("shuffle_merchants", "beans"): ("Make the Bean Merchant's first purchase an AP check; later purchases give normal beans. Requires NPC rewards and pre-planted beans.", "Le premier achat du marchand de haricots devient un check AP ; les suivants donnent de vrais haricots. Exige les récompenses PNJ et les haricots déjà plantés."),
    ("shuffle_merchants", "no_beans"): ("Enable the supported non-bean merchant reward, Medigoron. The Bean Merchant stays native unless another setting changes him.", "Activer la récompense marchande prise en charge hors haricots : Medigoron. Le marchand de haricots reste natif sauf autre réglage."),
    ("shuffle_merchants", "all"): ("Enable the Bean Merchant's one AP purchase and Medigoron. Requires NPC rewards and pre-planted beans; it does not include every NPC who asks for rupees.", "Activer l'achat AP du marchand de haricots et Medigoron. Exige les récompenses PNJ et les haricots plantés ; cela ne concerne pas tous les PNJ payants."),
    ("shopsanity_prices", "affordable"): ("Each special deal costs 10 rupees. Ordinary stock prices are unchanged.", "Chaque offre spéciale coûte 10 rubis. Les prix du stock ordinaire sont conservés."),
    ("shopsanity_prices", "starting"): ("Roll special-deal prices within the starting wallet's 200-rupee capacity.", "Tirer les prix des offres spéciales dans la capacité initiale de 200 rubis."),
    ("shopsanity_prices", "adult"): ("Special-deal prices may reach the Adult's Wallet's 500-rupee capacity. Kokiri deals remain within the starting wallet.", "Les offres spéciales peuvent demander jusqu'à la bourse d'adulte de 500 rubis. Celles de la boutique Kokiri restent dans la bourse initiale."),
    ("shopsanity_prices", "giant"): ("Roll special-deal prices from 10 to 995 rupees; prices above 500 need the Giant's Wallet. Kokiri deals remain within 200.", "Tirer les prix des offres spéciales de 10 à 995 rubis ; au-delà de 500, la bourse de géant est nécessaire. La boutique Kokiri reste limitée à 200."),
}
for _name in ("shuffle_smallkeys", "shuffle_bosskeys", "shuffle_ganon_bosskey", "shuffle_mapcompass"):
    for _value, _help in {
        "vanilla": ("Keep these items in their original native rewards.", "Conserver ces objets dans leurs récompenses d'origine."),
        "dungeon": ("Place these items only in their original dungeon in your Zelda world. This is an explicit placement restriction.", "Placer ces objets uniquement dans leur donjon d'origine dans votre monde Zelda. C'est une restriction de placement volontaire."),
        "regional": ("Place these items only in their original dungeon's surrounding region in your own Zelda world.", "Placer ces objets uniquement dans la région de leur donjon d'origine, dans votre propre monde Zelda."),
        "overworld": ("Place these items outside dungeons in your own Zelda world; requires all chests shuffled.", "Placer ces objets hors donjons dans votre propre monde Zelda ; exige tous les coffres mélangés."),
        "any_dungeon": ("Place these items in any dungeon in your own Zelda world; requires shuffled dungeon chests.", "Placer ces objets dans n'importe quel donjon de votre monde Zelda ; exige les coffres de donjon mélangés."),
        "keysanity": ("Mix these items throughout Archipelago, including other players' games. Native dungeon-chest shuffling is required.", "Mélanger ces objets dans Archipelago, y compris dans les jeux des autres joueurs. Le mélange des coffres de donjon est requis."),
    }.items():
        if _value in SPEC_BY_ID[_name]["choices"]:
            CHOICE_HELP[(_name, _value)] = _help
for _name in ("shuffle_bosskeys", "shuffle_ganon_bosskey", "shuffle_mapcompass"):
    CHOICE_HELP[(_name, "remove")] = (
        "Remove the need to find these items: their native door or map effects are available from the start.",
        "Supprimer la recherche de ces objets : leurs effets sur les portes ou les cartes sont disponibles dès le départ.")
CHOICE_HELP[("shuffle_mapcompass", "startwith")] = (
    "Start with every dungeon map and compass effect; they are not AP items to find.",
    "Disposer des effets de toutes les cartes et boussoles dès le départ ; elles ne sont pas à trouver dans AP.")
CHOICE_HELP[("shuffle_ganon_bosskey", "lacs_dungeons")] = (
    "Zelda gives your Ganon Boss Key at the Light Arrows scene after the chosen combined Stone/Medallion count. Light Arrows enter the AP pool instead; requires NPC rewards and dungeon chests.",
    "Zelda donne votre clé de Ganon dans la scène des Flèches de Lumière après le total de pierres et médaillons choisi. Les Flèches de Lumière rejoignent le pool AP ; exige les récompenses PNJ et coffres de donjon.")
for _name in ("shuffle_chests", "shuffle_pots", "shuffle_crates", "shuffle_rocks", "shuffle_grass"):
    for _value, _help in {
        "off": ("Do not shuffle this source family. Other source selectors remain active.", "Ne pas mélanger cette famille de sources. Les autres réglages de sources restent actifs."),
        "all": ("Turn all supported sources in this family into AP checks, in dungeons and the overworld.", "Transformer toutes les sources prises en charge de cette famille en checks AP, en donjon et hors donjons."),
        "overworld": ("Shuffle this source family outside dungeons; keep its dungeon rewards unchanged.", "Mélanger cette famille hors donjons ; conserver ses récompenses de donjon."),
        "dungeons": ("Shuffle this source family only inside dungeons; keep its overworld rewards unchanged.", "Mélanger cette famille uniquement en donjon ; conserver ses récompenses hors donjons."),
    }.items():
        CHOICE_HELP.setdefault((_name, _value), _help)
for _count in range(1, 5):
    CHOICE_HELP[("shuffle_shops", "deals_" + str(_count))] = (
        f"Use {_count} special deals per shop in the native stock/price layout. All 64 purchases are AP checks, with no recipient quota.",
        f"Utiliser {_count} offres spéciales par boutique pour le stock et les prix natifs. Les 64 achats sont des checks AP, sans quota de destinataires.")
for _name in ("scrub_prices", "merchant_prices", "fairy_prices"):
    CHOICE_HELP[(_name, "vanilla")] = ("Keep the native prices; the Fixed amount field is ignored.", "Conserver les prix natifs ; le champ Prix fixe n'est pas utilisé.")
    CHOICE_HELP[(_name, "cheap")] = ("Roll a low price per reward from 0 to 95 rupees in steps of 5, favoring cheaper results. This is not a fixed 10 rupees.", "Tirer un petit prix par récompense de 0 à 95 rubis, par pas de 5, en favorisant les petits montants. Ce n'est pas un prix fixe de 10 rubis.")
    CHOICE_HELP[(_name, "fixed")] = ("Use exactly the Fixed amount below for each affected sale or offering; zero makes it free.", "Utiliser exactement le Prix fixe indiqué pour chaque achat ou offrande concerné ; zéro le rend gratuit.")
del _name, _value, _help, _count

CHOICE_HELP.update({
    ("bridge", "medallions"): ("Open the bridge after the chosen number of Medallions; Spiritual Stones never count toward this condition.", "Ouvrir le pont après le nombre choisi de médaillons ; les pierres ancestrales ne comptent jamais pour cette condition."),
    ("shuffle_ganon_bosskey", "lacs_medallions"): ("Zelda gives the Ganon Boss Key after the chosen Medallion count. Spiritual Stones do not count; Light Arrows join the AP pool.", "Zelda donne la clé du boss de Ganon après le nombre choisi de médaillons. Les pierres ne comptent pas ; les Flèches de Lumière rejoignent le pool AP."),
    ("nocturne_trigger", "vanilla"): ("Adult Kakariko burns after clearing Forest, Fire and Water Temples, as in the remake. Owning the Medallions alone is insufficient.", "Cocorico adulte brûle après avoir terminé les temples de la Forêt, du Feu et de l'Eau, comme dans le remake. Posséder seulement leurs médaillons ne suffit pas."),
    ("nocturne_trigger", "classic"): ("Adult Kakariko burns once you hold the Forest, Fire and Water Medallions, including those received from other games.", "Cocorico adulte brûle dès que tu possèdes les médaillons de la Forêt, du Feu et de l'Eau, y compris ceux reçus des autres jeux."),
    ("prelude_trigger", "vanilla"): ("Sheik offers the Prelude after clearing Forest Temple, as in the remake.", "Sheik propose le Prélude après avoir terminé le temple de la Forêt, comme dans le remake."),
    ("prelude_trigger", "classic"): ("Sheik offers the Prelude once you hold the Forest Medallion, including one received through Archipelago.", "Sheik propose le Prélude dès que tu possèdes le médaillon de la Forêt, même reçu par Archipelago."),
    ("cosmetic_color_mode", "off"): ("Use the game's original colours; individual colour picks remain inactive.", "Utiliser les couleurs d'origine du jeu ; les choix détaillés restent inactifs."),
    ("cosmetic_color_mode", "custom"): ("Use only your individual colour picks. Unlisted parts keep their original colours; each listed part can be exact or random.", "Utiliser seulement tes choix de couleurs détaillés. Les éléments non listés gardent leur couleur d'origine ; chaque choix peut être précis ou aléatoire."),
    ("cosmetic_color_mode", "random"): ("Draw an independent random colour for every supported part; individual picks are inactive.", "Tirer une couleur aléatoire indépendante pour chaque élément pris en charge ; les choix détaillés sont inactifs."),
    ("cosmetic_color_mode", "shared"): ("Draw one random hue and give every supported part a shade of it.", "Tirer une seule teinte aléatoire et donner à chaque élément pris en charge une nuance de cette teinte."),
    ("shuffle_music", "off"): ("Keep each native music track in its original place.", "Conserver chaque musique native à sa place d'origine."),
    ("shuffle_music", "grouped"): ("Shuffle music within compatible native categories, keeping battle, boss and other groups separate.", "Mélanger les musiques à l'intérieur de leurs catégories compatibles, en séparant combats, boss et autres groupes."),
    ("shuffle_music", "anywhere"): ("Mix compatible music across categories; a scene may use music of another category.", "Mélanger les musiques compatibles entre catégories ; une scène peut jouer une musique d'une autre catégorie."),
    ("shuffle_sfx", "off"): ("Keep the game's original sound effects.", "Conserver les effets sonores d'origine du jeu."),
    ("shuffle_sfx", "grouped"): ("Shuffle similar compatible sound effects within their groups.", "Mélanger les effets sonores compatibles similaires à l'intérieur de leurs groupes."),
    ("shuffle_sfx", "anywhere"): ("Mix compatible sound effects between groups, while retaining the adapter's native safety exclusions.", "Mélanger les effets sonores compatibles entre groupes, en conservant les exclusions natives de l'adaptateur."),
    ("damage_taken", "normal"): ("Keep the normal global damage multiplier. A separate Enemy attack damage setting can still change enemy hits.", "Garder le multiplicateur global normal. Le réglage séparé des dégâts d'attaque ennemis peut toujours modifier leurs coups."),
    ("damage_taken", "double"): ("Take twice the normal damage from enemies, traps and falls; enemy attack scaling also applies.", "Subir deux fois les dégâts habituels des ennemis, pièges et chutes ; le multiplicateur d'attaque ennemi s'applique aussi."),
    ("damage_taken", "quadruple"): ("Take four times the normal damage from enemies, traps and falls; enemy attack scaling also applies.", "Subir quatre fois les dégâts habituels des ennemis, pièges et chutes ; le multiplicateur d'attaque ennemi s'applique aussi."),
    ("damage_taken", "one_hit"): ("A damaging hit can knock Link out regardless of his current hearts. This is separate from DeathLink.", "Un coup causant des dégâts peut tuer Link quel que soit son nombre de cœurs. Ce réglage est distinct de DeathLink."),
    ("enemy_sizes", "off"): ("Keep original enemy sizes; size-based health scaling is inactive.", "Conserver les tailles d'origine des ennemis ; l'adaptation de vie selon leur taille est inactive."),
    ("enemy_sizes", "mild"): ("Use moderate random size variations at supported enemy spawns.", "Utiliser des variations de taille aléatoires modérées sur les ennemis pris en charge."),
    ("enemy_sizes", "wild"): ("Use a wider random size range at supported enemy spawns.", "Utiliser une plage de tailles aléatoires plus large sur les ennemis pris en charge."),
    ("shorter_timers", "off"): ("Keep the original durations of supported timed challenges.", "Conserver les durées d'origine des défis chronométrés pris en charge."),
    ("shorter_timers", "three_quarters"): ("Use 75 percent of each supported challenge's original time.", "Accorder 75 pour cent du temps d'origine pour chaque défi pris en charge."),
    ("shorter_timers", "half"): ("Use half of each supported challenge's original time.", "Accorder la moitié du temps d'origine pour chaque défi pris en charge."),
})

TOGGLE_OFF_HELP = {
    "death_link": ("Do not send or receive DeathLink deaths.", "Ne pas envoyer ni recevoir de morts DeathLink."),
    "shops_always_open": ("Use the shops' native opening hours; quest locks still apply.", "Utiliser les horaires d'origine des boutiques ; leurs conditions de quête restent nécessaires."),
    "jabu_open": ("A fish is still needed to enter Jabu-Jabu.", "Un poisson reste nécessaire pour entrer dans Jabu-Jabu."),
    "time_always_passes": ("Keep the early story's normal restrictions on the day/night cycle.", "Conserver les restrictions du début de l'histoire sur le cycle jour/nuit."),
    "early_beds": ("Keep the normal story requirement before beds can change the time of day.", "Conserver la condition habituelle de l'histoire pour utiliser les lits et changer l'heure."),
    "door_of_time_song": ("With either closed-door requirement, the door opens by itself when that requirement is met; Open and Song only ignore this switch.", "Avec l'une des conditions de porte fermée, la porte s'ouvre seule une fois la condition remplie ; Ouvert et Chant seul ignorent cet interrupteur."),
    "skip_ganon_trials": ("Use the Number of trials slider to choose how many trials remain.", "Utiliser le curseur du nombre d'épreuves pour choisir combien restent nécessaires."),
    "faster_chests": ("Keep normal chest-opening and item-receive scene timing.", "Conserver la durée habituelle des animations de coffre et de réception."),
    "faster_blocks": ("Push and pull blocks at their usual speed.", "Pousser et tirer les blocs à leur vitesse habituelle."),
    "skip_intro": ("Play the normal opening movie and Link's wake-up scene; manual skipping is controlled separately.", "Jouer le film d'ouverture et le réveil de Link ; le saut manuel se règle séparément."),
    "skip_first_pickup_text": ("Keep the native first-time message for small pickups.", "Conserver le premier message de ramassage des petits objets."),
    "anju_one_cucco": ("Use Anju's normal Cucco requirement.", "Conserver le nombre habituel de cocottes demandé par Anju."),
    "big_poe_one": ("Use the Poe Collector's normal Big Poe requirement.", "Conserver le nombre habituel de Grands Esprits demandé par le marchand d'âmes."),
    "skip_epona_race": ("Complete Ingo's normal Epona quest; knowing Epona's Song alone does not grant the horse.", "Accomplir la quête habituelle d'Ingo ; connaître le Chant d'Epona ne donne pas le cheval à lui seul."),
    "skip_mask_quest": ("Unlock the masks through their normal trading quest.", "Débloquer les masques avec leur quête d'échanges habituelle."),
    "plant_beans": ("Plant the beans yourself before using their adult platforms. The shuffled Bean Merchant requires this option enabled.", "Planter vous-même les haricots avant d'utiliser leurs plateformes adultes. Le marchand de haricots mélangé exige cette option activée."),
    "gerudo_bridge_open": ("Keep the broken Gerudo Valley bridge and its normal repair requirement.", "Conserver le pont cassé de la vallée Gerudo et sa réparation habituelle."),
    "deku_bridge_safe": ("The Deku Tree slingshot-room bridge can collapse normally.", "Le pont de la salle du lance-pierre de l'Arbre Mojo peut s'effondrer normalement."),
    "shuffle_beehives": ("Keep beehive drops unchanged.", "Conserver les butins habituels des ruches."),
    "shuffle_rewards_extra": ("Do not add this extra NPC-reward set. Other selectors can still include overlapping rewards, such as the adult-trade finale.", "Ne pas ajouter ce groupe de récompenses PNJ. D'autres réglages peuvent encore inclure des récompenses communes, comme la fin des échanges adultes."),
    "shuffle_boss_hearts": ("Keep the boss heart containers as normal health rewards.", "Conserver les réceptacles de cœur des boss comme gains de vie habituels."),
    "shuffle_potion_shop": ("Keep the Potion Shop's bottle and tutorial gifts unchanged.", "Conserver les cadeaux habituels de bouteille et de tutoriel de l'apothicaire."),
    "adult_trade_shuffle": ("Do not mix the ten adult-trade quest inputs into AP. Separately enabled NPC rewards may still change.", "Ne pas mélanger les dix objets d'échange adulte dans AP. Les récompenses PNJ activées séparément peuvent encore changer."),
    "shuffle_scrubs_a": ("Do not add the three Lost Woods/Crater one-time Scrub sellers through this option.", "Ne pas ajouter les trois ventes uniques des pestes des Bois Perdus et du cratère par ce réglage."),
    "shuffle_scrubs_b": ("Keep the two supported Jabu/rear-grotto Scrub menus unchanged.", "Conserver les deux menus habituels des pestes de Jabu et du fond de la grotte."),
    "shuffle_cows": ("Keep cow milk rewards unchanged.", "Conserver les récompenses habituelles de lait des vaches."),
    "shuffle_treasure_reward": ("Keep the Treasure Chest Game's first-win heart piece unchanged.", "Conserver le quart de cœur habituel de la première victoire à la chasse aux trésors."),
    "shuffle_frog_songs": ("Keep the five first-time frog-song rewards unchanged.", "Conserver les cinq premières récompenses des chants des grenouilles."),
    "shuffle_frog_bug_heart": ("Keep the frog bug game's heart piece unchanged.", "Conserver le quart de cœur habituel du jeu des insectes des grenouilles."),
    "shuffle_ocarinas": ("Saria and the castle moat keep their original instruments.", "Saria et les douves du château gardent leurs instruments d'origine."),
    "shuffle_kokiri_sword": ("Keep the Kokiri Sword in its original chest.", "Conserver l'Épée Kokiri dans son coffre d'origine."),
    "shuffle_master_sword": ("Receive the Master Sword normally at the pedestal. Rauru's separately selected reward can still be an AP check.", "Recevoir l'Épée de Légende normalement au piédestal. La récompense distincte de Rauru peut rester un check AP si activée séparément."),
    "scrub_hint_text": ("Describe enabled Scrub offers as mystery items without revealing the reward or owner.", "Présenter les offres de pestes activées comme des objets mystères, sans révéler le gain ni son propriétaire."),
    "song_harp_colors": ("Keep the ordinary harp colors for shuffled song pickups.", "Conserver les couleurs habituelles des harpes des chants mélangés."),
    "enemy_regen": ("Enemies do not gain the added health regeneration.", "Ne pas ajouter de régénération aux ennemis."),
    "enemy_backup": ("Do not add the reinforcement-calling behavior.", "Ne pas ajouter le comportement d'appel de renforts."),
    "no_heart_drops": ("Ordinary random drops can still contain recovery hearts.", "Les butins ordinaires peuvent toujours contenir des cœurs de soin."),
    "no_gossip_fairies": ("Gossip stones can still release fairies normally.", "Les pierres à potins peuvent toujours libérer des fées."),
    "no_ammo_drops": ("Keep ordinary ammunition, stick and nut drops.", "Conserver les butins ordinaires de munitions, bâtons et noix Mojo."),
    "lose_heart_on_death": ("Game Over does not remove a heart container.", "Le Game Over ne retire pas de réceptacle de cœur."),
    "no_bottles_in_combat": ("Allow normal bottle use during combat.", "Autoriser l'utilisation habituelle des bouteilles en combat."),
    "no_z_targeting": ("Keep normal enemy targeting.", "Conserver le ciblage habituel des ennemis."),
    "no_dupe_items": ("Keep normal bottle-capture and refill rules; this option adds no duplicate-content restriction.", "Conserver les règles habituelles de capture et remplissage des bouteilles, sans restriction supplémentaire des contenus identiques."),
    "enemies_respawn_sooner": ("Use enemies' usual respawn timing.", "Conserver les conditions habituelles de réapparition des ennemis."),
    "boss_minibosses": ("Do not add minibosses to boss arenas.", "Ne pas ajouter de mini-boss dans les arènes des boss."),
    "boss_minions": ("Do not add this extra set of enemies to boss arenas.", "Ne pas ajouter ce groupe d'ennemis supplémentaires dans les arènes des boss."),
    "bean_pitch": ("Keep the Bean Seller's normal dialogue without the difficulty-mod aside.", "Conserver le dialogue du vendeur de haricots sans sa remarque sur les mods de difficulté."),
    "zora_ambush": ("Do not add the Zora's Domain Skulltula ambush.", "Ne pas ajouter l'embuscade de Skulltulas au domaine Zora."),
    "enemy_gates": ("Do not add these combat barriers to overworld paths.", "Ne pas ajouter ces barrières de combat sur les chemins du monde extérieur."),
    "cucco_revenge": ("Use the normal number of Cucco hits before the flock retaliates.", "Conserver le nombre habituel de coups avant la vengeance des cocottes."),
    "enemy_spawn_combo": ("Disable the practice-enemy spawning shortcut.", "Désactiver le raccourci d'apparition d'ennemis d'entraînement."),
    "fairy_helps_enemies": ("Released fairies keep their normal effect and do not gain enemy healing.", "Les fées libérées gardent leur effet habituel, sans soin supplémentaire des ennemis."),
}
for _name, _help in TOGGLE_OFF_HELP.items():
    CHOICE_HELP[(_name, False)] = _help
del _name, _help


TOGGLE_OFF_HELP.update({
    "skulls_by_day": ("Keep night-only Skulltulas restricted to night.", "Conserver les Skulltulas nocturnes uniquement la nuit."),
    "night_skulls_suns_song": ("Logic may reach night Skulltulas by waiting for night, without requiring Sun's Song.", "La logique peut atteindre les Skulltulas nocturnes en attendant la nuit, sans exiger le Chant du Soleil."),
    "free_scarecrow": ("Keep the native child song-recording requirement before adult Scarecrow use.", "Conserver la condition native d'enregistrement du chant enfant avant d'utiliser l'épouvantail adulte."),
    "skip_tower_escape": ("Play the normal timed escape between Ganondorf and the final Ganon fight.", "Jouer la fuite chronométrée habituelle entre Ganondorf et le combat final contre Ganon."),
    "skip_area_intros": ("Keep first-visit area camera tours, subject to the existing opening-skip behavior.", "Conserver les présentations des premières visites, selon le comportement existant du saut de l'introduction."),
    "dungeon_key_tracker": ("Keep the original dungeon-map information display.", "Conserver l'affichage d'informations d'origine des cartes de donjon."),
    "dpad_gear_cycle": ("Keep the original D-pad equipment shortcuts without hold-to-cycle behavior.", "Conserver les raccourcis d'équipement d'origine sans changement en maintenant la croix."),
    "fishing_any_fish": ("Keep the normal fish-size and lure requirements for pond prizes.", "Conserver les conditions habituelles de taille et de leurre pour les récompenses de pêche."),
    "faster_ocarina_minigame": ("Keep the Skull Kids' normal memory-game rounds.", "Conserver les manches habituelles du jeu de mémoire des Skull Kids."),
    "dampe_one_race": ("Keep the original separate race requirements for Dampe's two rewards.", "Conserver les conditions de courses séparées d'origine pour les deux récompenses d'Igor."),
    "dampe_first_dig": ("Keep Dampe's normal dig lottery and fees.", "Conserver les tirages et paiements habituels des creusements d'Igor."),
    "disable_low_health_warnings": ("Keep the game's low-health sound and visual warnings.", "Conserver les alertes sonores et visuelles de vie faible du jeu."),
    "owl_warps": ("Keep the native owl appearances and flight availability.", "Conserver les apparitions et disponibilités de voyage natives du hibou."),
    "starting_bunny_hood": ("Do not grant the Bunny Hood at the start.", "Ne pas donner le Masque du Lapin au départ."),
    "shuffle_ice_traps": ("Do not replace AP filler items with Ice Traps.", "Ne pas remplacer les objets de remplissage AP par des pièges de glace."),
    "unbreakable_bowling_grass": ("Keep Bombchu Bowling obstacles normally destructible.", "Conserver la destruction habituelle des obstacles du bowling Teigneux."),
    "harder_talon_cuccos": ("Keep Talon's normal Super Cucco minigame setup.", "Conserver la configuration habituelle du jeu des super cocottes de Talon."),
    "fireball_storms": ("Do not add the optional falling fire-rock storms.", "Ne pas ajouter les pluies facultatives de rochers enflammés."),
    "volvagia_roams": ("Do not add the optional field Volvagia encounter.", "Ne pas ajouter la rencontre facultative avec Volcania dans la plaine."),
    "mega_like_likes": ("Keep the normal Like Like sizes.", "Conserver les tailles habituelles des Like Likes."),
    "random_fuses": ("Keep supported explosives' native fuse durations.", "Conserver les durées de mèches natives des explosifs pris en charge."),
    "enemy_randomizer": ("Keep ordinary enemy types at their original spawns.", "Conserver les types d'ennemis ordinaires à leurs emplacements d'origine."),
    "enemy_sizes_health": ("Random enemy size does not add another health multiplier.", "La taille aléatoire des ennemis n'ajoute pas de multiplicateur de vie supplémentaire."),
})


for _quarantined in QUARANTINED_DEFAULTS:
    LABELS.pop(_quarantined, None)
    TOGGLE_OFF_HELP.pop(_quarantined, None)
CHOICE_HELP = {key: value for key, value in CHOICE_HELP.items() if key[0] in SPEC_BY_ID}
CHOICE_OVERRIDES = {key: value for key, value in CHOICE_OVERRIDES.items() if key[0] in SPEC_BY_ID}
del _quarantined


def choice_description(name, value, language="en"):
    """Explain one selected value, or a draft list of starting items/songs."""
    spec, fr = SPEC_BY_ID[name], is_french(language)
    if spec["kind"] == "set":
        if isinstance(value, str):
            label = choice_label(name, value, language)
            return (("Connaître dès le départ : " if name == "starting_songs" else "Commencer avec : ") + label + "."
                    if fr else ("Know from the start: " if name == "starting_songs" else "Start with: ") + label + ".")
        selected = [choice_label(name, item, language) for item in value]
        if not selected:
            return "Aucun choix ajouté au départ." if fr else "No additional starting selections."
        return ("Au départ : " if fr else "Starting selections: ") + ", ".join(selected) + ". " + description(name, language)
    if spec["kind"] == "dict":
        count = len(value) if isinstance(value, dict) else 0
        return ((f"{count} choix configuré(s). " if fr else f"{count} configured entries. ")
                + description(name, language))
    help_text = CHOICE_HELP.get((name, value))
    if help_text:
        return help_text[int(fr)]
    if spec["kind"] == "toggle":
        if value:
            return description(name, language)
        return ("Ce changement n'est pas appliqué. Les autres réglages restent actifs." if fr
                else "Do not apply this change; other settings still take effect.")
    if spec["kind"] == "range":
        suffix = "%" if name in {"enemy_health", "enemy_damage", "enemy_speed", "more_enemies"} else ""
        return ("Valeur choisie : " if fr else "Selected value: ") + str(value) + suffix + ". " + description(name, language)
    return choice_label(name, value, language) + ". " + description(name, language)


def selection_summary(values, language="en"):
    """A compact, non-mutating preview using the same dependencies as export."""
    from .settings import default_options
    fr = is_french(language)
    draft = default_options()
    draft.update(values)
    effective = normalize_inactive(draft)
    enabled = [setting_label(name, language) for name in
               ("shuffle_pots", "shuffle_crates", "shuffle_rocks", "shuffle_grass", "shuffle_beehives",
                "shuffle_rewards", "shuffle_songs", "adult_trade_shuffle", "shuffle_master_sword")
               if effective[name] not in (False, "off")]
    state = lambda value: ("Oui" if value else "Non") if fr else ("On" if value else "Off")
    rows = ["DeathLink: " + state(effective["death_link"])
            + (" ; boutiques jour/nuit : " if fr else "; day/night shops: ") + state(effective["shops_always_open"]),
            ("Coffres : " if fr else "Chests: ") + choice_label("shuffle_chests", effective["shuffle_chests"], language)
            + (" ; objets au sol : " if fr else "; ground items: ")
            + choice_label("shuffle_freestanding_items", effective["shuffle_freestanding_items"], language),
            ("Boutiques : " if fr else "Shops: ") + choice_label("shuffle_shops", effective["shuffle_shops"], language)
            + (" ; Skulltulas : " if fr else "; Skulltulas: ")
            + choice_label("shuffle_skulltulas", effective["shuffle_skulltulas"], language)
            + ((f" ; {len(enabled)} autres mélanges" if fr else f"; {len(enabled)} other shuffles") if enabled else ""),
            ("Petites clés : " if fr else "Small keys: ") + choice_label("shuffle_smallkeys", effective["shuffle_smallkeys"], language)
            + (" ; boss : " if fr else "; boss: ") + choice_label("shuffle_bosskeys", effective["shuffle_bosskeys"], language)
            + (" ; Ganon : " if fr else "; Ganon: ") + choice_label("shuffle_ganon_bosskey", effective["shuffle_ganon_bosskey"], language)
            + (" ; cartes : " if fr else "; maps: ") + choice_label("shuffle_mapcompass", effective["shuffle_mapcompass"], language),
            ("Porte du Temps : " if fr else "Door of Time: ") + choice_label("door_of_time_condition", effective["door_of_time_condition"], language)
            + (" ; pont : " if fr else "; bridge: ") + choice_label("bridge", effective["bridge"], language)
            + ((" (" + str(effective["bridge_rewards"]) + ")") if effective["bridge"] == "dungeons" else
               (" (" + str(effective["bridge_medallions"]) + ")") if effective["bridge"] == "medallions" else "")
            + (" ; épreuves : " if fr else "; trials: ")
            + str(0 if effective["skip_ganon_trials"] else effective["trials"])]
    ignored = sum(draft[spec["id"]] != spec["default"] and bool(active_reason(spec["id"], draft, language))
                  for spec in OPTION_SPECS)
    last = ("Objectif : vaincre Ganon. Nouvelle salle requise." if fr else "Goal: defeat Ganon. Generate a new room to use these settings.")
    if ignored:
        last += (f" {ignored} choix conservé(s) mais inactif(s) à l'export." if fr
                 else f" {ignored} draft selection(s) are inactive in the effective export.")
    rows.append(last)
    return tuple(rows)


def active_reason(name, values, language="en"):
    """Empty when active, otherwise a concise, localised dependency explanation."""
    fr = is_french(language)
    def requires(dependency, expected=None):
        label = setting_label(dependency, language)
        if expected is not None:
            label += ": " + choice_label(dependency, expected, language)
        return ("Nécessite : " if fr else "Requires: ") + label
    if name == "bridge_rewards" and values["bridge"] != "dungeons":
        return requires("bridge", "dungeons")
    if name == "bridge_medallions" and values["bridge"] != "medallions":
        return requires("bridge", "medallions")
    if name == "lacs_medallions" and values["shuffle_ganon_bosskey"] != "lacs_medallions":
        return requires("shuffle_ganon_bosskey", "lacs_medallions")
    if name == "night_skulls_suns_song" and values["skulls_by_day"]:
        return "Désactiver les Skulltulas présentes aussi le jour." if fr else "Turn off Skulltulas appearing by day."
    if name == "cosmetic_colors" and values["cosmetic_color_mode"] != "custom":
        return requires("cosmetic_color_mode", "custom")
    if name == "ice_trap_count" and not values["shuffle_ice_traps"]:
        return requires("shuffle_ice_traps")
    if name in {"bean_pitch", "zora_ambush"} and not values[name]:
        return "Compatibilité avec les anciennes configurations uniquement." if fr else "Older configuration compatibility only."
    if name == "trials" and values["skip_ganon_trials"]:
        return "Désactiver le saut des épreuves." if fr else "Turn off Skip Ganon's trials."
    if name == "door_of_time_escape" and values["door_of_time_condition"] not in {"open", "song"}:
        return "Nécessite une porte ouverte ou le chant seul." if fr else "Requires an open door or Song of Time only."
    if name == "door_of_time_song" and values["door_of_time_condition"] in {"open", "song"}:
        return "Nécessite la condition d'origine ou les trois pierres." if fr else "Requires the original condition or the three Stones."
    if name == "lacs_rewards" and values["shuffle_ganon_bosskey"] != "lacs_dungeons":
        return requires("shuffle_ganon_bosskey", "lacs_dungeons")
    if name == "shopsanity_prices" and values["shuffle_shops"] not in {"random", "deals_1", "deals_2", "deals_3", "deals_4"}:
        return "Nécessite des offres spéciales en boutique." if fr else "Requires special shop deals."
    if name in {"scrub_prices", "scrub_hint_text"} and not (values["shuffle_scrubs_a"] or values["shuffle_scrubs_b"]):
        return "Activer au moins un groupe de pestes marchandes." if fr else "Enable at least one Deku Scrub set."
    if name == "merchant_prices" and values["shuffle_merchants"] == "off":
        return requires("shuffle_merchants")
    for kind in ("scrub", "merchant", "fairy"):
        if name == kind + "_price_fixed" and (values[kind + "_prices"] != "fixed" or active_reason(kind + "_prices", values, language)):
            return requires(kind + "_prices", "fixed")
    if name == "song_harp_colors" and values["shuffle_songs"] != "anywhere":
        return requires("shuffle_songs", "anywhere")
    if name == "early_beds" and not values["time_always_passes"]:
        return requires("time_always_passes")
    if name == "open_kakariko" and values["open_forest"] != "open":
        return requires("open_forest", "open")
    if name == "enemy_gates" and (values["open_forest"] != "closed" or values["shuffle_entrances"] != "off"):
        return "Nécessite une forêt fermée et les entrées d'origine." if fr else "Requires a closed forest and original dungeon entrances."
    if name == "shuffle_kokiri_sword" and values["shuffle_chests"] not in {"all", "overworld"}:
        return "Nécessite le mélange des coffres du monde extérieur." if fr else "Requires shuffled overworld chests."
    npc_children = {"shuffle_rewards_extra", "shuffle_potion_shop", "adult_trade_shuffle", "shuffle_scrubs_a",
                    "shuffle_scrubs_b", "shuffle_cows", "shuffle_frog_songs", "shuffle_frog_bug_heart",
                    "shuffle_ocarinas", "shuffle_dungeon_rewards", "shuffle_merchants"}
    if name in npc_children and values["shuffle_rewards"] != "supported":
        return requires("shuffle_rewards", "supported")
    return ""


def normalize_inactive(values):
    """Reset disabled subsettings to defaults, so the GUI exports usable YAML."""
    import copy
    result = copy.deepcopy(values)
    for _ in range(3):
        for spec in OPTION_SPECS:
            if active_reason(spec["id"], result):
                result[spec["id"]] = copy.deepcopy(spec["default"])
        if result["bridge"] == "open":
            result["bridge_rewards"] = 0
    return result


def validation_message(error, language="en"):
    """Localise editor validation without changing YAML keys or validation rules."""
    text = str(error)
    if not is_french(language):
        return text
    for name, explanation in {
        "volvagia_roams": "La séquence de mort de Volcania en liberté est incomplète ; ce réglage reste désactivé jusqu'à un correctif testé.",
        "enemy_sizes": "Le jeu ignore les modifications de taille du placement seul ; ce réglage reste désactivé jusqu'à un correctif testé.",
        "enemy_sizes_health": "La vie selon la taille dépend du réglage de taille des ennemis actuellement indisponible.",
    }.items():
        if text.startswith("Unavailable setting: " + name + ". "):
            return "Réglage indisponible : " + name + ". " + explanation
    messages = {
        "Starting Bombchus also require a bomb bag in starting_items.": "Sélectionne aussi un sac de bombes dans l'équipement initial pour commencer avec des Bombchus.",
        "open_kakariko: open already grants Impa's song; remove zeldas_lullaby from starting_songs.": "L'ouverture de la grille accorde déjà le chant d'Impa : retire la Berceuse de Zelda des chants initiaux.",
        "Shuffling the Bean Merchant requires plant_beans: true.": "Active Haricots déjà plantés pour mélanger les achats du marchand de haricots.",
        "lacs_dungeons requires shuffle_rewards: supported and dungeon or all chests.": "Pour obtenir la clé de Ganon dans la scène des Flèches de Lumière, active les récompenses des PNJ et les coffres de donjon.",
        "shuffle_chests: off requires AP shop deals, Skulltulas or adult trades.": "Sans coffre mélangé, active des offres spéciales en boutique, les Skulltulas ou les échanges adultes.",
        "bridge: open fixes bridge_rewards at zero; leave its default value or set it to zero.": "Un pont ouvert ne demande aucune récompense : garde le nombre par défaut ou choisis zéro.",
    }
    if text in messages:
        return messages[text]
    match = re.fullmatch(r"([a-z_]+) must be an integer between (-?\d+) and (-?\d+)\.", text)
    if match:
        return f"{setting_label(match[1], language)} : choisis un entier entre {match[2]} et {match[3]}."
    match = re.fullmatch(r"([a-z_]+) uses steps of (\d+) from (-?\d+)\.", text)
    if match:
        return f"{setting_label(match[1], language)} : utilise des pas de {match[2]} à partir de {match[3]}."
    match = re.fullmatch(r"([a-z_]+)(?:: overworld)? requires shuffle_chests: (.+)\.", text)
    if match:
        return setting_label(match[1], language) + " : active les coffres de donjon et, pour un placement extérieur, tous les coffres."
    match = re.fullmatch(r"([a-z_]+) requires shuffled chests for this placement mode\.", text)
    if match:
        return setting_label(match[1], language) + " : ce placement nécessite le mélange des coffres."
    return text
