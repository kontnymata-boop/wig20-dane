#!/usr/bin/env node
/*
  RadMat · Sygnały GPW – podsumowanie sygnałów dla listy spółek
  Liczy sygnały (3 horyzonty) i oceny Ichimoku dla każdej spółki tym samym silnikiem,
  którego używa aplikacja (kod między znacznikami ENGINE w index.html).
  Użycie: node scripts/summary.js <folder_store>
*/
'use strict';
const fs = require('fs');
const path = require('path');

const store = process.argv[2] || path.join(__dirname, '..', 'store');
const html = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8');
const code = html.split('/*ENGINE-START*/')[1].split('/*ENGINE-END*/')[0];
const E = new Function(code + '; return {PROFILES, analyze, ichiFor, resample, compactToBars, sliceBars, entryStudy, EW};')();

function warsawNow() {
  const p = {};
  new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Warsaw', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false, weekday: 'short' })
    .formatToParts(new Date()).forEach(x => p[x.type] = x.value);
  return { date: `${p.year}-${p.month}-${p.day}`, min: (parseInt(p.hour, 10) % 24) * 60 + parseInt(p.minute, 10), wd: p.weekday };
}
const r = (x, d = 2) => (x == null || !isFinite(x)) ? null : Math.round(x * 10 ** d) / 10 ** d;
const sig = x => (x == null || !isFinite(x)) ? null : Number(x.toPrecision(5));

const uni = JSON.parse(fs.readFileSync(path.join(store, 'universe.json'), 'utf8'));
const w = warsawNow();
const items = [];
let fails = 0;
const ewT = { krotki: [], sredni: [], dlugi: [] };   // zakończone transakcje metody „Moment wejścia” ze wszystkich spółek
for (const u of uni.items) {
  if (!u.ok) continue;
  const f = path.join(store, 'd', u.t + '.json');
  if (!fs.existsSync(f)) continue;
  try {
    const x = JSON.parse(fs.readFileSync(f, 'utf8'));
    let B = E.compactToBars(x);
    const n = B.d.length;
    let live = null;
    if (n > 1 && B.d[n - 1] === w.date && !['Sat', 'Sun'].includes(w.wd) && w.min < 17 * 60 + 15) {
      live = { p: u.idx ? r(B.c[n - 1], 2) : sig(B.c[n - 1]), ch: r(B.c[n - 1] / B.c[n - 2] - 1, 4) };
      const o = {}; for (const k of Object.keys(B)) o[k] = B[k].slice(0, -1); B = o;
    }
    const Bs = E.sliceBars(B, 1300);
    const L = Bs.c.length - 1;
    const c20 = Bs.c.slice(-20), v20 = Bs.v.slice(-20);
    const obr = c20.reduce((s, c, i) => s + c * v20[i], 0) / Math.max(1, c20.length);
    const it = {
      t: u.t, n: u.n, y: x.sym || u.y, w20: !!u.w20, idx: !!u.idx, nc: !!u.nc, d: Bs.d[L], c: u.idx ? r(Bs.c[L], 2) : sig(Bs.c[L]),
      ch: L > 0 ? r(Bs.c[L] / Bs.c[L - 1] - 1, 4) : null, obr: Math.round(obr), live,
      sp: Bs.c.slice(-60).map(sig), s: {}, ichi: {},
      ix: u.ix && u.ix.length ? u.ix : undefined, grp: u.grp || undefined, nm: u.nm || undefined,
      y1: L >= 250 ? r(Bs.c[L] / Bs.c[L - 250] - 1, 4) : undefined,
      h52: L >= 20 ? r(Bs.c[L] / Math.max(...Bs.h.slice(-250)) - 1, 4) : null,
      m3: L >= 63 ? r(Bs.c[L] / Bs.c[L - 63] - 1, 4) : null, atr: null
    };
    // wskaźniki do wyszukiwania tanich spółek z rodzącym się wzrostem („złote strzały”)
    const mean = a => { const z = a.filter(v => v != null && isFinite(v)); return z.length ? z.reduce((s, v) => s + v, 0) / z.length : null; };
    if (L >= 60) {
      const v5 = mean(Bs.v.slice(-5)), v50 = mean(Bs.v.slice(-55, -5));
      it.vr = v5 != null && v50 ? r(v5 / v50, 2) : null;                       // wolumen: 5 ostatnich sesji / 50 wcześniejszych
      it.m1 = r(Bs.c[L] / Bs.c[L - 21] - 1, 4);                                 // zmiana z ok. miesiąca
      it.l52 = r(Bs.c[L] / Math.min(...Bs.c.slice(-250)) - 1, 4);               // ile nad najniższym zamknięciem z roku
      if (L >= 130) {
        const prevMax = Math.max(...Bs.c.slice(-130, -5)), recentMax = Math.max(...Bs.c.slice(-5));
        it.brk = recentMax > prevMax ? 1 : 0;                                    // nowy szczyt 6-miesięczny w ostatnim tygodniu
      }
      it.nz = Bs.v.slice(-20).filter(v => !v).length;                            // sesje bez obrotu w ostatnich 20
    }
    // „zamrożone” notowania: kolejne ostatnie sesje z tym samym kursem i zerowym obrotem
    // (zawieszony obrót, brak transakcji albo Yahoo przestało aktualizować dane)
    if (!u.idx) {
      let fz = 0;
      for (let i = L; i > 0 && Bs.c[i] === Bs.c[i - 1] && !Bs.v[i]; i--) fz++;
      if (fz >= 3) { it.fz = fz; it.fzd = Bs.d[L - fz + 1]; }
    }
    // dywidendy: suma z 12 miesięcy, stopa, ostatnie wypłaty i zapowiedziany dzień odcięcia
    const dvAll = Array.isArray(x.dv) ? x.dv.filter(a => Array.isArray(a) && a[1] > 0) : [];
    let nx = null;
    try {
      const ff0 = path.join(store, 'f', u.t + '.json');
      if (fs.existsSync(ff0)) { const F0 = JSON.parse(fs.readFileSync(ff0, 'utf8')); const dvf = F0.div || {}; if (dvf.ex && dvf.ex > w.date) nx = { d: dvf.ex, p: dvf.pay || null, a: null }; }
    } catch (e) { /* brak danych */ }
    const fut = dvAll.filter(a => a[0] > w.date), past = dvAll.filter(a => a[0] <= w.date);
    if (fut.length) nx = { d: fut[0][0], a: sig(fut[0][1]), p: nx && nx.d === fut[0][0] ? nx.p : null };
    if (past.length || nx) {
      const yAgo = new Date(Date.parse(w.date + 'T12:00:00Z') - 365 * 864e5).toISOString().slice(0, 10);
      const ttm = past.filter(a => a[0] > yAgo).reduce((s, a) => s + a[1], 0);
      it.dv = { a: ttm ? sig(ttm) : 0, y: ttm && it.c ? r(ttm / it.c, 4) : 0, h: past.slice(-10).reverse().map(a => [a[0], sig(a[1])]) };
      if (nx) it.dv.nx = nx;
    }
    // ocena kondycji finansowej (scripts/fundamentals.py → f/<SKRÓT>.json)
    try {
      const ff = path.join(store, 'f', u.t + '.json');
      if (fs.existsSync(ff)) {
        const F = JSON.parse(fs.readFileSync(ff, 'utf8')), g = F.grade, fm = F.m || {};
        if (g) it.fk = { l: g.lvl, n: g.lbl };
        if (fm.mcap) it.mc = Math.round(fm.mcap);
        if (fm.pe != null && isFinite(fm.pe)) it.pe = r(fm.pe, 1);
        if (fm.pb != null && isFinite(fm.pb)) it.pb = r(fm.pb, 2);
      }
    } catch (e) { /* brak oceny */ }
    // komunikaty spółki i wiadomości (scripts/news.py → n/<SKRÓT>.json): ostatni wpis, liczba z 7 dni, ostatni ważny
    try {
      const fn = path.join(store, 'n', u.t + '.json');
      if (fs.existsSync(fn)) {
        const N = JSON.parse(fs.readFileSync(fn, 'utf8')), arr = Array.isArray(N.items) ? N.items : [];
        if (arr.length) {
          const back = k => { const d = new Date(Date.UTC(+w.date.slice(0, 4), +w.date.slice(5, 7) - 1, +w.date.slice(8, 10) - k)); return d.toISOString().slice(0, 10); };
          const d7 = back(7), d14 = back(14);
          const k = arr.find(x => (x.imp || 0) >= 2 && x.d >= d14);
          it.nw = { d: arr[0].d, n7: arr.filter(x => x.d >= d7).length };
          if (k) it.nw.k = { id: k.id, d: k.d, ti: String(k.ti || '').slice(0, 110), c: k.c, imp: k.imp, dir: k.dir || 0, ty: k.ty };
        }
      }
    } catch (e) { /* brak komunikatów */ }
    for (const p of Object.keys(E.PROFILES)) {
      const A = E.analyze(Bs, E.PROFILES[p], { fee: 0.3 });
      if (!A.ok) { it.s[p] = { st: 'BRAK', msg: A.msg }; continue; }
      const lv = {}; for (const k of Object.keys(A.levels)) lv[k] = sig(A.levels[k]);
      const P = A.P || E.PROFILES[p];   // przy krótkiej historii – profil zastępczy
      // poziomy do oceny potencjału: pozycja otwarta/nowy sygnał – cel i stop systemu liczone od obecnego kursu;
      // bez pozycji – wejście dopiero po wybiciu (max(kurs, poziom wybicia)), cel i stop liczone od tego wejścia
      const ent = A.levels.target != null ? A.close : Math.max(A.close, A.levels.breakout || A.close);
      const tgt = A.levels.target != null ? A.levels.target : ent + P.targetATR * A.atr;
      const stp = A.levels.stop != null ? A.levels.stop : ent - P.stopATR * A.atr;
      const st = A.stats || {};
      if (it.atr == null) it.atr = r(A.atr / A.close, 4);
      it.s[p] = { st: A.status, sc: A.score, rsi: r(A.rsi, 1), tr: A.trend, bear: A.close < A.I.smaT[A.L], lv,
        k: A.info.kind, sd: A.info.sigIdx != null ? Bs.d[A.info.sigIdx] : null, fb: A.fb ? A.fb.to : undefined,
        en: r(ent / A.close - 1, 4), up: r(tgt / ent - 1, 4), dn: r(1 - stp / ent, 4),
        bt: { n: st.n || 0, wr: r(st.winRate, 2), avg: r(st.avgRet, 4) } };
    }
    // „Moment wejścia”: kupno cofnięcia w trendzie wzrostowym (stan na ostatnim zamknięciu + historia transakcji)
    if (!u.idx && !it.fz) {
      try {
        const W = E.entryStudy(B, {});
        if (W.ok) {
          for (const k of Object.keys(ewT)) for (const t of W.trades[k]) ewT[k].push({ t: u.t, nc: !!u.nc, sd: t.sd, xd: t.xd, ret: t.ret, bars: t.bars, tier: t.tier, turn: t.turn, why: t.why });
          const o = {};
          for (const [k, t] of Object.entries(W.open)) o[k] = { sd: t.sd, ed: t.ed, en: sig(t.entry), sl: sig(t.stop), tg: t.tgt != null ? sig(t.tgt) : undefined, b: t.bars, lf: t.left, rt: r(t.ret, 4), x: t.sell ? 1 : undefined, tr: t.tier };
          if (W.st !== 'none' || Object.keys(o).length) {
            it.ew = { st: W.st, r: r(W.rsi, 1), a: sig(W.atr), tr: W.tier, s5: sig(W.s5), tv: Math.round(W.turn),
              lim: W.cur.lim != null ? sig(W.cur.lim) : undefined, px: W.cur.px != null ? sig(W.cur.px) : undefined,
              o: Object.keys(o).length ? o : undefined, h: { krotki: [W.S.krotki.n, W.S.krotki.w], sredni: [W.S.sredni.n, W.S.sredni.w], dlugi: [W.S.dlugi.n, W.S.dlugi.w] } };
          }
        }
      } catch (e) { console.log('Moment wejścia', u.t, e.message); }
    }
    const ic = BB => { const s = E.ichiFor(BB); return s.ok ? { sc: s.score, ic: s.icon, lb: s.label } : null; };
    it.ichi = { D: ic(B), W: ic(E.resample(B, 'W')), M: ic(E.resample(B, 'M')) };
    items.push(it);
  } catch (e) { fails++; console.log('Błąd', u.t, e.message); }
}
items.sort((a, b) => a.t.localeCompare(b.t));
const out = { ok: true, app: 'gpw-sygnaly', updated: uni.updated, mode: uni.mode, dv: (uni.fmt || 1) >= 2, count: items.length, items };
fs.writeFileSync(path.join(store, 'summary.json'), JSON.stringify(out));

// statystyki metody „Moment wejścia” z całej historii (bt.json)
{
  const agg = T => {
    if (!T.length) return { n: 0 };
    const rs = T.map(t => t.ret).sort((a, b) => a - b), w = T.filter(t => t.ret > 0), ls = T.filter(t => t.ret <= 0);
    const sw = w.reduce((s, t) => s + t.ret, 0), sl = -ls.reduce((s, t) => s + t.ret, 0);
    return { n: T.length, win: r(w.length / T.length, 4), avg: r(rs.reduce((s, x) => s + x, 0) / T.length, 4), med: r(rs[Math.floor(rs.length / 2)], 4),
      pf: sl > 0 ? r(sw / sl, 2) : null, bars: r(T.reduce((s, t) => s + t.bars, 0) / T.length, 1), best: r(rs[rs.length - 1], 4), worst: r(rs[0], 4),
      aw: w.length ? r(sw / w.length, 4) : null, al: ls.length ? r(-sl / ls.length, 4) : null };
  };
  const bt = { v: E.EW.v, at: w.date, cfg: E.EW, hz: {} };
  let from = '9999', to = '0000'; const sp = new Set();
  for (const [k, T] of Object.entries(ewT)) {
    T.forEach(t => { if (t.sd < from) from = t.sd; if (t.xd > to) to = t.xd; sp.add(t.t); });
    const yrs = {}; for (const t of T) { const y = t.sd.slice(0, 4); (yrs[y] = yrs[y] || []).push(t); }
    const why = {}; for (const t of T) why[t.why] = (why[t.why] || 0) + 1;
    bt.hz[k] = { all: agg(T), A: agg(T.filter(t => t.tier === 'A')), B: agg(T.filter(t => t.tier === 'B')),
      liq: { l1: agg(T.filter(t => t.turn < 3e5)), l2: agg(T.filter(t => t.turn >= 3e5 && t.turn < 1e6)), l3: agg(T.filter(t => t.turn >= 1e6)) },
      mk: { gpw: agg(T.filter(t => !t.nc)), nc: agg(T.filter(t => t.nc)) },
      yrs: Object.fromEntries(Object.entries(yrs).sort().map(([y, a]) => { const g = agg(a); return [y, [g.n, g.win, g.avg]]; })),
      why: Object.fromEntries(Object.entries(why).map(([x, n]) => [x, r(n / T.length, 3)])),
      last: T.slice().sort((a, b) => b.xd.localeCompare(a.xd) || b.sd.localeCompare(a.sd)).slice(0, 30).map(t => [t.t, t.sd, t.xd, r(t.ret, 4), t.why, t.bars]) };
  }
  bt.from = from; bt.to = to; bt.spolek = sp.size;
  fs.writeFileSync(path.join(store, 'bt.json'), JSON.stringify(bt));
  console.log(`bt.json: ${Object.entries(bt.hz).map(([k, x]) => `${k} ${x.all.n} transakcji, ${Math.round((x.all.win || 0) * 100)}% zyskownych`).join('; ')}`);
}
console.log(`summary.json: ${items.length} spółek, błędy: ${fails}, ${Math.round(fs.statSync(path.join(store, 'summary.json')).size / 1024)} KB`);
