"""Persistent accounting of measured CPU energy, independent of browser uptime."""
import math
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MICROJOULES_PER_KWH = 3_600_000_000_000

def local_timezone():
    try:
        return ZoneInfo('Europe/Rome')
    except ZoneInfoNotFoundError:
        with open('/host/root/usr/share/zoneinfo/Europe/Rome', 'rb') as source:
            return ZoneInfo.from_file(source, key='Europe/Rome')

def counter_delta(current, previous, maximum, seconds):
    # A long unobserved interval could conceal several counter rollovers.
    if previous is None or not 0 < seconds <= 30 or maximum <= 0:
        return None
    if not 0 <= current < maximum or not 0 <= previous < maximum:
        return None
    delta = current - previous
    if delta < 0:
        delta += maximum
    # Reject counter resets that would imply implausible package power.
    return delta if delta <= 2000 * 1_000_000 * seconds else None

class EnergyStore:
    def __init__(self, path, timezone=None, now=None, initial_price=0.30):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.timezone = timezone or local_timezone()
        self.lock = threading.Lock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS settings (
                id INTEGER PRIMARY KEY CHECK (id=1),
                price REAL NOT NULL, started REAL NOT NULL, last_end REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS daily (
                day TEXT PRIMARY KEY, energy_uj INTEGER NOT NULL,
                cost REAL NOT NULL, measured_seconds REAL NOT NULL,
                missing_seconds REAL NOT NULL);
        ''')
        start = time.time() if now is None else now
        if isinstance(initial_price, bool) or not isinstance(initial_price, (int, float)) or not math.isfinite(initial_price) or not 0 <= initial_price <= 100:
            raise ValueError('Invalid initial energy price')
        self.db.execute('INSERT OR IGNORE INTO settings VALUES (1, ?, ?, ?)', (initial_price, start, start))
        self.db.commit()

    def _add_span(self, start, end, energy_uj, price):
        original_start, duration = start, end - start
        if duration <= 0:
            return
        allocated = 0
        while start < end:
            local = datetime.fromtimestamp(start, self.timezone)
            tomorrow = local.date() + timedelta(days=1)
            boundary = datetime.combine(tomorrow, datetime.min.time(), self.timezone).timestamp()
            stop = min(end, boundary)
            seconds = stop - start
            if energy_uj is None:
                part, measured, missing = 0, 0, seconds
            else:
                cumulative = round(energy_uj * (stop - original_start) / duration)
                part = cumulative - allocated
                allocated = cumulative
                measured, missing = seconds, 0
            cost = part / MICROJOULES_PER_KWH * price
            self.db.execute('''INSERT INTO daily VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(day) DO UPDATE SET
                energy_uj=energy_uj+excluded.energy_uj, cost=cost+excluded.cost,
                measured_seconds=measured_seconds+excluded.measured_seconds,
                missing_seconds=missing_seconds+excluded.missing_seconds''',
                (local.date().isoformat(), part, cost, measured, missing))
            start = stop

    def record(self, start, end, energy_uj):
        if not math.isfinite(start) or not math.isfinite(end) or end < start:
            raise ValueError('Invalid interval')
        if energy_uj is not None and (not isinstance(energy_uj, int) or energy_uj < 0):
            raise ValueError('Invalid energy')
        with self.lock, self.db:
            settings = self.db.execute('SELECT * FROM settings WHERE id=1').fetchone()
            last_end, price = settings['last_end'], settings['price']
            if end <= last_end:
                return
            if start > last_end:
                self._add_span(last_end, start, None, price)
            if start < last_end:
                if energy_uj is not None and end > start:
                    energy_uj = round(energy_uj * (end - last_end) / (end - start))
                start = last_end
            self._add_span(start, end, energy_uj, price)
            self.db.execute('UPDATE settings SET last_end=? WHERE id=1', (end,))

    def set_price(self, price):
        if isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or not 0 <= price <= 100:
            raise ValueError('Inserisci una tariffa tra 0 e 100 €/kWh.')
        with self.lock, self.db:
            self.db.execute('UPDATE settings SET price=? WHERE id=1', (price,))

    @staticmethod
    def _totals(rows):
        return dict(kwh=sum(r['energy_uj'] for r in rows) / MICROJOULES_PER_KWH,
                    cost=sum(r['cost'] for r in rows),
                    measured_seconds=sum(r['measured_seconds'] for r in rows),
                    missing_seconds=sum(r['missing_seconds'] for r in rows))

    def snapshot(self, now=None):
        date = datetime.fromtimestamp(time.time() if now is None else now, self.timezone).date()
        with self.lock:
            settings = dict(self.db.execute('SELECT * FROM settings WHERE id=1').fetchone())
            all_rows = self.db.execute('SELECT * FROM daily ORDER BY day DESC').fetchall()
        today = [r for r in all_rows if r['day'] == date.isoformat()]
        month = [r for r in all_rows if r['day'].startswith(date.isoformat()[:7])]
        days = [dict(day=r['day'], **self._totals([r])) for r in all_rows[:31]]
        return dict(price=settings['price'], started_at=settings['started'], last_sample_at=settings['last_end'],
                    timezone=self.timezone.key, scope='CPU', today=self._totals(today),
                    month=self._totals(month), total=self._totals(all_rows), days=days)

    def close(self):
        with self.lock:
            self.db.close()
