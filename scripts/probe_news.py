"""Jednorazowa sonda: struktura listy komunikatów ESPI/EBI i mapowanie spółek."""
import re, json, sys
sys.path.insert(0, "scripts")
import update as U
S = U.session()
def get(url):
    try:
        r = S.get(url, timeout=30); return r.status_code, r.text
    except Exception as e:
        return 0, str(e)
c, b = get("https://www.biznesradar.pl/news/2")
print("BR news/2:", c, len(b))
i = b.find("EBI/ESPI"); print("FRAGMENT:", re.sub(r"\s+", " ", b[max(0, i-3000):i+800]))
print("linki notowania:", re.findall(r'href="(/notowania/[^"]+)"', b)[:30])
print("linki news:", re.findall(r'href="(/news/[^"]+)"', b)[:10], re.findall(r'href="(https?://[^"]*(?:espi|ebi|raport)[^"]*)"', b, re.I)[:10])
print("paginacja:", sorted(set(re.findall(r'/news/2,(\d+)', b)))[:10])
for u in ["https://www.biznesradar.pl/gielda/akcje_gpw", "https://www.biznesradar.pl/gielda/newconnect"]:
    c, b2 = get(u); lab = re.findall(r'<a href="/notowania/([^"#?]+)"[^>]*>\s*(?:<[^>]+>\s*)*([^<]{2,60})<', b2)
    print(u, c, len(b2), len(lab), lab[:12])
c, b3 = get("https://www.biznesradar.pl/raporty-espi-ebi/PKOBP"); print("BR raporty PKOBP:", c, len(b3), re.sub(r"\s+", " ", b3[b3.find("ESPI"):b3.find("ESPI")+600]) if c == 200 else "")
c, b4 = get("https://www.bankier.pl/gielda/notowania/akcje/PKOBP/komunikaty"); print("bankier PKOBP komunikaty:", c, len(b4))
j = b4.find("komunikat"); print(re.sub(r"\s+", " ", b4[j:j+400]) if j > 0 else "")
c, b5 = get("https://www.bankier.pl/inwestowanie/depeszerynkowe.html"); print("bankier depesze:", c, len(b5))
k = b5.find("Pokaż więcej"); print(re.sub(r"\s+", " ", b5[max(0, k-2500):k]) if k > 0 else b5[:300])
