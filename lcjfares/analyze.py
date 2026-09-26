"""Historia cen → agregaty dla strony (site/data.json)."""
from __future__ import annotations

import datetime as dt
import json
import statistics
import sys
from bisect import bisect_left, bisect_right
from collections import defaultdict
from pathlib import Path

from lcjfares import store

MIN_N = 5
MIN_N_CELL = 3            # heatmapa: miesiąc ma tylko 4–5 danego dnia tygodnia
MIN_HISTORY_DAYS = 30     # krzywa „kiedy kupować” wiarygodna dopiero po takiej historii
HEAT_WINDOW = (31, 60)    # heatmapa: cena lotu na 31–60 dni przed wylotem (porównywalne miesiące)
HORIZON_MONTHS = 12
TRIP_NIGHTS = (3, 10)     # wyjazd z Łodzi: powrót 3–10 dni po wylocie
TOP_PER_DEST = 3          # ranking łączny: max tyle wyjazdów na kierunek (różnorodność)
BUCKETS = [(0, 7), (8, 14), (15, 30), (31, 60), (61, 90), (91, 180), (181, None)]
LABELS = [f"{lo}+" if hi is None else f"{lo}-{hi}" for lo, hi in BUCKETS]


def _date(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def _month_index(s: str) -> int:
    return int(s[:4]) * 12 + int(s[5:7])


def bucket_label(days: int) -> str | None:
    for (lo, hi), label in zip(BUCKETS, LABELS):
        if days >= lo and (hi is None or days <= hi):
            return label
    return None


def _split(s: str) -> set[str]:
    return set(filter(None, s.split(";")))


def iter_flights(prices, runs: list[dict]):
    """Po jednym locie: ((origin, dest, day), [obserwacje]) — stan lotu w każdym dniu, w którym był
    faktycznie mierzony (luki pomijane). `prices` czytane jednokrotnie, wiersze trzymane jako krotki."""
    intern = {}
    s_ = lambda v: intern.setdefault(v, v)
    hist = defaultdict(list)
    for r in prices:
        hist[(s_(r["origin"]), s_(r["dest"]), s_(r["day"]))].append(
            (s_(r["observed"]), s_(r["dep_time"]), float(r["price"]) if r["price"] else None, s_(r["status"])))
    coverage = defaultdict(list)  # observed -> [(routes, missing)]
    for r in runs:
        coverage[r["observed"]].append((_split(r["routes"]), _split(r["missing"])))
    run_days = sorted(coverage)

    for (origin, dest, day), rows in hist.items():
        dates = [r[0] for r in rows]
        month_key = f"{origin}-{dest}-{day[:7]}"
        obs = []
        for d in run_days[bisect_left(run_days, dates[0]):bisect_right(run_days, day)]:
            if _month_index(day) - _month_index(d) >= HORIZON_MONTHS:
                continue
            if not any((origin in routes or dest in routes) and month_key not in missing
                       for routes, missing in coverage[d]):
                continue
            _, dep, price, status = rows[bisect_right(dates, d) - 1]
            obs.append({"origin": origin, "dest": dest, "day": day, "observed": d,
                        "price": price, "status": status, "dep_time": dep})
        yield (origin, dest, day), obs


def reconstruct(prices, runs: list[dict]) -> list[dict]:
    return [o for _, obs in iter_flights(prices, runs) for o in obs]


def _median(vals):
    return round(statistics.median(vals), 2) if vals else None


def _stats(vals):
    if not vals:
        return {"median": None, "q1": None, "q3": None, "n": 0}
    q1 = q3 = vals[0]
    if len(vals) > 1:
        q1, _, q3 = statistics.quantiles(vals, n=4, method="inclusive")
    return {"median": _median(vals), "q1": round(q1, 2), "q3": round(q3, 2), "n": len(vals)}


def covers_weekend(out_day: str, ret_day: str) -> bool:
    """Czy pobyt obejmuje całą sobotę i niedzielę (wylot najpóźniej w sobotę, powrót najwcześniej w niedzielę)."""
    out, ret = _date(out_day), _date(ret_day)
    sat = out + dt.timedelta(days=(5 - out.weekday()) % 7)
    return sat + dt.timedelta(days=1) <= ret


def _trip_key(total, weekend):
    return (total, not weekend)  # przy równej cenie wygrywa wyjazd z weekendem


def pair_trips(out_fares, ret_fares, nights=TRIP_NIGHTS) -> list[dict]:
    """Dla każdego dnia wylotu najtańszy powrót za `nights` dni. Fares: [(day, dep_time, price)]."""
    returns = {day: (dep, price) for day, dep, price in ret_fares}
    trips = []
    for day, dep, price in out_fares:
        best = None
        for k in range(nights[0], nights[1] + 1):
            rd = (_date(day) + dt.timedelta(days=k)).isoformat()
            if rd not in returns:
                continue
            cand = (rd, returns[rd][0], returns[rd][1], k, covers_weekend(day, rd))
            if best is None or _trip_key(cand[2], cand[4]) < _trip_key(best[2], best[4]):
                best = cand
        if best:
            trips.append({"out_day": day, "out_time": dep, "out_price": price,
                          "ret_day": best[0], "ret_time": best[1], "ret_price": best[2],
                          "nights": best[3], "total": round(price + best[2], 2), "weekend": best[4]})
    return trips


def _vs(p, med):
    return round((p / med - 1) * 100) if med else None


def build(prices, runs: list[dict], today: dt.date, home: str = "LCJ", airports: dict | None = None) -> dict:
    t = today.isoformat()
    ok_days = sorted({r["observed"] for r in runs if r["status"] != "failed"})
    last_ok = ok_days[-1] if ok_days else None

    routes = defaultdict(lambda: {"cells": defaultdict(list), "upcoming": [],
                                  "curve": defaultdict(lambda: ([], []))})
    for (origin, dest, day), fobs in iter_flights(prices, runs):
        priced = [o for o in fobs if o["price"] is not None]
        if not priced:
            continue
        r = routes[f"{origin}-{dest}"]
        low = min(o["price"] for o in priced)
        window, buckets = [], defaultdict(list)
        for o in priced:
            days = (_date(day) - _date(o["observed"])).days
            if HEAT_WINDOW[0] <= days <= HEAT_WINDOW[1]:
                window.append(o["price"])
            # „nadchodzące” tylko z ostatniego udanego pomiaru (luki i zniknięte trasy odpadają)
            if o["observed"] == last_ok and o["status"] == "ok" and day > t:
                r["upcoming"].append((day, o["dep_time"], o["price"]))
            label = bucket_label(days)
            if label is not None:
                buckets[label].append(o["price"])
        if window:
            r["cells"][(day[:7], _date(day).weekday())].append(statistics.median(window))
        # krzywa: najpierw mediana w obrębie lotu, potem po lotach — każdy lot waży tyle samo
        for label, ps in buckets.items():
            m = statistics.median(ps)
            r["curve"][label][0].append(m)
            r["curve"][label][1].append(m / low)

    out = {}
    for name in sorted(routes):
        r = routes[name]
        normal = _stats([p for _, _, p in r["upcoming"]])
        med = normal["median"]
        by_wd, by_month = defaultdict(list), defaultdict(list)
        for (m, wd), vs in r["cells"].items():
            by_wd[wd] += vs
            by_month[m] += vs
        out[name] = {
            "normal": normal,
            "heatmap": [{"month": m, "weekday": wd, "median": _median(v), "n": len(v)}
                        for (m, wd), v in sorted(r["cells"].items())],
            "heatmap_weekday": [{"weekday": wd, "median": _median(v), "n": len(v)}
                                for wd, v in sorted(by_wd.items())],
            "heatmap_month": [{"month": m, "median": _median(v), "n": len(v)}
                              for m, v in sorted(by_month.items())],
            "curve": [{"bucket": lb, "median": _median(r["curve"][lb][0]),
                       "ratio": round(statistics.median(r["curve"][lb][1]), 3),
                       "n": len(r["curve"][lb][0])}  # liczba lotów
                      for lb in LABELS if lb in r["curve"]],
            # pełny kalendarz z ostatniego pomiaru — strona składa z niego pary wylot + powroty
            "calendar": [[d, dep, p] for d, dep, p in sorted(r["upcoming"])],
            "cheapest": [{"day": d, "dep_time": dep, "price": p, "vs_median_pct": _vs(p, med)}
                         for d, dep, p in sorted(r["upcoming"], key=lambda x: (x[2], x[0]))[:10]],
        }

    trips, top = {}, []
    for name in sorted(routes):
        origin, dest = name.split("-")
        if origin != home or f"{dest}-{home}" not in routes:
            continue
        pairs = pair_trips(routes[name]["upcoming"], routes[f"{dest}-{home}"]["upcoming"])
        normal = _stats([x["total"] for x in pairs])
        best = [{**x, "vs_median_pct": _vs(x["total"], normal["median"])}
                for x in sorted(pairs, key=lambda x: (*_trip_key(x["total"], x["weekend"]), x["out_day"]))]
        trips[dest] = {"normal": normal, "best": best[:10]}
        top += [{"dest": dest, **x} for x in best[:TOP_PER_DEST]]
    top.sort(key=lambda x: (*_trip_key(x["total"], x["weekend"]), x["out_day"], x["dest"]))
    codes = {c for name in routes for c in name.split("-")}
    return {"generated": t, "last_ok": last_ok, "history_days": len(ok_days),
            "min_n": MIN_N, "min_n_cell": MIN_N_CELL, "min_history_days": MIN_HISTORY_DAYS,
            "trip_nights": list(TRIP_NIGHTS), "home": home,
            "airports": {c: a for c, a in sorted((airports or {}).items()) if c in codes},
            "routes": out, "trips": trips, "trips_top": top[:10]}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print("użycie: python -m lcjfares.analyze HOME [data_root] [site_dir]", file=sys.stderr)
        return 2
    home = argv[0].upper()
    data_dir = Path(argv[1] if len(argv) > 1 else "data") / home
    out_path = Path(argv[2] if len(argv) > 2 else "site") / "data" / f"{home}.json"
    data = build(store.iter_prices(data_dir / "prices.csv"), store.read_runs(data_dir / "runs.csv"),
                 dt.datetime.now(dt.timezone.utc).date(), home, store.load_airports(data_dir / "airports.json"))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{out_path}: {len(data['routes'])} kierunków, {data['history_days']} dni historii")
    return 0


if __name__ == "__main__":
    sys.exit(main())
