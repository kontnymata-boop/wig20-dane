import json, sys, time
from curl_cffi import requests as http
s = http.Session(impersonate="chrome")
r = s.get("https://fc.yahoo.com", timeout=20); print("fc", r.status_code, list(s.cookies.keys()))
crumb = s.get("https://query1.finance.yahoo.com/v1/test/getcrumb", timeout=20).text.strip(); print("crumb", repr(crumb[:20]))
mods = "assetProfile,summaryDetail,financialData,defaultKeyStatistics,earnings,incomeStatementHistory,incomeStatementHistoryQuarterly,balanceSheetHistory,cashflowStatementHistory,price"
types = ",".join([f"{p}{k}" for p in ("annual", "quarterly", "trailing") for k in (
    "TotalRevenue", "NetIncome", "OperatingIncome", "EBITDA", "StockholdersEquity", "TotalDebt", "CashAndCashEquivalents",
    "CurrentAssets", "CurrentLiabilities", "FreeCashFlow", "OperatingCashFlow", "NetIncomeCommonStockholders", "TotalAssets", "DilutedEPS")])
for sym in sys.argv[1:]:
    print("=" * 30, sym)
    r = s.get(f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{sym}", params={"modules": mods, "crumb": crumb}, timeout=25)
    print("QS", r.status_code)
    try:
        j = r.json(); res = (j.get("quoteSummary") or {}).get("result") or []
        if res:
            res = res[0]
            for k, v in res.items():
                txt = json.dumps(v, ensure_ascii=False)
                print(" ", k, len(txt), txt[:1500])
        else: print(" ", json.dumps(j)[:500])
    except Exception as e: print("QS err", e, r.text[:300])
    p2 = int(time.time()); p1 = p2 - 6 * 365 * 86400
    r = s.get(f"https://query2.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/{sym}",
              params={"symbol": sym, "type": types, "period1": p1, "period2": p2, "crumb": crumb}, timeout=25)
    print("TS", r.status_code)
    try:
        for it in (r.json().get("timeseries") or {}).get("result") or []:
            t = it["meta"]["type"][0]; vals = it.get(t) or []
            print("  ", t, [(v.get("asOfDate"), v.get("periodType"), v.get("currencyCode"), (v.get("reportedValue") or {}).get("raw")) for v in vals if v])
    except Exception as e: print("TS err", e, r.text[:300])
