"""Jednorazowa sonda 4: Yahoo – godzinowe indeksów (2 lata), lista indeksów WSE; bankier – indeksy sektorowe."""
import re, json, sys, datetime as D
sys.path.insert(0, "scripts")
import update as U
S = U.session()
f = lambda t: D.datetime.fromtimestamp(t, D.UTC).strftime("%Y-%m-%d")
def get(url):
    try:
        r = S.get(url, timeout=30); return r.status_code, r.text
    except Exception as e:
        return 0, str(e)
for s, rng in [("WIG20.WA", "730d"), ("WIG20.WA", "2y"), ("MWIG40.WA", "730d"), ("WIG-BANKI.WA", "730d"), ("NCINDEX.WA", "730d"), ("WIG.WA", "730d")]:
    c, b = get(f"https://query1.finance.yahoo.com/v8/finance/chart/{s}?range={rng}&interval=60m")
    try:
        res = json.loads(b)["chart"]["result"][0]; ts = res.get("timestamp") or []; q = res["indicators"]["quote"][0]
        days = sorted({f(t + 3600) for t in ts})
        print(f"yahoo60 {s} {rng}: n={len(ts)} dni={len(days)} {days[0] if days else '-'}..{days[-1] if days else '-'} close={q['close'][-2:]} vol={q['volume'][-2:]}")
    except Exception as e:
        print("yahoo60", s, rng, c, b[:150])
try:
    crumb = U.yahoo_crumb()
    out = []
    for off in (0, 250):
        body = {"size": 250, "offset": off, "sortField": "ticker", "sortType": "ASC", "quoteType": "INDEX",
                "query": {"operator": "eq", "operands": ["exchange", "WSE"]}, "userId": "", "userIdType": "guid"}
        r = S.post(f"https://query1.finance.yahoo.com/v1/finance/screener?crumb={crumb}&lang=en-US&region=PL", json=body, timeout=30)
        q = r.json()["finance"]["result"][0]["quotes"]; out += q
        if len(q) < 250: break
    print("SCREENER INDEX WSE:", len(out), [(x["symbol"], x.get("shortName")) for x in out])
except Exception as e:
    print("screener ERR", repr(e)[:300])
for sym in ["WIG-BUDOW", "WIG-ENERG", "WIG-GORNIC", "WIG-GRY", "WIG-INFO", "WIG-NRCHOM", "WIG-SPOZYW", "NCINDEX", "WIG140", "WIG-UKRAIN", "WIGDIV"]:
    c, b = get(f"https://www.bankier.pl/new-charts/get-data?symbol={sym}&intraday=false&type=ohlc&max_period=true")
    try:
        m = json.loads(b)["main"]; print(f"bankier {sym}: n={len(m)} {f(m[0][0]/1000)}..{f(m[-1][0]/1000)}")
    except Exception:
        print("bankier", sym, c, b[:100])
