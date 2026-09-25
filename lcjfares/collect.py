"""Codzienny zbiór: kalendarz cheapestPerDay dla wszystkich kierunków z/do LCJ → zmiany w data/prices.csv."""
from __future__ import annotations

import datetime as dt
import random
import sys
import time
from pathlib import Path

from lcjfares import ryanair, store

HOME = "LCJ"
MONTHS = 12


def months_ahead(today: dt.date, n: int = MONTHS) -> list[str]:
    y, m, out = today.year, today.month, []
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}-01")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def directions(routes: list[str]) -> list[tuple[str, str]]:
    out = []
    for d in sorted(routes):
        out += [(HOME, d), (d, HOME)]
    return out


def diff_rows(snapshot, state: dict, observed: str) -> list[dict]:
    """Wiersze tylko dla kluczy nowych albo ze zmienioną (dep_time, price, status). Aktualizuje `state`."""
    rows = []
    for origin, dest, fare in snapshot:
        key = (origin, dest, fare.day)
        val = (fare.dep_time, fare.price, fare.status)
        if state.get(key) != val:
            rows.append({"observed": observed, "origin": origin, "dest": dest, "day": fare.day,
                         "dep_time": fare.dep_time, "price": fare.price, "status": fare.status})
            state[key] = val
    return rows


def _routes(routes_path: Path, sleep) -> list[str]:
    try:
        routes = ryanair.routes_from(HOME, sleep=sleep)
        if not routes:
            raise ryanair.ApiError("pusta lista tras")
    except ryanair.ApiError as e:
        print(f"trasy z API niedostępne ({e}) — używam zapisanej listy", file=sys.stderr)
        return store.load_routes(routes_path)
    store.save_routes(routes_path, routes)
    return routes


def run(data_dir: Path, now: dt.datetime, *, pause=(0.5, 1.0), sleep=time.sleep) -> dict:
    today = now.date()
    observed = today.isoformat()
    prices_path = data_dir / "prices.csv"
    routes = _routes(data_dir / "routes.json", sleep)
    state = store.last_state(store.read_prices(prices_path))

    snapshot, missing, requests = [], [], 0
    for origin, dest in directions(routes):
        for month in months_ahead(today):
            requests += 1
            try:
                fares = ryanair.cheapest_per_day(origin, dest, month, sleep=sleep)
            except ryanair.ApiError as e:
                print(f"{origin}-{dest} {month[:7]}: {e}", file=sys.stderr)
                missing.append(f"{origin}-{dest}-{month[:7]}")
            else:
                # API zwraca też minione dni bieżącego miesiąca (jako unavailable) — pomijamy
                snapshot += [(origin, dest, f) for f in fares
                             if f.day >= observed and f.day[:7] == month[:7]]
            sleep(random.uniform(*pause))

    store.append_prices(prices_path, diff_rows(snapshot, state, observed))
    failed = len(missing)
    status = "failed" if requests == 0 or failed * 2 > requests else "partial" if failed else "ok"
    run_row = {"observed": observed, "started_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
               "requests": requests, "failed": failed, "status": status,
               "routes": ";".join(sorted(routes)), "missing": ";".join(missing)}
    store.append_run(data_dir / "runs.csv", run_row)
    return run_row


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    data_dir = Path(argv[0] if argv else "data")
    r = run(data_dir, dt.datetime.now(dt.timezone.utc))
    print(f"{r['status']}: {r['requests']} zapytań, {r['failed']} nieudanych")
    return 1 if r["status"] == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())
