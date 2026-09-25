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
                   "min_n": 5, "min_n_cell": 3, "min_history_days": 30, "trip_nights": [3, 10],
                   "routes": {}, "trips": {}, "trips_top": []}


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
    # heatmapa: mediana ceny lotu w oknie 31–60 dni przed wylotem
    heat = {(c["month"], c["weekday"]): c for c in r["heatmap"]}
    assert len(heat) == 3
    wd = lambda d: dt.date.fromisoformat(d).weekday()
    assert heat[("2026-10", wd("2026-10-06"))] == {
        "month": "2026-10", "weekday": wd("2026-10-06"), "median": 200.0, "n": 1}
    assert heat[("2026-10", wd("2026-10-07"))]["median"] == 300.0
    assert heat[("2026-10", wd("2026-10-08"))]["median"] == 50.0
    assert r["heatmap_month"] == [{"month": "2026-10", "median": 200.0, "n": 3}]
    assert sorted(c["weekday"] for c in r["heatmap_weekday"]) == sorted(
        wd(d) for d in ("2026-10-06", "2026-10-07", "2026-10-08"))
    # n = liczba różnych lotów (3), nie liczba obserwacji (12)
    assert r["curve"] == [{"bucket": "31-60", "median": 200.0, "ratio": 1.0, "n": 3}]


def test_cheapest_skips_month_missing_on_latest_run():
    prices = [p("2026-09-01", "2026-10-10", "100.00")]
    runs = [run("2026-09-01"), run("2026-09-02", missing="LCJ-STN-2026-10", status="partial")]
    r = analyze.build(prices, runs, dt.date(2026, 9, 2))["routes"]["LCJ-STN"]
    assert r["cheapest"] == [] and r["normal"]["n"] == 0


def test_cheapest_skips_route_dropped_from_latest_run():
    prices = [p("2026-09-01", "2026-10-10", "100.00", dest="DUB"),
              p("2026-09-01", "2026-10-11", "120.00")]
    runs = [run("2026-09-01", routes="DUB;STN"), run("2026-09-02", routes="STN")]
    out = analyze.build(prices, runs, dt.date(2026, 9, 2))["routes"]
    assert out["LCJ-DUB"]["cheapest"] == []
    assert [c["day"] for c in out["LCJ-STN"]["cheapest"]] == ["2026-10-11"]


def test_build_multi_route_keeps_routes_separate():
    prices = [p("2026-09-01", "2026-10-10", "100.00"),
              p("2026-09-01", "2026-10-11", "200.00", dest="DUB")]
    out = analyze.build(prices, [run("2026-09-01", routes="DUB;STN")], dt.date(2026, 9, 1))["routes"]
    assert [c["day"] for c in out["LCJ-STN"]["cheapest"]] == ["2026-10-10"]
    assert [c["day"] for c in out["LCJ-DUB"]["cheapest"]] == ["2026-10-11"]


def test_todays_flight_is_not_upcoming():
    prices = [p("2026-09-01", "2026-09-05", "100.00")]
    runs = [run(f"2026-09-0{d}") for d in range(1, 6)]
    assert analyze.build(prices, runs, dt.date(2026, 9, 5))["routes"]["LCJ-STN"]["cheapest"] == []


def test_curve_n_counts_distinct_flights():
    prices = [p("2026-09-01", "2026-10-10", "100.00")]
    runs = [run("2026-09-01"), run("2026-09-02"), run("2026-09-03")]
    curve = analyze.build(prices, runs, dt.date(2026, 9, 3))["routes"]["LCJ-STN"]["curve"]
    assert curve == [{"bucket": "31-60", "median": 100.0, "ratio": 1.0, "n": 1}]


def test_heatmap_uses_lead_time_window_and_margins():
    prices = [
        p("2026-09-10", "2026-10-20", "200.00"),  # 40 dni przed
        p("2026-09-15", "2026-10-20", "100.00"),  # 35 dni przed → wartość lotu 150
        p("2026-09-10", "2026-09-30", "80.00"),   # 20 dni przed → poza oknem
        p("2026-09-15", "2026-11-10", "300.00"),  # 56 dni przed
    ]
    runs = [run("2026-09-10"), run("2026-09-15")]
    r = analyze.build(prices, runs, dt.date(2026, 9, 15))["routes"]["LCJ-STN"]
    tue = dt.date(2026, 10, 20).weekday()
    assert dt.date(2026, 11, 10).weekday() == tue
    assert r["heatmap"] == [{"month": "2026-10", "weekday": tue, "median": 150.0, "n": 1},
                            {"month": "2026-11", "weekday": tue, "median": 300.0, "n": 1}]
    assert r["heatmap_month"] == [{"month": "2026-10", "median": 150.0, "n": 1},
                                  {"month": "2026-11", "median": 300.0, "n": 1}]
    assert r["heatmap_weekday"] == [{"weekday": tue, "median": 225.0, "n": 2}]


def test_main_writes_json(tmp_path):
    store.append_prices(tmp_path / "prices.csv", [p("2026-09-01", "2026-10-10", "100.00")])
    store.append_run(tmp_path / "runs.csv", run("2026-09-01"))
    out = tmp_path / "site" / "data.json"
    assert analyze.main([str(tmp_path), str(out)]) == 0
    data = json.loads(out.read_text())
    assert "LCJ-STN" in data["routes"]


def test_pair_trips_picks_cheapest_return_within_window():
    out = [("2026-10-10", "06:00", 100.0)]
    ret = [("2026-10-12", "07:00", 10.0),   # 2 noce — za krótko
           ("2026-10-13", "08:00", 50.0),   # 3 noce
           ("2026-10-20", "09:00", 40.0),   # 10 nocy — najtaniej w oknie
           ("2026-10-21", "10:00", 5.0)]    # 11 nocy — za długo
    assert analyze.pair_trips(out, ret) == [{
        "out_day": "2026-10-10", "out_time": "06:00", "out_price": 100.0,
        "ret_day": "2026-10-20", "ret_time": "09:00", "ret_price": 40.0,
        "nights": 10, "total": 140.0}]


def test_pair_trips_tie_prefers_shorter_stay_and_skips_without_return():
    out = [("2026-10-10", "06:00", 100.0), ("2026-11-01", "06:00", 90.0)]
    ret = [("2026-10-14", "07:00", 40.0), ("2026-10-16", "07:00", 40.0)]
    trips = analyze.pair_trips(out, ret)
    assert [(t["out_day"], t["ret_day"], t["nights"]) for t in trips] == [("2026-10-10", "2026-10-14", 4)]


def test_build_trips_per_destination_and_top():
    prices = [
        p("2026-09-01", "2026-10-10", "100.00"),
        p("2026-09-01", "2026-10-15", "50.00", origin="STN", dest="LCJ"),
        p("2026-09-01", "2026-10-11", "30.00", dest="DUB"),
        p("2026-09-01", "2026-10-14", "20.00", origin="DUB", dest="LCJ"),
        p("2026-09-01", "2026-10-20", "10.00", dest="DUB"),              # brak powrotu
        p("2026-09-01", "2026-10-12", "", "soldout", origin="STN", dest="LCJ"),
    ]
    out = analyze.build(prices, [run("2026-09-01", routes="DUB;STN")], dt.date(2026, 9, 1))
    stn = out["trips"]["STN"]
    assert stn["normal"]["median"] == 150.0 and stn["normal"]["n"] == 1
    assert stn["best"] == [{"out_day": "2026-10-10", "out_time": "10:00", "out_price": 100.0,
                            "ret_day": "2026-10-15", "ret_time": "10:00", "ret_price": 50.0,
                            "nights": 5, "total": 150.0, "vs_median_pct": 0}]
    assert [t["out_day"] for t in out["trips"]["DUB"]["best"]] == ["2026-10-11"]
    assert [(t["dest"], t["total"]) for t in out["trips_top"]] == [("DUB", 50.0), ("STN", 150.0)]
    assert out["trip_nights"] == [3, 10]
