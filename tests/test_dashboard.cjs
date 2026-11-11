"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const dashboard = require("../docs/dashboard.js");
const NOW = Date.parse("2026-11-10T21:00:00Z");
const minute = 60000;
const entry = (data = []) => ({data, fetched_at: new Date(NOW).toISOString(), observed_at: new Date(NOW).toISOString(), stale: false});
function fixture() {
  return {generated_at: new Date(NOW).toISOString(), solar: {
    kp: entry([{time_tag: "2026-11-10T20:59:00", kp_index: 0}]), regions: entry([{region: 1}]),
    flares: entry([]), flare_history: entry([]), alerts: entry([])
  }, images: {aia: entry(), hmi: entry()}, news: {},
  status: {kp: "ok", regions: "ok", flares: "ok", flare_history: "ok", alerts: "ok", nasa_aia: "ok", nasa_hmi: "ok"}};
}
const settle = () => new Promise(resolve => setImmediate(resolve));
function browser(payload = fixture()) {
  let now = NOW, nextPayload = payload, failure = null, requests = 0, pending = false;
  const elements = new Map(), intervals = new Map(), timeouts = new Map(), listeners = new Map();
  const ctx = new Proxy({}, {get: (target, key) => target[key] || (() => {})});
  function element() {
    return {textContent: "", className: "", children: [], listeners: {},
      append(...children) { this.children.push(...children); },
      replaceChildren() { this.children = []; },
      addEventListener(name, callback) { this.listeners[name] = callback; },
      removeAttribute(name) { delete this[name]; },
      getBoundingClientRect() { return {width: 500, height: 245}; },
      getContext() { return ctx; }};
  }
  const document = {hidden: false,
    getElementById(id) { if (!elements.has(id)) elements.set(id, element()); return elements.get(id); },
    createElement: element,
    querySelector() { return this.getElementById("pulse"); },
    addEventListener(name, callback) { listeners.set(name, callback); }};
  const sandbox = {module: {exports: {}}, document, AbortController,
    window: {devicePixelRatio: 1, addEventListener() {}},
    Date: class extends Date { static now() { return now; } },
    setInterval(callback, ms) { intervals.set(ms, callback); return ms; },
    setTimeout(callback, ms) { timeouts.set(ms, callback); return ms; },
    clearTimeout(id) { timeouts.delete(id); },
    fetch: async (url, options) => {
      requests++;
      if (pending) return new Promise((resolve, reject) => {
        options.signal.addEventListener("abort", () => reject(Object.assign(Error("aborted"), {name: "AbortError"})));
      });
      if (failure) throw Error(failure);
      return {ok: true, json: async () => nextPayload};
    }};
  vm.runInNewContext(fs.readFileSync(require.resolve("../docs/dashboard.js"), "utf8"), sandbox);
  return {document, elements, intervals, timeouts, listeners,
    get requests() { return requests; },
    get(id) { return document.getElementById(id); },
    advance(ms) { now += ms; },
    payload(value) { nextPayload = value; },
    fail(message) { failure = message; },
    hang() { pending = true; }};
}

test("geopolitical source and thematic filters retain original links", async () => {
  const data = fixture();
  data.news = {
    "BBC World": {items: [{title: "Military conflict escalates", title_original: "Military conflict escalates", link: "https://www.bbc.com/news/example", pubDate: "Tue, 10 Nov 2026 20:00:00 GMT"}], fetched_at: new Date(NOW).toISOString()},
    "Al Jazeera": {items: [{title: "Energy markets fluctuate", title_original: "Energy markets fluctuate", link: "https://www.aljazeera.com/news/example", pubDate: "Tue, 10 Nov 2026 20:00:00 GMT"}], fetched_at: new Date(NOW).toISOString()}
  };
  const app = browser(data); await settle();
  assert.match(app.get("newsSummary").textContent, /2 manchetes exibidas/);
  const selector = app.get("newsTopic");
  selector.value = "security"; selector.listeners.change.call(selector);
  assert.match(app.get("newsSummary").textContent, /1 manchetes exibidas/);
  const group = app.get("news").children[0];
  assert.equal(group.children[0].textContent, "BBC World · INDISPONÍVEL");
  assert.equal(group.children[2].children[0].children[0].href, "https://www.bbc.com/news/example");
  selector.value = "all"; selector.listeners.change.call(selector);
  const source = app.get("newsSource");
  source.value = "Al Jazeera"; source.listeners.change.call(source);
  assert.match(app.get("newsSummary").textContent, /1 manchetes exibidas/);
  assert.equal(app.get("news").children[0].children[0].textContent, "Al Jazeera · INDISPONÍVEL");
});

test("NOAA timestamps without suffix are UTC in any host timezone", () => {
  assert.equal(dashboard.utcTime("2026-11-10T20:19:00"), Date.parse("2026-11-10T20:19:00Z"));
  assert.equal(dashboard.utcTime("2026-11-10 20:19:00"), Date.parse("2026-11-10T20:19:00Z"));
  assert.equal(dashboard.utcTime("2026-11-10T17:19:00-03:00"), Date.parse("2026-11-10T20:19:00Z"));
  assert.ok(Number.isNaN(dashboard.utcTime("bad")));
});

test("diagnosis keeps geomagnetic and solar observations separate", () => {
  const data = fixture();
  data.solar.flares.data = [{max_time: "2026-11-10T18:18:00Z", max_class: "C2.2"}];
  const result = dashboard.buildDiagnosis(data, NOW);
  assert.equal(result.level, "below");
  assert.match(result.title, /Kp abaixo/);
  assert.match(result.solar, /C2.2 \(classe C\)/);
  assert.match(result.solar, /não demonstra que o flare continue/);
});
test("diagnosis applies NOAA geomagnetic thresholds", () => {
  for (const [kp, expected] of [[4.99, null], [5, "G1"], [6, "G2"], [7, "G3"], [8, "G4"], [9, "G5"]]) {
    const data = fixture(); data.solar.kp.data[0].kp_index = kp;
    const result = dashboard.buildDiagnosis(data, NOW);
    assert.equal(result.level, expected ? "storm" : "below");
    if (expected) assert.ok(result.title.endsWith(expected));
  }
});
test("stale, failed or invalid Kp cannot produce a reassuring diagnosis", () => {
  for (const variant of ["stale", "failed", "missing", "invalid"]) {
    const data = fixture();
    if (variant === "stale") data.solar.kp.observed_at = "2026-11-10T18:00:00Z";
    if (variant === "failed") data.status.kp = "failed: URLError";
    if (variant === "missing") delete data.solar.kp;
    if (variant === "invalid") data.solar.kp.data[0].kp_index = 99;
    const result = dashboard.buildDiagnosis(data, NOW);
    assert.equal(result.level, "limited");
    assert.match(result.title, /Dados insuficientes/);
  }
});
test("old snapshot suspends current assessment even if stored statuses say OK", () => {
  const data = fixture(); data.generated_at = "2026-11-10T18:00:00Z";
  const result = dashboard.buildDiagnosis(data, NOW);
  assert.equal(result.level, "limited");
  assert.match(result.solar, /ausente, antigo ou com falha/);
});
test("region and bulletin counts do not change geomagnetic severity", () => {
  const data = fixture(); data.solar.regions.data = Array(50).fill({}); data.solar.alerts.data = Array(15).fill({});
  const result = dashboard.buildDiagnosis(data, NOW);
  assert.equal(result.level, "below");
  assert.match(result.context.join(" "), /contagem isolada não prevê/);
  assert.match(result.context.join(" "), /vigência.*não foram classificados/);
});
test("valid empty flare response is distinct from unavailable data", () => {
  assert.match(dashboard.buildDiagnosis(fixture(), NOW).solar, /não retornou evento/);
  const data = fixture(); delete data.solar.flares;
  assert.match(dashboard.buildDiagnosis(data, NOW).solar, /ausente, antigo ou com falha/);
});
test("diagnosis does not interpret future flare records", () => {
  const data = fixture(); data.solar.flares.data = [{max_time: "2026-11-11T21:00:00Z", max_class: "X9"}];
  const result = dashboard.buildDiagnosis(data, NOW);
  assert.doesNotMatch(result.solar, /X9/);
  assert.match(result.limits.join(" "), /classe e horário válidos/);
});
test("partial Kp history is disclosed and diagnosis ages on tick", async () => {
  const data = fixture();
  data.solar.kp.data.push({time_tag: "2026-11-10T20:00:00Z", kp_index: 1});
  assert.match(dashboard.buildDiagnosis(data, NOW).limits.join(" "), /Não há base contínua de 24 horas/);
  const app = browser(data); await settle();
  assert.match(app.get("diagnosisTitle").textContent, /Kp abaixo/);
  app.advance(46 * minute); app.intervals.get(30000)();
  assert.match(app.get("diagnosisTitle").textContent, /Dados insuficientes/);
});

test("Portuguese headline links to original article and reveals original title", async () => {
  const data = fixture();
  data.news = {"BBC World": {items: [{title: "Peace talks resume", title_original: "Peace talks resume",
    title_pt: "Negociações de paz são retomadas", translation_status: "translated", link: "https://example.com/story"}],
    fetched_at: data.generated_at, stale: false}};
  data.status["BBC World"] = "ok";
  const app = browser(data); await settle();
  const section = app.get("news").children[0], li = section.children.at(-1).children[0];
  assert.equal(li.children[0].textContent, "Negociações de paz são retomadas");
  assert.equal(li.children[0].href, "https://example.com/story");
  assert.equal(li.children[2].children[0].textContent, "Ver título original");
  assert.equal(li.children[2].children[1].textContent, "Peace talks resume");
});
test("missing translation is labelled and keeps original instead of blank text", async () => {
  const data = fixture();
  data.news = {"BBC World": {items: [{title: "Peace talks resume", translation_status: "limited",
    link: "https://example.com/story"}], fetched_at: data.generated_at}};
  data.status["BBC World"] = "ok";
  const app = browser(data); await settle();
  const li = app.get("news").children[0].children.at(-1).children[0];
  assert.equal(li.children[0].textContent, "Peace talks resume");
  assert.match(li.children[2].textContent, /tradução indisponível ou limite gratuito/);
});
test("Kp missing values stay missing and true zero remains zero", () => {
  for (const value of [null, "", true, -1, 99, Infinity, "bad"]) assert.equal(dashboard.kpValue({kp_index: value}), null);
  assert.equal(dashboard.kpValue({kp_index: 0}), 0);
});
test("source age changes without another collection; empty flare response remains valid", () => {
  assert.equal(dashboard.sourceState(entry(), "ok", "flares", NOW), "ok");
  assert.equal(dashboard.sourceState(entry(), "ok", "kp", NOW + 46 * minute), "stale");
  assert.equal(dashboard.sourceState(entry(), "failed: URLError", "kp", NOW), "failed");
  assert.equal(dashboard.sourceState(null, "failed: URLError", "kp", NOW), "unavailable");
});
test("Kp chart deduplicates, orders, excludes future and invalid readings", () => {
  const rows = [{time_tag: "2026-11-10T21:01:00Z", kp_index: 4},
    {time_tag: "2026-11-10T20:59:00", kp_index: 1},
    {time_tag: "2026-11-10T20:59:00Z", kp_index: 2},
    {time_tag: "2026-11-10T20:58:00Z", kp_index: null}];
  assert.deepEqual(dashboard.kpPoints(rows, NOW), [{t: NOW - minute, v: 2}]);
});
test("flare days after the last successful query are not labelled zero", () => {
  const days = dashboard.flareDays([], "2026-11-09T23:00:00Z", NOW);
  assert.equal(days.at(-1).covered, false);
  assert.equal(days.at(-2).covered, true);
});
test("initial load renders real zero and valid absence of events", async () => {
  const app = browser(); await settle();
  assert.equal(app.get("kp").textContent, "0");
  assert.equal(app.get("flares").textContent, "Sem evento reportado");
  assert.equal(app.timeouts.size, 0);
  assert.match(app.get("time").textContent, /BRT/);
});
test("daily regions keep their UTC day and flare peak does not use feed heartbeat", async () => {
  const data = fixture(); data.solar.regions.observed_at = "2026-11-10T00:00:00Z";
  data.solar.flares.data = [{max_time: "2026-11-10T18:18:00Z", max_class: "C2.2"}];
  const app = browser(data); await settle();
  assert.match(app.get("regionsDate").textContent, /2026-11-10 \(UTC\)/);
  assert.match(app.get("flaresDate").textContent, /15:18:00 BRT/);
});
test("five-minute refresh reads a new snapshot", async () => {
  const app = browser(); await settle();
  const data = fixture(); data.solar.kp.data[0].kp_index = 4; app.payload(data);
  app.intervals.get(5 * minute)(); await settle();
  assert.equal(app.requests, 2); assert.equal(app.get("kp").textContent, "4");
});
test("age warning and card change on the 30-second tick", async () => {
  const app = browser(); await settle(); app.advance(46 * minute);
  app.intervals.get(30000)();
  assert.match(app.get("notice").textContent, /46 minutos/);
  assert.match(app.get("kp").textContent, /DADO ANTIGO/);
  assert.match(app.get("pulse").className, /warn/);
});
test("network failure retains readings and visibly reports failed refresh", async () => {
  const app = browser(); await settle(); app.fail("offline");
  app.intervals.get(5 * minute)(); await settle();
  assert.equal(app.get("kp").textContent, "0");
  assert.match(app.get("notice").textContent, /Falha ao atualizar: offline/);
});
test("no flare data is unavailable rather than a zero-events assertion", async () => {
  const data = fixture(); delete data.solar.flares; delete data.solar.flare_history;
  data.status.flares = "failed: URLError"; data.status.flare_history = "failed: URLError";
  const app = browser(data); await settle();
  assert.match(app.get("flares").textContent, /Indisponível/);
  assert.match(app.get("flareNote").textContent, /ausência não significa zero/);
});
test("hidden tabs pause fetches and refresh when shown", async () => {
  const app = browser(); await settle(); app.document.hidden = true;
  app.intervals.get(5 * minute)(); await settle(); assert.equal(app.requests, 1);
  app.document.hidden = false; app.listeners.get("visibilitychange")(); await settle();
  assert.equal(app.requests, 2);
});
test("overlapping requests are suppressed and a timeout releases the lock", async () => {
  const app = browser(); await settle(); app.hang();
  app.intervals.get(5 * minute)(); app.intervals.get(5 * minute)();
  assert.equal(app.requests, 2);
  app.timeouts.get(15000)(); await settle();
  assert.match(app.get("notice").textContent, /tempo de resposta excedido/);
  assert.equal(app.timeouts.size, 0);
});
