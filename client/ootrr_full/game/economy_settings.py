"""Deterministic native prices and their matching wallet requirements."""
import hashlib

DEFAULTS = {'shopsanity_prices': 'starting', 'shop_price_fixed': 10,
            'scrub_prices': 'shuffle', 'scrub_price_fixed': 10,
            'merchant_prices': 'vanilla', 'merchant_price_fixed': 10,
            'fairy_prices': 'vanilla', 'fairy_price_fixed': 10,
            'scrub_hint_text': False}
FAIRIES = (
    ('DMT Great Fairy Reward', 'Dm_FairyFountain_Din', 25, 'Event69', 'Event123'),
    ('HC Great Fairy Reward', 'Dm_FairyFountain_Power', 50, 'Event14', 'Event29'),
    ('ZF Great Fairy Reward', 'Dm_FairyFountain_Frore', 100, 'Event17', 'Event24'),
    ('DMC Great Fairy Reward', 'Dm_FairyFountain_Wisdom', 200, 'Event17', 'Event23'),
    ('Colossus Great Fairy Reward', 'Dm_FairyFountain_Nayru', 300, 'Event17', 'Event23'),
    ('OGC Great Fairy Reward', 'Dm_FairyFountain_Courage', 500, 'Event18', 'Event24'),
)


def options(Option, OK):
    result = [Option('shopsanity_prices', 'Economy', 'Shop prices',
                     (('starting', '10 rupees', OK), ('affordable', 'Starting wallet (1–200)', OK),
                      ('adult', 'Adult wallet (201–500)', OK), ('giant', 'Giant wallet (501–1000)', OK),
                      ('fixed', 'Fixed price', OK)), 'starting',
                     'Prices use the native shop display and payment. Random tier prices are stable per '
                     'offered item; the same offered item has the same price throughout the seed. '
                     'The logic requires exactly the wallet tier that can pay these prices.')]
    for prefix, label in (('scrub', 'Business Scrub'), ('merchant', 'Merchant'), ('fairy', 'Great Fairy')):
        values = [('vanilla', 'Native prices', OK), ('cheap', '10 rupees', OK), ('fixed', 'Fixed price', OK)]
        if prefix == 'scrub':
            values.insert(0, ('shuffle', 'Follow Scrub shuffle setting', OK))
        result.append(Option(prefix + '_prices', 'Economy', label + ' prices', tuple(values),
                             DEFAULTS[prefix + '_prices'],
                             'Native prices or an explicit price for the enabled sales. '
                             'The access rules require an affordable wallet.'))
    for prefix, label in (('shop', 'Shop'), ('scrub', 'Business Scrub'),
                          ('merchant', 'Merchant'), ('fairy', 'Great Fairy')):
        result.append(Option(prefix + '_price_fixed', 'Economy', label + ' fixed price', None, 10,
                             'Used only with the corresponding price mode set to fixed.',
                             kind='int', minimum=0, maximum=1000, supported_ints=tuple(range(1001))))
    result.append(Option('scrub_hint_text', 'Economy', 'Scrub item names',
                         ((False, OK), (True, OK)), False, 'Native Business Scrub offers name the final item, its recipient '
                         'and the actual price, in the current game language.', kind='bool'))
    return result


def wallet(price):
    if not 0 <= price <= 1000:
        raise ValueError('Price exceeds the supported native wallets.')
    return 2 if price > 500 else 1 if price > 200 else 0


def shop_wallet(options):
    mode = options['shopsanity_prices']
    return {'starting': 0, 'affordable': 0, 'adult': 1, 'giant': 2}.get(
        mode, wallet(options['shop_price_fixed']))


def shop_price(options, seed_key, actor):
    mode = options['shopsanity_prices']
    if mode == 'starting':
        return 10
    if mode == 'fixed':
        return options['shop_price_fixed']
    low, high = {'affordable': (1, 200), 'adult': (201, 500), 'giant': (501, 1000)}[mode]
    digest = hashlib.sha256((seed_key + '\0full-shop-price\0' + actor).encode()).digest()
    return low + int.from_bytes(digest[:8], 'big') % (high - low + 1)


def sale_price(options, prefix, native):
    mode = options[prefix + '_prices']
    return native if mode in ('vanilla', 'shuffle') else 10 if mode == 'cheap' else options[prefix + '_price_fixed']


def scrub_price(options, seed_key, entry):
    from ootrr_full.game.extra_sources import scrub_price as previous
    native = previous(options['shuffle_scrubs'], seed_key, entry) if options['scrub_prices'] == 'shuffle' else entry['price']
    return sale_price(options, 'scrub', native)


def source_price(options, entry):
    """Non-shop prices are known before placement, including finite bean sales."""
    if entry['source'] == 'fairy':
        name = entry['ap'][0]
        native = next((row[2] for row in FAIRIES if row[0] == name), None)
        return sale_price(options, 'fairy', native) if native is not None else None
    if entry.get('extra_name') == 'GC Medigoron':
        return sale_price(options, 'merchant', 200)
    if 'bean_index' in entry:
        # All ten native bean prices fit the remake's 200-rupee starting wallet.
        return sale_price(options, 'merchant', (entry['bean_index'] + 1) * 10)
    return None
