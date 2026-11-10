import datetime as dt
import importlib.util
import pathlib
import unittest

PATH = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "collect.py"
spec = importlib.util.spec_from_file_location("sentinela_collect", PATH)
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)

class CollectorTests(unittest.TestCase):
    def test_kp_preserves_timeline_and_missing_is_not_zero(self):
        now = collector.NOW.isoformat()
        result = collector.solar_data("kp", [{"time_tag": now, "kp_index": 3.0}, {"time_tag": now, "kp_index": 4.0}])
        self.assertEqual(len(result["data"]), 2)
        self.assertEqual(result["observed_at"], now)
        self.assertFalse(result["stale"])

    def test_solar_regions_choose_latest_observation_day(self):
        a = [{"observed_date": "2026-09-01", "region": 1},
             {"observed_date": "2026-11-09", "region": 2},
             {"observed_date": "2026-11-09", "region": 3}]
        result = collector.solar_data("regions", a)
        self.assertEqual(len(result["data"]), 2)
        self.assertTrue(all(row["region"] != 1 for row in result["data"]))

    def test_flare_history_empty_week_is_valid(self):
        result = collector.solar_data("flare_history", [])
        self.assertEqual(result["data"], [])
        self.assertFalse(result["stale"])

    def test_rejects_wrong_schema(self):
        with self.assertRaises(ValueError):
            collector.solar_data("kp", {"error": "upstream changed"})

    def test_missing_kp_is_not_accepted(self):
        with self.assertRaises(ValueError):
            collector.solar_data("kp", [])

if __name__ == "__main__":
    unittest.main()
