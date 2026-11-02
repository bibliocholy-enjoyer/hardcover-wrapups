"""Anonymous usage counts, kept in a small SQLite file.

Only daily totals are kept for good. To count unique makers, the current month also
keeps a salted hash of each maker's username; when the month rolls over, its total is
saved and the hashes and salt are deleted. Nothing here ever records an IP address.

Show the numbers with `hc-wrapup-stats`.
"""
import hashlib
import logging
import os
import secrets
import sqlite3
from datetime import date
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_PATH = "/data/stats.db"  # the Fly volume

VISIT, SIGN_IN, DOWNLOAD = "visit", "sign_in", "download"
WRAPUP_PREFIX = "wrapup:"  # followed by the style
BUSIEST_DAYS = 3

SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_counts (
    day TEXT NOT NULL, event TEXT NOT NULL, count INTEGER NOT NULL,
    PRIMARY KEY (day, event));
CREATE TABLE IF NOT EXISTS month_salts (month TEXT PRIMARY KEY, salt BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS month_makers (
    month TEXT NOT NULL, maker TEXT NOT NULL, PRIMARY KEY (month, maker));
CREATE TABLE IF NOT EXISTS monthly_uniques (month TEXT PRIMARY KEY, makers INTEGER NOT NULL);
"""


class Stats:
    """Counts events. A failure here is logged and never reaches the person using the site."""

    def __init__(self, path, exclude=frozenset(), today=date.today):
        self.path = path  # None turns counting off
        self.exclude = exclude
        self.today = today
        if path:
            self._write(lambda db: db.executescript(SCHEMA))

    def _write(self, change):
        db = None
        try:
            db = sqlite3.connect(self.path, timeout=1)
            with db:
                change(db)
        except sqlite3.Error:
            log.exception("couldn't update the usage stats")
        finally:
            if db:
                db.close()

    def _excluded(self, username):
        return bool(username) and username.lower() in self.exclude

    def count(self, event, username=None):
        """Add one to today's count, unless this is an excluded user."""
        if not self.path or self._excluded(username):
            return
        day = self.today()

        def change(db):
            close_past_months(db, day)
            db.execute("""INSERT INTO daily_counts VALUES (?, ?, 1)
                          ON CONFLICT DO UPDATE SET count = count + 1""", (day.isoformat(), event))
        self._write(change)

    def count_wrapup(self, style, username):
        """Count a finished wrap-up and, for this month's uniques, the person who made it."""
        if not self.path or self._excluded(username):
            return
        self.count(WRAPUP_PREFIX + style, username)
        if not username:
            return
        month = month_of(self.today())

        def change(db):
            db.execute("INSERT OR IGNORE INTO month_salts VALUES (?, ?)",
                       (month, secrets.token_bytes(32)))
            salt = db.execute("SELECT salt FROM month_salts WHERE month = ?", (month,)).fetchone()[0]
            maker = hashlib.sha256(salt + username.lower().encode()).hexdigest()
            db.execute("INSERT OR IGNORE INTO month_makers VALUES (?, ?)", (month, maker))
        self._write(change)


def excluded_users():
    """The lowercase usernames in STATS_EXCLUDE_USERS, which is separated by commas."""
    names = os.environ.get("STATS_EXCLUDE_USERS", "").split(",")
    return frozenset(name.strip().lower() for name in names if name.strip())


def month_of(day):
    return day.isoformat()[:7]


def close_past_months(db, today):
    """Save past months' unique totals, then delete their hashes and salts."""
    month = month_of(today)
    db.execute("""INSERT OR REPLACE INTO monthly_uniques
                  SELECT month, COUNT(*) FROM month_makers WHERE month < ? GROUP BY month""", (month,))
    db.execute("DELETE FROM month_makers WHERE month < ?", (month,))
    db.execute("DELETE FROM month_salts WHERE month < ?", (month,))


def read_rows(db):
    """{month: row} of the monthly totals, oldest first, for the report."""
    months = {}

    def row(month):
        return months.setdefault(month, {"visits": 0, "sign_ins": 0, "makers": 0,
                                         "wrapups": 0, "downloads": 0})

    columns = {VISIT: "visits", SIGN_IN: "sign_ins", DOWNLOAD: "downloads"}
    for day, event, count in db.execute("SELECT day, event, count FROM daily_counts"):
        column = "wrapups" if event.startswith(WRAPUP_PREFIX) else columns.get(event)
        if column:
            row(day[:7])[column] += count
    for month, makers in db.execute("""SELECT month, makers FROM monthly_uniques UNION ALL
                                       SELECT month, COUNT(*) FROM month_makers GROUP BY month"""):
        row(month)["makers"] = makers
    return dict(sorted(months.items()))


def report(db, today, style_labels, excluded=frozenset()):
    """The usage report as text. style_labels maps a style's key to its name."""
    months = read_rows(db)
    lines = ["Hardcover Wrap-Ups usage", ""]
    header = f"{'Month':<9}{'Visits':>8}{'Sign-ins':>10}{'Unique makers':>15}{'Wrap-ups':>10}{'Downloads':>11}"
    lines.append(header)
    for month, row in months.items():
        lines.append(f"{month:<9}{row['visits']:>8}{row['sign_ins']:>10}{row['makers']:>15}"
                     f"{row['wrapups']:>10}{row['downloads']:>11}")
    total = {key: sum(row[key] for row in months.values())
             for key in ("visits", "sign_ins", "wrapups", "downloads")}
    # No total for makers: each month has its own salt, so months can't be compared.
    lines.append(f"{'Total':<9}{total['visits']:>8}{total['sign_ins']:>10}{'-':>15}"
                 f"{total['wrapups']:>10}{total['downloads']:>11}")

    month = month_of(today)
    wrapups = list(db.execute(
        """SELECT substr(event, ?), SUM(count) FROM daily_counts
           WHERE substr(day, 1, 7) = ? AND event LIKE ? GROUP BY event ORDER BY 2 DESC, 1""",
        (len(WRAPUP_PREFIX) + 1, month, WRAPUP_PREFIX + "%")))
    if wrapups:
        made = sum(count for _, count in wrapups)
        lines += ["", "This month's wrap-ups by style"]
        for style, count in wrapups:
            lines.append(f"  {style_labels.get(style, style):<10}{count:>5}{count * 100 / made:>6.0f}%")
        lines += ["", "Busiest days this month"]
        for day, count in db.execute(
                """SELECT day, SUM(count) FROM daily_counts
                   WHERE substr(day, 1, 7) = ? AND event LIKE ?
                   GROUP BY day ORDER BY 2 DESC, 1 LIMIT ?""",
                (month, WRAPUP_PREFIX + "%", BUSIEST_DAYS)):
            lines.append(f"  {day}{count:>5} wrap-up{'' if count == 1 else 's'}")
    if excluded:
        lines += ["", f"Left out: {', '.join(sorted(excluded))}",
                  "  Not counted: sign-ins, unique makers, wrap-ups, downloads, and visits while signed in",
                  "  Still counted: home page visits while signed out"]
    return "\n".join(lines)


def main():
    """Entry point for `hc-wrapup-stats`."""
    from .web import STYLE_CHOICES

    path = Path(os.environ.get("STATS_DB") or DEFAULT_PATH)
    if not path.exists():
        raise SystemExit(f"No usage stats yet ({path} doesn't exist).")
    db = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        print(report(db, date.today(), {key: label for key, label, _ in STYLE_CHOICES},
                     excluded_users()))
    finally:
        db.close()
