/* Star Crusade CCG 再現版 — カード・モジュール・勢力データ
 * 出典区分 src:
 *   A = 検証済み(公式告知/パッチノート/開発者投稿で文面・数値を確認)
 *   B = 一部確認(名称+一部の数値または文面を確認。残りは再構成)
 *   C = 名称のみ確認(名称と勢力の文脈のみ確認。数値・効果はプレイ用に再構成)
 *   D = 補完(資料で確認できない。ゲーム成立のため作成した仮称カード)
 * 効果は engine.js が解釈する op リスト。tx は表示用の日本語テキスト、en は確認済み英文。
 */
(function () {
  const F = {
    ANN: { ja: 'アヌンナキ', en: 'Annunaki', color: '#8e5cd9', glyph: '☉',
      commander: 'アヌンナキ指揮官(名称未確認)',
      blurb: '神として崇められるサイキック種族。指揮官能力で「サイキックチャージ」を蓄え、それを盾と打点の両方に使う。精神支配(TAKE CONTROL)・複製(COPY)・帰還(RETURN)が得意。' },
    HIE: { ja: 'ヒエラルキー', en: 'Hierarchy', color: '#3fa7c9', glyph: '⚙',
      commander: 'テル=マクス (Tel\'Machus)',
      blurb: 'サイボーグ化した冷徹な秩序の勢力。強力な修復技術で防御を固める。指揮官能力 Restore(修復2)、サイボーグ統一デッキ向けのモジュール、SHIELD・ARMORED・CYPHER を持つ。' },
    SHA: { ja: 'シャンティ', en: "Shan'Ti", color: '#4fbf62', glyph: '❦',
      commander: 'ダル・ゲハリス (Dar Geharis)',
      blurb: '遺伝子を生ける兵器に作り変える種族。指揮官能力 Release Mutagen でユニットの MUTATE テキストを任意に発動できる。アベレーション(異形)を中心に、育つユニットで盤面を制圧する。' },
    HAJ: { ja: 'ハジル=ゴグ', en: 'Hajir-Gog', color: '#d9533f', glyph: '✠',
      commander: 'ハジル=ゴグ軍閥長(名称未確認)',
      blurb: '数で押し寄せる残忍で適応力の高い種族。指揮官能力 Thrash は任意の対象に1ダメージ。FURY(被ダメージ時誘発)・SWARM・ウェポン・全体強化で押し切る。' },
    CON: { ja: 'コンソーシアム', en: 'Consortium', color: '#d9a93f', glyph: '¤',
      commander: 'コンソーシアム総帥(名称未確認)',
      blurb: '陰謀と傭兵軍団の勢力。指揮官能力 Redeem Contract でランダムな傭兵(0/2 SCREEN/1/1 CLOAK/0/1 Trader)を雇う。CREDIT(前借り)で早いターンに強いカードを出し、CLOAK で奇襲する。' },
    TER: { ja: 'テラン', en: 'Terran', color: '#7a8ca6', glyph: '✦',
      commander: 'テラン提督(名称未確認)',
      blurb: '恐れを知らない歴戦の人類。巨大兵器(マッシブ)を擁する。指揮官能力で1/1のサポート・マリーンを配備し、ARMORED・SCREEN を持つ重装ユニットとウェポンで戦線を押し上げる。' },
    VRX: { ja: 'ヴラクシアン', en: 'Vraxxian', color: '#c95fa0', glyph: '♛',
      commander: 'ハイメイン・グリクス (High Mane Grix)',
      blurb: '2016年12月の拡張で追加された海賊的な獅子族。相手の手札を REVEAL(公開)し、公開枚数に応じて PILLAGE(略奪)効果やダメージが伸びる情報戦の勢力。' },
    NEU: { ja: '中立', en: 'Neutral', color: '#9aa0a6', glyph: '◇',
      commander: '—', blurb: 'どの勢力のデッキにも入れられるカード。シャドウ・オブ・ザ・カウンシル拡張のカウンシル・ユニットを含む。' }
  };

  const GROUPS = { Cyborg: 'サイボーグ', Aberration: 'アベレーション', Massive: 'マッシブ', Mercenary: 'マーセナリー', Vraxxian: 'ヴラクシアン', Council: 'カウンシル', Support: 'サポート' };

  const KW = {
    ACTIVATE: ['起動時', '手札からプレイされた時にのみ発生する効果。', 'A'],
    'ARC ATTACK': ['アーク攻撃', '攻撃した対象とその隣のユニットにもダメージを与える。', 'A'],
    ARMORED: ['装甲', '他のユニット(指揮官の攻撃を含む)からの攻撃1回につき1ダメージしか受けない。タクティクスや能力のダメージは全て受ける。', 'A'],
    ASSAULT: ['連撃', '1ターンに2回攻撃できる。', 'A'],
    BUNKER: ['掩蔽', '相手のタクティクスやモジュールの対象にならない。', 'A'],
    CLOAK: ['クローク', '攻撃するかダメージを与えるまで、相手の攻撃・能力・タクティクスの対象にならない。', 'A'],
    COPY: ['複製', '場、または相手の手札/デッキのカードを複製する。', 'A'],
    CREDIT: ['クレジット', 'CREDIT X:次の自分のターン開始時、サプライをX失う(前借り)。', 'A'],
    CRITICAL: ['クリティカル', 'ユニット同士の戦闘で、このユニットからダメージを受けたユニットは破壊される。', 'A'],
    CYPHER: ['サイファー', '伏せて置かれ、条件を満たすまで相手に公開されないタクティクス。', 'A'],
    DEVOUR: ['捕食', '戦闘で敵ユニットを破壊し、自身が生き残った時に発動。', 'A'],
    DISABLE: ['無力化', '対象は次の自分のターンに攻撃できない。', 'A'],
    ENERGIZE: ['エナジャイズ', 'ENERGIZE X:プレイ時にエネルギーをX払うと追加効果を得る(公式定義未確認・カード文面から推定)。', 'B'],
    FIREPOWER: ['火力', 'FIREPOWER X:自分のタクティクスのダメージ+X。計算式で決まるダメージには適用されない。', 'A'],
    FURY: ['激昂', 'このユニットがダメージを受けて生き残ると発動。', 'A'],
    'IGNORE ARMOR': ['装甲無視', '敵の ARMORED を無視して戦闘ダメージを与える。', 'A'],
    IMPACT: ['常在', '場にいる限り常に有効な効果。', 'A'],
    INVINCIBLE: ['無敵', 'ユニットや能力からダメージを受けない(タクティクスからは受ける)。', 'A'],
    LINK: ['リンク', 'LINK (グループ):そのグループの他の味方ユニットがいればプレイ時に発動(v1.3.11追加。定義は推定)。', 'B'],
    MOBILITY: ['機動', '場に出たターンに攻撃できる。', 'A'],
    MUTATE: ['変異', '「MUTATE:」以下の効果を発動させる。シャンティの指揮官能力などで誘発。', 'A'],
    NULLIFY: ['無効化', '対象ユニットのカードテキストと効果をすべて取り除く。', 'A'],
    PACIFIST: ['非戦', '攻撃できない。', 'A'],
    PILLAGE: ['略奪', 'REVEAL したカードを参照する追加効果(定義は推定)。', 'B'],
    'PSYCHIC CHARGE': ['サイキックチャージ', 'アヌンナキ指揮官の蓄積値。指揮官へのダメージを先に肩代わりし、多くのアヌンナキカードの効果量になる。', 'A'],
    REGENERATE: ['再生', '最大体力まで全回復する。', 'A'],
    RESTORE: ['修復', 'RESTORE X:体力をX回復する。', 'A'],
    RETURN: ['帰還', '対象ユニットを持ち主の手札に戻す。', 'A'],
    REVEAL: ['公開', '相手の手札のカードを公開状態にする。', 'A'],
    REVENGE: ['報復', 'このユニットが破壊された時に発動。', 'A'],
    SCREEN: ['遮蔽', '敵はこのユニットを、指揮官や他のユニットより先に攻撃しなければならない。', 'A'],
    SHIELD: ['シールド', '最初に受けるダメージを無視し、シールドを失う。', 'A'],
    SOAK: ['吸収', 'SOAK X:あらゆるダメージの最初のX点を無視する。', 'A'],
    SWARM: ['群れ', '他の味方ユニット1体につき攻撃力+1。', 'A'],
    'TAKE CONTROL': ['奪取', '対象ユニットのコントロールを得る。', 'A'],
    TRANSFORM: ['変身', 'ユニットを別のユニットに変える。', 'A'],
    VULNERABILITY: ['脆弱', 'VULNERABILITY X:あらゆるダメージ源からX点余分にダメージを受ける。', 'A'],
    WEAPON: ['ウェポン', '指揮官に装備させる武器。チャージ数が攻撃回数。', 'A'],
    ZEAL: ['熱狂', '敵ユニット1体につき攻撃力+1。', 'A'],
    ENERGY: ['エネルギー', '第2リソース。敵ユニット撃破・敵指揮官へのダメージ・空きモジュールスロットで獲得し、モジュールや ENERGIZE に使う。', 'A'],
    SUPPLY: ['サプライ', '基本リソース(マナ相当)。毎ターン最大値+1(上限10)。', 'A']
  };

  // ---------- カード ----------
  const C = [];
  const add = (o) => { C.push(o); };

  /* ===== 中立 / カウンシル ===== */
  add({ id: 'patrol_trooper', n: 'Patrol Trooper', ja: 'パトロール・トルーパー', f: 'NEU', t: 'U', c: 5, a: 4, h: 3, r: 'C', g: ['Council'],
    kw: { SHIELD: 1, ASSAULT: 1 }, tx: 'SHIELD。ASSAULT', en: 'SHIELD. ASSAULT', src: 'A', note: 'プレビュー時4/4 → v1.3.12で体力4→3' });
  add({ id: 'consul_serazia', n: 'Consul Serazia', ja: '執政官セラジア', f: 'NEU', t: 'U', c: 5, a: 4, h: 5, r: 'P', g: ['Council'],
    on: { play: [{ op: 'grant', t: 'AA', trig: 'revenge', fx: [{ op: 'summon', id: 'council_legate', n: 1 }] }] },
    tx: 'ACTIVATE:自軍の全ユニットは「REVENGE:1/1のカウンシル・レガートを配備」を得る。', en: 'ACTIVATE: All your units gain "REVENGE: Deploy 1/1 Council Legate".', src: 'A', note: '2017/8/18 プレビュー文面' });
  add({ id: 'council_legate', n: 'Council Legate', ja: 'カウンシル・レガート', f: 'NEU', t: 'U', c: 1, a: 1, h: 1, r: 'C', g: ['Council'], token: true,
    kw: { 'ARC ATTACK': 1 }, tx: 'ARC ATTACK', en: 'ARC ATTACK', src: 'A', note: 'セラジアのプレビューで提示されたトークン' });
  add({ id: 'oathbinder_kiri', n: 'Oathbinder Kiri', ja: '誓約者キリ', f: 'NEU', t: 'U', c: 4, a: 2, h: 5, r: 'H',
    on: { revengeAny: [{ op: 'buff', t: 'self', a: 1 }] },
    tx: 'REVENGE が発動するたびに、このユニットは攻撃力+1。', en: 'Whenever a REVENGE triggers, gain +1 attack.', src: 'A', note: 'シャドウ・オブ・ザ・カウンシル予約特典' });
  add({ id: 'council_imperial', n: 'Council Imperial', ja: 'カウンシル・インペリアル', f: 'NEU', t: 'U', c: 9, a: 7, h: 4, r: 'E', g: ['Council'],
    kw: { SCREEN: 1 }, on: { play: [{ op: 'kw', t: { s: 'OA', g: 'Council' }, k: 'SHIELD', v: 1 }] },
    tx: 'SCREEN。ACTIVATE:他の味方カウンシル・ユニットは SHIELD を得る。', src: 'B', note: 'コスト9・7/4はv1.3.12で確認。効果は再構成' });
  add({ id: 'council_voidliner', n: 'Council Voidliner', ja: 'カウンシル虚空船', f: 'NEU', t: 'U', c: 8, a: 6, h: 7, r: 'P', g: ['Council', 'Massive'],
    on: { play: [{ op: 'summon', id: 'council_legate', n: 2 }] }, tx: 'ACTIVATE:1/1のカウンシル・レガートを2体配備。', src: 'C', note: 'パラゴン評価スレッドで名称のみ確認' });
  add({ id: 'boss_hauser', n: 'Boss Hauser', ja: 'ボス・ハウザー', f: 'NEU', t: 'U', c: 6, a: 4, h: 5, r: 'H',
    kw: { ZEAL: 1 }, tx: 'ZEAL', src: 'C', note: 'シャドウ・オブ・ザ・カウンシル予約特典(名称のみ)' });
  add({ id: 'combat_engineer', n: 'Combat Engineer', ja: '戦闘工兵', f: 'NEU', t: 'U', c: 3, a: 2, h: 3, r: 'E', g: ['Support'],
    on: { endTurn: [{ op: 'buff', t: 'ROA', h: 1 }] }, tx: 'ターン終了時:ランダムな他の味方ユニット1体の最大体力+1。', en: 'At the end of your turn, give another random friendly unit +1 max health.', src: 'B', note: '効果はv1.2.2で確認。コスト・数値は再構成' });
  add({ id: 'fusion_bomb', n: 'Fusion Bomb', ja: '核融合爆弾', f: 'NEU', t: 'T', c: 8, r: 'H',
    on: { play: [{ op: 'destroy', t: 'AU' }, { op: 'noEnergy' }] }, tx: '全ユニットを破壊する。このターン、両指揮官はエネルギーを得られない。', en: 'Destroy all units. Neither commander gains energy this turn.', src: 'B', note: '効果は2017/5/22で確認。コストは再構成' });
  add({ id: 'time_echoes', n: 'Time Echoes', ja: '時の残響', f: 'NEU', t: 'T', c: 3, r: 'E', tg: { side: 'any', kind: 'unit' },
    on: { play: [{ op: 'echo', t: 'T', n: 2 }] }, tx: '選んだユニットの1/1のコピーを2体作る(自軍に配備)。ユニットにかかった効果は複製されない。', en: 'Create two 1/1 copies of target unit. Effects on the unit are not copied.', src: 'B', note: '効果はv1.2.2で確認。コストは再構成' });
  add({ id: 'swarm_sentinel', n: 'Swarm Sentinel', ja: '群れの歩哨', f: 'NEU', t: 'U', c: 3, a: 1, h: 4, r: 'E',
    kw: { SCREEN: 1 }, on: { endTurn: [{ op: 'if', c: { energy: 2 }, then: [{ op: 'energy', n: -2 }, { op: 'kw', t: 'self', k: 'SWARM', v: 1, until: 'next' }] }] },
    tx: 'SCREEN。ターン終了時:エネルギー2を消費し、次の自ターン終了時まで SWARM を得る(エネルギーが足りれば自動)。', en: 'SCREEN. At the end of your turn, spend 2 energy to gain SWARM until the end of your next turn.', src: 'B', note: '効果はv1.3.12で確認。コスト・数値は再構成' });
  add({ id: 'slicer', n: 'Slicer', ja: 'スライサー', f: 'NEU', t: 'U', c: 4, a: 3, h: 3, r: 'E',
    on: { play: [{ op: 'soakBreak' }] }, energize: [{ n: 6, fx: [{ op: 'lose', t: 'AU', k: 'BUNKER' }], tx: '全ユニットは BUNKER を失う' }],
    tx: 'ACTIVATE:SOAK を持つ全ユニットは SOAK を失い1ダメージを受ける。ENERGIZE 6:さらに全ユニットは BUNKER を失う。', en: 'ACTIVATE: All units with SOAK lose SOAK and take 1 damage. ENERGIZE 6: All units also lose BUNKER.', src: 'B', note: '効果はv1.3.12で確認。コスト・数値は再構成' });
  add({ id: 'anti_armor_squad', n: 'Anti Armor Squad', ja: '対装甲分隊', f: 'NEU', t: 'U', c: 3, a: 3, h: 2, r: 'C',
    kw: { 'IGNORE ARMOR': 1 }, tg: { side: 'enemy', kind: 'unit', opt: true, needEn: true },
    energize: [{ n: 4, fx: [{ op: 'lose', t: 'T', k: 'BUNKER' }, { op: 'lose', t: 'T', k: 'ARMORED' }], tx: '対象ユニットは BUNKER(と ARMORED)を失う' }],
    tx: '戦闘で敵の ARMORED を無視する。ENERGIZE 4:ACTIVATE:対象ユニットは BUNKER を失う。', en: 'Ignores enemy ARMORED in combat. ENERGIZE 4: ACTIVATE: Target unit loses BUNKER.', src: 'B', note: '効果はv1.3.12で確認(ARMORED喪失は再現版の補足)。コスト・数値は再構成' });
  add({ id: 'adept_of_time', n: 'Adept of Time', ja: '時の達人', f: 'NEU', t: 'U', c: 3, a: 2, h: 3, r: 'H',
    energize: [{ n: 3, fx: [{ op: 'kw', t: 'self', k: 'NOREVEAL', v: 1 }], tx: 'IMPACT:自分のカードは REVEAL されない。防いだ REVEAL 1回ごとに+1/+1' },
      { n: 8, fx: [{ op: 'buff', t: 'self', a: 1 }, { op: 'lose', t: 'AU', k: 'SCREEN' }], tx: '攻撃力+1。全ユニットは SCREEN を失う' }],
    tx: 'ENERGIZE 3:IMPACT:自分のカードは REVEAL されない。防いだ REVEAL 1回ごとに+1/+1。ENERGIZE 8:攻撃力+1。全ユニットは SCREEN を失う。', en: 'ENERGIZE 3: IMPACT: Your cards can\'t be REVEALED. +1/+1 for each REVEAL prevented. ENERGIZE 8: +1 attack. All units lose SCREEN.', src: 'B', note: '効果はv1.3.12で確認。コスト・数値は再構成' });
  add({ id: 'hk3_vindicator', n: 'HK-3 Vindicator', ja: 'HK-3ヴィンディケーター', f: 'NEU', t: 'U', c: 6, a: 4, h: 4, r: 'H',
    tg: { side: 'any', kind: 'unit', gs: ['Aberration', 'Cyborg'], opt: true },
    on: { play: [{ op: 'remember', t: 'T' }, { op: 'destroy', t: 'T' }] }, energize: [{ n: 6, fx: [{ op: 'summonRemembered', a: 1, h: 1 }], tx: '破壊したユニットの1/1コピーを配備' }],
    tx: 'ACTIVATE:アベレーションかサイボーグ1体を破壊する。ENERGIZE 6:破壊したユニットの1/1コピーを配備。', en: 'ACTIVATE: Destroy an Aberration or Cyborg. ENERGIZE 6: Deploy a 1/1 copy of it.', src: 'B', note: '効果はv1.3.12で確認。コスト・数値は再構成' });
  add({ id: 'phoenix_fighter', n: 'Phoenix Fighter', ja: 'フェニックス戦闘機', f: 'NEU', t: 'U', c: 2, a: 3, h: 2, r: 'E',
    kw: { SOAK: 2 }, on: { play: [{ op: 'crate', side: 'enemy' }] }, tx: 'SOAK 2。ACTIVATE:相手は追加のサプライ・クレートを1つ得る。', en: 'SOAK 2. ACTIVATE: Your opponent gets an additional Supply Crate.', src: 'B', note: '効果は2017/5/22で確認。コスト・数値は再構成' });
  add({ id: 'zeron', n: 'Zeron', ja: 'ゼロン', f: 'NEU', t: 'U', c: 4, a: 4, h: 3, r: 'H', kw: { MOBILITY: 1 },
    tx: 'MOBILITY', src: 'B', note: 'コスト4・体力3はv1.3.12で確認。攻撃力・効果は再構成' });
  add({ id: 'the_outsider', n: 'The Outsider', ja: '異邦人', f: 'NEU', t: 'U', c: 6, a: 6, h: 3, r: 'H', kw: { CLOAK: 1 },
    tx: 'CLOAK', src: 'B', note: 'コスト6・6/3はv1.3.12で確認。効果は再構成' });
  add({ id: 'duskwind_guerilla', n: 'Duskwind Guerilla', ja: 'ダスクウィンド・ゲリラ', f: 'NEU', t: 'U', c: 1, a: 1, h: 1, r: 'C', kw: { CLOAK: 1 },
    on: { attack: [{ op: 'buff', t: 'self', a: 1, temp: 1 }] }, tx: 'CLOAK。攻撃時:このターン攻撃力+1。', src: 'C', note: '「必須の安価カード」として名称のみ確認' });
  add({ id: 'gargoyle_bomber', n: 'Gargoyle Bomber', ja: 'ガーゴイル爆撃機', f: 'NEU', t: 'U', c: 2, a: 2, h: 1, r: 'C',
    on: { revenge: [{ op: 'dmg', t: 'RE', n: 2 }] }, tx: 'REVENGE:ランダムな敵ユニット1体に2ダメージ。', src: 'C', note: '「必須の安価カード」として名称のみ確認' });
  add({ id: 'leviathan', n: 'Leviathan', ja: 'リヴァイアサン', f: 'NEU', t: 'U', c: 10, a: 8, h: 9, r: 'H', g: ['Massive'], kw: { SCREEN: 1, SOAK: 1 },
    tx: 'SCREEN。SOAK 1', src: 'C', note: 'v1.3.12バグ修正欄で名称のみ確認' });
  add({ id: 'veteran_scout', n: 'Veteran Scout', ja: '古参斥候', f: 'NEU', t: 'U', c: 2, a: 1, h: 2, r: 'C',
    on: { play: [{ op: 'draw', n: 1 }] }, tx: 'ACTIVATE:カードを1枚引く。', src: 'C', note: '名称のみ確認' });
  add({ id: 'reddow', n: 'Reddow', ja: 'レドウ', f: 'NEU', t: 'U', c: 2, a: 2, h: 3, r: 'E', kw: { MOBILITY: 1 },
    tx: 'MOBILITY', src: 'B', note: '転載断片「MOBILITY」「体力1→3」を採用。コストは再構成' });
  add({ id: 'blaster', n: 'Blaster', ja: 'ブラスター', f: 'NEU', t: 'W', c: 2, a: 2, ch: 2, r: 'C',
    tx: 'WEAPON(攻撃力2/チャージ2)', src: 'C', note: 'ウェポンとして名称のみ確認' });
  add({ id: 'the_manovar', n: 'The Manovar', ja: 'マノヴァー', f: 'NEU', t: 'U', c: 7, a: 5, h: 6, r: 'H', kw: { 'ARC ATTACK': 1 },
    tx: 'ARC ATTACK', src: 'C', note: 'v1.3 アニメーションカード告知で名称のみ確認' });
  add({ id: 'anti_personnel_turret', n: 'Anti-personnel Turret', ja: '対人砲塔', f: 'NEU', t: 'U', c: 4, a: 1, h: 5, r: 'C', kw: { PACIFIST: 1 },
    on: { endTurn: [{ op: 'dmg', t: 'RE', n: 1 }, { op: 'dmg', t: 'RE', n: 1 }] }, tx: 'PACIFIST。ターン終了時:ランダムな敵ユニットに1ダメージを2回。', src: 'B', note: '体力5はv1.3.12で確認。他は再構成' });

  /* ===== アヌンナキ ===== */
  add({ id: 'grand_inquisitor_toroth', n: 'Grand Inquisitor Toroth', ja: '大審問官トロス', f: 'ANN', t: 'U', c: 7, a: 4, h: 8, r: 'P',
    tg: { side: 'enemy', kind: 'unit', gs: ['Massive', 'Cyborg', 'Aberration'], opt: true },
    on: { play: [{ op: 'control', t: 'T', until: 'next' }] },
    tx: 'ACTIVATE:マッシブ、サイボーグ、アベレーションのいずれかのユニット1体のコントロールを、次の自ターン終了時まで得る。', en: 'ACTIVATE: Take control of a Massive, Cyborg or Aberration unit until the end of your next turn.', src: 'A', note: '2017/7/21 プレビュー文面' });
  add({ id: 'ethereal_weapon', n: 'Ethereal Weapon', ja: 'エーテルの武器', f: 'ANN', t: 'T', c: 1, r: 'E',
    on: { play: [{ op: 'mirrorWeapon' }] }, needs: 'enemyWeapon',
    tx: '相手のウェポンのコピーを装備する。それはチャージ+1を得る。', en: 'Equip a copy of your opponent\'s weapon. It gains +1 charge.', src: 'A', note: '2016/12/19 プレビュー文面' });
  add({ id: 'toroths_scepter', n: "Toroth's Scepter", ja: 'トロスの王笏', f: 'ANN', t: 'W', c: 3, a: 2, ch: 2, r: 'H',
    on: { play: [{ op: 'psy', n: 1 }] }, tx: 'WEAPON(攻撃力2/チャージ2)。ACTIVATE:サイキックチャージ+1。', src: 'B', note: 'チャージ2はv1.3.12で確認(3→2)。他は再構成' });
  add({ id: 'mystic_apprentice', n: 'Mystic Apprentice', ja: '神秘の徒弟', f: 'ANN', t: 'U', c: 1, a: 1, h: 2, r: 'C',
    on: { play: [{ op: 'psy', n: 1 }] }, tx: 'ACTIVATE:サイキックチャージ+1。', src: 'B', note: '体力2は2017/5/22で確認。他は再構成' });
  add({ id: 'mass_indoctrination', n: 'Mass Indoctrination', ja: '大衆教化', f: 'ANN', t: 'T', c: 6, r: 'H', tg: { side: 'enemy', kind: 'unit', maxAtk: 'psy+2' },
    on: { play: [{ op: 'control', t: 'T' }] }, tx: '攻撃力が(サイキックチャージ+2)以下の敵ユニット1体のコントロールを得る。', src: 'C', note: '名称のみ確認' });
  add({ id: 'paranoia', n: 'Paranoia', ja: 'パラノイア', f: 'ANN', t: 'T', c: 2, r: 'C', tg: { side: 'enemy', kind: 'unit' },
    on: { play: [{ op: 'disable', t: 'T' }, { op: 'if', c: { psy: 3 }, then: [{ op: 'draw', n: 1 }] }] },
    tx: '敵ユニット1体を DISABLE。サイキックチャージが3以上ならカードを1枚引く。', src: 'C', note: '名称のみ確認' });
  add({ id: 'mad_seer', n: 'Mad Seer', ja: '狂える予言者', f: 'ANN', t: 'U', c: 3, a: 2, h: 3, r: 'C',
    on: { play: [{ op: 'draw', n: 1 }, { op: 'if', c: { psy: 3 }, then: [{ op: 'draw', n: 1 }] }] },
    tx: 'ACTIVATE:カードを1枚引く。サイキックチャージが3以上ならさらに1枚引く。', src: 'C', note: '名称のみ確認' });
  add({ id: 'tower_of_eyes', n: 'Tower of Eyes', ja: '眼の塔', f: 'ANN', t: 'U', c: 3, a: 0, h: 6, r: 'E', kw: { SCREEN: 1, PACIFIST: 1 },
    on: { endTurn: [{ op: 'psy', n: 1 }] }, tx: 'SCREEN。PACIFIST。ターン終了時:サイキックチャージ+1。', src: 'C', note: '名称のみ確認' });
  add({ id: 'beholder', n: 'Beholder', ja: 'ビホルダー', f: 'ANN', t: 'U', c: 5, a: 4, h: 5, r: 'E', tg: { side: 'enemy', kind: 'unit', opt: true },
    on: { play: [{ op: 'dmg', t: 'T', n: 'psy' }] }, tx: 'ACTIVATE:敵ユニット1体にサイキックチャージと同じ値のダメージ。', src: 'C', note: '名称のみ確認' });
  add({ id: 'preacher', n: 'Preacher', ja: '説教者', f: 'ANN', t: 'U', c: 2, a: 1, h: 3, r: 'C', tg: { side: 'ally', kind: 'unit', opt: true },
    on: { play: [{ op: 'kw', t: 'T', k: 'SHIELD', v: 1 }] }, tx: 'ACTIVATE:味方ユニット1体に SHIELD を与える。', src: 'C', note: 'v1.3 アニメーションカード告知で名称のみ確認' });
  add({ id: 'gatekeeper', n: 'Gatekeeper', ja: '門番', f: 'ANN', t: 'U', c: 2, a: 1, h: 4, r: 'C', kw: { SCREEN: 1 },
    tx: 'SCREEN', src: 'C', note: 'バランス議論で名称のみ確認(勢力推定)' });
  add({ id: 'portal_master', n: 'Portal Master', ja: 'ポータルの主', f: 'ANN', t: 'U', c: 5, a: 3, h: 4, r: 'E', tg: { side: 'any', kind: 'unit', opt: true },
    on: { play: [{ op: 'bounce', t: 'T' }] }, tx: 'ACTIVATE:ユニット1体を持ち主の手札に RETURN する。', src: 'B', note: '攻撃力3はv1.3.9で確認。勢力・他は再構成' });
  add({ id: 'psychic_overload', n: 'Psychic Overload', ja: 'サイキック・オーバーロード', f: 'ANN', t: 'T', c: 3, r: 'E', tg: { side: 'enemy', kind: 'char' },
    on: { play: [{ op: 'dmg', t: 'T', n: 'psy*2', calc: 1 }] }, tx: '対象に(サイキックチャージ×2)のダメージ。計算式ダメージのため FIREPOWER は適用されない。', src: 'C', note: 'FIREPOWER の補足説明で名称のみ確認' });
  add({ id: 'the_restless', n: 'The Restless', ja: '安らがぬ者', f: 'ANN', t: 'U', c: 6, a: 5, h: 4, r: 'P', kw: { CLOAK: 1 },
    on: { revenge: [{ op: 'returnSelf' }] }, tx: 'CLOAK。REVENGE:このカードを手札に戻す。', src: 'C', note: 'パラゴン(名称のみ確認)' });
  add({ id: 'horror_of_the_shade', n: 'Horror of the Shade', ja: '影の恐怖', f: 'ANN', t: 'U', c: 8, a: 6, h: 6, r: 'P',
    on: { play: [{ op: 'spendPsy', fx: [{ op: 'dmg', t: 'REA', n: 2 }] }] }, tx: 'ACTIVATE:サイキックチャージをすべて消費し、1点につきランダムな敵に2ダメージ。', src: 'C', note: 'パラゴン(名称のみ確認)' });
  add({ id: 'soul_devourer', n: 'Soul Devourer', ja: '魂喰らい', f: 'ANN', t: 'U', c: 7, a: 5, h: 7, r: 'P',
    on: { devour: [{ op: 'psy', n: 2 }, { op: 'regen', t: 'self' }] }, tx: 'DEVOUR:サイキックチャージ+2し、このユニットを REGENERATE。', src: 'C', note: 'パラゴン(名称のみ確認)' });
  add({ id: 'fen_fire', n: 'Fen Fire', ja: '鬼火', f: 'ANN', t: 'T', c: 5, r: 'P',
    on: { play: [{ op: 'dmg', t: 'AE', n: 'psy', calc: 1 }] }, tx: '全ての敵ユニットにサイキックチャージと同じ値のダメージ。', src: 'C', note: 'パラゴン(名称のみ確認)' });

  /* ===== ヒエラルキー ===== */
  add({ id: 'cryptographer', n: 'Cryptographer', ja: '暗号解読者', f: 'HIE', t: 'U', c: 6, a: 5, h: 7, r: 'E', g: ['Council'], kw: { SHIELD: 1 },
    on: { play: [{ op: 'if', c: { hasGroup: 'Support' }, then: [{ op: 'stealCypher' }] }] },
    tx: 'SHIELD。LINK (Support):ランダムな敵の CYPHER 1枚のコントロールを得る。', en: 'SHIELD. LINK (Support): Take control of a random enemy CYPHER.', src: 'A', note: '2017/8/3 プレビュー文面' });
  add({ id: 'power_engineer', n: 'Power Engineer', ja: '動力技師', f: 'HIE', t: 'U', c: 5, a: 3, h: 4, r: 'E', g: ['Cyborg', 'Support'],
    on: { endTurn: [{ op: 'heal', t: { s: 'AA', g: 'Cyborg' }, n: 1 }] }, tx: 'ターン終了時:味方サイボーグ全体を RESTORE 1。', src: 'B', note: 'コスト5・エリートはプレビューで確認。他は再構成' });
  add({ id: 'techmaster_andros', n: 'Techmaster Andros', ja: '技術長アンドロス', f: 'HIE', t: 'U', c: 2, a: 2, h: 2, r: 'H', g: ['Cyborg'], tg: { side: 'ally', kind: 'unit', g: 'Cyborg', opt: true },
    on: { play: [{ op: 'buff', t: 'T', a: 1, h: 1 }] }, tx: 'ACTIVATE:味方サイボーグ1体に+1/+1。', src: 'B', note: 'コスト2・2/2はv1.3.12で確認。勢力・効果は再構成' });
  add({ id: 'hunter_seeker_drones', n: 'Hunter Seeker Drones', ja: 'ハンターシーカー・ドローン', f: 'HIE', t: 'U', c: 3, a: 3, h: 1, r: 'C', g: ['Cyborg'], kw: { SHIELD: 1 },
    tx: 'SHIELD', src: 'B', note: '攻撃力3・SHIELDはv1.3.8断片で確認。他は再構成' });
  add({ id: 'cytek_drone', n: 'Cytek Drone', ja: 'サイテック・ドローン', f: 'HIE', t: 'U', c: 1, a: 1, h: 1, r: 'C', g: ['Cyborg'],
    on: { revenge: [{ op: 'heal', t: 'ac', n: 1 }] }, tx: 'REVENGE:自分の指揮官を RESTORE 1。', src: 'C', note: '名称のみ確認' });
  add({ id: 'carbonic_protector', n: 'Carbonic Protector', ja: '炭素の守護者', f: 'HIE', t: 'U', c: 3, a: 1, h: 4, r: 'C', g: ['Cyborg'], kw: { SCREEN: 1 },
    tx: 'SCREEN', src: 'C', note: 'アニメーションカード告知で名称のみ確認(勢力推定)' });
  add({ id: 'material_defender', n: 'Material Defender', ja: '物質防衛者', f: 'HIE', t: 'U', c: 5, a: 2, h: 4, r: 'E', g: ['Cyborg'], kw: { SCREEN: 1, ARMORED: 1 },
    tx: 'SCREEN。ARMORED', src: 'C', note: 'アニメーションカード告知で名称のみ確認(勢力推定)' });
  add({ id: 'replicant', n: 'Replicant', ja: 'レプリカント', f: 'HIE', t: 'U', c: 4, a: 1, h: 1, r: 'H', g: ['Cyborg'], tg: { side: 'any', kind: 'unit', opt: true, notSelf: true },
    on: { play: [{ op: 'becomeCopy', t: 'T' }] }, tx: 'ACTIVATE:COPY:このユニットは対象ユニットのコピー(グループにサイボーグを追加)に TRANSFORM する。', src: 'C', note: 'アニメーションカード告知で名称のみ確認' });
  add({ id: 'regulator', n: 'Regulator', ja: 'レギュレーター', f: 'HIE', t: 'U', c: 4, a: 2, h: 3, r: 'E', g: ['Cyborg'], tg: { side: 'any', kind: 'unit', opt: true },
    on: { play: [{ op: 'nullify', t: 'T' }] }, tx: 'ACTIVATE:ユニット1体を NULLIFY する。', src: 'C', note: '上位デッキリストで名称のみ確認(勢力推定)' });
  add({ id: 'automated_defences', n: 'Automated Defences', ja: '自動防衛', f: 'HIE', t: 'T', c: 2, r: 'E', cy: { on: 'enemyAttackCmd', fx: [{ op: 'dmg', t: 'T', n: 4 }] },
    tx: 'CYPHER:敵ユニットが自分の指揮官を攻撃した時、そのユニットに4ダメージ。', src: 'C', note: '上位デッキリストで名称のみ確認(勢力推定)' });
  add({ id: 'interphasic_weaponry', n: 'Interphasic Weaponry', ja: '相間兵装', f: 'HIE', t: 'T', c: 2, r: 'C', tg: { side: 'ally', kind: 'unit' },
    on: { play: [{ op: 'buff', t: 'T', a: 2 }, { op: 'kw', t: 'T', k: 'IGNORE ARMOR', v: 1 }] }, tx: '味方ユニット1体に攻撃力+2と IGNORE ARMOR を与える。', src: 'C', note: '名称のみ確認' });
  add({ id: 'fleet_core', n: 'Fleet Core', ja: '艦隊中枢', f: 'HIE', t: 'U', c: 7, a: 5, h: 7, r: 'P', g: ['Cyborg', 'Massive'],
    aura: { a: 1, g: 'Cyborg' }, tx: 'IMPACT:他の味方サイボーグの攻撃力+1。', src: 'C', note: 'パラゴン(名称のみ確認)' });
  add({ id: 'archon_carrier', n: 'Archon Carrier', ja: 'アルコン母艦', f: 'HIE', t: 'U', c: 8, a: 5, h: 8, r: 'P', g: ['Massive'],
    on: { play: [{ op: 'summon', id: 'cytek_drone', n: 3 }] }, tx: 'ACTIVATE:サイテック・ドローンを3体配備。', src: 'C', note: 'パラゴン(名称のみ確認)' });

  /* ===== シャンティ ===== */
  add({ id: 'infected_militia', n: 'Infected Militia', ja: '感染民兵', f: 'SHA', t: 'U', c: 2, a: 2, h: 3, r: 'C', g: ['Aberration'],
    on: { mutate: [{ op: 'buff', t: 'self', a: 1, h: 1 }] }, tx: 'MUTATE:+1/+1。', src: 'C', note: 'デッキリストで名称のみ確認' });
  add({ id: 'fleshborer', n: 'Fleshborer', ja: '肉穿ち', f: 'SHA', t: 'U', c: 3, a: 3, h: 2, r: 'C', g: ['Aberration'],
    on: { mutate: [{ op: 'buff', t: 'self', a: 2 }] }, tx: 'MUTATE:攻撃力+2。', src: 'C', note: '名称のみ確認' });
  add({ id: 'geneshaper_apprentice', n: 'Geneshaper Apprentice', ja: 'ジーンシェイパー見習い', f: 'SHA', t: 'U', c: 1, a: 1, h: 1, r: 'C', g: ['Aberration'],
    tg: { side: 'ally', kind: 'unit', mutable: true, opt: true }, on: { play: [{ op: 'mutate', t: 'T' }] }, tx: 'ACTIVATE:味方ユニット1体を MUTATE する。', src: 'C', note: 'モジュール Plague Nexus が生成するカードとして名称確認' });
  add({ id: 'disciple_of_asag', n: 'Disciple of Asag', ja: 'アサグの使徒', f: 'SHA', t: 'U', c: 3, a: 2, h: 4, r: 'E',
    on: { endTurn: [{ op: 'mutate', t: { s: 'RA', g: 'Aberration', mut: 1 } }] }, tx: 'ターン終了時:ランダムな味方アベレーション1体を MUTATE する。', src: 'C', note: 'バグ修正記載で名称のみ確認' });
  add({ id: 'toxic_creeper', n: 'Toxic Creeper', ja: '有毒の匍匐者', f: 'SHA', t: 'U', c: 1, a: 1, h: 2, r: 'C', g: ['Aberration'],
    on: { revenge: [{ op: 'dmg', t: 'RE', n: 1 }], mutate: [{ op: 'regen', t: 'self' }, { op: 'buff', t: 'self', h: 1 }] },
    tx: 'REVENGE:ランダムな敵ユニットに1ダメージ。MUTATE:REGENERATE し、体力+1。', src: 'B', note: 'コスト1(0→1)・体力2(1→2)はパッチで確認。効果は再構成' });
  add({ id: 'spider_egg', n: 'Spider Egg', ja: '蜘蛛の卵', f: 'SHA', t: 'U', c: 1, a: 0, h: 3, r: 'C', g: ['Aberration'], kw: { PACIFIST: 1 },
    on: { mutate: [{ op: 'transform', t: 'self', id: 'fleshborer' }] }, tx: 'PACIFIST。MUTATE:肉穿ち(3/2)に TRANSFORM する。', src: 'C', note: 'Natural Selection 関連の更新文で名称のみ確認' });
  add({ id: 'parasitic_thrall', n: 'Parasitic Thrall', ja: '寄生隷属体', f: 'SHA', t: 'U', c: 5, a: 4, h: 4, r: 'P', g: ['Aberration'],
    on: { devour: [{ op: 'summonRemembered', a: 1, h: 1, from: 'victim' }], mutate: [{ op: 'kw', t: 'self', k: 'ASSAULT', v: 1 }] },
    tx: 'DEVOUR:破壊した敵ユニットの1/1コピーを自軍に配備。MUTATE:ASSAULT を得る。', src: 'C', note: 'パラゴン(名称のみ確認)' });
  add({ id: 'weaver_of_synthus', n: 'Weaver of Synthus', ja: 'シンサスの織り手', f: 'SHA', t: 'U', c: 6, a: 4, h: 6, r: 'P',
    on: { startTurn: [{ op: 'mutate', t: { s: 'AA', g: 'Aberration' } }] }, tx: '自ターン開始時:味方アベレーション全体を MUTATE する。', src: 'C', note: 'パラゴン(名称のみ確認)' });
  add({ id: 'life_advance', n: 'Life Advance', ja: '生命の前進', f: 'SHA', t: 'T', c: 0, r: 'C', tg: { side: 'ally', kind: 'unit', mutable: true },
    on: { play: [{ op: 'mutate', t: 'T' }] }, tx: '味方ユニット1体を MUTATE する。', src: 'B', note: 'コスト0(1→0)はv1.3.12で確認。効果は再構成' });
  add({ id: 'accelerated_bloom', n: 'Accelerated Bloom', ja: '加速開花', f: 'SHA', t: 'T', c: 2, r: 'C', tg: { side: 'ally', kind: 'unit' },
    on: { play: [{ op: 'mutate', t: 'T' }, { op: 'buff', t: 'T', h: 2 }, { op: 'draw', n: 1 }] }, tx: '味方ユニット1体を MUTATE し、体力+2。カードを1枚引く。', src: 'C', note: '名称のみ確認' });
  add({ id: 'minerva_spores', n: 'Minerva Spores', ja: 'ミネルヴァ胞子', f: 'SHA', t: 'T', c: 4, r: 'E',
    on: { play: [{ op: 'mutate', t: 'AA' }] }, tx: '味方ユニット全体を MUTATE する。', src: 'C', note: '名称のみ確認' });
  add({ id: 'ravager', n: 'Ravager', ja: '略奪者', f: 'SHA', t: 'U', c: 6, a: 6, h: 5, r: 'P', g: ['Aberration'],
    on: { mutate: [{ op: 'dmg', t: 'AE', n: 1 }] }, tx: 'MUTATE:全ての敵ユニットに1ダメージ。', src: 'C', note: 'パラゴン(名称のみ確認・勢力推定)' });

  /* ===== ハジル=ゴグ ===== */
  add({ id: 'rippers', n: 'Rippers', ja: 'リッパーズ', f: 'HAJ', t: 'U', c: 2, a: 2, h: 2, r: 'C',
    on: { endTurn: [{ op: 'buff', t: 'self', a: 1 }] }, tx: 'ターン終了時:攻撃力+1。', en: 'At the end of your turn, gain +1 attack.', src: 'B', note: '効果は2017/5/22で確認。勢力・数値は再構成' });
  add({ id: 'rend', n: 'Rend', ja: '引き裂き', f: 'HAJ', t: 'T', c: 2, r: 'E',
    on: { play: [{ op: 'setModule', slot: 0, id: 'rend_mod' }] }, tx: '左端のモジュールを「ランダムな敵ユニット1体に2ダメージ。次回以降:ダメージ+1」に置き換える。', en: 'Replace your leftmost module with "Deal 2 damage to a random enemy unit. Subsequent uses: +1 damage".', src: 'B', note: '効果はv1.3.4で確認。コストは再構成' });
  add({ id: 'rampage', n: 'Rampage', ja: '暴走', f: 'HAJ', t: 'T', c: 3, r: 'C', tg: { side: 'ally', kind: 'unit' },
    on: { play: [{ op: 'buff', t: 'T', a: 3, temp: 1 }, { op: 'kw', t: 'T', k: 'ASSAULT', v: 1, temp: 1 }, { op: 'extraAttack', t: 'T' }] }, tx: '味方ユニット1体はこのターン攻撃力+3と ASSAULT を得る。', src: 'C', note: '上位デッキリストで名称のみ確認' });
  add({ id: 'frenzy', n: 'Frenzy', ja: '狂乱', f: 'HAJ', t: 'T', c: 1, r: 'C',
    on: { play: [{ op: 'buff', t: 'AA', a: 1, temp: 1 }] }, tx: '味方ユニット全体はこのターン攻撃力+1。', src: 'C', note: '名称のみ確認' });
  add({ id: 'oppressor', n: 'Oppressor', ja: '圧制者', f: 'HAJ', t: 'U', c: 4, a: 3, h: 5, r: 'E', kw: { ZEAL: 1 },
    tx: 'ZEAL', src: 'C', note: '名称のみ確認' });
  add({ id: 'bloodsworn_berserker', n: 'Bloodsworn Berserker', ja: '血誓の狂戦士', f: 'HAJ', t: 'U', c: 2, a: 2, h: 3, r: 'C',
    on: { fury: [{ op: 'buff', t: 'self', a: 2 }] }, tx: 'FURY:攻撃力+2。', src: 'C', note: '名称のみ確認' });
  add({ id: 'adrenal_overload', n: 'Adrenal Overload', ja: 'アドレナル過負荷', f: 'HAJ', t: 'T', c: 1, r: 'C', tg: { side: 'ally', kind: 'unit' },
    on: { play: [{ op: 'dmg', t: 'T', n: 1, calc: 1 }, { op: 'buff', t: 'T', a: 2 }] }, tx: '味方ユニット1体に1ダメージを与え、攻撃力+2(FURY を誘発させられる)。', src: 'C', note: '名称のみ確認' });
  add({ id: 'adrenal_transformation', n: 'Adrenal Transformation', ja: 'アドレナル変容', f: 'HAJ', t: 'T', c: 3, r: 'E', tg: { side: 'ally', kind: 'unit' },
    on: { play: [{ op: 'buff', t: 'T', a: 2, h: 2 }, { op: 'grant', t: 'T', trig: 'fury', fx: [{ op: 'buff', t: 'self', a: 1 }] }] }, tx: '味方ユニット1体に+2/+2と「FURY:攻撃力+1」を与える。', src: 'C', note: '名称のみ確認' });
  add({ id: 'refurbish_weapon', n: 'Refurbish Weapon', ja: '武器再整備', f: 'HAJ', t: 'T', c: 1, r: 'C', needs: 'ownWeapon',
    on: { play: [{ op: 'weaponUp', a: 1, ch: 1 }] }, tx: '装備中のウェポンは攻撃力+1、チャージ+1。', src: 'C', note: '名称のみ確認' });
  add({ id: 'scour', n: 'Scour', ja: '掃討', f: 'HAJ', t: 'T', c: 3, r: 'E',
    on: { play: [{ op: 'dmg', t: 'AU', n: 2 }] }, tx: '全てのユニットに2ダメージ。', src: 'C', note: '名称のみ確認' });
  add({ id: 'rage_dok', n: 'Rage Dok', ja: 'レイジ・ドク', f: 'HAJ', t: 'U', c: 3, a: 3, h: 3, r: 'E', g: ['Support'],
    on: { play: [{ op: 'grant', t: 'OA', trig: 'fury', fx: [{ op: 'buff', t: 'self', a: 1 }] }] }, tx: 'ACTIVATE:他の味方ユニット全体は「FURY:攻撃力+1」を得る。', src: 'C', note: '名称のみ確認' });
  add({ id: 'hellfire_cannon', n: 'Hellfire Cannon', ja: 'ヘルファイア砲', f: 'HAJ', t: 'W', c: 3, a: 3, ch: 3, r: 'E',
    tx: 'WEAPON(攻撃力3/チャージ3)', src: 'C', note: '主力ウェポンとして名称のみ確認' });
  add({ id: 'war_banner', n: 'War Banner', ja: '軍旗', f: 'HAJ', t: 'T', c: 2, r: 'C',
    on: { play: [{ op: 'kw', t: 'AA', k: 'SWARM', v: 1, temp: 1 }] }, tx: '味方ユニット全体はこのターン SWARM を得る。', src: 'B', note: 'コスト2(3→2)はv1.2.2で確認。他は再構成' });
  add({ id: 'mad_volley', n: 'Mad Volley', ja: '狂乱の斉射', f: 'HAJ', t: 'T', c: 2, r: 'C',
    on: { play: [{ op: 'dmg', t: 'REA', n: 1 }, { op: 'dmg', t: 'REA', n: 1 }, { op: 'dmg', t: 'REA', n: 1 }] }, tx: 'ランダムな敵に1ダメージを3回与える。', src: 'B', note: 'コスト2(3→2)はv1.2.7で確認。他は再構成' });
  add({ id: 'land_crawler', n: 'Land Crawler', ja: 'ランドクローラー', f: 'HAJ', t: 'U', c: 7, a: 2, h: 8, r: 'P', g: ['Massive'], kw: { SWARM: 1, SCREEN: 1 },
    tx: 'SWARM。SCREEN', src: 'C', note: 'パラゴン(名称のみ確認)' });
  add({ id: 'spider_walker', n: 'Spider Walker', ja: 'スパイダーウォーカー', f: 'HAJ', t: 'U', c: 3, a: 3, h: 3, r: 'C',
    on: { fury: [{ op: 'dmg', t: 'RE', n: 1 }] }, tx: 'FURY:ランダムな敵ユニットに1ダメージ。', src: 'C', note: 'バランス議論で名称のみ確認(勢力推定)' });

  /* ===== コンソーシアム ===== */
  add({ id: 'despaired_debtor', n: 'Despaired Debtor', ja: '絶望した債務者', f: 'CON', t: 'U', c: 1, a: 3, h: 2, r: 'H', g: ['Mercenary'], kw: { CREDIT: 1 },
    tx: 'CREDIT 1', src: 'B', note: 'キャンペーン「ネルガル教団」報酬。コスト1・ヒロイックは確認、他は再構成' });
  add({ id: 'arms_merchant', n: 'Arms Merchant', ja: '武器商人', f: 'CON', t: 'U', c: 3, a: 2, h: 3, r: 'C', g: ['Mercenary'], kw: { CREDIT: 1 },
    on: { play: [{ op: 'equip', id: 'blaster' }] }, tx: 'CREDIT 1。ACTIVATE:ブラスター(2/2)を装備する。', src: 'C', note: '傭兵デッキで名称のみ確認' });
  add({ id: 'field_commander', n: 'Field Commander', ja: '野戦指揮官', f: 'CON', t: 'U', c: 4, a: 3, h: 4, r: 'E',
    aura: { a: 1, g: 'Mercenary' }, tx: 'IMPACT:他の味方マーセナリーの攻撃力+1。', src: 'C', note: '傭兵デッキで名称のみ確認' });
  add({ id: 'veteran_advisor', n: 'Veteran Advisor', ja: '古参顧問', f: 'CON', t: 'U', c: 3, a: 2, h: 3, r: 'E', kw: { CREDIT: 2 },
    on: { play: [{ op: 'draw', n: 2 }] }, tx: 'CREDIT 2。ACTIVATE:カードを2枚引く。', src: 'C', note: '傭兵デッキで名称のみ確認' });
  add({ id: 'double_retainer', n: 'Double Retainer', ja: '二重雇用', f: 'CON', t: 'T', c: 3, r: 'C',
    on: { play: [{ op: 'summon', id: 'merc_bodyguard', n: 1 }, { op: 'summon', id: 'merc_infiltrator', n: 1 }] }, tx: '傭兵護衛(0/2 SCREEN)と傭兵潜入員(1/1 CLOAK)を配備する。', src: 'C', note: '傭兵デッキで名称のみ確認' });
  add({ id: 'syndicate_enforcers', n: 'Syndicate Enforcers', ja: 'シンジケートの執行者', f: 'CON', t: 'U', c: 4, a: 3, h: 4, r: 'E', g: ['Mercenary'],
    on: { cardPlayed: [{ op: 'dmg', t: 'RE', n: 1 }] }, tx: '自分がカードをプレイするたびに、ランダムな敵ユニットに1ダメージ。', en: 'Whenever you play a card, deal 1 damage to a random enemy.', src: 'B', note: '効果は2017/5/22で確認。勢力・数値は再構成' });
  add({ id: 'mr_bradford', n: 'Mr Bradford', ja: 'ブラッドフォード氏', f: 'CON', t: 'U', c: 5, a: 4, h: 4, r: 'P',
    on: { play: [{ op: 'copyEnemyHand', n: 1 }] }, tx: 'ACTIVATE:COPY:相手の手札のランダムなカード1枚のコピーを手札に加える。', src: 'C', note: 'パラゴン(名称のみ確認)' });
  add({ id: 'mr_slink', n: 'Mr Slink', ja: 'スリンク氏', f: 'CON', t: 'U', c: 3, a: 3, h: 2, r: 'P', g: ['Mercenary'], kw: { CLOAK: 1 },
    on: { hitCmd: [{ op: 'draw', n: 1 }] }, tx: 'CLOAK。このユニットが敵指揮官にダメージを与えるたびに、カードを1枚引く。', src: 'C', note: 'パラゴン(名称のみ確認)' });
  add({ id: 'blockade_runner', n: 'Blockade Runner', ja: '封鎖突破船', f: 'CON', t: 'U', c: 2, a: 2, h: 2, r: 'C', g: ['Mercenary'], kw: { MOBILITY: 1 },
    tx: 'MOBILITY', src: 'B', note: 'コスト2(1→2)はv1.3.12で確認。勢力・他は再構成' });
  add({ id: 'deathstalker_malik', n: 'Deathstalker Malik', ja: '死の追跡者マリク', f: 'CON', t: 'U', c: 6, a: 4, h: 7, r: 'H', g: ['Mercenary'], kw: { CLOAK: 1 },
    on: { devour: [{ op: 'buff', t: 'self', a: 2 }] }, tx: 'CLOAK。DEVOUR:攻撃力+2。', src: 'B', note: '体力7(6→7)はv1.3.12で確認。他は再構成' });
  add({ id: 'protected_convoys', n: 'Protected Convoys', ja: '護衛付き輸送隊', f: 'CON', t: 'U', c: 4, a: 3, h: 3, r: 'C', kw: { SCREEN: 1, SHIELD: 1 },
    tx: 'SCREEN。SHIELD', src: 'B', note: '攻撃力3(4→3)はv1.3.9で確認。他は再構成' });
  add({ id: 'sniper', n: 'Sniper', ja: '狙撃兵', f: 'CON', t: 'U', c: 3, a: 2, h: 2, r: 'C', g: ['Mercenary'], tg: { side: 'enemy', kind: 'unit', opt: true },
    on: { play: [{ op: 'dmg', t: 'T', n: 2 }] }, tx: 'ACTIVATE:敵ユニット1体に2ダメージ。', src: 'C', note: 'バランス議論で名称のみ確認(勢力推定)' });
  add({ id: 'attache', n: 'Attaché', ja: '随員', f: 'CON', t: 'U', c: 2, a: 1, h: 3, r: 'C', kw: { CREDIT: 1 },
    on: { play: [{ op: 'draw', n: 1 }] }, tx: 'CREDIT 1。ACTIVATE:カードを1枚引く。', src: 'C', note: 'バランス議論で名称のみ確認(勢力推定)' });
  add({ id: 'advisor', n: 'Advisor', ja: '顧問', f: 'CON', t: 'U', c: 4, a: 2, h: 5, r: 'P', kw: { SCREEN: 1 }, aura: { creditRed: 1 },
    tx: 'SCREEN。IMPACT:CREDIT を持つ自分のカードのコスト-1。', src: 'C', note: 'パラゴン(名称のみ確認)' });
  add({ id: 'kongs_blockade', n: "Kong's Blockade", ja: 'コングの封鎖', f: 'CON', t: 'T', c: 2, r: 'E', cy: { on: 'enemyUnitPlayed', fx: [{ op: 'bounce', t: 'T' }] },
    tx: 'CYPHER:相手がユニットをプレイした時、それを持ち主の手札に RETURN する。', src: 'C', note: 'v1.3.12バグ修正欄で名称のみ確認' });
  add({ id: 'heavy_transport', n: 'Heavy Transport', ja: '重輸送艦', f: 'CON', t: 'U', c: 6, a: 3, h: 7, r: 'P', g: ['Massive'],
    on: { play: [{ op: 'summon', id: 'merc_bodyguard', n: 1 }, { op: 'summon', id: 'merc_infiltrator', n: 1 }, { op: 'summon', id: 'merc_trader', n: 1 }] },
    tx: 'ACTIVATE:3種の傭兵(護衛・潜入員・Trader)を1体ずつ配備。', src: 'C', note: 'パラゴン(名称のみ確認・勢力推定)' });

  /* ===== テラン ===== */
  add({ id: 'sect_recruiter', n: 'Sect Recruiter', ja: '教団の勧誘者', f: 'TER', t: 'U', c: 5, a: 3, h: 5, r: 'H',
    on: { play: [{ op: 'summon', id: 'support_marine', n: 2 }] }, tx: 'ACTIVATE:サポート・マリーンを2体配備。', src: 'B', note: 'キャンペーン報酬。コスト5・ヒロイックは確認、他は再構成' });
  add({ id: 'recon_element', n: 'Recon Element', ja: '偵察要素', f: 'TER', t: 'U', c: 1, a: 1, h: 1, r: 'C', kw: { CLOAK: 1 },
    tx: 'CLOAK', src: 'B', note: '1/1クロークとして言及。コストは再構成' });
  add({ id: 'guardsman', n: 'Guardsman', ja: '衛兵', f: 'TER', t: 'U', c: 2, a: 1, h: 3, r: 'C', kw: { SCREEN: 1 },
    tx: 'SCREEN', src: 'C', note: '名称のみ確認' });
  add({ id: 'heavy_infantry', n: 'Heavy Infantry', ja: '重歩兵', f: 'TER', t: 'U', c: 3, a: 2, h: 4, r: 'C', kw: { ARMORED: 1 },
    tx: 'ARMORED', src: 'B', note: '攻撃力2(3→2)は2017/5/22で確認。他は再構成' });
  add({ id: 'zero_in', n: 'Zero In', ja: '照準固定', f: 'TER', t: 'T', c: 1, r: 'C', tg: { side: 'ally', kind: 'char' },
    on: { play: [{ op: 'buff', t: 'T', a: 2, temp: 1 }, { op: 'kw', t: 'T', k: 'CRITICAL', v: 1, temp: 1 }] }, tx: '味方1体(指揮官可)はこのターン攻撃力+2と CRITICAL を得る。', src: 'C', note: '名称のみ確認' });
  add({ id: 'emp_blast', n: 'EMP Blast', ja: 'EMPブラスト', f: 'TER', t: 'T', c: 3, r: 'E',
    on: { play: [{ op: 'disable', t: 'AE' }, { op: 'dmg', t: { s: 'AE', g: 'Cyborg' }, n: 2 }] }, tx: '全ての敵ユニットを DISABLE。敵サイボーグには2ダメージ。', src: 'C', note: '名称のみ確認' });
  add({ id: 'corvette', n: 'Corvette', ja: 'コルベット', f: 'TER', t: 'U', c: 3, a: 3, h: 3, r: 'C', kw: { SHIELD: 1 },
    tx: 'SHIELD', src: 'C', note: '名称のみ確認' });
  add({ id: 'pulse_rifles', n: 'Pulse Rifles', ja: 'パルスライフル', f: 'TER', t: 'W', c: 2, a: 2, ch: 2, r: 'C',
    tx: 'WEAPON(攻撃力2/チャージ2)', src: 'C', note: '名称のみ確認' });
  add({ id: 'paynes_rifle', n: "Payne's Rifle", ja: 'ペインのライフル', f: 'TER', t: 'W', c: 3, a: 5, ch: 1, r: 'H',
    tx: 'WEAPON(攻撃力5/チャージ1)', src: 'B', note: 'チャージ1(2→1)はv1.3.12で確認。他は再構成' });
  add({ id: 'displacer_cannon', n: 'Displacer Cannon', ja: 'ディスプレイサー砲', f: 'TER', t: 'W', c: 5, a: 4, ch: 2, r: 'E',
    wkw: { 'IGNORE ARMOR': 1 }, tx: 'WEAPON(攻撃力4/チャージ2)。装備中、指揮官は IGNORE ARMOR を得る。', src: 'C', note: 'デッキリストで名称のみ確認' });
  add({ id: 'myrmidon_squad', n: 'Myrmidon Squad', ja: 'ミュルミドン分隊', f: 'TER', t: 'U', c: 4, a: 3, h: 4, r: 'C', kw: { SHIELD: 1, SCREEN: 1 },
    tx: 'SHIELD。SCREEN', src: 'C', note: '名称のみ確認' });
  add({ id: 'eridani_patrol', n: 'Eridani Patrol', ja: 'エリダニ哨戒隊', f: 'TER', t: 'U', c: 2, a: 2, h: 1, r: 'C',
    on: { play: [{ op: 'summon', id: 'support_marine', n: 1 }] }, tx: 'ACTIVATE:サポート・マリーンを1体配備。', src: 'C', note: 'デッキリストで名称のみ確認(勢力推定)' });
  add({ id: 'eredani_guards', n: 'Eredani Guards', ja: 'エレダニ近衛', f: 'TER', t: 'U', c: 3, a: 2, h: 4, r: 'C', kw: { SCREEN: 1 },
    on: { revenge: [{ op: 'summon', id: 'support_marine', n: 1 }] }, tx: 'SCREEN。REVENGE:サポート・マリーンを1体配備。', src: 'C', note: 'デッキリストで名称のみ確認(勢力推定)' });
  add({ id: 'eredani_battalion', n: 'Eredani Battalion', ja: 'エレダニ大隊', f: 'TER', t: 'U', c: 6, a: 4, h: 6, r: 'E', kw: { ARMORED: 1 },
    on: { play: [{ op: 'buff', t: { s: 'OA', g: 'Support' }, a: 1, h: 1 }] }, tx: 'ARMORED。ACTIVATE:他の味方サポート・ユニット全体に+1/+1。', src: 'C', note: 'デッキリストで名称のみ確認(勢力推定)' });
  add({ id: 'void_probe', n: 'Void Probe', ja: '虚空探査機', f: 'TER', t: 'U', c: 1, a: 0, h: 2, r: 'C', kw: { PACIFIST: 1 },
    on: { revenge: [{ op: 'draw', n: 1 }] }, tx: 'PACIFIST。REVENGE:カードを1枚引く。', src: 'C', note: 'デッキリストで名称のみ確認' });
  add({ id: 'rapid_strike_team', n: 'Rapid Strike Team', ja: '即応打撃チーム', f: 'TER', t: 'U', c: 3, a: 3, h: 3, r: 'C', kw: { MOBILITY: 1 },
    tx: 'MOBILITY', src: 'B', note: '体力3(4→3)はv1.3.9で確認。他は再構成' });
  add({ id: 'bombardiers', n: 'Bombardiers', ja: '爆撃兵', f: 'TER', t: 'U', c: 5, a: 3, h: 4, r: 'E',
    on: { play: [{ op: 'dmg', t: 'AE', n: 1 }] }, tx: 'ACTIVATE:全ての敵ユニットに1ダメージ。', src: 'B', note: '体力4(5→4)はv1.3.9で確認。他は再構成' });
  add({ id: 'drop_troopers', n: 'Drop Troopers', ja: '降下兵', f: 'TER', t: 'U', c: 5, a: 3, h: 6, r: 'C', kw: { MOBILITY: 1 },
    tx: 'MOBILITY', src: 'B', note: '体力6(5→6)はv1.3.9で確認。他は再構成' });
  add({ id: 'assault_autovec_squad', n: 'Assault Autovec Squad', ja: '強襲オートヴェク分隊', f: 'TER', t: 'U', c: 5, a: 3, h: 4, r: 'E', kw: { ASSAULT: 1 },
    tx: 'ASSAULT', src: 'B', note: 'コスト5(4→5)はv1.3.9で確認。他は再構成' });
  add({ id: 'raptor_tank', n: 'Raptor Tank', ja: 'ラプター戦車', f: 'TER', t: 'U', c: 5, a: 4, h: 4, r: 'E', g: ['Massive'], kw: { ARMORED: 1 },
    energize: [{ n: 8, fx: [{ op: 'kw', t: 'self', k: 'SCREEN', v: 1 }], tx: 'さらに SCREEN を得る' }], tx: 'ARMORED。ENERGIZE 8:さらに SCREEN を得る。', en: 'ARMORED. ENERGIZE 8: Also gain SCREEN.', src: 'B', note: '転載断片の文面を採用(カード名との対応は未確定)' });
  add({ id: 'archeus_cruiser', n: 'Archeus Cruiser', ja: 'アーケウス巡洋艦', f: 'TER', t: 'U', c: 6, a: 5, h: 6, r: 'E', g: ['Massive'], kw: { ARMORED: 1 },
    tx: 'ARMORED', src: 'C', note: '名称のみ確認' });
  add({ id: 'terazin_destroyer', n: 'Terazin Destroyer', ja: 'テラジン駆逐艦', f: 'TER', t: 'U', c: 7, a: 6, h: 6, r: 'E', g: ['Massive'], tg: { side: 'enemy', kind: 'unit', opt: true },
    on: { play: [{ op: 'dmg', t: 'T', n: 3 }] }, tx: 'ACTIVATE:敵ユニット1体に3ダメージ。', src: 'C', note: '名称のみ確認' });
  add({ id: 'titan', n: 'Titan', ja: 'タイタン', f: 'TER', t: 'U', c: 9, a: 8, h: 8, r: 'H', g: ['Massive'], kw: { ARMORED: 1 },
    tx: 'ARMORED', src: 'C', note: 'アニメーションカード告知で名称のみ確認(勢力推定)' });
  add({ id: 'fleet_beacon', n: 'Fleet Beacon', ja: '艦隊標識', f: 'TER', t: 'U', c: 3, a: 0, h: 4, r: 'E', kw: { PACIFIST: 1 },
    on: { startTurn: [{ op: 'summon', id: 'support_marine', n: 1 }] }, tx: 'PACIFIST。自ターン開始時:サポート・マリーンを1体配備。', src: 'C', note: 'アニメーションカード告知で名称のみ確認(勢力推定)' });
  add({ id: 'rally', n: 'Rally', ja: '結集', f: 'TER', t: 'T', c: 3, r: 'C',
    on: { play: [{ op: 'buff', t: 'AA', a: 1, h: 1 }] }, tx: '味方ユニット全体に+1/+1。', src: 'C', note: '名称のみ確認' });
  add({ id: 'ion_cannon', n: 'Ion Cannon', ja: 'イオン砲', f: 'TER', t: 'T', c: 6, r: 'P', tg: { side: 'enemy', kind: 'char' },
    on: { play: [{ op: 'dmg', t: 'T', n: 6 }] }, tx: '対象に6ダメージ。', src: 'C', note: 'パラゴン(名称のみ確認)' });
  add({ id: 'asteroid_fortress', n: 'Asteroid Fortress', ja: '小惑星要塞', f: 'TER', t: 'U', c: 8, a: 3, h: 12, r: 'P', g: ['Massive'], kw: { SCREEN: 1, ARMORED: 1 },
    tx: 'SCREEN。ARMORED', src: 'C', note: 'パラゴン(名称のみ確認)' });
  add({ id: 'orbital_citadel', n: 'Orbital Citadel', ja: '軌道城塞', f: 'TER', t: 'U', c: 7, a: 4, h: 8, r: 'E', g: ['Massive'],
    on: { endTurn: [{ op: 'dmg', t: 'RE', n: 2 }] }, tx: 'ターン終了時:ランダムな敵ユニットに2ダメージ。', src: 'C', note: 'バランス議論で名称のみ確認' });
  add({ id: 'avalanche_bombard', n: 'Avalanche Bombard', ja: 'アバランチ砲撃艦', f: 'TER', t: 'U', c: 7, a: 5, h: 5, r: 'E', g: ['Massive'],
    on: { play: [{ op: 'dmg', t: 'AE', n: 1 }, { op: 'dmg', t: 'ec', n: 2 }] }, tx: 'ACTIVATE:全ての敵ユニットに1ダメージ、敵指揮官に2ダメージ。', src: 'C', note: 'バランス議論で名称のみ確認' });
  add({ id: 'fighter_squadron', n: 'Fighter Squadron', ja: '戦闘機中隊', f: 'TER', t: 'U', c: 4, a: 2, h: 3, r: 'C', kw: { ASSAULT: 1, MOBILITY: 1 },
    tx: 'ASSAULT。MOBILITY', src: 'C', note: 'バランス議論で名称のみ確認' });
  add({ id: 'arsenal_dropship', n: 'Arsenal Dropship', ja: '武器庫降下艇', f: 'TER', t: 'U', c: 6, a: 4, h: 5, r: 'E',
    on: { play: [{ op: 'equip', id: 'pulse_rifles' }] }, tx: 'ACTIVATE:パルスライフル(2/2)を装備する。', src: 'C', note: 'バランス議論で名称のみ確認' });
  add({ id: 'fenriks_partisan', n: "Fenrik's Partisan", ja: 'フェンリクの遊撃兵', f: 'TER', t: 'U', c: 2, a: 2, h: 1, r: 'C', kw: { MOBILITY: 1 },
    tx: 'MOBILITY', src: 'C', note: 'v1.3.12バグ修正欄で名称のみ確認' });

  /* ===== ヴラクシアン ===== */
  add({ id: 'pirate_outrider', n: 'Pirate Outrider', ja: '海賊斥候騎', f: 'VRX', t: 'U', c: 3, a: 4, h: 2, r: 'E', g: ['Vraxxian'],
    on: { play: [{ op: 'reveal', n: 1 }, { op: 'pillageCost' }] }, tx: 'ACTIVATE:敵カード1枚を REVEAL。PILLAGE:公開したカードのコストを、敵手札の公開済みカード枚数分増やす(10を超えない)。',
    en: 'ACTIVATE: REVEAL enemy card. PILLAGE: increase cost of the revealed card by the number of REVEALED cards in enemy hand, but not over 10.', src: 'A', note: '2016/12 プレビュー文面' });
  add({ id: 'hyper_compression', n: 'Hyper-Compression', ja: '超圧縮', f: 'VRX', t: 'T', c: 3, r: 'H',
    on: { play: [{ op: 'copyRevealed' }] }, energize: [{ n: 4, fx: [{ op: 'flag', k: 'cheap' }], tx: 'コピーのコストは1サプライ少ない', pre: true }],
    tx: '相手の手札の公開済みカードすべてのコピーを引く。ENERGIZE 4:コピーのコストは1サプライ少ない。', en: 'DRAW copies of all REVEALED cards in opponent\'s hand. ENERGIZE 4: Copies cost 1 less supply.', src: 'A', note: '2016/12/11 プレビュー文面。コストは再構成' });
  add({ id: 'youngmane', n: 'Youngmane', ja: 'ヤングメイン', f: 'VRX', t: 'U', c: 1, a: 1, h: 2, r: 'C', g: ['Vraxxian'],
    on: { play: [{ op: 'reveal', n: 1 }] }, tx: 'ACTIVATE:敵カード1枚を REVEAL。', src: 'B', note: '攻撃力1(2→1)はv1.2.2で確認。他は再構成' });
  add({ id: 'pridemistress_shagar', n: 'Pridemistress Shagar', ja: '群れの女主人シャガル', f: 'VRX', t: 'U', c: 6, a: 4, h: 5, r: 'P', g: ['Vraxxian'],
    on: { play: [{ op: 'reveal', n: 10 }, { op: 'buff', t: 'self', a: 'rev' }] }, tx: 'ACTIVATE:相手の手札をすべて REVEAL。PILLAGE:公開済みカード1枚につき攻撃力+1。', src: 'C', note: 'ヴラクシアン・パック特典のパラゴン(名称のみ確認)' });
  add({ id: 'vraxxian_gunboat', n: 'Vraxxian Gunboat', ja: 'ヴラクシアン砲艦', f: 'VRX', t: 'U', c: 6, a: 5, h: 5, r: 'E', g: ['Vraxxian', 'Massive'],
    on: { play: [{ op: 'repeat', n: 'rev', fx: [{ op: 'dmg', t: 'REA', n: 1 }] }] }, tx: 'ACTIVATE:敵手札の公開済みカード1枚につき、ランダムな敵に1ダメージ。', src: 'B', note: 'コスト6は確認。他は再構成' });
  add({ id: 'through_the_maw', n: 'Through the Maw', ja: '顎の向こうへ', f: 'VRX', t: 'T', c: 4, r: 'E', tg: { side: 'enemy', kind: 'char' },
    on: { play: [{ op: 'dmg', t: 'T', n: 3 }, { op: 'draw', n: 1 }, { op: 'draw', n: 'rev' }] }, tx: '3ダメージを与え、カードを1枚引く。相手手札の公開済みカード1枚ごとに追加で1枚引く。', src: 'B', note: '帰属不明の断片テキストを、推定名とともに採用。コストは再構成' });
  add({ id: 'vrx_fragment_storm', n: 'Unidentified Tactic (fragment)', ja: '名称不明の戦術(断片)', f: 'VRX', t: 'T', c: 4, r: 'E',
    on: { play: [{ op: 'dmg', t: 'AE', n: 'rev', calc: 1 }] }, tx: '相手手札の公開済みカード1枚ごとに、全ての敵ユニットに1ダメージ。', src: 'B', note: '帰属不明の断片テキスト。カード名は未確認' });
  add({ id: 'vrx_raider', n: 'Pride Raider (provisional)', ja: 'プライド・レイダー(仮称)', f: 'VRX', t: 'U', c: 2, a: 2, h: 3, r: 'C', g: ['Vraxxian'],
    on: { play: [{ op: 'if', c: { rev: 1 }, then: [{ op: 'buff', t: 'self', a: 1, h: 1 }] }] }, tx: 'ACTIVATE:敵手札に公開済みカードがあれば+1/+1。', src: 'D', note: '資料で確認できない補完カード(仮称)' });
  add({ id: 'vrx_plunderer', n: 'Mane Plunderer (provisional)', ja: 'メイン・プランダラー(仮称)', f: 'VRX', t: 'U', c: 4, a: 3, h: 4, r: 'C', g: ['Vraxxian'],
    on: { play: [{ op: 'reveal', n: 1 }, { op: 'if', c: { rev: 3 }, then: [{ op: 'draw', n: 1 }] }] }, tx: 'ACTIVATE:敵カード1枚を REVEAL。PILLAGE:公開済みが3枚以上ならカードを1枚引く。', src: 'D', note: '資料で確認できない補完カード(仮称)' });
  add({ id: 'vrx_hunter', n: 'Pride Hunter (provisional)', ja: 'プライド・ハンター(仮称)', f: 'VRX', t: 'U', c: 5, a: 4, h: 4, r: 'C', g: ['Vraxxian'], kw: { MOBILITY: 1 },
    on: { play: [{ op: 'reveal', n: 1 }] }, tx: 'MOBILITY。ACTIVATE:敵カード1枚を REVEAL。', src: 'D', note: '資料で確認できない補完カード(仮称)' });

  /* ===== トークン/生成カード ===== */
  add({ id: 'support_marine', n: 'Support Marine', ja: 'サポート・マリーン', f: 'TER', t: 'U', c: 1, a: 1, h: 1, r: 'C', g: ['Support'], token: true,
    tx: '(テラン指揮官能力で配備される1/1)', src: 'B', note: '「2サプライで1/1のSupport marineを配備」とのプレイヤー説明' });
  add({ id: 'merc_bodyguard', n: 'Mercenary Bodyguard', ja: '傭兵護衛', f: 'CON', t: 'U', c: 1, a: 0, h: 2, r: 'C', g: ['Mercenary'], token: true, kw: { SCREEN: 1 },
    tx: 'SCREEN', src: 'B', note: '指揮官能力の生成ユニット「0/2 SCREEN」。名称は仮称' });
  add({ id: 'merc_infiltrator', n: 'Mercenary Infiltrator', ja: '傭兵潜入員', f: 'CON', t: 'U', c: 1, a: 1, h: 1, r: 'C', g: ['Mercenary'], token: true, kw: { CLOAK: 1 },
    tx: 'CLOAK', src: 'B', note: '指揮官能力の生成ユニット「1/1ステルス」。名称は仮称' });
  add({ id: 'merc_trader', n: 'Trader', ja: 'トレーダー', f: 'CON', t: 'U', c: 1, a: 0, h: 1, r: 'C', g: ['Mercenary'], token: true, aura: { creditRed: 1 },
    tx: 'IMPACT:CREDIT を持つ自分のカードのコスト-1。', src: 'B', note: '「0/1のTrader」「CREDITカードのコストを下げる」とのプレイヤー証言' });
  add({ id: 'supply_crate', n: 'Supply Crate', ja: 'サプライ・クレート', f: 'NEU', t: 'T', c: 0, r: 'C', token: true,
    on: { play: [{ op: 'supply', n: 1 }] }, tx: 'このターン、サプライ+1。', src: 'C', note: '後攻ボーナスとして再構成(Phoenix Fighterの文面に名称が登場)' });

  // ---------- モジュール ----------
  // ct: supply(指揮官基本能力) / energy(起動型) / passive
  const M = [
    { id: 'psychic_charge', n: 'Psychic Charge', ja: 'サイキックチャージ', f: 'ANN', ct: 'supply', c: 2, base: 1,
      fx: [{ op: 'psy', n: 1 }], tx: 'サイキックチャージ+1(上限10)。チャージは指揮官へのダメージを先に肩代わりする。', src: 'B', note: '「2サプライで指揮官のサイキックパワー+1。指揮官体力の盾として働く」とのプレイヤー説明' },
    { id: 'restore', n: 'Restore', ja: '修復', f: 'HIE', ct: 'supply', c: 2, base: 1, tg: { side: 'ally', kind: 'char' },
      fx: [{ op: 'heal', t: 'T', n: 2 }], tx: '味方のユニットか指揮官1体を RESTORE 2。', src: 'B', note: 'テル=マクスの初期モジュール。「2サプライで対象を2回復」とのプレイヤー説明' },
    { id: 'release_mutagen', n: 'Release Mutagen', ja: '変異原放出', f: 'SHA', ct: 'supply', c: 2, base: 1, tg: { side: 'ally', kind: 'char', mutable: true },
      fx: [{ op: 'mutagen', t: 'T' }], tx: '味方ユニット1体を MUTATE する。指揮官を対象にした場合、指揮官は1ダメージを受け、このターン攻撃力+2。', src: 'B', note: 'プレイヤー説明より' },
    { id: 'thrash', n: 'Thrash', ja: 'スラッシュ', f: 'HAJ', ct: 'supply', c: 2, base: 1, tg: { side: 'any', kind: 'char' },
      fx: [{ op: 'dmg', t: 'T', n: 1 }], tx: '任意の対象に1ダメージ。', src: 'B', note: '「2サプライで任意の対象に1ダメージ」とのプレイヤー説明。Rend の置き換え対象として名称確認' },
    { id: 'redeem_contract', n: 'Redeem Contract', ja: '契約履行', f: 'CON', ct: 'supply', c: 2, base: 1,
      fx: [{ op: 'summonRandom', ids: ['merc_bodyguard', 'merc_infiltrator', 'merc_trader'] }], tx: 'ランダムな傭兵を配備:0/2 SCREEN、1/1 CLOAK、0/1 Trader(CREDITカードのコスト-1)のいずれか。', src: 'B', note: 'プレイヤー説明より' },
    { id: 'call_marines', n: 'Call Reinforcements', ja: '増援要請(仮称)', f: 'TER', ct: 'supply', c: 2, base: 1,
      fx: [{ op: 'summon', id: 'support_marine', n: 1 }], tx: '1/1のサポート・マリーンを配備。', src: 'B', note: '効果はプレイヤー説明で確認。モジュール名は未確認' },
    { id: 'scout_ahead', n: 'Scout Ahead', ja: '先行偵察', f: 'VRX', ct: 'supply', c: 2, base: 1,
      fx: [{ op: 'reveal', n: 1 }, { op: 'if', c: { rev: 3 }, then: [{ op: 'dmg', t: 'REA', n: 1 }] }], tx: '敵カード1枚を REVEAL。公開済みが3枚以上ならランダムな敵に1ダメージ。', src: 'C', note: 'モジュール名のみ確認。ヴラクシアンの指揮官能力とするのは推定' },
    { id: 'rend_mod', n: 'Rend', ja: '引き裂き', f: 'HAJ', ct: 'supply', c: 2, hidden: 1,
      fx: [{ op: 'dmg', t: 'RE', n: 'rend' }], tx: 'ランダムな敵ユニット1体に(2+使用回数)ダメージ。', src: 'B', note: 'v1.3.4' },

    { id: 'ethereal_enlightenment', n: 'Ethereal Enlightenment', ja: 'エーテルの啓示', f: 'ANN', ct: 'passive', hp: -10, r: 'P',
      end: [{ op: 'if', c: { psyLt: 5 }, then: [{ op: 'psy', n: 1 }] }], tx: 'ターン終了時、サイキックチャージが5未満なら1得る。初期体力-10。', src: 'A', note: 'v1.2.2' },
    { id: 'mind_anchor', n: 'Mind Anchor', ja: '精神の錨', f: 'ANN', ct: 'energy', c: 7, tg: { side: 'enemy', kind: 'unit' },
      fx: [{ op: 'disable', t: 'T' }, { op: 'psy', n: 1 }], tx: '敵ユニット1体を DISABLE し、サイキックチャージ+1。', src: 'C', note: '名称のみ確認(勢力推定)' },
    { id: 'noise_veil', n: 'Noise Veil', ja: 'ノイズヴェール', f: 'ANN', ct: 'energy', c: 6, tg: { side: 'ally', kind: 'unit' },
      fx: [{ op: 'kw', t: 'T', k: 'CLOAK', v: 1 }], tx: '味方ユニット1体に CLOAK を与える。', src: 'C', note: '名称のみ確認(勢力推定)' },
    { id: 'auto_repair', n: 'Auto-Repair Protocols', ja: '自動修復プロトコル', f: 'HIE', ct: 'passive', hp: -5,
      end: [{ op: 'if', c: { onlyGroup: 'Cyborg' }, then: [{ op: 'heal', t: 'AA', n: 2 }] }], tx: '自軍のユニットがサイボーグのみなら、ターン終了時にそれらは体力を2修復する。初期体力-5。', src: 'A', note: 'v1.2.2' },
    { id: 'nergals_gift', n: "Nergal's Gift", ja: 'ネルガルの恩寵', f: 'HIE', ct: 'energy', c: 8,
      fx: [{ op: 'heal', t: 'AA', n: 2 }, { op: 'kw', t: { s: 'AA', g: 'Cyborg' }, k: 'SHIELD', v: 1 }], tx: '味方ユニット全体を RESTORE 2。味方サイボーグは SHIELD を得る。', src: 'B', note: 'コスト8はv1.2.2で確認。効果は再構成' },
    { id: 'duplicate', n: 'Duplicate', ja: '複製', f: 'HIE', ct: 'energy', c: 9,
      fx: [{ op: 'dupHand' }], tx: '自分の手札のランダムなカード1枚のコピーを手札に加える。', src: 'C', note: '「Duplicate Hierarchy」デッキで名称確認' },
    { id: 'natural_selection', n: 'Natural Selection', ja: '自然淘汰', f: 'SHA', ct: 'passive', hp: -5,
      end: [{ op: 'if', c: { groupCount: ['Aberration', 3] }, then: [{ op: 'mutate', t: { s: 'RA', mut: 1 } }] }], tx: 'アベレーションを3体以上コントロールしていれば、ターン終了時に MUTATE 能力を持つ1体がランダムで変異する。初期体力-5。', src: 'A', note: 'v1.2.2' },
    { id: 'plague_nexus', n: 'Plague Nexus', ja: '疫病の結節', f: 'SHA', ct: 'energy', c: 9,
      fx: [{ op: 'addHand', id: 'geneshaper_apprentice', n: 1 }], tx: '「ジーンシェイパー見習い」を1枚手札に加える。', src: 'A', note: 'v1.2.2(6→9)' },
    { id: 'infect', n: 'Infect', ja: '感染', f: 'SHA', ct: 'energy', c: 9, tg: { side: 'enemy', kind: 'unit' },
      fx: [{ op: 'kw', t: 'T', k: 'VULNERABILITY', v: 1 }, { op: 'dmg', t: 'T', n: 2 }], tx: '敵ユニット1体に VULNERABILITY 1 を与え、2ダメージ。', src: 'B', note: 'コスト9はv1.2.2で確認。効果は再構成' },
    { id: 'viromorphic_spores', n: 'Viromorphic Spores', ja: 'ウイルス形態胞子', f: 'SHA', ct: 'energy', c: 14,
      fx: [{ op: 'mutate', t: 'AA' }], tx: '味方ユニット全体を MUTATE する。', src: 'B', note: 'コスト14は2017/5/22で確認。効果は再構成' },
    { id: 'warlords_call', n: "Warlord's Call", ja: '軍閥の号令', f: 'HAJ', ct: 'energy', c: 8,
      fx: [{ op: 'buff', t: 'AA', a: 1, h: 1 }], tx: '味方ユニット全体に+1/+1。', src: 'C', note: 'デッキリストで名称のみ確認' },
    { id: 'pain_projection', n: 'Pain Projection', ja: '苦痛投射', f: 'HAJ', ct: 'energy', c: 6,
      fx: [{ op: 'dmg', t: 'ec', n: 'damagedAllies' }], tx: 'ダメージを受けている味方ユニット1体につき、敵指揮官に1ダメージ。', src: 'C', note: 'デッキリストで名称のみ確認' },
    { id: 'arsenal', n: 'Arsenal', ja: '武器庫', f: 'HAJ', ct: 'energy', c: 8,
      fx: [{ op: 'equip', id: 'hellfire_cannon' }], tx: 'ヘルファイア砲(3/3)を装備する。', src: 'B', note: 'コスト8(6→8)は2017/5/22で確認。効果は再構成' },
    { id: 'hit_and_run', n: 'Hit and Run Tactics', ja: '一撃離脱戦術', f: 'CON', ct: 'energy', c: 7, tg: { side: 'ally', kind: 'unit' },
      fx: [{ op: 'kw', t: 'T', k: 'MOBILITY', v: 1 }, { op: 'kw', t: 'T', k: 'CLOAK', v: 1 }, { op: 'refresh', t: 'T' }], tx: '味方ユニット1体は CLOAK を得て、このターンもう一度攻撃できる。', src: 'C', note: '傭兵ラッシュ用として名称のみ確認' },
    { id: 'smash_grab', n: 'Smash&Grab', ja: '強奪', f: 'CON', ct: 'energy', c: 8,
      fx: [{ op: 'copyEnemyHand', n: 1 }, { op: 'dmg', t: 'ec', n: 1 }], tx: '相手の手札のランダムなカードのコピーを得て、敵指揮官に1ダメージ。', src: 'C', note: '名称のみ確認' },
    { id: 'mad_minute', n: 'Mad Minute', ja: 'マッドミニット', f: 'TER', ct: 'energy', c: 11, tg: { side: 'ally', kind: 'unit', maxAtk: 5 },
      fx: [{ op: 'refresh', t: 'T' }], tx: '攻撃力5以下のユニット1体を選ぶ。それはもう1回攻撃できる。', src: 'A', note: '2017/5/22(14→11)' },
    { id: 'veterancy', n: 'Veterancy', ja: '歴戦', f: 'TER', ct: 'passive', hp: -5, r: 'P',
      end: [{ op: 'buff', t: 'RA', a: 1, h: 1 }], tx: 'ターン終了時、ランダムな味方ユニット1体に+1/+1。初期体力-5。', src: 'C', note: 'パラゴン。体力ペナルティありとのみ確認' },
    { id: 'overclock_servos', n: 'Overclock Targeting Servos', ja: '照準サーボ過負荷', f: 'ANY', ct: 'energy', c: 6, r: 'P',
      fx: [{ op: 'dmg', t: 'ac', n: 3, calc: 1 }, { op: 'tacticDiscount', n: 2 }], tx: '自分の指揮官は3ダメージを受ける。次にプレイするタクティクスのコスト-2サプライ。', src: 'A', note: 'v1.2.2(8→6)' },
    { id: 'captains_pride', n: "Captain's Pride", ja: '船長の誇り', f: 'ANY', ct: 'passive',
      start: [{ op: 'captainsPride' }], tx: 'ターン開始時、SCREEN を持つ味方ユニットがおらず、指揮官の体力が相手より多ければ指揮官は SCREEN を得る。ダメージを受けると失う。', src: 'A', note: 'v1.2.2' },
    { id: 'shimmer', n: 'Shimmer', ja: '揺らめき', f: 'ANY', ct: 'passive', hp: 15, cmdKw: { VULNERABILITY: 1 },
      tx: '初期体力+15。指揮官は VULNERABILITY 1 を得る。', src: 'A', note: 'v1.3.12' },
    { id: 'hedronic_capacitor', n: 'Hedronic Capacitor', ja: 'ヘドロン蓄電器', f: 'ANY', ct: 'passive', cmdKw: { VULNERABILITY: 1 },
      start: [{ op: 'if', c: { energy: 2 }, then: [{ op: 'energy', n: -2 }, { op: 'kw', t: 'ac', k: 'SHIELD', v: 1 }] }], tx: 'ターン開始時にエネルギー2を消費し、指揮官は SHIELD を得る。指揮官は VULNERABILITY 1。', src: 'A', note: 'v1.3.12' },
    { id: 'bone_spurs', n: 'Bone Spurs', ja: '骨棘', f: 'ANY', ct: 'passive',
      start: [{ op: 'if', c: { energy: 2 }, then: [{ op: 'energy', n: -2 }, { op: 'boneSpurs' }] }], tx: 'ターン開始時にエネルギー2を消費し、指揮官は次の自ターンまで攻撃力+1と VULNERABILITY 1 を得る。', src: 'A', note: 'v1.3.12' },
    { id: 'war_lust', n: 'War Lust', ja: '戦争欲', f: 'ANY', ct: 'energy', c: 10, tg: { side: 'ally', kind: 'unit' },
      fx: [{ op: 'grant', t: 'T', trig: 'fury', temp: 1, fx: [{ op: 'refresh', t: 'self' }] }], tx: '味方ユニット1体はこのターン「FURY:ASSAULT(もう一度攻撃できる)」を得る。', src: 'A', note: 'v1.3.12(7→10)' },
    { id: 'efficiency', n: 'Efficiency', ja: '効率化', f: 'ANY', ct: 'energy', c: 8,
      fx: [{ op: 'draw', n: 1 }, { op: 'supply', n: 1 }], tx: 'カードを1枚引き、このターンのサプライ+1。', src: 'B', note: 'コスト8(7→8)は2017/5/22で確認。効果は再構成' },
    { id: 'compression_algorithm', n: 'Compression Algorithm', ja: '圧縮アルゴリズム', f: 'ANY', ct: 'energy', c: 10,
      fx: [{ op: 'nextDiscount', n: 3 }], tx: '次にプレイするカードのコスト-3サプライ。', src: 'B', note: 'コスト10(8→10)は2017/5/22で確認。効果は再構成' },
    { id: 'consult_general_staff', n: 'Consult General Staff', ja: '参謀本部への諮問', f: 'ANY', ct: 'energy', c: 6,
      fx: [{ op: 'draw', n: 1, filter: { t: 'T' } }], tx: '山札からタクティクスを1枚引く。', src: 'B', note: '効果の大意のみ確認。コストは再構成' },
    { id: 'cb_pods', n: 'CB Pods', ja: 'CBポッド', f: 'ANY', ct: 'energy', c: 5,
      fx: [{ op: 'supply', n: 2 }], tx: 'このターンのサプライ+2。', src: 'B', note: '「エネルギーからリソースを生成」とのみ確認' }
  ];

  // カード属性(読みやすさのため)
  const RAR = { C: 'コンスクリプト', E: 'エリート', H: 'ヒロイック', P: 'パラゴン' };
  const TYPES = { U: 'ユニット', T: 'タクティクス', W: 'ウェポン' };
  const SRC = {
    A: ['検証済み', '公式告知・パッチノート・開発者投稿で文面と数値を確認'],
    B: ['一部確認', '名称と一部の数値/文面を確認。残りは再構成'],
    C: ['名称のみ', '名称と文脈のみ確認。数値・効果は遊べるように再構成'],
    D: ['補完', '資料で確認できない仮称カード。デッキ成立のため追加']
  };

  window.SC_DATA = { factions: F, groups: GROUPS, keywords: KW, cards: C, modules: M, rarity: RAR, types: TYPES, src: SRC };
})();
