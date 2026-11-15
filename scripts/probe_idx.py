"""Jednorazowa sonda 2: historia indeksów w Yahoo, indeksy sektorowe, skład indeksów."""
import re, json, sys, html
sys.path.insert(0, "scripts")
from curl_cffi import requests as R
S = R.Session(impersonate="chrome")
def get(url, **kw):
    try:
        r = S.get(url, timeout=25, **kw); return r.status_code, r.text
    except Exception as e:
        return 0, str(e)
def ychart(sym, rng="10y"):
    c, b = get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range={rng}&interval=1d")
    try:
        res = json.loads(b)["chart"]["result"][0]; q = res["indicators"]["quote"][0]; ts = res.get("timestamp") or []
        cl = [x for x in q["close"] if x is not None]
        import datetime as D
        f = lambda t: D.datetime.utcfromtimestamp(t).strftime("%Y-%m-%d")
        return f"{c} n={len(ts)} {f(ts[0]) if ts else '-'}..{f(ts[-1]) if ts else '-'} last={cl[-3:]} vol={q['volume'][-3:]} name={res['meta'].get('longName') or res['meta'].get('shortName')}"
    except Exception as e:
        return f"{c} ERR {b[:120]!r}"
for s in ["WIG20.WA", "WIG.WA", "WIG30.WA", "MWIG40.WA", "SWIG80.WA", "WIG140.WA", "NCINDEX.WA", "WIG-BANKI.WA", "WIGBANKI.WA", "WIG_BANKI.WA", "WIG-PALIWA.WA", "WIG-POLAND.WA", "WIGDIV.WA"]:
    print(s, "10y:", ychart(s), "| 2y:", ychart(s, "2y") if not s.startswith("WIG2") else "")
# Yahoo – lista indeksów WSE ze screenera
try:
    from update import yahoo_crumb
    crumb = yahoo_crumb(S)
    body = {"size": 250, "offset": 0, "sortField": "ticker", "sortType": "ASC", "quoteType": "INDEX",
            "query": {"operator": "eq", "operands": ["exchange", "WSE"]}, "userId": "", "userIdType": "guid"}
    r = S.post(f"https://query1.finance.yahoo.com/v1/finance/screener?crumb={crumb}&lang=en-US&region=PL", json=body, timeout=30)
    q = r.json()["finance"]["result"][0]["quotes"]
    print("SCREENER INDEX WSE:", len(q), [(x["symbol"], x.get("shortName")) for x in q][:120])
except Exception as e:
    print("screener ERR", e)
# biznesradar – skład indeksu
for ix in ["mWIG40", "WIGBANKI"]:
    c, b = get(f"https://www.biznesradar.pl/gielda/indeks:{ix}")
    rows = re.findall(r'<a href="/notowania/([^"#?]+)"[^>]*>\s*(?:<[^>]+>\s*)*([^<]{2,60})<', b)
    print(f"\nbiznesradar {ix}: {c} {len(b)} B; linki notowań ({len(rows)}):", rows[:60])
    i = b.find('qTableFull'); print("fragment:", re.sub(r'\s+', ' ', b[i:i+1500]) if i > 0 else b[:300])
# bankier – fragment tabeli składu
c, b = get("https://www.bankier.pl/inwestowanie/profile/quote.html?symbol=WIG-BANKI")
i = b.find('symbol=ALIOR'); print("\nbankier WIG-BANKI:", c, len(b), re.sub(r'\s+', ' ', b[max(0,i-1500):i+600]) if i > 0 else 'brak ALIOR')
c, b = get("https://www.bankier.pl/new-charts/get-data?symbol=WIG20&intraday=false&type=candle&max_period=true")
try:
    j = json.loads(b); print("\nbankier candle keys:", list(j.keys()), {k: (len(v), v[-2:]) for k, v in j.items() if isinstance(v, list)})
except Exception as e: print("bankier candle ERR", e, b[:200])
c, b = get("https://www.bankier.pl/new-charts/get-data?symbol=WIG20&intraday=true&type=candle&max_period=false&date_from=2026-11-01")
print("bankier intraday:", c, b[:300])
