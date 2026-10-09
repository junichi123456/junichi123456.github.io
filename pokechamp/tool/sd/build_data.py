"""export_showdown.js の出力と PokeAPI の日本語名から data/champ.json（日本語キー）を作る。

  python sd/build_data.py <export.json> <PokeAPIのcsvフォルダ>
csv: abilities, ability_names, items, item_names, moves, move_names（PokeAPI/pokeapi の data/v2/csv）
"""
import csv, json, os, re, sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from calc import MOVE, POKE  # noqa: E402

tid = lambda s: re.sub(r'[^a-z0-9]', '', s.lower())
# Legends Z-A / Champions で増えた名前（PokeAPI に未収録）
EXTRA = {'ability': {'auraguard': 'はどうのぼうご', 'eelevate': 'うなぎのぼり', 'firemane': 'ほのおのたてがみ'},
         'item': {'leek': 'ながねぎ'}}


def names(folder, kind, table):
    ids = {r['id']: tid(r['identifier']) for r in csv.DictReader(open(os.path.join(folder, table + '.csv'), encoding='utf-8'))}
    out = {}
    for r in csv.DictReader(open(os.path.join(folder, kind + '_names.csv'), encoding='utf-8')):
        lid, k = r['local_language_id'], ids.get(r[kind + '_id'])
        if k and lid in ('1', '11') and (lid == '1' or k not in out):
            out[k] = r['name'].replace('　', '')
    return out


def main():
    E = json.load(open(sys.argv[1], encoding='utf-8'))
    folder = sys.argv[2]
    mvn, abn, itn = names(folder, 'move', 'moves'), names(folder, 'ability', 'abilities'), names(folder, 'item', 'items')
    abn.update(EXTRA['ability']); itn.update(EXTRA['item'])
    mv_en = {tid(m['en']): j for j, m in MOVE.items()}
    moves = {}
    for k, m in E['moves'].items():
        ja = mv_en.get(k) or mvn.get(k)
        if ja:
            m['id'] = k
            moves[ja] = m
    abilities = {abn.get(k, k): dict(v, id=k) for k, v in E['abilities'].items()}
    items = {itn.get(k, k): dict(v, id=k) for k, v in E['items'].items()}
    # species: our Japanese name -> showdown data
    by_num = {}
    for n, p in POKE.items():
        num = p['baseId'] or p['id']
        by_num.setdefault(num, []).append((n, tid(p.get('form') or '')))
    species = {}
    for k, s in E['species'].items():
        form = tid(s['forme'] or '')
        if form == 'f': form = 'female'
        for n, f in by_num.get(s['num'], []):
            if f == form or (form and f.startswith(form)):
                species[n] = dict(s, id=k)
                break
    # in-battle forms that have no entry in our Japanese data
    extra = {'palafinhero': 'イルカマン(マイティ)', 'mimikyubusted': 'ミミッキュ(ばれたすがた)',
             'morpekohangry': 'モルペコ(はらぺこ)', 'castformsunny': 'ポワルン(たいよう)',
             'castformrainy': 'ポワルン(あまみず)', 'castformsnowy': 'ポワルン(ゆきぐも)',
             'meowsticmmega': 'メガニャオニクス', 'meowsticfmega': 'メガニャオニクス♀'}
    for k, ja in extra.items():
        if k in E['species'] and ja not in species:
            species[ja] = dict(E['species'][k], id=k)
    ls = {}
    for n, s in species.items():
        ls[n] = sorted(ja for ja, m in moves.items() if m['id'] in set(E['learnsets'].get(s['id'], [])))
    out = {'moves': moves, 'abilities': abilities, 'items': items, 'species': species, 'learnsets': ls,
           'conditions': E['conditions']}
    json.dump(out, open(os.path.join(HERE, 'data', 'champ.json'), 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    print('moves', len(moves), 'abilities', len(abilities), 'items', len(items), 'species', len(species), '/', len(E['species']))
    print('species not mapped:', [s['name'] for k, s in E['species'].items() if k not in {v['id'] for v in species.values()}])


if __name__ == '__main__':
    main()
