"use strict";

import { TEXT, t, setText, setLanguage, detectLanguage } from "./i18n.js";
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
  videoOptions: $("video-options"), audioOptions: $("audio-options"), quality: $("quality"),
  containerHint: $("container-hint"), audioFormatHint: $("audio-format-hint"), compatibleRow: $("compatible-row"),
  compatible: $("compatible"), playlistRow: $("playlist-row"), playlist: $("playlist"),
  folder: $("folder"), chooseFolder: $("choose-folder"), openFolder: $("open-folder"),
  download: $("download-btn"), downloadLabel: $("download-label"),
  queue: $("queue"), queueList: $("queue-list"), queueCount: $("queue-count"), clearFinished: $("clear-finished"),
  log: $("log"), toolsWarning: $("tools-warning"),
  modeTitle: $("mode-title"), modeGrid: $("mode-grid"),
  videoFormatTitle: $("video-format-title"), audioFormatTitle: $("audio-format-title"),
  playlistCard: $("playlist-card"), playlistItems: $("playlist-items"), playlistSummary: $("playlist-summary"),
  playlistLoading: $("playlist-loading"), playlistError: $("playlist-error"),
  editorPreview: $("editor-preview"), editorThumb: $("editor-thumb"), editorTitle: $("editor-title"), editorMeta: $("editor-meta"),
  editorLoading: $("editor-loading"), editorError: $("editor-error"),
  rangeSection: $("range-section"), rangeSlider: $("range-slider"), rangeSelection: $("range-selection"),
  rangeStart: $("range-start"), rangeEnd: $("range-end"), rangeStartValue: $("range-start-value"), rangeEndValue: $("range-end-value"),
  rangeDuration: $("range-duration"), rangeSummary: $("range-summary"), rangeReset: $("range-reset"),
};

const state = {
  probeToken: 0, probedUrl: "", probeInfo: null, isPlaylist: false,
  quality: "best", // a felhasználó mentett választása; a kijelölt chip ehhez a legközelebbi elérhető
  batch: [], // több beillesztett link, amíg sorba nem kerülnek
  queueVersion: -1, items: new Map(),
  playlistToken: 0, playlistUrl: "", playlistTitle: "", entries: [], itemModes: new Map(), excludedItems: new Set(),
  activeIndex: null, entryOptions: new Map(), entryInfo: new Map(), entryPending: new Map(),
  singleOptions: null,
  defaults: { mode: "video", quality: "best", container: "mp4", audio_format: "mp3", compatible: false },
  lastEvents: new Map(),
};

const radios = (name) => [...document.querySelectorAll(`input[name="${name}"]`)];
const radioValue = (name) => radios(name).find((r) => r.checked)?.value;
const setRadio = (name, value) => radios(name).forEach((r) => { r.checked = r.value === value; });

// --- Formázás ----------------------------------------------------------------

function formatDuration(seconds) {
  if (seconds == null) return "";
  seconds = Math.floor(seconds);
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

function tierLabel(tier, fps) {
  const name = tier >= 4320 ? "8K" : tier >= 2160 ? "4K" : `${tier}p`;
  return fps > 30 ? `${name}${fps}` : name;
}

function formatSize(bytes) {
  if (!bytes) return "";
  const mb = bytes / 1024 ** 2;
  return mb >= 1024 ? `~${(mb / 1024).toFixed(1)} GB` : `~${Math.max(1, Math.round(mb))} MB`;
}

const cssUrl = (url) => (url ? `url("${url.replace(/"/g, "%22")}")` : "");

const looksLikeUrl = (text) => /^(https?:\/\/)?([\w-]+\.)*(youtube\.com|youtu\.be|youtube-nocookie\.com)\//i.test(text.trim())
  || /^https?:\/\/\S+\.\S+/i.test(text.trim());
const hasPlaylist = (text) => /[?&]list=/.test(text);

// --- Napló -------------------------------------------------------------------

function log(text, level = "info") {
  const line = document.createElement("div");
  if (level !== "info") line.className = level;
  setText(line, text);
  el.log.appendChild(line);
  el.log.scrollTop = el.log.scrollHeight;
}

function showNotice(text, error = false) {
  setText(el.notice, text);
  el.notice.classList.toggle("error", error);
  el.notice.hidden = !text;
}

// --- Előnézet ----------------------------------------------------------------

// Az előző linkhez tartozó állapot (lista, elemenkénti választás) eldobása, hogy ne keveredjen az újjal.
function resetLinkState() {
  el.playlistRow.hidden = true;
  el.playlist.checked = false;
  state.isPlaylist = false;
  clearPlaylist();
  state.singleOptions = null;
  restoreOptions(state.defaults);
}

function clearPreview() {
  state.probeToken++;
  state.probedUrl = "";
  state.probeInfo = null;
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
  state.probeInfo = null;
  el.preview.hidden = el.probeError.hidden = true;
  el.skeleton.hidden = false;
  resetLinkState();
  applyMode();

  const res = await api().probe(url);
  if (token !== state.probeToken) return; // közben új link érkezett
  el.skeleton.hidden = true;

  if (!res.ok) {
    setText(el.probeError, res.error);
    el.probeError.hidden = false;
    state.probedUrl = "";
    applyMode();
    return;
  }
  showPreview(res.info, url);
}

function showPreview(info, url) {
  state.probeInfo = info;
  state.isPlaylist = info.kind === "playlist";
  el.thumb.style.backgroundImage = cssUrl(info.thumbnail);
  el.title.textContent = info.title;
  el.uploader.textContent = info.uploader;

  if (info.kind === "playlist") {
    setText(el.kind, info.count ? TEXT.PLAYLIST_VIDEO_COUNT : TEXT.PLAYLIST, { count: info.count });
    el.badge.hidden = el.duration.hidden = true;
    el.playlistRow.hidden = true; // tiszta lista-link: a lista elemeiből választunk
    showPlaylist(info.entries, url, info.title);
  } else {
    state.singleOptions = { ...state.defaults, start_time: 0, end_time: null };
    restoreOptions(state.singleOptions);
    setText(el.kind, TEXT.VIDEO);
    el.badge.textContent = heightLabel(info.max_height);
    el.badge.hidden = !info.max_height;
    el.duration.textContent = formatDuration(info.duration);
    el.duration.hidden = !info.duration;
    el.playlistRow.hidden = !hasPlaylist(url);
  }
  state.probeInfo = info;
  state.isPlaylist = info.kind === "playlist";
  renderQualities();
  el.preview.hidden = false;
  applyMode();
}

// --- Lejátszási lista elemei ---------------------------------------------------

const playlistSelected = () => state.isPlaylist || (!el.playlistRow.hidden && el.playlist.checked);
// Elemenkénti választás csak akkor van, ha a lista elemeit sikerült lekérni; különben a teljes lista egy módban megy.
const perItemMode = () => playlistSelected() && state.entries.length > 0;
// Amíg a link vagy a lista adatai töltődnek, még nem tudjuk, mit és hogyan kell letölteni.
const loading = () => !el.skeleton.hidden || !el.playlistLoading.hidden;
const selectedEntries = () => state.entries.filter((e) => !state.excludedItems.has(e.index));
const itemMode = (index) => state.itemModes.get(index) ?? "video";

function modeCounts() {
  const selected = selectedEntries();
  const audio = selected.filter((e) => itemMode(e.index) === "audio").length;
  return { video: selected.length - audio, audio };
}

function clearPlaylist() {
  state.playlistToken++;
  state.playlistUrl = "";
  state.playlistTitle = "";
  state.entries = [];
  state.itemModes = new Map();
  state.excludedItems = new Set();
  state.activeIndex = null;
  state.entryOptions = new Map();
  state.entryInfo = new Map();
  state.entryPending = new Map();
  el.playlistItems.replaceChildren();
  el.playlistCard.hidden = el.playlistLoading.hidden = el.playlistError.hidden = true;
}

function showPlaylist(entries, url, title) {
  state.playlistToken++;
  state.playlistUrl = url;
  state.playlistTitle = title || "";
  state.entries = entries || [];
  state.itemModes = new Map();
  state.excludedItems = new Set();
  el.playlistLoading.hidden = el.playlistError.hidden = true;
  // Fragmenttel, mert a több tízezer elemes listák szétterítve túllépnék a függvényargumentumok korlátját.
  const rows = document.createDocumentFragment();
  for (const entry of state.entries) rows.append(playlistRow(entry));
  el.playlistItems.replaceChildren(rows);
  el.playlistCard.hidden = state.entries.length === 0;
  updatePlaylistSummary();
  if (state.entries.length) selectPlaylistEntry(state.entries[0].index);
}

function playlistRow(entry) {
  const li = document.createElement("li");
  li.className = "playlist-item";
  li.dataset.index = entry.index;

  const select = document.createElement("input");
  select.type = "checkbox";
  select.className = "playlist-select";
  select.checked = true;
  select.setAttribute("aria-label", t(TEXT.SELECT_VIDEO, { title: entry.title }));

  const number = document.createElement("span");
  number.className = "playlist-index";
  number.textContent = entry.index;

  const thumb = document.createElement("img");
  thumb.className = "playlist-thumb";
  thumb.alt = "";
  thumb.loading = "lazy";
  if (entry.thumbnail) thumb.src = entry.thumbnail;

  const text = document.createElement("button");
  text.type = "button";
  text.className = "playlist-text playlist-open";
  text.setAttribute("aria-label", t(TEXT.EDIT_VIDEO, { title: entry.title }));
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
  const range = document.createElement("small");
  range.className = "playlist-range";
  range.hidden = true;
  text.append(range);

  const toggle = document.createElement("span");
  toggle.className = "segmented";
  toggle.setAttribute("role", "group");
  toggle.setAttribute("aria-label", t(TEXT.FORMAT_FOR_ITEM_INDEX, { index: entry.index }));
  for (const [mode, label] of [["video", t(TEXT.VIDEO)], ["audio", t(TEXT.AUDIO)]]) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.dataset.mode = mode;
    btn.textContent = label;
    btn.setAttribute("aria-pressed", String(mode === "video"));
    toggle.append(btn);
  }

  li.append(select, number, thumb, text, toggle);
  return li;
}

function setItemMode(li, mode) {
  const index = Number(li.dataset.index);
  state.itemModes.set(index, mode);
  optionsForEntry(index).mode = mode;
  li.querySelectorAll("button[data-mode]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.mode === mode)));
  if (state.activeIndex === index) restoreOptions(optionsForEntry(index));
}

function updatePlaylistSummary() {
  const { video, audio } = modeCounts();
  setText(el.playlistSummary, TEXT.PLAYLIST_SELECTION_SUMMARY, { selected: video + audio, total: state.entries.length, video, audio });
  applyMode();
}

el.playlistItems.addEventListener("change", (e) => {
  if (!e.target.matches(".playlist-select")) return;
  const li = e.target.closest(".playlist-item");
  const index = Number(li.dataset.index);
  if (e.target.checked) state.excludedItems.delete(index);
  else state.excludedItems.add(index);
  li.classList.toggle("unselected", !e.target.checked);
  updatePlaylistSummary();
});

el.playlistCard.querySelectorAll("button[data-select]").forEach((btn) => btn.addEventListener("click", () => {

  const checked = btn.dataset.select === "all";
  state.excludedItems = new Set(checked ? [] : state.entries.map((e) => e.index));
  el.playlistItems.querySelectorAll(".playlist-item").forEach((li) => {
    li.querySelector(".playlist-select").checked = checked;
    li.classList.toggle("unselected", !checked);
  });
  updatePlaylistSummary();
}));

el.playlistItems.addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-mode]");
  const li = e.target.closest(".playlist-item");
  if (!li || e.target.closest(".playlist-select")) return;
  if (btn) setItemMode(li, btn.dataset.mode);
  selectPlaylistEntry(Number(li.dataset.index));
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
  setText(el.playlistSummary, TEXT.LOADING_PLAYLIST);
  applyMode();

  const res = await api().probe(url, true);
  if (token !== state.playlistToken) return; // közben új link érkezett, vagy kikapcsolták
  el.playlistLoading.hidden = true;
  if (res.ok && res.info.kind === "playlist") state.playlistTitle = res.info.title || "";
  if (!res.ok || res.info.kind !== "playlist" || !res.info.entries.length) {
    // Az elemek nélkül is letölthető a lista, csak egységesen a felül választott módban.
    setText(el.playlistSummary, "");
    const reason = res.ok ? TEXT.INDIVIDUAL_SELECTION_UNAVAILABLE : res.error;
    setText(el.playlistError, TEXT.PLAYLIST_SELECTION_UNAVAILABLE, { reason: { message: reason } });
    el.playlistError.hidden = false;
    applyMode();
    return;
  }
  showPlaylist(res.info.entries, url, res.info.title);
}

el.playlist.addEventListener("change", () => {
  if (el.playlist.checked) {
    loadPlaylist();
  } else {
    state.playlistToken++; // a folyamatban lévő lekérés eredményét eldobjuk
    el.playlistLoading.hidden = true;
    if (!state.entries.length) state.playlistUrl = "";
    el.playlistCard.hidden = true;
    restoreOptions(state.singleOptions ?? state.defaults);
    applyMode();
  }
});

// --- Közös videószerkesztő ----------------------------------------------------

function optionsForEntry(index) {
  if (!state.entryOptions.has(index)) {
    state.entryOptions.set(index, { ...state.defaults, mode: itemMode(index), start_time: 0, end_time: null });
  }
  return state.entryOptions.get(index);
}

function editorOptions() {
  return perItemMode() && state.activeIndex !== null
    ? optionsForEntry(state.activeIndex) : playlistSelected() ? null : state.singleOptions;
}

function editorInfo() {
  if (perItemMode()) {
    const entry = state.entries.find((e) => e.index === state.activeIndex);
    return entry ? state.entryInfo.get(entry.id) ?? { ...entry, kind: "video" } : null;
  }
  return playlistSelected() ? null : state.probeInfo;
}

function restoreOptions(options) {
  for (const key of ["mode", "container", "audio_format"]) setRadio(key, options[key]);
  state.quality = options.quality ?? "best";
  el.compatible.checked = Boolean(options.compatible);
}

function readOptions() {
  return {
    mode: radioValue("mode"), quality: state.quality,
    container: radioValue("container"), audio_format: radioValue("audio_format"), compatible: el.compatible.checked,
  };
}

function rememberOptions() {
  const options = readOptions();
  const current = editorOptions();
  if (current) Object.assign(current, options);
  if (perItemMode()) {
    state.itemModes.set(state.activeIndex, options.mode);
    const row = playlistItemRow(state.activeIndex);
    row?.querySelectorAll("button[data-mode]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.mode === options.mode)));
  } else {
    Object.assign(state.defaults, options);
    saveSettings(options);
  }
}

const playlistItemRow = (index) => el.playlistItems.querySelector(`.playlist-item[data-index="${index}"]`);

async function selectPlaylistEntry(index) {
  const entry = state.entries.find((e) => e.index === index);
  if (!entry) return;
  const previous = playlistItemRow(state.activeIndex);
  previous?.classList.remove("active");
  previous?.querySelector(".playlist-open").removeAttribute("aria-current");
  state.activeIndex = index;
  const row = playlistItemRow(index);
  row?.classList.add("active");
  row?.querySelector(".playlist-open").setAttribute("aria-current", "true");
  restoreOptions(optionsForEntry(index));
  applyMode();
  if ((state.entryInfo.has(entry.id) && !state.entryInfo.get(entry.id).error) || state.entryPending.has(entry.id)) return;
  const token = state.playlistToken;
  const request = api().probe(`https://www.youtube.com/watch?v=${encodeURIComponent(entry.id)}`);
  state.entryPending.set(entry.id, request);
  renderEditor();
  try {
    const res = await request;
    if (token !== state.playlistToken) return;
    state.entryInfo.set(entry.id, res.ok && res.info.kind === "video"
      ? res.info : { ...entry, kind: "video", error: res.error || TEXT.VIDEO_DETAILS_ARE_UNAVAILABLE });
  } catch {
    if (token !== state.playlistToken) return;
    state.entryInfo.set(entry.id, { ...entry, kind: "video", error: TEXT.COULD_NOT_LOAD_VIDEO_DETAILS });
  } finally {
    if (token === state.playlistToken) {
      state.entryPending.delete(entry.id);
      if (perItemMode() && state.entries.find((e) => e.index === state.activeIndex)?.id === entry.id) applyMode();
    }
  }
}

function hasSection() {
  const options = editorOptions();
  return Boolean(options && (options.start_time > 0 || options.end_time != null));
}

function renderEditor() {
  const info = editorInfo();
  const perItem = perItemMode();
  el.editorPreview.hidden = !perItem || !info;
  const entry = state.entries.find((e) => e.index === state.activeIndex);
  el.editorLoading.hidden = !perItem || !state.entryPending.has(entry?.id);
  el.editorError.hidden = !perItem || !info?.error;
  setText(el.editorError, perItem ? info?.error ?? "" : "");
  if (perItem && info) {
    el.editorThumb.style.backgroundImage = cssUrl(info.thumbnail);
    el.editorTitle.textContent = info.title;
    el.editorMeta.textContent = [info.uploader, formatDuration(info.duration), info.max_height ? tierLabel(info.max_height) : null].filter(Boolean).join(" · ");
  }
  renderRange();
}

function renderRange() {
  const info = editorInfo(), options = editorOptions();
  const duration = Math.floor(info?.duration ?? 0);
  if (options && info?.is_live) {
    options.start_time = 0;
    options.end_time = null;
    const label = playlistItemRow(state.activeIndex)?.querySelector(".playlist-range");
    if (label) label.hidden = true;
  }
  el.rangeSection.hidden = !options || duration < 1 || Boolean(info?.is_live);
  if (el.rangeSection.hidden) {
    el.quality.classList.remove("has-section");
    return;
  }
  const start = Math.min(options.start_time ?? 0, duration - 1);
  const end = Math.max(start + 1, Math.min(options.end_time ?? duration, duration));
  options.start_time = start;
  options.end_time = end === duration ? null : end;
  el.quality.classList.toggle("has-section", hasSection());
  el.rangeStart.max = el.rangeEnd.max = duration;
  el.rangeStart.value = start;
  el.rangeEnd.value = end;
  el.rangeStartValue.textContent = formatDuration(start);
  el.rangeEndValue.textContent = formatDuration(end);
  el.rangeDuration.textContent = formatDuration(duration);
  el.rangeStart.setAttribute("aria-valuetext", formatDuration(start));
  el.rangeEnd.setAttribute("aria-valuetext", formatDuration(end));
  el.rangeStart.setAttribute("aria-valuemax", end - 1);
  el.rangeEnd.setAttribute("aria-valuemin", start + 1);
  el.rangeSelection.style.left = `calc(12px + (100% - 24px) * ${start / duration})`;
  el.rangeSelection.style.right = `calc(12px + (100% - 24px) * ${1 - end / duration})`;
  el.rangeSummary.textContent = `${hasSection() ? t(TEXT.SELECTED_DURATION) : t(TEXT.FULL_VIDEO)}: ${formatDuration(end - start)}`;
  el.rangeReset.disabled = !hasSection();
  if (perItemMode()) {
    const label = playlistItemRow(state.activeIndex)?.querySelector(".playlist-range");
    if (label) {
      label.hidden = !hasSection();
      label.textContent = `${formatDuration(start)} – ${formatDuration(end)}`;
    }
  }
}

function changeRange(side, value) {
  const options = editorOptions();
  if (!options || el.rangeSection.hidden) return;
  const duration = Number(el.rangeEnd.max);
  if (side === "start") options.start_time = Math.max(0, Math.min(value, Number(el.rangeEnd.value) - 1));
  else options.end_time = Math.min(duration, Math.max(value, Number(el.rangeStart.value) + 1));
  renderRange();
}

for (const [side, input] of [["start", el.rangeStart], ["end", el.rangeEnd]]) {
  input.addEventListener("input", () => changeRange(side, Number(input.value)));
  input.addEventListener("keydown", (event) => {
    if (event.shiftKey && ["ArrowLeft", "ArrowDown", "ArrowRight", "ArrowUp"].includes(event.key)) {
      event.preventDefault();
      changeRange(side, Number(input.value) + (["ArrowLeft", "ArrowDown"].includes(event.key) ? -10 : 10));
    }
  });
}

let draggedRangeSide = null;
el.rangeSlider.addEventListener("pointerdown", (event) => {
  if (event.button !== 0 || el.rangeSection.hidden) return;
  const bounds = el.rangeSlider.getBoundingClientRect();
  const duration = Number(el.rangeEnd.max), width = Math.max(1, bounds.width - 24);
  const startX = Number(el.rangeStart.value) / duration * width;
  const endX = Number(el.rangeEnd.value) / duration * width;
  const overlapping = endX - startX < 24;
  const nativeThumb = event.target === el.rangeStart || event.target === el.rangeEnd;
  if (nativeThumb && !overlapping) return;
  if (nativeThumb) event.preventDefault();
  const x = event.clientX - bounds.left - 12;
  const value = Math.round(Math.max(0, Math.min(1, x / width)) * duration);
  draggedRangeSide = overlapping
    ? (x <= (startX + endX) / 2 ? "start" : "end")
    : (Math.abs(x - startX) <= Math.abs(x - endX) ? "start" : "end");
  el.rangeSlider.setPointerCapture(event.pointerId);
  (draggedRangeSide === "start" ? el.rangeStart : el.rangeEnd).focus();
  changeRange(draggedRangeSide, value);
});
el.rangeSlider.addEventListener("pointermove", (event) => {
  if (!draggedRangeSide) return;
  const bounds = el.rangeSlider.getBoundingClientRect();
  const value = Math.round(Math.max(0, Math.min(1, (event.clientX - bounds.left - 12) / Math.max(1, bounds.width - 24))) * Number(el.rangeEnd.max));
  changeRange(draggedRangeSide, value);
});
for (const event of ["pointerup", "pointercancel", "lostpointercapture"]) el.rangeSlider.addEventListener(event, () => { draggedRangeSide = null; });
el.rangeReset.addEventListener("click", () => {
  const options = editorOptions();
  if (!options) return;
  options.start_time = 0;
  options.end_time = null;
  renderRange();
});

// --- Minőség -----------------------------------------------------------------

// Előnézet nélkül, lejátszási listánál és több linknél nincs videónkénti lista, ott ezek közül lehet választani.
const FALLBACK_TIERS = [2160, 1440, 1080, 720, 480, 360];
const MIN_TIER = 360; // ennél kisebbet csak akkor kínálunk, ha a videó eleve ilyen kicsi

// A Python quality_key() párja.
function qualityKey() {
  const container = radioValue("container");
  return el.compatible.checked && container !== "webm" ? `${container}-compatible` : container;
}

// A videónál a választott formátumban ténylegesen letölthető fokozatok, csökkenő sorrendben; null, ha nem ismertek.
function availableQualities() {
  const info = editorInfo();
  if (info?.kind !== "video") return null;
  const list = info.qualities?.[qualityKey()];
  return list?.length ? list : null;
}

function qualityChips() {
  const available = availableQualities();
  if (!available) {
    return [{ value: "best", label: t(TEXT.BEST), tier: Infinity }, ...FALLBACK_TIERS.map((tier) => ({ value: String(tier), label: tierLabel(tier), tier }))];
  }
  // A legfelső fokozat maga a TEXT.BEST: külön chipként ugyanazt jelentené.
  const [top, ...rest] = available;
  const shown = top.tier > MIN_TIER ? rest.filter((q) => q.tier >= MIN_TIER) : rest;
  return [
    { value: "best", label: t(TEXT.BEST_QUALITY, { quality: tierLabel(top.tier, top.fps) }), size: top.size, tier: top.tier },
    ...shown.map((q) => ({ value: String(q.tier), label: tierLabel(q.tier, q.fps), size: q.size, tier: q.tier })),
  ];
}

function qualityChip({ value, label, size }) {
  const input = Object.assign(document.createElement("input"), { type: "radio", name: "quality", value });
  const text = document.createElement("span");
  text.textContent = label;
  if (size) {
    const small = document.createElement("small");
    small.textContent = formatSize(size);
    small.title = t(TEXT.ESTIMATED_FILE_SIZE);
    text.append(small);
  }
  const chip = document.createElement("label");
  chip.append(input, text);
  return chip;
}

function renderQualities() {
  const chips = qualityChips();
  const wanted = state.quality === "best" ? Infinity : Number(state.quality) || Infinity;
  // A mentett választáshoz legközelebbi: a legnagyobb, ami nem több nála; ha mind több, a legkisebb.
  const selected = chips.find((c) => c.tier <= wanted) ?? chips.at(-1);
  el.quality.replaceChildren(...chips.map(qualityChip));
  setRadio("quality", selected.value);
}

// --- Több link egyszerre -----------------------------------------------------

const BATCH_PREVIEW = 5;

function showBatch(urls) {
  clearPreview();
  el.url.value = "";
  state.batch = urls;
  setText(el.batchCount, TEXT.LINK_COUNT, { count: urls.length });
  const rows = urls.slice(0, BATCH_PREVIEW).map((url) => {
    const li = document.createElement("li");
    li.textContent = url;
    li.title = url;
    return li;
  });
  if (urls.length > BATCH_PREVIEW) {
    const more = document.createElement("li");
    more.className = "more";
    setText(more, TEXT.AND_COUNT_MORE, { count: urls.length - BATCH_PREVIEW });
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
  mp4: { label: "MP4", hint: TEXT.MP4_HINT },
  mkv: { label: "MKV", hint: TEXT.MKV_HINT },
  webm: { label: "WebM", hint: TEXT.WEBM_HINT },
};

const AUDIO_FORMATS = {
  mp3: { label: "MP3", hint: TEXT.MP3_HINT },
  m4a: { label: "M4A", hint: TEXT.M4A_HINT },
  opus: { label: "Opus", hint: TEXT.OPUS_HINT },
  wav: { label: "WAV", hint: TEXT.WAV_HINT },
};

function currentFormat() {
  return radioValue("mode") === "audio"
    ? AUDIO_FORMATS[radioValue("audio_format")] ?? AUDIO_FORMATS.mp3
    : CONTAINERS[radioValue("container")] ?? CONTAINERS.mp4;
}

function updateDownloadLabel() {
  if (perItemMode()) {
    el.downloadLabel.textContent = t(TEXT.ADD_ITEMS_TO_QUEUE, { count: selectedEntries().length });
    return;
  }
  const { label } = currentFormat();
  const busy = [...state.items.values()].some((i) => i.state === "queued" || i.state === "running");
  if (state.batch.length) el.downloadLabel.textContent = t(TEXT.DOWNLOAD_LINKS, { count: state.batch.length, format: label });
  else if (busy) el.downloadLabel.textContent = t(TEXT.ADD_FORMAT_TO_QUEUE, { format: label });
  else el.downloadLabel.textContent = t(TEXT.DOWNLOAD_FORMAT, { format: label });
}

function applyMode() {
  const audio = radioValue("mode") === "audio";
  const container = CONTAINERS[radioValue("container")] ?? CONTAINERS.mp4;
  const audioFormat = AUDIO_FORMATS[radioValue("audio_format")] ?? AUDIO_FORMATS.mp3;
  const perItem = perItemMode();
  const counts = perItem ? modeCounts() : null;
  el.modeTitle.hidden = el.modeGrid.hidden = false;
  el.videoOptions.hidden = audio;
  el.audioOptions.hidden = !audio;
  el.videoFormatTitle.textContent = el.audioFormatTitle.textContent = t(TEXT.FILE_FORMAT);
  el.containerHint.textContent = t(container.hint);
  el.audioFormatHint.textContent = t(audioFormat.hint);
  el.compatibleRow.hidden = radioValue("container") === "webm"; // H.264 nem fér WebM-be
  renderQualities(); // a fokozatok formátumonként mások (pl. kompatibilis módban legfeljebb 1080p)
  el.download.disabled = loading() || (perItem && counts.video + counts.audio === 0);
  el.download.querySelector("#download-label").textContent = perItem
    ? t(TEXT.DOWNLOAD_ITEMS, { count: counts.video + counts.audio })
    : t(TEXT.DOWNLOAD_FORMAT, { format: (audio ? audioFormat : container).label });
  if (!perItem) updateDownloadLabel();
  renderEditor();
}

radios("mode").forEach((r) => r.addEventListener("change", () => {
  rememberOptions();
  applyMode();
}));
radios("container").forEach((r) => r.addEventListener("change", () => {
  rememberOptions();
  applyMode();
}));
radios("audio_format").forEach((r) => r.addEventListener("change", () => {
  rememberOptions();
  applyMode();
}));
// A chipek újrarajzolódnak, ezért a konténeren figyeljük; csak a felhasználó kattintása módosítja a választást.
el.quality.addEventListener("change", () => {
  state.quality = radioValue("quality");
  rememberOptions();
});
el.compatible.addEventListener("change", () => {
  rememberOptions();
  renderQualities();
});
el.playlist.addEventListener("change", renderQualities); // a teljes listánál nincs videónkénti lista

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
    if (looksLikeUrl(url) && url !== state.probedUrl) {
      clearTimeout(probeTimer);
      await runProbe();
      if (el.url.value.trim() !== url) return;
    }
    if (loading() || (perItemMode() && selectedEntries().length === 0)) return;
    const info = url === state.probedUrl ? state.probeInfo : null;
    items = [{
      url,
      selection: perItemMode() && state.playlistUrl === url
        ? selectedEntries().map((e) => ({
          id: e.id,
          title: state.entryInfo.get(e.id)?.title ?? e.title,
          thumbnail: state.entryInfo.get(e.id)?.thumbnail ?? e.thumbnail ?? null,
          options: { ...optionsForEntry(e.index) },
        }))
        : null,
      title: info?.title ?? "",
      playlist_title: playlistSelected() ? state.playlistTitle || (info?.kind === "playlist" ? info.title : "") : "",
      thumbnail: info?.thumbnail ?? null,
      // Előnézet nélkül nem tudjuk, lista-e; ilyenkor a Python a link alakjából dönt.
      playlist: info ? state.isPlaylist || (!el.playlistRow.hidden && el.playlist.checked) : null,
    }];
  } else {
    el.url.focus();
    return;
  }

  const res = await api().enqueue({
    ...(perItemMode() ? state.defaults : { ...readOptions(), ...(!playlistSelected() ? state.singleOptions : {}), quality: radioValue("quality") }),
    items,
  });
  if (!res.ok) { showNotice(res.error, true); return; }

  el.url.value = "";
  clearPreview();
  clearBatch();
  if (!res.skipped) showNotice("");
  else if (res.added) showNotice({ message: TEXT.QUEUE_ADDED_SUMMARY, params: { added: res.added, skipped: res.skipped } });
  else showNotice(res.skipped > 1 ? TEXT.LINKS_ALREADY_QUEUED : TEXT.LINK_ALREADY_QUEUED);
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
    if (item.max_height) parts.push(tierLabel(item.max_height));
    if (item.compatible && item.container !== "webm") parts.push(t(TEXT.COMPATIBLE));
  }
  if (item.start_time > 0 || item.end_time != null) parts.push(`${formatDuration(item.start_time ?? 0)} – ${item.end_time == null ? t(TEXT.TO_END) : formatDuration(item.end_time)}`);
  return parts.join(" · ");
}

function stateText(item) {
  switch (item.state) {
    case "queued": return t(TEXT.QUEUED);
    case "running": return t(item.status || TEXT.PREPARING);
    case "done": return item.files.length > 1 ? t(TEXT.DONE_COUNT_FILES, { count: item.files.length }) : t(TEXT.DONE);
    case "cancelled": return t(TEXT.CANCELLED);
    default: return t(item.message || TEXT.AN_ERROR_OCCURRED);
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
  btn.title = t(TEXT.REMOVE_FROM_QUEUE);
  btn.setAttribute("aria-label", btn.title);
  return btn;
}

function actionsFor(item) {
  const { id } = item;
  switch (item.state) {
    case "queued":
      return [removeButton(id)];
    case "running": {
      const cancel = button(t(TEXT.CANCEL), () => {
        cancel.disabled = true;
        cancel.textContent = t(TEXT.CANCELLING);
        api().cancel(id);
      });
      return [cancel];
    }
    case "done":
      // Lejátszási listánál az első fájlt jelöljük ki, így a mappája nyílik meg.
      return [...(item.files.length ? [button(t(TEXT.SHOW_IN_FOLDER), () => api().reveal(item.files[0]))] : []), removeButton(id)];
    default:
      return [button(t(TEXT.RETRY), () => api().retry(id)), removeButton(id)];
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
      <div class="q-playlist" hidden></div>
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
  else if (item.state === "failed") log({ message: TEXT.NAMED_MESSAGE, params: { name, error: { message: item.message } } }, "error");
  else if (item.state === "cancelled") log({ message: TEXT.NAME_CANCELLED, params: { name } }, "warning");
}

function updateRow(row, item, refresh = false) {
  const title = row.querySelector(".q-title");
  title.textContent = item.title || (item.playlist ? t(TEXT.FETCHING_VIDEO_DETAILS) : item.url);
  title.title = item.url;
  const playlist = row.querySelector(".q-playlist");
  playlist.hidden = !item.playlist;
  playlist.textContent = item.playlist_title ? t(TEXT.PLAYLIST_TITLE, { title: item.playlist_title }) : t(TEXT.FROM_PLAYLIST);
  playlist.title = playlist.textContent;
  row.querySelector(".q-format").textContent = formatLabel(item);
  const thumb = row.querySelector(".q-thumb");
  thumb.style.backgroundImage = cssUrl(item.thumbnail);
  thumb.classList.toggle("has-image", Boolean(item.thumbnail));

  // A futó elem szövegét és sávját a folyamatesemények frissítik, ezt csak állapotváltáskor írjuk felül.
  if (row.dataset.state === item.state) {
    if (refresh) {
      setRowStatus(row, stateText(item));
      const actions = row.querySelector(".q-actions");
      const buttons = actionsFor(item);
      buttons.forEach((button, index) => {
        if (!actions.children[index]?.disabled) return;
        button.disabled = true;
        if (item.state === "running") button.textContent = t(TEXT.CANCELLING);
      });
      actions.replaceChildren(...buttons);
    }
    return;
  }
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
  for (const id of state.lastEvents.keys()) if (state.items.get(id)?.state !== "running") state.lastEvents.delete(id);
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
    [count("queued"), t(TEXT.QUEUED_SUMMARY)], [count("done"), t(TEXT.DONE_SUMMARY)],
    [count("failed"), t(TEXT.FAILED)], [count("cancelled"), t(TEXT.CANCELLED_SUMMARY)],
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
    state.lastEvents.set(e.id, e);
    const what = (e.mode ?? item.mode) === "audio" ? t(TEXT.DOWNLOADING_AUDIO) : e.kind === "audio" ? t(TEXT.DOWNLOADING_AUDIO_TRACK) : t(TEXT.DOWNLOADING_VIDEO_TRACK);
    const parts = [
      e.item ? `${e.item} · ${what}` : what,
      formatSpeed(e.speed),
      e.eta != null ? t(TEXT.TIME_REMAINING, { time: formatDuration(e.eta) || "0:00" }) : "",
    ];
    setRowStatus(row, parts.filter(Boolean).join(" · "));
    setBar(row, e.percent);
  },
  status(e) {
    const row = rowFor(e.id);
    if (!row || state.items.get(e.id)?.state !== "running") return;
    state.lastEvents.set(e.id, e);
    setRowStatus(row, t(e.text));
    setBar(row, null);
  },
  log(e) { log(e.text, e.level); },
};

// --- Alkalmazásfrissítés ------------------------------------------------------

let updateState = null;
let updateRequest = false;
const updateDialog = $("updates-dialog");

function renderUpdate(update, refresh = false) {
  updateState = update;
  const busy = ["checking", "downloading", "installing"].includes(update.status);
  const pending = [...state.items.values()].some((item) => ["queued", "running"].includes(item.state));
  $("app-version").textContent = `v${update.current_version}`;
  $("update-current").textContent = t(TEXT.INSTALLED_V_VERSION, { version: update.current_version });
  $("update-latest").textContent = `${update.available ? t(TEXT.AVAILABLE) : t(TEXT.LATEST_RELEASE)}: v${update.version}`;
  $("update-latest").hidden = !update.version;
  $("update-banner").hidden = !update.available;
  $("update-banner-title").textContent = `Media Minds Downloader · v${update.version}`;
  $("update-check").disabled = busy || update.status === "ready";
  $("update-download").hidden = !update.available || !update.supported || ["ready", "installing"].includes(update.status);
  $("update-download").disabled = busy;
  $("update-install").hidden = !["ready", "installing"].includes(update.status);
  $("update-install").disabled = pending || update.status === "installing";
  $("update-progress").hidden = update.status !== "downloading";
  $("update-progress").value = update.progress ?? 0;
  if (!refresh) {
    $("update-error").hidden = !update.error;
    setText($("update-error"), update.error || "");
  }
  const messages = {
    idle: t(TEXT.UPDATE_AUTO_CHECK_HINT),
    checking: t(TEXT.CHECKING_FOR_UPDATES),
    current: t(TEXT.UPDATE_CURRENT),
    available: t(TEXT.UPDATE_AVAILABLE_HINT),
    downloading: t(TEXT.UPDATE_DOWNLOAD_PROGRESS, { percent: update.progress ?? 0 }),
    ready: pending ? t(TEXT.UPDATE_WAIT_FOR_QUEUE) : t(TEXT.UPDATE_READY),
    installing: t(TEXT.INSTALLING_UPDATE_AND_RESTARTING),
    error: t(TEXT.UPDATE_RETRY_HINT),
  };
  $("update-status").textContent = messages[update.status] || "";
  if (!update.supported) $("update-status").textContent += " " + t(TEXT.UPDATE_PACKAGED_ONLY);
  // Release text is untrusted; render as text, never HTML.
  $("release-notes").textContent = update.notes || t(update.version
    ? TEXT.RELEASE_NOTES_UNAVAILABLE
    : TEXT.RELEASE_NOTES_PLACEHOLDER);
  const date = new Date(update.published_at);
  $("release-date").textContent = Number.isNaN(date.getTime()) ? "" : date.toLocaleDateString(window.i18n.locale, {year: "numeric", month: "long", day: "numeric"});
}

async function requestUpdate(method) {
  if (updateRequest) return;
  updateRequest = true;
  try { renderUpdate(await api()[method]()); }
  catch { setText($("update-error"), TEXT.UPDATE_OPERATION_FAILED); $("update-error").hidden = false; }
  finally { updateRequest = false; }
}

function openUpdates() {
  if (!updateDialog.open) updateDialog.showModal();
  if (updateState?.status === "idle") requestUpdate("check_update");
}
$("updates-open").addEventListener("click", openUpdates);
$("update-banner-open").addEventListener("click", openUpdates);
$("updates-close").addEventListener("click", () => updateDialog.close());
$("update-check").addEventListener("click", () => requestUpdate("check_update"));
$("update-download").addEventListener("click", () => requestUpdate("download_update"));
$("update-install").addEventListener("click", async () => {
  $("update-install").disabled = true;
  try {
    const result = await api().install_update();
    if (!result.ok) { setText($("update-error"), result.error); $("update-error").hidden = false; }
  } catch { setText($("update-error"), TEXT.RESTART_FAILED); $("update-error").hidden = false; }
  finally { if (updateState) $("update-install").disabled = updateState.status === "installing" || [...state.items.values()].some((item) => ["queued", "running"].includes(item.state)); }
});

window.app = {
  onEvent: (e) => { handlers[e.type]?.(e); if (e.type === "queue" && updateState) renderUpdate(updateState); },
  onUpdate: renderUpdate,
};

// --- Indulás -----------------------------------------------------------------

function changeLanguage(value) {
  $("language").value = window.i18n.setLanguage(value);
  $("language-flag").src = `flags/${window.i18n.language}.svg`;
  $("language-code").textContent = window.i18n.language.toUpperCase();
  document.querySelectorAll("[data-language]").forEach((option) => {
    option.setAttribute("aria-checked", String(option.dataset.language === window.i18n.language));
  });
  applyMode();
  for (const entry of state.entries) {
    const row = playlistItemRow(entry.index);
    if (!row) continue;
    row.querySelector(".playlist-select").setAttribute("aria-label", t(TEXT.SELECT_VIDEO, { title: entry.title }));
    row.querySelector(".playlist-open").setAttribute("aria-label", t(TEXT.EDIT_VIDEO, { title: entry.title }));
    row.querySelector(".segmented").setAttribute("aria-label", t(TEXT.FORMAT_FOR_ITEM_INDEX, { index: entry.index }));
    row.querySelectorAll("button[data-mode]").forEach((button) => { button.textContent = t(button.dataset.mode === "video" ? TEXT.VIDEO : TEXT.AUDIO); });
  }
  if (state.entries.length) updatePlaylistSummary();
  for (const item of state.items.values()) updateRow(rowFor(item.id), item, true);
  for (const event of state.lastEvents.values()) handlers[event.type](event);
  renderQueue([...state.items.values()]);
  if (updateState) renderUpdate(updateState, true);
}

const languagePicker = $("language-picker");
const languageOptions = [...$("language-menu").querySelectorAll("[data-language]")];
function closeLanguageMenu(restoreFocus = false) {
  $("language-menu").hidden = true;
  $("language").setAttribute("aria-expanded", "false");
  if (restoreFocus) $("language").focus();
}
function openLanguageMenu() {
  $("language-menu").hidden = false;
  $("language").setAttribute("aria-expanded", "true");
  languageOptions.find((option) => option.dataset.language === window.i18n.language).focus();
}
$("language").addEventListener("click", () => {
  if ($("language-menu").hidden) openLanguageMenu();
  else closeLanguageMenu();
});
languageOptions.forEach((option) => option.addEventListener("click", () => {
  changeLanguage(option.dataset.language);
  closeLanguageMenu(true);
  saveSettings({ language: window.i18n.language });
}));
languagePicker.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    closeLanguageMenu(true);
    event.preventDefault();
  } else if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
    event.preventDefault();
    if ($("language-menu").hidden) {
      openLanguageMenu();
      if (event.key === "End") languageOptions.at(-1).focus();
      else if (event.key === "Home") languageOptions[0].focus();
      return;
    }
    const current = languageOptions.indexOf(document.activeElement);
    const next = event.key === "Home" ? 0 : event.key === "End" ? languageOptions.length - 1
      : (current + (event.key === "ArrowDown" ? 1 : -1) + languageOptions.length) % languageOptions.length;
    languageOptions[next].focus();
  }
});
document.addEventListener("click", (event) => {
  if (!languagePicker.contains(event.target)) closeLanguageMenu();
});
languagePicker.addEventListener("focusout", (event) => {
  if (!languagePicker.contains(event.relatedTarget)) closeLanguageMenu();
});

setLanguage(detectLanguage(navigator.language));
renderQualities(); // amíg a mentett beállítások meg nem érkeznek

let initialized = false;
async function initialize() {
  if (initialized || typeof window.pywebview?.api?.init !== "function") return;
  initialized = true;
  try {
    const { settings, ffmpeg, js_runtime, queue, update } = await api().init();
    changeLanguage(settings.language);
    $("language").disabled = false;
    for (const key of Object.keys(state.defaults)) state.defaults[key] = settings[key] ?? state.defaults[key];
    setRadio("mode", settings.mode);
    state.quality = settings.quality;
    setRadio("container", CONTAINERS[settings.container] ? settings.container : "mp4");
    setRadio("audio_format", AUDIO_FORMATS[settings.audio_format] ? settings.audio_format : "mp3");
    el.compatible.checked = settings.compatible;
    showFolder(settings.output_dir);
    applyMode();
    handlers.queue(queue);

    if (!ffmpeg) {
      setText(el.toolsWarning, TEXT.FFMPEG_WARNING);
      el.toolsWarning.hidden = false;
    } else if (!js_runtime) {
      setText(el.toolsWarning, TEXT.JS_RUNTIME_WARNING);
      el.toolsWarning.hidden = false;
    }
    el.url.focus();
    if (update) {
      renderUpdate(update);
      $("updates-open").disabled = false;
      requestUpdate("check_update");
      setInterval(() => {
        if (!["ready", "installing", "downloading"].includes(updateState?.status)) requestUpdate("check_update");
      }, 60 * 60 * 1000);
    }
  } catch (error) {
    initialized = false;
    console.error("Failed to initialize the application:", error);
  }
}
window.addEventListener("pywebviewready", initialize);
// The native bridge may become ready while the text catalogs are loading.
if (typeof window.pywebview?.api?.init === "function") initialize();
