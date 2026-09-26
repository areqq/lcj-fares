from lcjfares import store


def row(observed, day, price, status="ok", dep="10:00", origin="LCJ", dest="STN"):
    return {"observed": observed, "origin": origin, "dest": dest, "day": day,
            "dep_time": dep, "price": price, "status": status}


def test_read_missing_file_returns_empty(tmp_path):
    assert store.read_prices(tmp_path / "prices.csv") == []
    assert store.read_runs(tmp_path / "runs.csv") == []


def test_append_prices_roundtrip_header_once(tmp_path):
    p = tmp_path / "data" / "prices.csv"
    store.append_prices(p, [row("2026-09-25", "2026-11-01", "394.24")])
    store.append_prices(p, [row("2026-09-26", "2026-11-01", "", "soldout")])
    rows = store.read_prices(p)
    assert rows == [row("2026-09-25", "2026-11-01", "394.24"),
                    row("2026-09-26", "2026-11-01", "", "soldout")]
    assert p.read_text().splitlines()[0] == ",".join(store.PRICE_FIELDS)
    assert p.read_text().count("observed") == 1


def test_append_empty_does_not_create_file(tmp_path):
    p = tmp_path / "prices.csv"
    store.append_prices(p, [])
    assert not p.exists()


def test_append_run_roundtrip(tmp_path):
    p = tmp_path / "runs.csv"
    r = {"observed": "2026-09-25", "started_utc": "2026-09-25T06:00:00Z", "requests": 168,
         "failed": 1, "status": "partial", "routes": "DUB;STN", "missing": "LCJ-STN-2026-11",
         "ip": "203.0.113.7"}
    store.append_run(p, r)
    assert store.read_runs(p) == [{k: str(v) for k, v in r.items()}]


def test_last_state_latest_row_wins():
    rows = [row("2026-09-25", "2026-11-01", "394.24"),
            row("2026-09-25", "2026-11-02", "100.00"),
            row("2026-09-27", "2026-11-01", "299.00")]
    assert store.last_state(rows) == {
        ("LCJ", "STN", "2026-11-01"): ("10:00", "299.00", "ok"),
        ("LCJ", "STN", "2026-11-02"): ("10:00", "100.00", "ok"),
    }


def test_routes_roundtrip(tmp_path):
    p = tmp_path / "routes.json"
    assert store.load_routes(p) == []
    store.save_routes(p, ["STN", "AGP"])
    assert store.load_routes(p) == ["AGP", "STN"]


def test_load_routes_corrupted_file_returns_empty(tmp_path):
    p = tmp_path / "routes.json"
    p.write_text("{not json")
    assert store.load_routes(p) == []


def test_iter_prices_streams_rows(tmp_path):
    p = tmp_path / "prices.csv"
    assert list(store.iter_prices(p)) == []
    store.append_prices(p, [row("2026-09-25", "2026-11-01", "394.24")])
    it = store.iter_prices(p)
    assert next(it)["price"] == "394.24"


def test_airports_roundtrip_and_corrupt(tmp_path):
    p = tmp_path / "airports.json"
    assert store.load_airports(p) == {}
    a = {"STN": {"name": "Londyn Stansted", "country": "gb"}}
    store.save_airports(p, a)
    assert store.load_airports(p) == a
    p.write_text("{oops")
    assert store.load_airports(p) == {}
