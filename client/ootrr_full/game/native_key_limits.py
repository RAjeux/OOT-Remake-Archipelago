"""Native small-key totals for every remake layout.

The merged1.1.1 NUP audit found these real key sources. Water, Well and Ganon
also have4/2/1 physical chain-lock clusters. Reaching the complete native key
set resolves their imported thresholds above that total; lower thresholds keep
the conservative imported route. This corrects only access rules; stored AP
identities, delivery recipes, item pools and historical ring grants are unchanged.
"""

NATIVE_SMALL_KEYS = {'ForestTemple': 5, 'FireTemple': 8, 'WaterTemple': 4,
                     'ShadowTemple': 5, 'SpiritTemple': 5, 'BottomOfTheWell': 2,
                     'GerudoTrainingGround': 9, 'InsideGanonCastle': 1}
THRESHOLDS = {'Small Key (Water Temple)': 4, 'Small Key (Bottom of the Well)': 2,
              'Small Key (Ganons Castle)': 1}


def enabled(options):
    # Native door counts do not change when the delivery system changes.
    return True


def quantity(item, amount, settings):
    return min(amount, THRESHOLDS.get(item, amount)) if settings.get('native_key_limits') else amount
