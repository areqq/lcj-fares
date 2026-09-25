# lcj-fares — monitoring cen Ryanair z/do Łodzi (LCJ)

Data: 2026-09-25 · Status: zatwierdzony projekt (przed planem implementacji)

## Cel

Zbudować wiedzę, **kiedy loty z/do Łodzi są tanie**, na podstawie własnej historii cen:

1. **Tanie terminy** — które dni tygodnia / miesiące są najtańsze na danej trasie.
2. **Kiedy kupować** — jak cena konkretnego lotu zmienia się wraz ze zbliżaniem się wylotu
   (ile dni przed wylotem jest najtaniej).

Poza zakresem (na teraz): alerty/powiadomienia o spadkach, inne linie niż Ryanair, loty z przesiadką,
taryfy round-trip z API (pary tam+powrót składamy z cen 1-way).

## Ustalenia

| Kwestia | Decyzja | Uzasadnienie |
|---|---|---|
| Linia | tylko Ryanair | Wizz nie lata z LCJ (sprawdzone 2026-09-25); Ryanair = cała tania oferta LCJ |
| Źródło | otwarte API `farfnd/v4/oneWayFares/{O}/{D}/cheapestPerDay` | bez auth/anti-bota; 1 zapytanie = 1 miesiąc cen dziennych |
| Trasy | dynamicznie z `routes/.../airport/LCJ`, obie strony | dziś: AGP, ALC, BGY, BHX, CRL, DUB, STN → 14 kierunków |
| Horyzont | bieżący miesiąc + 11 kolejnych | ~14 × 12 ≈ 170 zapytań/dzień |
| Waluta | PLN, 1 dorosły | |
| Harmonogram | GitHub Actions, raz dziennie ~06:00 UTC | darmowe, bez własnego serwera |
| Repo | publiczne GitHub, osobny katalog `~/lcj-fares` | publiczne umożliwia darmowe Pages; oddzielone od `skyskaner` (APK, tokeny) |
| Prezentacja | GitHub Pages: statyczna strona + Chart.js z CDN | wykresy; dane jawne — akceptowane |
| Magazyn | dziennik zmian w CSV (podejście A) | mały przyrost, czytelny diff, pełna historia odtwarzalna |

## Architektura

```
.github/workflows/collect.yml   cron codziennie; concurrency: collect (bez równoległych runów)
  1. pytest
  2. python -m lcjfares.collect   → data/prices.csv (+zmiany), data/runs.csv (+1 wiersz)
  3. python -m lcjfares.analyze   → site/data.json
  4. commit + push data/ (i site/data.json)
  5. deploy site/ na GitHub Pages (actions/deploy-pages)

lcjfares/
  ryanair.py    kopia ryanair_client.py ze skyskaner (cheapest_per_day, routes_from) + retry
  collect.py    pobranie snapshotu, porównanie z ostatnim znanym stanem, dopisanie zmian
  store.py      odczyt/zapis CSV (ostatni stan per lot, dopisywanie, runs.csv)
  analyze.py    agregaty → data.json
site/index.html statyczna strona czytająca data.json
tests/          pytest + fixtures (zapisane prawdziwe odpowiedzi API)
```

Każdy moduł ma jedno zadanie: `ryanair` = sieć, `store` = pliki, `collect` = logika zmian,
`analyze` = statystyka. `collect` i `analyze` nie wiedzą o sobie nic poza formatem CSV.

## Model danych

**`data/prices.csv`** — dziennik zmian (append-only):

| kolumna | przykład | opis |
|---|---|---|
| `observed` | `2026-09-25` | data obserwacji (UTC) |
| `origin` | `LCJ` | |
| `dest` | `STN` | |
| `day` | `2026-11-01` | data lotu |
| `dep_time` | `13:40` | godzina odlotu (pusta, gdy brak lotu) |
| `price` | `394.24` | pusta, gdy brak ceny |
| `status` | `ok` / `unavailable` / `soldout` | z pól `unavailable`, `soldOut` odpowiedzi API |

Wiersz dopisujemy tylko, gdy dla klucza `(origin, dest, day)` zmieniła się któraś z wartości
`(dep_time, price, status)` względem ostatniego wiersza tego klucza — lub klucz pojawia się pierwszy raz.
Ponowne uruchomienie tego samego dnia nie dubluje wierszy (idempotencja: brak zmiany ⇒ brak wiersza).

**`data/runs.csv`** — jeden wiersz na uruchomienie:
`observed, started_utc, requests, failed, status (ok|partial|failed), routes, missing` —
`routes` = `;`-lista kierunków próbowanych w runie (odróżnia „nie próbowano” od „bez zmian”),
`missing` = lista `ORIGIN-DEST-YYYY-MM`, których nie pobrano.

**`data/routes.json`** — ostatnia udanie pobrana lista kierunków z LCJ (fallback, gdy API tras zawiedzie).

Rekonstrukcja: cena lotu `k` w dniu `d` = ostatni wiersz `k` z `observed ≤ d`, **o ile** `d` było dniem
z udanym pobraniem danego `ORIGIN-DEST-miesiąc` (wg `runs.csv`); w przeciwnym razie brak pomiaru.

## Analiza (`site/data.json`)

Per kierunek:

- **Heatmapa** dzień tygodnia × miesiąc lotu → mediana „wartości lotu” + `n` (liczba lotów), gdzie wartość lotu =
  mediana jego cen zmierzonych 31–60 dni przed wylotem (stałe wyprzedzenie → miesiące porównywalne; loty bez
  pomiaru w tym oknie pomijane). Plus marginesy „razem”: per dzień tygodnia i per miesiąc.
- **Krzywa „kiedy kupować”** — dla każdego lotu i każdego dnia pomiaru: `days_before = day − observed`;
  mediana ceny w koszykach dni do wylotu (0–7, 8–14, 15–30, 31–60, 61–90, 91–180, 181+) + `n` (liczba różnych lotów).
  Dodatkowo wskaźnik relatywny: cena / minimalna cena tego lotu w historii — pokazuje, o ile drożeje.
- **Najtańsze nadchodzące loty** — top 10 cen z ostatniego udanego pomiaru (loty od jutra) + odchylenie od mediany trasy (%).
- **„Cena normalna”** trasy — mediana i kwartyle tych samych cen (ostatni udany pomiar).
- **Wyjazdy z Łodzi (tam + powrót)** — dla każdego kierunku X i każdego dnia wylotu LCJ→X (ostatni udany
  pomiar, loty od jutra) najtańszy powrót X→LCJ 3–10 dni później; top 10 par na kierunek + „typowy wyjazd”
  (mediana/kwartyle sum najlepszych par) + ranking top 10 ze wszystkich kierunków (max 3 na kierunek). Przy równej cenie preferowany wyjazd obejmujący
  weekend (cała sobota i niedziela w trakcie pobytu) — przy wyborze powrotu i w rankingach. Tylko najtańszy lot dnia (ograniczenie API).

Wyniki z małą próbą (`n` poniżej progu, domyślnie 5; komórki heatmapy: 3) są wyszarzone na stronie.
Krzywa jest wyszarzona z ostrzeżeniem, dopóki historia ma mniej niż 30 dni.

## Strona (`site/index.html`)

Pojedynczy statyczny plik, Chart.js z CDN, wybór kierunku z listy. Widoki: ranking najtańszych wyjazdów z Łodzi (wszystkie kierunki), wyjazdy na wybrany kierunek, heatmapa (z wierszem i kolumną „razem”), krzywa
„kiedy kupować”, tabela najtańszych lotów. Na górze: data ostatniego udanego pobrania i liczba dni historii.
Działa na telefonie.

## Obsługa błędów

- Każde zapytanie: do 3 prób z rosnącym odstępem; pauza 0,5–1 s między zapytaniami.
- Częściowa porażka: zapisujemy, co się udało; `runs.csv status=partial` + `missing`. Luki nie są
  interpretowane jako „bez zmian”.
- > 50% zapytań nieudanych (403/429/zmieniony JSON) ⇒ zapis `status=failed`, job kończy się błędem
  (GitHub mailuje o nieudanym workflow). Commit `runs.csv` mimo to, żeby luka była widoczna.
- Zmiana schematu odpowiedzi (brak oczekiwanych pól) traktowana jak błąd zapytania, nie jak brak lotu.
- Lista tras z API pusta/nieudana ⇒ fallback do ostatniej znanej listy (zapisanej w `data/routes.json`).
- `concurrency` w workflow uniemożliwia równoległe commity.
- Scheduled workflows są wyłączane po 60 dniach bez aktywności repo — codzienne commity danych
  temu zapobiegają.

## Testy

- `store`/`collect`: dopisywanie tylko zmian; poprawne statusy `unavailable`/`soldout`; idempotencja
  podwójnego uruchomienia; zapis `partial`/`failed` w `runs.csv`.
- Parser: na fixture z prawdziwą odpowiedzią `cheapestPerDay` (bez sieci).
- `analyze`: mediany, koszyki `days_before`, rekonstrukcja z luką — na małym ręcznym zbiorze.
- Smoke test na żywo: przy pierwszym wdrożeniu ręczny `workflow_dispatch` — weryfikacja, że Ryanair nie
  blokuje IP runnerów GitHub (Azure). Jeśli blokuje — projekt wraca do decyzji o miejscu uruchamiania.

## Ryzyka

- Ryanair może zmienić/zablokować nieoficjalne API lub IP GitHub — wykrywane przez `status=failed`.
- `cheapestPerDay` zwraca najtańszy lot dnia, nie wszystkie loty — przy 1 locie dziennie (typowo LCJ)
  to bez znaczenia; przy kilku lotach krzywa dotyczy „najtańszej opcji dnia”.
- Wiarygodne wnioski o krzywej „kiedy kupować” wymagają tygodni–miesięcy zbierania.
