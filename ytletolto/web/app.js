"use strict";

const $ = (id) => document.getElementById(id);
const api = () => window.pywebview.api;
// Beállítás mentése; a pywebview API még nem biztos, hogy kész (pl. visszaállított űrlapállapotnál).
const saveSettings = (changes) => window.pywebview?.api?.save_settings(changes);

const el = {
  form: $("url-form"), url: $("url"), paste: $("paste-btn"),
  preview: $("preview"), skeleton: $("skeleton"), probeError: $("probe-error"),
  thumb: $("thumb"), badge: $("badge"), duration: $("duration"),
  kind: $("preview-kind"), title: $("title"), uploader: $("uploader"),
  videoOptions: $("video-options"), audioOptions: $("audio-options"),
  containerHint: $("container-hint"), audioFormatHint: $("audio-format-hint"), compatibleRow: $("compatible-row"),
  compatible: $("compatible"), playlistRow: $("playlist-row"), playlist: $("playlist"),
  folder: $("folder"), chooseFolder: $("choose-folder"), openFolder: $("open-folder"),
  download: $("download-btn"), progress: $("progress"), progressLabel: $("progress-label"),
  progressPct: $("progress-pct"), progressMeta: $("progress-meta"), bar: $("bar-fill"),
  cancel: $("cancel-btn"), result: $("result"), resultIcon: $("result-icon"),
  resultTitle: $("result-title"), files: $("files"), resultClose: $("result-close"),
  log: $("log"), toolsWarning: $("tools-warning"),
  modeTitle: $("mode-title"), modeGrid: $("mode-grid"),
  videoFormatTitle: $("video-format-title"), audioFormatTitle: $("audio-format-title"),
  playlistCard: $("playlist-card"), playlistItems: $("playlist-items"), playlistSummary: $("playlist-summary"),
  playlistLoading: $("playlist-loading"), playlistError: $("playlist-error"),
};

const state = {
  probeToken: 0, probedUrl: "", downloading: false, maxHeight: null, isPlaylist: false,
  // A lista elemei és elemenként a választott mód ("video" | "audio"); alapból minden videó.
  playlistToken: 0, playlistUrl: "", entries: [], itemModes: new Map(),
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

// --- Előnézet ----------------------------------------------------------------

// Az előző linkhez tartozó állapot (lista, elemenkénti választás) eldobása, hogy ne keveredjen az újjal.
function resetLinkState() {
  el.playlistRow.hidden = true;
  el.playlist.checked = false;
  state.isPlaylist = false;
  state.maxHeight = null;
  updateQualityLimits(null);
  clearPlaylist();
}

function clearPreview() {
  state.probeToken++;
  state.probedUrl = "";
  el.preview.hidden = el.skeleton.hidden = el.probeError.hidden = true;
  resetLinkState();
  applyMode();
}

async function runProbe() {
  const url = el.url.value.trim();
  if (!url || !looksLikeUrl(url)) { clearPreview(); return; }
  if (url === state.probedUrl) return;

  const token = ++state.probeToken;
  state.probedUrl = url;
  el.preview.hidden = el.probeError.hidden = true;
  el.skeleton.hidden = false;
  resetLinkState();
  applyMode();

  const res = await api().probe(url);
  if (token !== state.probeToken) return; // közben új link érkezett
  el.skeleton.hidden = true;

  if (!res.ok) {
    el.probeError.textContent = res.error;
    el.probeError.hidden = false;
    state.probedUrl = "";
    applyMode();
    return;
  }
  showPreview(res.info, url);
}

function showPreview(info, url) {
  el.thumb.style.backgroundImage = info.thumbnail ? `url("${info.thumbnail.replace(/"/g, "%22")}")` : "";
  el.title.textContent = info.title;
  el.uploader.textContent = info.uploader;

  if (info.kind === "playlist") {
    el.kind.textContent = info.count ? `Lejátszási lista · ${info.count} videó` : "Lejátszási lista";
    el.badge.hidden = el.duration.hidden = true;
    el.playlistRow.hidden = true; // tiszta lista-link: mindenképp a teljes listát töltjük le
    showPlaylist(info.entries, url);
  } else {
    el.kind.textContent = "Videó";
    el.badge.textContent = heightLabel(info.max_height);
    el.badge.hidden = !info.max_height;
    el.duration.textContent = formatDuration(info.duration);
    el.duration.hidden = !info.duration;
    el.playlistRow.hidden = !hasPlaylist(url);
  }
  state.isPlaylist = info.kind === "playlist";
  state.maxHeight = info.kind === "video" ? info.max_height : null;
  updateQualityLimits(state.maxHeight);
  el.preview.hidden = false;
  applyMode();
}

// --- Lejátszási lista elemei ---------------------------------------------------

const playlistSelected = () => state.isPlaylist || (!el.playlistRow.hidden && el.playlist.checked);
// Elemenkénti választás csak akkor van, ha a lista elemeit sikerült lekérni; különben a teljes lista egy módban megy.
const perItemMode = () => playlistSelected() && state.entries.length > 0;
// Amíg a link vagy a lista adatai töltődnek, még nem tudjuk, mit és hogyan kell letölteni.
const loading = () => !el.skeleton.hidden || !el.playlistLoading.hidden;
const itemMode = (index) => state.itemModes.get(index) ?? "video";

function modeCounts() {
  const audio = state.entries.filter((e) => itemMode(e.index) === "audio").length;
  return { video: state.entries.length - audio, audio };
}

function clearPlaylist() {
  state.playlistToken++;
  state.playlistUrl = "";
  state.entries = [];
  state.itemModes = new Map();
  el.playlistItems.replaceChildren();
  el.playlistCard.hidden = el.playlistLoading.hidden = el.playlistError.hidden = true;
}

function showPlaylist(entries, url) {
  state.playlistToken++;
  state.playlistUrl = url;
  state.entries = entries || [];
  state.itemModes = new Map();
  el.playlistLoading.hidden = el.playlistError.hidden = true;
  el.playlistItems.replaceChildren(...state.entries.map(playlistRow));
  el.playlistCard.hidden = state.entries.length === 0;
  updatePlaylistSummary();
}

function playlistRow(entry) {
  const li = document.createElement("li");
  li.className = "playlist-item";
  li.dataset.index = entry.index;

  const number = document.createElement("span");
  number.className = "playlist-index";
  number.textContent = entry.index;

  const thumb = document.createElement("img");
  thumb.className = "playlist-thumb";
  thumb.alt = "";
  thumb.loading = "lazy";
  if (entry.thumbnail) thumb.src = entry.thumbnail;

  const text = document.createElement("span");
  text.className = "playlist-text";
  const title = document.createElement("span");
  title.className = "playlist-title";
  title.textContent = entry.title;
  title.title = entry.title;
  text.append(title);
  if (entry.duration) {
    const duration = document.createElement("small");
    duration.textContent = formatDuration(entry.duration);
    text.append(duration);
  }

  const toggle = document.createElement("span");
  toggle.className = "segmented";
  toggle.setAttribute("role", "group");
  toggle.setAttribute("aria-label", `${entry.index}. elem formátuma`);
  for (const [mode, label] of [["video", "Videó"], ["audio", "Hang"]]) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.dataset.mode = mode;
    btn.textContent = label;
    btn.setAttribute("aria-pressed", String(mode === "video"));
    toggle.append(btn);
  }

  li.append(number, thumb, text, toggle);
  return li;
}

function setItemMode(li, mode) {
  state.itemModes.set(Number(li.dataset.index), mode);
  li.querySelectorAll("button[data-mode]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.mode === mode)));
}

function updatePlaylistSummary() {
  const { video, audio } = modeCounts();
  el.playlistSummary.textContent = `${state.entries.length} elem · ${video} videó, ${audio} hang`;
  applyMode();
}

el.playlistItems.addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-mode]");
  if (!btn || state.downloading) return;
  setItemMode(btn.closest(".playlist-item"), btn.dataset.mode);
  updatePlaylistSummary();
});

el.playlistCard.querySelectorAll("button[data-all]").forEach((btn) => btn.addEventListener("click", () => {
  el.playlistItems.querySelectorAll(".playlist-item").forEach((li) => setItemMode(li, btn.dataset.all));
  updatePlaylistSummary();
}));

// Listához tartozó videó linkjénél a lista elemeit csak a kapcsoló bekapcsolásakor kérjük le.
async function loadPlaylist() {
  const url = el.url.value.trim();
  if (state.playlistUrl === url && state.entries.length) {
    el.playlistCard.hidden = false;
    applyMode();
    return;
  }
  clearPlaylist();
  const token = state.playlistToken;
  el.playlistCard.hidden = el.playlistLoading.hidden = false;
  el.playlistSummary.textContent = "Lista betöltése…";
  applyMode();

  const res = await api().probe(url, true);
  if (token !== state.playlistToken) return; // közben új link érkezett, vagy kikapcsolták
  el.playlistLoading.hidden = true;
  if (!res.ok || res.info.kind !== "playlist" || !res.info.entries.length) {
    // Az elemek nélkül is letölthető a lista, csak egységesen a felül választott módban.
    el.playlistSummary.textContent = "";
    const reason = res.ok ? "A lista elemei nem érhetők el" : res.error.replace(/\.+$/, "");
    el.playlistError.textContent = `${reason}. A teljes lista a választott formátumban töltődik le.`;
    el.playlistError.hidden = false;
    applyMode();
    return;
  }
  showPlaylist(res.info.entries, url);
}

el.playlist.addEventListener("change", () => {
  if (el.playlist.checked) {
    loadPlaylist();
  } else {
    state.playlistToken++; // a folyamatban lévő lekérés eredményét eldobjuk
    el.playlistLoading.hidden = true;
    if (!state.entries.length) state.playlistUrl = "";
    el.playlistCard.hidden = true;
    applyMode();
  }
});

// A videónál nem elérhető felbontások letiltása.
function updateQualityLimits(maxHeight) {
  for (const radio of radios("quality")) {
    if (radio.value === "best") continue;
    radio.disabled = Boolean(maxHeight) && Number(radio.value) > maxHeight;
  }
  if (radios("quality").find((r) => r.checked)?.disabled) setRadio("quality", "best");
}

let probeTimer;
el.url.addEventListener("input", () => {
  clearTimeout(probeTimer);
  if (!el.url.value.trim()) { clearPreview(); return; }
  probeTimer = setTimeout(runProbe, 600);
});
el.url.addEventListener("paste", () => { clearTimeout(probeTimer); setTimeout(runProbe, 0); });

el.paste.addEventListener("click", async () => {
  const text = await api().paste();
  if (!text) return;
  el.url.value = text;
  el.url.focus();
  runProbe();
});

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

function applyMode() {
  const audio = radioValue("mode") === "audio";
  const container = CONTAINERS[radioValue("container")] ?? CONTAINERS.mp4;
  const audioFormat = AUDIO_FORMATS[radioValue("audio_format")] ?? AUDIO_FORMATS.mp3;
  // Elemenkénti választásnál nincs közös mód: azokat a beállításokat mutatjuk, amelyik módot valamelyik elem használja.
  const perItem = perItemMode();
  const counts = perItem ? modeCounts() : null;
  el.modeTitle.hidden = el.modeGrid.hidden = perItem;
  el.videoOptions.hidden = perItem ? counts.video === 0 : audio;
  el.audioOptions.hidden = perItem ? counts.audio === 0 : !audio;
  el.videoFormatTitle.textContent = perItem ? "Videók fájlformátuma" : "Fájlformátum";
  el.audioFormatTitle.textContent = perItem ? "Hangok fájlformátuma" : "Fájlformátum";
  el.containerHint.textContent = container.hint;
  el.audioFormatHint.textContent = audioFormat.hint;
  el.compatibleRow.hidden = radioValue("container") === "webm"; // H.264 nem fér WebM-be
  el.download.disabled = loading();
  el.download.querySelector("#download-label").textContent = perItem
    ? `${state.entries.length} elem letöltése`
    : `${(audio ? audioFormat : container).label} letöltése`;
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

// --- Letöltés ----------------------------------------------------------------

function setDownloading(on) {
  state.downloading = on;
  el.download.hidden = on;
  el.progress.hidden = !on;
  el.cancel.disabled = false;
  el.url.disabled = el.paste.disabled = on;
  document.querySelectorAll(".card input, .card button").forEach((c) => { c.disabled = on; });
  if (!on) updateQualityLimits(state.maxHeight);
}

function setIndeterminate(on) {
  el.bar.parentElement.classList.toggle("indeterminate", on);
  if (on) el.progressPct.textContent = "";
}

async function startDownload() {
  if (state.downloading) return;
  const url = el.url.value.trim();
  if (!url) { el.url.focus(); return; }
  // Enterrel a késleltetett előnézet előtt is indulhat: előbb az új linket kérjük le, nehogy a régi lista menjen.
  if (looksLikeUrl(url) && url !== state.probedUrl) {
    clearTimeout(probeTimer);
    await runProbe();
    if (el.url.value.trim() !== url) return;
  }
  if (loading()) return;

  el.result.hidden = true;
  const res = await api().start({
    url,
    mode: radioValue("mode"),
    quality: radioValue("quality"),
    container: radioValue("container"),
    audio_format: radioValue("audio_format"),
    compatible: el.compatible.checked,
    playlist: playlistSelected(),
    items: perItemMode() && state.playlistUrl === url
      ? state.entries.map((e) => ({ id: e.id, mode: itemMode(e.index) }))
      : null,
  });
  if (!res.ok) { showResult(false, res.error, []); return; }

  log(`▶ ${url}`);
  setDownloading(true);
  el.progressLabel.textContent = "Előkészítés…";
  el.progressMeta.textContent = "";
  el.bar.style.width = "0%";
  setIndeterminate(true);
}

el.form.addEventListener("submit", (e) => { e.preventDefault(); startDownload(); });
el.download.addEventListener("click", startDownload);
el.cancel.addEventListener("click", () => {
  el.cancel.disabled = true;
  el.progressLabel.textContent = "Megszakítás…";
  api().cancel();
});

function showResult(ok, message, files) {
  el.result.classList.toggle("ok", ok);
  el.result.classList.toggle("fail", !ok);
  el.resultIcon.textContent = ok ? "✓" : "!";
  el.resultTitle.textContent = message;
  el.files.replaceChildren(...files.map((path) => {
    const li = document.createElement("li");
    const name = document.createElement("span");
    name.textContent = path.split(/[\\/]/).pop();
    name.title = path;
    const btn = document.createElement("button");
    btn.className = "btn btn-ghost btn-sm";
    btn.textContent = "Megmutatás";
    btn.addEventListener("click", () => api().reveal(path));
    li.append(name, btn);
    return li;
  }));
  el.result.hidden = false;
}
el.resultClose.addEventListener("click", () => { el.result.hidden = true; });

// --- Események a Pythonból ---------------------------------------------------

const handlers = {
  progress(e) {
    const audioMode = e.mode === "audio";
    const what = audioMode ? "Hang letöltése" : e.kind === "audio" ? "Hangsáv letöltése" : "Videósáv letöltése";
    el.progressLabel.textContent = e.item ? `${e.item} · ${what}` : what;
    if (e.percent == null) {
      setIndeterminate(true);
    } else {
      setIndeterminate(false);
      el.bar.style.width = `${e.percent}%`;
      el.progressPct.textContent = `${Math.floor(e.percent)}%`;
    }
    const meta = [formatSpeed(e.speed), e.eta != null ? `még ${formatDuration(e.eta) || "0:00"}` : ""].filter(Boolean);
    el.progressMeta.textContent = meta.join(" · ");
  },
  status(e) {
    el.progressLabel.textContent = e.text;
    el.progressMeta.textContent = "";
    setIndeterminate(true);
  },
  log(e) { log(e.text, e.level); },
  finished(e) {
    setDownloading(false);
    showResult(e.ok, e.ok ? (e.files.length > 1 ? `Kész! ${e.files.length} fájl letöltve.` : "Kész!") : e.message, e.files);
    for (const f of e.files) log(`✔ ${f}`);
    if (!e.ok) log(e.message, "error");
  },
};

window.app = { onEvent: (e) => handlers[e.type]?.(e) };

// --- Indulás -----------------------------------------------------------------

window.addEventListener("pywebviewready", async () => {
  const { settings, ffmpeg, js_runtime } = await api().init();
  setRadio("mode", settings.mode);
  setRadio("quality", settings.quality);
  setRadio("container", CONTAINERS[settings.container] ? settings.container : "mp4");
  setRadio("audio_format", AUDIO_FORMATS[settings.audio_format] ? settings.audio_format : "mp3");
  el.compatible.checked = settings.compatible;
  showFolder(settings.output_dir);
  applyMode();

  if (!ffmpeg) {
    el.toolsWarning.textContent = "Az ffmpeg nem található, a letöltés nem fog működni. Telepítsd, vagy használd a csomagolt programot.";
    el.toolsWarning.hidden = false;
  } else if (!js_runtime) {
    el.toolsWarning.textContent = "Nincs JavaScript futtatókörnyezet (Deno): a YouTube csak korlátozottan működhet.";
    el.toolsWarning.hidden = false;
  }
  el.url.focus();
});
