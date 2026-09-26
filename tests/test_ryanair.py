import json
from pathlib import Path

import pytest

from lcjfares import ryanair
from lcjfares.ryanair import ApiError, Fare

FIX = Path(__file__).parent / "fixtures"


def _day(day, **kw):
    base = {"day": day, "arrivalDate": None, "departureDate": None, "price": None,
            "soldOut": False, "unavailable": False}
    base.update(kw)
    return base


def test_parse_fares_real_fixture():
    data = json.loads((FIX / "cheapest_LCJ_STN_2026-11.json").read_text())
    fares = ryanair.parse_fares(data)
    raw = data["outbound"]["fares"]
    assert len(fares) == len(raw) == 30
    assert all(f.status in {"ok", "unavailable", "soldout"} for f in fares)
    ok_raw = next(r for r in raw if not r["unavailable"] and not r["soldOut"])
    ok = next(f for f in fares if f.day == ok_raw["day"])
    assert ok.price == f"{ok_raw['price']['value']:.2f}"
    assert ok.dep_time == ok_raw["departureDate"][11:16]
    assert ok.status == "ok"


def test_parse_fares_statuses():
    data = {"outbound": {"fares": [
        _day("2026-11-01", departureDate="2026-11-01T13:40:00", price={"value": 394.2, "currencyCode": "PLN"}),
        _day("2026-11-02", unavailable=True),
        _day("2026-11-03", departureDate="2026-11-03T09:05:00", soldOut=True),
    ]}}
    assert ryanair.parse_fares(data) == [
        Fare("2026-11-01", "13:40", "394.20", "ok"),
        Fare("2026-11-02", "", "", "unavailable"),
        Fare("2026-11-03", "09:05", "", "soldout"),
    ]


@pytest.mark.parametrize("data", [
    {"foo": 1},
    {"outbound": {"fares": [{"day": "2026-11-01"}]}},
    {"outbound": {"fares": [_day("2026-11-01", price=None)]}},
    [],
])
def test_parse_fares_rejects_unknown_schema(data):
    with pytest.raises(ApiError):
        ryanair.parse_fares(data)


def test_get_json_retries_then_succeeds(monkeypatch):
    calls, sleeps = [], []

    def fake(url, params):
        calls.append(url)
        if len(calls) < 3:
            raise RuntimeError("429")
        return {"ok": True}

    monkeypatch.setattr(ryanair, "_http_get", fake)
    assert ryanair.get_json("u", sleep=sleeps.append) == {"ok": True}
    assert len(calls) == 3
    assert sleeps == [2.0, 4.0]


def test_get_json_gives_up_after_retries(monkeypatch):
    calls = []

    def fake(url, params):
        calls.append(url)
        raise RuntimeError("403")

    monkeypatch.setattr(ryanair, "_http_get", fake)
    with pytest.raises(ApiError):
        ryanair.get_json("u", sleep=lambda s: None)
    assert len(calls) == 3


def test_routes_info(monkeypatch):
    monkeypatch.setattr(ryanair, "_http_get", lambda url, params: [
        {"arrivalAirport": {"code": "STN", "name": "Londyn Stansted", "country": {"code": "gb"}}},
        {"arrivalAirport": {"code": "DUB", "name": "Dublin", "country": {"code": "ie"}}}])
    assert ryanair.routes_info("LCJ", sleep=lambda s: None) == {
        "STN": {"name": "Londyn Stansted", "country": "gb"},
        "DUB": {"name": "Dublin", "country": "ie"}}


def test_routes_info_rejects_unknown_schema(monkeypatch):
    monkeypatch.setattr(ryanair, "_http_get", lambda url, params: {"x": 1})
    with pytest.raises(ApiError):
        ryanair.routes_info("LCJ", sleep=lambda s: None)


@pytest.mark.parametrize("price", [
    {"value": 0, "currencyCode": "PLN"},
    {"value": -5, "currencyCode": "PLN"},
    {"value": float("nan"), "currencyCode": "PLN"},
    {"value": 100, "currencyCode": "EUR"},
    {"value": 100},
])
def test_parse_fares_rejects_bad_price(price):
    data = {"outbound": {"fares": [_day("2026-11-01", departureDate="2026-11-01T13:40:00", price=price)]}}
    with pytest.raises(ApiError):
        ryanair.parse_fares(data)


def test_cheapest_per_day_empty_calendar_is_error(monkeypatch):
    monkeypatch.setattr(ryanair, "_http_get", lambda url, params: {"outbound": {"fares": []}})
    with pytest.raises(ApiError):
        ryanair.cheapest_per_day("LCJ", "STN", "2026-11-01", sleep=lambda s: None)
