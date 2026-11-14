import json, collections
from curl_cffi import requests as http
s = http.Session(impersonate="chrome")
s.get("https://fc.yahoo.com", timeout=20)
crumb = s.get("https://query1.finance.yahoo.com/v1/test/getcrumb", timeout=20).text.strip()
allq = []
for off in range(0, 2000, 250):
    body = {"offset": off, "size": 250, "sortField": "ticker", "sortType": "ASC", "quoteType": "EQUITY",
            "query": {"operator": "and", "operands": [{"operator": "eq", "operands": ["exchange", "WSE"]}]}, "userId": "", "userIdType": "guid"}
    r = s.post("https://query2.finance.yahoo.com/v1/finance/screener", params={"crumb": crumb, "lang": "en-US", "region": "US", "formatted": "false"}, json=body, timeout=30)
    print('off', off, r.status_code, r.text[:200] if r.status_code != 200 else '')
    if r.status_code != 200: break
    res = ((r.json().get('finance') or {}).get('result') or [{}])[0]
    q = res.get('quotes') or []
    print('  total', res.get('total'), 'got', len(q))
    allq += q
    if len(q) < 250: break
print('ALL', len(allq))
if allq:
    print('keys', sorted(allq[0].keys())[:60])
    c = collections.Counter((x.get('shortName') or '').split(' ')[-2] if len((x.get('shortName') or '').split(' '))>1 else '' for x in allq)
    print('markers', c.most_common(15))
    for x in allq[:5]: print({k: x.get(k) for k in ('symbol','shortName','longName','fullExchangeName','market','regularMarketPrice','marketCap','averageDailyVolume3Month')})
    ex = [x for x in allq if x.get('symbol') == 'EXC.WA']; print('EXC', ex[0] if ex else None)
    out = [{k: x.get(k) for k in ('symbol','shortName','longName','regularMarketPrice','marketCap','averageDailyVolume3Month','regularMarketTime')} for x in allq]
    json.dump(out, open('wse_all.json', 'w'), ensure_ascii=False)
    print('NCO count', sum(1 for x in allq if 'XNCO' in (x.get('shortName') or '')))
