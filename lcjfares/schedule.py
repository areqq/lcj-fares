"""Które lotnisko zmierzyć teraz: spośród dawno niemierzonych losowo jedno z 2 najstarszych.

Cron odpala się co 2 h; opóźnione/pominięte/nieudane uruchomienie nadrabia następne.
Tylko biblioteka standardowa — działa przed instalacją zależności.
"""
from __future__ import annotations

import datetime as dt
import random
import sys
from pathlib import Path

from lcjfares import store

AIRPORTS = ["LCJ", "KTW", "WRO", "WMI", "BZG"]
MIN_AGE_OK = dt.timedelta(hours=18)   # ostatni udany pomiar starszy niż to → lotnisko do zrobienia
MIN_AGE_TRY = dt.timedelta(hours=4)   # po każdej próbie (także nieudanej) odczekaj — nie dobijamy się przy blokadzie
NEVER = dt.datetime.min.replace(tzinfo=dt.timezone.utc)


def _ts(s: str) -> dt.datetime:
    return dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)


def last_times(runs: list[dict]) -> tuple[dt.datetime | None, dt.datetime | None]:
    """(ostatni udany pomiar, ostatnia próba) — udany = status różny od failed."""
    ok = [_ts(r["started_utc"]) for r in runs if r["status"] != "failed"]
    tried = [_ts(r["started_utc"]) for r in runs]
    return (max(ok) if ok else None), (max(tried) if tried else None)


def pick(data_root: Path, now: dt.datetime, airports=AIRPORTS, rng=random) -> str | None:
    candidates = []
    for home in airports:
        ok, tried = last_times(store.read_runs(data_root / home / "runs.csv"))
        if ok and now - ok < MIN_AGE_OK:
            continue
        if tried and now - tried < MIN_AGE_TRY:
            continue
        candidates.append((ok or NEVER, home))
    if not candidates:
        return None
    candidates.sort()
    return rng.choice(candidates[:2])[1]


def main(argv: list[str] | None = None, now: dt.datetime | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    home = pick(Path(argv[0] if argv else "data"), now or dt.datetime.now(dt.timezone.utc))
    print(home or "")
    return 0


if __name__ == "__main__":
    sys.exit(main())
