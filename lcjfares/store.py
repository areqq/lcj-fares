"""Pliki danych: dziennik zmian cen (prices.csv), log uruchomień (runs.csv), lista tras (routes.json)."""
from __future__ import annotations

import csv
import json
from pathlib import Path

PRICE_FIELDS = ["observed", "origin", "dest", "day", "dep_time", "price", "status"]
RUN_FIELDS = ["observed", "started_utc", "requests", "failed", "status", "routes", "missing"]


def _read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _append(path: Path, fields: list[str], rows: list[dict]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        if new:
            w.writeheader()
        w.writerows(rows)


def read_prices(path: Path) -> list[dict]:
    return _read(path)


def read_runs(path: Path) -> list[dict]:
    return _read(path)


def append_prices(path: Path, rows: list[dict]) -> None:
    _append(path, PRICE_FIELDS, rows)


def append_run(path: Path, row: dict) -> None:
    _append(path, RUN_FIELDS, [row])


def last_state(rows: list[dict]) -> dict:
    """(origin, dest, day) -> (dep_time, price, status) z ostatniego wiersza (plik jest chronologiczny)."""
    return {(r["origin"], r["dest"], r["day"]): (r["dep_time"], r["price"], r["status"]) for r in rows}


def load_routes(path: Path) -> list[str]:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []


def save_routes(path: Path, routes: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted(routes)) + "\n", encoding="utf-8")
