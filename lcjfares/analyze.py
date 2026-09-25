"""Historia cen → agregaty dla strony (site/data.json)."""
from __future__ import annotations

import datetime as dt
import json
import statistics
import sys
from bisect import bisect_right
from collections import defaultdict
from pathlib import Path

from lcjfares import store

MIN_N = 5
HORIZON_MONTHS = 12
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


def reconstruct(prices: list[dict], runs: list[dict]) -> list[dict]:
    """Stan każdego lotu w każdym dniu, w którym był faktycznie mierzony (luki pomijane)."""
    hist = defaultdict(list)
    for r in prices:
        hist[(r["origin"], r["dest"], r["day"])].append(r)
    coverage = defaultdict(list)  # observed -> [(routes, missing)]
    for r in runs:
        coverage[r["observed"]].append((_split(r["routes"]), _split(r["missing"])))
    run_days = sorted(coverage)

    obs = []
    for (origin, dest, day), rows in hist.items():
        dates = [r["observed"] for r in rows]
        month_key = f"{origin}-{dest}-{day[:7]}"
        for d in run_days:
            if d < dates[0] or d > day or _month_index(day) - _month_index(d) >= HORIZON_MONTHS:
                continue
            if not any((origin in routes or dest in routes) and month_key not in missing
                       for routes, missing in coverage[d]):
                continue
            row = rows[bisect_right(dates, d) - 1]
            obs.append({"origin": origin, "dest": dest, "day": day, "observed": d,
                        "price": float(row["price"]) if row["price"] else None,
                        "status": row["status"]})
    return obs


def _median(vals):
    return round(statistics.median(vals), 2) if vals else None


def _stats(vals):
    if not vals:
        return {"median": None, "q1": None, "q3": None, "n": 0}
    q1 = q3 = vals[0]
    if len(vals) > 1:
        q1, _, q3 = statistics.quantiles(vals, n=4, method="inclusive")
    return {"median": _median(vals), "q1": round(q1, 2), "q3": round(q3, 2), "n": len(vals)}


def build(prices: list[dict], runs: list[dict], today: dt.date) -> dict:
    t = today.isoformat()
    state = store.last_state(prices)
    last_priced = {}  # ostatnia znana cena lotu (także lotów już odbytych / wyprzedanych)
    for r in prices:
        if r["price"]:
            last_priced[(r["origin"], r["dest"], r["day"])] = r
    obs = [o for o in reconstruct(prices, runs) if o["price"] is not None]
    min_price = {}
    for o in obs:
        k = (o["origin"], o["dest"], o["day"])
        min_price[k] = min(min_price.get(k, o["price"]), o["price"])

    routes = defaultdict(lambda: {"heat": defaultdict(list), "upcoming": [],
                                  "curve": defaultdict(lambda: ([], []))})
    for (origin, dest, day), r in last_priced.items():
        routes[f"{origin}-{dest}"]["heat"][(day[:7], _date(day).weekday())].append(float(r["price"]))
    for (origin, dest, day), (dep, price, status) in state.items():
        if status == "ok" and price and day >= t:
            routes[f"{origin}-{dest}"]["upcoming"].append((day, dep, float(price)))
    for o in obs:
        label = bucket_label((_date(o["day"]) - _date(o["observed"])).days)
        if label is None:
            continue
        ps, ratios = routes[f"{o['origin']}-{o['dest']}"]["curve"][label]
        ps.append(o["price"])
        ratios.append(o["price"] / min_price[(o["origin"], o["dest"], o["day"])])

    out = {}
    for name in sorted(routes):
        r = routes[name]
        normal = _stats([p for _, _, p in r["upcoming"]])
        med = normal["median"]
        out[name] = {
            "normal": normal,
            "heatmap": [{"month": m, "weekday": wd, "median": _median(v), "n": len(v)}
                        for (m, wd), v in sorted(r["heat"].items())],
            "curve": [{"bucket": lb, "median": _median(r["curve"][lb][0]),
                       "ratio": round(statistics.median(r["curve"][lb][1]), 3),
                       "n": len(r["curve"][lb][0])}
                      for lb in LABELS if lb in r["curve"]],
            "cheapest": [{"day": d, "dep_time": dep, "price": p,
                          "vs_median_pct": round((p / med - 1) * 100) if med else None}
                         for d, dep, p in sorted(r["upcoming"], key=lambda x: (x[2], x[0]))[:10]],
        }
    ok_days = sorted({r["observed"] for r in runs if r["status"] != "failed"})
    return {"generated": t, "last_ok": ok_days[-1] if ok_days else None,
            "history_days": len(ok_days), "min_n": MIN_N, "routes": out}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    data_dir = Path(argv[0] if argv else "data")
    out_path = Path(argv[1] if len(argv) > 1 else "site/data.json")
    data = build(store.read_prices(data_dir / "prices.csv"), store.read_runs(data_dir / "runs.csv"),
                 dt.datetime.now(dt.timezone.utc).date())
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{out_path}: {len(data['routes'])} kierunków, {data['history_days']} dni historii")
    return 0


if __name__ == "__main__":
    sys.exit(main())
