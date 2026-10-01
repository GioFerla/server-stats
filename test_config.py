"""Installation settings and public HTML escaping regression tests."""
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from config import Settings
from energy_store import EnergyStore, MICROJOULES_PER_KWH
import server


class ConfigTests(unittest.TestCase):
    def test_neutral_defaults_and_custom_settings(self):
        default = Settings.from_env({})
        self.assertEqual((default.name, default.label), ('Server', 'Stats'))
        custom = Settings.from_env({
            'STATS_NAME': 'My Lab', 'STATS_LABEL': 'Monitor',
            'STATS_HEADING': 'Stato infrastruttura',
            'STATS_ACCENT': '#112233', 'STATS_SECONDARY': '#445566',
            'STATS_SAMPLE_SECONDS': '2', 'STATS_HISTORY_SECONDS': '120',
            'STATS_TIMEZONE': 'UTC', 'STATS_INITIAL_PRICE': '0.42',
        })
        self.assertEqual(custom.history_samples, 60)
        self.assertEqual(custom.timezone.key, 'UTC')
        with patch.object(server, 'settings', custom):
            for filename in ('index.html', 'login.html'):
                page = server.render_page((Path('static') / filename).read_text())
                self.assertIn('My Lab', page)
                self.assertIn('Monitor', page)
                self.assertNotIn('{{', page)
            self.assertIn('data-poll-ms="2000"', page := server.render_page(Path('static/index.html').read_text()))
            self.assertIn('ultimi 2 minuti', page)
            self.assertIn('value="0.42"', page)

    def test_brand_is_escaped_once(self):
        custom = replace(Settings.from_env({}), name='<script>alert("x")</script>{{label}}')
        with patch.object(server, 'settings', custom):
            page = server.render_page('{{name}} / {{label}}')
        self.assertEqual(page, '&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;{{label}} / Stats')

    def test_invalid_values_fail(self):
        for key, value in (
            ('STATS_NAME', ''), ('STATS_NAME', 'x\ny'), ('STATS_LABEL', 'x' * 201),
            ('STATS_ACCENT', 'red;}body{display:none}'),
            ('STATS_SAMPLE_SECONDS', 'nan'), ('STATS_SAMPLE_SECONDS', '0'),
            ('STATS_HISTORY_SECONDS', '3601'), ('STATS_INITIAL_PRICE', '-1'),
        ):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                Settings.from_env({key: value})

    def test_initial_price_only_applies_to_new_database(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'energy.sqlite3'
            store = EnergyStore(path, initial_price=0.42, now=0)
            try:
                store.record(0, 1, MICROJOULES_PER_KWH)
                self.assertEqual(store.snapshot(1)['total']['cost'], 0.42)
                store.set_price(0.5)
            finally:
                store.close()
            store = EnergyStore(path, initial_price=0.99, now=2)
            try:
                self.assertEqual(store.snapshot(2)['price'], 0.5)
            finally:
                store.close()


if __name__ == '__main__':
    unittest.main()
