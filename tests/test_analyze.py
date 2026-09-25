import datetime as dt
import json

import pytest

from lcjfares import analyze, store


def p(observed, day, price, status="ok", dep="10:00", origin="LCJ", dest="STN"):
    return {"observed": observed, "origin": origin, "dest": dest, "day": day,
            "dep_time": dep, "price": price, "status": status}


def run(observed, routes="STN", missing="", status="ok"):
    return {"observed": observed, "started_utc": observed + "T06:00:00Z", "requests": "24",
            "failed": "0", "status": status, "routes": routes, "missing": missing}


@pytest.mark.parametrize("days,label", [
    (0, "0-7"), (7, "0-7"), (8, "8-14"), (30, "15-30"), (31, "31-60"),
    (90, "61-90"), (180, "91-180"), (181, "181+"), (400, "181+"), (-1, None)])
def test_bucket_label(days, label):
    assert analyze.bucket_label(days) == label


def test_reconstruct_carries_forward_and_respects_missing():
    prices = [p("2026-09-01", "2026-10-10", "100.00"), p("2026-09-03", "2026-10-10", "150.00")]
    runs = [run("2026-09-01"), run("2026-09-02"), run("2026-09-03"),
            run("2026-09-04", missing="LCJ-STN-2026-10", status="partial"), run("2026-09-05")]
    obs = analyze.reconstruct(prices, runs)
    assert [(o["observed"], o["price"]) for o in obs] == [
        ("2026-09-01", 100.0), ("2026-09-02", 100.0), ("2026-09-03", 150.0), ("2026-09-05", 150.0)]


def test_reconstruct_skips_route_not_attempted():
    prices = [p("2026-09-01", "2026-10-10", "100.00")]
    runs = [run("2026-09-01"), run("2026-09-02", routes="DUB")]
    assert [o["observed"] for o in analyze.reconstruct(prices, runs)] == ["2026-09-01"]


def test_reconstruct_stops_at_flight_day_and_before_first_row():
    prices = [p("2026-09-02", "2026-09-03", "100.00")]
    runs = [run("2026-09-01"), run("2026-09-02"), run("2026-09-03"), run("2026-09-04")]
    assert [o["observed"] for o in analyze.reconstruct(prices, runs)] == ["2026-09-02", "2026-09-03"]


def test_reconstruct_soldout_has_no_price():
    prices = [p("2026-09-01", "2026-10-10", "100.00"), p("2026-09-02", "2026-10-10", "", "soldout")]
    obs = analyze.reconstruct(prices, [run("2026-09-01"), run("2026-09-02")])
    assert [(o["price"], o["status"]) for o in obs] == [(100.0, "ok"), (None, "soldout")]


def test_build_empty():
    out = analyze.build([], [], dt.date(2026, 9, 25))
    assert out == {"generated": "2026-09-25", "last_ok": None, "history_days": 0,
                   "min_n": 5, "routes": {}}


def test_build_full():
    prices = [
        p("2026-09-01", "2026-10-06", "200.00"),
        p("2026-09-04", "2026-10-06", "100.00"),
        p("2026-09-01", "2026-10-07", "300.00"),
        p("2026-09-01", "2026-10-08", "50.00"),
        p("2026-09-03", "2026-10-08", "", "soldout", dep=""),
    ]
    runs = [run(f"2026-09-0{d}") for d in range(1, 6)] + [run("2026-09-06", status="failed", routes="")]
    out = analyze.build(prices, runs, dt.date(2026, 9, 5))
    assert out["last_ok"] == "2026-09-05" and out["history_days"] == 5
    r = out["routes"]["LCJ-STN"]
    assert r["normal"] == {"median": 200.0, "q1": 150.0, "q3": 250.0, "n": 2}
    assert r["cheapest"] == [
        {"day": "2026-10-06", "dep_time": "10:00", "price": 100.0, "vs_median_pct": -50},
        {"day": "2026-10-07", "dep_time": "10:00", "price": 300.0, "vs_median_pct": 50},
    ]
    heat = {(c["month"], c["weekday"]): c for c in r["heatmap"]}
    assert len(heat) == 3
    assert heat[("2026-10", dt.date(2026, 10, 6).weekday())] == {
        "month": "2026-10", "weekday": dt.date(2026, 10, 6).weekday(), "median": 100.0, "n": 1}
    assert heat[("2026-10", dt.date(2026, 10, 8).weekday())]["median"] == 50.0
    assert r["curve"] == [{"bucket": "31-60", "median": 200.0, "ratio": 1.0, "n": 12}]


def test_main_writes_json(tmp_path):
    store.append_prices(tmp_path / "prices.csv", [p("2026-09-01", "2030-01-01", "100.00")])
    store.append_run(tmp_path / "runs.csv", run("2026-09-01"))
    out = tmp_path / "site" / "data.json"
    assert analyze.main([str(tmp_path), str(out)]) == 0
    data = json.loads(out.read_text())
    assert "LCJ-STN" in data["routes"]
