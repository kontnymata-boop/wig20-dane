#!/usr/bin/env python3
"""
RadMat · WIG20 Sygnały – robot pobierający notowania (GitHub Actions)

Pobiera z Yahoo Finance notowania dzienne (10 lat) i godzinowe (3 miesiące)
spółek WIG20 i zapisuje je w folderze data/. Aplikacja WIG20 Sygnały czyta
te pliki bezpośrednio z GitHuba (raw.githubusercontent.com obsługuje CORS),
więc działa jako zwykły plik HTML – bez serwera i bez konfiguracji.
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

try:
    from curl_cffi import requests as http      # podszywa się pod przeglądarkę Chrome
    SESSION = http.Session(impersonate="chrome")
except ImportError:                              # awaryjnie: zwykłe requests
    import requests as http
    SESSION = http.Session()
    SESSION.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130.0 Safari/537.36"

# skrót w aplikacji -> symbole Yahoo (kolejne warianty, gdy pierwszy nie działa)
ENTITIES = [
    ("WIG20", ["WIG20.WA"]),
    ("PKO", ["PKO.WA"]), ("PKN", ["PKN.WA"]), ("KGH", ["KGH.WA"]), ("ALE", ["ALE.WA"]),
    ("PEO", ["PEO.WA"]), ("PZU", ["PZU.WA"]), ("EBP", ["EBP.WA", "SPL.WA"]), ("LPP", ["LPP.WA"]),
    ("CDR", ["CDR.WA"]), ("DNP", ["DNP.WA"]), ("MBK", ["MBK.WA"]), ("ZAB", ["ZAB.WA"]),
    ("ALR", ["ALR.WA"]), ("KTY", ["KTY.WA"]), ("TPE", ["TPE.WA"]), ("PGE", ["PGE.WA"]),
    ("BDX", ["BDX.WA"]), ("KRU", ["KRU.WA"]), ("PCO", ["PCO.WA"]), ("MDV", ["MDV.WA", "CCC.WA"]),
    ("BFT", ["BFT.WA"]), ("XTB", ["XTB.WA"]),
]
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")


def r4(x):
    return None if x is None else round(float(x), 4)


def chart(sym, rng, interval):
    """Notowania z Yahoo v8 chart; zwraca słownik w formacie skróconym albo rzuca wyjątek."""
    last = None
    for host in ("query1", "query2"):
        url = (f"https://{host}.finance.yahoo.com/v8/finance/chart/{sym}"
               f"?range={rng}&interval={interval}&includePrePost=false")
        for attempt in range(3):
            try:
                r = SESSION.get(url, timeout=30)
                if r.status_code == 429:
                    last = "HTTP 429 (limit Yahoo)"
                    time.sleep(3 + attempt * 4)
                    continue
                j = r.json()
                res = (j.get("chart") or {}).get("result")
                if not res:
                    err = (j.get("chart") or {}).get("error") or {}
                    raise LookupError(err.get("description") or err.get("code") or f"HTTP {r.status_code}")
                return compact(res[0])
            except LookupError:
                raise
            except Exception as e:                      # sieć / zły JSON – spróbuj ponownie
                last = f"{type(e).__name__}: {e}"
                time.sleep(2 + attempt * 2)
    raise RuntimeError(last or "nieznany błąd")


def compact(res):
    q = ((res.get("indicators") or {}).get("quote") or [{}])[0]
    m = res.get("meta") or {}
    out = {"meta": {"off": m.get("gmtoffset"), "time": m.get("regularMarketTime"), "price": m.get("regularMarketPrice")},
           "t": [], "o": [], "h": [], "l": [], "c": [], "v": []}
    ts = res.get("timestamp") or []
    closes = q.get("close") or []
    for i, t in enumerate(ts):
        c = closes[i] if i < len(closes) else None
        if c is None:
            continue
        out["t"].append(t)
        for k, src in (("o", "open"), ("h", "high"), ("l", "low")):
            arr = q.get(src) or []
            out[k].append(r4(arr[i]) if i < len(arr) else None)
        out["c"].append(r4(c))
        vol = q.get("volume") or []
        out["v"].append(int(vol[i]) if i < len(vol) and vol[i] else 0)
    if not out["t"]:
        raise LookupError("pusta lista notowań")
    return out


def dump(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))


def main():
    os.makedirs(os.path.join(OUT, "h"), exist_ok=True)
    daily, errors = {}, {}
    for tk, syms in ENTITIES:
        for sym in syms:
            try:
                daily[sym] = dict(chart(sym, "10y", "1d"), ticker=tk)
                print(f"OK   {tk:6} {sym:10} {len(daily[sym]['t'])} sesji")
                break
            except Exception as e:
                errors[f"{tk}:{sym}"] = str(e)[:200]
                print(f"BŁĄD {tk:6} {sym:10} {e}")
        time.sleep(0.4)
    # godzinowe (do Ichimoku 1 godz.)
    for tk, syms in ENTITIES:
        sym = next((s for s in syms if s in daily), None)
        if not sym or tk == "WIG20":
            continue
        try:
            dump(os.path.join(OUT, "h", f"{sym}.json"), {"ok": True, "sym": sym, **chart(sym, "3mo", "60m")})
        except Exception as e:
            errors[f"{tk}:{sym}:60m"] = str(e)[:200]
        time.sleep(0.4)
    if len([s for s in daily if daily[s]["ticker"] != "WIG20"]) < 5:
        print("Za mało pobranych spółek – nie nadpisuję danych.")
        sys.exit(1)
    dump(os.path.join(OUT, "wig20.json"), {
        "ok": True, "app": "wig20-sygnaly", "source": "Yahoo Finance",
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data": daily, "errors": errors,
    })
    print(f"Zapisano {len(daily)} pozycji, błędy: {len(errors)}")


if __name__ == "__main__":
    main()
