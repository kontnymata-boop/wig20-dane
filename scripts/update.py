#!/usr/bin/env python3
"""
RadMat · Sygnały GPW – robot pobierający notowania (GitHub Actions)

Dla wszystkich spółek rynku głównego GPW (scripts/companies.json) oraz NewConnect i nowych debiutów
(lista z wyszukiwarki akcji Yahoo, odświeżana raz na dobę) pobiera z Yahoo Finance:
  • notowania dzienne – pełne 10 lat raz dziennie (po sesji), w ciągu sesji tylko ostatnie dni,
  • notowania godzinowe – do wykresów Ichimoku 1 godz.
Wynik trafia do folderu STORE (gałąź `data` repozytorium):
  d/<SKRÓT>.json, h/<SKRÓT>.json, universe.json
Dodatkowo zapisuje data/wig20.json (zgodność ze starszą wersją aplikacji WIG20 Sygnały).
Podsumowanie sygnałów (summary.json) liczy osobno scripts/summary.js – tym samym silnikiem co aplikacja.
"""
import argparse
import json
import os
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

try:
    from curl_cffi import requests as http
    IMPERSONATE = True
except ImportError:
    import requests as http
    IMPERSONATE = False

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WAW = ZoneInfo("Europe/Warsaw")
KEEP_DAYS = 2600          # ok. 10 lat sesji
INDEX = {"t": "WIG20", "n": "WIG20 (wg ETF Beta WIG20TR)", "y": "WIG20.WA",
         "alts": ["^WIG20", "WIG20TR.WA", "ETFBW20TR.WA"], "w20": False, "idx": True}
LEGACY = [  # skróty dla starej wersji aplikacji (data/wig20.json, klucze = symbole Yahoo)
    ("WIG20", "WIG20.WA"), ("PKO", "PKO.WA"), ("PKN", "PKN.WA"), ("KGH", "KGH.WA"), ("ALE", "ALE.WA"),
    ("PEO", "PEO.WA"), ("PZU", "PZU.WA"), ("EBP", "EBP.WA"), ("LPP", "LPP.WA"), ("CDR", "CDR.WA"),
    ("DNP", "DNP.WA"), ("MBK", "MBK.WA"), ("ZAB", "ZAB.WA"), ("ALR", "ALR.WA"), ("KTY", "KTY.WA"),
    ("TPE", "TPE.WA"), ("PGE", "PGE.WA"), ("BDX", "BDX.WA"), ("KRU", "KRU.WA"), ("PCO", "PCO.WA"),
    ("MDV", "MDV.WA"), ("BFT", "BFT.WA"), ("XTB", "XTB.WA"),
]

_local = threading.local()


def session():
    s = getattr(_local, "s", None)
    if s is None:
        if IMPERSONATE:
            s = http.Session(impersonate="chrome")
        else:
            s = http.Session()
            s.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130.0 Safari/537.36"
        _local.s = s
    return s


def r4(x):
    return None if x is None else round(float(x), 4)


def compact(res):
    q = ((res.get("indicators") or {}).get("quote") or [{}])[0]
    m = res.get("meta") or {}
    out = {"meta": {"off": m.get("gmtoffset"), "time": m.get("regularMarketTime"), "price": m.get("regularMarketPrice"),
                    "name": m.get("longName") or m.get("shortName")},
           "t": [], "o": [], "h": [], "l": [], "c": [], "v": []}
    ts = res.get("timestamp") or []
    closes = q.get("close") or []
    for i, t in enumerate(ts):
        c = closes[i] if i < len(closes) else None
        if c is None:
            continue
        out["t"].append(int(t))
        for k, src in (("o", "open"), ("h", "high"), ("l", "low")):
            arr = q.get(src) or []
            out[k].append(r4(arr[i]) if i < len(arr) else None)
        out["c"].append(r4(c))
        vol = q.get("volume") or []
        out["v"].append(int(vol[i]) if i < len(vol) and vol[i] else 0)
    if not out["t"]:
        raise LookupError("pusta lista notowań")
    return out


def chart(sym, rng, interval):
    last = None
    for host in ("query1", "query2"):
        url = (f"https://{host}.finance.yahoo.com/v8/finance/chart/{sym}"
               f"?range={rng}&interval={interval}&includePrePost=false")
        for attempt in range(3):
            try:
                r = session().get(url, timeout=30)
                if r.status_code == 429:
                    last = "HTTP 429 (limit Yahoo)"
                    time.sleep(4 + attempt * 6 + random.random() * 3)
                    continue
                j = r.json()
                res = (j.get("chart") or {}).get("result")
                if not res:
                    err = (j.get("chart") or {}).get("error") or {}
                    raise LookupError(err.get("description") or err.get("code") or f"HTTP {r.status_code}")
                return compact(res[0])
            except LookupError:
                raise
            except Exception as e:
                last = f"{type(e).__name__}: {e}"
                time.sleep(1.5 + attempt * 2)
    raise RuntimeError(last or "nieznany błąd")


def yahoo_search(name):
    url = f"https://query2.finance.yahoo.com/v1/finance/search?q={name}&quotesCount=10&newsCount=0"
    r = session().get(url, timeout=20)
    key = name.lower().split()[0][:6]
    for q in (r.json().get("quotes") or []):
        s = q.get("symbol") or ""
        nm = (q.get("longname") or q.get("shortname") or "").lower()
        if s.endswith(".WA") and key in nm.replace("ó", "o"):
            return s, q.get("longname") or q.get("shortname") or name
    return None, None


def yahoo_crumb():
    s = session()
    c = getattr(_local, "crumb", None)
    if c:
        return c
    try:
        s.get("https://fc.yahoo.com", timeout=20)
    except Exception:
        pass
    c = s.get("https://query1.finance.yahoo.com/v1/test/getcrumb", timeout=20).text.strip()
    if not c or "<" in c or len(c) > 40:
        raise RuntimeError("brak crumb")
    _local.crumb = c
    return c


def clean_name(n):
    import re
    n = (n or "").strip()
    n = n.replace("Spólka", "Spółka").replace("Spolka", "Spółka")
    for _ in range(2):
        n = re.sub(r"[\s,]+(S\.?\s?A\.?|SA|Spółka Akcyjna|SE|N\.V\.|AB \(publ\)|AS|plc|Inc\.?|w restrukturyzacji|w upadłości)$", "", n, flags=re.I).strip()
    return n


def yahoo_wse_list():
    import re
    """Wszystkie akcje notowane w Warszawie wg wyszukiwarki Yahoo: rynek główny (XWAR) i NewConnect (XNCO)."""
    out, off = [], 0
    while off < 3000:
        body = {"offset": off, "size": 250, "sortField": "ticker", "sortType": "ASC", "quoteType": "EQUITY",
                "query": {"operator": "and", "operands": [{"operator": "eq", "operands": ["exchange", "WSE"]}]},
                "userId": "", "userIdType": "guid"}
        r = session().post("https://query2.finance.yahoo.com/v1/finance/screener",
                           params={"crumb": yahoo_crumb(), "lang": "en-US", "region": "US", "formatted": "false"}, json=body, timeout=30)
        r.raise_for_status()
        res = ((r.json().get("finance") or {}).get("result") or [{}])[0]
        q = res.get("quotes") or []
        for x in q:
            sym, sn = x.get("symbol") or "", x.get("shortName") or ""
            mk = "XNCO" if "XNCO" in sn else "XWAR" if "XWAR" in sn else None
            nm = (x.get("longName") or "")
            if mk and sym.endswith(".WA") and len(sym) <= 8 and not re.search(r"fundusz|fizan|\bfiz\b|certyfikat", nm, re.I):  # bez funduszy (FIZ)
                out.append({"t": sym[:-3], "y": sym, "n": clean_name(x.get("longName") or sym[:-3]), "nc": mk == "XNCO"})
        if len(q) < 250:
            break
        off += 250
    return out


def day_key(t, off, intraday):
    if intraday:
        return t
    return datetime.fromtimestamp(t + (off if off is not None else 3600), tz=timezone.utc).strftime("%Y-%m-%d")


def merge(old, new, intraday=False, keep=KEEP_DAYS):
    """Łączy stare i nowe notowania (nowsze nadpisują ten sam dzień / tę samą godzinę)."""
    off = (new.get("meta") or {}).get("off")
    rows = {}
    for src in (old, new):
        o = (src.get("meta") or {}).get("off", off)
        for i, t in enumerate(src["t"]):
            rows[day_key(t, o, intraday)] = (t, src["o"][i], src["h"][i], src["l"][i], src["c"][i], src["v"][i])
    keys = sorted(rows)[-keep:]
    out = {"meta": dict(old.get("meta") or {}, **{k: v for k, v in (new.get("meta") or {}).items() if v is not None}),
           "t": [], "o": [], "h": [], "l": [], "c": [], "v": []}
    for k in keys:
        t, o, h, l, c, v = rows[k]
        out["t"].append(t); out["o"].append(o); out["h"].append(h); out["l"].append(l); out["c"].append(c); out["v"].append(v)
    return out


def fetch_full(sym, min_len, old=None):
    """Pełna historia dzienna. Yahoo dla części małych spółek przy zakresie 10 lat zwraca dane urwane albo pojedynczy
    punkt – wtedy próbuję innych zakresów, a na końcu łączę najdłuższy wynik (lub poprzednie dane) z ostatnim miesiącem."""
    empty = {"meta": {}, "t": [], "o": [], "h": [], "l": [], "c": [], "v": []}

    def good(x):
        return x is not None and len(x["t"]) >= min_len and age_days(x) <= 21

    got = []
    for i, rng in enumerate(("10y", "max", "5y", "2y", "1y")):
        try:
            x = chart(sym, rng, "1d")
        except LookupError:
            if i == 0 and not old:
                raise
            continue
        except Exception:
            continue
        x = merge(empty, x)            # przycięcie do KEEP_DAYS sesji
        if good(x):
            return x
        got.append(x)
    if old and old.get("t"):
        got.append(old)
    if not got:
        raise LookupError("brak notowań")
    base = max(got, key=lambda x: len(x["t"]))
    try:
        base = merge(base, chart(sym, "1mo", "1d"))
    except Exception:
        pass
    if len(base["t"]) < min_len:
        raise LookupError(f"za krótka historia ({len(base['t'])})")
    return base


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def dump(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)


def age_days(x):
    if not x or not x.get("t"):
        return 9999
    return (time.time() - x["t"][-1]) / 86400


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default=os.path.join(ROOT, "store"))
    ap.add_argument("--full", action="store_true", help="pełne pobranie 10 lat dla wszystkich")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--limit", type=int, default=0, help="(test) tylko N pierwszych spółek")
    args = ap.parse_args()
    store = args.store
    os.makedirs(os.path.join(store, "d"), exist_ok=True)
    os.makedirs(os.path.join(store, "h"), exist_ok=True)

    now_w = datetime.now(WAW)
    prev = load(os.path.join(store, "universe.json")) or {}
    last_full = prev.get("lastFull") or ""
    after_close = now_w.weekday() < 5 and (now_w.hour > 17 or (now_w.hour == 17 and now_w.minute >= 30))
    full = args.full or not prev or (after_close and last_full[:10] != now_w.strftime("%Y-%m-%d"))
    if not full and last_full:
        try:
            full = (now_w - datetime.fromisoformat(last_full)).total_seconds() > 30 * 3600
        except ValueError:
            full = True
    print(f"Tryb: {'PEŁNY (10 lat)' if full else 'SZYBKI (ostatnie dni)'} · {now_w:%Y-%m-%d %H:%M} czasu polskiego")

    cfg = load(os.path.join(ROOT, "scripts", "companies.json"))["items"]
    # debiuty, których oznaczenie ustala wyszukiwarka Yahoo (wynik zapamiętywany)
    resolved = dict(prev.get("resolved") or {})
    for name in (load(os.path.join(ROOT, "scripts", "resolve.json")) or {}).get("names", []):
        if name in resolved:
            continue
        try:
            sym, lname = yahoo_search(name)
            resolved[name] = {"y": sym, "n": lname} if sym else None
            print(f"Wyszukiwanie „{name}”: {sym or 'brak'}")
        except Exception as e:
            print(f"Wyszukiwanie „{name}” nieudane: {e}")
    known = {c["y"] for c in cfg} | {a for c in cfg for a in c.get("alts", [])}
    for name, r in resolved.items():
        if r and r.get("y") and r["y"] not in known:
            cfg.append({"t": r["y"][:-3], "y": r["y"], "n": name, "alts": [], "w20": False})
            known.add(r["y"])
    # NewConnect i nowe spółki rynku głównego – lista z wyszukiwarki akcji Yahoo (raz na dobę, w trybie pełnym)
    disc = prev.get("disc") or []
    if full or not disc:
        try:
            fresh = yahoo_wse_list()
            if len(fresh) > 300:
                disc = fresh
            print(f"Lista Yahoo: {len(fresh)} akcji (NewConnect: {sum(1 for d in fresh if d['nc'])})")
        except Exception as e:
            print(f"Lista Yahoo nieudana ({e}) – używam zapamiętanej ({len(disc)})")
    nc_set = {d["t"] for d in disc if d.get("nc")}
    have_t = {c["t"] for c in cfg}
    added = 0
    import re
    disc = [d for d in disc if len(d["y"]) <= 8 and not re.search(r"fundusz|fizan|\bfiz\b|certyfikat", d.get("n") or "", re.I)]
    for d in disc:
        if d["y"] in known or d["t"] in have_t:
            continue
        cfg.append({"t": d["t"], "y": d["y"], "n": d["n"], "alts": [], "w20": False, "nc": bool(d.get("nc"))})
        known.add(d["y"]); have_t.add(d["t"]); added += 1
    for c in cfg:
        if c["t"] in nc_set:
            c["nc"] = True
    print(f"Spółki: {len(cfg)} (dodane z listy Yahoo: {added}, NewConnect: {sum(1 for c in cfg if c.get('nc'))})")
    entities = [INDEX] + cfg
    if args.limit:
        entities = entities[: args.limit]

    def work(e):
        t = e["t"]
        path = os.path.join(store, "d", f"{t}.json")
        old = load(path)
        info = {"t": t, "n": e["n"], "y": e["y"], "w20": bool(e.get("w20")), "idx": bool(e.get("idx")), "nc": bool(e.get("nc"))}
        min_len = 300 if e.get("idx") else 30
        try:
            if old and not full and old.get("sym") and age_days(old) < 20:
                data = merge(old, chart(old["sym"], "5d", "1d"))
                data["sym"] = old["sym"]
            else:
                data, errs = None, []
                for sym in [e["y"]] + list(e.get("alts", [])):
                    try:
                        data = fetch_full(sym, min_len, old if (old and old.get("sym") == sym) else None)
                        data["sym"] = sym
                        break
                    except Exception as ex:
                        errs.append(f"{sym}: {ex}")
                if data is None:
                    raise LookupError("; ".join(errs))
            if age_days(data) > 21:
                raise LookupError("brak notowań od ponad 3 tygodni (spółka wycofana?)")
            dump(path, data)
            info.update(ok=True, sym=data["sym"], bars=len(data["t"]),
                        last=day_key(data["t"][-1], (data.get("meta") or {}).get("off"), False))
        except Exception as ex:
            info.update(ok=False, err=str(ex)[:200])
            if old and age_days(old) < 21:      # chwilowy błąd Yahoo – zostaw poprzednie dane
                info.update(ok=True, sym=old.get("sym"), stale=True)
            elif os.path.exists(path):
                os.remove(path)
        time.sleep(random.random() * 0.3)
        return info

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        infos = list(pool.map(work, entities))
    ok = [i for i in infos if i.get("ok")]
    print(f"Dzienne: {len(ok)}/{len(infos)} OK w {time.time() - t0:.0f} s")
    for i in infos:
        if not i.get("ok"):
            print(f"  BRAK {i['t']:6} {i.get('err', '')[:120]}")

    # godzinowe: tryb pełny – wszystkie; szybki – WIG20 i najpłynniejsze
    def turnover(t):
        x = load(os.path.join(store, "d", f"{t}.json"))
        if not x:
            return 0
        c, v = x["c"][-20:], x["v"][-20:]
        return sum(a * b for a, b in zip(c, v)) / max(1, len(c))

    cand = [i for i in ok if not i.get("idx")]
    if not full:
        cand.sort(key=lambda i: (not i.get("w20"), -turnover(i["t"])))
        cand = cand[:60]

    def work_h(i):
        path = os.path.join(store, "h", f"{i['t']}.json")
        old = load(path)
        try:
            if old and not full and age_days(old) < 5:
                data = merge(old, chart(i["sym"], "5d", "60m"), intraday=True, keep=700)
            else:
                data = chart(i["sym"], "3mo", "60m")
            data["sym"] = i["sym"]
            dump(path, dict(data, ok=True))
        except Exception as ex:
            return f"{i['t']}: {ex}"
        time.sleep(random.random() * 0.3)
        return None

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        herr = [x for x in pool.map(work_h, cand) if x]
    print(f"Godzinowe: {len(cand) - len(herr)}/{len(cand)} OK w {time.time() - t0:.0f} s")

    if len([i for i in ok if not i.get("idx")]) < min(50, max(1, len(entities) // 2)):
        print("Za mało pobranych spółek – nie nadpisuję listy.")
        sys.exit(1)
    uni = {"ok": True, "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "lastFull": now_w.isoformat(timespec="minutes") if full else last_full,
           "mode": "full" if full else "quick", "resolved": resolved, "disc": disc, "items": infos}
    dump(os.path.join(store, "universe.json"), uni)

    # zgodność ze starszą wersją aplikacji (WIG20 Sygnały 1.3)
    legacy = {}
    for t, key in LEGACY:
        x = load(os.path.join(store, "d", f"{t}.json"))
        if x:
            legacy[key] = dict(x, ticker=t)
            hx = load(os.path.join(store, "h", f"{t}.json"))
            if hx:
                dump(os.path.join(ROOT, "data", "h", f"{key}.json"), hx)
    dump(os.path.join(ROOT, "data", "wig20.json"), {"ok": True, "app": "wig20-sygnaly", "source": "Yahoo Finance",
                                                     "updated": uni["updated"], "data": legacy, "errors": {}})
    print("Zapisano.")


if __name__ == "__main__":
    main()
