"""Jednorazowa sonda 3: element listy komunikatów i strona wiadomości spółki."""
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
a = [m.start() for m in re.finditer(r'href="/a/\d+', b)]
print("BRA count", len(a))
if len(a) > 6: print("BRITEM:", sq(b[a[4]-900:a[6]+300]))
print("BR page links:", sorted(set(re.findall(r'href="(/news/2[^"]*)"', b)))[:10], sorted(set(re.findall(r'href="(/news/[^"]{1,20})"', b)))[:20])
c, b = get("https://www.biznesradar.pl/gielda/akcje_gpw")
print("PKO slug:", re.findall(r'href="/notowania/([^"]+)"[^>]*>\s*(?:<[^>]+>\s*)*PKO \(', b)[:3], re.findall(r'href="/notowania/([^"]+)"[^>]*>\s*(?:<[^>]+>\s*)*KGH \(', b)[:3])
c, b = get("https://www.biznesradar.pl/wiadomosci/PKO")
a = [m.start() for m in re.finditer(r'href="/a/\d+', b)]
print("BRCO PKO", c, len(b), "art", len(a))
if len(a) > 3: print("BRCOITEM:", sq(b[a[1]-900:a[3]+300]))
c, b = get("https://www.biznesradar.pl/wiadomosci/KGHM"); print("BRCO KGHM", c, len(b), len(re.findall(r'href="/a/\d+', b)))
c, b = get("https://www.biznesradar.pl/news/2,2"); print("BR page 2", c, len(re.findall(r'href="/a/\d+', b)))
