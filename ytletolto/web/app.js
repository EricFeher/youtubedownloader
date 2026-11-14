"use strict";

const $ = (id) => document.getElementById(id);
const api = () => window.pywebview.api;
// Beállítás mentése; a pywebview API még nem biztos, hogy kész (pl. visszaállított űrlapállapotnál).
const saveSettings = (changes) => window.pywebview?.api?.save_settings(changes);

const el = {
  form: $("url-form"), url: $("url"), paste: $("paste-btn"),
  preview: $("preview"), skeleton: $("skeleton"), probeError: $("probe-error"), notice: $("notice"),
  thumb: $("thumb"), badge: $("badge"), duration: $("duration"),
  kind: $("preview-kind"), title: $("title"), uploader: $("uploader"),
  batch: $("batch"), batchCount: $("batch-count"), batchList: $("batch-list"), batchClear: $("batch-clear"),
  videoOptions: $("video-options"), audioOptions: $("audio-options"),
  containerHint: $("container-hint"), audioFormatHint: $("audio-format-hint"), compatibleRow: $("compatible-row"),
  compatible: $("compatible"), playlistRow: $("playlist-row"), playlist: $("playlist"),
  folder: $("folder"), chooseFolder: $("choose-folder"), openFolder: $("open-folder"),
  download: $("download-btn"), downloadLabel: $("download-label"),
  queue: $("queue"), queueList: $("queue-list"), queueCount: $("queue-count"), clearFinished: $("clear-finished"),
  log: $("log"), toolsWarning: $("tools-warning"),
};

const state = {
  probeToken: 0, probedUrl: "", probeInfo: null, maxHeight: null, isPlaylist: false,
  batch: [], // több beillesztett link, amíg sorba nem kerülnek
  queueVersion: -1, items: new Map(),
};

const radios = (name) => [...document.querySelectorAll(`input[name="${name}"]`)];
const radioValue = (name) => radios(name).find((r) => r.checked)?.value;
const setRadio = (name, value) => radios(name).forEach((r) => { r.checked = r.value === value; });

// --- Formázás ----------------------------------------------------------------

function formatDuration(seconds) {
  if (!seconds) return "";
  const h = Math.floor(seconds / 3600), m = Math.floor((seconds % 3600) / 60), s = seconds % 60;
  const pad = (n) => String(n).padStart(2, "0");
  return h ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
}

function formatSpeed(bps) {
  if (!bps) return "";
  const units = ["B/s", "KB/s", "MB/s", "GB/s"];
  let i = 0;
  while (bps >= 1024 && i < units.length - 1) { bps /= 1024; i++; }
  return `${bps.toFixed(1)} ${units[i]}`;
}

function heightLabel(h) {
  if (!h) return "";
  if (h >= 4320) return "8K";
  if (h >= 2160) return "4K";
  if (h >= 1440) return "2K";
  if (h >= 720) return "HD";
  return `${h}p`;
}

const cssUrl = (url) => (url ? `url("${url.replace(/"/g, "%22")}")` : "");

const looksLikeUrl = (text) => /^(https?:\/\/)?([\w-]+\.)*(youtube\.com|youtu\.be|youtube-nocookie\.com)\//i.test(text.trim())
  || /^https?:\/\/\S+\.\S+/i.test(text.trim());
const hasPlaylist = (text) => /[?&]list=/.test(text);

// --- Napló -------------------------------------------------------------------

function log(text, level = "info") {
  const line = document.createElement("div");
  if (level !== "info") line.className = level;
  line.textContent = text;
  el.log.appendChild(line);
  el.log.scrollTop = el.log.scrollHeight;
}

function showNotice(text, error = false) {
  el.notice.textContent = text;
  el.notice.classList.toggle("error", error);
  el.notice.hidden = !text;
}

// --- Előnézet ----------------------------------------------------------------

function clearPreview() {
  state.probeToken++;
  state.probedUrl = "";
  state.probeInfo = null;
  el.preview.hidden = el.skeleton.hidden = el.probeError.hidden = true;
  el.playlistRow.hidden = true;
  state.isPlaylist = false;
  state.maxHeight = null;
  updateQualityLimits(null);
}

async function runProbe() {
  const url = el.url.value.trim();
  if (!url || !looksLikeUrl(url)) { clearPreview(); return; }
  if (url === state.probedUrl) return;

  const token = ++state.probeToken;
  state.probedUrl = url;
  state.probeInfo = null;
  el.preview.hidden = el.probeError.hidden = true;
  el.skeleton.hidden = false;

  const res = await api().probe(url);
  if (token !== state.probeToken) return; // közben új link érkezett
  el.skeleton.hidden = true;

  if (!res.ok) {
    el.probeError.textContent = res.error;
    el.probeError.hidden = false;
    state.probedUrl = "";
    return;
  }
  showPreview(res.info, url);
}

function showPreview(info, url) {
  el.thumb.style.backgroundImage = cssUrl(info.thumbnail);
  el.title.textContent = info.title;
  el.uploader.textContent = info.uploader;

  if (info.kind === "playlist") {
    el.kind.textContent = info.count ? `Lejátszási lista · ${info.count} videó` : "Lejátszási lista";
    el.badge.hidden = el.duration.hidden = true;
    el.playlistRow.hidden = true; // tiszta lista-link: mindenképp a teljes listát töltjük le
  } else {
    el.kind.textContent = "Videó";
    el.badge.textContent = heightLabel(info.max_height);
    el.badge.hidden = !info.max_height;
    el.duration.textContent = formatDuration(info.duration);
    el.duration.hidden = !info.duration;
    el.playlistRow.hidden = !hasPlaylist(url);
    el.playlist.checked = false;
  }
  state.probeInfo = info;
  state.isPlaylist = info.kind === "playlist";
  state.maxHeight = info.kind === "video" ? info.max_height : null;
  updateQualityLimits(state.maxHeight);
  el.preview.hidden = false;
}

// A videónál nem elérhető felbontások letiltása.
function updateQualityLimits(maxHeight) {
  for (const radio of radios("quality")) {
    if (radio.value === "best") continue;
    radio.disabled = Boolean(maxHeight) && Number(radio.value) > maxHeight;
  }
  if (radios("quality").find((r) => r.checked)?.disabled) setRadio("quality", "best");
}

// --- Több link egyszerre -----------------------------------------------------

const BATCH_PREVIEW = 5;

function showBatch(urls) {
  clearPreview();
  el.url.value = "";
  state.batch = urls;
  el.batchCount.textContent = `${urls.length} link`;
  const rows = urls.slice(0, BATCH_PREVIEW).map((url) => {
    const li = document.createElement("li");
    li.textContent = url;
    li.title = url;
    return li;
  });
  if (urls.length > BATCH_PREVIEW) {
    const more = document.createElement("li");
    more.className = "more";
    more.textContent = `és még ${urls.length - BATCH_PREVIEW}…`;
    rows.push(more);
  }
  el.batchList.replaceChildren(...rows);
  el.batch.hidden = false;
  updateDownloadLabel();
}

function clearBatch() {
  if (!state.batch.length) return;
  state.batch = [];
  el.batch.hidden = true;
  updateDownloadLabel();
}

// Beillesztett szöveg: ha több link van benne, mindet sorba lehet állítani egyszerre.
async function handlePastedText(text) {
  const urls = await api().split_urls(text);
  showNotice("");
  if (urls.length > 1) { showBatch(urls); return; }
  clearBatch();
  el.url.value = urls[0] ?? text.trim();
  el.url.focus();
  runProbe();
}

let probeTimer;
el.url.addEventListener("input", () => {
  clearTimeout(probeTimer);
  clearBatch();
  showNotice("");
  if (!el.url.value.trim()) { clearPreview(); return; }
  probeTimer = setTimeout(runProbe, 600);
});
el.url.addEventListener("paste", (e) => {
  clearTimeout(probeTimer);
  const text = e.clipboardData?.getData("text") ?? "";
  // Az egysoros mező a sortöréseket eldobná, ezért a többsoros szöveget mi dolgozzuk fel.
  if (/\s/.test(text.trim())) {
    e.preventDefault();
    handlePastedText(text);
    return;
  }
  setTimeout(runProbe, 0);
});

el.paste.addEventListener("click", async () => {
  const text = await api().paste();
  if (text) handlePastedText(text);
});
el.batchClear.addEventListener("click", () => { clearBatch(); el.url.focus(); });

// --- Beállítások -------------------------------------------------------------

const CONTAINERS = {
  mp4: { label: "MP4", hint: "Mindenhol lejátszható: telefonon, tévén, szerkesztőprogramokban is." },
  mkv: { label: "MKV", hint: "Bármilyen kodek belefér, így a legjobb hangsávot kapod; VLC-vel és a legtöbb lejátszóval megy." },
  webm: { label: "WebM", hint: "Nyílt formátum (VP9/AV1 + Opus), böngészőkhöz ideális. Borítókép nélkül." },
};

const AUDIO_FORMATS = {
  mp3: { label: "MP3", hint: "Mindenhol lejátszható: autóban, régi lejátszón is. 320 kbps, borítóképpel, címmel és előadóval." },
  m4a: { label: "M4A", hint: "Az eredeti AAC hangsáv átalakítás nélkül, borítóképpel. Apple-eszközökön és telefonon ideális." },
  opus: { label: "Opus", hint: "A legjobb elérhető minőség átalakítás nélkül, kis fájlban. Régebbi lejátszók nem mindig kezelik." },
  wav: { label: "WAV", hint: "Tömörítetlen, vágó- és DJ-programokhoz. Nem szól jobban, csak sokkal nagyobb; borítókép nélkül." },
};

function currentFormat() {
  return radioValue("mode") === "audio"
    ? AUDIO_FORMATS[radioValue("audio_format")] ?? AUDIO_FORMATS.mp3
    : CONTAINERS[radioValue("container")] ?? CONTAINERS.mp4;
}

function updateDownloadLabel() {
  const { label } = currentFormat();
  const busy = [...state.items.values()].some((i) => i.state === "queued" || i.state === "running");
  if (state.batch.length) el.downloadLabel.textContent = `${state.batch.length} link letöltése · ${label}`;
  else if (busy) el.downloadLabel.textContent = `${label} hozzáadása a sorhoz`;
  else el.downloadLabel.textContent = `${label} letöltése`;
}

function applyMode() {
  const audio = radioValue("mode") === "audio";
  el.videoOptions.hidden = audio;
  el.audioOptions.hidden = !audio;
  el.containerHint.textContent = (CONTAINERS[radioValue("container")] ?? CONTAINERS.mp4).hint;
  el.audioFormatHint.textContent = (AUDIO_FORMATS[radioValue("audio_format")] ?? AUDIO_FORMATS.mp3).hint;
  el.compatibleRow.hidden = radioValue("container") === "webm"; // H.264 nem fér WebM-be
  updateDownloadLabel();
}

radios("mode").forEach((r) => r.addEventListener("change", () => {
  applyMode();
  saveSettings({ mode: radioValue("mode") });
}));
radios("container").forEach((r) => r.addEventListener("change", () => {
  applyMode();
  saveSettings({ container: radioValue("container") });
}));
radios("audio_format").forEach((r) => r.addEventListener("change", () => {
  applyMode();
  saveSettings({ audio_format: radioValue("audio_format") });
}));
radios("quality").forEach((r) => r.addEventListener("change", () => saveSettings({ quality: radioValue("quality") })));
el.compatible.addEventListener("change", () => saveSettings({ compatible: el.compatible.checked }));

function showFolder(path) {
  // A mező jobbról balra vág (az útvonal vége a fontos); az LRM jelek tartják a helyén a perjeleket.
  el.folder.textContent = `\u200E${path}\u200E`;
  el.folder.title = path;
}

el.chooseFolder.addEventListener("click", async () => {
  const folder = await api().choose_folder();
  if (folder) showFolder(folder);
});
el.openFolder.addEventListener("click", () => api().open_folder());

// --- Sorba állítás -----------------------------------------------------------

// Dupla kattintásnál vagy Enter + kattintásnál ne próbálja kétszer sorba állítani.
let adding = false;

async function addToQueue() {
  if (adding) return;
  adding = true;
  try {
    await submitToQueue();
  } finally {
    adding = false;
  }
}

async function submitToQueue() {
  const url = el.url.value.trim();
  let items;
  if (state.batch.length) {
    items = state.batch.map((u) => ({ url: u, playlist: null })); // a lista-linkeket a Python ismeri fel
  } else if (url) {
    const info = url === state.probedUrl ? state.probeInfo : null;
    items = [{
      url,
      title: info?.title ?? "",
      thumbnail: info?.thumbnail ?? null,
      // Előnézet nélkül nem tudjuk, lista-e; ilyenkor a Python a link alakjából dönt.
      playlist: info ? state.isPlaylist || (!el.playlistRow.hidden && el.playlist.checked) : null,
    }];
  } else {
    el.url.focus();
    return;
  }

  const res = await api().enqueue({
    items,
    mode: radioValue("mode"),
    quality: radioValue("quality"),
    container: radioValue("container"),
    audio_format: radioValue("audio_format"),
    compatible: el.compatible.checked,
  });
  if (!res.ok) { showNotice(res.error, true); return; }

  el.url.value = "";
  clearPreview();
  clearBatch();
  if (!res.skipped) showNotice("");
  else if (res.added) showNotice(`${res.added} link a sorba került, ${res.skipped} már benne volt.`);
  else showNotice(res.skipped > 1 ? "Ezek a linkek már a sorban vannak." : "Ez a link már a sorban van.");
  el.url.focus();
}

el.form.addEventListener("submit", (e) => { e.preventDefault(); addToQueue(); });
el.download.addEventListener("click", addToQueue);

// --- Letöltési sor -----------------------------------------------------------

const ICONS = {
  video: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="2" y="5" width="15" height="14" rx="3"/><path d="m17 10 5-3v10l-5-3"/></svg>',
  audio: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>',
  remove: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12"/></svg>',
};

function formatLabel(item) {
  const parts = [];
  if (item.mode === "audio") {
    parts.push(AUDIO_FORMATS[item.audio_format]?.label ?? item.audio_format);
  } else {
    parts.push(CONTAINERS[item.container]?.label ?? item.container);
    if (item.max_height) parts.push(item.max_height >= 2160 ? "4K" : `${item.max_height}p`);
    if (item.compatible && item.container !== "webm") parts.push("kompatibilis");
  }
  if (item.playlist) parts.push("lista");
  return parts.join(" · ");
}

function stateText(item) {
  switch (item.state) {
    case "queued": return "Várakozik";
    case "running": return item.status || "Előkészítés…";
    case "done": return item.files.length > 1 ? `Kész · ${item.files.length} fájl` : "Kész";
    case "cancelled": return "Megszakítva";
    default: return item.message || "Hiba történt.";
  }
}

function button(label, onClick, className = "btn btn-ghost btn-sm") {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = className;
  btn.textContent = label;
  btn.addEventListener("click", onClick);
  return btn;
}

function removeButton(id) {
  const btn = button("", () => { btn.disabled = true; api().remove(id); }, "btn btn-ghost btn-sm btn-icon");
  btn.innerHTML = ICONS.remove;
  btn.title = "Eltávolítás a sorból";
  btn.setAttribute("aria-label", btn.title);
  return btn;
}

function actionsFor(item) {
  const { id } = item;
  switch (item.state) {
    case "queued":
      return [removeButton(id)];
    case "running": {
      const cancel = button("Mégse", () => {
        cancel.disabled = true;
        cancel.textContent = "Megszakítás…";
        api().cancel(id);
      });
      return [cancel];
    }
    case "done":
      // Lejátszási listánál az első fájlt jelöljük ki, így a mappája nyílik meg.
      return [...(item.files.length ? [button("Megmutatás", () => api().reveal(item.files[0]))] : []), removeButton(id)];
    default:
      return [button("Újra", () => api().retry(id)), removeButton(id)];
  }
}

function createRow(item) {
  const row = document.createElement("li");
  row.className = "q-item";
  row.dataset.id = item.id;
  row.innerHTML = `
    <div class="q-thumb">${item.mode === "audio" ? ICONS.audio : ICONS.video}</div>
    <div class="q-body">
      <div class="q-title"></div>
      <div class="q-meta"><span class="q-format"></span><span class="q-status"></span></div>
      <div class="bar" hidden><div class="bar-fill"></div></div>
    </div>
    <span class="q-pct"></span>
    <div class="q-actions"></div>`;
  return row;
}

function setBar(row, percent) {
  const bar = row.querySelector(".bar");
  bar.classList.toggle("indeterminate", percent == null);
  if (percent != null) bar.firstElementChild.style.width = `${percent}%`;
  row.querySelector(".q-pct").textContent = percent == null ? "" : `${Math.floor(percent)}%`;
}

function setRowStatus(row, text) {
  const status = row.querySelector(".q-status");
  status.textContent = text;
  status.title = text;
}

function logTransition(item) {
  const name = item.title || item.url;
  if (item.state === "running") log(`▶ ${name}`);
  else if (item.state === "done") item.files.forEach((f) => log(`✔ ${f}`));
  else if (item.state === "failed") log(`${name}: ${item.message}`, "error");
  else if (item.state === "cancelled") log(`${name}: megszakítva`, "warning");
}

function updateRow(row, item) {
  const title = row.querySelector(".q-title");
  title.textContent = item.title || item.url;
  title.title = item.url;
  row.querySelector(".q-format").textContent = formatLabel(item);
  const thumb = row.querySelector(".q-thumb");
  thumb.style.backgroundImage = cssUrl(item.thumbnail);
  thumb.classList.toggle("has-image", Boolean(item.thumbnail));

  // A futó elem szövegét és sávját a folyamatesemények frissítik, ezt csak állapotváltáskor írjuk felül.
  if (row.dataset.state === item.state) return;
  row.dataset.state = item.state;
  row.className = `q-item ${item.state}`;
  row.querySelector(".bar").hidden = item.state !== "running";
  setBar(row, null);
  setRowStatus(row, stateText(item));
  row.querySelector(".q-actions").replaceChildren(...actionsFor(item));
  logTransition(item);
}

function renderQueue(items) {
  state.items = new Map(items.map((i) => [i.id, i]));
  const rows = new Map([...el.queueList.children].map((row) => [Number(row.dataset.id), row]));
  // Helyben rendezzük a sorokat: az újra beszúrt elem újrajátszaná a megjelenési animációt.
  items.forEach((item, index) => {
    const row = rows.get(item.id) ?? createRow(item);
    rows.delete(item.id);
    updateRow(row, item);
    const current = el.queueList.children[index];
    if (current !== row) el.queueList.insertBefore(row, current ?? null);
  });
  rows.forEach((row) => row.remove());

  const count = (s) => items.filter((i) => i.state === s).length;
  const parts = [
    [count("queued"), "várakozik"], [count("done"), "kész"],
    [count("failed"), "sikertelen"], [count("cancelled"), "megszakítva"],
  ].filter(([n]) => n).map(([n, label]) => `${n} ${label}`);
  el.queueCount.textContent = parts.join(" · ");
  el.clearFinished.hidden = !items.some((i) => ["done", "failed", "cancelled"].includes(i.state));
  el.queue.hidden = items.length === 0;
  updateDownloadLabel();
}

el.clearFinished.addEventListener("click", () => api().clear_finished());

const rowFor = (id) => el.queueList.querySelector(`.q-item[data-id="${id}"]`);

// --- Események a Pythonból ---------------------------------------------------

const handlers = {
  queue(e) {
    if (e.version <= state.queueVersion) return; // egy későbbi állapot már megérkezett
    state.queueVersion = e.version;
    renderQueue(e.items);
  },
  progress(e) {
    const row = rowFor(e.id), item = state.items.get(e.id);
    if (!row || item?.state !== "running") return;
    const what = item.mode === "audio" ? "Hang letöltése" : e.kind === "audio" ? "Hangsáv letöltése" : "Videósáv letöltése";
    const parts = [
      e.item ? `${e.item} · ${what}` : what,
      formatSpeed(e.speed),
      e.eta != null ? `még ${formatDuration(e.eta) || "0:00"}` : "",
    ];
    setRowStatus(row, parts.filter(Boolean).join(" · "));
    setBar(row, e.percent);
  },
  status(e) {
    const row = rowFor(e.id);
    if (!row || state.items.get(e.id)?.state !== "running") return;
    setRowStatus(row, e.text);
    setBar(row, null);
  },
  log(e) { log(e.text, e.level); },
};

window.app = { onEvent: (e) => handlers[e.type]?.(e) };

// --- Indulás -----------------------------------------------------------------

window.addEventListener("pywebviewready", async () => {
  const { settings, ffmpeg, js_runtime, queue } = await api().init();
  setRadio("mode", settings.mode);
  setRadio("quality", settings.quality);
  setRadio("container", CONTAINERS[settings.container] ? settings.container : "mp4");
  setRadio("audio_format", AUDIO_FORMATS[settings.audio_format] ? settings.audio_format : "mp3");
  el.compatible.checked = settings.compatible;
  showFolder(settings.output_dir);
  applyMode();
  handlers.queue(queue);

  if (!ffmpeg) {
    el.toolsWarning.textContent = "Az ffmpeg nem található, a letöltés nem fog működni. Telepítsd, vagy használd a csomagolt programot.";
    el.toolsWarning.hidden = false;
  } else if (!js_runtime) {
    el.toolsWarning.textContent = "Nincs JavaScript futtatókörnyezet (Deno): a YouTube csak korlátozottan működhet.";
    el.toolsWarning.hidden = false;
  }
  el.url.focus();
});
