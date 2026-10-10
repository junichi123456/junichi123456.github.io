"""Read a team from a pokesol.app article (the pokemon cards embedded in the page).

  python pokesol.py <記事URL>...        → data/known_teams.json に追加（同じ記事は上書き）
その後 python prep.py で対策（選出と対戦結果）を作り直す。
"""
import html, json, os, re, sys, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
KNOWN_P = os.path.join(HERE, 'data', 'known_teams.json')
_STAT = {'hp': 'hp', 'attack': 'atk', 'defense': 'def', 'specialAttack': 'spa', 'specialDefense': 'spd', 'speed': 'spe'}


def _stream(page):
    """Decode the React Router turbo-stream payload in the page into Python objects."""
    chunks = re.findall(r'streamController\.enqueue\((".*?")\);?</script>', page, re.S)
    vals = json.loads(''.join(json.loads(c) for c in chunks).split('\n')[0])
    memo = {}
    sys.setrecursionlimit(100000)

    def h(i):
        if i < 0:
            return None
        if i in memo:
            return memo[i]
        v = vals[i]
        if isinstance(v, dict):
            o = memo[i] = {}
            for k, x in v.items():
                o[vals[int(k[1:])]] = h(x) if isinstance(x, int) else x
            return o
        if isinstance(v, list):
            if v and isinstance(v[0], str) and v[0] in ('D', 'P', 'Y', 'R', 'E', 'Z'):
                return v
            o = memo[i] = []
            o.extend(h(x) if isinstance(x, int) else x for x in v)
            return o
        memo[i] = v
        return v
    return h(0)


def parse(page, url=''):
    root = _stream(page)['loaderData']['routes/u.$username.articles.$id']
    md = root['masterData']
    P = {p['id']: p['name'] for p in md['pokemons']}
    I = {x['id']: x['name'] for x in md['items']}
    N = {x['id']: x['name'] for x in md['natures']}
    M = {x['id']: x['name'] for x in md['moves']}
    A = {x['id']: x['name'] for x in md['abilities']}
    art = root.get('article') or {}
    team = []
    for c in re.findall(r'<div data-type=\\?"pokemon-card\\?"([^>]*)>', page):
        c = c.replace('\\"', '"')
        a = {k: html.unescape(v) for k, v in re.findall(r'data-([a-z-]+)="([^"]*)"', c)}
        ab = [A.get(x) for x in json.loads(a.get('ability-ids', '[]'))]
        name = re.sub(r'\((♂|♀)\)', '', P.get(int(a['pokemon-id']), '')).replace('ヤドキング(ガラル)', 'ガラルヤドキング')
        m = {'name': name, 'nature': N.get(int(a['nature-id'])) if a.get('nature-id') else None,
             'ability': ab[0] if ab else None, 'base_ability': ab[1] if len(ab) > 1 else (ab[0] if ab else None),
             'item': I.get(int(a['item-id'])) if a.get('item-id') else None,
             'moves': [M.get(x) for x in json.loads(a.get('move-ids', '[]'))],
             'ap': {_STAT[k]: v for k, v in json.loads(a.get('evs', '{}')).items() if v and k in _STAT}}
        if m not in team:
            team.append(m)
    aid = url.rstrip('/').split('/')[-1] if url else str(art.get('id', ''))
    return {'id': aid, 'title': ' '.join(str(art.get('title', '')).split()), 'url': url, 'team': team, 'picks': []}


def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    return urllib.request.urlopen(req, timeout=30).read().decode('utf-8')


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    data = json.load(open(KNOWN_P, encoding='utf-8')) if os.path.exists(KNOWN_P) else {'teams': []}
    for url in sys.argv[1:]:
        t = parse(fetch(url), url)
        old = next((x for x in data['teams'] if x['id'] == t['id']), None)
        if old:
            t['picks'] = old.get('picks', [])
            data['teams'][data['teams'].index(old)] = t
        else:
            data['teams'].append(t)
        print(t['title'], '/', ' '.join(m['name'] for m in t['team']))
    json.dump(data, open(KNOWN_P, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
