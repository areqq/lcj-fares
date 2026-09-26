import calendar
import datetime as dt

from lcjfares import collect, ryanair, store
from lcjfares.ryanair import Fare

NOW = dt.datetime(2026, 9, 25, 6, 0, tzinfo=dt.timezone.utc)
NOSLEEP = {"pause": (0, 0), "sleep": lambda s: None}


def fake_api(monkeypatch, prices=None, routes=("STN",), fail=(), fail_all=False):
    """prices: {(origin, dest, day): "123.00"}; fail: {(origin, dest, "YYYY-MM")}."""
    prices = prices or {}

    def month(origin, dest, month, **kw):
        if fail_all or (origin, dest, month[:7]) in fail:
            raise ryanair.ApiError("boom")
        y, m = int(month[:4]), int(month[5:7])
        out = []
        for d in range(1, calendar.monthrange(y, m)[1] + 1):
            day = f"{y:04d}-{m:02d}-{d:02d}"
            p = prices.get((origin, dest, day))
            out.append(Fare(day, "10:00", p, "ok") if p else Fare(day, "", "", "unavailable"))
        return out

    monkeypatch.setattr(ryanair, "routes_info",
                        lambda origin, **kw: {c: {"name": f"Miasto {c}", "country": "gb"} for c in routes})
    monkeypatch.setattr(ryanair, "cheapest_per_day", month)
    monkeypatch.setattr(collect, "public_ip", lambda: "203.0.113.7")


def test_months_ahead():
    m = collect.months_ahead(dt.date(2026, 9, 25))
    assert len(m) == 12 and m[0] == "2026-09-01" and m[-1] == "2027-08-01"
    assert collect.months_ahead(dt.date(2026, 12, 3), 2) == ["2026-12-01", "2027-01-01"]


def test_directions_both_ways():
    assert collect.directions(["STN", "DUB"], "LCJ") == [
        ("LCJ", "DUB"), ("DUB", "LCJ"), ("LCJ", "STN"), ("STN", "LCJ")]


def test_first_run_writes_future_days_only(tmp_path, monkeypatch):
    fake_api(monkeypatch, {("LCJ", "STN", "2026-10-10"): "199.00"})
    r = collect.run(tmp_path, NOW, "LCJ", **NOSLEEP)
    rows = store.read_prices(tmp_path / "prices.csv")
    days = (dt.date(2027, 8, 31) - dt.date(2026, 9, 25)).days + 1
    assert len(rows) == 2 * days
    assert min(x["day"] for x in rows) == "2026-09-25"
    assert {"observed": "2026-09-25", "origin": "LCJ", "dest": "STN", "day": "2026-10-10",
            "dep_time": "10:00", "price": "199.00", "status": "ok"} in rows
    assert r["status"] == "ok" and r["requests"] == 24 and r["failed"] == 0
    assert r["routes"] == "STN" and r["missing"] == ""
    assert store.load_routes(tmp_path / "routes.json") == ["STN"]
    assert store.load_airports(tmp_path / "airports.json") == {"STN": {"name": "Miasto STN", "country": "gb"}}
    assert r["ip"] == "203.0.113.7"


def test_rerun_same_day_adds_no_price_rows(tmp_path, monkeypatch):
    fake_api(monkeypatch, {("LCJ", "STN", "2026-10-10"): "199.00"})
    collect.run(tmp_path, NOW, "LCJ", **NOSLEEP)
    n = len(store.read_prices(tmp_path / "prices.csv"))
    collect.run(tmp_path, NOW, "LCJ", **NOSLEEP)
    assert len(store.read_prices(tmp_path / "prices.csv")) == n
    assert len(store.read_runs(tmp_path / "runs.csv")) == 2


def test_next_day_appends_only_changes(tmp_path, monkeypatch):
    fake_api(monkeypatch, {("LCJ", "STN", "2026-10-10"): "199.00"})
    collect.run(tmp_path, NOW, "LCJ", **NOSLEEP)
    n = len(store.read_prices(tmp_path / "prices.csv"))
    fake_api(monkeypatch, {("LCJ", "STN", "2026-10-10"): "149.00"})
    collect.run(tmp_path, NOW + dt.timedelta(days=1), "LCJ", **NOSLEEP)
    rows = store.read_prices(tmp_path / "prices.csv")
    assert len(rows) == n + 1
    assert rows[-1]["observed"] == "2026-09-26" and rows[-1]["price"] == "149.00"


def test_partial_failure_recorded(tmp_path, monkeypatch):
    fake_api(monkeypatch, fail={("LCJ", "STN", "2026-11")})
    r = collect.run(tmp_path, NOW, "LCJ", **NOSLEEP)
    assert r["status"] == "partial" and r["failed"] == 1
    assert r["missing"] == "LCJ-STN-2026-11"
    rows = store.read_prices(tmp_path / "prices.csv")
    assert not [x for x in rows if x["origin"] == "LCJ" and x["day"].startswith("2026-11")]
    assert [x for x in rows if x["origin"] == "STN" and x["day"].startswith("2026-11")]


_real_run = collect.run


def test_majority_failure_is_failed_and_exit_1(tmp_path, monkeypatch):
    fake_api(monkeypatch, fail_all=True)
    monkeypatch.setattr(collect, "run", lambda d, now, home: _real_run(d, now, home, **NOSLEEP))
    assert collect.main(["LCJ", str(tmp_path)]) == 1
    runs = store.read_runs(tmp_path / "LCJ" / "runs.csv")
    assert runs[-1]["status"] == "failed" and runs[-1]["failed"] == "24"


def test_routes_fallback_to_saved_list(tmp_path, monkeypatch):
    fake_api(monkeypatch, routes=("STN", "DUB"))
    collect.run(tmp_path, NOW, "LCJ", **NOSLEEP)

    def boom(origin, **kw):
        raise ryanair.ApiError("down")

    monkeypatch.setattr(ryanair, "routes_info", boom)
    r = collect.run(tmp_path, NOW + dt.timedelta(days=1), "LCJ", **NOSLEEP)
    assert r["status"] == "ok" and r["routes"] == "DUB;STN" and r["requests"] == 48


def test_no_routes_at_all_is_failed(tmp_path, monkeypatch):
    fake_api(monkeypatch, routes=())
    r = collect.run(tmp_path, NOW, "LCJ", **NOSLEEP)
    assert r["status"] == "failed" and r["requests"] == 0


def test_circuit_breaker_stops_after_consecutive_failures(tmp_path, monkeypatch):
    calls = []

    def boom(origin, dest, month, **kw):
        calls.append((origin, dest, month))
        raise ryanair.ApiError("down")

    fake_api(monkeypatch)
    monkeypatch.setattr(ryanair, "cheapest_per_day", boom)
    r = collect.run(tmp_path, NOW, "LCJ", **NOSLEEP)
    assert len(calls) == collect.MAX_CONSECUTIVE_FAILURES == 10
    assert r["requests"] == 24 and r["failed"] == 24 and r["status"] == "failed"
    assert len(r["missing"].split(";")) == 24


def test_other_home_airport(tmp_path, monkeypatch):
    fake_api(monkeypatch, {("KTW", "STN", "2026-10-10"): "99.00"})
    assert collect.directions(["STN"], "KTW") == [("KTW", "STN"), ("STN", "KTW")]
    collect.run(tmp_path, NOW, "KTW", **NOSLEEP)
    rows = store.read_prices(tmp_path / "prices.csv")
    assert {x["origin"] for x in rows} == {"KTW", "STN"}
    assert any(x["origin"] == "KTW" and x["price"] == "99.00" for x in rows)


def test_main_writes_into_home_subdir(tmp_path, monkeypatch):
    fake_api(monkeypatch)
    monkeypatch.setattr(collect, "run", lambda d, now, home: _real_run(d, now, home, **NOSLEEP))
    assert collect.main(["wro", str(tmp_path)]) == 0
    assert store.read_runs(tmp_path / "WRO" / "runs.csv")[-1]["status"] == "ok"
