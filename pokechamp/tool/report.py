"""Generate ../index.html (構築レポート) from the calculator so every number is reproducible."""
import html, os
from calc import calc, ko_text, eff, TYPES, JT, MOVE
from meta import META
from team import TEAM
from coverage import verdict, best

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'index.html')
mm = {f.label: f for _, f in META}
L, G, A, H, Mi, Y = TEAM
NAME = {id(L): 'メガルカリオZ', id(G): 'ガブリアス', id(A): 'アシレーヌ', id(H): 'ヒートロトム', id(Mi): 'ミミッキュ', id(Y): 'ギャラドス'}
e = html.escape


def nm(m):
    return NAME.get(id(m), m.label)


def row(att, dfn, move, note='', **kw):
    r = calc(att, dfn, move, **kw)
    cond = []
    if kw.get('atk_boost'): cond.append(f"攻撃側{kw['atk_boost']:+d}")
    if kw.get('intimidated'): cond.append('いかく後')
    if kw.get('burned'): cond.append('やけど')
    if kw.get('weather') == 'sun': cond.append('晴れ')
    if kw.get('terrain') == 'grassy': cond.append('GF')
    if kw.get('extra_power_mod') == 8192: cond.append('威力2倍')
    if note: cond.append(note)
    return (f"<tr><td>{e(nm(att))}</td><td>{e(move)}</td><td>{e(nm(dfn))}</td>"
            f"<td class=num>{r[0]}〜{r[-1]}</td><td>{e(ko_text(r, dfn.stat['hp']))}</td><td class=sub>{e(' / '.join(cond))}</td></tr>")


CALCS = [
    ('メガルカリオZ（エース）', [
        (L, mm['ブリジュラス'], 'はどうだん', {}), (L, mm['セグレイブ'], 'はどうだん', {}),
        (L, mm['メガボーマンダ'], 'ラスターカノン', dict(atk_boost=2)), (L, mm['アシレーヌ'], 'ラスターカノン', dict(atk_boost=2)),
        (L, mm['メガグソクムシャ'], 'はどうだん', dict(atk_boost=2)), (L, mm['サーフゴー'], 'あくのはどう', {}),
        (L, mm['メガゲンガー'], 'あくのはどう', {}), (L, mm['メガアブソルＺ'], 'ラスターカノン', {}),
        (mm['メガグソクムシャ'], L, 'アイアンヘッド', {}), (mm['ミミッキュ'], L, 'シャドークロー', dict(atk_boost=2, def_full_hp=False)),
        (mm['メガボーマンダ'], L, 'じしん', {}), (mm['アシレーヌ'], L, 'ムーンフォース', {}),
    ]),
    ('ガブリアス（先発・ステロ）', [
        (G, mm['メガリザードンＹ'], 'がんせきふうじ', {}), (G, mm['メガルカリオＺ'], 'じしん', {}),
        (G, mm['メガボーマンダ'], 'げきりん', {}), (G, mm['メガガブリアスZ(CS)'], 'げきりん', {}),
        (G, mm['メガゲンガー'], 'じしん', {}), (G, mm['キラフロル'], 'じしん', {}),
        (mm['メガガブリアスZ(CS)'], G, 'りゅうせいぐん', {}),
    ]),
    ('アシレーヌ（ドラゴン受け・めいそう）', [
        (A, mm['メガボーマンダ'], 'ムーンフォース', {}), (A, mm['メガガブリアスZ(CS)'], 'ムーンフォース', {}),
        (A, mm['セグレイブ'], 'ムーンフォース', {}), (A, mm['カバルドン'], 'うたかたのアリア', dict(atk_boost=1)),
        (A, mm['メガルカリオＺ'], 'うたかたのアリア', {}),
        (mm['メガボーマンダ'], A, 'すてみタックル', {}), (mm['メガガブリアスZ(CS)'], A, 'だいちのちから', {}),
        (mm['メガルカリオＺ'], A, 'ラスターカノン', dict(atk_boost=2)),
    ]),
    ('ヒートロトム（鋼・草・虫の処理）', [
        (H, mm['メガグソクムシャ'], 'オーバーヒート', {}), (H, mm['ゴリランダー'], 'オーバーヒート', {}),
        (H, mm['マスカーニャ'], 'オーバーヒート', {}), (H, mm['サーフゴー'], 'オーバーヒート', {}),
        (H, mm['メガメタグロス'], 'オーバーヒート', {}), (H, mm['ギャラドス'], 'ボルトチェンジ', {}),
        (mm['メガボーマンダ'], H, 'すてみタックル', dict(atk_boost=1, burned=True)),
        (mm['ゴリランダー'], H, 'グラススライダー', dict(terrain='grassy')),
        (mm['メガリザードンＹ'], H, 'りゅうのはどう', {}),
    ]),
    ('ミミッキュ（ストッパー）', [
        (Mi, mm['メガボーマンダ'], 'じゃれつく', dict(atk_boost=2)), (Mi, mm['メガガブリアスZ(CS)'], 'じゃれつく', {}),
        (Mi, mm['サザンドラ'], 'じゃれつく', {}), (Mi, mm['メガゲンガー'], 'シャドークロー', {}),
        (Mi, mm['メガアブソルＺ'], 'じゃれつく', {}), (Mi, mm['サーフゴー'], 'シャドークロー', dict(atk_boost=2)),
        (Mi, mm['メガリザードンＹ'], 'シャドークロー', dict(atk_boost=2)),
    ]),
    ('ギャラドス（物理受け・対ボーマンダ）', [
        (Y, mm['メガボーマンダ'], 'ゆきなだれ', dict(extra_power_mod=8192)), (Y, mm['タスキガブリアス'], 'ゆきなだれ', dict(extra_power_mod=8192)),
        (Y, mm['エースバーン'], 'たきのぼり', {}), (Y, mm['メガバシャーモ'], 'たきのぼり', {}),
        (mm['メガボーマンダ'], Y, 'すてみタックル', dict(atk_boost=1, intimidated=True)),
        (mm['エースバーン'], Y, 'ダストシュート', dict(intimidated=True)),
        (mm['オオニューラ'], Y, 'フェイタルクロー', dict(intimidated=True)),
        (mm['メガアブソルＺ'], Y, 'シャドークロー', dict(intimidated=True)),
        (mm['メガルカリオＺ'], Y, 'あくのはどう', dict(atk_boost=2)),
    ]),
]

SETS = [
    (L, 'エース／抜きエース', 'S151族の最速帯(実数値223)。接触技半減の「はどうのぼうご」で環境に多い物理接触アタッカー(グソクムシャ・ミミッキュ・セグレイブの氷柱/つぶて・ボーマンダの捨て身)に強く、わるだくみ1回で鋼・水・ドラゴンをまとめて縛る。'),
    (G, '先発／ステルスロック', 'タスキで行動保証、ステロでタスキ(セグレイブ51%・キラフロル62%・エースバーン)と化けの皮以外の削りを入れる。がんせきふうじでリザードンY確1と後続のS操作。ルカリオの地面・炎弱点を受ける。'),
    (A, '特殊受け／ドラゴン対策', '最大の流行枠であるボーマンダ・ガブリアス(メガZ含む)・セグレイブにタイプ有利。アンコールで積み技(竜舞・悪巧み・剣舞・ステロ)を固定して起点を作り返す。'),
    (H, 'クッション／対鋼・虫・草', 'グソクムシャ・ゴリランダー・マスカーニャ・アーマーガア・メタグロス・サーフゴーにオバヒが通る。浮遊で地面無効、おにびで物理全般を機能停止。'),
    (Mi, '行動保証ストッパー', '化けの皮で1発保証。メガガブリアスZ・サザンドラ・メガゲッコウガ・アブソルZなど高速アタッカーへの切り返し。'),
    (Y, '物理受け／いかく', 'いかく＋ゴツメで物理の削りを稼ぐ。ゆきなだれ(後攻威力2倍)でボーマンダ・ガブリアスを確1。炎・格闘を半減しエースバーン・バシャーモ・オオニューラを止める。'),
]

PLANS = [
    ('基本選出', 'ガブリアス ＋ メガルカリオZ ＋ アシレーヌ', '先発ガブでステロ→がんせきふうじ/じしんで1体削る。タスキ潰れ後はルカリオで悪巧み→全抜き、残りをアシレーヌのアンコールとムンフォで詰める。'),
    ('ドラゴン多め(ボーマンダ・ガブ・セグレイブ・カイリュー)', 'アシレーヌ ＋ ギャラドス ＋ ミミッキュ/ルカリオ', 'いかくギャラドスで竜舞を受け、ゆきなだれ。アシレーヌはアンコールで積みを固定。セグレイブ(タスキ)はルカリオのはどうだんで処理。'),
    ('鋼・虫・草が多い(グソクムシャ・ゴリランダー・アーマーガア・メタグロス)', 'ヒートロトム ＋ メガルカリオZ ＋ ガブリアス', 'ロトムのオバヒ・ボルチェンで対面を回し、ルカリオ(接触半減)で起点を作る。'),
    ('メガリザードンY入り', 'ガブリアス ＋ ヒートロトム ＋ アシレーヌ', 'ガブは最速なのでリザY(152)より速く、がんせきふうじ確1。ロトムはソラビ3割弱・りゅうのはどう4割前後で後投げできる。'),
    ('炎格闘・高速物理(エースバーン・バシャーモ・オオニューラ)', 'ギャラドス ＋ ガブリアス ＋ アシレーヌ', 'いかく後のダストシュートでも3割程度。たきのぼりでエースバーン乱1、バシャーモを削る。'),
    ('カバルドン・ステロ起点系', 'アシレーヌ ＋ メガルカリオZ ＋ ヒートロトム', 'めいそう+1のアリアでカバルドン確1。あくびはロトムでいなす。'),
]


def type_rows():
    out = []
    for t in TYPES:
        cells = []
        weak = res = 0
        for m in TEAM:
            v = eff(t, m.types)
            if t == 'ground' and (m.ability == 'ふゆう' or 'flying' in m.types):
                v = 0.0
            if m.ability == 'ばけのかわ':
                pass
            cls = 'x4' if v >= 4 else 'x2' if v == 2 else 'h' if 0 < v < 1 else 'z' if v == 0 else ''
            txt = {4: '×4', 2: '×2', 1: '', 0.5: '½', 0.25: '¼', 0: '無'}.get(v, str(v))
            weak += v > 1
            res += v < 1
            cells.append(f'<td class="{cls}">{txt}</td>')
        out.append(f"<tr><th>{JT[t]}</th>{''.join(cells)}<td class=num>{weak}</td><td class=num>{res}</td></tr>")
    return '\n'.join(out)


def grid_rows():
    sym = {1.0: ('◎', 'g2'), 0.8: ('○', 'g1'), 0.5: ('△', 'g0'), 0: ('×', 'gx')}
    out = []
    for rank, f in META:
        cells = []
        n = 0
        for m in TEAM:
            v = verdict(m, f)
            s, c = sym[v]
            n += v >= 0.8
            mv, p = best(m, f)
            cells.append(f'<td class="{c}" title="{e(mv)} {p[0]:.0f}-{p[1]:.0f}%">{s}</td>')
        out.append(f"<tr><td class=num>{rank}</td><th>{e(f.label)}</th><td class=num>{f.speed()}</td>{''.join(cells)}<td class=num>{n}</td></tr>")
    return '\n'.join(out)


def speed_rows():
    pts = [(m.speed(), nm(m), True) for m in TEAM]
    for lab in ['メガルカリオＺ', 'メガガブリアスZ(CS)', 'メガアブソルＺ', 'メガゲッコウガ', 'メガゲンガー', 'メガボーマンダ', 'オオニューラ', 'パーモット',
                'エースバーン', 'タスキガブリアス', 'メガメタグロス', 'メガリザードンＹ', 'キラフロル', 'ミミッキュ', 'セグレイブ', 'ブリジュラス',
                'サーフゴー', 'ゴリランダー', 'カバルドン', 'メガグソクムシャ']:
        pts.append((mm[lab].speed(), mm[lab].label, False))
    for lab in ['スカーフガブリアス', 'マスカーニャ', 'スカーフイダイトウ', 'サザンドラ']:
        pts.append((mm[lab].speed(), mm[lab].label + '(スカーフ)' if 'スカーフ' not in mm[lab].label else mm[lab].label, False))
    pts.append((mm['メガボーマンダ'].speed(boost=1), 'メガボーマンダ(竜舞+1)', False))
    pts.sort(key=lambda x: (-x[0], not x[2]))
    return '\n'.join(f'<tr class="{"me" if mine else ""}"><td class=num>{s}</td><td>{e(n)}</td></tr>' for s, n, mine in pts)


def team_cards():
    out = []
    for m, role, desc in SETS:
        moves = ''.join(f'<li>{e(x)}</li>' for x in m.moves)
        ty = '・'.join(JT[t] for t in m.types)
        out.append(f'''<article class=card><header><h3>{e(nm(m))}</h3><span class=role>{e(role)}</span></header>
<dl><dt>タイプ</dt><dd>{ty}</dd><dt>特性</dt><dd>{e(m.ability)}</dd><dt>持ち物</dt><dd>{e(m.item)}</dd>
<dt>性格</dt><dd>{e(m.nature)}</dd><dt>能力P</dt><dd>{e(m.sp_str())}</dd><dt>実数値</dt><dd class=mono>{m.stat_str()}</dd></dl>
<ul class=moves>{moves}</ul><p>{e(desc)}</p></article>''')
    return '\n'.join(out)


def calc_sections():
    out = []
    for title, rows in CALCS:
        body = '\n'.join(row(a, d, mv, **kw) for a, d, mv, kw in rows)
        out.append(f'<h3>{e(title)}</h3><div class=scroll><table class=calc><thead><tr><th>攻撃側</th><th>技</th><th>防御側</th><th>ダメージ</th><th>割合・確定数</th><th>条件</th></tr></thead><tbody>{body}</tbody></table></div>')
    return '\n'.join(out)


page = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'template.html'), encoding='utf-8').read()
page = (page.replace('{{TEAM}}', team_cards()).replace('{{TYPES}}', type_rows()).replace('{{GRID}}', grid_rows())
        .replace('{{SPEED}}', speed_rows()).replace('{{CALCS}}', calc_sections())
        .replace('{{PLANS}}', '\n'.join(f'<tr><th>{e(a)}</th><td>{e(b)}</td><td>{e(c)}</td></tr>' for a, b, c in PLANS))
        .replace('{{HEAD}}', ''.join(f'<th>{e(nm(m))}</th>' for m in TEAM)))
open(OUT, 'w', encoding='utf-8').write(page)
print('wrote', os.path.normpath(OUT))
