"""Jednorazowa migracja: data/<HOME>/prices.csv → data/<HOME>/prices/YYYY-MM.csv (wg observed).

Użycie: python tools/split_prices.py [data_root]
"""
import sys
from pathlib import Path

from lcjfares import store


def split(data_dir: Path) -> None:
    old = data_dir / "prices.csv"
    if not old.exists():
        return
    if (data_dir / "prices").exists():
        sys.exit(f"{data_dir}/prices/ już istnieje — przerywam")
    n = 0
    batch = []
    for r in store.iter_prices(old):
        batch.append(r)
        n += 1
        if len(batch) >= 100_000:
            store.append_monthly(data_dir, batch)
            batch = []
    store.append_monthly(data_dir, batch)
    if sum(1 for _ in store.iter_all_prices(data_dir)) != n:
        sys.exit(f"{data_dir}: liczba wierszy się nie zgadza — zostawiam prices.csv")
    old.unlink()
    print(f"{data_dir}: {n} wierszy → {sorted(p.name for p in (data_dir / 'prices').glob('*.csv'))}")


if __name__ == "__main__":
    for d in sorted(Path(sys.argv[1] if len(sys.argv) > 1 else "data").iterdir()):
        if d.is_dir():
            split(d)
