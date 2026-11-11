"""Public-feed collector; failed refreshes retain dated observations and diagnostics."""
import datetime as dt
import json
import hashlib
import html
import math
import pathlib
import re
import time
import urllib.error
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET

BASE = pathlib.Path(__file__).resolve().parents[1]
OUT = BASE / "docs" / "data.json"
NOW = dt.datetime.now(dt.timezone.utc)
FEEDS = {
    "regions": "https://services.swpc.noaa.gov/json/solar_regions.json",
    "kp": "https://services.swpc.noaa.gov/json/planetary_k_index_1m.json",
    "flares": "https://services.swpc.noaa.gov/json/goes/primary/xray-flares-latest.json",
    "flare_history": "https://services.swpc.noaa.gov/json/goes/primary/xray-flares-7-day.json",
    "alerts": "https://services.swpc.noaa.gov/products/alerts.json",
}
NEWS = {
    "BBC World": "https://feeds.bbci.co.uk/news/world/rss.xml",
    "Al Jazeera": "https://www.aljazeera.com/xml/rss/all.xml",
}
NASA = {
    "aia": ("https://sdo.gsfc.nasa.gov/assets/img/latest/times0193.txt",
            "https://sdo.gsfc.nasa.gov/assets/img/latest/latest_512_0193.jpg"),
    "hmi": ("https://sdo.gsfc.nasa.gov/assets/img/latest/hmitimes.txt",
            "https://sdo.gsfc.nasa.gov/assets/img/latest/latest_512_HMII.jpg"),
}


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": "SentinelaZero/0.4.1"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            if error.code not in (408, 429, 500, 502, 503, 504) or attempt == 2:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == 2:
                raise
        time.sleep(attempt + 1)


def parse_time(value):
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=dt.timezone.utc) if parsed.tzinfo is None else parsed.astimezone(dt.timezone.utc)
    except (ValueError, TypeError, OverflowError):
        return None


def checked_time(value, now):
    parsed = parse_time(value)
    if parsed is None or parsed > now + dt.timedelta(minutes=5):
        raise ValueError("Invalid or future observation time")
    return parsed


def kp_value(row):
    raw = row.get("kp_index", row.get("Kp"))
    if raw is None or raw == "" or isinstance(raw, bool):
        raise ValueError("Missing Kp value")
    value = float(raw)
    if not math.isfinite(value) or not 0 <= value <= 9:
        raise ValueError("Kp outside 0..9")
    return value


def latest_time(rows, fields):
    values = [parse_time(row.get(key)) for row in rows for key in fields]
    values = [value for value in values if value is not None]
    return max(values).isoformat() if values else None


def solar_data(name, raw, previous=None, now=None):
    now = now or NOW
    if not isinstance(raw, list) or any(not isinstance(row, dict) for row in raw):
        raise ValueError("Expected a list of records")
    observed = None
    stale = False
    extra = {}
    if name == "kp":
        if not raw:
            raise ValueError("No Kp observations")
        incoming = []
        for row in raw:
            stamp = checked_time(row.get("time_tag"), now)
            incoming.append({**row, "time_tag": stamp.isoformat(), "kp_index": kp_value(row)})
        # Freshness refers to the current response, not retained history.
        observed = latest_time(incoming, ("time_tag",))
        stale = now - parse_time(observed) > dt.timedelta(minutes=45)
        cutoff = now - dt.timedelta(hours=24)
        merged = {}
        for row in (previous or {}).get("data", []):
            try:
                stamp = checked_time(row.get("time_tag"), now)
                value = kp_value(row)
            except (AttributeError, ValueError, TypeError):
                continue
            if cutoff <= stamp <= now:
                merged[stamp.isoformat()] = {**row, "time_tag": stamp.isoformat(), "kp_index": value}
        for row in incoming:
            stamp = parse_time(row["time_tag"])
            if cutoff <= stamp <= now:
                merged[row["time_tag"]] = row
        data = [merged[key] for key in sorted(merged)]
        stamps = [parse_time(row["time_tag"]) for row in data]
        extra = {"coverage_hours": round((stamps[-1] - stamps[0]).total_seconds() / 3600, 3) if stamps else 0,
                 "gap_count": sum((b - a).total_seconds() > 120 for a, b in zip(stamps, stamps[1:])),
                 "window_start": cutoff.isoformat(), "window_end": now.isoformat()}
    elif name == "regions":
        if not raw:
            raise ValueError("No dated regions")
        for row in raw:
            day = row.get("observed_date")
            if not isinstance(day, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
                raise ValueError("Invalid region date")
            checked_time(day, now)
        day = max(row["observed_date"] for row in raw)
        data = [row for row in raw if row["observed_date"] == day]
        observed = checked_time(day, now).isoformat()
        stale = now - parse_time(observed) > dt.timedelta(hours=48)
    elif name in ("flares", "flare_history"):
        data = []
        for row in raw:
            peak = checked_time(row.get("max_time") or row.get("peak_time"), now)
            if not re.fullmatch(r"[ABCMX]\d+(?:\.\d+)?", str(row.get("max_class", ""))):
                raise ValueError("Invalid flare class")
            copy = {**row, "max_time": peak.isoformat()}
            for field in ("begin_time", "end_time", "time_tag"):
                if row.get(field):
                    copy[field] = checked_time(row[field], now).isoformat()
            data.append(copy)
        data.sort(key=lambda row: row["max_time"])
        observed = latest_time(data, ("max_time",))
        # No events is valid; event age is not feed age.
    elif name == "alerts":
        for row in raw:
            checked_time(row.get("issue_datetime"), now)
            if not isinstance(row.get("message"), str):
                raise ValueError("Invalid bulletin")
        data = sorted(raw, key=lambda row: parse_time(row["issue_datetime"]), reverse=True)[:15]
        observed = latest_time(data, ("issue_datetime",))
    else:
        raise ValueError("Unknown feed")
    return {"data": data, "source": FEEDS[name], "fetched_at": now.isoformat(),
            "observed_at": observed, "stale": stale, **extra}


def image_data(name, raw, now):
    text = raw.decode("utf-8")
    pattern = r"^0193:\s*(\d{8}_\d{6})\s*$" if name == "aia" else r"^Time\s+(\d{8}_\d{6})\s*$"
    match = re.search(pattern, text, re.MULTILINE)
    if not match:
        raise ValueError("Missing NASA observation time")
    stamp = dt.datetime.strptime(match[1], "%Y%m%d_%H%M%S").replace(tzinfo=dt.timezone.utc)
    checked_time(stamp.isoformat(), now)
    return {"source": NASA[name][0], "image_url": NASA[name][1],
            "observed_at": stamp.isoformat(), "fetched_at": now.isoformat(),
            "stale": now - stamp > dt.timedelta(hours=2)}


TRANSLATION_URL = "https://api.mymemory.translated.net/get"
NEWS_LANGUAGES = {"BBC World": "en", "Al Jazeera": "en"}
TRANSLATION_BUDGET = 4500  # Conservative rolling 24h ceiling; anonymous provider limit is 5000.


def translation_fetch(url):
    # A translation outage must not delay the scientific feeds with retries.
    request = urllib.request.Request(url, headers={"User-Agent": "SentinelaZero/0.4.1"})
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.read()


def translate_headlines(news, previous, now):
    old = previous if isinstance(previous, dict) else {}
    cutoff = now - dt.timedelta(days=7)
    cache = {key: value for key, value in old.get("cache", {}).items()
             if isinstance(value, dict) and parse_time(value.get("at"))
             and cutoff <= parse_time(value["at"]) <= now}
    usage = [row for row in old.get("usage", [])
             if isinstance(row, dict) and parse_time(row.get("at"))
             and now - dt.timedelta(hours=24) < parse_time(row["at"]) <= now
             and isinstance(row.get("chars"), int) and 0 < row["chars"] <= 500]
    spent = sum(row["chars"] for row in usage)
    blocked_until = parse_time(old.get("blocked_until"))
    started = time.monotonic()
    calls = 0
    sources = list(news.items())
    # Alternate sources so one feed cannot consume the whole run's allowance.
    for index in range(max((len(entry.get("items", [])) for _, entry in sources), default=0)):
        for source, entry in sources:
            if index >= len(entry.get("items", [])):
                continue
            item = entry["items"][index]
            title = item.get("title", "")
            language = NEWS_LANGUAGES.get(source)
            item["title_original"] = title
            item["source_language"] = language or "unknown"
            item.pop("title_pt", None)
            item["translation_status"] = "unavailable"
            if not title or not language:
                continue
            key = hashlib.sha256((language + "|pt-BR|" + title).encode("utf-8")).hexdigest()
            saved = cache.get(key, {})
            if saved.get("original") == title and saved.get("text"):
                item["title_pt"] = saved["text"]
                item["translation_status"] = "translated"
                continue
            if entry.get("stale"):
                continue
            retry = parse_time(saved.get("retry_after"))
            if retry and retry > now:
                continue
            if (len(title.encode("utf-8")) > 500 or spent + len(title) > TRANSLATION_BUDGET
                    or (blocked_until and blocked_until > now)
                    or calls >= 30 or time.monotonic() - started >= 45):
                item["translation_status"] = "limited"
                continue
            usage.append({"at": now.isoformat(), "chars": len(title)})
            spent += len(title)
            calls += 1
            cache[key] = {"original": title, "at": now.isoformat(),
                          "retry_after": (now + dt.timedelta(hours=1)).isoformat()}
            try:
                query = urllib.parse.urlencode({"q": title, "langpair": language + "|pt-BR", "mt": "1"})
                result = json.loads(translation_fetch(TRANSLATION_URL + "?" + query))
                if result.get("quotaFinished"):
                    blocked_until = now + dt.timedelta(hours=24)
                    item["translation_status"] = "limited"
                    continue
                if str(result.get("responseStatus")) != "200":
                    raise ValueError("Translation provider rejected request")
                match = float(result.get("responseData", {}).get("match", 0))
                if not math.isfinite(match) or match < 0.7:
                    raise ValueError("Low-confidence translation match")
                translated = result.get("responseData", {}).get("translatedText")
                if not isinstance(translated, str):
                    raise ValueError("Missing translation")
                translated = html.unescape(translated).strip()
                if not translated or translated == title or len(translated) > 2000 or translated.upper().startswith("MYMEMORY WARNING"):
                    raise ValueError("No usable translation")
                cache[key] = {"original": title, "text": translated, "at": now.isoformat()}
                item["title_pt"] = translated
                item["translation_status"] = "translated"
            except (OSError, ValueError, TypeError, AttributeError):
                # Keep the source headline; never present an error as a translation.
                pass
    cache = dict(sorted(cache.items(), key=lambda pair: pair[1]["at"], reverse=True)[:500])
    return {"provider": "MyMemory", "target_language": "pt-BR", "cache": cache,
            "usage": usage, "blocked_until": blocked_until.isoformat() if blocked_until else None}


def main(now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    try:
        previous = json.loads(OUT.read_text(encoding="utf-8"))
        if not isinstance(previous, dict):
            previous = {}
    except (OSError, ValueError):
        previous = {}
    result = {"schema_version": "0.4.1", "generated_at": now.isoformat(),
              "solar": {}, "images": {}, "news": {}, "status": {}}

    def failure(section, name, error, status_name=None):
        old = previous.get(section, {}).get(name)
        if isinstance(old, dict):
            result[section][name] = {**old, "stale": True}
        result["status"][status_name or name] = "failed: " + type(error).__name__

    for name, url in FEEDS.items():
        try:
            entry = solar_data(name, json.loads(fetch(url)), previous.get("solar", {}).get(name), now)
            result["solar"][name] = entry
            result["status"][name] = "stale" if entry["stale"] else "ok"
        except Exception as error:
            failure("solar", name, error)
    for name, (url, _) in NASA.items():
        try:
            entry = image_data(name, fetch(url), now)
            result["images"][name] = entry
            result["status"]["nasa_" + name] = "stale" if entry["stale"] else "ok"
        except Exception as error:
            failure("images", name, error, "nasa_" + name)
    for name, url in NEWS.items():
        try:
            root = ET.fromstring(fetch(url))
            if root.tag != "rss" or root.find("channel") is None:
                raise ValueError("Expected RSS channel")
            items = [{key: (item.findtext(key) or "").strip() for key in ("title", "link", "pubDate")}
                     for item in root.findall("./channel/item")[:15]]
            result["news"][name] = {"items": items, "source": url,
                                    "fetched_at": now.isoformat(), "stale": False}
            result["status"][name] = "ok"
        except Exception as error:
            failure("news", name, error)
    result["translation"] = translate_headlines(result["news"], previous.get("translation"), now)
    bad = [name for name, status in result["status"].items() if status != "ok"]
    result["health"] = "degraded" if bad else "ok"
    # Save diagnostics before signalling failure. Never renew retained timestamps.
    OUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUT.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(OUT)
    print(json.dumps(result["status"], ensure_ascii=False, indent=2))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
