import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import main


class RatesReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cache_file = Path(self.temp_dir.name) / "cache.json"
        self.history_file = Path(self.temp_dir.name) / "history.json"
        self.original_cache = main.CACHE_FILE
        self.original_history = main.HISTORY_FILE
        self.original_memory = main.memory_cache
        main.CACHE_FILE = self.cache_file
        main.HISTORY_FILE = self.history_file
        main.memory_cache = None

    def tearDown(self):
        main.CACHE_FILE = self.original_cache
        main.HISTORY_FILE = self.original_history
        main.memory_cache = self.original_memory
        self.temp_dir.cleanup()

    def test_normalized_rates_rejects_malformed_and_non_finite_values(self):
        self.assertIsNone(main.normalized_rates(None))
        self.assertIsNone(main.normalized_rates({"PKR": 1, "USD": "nan", "AED": 1, "SAR": 1}))
        self.assertIsNone(main.normalized_rates({"PKR": 1, "USD": "inf", "AED": 1, "SAR": 1}))

    def test_rates_endpoint_returns_stale_cache_when_refresh_fails(self):
        cached = {
            "rates": {"PKR": 1, "USD": 0.0035, "AED": 0.013, "SAR": 0.013},
            "updated": "yesterday",
            "next_update_unix": 0,
        }
        self.cache_file.write_text(json.dumps(cached), encoding="utf-8")
        with patch.object(main, "fetch_rates", return_value=None):
            result = asyncio.run(main.get_rates())
        self.assertTrue(result["stale"])
        self.assertEqual(result["rates"]["USD"], 0.0035)

    def test_rates_endpoint_does_not_return_fake_rates_without_cache(self):
        with patch.object(main, "fetch_rates", return_value=None):
            result = asyncio.run(main.get_rates())
        self.assertEqual(result.status_code, 503)
        self.assertEqual(json.loads(result.body)["rates"], {})
        self.assertIn("error", json.loads(result.body))

    def test_history_endpoint_filters_malformed_entries(self):
        self.history_file.write_text(json.dumps([{"date": "2026-01-01"}, "bad", 4]), encoding="utf-8")
        result = asyncio.run(main.get_history())
        self.assertEqual(result, [{"date": "2026-01-01"}])

    def test_daily_snapshot_discards_malformed_history_entries(self):
        self.history_file.write_text(json.dumps(["bad", {"date": "2020-01-01"}]), encoding="utf-8")
        main.save_daily_snapshot({"PKR": 1, "USD": 0.0035, "AED": 0.013, "SAR": 0.013})
        history = json.loads(self.history_file.read_text(encoding="utf-8"))
        self.assertTrue(all(isinstance(item, dict) for item in history))


if __name__ == "__main__":
    unittest.main()
