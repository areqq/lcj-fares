"""Codzienny zbiór dla jednego lotniska: kalendarz cheapestPerDay wszystkich kierunków z/do niego → zmiany w data/<HOME>/prices.csv."""
from __future__ import annotations

import datetime as dt
import random
import sys
import time
from pathlib import Path

import curl_cffi

from lcjfares import ryanair, store

MONTHS = 12
MAX_CONSECUTIVE_FAILURES = 10


def months_ahead(today: dt.date, n: int = MONTHS) -> list[str]:
    y, m, out = today.year, today.month, []
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}-01")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def directions(routes: list[str], home: str) -> list[tuple[str, str]]:
    out = []
    for d in sorted(routes):
        out += [(home, d), (d, home)]
    return out


def public_ip() -> str:
    """Publiczne IP runnera (do analizy blokad); puste, gdy się nie da."""
    try:
        return curl_cffi.get("https://ifconfig.me/ip", timeout=5).text.strip()[:64]
    except Exception:
        return ""


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


def _routes(data_dir: Path, home: str, sleep) -> list[str]:
    try:
        info = ryanair.routes_info(home, sleep=sleep)
        if not info:
            raise ryanair.ApiError("pusta lista tras")
    except ryanair.ApiError as e:
        print(f"trasy z API niedostępne ({e}) — używam zapisanej listy", file=sys.stderr)
        return store.load_routes(data_dir / "routes.json")
    store.save_routes(data_dir / "routes.json", list(info))
    store.save_airports(data_dir / "airports.json", {**store.load_airports(data_dir / "airports.json"), **info})
    return list(info)


def run(data_dir: Path, now: dt.datetime, home: str, *, pause=(0.5, 1.0), sleep=time.sleep) -> dict:
    today = now.date()
    observed = today.isoformat()
    prices_path = data_dir / "prices.csv"
    ip = public_ip()
    print(f"{home}: publiczne IP runnera: {ip or '?'}")
    routes = _routes(data_dir, home, sleep)
    state = store.last_state(store.iter_prices(prices_path))

    snapshot, missing, requests, streak = [], [], 0, 0
    for origin, dest in directions(routes, home):
        for month in months_ahead(today):
            requests += 1
            if streak >= MAX_CONSECUTIVE_FAILURES:  # API leży — nie męczymy go dalej
                missing.append(f"{origin}-{dest}-{month[:7]}")
                continue
            try:
                fares = ryanair.cheapest_per_day(origin, dest, month, sleep=sleep)
            except ryanair.ApiError as e:
                print(f"{origin}-{dest} {month[:7]}: {e}", file=sys.stderr)
                missing.append(f"{origin}-{dest}-{month[:7]}")
                streak += 1
                if streak == MAX_CONSECUTIVE_FAILURES:
                    print(f"przerywam po {streak} kolejnych błędach", file=sys.stderr)
            else:
                streak = 0
                # API zwraca też minione dni bieżącego miesiąca (jako unavailable) — pomijamy
                snapshot += [(origin, dest, f) for f in fares
                             if f.day >= observed and f.day[:7] == month[:7]]
            sleep(random.uniform(*pause))

    store.append_prices(prices_path, diff_rows(snapshot, state, observed))
    failed = len(missing)
    status = "failed" if requests == 0 or failed * 2 > requests else "partial" if failed else "ok"
    run_row = {"observed": observed, "started_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
               "requests": requests, "failed": failed, "status": status,
               "routes": ";".join(sorted(routes)), "missing": ";".join(missing), "ip": ip}
    store.append_run(data_dir / "runs.csv", run_row)
    return run_row


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print("użycie: python -m lcjfares.collect HOME [data_root]", file=sys.stderr)
        return 2
    home = argv[0].upper()
    root = Path(argv[1] if len(argv) > 1 else "data")
    r = run(root / home, dt.datetime.now(dt.timezone.utc), home)
    print(f"{home} {r['status']}: {r['requests']} zapytań, {r['failed']} nieudanych")
    return 1 if r["status"] == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())
