"""SENTINELA ZERO: coleta de dados públicos, sem credenciais nem bibliotecas externas."""
import datetime as dt
import json
import pathlib
import urllib.request
import xml.etree.ElementTree as ET

BASE = pathlib.Path(__file__).resolve().parents[1]
OUT = BASE / "docs" / "data.json"
NOW = dt.datetime.now(dt.timezone.utc)
ISO = NOW.isoformat()
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

def fetch(url):
    request = urllib.request.Request(url, headers={
        "User-Agent": "SentinelaZero/0.4 (open-source public data monitor)"
    })
    with urllib.request.urlopen(request, timeout=25) as response:
        return response.read()

def parse_time(value):
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=dt.timezone.utc) if parsed.tzinfo is None else parsed
    except (ValueError, TypeError):
        return None

def latest_time(rows, fields):
    dates = [parse_time(row.get(key)) for row in rows if isinstance(row, dict)
             for key in fields]
    dates = [value for value in dates if value]
    return max(dates).isoformat() if dates else None

def solar_data(name, raw):
    if not isinstance(raw, list):
        raise ValueError("Expected JSON list")
    observed = None
    limit = None
    if name == "regions":
        valid = [r for r in raw if isinstance(r, dict) and r.get("observed_date")]
        if not valid:
            raise ValueError("No dated regions")
        day = max(str(r["observed_date"]) for r in valid)
        data = [r for r in valid if r["observed_date"] == day]
        observed = day + "T00:00:00+00:00"
        limit = 48
    elif name == "kp":
        data = [r for r in raw if isinstance(r, dict) and r.get("time_tag")][-720:]
        observed = latest_time(data, ("time_tag",))
        limit = 3
    elif name == "flare_history":
        data = [r for r in raw if isinstance(r, dict)][-250:]
        observed = latest_time(data, ("max_time", "begin_time"))
        # A week without new flares is a valid result, not an outage.
        limit = None
    elif name == "flares":
        data = raw[-15:]
        observed = latest_time(data, ("max_time", "peak_time", "begin_time", "time_tag"))
        limit = None
    else:
        data = raw[:15]
    if name == "kp" and not data:
        raise ValueError("No Kp observations")
    measured = parse_time(observed)
    stale = bool(limit and (not measured or
                  (NOW - measured).total_seconds() > limit * 3600))
    return {"data": data, "source": FEEDS[name], "fetched_at": ISO,
            "observed_at": observed, "stale": stale}

def main():
    previous = {}
    try:
        previous = json.loads(OUT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    result = {"schema_version": "0.4", "generated_at": ISO,
              "solar": {}, "news": {}, "status": {}}
    for name, url in FEEDS.items():
        try:
            entry = solar_data(name, json.loads(fetch(url)))
            result["solar"][name] = entry
            result["status"][name] = "stale" if entry["stale"] else "ok"
        except Exception as error:
            previous_entry = previous.get("solar", {}).get(name)
            if previous_entry:
                result["solar"][name] = {**previous_entry, "stale": True}
            result["status"][name] = "failed: " + type(error).__name__
    for name, url in NEWS.items():
        try:
            root = ET.fromstring(fetch(url))
            items = []
            for item in root.findall(".//item")[:15]:
                items.append({key: (item.findtext(key) or "").strip()
                              for key in ("title", "link", "pubDate")})
            result["news"][name] = {"items": items, "source": url,
                                    "fetched_at": ISO, "stale": False}
            result["status"][name] = "ok"
        except Exception as error:
            old = previous.get("news", {}).get(name)
            if old:
                result["news"][name] = {**old, "stale": True}
            result["status"][name] = "failed: " + type(error).__name__
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(json.dumps(result["status"], ensure_ascii=False, indent=2))
    if result["status"].get("kp") != "ok" and result["status"].get("regions") != "ok":
        raise SystemExit("Both time-sensitive NOAA feeds unavailable or stale")

if __name__ == "__main__":
    main()
