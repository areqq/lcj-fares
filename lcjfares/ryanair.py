"""Klient otwartego API fare-finder Ryanair (bez auth). Na bazie skyskaner/ryanair_client.py."""
from __future__ import annotations

import math
import time
from typing import NamedTuple

import curl_cffi

W = "https://www.ryanair.com/api"
_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131 Safari/537.36"
_FARE_KEYS = {"day", "departureDate", "price", "soldOut", "unavailable"}


class ApiError(Exception):
    """Zapytanie nieudane po wszystkich próbach albo odpowiedź w nieznanym formacie."""


class Fare(NamedTuple):
    day: str        # YYYY-MM-DD
    dep_time: str   # HH:MM albo ""
    price: str      # "%.2f" albo ""
    status: str     # ok | unavailable | soldout


def _http_get(url, params):
    r = curl_cffi.get(url, params=params, headers={"User-Agent": _UA},
                      impersonate="chrome131", timeout=30)
    r.raise_for_status()
    return r.json()


def get_json(url, params=None, *, retries=3, backoff=2.0, sleep=time.sleep):
    last = None
    for attempt in range(retries):
        try:
            return _http_get(url, params)
        except Exception as e:  # sieć, HTTP 4xx/5xx, zły JSON — wszystko ponawiamy
            last = e
            if attempt < retries - 1:
                sleep(backoff * 2 ** attempt)
    raise ApiError(f"{url}: {last}") from last


def parse_fares(data) -> list[Fare]:
    try:
        raw = data["outbound"]["fares"]
    except (KeyError, TypeError) as e:
        raise ApiError(f"brak outbound.fares: {e!r}") from e
    out = []
    for f in raw:
        if not isinstance(f, dict) or not _FARE_KEYS <= f.keys():
            raise ApiError(f"nieoczekiwany format dnia: {f!r}"[:200])
        dep = (f["departureDate"] or "")[11:16]
        if f["unavailable"]:
            out.append(Fare(f["day"], "", "", "unavailable"))
        elif f["soldOut"]:
            out.append(Fare(f["day"], dep, "", "soldout"))
        else:
            try:
                value = float(f["price"]["value"])
                currency = f["price"].get("currencyCode")
            except (KeyError, TypeError, ValueError, AttributeError) as e:
                raise ApiError(f"brak ceny dla {f['day']}: {e!r}") from e
            if not math.isfinite(value) or value <= 0:
                raise ApiError(f"nieprawidłowa cena dla {f['day']}: {value!r}")
            if currency != "PLN":
                raise ApiError(f"nieoczekiwana waluta dla {f['day']}: {currency!r}")
            out.append(Fare(f["day"], dep, f"{value:.2f}", "ok"))
    return out


def cheapest_per_day(origin, dest, month, *, sleep=time.sleep) -> list[Fare]:
    """Najtańszy lot każdego dnia miesiąca (month = YYYY-MM-01)."""
    data = get_json(f"{W}/farfnd/v4/oneWayFares/{origin}/{dest}/cheapestPerDay",
                    {"outboundMonthOfDate": month, "currency": "PLN"}, sleep=sleep)
    fares = parse_fares(data)
    if not fares:  # 200 z pustą listą = miękka blokada, nie "brak lotów"
        raise ApiError(f"pusty kalendarz {origin}-{dest} {month}")
    return fares


def routes_info(origin, *, sleep=time.sleep) -> dict[str, dict]:
    """Kierunki z lotniska: IATA -> {"name": polska nazwa, "country": kod ISO-2}."""
    data = get_json(f"{W}/views/locate/searchWidget/routes/pl/airport/{origin}", sleep=sleep)
    try:
        return {a["code"]: {"name": a["name"], "country": a["country"]["code"]}
                for a in (r["arrivalAirport"] for r in data)}
    except (KeyError, TypeError) as e:
        raise ApiError(f"nieoczekiwany format tras: {e!r}") from e
