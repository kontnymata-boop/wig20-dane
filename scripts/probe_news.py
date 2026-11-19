"""Jednorazowa sonda 2: struktura komunikatów (biznesradar, bankier)."""
import re, sys
sys.path.insert(0, "scripts")
import update as U
S = U.session()
def get(url):
    try:
        r = S.get(url, timeout=30); return r.status_code, r.text
    except Exception as e:
        return 0, str(e)
sq = lambda x: re.sub(r"\s+", " ", x)
c, b = get("https://www.biznesradar.pl/news/2")
occ = [m.start() for m in re.finditer("EBI/ESPI", b)]
print("BR occurrences:", len(occ))
if len(occ) > 3: print("BRITEM:", sq(b[occ[2]-1500:occ[3]+200]))
print("BR hrefs sample:", list(dict.fromkeys(re.findall(r'href="([^"]+)"', b)))[60:130])
for u in ["https://www.biznesradar.pl/raporty-espi-ebi/PKO", "https://www.biznesradar.pl/wiadomosci/PKO", "https://www.biznesradar.pl/news-espi/PKO", "https://www.biznesradar.pl/komunikaty/PKO"]:
    c2, b2 = get(u); print("BRco", u, c2, len(b2))
c, b = get("https://www.bankier.pl/inwestowanie/depeszerynkowe.html")
k = b.find("Kategorie nadawane"); 
items = re.findall(r'<a[^>]+href="([^"]*wiadomosc[^"]*)"[^>]*>([^<]{5,200})</a>', b)
print("BKDEP items:", len(items), items[:8])
j = b.find(items[0][0]) if items else -1
print("BKDEPITEM:", sq(b[max(0, j-1500):j+600]) if j > 0 else sq(b[k-3000:k]))
c, b = get("https://www.bankier.pl/gielda/notowania/akcje/PKOBP/komunikaty")
items = re.findall(r'<a[^>]+href="([^"]*wiadomosc[^"]*)"[^>]*>([^<]{5,200})</a>', b)
print("BKCO items:", len(items), items[:8])
j = b.find(items[0][0]) if items else -1
print("BKCOITEM:", sq(b[max(0, j-1200):j+500]) if j > 0 else "")
c, b = get("https://www.bankier.pl/inwestowanie/depeszerynkowe.html?page=2")
print("BKDEP page2:", c, len(re.findall(r'href="[^"]*wiadomosc[^"]*"', b)))
