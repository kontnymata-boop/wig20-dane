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
const E = new Function(code + '; return {PROFILES, analyze, ichiFor, resample, compactToBars, sliceBars};')();

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
      live = { p: sig(B.c[n - 1]), ch: r(B.c[n - 1] / B.c[n - 2] - 1, 4) };
      const o = {}; for (const k of Object.keys(B)) o[k] = B[k].slice(0, -1); B = o;
    }
    const Bs = E.sliceBars(B, 1300);
    const L = Bs.c.length - 1;
    const c20 = Bs.c.slice(-20), v20 = Bs.v.slice(-20);
    const obr = c20.reduce((s, c, i) => s + c * v20[i], 0) / Math.max(1, c20.length);
    const it = {
      t: u.t, n: u.n, y: x.sym || u.y, w20: !!u.w20, idx: !!u.idx, d: Bs.d[L], c: sig(Bs.c[L]),
      ch: L > 0 ? r(Bs.c[L] / Bs.c[L - 1] - 1, 4) : null, obr: Math.round(obr), live,
      sp: Bs.c.slice(-60).map(sig), s: {}, ichi: {},
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
    for (const p of Object.keys(E.PROFILES)) {
      const A = E.analyze(Bs, E.PROFILES[p], { fee: 0.3 });
      if (!A.ok) { it.s[p] = { st: 'BRAK', msg: A.msg }; continue; }
      const lv = {}; for (const k of Object.keys(A.levels)) lv[k] = sig(A.levels[k]);
      const P = E.PROFILES[p];
      // poziomy do oceny potencjału: pozycja otwarta/nowy sygnał – cel i stop systemu liczone od obecnego kursu;
      // bez pozycji – wejście dopiero po wybiciu (max(kurs, poziom wybicia)), cel i stop liczone od tego wejścia
      const ent = A.levels.target != null ? A.close : Math.max(A.close, A.levels.breakout || A.close);
      const tgt = A.levels.target != null ? A.levels.target : ent + P.targetATR * A.atr;
      const stp = A.levels.stop != null ? A.levels.stop : ent - P.stopATR * A.atr;
      const st = A.stats || {};
      if (it.atr == null) it.atr = r(A.atr / A.close, 4);
      it.s[p] = { st: A.status, sc: A.score, rsi: r(A.rsi, 1), tr: A.trend, bear: A.close < A.I.smaT[A.L], lv,
        k: A.info.kind, sd: A.info.sigIdx != null ? Bs.d[A.info.sigIdx] : null,
        en: r(ent / A.close - 1, 4), up: r(tgt / ent - 1, 4), dn: r(1 - stp / ent, 4),
        bt: { n: st.n || 0, wr: r(st.winRate, 2), avg: r(st.avgRet, 4) } };
    }
    const ic = BB => { const s = E.ichiFor(BB); return s.ok ? { sc: s.score, ic: s.icon, lb: s.label } : null; };
    it.ichi = { D: ic(B), W: ic(E.resample(B, 'W')), M: ic(E.resample(B, 'M')) };
    items.push(it);
  } catch (e) { fails++; console.log('Błąd', u.t, e.message); }
}
items.sort((a, b) => a.t.localeCompare(b.t));
const out = { ok: true, app: 'gpw-sygnaly', updated: uni.updated, mode: uni.mode, count: items.length, items };
fs.writeFileSync(path.join(store, 'summary.json'), JSON.stringify(out));
console.log(`summary.json: ${items.length} spółek, błędy: ${fails}, ${Math.round(fs.statSync(path.join(store, 'summary.json')).size / 1024)} KB`);
