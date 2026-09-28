import datetime as dt
import random

from lcjfares import schedule, store

NOW = dt.datetime(2026, 9, 27, 12, 0, tzinfo=dt.timezone.utc)


def add_run(root, home, hours_ago, status="ok"):
    t = NOW - dt.timedelta(hours=hours_ago)
    store.append_run(root / home / "runs.csv", {
        "observed": t.date().isoformat(), "started_utc": t.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "requests": 10, "failed": 0, "status": status, "routes": "STN", "missing": "", "ip": ""})


def pick(root, seed=0, airports=("LCJ", "KTW", "WRO")):
    return schedule.pick(root, NOW, airports=airports, rng=random.Random(seed))


def test_never_measured_airport_goes_first(tmp_path):
    add_run(tmp_path, "LCJ", 30)
    add_run(tmp_path, "KTW", 25)
    assert {pick(tmp_path, s, ("LCJ", "KTW", "BZG")) for s in range(20)} <= {"BZG", "LCJ"}
    assert pick(tmp_path, 0, ("LCJ", "BZG")) in {"LCJ", "BZG"}


def test_fresh_airports_are_skipped(tmp_path):
    add_run(tmp_path, "LCJ", 10)      # świeży udany pomiar (< 18 h)
    add_run(tmp_path, "KTW", 19)      # kwalifikuje się
    add_run(tmp_path, "WRO", 17.9)    # jeszcze świeży
    assert {pick(tmp_path, s) for s in range(20)} == {"KTW"}


def test_nothing_to_do_returns_none(tmp_path):
    for h in ("LCJ", "KTW", "WRO"):
        add_run(tmp_path, h, 5)
    assert pick(tmp_path) is None


def test_recent_failed_attempt_waits_4h(tmp_path):
    add_run(tmp_path, "LCJ", 30)
    add_run(tmp_path, "LCJ", 3, status="failed")    # próba 3 h temu — odczekaj
    add_run(tmp_path, "KTW", 20)
    add_run(tmp_path, "WRO", 10)
    assert {pick(tmp_path, s) for s in range(20)} == {"KTW"}
    add_run(tmp_path, "KTW", 1)                      # KTW świeży, LCJ wciąż w karencji
    assert pick(tmp_path) is None


def test_failed_attempt_older_than_4h_is_retried(tmp_path):
    add_run(tmp_path, "LCJ", 30)
    add_run(tmp_path, "LCJ", 5, status="failed")
    for h in ("KTW", "WRO"):
        add_run(tmp_path, h, 1)
    assert pick(tmp_path) == "LCJ"


def test_random_among_two_oldest_only(tmp_path):
    add_run(tmp_path, "LCJ", 40)
    add_run(tmp_path, "KTW", 30)
    add_run(tmp_path, "WRO", 20)      # kwalifikuje się, ale jest trzeci najstarszy
    picks = {pick(tmp_path, s) for s in range(50)}
    assert picks == {"LCJ", "KTW"}


def test_due_lists_all_eligible_two_oldest_first_in_random_order(tmp_path):
    add_run(tmp_path, "LCJ", 40)
    add_run(tmp_path, "KTW", 30)
    add_run(tmp_path, "WRO", 20)
    add_run(tmp_path, "WMI", 10)       # świeży — pomijany
    orders = {tuple(schedule.due(tmp_path, NOW, airports=("LCJ", "KTW", "WRO", "WMI"), rng=random.Random(s)))
              for s in range(50)}
    assert orders == {("LCJ", "KTW", "WRO"), ("KTW", "LCJ", "WRO")}


def test_due_empty_when_all_fresh(tmp_path):
    for h in ("LCJ", "KTW"):
        add_run(tmp_path, h, 2)
    assert schedule.due(tmp_path, NOW, airports=("LCJ", "KTW")) == []


def test_main_prints_space_separated_list_or_empty(tmp_path, capsys):
    assert schedule.main([str(tmp_path)], now=NOW) == 0
    assert sorted(capsys.readouterr().out.split()) == sorted(schedule.AIRPORTS)
    for h in schedule.AIRPORTS:
        add_run(tmp_path, h, 1)
    schedule.main([str(tmp_path)], now=NOW)
    assert capsys.readouterr().out.strip() == ""
