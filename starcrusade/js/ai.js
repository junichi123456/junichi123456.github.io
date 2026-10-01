/* Star Crusade CCG 再現版 — CPU 対戦相手
 * 各行動を状態の複製に適用して評価し、最も評価が上がる行動を選ぶ貪欲法。
 */
(function () {
  const SC = window.SC;
  const clone = (o) => JSON.parse(JSON.stringify(o));

  function unitVal(s, u) {
    const a = SC.atkOf(s, u.uid);
    let v = 1 + a * 1.0 + u.hp * 0.75;
    if (SC.has(u, 'SCREEN')) v += 1;
    if (SC.has(u, 'SHIELD')) v += 1.5;
    if (SC.has(u, 'ARMORED')) v += 2;
    if (SC.has(u, 'CLOAK')) v += 1;
    if (SC.has(u, 'ASSAULT')) v += a * 0.5;
    if (SC.has(u, 'SOAK')) v += SC.has(u, 'SOAK') * 1.2;
    if (SC.has(u, 'PACIFIST')) v -= a * 0.8;
    if (SC.trigs(u, 'endTurn').length || SC.trigs(u, 'startTurn').length) v += 1.5;
    if (u.ctrlBack !== undefined) v *= 0.5;
    return v;
  }

  function evaluate(s, p) {
    if (s.winner === p) return 1e6;
    if (s.winner !== null) return -1e6;
    const me = s.players[p], op = s.players[1 - p];
    let v = (me.hp + me.psy) * 1.0 - (op.hp + op.psy) * 1.15;
    for (const u of me.board) v += unitVal(s, u);
    for (const u of op.board) v -= unitVal(s, u) * 1.1;
    v += me.hand.length * 0.6;
    if (me.weapon) v += me.weapon.a * me.weapon.ch * 0.5;
    v += me.energy * 0.12 + me.cyphers.length * 2;
    // 次の相手ターンの脅威
    let threat = 0;
    for (const u of op.board) if (!SC.has(u, 'PACIFIST')) threat += SC.atkOf(s, u.uid) * (SC.has(u, 'ASSAULT') ? 2 : 1);
    const screen = me.board.some(u => SC.has(u, 'SCREEN'));
    if (!screen && threat >= me.hp + me.psy) v -= 200;
    else if (threat >= me.hp + me.psy - 3) v -= 10;
    if (op.hp <= 0) v += 1e5;
    return v;
  }

  function chooseAction(s, diff) {
    const p = s.active;
    const base = evaluate(s, p);
    const acts = SC.legalActions(s).filter(a => a.type !== 'end');
    const scored = [];
    for (const a of acts) {
      const c = clone(s);
      if (!SC.act(c, a)) continue;
      let sc = evaluate(c, p);
      // 手札を使うこと自体にわずかなボーナス(サプライを余らせない)
      if (a.type === 'play') sc += 0.3;
      if (a.type === 'module') sc += 0.2;
      scored.push({ a, sc });
    }
    const good = scored.filter(x => x.sc > base + 0.05).sort((x, y) => y.sc - x.sc);
    if (!good.length) return { type: 'end' };
    if (diff === 'easy') {
      if (Math.random() < 0.15) return { type: 'end' };
      return good[Math.floor(Math.random() * Math.min(good.length, 4))].a;
    }
    return good[0].a;
  }

  window.SC_AI = { chooseAction, evaluate };
})();
