"use strict";
(function () {
  const MINUTE = 60000;
  const HOUR = 60 * MINUTE;
  const REFRESH_MS = 5 * MINUTE;
  const MAX_FETCH_AGE = 45 * MINUTE;
  const IMAGE_URLS = {
    aia: "https://sdo.gsfc.nasa.gov/assets/img/latest/latest_512_0193.jpg",
    hmi: "https://sdo.gsfc.nasa.gov/assets/img/latest/latest_512_HMII.jpg"
  };
  function utcTime(value) {
    if (typeof value !== "string" || !value.trim()) return NaN;
    const text = value.trim().replace(" ", "T");
    return Date.parse(/^\d{4}-\d\d-\d\d$/.test(text) ? text + "T00:00:00Z" :
      /(?:Z|[+-]\d\d:\d\d)$/i.test(text) ? text : text + "Z");
  }
  function kpValue(row) {
    const raw = row?.kp_index ?? row?.Kp;
    if (raw == null || raw === "" || typeof raw === "boolean") return null;
    const value = Number(raw);
    return Number.isFinite(value) && value >= 0 && value <= 9 ? value : null;
  }
  function sourceState(entry, status, name, now = Date.now()) {
    if (!entry || !Number.isFinite(utcTime(entry.fetched_at))) return "unavailable";
    if (typeof status !== "string" || status.startsWith("failed")) return "failed";
    const fetched = utcTime(entry.fetched_at);
    if (fetched > now + 5 * MINUTE || now - fetched > MAX_FETCH_AGE || entry.stale || status === "stale") return "stale";
    const limit = name === "kp" ? 45 * MINUTE : name === "regions" ? 48 * HOUR :
      name.startsWith("nasa_") ? 2 * HOUR : null;
    const observed = utcTime(entry.observed_at);
    if (limit && (!Number.isFinite(observed) || observed > now + 5 * MINUTE || now - observed > limit)) return "stale";
    return status === "ok" ? "ok" : "unavailable";
  }
  function kpPoints(rows, now = Date.now()) {
    const byTime = new Map();
    for (const row of Array.isArray(rows) ? rows : []) {
      const t = utcTime(row?.time_tag), v = kpValue(row);
      if (Number.isFinite(t) && t >= now - 24 * HOUR && t <= now && v != null) byTime.set(t, {t, v});
    }
    return [...byTime.values()].sort((a, b) => a.t - b.t);
  }
  function flareDays(rows, fetchedAt, now = Date.now()) {
    const fetched = utcTime(fetchedAt);
    const days = Array.from({length: 7}, (_, i) => {
      const date = new Date(now - (6 - i) * 24 * HOUR).toISOString().slice(0, 10);
      return {date, covered: Number.isFinite(fetched) && Date.parse(date + "T00:00:00Z") <= fetched, C: 0, M: 0, X: 0};
    });
    for (const row of Array.isArray(rows) ? rows : []) {
      const t = utcTime(row?.max_time || row?.peak_time);
      if (!Number.isFinite(t) || t > now) continue;
      const day = days.find(d => d.date === new Date(t).toISOString().slice(0, 10));
      const type = String(row?.max_class || "").charAt(0);
      if (day?.covered && ["C", "M", "X"].includes(type)) day[type]++;
    }
    return days;
  }
  const api = {utcTime, kpValue, sourceState, kpPoints, flareDays};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (typeof document === "undefined") return;

  const $ = id => document.getElementById(id);
  const make = (tag, value) => { const e = document.createElement(tag); e.textContent = value; return e; };
  const fmt = value => Number.isFinite(utcTime(value)) ?
    new Date(utcTime(value)).toLocaleString("pt-BR", {timeZone: "America/Sao_Paulo"}) + " BRT" : "indisponível";
  const label = state => ({ok: "OK", stale: "DADO ANTIGO", failed: "FALHA · dado retido, se disponível", unavailable: "INDISPONÍVEL"}[state]);
  const suffix = state => state === "ok" ? "" : " · " + label(state);
  const gScale = value => value == null ? "Indisponível" :
    value >= 9 ? "G5" : value >= 8 ? "G4" : value >= 7 ? "G3" : value >= 6 ? "G2" : value >= 5 ? "G1" : "G0 — sem tempestade geomagnética";
  let lastPayload = null, inFlight = false, transportError = "", lastImageRefresh = 0;
  const imageLoaded = {};
  function imageStatus(id) {
    const entry = lastPayload?.images?.[id], name = "nasa_" + id;
    const state = sourceState(entry, lastPayload?.status?.[name], name);
    $(id + "Status").textContent = (imageLoaded[id] === false ? "Imagem indisponível. " :
      imageLoaded[id] ? "Imagem carregada. " : "Carregando imagem. ") +
      "Metadado NASA: " + fmt(entry?.observed_at) + suffix(state) +
      ". Confirme o rodapé: o metadado não comprova a captura exibida.";
  }
  function solarImages() {
    for (const [id, url] of Object.entries(IMAGE_URLS)) {
      const image = $(id);
      image.onload = () => { imageLoaded[id] = true; imageStatus(id); };
      image.onerror = () => { imageLoaded[id] = false; image.removeAttribute("src"); imageStatus(id); };
      image.src = url + "?v=" + Math.floor(Date.now() / REFRESH_MS);
    }
    lastImageRefresh = Date.now();
  }
  function canvasContext(id) {
    const canvas = $(id), w = Math.max(240, Math.round(canvas.getBoundingClientRect().width));
    const h = Math.round(canvas.getBoundingClientRect().height) || 245;
    const ratio = Math.min(2, window.devicePixelRatio || 1);
    canvas.width = w * ratio; canvas.height = h * ratio;
    const ctx = canvas.getContext("2d");
    ctx.scale(ratio, ratio); ctx.clearRect(0, 0, w, h);
    return {ctx, w, h};
  }
  function axes(ctx, w, h, max) {
    const a = {left: 35, right: w - 12, top: 12, bottom: h - 28};
    ctx.font = "11px system-ui";
    for (let i = 0; i <= 3; i++) {
      const y = a.top + (a.bottom - a.top) * i / 3;
      ctx.strokeStyle = "#34516a"; ctx.beginPath(); ctx.moveTo(a.left, y); ctx.lineTo(a.right, y); ctx.stroke();
      ctx.fillStyle = "#afc3d2"; ctx.fillText(String(Math.round(max * (3 - i) / 3)), 4, y + 4);
    }
    return a;
  }
  function emptyChart(id, message) {
    const {ctx, h} = canvasContext(id);
    ctx.fillStyle = "#afc3d2"; ctx.font = "13px system-ui"; ctx.fillText(message, 12, h / 2);
  }
  function drawKp(entry, state, now) {
    const points = kpPoints(entry?.data, now);
    if (points.length < 2) {
      emptyChart("kpChart", "Histórico insuficiente");
      $("kpNote").textContent = "Cobertura insuficiente" + suffix(state); return;
    }
    const {ctx, w, h} = canvasContext("kpChart"), a = axes(ctx, w, h, 9);
    const x = t => a.left + (t - (now - 24 * HOUR)) / (24 * HOUR) * (a.right - a.left);
    const y = v => a.bottom - v / 9 * (a.bottom - a.top);
    let gaps = 0;
    ctx.beginPath(); ctx.strokeStyle = "#75c9fc"; ctx.lineWidth = 2;
    points.forEach((p, i) => {
      if (!i || p.t - points[i - 1].t > 2 * MINUTE) { ctx.moveTo(x(p.t), y(p.v)); if (i) gaps++; }
      else ctx.lineTo(x(p.t), y(p.v));
    });
    ctx.stroke(); ctx.beginPath(); ctx.setLineDash([5, 4]); ctx.strokeStyle = "#f1ad5c";
    ctx.moveTo(a.left, y(5)); ctx.lineTo(a.right, y(5)); ctx.stroke(); ctx.setLineDash([]);
    ctx.fillStyle = "#afc3d2"; ctx.fillText("−24h", a.left, a.bottom + 19); ctx.fillText("Agora", a.right - 34, a.bottom + 19);
    const hours = (points.at(-1).t - points[0].t) / HOUR;
    $("kpNote").textContent = points.length + " leituras · intervalo coberto: " + hours.toFixed(1) +
      "h/24h · lacunas >2min: " + gaps + suffix(state) + ". Linha tracejada: Kp 5.";
  }
  function drawFlares(entry, state, now) {
    if (!Array.isArray(entry?.data) || state === "unavailable") {
      emptyChart("flareChart", "Histórico indisponível");
      $("flareNote").textContent = "Sem dados válidos; ausência não significa zero eventos."; return;
    }
    const days = flareDays(entry.data, entry.fetched_at, now);
    const max = Math.max(1, ...days.map(d => d.C + d.M + d.X));
    const {ctx, w, h} = canvasContext("flareChart"), a = axes(ctx, w, h, max);
    const step = (a.right - a.left) / 7;
    days.forEach((day, i) => {
      let height = 0;
      if (!day.covered) { ctx.fillStyle = "#ffd08a"; ctx.fillText("?", a.left + i * step + 8, a.bottom - 8); }
      else for (const [type, color] of [["C", "#6ec2f2"], ["M", "#f4c16c"], ["X", "#f07f83"]]) {
        const bar = day[type] / max * (a.bottom - a.top);
        ctx.fillStyle = color; ctx.fillRect(a.left + i * step + step * .19, a.bottom - height - bar, step * .62, bar); height += bar;
      }
      ctx.fillStyle = "#afc3d2"; ctx.font = "10px system-ui"; ctx.fillText(day.date.slice(5), a.left + i * step, a.bottom + 17);
    });
    $("flareNote").textContent = "Dias UTC · C azul, M amarelo, X vermelho · consulta: " + fmt(entry.fetched_at) +
      suffix(state) + ". ? = dia sem cobertura; zero só em resposta válida, limitada à última consulta.";
  }
  function render() {
    if (!lastPayload) return;
    const data = lastPayload, now = Date.now(), solar = data.solar || {}, states = {};
    for (const [name, entry] of Object.entries(solar)) states[name] = sourceState(entry, data.status?.[name], name, now);
    for (const name of ["kp", "regions", "flares", "flare_history", "alerts"]) states[name] ??= "unavailable";
    for (const [name, entry] of Object.entries(data.news || {})) states[name] = sourceState(entry, data.status?.[name], name, now);
    for (const name of ["aia", "hmi"]) states["nasa_" + name] = sourceState(data.images?.[name], data.status?.["nasa_" + name], "nasa_" + name, now);
    const age = now - utcTime(data.generated_at);
    $("time").textContent = "Coleta: " + fmt(data.generated_at) + " · verificação automática a cada 5 min";
    const notices = [];
    if (transportError) notices.push("Falha ao atualizar: " + transportError + ". Exibindo último snapshot recebido.");
    if (!Number.isFinite(age) || age < -5 * MINUTE) notices.push("Data da coleta inválida.");
    else if (age > MAX_FETCH_AGE) notices.push("ATENÇÃO: última coleta há " + Math.floor(age / MINUTE) + " minutos.");
    if (Object.values(states).some(state => state !== "ok")) notices.push("Há fontes antigas, indisponíveis ou com falha; confira a integridade.");
    $("notice").textContent = notices.join(" ");
    document.querySelector(".pulse").className = "pulse" + (notices.length ? " warn" : "");
    const points = kpPoints(solar.kp?.data, now), value = points.at(-1)?.v ?? null;
    $("kp").textContent = (value == null ? "Indisponível" : String(value)) + suffix(states.kp);
    $("gscale").textContent = "Escala NOAA: " + gScale(value) + " · observação: " + fmt(solar.kp?.observed_at);
    $("regions").textContent = (Array.isArray(solar.regions?.data) ? solar.regions.data.length : "Indisponível") + suffix(states.regions);
    $("regionsDate").textContent = "Dia de observação: " + (solar.regions?.observed_at?.slice(0, 10) || "indisponível") + " (UTC)";
    const events = (Array.isArray(solar.flares?.data) ? solar.flares.data : []).filter(row => Number.isFinite(utcTime(row.max_time)));
    events.sort((a, b) => utcTime(a.max_time) - utcTime(b.max_time));
    $("flares").textContent = (events.length ? events.at(-1).max_class :
      states.flares === "ok" ? "Sem evento reportado" : "Indisponível") + suffix(states.flares);
    $("flaresDate").textContent = "Último pico: " + fmt(events.at(-1)?.max_time) + " · consulta: " + fmt(solar.flares?.fetched_at);
    $("alerts").textContent = (Array.isArray(solar.alerts?.data) ? solar.alerts.data.length : "Indisponível") + suffix(states.alerts);
    drawKp(solar.kp, states.kp, now); drawFlares(solar.flare_history, states.flare_history, now);
    $("news").replaceChildren();
    for (const [source, entry] of Object.entries(data.news || {})) {
      const section = make("div", ""); section.append(make("h3", source + suffix(states[source])));
      const ul = make("ul", "");
      for (const item of entry.items || []) {
        const li = make("li", ""), link = make("a", item.title || "Sem título");
        if (/^https:\/\//.test(item.link)) { link.href = item.link; link.target = "_blank"; link.rel = "noopener noreferrer"; }
        li.append(link, make("span", " · " + (item.pubDate || ""))); ul.append(li);
      }
      section.append(ul); $("news").append(section);
    }
    $("status").replaceChildren();
    for (const [name, state] of Object.entries(states)) {
      const entry = solar[name] || data.news?.[name] || data.images?.[name.replace("nasa_", "")];
      const row = make("div", ""); row.className = "status-row";
      const signal = make("span", label(state) + " · consulta: " + fmt(entry?.fetched_at));
      signal.className = state === "ok" ? "good" : state === "stale" ? "warn" : "bad";
      row.append(make("span", name), signal); $("status").append(row);
    }
    imageStatus("aia"); imageStatus("hmi");
  }
  async function load() {
    if (inFlight) return;
    inFlight = true;
    const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch("data.json?v=" + Date.now(), {cache: "no-store", signal: controller.signal});
      if (!response.ok) throw Error("HTTP " + response.status);
      const payload = await response.json();
      if (!payload || typeof payload !== "object" || !payload.solar || !payload.status ||
          !Number.isFinite(utcTime(payload.generated_at))) throw Error("Snapshot inválido");
      lastPayload = payload; transportError = "";
    } catch (error) {
      transportError = error.name === "AbortError" ? "tempo de resposta excedido" : error.message;
    } finally {
      clearTimeout(timeout); inFlight = false;
      if (lastPayload) render();
      else $("notice").textContent = "Não foi possível carregar os dados: " + transportError;
    }
  }
  $("refresh").addEventListener("click", () => { solarImages(); load(); });
  window.addEventListener("resize", render);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) { render(); solarImages(); load(); } });
  setInterval(() => { if (!document.hidden) { solarImages(); load(); } }, REFRESH_MS);
  setInterval(() => { if (!document.hidden) { render(); if (Date.now() - lastImageRefresh >= REFRESH_MS) solarImages(); } }, 30000);
  solarImages(); load();
})();
