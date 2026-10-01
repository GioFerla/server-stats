import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from energy_store import EnergyStore, MICROJOULES_PER_KWH, counter_delta

TZ = ZoneInfo('Europe/Rome')
def stamp(text):
    return datetime.fromisoformat(text).replace(tzinfo=TZ).timestamp()

class EnergyTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / 'energy.sqlite3'
        self.start = stamp('2026-10-01T10:00:00')
        self.store = EnergyStore(self.path, timezone=TZ, now=self.start)
    def tearDown(self):
        self.store.close()
        self.directory.cleanup()
    def test_counter_conversion_rollover_and_unknown(self):
        self.assertEqual(counter_delta(40, 90, 100, 1), 50)
        self.assertEqual(counter_delta(90, 40, 100, 1), 50)
        self.assertEqual(counter_delta(40, 40, 100, 1), 0)
        self.assertIsNone(counter_delta(40, None, 100, 1))
        self.assertIsNone(counter_delta(40, 90, 100, 31))
        self.assertIsNone(counter_delta(40, 90, 100, 0))
        self.assertIsNone(counter_delta(10, 20, 10**12, 1))
        self.assertIsNone(counter_delta(110, 90, 100, 1))
        # 100 W consumed for one hour: 0.1 kWh, not 100 kWh.
        self.store.record(self.start, self.start + 3600, 100 * 3600 * 1_000_000)
        total = self.store.snapshot(self.start + 3600)['total']
        self.assertAlmostEqual(total['kwh'], 0.1)
        self.assertAlmostEqual(total['cost'], 0.03)
        self.assertEqual(total['measured_seconds'], 3600)
    def test_tariff_change_preserves_past_and_survives_restart(self):
        self.store.record(self.start, self.start + 3600, MICROJOULES_PER_KWH)
        self.store.set_price(0.5)
        before = self.store.snapshot(self.start + 3600)
        self.assertAlmostEqual(before['total']['cost'], 0.3)
        self.store.record(self.start + 3600, self.start + 7200, MICROJOULES_PER_KWH)
        self.store.close()
        self.store = EnergyStore(self.path, timezone=TZ, now=self.start + 7200)
        total = self.store.snapshot(self.start + 7200)
        self.assertEqual(total['total']['kwh'], 2)
        self.assertAlmostEqual(total['total']['cost'], 0.8)
        self.assertEqual(total['price'], 0.5)
        self.assertEqual(total['started_at'], self.start)
    def test_downtime_and_missing_measurements_are_not_invented(self):
        self.store.record(self.start, self.start + 1, 10_000_000)
        self.store.close()
        self.store = EnergyStore(self.path, timezone=TZ, now=self.start + 100)
        self.store.record(self.start + 100, self.start + 100, None)
        self.store.record(self.start + 100, self.start + 101, None)
        snapshot = self.store.snapshot(self.start + 101)['total']
        self.assertAlmostEqual(snapshot['kwh'], 10_000_000 / MICROJOULES_PER_KWH)
        self.assertEqual(snapshot['measured_seconds'], 1)
        self.assertEqual(snapshot['missing_seconds'], 100)
    def test_midnight_month_boundary(self):
        self.store.close()
        start = stamp('2026-10-31T23:59:59')
        self.store = EnergyStore(self.path.with_name('month.sqlite3'), timezone=TZ, now=start)
        self.store.record(start, start + 2, MICROJOULES_PER_KWH)
        data = self.store.snapshot(start + 2)
        self.assertEqual(data['today']['kwh'], 0.5)
        self.assertEqual(data['month']['kwh'], 0.5)
        self.assertEqual(data['total']['kwh'], 1)
        self.assertEqual([day['day'] for day in data['days']], ['2026-11-01', '2026-10-31'])
    def test_daylight_saving_23_hour_day(self):
        self.store.close()
        start = stamp('2026-03-29T00:00:00')
        end = stamp('2026-03-30T00:00:00')
        self.assertEqual(end - start, 23 * 3600)
        self.store = EnergyStore(self.path.with_name('dst.sqlite3'), timezone=TZ, now=start)
        self.store.record(start, end, 100 * int(end - start) * 1_000_000)
        data = self.store.snapshot(end)
        self.assertEqual(len(data['days']), 1)
        self.assertEqual(data['days'][0]['day'], '2026-03-29')
        self.assertAlmostEqual(data['total']['kwh'], 2.3)
    def test_zero_price_and_bad_price_and_duplicate_interval(self):
        for invalid in (-1, 101, float('nan'), float('inf'), True, '0.3', None):
            with self.assertRaises(ValueError):
                self.store.set_price(invalid)
        self.store.set_price(0)
        self.store.record(self.start, self.start + 1, 20_000_000)
        self.store.record(self.start, self.start + 1, 20_000_000)
        total = self.store.snapshot(self.start + 1)['total']
        self.assertEqual(total['cost'], 0)
        self.assertAlmostEqual(total['kwh'], 20_000_000 / MICROJOULES_PER_KWH)

if __name__ == '__main__':
    unittest.main()
