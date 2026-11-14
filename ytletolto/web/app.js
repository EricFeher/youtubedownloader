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
  compatible: $("compatible"), playlistRow: $("playlist-row"), playlist: $("playlist"),
  folder: $("folder"), chooseFolder: $("choose-folder"), openFolder: $("open-folder"),
  download: $("download-btn"), progress: $("progress"), progressLabel: $("progress-label"),
  progressPct: $("progress-pct"), progressMeta: $("progress-meta"), bar: $("bar-fill"),
  cancel: $("cancel-btn"), result: $("result"), resultIcon: $("result-icon"),
  resultTitle: $("result-title"), files: $("files"), resultClose: $("result-close"),
  log: $("log"), toolsWarning: $("tools-warning"),
};

const state = { probeToken: 0, probedUrl: "", downloading: false, maxHeight: null, isPlaylist: false };

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

function clearPreview() {
  state.probeToken++;
  state.probedUrl = "";
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
  el.thumb.style.backgroundImage = info.thumbnail ? `url("${info.thumbnail.replace(/"/g, "%22")}")` : "";
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

function applyMode() {
  const audio = radioValue("mode") === "audio";
  el.videoOptions.hidden = audio;
  el.audioOptions.hidden = !audio;
  el.download.querySelector("#download-label").textContent = audio ? "MP3 letöltése" : "MP4 letöltése";
}

radios("mode").forEach((r) => r.addEventListener("change", () => {
  applyMode();
  saveSettings({ mode: radioValue("mode") });
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

  el.result.hidden = true;
  const res = await api().start({
    url,
    mode: radioValue("mode"),
    quality: radioValue("quality"),
    compatible: el.compatible.checked,
    playlist: state.isPlaylist || (!el.playlistRow.hidden && el.playlist.checked),
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
    const audioMode = radioValue("mode") === "audio";
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
