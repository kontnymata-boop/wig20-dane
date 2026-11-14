import re, json, sys, time
from curl_cffi import requests as http
s = http.Session(impersonate="chrome")
urls = [
 "https://newconnect.pl/archiwum-notowan?fetch=0&type=10&instrument=&date=13-11-2026",
 "https://www.newconnect.pl/archiwum-notowan?fetch=0&type=10&instrument=&date=13-11-2026",
 "https://www.gpw.pl/archiwum-notowan?fetch=0&type=10&instrument=&date=13-11-2026",
]
for u in urls:
    try:
        r = s.get(u, timeout=30)
        t = r.text
        isins = re.findall(r'PL[A-Z0-9]{9}\d', t)
        print(u, r.status_code, len(t), 'ISIN:', len(set(isins)))
        rows = re.findall(r'<tr[^>]*>(.*?)</tr>', t, re.S)
        print('  rows', len(rows))
        for row in rows[1:4]:
            cells = [re.sub(r'<[^>]+>', '', c).strip() for c in re.findall(r'<td[^>]*>(.*?)</td>', row, re.S)]
            print('  ', cells[:6])
    except Exception as e:
        print(u, 'ERR', e)
# Yahoo: crumb + search by ISIN and by name
s.get("https://fc.yahoo.com", timeout=20)
crumb = s.get("https://query1.finance.yahoo.com/v1/test/getcrumb", timeout=20).text.strip()
for q in ["PLEXCLN00016", "Excellence", "EXC.WA"]:
    r = s.get("https://query2.finance.yahoo.com/v1/finance/search", params={"q": q, "quotesCount": 5, "newsCount": 0}, timeout=20)
    print('search', q, r.status_code, [(x.get('symbol'), x.get('exchange'), x.get('shortname')) for x in (r.json().get('quotes') or [])])
r = s.get("https://query2.finance.yahoo.com/v8/finance/chart/EXC.WA", params={"range": "1mo", "interval": "1d"}, timeout=20)
j = r.json(); res = (j.get('chart') or {}).get('result') or []
print('chart EXC.WA', r.status_code, res[0]['meta'].get('regularMarketPrice') if res else j.get('chart', {}).get('error'), len(res[0]['timestamp']) if res else 0)
