# lcj-fares

Codzienny monitoring cen **Ryanair** z/do **Łodzi (LCJ), Katowic (KTW), Wrocławia (WRO) i Warszawy-Modlina (WMI)**:
własna historia cen, żeby wiedzieć, kiedy i dokąd lata się tanio i kiedy kupować.

**Strona:** https://areqq.github.io/lcj-fares/ — lotnisko wybierasz na górze (albo w adresie: `#LCJ`, `#KTW`, `#WRO`, `#WMI`).

## Co pokazuje strona
Dla wybranego lotniska:
- **Najtańsze wyjazdy** — wylot + najtańszy powrót 3–10 dni później, ranking ze wszystkich kierunków (max 3 na kierunek).
  Przy równej cenie wyżej wyjazdy obejmujące weekend (cała sobota i niedziela w trakcie pobytu).
- **Wyjazdy na wybrany kierunek** — top 10 par tam + z powrotem i „typowy wyjazd” (mediana) do porównania.
- **Kiedy tanio** — heatmapa dzień tygodnia × miesiąc: mediana ceny lotu na 31–60 dni przed wylotem
  (stałe wyprzedzenie → miesiące porównywalne), z wierszem i kolumną „razem”.
- **Kiedy kupować** — mediana ceny wg liczby dni do wylotu i „× min” (ile drożej od najniższej ceny lotu);
  wyszarzone z ostrzeżeniem, dopóki historia ma mniej niż 30 dni.
- **Najtańsze nadchodzące loty** (w jedną stronę) z odchyleniem od „ceny normalnej” kierunku.

Ceny „aktualne” pochodzą zawsze z ostatniego udanego pomiaru; wyszarzone są wyniki z małej próby.

## Jak to działa
- Źródło: otwarte (nieoficjalne) API Ryanair — `farfnd/v4/oneWayFares/{O}/{D}/cheapestPerDay` (najtańszy lot każdego
  dnia miesiąca) i lista tras lotniska (z polskimi nazwami i krajami). Bez logowania i tokenów.
- GitHub Actions (`.github/workflows/collect.yml`) zbiera **każde lotnisko o innej porze** (UTC):

  | Lotnisko | Godzina | Kierunki | Zapytań |
  |---|---|---|---|
  | LCJ Łódź | 06:00 | 7 | ~170 |
  | KTW Katowice | 12:00 | 28 | ~670 |
  | WRO Wrocław | 18:00 | 53 | ~1270 |
  | WMI Modlin | 00:00 | 52 | ~1250 |

  Każdy run: testy → zbiór (wszystkie kierunki w obie strony, 12 miesięcy do przodu) → commit danych → analiza →
  commit wyniku → publikacja strony. GitHub potrafi opóźnić zaplanowany run o kilka godzin — dane są dzienne, więc to nie szkodzi.
- Nieudany zbiór (>50% błędów) kończy job błędem → mail od GitHuba; `runs.csv` zapisuje się mimo to.
  Po 10 błędach z rzędu run przerywa zapytania (bezpiecznik).

## Dane
| Plik | Zawartość |
|---|---|
| `data/<HOME>/prices.csv` | dziennik zmian: wiersz tylko, gdy cena/status lotu się zmienia (`observed,origin,dest,day,dep_time,price,status`) |
| `data/<HOME>/runs.csv` | log uruchomień: status `ok`/`partial`/`failed`, liczba zapytań, braki, **publiczne IP runnera** |
| `data/<HOME>/routes.json`, `airports.json` | kierunki i nazwy lotnisk z kodem kraju |
| `site/data/<HOME>.json` | agregaty dla strony |

Publiczne IP runnera jest też w logu joba (krok „Public IP”) — przydaje się przy analizie blokad.

## Ręczne uruchomienie
Actions → **collect** → *Run workflow* → wybierz lotnisko. Albo:
```bash
gh workflow run collect.yml -R areqq/lcj-fares -f airport=KTW
```
Uruchamiaj **po jednym lotnisku naraz** — GitHub trzyma w kolejce tylko jeden oczekujący run, kolejne anuluje.

## Lokalnie
```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/pytest -q
.venv/bin/python -m lcjfares.collect LCJ           # → data/LCJ/  (LCJ ~2–3 min, WRO/WMI ~30 min)
.venv/bin/python -m lcjfares.analyze LCJ           # → site/data/LCJ.json
.venv/bin/python -m http.server -d site 8765       # http://localhost:8765/#LCJ
```

## Ograniczenia
- Tylko Ryanair (Wizz Air ma wyszukiwarkę za anti-botem), tylko loty bezpośrednie.
- API podaje **najtańszy lot dnia** — przy kilku lotach dziennie godziny dotyczą tego najtańszego.
- Wnioski „kiedy kupować” wymagają tygodni–miesięcy historii.
- Flagi to emoji — na Windows (Chrome/Edge) wyświetlają się jako litery kraju.

## Kod
`lcjfares/ryanair.py` (klient API) · `store.py` (pliki) · `collect.py` (zbiór) · `analyze.py` (agregaty) ·
`site/index.html` (strona). Specyfikacja: `docs/superpowers/specs/2026-09-25-lcj-fares-design.md`.
