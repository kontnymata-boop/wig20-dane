"""Jednorazowa sonda 3: historia indeksów GPW – bankier (zakresy dat), Yahoo (interwały), biznesradar, stooq (kwotowania)."""
import re, json, datetime as D
from curl_cffi import requests as R
S = R.Session(impersonate="chrome")
f = lambda t: D.datetime.fromtimestamp(t / 1000, D.UTC).strftime("%Y-%m-%d")
def get(url):
    try:
        r = S.get(url, timeout=25); return r.status_code, r.text
    except Exception as e:
        return 0, str(e)
def bank(qs):
    c, b = get("https://www.bankier.pl/new-charts/get-data?" + qs)
    try:
        j = json.loads(b); m = sorted(j.get("main") or [], key=lambda x: x[0]); v = j.get("volume") or []
        print(f"bankier {qs}: {c} main={len(m)} {f(m[0][0]) if m else '-'}..{f(m[-1][0]) if m else '-'} last={m[-3:]} width={len(m[-1]) if m else 0} vol={v[-2:]} pd={str(j.get('profileData'))[:200]}")
    except Exception as e:
        print("bankier", qs, c, b[:200])
bank("symbol=WIG20&intraday=false&type=candle&max_period=true")
bank("symbol=WIG20&intraday=false&type=candle&max_period=false&date_from=2026-09-01&date_to=2026-11-15")
bank("symbol=WIG20&intraday=false&type=ohlc&max_period=false&date_from=1704067200000&date_to=1763200000000")
bank("symbol=WIG20&intraday=false&type=area&max_period=false&date_from=1756684800000")
bank("symbol=WIG-BANKI&intraday=false&type=candle&max_period=false&date_from=1756684800000")
bank("symbol=PKOBP&intraday=false&type=candle&max_period=false&date_from=1756684800000")
bank("symbol=WIG20&intraday=true&type=candle&max_period=false&date_from=1762905600000")
for s, rng, itv in [("WIG20.WA", "max", "1d"), ("WIG20.WA", "1mo", "1d"), ("WIG20.WA", "5y", "1wk"), ("WIG20.WA", "1y", "1mo"), ("WIG20.WA", "5d", "60m")]:
    c, b = get(f"https://query1.finance.yahoo.com/v8/finance/chart/{s}?range={rng}&interval={itv}")
    try:
        res = json.loads(b)["chart"]["result"][0]; ts = res.get("timestamp") or []; cl = res["indicators"]["quote"][0]["close"]
        print(f"yahoo {s} {rng}/{itv}: n={len(ts)} {f(ts[0]*1000) if ts else '-'}..{f(ts[-1]*1000) if ts else '-'} last={cl[-3:]}")
    except Exception as e:
        print("yahoo", s, rng, itv, c, b[:150])
c, b = get("https://www.biznesradar.pl/notowania-historyczne/WIG20")
rows = re.findall(r'<tr[^>]*>\s*<td[^>]*>(\d{2}\.\d{2}\.\d{4})</td>((?:\s*<td[^>]*>[^<]*</td>)+)', b)
print("\nbiznesradar hist WIG20:", c, len(b), "wierszy:", len(rows), [(d, re.findall(r'>([^<]*)<', t)) for d, t in rows[:3]])
print("paginacja:", sorted(set(re.findall(r'notowania-historyczne/WIG20,(\d+)', b)))[-5:])
c, b = get("https://stooq.pl/q/l/?s=wig20+mwig40+wig_banki&f=sd2t2ohlcv&h&e=csv"); print("\nstooq quote:", c, b[:200])
c, b = get("https://www.money.pl/gielda/indeksy_gpw/"); print("money.pl:", c, len(b))
c, b = get("https://www.biznesradar.pl/gielda/indeksy"); 
links = sorted(set(re.findall(r'href="/notowania/([A-Za-z0-9\-]+)"[^>]*>\s*([^<]{2,40})<', b)))
print("biznesradar indeksy – linki notowań:", links[:90])
