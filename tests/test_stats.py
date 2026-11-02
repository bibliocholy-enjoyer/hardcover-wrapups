import contextlib
import sqlite3
from datetime import date

import pytest

from hardcover_wrapups import stats

LABELS = {"grid": "Grid", "cork": "Corkboard"}


class Clock:
    def __init__(self, day):
        self.day = day

    def __call__(self):
        return self.day


@pytest.fixture
def clock():
    return Clock(date(2026, 11, 2))


@pytest.fixture
def usage(tmp_path, clock):
    return stats.Stats(str(tmp_path / "stats.db"), frozenset({"me"}), clock)


def rows(usage, query):
    with contextlib.closing(sqlite3.connect(usage.path)) as db:
        return list(db.execute(query))


def report(usage, today):
    with contextlib.closing(sqlite3.connect(usage.path)) as db:
        return stats.report(db, today, LABELS)


def test_unique_makers_are_counted_once_and_hashed(usage):
    usage.count_wrapup("grid", "Sam")
    usage.count_wrapup("cork", "sam")
    usage.count_wrapup("grid", "alex")
    makers = [maker for (maker,) in rows(usage, "SELECT maker FROM month_makers")]
    assert len(makers) == 2
    assert not any("sam" in maker or "alex" in maker for maker in makers)


def test_a_new_month_keeps_the_total_and_deletes_hashes_and_salt(usage, clock):
    usage.count_wrapup("grid", "sam")
    usage.count_wrapup("grid", "alex")
    clock.day = date(2026, 12, 1)
    usage.count(stats.VISIT)
    assert rows(usage, "SELECT * FROM monthly_uniques") == [("2026-11", 2)]
    assert rows(usage, "SELECT * FROM month_makers") == []
    assert rows(usage, "SELECT * FROM month_salts") == []


def test_each_month_has_its_own_salt(usage, clock):
    usage.count_wrapup("grid", "sam")
    first = rows(usage, "SELECT maker FROM month_makers")
    clock.day = date(2026, 12, 1)
    usage.count_wrapup("grid", "sam")
    assert rows(usage, "SELECT maker FROM month_makers") != first


def test_excluded_user_matches_any_case(usage):
    usage.count_wrapup("grid", "ME")
    usage.count(stats.DOWNLOAD, "Me")
    assert rows(usage, "SELECT * FROM daily_counts") == []
    assert rows(usage, "SELECT * FROM month_makers") == []


def test_report(usage, clock):
    usage.count_wrapup("grid", "sam")
    usage.count(stats.VISIT)
    clock.day = date(2026, 12, 1)
    usage.count(stats.VISIT)
    usage.count(stats.SIGN_IN, "alex")
    usage.count_wrapup("cork", "alex")
    usage.count_wrapup("cork", "sam")
    usage.count_wrapup("grid", "sam")
    usage.count(stats.DOWNLOAD, "sam")
    assert report(usage, clock.day).splitlines() == [
        "Hardcover Wrap-Ups usage",
        "",
        "Month      Visits  Sign-ins  Unique makers  Wrap-ups  Downloads",
        "2026-11         1         0              1         1          0",
        "2026-12         1         1              2         3          1",
        "Total           2         1              -         4          1",
        "",
        "This month's wrap-ups by style",
        "  Corkboard     2    67%",
        "  Grid          1    33%",
        "",
        "Busiest days this month",
        "  2026-12-01    3 wrap-ups",
    ]


def test_month_with_uniques_not_yet_rolled_over_is_reported(usage):
    usage.count_wrapup("grid", "sam")
    later = report(usage, date(2027, 1, 5))
    assert "2026-11         0         0              1         1          0" in later
    assert "by style" not in later


def test_main_needs_a_database(tmp_path, monkeypatch):
    monkeypatch.setenv("STATS_DB", str(tmp_path / "none.db"))
    with pytest.raises(SystemExit, match="No usage stats yet"):
        stats.main()


def test_main_prints_the_report(usage, monkeypatch, capsys):
    usage.count(stats.VISIT)
    monkeypatch.setenv("STATS_DB", usage.path)
    stats.main()
    assert "Hardcover Wrap-Ups usage" in capsys.readouterr().out


def test_main_reminds_who_is_left_out(usage, monkeypatch, capsys):
    usage.count(stats.VISIT)
    monkeypatch.setenv("STATS_DB", usage.path)
    monkeypatch.setenv("STATS_EXCLUDE_USERS", " Me, alex ")
    stats.main()
    out = capsys.readouterr().out
    assert "Left out: alex, me\n" in out
    assert "Still counted: home page visits while signed out" in out


def test_no_reminder_without_exclusions(usage, monkeypatch, capsys):
    usage.count(stats.VISIT)
    monkeypatch.setenv("STATS_DB", usage.path)
    monkeypatch.delenv("STATS_EXCLUDE_USERS", raising=False)
    stats.main()
    assert "Left out" not in capsys.readouterr().out
