import contextlib
import datetime as dt
import importlib.util
import io
import json
import pathlib
import uuid
import unittest
import urllib.error
from unittest.mock import patch

PATH = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "collect.py"
spec = importlib.util.spec_from_file_location("sentinela_collect", PATH)
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)
NOW = dt.datetime(2026, 11, 10, 21, tzinfo=dt.timezone.utc)


def kp(stamp, value=2):
    return {"time_tag": stamp, "kp_index": value}


@contextlib.contextmanager
def snapshot_directory():
    # Default directory mode also works in restricted Windows test processes.
    directory = PATH.parents[1] / "tests" / (".snapshot-" + uuid.uuid4().hex)
    directory.mkdir()
    try:
        yield directory
    finally:
        for name in ("data.json", "data.json.tmp"):
            (directory / name).unlink(missing_ok=True)
        directory.rmdir()


class CollectorTests(unittest.TestCase):
    def test_kp_merges_24h_deduplicates_and_prefers_new_response(self):
        rows = [kp((NOW - dt.timedelta(minutes=i)).isoformat(), 1) for i in range(1441)]
        previous = {"data": [kp((NOW - dt.timedelta(hours=25)).isoformat()), *rows]}
        result = collector.solar_data("kp", [kp(NOW.isoformat(), 4)], previous, NOW)
        self.assertEqual(len(result["data"]), 1441)
        self.assertEqual(result["data"][-1]["kp_index"], 4)
        self.assertEqual(result["coverage_hours"], 24)
        self.assertEqual(result["gap_count"], 0)

    def test_kp_normalizes_noaa_utc_and_retains_real_zero(self):
        result = collector.solar_data("kp", [kp("2026-11-10T20:59:00", 0)], now=NOW)
        self.assertEqual(result["data"][0]["time_tag"], "2026-11-10T20:59:00+00:00")
        self.assertEqual(result["data"][0]["kp_index"], 0)
        self.assertFalse(result["stale"])

    def test_invalid_kp_is_rejected(self):
        for value in (None, "", -1, 99, True, float("nan"), float("inf"), "bad"):
            with self.subTest(value=value), self.assertRaises((ValueError, TypeError)):
                collector.solar_data("kp", [kp(NOW.isoformat(), value)], now=NOW)

    def test_future_and_invalid_dates_are_rejected(self):
        for stamp in ("bad", None, (NOW + dt.timedelta(days=7)).isoformat()):
            with self.subTest(stamp=stamp), self.assertRaises(ValueError):
                collector.solar_data("kp", [kp(stamp)], now=NOW)

    def test_stale_incoming_kp_is_not_masked_by_newer_retained_history(self):
        result = collector.solar_data("kp", [kp((NOW - dt.timedelta(hours=4)).isoformat())],
                                      {"data": [kp(NOW.isoformat())]}, NOW)
        self.assertTrue(result["stale"])

    def test_gaps_are_reported(self):
        result = collector.solar_data("kp", [kp((NOW - dt.timedelta(minutes=10)).isoformat()), kp(NOW.isoformat())], now=NOW)
        self.assertEqual(result["gap_count"], 1)

    def test_regions_choose_latest_day(self):
        rows = [{"observed_date": "2026-11-09", "region": 1},
                {"observed_date": "2026-11-10", "region": 2}]
        result = collector.solar_data("regions", rows, now=NOW)
        self.assertEqual([r["region"] for r in result["data"]], [2])

    def test_empty_flare_response_is_valid(self):
        for name in ("flares", "flare_history"):
            result = collector.solar_data(name, [], now=NOW)
            self.assertFalse(result["stale"])
            self.assertIsNone(result["observed_at"])

    def test_flare_schema_is_required_and_full_history_not_truncated(self):
        for row in ({}, {"max_time": NOW.isoformat(), "max_class": "Q1"}):
            with self.assertRaises(ValueError):
                collector.solar_data("flare_history", [row], now=NOW)
        rows = [{"max_time": (NOW - dt.timedelta(minutes=i)).isoformat(), "max_class": "C1.0"} for i in range(300)]
        self.assertEqual(len(collector.solar_data("flare_history", rows, now=NOW)["data"]), 300)

    def test_wrong_top_level_and_empty_kp_are_rejected(self):
        for raw in ([], {"error": "upstream changed"}, [1]):
            with self.assertRaises(ValueError):
                collector.solar_data("kp", raw, now=NOW)

    def test_nasa_metadata_is_dated_and_future_time_rejected(self):
        for name, text in (("aia", b"0193: 20261110_205000"), ("hmi", b"Time 20261110_205000\nIc http://example.com")):
            entry = collector.image_data(name, text, NOW)
            self.assertFalse(entry["stale"])
        with self.assertRaises(ValueError):
            collector.image_data("aia", b"0193: 20261118_205000", NOW)
        with self.assertRaises(ValueError):
            collector.image_data("hmi", b"<html>maintenance</html>", NOW)

    def run_collection(self, failed=(), previous=None, wrong_flare=False):
        def fake_fetch(url):
            if url in failed:
                raise urllib.error.URLError("simulated outage")
            if url == collector.FEEDS["kp"]:
                return json.dumps([kp(NOW.isoformat())]).encode()
            if url == collector.FEEDS["regions"]:
                return b'[{"observed_date":"2026-11-10","region":1}]'
            if url in (collector.FEEDS["flares"], collector.FEEDS["flare_history"]):
                return b'[{"unexpected":"schema"}]' if wrong_flare else b"[]"
            if url == collector.FEEDS["alerts"]:
                return b"[]"
            if url == collector.NASA["aia"][0]:
                return b"0193: 20261110_205000"
            if url == collector.NASA["hmi"][0]:
                return b"Time 20261110_205000"
            return b"<rss><channel/></rss>"
        with snapshot_directory() as directory:
            target = pathlib.Path(directory) / "data.json"
            if previous:
                target.write_text(json.dumps(previous), encoding="utf-8")
            with patch.object(collector, "OUT", target), patch.object(collector, "fetch", side_effect=fake_fetch), contextlib.redirect_stdout(io.StringIO()):
                code = collector.main(now=NOW)
            self.assertFalse(target.with_suffix(".json.tmp").exists())
            return code, json.loads(target.read_text(encoding="utf-8"))

    def test_success_and_empty_events(self):
        code, result = self.run_collection()
        self.assertEqual(code, 0)
        self.assertEqual(result["health"], "ok")
        self.assertEqual(result["solar"]["flare_history"]["data"], [])

    def test_partial_outage_returns_failure_and_retains_original_timestamp(self):
        old = {"data": [kp("2026-11-10T19:00:00")], "fetched_at": "2026-11-10T19:01:00Z",
               "observed_at": "2026-11-10T19:00:00Z"}
        code, result = self.run_collection([collector.FEEDS["kp"]], {"solar": {"kp": old}})
        self.assertEqual(code, 1)
        self.assertEqual(result["solar"]["kp"]["fetched_at"], old["fetched_at"])
        self.assertTrue(result["solar"]["kp"]["stale"])
        self.assertTrue(result["status"]["kp"].startswith("failed"))
        self.assertEqual(result["status"]["regions"], "ok")

    def test_all_noaa_down_still_saves_diagnostic(self):
        code, result = self.run_collection(list(collector.FEEDS.values()))
        self.assertEqual(code, 1)
        self.assertEqual(result["health"], "degraded")
        self.assertTrue(all(result["status"][name].startswith("failed") for name in collector.FEEDS))

    def test_invalid_flare_response_cannot_be_green(self):
        code, result = self.run_collection(wrong_flare=True)
        self.assertEqual(code, 1)
        self.assertTrue(result["status"]["flare_history"].startswith("failed"))

    def test_flare_outage_without_history_remains_unavailable(self):
        code, result = self.run_collection([collector.FEEDS["flares"], collector.FEEDS["flare_history"]])
        self.assertEqual(code, 1)
        self.assertNotIn("flares", result["solar"])

    def test_transient_network_errors_retry_but_404_does_not(self):
        with patch.object(collector.urllib.request, "urlopen", side_effect=urllib.error.URLError("offline")) as request, patch.object(collector.time, "sleep") as sleep:
            with self.assertRaises(urllib.error.URLError):
                collector.fetch("https://example.com")
            self.assertEqual(request.call_count, 3)
            self.assertEqual(sleep.call_count, 2)
        error = urllib.error.HTTPError("https://example.com", 404, "missing", {}, None)
        with patch.object(collector.urllib.request, "urlopen", side_effect=error) as request, patch.object(collector.time, "sleep") as sleep:
            with self.assertRaises(urllib.error.HTTPError):
                collector.fetch("https://example.com")
            self.assertEqual(request.call_count, 1)
            sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()

