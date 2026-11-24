"""Shared full-network goal contract; contains no resource or AP imports.

The default contract is the one released in 0.11. Additional settings are
optional in older manifests and always use their historical behaviour there.
"""
from itertools import combinations

GANON_KEY = 'Boss Key (Ganons Castle)'
GANON_KEY_SOURCE = 'InsideGanonCastle#17092385671602176550'
LACS_SOURCE = 'quest#ToT Light Arrows Cutscene'
TRIALS = ('Forest', 'Fire', 'Water', 'Shadow', 'Spirit', 'Light')
STONES = ('IsGet.Item_Stone_Forest', 'IsGet.Item_Stone_Fire', 'IsGet.Item_Stone_Water')
MEDALLIONS = tuple('IsGet.Item_Medal_' + name for name in
                  ('Light', 'Forest', 'Fire', 'Water', 'Spirit', 'Shadow'))
REWARDS = STONES + MEDALLIONS
REWARD_ITEMS = ('Kokiri Emerald', 'Goron Ruby', 'Zora Sapphire', 'Light Medallion',
                'Forest Medallion', 'Fire Medallion', 'Water Medallion', 'Shadow Medallion', 'Spirit Medallion')
NEW_DEFAULTS = {
    'bridge_stones': 3, 'bridge_medallions': 6, 'bridge_rewards': 9,
    'lacs_condition': 'vanilla', 'lacs_stones': 3, 'lacs_medallions': 6, 'lacs_rewards': 9,
    'starting_hearts': 3,
    'dungeon_reward_placement': 'anywhere',
    'shuffle_entrances': 'off',
    'chest_scope': 'all', 'pot_scope': 'all', 'crate_scope': 'all',
    'rock_scope': 'all', 'bush_scope': 'all',
    'bridge_tokens': 50, 'bridge_hearts': 20, 'lacs_tokens': 50, 'lacs_hearts': 20,
    'shuffle_treasure_reward': 'inherit',
    'door_of_time_song': True,
    'individual_smallkeys': False,
}


def trial_rule(required):
    """Any N completed trials, matching the native decrementing barrier counter."""
    if not 0 <= required <= len(TRIALS):
        raise ValueError('Ganon trial count must be between zero and six.')
    if required == 0:
        return 'True'
    return ' or '.join('(' + ' and '.join(repr(name + ' Trial Clear') for name in subset) + ')'
                       for subset in combinations(TRIALS, required))


def at_least(flags, count):
    """Native postfix program for at least N distinct reward flags.

    Port of the audited MIT OOTRR medal_gate::at_least split-count formula.
    Zero returns an empty program so callers can use their own true guard.
    """
    flags = tuple(flags)
    if not 0 <= count <= len(flags):
        raise ValueError('Reward count exceeds its available distinct rewards.')
    if not count:
        return []
    if len(flags) == 1:
        return [(0, flags[0])]
    left, right = flags[:len(flags) // 2], flags[len(flags) // 2:]
    result = []
    for amount in range(min(count, len(left)) + 1):
        if count - amount > len(right):
            continue
        a, b = at_least(left, amount), at_least(right, count - amount)
        part = a + b + ([(3,)] if a and b else [])
        result += part + ([(4,)] if result else [])
    return result


def reward_program(mode, options, prefix, played):
    """Reward threshold AND the native one-time scene has not already played."""
    if mode in ('tokens', 'hearts'):
        name = 'PouchData.Item_Token_Gold.StockNum' if mode == 'tokens' else 'PlayerStatus.MaxLife'
        count = options[prefix + '_' + mode] * (1 if mode == 'tokens' else 4)
        # Actual 1.1.1 VM proof: 18 is strictly less than, 16 is an Int32
        # literal (not U64), and NOT makes the native comparison >=.
        # See tests and the actual-host counter boundary proof.
        terms = [(18, name), (16, count), (5,)]
        return terms + [(0, played), (5,), (3,)]
    if mode == 'vanilla':
        flags, count = ('IsGet.Item_Medal_Shadow', 'IsGet.Item_Medal_Spirit'), 2
    elif mode == 'open':
        flags, count = (), 0
    else:
        flags = {'stones': STONES, 'medallions': MEDALLIONS, 'dungeons': REWARDS}[mode]
        suffix = {'stones': 'stones', 'medallions': 'medallions', 'dungeons': 'rewards'}[mode]
        count = options[prefix + '_' + suffix]
    terms = at_least(flags, count)
    return terms + [(0, played), (5,)] + ([(3,)] if terms else [])
