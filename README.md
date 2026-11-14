# Sygnały GPW – serwer danych (RadMat)

Automat (GitHub Actions) pobiera z Yahoo Finance notowania wszystkich spółek rynku głównego GPW
(lista: `scripts/companies.json`, debiuty wyszukiwane wg `scripts/resolve.json`):

- co 30 minut w trakcie sesji – ostatnie dni (szybka aktualizacja),
- po zamknięciu sesji – pełne 10 lat notowań dziennych i 3 miesiące godzinowych.

Dane trafiają do gałęzi **data** (zawsze jedna, bieżąca wersja – bez historii):

- `f/<SKRÓT>.json` – dane finansowe z Yahoo Finance i ocena kondycji spółki z opisem po polsku (`scripts/fundamentals.py`, odświeżane raz na dobę),
- `summary.json` – sygnały (3 horyzonty), oceny Ichimoku D/T/M, kurs, obrót, ATR, przestrzeń do celu i ryzyko do stopu oraz wyniki systemu na spółce (dla rankingu Top 3) – dla listy spółek,
- `d/<SKRÓT>.json` – notowania dzienne, `h/<SKRÓT>.json` – godzinowe,
- `universe.json` – stan pobierania każdej spółki.

Sygnały w `summary.json` liczy `scripts/summary.js` tym samym silnikiem, którego używa aplikacja
(`index.html`, kod między znacznikami ENGINE). Aplikacja `gpw-sygnaly-*.html` czyta te pliki
bezpośrednio z GitHuba – działa jako zwykły plik HTML, bez serwera i konfiguracji.

`data/wig20.json` w gałęzi main – plik zgodności dla starszej aplikacji „WIG20 Sygnały”.

Ręczne uruchomienie: **Actions → Aktualizacja notowań GPW → Run workflow** (opcja „pełne pobranie”).

Narzędzie edukacyjne – nie stanowi rekomendacji inwestycyjnej.
