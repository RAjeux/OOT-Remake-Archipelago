"""Native Scrub offer text from the final AP item and recipient, in game language."""
import hashlib
import json

FLOW = 'Event/EventFlow/Enemy_Scrub_Business_Common.bfevfl.zs'
NAMES = 'ActorMsg/PouchContent.msbt'


def patch_messages(raw, language, sales):
    from ootrr_full.formats import msbt, byml_codec
    from ootrr_full.formats.inspect_resources import sarc
    files = sarc(raw)
    message = msbt.load(files[NAMES])
    for sale in sales:
        name = next((message.get(actor + '_Name') for actor in sale['names']
                     if message.get(actor + '_Name')), None)
        if name is None or not name.endswith(b'\0'):
            raise ValueError('The final AP Scrub item has no localized native pouch name.')
        label = sale['label']
        if label in message.labels:
            raise ValueError('The AP Scrub offer text already exists.')
        price = sale['price']
        if language.endswith('fr'):
            prefix, suffix = 'Je vends ', f' pour {price} rubis.\nTu en veux ?'
        else:
            prefix = 'I sell '
            suffix = f" for {price} {'rupee' if price == 1 else 'rupees'}.\nWant to buy it?"
        # Preserve native colour/grammar tags in the translated item name.
        # Remove exactly its final NUL, never the zero bytes in a control tag.
        text = prefix.encode('utf-8') + name[:-1] + suffix.encode('utf-8') + b'\0'
        message.labels[label] = len(message.texts)
        message.texts.append(text)
    files[NAMES] = msbt.dump(message)
    result = byml_codec.build_sarc(files)
    checked = msbt.load(sarc(result)[NAMES])
    if any(checked.get(sale['label']) != message.get(sale['label']) for sale in sales):
        raise ValueError('The localized AP Scrub offers did not round-trip.')
    return result


def prepare(artifact, options, seed_key, message_paths, read, stage):
    from ootrr_full.patching.progressive import FlowEditor
    from ootrr_full.game.extra_sources import SCRUB_GIFTS
    from ootrr_full.game.economy_settings import scrub_price
    from ootrr_full.formats import byml_codec
    spoiler = json.loads((artifact / 'spoiler.json').read_text(encoding='utf-8'))
    rows = [row for row in spoiler['placements'] if row.get('source') == 'scrub']
    if not rows:
        return 0
    # The final physical actor already carries the translated own-item name,
    # or the exact AP item and recipient for a foreign reward.
    actor_info = byml_codec.load(read('RSDB/ActorInfo.Product.111.rstbl.byml.zs'))['root']
    actors = {row['__RowId']: row.get('ActorName', row['__RowId']) for row in actor_info}
    sites = {'scrub#' + name: (variants, native) for name, _, variants, native in SCRUB_GIFTS}
    editor = FlowEditor(read(FLOW), 'AP Scrub offer names')
    events = {event.name: event for event in editor.chart.events}
    sales = []
    for row in rows:
        variants, _ = sites[row['id']]
        native = max(price for _, _, price in variants)
        entry = {'id': row['id'], 'price': native}
        price = scrub_price(options, seed_key, entry)
        actor = row.get('reward_actor', row['actor'])
        label = 'APScrub_' + hashlib.sha256(row['id'].encode()).hexdigest()[:16]
        sales.append({'label': label, 'price': price, 'names': [actor, actors.get(actor, actor)]})
        for event_name, _, _ in variants:
            event = events.get(event_name)
            params = getattr(getattr(event, 'data', None), 'params', None)
            if params is None or 'SellerMessageId' not in params.data:
                raise ValueError('A shuffled native Scrub has no seller message argument.')
            params.data['SellerMessageId'] = 'ActorMsg/PouchContent:' + label
            editor.expected[event_name] = dict(params.data)
    stage(FLOW, editor.write('AP Scrub offer names')[0])
    if not message_paths:
        raise ValueError('Native language archives are required for AP Scrub offer names.')
    for path in message_paths:
        language = path.split('/')[-1].split('.')[0]
        stage(path, patch_messages(read(path), language, sales))
    return len(sales)
