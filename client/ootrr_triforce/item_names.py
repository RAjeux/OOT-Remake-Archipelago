"""Display-only Zelda item translations; AP names and IDs never change."""
import re

from .catalog import GAME, LEGACY_GAME, ITEM_IDS


_FR = {
    "Master Sword": "Épée de légende",
    "Bolero of Fire": "Boléro du Feu", "Boomerang": "Boomerang", "Dins Fire": "Feu de Din",
    "Eponas Song": "Chant d'Épona", "Farores Wind": "Vent de Farore", "Fire Arrows": "Flèches de feu",
    "Gerudo Membership Card": "Carte Gerudo", "Goron Tunic": "Tunique Goron",
    "Hover Boots": "Bottes des airs", "Ice Arrows": "Flèches de glace", "Iron Boots": "Bottes de plomb",
    "Lens of Truth": "Monocle de Vérité", "Light Arrows": "Flèches de lumière",
    "Megaton Hammer": "Masse des Titans", "Minuet of Forest": "Menuet des Bois",
    "Mirror Shield": "Bouclier miroir", "Nayrus Love": "Amour de Nayru",
    "Nocturne of Shadow": "Nocturne de l'Ombre", "Prelude of Light": "Prélude de la Lumière",
    "Requiem of Spirit": "Requiem des Esprits", "Sarias Song": "Chant de Saria",
    "Serenade of Water": "Sérénade de l'Eau", "Song of Storms": "Chant des Tempêtes",
    "Song of Time": "Chant du Temps", "Stone of Agony": "Pierre de Souffrance",
    "Suns Song": "Chant du Soleil", "Zeldas Lullaby": "Berceuse de Zelda", "Zora Tunic": "Tunique Zora",
    "Blue Rupee (5)": "Rubis bleu (5)", "Biggoron Sword": "Épée Biggoron", "Blue Potion": "Potion bleue",
    "Bomb Bag": "Sac de bombes", "Bombchus": "Missiles", "Boss Key": "Clé du boss", "Bottle": "Bouteille",
    "Bottle with Big Poe": "Bouteille avec Grand Esprit", "Bottle with Blue Fire": "Bouteille de flamme bleue",
    "Bottle with Blue Potion": "Bouteille de potion bleue", "Bottle with Bugs": "Bouteille d'insectes",
    "Bottle with Fairy": "Bouteille avec fée", "Bottle with Fish": "Bouteille de poisson",
    "Bottle with Green Potion": "Bouteille de potion verte", "Bottle with Milk": "Bouteille de lait",
    "Bottle with Poe": "Bouteille avec Esprit", "Bottle with Red Potion": "Bouteille de potion rouge",
    "Bow": "Arc", "Broken Sword": "Épée brisée", "Bunny Hood": "Masque du Lapin",
    "Business Scrub Seed": "Noix de peste marchande", "Buy Magic Bean": "Haricot magique (achat)",
    "Chicken": "Cocotte", "Claim Check": "Certificat", "Cojiro": "Cojiro", "Compass": "Boussole",
    "Deku Nut Capacity": "Capacité de noix Mojo", "Deku Shield": "Bouclier Mojo",
    "Deku Stick Capacity": "Capacité de bâtons Mojo", "Double Defense": "Double défense",
    "Eyeball Frog": "Crapaud-qui-louche", "Eyedrops": "Super gouttes", "Fairy Drop": "Goutte de fée",
    "Fire Medallion": "Médaillon du Feu", "Forest Medallion": "Médaillon de la Forêt",
    "Gerudo Mask": "Masque Gerudo", "Giants Knife": "Lame des Géants",
    "Gold Skulltula Token": "Symbole de Skulltula d'or", "Goron Mask": "Masque Goron",
    "Goron Ruby": "Rubis Goron", "Heart Container": "Réceptacle de cœur", "Hylian Shield": "Bouclier Hylien",
    "Keaton Mask": "Masque du Renard", "Kokiri Emerald": "Émeraude Kokiri", "Kokiri Sword": "Épée Kokiri",
    "Light Medallion": "Médaillon de la Lumière", "Magic Bean": "Haricot magique",
    "Magic Jar (Large)": "Grande jarre de magie", "Magic Meter": "Jauge de magie", "Map": "Carte",
    "Mask of Truth": "Masque de Vérité", "Milk": "Lait", "Ocarina": "Ocarina",
    "Odd Mushroom": "Champignon suspect", "Odd Potion": "Mixture suspecte", "Piece of Heart": "Quart de cœur",
    "Piece of Heart (Out of Logic)": "Quart de cœur (hors logique)",
    "Piece of Heart (Treasure Chest Game)": "Quart de cœur (Chasse aux trésors)",
    "Poachers Saw": "Scie du chasseur", "Pocket Cucco": "Cocotte de poche", "Pocket Egg": "Œuf de poche",
    "Prescription": "Ordonnance", "Progressive Hookshot": "Grappin progressif",
    "Progressive Scale": "Écaille progressive", "Progressive Strength Upgrade": "Force progressive",
    "Progressive Wallet": "Bourse progressive", "Recovery Heart": "Cœur de vie", "Rutos Letter": "Lettre de Ruto",
    "Scarecrow Song": "Chant de l'Épouvantail", "Shadow Medallion": "Médaillon de l'Ombre",
    "Skull Mask": "Masque de Mort", "Slingshot": "Lance-pierre", "Small Key": "Petite clé",
    "Spirit Medallion": "Médaillon des Esprits", "Spooky Mask": "Masque d'Effroi",
    "Water Medallion": "Médaillon de l'Eau", "Weird Egg": "Œuf curieux", "Zeldas Letter": "Lettre de Zelda",
    "Zora Mask": "Masque Zora", "Zora Sapphire": "Saphir Zora",
}
_DUNGEONS = {
    "Bottom of the Well": "Puits", "Deku Tree": "Arbre Mojo", "Dodongos Cavern": "Caverne Dodongo",
    "Fire Temple": "Temple du Feu", "Forest Temple": "Temple de la Forêt", "Ganons Castle": "Château de Ganon",
    "Gerudo Training Ground": "Gymnase Gerudo", "Ice Cavern": "Caverne Polaire",
    "Jabu Jabus Belly": "Ventre de Jabu-Jabu", "Shadow Temple": "Temple de l'Ombre",
    "Spirit Temple": "Temple de l'Esprit", "Thieves Hideout": "Repaire des voleurs",
    "Treasure Chest Game": "Chasse aux trésors", "Water Temple": "Temple de l'Eau",
}
_COUNTS = {
    "Arrows": "Flèches", "Bomb": "Bombe", "Bombs": "Bombes", "Bombchus": "Missiles",
    "Deku Nuts": "Noix Mojo", "Deku Seeds": "Graines Mojo", "Deku Stick": "Bâton Mojo",
    "Deku Sticks": "Bâtons Mojo", "Rupee": "Rubis", "Rupees": "Rubis",
}
_PURCHASES = {
    "Blue Fire": "Flamme bleue", "Bottle Bug": "Insecte", "Deku Shield": "Bouclier Mojo",
    "Fairy's Spirit": "Fée", "Fish": "Poisson", "Goron Tunic": "Tunique Goron",
    "Green Potion": "Potion verte", "Half Milk": "Demi-bouteille de lait", "Heart": "Cœur de vie",
    "Hylian Shield": "Bouclier Hylien", "Magic Jar": "Jarre de magie", "Poe": "Esprit",
    "Zora Tunic": "Tunique Zora",
}
_PURCHASE_COUNTS = {
    "Arrows": "Flèches", "Bombchu": "Missiles", "Bombs": "Bombes", "Deku Nut": "Noix Mojo",
    "Deku Seeds": "Graines Mojo", "Deku Stick": "Bâtons Mojo",
}


def _french(name):
    if name in _FR:
        return _FR[name]
    match = re.fullmatch(r"(Boss Key|Small Key|Map|Compass) \((.+)\)", name)
    if match and match[2] in _DUNGEONS:
        return f"{_FR[match[1]]} ({_DUNGEONS[match[2]]})"
    match = re.fullmatch(r"(.+?) \((\d+)\)", name)
    if match and match[1] in _COUNTS:
        return f"{_COUNTS[match[1]]} ({match[2]})"
    match = re.fullmatch(r"Rupees? \(Treasure Chest Game\) \((\d+)\)", name)
    if match:
        return f"Rubis (Chasse aux trésors) ({match[1]})"
    if name.startswith("Buy "):
        purchase = name[4:]
        if purchase in _PURCHASES:
            return _PURCHASES[purchase] + " (achat)"
        match = re.fullmatch(r"(.+?) \((\d+)\)(?: for (\d+) Rupees)?", purchase)
        if match and match[1] in _PURCHASE_COUNTS:
            price = f", {match[3]} rubis" if match[3] else ""
            return f"{_PURCHASE_COUNTS[match[1]]} ({match[2]}, achat{price})"
        if purchase == "Red Potion for 30 Rupees":
            return "Potion rouge (achat, 30 rubis)"
    raise KeyError("Missing French Zelda item name: " + name)


def item_name(canonical, language="en", *, game=None):
    """Localize known Zelda display names; leave foreign and unknown names intact."""
    code = str(language).lower().replace("_", "-")
    french = code.startswith("fr") or code.endswith("fr")
    if not french or canonical not in ITEM_IDS or game not in (None, GAME, LEGACY_GAME):
        return canonical
    return _french(canonical)


def item_names():
    """Canonical AP name -> bilingual labels, for the native session file."""
    return {name: {"en": name, "fr": _french(name)} for name in ITEM_IDS}
