/* Star Crusade CCG 再現版 — UI */
(function () {
  const D = window.SC_DATA, G = window.SC_GUIDE;
  const app = document.getElementById('app');
  const modal = document.getElementById('modal');
  const FKEYS = ['ANN', 'HIE', 'SHA', 'HAJ', 'CON', 'TER', 'VRX'];

  // ---------- 保存 ----------
  const LS = {
    get(k, d) { try { const v = localStorage.getItem('scr.' + k); return v ? JSON.parse(v) : d; } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem('scr.' + k, JSON.stringify(v)); return true; } catch (e) { return false; } },
    del(k) { try { localStorage.removeItem('scr.' + k); } catch (e) { /* noop */ } }
  };
  const settings = Object.assign({ font: 1, theme: 'dark', speed: 'normal', diff: 'normal', hints: true, confirmEnd: true, name: 'あなた' }, LS.get('settings', {}));
  let decks = LS.get('decks', []);
  let stats = LS.get('stats', { games: [] });
  const saveSettings = () => LS.set('settings', settings);
  const saveDecks = () => LS.set('decks', decks);
  const saveStats = () => LS.set('stats', stats);

  function applySettings() {
    document.documentElement.style.fontSize = (16 * settings.font) + 'px';
    document.documentElement.dataset.theme = settings.theme;
  }
  applySettings();

  // ---------- ユーティリティ ----------
  const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const KWKEYS = Object.keys(D.keywords).sort((a, b) => b.length - a.length);
  const KWRE = new RegExp('(' + KWKEYS.map(k => k.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|') + ')', 'g');
  const kwify = t => esc(t).replace(KWRE, m => `<b class="kw" data-kw="${m}">${m}</b>`);
  function toast(m, ms) {
    const t = document.getElementById('toast'); t.textContent = m; t.classList.add('on');
    clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.remove('on'), ms || 2200);
  }
  function ask(msg, yes, onYes) {
    openModal(`<p>${esc(msg)}</p><div class="row"><button class="btn bad grow" id="ask-yes">${esc(yes)}</button><button class="btn grow" data-close>キャンセル</button></div>`);
    document.getElementById('ask-yes').onclick = () => { closeModal(); onYes(); };
  }
  function openModal(html) { modal.innerHTML = `<div class="box">${html}</div>`; modal.hidden = false; }
  function closeModal() { modal.hidden = true; modal.innerHTML = ''; }
  modal.addEventListener('click', e => { if (e.target === modal || e.target.closest('[data-close]')) closeModal(); });
  document.addEventListener('click', e => {
    const k = e.target.closest('.kw');
    if (k && D.keywords[k.dataset.kw]) { const d = D.keywords[k.dataset.kw]; toast(`${k.dataset.kw}(${d[0]}):${d[1]}`, 4500); e.stopPropagation(); }
  }, true);
  const fcol = f => D.factions[f].color;
  const srcChip = s => `<span class="chip src-${s}" title="${esc(D.src[s][1])}">${D.src[s][0]}</span>`;
  function download(name, obj) {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([JSON.stringify(obj, null, 1)], { type: 'application/json' }));
    a.download = name; document.body.appendChild(a); a.click(); a.remove();
  }
  function topbar(title, back) {
    return `<div class="topbar"><button class="btn sm" data-go="${back || 'home'}">←</button><h1>${title}</h1></div>`;
  }

  // ---------- カード表示 ----------
  function typeLine(c) {
    let t = D.types[c.t];
    if (c.g && c.g.length) t += '/' + c.g.map(g => D.groups[g]).join('・');
    return `${t} ・ ${D.rarity[c.r]}`;
  }
  function cardHTML(c, opt) {
    opt = opt || {};
    const stats = c.t === 'U' ? `<span class="stat"><span class="atk">⚔${c.a}</span><span class="hp">♥${c.h}</span></span>` : c.t === 'W' ? `<span class="stat"><span class="atk">⚔${c.a}</span><span>⚡${c.ch}</span></span>` : '<span></span>';
    return `<div class="card rar-${c.r}" style="--fc:${fcol(c.f)}" data-card="${c.id}">
      <div class="hd"><div class="cost">${c.c}</div><div class="grow"><div class="nm">${esc(c.ja)}</div><div class="en">${esc(c.n)}</div></div><span class="chip" style="border-color:${fcol(c.f)}">${D.factions[c.f].glyph} ${D.factions[c.f].ja}</span></div>
      <div class="meta">${typeLine(c)}${c.token ? ' ・ 生成カード' : ''}</div>
      <div class="txt">${kwify(c.tx)}</div>
      ${opt.full && c.en ? `<div class="en">原文: ${esc(c.en)}</div>` : ''}
      <div class="ft">${stats}${srcChip(c.src)}</div>
      ${opt.full ? `<div class="tiny muted">出典メモ: ${esc(c.note || '')}</div>` : ''}
    </div>`;
  }
  function kwExplain(text) {
    const found = []; let m; KWRE.lastIndex = 0;
    while ((m = KWRE.exec(text))) if (!found.includes(m[1])) found.push(m[1]);
    if (!found.length) return '';
    return '<div class="small" style="margin-top:.4rem">' + found.map(k => `<div><b class="kw">${k}</b>(${D.keywords[k][0]}):${esc(D.keywords[k][1])}</div>`).join('') + '</div>';
  }
  function showCard(id) {
    const c = SC.card(id);
    openModal(cardHTML(c, { full: true }) + kwExplain(c.tx + ' ' + (c.kw ? Object.keys(c.kw).join(' ') : '')) + `<div class="row" style="margin-top:.8rem"><button class="btn grow" data-close>閉じる</button></div>`);
  }
  function moduleHTML(m) {
    const cost = m.ct === 'passive' ? 'パッシブ' : m.ct === 'supply' ? `${m.c}サプライ(指揮官能力)` : `${m.c}エネルギー`;
    return `<div class="card" style="--fc:${m.f === 'ANY' ? '#9aa0a6' : fcol(m.f)}">
      <div class="hd"><div class="grow"><div class="nm">${esc(m.ja)}</div><div class="en">${esc(m.n)}</div></div><span class="chip">${m.f === 'ANY' ? '共通' : D.factions[m.f].ja}</span></div>
      <div class="meta">モジュール ・ ${cost}${m.hp ? ` ・ 初期体力${m.hp > 0 ? '+' : ''}${m.hp}` : ''}${m.r === 'P' ? ' ・ パラゴン' : ''}${m.base ? ' ・ 基本能力' : ''}</div>
      <div class="txt">${kwify(m.tx)}</div>
      <div class="ft"><span class="tiny muted">${esc(m.note || '')}</span>${srcChip(m.src)}</div></div>`;
  }

  // ---------- デッキ ----------
  function starterDeck(f) {
    const fac = D.cards.filter(c => c.f === f && !c.token && c.r !== 'P').sort((a, b) => a.c - b.c);
    const cards = [];
    for (const c of fac) { if (c.c >= 8) continue; cards.push(c.id, c.id); if (cards.length >= 20) break; }
    const neu = D.cards.filter(c => c.f === 'NEU' && !c.token && c.r === 'C' && c.c <= 4).sort((a, b) => a.c - b.c);
    for (const c of neu) { if (cards.length >= 26) break; cards.push(c.id); if (cards.length < 26) cards.push(c.id); }
    return { id: 'starter_' + f, name: `${D.factions[f].ja} スターター`, faction: f, cards: cards.slice(0, 26), modules: [], starter: true };
  }
  const allDecks = () => FKEYS.map(starterDeck).concat(decks);
  const deckById = id => allDecks().find(d => d.id === id);

  // ---------- ルーター ----------
  let game = null;
  const ui = { mode: null, targets: [], sheet: null, viewer: 0, cover: false, aiTimer: null, showLog: false };
  window.addEventListener('hashchange', route);
  app.addEventListener('click', e => {
    const g = e.target.closest('[data-go]');
    if (g) { e.preventDefault(); location.hash = g.dataset.go; }
  });
  function route() {
    clearTimeout(ui.aiTimer);
    closeModal();
    const h = location.hash.slice(1) || 'home';
    const [v, arg] = h.split('/');
    window.scrollTo(0, 0);
    if (v === 'game') { if (!game) { location.hash = 'home'; return; } return renderGame(); }
    const views = { home: viewHome, setup: viewSetup, decks: viewDecks, deck: viewDeck, cards: viewCards, guide: viewGuide, stats: viewStats, settings: viewSettings };
    (views[v] || viewHome)(arg);
  }

  // ---------- ホーム ----------
  function viewHome() {
    const auto = LS.get('auto', null);
    app.innerHTML = `<div class="home">
      <div class="logo">STAR CRUSADE</div>
      <div class="sub">War for the Expanse ・ 非公式再現版</div>
      <div class="menu">
        ${auto ? `<button class="btn warn wide" id="resume">▶ 続きから(ターン${auto.turn}・${esc(D.factions[auto.players[0].faction].ja)} vs ${esc(D.factions[auto.players[1].faction].ja)})</button>` : ''}
        <button class="btn pri wide" data-go="setup/ai">CPU と対戦</button>
        <button class="btn" data-go="setup/hot">2人対戦(同じ端末)</button>
        <button class="btn" data-go="decks">デッキ</button>
        <button class="btn" data-go="cards">カード図鑑</button>
        <button class="btn" data-go="guide">勢力ガイド</button>
        <button class="btn" data-go="guide/rules">遊び方</button>
        <button class="btn" data-go="stats">戦績</button>
        <button class="btn wide" data-go="settings">設定・セーブ</button>
      </div>
      <p class="notice">ZiMAD の「Star Crusade CCG」(2015〜2017)のファンによる非公式再現です。原作のカードデータは失われており、各カードには資料の確認度(検証済み/一部確認/名称のみ/補完)を表示しています。完全オフラインで動作します。</p>
    </div>`;
    const r = document.getElementById('resume');
    if (r) r.onclick = () => { game = LS.get('auto', null); if (game) { resetUI(); location.hash = 'game'; } };
  }

  // ---------- 対戦設定 ----------
  function deckOptions(sel) {
    return `<option value="random">ランダム(全勢力)</option>` + allDecks().map(d => `<option value="${esc(d.id)}" ${d.id === sel ? 'selected' : ''}>${esc(d.name)}(${D.factions[d.faction].ja}・${d.cards.length}枚)</option>`).join('');
  }
  function viewSetup(mode) {
    const hot = mode === 'hot';
    const last = LS.get('lastDeck', 'starter_TER');
    app.innerHTML = topbar(hot ? '2人対戦(同じ端末)' : 'CPU と対戦') + `<div class="view">
      <div class="panel"><h3>${hot ? 'プレイヤー1' : 'あなた'}のデッキ</h3>
        ${hot ? `<input id="n0" value="プレイヤー1" style="width:100%;margin-bottom:.5rem">` : ''}
        <select id="d0" style="width:100%">${deckOptions(last)}</select></div>
      <div class="panel"><h3>${hot ? 'プレイヤー2のデッキ' : '相手(ランダムデッキ)'}</h3>
        ${hot ? `<input id="n1" value="プレイヤー2" style="width:100%;margin-bottom:.5rem"><select id="d1" style="width:100%">${deckOptions('random')}</select>` :
        `<select id="of" style="width:100%"><option value="">ランダムな勢力</option>${FKEYS.map(f => `<option value="${f}">${D.factions[f].ja}</option>`).join('')}</select>
         <div class="row" style="margin-top:.6rem"><span class="muted small">強さ</span>
         <select id="df"><option value="easy" ${settings.diff === 'easy' ? 'selected' : ''}>やさしい</option><option value="normal" ${settings.diff === 'normal' ? 'selected' : ''}>ふつう</option></select></div>
         <p class="small muted">相手は毎回、勢力カードと中立カードからランダムに組まれたデッキ(25〜30枚・モジュールもランダム)を使います。</p>`}
      </div>
      ${hot ? '<p class="small muted">ターンの切り替わりで手札を隠す画面が出ます。端末を相手に渡してからタップしてください。</p>' : ''}
      <button class="btn pri" id="start" style="width:100%;min-height:3.2rem">対戦開始</button>
    </div>`;
    document.getElementById('start').onclick = () => {
      const pickDeck = v => v === 'random' ? SC.randomDeck() : JSON.parse(JSON.stringify(deckById(v)));
      const v0 = document.getElementById('d0').value;
      LS.set('lastDeck', v0);
      const d0 = pickDeck(v0);
      let d1, p1;
      if (hot) {
        d1 = pickDeck(document.getElementById('d1').value);
        p1 = { name: document.getElementById('n1').value || 'プレイヤー2', faction: d1.faction, cards: d1.cards, modules: d1.modules, deckName: d1.name };
      } else {
        const of = document.getElementById('of').value;
        settings.diff = document.getElementById('df').value; saveSettings();
        d1 = SC.randomDeck(of || null);
        p1 = { name: 'CPU(' + D.factions[d1.faction].ja + ')', faction: d1.faction, cards: d1.cards, modules: d1.modules, ai: true, deckName: d1.name };
      }
      const n0 = hot ? (document.getElementById('n0').value || 'プレイヤー1') : settings.name;
      game = SC.newGame({ mode: hot ? 'hot' : 'ai', diff: settings.diff, p0: { name: n0, faction: d0.faction, cards: d0.cards, modules: d0.modules, deckName: d0.name }, p1 });
      resetUI();
      if (hot) { ui.viewer = game.active; ui.cover = true; }
      autosave();
      location.hash = 'game';
    };
  }
  function resetUI() { ui.mode = null; ui.targets = []; ui.sheet = null; ui.viewer = game && game.mode === 'hot' ? game.active : 0; ui.cover = !!(game && game.mode === 'hot'); ui.showLog = false; }
  function autosave() { if (game && game.winner === null) LS.set('auto', game); }

  // ---------- ゲーム画面 ----------
  function unitHTML(s, u) {
    const c = SC.card(u.id);
    const a = SC.atkOf(s, u.uid);
    const kws = [];
    const show = { SCREEN: '遮', SHIELD: '盾', ARMORED: '装', CLOAK: '隠', ASSAULT: '連', MOBILITY: '機', SOAK: '吸', SWARM: '群', ZEAL: '熱', CRITICAL: '致', 'ARC ATTACK': '弧', PACIFIST: '非', BUNKER: '掩', VULNERABILITY: '脆', INVINCIBLE: '無', 'IGNORE ARMOR': '貫', NOREVEAL: '秘' };
    for (const k in show) { const v = SC.has(u, k); if (v) kws.push(show[k] + (['SOAK', 'VULNERABILITY'].includes(k) ? v : '')); }
    if (SC.trigs(u, 'revenge').length) kws.push('報');
    if (SC.trigs(u, 'fury').length) kws.push('激');
    if (SC.trigs(u, 'mutate').length) kws.push('変');
    if (u.nulled) kws.push('無効');
    const cls = ['unit'];
    if (SC.has(u, 'SCREEN')) cls.push('screen');
    if (SC.has(u, 'CLOAK')) cls.push('cloak');
    if (SC.has(u, 'SHIELD')) cls.push('shield');
    const canAtk = s.active === u.p && SC.canAttack(s, u.uid) && isHumanTurn();
    if (canAtk && settings.hints) cls.push('can');
    if (ui.mode && ui.mode.from === u.uid) cls.push('sel');
    if (ui.targets.includes(u.uid)) cls.push('tgt');
    const sleepy = (u.sick && !SC.has(u, 'MOBILITY')) || u.disabled || u.wasDisabled;
    const atkCls = a > (c.a || 0) ? 'style="color:var(--good)"' : '';
    return `<div class="${cls.join(' ')}" style="--fc:${fcol(c.f)}" data-ref="${u.uid}">
      ${sleepy && s.active === u.p ? '<span class="zz">💤</span>' : ''}${u.ctrlBack !== undefined ? '<span class="zz">🌀</span>' : ''}
      <div class="un">${esc(c.ja)}</div><div class="kws">${kws.map(k => `<span>${k}</span>`).join('')}</div>
      <div class="us"><span class="atk" ${atkCls}>${a}</span><span class="hp ${u.hp < u.maxHp ? 'dmg' : ''}">${u.hp}</span></div></div>`;
  }
  function avatarHTML(s, p) {
    const pl = s.players[p];
    const ref = 'c' + p;
    const cls = ['avatar'];
    if (ui.targets.includes(ref)) cls.push('tgt');
    if (ui.mode && ui.mode.from === ref) cls.push('sel');
    if (s.active === p && isHumanTurn() && p === ui.viewer && SC.canAttack(s, ref) && settings.hints) cls.push('can');
    const a = SC.atkOf(s, ref);
    return `<div class="${cls.join(' ')}" style="--fc:${fcol(pl.faction)}" data-ref="${ref}">${D.factions[pl.faction].glyph}
      <span class="hpb">${Math.max(0, pl.hp)}</span>${pl.psy ? `<span class="psyb">${pl.psy}</span>` : ''}${a ? `<span class="atkb">${a}</span>` : ''}</div>`;
  }
  function resHTML(s, p) {
    const pl = s.players[p];
    const w = pl.weapon ? `<span class="chip">🗡${esc(SC.ja(pl.weapon.id))} ${pl.weapon.a}/${pl.weapon.ch}</span>` : '';
    const kw = [];
    if (SC.has(pl, 'SHIELD')) kw.push('盾'); if (SC.has(pl, 'SCREEN')) kw.push('遮'); if (SC.has(pl, 'VULNERABILITY')) kw.push('脆' + SC.has(pl, 'VULNERABILITY'));
    return `<div class="res"><span class="pname">${esc(pl.name)}${s.active === p ? ' ◀' : ''}</span>
      <span class="r-sup">◆<b>${pl.supply}</b>/${pl.maxSupply}</span><span class="r-en">⚡<b>${pl.energy}</b></span>
      ${pl.psy ? `<span class="r-psy">✧${pl.psy}</span>` : ''}<span class="muted">山${pl.deck.length}</span><span class="muted">手${pl.hand.length}</span>
      ${pl.cyphers.length ? `<span class="chip">🔒CYPHER×${pl.cyphers.length}</span>` : ''}${pl.credit ? `<span class="chip" style="color:var(--bad)">CREDIT ${pl.credit}</span>` : ''}
      ${kw.length ? `<span class="chip">${kw.join(' ')}</span>` : ''}${w}</div>`;
  }
  function isHumanTurn() { if (!game || game.winner !== null) return false; const pl = game.players[game.active]; return !pl.ai && game.active === ui.viewer && !ui.cover; }

  function renderGame() {
    const s = game;
    if (s.mode === 'hot' && s.winner === null && s.active !== ui.viewer) { ui.cover = true; ui.viewer = s.active; }
    const me = ui.viewer, op = 1 - me;
    const P = s.players[me], O = s.players[op];
    const my = isHumanTurn();
    const msg = ui.mode ? (ui.mode.kind === 'attack' ? '攻撃対象を選んでください' : '対象を選んでください') :
      s.winner !== null ? '対戦終了' : my ? (settings.hints ? hintText(s) : 'あなたのターン') : `${esc(s.players[s.active].name)} のターン…`;
    const ohand = O.hand.map(h => h.rev ? `<span class="crev" data-card="${h.id}">${esc(SC.ja(h.id))} (${SC.costOf(s, op, h)})</span>` : '<span class="cback"></span>').join('');
    const hand = P.hand.map(h => {
      const c = SC.card(h.id), cost = SC.costOf(s, me, h);
      const can = my && SC.canPlay(s, me, h);
      const cc = cost > c.c ? 'up' : cost < c.c ? 'down' : '';
      const st = c.t === 'U' ? `<span class="atk">${c.a}</span><span class="hp">${c.h}</span>` : c.t === 'W' ? `<span class="atk">${c.a}</span><span>⚡${c.ch}</span>` : '<span class="muted tiny">戦術</span>';
      return `<button class="hcard ${can && settings.hints ? 'can' : ''} ${!can ? 'no' : ''} ${h.rev ? 'rev' : ''} ${ui.sheet && ui.sheet.uid === h.uid ? 'sel' : ''} ${ui.mode && ui.mode.uid === h.uid ? 'sel' : ''}" style="--fc:${fcol(c.f)}" data-h="${h.uid}">
        <span class="cost ${cc}">${cost}</span><span class="hn">${esc(c.ja)}</span><span class="ht">${esc(c.tx)}</span><span class="hs">${st}</span></button>`;
    }).join('');
    const mods = P.modules.map((m, i) => {
      const d = SC.MODS[m.id];
      const cost = d.ct === 'passive' ? 'パッシブ' : d.ct === 'supply' ? `◆${d.c}` : `⚡${d.c}`;
      const can = my && SC.canUseModule(s, me, i);
      return `<button class="mod ${d.ct === 'passive' ? 'passive' : ''} ${m.used ? 'used' : ''} ${can && settings.hints ? 'can' : ''}" data-m="${i}">${esc(d.ja)}<small>${cost}${m.id === 'rend_mod' ? ` (${2 + m.count}dmg)` : ''}</small></button>`;
    }).join('') + `<button class="mod" data-m="-1" title="空きスロット">空き×${3 - P.modules.length}<small>⚡+${3 - P.modules.length}/ターン</small></button>`;

    app.innerHTML = `<div class="game">
      <div class="cbar">${avatarHTML(s, op)}${resHTML(s, op)}<button class="btn sm" id="gmenu">≡</button></div>
      <div class="ohand">${ohand || '<span class="tiny muted">手札なし</span>'}</div>
      <div class="board ${O.board.length ? '' : 'empty'}" data-empty="相手の場">${O.board.map(u => unitHTML(s, u)).join('')}</div>
      <div class="mid"><span class="msg">${msg}</span>
        ${ui.mode ? `${ui.mode.opt ? '<button class="btn sm" id="notgt">対象なし</button>' : ''}<button class="btn sm" id="cancel">やめる</button>` : ''}
        <button class="btn sm" id="logbtn">ログ</button>
        ${my && !ui.mode ? '<button class="btn sm pri" id="endbtn">ターン終了</button>' : ''}</div>
      <div class="board ${P.board.length ? '' : 'empty'}" data-empty="自分の場(手札のカードをタップして出す)">${P.board.map(u => unitHTML(s, u)).join('')}</div>
      <div class="cbar me">${avatarHTML(s, me)}${resHTML(s, me)}<div class="mods">${mods}</div></div>
      <div class="hand">${hand || '<span class="tiny muted" style="margin:auto">手札なし</span>'}</div>
      ${ui.sheet ? sheetHTML(s) : ''}
      ${ui.cover && s.winner === null ? `<div class="cover"><div class="logo" style="font-size:1.6rem">${esc(s.players[s.active].name)} のターン</div><p class="muted">相手に画面が見えないようにしてからタップしてください。</p><button class="btn pri" id="uncover">はじめる</button></div>` : ''}
    </div>`;
    bindGame();
    playFx();
    if (s.winner !== null) return finishGame();
    if (!ui.cover && s.players[s.active].ai) scheduleAI();
  }

  function hintText(s) {
    const p = s.active;
    const acts = SC.legalActions(s);
    const plays = acts.filter(a => a.type === 'play').length, atks = acts.filter(a => a.type === 'attack').length, mods = acts.filter(a => a.type === 'module').length;
    if (!plays && !atks && !mods) return 'できることがありません。「ターン終了」を押しましょう';
    const parts = [];
    if (plays) parts.push('光る手札をプレイ');
    if (atks) parts.push('光るユニットで攻撃');
    if (mods) parts.push('モジュール使用');
    return parts.join('・') + 'ができます';
  }

  function sheetHTML(s) {
    const sh = ui.sheet, me = ui.viewer;
    let body = '', btns = '';
    if (sh.type === 'hand') {
      const pl = s.players[me]; const h = pl.hand.find(x => x.uid === sh.uid); if (!h) { ui.sheet = null; return ''; }
      const c = SC.card(h.id), cost = SC.costOf(s, me, h);
      body = cardHTML(c) + kwExplain(c.tx);
      const can = isHumanTurn() && SC.canPlay(s, me, h);
      if (can) {
        btns += `<button class="btn pri grow" data-play="${h.uid}" data-en="">プレイ(${cost})</button>`;
        (c.energize || []).forEach((e, i) => { btns += `<button class="btn warn grow" data-play="${h.uid}" data-en="${i}" ${pl.energy < e.n ? 'disabled' : ''}>ENERGIZE ${e.n}:${esc(e.tx)}</button>`; });
      } else btns += `<span class="muted small grow">${!isHumanTurn() ? '自分のターンではありません' : cost > pl.supply ? `サプライが足りません(必要${cost})` : c.t === 'U' && pl.board.length >= SC.BOARD_MAX ? '場がいっぱいです' : '今は使えません(対象がない等)'}</span>`;
    } else if (sh.type === 'unit') {
      const ch = SC.getChar(s, sh.ref); if (!ch) { ui.sheet = null; return ''; }
      if (ch.cmd) {
        const pl = ch.o;
        body = `<div class="panel"><b>${esc(pl.name)}</b> ・ ${D.factions[pl.faction].ja}<div class="small">体力 ${pl.hp}/${pl.maxHp} ・ サイキックチャージ ${pl.psy} ・ エネルギー ${pl.energy}<br>攻撃力 ${SC.atkOf(s, sh.ref)}${pl.weapon ? ` ・ ウェポン ${esc(SC.ja(pl.weapon.id))}(${pl.weapon.a}/${pl.weapon.ch})` : ''}<br>デッキ「${esc(pl.deckName || '')}」</div></div>`;
      } else {
        const u = ch.o, c = SC.card(u.id);
        const extra = [];
        if (u.nulled) extra.push('NULLIFY 済み(テキスト無効)');
        if (u.mut) extra.push(`変異回数 ${u.mut}`);
        if (u.xt.length) extra.push('付与された能力: ' + u.xt.map(x => ({ revenge: 'REVENGE', fury: 'FURY' }[x.trig] || x.trig)).join('、'));
        const kwNow = Object.keys(u.kw).concat(u.mods.map(m => m.k)).filter(k => k !== 'ATK' && k !== 'NOREVEAL');
        body = cardHTML(c) + `<div class="small panel">現在:攻撃力 ${SC.atkOf(s, u.uid)} / 体力 ${u.hp}/${u.maxHp}${kwNow.length ? '<br>キーワード: ' + kwify(Array.from(new Set(kwNow)).join(' ')) : ''}${extra.length ? '<br>' + esc(extra.join(' / ')) : ''}${u.ctrlBack !== undefined ? '<br>一時的にコントロールされている' : ''}</div>` + kwExplain(c.tx + ' ' + kwNow.join(' '));
      }
    } else if (sh.type === 'module') {
      const pl = s.players[me]; const m = pl.modules[sh.i];
      if (sh.i < 0 || !m) body = `<div class="panel small">空きモジュールスロット1つにつき、ターン開始時にエネルギー+1。</div>`;
      else {
        const d = SC.MODS[m.id];
        body = moduleHTML(d);
        if (d.ct !== 'passive') {
          const can = isHumanTurn() && SC.canUseModule(s, me, sh.i);
          btns = can ? `<button class="btn pri grow" data-usemod="${sh.i}">使用</button>` : `<span class="muted small grow">${m.used ? 'このターンは使用済み' : '今は使えません(コストか対象が不足)'}</span>`;
        }
      }
    }
    return `<div class="sheet">${body}<div class="row">${btns}<button class="btn" id="closesheet">閉じる</button></div></div>`;
  }

  function bindGame() {
    const root = app.querySelector('.game');
    root.addEventListener('click', onGameClick);
    let pressT = null;
    root.addEventListener('pointerdown', e => {
      const el = e.target.closest('[data-ref]'); if (!el) return;
      pressT = setTimeout(() => { pressT = 'fired'; ui.sheet = { type: 'unit', ref: refOf(el.dataset.ref) }; ui.mode = null; ui.targets = []; renderGame(); }, 480);
    });
    const clear = () => { if (pressT && pressT !== 'fired') clearTimeout(pressT); setTimeout(() => { pressT = null; }, 0); };
    root.addEventListener('pointerup', clear); root.addEventListener('pointercancel', clear); root.addEventListener('pointerleave', clear);
    root.addEventListener('click', e => { if (pressT === 'fired') { e.stopImmediatePropagation(); } }, true);
  }
  const refOf = v => (v[0] === 'c' ? v : +v);

  function onGameClick(e) {
    const s = game;
    const t = e.target;
    if (t.closest('#uncover')) { ui.cover = false; renderGame(); return; }
    if (t.closest('#gmenu')) return gameMenu();
    if (t.closest('#logbtn')) return showLog();
    if (t.closest('#closesheet')) { ui.sheet = null; renderGame(); return; }
    if (t.closest('#cancel')) { ui.mode = null; ui.targets = []; renderGame(); return; }
    if (t.closest('#endbtn')) {
      if (settings.confirmEnd && SC.legalActions(s).some(a => a.type !== 'end')) {
        openModal(`<p>まだ行動できます。ターンを終了しますか?</p><div class="row"><button class="btn pri grow" id="yesend">終了する</button><button class="btn grow" data-close>戻る</button></div>`);
        document.getElementById('yesend').onclick = () => { closeModal(); doAct({ type: 'end' }); };
        return;
      }
      return doAct({ type: 'end' });
    }
    if (t.closest('#notgt')) { const m = ui.mode; ui.mode = null; ui.targets = []; return doAct({ type: 'play', uid: m.uid, T: null, en: m.en }); }
    const pb = t.closest('[data-play]');
    if (pb) return startPlay(+pb.dataset.play, pb.dataset.en === '' ? null : +pb.dataset.en);
    const um = t.closest('[data-usemod]');
    if (um) return startModule(+um.dataset.usemod);
    const cd = t.closest('[data-card]');
    if (cd && cd.classList.contains('crev')) return showCard(cd.dataset.card);
    const hc = t.closest('[data-h]');
    if (hc) { ui.mode = null; ui.targets = []; ui.sheet = { type: 'hand', uid: +hc.dataset.h }; renderGame(); return; }
    const md = t.closest('[data-m]');
    if (md) { ui.mode = null; ui.targets = []; ui.sheet = { type: 'module', i: +md.dataset.m }; renderGame(); return; }
    const rf = t.closest('[data-ref]');
    if (rf) {
      const ref = refOf(rf.dataset.ref);
      if (ui.mode) {
        if (ui.targets.includes(ref)) {
          const m = ui.mode; ui.mode = null; ui.targets = [];
          if (m.kind === 'attack') return doAct({ type: 'attack', from: m.from, to: ref });
          if (m.kind === 'play') return doAct({ type: 'play', uid: m.uid, T: ref, en: m.en });
          if (m.kind === 'module') return doAct({ type: 'module', i: m.i, T: ref });
        }
        if (ui.mode.kind === 'attack' && ui.mode.from === ref) { ui.mode = null; ui.targets = []; renderGame(); return; }
      }
      const ch = SC.getChar(s, ref);
      if (ch && ch.p === ui.viewer && isHumanTurn() && SC.canAttack(s, ref)) {
        ui.sheet = null; ui.mode = { kind: 'attack', from: ref }; ui.targets = SC.attackTargets(s, ref); renderGame(); return;
      }
      ui.mode = null; ui.targets = []; ui.sheet = { type: 'unit', ref }; renderGame(); return;
    }
    if (ui.mode && !t.closest('.mid')) { ui.mode = null; ui.targets = []; renderGame(); }
  }

  function startPlay(uid, en) {
    const s = game, p = ui.viewer;
    const h = s.players[p].hand.find(x => x.uid === uid); if (!h) return;
    const c = SC.card(h.id);
    ui.sheet = null;
    if (c.tg) {
      const vt = SC.validTargets(s, p, c.tg, c.t === 'T' ? 'tactic' : 'ability');
      if (vt.length) { ui.mode = { kind: 'play', uid, en, opt: !!c.tg.opt }; ui.targets = vt; renderGame(); return; }
    }
    doAct({ type: 'play', uid, T: null, en });
  }
  function startModule(i) {
    const s = game, p = ui.viewer;
    const d = SC.MODS[s.players[p].modules[i].id];
    ui.sheet = null;
    if (d.tg) { ui.mode = { kind: 'module', i }; ui.targets = SC.validTargets(s, p, d.tg, 'module'); renderGame(); return; }
    doAct({ type: 'module', i });
  }

  function doAct(a) {
    const prevActive = game.active;
    const ok = SC.act(game, a);
    if (!ok) { toast('その行動はできません'); renderGame(); return; }
    autosave();
    renderGame();
    if (a.type === 'end' && game.winner === null && game.mode === 'ai' && game.active !== prevActive) banner('相手のターン');
  }

  function banner(t) { const b = document.createElement('div'); b.className = 'banner'; b.textContent = t; document.body.appendChild(b); setTimeout(() => b.remove(), 1300); }

  function playFx() {
    const list = game.fx || [];
    game.fx = [];
    let delay = 0;
    for (const f of list) {
      if (f.k === 'play' && game.players[f.p].ai) { const c = SC.card(f.id); toast(`相手が「${c.ja}」をプレイ`, 1800); continue; }
      if (f.k === 'module' && game.players[f.p].ai) { toast(`相手がモジュール「${SC.MODS[f.id].ja}」を使用`, 1800); continue; }
      if (f.ref === undefined) continue;
      const el = app.querySelector(`[data-ref="${f.ref}"]`);
      if (!el) continue;
      const r = el.getBoundingClientRect();
      const txt = f.k === 'dmg' ? '-' + f.n : f.k === 'heal' ? '+' + f.n : f.k === 'shield' ? '盾' : f.k === 'soak' ? '吸収' : f.k === 'immune' ? '無敵' : f.k === 'mutate' ? '変異' : f.k === 'cypher' ? 'CYPHER!' : f.k === 'psy' ? '✧' : null;
      if (f.k === 'dmg') el.classList.add('shake');
      if (!txt) continue;
      const fl = document.createElement('div');
      fl.className = 'float ' + (f.k === 'dmg' ? 'dmg' : f.k === 'heal' ? 'heal' : 'info');
      fl.textContent = txt; fl.style.left = (r.left + r.width / 2) + 'px'; fl.style.top = (r.top + r.height / 3) + 'px';
      fl.style.animationDelay = delay + 'ms'; delay += 60;
      document.body.appendChild(fl); setTimeout(() => fl.remove(), 1200 + delay);
    }
  }

  function scheduleAI() {
    clearTimeout(ui.aiTimer);
    const ms = { fast: 250, normal: 700, slow: 1200 }[settings.speed] || 700;
    ui.aiTimer = setTimeout(() => {
      if (!game || game.winner !== null || !game.players[game.active].ai || location.hash !== '#game') return;
      const a = SC_AI.chooseAction(game, game.diff);
      const ok = SC.act(game, a);
      if (!ok) SC.act(game, { type: 'end' });
      autosave();
      if (a.type === 'end' && game.winner === null) banner('あなたのターン');
      renderGame();
    }, ms);
  }

  function showLog() {
    const l = game.log.slice(-120).reverse().map(x => `<div>${esc(x.m)}</div>`).join('');
    openModal(`<h3>ログ</h3><div class="logbox">${l}</div><div class="row" style="margin-top:.6rem"><button class="btn grow" data-close>閉じる</button></div>`);
  }
  function gameMenu() {
    openModal(`<h3>メニュー</h3><div class="dk-list">
      <button class="btn" data-close>対戦に戻る</button>
      <button class="btn" id="m-save">スロットに保存</button>
      <button class="btn" id="m-rules">遊び方を見る</button>
      <button class="btn" id="m-home">ホームへ(自動保存済み)</button>
      <button class="btn bad" id="m-resign">降参する</button></div>`);
    document.getElementById('m-home').onclick = () => { closeModal(); location.hash = 'home'; };
    document.getElementById('m-rules').onclick = () => { openModal(G.rules + '<button class="btn" data-close style="width:100%">閉じる</button>'); };
    document.getElementById('m-save').onclick = () => slotPicker(true);
    document.getElementById('m-resign').onclick = () => {
      closeModal();
      game.winner = game.mode === 'ai' ? 1 : 1 - game.active;
      game.log.push({ t: game.turn, m: `${game.players[game.mode === 'ai' ? 0 : game.active].name} が降参した。` });
      renderGame();
    };
  }

  // ---------- 対戦終了・戦績 ----------
  function finishGame() {
    const s = game;
    if (!s.recorded) {
      s.recorded = true;
      LS.del('auto');
      const rec = (p) => {
        const pl = s.players[p], op = s.players[1 - p];
        return { d: Date.now(), mode: s.mode, me: pl.faction, opp: op.faction, deck: pl.deckName, oppDeck: op.deckName, name: pl.name,
          res: s.winner === -1 ? 'D' : s.winner === p ? 'W' : 'L', turns: s.turn, dmg: pl.st.dmg, taken: pl.st.taken, played: pl.st.played, kills: pl.st.kills, cards: pl.st.cards, hp: Math.max(0, pl.hp) };
      };
      stats.games.push(rec(0));
      if (s.mode === 'hot') stats.games.push(rec(1));
      if (stats.games.length > 500) stats.games = stats.games.slice(-500);
      saveStats();
    }
    const me = s.mode === 'ai' ? 0 : s.winner === -1 ? 0 : s.winner;
    const title = s.winner === -1 ? '引き分け' : s.mode === 'ai' ? (s.winner === 0 ? '勝利!' : '敗北…') : `${esc(s.players[s.winner].name)} の勝利!`;
    const pl = s.players[me];
    setTimeout(() => {
      openModal(`<h2 style="text-align:center">${title}</h2>
        <div class="kpis"><div class="kpi"><b>${s.turn}</b><span>ターン</span></div><div class="kpi"><b>${pl.st.dmg}</b><span>与ダメージ</span></div><div class="kpi"><b>${pl.st.kills}</b><span>撃破</span></div><div class="kpi"><b>${pl.st.played}</b><span>プレイ枚数</span></div></div>
        <div class="row" style="margin-top:1rem"><button class="btn pri grow" id="again">もう一度</button><button class="btn grow" id="tostats">戦績</button><button class="btn grow" id="tohome">ホーム</button></div>`);
      document.getElementById('again').onclick = () => { closeModal(); location.hash = 'setup/' + (s.mode === 'hot' ? 'hot' : 'ai'); };
      document.getElementById('tostats').onclick = () => { closeModal(); game = null; location.hash = 'stats'; };
      document.getElementById('tohome').onclick = () => { closeModal(); game = null; location.hash = 'home'; };
    }, 700);
  }

  // ---------- セーブスロット ----------
  function slotPicker(saving) {
    const rows = [1, 2, 3].map(i => {
      const g = LS.get('slot' + i, null);
      const meta = g ? `${new Date(g.savedAt || 0).toLocaleString()} ・ ターン${g.turn} ・ ${D.factions[g.players[0].faction].ja} vs ${D.factions[g.players[1].faction].ja}` : '空き';
      return `<div class="dk-item"><div class="grow"><b>スロット${i}</b><div class="small muted">${meta}</div></div>
        ${saving ? `<button class="btn sm pri" data-slot-save="${i}">保存</button>` : ''}${g ? `<button class="btn sm" data-slot-load="${i}">読込</button><button class="btn sm bad" data-slot-del="${i}">削除</button>` : ''}</div>`;
    }).join('');
    openModal(`<h3>セーブスロット</h3><div class="dk-list">${rows}</div><button class="btn" data-close style="width:100%;margin-top:.6rem">閉じる</button>`);
    modal.querySelectorAll('[data-slot-save]').forEach(b => b.onclick = () => { const g = JSON.parse(JSON.stringify(game)); g.savedAt = Date.now(); g.fx = []; if (LS.set('slot' + b.dataset.slotSave, g)) toast('保存しました'); else toast('保存に失敗しました(容量不足?)'); slotPicker(saving); });
    modal.querySelectorAll('[data-slot-load]').forEach(b => b.onclick = () => { const g = LS.get('slot' + b.dataset.slotLoad, null); if (!g) return; game = g; game.recorded = false; resetUI(); closeModal(); if (location.hash === '#game') renderGame(); else location.hash = 'game'; toast('読み込みました'); });
    modal.querySelectorAll('[data-slot-del]').forEach(b => b.onclick = () => { LS.del('slot' + b.dataset.slotDel); slotPicker(saving); });
  }

  // ---------- デッキ一覧 ----------
  function viewDecks() {
    const item = d => `<div class="dk-item" style="--fc:${fcol(d.faction)}"><div class="grow"><b>${esc(d.name)}</b><div class="small muted">${D.factions[d.faction].ja} ・ ${d.cards.length}枚 ・ モジュール ${1 + (d.modules || []).length}</div></div>
      ${d.starter ? `<button class="btn sm" data-copy="${d.id}">複製して編集</button>` : `<button class="btn sm" data-go="deck/${d.id}">編集</button>`}</div>`;
    app.innerHTML = topbar('デッキ') + `<div class="view">
      <div class="panel"><h3>新しいデッキ</h3><div class="row"><select id="nf" class="grow">${FKEYS.map(f => `<option value="${f}">${D.factions[f].ja}</option>`).join('')}</select><button class="btn pri" id="mk">空から作成</button><button class="btn" id="mkr">おまかせ作成</button></div></div>
      <h3>マイデッキ</h3><div class="dk-list">${decks.length ? decks.map(item).join('') : '<p class="muted small">まだありません。スターターを複製するか、新しく作成してください。</p>'}</div>
      <h3>スターターデッキ</h3><div class="dk-list">${FKEYS.map(f => item(starterDeck(f))).join('')}</div></div>`;
    const create = (d) => { d.id = 'd' + Date.now().toString(36); decks.push(d); saveDecks(); location.hash = 'deck/' + d.id; };
    document.getElementById('mk').onclick = () => { const f = document.getElementById('nf').value; create({ name: `新しい${D.factions[f].ja}デッキ`, faction: f, cards: [], modules: [] }); };
    document.getElementById('mkr').onclick = () => { const f = document.getElementById('nf').value; const r = SC.randomDeck(f, 26); create({ name: `おまかせ${D.factions[f].ja}`, faction: f, cards: r.cards, modules: r.modules }); };
    app.querySelectorAll('[data-copy]').forEach(b => b.onclick = () => { const s = starterDeck(b.dataset.copy.replace('starter_', '')); create({ name: s.name + '(改)', faction: s.faction, cards: s.cards.slice(), modules: [] }); });
  }

  function viewDeck(id) {
    const d = decks.find(x => x.id === id); if (!d) { location.hash = 'decks'; return; }
    let q = '';
    const draw = () => {
      const cnt = {}; d.cards.forEach(x => { cnt[x] = (cnt[x] || 0) + 1; });
      const errs = SC.validateDeck(d);
      const curve = [0, 0, 0, 0, 0, 0, 0, 0]; d.cards.forEach(x => { curve[Math.min(7, SC.card(x).c)]++; });
      const mx = Math.max(1, ...curve);
      const pool = SC.poolFor(d.faction).filter(c => !q || (c.ja + c.n + c.tx).toLowerCase().includes(q.toLowerCase())).sort((a, b) => (a.f === 'NEU') - (b.f === 'NEU') || a.c - b.c || a.ja.localeCompare(b.ja));
      const mp = SC.modulePoolFor(d.faction);
      const hp = d.cards.length + (d.modules || []).reduce((a, m) => a + (SC.MODS[m].hp || 0), 0) + (SC.MODS[SC.BASE_MODULE[d.faction]].hp || 0);
      app.innerHTML = topbar('デッキ編集', 'decks') + `<div class="view">
        <div class="row" style="margin-top:.6rem"><input id="dn" class="grow" value="${esc(d.name)}" maxlength="30"><span class="chip" style="border-color:${fcol(d.faction)}">${D.factions[d.faction].ja}</span></div>
        <div class="sticky-sum"><div class="row"><b>${d.cards.length}</b>/25〜40枚 ・ 初期体力 ${Math.max(10, hp)}<span class="grow"></span><button class="btn sm pri" id="test">この デッキで対戦</button></div>
          <div class="curve" style="margin:.4rem 0 1.2rem">${curve.map((n, i) => `<div style="height:${n / mx * 100}%"><span>${i === 7 ? '7+' : i}</span></div>`).join('')}</div>
          ${errs.length ? `<div class="small" style="color:var(--bad)">${errs.map(esc).join('<br>')}</div>` : '<div class="small" style="color:var(--good)">使用可能なデッキです</div>'}</div>
        <div class="panel"><h3>モジュール(基本能力+追加2つまで)</h3>
          <div class="small">基本:<b>${esc(SC.MODS[SC.BASE_MODULE[d.faction]].ja)}</b>(固定)。追加しないほどエネルギーが速く貯まります。</div>
          ${mp.map(m => `<label class="pool-row"><input type="checkbox" data-mod="${m.id}" ${(d.modules || []).includes(m.id) ? 'checked' : ''}><span class="nm">${esc(m.ja)} <span class="tiny muted">${m.ct === 'passive' ? 'パッシブ' : '⚡' + m.c}${m.hp ? ' 体力' + (m.hp > 0 ? '+' : '') + m.hp : ''}</span></span>${srcChip(m.src)}<button class="btn sm" data-minfo="${m.id}">i</button></label>`).join('')}</div>
        <input id="q" placeholder="カード名・効果で絞り込み" value="${esc(q)}" style="width:100%">
        <div>${pool.map(c => `<div class="pool-row"><span class="cost">${c.c}</span><span class="nm" data-info="${c.id}"><b style="color:${fcol(c.f)}">${D.factions[c.f].glyph}</b> ${esc(c.ja)} <span class="tiny muted">${c.t === 'U' ? c.a + '/' + c.h : D.types[c.t]}${c.r === 'P' ? ' ・パラゴン' : ''}</span></span>${srcChip(c.src)}
          <button class="btn sm" data-dec="${c.id}" ${cnt[c.id] ? '' : 'disabled'}>−</button><span class="cnt">${cnt[c.id] || 0}</span><button class="btn sm" data-inc="${c.id}" ${(cnt[c.id] || 0) >= (c.r === 'P' ? 1 : 2) || d.cards.length >= 40 ? 'disabled' : ''}>+</button></div>`).join('')}</div>
        <div class="row" style="margin-top:1rem"><button class="btn bad" id="del">デッキを削除</button></div></div>`;
      const save = () => { saveDecks(); };
      document.getElementById('dn').onchange = e => { d.name = e.target.value || '名無しデッキ'; save(); };
      const qi = document.getElementById('q'); qi.oninput = e => { q = e.target.value; draw(); const n = document.getElementById('q'); n.focus(); n.setSelectionRange(q.length, q.length); };
      app.querySelectorAll('[data-inc]').forEach(b => b.onclick = () => { d.cards.push(b.dataset.inc); save(); keepScroll(draw); });
      app.querySelectorAll('[data-dec]').forEach(b => b.onclick = () => { const i = d.cards.indexOf(b.dataset.dec); if (i >= 0) d.cards.splice(i, 1); save(); keepScroll(draw); });
      app.querySelectorAll('[data-info]').forEach(b => b.onclick = () => showCard(b.dataset.info));
      app.querySelectorAll('[data-minfo]').forEach(b => b.onclick = e => { e.preventDefault(); openModal(moduleHTML(SC.MODS[b.dataset.minfo]) + '<button class="btn" data-close style="width:100%">閉じる</button>'); });
      app.querySelectorAll('[data-mod]').forEach(b => b.onchange = () => {
        d.modules = d.modules || [];
        if (b.checked) { if (d.modules.length >= 2) { b.checked = false; toast('追加モジュールは2つまでです'); return; } d.modules.push(b.dataset.mod); }
        else d.modules = d.modules.filter(m => m !== b.dataset.mod);
        save(); keepScroll(draw);
      });
      document.getElementById('del').onclick = () => ask('このデッキを削除しますか?', '削除する', () => { decks = decks.filter(x => x !== d); saveDecks(); location.hash = 'decks'; });
      document.getElementById('test').onclick = () => { if (errs.length) { toast('デッキが条件を満たしていません'); return; } LS.set('lastDeck', d.id); location.hash = 'setup/ai'; };
    };
    draw();
  }
  function keepScroll(f) { const y = window.scrollY; f(); window.scrollTo(0, y); }

  // ---------- 図鑑 ----------
  function viewCards(tab) {
    tab = tab || 'cards';
    const st = viewCards.st = viewCards.st || { f: '', t: '', s: '', r: '', q: '', c: '' };
    const tabs = `<div class="tabs">${[['cards', 'カード'], ['modules', 'モジュール'], ['keywords', 'キーワード']].map(([k, l]) => `<button class="btn sm ${tab === k ? 'on' : ''}" data-go="cards/${k}">${l}</button>`).join('')}</div>`;
    if (tab === 'keywords') {
      app.innerHTML = topbar('カード図鑑') + `<div class="view">${tabs}<div class="tbl-wrap"><table><tr><th>キーワード</th><th>意味</th><th>確認</th></tr>${Object.keys(D.keywords).map(k => `<tr><td><b class="kw">${k}</b><br><span class="small muted">${D.keywords[k][0]}</span></td><td>${esc(D.keywords[k][1])}</td><td>${srcChip(D.keywords[k][2])}</td></tr>`).join('')}</table></div></div>`;
      return;
    }
    if (tab === 'modules') {
      const list = D.modules.filter(m => !m.hidden && (!st.f || m.f === st.f || (st.f === 'NEU' && m.f === 'ANY')));
      app.innerHTML = topbar('カード図鑑') + `<div class="view">${tabs}<div class="filters"><select id="ff"><option value="">全勢力</option>${FKEYS.concat(['NEU']).map(f => `<option value="${f}" ${st.f === f ? 'selected' : ''}>${f === 'NEU' ? '共通' : D.factions[f].ja}</option>`).join('')}</select></div>
        <p class="small muted">${list.length}種</p><div class="cat-grid">${list.map(moduleHTML).join('')}</div></div>`;
      document.getElementById('ff').onchange = e => { st.f = e.target.value; viewCards('modules'); };
      return;
    }
    const list = D.cards.filter(c => (!st.f || c.f === st.f) && (!st.t || c.t === st.t) && (!st.s || c.src === st.s) && (!st.r || c.r === st.r) &&
      (st.c === '' || (st.c === '7' ? c.c >= 7 : c.c === +st.c)) && (!st.q || (c.ja + c.n + c.tx + (c.en || '')).toLowerCase().includes(st.q.toLowerCase())))
      .sort((a, b) => FKEYS.concat(['NEU']).indexOf(a.f) - FKEYS.concat(['NEU']).indexOf(b.f) || a.c - b.c);
    const cnt = { A: 0, B: 0, C: 0, D: 0 }; D.cards.forEach(c => cnt[c.src]++);
    app.innerHTML = topbar('カード図鑑') + `<div class="view">${tabs}
      <div class="small muted">全${D.cards.length}枚(うち生成カード${D.cards.filter(c => c.token).length}枚)・ ${['A', 'B', 'C', 'D'].map(k => `${srcChip(k)} ${cnt[k]}`).join(' ')}</div>
      <div class="filters">
        <select id="ff"><option value="">全勢力</option>${FKEYS.concat(['NEU']).map(f => `<option value="${f}" ${st.f === f ? 'selected' : ''}>${D.factions[f].ja}</option>`).join('')}</select>
        <select id="ft"><option value="">全種別</option>${Object.keys(D.types).map(k => `<option value="${k}" ${st.t === k ? 'selected' : ''}>${D.types[k]}</option>`).join('')}</select>
        <select id="fc"><option value="">全コスト</option>${[0, 1, 2, 3, 4, 5, 6, 7].map(n => `<option value="${n}" ${st.c === String(n) ? 'selected' : ''}>${n === 7 ? '7以上' : n}</option>`).join('')}</select>
        <select id="fr"><option value="">全レアリティ</option>${Object.keys(D.rarity).map(k => `<option value="${k}" ${st.r === k ? 'selected' : ''}>${D.rarity[k]}</option>`).join('')}</select>
        <select id="fs"><option value="">全確認度</option>${Object.keys(D.src).map(k => `<option value="${k}" ${st.s === k ? 'selected' : ''}>${D.src[k][0]}</option>`).join('')}</select>
        <input id="fq" placeholder="検索(日本語/英語/効果)" value="${esc(st.q)}">
      </div>
      <p class="small muted">${list.length}枚表示。カードをタップで詳細と出典メモ。</p>
      <div class="cat-grid">${list.map(c => cardHTML(c)).join('')}</div></div>`;
    const bind = (id, k) => { document.getElementById(id).onchange = e => { st[k] = e.target.value; viewCards('cards'); }; };
    bind('ff', 'f'); bind('ft', 't'); bind('fc', 'c'); bind('fr', 'r'); bind('fs', 's');
    const fq = document.getElementById('fq');
    fq.oninput = e => { st.q = e.target.value; clearTimeout(viewCards._t); viewCards._t = setTimeout(() => { viewCards('cards'); const n = document.getElementById('fq'); n.focus(); n.setSelectionRange(st.q.length, st.q.length); }, 250); };
    app.querySelectorAll('.cat-grid [data-card]').forEach(el => el.onclick = () => showCard(el.dataset.card));
  }

  // ---------- ガイド ----------
  function viewGuide(tab) {
    tab = tab || 'ANN';
    const tabs = `<div class="tabs">${FKEYS.concat(['NEU']).map(f => `<button class="btn sm ${tab === f ? 'on' : ''}" data-go="guide/${f}">${D.factions[f].ja}</button>`).join('')}<button class="btn sm ${tab === 'rules' ? 'on' : ''}" data-go="guide/rules">遊び方</button><button class="btn sm ${tab === 'notes' ? 'on' : ''}" data-go="guide/notes">調査ノート</button></div>`;
    let body = '';
    if (tab === 'rules') body = `<div class="guide panel">${G.rules}</div><div class="panel guide"><h2>キーワード</h2><p class="small">図鑑の「キーワード」タブに全定義があります。カードの黄色い単語をタップしても意味が表示されます。</p><button class="btn" data-go="cards/keywords">キーワード一覧へ</button></div>`;
    else if (tab === 'notes') {
      const cnt = { A: 0, B: 0, C: 0, D: 0 }, mc = { A: 0, B: 0, C: 0, D: 0 };
      D.cards.forEach(c => cnt[c.src]++); D.modules.filter(m => !m.hidden).forEach(m => mc[m.src]++);
      body = `<div class="guide panel"><h2>調査ノート</h2>
        <p>Star Crusade CCG(Steam AppID 415270、開発 ZiMAD、2015年12月オープンβ〜2017年9月 v1.3.12)は配信終了しており、公式のカードデータベースは残っていません。原作の総カード数は約590枚(コア400枚超+ヴラクシアン約60+キャンペーン2+シャドウ・オブ・ザ・カウンシル119)と推定されます。</p>
        <p><b>この再現版のカード ${D.cards.length}枚の内訳</b>:${['A', 'B', 'C', 'D'].map(k => `${srcChip(k)} ${cnt[k]}枚`).join(' ・ ')}<br><b>モジュール ${D.modules.filter(m => !m.hidden).length}種</b>:${['A', 'B', 'C', 'D'].map(k => `${srcChip(k)} ${mc[k]}`).join(' ・ ')}</p>
        <ul><li><b>検証済み</b>:公式告知・パッチノート・開発者投稿で文面とコスト/攻撃/体力を確認したもの。プレビュー版文面は実装版と違う可能性があります。</li>
        <li><b>一部確認</b>:パッチノートのバランス変更(例「体力6→5」)などで一部の数値や文面だけ分かっているもの。残りは同勢力の傾向から再構成。</li>
        <li><b>名称のみ</b>:デッキリストや議論スレッドで名前と勢力の文脈だけ分かるもの。効果はキーワード体系に沿って遊べるよう設計。</li>
        <li><b>補完</b>:資料で一切確認できない仮称カード。ヴラクシアンの枚数不足を補うため3枚だけ追加。</li></ul>
        <h3>完全版に近づけるには</h3>
        <p>ファン DB「starcrusadeops.com」(2017年5月公開)の Wayback Machine アーカイブ、Android 版 APK(v1.3.12)内のデータ、YouTube のプレイ動画(カード画面の目視)が残された一次資料です。今回の作成環境からはアーカイブと Steam に接続できなかったため、提供された調査資料 v0.9 と検索結果の抜粋を基にしています。</p>
        <h3>主な出典</h3><ul class="small">${G.sources.map(([t, u]) => `<li><a href="${u}" target="_blank" rel="noopener">${esc(t)}</a></li>`).join('')}</ul></div>`;
    } else {
      const f = D.factions[tab], g = G.factions[tab];
      const cards = D.cards.filter(c => c.f === tab && !c.token);
      const sc = { A: 0, B: 0, C: 0, D: 0 }; cards.forEach(c => sc[c.src]++);
      const mods = D.modules.filter(m => m.f === tab && !m.hidden);
      body = `<div class="guide panel"><div class="fac-h"><div class="avatar" style="--fc:${f.color}">${f.glyph}</div><div><h2 style="margin:0">${f.ja}<span class="muted small"> ${f.en}</span></h2><div class="small muted">指揮官:${esc(f.commander)}</div></div></div>
        <p>${esc(f.blurb)}</p>
        ${tab !== 'NEU' ? `<h3>指揮官能力(基本モジュール)</h3><p><b>${esc(g.ability[0])}</b> ${srcChip(g.ability[2])}<br>${kwify(g.ability[1])}</p><p class="small muted">${esc(g.ability[3])}</p>` : ''}
        <h3>固有のメカニクス</h3><div class="row">${g.mech.map(m => `<span class="chip">${kwify(m)}</span>`).join('')}</div>
        <h3>資料で確認できた固有カード・モジュール</h3><ul>${g.verified.map(v => `<li>${kwify(v)}</li>`).join('')}</ul>
        <h3>効果の利用方法(想定)</h3><ul>${g.use.map(v => `<li>${kwify(v)}</li>`).join('')}</ul>
        ${g.weak ? `<h3>弱点・注意点</h3><p>${esc(g.weak)}</p>` : ''}
        <h3>収録状況</h3><p class="small">カード${cards.length}枚:${['A', 'B', 'C', 'D'].map(k => `${srcChip(k)} ${sc[k]}`).join(' ')}${mods.length ? ` ・ 勢力モジュール${mods.length}種` : ''}</p>
        <div class="row"><button class="btn" id="g-cards">この勢力のカードを見る</button>${tab !== 'NEU' ? `<button class="btn pri" id="g-play">スターターで対戦</button>` : ''}</div></div>`;
    }
    app.innerHTML = topbar('勢力ガイド') + `<div class="view">${tabs}${body}</div>`;
    const gc = document.getElementById('g-cards'); if (gc) gc.onclick = () => { viewCards.st = { f: tab, t: '', s: '', r: '', q: '', c: '' }; location.hash = 'cards/cards'; };
    const gp = document.getElementById('g-play'); if (gp) gp.onclick = () => { LS.set('lastDeck', 'starter_' + tab); location.hash = 'setup/ai'; };
  }

  // ---------- 戦績 ----------
  function viewStats() {
    const gs = stats.games;
    const ai = gs.filter(g => g.mode === 'ai');
    const W = ai.filter(g => g.res === 'W').length, L = ai.filter(g => g.res === 'L').length;
    const pct = (a, b) => b ? Math.round(a / b * 100) : 0;
    const avg = (arr, k) => arr.length ? (arr.reduce((a, g) => a + (g[k] || 0), 0) / arr.length).toFixed(1) : '-';
    let streak = 0; for (let i = ai.length - 1; i >= 0 && ai[i].res === 'W'; i--) streak++;
    let best = 0, cur = 0; for (const g of ai) { cur = g.res === 'W' ? cur + 1 : 0; best = Math.max(best, cur); }
    const byF = (key, arr) => FKEYS.map(f => { const x = arr.filter(g => g[key] === f); const w = x.filter(g => g.res === 'W').length; return { f, n: x.length, w }; }).filter(r => r.n);
    const ftable = (rows, label) => rows.length ? `<div class="tbl-wrap"><table><tr><th>${label}</th><th>試合</th><th>勝</th><th>勝率</th><th style="width:35%"></th></tr>${rows.map(r => `<tr><td><span style="color:${fcol(r.f)}">${D.factions[r.f].glyph}</span> ${D.factions[r.f].ja}</td><td>${r.n}</td><td>${r.w}</td><td>${pct(r.w, r.n)}%</td><td><div class="bar"><i style="width:${pct(r.w, r.n)}%"></i></div></td></tr>`).join('')}</table></div>` : '<p class="muted small">記録なし</p>';
    const cc = {}; for (const g of gs) for (const k in (g.cards || {})) cc[k] = (cc[k] || 0) + g.cards[k];
    const top = Object.keys(cc).sort((a, b) => cc[b] - cc[a]).slice(0, 10);
    const maxc = top.length ? cc[top[0]] : 1;
    const recent = gs.slice(-25).reverse();
    app.innerHTML = topbar('戦績') + `<div class="view">
      <h3>CPU 対戦</h3>
      <div class="kpis"><div class="kpi"><b>${ai.length}</b><span>試合</span></div><div class="kpi"><b class="res-W">${W}</b><span>勝ち</span></div><div class="kpi"><b class="res-L">${L}</b><span>負け</span></div><div class="kpi"><b>${pct(W, ai.length)}%</b><span>勝率</span></div>
        <div class="kpi"><b>${streak}</b><span>現在の連勝</span></div><div class="kpi"><b>${best}</b><span>最高連勝</span></div><div class="kpi"><b>${avg(ai, 'turns')}</b><span>平均ターン</span></div><div class="kpi"><b>${avg(ai, 'dmg')}</b><span>平均与ダメージ</span></div></div>
      <div class="panel"><h3>使用勢力別</h3>${ftable(byF('me', ai), '使用勢力')}</div>
      <div class="panel"><h3>相手勢力別</h3>${ftable(byF('opp', ai), '相手勢力')}</div>
      <div class="panel"><h3>2人対戦(勢力別成績)</h3>${ftable(byF('me', gs.filter(g => g.mode === 'hot')), '勢力')}</div>
      <div class="panel"><h3>よく使ったカード</h3>${top.length ? top.map(id => `<div class="row small" style="margin:.2rem 0"><span style="width:45%">${esc(SC.ja(id))}</span><div class="bar grow"><i style="width:${cc[id] / maxc * 100}%;background:var(--acc)"></i></div><span>${cc[id]}</span></div>`).join('') : '<p class="muted small">記録なし</p>'}</div>
      <div class="panel"><h3>最近の対戦</h3><div class="tbl-wrap"><table><tr><th>日時</th><th>結果</th><th>対戦</th><th>T</th><th>与/被</th></tr>
        ${recent.map(g => `<tr><td class="small">${new Date(g.d).toLocaleString([], { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</td><td class="res-${g.res}">${{ W: '勝', L: '負', D: '分' }[g.res]}</td><td class="small">${g.mode === 'hot' ? '👥' + esc(g.name) + ' ' : ''}${D.factions[g.me].ja} vs ${D.factions[g.opp].ja}</td><td>${g.turns}</td><td class="small">${g.dmg}/${g.taken}</td></tr>`).join('') || '<tr><td colspan="5" class="muted">記録なし</td></tr>'}</table></div></div>
      <div class="row"><button class="btn" id="exp">戦績を書き出し(JSON)</button><label class="btn">読み込み<input type="file" id="imp" accept=".json,application/json" hidden></label><button class="btn bad" id="rst">リセット</button></div></div>`;
    document.getElementById('exp').onclick = () => download('starcrusade-stats.json', stats);
    document.getElementById('imp').onchange = e => readJSON(e, d => { if (d && Array.isArray(d.games)) { stats = d; saveStats(); viewStats(); toast('読み込みました'); } else toast('形式が違います'); });
    document.getElementById('rst').onclick = () => ask('戦績をすべて消去しますか?', '消去する', () => { stats = { games: [] }; saveStats(); viewStats(); });
  }
  function readJSON(e, cb) { const f = e.target.files[0]; if (!f) return; const r = new FileReader(); r.onload = () => { try { cb(JSON.parse(r.result)); } catch (x) { toast('読み込めませんでした'); } }; r.readAsText(f); }

  // ---------- 設定 ----------
  function viewSettings() {
    app.innerHTML = topbar('設定・セーブ') + `<div class="view">
      <div class="panel"><h3>文字サイズ</h3><div class="row"><span class="small">小</span><input type="range" id="fs" min="0.8" max="1.6" step="0.05" value="${settings.font}" class="grow"><span>大</span><b id="fsv">${Math.round(settings.font * 100)}%</b></div>
        <p class="small muted">プレビュー:カードやボタンの文字はこの大きさになります。</p></div>
      <div class="panel"><h3>表示・操作</h3>
        <div class="pool-row"><span class="nm">テーマ</span><select id="th"><option value="dark" ${settings.theme === 'dark' ? 'selected' : ''}>ダーク</option><option value="light" ${settings.theme === 'light' ? 'selected' : ''}>ライト</option></select></div>
        <div class="pool-row"><span class="nm">CPU の行動速度</span><select id="sp"><option value="fast" ${settings.speed === 'fast' ? 'selected' : ''}>速い</option><option value="normal" ${settings.speed === 'normal' ? 'selected' : ''}>ふつう</option><option value="slow" ${settings.speed === 'slow' ? 'selected' : ''}>ゆっくり</option></select></div>
        <label class="pool-row"><span class="nm">操作ヒント(使えるカード・ユニットを光らせる)</span><input type="checkbox" id="hn" ${settings.hints ? 'checked' : ''}></label>
        <label class="pool-row"><span class="nm">行動が残っている時にターン終了を確認</span><input type="checkbox" id="ce" ${settings.confirmEnd ? 'checked' : ''}></label>
        <div class="pool-row"><span class="nm">プレイヤー名</span><input id="pn" value="${esc(settings.name)}" maxlength="16" style="width:9rem"></div></div>
      <div class="panel"><h3>セーブ</h3><p class="small muted">対戦中は1手ごとに自動保存され、ホームの「続きから」で再開できます。手動セーブは3スロット。</p>
        <div class="row"><button class="btn" id="slots">セーブスロットを開く</button></div></div>
      <div class="panel"><h3>データのバックアップ</h3><p class="small muted">デッキ・戦績・設定・セーブをまとめて書き出し/読み込みできます(機種変更や別ブラウザへの移行用)。</p>
        <div class="row"><button class="btn" id="bk">すべて書き出し</button><label class="btn">読み込み<input type="file" id="rs" accept=".json,application/json" hidden></label><button class="btn bad" id="wipe">全データ消去</button></div></div>
      <p class="small muted">非公式ファン再現版。Star Crusade は ZiMAD の作品です。</p></div>`;
    const fs = document.getElementById('fs');
    fs.oninput = () => { settings.font = +fs.value; document.getElementById('fsv').textContent = Math.round(settings.font * 100) + '%'; applySettings(); saveSettings(); };
    document.getElementById('th').onchange = e => { settings.theme = e.target.value; applySettings(); saveSettings(); };
    document.getElementById('sp').onchange = e => { settings.speed = e.target.value; saveSettings(); };
    document.getElementById('hn').onchange = e => { settings.hints = e.target.checked; saveSettings(); };
    document.getElementById('ce').onchange = e => { settings.confirmEnd = e.target.checked; saveSettings(); };
    document.getElementById('pn').onchange = e => { settings.name = e.target.value || 'あなた'; saveSettings(); };
    document.getElementById('slots').onclick = () => slotPicker(false);
    document.getElementById('bk').onclick = () => download('starcrusade-backup.json', { settings, decks, stats, auto: LS.get('auto', null), slot1: LS.get('slot1', null), slot2: LS.get('slot2', null), slot3: LS.get('slot3', null) });
    document.getElementById('rs').onchange = e => readJSON(e, d => {
      if (!d || !d.settings) { toast('形式が違います'); return; }
      Object.assign(settings, d.settings); saveSettings(); applySettings();
      decks = d.decks || []; saveDecks(); stats = d.stats || { games: [] }; saveStats();
      ['auto', 'slot1', 'slot2', 'slot3'].forEach(k => { if (d[k]) LS.set(k, d[k]); });
      toast('復元しました'); viewSettings();
    });
    document.getElementById('wipe').onclick = () => {
      ask('デッキ・戦績・セーブ・設定をすべて消去しますか?', 'すべて消去', () => {
      ['settings', 'decks', 'stats', 'auto', 'slot1', 'slot2', 'slot3', 'lastDeck'].forEach(LS.del);
      location.reload();
      });
    };
  }

  route();
  if ('serviceWorker' in navigator && location.protocol.startsWith('http')) {
    navigator.serviceWorker.register('sw.js').catch(() => { /* オフライン対応は任意 */ });
  }
})();
