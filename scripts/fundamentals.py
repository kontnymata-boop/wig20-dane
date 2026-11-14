#!/usr/bin/env python3
"""
RadMat · Sygnały GPW – dane finansowe i ocena kondycji spółek (GitHub Actions)

Dla każdej spółki z universe.json (bez indeksu i ETF) pobiera z Yahoo Finance:
  • quoteSummary – profil, kapitalizacja, C/Z, C/WK, dywidenda, prognozy analityków,
  • fundamentals-timeseries – przychody, zysk netto, EBITDA, dług, gotówka, kapitał własny, przepływy (roczne, kwartalne, 12 mies.).
Zapisuje STORE/f/<SKRÓT>.json: wskaźniki, ocenę kondycji (0–4) i opis po polsku.
Dane odświeża, gdy są starsze niż --max-age godzin (domyślnie 20), więc w ciągu dnia robot ich nie pobiera ponownie.
"""
import argparse
import hashlib
import json
import math
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

try:
    from curl_cffi import requests as http
    IMPERSONATE = True
except ImportError:  # lokalne testy
    http = None
    IMPERSONATE = False

QS_MODULES = "assetProfile,summaryDetail,financialData,defaultKeyStatistics,price"
TS_KEYS = ["TotalRevenue", "NetIncome", "OperatingIncome", "EBITDA", "StockholdersEquity", "TotalDebt",
           "CashAndCashEquivalents", "CurrentAssets", "CurrentLiabilities", "FreeCashFlow", "OperatingCashFlow"]
TS_TYPES = ",".join(f"{p}{k}" for p in ("annual", "quarterly", "trailing") for k in TS_KEYS)

SECTORS = {
    "Basic Materials": "surowce i materiały", "Communication Services": "telekomunikacja i media",
    "Consumer Cyclical": "konsumpcja cykliczna", "Consumer Defensive": "dobra podstawowe",
    "Energy": "energia (ropa, gaz, węgiel)", "Financial Services": "finanse", "Healthcare": "ochrona zdrowia",
    "Industrials": "przemysł i usługi", "Real Estate": "nieruchomości", "Technology": "technologie",
    "Utilities": "energetyka i media",
}
INDUSTRIES = {
    "Banks - Regional": "bank", "Banks - Diversified": "bank", "Insurance - Diversified": "ubezpieczenia",
    "Insurance - Property & Casualty": "ubezpieczenia majątkowe", "Insurance - Life": "ubezpieczenia na życie",
    "Insurance Brokers": "pośrednictwo ubezpieczeniowe", "Capital Markets": "dom maklerski / rynki kapitałowe",
    "Credit Services": "usługi kredytowe i windykacja", "Asset Management": "zarządzanie aktywami",
    "Financial Conglomerates": "grupa finansowa", "Mortgage Finance": "kredyty hipoteczne",
    "Oil & Gas Integrated": "koncern paliwowo-energetyczny", "Oil & Gas Refining & Marketing": "rafineria i sprzedaż paliw",
    "Oil & Gas E&P": "wydobycie ropy i gazu", "Oil & Gas Equipment & Services": "usługi dla branży naftowej",
    "Thermal Coal": "węgiel energetyczny", "Coking Coal": "węgiel koksowy", "Copper": "miedź i srebro",
    "Other Industrial Metals & Mining": "metale i górnictwo", "Steel": "stal", "Aluminum": "aluminium",
    "Gold": "złoto", "Silver": "srebro", "Uranium": "uran", "Chemicals": "chemia", "Specialty Chemicals": "chemia specjalistyczna",
    "Agricultural Inputs": "nawozy i środki dla rolnictwa", "Building Materials": "materiały budowlane",
    "Paper & Paper Products": "papier", "Packaging & Containers": "opakowania", "Lumber & Wood Production": "drewno",
    "Utilities - Regulated Electric": "energetyka", "Utilities - Diversified": "energetyka",
    "Utilities - Renewable": "energia odnawialna", "Utilities - Independent Power Producers": "wytwarzanie energii",
    "Utilities - Regulated Gas": "dystrybucja gazu", "Utilities - Regulated Water": "wodociągi",
    "Telecom Services": "telekomunikacja", "Entertainment": "rozrywka i media", "Electronic Gaming & Multimedia": "gry komputerowe",
    "Internet Content & Information": "internet", "Advertising Agencies": "reklama", "Broadcasting": "telewizja i radio",
    "Publishing": "wydawnictwa", "Software - Application": "oprogramowanie", "Software - Infrastructure": "oprogramowanie",
    "Information Technology Services": "usługi IT", "Computer Hardware": "sprzęt komputerowy",
    "Electronic Components": "elektronika", "Communication Equipment": "sprzęt telekomunikacyjny",
    "Scientific & Technical Instruments": "aparatura naukowo-techniczna", "Semiconductors": "półprzewodniki",
    "Consumer Electronics": "elektronika użytkowa", "Electronics & Computer Distribution": "dystrybucja elektroniki",
    "Apparel Retail": "handel odzieżą", "Apparel Manufacturing": "produkcja odzieży", "Footwear & Accessories": "obuwie i akcesoria",
    "Internet Retail": "handel internetowy", "Specialty Retail": "handel specjalistyczny", "Department Stores": "domy handlowe",
    "Discount Stores": "sklepy dyskontowe", "Grocery Stores": "sklepy spożywcze", "Home Improvement Retail": "markety budowlane",
    "Luxury Goods": "dobra luksusowe", "Auto Parts": "części samochodowe", "Auto & Truck Dealerships": "dealerzy samochodów",
    "Auto Manufacturers": "produkcja pojazdów", "Furnishings, Fixtures & Appliances": "meble i wyposażenie",
    "Household & Personal Products": "kosmetyki i chemia domowa", "Packaged Foods": "żywność", "Confectioners": "słodycze",
    "Farm Products": "produkcja rolna", "Beverages - Wineries & Distilleries": "alkohole", "Beverages - Brewers": "piwo",
    "Beverages - Non-Alcoholic": "napoje", "Food Distribution": "dystrybucja żywności", "Tobacco": "tytoń",
    "Restaurants": "restauracje", "Lodging": "hotele", "Travel Services": "turystyka", "Leisure": "rekreacja",
    "Gambling": "zakłady i gry losowe", "Residential Construction": "deweloper mieszkaniowy",
    "Real Estate - Development": "deweloper", "Real Estate - Diversified": "nieruchomości", "Real Estate Services": "usługi na rynku nieruchomości",
    "REIT - Diversified": "nieruchomości komercyjne", "REIT - Office": "biurowce", "REIT - Retail": "centra handlowe",
    "REIT - Industrial": "magazyny", "Engineering & Construction": "budownictwo", "Infrastructure Operations": "infrastruktura",
    "Industrial Distribution": "dystrybucja przemysłowa", "Specialty Industrial Machinery": "maszyny przemysłowe",
    "Farm & Heavy Construction Machinery": "maszyny ciężkie", "Electrical Equipment & Parts": "sprzęt elektryczny",
    "Aerospace & Defense": "zbrojeniówka i lotnictwo", "Railroads": "kolej", "Trucking": "transport drogowy",
    "Integrated Freight & Logistics": "logistyka", "Marine Shipping": "żegluga", "Airlines": "linie lotnicze",
    "Airports & Air Services": "usługi lotniskowe", "Waste Management": "gospodarka odpadami",
    "Security & Protection Services": "ochrona", "Staffing & Employment Services": "rekrutacja i praca tymczasowa",
    "Consulting Services": "doradztwo", "Specialty Business Services": "usługi dla biznesu",
    "Rental & Leasing Services": "wynajem i leasing", "Conglomerates": "konglomerat", "Metal Fabrication": "obróbka metali",
    "Tools & Accessories": "narzędzia", "Pollution & Treatment Controls": "ochrona środowiska",
    "Building Products & Equipment": "wyroby budowlane", "Diagnostics & Research": "diagnostyka i badania",
    "Medical Care Facilities": "placówki medyczne", "Drug Manufacturers - Specialty & Generic": "leki generyczne",
    "Drug Manufacturers - General": "producent leków", "Biotechnology": "biotechnologia",
    "Medical Instruments & Supplies": "sprzęt medyczny", "Medical Devices": "urządzenia medyczne",
    "Medical Distribution": "dystrybucja leków", "Pharmaceutical Retailers": "apteki", "Health Information Services": "informatyka medyczna",
    "Education & Training Services": "edukacja", "Personal Services": "usługi dla ludności", "Textile Manufacturing": "tekstylia",
    "Recreational Vehicles": "pojazdy rekreacyjne", "Solar": "fotowoltaika", "Shell Companies": "spółka bez działalności operacyjnej",
}
REC = {"strong_buy": "zdecydowanie kupuj", "buy": "kupuj", "hold": "trzymaj", "underperform": "słabiej od rynku",
       "sell": "sprzedaj", "strong_sell": "zdecydowanie sprzedaj"}
FVER = 4  # zmiana wersji wymusza ponowne przeliczenie wszystkich plików f/
LEVELS = ["bardzo słaba", "słaba", "przeciętna", "dobra", "bardzo dobra"]

_local = threading.local()


# ---------------------------------------------------------------- formatowanie (po polsku)
def fnum(x, d=1):
    s = f"{abs(x):,.{d}f}".replace(",", " ").replace(".", ",")
    return ("−" if x < 0 else "") + s


def money(x, cur):
    if x is None:
        return "–"
    a = abs(x)
    if a >= 1e9:
        v, u = x / 1e9, " mld"
    elif a >= 1e6:
        v, u = x / 1e6, " mln"
    elif a >= 1e3:
        v, u = x / 1e3, " tys."
    else:
        v, u = x, ""
    d = 1 if abs(v) < 100 else 0
    return fnum(v, d) + u + (" zł" if cur in (None, "PLN") else " " + cur)


def plural(n, one, few, many):
    n = int(n)
    if n == 1:
        return one
    return few if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14) else many


def pct(x, d=1, sign=True):
    if x is None:
        return "–"
    return ("+" if sign and x > 0 else "") + fnum(x * 100, d) + "%"


def qlabel(iso):
    y, m = int(iso[:4]), int(iso[5:7])
    return f"{['I', 'II', 'III', 'IV'][(m - 1) // 3]} kw. {y}"


def ylabel(iso):
    y, m = int(iso[:4]), int(iso[5:7])
    return str(y) if m == 12 else f"{y - 1}/{str(y)[2:]}"


def dpl(iso):
    return f"{iso[8:10]}.{iso[5:7]}.{iso[:4]}"


# ---------------------------------------------------------------- pobieranie
def session():
    s = getattr(_local, "s", None)
    if s is None:
        s = http.Session(impersonate="chrome")
        _local.s, _local.crumb = s, None
    return s


def crumb(force=False):
    if getattr(_local, "crumb", None) and not force:
        return _local.crumb
    s = session()
    try:
        s.get("https://fc.yahoo.com", timeout=20)
    except Exception:
        pass
    c = s.get("https://query1.finance.yahoo.com/v1/test/getcrumb", timeout=20).text.strip()
    if not c or "<" in c or len(c) > 40:
        raise RuntimeError("brak crumb")
    _local.crumb = c
    return c


def get_json(url, params):
    for attempt in range(4):
        try:
            p = dict(params, crumb=crumb(force=attempt > 0 and attempt % 2 == 1))
            r = session().get(url, params=p, timeout=25)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 404:
                return None
            time.sleep(1.5 * (attempt + 1))
        except Exception:
            time.sleep(1.5 * (attempt + 1))
    return None


def fetch(sym):
    qs = get_json(f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{sym}", {"modules": QS_MODULES})
    res = ((qs or {}).get("quoteSummary") or {}).get("result") or [{}]
    now = int(time.time())
    ts = get_json(f"https://query2.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/{sym}",
                  {"symbol": sym, "type": TS_TYPES, "period1": now - 6 * 366 * 86400, "period2": now})
    series = {}
    for it in ((ts or {}).get("timeseries") or {}).get("result") or []:
        t = ((it.get("meta") or {}).get("type") or [None])[0]
        if not t:
            continue
        vals = [v for v in (it.get(t) or []) if v and (v.get("reportedValue") or {}).get("raw") is not None]
        series[t] = [{"d": v.get("asOfDate"), "cur": v.get("currencyCode"), "v": v["reportedValue"]["raw"]} for v in vals]
    return (res[0] if res else {}), series


# ---------------------------------------------------------------- ocena
def raw(d, *path):
    for k in path:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    if isinstance(d, dict):
        d = d.get("raw")
    return d if isinstance(d, (int, float)) and not (isinstance(d, float) and math.isnan(d)) else None


def r_inflated(m):
    return m.get("roe") is not None and m["roe"] >= 0.3 and m.get("de") is not None and m["de"] > 3


def assess(t, name, qs, S, price=None, fx=None, opis=None, opis_src=None):
    """qs – wynik quoteSummary (dict modułów), S – szeregi {typ: [{d,cur,v}]}; zwraca rekord f/<t>.json"""
    ap, sd, fd, ks = (qs.get(k) or {} for k in ("assetProfile", "summaryDetail", "financialData", "defaultKeyStatistics"))

    def last(k, n=1):
        a = S.get(k) or []
        return a[-n] if len(a) >= n else None

    def lv(k):
        x = last(k)
        return x["v"] if x else None

    cur = None
    for k in ("trailingTotalRevenue", "annualTotalRevenue", "quarterlyTotalRevenue", "annualNetIncome"):
        if last(k):
            cur = last(k)["cur"]
            break
    cur = cur or fd.get("financialCurrency") or "PLN"

    def sum4(k):  # suma 4 ostatnich kolejnych kwartałów (spójna z tabelą kwartałów i wskaźnikiem C/Z)
        a = S.get(k) or []
        if len(a) < 4:
            return None
        try:
            d0 = datetime.strptime(a[-4]["d"], "%Y-%m-%d"); d1 = datetime.strptime(a[-1]["d"], "%Y-%m-%d")
        except Exception:
            return None
        return sum(x["v"] for x in a[-4:]) if 250 <= (d1 - d0).days <= 300 else None

    rev = sum4("quarterlyTotalRevenue")
    ni = sum4("quarterlyNetIncome")
    if rev is None:
        rev = lv("trailingTotalRevenue")
    if ni is None:
        ni = lv("trailingNetIncome")
    ebitda = lv("trailingEBITDA")
    fcf = lv("trailingFreeCashFlow")
    qr, qn = S.get("quarterlyTotalRevenue") or [], S.get("quarterlyNetIncome") or []
    if rev is None:
        rev = lv("annualTotalRevenue")
    if ni is None:
        ni = lv("annualNetIncome")
    if ebitda is None:
        ebitda = lv("annualEBITDA")
    if fcf is None:
        fcf = lv("annualFreeCashFlow")

    def latest(k):
        q, a = last("quarterly" + k), last("annual" + k)
        if q and (not a or q["d"] >= a["d"]):
            return q["v"]
        return a["v"] if a else None

    eq, debt, cash = latest("StockholdersEquity"), latest("TotalDebt"), latest("CashAndCashEquivalents")
    ca, cl = latest("CurrentAssets"), latest("CurrentLiabilities")
    asof = max([x["d"] for k in ("quarterlyTotalRevenue", "quarterlyNetIncome", "trailingTotalRevenue", "annualTotalRevenue",
                                 "quarterlyStockholdersEquity") for x in (S.get(k) or [])[-1:]] or [None]) if S else None

    industry_en = (ap.get("industry") or "").replace("—", " - ").replace("  ", " ").strip()
    sector_en = ap.get("sector") or ""
    is_fin = industry_en.startswith("Banks") or industry_en.startswith("Insurance")

    m = {
        "mcap": raw(sd, "marketCap") or raw(qs, "price", "marketCap"),
        "rev": rev, "ni": ni, "ebitda": ebitda, "fcf": fcf, "eq": eq, "debt": debt, "cash": cash,
        "margin": (ni / rev) if (ni is not None and rev and rev > 0) else None,
        "roe": (ni / eq) if (ni is not None and eq and eq > 0) else raw(fd, "returnOnEquity"),
        "nd": (debt - (cash or 0)) if debt is not None else None,
        "cr": (ca / cl) if (ca is not None and cl and cl > 0) else raw(fd, "currentRatio"),
        "pe": None, "pb": None,
        "dy": raw(sd, "dividendYield") or raw(sd, "trailingAnnualDividendYield"), "payout": raw(sd, "payoutRatio"),
        "tgt": raw(fd, "targetMeanPrice"), "nAn": raw(fd, "numberOfAnalystOpinions"), "rec": fd.get("recommendationKey"),
    }
    # C/Z i C/WK liczone z kapitalizacji (zł) i wyników przeliczonych na złote – Yahoo myli waluty u spółek raportujących w EUR/USD
    rate = 1.0 if cur == "PLN" else (fx(cur) if fx else None)
    if m["mcap"] and rate:
        if ni is not None and ni > 0:
            m["pe"] = m["mcap"] / (ni * rate)
        if eq is not None and eq > 0:
            m["pb"] = m["mcap"] / (eq * rate)
    m["nde"] = (m["nd"] / ebitda) if (m["nd"] is not None and ebitda and ebitda > 0) else None
    m["de"] = (debt / eq) if (debt is not None and eq and eq > 0) else None
    if eq is not None and eq <= 0:
        m["roe"] = None

    # dynamika kwartalna r/r (ostatni kwartał vs ten sam kwartał rok wcześniej)
    def yoy(arr):
        if len(arr) >= 5:
            a, b = arr[-1], arr[-5]
            return a, b
        return None, None

    qa, qb = yoy(qr)
    m["revYoY"] = (qa["v"] / qb["v"] - 1) if (qa and qb and qb["v"] > 0) else raw(fd, "revenueGrowth")
    m["revQ"] = qlabel(qa["d"]) if qa else None
    na, nb = yoy(qn)
    m["niQ"] = (na["v"], nb["v"], qlabel(na["d"])) if (na and nb) else None

    lines, pts, mx = [], 0.0, 0

    def add(key, score, txt, weight=2):
        nonlocal pts, mx
        if score is not None:
            pts += score
            mx += weight
        s = None if score is None else (1 if score >= weight * 0.75 else -1 if score <= weight * 0.25 else 0)
        lines.append({"k": key, "s": s, "txt": txt})

    # 1. rentowność
    if ni is not None and rev:
        mg = m["margin"]
        if ni > 0 and mg is not None and mg > 1:
            add("zysk", 1, f"W ostatnich 12 miesiącach zysk netto ({money(ni, cur)}) był większy niż przychody ({money(rev, cur)}) – "
                           "to zwykle efekt zdarzeń jednorazowych, więc rentowność trudno ocenić.")
        elif ni > 0:
            add("zysk", 2 if mg is not None and mg >= 0.08 else 1,
                f"Jest rentowna: w ostatnich 12 miesiącach zarobiła {money(ni, cur)} netto przy przychodach {money(rev, cur)}"
                + (f" (marża netto {pct(mg, 1, False)})." if mg is not None else "."))
        else:
            add("zysk", 0, f"Jest na stracie: w ostatnich 12 miesiącach strata netto {money(-ni, cur)} przy przychodach {money(rev, cur)}.")
    elif ni is not None:
        add("zysk", 2 if ni > 0 else 0, f"Zysk netto w ostatnich 12 miesiącach: {money(ni, cur)}.")

    # 2. ROE
    if m["roe"] is not None and r_inflated(m):
        add("roe", 1, f"Zwrot z kapitału własnego (ROE) {pct(m['roe'], 0, False)} – zawyżony, bo kapitał własny jest bardzo mały w porównaniu z długiem.")
    elif m["roe"] is not None:
        r = m["roe"]
        add("roe", 2 if r >= 0.12 else 1 if r >= 0.05 else 0,
            f"Zwrot z kapitału własnego (ROE) {pct(r, 1, False)} – "
            + ("wysoki." if r >= 0.15 else "dobry." if r >= 0.12 else "przeciętny." if r >= 0.05 else "niski." if r >= 0 else "ujemny."))
    elif eq is not None and eq <= 0:
        add("roe", 0, "Kapitał własny jest ujemny – straty przewyższyły wkład właścicieli. To poważny sygnał ostrzegawczy.")

    # 3. przychody
    if m["revYoY"] is not None:
        g = m["revYoY"]
        when = f"W ostatnim kwartale ({m['revQ']})" if m["revQ"] else "W ostatnim kwartale"
        add("przych", 2 if g >= 0.05 else 1 if g >= -0.05 else 0,
            f"{when} przychody " + ("wzrosły o " + pct(g, 1, False) if g >= 0.005 else "spadły o " + pct(-g, 1, False) if g <= -0.005 else "były na podobnym poziomie")
            + " rok do roku.")

    # 4. zysk kwartalny r/r
    if m["niQ"]:
        a, b, ql = m["niQ"]
        if a > 0 and b > 0:
            g = a / b - 1
            sc = 2 if g >= 0 else 1 if g >= -0.3 else 0
            txt = f"Zysk netto w {ql} " + (f"wzrósł o {pct(g, 0, False)}" if g >= 0.005 else f"spadł o {pct(-g, 0, False)}" if g <= -0.005 else "był podobny") \
                + f" rok do roku ({money(a, cur)})."
        elif a > 0 >= b:
            sc, txt = 2, f"W {ql} spółka wyszła na plus: {money(a, cur)} zysku wobec straty rok wcześniej."
        elif a <= 0 < b:
            sc, txt = 0, f"W {ql} spółka miała stratę {money(-a, cur)}, a rok wcześniej była na plusie."
        else:
            sc = 1 if a > b else 0
            txt = f"W {ql} strata netto {money(-a, cur)} – " + ("mniejsza niż rok wcześniej." if a > b else "większa niż rok wcześniej.")
        add("zyskq", sc, txt)

    # 5–7: tylko poza bankami i ubezpieczycielami
    if not is_fin:
        if m["nd"] is not None and ebitda is not None:
            nd = m["nd"]
            if nd <= 0:
                add("dlug", 2, f"Ma więcej gotówki niż długu (gotówka netto {money(-nd, cur)}).")
            elif ebitda <= 0:
                add("dlug", 0, f"Ma dług netto {money(nd, cur)} przy ujemnym wyniku operacyjnym (EBITDA) – zadłużenie jest ryzykowne.")
            else:
                x = m["nde"]
                if x < 0.05:
                    add("dlug", 2, f"Praktycznie nie ma długu netto ({money(nd, cur)}).")
                else:
                  add("dlug", 2 if x <= 1.5 else 1 if x <= 3 else 0,
                      f"Zadłużenie {'niskie' if x <= 1.5 else 'umiarkowane' if x <= 3 else 'wysokie'}: dług netto to {fnum(x, 1)}× roczna EBITDA ({money(nd, cur)}).")
        elif m["de"] is not None:
            x = m["de"]
            add("dlug", 2 if x < 0.5 else 1 if x < 1.5 else 0,
                f"Dług stanowi {pct(x, 0, False)} kapitału własnego – zadłużenie {'niskie' if x < 0.5 else 'umiarkowane' if x < 1.5 else 'wysokie'}.")
        if m["cr"] is not None:
            x = m["cr"]
            add("plyn", 2 if x >= 1.5 else 1 if x >= 1.0 else 0,
                f"Płynność bieżąca {fnum(x, 2)} – " + ("bezpieczna: aktywa obrotowe z zapasem pokrywają bieżące zobowiązania." if x >= 1.5
                                                       else "wystarczająca." if x >= 1.0
                                                       else "poniżej 1: bieżące zobowiązania są większe niż aktywa obrotowe, warto to obserwować."))
        if fcf is not None:
            add("fcf", 2 if fcf > 0 else 0,
                f"Wolne przepływy pieniężne w 12 miesięcy: {money(fcf, cur)} – " +
                ("spółka generuje gotówkę." if fcf > 0 else "spółka więcej wydaje, niż zarabia gotówkowo."))

    grade = None
    n_crit = mx // 2
    if mx >= 8 and n_crit >= 4:
        sc = pts / mx
        lvl = 4 if sc >= 0.8 else 3 if sc >= 0.6 else 2 if sc >= 0.4 else 1 if sc >= 0.2 else 0
        grade = {"pts": round(pts, 1), "max": mx, "s": round(sc, 3), "lvl": lvl, "lbl": LEVELS[lvl]}

    # informacje dodatkowe (nie wpływają na ocenę)
    extra = []
    val = []
    if m["pe"] is not None and m["pe"] > 0:
        pe = m["pe"]
        val.append(f"C/Z {fnum(pe, 1)} ({'niski' if pe < 10 else 'umiarkowany' if pe <= 20 else 'wysoki'})")
    elif ni is not None and ni <= 0:
        val.append("C/Z nie do policzenia (strata)")
    if m["pb"] is not None and m["pb"] >= 0.05:
        val.append(f"C/WK {fnum(m['pb'], 2)}")
    if m["dy"]:
        val.append(f"stopa dywidendy {pct(m['dy'], 1, False)}")
    if val:
        extra.append({"k": "wycena", "s": None, "txt": "Wycena: " + ", ".join(val) + "."})
    if is_fin:
        extra.append({"k": "bank", "s": None, "txt": "W bankach i u ubezpieczycieli nie oceniam zadłużenia, płynności ani przepływów gotówki – w tej branży liczy się je inaczej."})
    if m["tgt"] and (m["nAn"] or 0) >= 2:
        n_an = int(m['nAn'])
        txt = f"Analitycy ({n_an} {plural(n_an, 'opinia', 'opinie', 'opinii')}): średnia cena docelowa {fnum(m['tgt'], 2)} zł"
        if price:
            txt += f" ({pct(m['tgt'] / price - 1, 0)} od obecnego kursu)"
        if m["rec"] in REC:
            txt += f", przeważające zalecenie: {REC[m['rec']]}"
        extra.append({"k": "analitycy", "s": None, "txt": txt + "."})

    # wstęp
    mc = m["mcap"]
    size = None if not mc else "duża spółka" if mc >= 10e9 else "średnia spółka" if mc >= 1e9 else "mała spółka" if mc >= 2e8 else "bardzo mała spółka"
    branza = INDUSTRIES.get(industry_en) or (SECTORS.get(sector_en))
    intro = name
    if branza:
        intro += f" – {branza}"
    if size:
        intro += f"; {size} (kapitalizacja {money(mc, 'PLN')})"
    emp = raw(ap, "fullTimeEmployees") or ap.get("fullTimeEmployees")
    if isinstance(emp, (int, float)) and emp > 0:
        intro += f", ok. {fnum(emp, 0) if emp < 10000 else fnum(emp / 1000, 0) + ' tys.'} {plural(emp, 'pracownik', 'pracowników', 'pracowników')}"
    intro += "."

    years = []
    ar = {x["d"]: x["v"] for x in S.get("annualTotalRevenue") or []}
    an = {x["d"]: x["v"] for x in S.get("annualNetIncome") or []}
    for d in sorted(set(ar) | set(an))[-4:]:
        years.append({"p": ylabel(d), "rev": ar.get(d), "ni": an.get(d)})
    quarters = []
    qrd = {x["d"]: x["v"] for x in qr}
    qnd = {x["d"]: x["v"] for x in qn}
    for d in sorted(set(qrd) | set(qnd))[-5:]:
        quarters.append({"p": qlabel(d), "rev": qrd.get(d), "ni": qnd.get(d)})

    has_any = bool(lines or extra or years)
    out = {
        "t": t, "v": FVER, "ok": has_any, "upd": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "src": "Yahoo Finance", "cur": cur, "asof": asof, "fin": is_fin,
        "intro": intro, "grade": grade, "lines": lines, "extra": extra, "years": years, "quarters": quarters,
        "info": {"sector": sector_en or None, "industry": industry_en or None, "branza": branza,
                 "web": ap.get("website"), "opis": opis, "opisSrc": opis_src if opis else None,
                 "desc": None if opis else ((ap.get("longBusinessSummary") or "")[:900] or None)},
        "m": {k: (round(v, 4) if isinstance(v, float) and abs(v) < 1e4 else v) for k, v in m.items() if k not in ("niQ",)},
    }
    return out


# ---------------------------------------------------------------- opisy po polsku
OPISY_PL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "opisy_pl.json")


def chunks(text, limit=450):
    import re
    parts, cur = [], ""
    for sent in re.split(r"(?<=[.!?])\s+", text.strip()):
        if len(cur) + len(sent) + 1 > limit and cur:
            parts.append(cur)
            cur = ""
        cur = (cur + " " + sent).strip()
    if cur:
        parts.append(cur)
    return [p[:480] for p in parts]


def translate_en_pl(text):
    """Awaryjne tłumaczenie automatyczne (MyMemory) – tylko dla spółek bez gotowego opisu po polsku."""
    out = []
    for part in chunks(text):
        r = session().get("https://api.mymemory.translated.net/get", params={"q": part, "langpair": "en|pl"}, timeout=25)
        j = r.json()
        tr = ((j or {}).get("responseData") or {}).get("translatedText") or ""
        if j.get("responseStatus") not in (200, "200") or not tr or "MYMEMORY WARNING" in tr.upper() or "QUERY LENGTH LIMIT" in tr.upper():
            raise RuntimeError("tłumaczenie niedostępne")
        out.append(tr.strip())
        time.sleep(0.5)
    return " ".join(out)


# ---------------------------------------------------------------- program
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


def last_close(store, t):
    d = load(os.path.join(store, "d", t + ".json")) or {}
    c = d.get("c") or []
    return c[-1] if c else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default="store")
    ap.add_argument("--max-age", type=float, default=20.0, help="godziny – starsze dane są odświeżane")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only", default="")
    ap.add_argument("--test-translate", default="")
    a = ap.parse_args()
    if http is None:
        print("Brak curl_cffi – pomijam dane finansowe"); return 0
    if a.test_translate:
        print(translate_en_pl(a.test_translate)); return 0
    uni = load(os.path.join(a.store, "universe.json")) or {}
    items = [it for it in uni.get("items") or [] if it.get("ok") and not it.get("idx") and not str(it.get("sym") or "").upper().startswith("ETF")]
    if a.only:
        want = set(a.only.split(","))
        items = [it for it in items if it["t"] in want]
    now = time.time()
    todo = []
    for it in items:
        f = load(os.path.join(a.store, "f", it["t"] + ".json"))
        age = None
        if f and f.get("upd"):
            try:
                age = (now - datetime.strptime(f["upd"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()) / 3600
            except Exception:
                age = None
        if a.only or age is None or age >= a.max_age or f.get("v") != FVER:
            todo.append(it)
    if a.limit:
        todo = todo[:a.limit]
    print(f"Dane finansowe: {len(items)} spółek, do odświeżenia {len(todo)}")
    if not todo:
        return 0
    opisy = load(OPISY_PL) or {}
    cache_path = os.path.join(a.store, "tlumaczenia.json")
    tcache = load(cache_path) or {}
    tlock = threading.Lock()

    def opis_for(t, qs):
        if opisy.get(t):
            return opisy[t], "pl"
        desc = ((qs.get("assetProfile") or {}).get("longBusinessSummary") or "")[:900]
        if not desc:
            return None, None
        key = t + ":" + hashlib.md5(desc.encode("utf-8")).hexdigest()[:10]
        with tlock:
            if key in tcache:
                return tcache[key], "auto"
        try:
            tr = translate_en_pl(desc)
        except Exception as e:
            print(f"  {t}: brak tłumaczenia ({e})", file=sys.stderr)
            return None, None
        with tlock:
            tcache[key] = tr
        return tr, "auto"

    rates, rlock = {}, threading.Lock()

    def fx(cur):
        with rlock:
            if cur in rates:
                return rates[cur]
        v = None
        try:
            j = session().get(f"https://query2.finance.yahoo.com/v8/finance/chart/{cur}PLN=X", params={"range": "5d", "interval": "1d"}, timeout=20).json()
            v = ((j.get("chart") or {}).get("result") or [{}])[0].get("meta", {}).get("regularMarketPrice")
        except Exception:
            v = None
        with rlock:
            rates[cur] = v
        return v

    stats = {"ok": 0, "grade": 0, "empty": 0, "err": 0}
    lock = threading.Lock()

    def work(it):
        t, sym = it["t"], it.get("sym") or it.get("y")
        try:
            qs, ts = fetch(sym)
            op, src = opis_for(t, qs)
            rec = assess(t, it.get("n") or t, qs, ts, price=last_close(a.store, t), fx=fx, opis=op, opis_src=src)
            dump(os.path.join(a.store, "f", t + ".json"), rec)
            with lock:
                stats["ok" if rec["ok"] else "empty"] += 1
                if rec["grade"]:
                    stats["grade"] += 1
        except Exception as e:
            with lock:
                stats["err"] += 1
            print(f"  {t}: błąd {e}", file=sys.stderr)

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        list(ex.map(work, todo))
    if tcache:
        dump(cache_path, tcache)
    print("Opisy po polsku:", sum(1 for it in todo if opisy.get(it["t"])), "gotowe,", len(tcache), "tłumaczeń automatycznych w pamięci")
    print("Kursy walut:", {k: v for k, v in rates.items()})
    print(f"Dane finansowe: zapisane {stats['ok']}, z oceną kondycji {stats['grade']}, puste {stats['empty']}, błędy {stats['err']} "
          f"({time.time() - t0:.0f} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
