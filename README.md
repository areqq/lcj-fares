# lcj-fares

Codzienny monitoring cen Ryanair z/do Łodzi (LCJ) — historia cen i analiza „kiedy tanio / kiedy kupować".

**Strona:** https://areqq.github.io/lcj-fares/

## Jak to działa
- GitHub Actions (`.github/workflows/collect.yml`) codziennie o 06:00 UTC pobiera kalendarz najtańszych cen
  (`cheapestPerDay`) dla wszystkich kierunków z/do LCJ na 12 miesięcy do przodu.
- `data/prices.csv` — dziennik zmian: wiersz tylko gdy cena/status lotu się zmienia.
- `data/runs.csv` — log uruchomień (`ok` / `partial` / `failed`, lista braków).
- `site/data.json` — agregaty dla strony (heatmapa, krzywa „kiedy kupować", najtańsze loty).

Specyfikacja: `docs/superpowers/specs/2026-09-25-lcj-fares-design.md`.

## Lokalnie
```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/pytest -q
.venv/bin/python -m lcjfares.collect data          # ~170 zapytań, 2–3 min
.venv/bin/python -m lcjfares.analyze data site/data.json
.venv/bin/python -m http.server -d site 8765       # http://localhost:8765/
```
