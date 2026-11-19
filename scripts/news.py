#!/usr/bin/env python3
"""
RadMat · Sygnały GPW – komunikaty spółek (ESPI/EBI) i wiadomości z mediów (GitHub Actions)

Źródło: biznesradar.pl
  • /news/2 (+ strona 2) – bieżąca lista komunikatów ESPI/EBI wszystkich spółek; spółki, które właśnie
    coś opublikowały, robot sprawdza w tym samym przebiegu (priorytet),
  • /wiadomosci/<spółka> – komunikaty i wiadomości z mediów jednej spółki; pozostałe spółki robot
    odwiedza po kolei (najdawniej sprawdzane najpierw), kilkadziesiąt na przebieg, więc każda spółka
    jest odświeżana kilka razy w ciągu dnia sesyjnego.
Zapisuje STORE/n/<SKRÓT>.json – wpisy z ostatnich --keep-days dni z kategorią (wyniki, dywidenda,
emisja akcji, wezwanie, kłopoty…), wagą 0–3 i kierunkiem (+1 / −1 / 0).
Stan robota: STORE/n/_state.json (mapa skrót → adres w serwisie, czas ostatniego sprawdzenia).
"""
import argparse
import html as H
import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import update as U  # noqa: E402  (sesja curl_cffi, load/dump, strefa czasowa)

BASE = "https://www.biznesradar.pl"
LISTINGS = ["/gielda/akcje_gpw", "/gielda/newconnect"]
FEEDS = ["/news/2", "/news/2,2"]
NVER = 1

# ---------------------------------------------------------------- kategorie
# (klucz, waga 0–3, wzorce) – kolejność ma znaczenie: pierwszy pasujący wygrywa
CATS = [
    ("klopoty", 3, r"upadlos|restruktury|sanac|niewyplacal|zawiesz\w* obrot|zawieszeni\w* obrot|wyklucz\w* (akcji )?z obrotu|lista alertow"
                   r"|segment\w* lista alertow|wypowiedzen\w* umow\w* kredyt|utrat\w* plynnosci|zagrozeni\w* kontynuacj|zabezpieczeni\w* majatku"),
    ("wezwanie", 3, r"wezwani\w* do zapisywania|wezwani\w* do sprzedazy|\bwezwani|przymusow\w* wykup|squeeze|przejeci|polaczeni\w* (ze? |spol)"
                    r"|plan\w* polaczenia|zniesieni\w* dematerializacji|wycofani\w* akcji z obrotu|delisting"),
    ("emisja", 2, r"emisj\w* akcji|emisji nowych akcji|podwyzszeni\w* kapitalu|kapitalu docelowego|\babb\b|budowani\w* ksiegi popytu|przydzial\w* akcji"
                  r"|ofert\w* publiczn|prawa poboru|prawo poboru|warrant\w* subskrypcyjn|akcji serii [a-z0-9]+\b.*(emisj|subskrypc|objeci)|subskrypcj\w* akcji|zapis\w* na akcje"),
    ("skup", 2, r"skup\w* akcji wlasnych|nabyci\w* akcji wlasnych|nabywani\w* akcji wlasnych|buyback|program\w* odkupu"),
    ("dywidenda", 2, r"dywidend|podzial\w* zysku|podziale zysku|wyplat\w* zysku|zaliczk\w* na poczet"),
    ("prognoza", 2, r"prognoz|strategi|guidance|cel\w* finansow|plan\w* inwestycyjn|capex"),
    ("wyniki", 2, r"raport\w* (kwartaln|polroczn|roczn|okresow)|skonsolidowan\w* raport|\b(qsr|psr|sa-q|sa-p|sa-r|rs|srs)\b|wynik\w* finansow"
                  r"|szacunkow\w* (wynik|dane)|wstepn\w* (wynik|dane)|wybran\w* dane finansow|zysk\w* netto|przychod\w* ze sprzedazy|\bwynik"),
    ("prawo", 2, r"\bpozw|postepowani\w* (sadow|administracyjn|przed|wyjasn|karn|egzekuc)|\bkar[aey]\b|kary pieniezn|uokik|\bknf\b.*(nalozyl|kar)"
                 r"|prokurat|akt\w* oskarzeni|zajeci\w* (rachun|majat)|egzekuc|arbitraz"),
    ("umowa", 1, r"umow|kontrakt|zamowieni|przetarg|list\w* intencyjn|porozumieni|zlecen|aneks|oferty najkorzystniejszej|wybor\w* oferty"),
    ("insider", 1, r"art\.? ?19|\bmar\b|transakcj\w* (na akcjach|osob|czlon)|osob\w* pelniac\w* obowiazki zarzadcze|blisko zwiazan"),
    ("akcjonariat", 1, r"znaczn\w* pakiet|zmian\w* (udzialu|stanu posiadania)|zmianie (udzialu|stanu posiadania)|przekroczeni\w* progu|art\.? ?69"
                       r"|zawiadomieni\w* (o|od) (akcjonariusz|zmian)|stan\w* posiadania|zejsci\w* poniżej|ponizej progu|udzial\w* w ogolnej liczbie glosow"),
    ("wladze", 1, r"zarzad\w*|rad\w* nadzorcz|prezes|powolani|odwolani|rezygnacj|wiceprezes|czlonk\w* rady|kadencj"),
    ("rekomendacja", 1, r"rekomendac|cen\w* docelow|\bkupuj\b|\bsprzedaj\b|\bakumuluj\b|\bredukuj\b|\btrzymaj\b|podniosl\w* (cen|wycen)|obnizyl\w* (cen|wycen)"),
    ("wza", 0, r"walne\w* zgromadzeni|\bwza\b|\bnwza?\b|\bzwza?\b|projekt\w* uchwal|uchwal\w* podjet|lista akcjonariuszy|zwolani\w* (zwyczajn|nadzwyczajn)"),
    ("obligacje", 0, r"obligacj|kupon|odsetek|odsetki|wykup\w* (obligacji|certyfikat)"),
    ("fundusz", 0, r"wartosci aktywow netto|certyfikat\w* inwestycyjn|aktywow netto"),
    ("terminy", 0, r"terminy przekazywania|harmonogram|kalendarz|terminow publikacji"),
]
CATS_RE = [(k, w, re.compile(p)) for k, w, p in CATS]
UP = re.compile(r"nabyci|zakup|kupn|zwiekszeni|przekroczeni\w* progu|podwyzsz\w* prognoz|wzrost|rekord|lepsz|podniosl|\bkupuj|\bakumuluj"
                r"|pozyskal|wygral|zawarci|podpisani|wybor\w* oferty|najkorzystniejsz")
DOWN = re.compile(r"zbyci|sprzedaz\w* akcji|sprzedal|zmniejszeni|zejsci|ponizej progu|obnizeni\w* prognoz|obniz\w* prognoz|spadek|spadl|strat[aey]\b"
                  r"|gorsz|obnizyl|\bsprzedaj|\bredukuj|rozwiazani\w* umow|wypowiedzeni|odstapieni|odwolani\w* prognoz|kar[aey]\b")

PL = str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ", "acelnoszzACELNOSZZ")


def fold(s):
    s = (s or "").translate(PL)
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def classify(title, body, kind):
    t = fold(title + " " + (body or ""))
    cat, imp = "inne", 0
    for k, w, rx in CATS_RE:
        if rx.search(t):
            cat, imp = k, w
            break
    if kind == "news" and cat not in ("rekomendacja", "klopoty", "wezwanie"):
        imp = max(0, imp - 1)               # wiadomość z mediów waży mniej niż komunikat spółki
    if cat == "umowa" and re.search(r"znaczac|istotn", t):
        imp = 2
    tt = fold(title)
    d = 0
    if cat in ("insider", "akcjonariat", "rekomendacja", "prognoza", "umowa", "wyniki"):
        u, dn = bool(UP.search(tt)), bool(DOWN.search(tt))
        d = 1 if u and not dn else -1 if dn and not u else 0
    elif cat == "skup":
        d = 1
    elif cat in ("klopoty", "emisja"):
        d = -1
    return cat, imp, d


# ---------------------------------------------------------------- pomocnicze
STOP = {"SA", "S.A.", "S.A", "SPOLKA", "AKCYJNA", "ASI", "SE", "S.E.", "NV", "N.V.", "PLC", "AG", "SP.", "Z", "O.O.", "SKA", "S.K.A.", "GRUPA", "GROUP", "HOLDING"}


def norm_name(s):
    toks = [w for w in fold(s).upper().replace(",", " ").split() if w not in STOP]
    return re.sub(r"[^A-Z0-9]", "", "".join(toks))


def text(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    return re.sub(r"\s+", " ", H.unescape(s)).strip()


def get(url, tries=2):
    last = None
    for k in range(tries):
        try:
            r = U.session().get(url, timeout=30)
            if r.status_code == 200:
                return r.text
            last = f"HTTP {r.status_code}"
            if r.status_code == 404:
                break
        except Exception as e:  # noqa: BLE001
            last = str(e)[:120]
        time.sleep(1.5 * (k + 1))
    raise RuntimeError(last or "błąd")


def parse_listing(src):
    out = {}
    for m in re.finditer(r'href="/notowania/([^"#?]+)"[^>]*>(.*?)</a>', src, re.S):
        slug, lab = m.group(1), text(m.group(2))
        mm = re.match(r"^([A-Z0-9]{2,6})\s*\(([^)]*)\)", lab)
        if mm and mm.group(1) not in out:
            out[mm.group(1)] = {"s": slug, "sn": mm.group(2).strip()}
    return out


def split_espi(title):
    """„PKO BP SA (43/2026) Koszty emisji…” → („PKO BP SA”, „43/2026”, „Koszty emisji…”)."""
    m = re.match(r"^(.*?)\s*\((\d+/\d{4})\)\s*(.*)$", title)
    if m:
        return m.group(1).strip(), m.group(2), m.group(3).strip() or title
    return "", "", title


def parse_company(src):
    items = []
    for m in re.finditer(r'<div id="msg-(\d+)" class="record record-type-(\w+)">(.*?)<div class="cb">', src, re.S):
        mid, typ, blk = m.group(1), m.group(2).upper(), m.group(3)
        a = re.search(r'<div class="record-header">\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', blk, re.S)
        dt = re.search(r'<span class="record-date">([^<]+)</span>', blk)
        if not a or not dt:
            continue
        href, title = H.unescape(a.group(1)), text(a.group(2))
        body = re.search(r'<div class="record-body">(.*?)</div>', blk, re.S)
        body = text(body.group(1)) if body else ""
        au = re.search(r'class="record-author"[^>]*>(.*?)</a>', blk, re.S)
        d = dt.group(1).strip()[:16]
        if typ == "POST":
            _, nr, ti = split_espi(title)
            it = {"id": mid, "ty": "espi", "nr": nr, "ti": ti, "d": d, "u": BASE + href if href.startswith("/") else href}
            if body and not re.match(r"^Raport bie[żz][ąa]cy", body):
                it["b"] = body[:200]
        else:
            it = {"id": mid, "ty": "news", "ti": title, "d": d, "u": href, "s": text(au.group(1)) if au else ""}
            if body and body != title:
                it["b"] = body[:220]
        it["c"], it["imp"], it["dir"] = classify(it["ti"], it.get("b", ""), it["ty"])
        items.append(it)
    return items


def parse_feed(src):
    out = []
    for m in re.finditer(r'<h3><a href="/a/(\d+),[^"]*">(.*?)</a></h3>(.*?)<div class="time">([^<]+)</div>', src, re.S):
        mid, title, mid_html, tm = m.group(1), text(m.group(2)), m.group(3), m.group(4).strip()
        if "<h3>" in mid_html:
            continue
        who, nr, ti = split_espi(title)
        if not nr:
            continue
        try:
            d = datetime.strptime(tm, "%Y-%m-%d, %H:%M").strftime("%Y-%m-%d %H:%M")
        except ValueError:
            d = tm[:16]
        out.append({"id": mid, "who": who, "nr": nr, "ti": ti, "d": d, "href": f"/a/{m.group(1)}"})
    return out


def merge(old, new, keep_from, cap):
    by = {x["id"]: x for x in (old or [])}
    for x in new:
        prev = by.get(x["id"])
        if prev and prev.get("u", "").count(",") > x.get("u", "").count(","):
            x["u"] = prev["u"]          # pełniejszy adres z /wiadomosci zamiast skróconego z listy
        by[x["id"]] = {**(prev or {}), **x}
    arr = [x for x in by.values() if x.get("d", "") >= keep_from]
    arr.sort(key=lambda x: (x.get("d", ""), x["id"]), reverse=True)
    return arr[:cap]


# ---------------------------------------------------------------- główna część
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default="store")
    ap.add_argument("--budget", type=int, default=70, help="ile stron spółek odwiedzić w jednym przebiegu")
    ap.add_argument("--delay", type=float, default=0.35)
    ap.add_argument("--keep-days", type=int, default=45)
    ap.add_argument("--cap", type=int, default=40)
    ap.add_argument("--only", default="", help="lista skrótów do testu, np. PKO,KGH")
    ap.add_argument("--dry", action="store_true", help="nic nie zapisuj, wypisz wyniki")
    a = ap.parse_args()
    t0 = time.time()
    store = a.store
    ndir = os.path.join(store, "n")
    uni = U.load(os.path.join(store, "universe.json")) or {}
    cos = [x for x in (uni.get("items") or []) if not x.get("idx") and x.get("t")]
    if not cos:
        print("Brak universe.json – pomijam komunikaty.")
        return
    st = U.load(os.path.join(ndir, "_state.json")) or {}
    if st.get("v") != NVER:
        st = {"v": NVER}
    now = datetime.now(U.WAW)
    today = now.strftime("%Y-%m-%d")
    keep_from = (now - timedelta(days=a.keep_days)).strftime("%Y-%m-%d")

    # 1) mapa skrót → adres w serwisie (raz na dobę)
    mp = st.get("map") or {}
    if st.get("mapAt") != today or len(mp) < 100:
        got = {}
        for path in LISTINGS:
            try:
                got.update(parse_listing(get(BASE + path)))
            except Exception as e:  # noqa: BLE001
                print("Lista spółek", path, "–", e)
            time.sleep(a.delay)
        if len(got) > 100:
            mp = got
            st["mapAt"] = today
        print(f"Mapa spółek: {len(got)} z serwisu, w użyciu {len(mp)}")
    st["map"] = mp

    # indeks nazw do rozpoznawania emitenta w ogólnej liście komunikatów
    names = {}
    for c in cos:
        t = c["t"]
        for nm in {t, c.get("n") or "", (mp.get(t) or {}).get("sn", "")}:
            k = norm_name(nm)
            if len(k) >= 3:
                names.setdefault(k, set()).add(t)

    def who_to_t(who):
        k = norm_name(who)
        if not k:
            return []
        if k in names:
            return sorted(names[k])
        if len(k) >= 6:   # „CDPROJEKT” ↔ „CDPROJEKTSA…” – zgodny początek nazwy
            hit = {t for n, ts in names.items() if len(n) >= 5 and (k.startswith(n) or n.startswith(k)) for t in ts}
            if len(hit) == 1:
                return sorted(hit)
        return []

    last = st.get("last") or {}
    seen = set(st.get("seen") or [])
    files = {}

    def load_file(t):
        if t not in files:
            files[t] = U.load(os.path.join(ndir, t + ".json")) or {"t": t, "items": []}
        return files[t]

    # 2) bieżące komunikaty ESPI/EBI wszystkich spółek
    prio, nfeed, unk = [], 0, []
    if not a.only:
        for path in FEEDS:
            try:
                feed = parse_feed(get(BASE + path))
            except Exception as e:  # noqa: BLE001
                print("Lista komunikatów", path, "–", e)
                continue
            time.sleep(a.delay)
            for f in feed:
                nfeed += 1
                ts = who_to_t(f["who"])
                if not ts:
                    if f["id"] not in seen:
                        unk.append(f["who"])
                    continue
                for t in ts:
                    it = {"id": f["id"], "ty": "espi", "nr": f["nr"], "ti": f["ti"], "d": f["d"], "u": BASE + f["href"]}
                    it["c"], it["imp"], it["dir"] = classify(it["ti"], "", "espi")
                    F = load_file(t)
                    if not any(x["id"] == f["id"] for x in F["items"]):
                        F["items"] = merge(F["items"], [it], keep_from, a.cap)
                        F["chg"] = True
                    if f["id"] not in seen and t not in prio:
                        prio.append(t)
                seen.add(f["id"])
        print(f"Lista komunikatów: {nfeed} pozycji, nowe spółki do sprawdzenia: {len(prio)}"
              + (f", nierozpoznani emitenci: {len(set(unk))} (np. {', '.join(sorted(set(unk))[:6])})" if unk else ""))

    # 3) strony spółek: priorytet + kolejka najdawniej sprawdzanych
    ok_t = [c["t"] for c in cos if c.get("ok")]
    if a.only:
        queue = [t.strip().upper() for t in a.only.split(",") if t.strip()]
    else:
        big = {c["t"] for c in cos if c.get("w20") or set(c.get("ix") or []) & {"WIG20", "MWIG40", "SWIG80", "WIG30"}}
        rest = sorted((t for t in ok_t if t not in prio), key=lambda t: (last.get(t, 0), 0 if t in big else 1, t))
        queue = prio[: a.budget] + rest[: max(15, a.budget - len(prio))]
    done = errs = 0
    nf = set(st.get("nf") or [])
    for t in queue:
        info = mp.get(t)
        slug = info["s"] if info else None
        if not slug:
            if t in nf:
                last[t] = int(time.time())
                continue
            slug = t
        try:
            items = parse_company(get(f"{BASE}/wiadomosci/{slug}"))
            done += 1
            nf.discard(t)
        except Exception as e:  # noqa: BLE001
            errs += 1
            if "404" in str(e):
                nf.add(t)
            last[t] = int(time.time())
            time.sleep(a.delay)
            continue
        F = load_file(t)
        F["items"] = merge(F["items"], items, keep_from, a.cap)
        F["chg"] = True
        F["chk"] = now.strftime("%Y-%m-%d %H:%M")
        last[t] = int(time.time())
        if a.dry:
            print(f"--- {t} ({slug}): {len(items)} wpisów")
            for x in items[:8]:
                print(f"   {x['d']} {x['ty']:4} {x['c']:12} w{x['imp']} {x['dir']:+d} {x['ti'][:90]}")
        time.sleep(a.delay)
        if time.time() - t0 > 240:
            print("Limit czasu – resztę spółek sprawdzę w następnym przebiegu.")
            break

    # 4) zapis
    wrote = 0
    for t, F in files.items():
        if not F.pop("chg", False):
            continue
        F["t"] = t
        F["at"] = now.strftime("%Y-%m-%d %H:%M")
        F["src"] = "biznesradar.pl"
        F["items"] = [x for x in F["items"] if x.get("d", "") >= keep_from]
        if not a.dry:
            U.dump(os.path.join(ndir, t + ".json"), F)
        wrote += 1
    st["last"] = {t: v for t, v in last.items() if t in set(ok_t) | set(queue)}
    st["seen"] = sorted(seen, key=lambda x: int(x) if x.isdigit() else 0)[-600:]
    st["nf"] = sorted(nf)
    st["at"] = now.strftime("%Y-%m-%d %H:%M")
    if not a.dry:
        U.dump(os.path.join(ndir, "_state.json"), st)
    cover = sum(1 for t in ok_t if last.get(t))
    print(f"Komunikaty: sprawdzono {done} spółek (błędy {errs}), zapisano {wrote} plików, "
          f"pokrycie {cover}/{len(ok_t)}, {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
