"""Full goal/economy settings must agree in AP logic and native resources."""
from collections import Counter
import copy
import itertools
import json
import os
from pathlib import Path
import sys
import unittest
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'client'))
from ootrr_full.game.goal_settings import (at_least, trial_rule, REWARDS, GANON_KEY,
                                           GANON_KEY_SOURCE, LACS_SOURCE)
from ootrr_full.game.economy_settings import shop_price, shop_wallet, sale_price, wallet, FAIRIES
from ootrr_full.logic import rando_options
from ootrr_full.logic.rules import Logic, TRIALS
from ootrr_full.logic.world import World
from ootrr_full.randomizer.full_randomizer import ap_settings, enabled_sources, source_in_scope
from ootrr_triforce.full_ap import (full_defaults, new_world, validate_full_options,
                                   validate_manifest, translate_legacy_options)


def evaluate(program, values):
    stack = []
    for term in program:
        if term[0] == 0:
            stack.append(term[1] in values)
        elif term[0] == 5:
            stack[-1] = not stack[-1]
        else:
            right, left = stack.pop(), stack.pop()
            stack.append(left and right if term[0] == 3 else left or right)
    return stack[0] if program else True


class FullGoalContractTests(unittest.TestCase):
    def test_permanent_health_loss_rejects_only_active_heart_goals_above_its_floor(self):
        for changed in ({'full_bridge': 'hearts', 'full_bridge_hearts': 4},
                        {'full_lacs_condition': 'hearts', 'full_lacs_hearts': 20},
                        {'full_shuffle_ganon_bosskey': 'lacs_hearts', 'full_lacs_condition': 'vanilla'}):
            with self.assertRaisesRegex(ValueError, 'Heart requirements above three'):
                validate_full_options(dict(full_defaults(), full_lose_heart_on_death=True, **changed))
        for changed in ({}, {'full_bridge': 'hearts', 'full_bridge_hearts': 3},
                        {'full_lacs_condition': 'hearts', 'full_lacs_hearts': 3},
                        {'full_shuffle_ganon_bosskey': 'lacs_tokens', 'full_lacs_condition': 'hearts'}):
            self.assertTrue(validate_full_options(dict(full_defaults(), full_lose_heart_on_death=True,
                                                      **changed))['full_lose_heart_on_death'])

    def test_distinct_reward_threshold_formula_at_every_inventory_boundary(self):
        for count in range(10):
            formula = at_least(REWARDS, count)
            for bits in itertools.product((False, True), repeat=9):
                held = {flag for flag, present in zip(REWARDS, bits) if present}
                self.assertEqual(evaluate(formula, held), sum(bits) >= count, (count, bits))

    def test_native_any_n_trials_and_solver_accept_each_subset_of_exactly_n_trials(self):
        data = World()
        for required in range(7):
            logic = Logic(data, {'trials': required})
            gate = next(rule for target, rule in logic.regions['Ganons Castle Lobby']['exits']
                        if target == 'Ganons Castle Tower')
            for selected in itertools.combinations(TRIALS, required):
                counts = {name + ' Trial Clear': 1 for name in selected}
                state = logic.new_state(counts)
                self.assertTrue(gate(state, state.counts, 'adult'), (required, selected))
                if selected:
                    counts.pop(selected[0] + ' Trial Clear')
                    state = logic.new_state(counts)
                    self.assertFalse(gate(state, state.counts, 'adult'), (required, selected))

    def test_starting_health_is_real_solver_health_without_adding_heart_items(self):
        for hearts in (1, 3, 7, 20):
            options = dict(rando_options.defaults(), starting_hearts=hearts)
            logic = Logic(World(), ap_settings(options, True))
            self.assertEqual(logic.new_state({'Heart Container': 2, 'Piece of Heart': 4}).hearts(), min(20, hearts + 3))

    def test_minimal_pool_keeps_health_that_the_selected_goal_actually_requires(self):
        from ootrr_full.randomizer.full_randomizer import apply_item_pool
        pool = ['Heart Container'] * 8 + ['Piece of Heart'] * 16 + ['Bottle']
        self.assertNotIn('Heart Container', apply_item_pool(pool, 'minimal', set()))
        self.assertEqual(Counter(apply_item_pool(pool, 'minimal', set(), protect_hearts=True))['Heart Container'], 8)

    def test_default_native_health_has_no_inherited_n64_bonus_rewards(self):
        world = new_world(full_defaults(), 'real-native-health')
        state, _, _ = world.c.sweep({}, Counter(world.pool))
        self.assertEqual(state.counts['Piece of Heart'], 33)
        self.assertEqual(state.counts['Heart Container'], 8)
        self.assertEqual(state.hearts(), 19)
        self.assertEqual(world.c.health_goal_added, 0)

    def test_highest_heart_goals_have_real_capacity_with_starting_one_or_three(self):
        for prefix in ('bridge', 'lacs'):
            for start, added in ((3, 3), (1, 11)):
                values = dict(full_defaults(), full_starting_hearts=start, full_item_pool_value='minimal')
                values['full_bridge' if prefix == 'bridge' else 'full_lacs_condition'] = 'hearts'
                values['full_' + prefix + '_hearts'] = 20
                world = new_world(values, 'real-twenty-heart-goal')
                state, _, _ = world.c.sweep({}, Counter(world.pool))
                self.assertEqual(world.c.health_goal_added, added)
                self.assertEqual(state.counts['Piece of Heart'], 33 + added)
                self.assertEqual(state.hearts(), 20)
                self.assertTrue(state.has('Triforce'))
                self.assertEqual(len(world.pool), len(world.names))

    def test_heart_goal_counts_each_real_unshuffled_family_without_duplicate_base_hearts(self):
        for field, value in (('full_shuffle_freestanding_items', 'off'),
                             ('full_shuffle_boss_rewards', False), ('full_shuffle_npc_gifts', False),
                             ('full_shuffle_frog_bug_heart', False)):
            world = new_world(dict(full_defaults(), full_bridge='hearts', full_bridge_hearts=20,
                                   **{field: value}), 'unshuffled-native-health')
            state, _, _ = world.c.sweep({}, Counter(world.pool))
            physical = world.options['starting_hearts'] * 4 + 4 * state.counts['Heart Container'] + state.counts['Piece of Heart']
            self.assertEqual(physical, 80, field)
            self.assertEqual(state.hearts(), 20)
            self.assertTrue(state.has('Triforce'))

    def test_from_pool_health_starts_are_not_counted_twice_by_goal_topup(self):
        from ootrr_full.randomizer.full_randomizer import prepare
        from ootrr_triforce.full_ap import load_catalog
        catalog = load_catalog()
        options = dict(rando_options.defaults(), bridge='hearts', bridge_hearts=20,
                       start_inventory_from_pool={'Piece of Heart': 4})
        full = prepare(World(), options, catalog['groups'], catalog['enemies'], 'starting-heart-pool',
                       extra=catalog['extra'])
        state, _, _ = full.sweep({}, Counter(full.pool))
        self.assertEqual(state.hearts(), 20)
        self.assertEqual(full.start_items.count('Piece of Heart'), 4)
        self.assertEqual(4 * state.counts['Heart Container'] + state.counts['Piece of Heart'] + 12, 80)

    def test_twenty_heart_lacs_key_stays_a_reachable_progression_handover(self):
        world = new_world(dict(full_defaults(), full_starting_hearts=1,
                               full_shuffle_ganon_bosskey='lacs_hearts', full_lacs_hearts=20,
                               full_item_pool_value='minimal'), 'real-lacs-twenty')
        counts = Counter(world.pool)
        counts.pop(GANON_KEY)
        self.assertTrue(world.in_logic[LACS_SOURCE])
        self.assertTrue(world.reachable(LACS_SOURCE, counts))
        self.assertTrue(world.can_hold(LACS_SOURCE, GANON_KEY))

    def test_goal_and_price_values_translate_without_silent_legacy_fallback(self):
        values = translate_legacy_options({'bridge': 'dungeons', 'bridge_rewards': 5, 'trials': 2,
                                           'shuffle_ganon_bosskey': 'keysanity', 'starting_hearts': 4,
                                           'fairy_prices': 'fixed', 'fairy_price_fixed': 150})
        self.assertEqual(values['full_bridge_rewards'], 5)
        self.assertEqual(values['full_trials'], 2)
        self.assertEqual(values['full_shuffle_ganon_bosskey'], 'keysanity')
        self.assertEqual(values['full_fairy_price_fixed'], 150)
        self.assertEqual(translate_legacy_options({'skip_ganon_trials': True})['full_trials'], 0)

    def test_step_slider_rejects_unrepresentable_values(self):
        with self.assertRaisesRegex(ValueError, 'full_enemy_health'):
            validate_full_options(dict(full_defaults(), full_enemy_health=101))
        self.assertEqual(validate_full_options(dict(full_defaults(), full_enemy_health=125))['full_enemy_health'], 125)

    def test_freestanding_pieces_only_keeps_other_ground_pickups_native(self):
        sources = enabled_sources(dict(rando_options.defaults(), shuffle_freestanding_items='pieces'))
        self.assertTrue(source_in_scope({'source': 'freestanding', 'vanilla': 'Piece of Heart'}, sources))
        self.assertFalse(source_in_scope({'source': 'freestanding', 'vanilla': 'Rupees (20)'}, sources))

    def test_ap_ganon_boss_key_has_a_real_own_dungeon_remote_actor(self):
        from ootrr_full.patching.ap_mailbox import records, key_items
        records = records([{'item': GANON_KEY, 'player': 'Friend', 'location': 'Their chest'}])
        self.assertEqual(records[0]['actor'], 'Item_BossKey_Ganon')
        self.assertEqual(key_items(records), [GANON_KEY])

    def test_new_ganon_key_check_is_added_without_renumbering_old_checks(self):
        base = new_world(full_defaults(), 'full-goals-test')
        shuffled = new_world(dict(full_defaults(), full_shuffle_ganon_bosskey='keysanity'), 'full-goals-test')
        self.assertEqual(set(shuffled.names) - set(base.names), {GANON_KEY_SOURCE})
        self.assertEqual(Counter(shuffled.pool)[GANON_KEY], 1)
        self.assertNotIn(GANON_KEY, shuffled.local_only)
        self.assertTrue(shuffled.reach(Counter(shuffled.pool))[1])
        missing = Counter(shuffled.pool)
        missing.pop(GANON_KEY)
        self.assertFalse(shuffled.reach(missing)[1])

    def test_lacs_key_requires_its_exact_real_handover(self):
        world = new_world(dict(full_defaults(), full_shuffle_ganon_bosskey='lacs_dungeons',
                               full_lacs_rewards=5), 'full-lacs-test')
        self.assertEqual(world.options['lacs_condition'], 'dungeons')
        self.assertEqual(Counter(world.pool)[GANON_KEY], 1)
        self.assertTrue(world.can_hold(LACS_SOURCE, GANON_KEY))
        self.assertFalse(world.can_hold(LACS_SOURCE, None))
        self.assertFalse(world.can_hold(GANON_KEY_SOURCE, GANON_KEY))
        self.assertTrue(world.reach(Counter(world.pool))[1])

    def test_reward_restriction_is_explicit_and_default_stays_full_multiworld(self):
        world = new_world(dict(full_defaults(), full_dungeon_reward_placement='dungeons'), 'reward-restriction')
        for item in ('Kokiri Emerald', 'Forest Medallion', 'Light Medallion'):
            self.assertIn(item, world.boss_rewards)
            self.assertNotIn(item, world.local_only)
            for gid, entry in world.c.shuffled.items():
                if entry['source'] != 'boss':
                    self.assertFalse(world.can_hold(gid, item), (item, gid))
        self.assertEqual(full_defaults()['full_dungeon_reward_placement'], 'anywhere')

    def test_open_fortress_removes_skipped_check_but_keeps_exactly_one_card(self):
        for shuffled in (False, True):
            world = new_world(dict(full_defaults(), full_gerudo_fortress='open',
                                   full_shuffle_gerudo_card=shuffled), 'open-fortress-card')
            self.assertNotIn('gerudo_card#Hideout Gerudo Membership Card', world.names)
            self.assertEqual(Counter(world.pool)['Gerudo Membership Card'], int(shuffled))
            self.assertEqual(world.c.start_items.count('Gerudo Membership Card'), int(not shuffled))
            self.assertEqual(len(world.pool), len(world.names))
            self.assertTrue(world.reach(Counter(world.pool))[1])

    def test_songless_door_requires_its_stones_without_an_ocarina(self):
        for mode, stones in (('all', {'Kokiri Emerald': 1, 'Goron Ruby': 1, 'Zora Sapphire': 1}),
                             ('vanilla', {'Goron Ruby': 1, 'Zora Sapphire': 1}), ('song', {})):
            logic = Logic(World(), {'door_of_time_requirement': mode, 'door_of_time_song': False})
            rule = next(rule for target, rule in logic.regions['Temple of Time']['exits']
                        if target == 'Beyond Door of Time')
            state = logic.new_state(stones)
            self.assertTrue(rule(state, state.counts, 'child'))
            if stones:
                state = logic.new_state({})
                self.assertFalse(rule(state, state.counts, 'child'))

    def test_unshuffled_open_fortress_card_is_in_real_ap_native_start_plan(self):
        from ootrr_triforce.full_ap import load_catalog
        from ootrr_full.randomizer.full_randomizer import plan_assigned
        values = dict(full_defaults(), full_gerudo_fortress='open', full_shuffle_gerudo_card=False)
        world = new_world(values, 'native-open-card')
        catalog = load_catalog()
        result = plan_assigned(World(), world.options, catalog['groups'], catalog['enemies'],
                               'native-open-card', dict.fromkeys(world.names, 'Rupees (5)'),
                               extra=catalog['extra'])
        self.assertEqual(result['starting'], [{'item': 'Gerudo Membership Card', 'actor': 'Item_Token_Gerudo'}])


class FullEconomyContractTests(unittest.TestCase):
    def test_shuffled_vendors_keep_missing_shields_in_the_ap_pool_without_default_duplicates(self):
        regular = new_world(full_defaults(), 'shop-shield-pool-baseline')
        self.assertEqual(Counter(regular.pool)['Deku Shield'], 4)
        self.assertEqual(Counter(regular.pool)['Hylian Shield'], 1)
        native = new_world(dict(full_defaults(), full_shuffle_chests=False,
                                full_shuffle_ganon_bosskey='vanilla'), 'native-chests-need-shop-shields')
        self.assertEqual(Counter(native.pool)['Deku Shield'], 1)
        self.assertEqual(Counter(native.pool)['Hylian Shield'], 1)
        reached, victory = native.reach(Counter(native.pool))
        self.assertTrue(victory)
        self.assertEqual([name for gid, name in native.names.items() if native.vnames[gid] not in reached], [])

    def test_no_ammo_drops_uses_real_stock_and_preserves_renewable_shop_ammunition(self):
        from ootrr_full.logic.rules import vanilla_placements
        from ootrr_full.randomizer.full_randomizer import shop_purchase
        data = World()
        logic = Logic(data, {'no_ammo_drops': True})
        self.assertFalse(set(vanilla_placements(data, logic).values()) &
                         {'Deku Stick Drop', 'Deku Nut Drop', 'Bombchu Drop'})
        for expression, dropped, owned, bought in (
                ('Sticks', 'Deku Stick Drop', 'Deku Stick (1)', 'Buy Deku Stick (1)'),
                ('Nuts', 'Deku Nut Drop', 'Deku Nuts (5)', 'Buy Deku Nut (5)'),
                ('has_bombchus', 'Bombchu Drop', 'Bombchus (5)', 'Buy Bombchu (5)')):
            rule = logic.compile(expression)
            for item, expected in ((dropped, False), (owned, True), (bought, True)):
                state = logic.new_state({item: 1, 'Bomb Bag': 1})
                self.assertEqual(rule(state, state.counts, 'child'), expected, (expression, item))
        with self.assertRaisesRegex(ValueError, 'retained shop refills'):
            validate_full_options(dict(full_defaults(), full_no_ammo_drops=True))
        world = new_world(dict(full_defaults(), full_no_ammo_drops=True, full_shopsanity='8'), 'renewable-native-ammunition')
        ammunition = {gid: entry for gid, entry in world.c.matches.items() if entry['source'] == 'shop'
                      and entry['before'].startswith(('Shop_Arrow', 'Shop_Bomb', 'Shop_Deku'))}
        needed = {shop_purchase(entry['vanilla']) for entry in ammunition.values()}
        retained = {shop_purchase(entry['vanilla']) for gid, entry in ammunition.items() if gid not in world.c.shuffled}
        self.assertTrue(needed <= retained)
        self.assertTrue(world.reach(Counter(world.pool))[1])
        ordinary = Logic(data)
        ordinary.compile('Sticks')
        ordinary.compile('Nuts')
        self.assertFalse({'Deku Stick (1)', 'Deku Nuts (5)', 'Deku Nuts (10)'} & ordinary.referenced)

    def test_ap_owned_shields_work_without_a_native_shop_purchase_event(self):
        logic = Logic(World())
        for item, age in (('Deku Shield', 'child'), ('Hylian Shield', 'adult')):
            state = logic.new_state({item: 1})
            rule = logic.compile('can_shield')
            self.assertTrue(rule(state, state.counts, age), (item, age))
        world = new_world(full_defaults(), 'actual-ap-shields')
        self.assertTrue({'Deku Shield', 'Hylian Shield'} <= world.progression)

    def test_random_native_price_is_deterministic_and_never_changes_its_wallet_tier(self):
        for mode, tier in (('starting', 0), ('affordable', 0), ('adult', 1), ('giant', 2)):
            options = dict(rando_options.defaults(), shopsanity_prices=mode)
            for index in range(100):
                actor = 'Shop_Rando_Item_' + str(index)
                value = shop_price(options, 'real-ap-seed', actor)
                self.assertEqual(shop_price(options, 'real-ap-seed', actor), value)
                self.assertEqual(wallet(value), tier)
                self.assertEqual(shop_wallet(options), tier)

    def test_fixed_price_boundaries_use_the_exact_native_wallet_capacity(self):
        for amount, tier in ((0, 0), (99, 0), (100, 0), (200, 0), (201, 1), (500, 1), (501, 2), (1000, 2)):
            options = dict(rando_options.defaults(), shopsanity_prices='fixed', shop_price_fixed=amount)
            self.assertEqual(shop_price(options, 'seed', 'actor'), amount)
            self.assertEqual(shop_wallet(options), tier)

    def test_wallet_guard_counts_both_upgrades(self):
        logic = Logic(World())
        self.assertFalse(logic.accessible(logic.new_state({'Progressive Wallet': 1}), 'Wallet|2'))
        self.assertTrue(logic.accessible(logic.new_state({'Progressive Wallet': 2}), 'Wallet|2'))

    def test_native_default_price_modes_do_not_change_published_runtime(self):
        options = rando_options.defaults()
        self.assertEqual(shop_price(options, 'seed', 'actor'), 10)
        for prefix in ('merchant', 'fairy'):
            self.assertEqual(sale_price(options, prefix, 200), 200)


ROMFS = os.environ.get('OOT_ROMFS') or os.environ.get('OOTRR_ROMFS')


@unittest.skipUnless(ROMFS, 'Set OOT_ROMFS for native 1.1.1 resource validation.')
class NativeGoalSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from ootrr_triforce import app_runtime
        app_runtime._resource_override = ROOT / 'dist'
        from ootrr_triforce.mod_codec import Codec
        cls.romfs = Path(ROMFS)
        cls.codec = Codec((cls.romfs / 'Pack/ZsDic.pack.zs').read_bytes())

    def read(self, path):
        raw = (self.romfs / path).read_bytes()
        return self.codec.decode(raw) if path.endswith('.zs') else raw

    def test_native_barrier_counter_and_trial_completion_flags_for_every_count(self):
        from ootrr_triforce.full_settings import _trial_defaults, _trials, GAMEDATA, TRIAL_FLOW
        from ootrr_full.patching.game_defaults import set_new_game_defaults, read_defaults
        raw = self.read(GAMEDATA)
        for count in range(6):
            values = _trial_defaults(count)
            changed = set_new_game_defaults(raw, values)
            self.assertEqual(read_defaults(changed, values), values)
        changed = _trials(self.read(TRIAL_FLOW))
        from ootrr_full.patching.progressive import FlowEditor
        event = next(e for e in FlowEditor(changed, 'test').chart.events if e.name == 'Event606')
        self.assertEqual(set(event.data.cases), {1})

    def test_counted_bridge_and_lacs_conditions_use_real_saved_item_flags(self):
        from ootrr_triforce.full_settings import _expressions, GAMEDATA
        from ootrr_full.patching import story_fixes
        from ootrr_full.formats import byml_codec
        from ootrr_full.patching.soul_adapter import murmur3
        raw = story_fixes.scene_expressions(self.read(GAMEDATA))[0]
        for mode in ('open', 'stones', 'medallions', 'dungeons', 'tokens', 'hearts'):
            changed, expressions = _expressions(raw, dict(rando_options.defaults(), bridge=mode,
                                                         lacs_condition='dungeons', lacs_rewards=5))
            table = {int(e['Hash']): e for e in byml_codec.load(changed)['root']['Data']['BoolExp']}
            self.assertIn(murmur3(story_fixes.BRIDGE_READY), table)
            self.assertEqual(len(expressions), 2)

    def test_numeric_goal_literals_keep_the_actual_game_int32_type(self):
        from ootrr_triforce.full_settings import _expressions, GAMEDATA
        from ootrr_full.patching import story_fixes
        from ootrr_full.formats import byml_codec
        from ootrr_full.patching.soul_adapter import murmur3
        raw = story_fixes.scene_expressions(self.read(GAMEDATA))[0]
        for mode, amount in (('tokens', 50), ('hearts', 80)):
            changed, _ = _expressions(raw, dict(rando_options.defaults(), bridge=mode))
            data = byml_codec.load(changed)['root']['Data']['BoolExp']
            expression = next(row for row in data if int(row['Hash']) == murmur3(story_fixes.BRIDGE_READY))
            values = expression['Values']
            self.assertIs(type(values[1][1]), int)
            self.assertEqual(values[1][1], amount)
            self.assertEqual([int(values[i][0]) for i in range(3)], [18, 16, 5])

    def test_native_lacs_trigger_uses_threshold_reader_without_losing_sensor_or_once_guards(self):
        from ootrr_triforce.full_settings import _lacs_module, LACS_EXPRESSION
        from ootrr_full.patching import story_fixes
        import ainb
        raw = story_fixes.light_arrows_on_medallions(self.read(story_fixes.LIGHT_ARROWS_MODULE))[0]
        changed = _lacs_module(raw)
        nodes = ainb.AINB.from_binary(changed).as_dict()['Nodes']
        self.assertEqual(nodes[3]['Name'], 'HoldActorObserverBySensorHitInfo')
        self.assertEqual(nodes[7]['Name'], 'InvBool.module')
        for index in (5, 6):
            self.assertEqual(nodes[index]['Name'], 'HoldGameDataGetBoolExpSimple')
            self.assertEqual(nodes[index]['Parameters']['Inputs']['String'][0]['Default Value'], LACS_EXPRESSION)

    def test_fairy_native_display_check_and_actual_debit_match(self):
        from ootrr_triforce.full_settings import _fairy_display, _flow_prices, GAMEDATA
        from ootrr_full.patching.progressive import FlowEditor
        from ootrr_full.formats import byml_codec
        from ootrr_full.patching.soul_adapter import murmur3
        prices = {row[0]: 150 for row in FAIRIES}
        raw = _fairy_display(self.read(GAMEDATA), prices)
        integers = {int(e['Hash']): e for e in byml_codec.load(raw)['root']['Data']['Int']}
        for index, (name, flow, native, check, pay) in enumerate(FAIRIES, 1):
            changed = _flow_prices(self.read('Event/EventFlow/' + flow + '.bfevfl.zs'),
                                   {check: {'Value': (native, 150)}, pay: {'Value': (-native, -150)}})
            events = {e.name: e for e in FlowEditor(changed, 'test').chart.events}
            self.assertEqual(events[check].data.params.data['Value'], 150)
            self.assertEqual(events[pay].data.params.data['Value'], -150)
            self.assertEqual(integers[murmur3('GreatFairy_Price' + str(index))]['DefaultValue'], 150)

    def test_price_tiers_match_actual_remake_wallet_packs(self):
        from ootrr_full.formats import byml_codec
        from ootrr_full.formats.inspect_resources import sarc
        for name, capacity, tier in (('Small', 200, 0), ('Medium', 500, 1), ('Large', 1000, 2)):
            files = sarc(self.read(f'Pack/Actor/Pouch_Wallet_{name}.pack.zs'))
            rows = [byml_codec.load(raw)['root'] for path, raw in files.items() if '/ExpansionMaxNumActor/' in path]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['MaxNum'], capacity)
            self.assertEqual(wallet(capacity), tier)

    def test_songless_door_keeps_native_actor_and_uses_matching_stone_expression(self):
        from ootrr_triforce.full_settings import _songless_door, _expressions, GAMEDATA, DOOR_EXPRESSION
        from ootrr_full.patching import story_fixes
        from ootrr_full.formats import byml_codec
        from ootrr_full.patching.soul_adapter import murmur3
        import ainb
        raw = story_fixes.door_opens_on_saved_flag(self.read(story_fixes.DOOR_MODULE))[0]
        original = ainb.AINB.from_binary(raw).as_dict()
        actual = ainb.AINB.from_binary(_songless_door(raw)).as_dict()
        self.assertEqual(actual['Nodes'][3], original['Nodes'][3])
        reader = actual['Nodes'][6]
        self.assertEqual(reader['Name'], 'HoldGameDataGetBoolExpSimple')
        self.assertEqual(reader['Parameters']['Inputs']['String'][0]['Default Value'], DOOR_EXPRESSION)
        raw = story_fixes.scene_expressions(self.read(GAMEDATA))[0]
        changed, _ = _expressions(raw, dict(rando_options.defaults(), door_of_time_song=False,
                                           door_of_time_requirement='all'))
        row = next(row for row in byml_codec.load(changed)['root']['Data']['BoolExp']
                   if int(row['Hash']) == murmur3(DOOR_EXPRESSION))
        for stone in ('Forest', 'Fire', 'Water'):
            self.assertIn([0, murmur3('IsGet.Item_Stone_' + stone)], row['Values'])

    def test_open_fortress_sets_real_rescue_flags_without_granting_shuffled_card(self):
        from ootrr_triforce.full_settings import _open_fortress, GAMEDATA
        from ootrr_full.patching import game_defaults, gerudo_fortress
        changed = {}
        read = lambda path: changed.get(path) or self.read(path)
        report = _open_fortress(dict(rando_options.defaults(), gerudo_fortress='open',
                                    shuffle_gerudo_card=True), read, changed.__setitem__)
        self.assertEqual(game_defaults.read_defaults(changed[GAMEDATA], report['defaults']), report['defaults'])
        self.assertEqual(game_defaults.read_defaults(changed[GAMEDATA], [gerudo_fortress.CARD]),
                         {gerudo_fortress.CARD: False})
        self.assertEqual(report['defaults']['GerudoFortress_WarpPoint04_ClearEvent'], True)
        self.assertIn(gerudo_fortress.CELL_MODULE, changed)


if __name__ == '__main__':
    unittest.main()
