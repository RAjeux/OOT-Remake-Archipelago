"""Independent native comfort/challenge patches, without a second item fill.

Defaults deliberately keep every new patch off. Published full-network seeds
therefore retain their settings identity and their authored game behaviour.
"""

STATS = {
    'enemy_health': (50, 500, 25, 'Enemy health', 'Enemy and boss health as a percentage.'),
    'enemy_damage': (50, 500, 25, 'Enemy attack damage', 'Enemy attack damage as a percentage. Traps and falls retain their native damage.'),
    'enemy_speed': (75, 200, 5, 'Enemy speed', 'Native enemy movement and attack waits as a percentage. Animation-only movement retains its original pace.'),
    'more_enemies': (100, 1000, 50, 'Enemy density', 'Add native enemies within each supported area\'s limits. Existing reward sources and their AP identities stay unchanged.'),
}
FLAGS = {
    'enemy_regen': ('Enemy regeneration', 'Living enemies slowly recover health after avoiding damage.'),
    'enemy_backup': ('Enemy reinforcements', 'Supported ordinary enemies can call one native helper during prolonged combat.'),
    'enemy_gates': ('Enemy passage gates', 'Native barriers guard selected overworld passages until their nearby enemies are defeated. Archipelago includes their combat and soul requirements.'),
    'no_heart_drops': ('No random heart drops', 'Random drops no longer produce recovery hearts. Placed AP items and heart upgrades retain their placements.'),
    'no_gossip_fairies': ('No gossip-stone fairies', 'Playing a song to a gossip stone no longer summons a healing fairy.'),
    'no_ammo_drops': ('No random ammunition drops', 'Remove random ammunition drops. Placed AP items remain available. Use numbered Shopsanity to retain renewable shop stock; shuffling every shop item is incompatible.'),
    'lose_heart_on_death': ('Lose a heart on Game Over', 'Continuing after Game Over removes one heart container, down to three hearts, using the native save flow. Cannot be combined with a Rainbow Bridge or Light Arrows scene requirement above three hearts.'),
    'no_bottles_in_combat': ('No bottles in combat', 'Native battle music blocks bottle use during combat.'),
    'no_z_targeting': ('No enemy targeting', 'Disable enemy lock-on while retaining talk and object interactions.'),
    'no_dupe_items': ('No duplicate bottle contents', 'Native captures and ordinary refills reject contents already held in another bottle.'),
    'enemies_respawn_sooner': ('Faster enemy respawn', 'Ordinary enemies return after leaving their room or area.'),
    'boss_minibosses': ('Boss arena minibosses', 'Add a native miniboss to supported boss arenas.'),
    'boss_minions': ('Boss arena minions', 'Add native lesser enemies to supported boss arenas.'),
    'bean_pitch': ('Bean seller hints', 'The Bean Seller occasionally mentions enabled native challenge features.'),
    'zora_ambush': ('Zora cave ambush', 'Add a native Skulltula ambush to supported Zora\'s Domain caves.'),
    'cucco_revenge': ('Immediate Cucco revenge', 'One hit on a Cucco triggers its native attack.'),
    'fairy_helps_enemies': ('Fairies heal enemies', 'A released fairy also heals awake nearby enemies and bosses.'),
}
CHOICES = {
    'navi_return': (('off', 'dungeons', 'everywhere'), 'Navi return destinations',
                    'Navi offers a native return to a dungeon entrance, or also to Kokiri Forest/the Temple of Time outside dungeons.'),
    'bunny_hood': (('off', 'speed', 'jump'), 'Bunny Hood movement',
                   'Use native Bunny Hood movement parameters for faster running, or running and jumping. These shortcuts do not loosen progression rules.'),
}
WORLD_FLAGS = {
    'jabu_open': ('Open Jabu-Jabu', 'Jabu-Jabu opens without a fish after King Zora moves aside.'),
    'skip_epona_race': ('Skip the Epona race', 'Playing Epona\'s Song as adult in a riding area registers and calls Epona through her native event.'),
    'skip_mask_quest': ('Complete the mask quest', 'All masks can be borrowed once the Happy Mask Shop opens, without completing the mask-selling chain.'),
    'early_beds': ('Early bed time selection', 'Use native beds to choose morning or night before meeting Zelda.'),
}
QOL_FLAGS = {
    'skip_first_pickup_text': ('Skip first pickup messages', 'Skip first-time messages for ordinary rupees, recovery hearts, magic jars, arrows and seeds. Equipment and quest items retain their messages.'),
    'deku_bridge_safe': ('Stable Deku Tree bridge', 'The two native bridge pieces in the Deku Tree slingshot room no longer fall. A bridge already broken in a save stays broken.'),
}


def unrecorded():
    """Neutral values omitted from seed identities made before these adapters."""
    return {**dict.fromkeys(STATS, 100), **dict.fromkeys(FLAGS, False),
            **dict.fromkeys(CHOICES, 'off'), **dict.fromkeys(WORLD_FLAGS, False),
            **dict.fromkeys(QOL_FLAGS, False), 'faster_blocks': False}


def options(Option, OK):
    result = [Option('faster_blocks', 'Quality of life', 'Faster block movement',
                     ((False, OK), (True, OK)), False,
                     'Push and pull native blocks twice as fast; their stops remain unchanged.', kind='bool')]
    for name, (values, label, help_text) in CHOICES.items():
        result.append(Option(name, 'Quality of life', label, tuple((v, v.title(), OK) for v in values),
                             'off', help_text))
    for name, (low, high, step, label, help_text) in STATS.items():
        result.append(Option(name, 'Difficulty', label, None, 100, help_text, kind='int',
                             minimum=low, maximum=high, supported_ints=tuple(range(low, high + 1, step))))
    for name, (label, help_text) in FLAGS.items():
        result.append(Option(name, 'Difficulty', label, ((False, OK), (True, OK)), False, help_text, kind='bool'))
    for name, (label, help_text) in WORLD_FLAGS.items():
        result.append(Option(name, 'World', label, ((False, OK), (True, OK)), False, help_text, kind='bool'))
    for name, (label, help_text) in QOL_FLAGS.items():
        result.append(Option(name, 'Quality of life', label, ((False, OK), (True, OK)), False, help_text, kind='bool'))
    return result


def native_values(options):
    """Whitelist for resource-only Rust transforms; never pass shuffle settings."""
    values = {name: options.get(name, default) for name, default in unrecorded().items()}
    values.update(starting_hearts=options.get('starting_hearts', 3),
                  open_forest='open' if options.get('open_forest', True) else 'closed',
                  open_kakariko='closed' if options.get('open_kakariko', 'closed') == 'zelda' else options.get('open_kakariko', 'closed'),
                  # Only the stock-preservation context is used by challenge descriptions.
                  shuffle_shops='off' if options.get('shopsanity', 'off') == 'off' else 'deals_1',
                  # Coupled dungeon doors do not move these overworld passages.
                  # AP applies the matching gate rules; never run another shuffle.
                  enemy_spawn_combo=False, shuffle_entrances='off')
    return values
