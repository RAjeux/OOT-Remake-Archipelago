"""Versioned opt-in settings applied after the compatible native seed builder.

These values never enter an OOTRR 0.8.1 settings string.  A player file without
``features`` keeps its released preparation path; new rooms carry schema 1.
"""
import copy
import re


# IDs are the adapted engine's cosmetics::colors::ITEMS, not game paths.
COLOR_PARTS = {
    "kokiri": ("Kokiri tunic", "Tunique Kokiri"),
    "kokiri_pants": ("Kokiri child pants", "Pantalon Kokiri enfant"),
    "kokiri_shirt": ("Kokiri undershirt", "Sous-tunique Kokiri"),
    "kokiri_belt": ("Kokiri belts and child boots", "Ceintures Kokiri et bottes enfant"),
    "feathers": ("Kokiri feathers", "Plumes Kokiri"),
    "goron": ("Goron tunic", "Tunique Goron"),
    "goron_trim": ("Goron gold trim", "Bordures dorées Goron"),
    "goron_belt": ("Goron belt", "Ceinture Goron"),
    "goron_beads": ("Goron beads", "Perles Goron"),
    "zora": ("Zora tunic", "Tunique Zora"),
    "zora_belt": ("Zora belt sash", "Ceinture Zora"),
    "zora_shirt": ("Zora undershirt", "Sous-tunique Zora"),
    "zora_scales": ("Zora scale trim", "Bordures d'écailles Zora"),
    "boots": ("Boots", "Bottes"), "gloves": ("Gloves", "Gants"),
    "leather_trim": ("Red leather trim", "Bordures de cuir rouge"),
    "hair": ("Hair", "Cheveux"),
    "kokiri_sword": ("Kokiri Sword", "Épée Kokiri"),
    "master_sword": ("Master Sword", "Épée de Légende"),
    "biggoron_sword": ("Biggoron Sword", "Épée Biggoron"),
    "deku_shield": ("Deku Shield", "Bouclier Mojo"),
    "hylian_shield": ("Hylian Shield", "Bouclier Hylien"),
    "mirror_shield": ("Mirror Shield", "Bouclier Miroir"),
    "boomerang": ("Boomerang", "Boomerang"),
    "gauntlets": ("Gauntlets", "Gantelets"),
    "navi": ("Navi", "Navi"), "hearts": ("Recovery hearts", "Cœurs de soin"),
}


def validate_mapping(name, value):
    """Allow structured colour picks and canonical placements, never paths/code."""
    if not isinstance(value, dict) or len(value) > (len(COLOR_PARTS) if name == "cosmetic_colors" else 256):
        raise ValueError(name + " must be a bounded dictionary.")
    result = {}
    if name == "item_plando":
        from .catalog import ITEM_IDS, LOCATION_IDS
    for key, selected in value.items():
        if not isinstance(key, str) or not isinstance(selected, str):
            raise ValueError(name + " needs text keys and values.")
        if name == "cosmetic_colors":
            if key not in COLOR_PARTS or (selected not in {"original", "random"}
                                         and re.fullmatch(r"#[0-9a-fA-F]{6}", selected) is None):
                raise ValueError("Unsupported cosmetic colour: " + key)
            selected = selected.upper() if selected.startswith("#") else selected
        elif name == "item_plando":
            if key not in LOCATION_IDS or selected not in ITEM_IDS:
                raise ValueError("Unsupported planned location or item: " + key + " = " + selected)
        else:
            raise ValueError("Unsupported structured setting: " + name)
        result[key] = selected
    return result


def _toggle(name, description, group="Quality of life"):
    return dict(id=name, kind="toggle", default=False, description=description,
                group=group, label=name.replace("_", " ").title())


def _range(name, maximum, description):
    return dict(id=name, kind="range", default=maximum, min=0, max=maximum, step=1,
                description=description, group="Goal", label=name.replace("_", " ").title())


def _difficulty_number(name, default, minimum, maximum, step, description):
    return dict(id=name, kind="range", default=default, min=minimum, max=maximum, step=step,
                description=description, group="Difficulty", label=name.replace("_", " ").title())


LEGACY_DIFFICULTY_SPECS = (
    _difficulty_number("enemy_health", 100, 50, 500, 25, "Enemy and boss health as a percentage. 100 keeps normal health. Applied once by the current difficulty adapter."),
    _difficulty_number("enemy_damage", 100, 50, 500, 25, "Enemy attack damage as a percentage. Traps and falls are unaffected by this setting; Global damage taken applies separately."),
    _difficulty_number("enemy_speed", 100, 75, 200, 5, "Enemy movement speed as a percentage. Some authored animation timings keep their normal pace."),
    _difficulty_number("more_enemies", 100, 100, 1000, 50, "Enemy density as a percentage, with native per-area limits and supported special encounters. 100 keeps normal density."),
    *(_toggle(name, description + " Experimental.", "Difficulty") for name, description in (
        ("enemy_regen", "Living enemies recover health after ten seconds without taking a hit."),
        ("enemy_backup", "Fighting enemies can call for reinforcements during a prolonged fight; harmless Scrubs do not."),
        ("no_heart_drops", "Ordinary random drops no longer give recovery hearts."),
        ("no_gossip_fairies", "Gossip stones no longer spawn fairies."),
        ("no_ammo_drops", "Remove ordinary ammunition drops, including Deku sticks and nuts, seeds, arrows, bombs and Bombchus. Shuffled AP rewards and shop purchases are separate."),
        ("lose_heart_on_death", "After Game Over, lose one heart container if you have more than three. A starting health value below three is not raised."),
        ("no_bottles_in_combat", "Prevent bottle use during combat; a bottled fairy can still revive Link."),
        ("no_z_targeting", "Disable enemy targeting; interactions remain available."),
        ("no_dupe_items", "Native captures and refills reject contents already held in another bottle."),
        ("enemies_respawn_sooner", "Ordinary enemies return after leaving their room or area."),
        ("boss_minibosses", "Add a miniboss when a compatible native boss fight starts; remove it when the boss falls."),
        ("boss_minions", "Add lesser enemies when a compatible native boss fight starts; remove them when the boss falls."),
        ("bean_pitch", "Compatibility with older configurations: restore the Bean Seller's difficulty dialogue."),
        ("zora_ambush", "Compatibility with older configurations: add the separate Zora's Domain Skulltula ambush. Current increased enemy density already includes it."),
        ("enemy_gates", "Add combat barriers on ten supported overworld paths. They activate only once Link owns the sword for his age. Defeat their nearby guards to pass. Requires a closed forest and original dungeon entrances."),
        ("cucco_revenge", "One hit on a Cucco triggers the Cucco attack."),
        ("enemy_spawn_combo", "Hold both stick buttons and press D-pad Down to spawn a random practice enemy; Up repeats the last kind. Only area-loaded enemies can appear, with at most twelve retained."),
        ("fairy_helps_enemies", "A fairy released from a bottle also heals awake enemies and bosses."),
    )),
)
LEGACY_DIFFICULTY_KEYS = frozenset(spec["id"] for spec in LEGACY_DIFFICULTY_SPECS)
LEGACY_DIFFICULTY_DEFAULTS = {spec["id"]: spec["default"] for spec in LEGACY_DIFFICULTY_SPECS}
QUARANTINED_DEFAULTS = {"volvagia_roams": False, "enemy_sizes": "off", "enemy_sizes_health": False}
QUARANTINED_REASONS = {
    "volvagia_roams": "The roaming boss has an incomplete death sequence; it is disabled until a tested fix exists.",
    "enemy_sizes": "The game ignores placement-only size edits; this option is disabled until a tested fix exists.",
    "enemy_sizes_health": "Size-based health depends on the unavailable enemy-size feature.",
}


def unavailable_setting(name):
    return ValueError("Unavailable setting: " + name + ". " + QUARANTINED_REASONS[name])

DIFFICULTY_SPECS = (
    dict(id="damage_taken", kind="choice", default="normal", choices=("normal", "double", "quadruple", "one_hit"),
         description="Multiply damage received from enemies, traps and falls, or make a hit fatal. Enemy attack damage is a separate multiplier; selecting both multiplies their effects on enemy hits.",
         group="Difficulty", label="Global damage taken"),
    *(_toggle(name, description + " Experimental.", "Difficulty") for name, description in (
        ("unbreakable_bowling_grass", "Keep the Bombchu Bowling lane obstacles unbreakable, so Bombchus must be steered around them."),
        ("harder_talon_cuccos", "Talon's Super Cucco game has fifteen decoys instead of ten, faster-moving Cuccos and twenty seconds instead of thirty."),
        ("fireball_storms", "Add falling fire rocks to supported stretches of Hyrule Field and the child Hyrule Castle garden."),
        ("volvagia_roams", "Add an optional Volvagia encounter to adult Hyrule Field, without progression rewards or replacing the Fire Temple boss. Known upstream limitation: its death sequence can freeze."),
        ("mega_like_likes", "Add three tougher Like Likes in the Deku Tree meadow, with three times the health and a longer grip. They can steal any shield, including the Mirror Shield; defeating one returns a missing shield."),
        ("random_fuses", "Give each bomb a fuse of 1-4 seconds, each Bombchu 3.5-5.25 seconds and each lit Deku Stick 10-24 seconds. Bomb flowers and enemy explosives are unchanged."),
        ("enemy_randomizer", "Replace supported ordinary enemy spawns, in child and adult areas, with types that can be defeated using a sword. This adds no equipment requirement. AP check actors, Gold Skulltulas, bosses and merchants stay unchanged."),
        ("enemy_sizes_health", "Scale enemy health with its randomized size. Enemy health percentage still applies separately."),
    )),
    dict(id="enemy_sizes", kind="choice", default="off", choices=("off", "mild", "wild"),
         description="Keep enemy sizes, use 0.75-1.5 times size, or 0.5-2.5 times size at supported ordinary spawns. Bosses and scripted enemies are excluded and cramped areas are capped. Known upstream limitation: the game can ignore placement-only size edits.",
         group="Difficulty", label="Random enemy sizes"),
    dict(id="shorter_timers", kind="choice", default="off", choices=("off", "three_quarters", "half"),
         description="Keep supported challenge timers, shorten them to three quarters, or halve them. This affects timed challenges, not Archipelago connection or delivery timers.",
         group="Difficulty", label="Shorter challenge timers"),
)


FEATURE_SPECS = (
    dict(id="nocturne_trigger", kind="choice", default="vanilla", choices=("vanilla", "classic"),
         description="Choose what unlocks Sheik's Nocturne in adult Kakariko: clearing Forest, Fire and Water Temples, or holding their three Medallions. Receiving the Medallions through Archipelago counts in Classic mode.",
         group="World", label="Nocturne requirement"),
    dict(id="prelude_trigger", kind="choice", default="vanilla", choices=("vanilla", "classic"),
         description="Choose what unlocks Sheik's Prelude in the Temple of Time: clearing Forest Temple, or holding the Forest Medallion. Receiving it through Archipelago counts in Classic mode.",
         group="World", label="Prelude requirement"),
    _range("bridge_medallions", 6, "Number of Medallions needed when the Rainbow Bridge counts Medallions only. Spiritual Stones do not count."),
    _range("lacs_medallions", 6, "Number of Medallions needed when Zelda awards Ganon's Boss Key in the Light Arrows scene using Medallions only. Spiritual Stones do not count."),
    _toggle("skulls_by_day", "Gold Skulltulas that normally appear only at night also appear during the day. Their access logic no longer requires night.", "World"),
    _toggle("night_skulls_suns_song", "Require the Sun's Song in logic for outdoor night-only Gold Skulltulas, instead of assuming you can wait for night. Unused when Skulltulas also appear by day.", "World"),
    _toggle("free_scarecrow", "Allow adult Link to summon Pierre without first teaching the Scarecrow's Song as a child. An ocarina and the equipment needed at the spot are still required.", "World"),
    _toggle("skip_tower_escape", "After defeating Ganondorf, go to the final Ganon battle without the timed tower escape. The final battle is still required.", "Quality of life"),
    _toggle("skip_area_intros", "Skip first-visit camera tours that only introduce an area or dungeon entrance, while preserving arrivals that advance a quest. The corresponding area maps are marked visited."),
    _toggle("dungeon_key_tracker", "Show dungeon small-key and boss-key information in the native dungeon-map interface."),
    _toggle("dpad_gear_cycle", "Hold D-pad Up to cycle owned masks and the Lens of Truth; hold Down to cycle Iron and Hover Boots. Tapping keeps the normal equip or unequip action."),
    _toggle("fishing_any_fish", "The pond owner awards each age's fishing prize for any fish handed in, regardless of size, species or lure. You still need to catch and hand in a fish."),
    _toggle("faster_ocarina_minigame", "Shorten the Skull Kids' memory game while preserving its reward and completion check."),
    _toggle("dampe_one_race", "Put Dampe's race Heart Piece at the finish of the first race, so a second race is unnecessary. The first race's Hookshot chest stays separate."),
    _toggle("dampe_first_dig", "Guarantee Dampe's Heart Piece on the first dig at a correct big-prize soil, without a second fee. Ordinary soil still gives its normal result."),
    _toggle("disable_low_health_warnings", "Silence the low-health warning sound and warning number effect. Damage and heart recovery keep their normal behavior."),
    _toggle("owl_warps", "Keep the Death Mountain and Lake Hylia owl rides available, and add a child-only ride from Kakariko to Kokiri Forest."),
    _toggle("starting_bunny_hood", "Start with the Bunny Hood owned. Its movement effect is selected separately under Bunny Hood movement.", "Starting inventory"),
    _toggle("shuffle_ice_traps", "Replace a chosen number of ordinary filler pool items with Ice Traps. A trap freezes Link through the native cold effect and grants no inventory item. It can belong to any player's Zelda slot.", "Shuffle"),
    dict(id="ice_trap_count", kind="range", default=6, min=1, max=10, step=1,
         description="Number of filler copies replaced by Ice Traps when their shuffle is enabled. Progression and restricted dungeon rewards are never removed; generation stops if too few eligible filler copies exist.",
         group="Shuffle", label="Ice Trap count"),
    dict(id="cosmetic_color_mode", kind="choice", default="off", choices=("off", "custom", "random", "shared"),
         description="Keep original colours, use the individual picks below, randomize each part, or give all parts shades of one random hue. Colours affect appearance only.",
         group="Cosmetics", label="Colour mode"),
    dict(id="cosmetic_colors", kind="dict", default={},
         description="Choose an original colour, random colour or exact RGB colour for each supported part. Used only in Custom colour mode; unlisted parts keep their original colours.",
         group="Cosmetics", label="Individual colours"),
    dict(id="shuffle_music", kind="choice", default="off", choices=("off", "grouped", "anywhere"),
         description="Keep the game's music, shuffle within native music categories, or mix compatible music across categories. Cutscene audio keeps its dedicated behavior.",
         group="Cosmetics", label="Music shuffle"),
    dict(id="shuffle_sfx", kind="choice", default="off", choices=("off", "grouped", "anywhere"),
         description="Keep sound effects, shuffle similar effects together, or mix compatible effects across categories. This changes sound, not the reward being received.",
         group="Cosmetics", label="Sound-effect shuffle"),
    dict(id="item_plando", kind="dict", default={},
         description="Place chosen items for your Zelda player at chosen enabled checks in your own world. These placements consume real pool copies and must obey access and placement rules. Invalid or impossible plans stop generation instead of adding bonus items.",
         group="Planned placements", label="Planned local placements"),
) + LEGACY_DIFFICULTY_SPECS + DIFFICULTY_SPECS

# Keep the imported source for future repairs, but never advertise known broken
# switches in new YAMLs, the editor or Archipelago's public option types.
FEATURE_SPECS = tuple(spec for spec in FEATURE_SPECS if spec["id"] not in QUARANTINED_DEFAULTS)

FEATURE_BY_ID = {spec["id"]: spec for spec in FEATURE_SPECS}
FEATURE_KEYS = frozenset(FEATURE_BY_ID)
SCHEMA = 1


def feature_config(options):
    """Serialize only non-default additions, without changing the native seed."""
    selected = {name: copy.deepcopy(options.get(name, spec["default"]))
                for name, spec in FEATURE_BY_ID.items()
                if options.get(name, spec["default"]) != spec["default"]}
    if options.get("bridge") == "medallions":
        selected.update(bridge="medallions", bridge_medallions=options.get("bridge_medallions", 6))
    if options.get("shuffle_ganon_bosskey") == "lacs_medallions":
        selected.update(shuffle_ganon_bosskey="lacs_medallions", lacs_medallions=options.get("lacs_medallions", 6))
    return dict(schema=SCHEMA, settings=selected)


def read_features(value):
    """Validate an optional player-file envelope before native resource edits."""
    if value is None:
        return None
    if (not isinstance(value, dict) or set(value) != {"schema", "settings"}
            or type(value["schema"]) is not int or value["schema"] != SCHEMA
            or not isinstance(value["settings"], dict)):
        raise ValueError("Unsupported Archipelago feature settings format.")
    result = {}
    for name, setting in value["settings"].items():
        if name in QUARANTINED_DEFAULTS:
            default = QUARANTINED_DEFAULTS[name]
            if type(setting) is not type(default) or setting != default:
                raise unavailable_setting(name)
            continue
        if name == "bridge":
            valid = setting == "medallions"
        elif name == "shuffle_ganon_bosskey":
            valid = setting == "lacs_medallions"
        elif name not in FEATURE_BY_ID:
            valid = False
        else:
            spec = FEATURE_BY_ID[name]
            if spec["kind"] == "toggle":
                valid = type(setting) is bool
            elif spec["kind"] == "choice":
                valid = isinstance(setting, str) and setting in spec["choices"]
            elif spec["kind"] == "dict":
                try:
                    setting = validate_mapping(name, setting)
                    valid = True
                except ValueError:
                    valid = False
            else:
                valid = (type(setting) is int and spec["min"] <= setting <= spec["max"]
                         and (setting - spec["min"]) % spec.get("step", 1) == 0)
        if not valid:
            raise ValueError("Unsupported Archipelago feature setting: " + str(name))
        result[name] = copy.deepcopy(setting)
    return dict(schema=SCHEMA, settings=result)
