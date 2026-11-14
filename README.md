# WIG20 Sygnały – serwer danych (RadMat)

Automat (GitHub Actions) pobiera notowania spółek WIG20 z Yahoo Finance
co 20 minut w trakcie sesji GPW oraz po jej zamknięciu i zapisuje je w `data/`:

- `data/wig20.json` – notowania dzienne (10 lat) wszystkich spółek,
- `data/h/<SYMBOL>.json` – notowania godzinowe (3 miesiące) do Ichimoku 1 godz.

Aplikacja `wig20-sygnaly-*.html` czyta te pliki bezpośrednio – działa jako zwykły plik HTML,
na komputerze i telefonie, bez serwera i bez konfiguracji. `index.html` to ta sama aplikacja.

Ręczne uruchomienie: zakładka **Actions → Aktualizacja notowań WIG20 → Run workflow**.

Narzędzie edukacyjne – nie stanowi rekomendacji inwestycyjnej.
