#!/usr/bin/env python3
"""
RadMat · Sygnały GPW – robot pobierający notowania (GitHub Actions)

Dla wszystkich spółek rynku głównego GPW (scripts/companies.json) oraz NewConnect i nowych debiutów
(lista z wyszukiwarki akcji Yahoo, odświeżana raz na dobę) pobiera z Yahoo Finance:
  • notowania dzienne – pełne 10 lat raz dziennie (po sesji), w ciągu sesji tylko ostatnie dni,
  • notowania godzinowe – do wykresów Ichimoku 1 godz.,
  • dywidendy (kwota na akcję i dzień odcięcia) – zapisywane razem z notowaniami dziennymi jako „dv”.
Wynik trafia do folderu STORE (gałąź `data` repozytorium):
  d/<SKRÓT>.json, h/<SKRÓT>.json, universe.json
Dodatkowo zapisuje data/wig20.json (zgodność ze starszą wersją aplikacji WIG20 Sygnały).
Podsumowanie sygnałów (summary.json) liczy osobno scripts/summary.js – tym samym silnikiem co aplikacja.
"""
import argparse
import json
import re
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
DFMT = 2                  # wersja formatu d/<SKRÓT>.json (2 = z dywidendami „dv”); zmiana wymusza pełne pobranie
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
    # dywidendy (Yahoo: events.dividends – kwota na akcję, data = dzień odcięcia)
    dv = {}
    for v in ((res.get("events") or {}).get("dividends") or {}).values():
        try:
            a = float(v.get("amount"))
            if a > 0:
                dv[day_key(int(v["date"]), m.get("gmtoffset"), False)] = round(a, 4)
        except Exception:
            pass
    if dv:
        out["dv"] = [[d, dv[d]] for d in sorted(dv)]
    return out


def chart(sym, rng, interval):
    last = None
    for host in ("query1", "query2"):
        span = (f"period1={int(time.time()) - int(rng[1:-1]) * 366 * 86400}&period2={int(time.time()) + 86400}"
                if rng.startswith("p") else f"range={rng}")      # "p10y" = jawne daty od–do
        url = (f"https://{host}.finance.yahoo.com/v8/finance/chart/{sym}"
               f"?{span}&interval={interval}&includePrePost=false" + ("&events=div" if interval == "1d" else ""))
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


# ---------------- Indeksy GPW ----------------
# Notowania: Yahoo udostępnia indeksy GPW tylko w świecach godzinowych (ok. 3 lat) – składam z nich świece dzienne;
# starszą historię dzienną dokładam z bankier.pl (dane do początku 2026 r.). Skład indeksów: biznesradar.pl (raz na dobę).
#        skrót         nazwa                  grupa     Yahoo            bankier.pl     biznesradar (skład)
INDICES = [
    ("WIG20",      "WIG20",               "main",   "WIG20.WA",      "WIG20",       "WIG20"),
    ("WIG",        "WIG",                 "main",   "WIG.WA",        "WIG",         None),
    ("WIG30",      "WIG30",               "main",   "WIG30.WA",      "WIG30",       "WIG30"),
    ("MWIG40",     "mWIG40",              "main",   "MWIG40.WA",     "MWIG40",      "mWIG40"),
    ("SWIG80",     "sWIG80",              "main",   "SWIG80.WA",     "SWIG80",      "sWIG80"),
    ("WIG140",     "WIG140",              "main",   "WIG140.WA",     "WIG140",      "WIG140"),
    ("WIG-POLAND", "WIG-Poland",          "main",   "WIG-POLAND.WA", "WIG-POLAND",  None),
    ("NCINDEX",    "NCIndex",             "main",   "NCINDEX.WA",    "NCINDEX",     None),
    ("WIG-BANKI",  "WIG-banki",           "sector", "WIG-BANKI.WA",  "WIG-BANKI",   "WIGBANKI"),
    ("WIG-BUDOW",  "WIG-budownictwo",     "sector", "WIG-BUDOW.WA",  "WIG-BUDOW",   "WIGBUDOW"),
    ("WIG-CHEMIA", "WIG-chemia",          "sector", "WIG-CHEMIA.WA", "WIG-CHEMIA",  "WIGCHEMIA"),
    ("WIG-ENERG",  "WIG-energia",         "sector", "WIG-ENERG.WA",  "WIG-ENERG",   "WIGENERG"),
    ("WIG-GORNIC", "WIG-górnictwo",       "sector", "WIG-GORNIC.WA", "WIG-GORNIC",  "WIGGORNIC"),
    ("WIG-GRY",    "WIG-gry",             "sector", "WIG-GRY.WA",    "WIG-GRY",     "WIGGRY"),
    ("WIG-INFO",   "WIG-informatyka",     "sector", "WIG-INFO.WA",   "WIG-INFO",    "WIGINFO"),
    ("WIG-LEKI",   "WIG-leki",            "sector", "WIG-LEKI.WA",   "WIG-LEKI",    "WIGLEKI"),
    ("WIG-MEDIA",  "WIG-media",           "sector", "WIG-MEDIA.WA",  "WIG-MEDIA",   "WIGMEDIA"),
    ("WIG-MOTO",   "WIG-motoryzacja",     "sector", "WIG-MOTO.WA",   "WIG-MOTO",    "WIGMOTO"),
    ("WIG-NRCHOM", "WIG-nieruchomości",   "sector", "WIG-NRCHOM.WA", "WIG-NRCHOM",  "WIGNRCHOM"),
    ("WIG-ODZIEZ", "WIG-odzież",          "sector", "WIG-ODZIEZ.WA", "WIG-ODZIEZ",  "WIGODZIEZ"),
    ("WIG-PALIWA", "WIG-paliwa",          "sector", "WIG-PALIWA.WA", "WIG-PALIWA",  "WIGPALIWA"),
    ("WIG-SPOZYW", "WIG-spożywczy",       "sector", "WIG-SPOZYW.WA", "WIG-SPOZYW",  "WIGSPOZYW"),
    ("WIG-MS-FIN", "WIG.MS-FIN",          "macro",  "WIG-MS-FIN.WA", "WIG.MS-FIN",  "WIGMSFIN"),
    ("WIG-MS-BAS", "WIG.MS-BAS",          "macro",  "WIG-MS-BAS.WA", "WIG.MS-BAS",  "WIGMSBAS"),
    ("WIG-MS-ECM", "WIG.MS-ECM",          "macro",  "WIG-MS-ECM.WA", "WIG.MS-ECM",  "WIGMSECM"),
    ("WIGDIV",     "WIGdiv",              "other",  "WIGDIV.WA",     "WIGDIV",      "WIGdiv"),
    ("WIGTECHTR",  "WIGtech",             "other",  "WIGTECHTR.WA",  None,          "WIGtechTR"),
    ("WIGMED",     "WIGmed",              "other",  "WIGMED.WA",     None,          "WIGmed"),
    ("WIGIND",     "WIGind",              "other",  "WIGIND.WA",     None,          "WIGind"),
    ("WIG-GAMES5", "WIG.GAMES5",          "other",  "WIG-GAMES5.WA", "WIG.GAMES5",  "WIGGAMES5"),
    ("WIG-CEE",    "WIG-CEE",             "other",  "WIG-CEE.WA",    "WIG-CEE",     "WIGCEE"),
    ("WIG-UKRAIN", "WIG-Ukraine",         "other",  "WIG-UKRAIN.WA", "WIG-UKRAIN",  "WIGUkrain"),
    ("NCFINDEX",   "NCFIndex",            "other",  "NCFINDEX.WA",   None,          "NCFIndex"),
    ("INNOVATOR",  "INNOVATOR",           "other",  "INNOVATOR.WA",  None,          "INNOVATOR"),
]


def hourly_to_daily(hx):
    """Świece godzinowe → dzienne (otwarcie pierwszej godziny, maks./min. dnia, zamknięcie ostatniej)."""
    off = (hx.get("meta") or {}).get("off")
    days = {}
    for i, t in enumerate(hx["t"]):
        c = hx["c"][i]
        if c is None:
            continue
        o, h, l = (hx["o"][i] if hx["o"][i] is not None else c), (hx["h"][i] if hx["h"][i] is not None else c), (hx["l"][i] if hx["l"][i] is not None else c)
        k = day_key(t, off, False)
        r = days.get(k)
        if r is None:
            days[k] = [t, o, max(h, o, c), min(l, o, c), c]
        else:
            r[2] = max(r[2], h, c); r[3] = min(r[3], l, c); r[4] = c
    out = {"meta": dict(hx.get("meta") or {}), "t": [], "o": [], "h": [], "l": [], "c": [], "v": []}
    for k in sorted(days):
        t, o, h, l, c = days[k]
        out["t"].append(t); out["o"].append(o); out["h"].append(h); out["l"].append(l); out["c"].append(c); out["v"].append(0)
    return out


def bankier_daily(sym):
    """Historia dzienna indeksu z bankier.pl (OHLC, bez wolumenu)."""
    r = session().get(f"https://www.bankier.pl/new-charts/get-data?symbol={sym}&intraday=false&type=ohlc&max_period=true", timeout=30)
    rows = sorted((json.loads(r.text).get("main") or []), key=lambda x: x[0])
    out = {"meta": {"off": 3600}, "t": [], "o": [], "h": [], "l": [], "c": [], "v": []}
    for x in rows:
        if len(x) < 5 or x[4] is None:
            continue
        out["t"].append(int(x[0] // 1000) + 8 * 3600)      # 9:00 czasu polskiego tego dnia
        out["o"].append(x[1]); out["h"].append(x[2]); out["l"].append(x[3]); out["c"].append(x[4]); out["v"].append(0)
    return out


def splice_history(old_part, new_part):
    """Starsza historia (bankier) tylko przed pierwszym dniem z Yahoo – i tylko gdy na wspólnych dniach kursy się zgadzają."""
    off = (new_part.get("meta") or {}).get("off")
    if not old_part or not old_part["t"] or not new_part["t"]:
        return new_part, None
    nk = {day_key(t, off, False): new_part["c"][i] for i, t in enumerate(new_part["t"])}
    ok_ = {day_key(t, 3600, False): old_part["c"][i] for i, t in enumerate(old_part["t"])}
    common = [d for d in nk if d in ok_ and ok_[d]]
    ratios = sorted(nk[d] / ok_[d] for d in common)
    if len(ratios) < 20 or abs(ratios[len(ratios) // 2] - 1) > 0.005:
        return new_part, f"bankier pominięty (wspólnych dni: {len(ratios)})"
    first = min(nk)
    keep = [i for i, t in enumerate(old_part["t"]) if day_key(t, 3600, False) < first]
    head = {"meta": new_part.get("meta") or {}, **{k: [old_part[k][i] for i in keep] for k in ("t", "o", "h", "l", "c", "v")}}
    return merge(head, new_part), None


def index_members(slug):
    """Skład indeksu z biznesradar.pl – lista skrótów spółek (np. „ABE (ABPL)” → ABE)."""
    r = session().get(f"https://www.biznesradar.pl/gielda/indeks:{slug}", timeout=30)
    b = r.text
    tables = re.findall(r"<table.*?</table>", b, re.S)
    body = max(tables, key=lambda x: x.count("/notowania/")) if tables else b
    out = []
    for lab in re.findall(r'<a href="/notowania/[^"#?]+"[^>]*>\s*(?:<[^>]+>\s*)*([^<]{2,60})<', body):
        tk = lab.split(" (")[0].strip()
        if re.fullmatch(r"[A-Z0-9]{2,5}", tk) and tk not in out:
            out.append(tk)
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
    if not intraday:
        dv = {}
        for src in (old, new):
            for d, a in (src.get("dv") or []):
                dv[d] = a
        first = keys[0] if keys else ""
        dv = [[d, dv[d]] for d in sorted(dv) if d >= first]
        if dv:
            out["dv"] = dv
    return out


def is_daily(x):
    """Czy notowania są dzienne (Yahoo potrafi zwrócić świece tygodniowe mimo interval=1d)."""
    ts = (x or {}).get("t") or []
    if len(ts) < 12:
        return True
    tail = ts[-61:]
    gaps = sorted((b - a) / 86400 for a, b in zip(tail, tail[1:]))
    return gaps[len(gaps) // 2] <= 4


def fetch_full(sym, min_len, old=None):
    """Pełna historia dzienna. Yahoo dla części małych spółek przy zakresie 10 lat zwraca dane urwane albo pojedynczy
    punkt – wtedy próbuję innych zakresów, a na końcu łączę najdłuższy wynik (lub poprzednie dane) z ostatnim miesiącem."""
    empty = {"meta": {}, "t": [], "o": [], "h": [], "l": [], "c": [], "v": []}

    def good(x):
        return x is not None and len(x["t"]) >= min_len and age_days(x) <= 21 and is_daily(x)

    if old and not is_daily(old):
        old = None
    got = []
    for i, rng in enumerate(("10y", "p10y", "5y", "2y", "1y", "max")):
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
        if is_daily(x):
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
    full = args.full or not prev or prev.get("fmt") != DFMT or (after_close and last_full[:10] != now_w.strftime("%Y-%m-%d"))
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
    entities = cfg
    if args.limit:
        entities = entities[: args.limit]

    def work(e):
        t = e["t"]
        path = os.path.join(store, "d", f"{t}.json")
        old = load(path)
        info = {"t": t, "n": e["n"], "y": e["y"], "w20": bool(e.get("w20")), "idx": bool(e.get("idx")), "nc": bool(e.get("nc"))}
        min_len = 300 if e.get("idx") else 30
        try:
            if old and not full and old.get("sym") and age_days(old) < 20 and is_daily(old) and len(old["t"]) >= 200:
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

    def work_idx(spec):
        t, name, grp, ysym, bsym, _ = spec
        path, hpath = os.path.join(store, "d", f"{t}.json"), os.path.join(store, "h", f"{t}.json")
        old, oldh = load(path), load(hpath)
        info = {"t": t, "n": name, "y": ysym, "w20": False, "idx": True, "nc": False, "grp": grp}
        try:
            note = None
            if old and not full and old.get("src") == "idx" and age_days(old) < 20 and len(old["t"]) >= 200:
                hx = chart(ysym, "5d", "60m")
                data = merge(old, hourly_to_daily(hx))
                hdata = merge(oldh, hx, intraday=True, keep=700) if oldh and age_days(oldh) < 5 else hx
            else:
                hx = chart(ysym, "730d", "60m")
                data = merge({"meta": {}, "t": [], "o": [], "h": [], "l": [], "c": [], "v": []}, hourly_to_daily(hx))
                if bsym:
                    try:
                        data, note = splice_history(bankier_daily(bsym), data)
                    except Exception as ex:
                        note = f"bankier: {ex}"[:120]
                hdata = merge({"meta": {}, "t": [], "o": [], "h": [], "l": [], "c": [], "v": []}, hx, intraday=True, keep=700)
            if len(data["t"]) < 60 or age_days(data) > 21:
                raise LookupError(f"za mało notowań ({len(data['t'])})")
            data.update(sym=ysym, src="idx")
            dump(path, data)
            dump(hpath, dict(hdata, sym=ysym, ok=True))
            info.update(ok=True, sym=ysym, bars=len(data["t"]), last=day_key(data["t"][-1], (data.get("meta") or {}).get("off"), False))
            if note:
                info["note"] = note
        except Exception as ex:
            info.update(ok=False, err=str(ex)[:200])
            if old and old.get("src") == "idx" and age_days(old) < 21:
                info.update(ok=True, sym=ysym, stale=True)
        time.sleep(random.random() * 0.3)
        return info

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        infos = list(pool.map(work, entities))
        iinfos = list(pool.map(work_idx, INDICES))
    print(f"Indeksy: {sum(1 for i in iinfos if i.get('ok'))}/{len(iinfos)} OK" +
          "".join(f"\n  {i['t']}: {i.get('err') or i.get('note')}" for i in iinfos if i.get("err") or i.get("note")))

    # skład indeksów (biznesradar.pl) – raz na dobę albo gdy go brak
    members = dict(prev.get("members") or {})
    if full or not members or (prev.get("membersAt") or "")[:10] != now_w.strftime("%Y-%m-%d"):
        got = 0
        for t, _, _, _, _, slug in INDICES:
            if not slug:
                continue
            try:
                m = index_members(slug)
                if len(m) >= 3:
                    members[t] = m; got += 1
            except Exception as ex:
                print(f"  skład {t}: {ex}")
            time.sleep(0.4 + random.random() * 0.4)
        members_at = now_w.isoformat(timespec="minutes") if got else (prev.get("membersAt") or "")
        print(f"Skład indeksów: {got} pobranych, razem {len(members)}")
    else:
        members_at = prev.get("membersAt") or ""
    for i in infos:
        i["ix"] = [t for t, m in members.items() if i["t"] in m]
        if members.get("WIG20"):
            i["w20"] = i["t"] in members["WIG20"]
    for i in iinfos:
        if i["t"] in members:
            i["nm"] = len(members[i["t"]])
    infos = iinfos + infos
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
    uni = {"ok": True, "fmt": DFMT, "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "lastFull": now_w.isoformat(timespec="minutes") if full else last_full,
           "mode": "full" if full else "quick", "resolved": resolved, "disc": disc, "items": infos,
           "members": members, "membersAt": members_at}
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
