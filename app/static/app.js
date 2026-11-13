"use strict";

/* ------------------------------------------------------------------ helpers */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const esc = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function api(path, { method = "GET", body } = {}) {
  const res = await fetch(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  let data = null;
  try { data = await res.json(); } catch { /* empty body */ }
  if (!res.ok) {
    const detail = data && data.detail;
    throw new Error(typeof detail === "string" ? detail : `Request failed (${res.status})`);
  }
  return data;
}

function fmtDuration(seconds) {
  if (seconds == null || isNaN(seconds)) return "";
  const s = Math.round(seconds);
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  const pad = (n) => String(n).padStart(2, "0");
  return h ? `${h}:${pad(m)}:${pad(sec)}` : `${m}:${pad(sec)}`;
}

function fmtBytes(bytes) {
  if (!bytes) return "0 MB";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0, n = bytes;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return `${n >= 100 || i === 0 ? Math.round(n) : n.toFixed(1)} ${units[i]}`;
}

function fmtCount(n) {
  if (n == null) return "";
  if (n >= 1e9) return (n / 1e9).toFixed(1) + "B";
  if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
  if (n >= 1e3) return (n / 1e3).toFixed(1) + "K";
  return String(n);
}

function fmtDate(epochSeconds) {
  return new Date(epochSeconds * 1000).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

function toast(message, kind = "") {
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.textContent = message;
  $("#toasts").append(el);
  setTimeout(() => { el.classList.add("out"); setTimeout(() => el.remove(), 260); }, 3800);
}

const store = {
  get(key, fallback) { try { return localStorage.getItem(key) ?? fallback; } catch { return fallback; } },
  set(key, value) { try { localStorage.setItem(key, value); } catch { /* private mode */ } },
};

const ICON = {
  music: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18V5l11-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="17" cy="16" r="3"/></svg>',
  video: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="5" width="14" height="14" rx="3"/><path d="M17 10l4-2.5v9L17 14"/></svg>',
  play: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5.5v13a1 1 0 001.5.86l10.5-6.5a1 1 0 000-1.72L9.5 4.64A1 1 0 008 5.5z"/></svg>',
  folder: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2V7z"/></svg>',
  close: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>',
  retry: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 0115.5-6.2L21 8M21 3v5h-5M21 12a9 9 0 01-15.5 6.2L3 16m0 5v-5h5"/></svg>',
  trash: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 002 2h6a2 2 0 002-2l1-12M9 7V4h6v3"/></svg>',
  download: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12m0 0l-4-4m4 4l4-4M4 17v2a2 2 0 002 2h12a2 2 0 002-2v-2"/></svg>',
};

const AUDIO_OPTIONS = [
  { value: "320", label: "320 kbps", note: "Best" },
  { value: "256", label: "256 kbps" },
  { value: "192", label: "192 kbps" },
  { value: "128", label: "128 kbps", note: "Small" },
];
const VIDEO_OPTIONS = [
  { value: "best", label: "Best", note: "Highest available" },
  { value: "2160", label: "4K", note: "2160p" },
  { value: "1440", label: "2K", note: "1440p" },
  { value: "1080", label: "1080p", note: "Full HD" },
  { value: "720", label: "720p", note: "HD" },
  { value: "480", label: "480p" },
  { value: "360", label: "360p" },
];

const ACTIVE = new Set(["fetching", "downloading", "processing"]);
const FINISHED = new Set(["done", "error", "cancelled"]);

const state = {
  analysis: null,
  analyzedUrl: "",
  mode: store.get("td.mode", "audio"),
  audioQ: store.get("td.audioQ", "320"),
  videoQ: store.get("td.videoQ", "best"),
  numberFiles: store.get("td.number", "1") === "1",
  selected: new Set(),
  jobs: [],
  jobEls: new Map(),
  queueFilter: "all",
  baseline: null,        // ids that were already finished when the current batch began
  library: [],
  libKind: "all",
  libSearch: "",
  settings: {},
  connected: true,
};

/* ------------------------------------------------------------------ navigation + theme */

function showView(name) {
  $$(".nav-item").forEach((b) => b.classList.toggle("active", b.dataset.view === name));
  $$(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${name}`));
  $(".main").scrollTop = 0;
  if (name === "library") loadLibrary();
  if (name === "settings") loadSettings();
}
$("#nav").addEventListener("click", (e) => {
  const btn = e.target.closest(".nav-item");
  if (btn) showView(btn.dataset.view);
});

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  $("#themeLabel").textContent = theme === "dark" ? "Light mode" : "Dark mode";
  store.set("td.theme", theme);
}
applyTheme(store.get("td.theme", "dark"));
$("#themeToggle").addEventListener("click", () =>
  applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark"));

/* ------------------------------------------------------------------ analyze */

const urlInput = $("#urlInput");
const urlHint = $("#urlHint");
const DEFAULT_HINT = urlHint.textContent;

function setHint(text, isError = false) {
  urlHint.textContent = text || DEFAULT_HINT;
  urlHint.classList.toggle("error", isError);
}

function setFetching(on) {
  const btn = $("#fetchBtn");
  btn.disabled = on;
  $(".btn-label", btn).textContent = on ? "Fetching" : "Fetch";
  $(".spinner", btn).hidden = !on;
}

async function analyze(noplaylist = false) {
  const url = urlInput.value.trim();
  if (!url) { setHint("Paste a link first.", true); urlInput.focus(); return; }
  if (!/^https?:\/\//i.test(url)) { setHint("That does not look like a link. It should start with https://", true); return; }
  setHint("Looking up the link…");
  setFetching(true);
  try {
    const data = await api("/api/analyze", { method: "POST", body: { url, noplaylist } });
    state.analysis = data;
    state.analyzedUrl = url;
    state.selected = new Set(
      data.type === "playlist" ? data.entries.filter((e) => !e.unavailable).map((e) => e.index) : []);
    setHint("");
    renderPreview();
  } catch (err) {
    setHint(err.message, true);
  } finally {
    setFetching(false);
  }
}

$("#urlForm").addEventListener("submit", (e) => { e.preventDefault(); analyze(); });
urlInput.addEventListener("paste", () => setTimeout(() => analyze(), 0));
$("#pasteBtn").addEventListener("click", async () => {
  try {
    const text = (await navigator.clipboard.readText()).trim();
    if (!text) return toast("Clipboard is empty.");
    urlInput.value = text;
    analyze();
  } catch {
    toast("Clipboard access was blocked. Press Ctrl+V in the box instead.", "bad");
    urlInput.focus();
  }
});

/* ------------------------------------------------------------------ preview */

const preview = $("#preview");

function videoOptionsFor(analysis) {
  if (analysis.type !== "video" || !analysis.heights || !analysis.heights.length) return VIDEO_OPTIONS;
  const max = analysis.heights[0];
  // A 1080p video can be 1080 tall or (ultrawide / vertical) a bit less, so allow some slack.
  const options = VIDEO_OPTIONS.filter((o) => o.value === "best" || Number(o.value) <= max * 1.12);
  options[0] = { ...options[0], note: `up to ${max}p` };
  return options;
}

function currentQuality() {
  if (state.mode === "audio") return state.audioQ;
  const options = videoOptionsFor(state.analysis);
  return options.some((o) => o.value === state.videoQ) ? state.videoQ : "best";
}

function downloadLabel() {
  const a = state.analysis;
  const what = state.mode === "audio" ? "MP3" : "MP4";
  if (a.type === "playlist") {
    const n = state.selected.size;
    return n ? `Download ${n} ${n === 1 ? "item" : "items"} as ${what}` : "Select at least one";
  }
  return `Download ${what}`;
}

function formatControls() {
  const options = state.mode === "audio" ? AUDIO_OPTIONS : videoOptionsFor(state.analysis);
  const active = currentQuality();
  return `
    <div class="seg" role="tablist">
      <button data-mode="audio" class="${state.mode === "audio" ? "active" : ""}">${ICON.music}MP3 audio</button>
      <button data-mode="video" class="${state.mode === "video" ? "active" : ""}">${ICON.video}MP4 video</button>
    </div>
    <div class="quality">
      ${options.map((o) => `<button class="q-chip ${o.value === active ? "active" : ""}" data-quality="${o.value}">${o.label}${o.note ? `<small>${esc(o.note)}</small>` : ""}</button>`).join("")}
    </div>`;
}

function hasVideoAndList(url) {
  return /[?&]v=/.test(url) && /[?&]list=/.test(url);
}

function renderPreview() {
  const a = state.analysis;
  if (!a) { preview.hidden = true; preview.innerHTML = ""; return; }
  const isList = a.type === "playlist";
  const first = isList ? a.entries[0] : a;
  const thumb = first && first.thumbnail;
  const both = hasVideoAndList(state.analyzedUrl);

  let meta = "";
  if (isList) {
    const total = a.entries.reduce((sum, e) => sum + (e.duration || 0), 0);
    meta = [a.uploader, `${a.count} videos`, total ? `${fmtDuration(total)} total` : ""].filter(Boolean)
      .map((m) => `<span>${esc(m)}</span>`).join("");
  } else {
    meta = [a.uploader, a.view_count != null ? `${fmtCount(a.view_count)} views` : "",
      a.heights && a.heights.length ? `Up to ${a.heights[0]}p` : ""].filter(Boolean)
      .map((m) => `<span>${esc(m)}</span>`).join("");
  }

  const switchLink = both
    ? `<button class="ghost-btn" data-act="${isList ? "single" : "whole"}">${isList ? "Only the one video" : "Load the whole playlist"}</button>`
    : "";

  preview.innerHTML = `
    <div class="pv-top">
      <div class="pv-thumb">
        ${thumb ? `<img src="${esc(thumb)}" alt="" referrerpolicy="no-referrer">` : ""}
        ${!isList && a.duration ? `<span class="dur">${fmtDuration(a.duration)}</span>` : ""}
      </div>
      <div class="pv-body">
        <div class="job-line">
          <span class="pv-kind">${isList ? "Playlist" : "Video"}</span>
          <button class="icon-btn pv-close" data-act="close" aria-label="Dismiss">${ICON.close}</button>
        </div>
        <h3 class="pv-title">${esc(a.title)}</h3>
        <div class="pv-meta">${meta}</div>
        <div class="format-row" id="formatRow">${formatControls()}</div>
        <div class="pv-actions">
          <button class="primary-btn" id="dlBtn">${ICON.download}<span>${esc(downloadLabel())}</span></button>
          ${isList ? `<label class="check"><input type="checkbox" id="numberFiles" ${state.numberFiles ? "checked" : ""}>Number files in playlist order</label>` : ""}
          ${switchLink}
        </div>
      </div>
    </div>
    ${isList ? `
      <div class="pl-tools">
        <div class="search">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg>
          <input type="search" id="plSearch" placeholder="Filter this playlist…">
        </div>
        <button class="ghost-btn" data-act="all">Select all</button>
        <button class="ghost-btn" data-act="none">Select none</button>
        <span class="pl-count" id="plCount"></span>
      </div>
      <div class="pl-list" id="plList">
        ${a.entries.map((e) => `
          <label class="pl-row ${state.selected.has(e.index) ? "" : "off"}" data-index="${e.index}" data-title="${esc((e.title || "").toLowerCase())}">
            <input type="checkbox" ${state.selected.has(e.index) ? "checked" : ""}>
            <span class="pl-num">${e.index}</span>
            ${e.thumbnail ? `<img src="${esc(e.thumbnail)}" alt="" loading="lazy" referrerpolicy="no-referrer">` : "<span></span>"}
            <span class="pl-title"><strong>${esc(e.title)}</strong><span>${esc(e.uploader || "")}</span></span>
            <span class="pl-dur">${fmtDuration(e.duration)}</span>
          </label>`).join("")}
      </div>` : ""}`;
  preview.hidden = false;
  refreshSelection();
}

function refreshSelection() {
  const a = state.analysis;
  if (!a) return;
  const btn = $("#dlBtn");
  if (btn) {
    $("span", btn).textContent = downloadLabel();
    btn.disabled = a.type === "playlist" && state.selected.size === 0;
  }
  const count = $("#plCount");
  if (count) count.textContent = `${state.selected.size} of ${a.count} selected`;
}

function refreshFormat() {
  $("#formatRow").innerHTML = formatControls();
  refreshSelection();
}

function setRow(row, on) {
  const index = Number(row.dataset.index);
  on ? state.selected.add(index) : state.selected.delete(index);
  row.classList.toggle("off", !on);
  $("input", row).checked = on;
}

preview.addEventListener("click", (e) => {
  const modeBtn = e.target.closest("[data-mode]");
  if (modeBtn) {
    state.mode = modeBtn.dataset.mode;
    store.set("td.mode", state.mode);
    return refreshFormat();
  }
  const qBtn = e.target.closest("[data-quality]");
  if (qBtn) {
    if (state.mode === "audio") { state.audioQ = qBtn.dataset.quality; store.set("td.audioQ", state.audioQ); }
    else { state.videoQ = qBtn.dataset.quality; store.set("td.videoQ", state.videoQ); }
    return refreshFormat();
  }
  const act = e.target.closest("[data-act]");
  if (act) {
    const name = act.dataset.act;
    if (name === "close") { state.analysis = null; return renderPreview(); }
    if (name === "single") return analyze(true);
    if (name === "whole") return analyze(false);
    if (name === "all" || name === "none") {
      $$(".pl-row", preview).filter((r) => !r.hidden).forEach((r) => setRow(r, name === "all"));
      return refreshSelection();
    }
  }
  if (e.target.closest("#dlBtn")) startDownload();
});

preview.addEventListener("change", (e) => {
  if (e.target.id === "numberFiles") {
    state.numberFiles = e.target.checked;
    store.set("td.number", state.numberFiles ? "1" : "0");
    return;
  }
  const row = e.target.closest(".pl-row");
  if (row) { setRow(row, e.target.checked); refreshSelection(); }
});

preview.addEventListener("input", (e) => {
  if (e.target.id !== "plSearch") return;
  const q = e.target.value.trim().toLowerCase();
  $$(".pl-row", preview).forEach((r) => { r.hidden = Boolean(q) && !r.dataset.title.includes(q); });
});

async function startDownload() {
  const a = state.analysis;
  if (!a) return;
  const isList = a.type === "playlist";
  const items = isList
    ? a.entries.filter((e) => state.selected.has(e.index))
      .map((e) => ({ url: e.url, title: e.title, thumbnail: e.thumbnail, duration: e.duration, uploader: e.uploader, index: e.index }))
    : [{ url: a.url, title: a.title, thumbnail: a.thumbnail, duration: a.duration, uploader: a.uploader }];
  if (!items.length) return;

  const btn = $("#dlBtn");
  btn.disabled = true;
  try {
    const res = await api("/api/download", {
      method: "POST",
      body: {
        items,
        mode: state.mode,
        quality: currentQuality(),
        playlist_title: isList ? a.title : null,
        number_files: isList && state.numberFiles,
      },
    });
    if (res.queued) toast(`Added ${res.queued} ${res.queued === 1 ? "download" : "downloads"} to the queue.`, "ok");
    else toast("That is already in the queue.");
    state.analysis = null;
    urlInput.value = "";
    renderPreview();
    setQueueFilter("all");
    await pollJobs();
    $(".queue-card").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    toast(err.message, "bad");
    btn.disabled = false;
  }
}

/* ------------------------------------------------------------------ queue */

const queueEl = $("#queue");

function jobRank(job) {
  if (ACTIVE.has(job.status)) return 0;
  if (job.status === "queued") return 1;
  return 2;
}

function matchesFilter(job) {
  switch (state.queueFilter) {
    case "active": return !FINISHED.has(job.status);
    case "done": return job.status === "done";
    case "failed": return job.status === "error" || job.status === "cancelled";
    default: return true;
  }
}

function badgeText(job) {
  if (job.mode === "audio") return `MP3 ${job.quality}`;
  return job.quality === "best" ? "MP4 BEST" : `MP4 ${job.quality}p`;
}

function relLibraryPath(absPath) {
  const root = (state.settings.download_dir || "").replace(/[\\/]+$/, "");
  if (!absPath || !root || !absPath.toLowerCase().startsWith(root.toLowerCase())) return null;
  return absPath.slice(root.length).replace(/^[\\/]+/, "").replace(/\\/g, "/");
}

function jobActions(job) {
  const btn = (act, label, icon, cls = "") =>
    `<button class="icon-btn ${cls}" data-job-act="${act}" title="${label}" aria-label="${label}">${icon}</button>`;
  if (job.status === "done") {
    return btn("play", "Play", ICON.play) + btn("reveal", "Show in folder", ICON.folder) + btn("remove", "Remove from list", ICON.close);
  }
  if (FINISHED.has(job.status)) {
    return btn("retry", "Try again", ICON.retry) + btn("remove", "Remove from list", ICON.close);
  }
  return btn("cancel", "Cancel", ICON.close, "danger");
}

function createJobEl(job) {
  const el = document.createElement("div");
  el.dataset.id = job.id;
  el.innerHTML = `
    <div class="job-thumb">${job.mode === "audio" ? ICON.music : ICON.video}</div>
    <div class="job-body">
      <div class="job-line"><span class="badge"></span><span class="job-title"></span></div>
      <div class="bar"><i></i></div>
      <div class="job-meta"><span class="job-stage"></span><span data-f="size"></span><span data-f="speed"></span><span data-f="eta"></span><span data-f="where"></span></div>
      <div class="job-error" hidden></div>
    </div>
    <div class="job-actions"></div>`;
  return el;
}

function updateJobEl(el, job) {
  el.className = `job ${job.status}`;
  if (el.dataset.status !== job.status) {
    el.dataset.status = job.status;
    $(".job-actions", el).innerHTML = jobActions(job);
  }
  if (el.dataset.thumb !== (job.thumbnail || "")) {
    el.dataset.thumb = job.thumbnail || "";
    const holder = $(".job-thumb", el);
    $("img", holder)?.remove();
    if (job.thumbnail) {
      const img = new Image();
      img.loading = "lazy";
      img.referrerPolicy = "no-referrer";
      img.alt = "";
      img.onerror = () => img.remove();
      img.src = job.thumbnail;
      holder.append(img);
    }
  }
  const badge = $(".badge", el);
  badge.textContent = badgeText(job);
  badge.classList.toggle("audio", job.mode === "audio");
  const title = $(".job-title", el);
  title.textContent = job.title;
  title.title = job.title;
  $(".bar i", el).style.width = `${job.progress.toFixed(1)}%`;

  let stage = job.stage;
  if (job.status === "downloading" && job.total_bytes) stage = `Downloading ${Math.floor(job.progress)}%`;
  $(".job-stage", el).textContent = stage;

  const field = (name) => $(`[data-f="${name}"]`, el);
  const busy = job.status === "downloading";
  field("size").textContent = busy && job.total_bytes
    ? `${fmtBytes(job.downloaded_bytes)} of ${fmtBytes(job.total_bytes)}`
    : job.status === "done" && job.filesize ? fmtBytes(job.filesize) : "";
  field("speed").textContent = busy && job.speed ? `${fmtBytes(job.speed)}/s` : "";
  field("eta").textContent = busy && job.eta != null ? `${fmtDuration(job.eta)} left` : "";
  field("where").textContent = job.playlist_title ? job.playlist_title : (job.uploader || "");

  const err = $(".job-error", el);
  err.hidden = job.status !== "error";
  err.textContent = job.error || "";
}

function renderQueue() {
  const sorted = [...state.jobs].sort((a, b) => {
    const diff = jobRank(a) - jobRank(b);
    if (diff) return diff;
    return jobRank(a) === 2 ? (b.finished_at || 0) - (a.finished_at || 0) : 0;
  });
  const visible = sorted.filter(matchesFilter);
  const visibleIds = new Set(visible.map((j) => j.id));

  for (const [id, el] of state.jobEls) {
    if (!visibleIds.has(id)) { el.remove(); state.jobEls.delete(id); }
  }
  let cursor = queueEl.firstElementChild;
  for (const job of visible) {
    let el = state.jobEls.get(job.id);
    if (!el) { el = createJobEl(job); state.jobEls.set(job.id, el); }
    updateJobEl(el, job);
    if (el === cursor) cursor = cursor.nextElementSibling;
    else queueEl.insertBefore(el, cursor);
  }

  const hasAny = state.jobs.length > 0;
  $("#queueEmpty").hidden = visible.length > 0;
  $("#queueEmpty strong").textContent = hasAny ? "Nothing in this tab" : "No downloads yet";
  $("#queueEmpty span").textContent = hasAny ? "Switch tabs to see other downloads." : "Paste a link above to get started.";
}

function renderStats(stats) {
  const busy = stats.active + stats.queued;
  $("#statActive").textContent = stats.active;
  $("#statQueued").textContent = `${stats.queued} waiting`;
  $("#statDone").textContent = stats.done;
  $("#statFailed").textContent = `${stats.failed} failed`;
  $("#statActive").closest(".stat").classList.toggle("live", busy > 0);

  const badge = $("#navActive");
  badge.hidden = busy === 0;
  badge.textContent = busy;
  document.title = busy ? `(${busy}) TubeDrop` : "TubeDrop";

  $("#clearBtn").hidden = !state.jobs.some((j) => FINISHED.has(j.status));
  $("#cancelAllBtn").hidden = busy < 2;
  $("#retryFailedBtn").hidden = stats.failed === 0;

  // Overall progress for the batch that is running right now.
  const overall = $("#overall");
  if (busy === 0) {
    if (state.baseline) {
      const batch = state.jobs.filter((j) => !state.baseline.has(j.id));
      const ok = batch.filter((j) => j.status === "done").length;
      const failed = batch.filter((j) => j.status === "error").length;
      if (ok || failed) {
        toast(failed ? `${ok} finished, ${failed} failed.` : ok === 1 ? "Download finished." : `All ${ok} downloads finished.`, failed ? "bad" : "ok");
      }
      state.baseline = null;
      loadLibrary();
    }
    overall.hidden = true;
    return;
  }
  if (!state.baseline) {
    state.baseline = new Set(state.jobs.filter((j) => FINISHED.has(j.status)).map((j) => j.id));
  }
  const batch = state.jobs.filter((j) => !state.baseline.has(j.id));
  const finished = batch.filter((j) => FINISHED.has(j.status)).length;
  const pct = batch.length
    ? batch.reduce((sum, j) => sum + (FINISHED.has(j.status) ? 100 : j.progress), 0) / batch.length : 0;
  overall.hidden = batch.length < 2;
  $("#overallLabel").textContent = `${finished} of ${batch.length} finished`;
  $("#overallPct").textContent = `${Math.floor(pct)}%`;
  $("#overallBar").style.width = `${pct.toFixed(1)}%`;
}

function setConnected(on) {
  if (state.connected === on) return;
  state.connected = on;
  if (on) { loadHealth(); toast("Reconnected.", "ok"); }
  else {
    $("#engine").className = "engine bad";
    $("#engineText").textContent = "App is not running";
    toast("Lost connection to TubeDrop. Start it again with start.bat.", "bad");
  }
}

let pollTimer = null;
async function pollJobs() {
  clearTimeout(pollTimer);
  let busy = false;
  try {
    const data = await api("/api/jobs");
    setConnected(true);
    state.jobs = data.jobs;
    renderQueue();
    renderStats(data.stats);
    busy = data.stats.active + data.stats.queued > 0;
  } catch {
    setConnected(false);
  }
  pollTimer = setTimeout(pollJobs, busy ? 800 : 3000);
}

function setQueueFilter(name) {
  state.queueFilter = name;
  $$("#queueTabs .tab").forEach((t) => t.classList.toggle("active", t.dataset.filter === name));
  renderQueue();
}
$("#queueTabs").addEventListener("click", (e) => {
  const tab = e.target.closest(".tab");
  if (tab) setQueueFilter(tab.dataset.filter);
});

queueEl.addEventListener("click", async (e) => {
  const btn = e.target.closest("[data-job-act]");
  if (!btn) return;
  const id = btn.closest(".job").dataset.id;
  const job = state.jobs.find((j) => j.id === id);
  if (!job) return;
  try {
    switch (btn.dataset.jobAct) {
      case "cancel": await api(`/api/jobs/${id}/cancel`, { method: "POST" }); break;
      case "retry": await api(`/api/jobs/${id}/retry`, { method: "POST" }); break;
      case "remove": await api(`/api/jobs/${id}`, { method: "DELETE" }); break;
      case "reveal": await api("/api/open", { method: "POST", body: { path: job.filepath } }); return;
      case "play": {
        const rel = relLibraryPath(job.filepath);
        if (!rel) return toast("This file is outside the current download folder.", "bad");
        return playFile({ path: rel, name: job.title, kind: job.mode === "audio" ? "audio" : "video" });
      }
    }
    pollJobs();
  } catch (err) {
    toast(err.message, "bad");
  }
});

$("#clearBtn").addEventListener("click", async () => { await api("/api/jobs/clear", { method: "POST" }); pollJobs(); });
$("#cancelAllBtn").addEventListener("click", async () => {
  if (!confirm("Cancel every download that is running or waiting?")) return;
  await api("/api/jobs/cancel-all", { method: "POST" });
  pollJobs();
});
$("#retryFailedBtn").addEventListener("click", async () => { await api("/api/jobs/retry-failed", { method: "POST" }); pollJobs(); });

/* ------------------------------------------------------------------ library */

const LIB_RENDER_LIMIT = 400;

async function loadLibrary() {
  try {
    const data = await api("/api/library");
    state.library = data.files;
    $("#statFiles").textContent = data.files.length;
    $("#statSplit").textContent = `${data.audio_count} audio · ${data.video_count} video`;
    $("#statSize").textContent = fmtBytes(data.total_size);
    $("#libraryPath").textContent = `Saved in ${data.download_dir}`;
    renderLibrary();
  } catch { /* poll loop reports connection problems */ }
}

function renderLibrary() {
  const q = state.libSearch;
  const files = state.library.filter((f) =>
    (state.libKind === "all" || f.kind === state.libKind) &&
    (!q || f.name.toLowerCase().includes(q) || f.folder.toLowerCase().includes(q)));
  const shown = files.slice(0, LIB_RENDER_LIMIT);
  $("#libList").innerHTML = shown.map((f) => `
    <div class="lib-row" data-path="${esc(f.path)}">
      <button class="lib-icon ${f.kind}" data-lib-act="play" title="Play" aria-label="Play">${f.kind === "audio" ? ICON.music : ICON.video}</button>
      <div class="lib-name"><strong title="${esc(f.name)}">${esc(f.name)}</strong><span>${esc(f.folder || "Downloads")} · ${f.ext.toUpperCase()}</span></div>
      <div class="lib-info">${fmtBytes(f.size)}<br>${fmtDate(f.modified)}</div>
      <div class="lib-actions">
        <button class="icon-btn" data-lib-act="play" title="Play" aria-label="Play">${ICON.play}</button>
        <button class="icon-btn" data-lib-act="reveal" title="Show in folder" aria-label="Show in folder">${ICON.folder}</button>
        <button class="icon-btn danger" data-lib-act="delete" title="Delete" aria-label="Delete">${ICON.trash}</button>
      </div>
    </div>`).join("") +
    (files.length > shown.length ? `<p class="muted small-text" style="padding:12px 8px 0">Showing the newest ${shown.length} of ${files.length}. Search to narrow it down.</p>` : "");
  const empty = $("#libEmpty");
  empty.hidden = files.length > 0;
  $("strong", empty).textContent = state.library.length ? "No matches" : "Nothing here yet";
  $("span", empty).textContent = state.library.length ? "Try a different search or tab." : "Finished downloads show up in your library.";
}

$("#libSearch").addEventListener("input", (e) => { state.libSearch = e.target.value.trim().toLowerCase(); renderLibrary(); });
$("#libTabs").addEventListener("click", (e) => {
  const tab = e.target.closest(".tab");
  if (!tab) return;
  state.libKind = tab.dataset.kind;
  $$("#libTabs .tab").forEach((t) => t.classList.toggle("active", t === tab));
  renderLibrary();
});

$("#libList").addEventListener("click", async (e) => {
  const btn = e.target.closest("[data-lib-act]");
  if (!btn) return;
  const path = btn.closest(".lib-row").dataset.path;
  const file = state.library.find((f) => f.path === path);
  if (!file) return;
  try {
    if (btn.dataset.libAct === "play") return playFile(file);
    if (btn.dataset.libAct === "reveal") return void await api("/api/open", { method: "POST", body: { path } });
    if (btn.dataset.libAct === "delete") {
      if (!confirm(`Delete "${file.name}"?\n\nIt will be moved to the Recycle Bin.`)) return;
      if (currentMedia === path) stopMedia();
      const res = await api(`/api/library?path=${encodeURIComponent(path)}`, { method: "DELETE" });
      toast(res.recycled ? "Moved to the Recycle Bin." : "File deleted.", "ok");
      loadLibrary();
    }
  } catch (err) {
    toast(err.message, "bad");
  }
});

async function openFolder() {
  try { await api("/api/open", { method: "POST", body: {} }); } catch (err) { toast(err.message, "bad"); }
}
$("#openFolderSide").addEventListener("click", openFolder);
$("#openFolderLib").addEventListener("click", openFolder);

/* ------------------------------------------------------------------ playback */

const audioEl = $("#audioEl");
const videoEl = $("#videoEl");
let currentMedia = null;

const mediaUrl = (path) => "/media/" + path.split("/").map(encodeURIComponent).join("/");

function stopMedia() {
  audioEl.pause(); audioEl.removeAttribute("src"); audioEl.load();
  videoEl.pause(); videoEl.removeAttribute("src"); videoEl.load();
  $("#player").hidden = true;
  $("#videoModal").hidden = true;
  currentMedia = null;
}

function playFile(file) {
  stopMedia();
  currentMedia = file.path;
  if (file.kind === "audio") {
    $("#playerTitle").textContent = file.name;
    $("#player").hidden = false;
    audioEl.src = mediaUrl(file.path);
    audioEl.play().catch(() => {});
  } else {
    $("#videoTitle").textContent = file.name;
    $("#videoModal").hidden = false;
    videoEl.src = mediaUrl(file.path);
    videoEl.play().catch(() => {});
  }
}

$("#playerClose").addEventListener("click", stopMedia);
$("#videoClose").addEventListener("click", stopMedia);
$("#videoModal").addEventListener("click", (e) => { if (e.target.id === "videoModal") stopMedia(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("#videoModal").hidden) stopMedia(); });
[audioEl, videoEl].forEach((el) => el.addEventListener("error", () => {
  if (el.getAttribute("src")) toast("This file could not be played in the browser. Open it from the folder instead.", "bad");
}));

/* ------------------------------------------------------------------ settings */

function fillSettings(s) {
  state.settings = s;
  $("#setDir").value = s.download_dir;
  $("#setConcurrent").textContent = s.max_concurrent;
  $("#setThumb").checked = s.embed_thumbnail;
  $("#setMeta").checked = s.embed_metadata;
}

async function loadSettings() {
  try { fillSettings(await api("/api/settings")); } catch { /* handled by poll loop */ }
}

async function saveSettings(changes, message) {
  try {
    fillSettings(await api("/api/settings", { method: "POST", body: changes }));
    if (message) toast(message, "ok");
    if (changes.download_dir) { loadLibrary(); loadHealth(); }
  } catch (err) {
    toast(err.message, "bad");
    loadSettings();
  }
}

$("#saveDirBtn").addEventListener("click", () => {
  const dir = $("#setDir").value.trim();
  if (dir) saveSettings({ download_dir: dir }, "Download folder updated.");
});
$("#setDir").addEventListener("keydown", (e) => { if (e.key === "Enter") $("#saveDirBtn").click(); });
$("#browseBtn").addEventListener("click", async () => {
  const btn = $("#browseBtn");
  btn.disabled = true;
  toast("A folder picker opened on your PC. It may be behind this window.");
  try {
    const res = await api("/api/pick-folder", { method: "POST" });
    if (res.path) await saveSettings({ download_dir: res.path }, "Download folder updated.");
  } catch (err) {
    toast(err.message, "bad");
  } finally {
    btn.disabled = false;
  }
});
$("#concurrency").addEventListener("click", (e) => {
  const step = Number(e.target.dataset.step);
  if (!step) return;
  const next = Math.max(1, Math.min(6, (state.settings.max_concurrent || 3) + step));
  if (next !== state.settings.max_concurrent) saveSettings({ max_concurrent: next });
});
$("#setThumb").addEventListener("change", (e) => saveSettings({ embed_thumbnail: e.target.checked }));
$("#setMeta").addEventListener("change", (e) => saveSettings({ embed_metadata: e.target.checked }));

/* ------------------------------------------------------------------ startup */

async function loadHealth() {
  try {
    const h = await api("/api/health");
    const engine = $("#engine");
    engine.className = `engine ${h.ffmpeg ? "ok" : "bad"}`;
    $("#engineText").textContent = h.ffmpeg ? `Engine ready · yt-dlp ${h.ytdlp_version}` : "ffmpeg is missing";
    $("#engineDetail").textContent = h.ffmpeg
      ? `yt-dlp ${h.ytdlp_version} with ffmpeg. Everything is ready.`
      : "ffmpeg was not found. Install it with: winget install Gyan.FFmpeg";
  } catch { /* handled by poll loop */ }
}

loadHealth();
loadSettings();
loadLibrary();
pollJobs();
urlInput.focus();
