"""SPEC_RESOURCE.md の単体試験（§4①）。python3 test_resource.py [--timing]。ファイルは書かない。"""
import json, os, sys, time, traceback
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import roundrobin as RR, refine as R, battle as B, search as S  # noqa: E402

AX = ('リザードン', 'ガブリアス')
RES = []


def ok(n, cond, msg=''):
    RES.append((n, bool(cond)))
    print(('OK ' if cond else 'NG ') + n, msg, flush=True)


def setup():
    p = json.load(open(RR.m7_paths(None, 'm8_6')['plan'], encoding='utf-8'))
    teams = {**RR._m7_load_s3()['teams'], 'M8_6': p['m7_team']}
    RR._worker_init(teams)
    RR.rr_apply(teams['M8_6'])
    B.match_known = lambda *a, **k: None
    B.set_known_context(None)
    return p, teams


def tm(n):
    return R._templates([n], B.opp_sets, 1)[0]


def game(mine, foe):
    return B.engine_game(mine, foe)


def main():
    timing = '--timing' in sys.argv
    p, teams = setup()
    real_match = B.match_known
    G6 = ['ルカリオ', 'グソクムシャ', 'アーマーガア', 'ボーマンダ', 'メタグロス', 'ドドゲザン']   # ガブリアス(メガ)が全員に勝つ
    good = [tm(n) for n in G6]
    # ---- (a)
    st = game(['リザードン', 'ガブリアス', 'ミミッキュ'], ['ハッサム', 'アシレーヌ', 'カバルドン'])
    c = S.axis_cover(st, 0, AX, good)
    ok('a1 軸が全員に勝つ→成立', c['on'] and c['sats'] == [2] and c['axis'] == [0, 1])
    bad = good[:5] + [tm('アシレーヌ')]
    ok('a2 軸の受けが1体→不成立', not S.axis_cover(st, 0, AX, bad)['on'])
    ok('a2b C が空→不成立', not S.axis_cover(st, 0, AX, [])['on'])
    # 選出外・未出でも受けが漏れない（res_cand は opp6 の型・満タンを使う）
    st1 = game(['リザードン', 'ガブリアス', 'ミミッキュ'], ['ルカリオ', 'グソクムシャ', 'アーマーガア'])
    t6a = R._templates(G6, B.opp_sets, 1)
    rx = {'axis': AX, 'opp6': G6, 'loose': False}
    ok('a3 opp6 全員勝てる→成立', S.axis_cover(st1, 0, AX, R.res_cand(st1, st1, rx, t6a, {0}, 0)['cand'])['on'])
    opp6b = G6[:5] + ['アシレーヌ']      # アシレーヌは選出外で未出
    t6b = R._templates(opp6b, B.opp_sets, 1)
    rxb = {'axis': AX, 'opp6': opp6b, 'loose': False}
    ok('a4 選出外・未出の受けでも不成立', not S.axis_cover(st1, 0, AX, R.res_cand(st1, st1, rxb, t6b, {0}, 0)['cand'])['on'])
    st2 = game(['リザードン', 'ガブリアス', 'ミミッキュ'], ['ルカリオ', 'グソクムシャ', 'アシレーヌ'])
    ca = R.res_cand(st2, st2, rxb, t6b, {0}, 0)['cand']
    ok('a5 未出の選出内の受けも不成立', not S.axis_cover(st2, 0, AX, ca)['on'] and len(ca) == 6)
    st2.sides[1].mons[2].hp = 0
    cb = R.res_cand(st2, st2, rxb, t6b, {0, 1, 2}, 0)['cand']
    ok('a6 倒れた相手は C から外れる→成立', len(cb) == 5 and 'アシレーヌ' not in [m.name for m in cb] and S.axis_cover(st2, 0, AX, cb)['on'])
    # (a') ブラインド: 選出（未出の2体）だけ違う
    O6 = ['ハッサム', 'ルカリオ', 'グソクムシャ', 'アーマーガア', 'ボーマンダ', 'メタグロス']
    t6c = R._templates(O6, B.opp_sets, 1)
    rxc = {'axis': AX, 'opp6': O6, 'loose': False}
    sa = game(['リザードン', 'ガブリアス', 'ミミッキュ'], ['ハッサム', 'ルカリオ', 'グソクムシャ'])
    sb = game(['リザードン', 'ガブリアス', 'ミミッキュ'], ['ハッサム', 'アシレーヌ', 'ブリジュラス'])
    ca, cb = (R.res_cand(s, s, rxc, t6c, {0}, 0) for s in (sa, sb))
    key = lambda d: [(m.name, m.hp, m.item, m.moves) for m in d['cand']]
    ra, rb = S.axis_cover(sa, 0, AX, ca['cand']), S.axis_cover(sb, 0, AX, cb['cand'])
    ok("a' 相手の選出だけ違っても同じ判定", key(ca) == key(cb) and ra == rb and ra['on'], f"on={ra['on']}")
    # (a'') 緩和版
    st3 = game(['ガブリアス', 'ミミッキュ', 'ドドゲザン'], ['ハッサム', 'アシレーヌ', 'カバルドン'])
    c6 = good[:5] + [tm('サザンドラ')]
    s_, l_ = S.axis_cover(st3, 0, AX, c6), S.axis_cover(st3, 0, AX, c6, loose=True)
    ok("a'' 緩和版: 厳格False・緩和True・保護=ミミッキュ(割引はドドゲザンだけ)", not s_['on'] and l_['on'] and l_['sats'] == [2], str(l_))
    st3b = game(['ガブリアス', 'ミミッキュ', 'ドドゲザン'], ['ハッサム', 'アシレーヌ', 'カバルドン'])
    st3b.sides[0].mons[2].hp = 0
    ok("a''2 保護対象しか取り巻きがいなければ不成立", not S.axis_cover(st3b, 0, AX, c6, loose=True)['on'])
    ok("a''3 80%未満は緩和でも不成立", not S.axis_cover(st3, 0, AX, good[:4] + [tm('サザンドラ'), tm('アシレーヌ')], loose=True)['on'])
    # ---- (b)
    ok('b1 軸1体だけでも全員に勝てば成立', S.axis_cover(st3, 0, AX, good)['on'] and S.axis_cover(st3, 0, AX, good)['axis'] == [0])
    kb = [tm('カバルドン')]
    ok('b2 メガ未使用: メガ姿で勝てる', S.axis_cover(st3, 0, AX, kb)['on'])
    st3.sides[0].mega_used = True
    ok('b3 メガ使用済み・通常姿のガブリアスは勝てない', not S.axis_cover(st3, 0, AX, kb)['on'])
    st3.sides[0].mons[0] = S._res_mega(st3.sides[0].mons[0])
    ok('b4 メガ済みの姿なら勝てる', S.axis_cover(st3, 0, AX, kb)['on'])
    st4 = game(['リザードン', 'ガブリアス', 'ミミッキュ'], ['ハッサム', 'アシレーヌ', 'カバルドン'])
    mk = [tm('ミミッキュ'), tm('カバルドン')]
    one = [S.axis_cover(st4, 0, AX, [m])['on'] for m in mk]
    ok('b5 メガ枠は1つ: 別々の割り当てでしか勝てない組は不成立', one == [True, True] and not S.axis_cover(st4, 0, AX, mk)['on'], str(one))
    ev = S.evaluate_resource(st4, 0, [2]), S.evaluate(st4), S.evaluate_resource(st4, 1, [2])
    ok('b6 evaluate_resource の割引方向', ev[0] < ev[1] < ev[2])
    # ---- (c)
    ch, ex = [], None
    for f in ('カバルドン', 'セグレイブ', 'ガブリアス'):
        s_ = game(['ミミッキュ', 'ガブリアス', 'リザードン'], [f, 'ハッサム', 'ミミッキュ'])
        info = {}
        a1 = S.lookahead_action(s_, 0, 3)
        a2 = S.lookahead_action(s_, 0, 3, info=info, res={'axis': AX, 'cand': good, 'loose': False})
        if info.get('res_on') and a1[0] == 's' and a2[0] == 'm':
            ex = (f, a1, a2)
        ch.append((a1, a2, info.get('res_on')))
    ok('c1 成立局面で従来=交代・resource=居座り/攻撃の例', ex is not None, str(ex or ch))
    s_ = game(['ミミッキュ', 'ガブリアス', 'リザードン'], ['カバルドン', 'ハッサム', 'ミミッキュ'])
    same = True
    for dn in (None, 'deny'):
        for hp in (1.0, 0.5):
            s_.sides[0].mons[0].hp = max(1, int(s_.sides[0].mons[0].maxhp * hp))
            i1, i2 = {}, {}
            a1 = S.lookahead_action(s_, 0, 3, mode=dn, info=i1)
            a2 = S.lookahead_action(s_, 0, 3, mode=dn, info=i2, res={'axis': AX, 'cand': bad, 'loose': False})
            same = same and a1 == a2 and not i2.get('res_on') and all(i1[k] == i2[k] for k in i1)
    ok('c2 不成立なら従来の手・info と一致（通常・deny）', same)
    # ---- (d)
    X = p['opponents'][0]
    k1, k0 = p['sel1'][f'M8_6|{X}']['order'], p['sel1'][f'{X}|M8_6']['order']
    def play(s0, s1, o0, o1, seed, extra, depth=(2, 2)):
        pa = RR._pb_args(s0, s1)
        if extra is not None:
            pa = (pa[0] if pa else None, extra)
        return R.blind_play((None, s1 if s0 == 'M8_6' else s0, o0, o1, seed, depth[0], depth[1], False, None, False,
                             (s0,) if s0 == 'M8_6' else (s1,), (True, True)) + pa)
    same = True
    for seed in (RR.m7_seed(X, 0), RR.m7_seed(X, 1)):
        RR.rr_apply(teams['M8_6'])
        r0 = play('M8_6', X, k1, k0, seed, None)
        RR.rr_apply(teams['M8_6'])
        r1 = play('M8_6', X, k1, k0, seed, (None, None))
        same = same and r0.get('res') is not None and r0 == r1 and 'res_stats' not in r1
    ok('d1 args[13] 無し/(None,None) で完全一致（2戦）', same)
    opp6 = [B.BASE_OF.get(m['species'], m['species']) for m in teams[X]['mons']]
    rc = {'axis': list(AX), 'opp6': opp6, 'loose': False}
    RR.rr_apply(teams['M8_6'])
    r2 = play('M8_6', X, k1, k0, RR.m7_seed(X, 0), (rc, None))
    rs = (r2.get('res_stats') or {}).get(0)
    ok('d2 resource 有りで動く（res_stats 形式）', r2.get('res') is not None and rs and set(rs) == {'turns', 'on', 'first', 'sw_sat_on', 'sat_faint_on'}
       and rs['turns'] == r2['turns'] and 0 <= rs['on'] <= rs['turns'], str(r2.get('error') or rs))
    # 反対側（M8_6 が side 1: 側0の構築を適用してから回す）
    RR.rr_apply(teams[X])
    r3 = R.blind_play((None, 'M8_6', k0, k1, RR.m7_seed(X, 1), 2, 2, False, None, False, (X,), (True, True)) + (
        (RR._pb_args(X, 'M8_6') or (None,))[0], (None, rc)))
    ok('d3 side 1 でも動く', r3.get('res') is not None and 1 in (r3.get('res_stats') or {}), str(r3.get('error') or r3.get('res_stats')))
    hit = None
    for Y in p['opponents'][:25]:
        y6 = [B.BASE_OF.get(m['species'], m['species']) for m in teams[Y]['mons']]
        RR.rr_apply(teams['M8_6'])
        r = play('M8_6', Y, p['sel1'][f'M8_6|{Y}']['order'], p['sel1'][f'{Y}|M8_6']['order'], RR.m7_seed(Y, 0), ({'axis': list(AX), 'opp6': y6}, None))
        st_ = (r.get('res_stats') or {}).get(0) or {}
        if st_.get('on', 0) > 0:
            hit = (Y, st_, r)
            break
    ok('d5 成立する対戦で res_stats が増える（first あり・on<=turns）', hit and hit[1]['first'] is not None and hit[1]['on'] <= hit[1]['turns'] == hit[2]['turns'],
       str(hit and hit[1]))
    try:
        R.blind_play((None, X, k1, k0, 1, 2, 2, False, ('x',), False, (), (True, True), None, (rc, None)))
        ok('d4 rules との併用は ValueError', False)
    except ValueError:
        ok('d4 rules との併用は ValueError', True)
    # ---- 時間比
    if timing:
        ts = []
        for use in (False, True):
            t0 = time.time()
            for k in (0, 1):
                RR.rr_apply(teams['M8_6'])
                play('M8_6', X, k1, k0, RR.m7_seed(X, k), (rc, None) if use else None, depth=(5, 5))
            ts.append(time.time() - t0)
        ratio = ts[1] / ts[0]
        ok('5 時間比 (resource/従来, 2戦 深さ5) <= 1.3', ratio <= 1.3, f'従来 {ts[0]:.0f}秒 / resource {ts[1]:.0f}秒 = {ratio:.2f}')
    bad_ = [n for n, v in RES if not v]
    print('ALL OK' if not bad_ else f'FAILED {bad_}')
    return 1 if bad_ else 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(2)
