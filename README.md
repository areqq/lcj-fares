# lcj-fares

Codzienny monitoring cen Ryanair z/do Łodzi (LCJ) — historia cen i analiza „kiedy tanio / kiedy kupować".

**Strona:** https://areqq.github.io/lcj-fares/

## Jak to działa
- GitHub Actions (`.github/workflows/collect.yml`) zbiera każde lotnisko o innej porze (UTC): LCJ 06:00, KTW 12:00,
  WRO 18:00, WMI 00:00 — kalendarz najtańszych cen (`cheapestPerDay`) dla wszystkich kierunków z/do lotniska na 12 miesięcy.
- `data/<HOME>/prices.csv` — dziennik zmian: wiersz tylko gdy cena/status lotu się zmienia.
- `data/<HOME>/runs.csv` — log uruchomień (`ok` / `partial` / `failed`, braki, publiczne IP runnera).
- `data/<HOME>/routes.json`, `airports.json` — kierunki i nazwy lotnisk (z API Ryanair).
- `site/data/<HOME>.json` — agregaty dla strony (wyjazdy, heatmapa, krzywa „kiedy kupować”, najtańsze loty).

Specyfikacja: `docs/superpowers/specs/2026-09-25-lcj-fares-design.md`.

## Lokalnie
```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/pytest -q
.venv/bin/python -m lcjfares.collect LCJ           # data/LCJ/, ~170 zapytań, 2–3 min
.venv/bin/python -m lcjfares.analyze LCJ           # site/data/LCJ.json
.venv/bin/python -m http.server -d site 8765       # http://localhost:8765/
```
