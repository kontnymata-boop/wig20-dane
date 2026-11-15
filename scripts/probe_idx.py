"""Jednorazowa sonda: które źródło udostępnia notowania i skład indeksów GPW."""
import re, json
from curl_cffi import requests as R
S = R.Session(impersonate="chrome")
def get(url, n=300):
    try:
        r = S.get(url, timeout=25)
        b = r.text
        print(f"\n== {r.status_code} {len(b):>8} B  {url}\n{b[:n]!r}")
        return r.status_code, b
    except Exception as e:
        print(f"\n== ERR {url}: {e}")
        return 0, ""
# stooq
get("https://stooq.pl/q/d/l/?s=wig20&i=d")
get("https://stooq.com/q/d/l/?s=mwig40&i=d")
c, b = get("https://stooq.pl/q/i/?s=mwig40", 200)
print("stooq skład – tickery:", re.findall(r'q/\?s=([a-z0-9]{3,4})"', b)[:50])
# bankier
get("https://www.bankier.pl/new-charts/get-data?symbol=WIG20&intraday=false&type=area&max_period=true", 400)
get("https://www.bankier.pl/new-charts/get-data?symbol=WIG-BANKI&intraday=false&type=candle&max_period=true", 400)
c, b = get("https://www.bankier.pl/inwestowanie/profile/quote.html?symbol=MWIG40", 200)
print("bankier profil – symbole:", re.findall(r'symbol=([A-Z0-9\-]{3,12})', b)[:60])
# GPW Benchmark (administrator indeksów)
c, b = get("https://gpwbenchmark.pl/", 200)
print("gpwbenchmark linki:", sorted(set(re.findall(r'href="(/[^"]{3,60})"', b)))[:80])
get("https://gpwbenchmark.pl/notowania", 200)
get("https://www.gpw.pl/indeksy", 120)
# Yahoo
for sym in ["WIG.WA", "^WIG", "MWIG40.WA", "SWIG80.WA", "WIG20.WA", "WIG30.WA", "^WIG20"]:
    get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=5d&interval=1d", 160)
# biznesradar (tylko sprawdzenie dostępności)
c, b = get("https://www.biznesradar.pl/gielda/indeksy", 150)
print("biznesradar indeksy:", sorted(set(re.findall(r'indeks:([A-Za-z0-9\-]+)', b)))[:80])
