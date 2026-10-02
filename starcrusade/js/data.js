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
      blurb: 'サイボーグ化した冷徹な秩序の勢力。強力な修復技術で防御を固める。指揮官能力 Nanite Conversion(修復2)、サイボーグ統一デッキ向けのモジュール、SHIELD・ARMORED・CYPHER を持つ。' },
    SHA: { ja: 'シャンティ', en: "Shan'Ti", color: '#4fbf62', glyph: '❦',
      commander: 'ダル・ゲハリス (Dar Geharis)',
      blurb: '遺伝子を生ける兵器に作り変える種族。指揮官能力 Release Mutagen でユニットの MUTATE テキストを任意に発動できる。アベレーション(異形)を中心に、育つユニットで盤面を制圧する。' },
    HAJ: { ja: 'ハジル=ゴグ', en: 'Hajir-Gog', color: '#d9533f', glyph: '✠',
      commander: 'ハジル=ゴグ軍閥長(名称未確認)',
      blurb: '数で押し寄せる残忍で適応力の高い種族。指揮官能力 Thrash は任意の対象に1ダメージ。FURY(被ダメージ時誘発)・SWARM・ウェポン・全体強化で押し切る。' },
    CON: { ja: 'コンソーシアム', en: 'Consortium', color: '#d9a93f', glyph: '¤',
      commander: 'コンソーシアム総帥(名称未確認)',
      blurb: '陰謀と傭兵軍団の勢力。指揮官能力 Redeem Contract でランダムな傭兵(Bodyguard 0/2 SCREEN/Contractor 1/1 CLOAK/Dealer 0/1)を雇う。CREDIT(前借り)で早いターンに強いカードを出し、CLOAK で奇襲する。' },
    TER: { ja: 'テラン', en: 'Terran', color: '#7a8ca6', glyph: '✦',
      commander: 'テラン提督(名称未確認)',
      blurb: '恐れを知らない歴戦の人類。巨大兵器(マッシブ)を擁する。指揮官能力 Rally で1/1のガーズマンを配備し、ARMORED・SCREEN を持つ重装ユニットとウェポンで戦線を押し上げる。' },
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
    ENERGY: ['エネルギー', '第2リソース。攻撃・敵ユニット撃破・敵指揮官へのダメージ・空きモジュールスロットで獲得し、モジュールや ENERGIZE に使う。', 'A'],
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
  add({ id: 'fleshborer', n: 'Fleshborer', ja: '肉穿ち', f: 'SHA', t: 'U', c: 3, a: 3, h: 3, r: 'C', g: ['Aberration'],
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
  add({ id: 'oppressor', n: 'Oppressor', ja: '圧制者', f: 'HAJ', t: 'U', c: 4, a: 4, h: 5, r: 'E', kw: { ZEAL: 1 },
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
  add({ id: 'rage_dok', n: 'Rage Dok', ja: 'レイジ・ドク', f: 'HAJ', t: 'U', c: 3, a: 3, h: 4, r: 'E', g: ['Support'],
    on: { play: [{ op: 'grant', t: 'OA', trig: 'fury', fx: [{ op: 'buff', t: 'self', a: 1 }] }] }, tx: 'ACTIVATE:他の味方ユニット全体は「FURY:攻撃力+1」を得る。', src: 'C', note: '名称のみ確認' });
  add({ id: 'hellfire_cannon', n: 'Hellfire Cannon', ja: 'ヘルファイア砲', f: 'HAJ', t: 'W', c: 3, a: 3, ch: 3, r: 'E',
    tx: 'WEAPON(攻撃力3/チャージ3)', src: 'C', note: '主力ウェポンとして名称のみ確認' });
  add({ id: 'war_banner', n: 'War Banner', ja: '軍旗', f: 'HAJ', t: 'T', c: 2, r: 'C',
    on: { play: [{ op: 'kw', t: 'AA', k: 'SWARM', v: 1, temp: 1 }] }, tx: '味方ユニット全体はこのターン SWARM を得る。', src: 'B', note: 'コスト2(3→2)はv1.2.2で確認。他は再構成' });
  add({ id: 'mad_volley', n: 'Mad Volley', ja: '狂乱の斉射', f: 'HAJ', t: 'T', c: 2, r: 'C',
    on: { play: [{ op: 'dmg', t: 'REA', n: 1 }, { op: 'dmg', t: 'REA', n: 1 }, { op: 'dmg', t: 'REA', n: 1 }] }, tx: 'ランダムな敵に1ダメージを3回与える。', src: 'B', note: 'コスト2(3→2)はv1.2.7で確認。他は再構成' });
  add({ id: 'land_crawler', n: 'Land Crawler', ja: 'ランドクローラー', f: 'HAJ', t: 'U', c: 7, a: 2, h: 8, r: 'P', g: ['Massive'], kw: { SWARM: 1, SCREEN: 1 },
    tx: 'SWARM。SCREEN', src: 'C', note: 'パラゴン(名称のみ確認)' });
  add({ id: 'spider_walker', n: 'Spider Walker', ja: 'スパイダーウォーカー', f: 'HAJ', t: 'U', c: 3, a: 3, h: 4, r: 'C',
    on: { fury: [{ op: 'dmg', t: 'RE', n: 1 }] }, tx: 'FURY:ランダムな敵ユニットに1ダメージ。', src: 'C', note: 'バランス議論で名称のみ確認(勢力推定)' });

  /* ===== コンソーシアム ===== */
  add({ id: 'despaired_debtor', n: 'Despaired Debtor', ja: '絶望した債務者', f: 'CON', t: 'U', c: 1, a: 2, h: 2, r: 'H', g: ['Mercenary'], kw: { CREDIT: 1 },
    tx: 'CREDIT 1', src: 'B', note: 'キャンペーン「ネルガル教団」報酬。コスト1・ヒロイックは確認、他は再構成' });
  add({ id: 'arms_merchant', n: 'Arms Merchant', ja: '武器商人', f: 'CON', t: 'U', c: 3, a: 2, h: 3, r: 'C', g: ['Mercenary'], kw: { CREDIT: 1 },
    on: { play: [{ op: 'equip', id: 'blaster' }] }, tx: 'CREDIT 1。ACTIVATE:ブラスター(2/2)を装備する。', src: 'C', note: '傭兵デッキで名称のみ確認' });
  add({ id: 'field_commander', n: 'Field Commander', ja: '野戦指揮官', f: 'CON', t: 'U', c: 4, a: 3, h: 4, r: 'E',
    aura: { a: 1, g: 'Mercenary' }, tx: 'IMPACT:他の味方マーセナリーの攻撃力+1。', src: 'C', note: '傭兵デッキで名称のみ確認' });
  add({ id: 'veteran_advisor', n: 'Veteran Advisor', ja: '古参顧問', f: 'CON', t: 'U', c: 3, a: 2, h: 3, r: 'E', kw: { CREDIT: 2 },
    on: { play: [{ op: 'draw', n: 2 }] }, tx: 'CREDIT 2。ACTIVATE:カードを2枚引く。', src: 'C', note: '傭兵デッキで名称のみ確認' });
  add({ id: 'double_retainer', n: 'Double Retainer', ja: '二重雇用', f: 'CON', t: 'T', c: 3, r: 'C',
    on: { play: [{ op: 'summon', id: 'merc_bodyguard', n: 1 }, { op: 'summon', id: 'merc_infiltrator', n: 1 }] }, tx: 'Bodyguard(0/2 SCREEN)と Contractor(1/1 CLOAK)を配備する。', src: 'C', note: '傭兵デッキで名称のみ確認' });
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
    on: { play: [{ op: 'summon', id: 'support_marine', n: 2 }] }, tx: 'ACTIVATE:ガーズマンを2体配備。', src: 'B', note: 'キャンペーン報酬。コスト5・ヒロイックは確認、他は再構成' });
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
    on: { play: [{ op: 'summon', id: 'support_marine', n: 1 }] }, tx: 'ACTIVATE:ガーズマンを1体配備。', src: 'C', note: 'デッキリストで名称のみ確認(勢力推定)' });
  add({ id: 'eredani_guards', n: 'Eredani Guards', ja: 'エレダニ近衛', f: 'TER', t: 'U', c: 3, a: 2, h: 4, r: 'C', kw: { SCREEN: 1 },
    on: { revenge: [{ op: 'summon', id: 'support_marine', n: 1 }] }, tx: 'SCREEN。REVENGE:ガーズマンを1体配備。', src: 'C', note: 'デッキリストで名称のみ確認(勢力推定)' });
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
    on: { startTurn: [{ op: 'summon', id: 'support_marine', n: 1 }] }, tx: 'PACIFIST。自ターン開始時:ガーズマンを1体配備。', src: 'C', note: 'アニメーションカード告知で名称のみ確認(勢力推定)' });
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
  add({ id: 'support_marine', n: 'Support Marine', ja: 'ガーズマン', f: 'TER', t: 'U', c: 1, a: 1, h: 1, r: 'C', g: ['Support'], token: true,
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
      fx: [{ op: 'summon', id: 'support_marine', n: 1 }], tx: '1/1のガーズマンを配備。', src: 'B', note: '効果はプレイヤー説明で確認。モジュール名は未確認' },
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


  // ===================================================================
  // v2 修正(2026-10-02 YouTube 調査:デッキリスト34本+動画字幕13本)
  // 詳細と根拠は starcrusade/YOUTUBE_RESEARCH.md。
  //   - デッキリストで他勢力のデッキに入っていたカードは勢力を修正
  //   - 字幕で効果が判明したカードは効果を差し替え(src B、note に出典)
  //   - 誤りと分かったカードは retired(図鑑・デッキ構築から除外。古いセーブ互換のため残す)
  // ===================================================================
  const byId = {}; C.forEach(c => { byId[c.id] = c; });
  const YT = '動画字幕(自動生成・確度中)';
  const fix = (id, o, note) => { const c = byId[id] || C.find(x => x.id === id); if (!c) throw new Error('no card ' + id); Object.assign(c, o); if (note) c.note = (c.note ? c.note + ' / ' : '') + note; };
  const DECK = 'YouTube デッキリストで他勢力のデッキに登場';
  // --- 勢力の修正(他勢力のデッキに入っていた=その勢力のカードではない) ---
  [['automated_defences', 'NEU'], ['fighter_squadron', 'NEU'], ['field_commander', 'NEU'], ['eridani_patrol', 'NEU'], ['arsenal_dropship', 'NEU'],
    ['tower_of_eyes', 'NEU'], ['arms_merchant', 'NEU'], ['heavy_transport', 'NEU'], ['corvette', 'NEU'], ['terazin_destroyer', 'NEU'], ['land_crawler', 'NEU'],
    ['carbonic_protector', 'NEU'], ['gatekeeper', 'CON'], ['titan', 'NEU'], ['soul_devourer', 'NEU'], ['replicant', 'NEU'], ['mr_bradford', 'NEU'],
    ['cytek_drone', 'NEU'], ['fleet_beacon', 'NEU'], ['preacher', 'NEU'], ['advisor', 'HIE'], ['horror_of_the_shade', 'NEU'], ['archon_carrier', 'NEU'],
    ['ravager', 'NEU'], ['fleet_core', 'NEU'], ['deathstalker_malik', 'HIE'], ['void_probe', 'NEU'], ['eredani_guards', 'CON'], ['eredani_battalion', 'CON'],
    ['portal_master', 'CON'], ['regulator', 'NEU'], ['vraxxian_gunboat', 'NEU'], ['adrenal_transformation', 'SHA'], ['bombardiers', 'NEU'], ['rippers', 'NEU'],
    ['rapid_strike_team', 'NEU'], ['assault_autovec_squad', 'NEU'], ['attache', 'VRX'], ['mad_seer', 'NEU'], ['fenriks_partisan', 'HIE'], ['myrmidon_squad', 'HIE'],
    ['displacer_cannon', 'NEU']].forEach(([id, f]) => fix(id, { f }, DECK + '→' + (f === 'NEU' ? '中立' : F[f].ja) + 'に修正'));

  // --- 名称の修正(デッキリスト・字幕の表記に合わせる) ---
  fix('psychic_overload', { n: 'Psionic Overload', ja: 'サイオニック・オーバーロード' }, '正式名はデッキリストの Psionic Overload');
  fix('the_manovar', { n: 'The Manowar', ja: 'マノウォー' }, '正式名はデッキリストの The Manowar');
  fix('zero_in', { n: 'Zeroed In', ja: '照準固定' }, '正式名はデッキリストの Zeroed In');
  fix('duskwind_guerilla', { n: 'Duskwind Guerrillas', ja: 'ダスクウィンド・ゲリラ' });
  fix('automated_defences', { n: 'Automated Defenses' });
  fix('eredani_guards', { n: 'Eridani Guards', ja: 'エリダニ近衛' });
  fix('eredani_battalion', { n: 'Eridani Battalion', ja: 'エリダニ大隊' });
  fix('support_marine', { n: 'Guardsman', ja: 'ガーズマン', src: 'A', tx: '(テランの指揮官能力 Rally で配備される1/1のサポート)', note: '複数の動画で「Rally で 1/1 の Guardsman を配備」と確認' });
  fix('merc_bodyguard', { n: 'Bodyguard', ja: 'ボディガード', src: 'A', note: 'Redeem Contract の生成ユニット 0/2 SCREEN(動画2本で確認)' });
  fix('merc_infiltrator', { n: 'Contractor', ja: 'コントラクター', src: 'A', note: 'Redeem Contract の生成ユニット 1/1 CLOAK(動画2本で確認)' });
  fix('merc_trader', { n: 'Dealer', ja: 'ディーラー', src: 'B', tx: 'IMPACT:CREDIT を持つ自分のカードのコスト-1。', note: 'Redeem Contract の生成ユニット 0/1。「契約(CREDIT)カードのコスト-1」(動画)' });
  fix('supply_crate', { n: 'Initiative', ja: 'イニシアチブ', src: 'A', note: '後攻が得るカード。「そのターンのサプライ+1」(複数の動画で確認)' });
  fix('double_retainer', { tx: '傭兵2体(Bodyguard と Contractor)を配備する。' });
  fix('heavy_transport', { tx: 'ACTIVATE:3種の傭兵(Bodyguard・Contractor・Dealer)を1体ずつ配備。' });

  // --- 誤りと分かったカード(図鑑とデッキ構築から除外) ---
  fix('guardsman', { retired: true }, '実物の Guardsman は Rally で配備される 1/1 トークンと判明したため除外');
  fix('rally', { retired: true }, 'Rally はタクティクスではなくテランの指揮官モジュールと判明したため除外');

  // --- 字幕で効果が判明したカード(効果を差し替え) ---
  fix('paranoia', { c: 4, tg: { side: 'enemy', kind: 'unit', maxHp: 3 }, on: { play: [{ op: 'control', t: 'T' }] }, tx: '体力3以下の敵ユニット1体のコントロールを得る。', src: 'B' }, YT + ':コスト4、体力3以下を奪う');
  fix('infected_militia', { c: 1, a: 1, h: 2, on: { mutate: [{ op: 'summon', id: 'brood_egg', n: 2 }, { op: 'destroy', t: 'self' }] }, tx: 'MUTATE:このユニットを破壊し、0/3のブルードエッグを2体配備。', src: 'B' }, YT + ':1コスト、MUTATE で破壊+0/3 Brood Egg×2');
  fix('bloodsworn_berserker', { n: 'Bloodsworn Berserkers', on: { allyDamaged: [{ op: 'dmg', t: 'RE', n: 1, tag: 'berserk' }] }, tx: '味方ユニットがダメージを受けるたびに、ランダムな敵ユニットに1ダメージ。', src: 'B' }, YT);
  fix('avalanche_bombard', { c: 8, a: 6, h: 6, on: { play: [{ op: 'summon', id: 'technician', n: 1 }] }, tx: 'ACTIVATE:3/3のテクニシャンを配備。', src: 'B' }, YT + ':8コスト 6/6');
  fix('void_probe', { c: 2, a: 1, h: 2, kw: {}, tg: { side: 'any', kind: 'unit', opt: true }, on: { play: [{ op: 'nullify', t: 'T' }] }, tx: 'ACTIVATE:ユニット1体を NULLIFY する。', src: 'B' }, YT + '(コスト・数値は再構成)');
  fix('double_retainer', { on: { play: [{ op: 'buff', t: { s: 'AA', g: 'Mercenary' }, a: 2 }] }, tx: '味方マーセナリー全体の攻撃力+2。', src: 'B' }, YT);
  fix('veteran_advisor', { kw: {}, on: { play: [{ op: 'buff', t: { s: 'OA', g: 'Mercenary' }, a: 1, h: 1 }] }, tx: 'ACTIVATE:他の味方マーセナリー全体に+1/+1。', src: 'B' }, YT);
  fix('interphasic_weaponry', { on: { play: [{ op: 'atkFromHp', t: 'T' }] }, tx: '味方ユニット1体は、体力と同じ値だけ攻撃力を得る。', src: 'B' }, YT + ':コスト2');
  fix('rampage', { tg: null, on: { play: [{ op: 'cmdAttack', n: 1 }] }, energize: [{ n: 3, fx: [{ op: 'buff', t: 'ac', a: 1 }], tx: '指揮官の攻撃力+1(このターン)' }], tx: '自分の指揮官はこのターン ASSAULT を得る(もう1回攻撃できる)。ENERGIZE 3:指揮官の攻撃力+1。', src: 'B' }, YT + '(ENERGIZE の値は再構成)');
  fix('refurbish_weapon', { on: { play: [{ op: 'weaponUp', a: 2, ch: 1 }] }, tx: '装備中のウェポンは攻撃力+2、チャージ+1。', src: 'B' }, YT);
  fix('gargoyle_bomber', { on: { play: [{ op: 'dmg', t: 'REA', n: 2 }] }, tx: 'ACTIVATE:ランダムな敵に2ダメージ。', src: 'B' }, YT);
  fix('mystic_apprentice', { on: { endTurn: [{ op: 'dmg', t: 'REA', n: 1 }] }, tx: 'ターン終了時:ランダムな敵に1ダメージ。', src: 'B' }, YT);
  fix('minerva_spores', { c: 1, tg: { side: 'ally', kind: 'unit', mutable: true }, on: { play: [{ op: 'mutate', t: 'T' }, { op: 'draw', n: 1 }] }, tx: '味方ユニット1体を MUTATE し、カードを1枚引く。', src: 'B' }, YT + ':コスト1');
  fix('hellfire_cannon', { a: 3, ch: 2, tx: 'WEAPON(攻撃力3/チャージ2)', src: 'B' }, YT + ':3/2のウェポン(「倒すたびに強化」は未実装)');
  fix('sniper', { c: 2, a: 1, h: 1, tg: { side: 'enemy', kind: 'char', opt: true }, on: { play: [{ op: 'dmg', t: 'T', n: 1 }] }, energize: [{ n: 4, fx: [{ op: 'bounce', t: 'self' }], tx: 'このユニットを手札に戻す' }], tx: 'ACTIVATE:1ダメージ。ENERGIZE 4:このユニットを手札に戻す。', src: 'B' }, YT + ':コスト2');
  fix('raptor_tank', { src: 'B' }, '字幕でも ARMORED を確認');
  fix('rippers', { src: 'B' }, '字幕でも「ターン終了時に攻撃力+1」を確認');

  // --- 字幕で効果が判明した新カード(名称はデッキリストで確認) ---
  const N = (o, note) => { o.src = o.src || 'B'; o.note = note || YT; add(o); };
  N({ id: 'franchise', n: 'Franchise', ja: 'フランチャイズ', f: 'CON', t: 'T', c: 2, r: 'E', on: { play: [{ op: 'maxSupply', n: 1 }] }, tx: '空のサプライ・クレートを1つ得る(以後ずっと最大サプライ+1)。' }, YT + '(コストは再構成)');
  N({ id: 'contract_hit', n: 'Contract Hit', ja: '契約殺人', f: 'CON', t: 'T', c: 2, r: 'C', kw: { CREDIT: 1 }, tg: { side: 'enemy', kind: 'unit' },
    on: { play: [{ op: 'dmg', t: 'T', n: 2 }, { op: 'if', c: { tDead: 1 }, then: [{ op: 'creditPay', n: 1 }] }] }, tx: 'CREDIT 1。敵ユニット1体に2ダメージ。それを破壊したら CREDIT を1解消する。' }, YT + '(コストは再構成)');
  N({ id: 'red_tape', n: 'Red Tape', ja: 'レッドテープ', f: 'CON', t: 'T', c: 2, r: 'E', cy: { on: 'enemyUnitPlayed', fx: [{ op: 'tuck', t: 'T' }] }, tx: 'CYPHER:相手がユニットを配備した時、それを持ち主の山札に戻す。' }, YT + '(コストは再構成)');
  N({ id: 'neutralize', n: 'Neutralize', ja: '無力化工作', f: 'CON', t: 'T', c: 4, r: 'E', tg: { side: 'enemy', kind: 'unit' },
    on: { play: [{ op: 'if', c: { hasGroup: 'Mercenary' }, then: [{ op: 'destroy', t: 'T' }] }] }, tx: '味方マーセナリーがいれば、敵ユニット1体を破壊する。' }, YT + '(コストは再構成)');
  N({ id: 'abaku_scavenger', n: 'Abaku Scavenger', ja: 'アバク・スカベンジャー', f: 'CON', t: 'U', c: 2, a: 2, h: 2, r: 'C', g: ['Mercenary'], on: { attack: [{ op: 'stealEnergy', n: 1 }] }, tx: '攻撃時:相手のエネルギーを1奪う。' }, YT + ':コンスクリプト(数値は再構成)');
  N({ id: 'syndicate_agent', n: 'Syndicate Agent', ja: 'シンジケート工作員', f: 'CON', t: 'U', c: 4, a: 2, h: 3, r: 'E', g: ['Mercenary'], on: { creditPlayed: [{ op: 'dmg', t: 'ec', n: 2 }] }, tx: 'CREDIT を持つカードをプレイするたびに、敵指揮官に2ダメージ。' }, YT + '(数値は再構成)');
  N({ id: 'syndicate_security', n: 'Syndicate Security', ja: 'シンジケート警備員', f: 'CON', t: 'U', c: 1, a: 1, h: 2, r: 'C', g: ['Mercenary'], on: { play: [{ op: 'if', c: { hasGroup: 'Mercenary' }, then: [{ op: 'buff', t: 'self', a: 1 }] }] }, tx: 'ACTIVATE:他の味方マーセナリーがいれば攻撃力+1。' }, YT + ':コスト1(数値は再構成)');
  N({ id: 'psychic_rot', n: 'Psychic Rot', ja: 'サイキック・ロット', f: 'ANN', t: 'T', c: 1, r: 'E', tg: { side: 'enemy', kind: 'unit', maxAtk: 'psy' }, on: { play: [{ op: 'destroy', t: 'T' }] }, tx: '攻撃力がサイキックチャージ以下の敵ユニット1体を破壊する。' }, YT + ':コスト1');
  N({ id: 'dominate', n: 'Dominate', ja: '支配', f: 'ANN', t: 'T', c: 10, r: 'H', psyDiscount: 1, tg: { side: 'enemy', kind: 'unit' }, on: { play: [{ op: 'control', t: 'T' }] }, tx: '敵ユニット1体のコントロールを得る。サイキックチャージ1につきコスト-1。' }, YT + '(基本コスト10は「10以上」との発言から推定)');
  N({ id: 'emanation', n: 'Emanation', ja: '放射', f: 'ANN', t: 'T', c: 2, r: 'C', cy: { on: 'enemyUnitPlayed', fx: [{ op: 'kw', t: 'T', k: 'PACIFIST', v: 1 }] }, tx: 'CYPHER:相手がユニットを配備した時、それを PACIFY(攻撃不能)にする。' }, YT + '(コストは再構成)');
  N({ id: 'mindwipe', n: 'Mindwipe', ja: 'マインドワイプ', f: 'ANN', t: 'T', c: 2, r: 'E', tg: { side: 'enemy', kind: 'unit' }, on: { play: [{ op: 'nullify', t: 'T' }, { op: 'dmg', t: 'T', n: 'psy', calc: 1 }] }, tx: 'ユニット1体を NULLIFY し、サイキックチャージと同じ値のダメージを与える。' }, YT + '(コストは再構成)');
  N({ id: 'marduks_faithful', n: "Marduk's Faithful", ja: 'マルドゥクの信徒', f: 'ANN', t: 'U', c: 2, a: 2, h: 3, r: 'C', on: { endTurn: [{ op: 'psy', n: 1 }] }, tx: 'ターン終了時:サイキックチャージ+1。' }, YT + '(数値は再構成)');
  N({ id: 'harbinger_of_doom', n: 'Harbinger of Doom', ja: '破滅の先触れ', f: 'ANN', t: 'U', c: 4, a: 3, h: 5, r: 'H', on: { psyGain: [{ op: 'dmg', t: 'REA', n: 1 }] }, tx: 'サイキックチャージを得るたびに、ランダムな敵に1ダメージ。' }, YT + '(数値は再構成)');
  N({ id: 'council_patrol', n: 'Council Patrol', ja: 'カウンシル哨戒隊', f: 'ANN', t: 'U', c: 3, a: 3, h: 4, r: 'E', g: ['Council'], on: { play: [{ op: 'nullify', t: 'ROA' }, { op: 'nullify', t: 'RE' }] }, tx: 'ACTIVATE:ランダムな他の味方1体と敵1体を NULLIFY する。' }, YT + '(数値は再構成)');
  N({ id: 'teleport', n: 'Teleport', ja: 'テレポート', f: 'HIE', t: 'T', c: 3, r: 'C', on: { play: [{ op: 'draw', n: 2, filter: { g: 'Cyborg' } }] }, tx: '山札からサイボーグ・ユニットを2枚引く。' }, YT + ':コスト3(「体力+1」は未実装)');
  N({ id: 'disintegrate', n: 'Disintegrate', ja: '分解', f: 'HIE', t: 'T', c: 6, r: 'E', tg: { side: 'enemy', kind: 'unit' }, on: { play: [{ op: 'healFromTarget', t: 'T' }, { op: 'destroy', t: 'T' }] }, tx: '敵ユニット1体を破壊し、その体力と同じ値だけ自分の指揮官を回復する。' }, YT + '(コストは再構成)');
  N({ id: 'reassemble', n: 'Reassemble', ja: '再組立', f: 'HIE', t: 'T', c: 2, r: 'E', tg: { side: 'ally', kind: 'unit' }, on: { play: [{ op: 'grant', t: 'T', trig: 'revenge', fx: [{ op: 'returnSelf' }, { op: 'returnSelf' }] }] }, tx: '味方ユニット1体に「REVENGE:このカードを2枚手札に加える」を与える。' }, YT + '(コストは再構成)');
  N({ id: 'brood_mother', n: 'Brood Mother', ja: 'ブルードマザー', f: 'SHA', t: 'U', c: 2, a: 2, h: 4, r: 'E', g: ['Aberration'], on: { mutate: [{ op: 'summon', id: 'brood_spawn', n: 1 }] }, tx: 'MUTATE:1/1 SCREEN のブルードを配備。' }, YT + ':2/4(コストは再構成)');
  N({ id: 'spine_spitters', n: 'Spine Spitters', ja: 'スパイン・スピッター', f: 'SHA', t: 'T', c: 3, r: 'C',
    on: { play: [{ op: 'if', c: { hasGroup: 'Aberration' }, then: [{ op: 'repeat', n: 5, fx: [{ op: 'dmg', t: 'RE', n: 1, calc: 1 }] }], else: [{ op: 'repeat', n: 3, fx: [{ op: 'dmg', t: 'RE', n: 1, calc: 1 }] }] }] },
    tx: 'ランダムな敵ユニットに1ダメージを3回。味方アベレーションがいれば5回。' }, YT + '(コストは再構成)');
  N({ id: 'terminal_mutation', n: 'Terminal Mutation', ja: '末期変異', f: 'SHA', t: 'T', c: 1, r: 'E', tg: { side: 'enemy', kind: 'unit' },
    on: { play: [{ op: 'grant', t: 'T', trig: 'mutate', fx: [{ op: 'destroy', t: 'self' }] }, { op: 'mutate', t: 'T' }] }, tx: '敵ユニット1体に「MUTATE:このユニットを破壊する」を与え、MUTATE させる。' }, YT + '(即時に変異させる処理は再現版の解釈)');
  N({ id: 'unstable_transformation', n: 'Unstable Transformation', ja: '不安定な変容', f: 'SHA', t: 'T', c: 2, r: 'C', tg: { side: 'ally', kind: 'unit' },
    on: { play: [{ op: 'transform', t: 'T', id: 'unstable_monstrosity' }] }, tx: '味方ユニット1体を 4/3 のアンステーブル・モンストロシティに変身させる。' }, YT + '(コストは再構成)');
  N({ id: 'superheat', n: 'Superheat', ja: '過熱', f: 'HAJ', t: 'T', c: 2, r: 'E', needs: 'ownWeapon', tg: { side: 'enemy', kind: 'unit' },
    on: { play: [{ op: 'destroy', t: 'T' }, { op: 'breakWeapon' }] }, tx: '敵ユニット1体と、自分のウェポンを破壊する。' }, YT + '(コストは再構成)');
  N({ id: 'pulse_barrage', n: 'Pulse Barrage', ja: 'パルス弾幕', f: 'TER', t: 'T', c: 3, r: 'C', on: { play: [{ op: 'if', c: { allies: 3 }, then: [{ op: 'dmg', t: 'AE', n: 2 }] }] }, tx: '味方ユニットが3体以上いれば、全ての敵ユニットに2ダメージ。' }, YT + '(コストは再構成)');
  N({ id: 'precision_strike', n: 'Precision Strike', ja: '精密攻撃', f: 'TER', t: 'T', c: 3, r: 'C', tg: { side: 'enemy', kind: 'unit' }, on: { play: [{ op: 'dmg', t: 'T', n: 3 }] },
    energize: [{ n: 5, fx: [{ op: 'dmg', t: 'AE', n: 1 }], tx: 'さらに全ての敵ユニットに1ダメージ' }], tx: '敵ユニット1体に3ダメージ。ENERGIZE 5:さらに全ての敵ユニットに1ダメージ。' }, YT + '(数値は再構成)');
  N({ id: 'colonial_militia', n: 'Colonial Militia', ja: '植民地民兵', f: 'NEU', t: 'U', c: 3, a: 2, h: 2, r: 'E', on: { play: [{ op: 'buff', t: 'self', h: 'others' }] }, tx: 'ACTIVATE:他の味方ユニット1体につき体力+1。' }, YT + ':エリート(数値は再構成)');
  N({ id: 'viking_destroyer', n: 'Viking Destroyer', ja: 'ヴァイキング駆逐艦', f: 'NEU', t: 'U', c: 6, a: 5, h: 8, r: 'E', g: ['Massive'], tx: '(効果なし)' }, YT + ':6コスト 5/8(勢力不明のため中立)');
  // ハジル=ゴグのデッキリスト(Weaponry デッキ)で名前だけ確認できたカード
  const DL = 'YouTube デッキリスト(ハジル=ゴグ)で名称のみ確認。効果は再構成';
  add({ id: 'champion_of_the_pit', n: 'Champion of the Pit', ja: '闘技場の王者', f: 'HAJ', t: 'U', c: 5, a: 5, h: 5, r: 'E', kw: { ASSAULT: 1 }, tx: 'ASSAULT', src: 'C', note: DL });
  add({ id: 'reaver', n: 'Reaver', ja: 'リーヴァー', f: 'HAJ', t: 'U', c: 2, a: 3, h: 3, r: 'C', on: { fury: [{ op: 'buff', t: 'self', a: 1 }] }, tx: 'FURY:攻撃力+1。', src: 'C', note: DL });
  add({ id: 'vengeful_outcast', n: 'Vengeful Outcast', ja: '復讐の追放者', f: 'HAJ', t: 'U', c: 3, a: 3, h: 4, r: 'C', on: { revenge: [{ op: 'dmg', t: 'REA', n: 2 }] }, tx: 'REVENGE:ランダムな敵に2ダメージ。', src: 'C', note: DL });
  add({ id: 'repair_team', n: 'Repair Team', ja: '修理班', f: 'HAJ', t: 'U', c: 2, a: 2, h: 3, r: 'C', needsNot: 1, on: { play: [{ op: 'weaponUp', a: 0, ch: 1 }] }, tx: 'ACTIVATE:装備中のウェポンのチャージ+1。', src: 'C', note: DL });
  // 生成ユニット
  N({ id: 'brood_egg', n: 'Brood Egg', ja: 'ブルードエッグ', f: 'SHA', t: 'U', c: 1, a: 0, h: 3, r: 'C', g: ['Aberration'], token: true, on: { mutate: [{ op: 'buff', t: 'self', a: 3, h: 1 }] }, tx: 'MUTATE:+3/+1(3/4 になる)。' }, YT);
  N({ id: 'brood_spawn', n: 'Brood', ja: 'ブルード', f: 'SHA', t: 'U', c: 1, a: 1, h: 1, r: 'C', g: ['Aberration'], token: true, kw: { SCREEN: 1 }, tx: 'SCREEN' }, YT);
  N({ id: 'technician', n: 'Technician', ja: 'テクニシャン', f: 'NEU', t: 'U', c: 3, a: 3, h: 3, r: 'C', token: true, tx: '(Avalanche Bombard が配備する3/3)' }, YT);
  N({ id: 'unstable_monstrosity', n: 'Unstable Monstrosity', ja: 'アンステーブル・モンストロシティ', f: 'SHA', t: 'U', c: 4, a: 4, h: 3, r: 'C', g: ['Aberration'], token: true, tx: '(Unstable Transformation の変身先)' }, YT);
  N({ id: 'fledgling', n: 'Fledgling', ja: 'フレッジリング', f: 'HAJ', t: 'U', c: 1, a: 1, h: 1, r: 'C', token: true, kw: { MOBILITY: 1 }, on: { revenge: [{ op: 'shuffleIn', id: 'raider' }] }, tx: 'MOBILITY。REVENGE:2/1 MOBILITY のレイダーを山札に混ぜる。' }, YT);
  N({ id: 'raider', n: 'Raider', ja: 'レイダー', f: 'HAJ', t: 'U', c: 1, a: 2, h: 1, r: 'C', token: true, kw: { MOBILITY: 1 }, tx: 'MOBILITY' }, YT);

  // --- v2 モジュール修正(YouTube 調査) ---
  const mById = {}; M.forEach(m => { mById[m.id] = m; });
  const mfix = (id, o, note) => { Object.assign(mById[id], o); if (note) mById[id].note = (mById[id].note ? mById[id].note + ' / ' : '') + note; };
  mfix('call_marines', { n: 'Rally', ja: 'ラリー', src: 'A', tx: '1/1 のガーズマン(サポート)を配備。' }, '動画3本とデッキリストで名称・効果を確認');
  mfix('restore', { n: 'Nanite Conversion', ja: 'ナナイト変換', tx: '味方のユニットか指揮官1体を RESTORE 2。' }, '動画2本ではこの名前(Restore は開発者インタビューでの呼び名)');
  mfix('redeem_contract', { src: 'A', tx: 'ランダムな傭兵を配備:Bodyguard(0/2 SCREEN)、Contractor(1/1 CLOAK)、Dealer(0/1、CREDIT カードのコスト-1)のいずれか。' }, '動画2本で確認');
  mfix('scout_ahead', { src: 'B' }, 'ヴラクシアンのデッキのモジュール欄で確認(効果は未確認)');
  mfix('compression_algorithm', { tg: { side: 'enemy', kind: 'unit' }, fx: [{ op: 'bounce', t: 'T' }], tx: '敵ユニット1体を手札に戻す。' }, '動画字幕で効果を確認');
  mfix('arsenal', { fx: [{ op: 'equip', id: 'blaster' }], tx: 'ブラスターを装備する。' }, '動画字幕で「1/1 のブラスターを装備」');
  mfix('mind_anchor', { fx: [{ op: 'buff', t: 'T', a: -1 }, { op: 'psy', n: 1 }], tx: '敵ユニット1体の攻撃力-1、サイキックチャージ+1。' }, '動画字幕(確度中)');
  mfix('hit_and_run', { tg: { side: 'enemy', kind: 'unit' }, fx: [{ op: 'kw', t: 'T', k: 'VULNERABILITY', v: 1 }], tx: '敵ユニット1体は、ダメージを受けるたびに1点余分に受ける(VULNERABILITY 1)。' }, '動画字幕(確度中)');
  mfix('warlords_call', { fx: [{ op: 'summon', id: 'fledgling', n: 1 }], tx: '1/1 MOBILITY のフレッジリングを配備(破壊されると 2/1 のレイダーが山札に入る)。' }, '動画字幕(確度中)');
  M.push(
    { id: 'praecordian_symbiote', n: 'Praecordian Symbiote', ja: 'プレコーディアン共生体', f: 'SHA', ct: 'supply', c: 1, fx: [{ op: 'dmg', t: 'ac', n: 3, calc: 1 }, { op: 'energy', n: 8 }], tx: '自分の指揮官は3ダメージを受け、エネルギー+8。', src: 'B', note: '動画字幕(確度中)。シャンティのデッキ7本で採用' },
    { id: 'draw_essence', n: 'Draw Essence', ja: 'エッセンス抽出', f: 'ANN', ct: 'passive', start: [{ op: 'if', c: { hasKw: 'PACIFIST' }, then: [{ op: 'psy', n: 1 }] }], tx: 'ターン開始時、PACIFY(攻撃不能)の味方ユニットがいればサイキックチャージ+1。', src: 'B', note: '動画字幕(確度高)' },
    { id: 'battle_hardened', n: 'Battle Hardened', ja: '歴戦の守り', f: 'CON', ct: 'energy', c: 5, tg: { side: 'ally', kind: 'unit' }, fx: [{ op: 'kw', t: 'T', k: 'SOAK', v: 1 }], tx: '味方ユニット1体に SOAK 1 を与える。', src: 'B', note: '動画字幕(確度高、コストは再構成)' }
  );


  // ===================================================================
  // v3 修正(2026-10-02:追加の字幕調査 第1〜4回+ユーザー提供のスクリーンショット)
  // スクリーンショットで文面を読めたものは src A。詳細は YOUTUBE_RESEARCH.md 第3部。
  // ===================================================================
  const SS = 'ゲーム画面のスクリーンショットで文面を確認';
  const RU = 'ロシア語のデッキ解説動画(字幕)';
  // --- スクリーンショットで確認したカード ---
  fix('void_probe', { c: 3, a: 3, h: 2, g: ['Support'], src: 'A' }, SS + '(3コスト 3/2 Support)');
  fix('combat_engineer', { c: 1, a: 1, h: 2, src: 'A' }, SS + '(1コスト 1/2 Support)');
  fix('carbonic_protector', { c: 6, a: 4, h: 6, g: ['Massive'], kw: { SOAK: 2, SCREEN: 1 }, tx: 'SOAK 2。SCREEN', src: 'B' }, SS + '(4/6 Massive、SOAK 2・SCREEN)。コストは画面外のため推定');
  fix('adrenal_transformation', { c: 2, tg: null, on: {}, cy: { on: 'allyUnitAttacked', fx: [{ op: 'buff', t: 'T', a: 3, h: 3 }] }, tx: 'CYPHER:自分のユニットが攻撃された時、そのユニットは+3/+3を得る。', src: 'B' }, SS + '(コストは画面外のため推定)');
  fix('terminal_mutation', { on: { play: [{ op: 'grant', t: 'T', trig: 'mutate', fx: [{ op: 'destroy', t: 'self' }] }] }, tx: '対象は「MUTATE:このユニットを破壊する」を得る。(Release Mutagen で変異させて破壊する)', src: 'B' }, SS + '。即時に変異させる処理を削除');
  fix('the_restless', { f: 'NEU' }, 'シャンティのデッキリストにも登場したため中立に修正');
  N({ id: 'infestation', n: 'Infestation', ja: 'インフェステーション', f: 'SHA', t: 'T', c: 2, r: 'E',
    cy: { on: 'enemyUnitPlayed', fx: [{ op: 'grant', t: 'T', trig: 'revenge', fx: [{ op: 'summon', id: 'infestation_spawn', n: 2, side: 'enemy' }] }] },
    tx: 'CYPHER:相手がユニットを配備した時、そのユニットは「REVENGE:2/1 を2体、相手(あなた)の側に配備」を得る。', src: 'A' }, SS);
  N({ id: 'saboteur', n: 'Saboteur', ja: 'サボタージュ工作員', f: 'CON', t: 'U', c: 3, a: 3, h: 3, r: 'C', tg: { side: 'enemy', kind: 'unit', opt: true },
    on: { play: [{ op: 'disable', t: 'T' }] }, tx: 'ACTIVATE:敵ユニット1体を DISABLE。', src: 'A' }, SS + '(勢力はデッキリストから推定)');
  N({ id: 'defensive_bunker', n: 'Defensive Bunker', ja: '防衛バンカー', f: 'NEU', t: 'U', c: 2, a: 1, h: 4, r: 'C', kw: { SCREEN: 1 }, tx: 'SCREEN', src: 'A' }, SS);
  N({ id: 'battle_walker', n: 'Battle Walker', ja: 'バトルウォーカー', f: 'NEU', t: 'U', c: 3, a: 3, h: 3, r: 'C', on: { endTurn: [{ op: 'dmg', t: 'REA', n: 1 }] }, tx: 'ターン終了時:ランダムな敵に1ダメージ。', src: 'A' }, SS);
  N({ id: 'brigands_of_arcturis', n: 'Brigands of Arcturis', ja: 'アークトゥルスの略奪者', f: 'NEU', t: 'U', c: 3, a: 3, h: 1, r: 'H', kw: { MOBILITY: 1 }, on: { revenge: [{ op: 'redeployWeaker' }] },
    tx: 'MOBILITY。REVENGE:このユニットの基本攻撃力が1より大きければ、基本攻撃力を1下げて再配備する。', src: 'B' }, SS + '(コストは画面外のため推定)');
  N({ id: 'vraxxian_frigate', n: 'Vraxxian Frigate', ja: 'ヴラクシアン・フリゲート', f: 'NEU', t: 'U', c: 5, a: 3, h: 5, r: 'C', g: ['Vraxxian'], kw: { 'ARC ATTACK': 1 }, tx: 'ARC ATTACK', src: 'B' }, SS + '(コスト・勢力は推定)');
  // 英語名が分からないカード(ロシア語版の画面のみ)→ 仮称で新規実装
  const RUSS = 'ロシア語版のゲーム画面で文面を確認。英語名不明のため仮称(コストは推定)';
  N({ id: 'ru_spawn', n: 'Spawn (provisional)', ja: 'オトロージエ(仮称)', f: 'SHA', t: 'U', c: 5, a: 4, h: 7, r: 'E', g: ['Aberration'], on: { devour: [{ op: 'copyFromMem' }] },
    tx: 'DEVOUR:破壊したユニットの能力を COPY する。', src: 'B' }, RUSS + '。原文「Отродье」');
  N({ id: 'ru_walking_ironclads', n: 'Walking Ironclads (provisional)', ja: '歩行装甲兵(仮称)', f: 'NEU', t: 'U', c: 4, a: 2, h: 5, r: 'C', kw: { MOBILITY: 1, ARMORED: 1 },
    tx: 'MOBILITY。ARMORED', src: 'B' }, RUSS + '。原文「Шагающие броненосцы」');
  N({ id: 'ru_deadly_gaze', n: 'Deadly Gaze (provisional)', ja: '死の凝視(仮称)', f: 'NEU', t: 'U', c: 4, a: 2, h: 4, r: 'E', on: { attack: [{ op: 'nullify', t: 'T' }] },
    tx: '攻撃する前に、攻撃対象のユニットを NULLIFY する。', src: 'B' }, RUSS + '。原文「Смертельный взгляд」');
  // --- 字幕調査(第1〜3回)で分かったカード ---
  fix('disciple_of_asag', { f: 'ANN', c: 3, a: 3, h: 4, on: { moduleUsed: [{ op: 'psy', n: 1 }] }, tx: 'モジュールを使うたびに、サイキックチャージ+1。', src: 'B' }, '動画2本(英語・ロシア語)で「モジュールを使うたびにチャージ」。アヌンナキに修正');
  N({ id: 'prophetic_visions', n: 'Prophetic Visions', ja: '予言の幻視', f: 'ANN', t: 'T', c: 4, r: 'E', on: { play: [{ op: 'draw', n: 2 }, { op: 'if', c: { psy: 5 }, then: [{ op: 'draw', n: 2 }] }] },
    tx: 'カードを2枚引く。サイキックチャージが5以上なら、さらに2枚引く。' }, RU + '「4コストで最大4枚」+英語動画「チャージ5で2倍」');
  N({ id: 'true_believer', n: 'True Believer', ja: '真の信者', f: 'ANN', t: 'U', c: 4, a: 1, h: 2, r: 'H', on: { play: [{ op: 'buff', t: 'self', a: 'psy', h: 'psy' }] },
    tx: 'ACTIVATE:サイキックチャージ1につき+1/+1。' }, RU + '(数値は再構成)');
  N({ id: 'illusionary_force', n: 'Illusionary Force', ja: '幻影の軍勢', f: 'ANN', t: 'U', c: 3, a: 1, h: 4, r: 'E', kw: { SCREEN: 1 }, tg: { side: 'ally', kind: 'unit', opt: true, notSelf: true },
    on: { play: [{ op: 'copyText', t: 'T' }] }, tx: 'SCREEN。ACTIVATE:味方ユニット1体の効果をコピーする。' }, RU + '(数値は再構成)');
  N({ id: 'energy_link', n: 'Energy Link', ja: 'エナジーリンク', f: 'HIE', t: 'T', c: 1, r: 'C', tg: { side: 'ally', kind: 'unit' }, on: { play: [{ op: 'healHpFromCost', t: 'T' }] },
    tx: '味方ユニット1体の体力を、そのユニットのコスト分だけ増やす。' }, RU + '(確度高、コストは再構成)');
  N({ id: 'rangers', n: 'Rangers', ja: 'レンジャーズ', f: 'HIE', t: 'U', c: 2, a: 2, h: 3, r: 'C', tx: '(テキストなし)' }, RU + ':2コスト 2/3');
  N({ id: 'error_card', n: 'Error', ja: 'エラー', f: 'CON', t: 'T', c: 2, r: 'E', on: { play: [{ op: 'drawOpp', n: 1 }, { op: 'tax', n: 2 }] },
    tx: '相手はカードを1枚引く。相手の次のターン、相手のタクティクスのコスト+2。' }, RU + '(英語名は推定)');
  N({ id: 'treachery', n: 'Treachery', ja: '裏切り', f: 'CON', t: 'T', c: 2, r: 'E', kw: { CREDIT: 1 }, on: { play: [{ op: 'giveOpp', id: 'mercenary_traitor', n: 2 }] },
    tx: 'CREDIT 1。相手の手札に「裏切り者の傭兵」を2枚加える。' }, RU + '(2コスト・CREDIT 1)');
  N({ id: 'discharge', n: 'Discharge', ja: '放電', f: 'NEU', t: 'T', c: 3, r: 'E', on: { play: [{ op: 'grant', t: 'AE', trig: 'endTurn', fx: [{ op: 'dmg', t: 'self', n: 1 }] }] },
    energize: [{ n: 10, fx: [{ op: 'dmg', t: 'AE', n: 1 }], tx: 'さらに全ての敵ユニットに1ダメージ' }], tx: '全ての敵ユニットは「ターン終了時に自身に1ダメージ」を得る。ENERGIZE 10:さらに全ての敵ユニットに1ダメージ。' }, RU + '(ENERGIZE の値は再構成)');
  N({ id: 'privateer_raid', n: 'Privateer Raid', ja: '私掠襲撃', f: 'CON', t: 'T', c: 2, r: 'C', on: { play: [{ op: 'dmg', t: 'ec', n: 4, calc: 1 }] }, tx: '敵指揮官に4ダメージ。' }, RU + '(動画ではコスト1。再現版はバランスのため2)');
  N({ id: 'corrupted_hound', n: 'Corrupted Hound', ja: '汚染された猟犬', f: 'NEU', t: 'U', c: 1, a: 2, h: 1, r: 'C', kw: { MOBILITY: 1 }, tx: 'MOBILITY' }, RU + '(数値は再構成)');
  N({ id: 'mercenary_traitor', n: 'Mercenary Traitor', ja: '裏切り者の傭兵', f: 'CON', t: 'U', c: 3, a: 1, h: 2, r: 'C', g: ['Mercenary'], token: true, handEnd: [{ op: 'dmg', t: 'ac', n: 1, calc: 1 }],
    tx: 'これが手札にある間、自分のターン終了時に自分の指揮官は1ダメージを受ける。' }, RU + '(英語名は推定、数値は再構成)');
  N({ id: 'infestation_spawn', n: 'Infestation Spawn (provisional)', ja: '寄生体(仮称)', f: 'SHA', t: 'U', c: 1, a: 2, h: 1, r: 'C', g: ['Aberration'], token: true, tx: '(Infestation が配備する 2/1。画面上の名前は判読不可)' }, SS);
  fix('brood_egg', { n: 'Brood Eggs' });
  fix('fledgling', { on: { endTurn: [{ op: 'destroy', t: 'self' }], revenge: [{ op: 'shuffleIn', id: 'raider' }] }, tx: 'MOBILITY。ターン終了時に破壊される。REVENGE:2/1 MOBILITY のレイダーを山札に混ぜる。' }, RU + ':「ターン終了時に死ぬ」');

  // --- v3 モジュール修正 ---
  mfix('psychic_charge', { n: 'Mind Anchor', ja: 'マインドアンカー', tg: { side: 'any', kind: 'unit', opt: true },
    fx: [{ op: 'if', c: { hasT: 1 }, then: [{ op: 'buff', t: 'T', a: -1 }], else: [{ op: 'psy', n: 1 }] }],
    tx: '2サプライ:ユニット1体の攻撃力-1、または(対象を選ばなければ)サイキックチャージ+1。', src: 'B' }, '英語・ロシア語の動画2本で「チャージを得るか、ユニットの攻撃力-1」の二択と確認。名称 Mind Anchor は英語動画より');
  mfix('mind_anchor', { hidden: 1 }, '基本モジュールと同じものと判明したため追加モジュールから除外');
  mfix('viromorphic_spores', { c: 14, tg: { side: 'ally', kind: 'unit' }, fx: [{ op: 'copyLeft', t: 'T' }], tx: '選んだ味方ユニットは、左隣のユニットの効果を得る。', src: 'A' }, SS + '(画面ではエネルギー12。2017/5/22 のパッチで14)');
  mfix('infect', { tg: { side: 'ally', kind: 'unit' }, fx: [{ op: 'grant', t: 'T', trig: 'revenge', fx: [{ op: 'summon', id: 'brood_egg', n: 1 }] }], tx: '味方ユニット1体に「REVENGE:0/3 のブルードエッグを配備」を与える。', src: 'A' }, SS + '(画面ではエネルギー7。v1.2.2 のパッチで9)');
  mfix('release_mutagen', { tg: { side: 'any', kind: 'char', mutable: true }, tx: 'MUTATE を持つユニット1体(敵も可)を変異させる。指揮官を対象にした場合、指揮官は1ダメージを受け、このターン攻撃力+2。' }, 'Terminal Mutation を敵に使う画面から、敵ユニットも対象にできると推定');
  mfix('warlords_call', { ct: 'supply', c: 1, tx: '1サプライ:1/1 MOBILITY のフレッジリングを配備(ターン終了時に破壊され、2/1 のレイダーが山札に入る)。' }, RU + ':1サプライ');
  mfix('hit_and_run', { ct: 'supply', c: 1 }, RU + '(「攻撃と後退」):1サプライ');
  mfix('ethereal_enlightenment', {}, 'ロシア語動画では体力-15(後の版で変更された可能性)');
  M.push(
    { id: 'compensation_protocol', n: 'Compensation Protocol', ja: '補償プロトコル', f: 'HIE', ct: 'passive', tx: 'テキストのない味方ユニットにタクティクスを使うと、そのユニットは+1/+1を得る。', src: 'B', note: RU },
    { id: 'overextend', n: 'Overextend', ja: '過剰展開(ディスロケーション)', f: 'CON', ct: 'passive', r: 'P',
      end: [{ op: 'if', c: { enemyMore: 1 }, then: [{ op: 'giveOpp', id: 'mercenary_traitor', n: 1 }] }],
      tx: 'ターン終了時、相手のユニットの方が多ければ、相手の手札に「裏切り者の傭兵」を1枚加える。', src: 'B', note: '英語動画の Overextend の説明と、ロシア語動画の「ディスロケーション」の説明が一致。デッキリストでも名称確認' }
  );

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
