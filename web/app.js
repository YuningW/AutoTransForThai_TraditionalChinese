"use strict";
/* AutoCaption page. Talks to the local server (ac/server.py); no build step. */

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];

async function api(method, url, body) {
  const opt = { method, headers: { "x-ac": "1" } };
  if (body instanceof FormData) opt.body = body;
  else if (body !== undefined) { opt.body = JSON.stringify(body); opt.headers["content-type"] = "application/json"; }
  const r = await fetch(url, opt);
  let data = null;
  try { data = await r.json(); } catch { /* empty */ }
  if (!r.ok) throw new Error((data && (data.error || data.detail)) || `Request failed (${r.status})`);
  return data;
}

function fmtTime(t) {
  t = Math.max(0, t || 0);
  const m = Math.floor(t / 60), s = t - m * 60;
  return `${m}:${s.toFixed(1).padStart(4, "0")}`;
}
function ago(ts) {
  const s = Date.now() / 1000 - ts;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return new Date(ts * 1000).toLocaleDateString();
}
const STATE_WORDS = {
  fetching: "Downloading", preparing: "Reading the video", cleaning: "Removing music", listening: "Listening",
  reading: "Reading your screenshots", tidying: "Tidying the Thai", translating: "Translating", checking: "Checking itself",
  fixing: "Fixing your flags", redoing: "Redoing", burning: "Burning captions in", ready: "Ready to check",
};

/* ============================================================ start view */

const pending = { video: null, original: [], translation: [] };

function setVideo(file) {
  pending.video = file;
  $("#drop").classList.toggle("has", !!file);
  $("#dropText").textContent = file ? file.name : "Drop a video here";
  $("#dropHint").textContent = file ? `${(file.size / 1e6).toFixed(0)} MB. Click to choose a different one.` : "or click to choose a file";
  if (file) $("#link").value = "";
  updateGo();
}
function updateGo() {
  $("#go").disabled = !(pending.video || $("#link").value.trim());
}
function renderChips(kind) {
  const box = $(`[data-list="${kind}"]`);
  box.replaceChildren(...pending[kind].map((f, i) => {
    const s = document.createElement("span");
    const b = document.createElement("b"); b.textContent = f.name;
    const x = document.createElement("button"); x.type = "button"; x.textContent = "×"; x.setAttribute("aria-label", "Remove " + f.name);
    x.onclick = () => { pending[kind].splice(i, 1); renderChips(kind); };
    s.append(b, x);
    return s;
  }));
}

$("#videoFile").addEventListener("change", e => setVideo(e.target.files[0] || null));
$("#link").addEventListener("input", () => { if ($("#link").value.trim() && pending.video) setVideo(null); updateGo(); });
$$("input[type=file][data-kind]").forEach(inp => inp.addEventListener("change", () => {
  pending[inp.dataset.kind].push(...inp.files);
  inp.value = "";
  renderChips(inp.dataset.kind);
}));

// Drop anywhere on the start page: videos become the video, pictures/text become helpers.
const drop = $("#drop");
["dragenter", "dragover"].forEach(ev => document.addEventListener(ev, e => {
  if (!$("#startView").hidden && e.dataTransfer && [...e.dataTransfer.types].includes("Files")) { e.preventDefault(); drop.classList.add("over"); }
}));
["dragleave", "drop"].forEach(ev => document.addEventListener(ev, e => {
  if (ev === "dragleave" && e.relatedTarget) return;
  drop.classList.remove("over");
}));
document.addEventListener("drop", e => {
  if ($("#startView").hidden || !e.dataTransfer?.files.length) return;
  e.preventDefault();
  for (const f of e.dataTransfer.files) {
    if (f.type.startsWith("video/") || /\.(mkv|mov|mts|mp4|m4v|webm|avi)$/i.test(f.name)) setVideo(f);
    else if (f.type.startsWith("image/") || /\.(srt|txt|vtt)$/i.test(f.name)) {
      const kind = e.target.closest?.("[data-list], .help-col")?.querySelector("[data-kind]")?.dataset.kind || "original";
      pending[kind].push(f); renderChips(kind); $("#helpBox").open = true;
    }
  }
});

function uploadVideo(form, onProgress) {
  return new Promise((resolve, reject) => {
    const x = new XMLHttpRequest();
    x.open("POST", "/api/jobs/upload");
    x.setRequestHeader("x-ac", "1");
    x.upload.onprogress = e => e.lengthComputable && onProgress(e.loaded / e.total);
    x.onload = () => {
      let d = null; try { d = JSON.parse(x.responseText); } catch { /* */ }
      x.status < 300 ? resolve(d) : reject(new Error((d && d.error) || `Upload failed (${x.status})`));
    };
    x.onerror = () => reject(new Error("The upload stopped. Is AutoCaption still running?"));
    x.send(form);
  });
}

async function sendHelpers(jid) {
  for (const kind of ["original", "translation"]) {
    const text = $(`[data-text="${kind}"]`).value.trim();
    if (!pending[kind].length && !text) continue;
    const f = new FormData();
    f.append("kind", kind);
    f.append("text", text);
    pending[kind].forEach(file => f.append("files", file));
    await api("POST", `/api/jobs/${jid}/helpers`, f);
  }
}

$("#newForm").addEventListener("submit", async e => {
  e.preventDefault();
  const err = $("#formError"); err.textContent = "";
  const go = $("#go"); go.disabled = true;
  const about = $("#about").value.trim(), clean = $("#cleanVoice").checked, fast = $("#fast").checked;
  try {
    let job;
    if (pending.video) {
      const f = new FormData();
      f.append("file", pending.video); f.append("about", about); f.append("clean_voice", clean); f.append("fast", fast);
      job = await uploadVideo(f, p => { go.textContent = `Copying the video… ${Math.round(p * 100)}%`; });
    } else {
      go.textContent = "Starting…";
      job = await api("POST", "/api/jobs", { url: $("#link").value.trim(), about, clean_voice: clean, fast });
    }
    await sendHelpers(job.id);
    resetForm();
    location.hash = `#/job/${job.id}`;
  } catch (ex) {
    err.textContent = ex.message;
  } finally {
    go.textContent = "Make captions"; updateGo();
  }
});

function resetForm() {
  setVideo(null);
  $("#link").value = ""; $("#about").value = ""; $("#cleanVoice").checked = false; $("#fast").checked = false;
  pending.original = []; pending.translation = [];
  renderChips("original"); renderChips("translation");
  $$("[data-text]").forEach(t => { t.value = ""; });
}

async function loadJobList() {
  const list = await api("GET", "/api/jobs");
  $("#noJobs").hidden = list.length > 0;
  $("#jobList").replaceChildren(...list.map(j => {
    const li = document.createElement("li");
    const a = document.createElement("a"); a.href = `#/job/${j.id}`;
    const t = document.createElement("span"); t.className = "jt"; t.textContent = j.title || "Untitled";
    const s = document.createElement("span"); s.className = "js";
    const bits = [];
    if (j.busy) bits.push(`<span class="busy">${STATE_WORDS[j.state] || "Working"}…</span>`);
    else if (j.state === "ready") bits.push(`${j.counts?.lines || 0} lines`);
    if (j.counts?.flagged) bits.push(`${j.counts.flagged} flagged`);
    bits.push(ago(j.updated));
    s.innerHTML = bits.join(", ");
    a.append(t, s);
    const del = document.createElement("button"); del.className = "del"; del.type = "button"; del.textContent = "Delete";
    del.onclick = async () => {
      if (!confirm(`Delete “${j.title}” and its working files? Saved SRT and video files stay.`)) return;
      try { await api("DELETE", `/api/jobs/${j.id}`); loadJobList(); } catch (ex) { alert(ex.message); }
    };
    li.append(a, del);
    return li;
  }));
}

/* ============================================================ job view */

let job = null, lines = [], linesRev = -1, pollTimer = null, dirtyWhileEditing = false;
const video = $("#video");

async function openJob(jid) {
  $("#startView").hidden = true; $("#jobView").hidden = false;
  job = null; lines = []; linesRev = -1;
  $("#lines").replaceChildren();
  video.removeAttribute("src"); video.load();
  await refresh(jid);
}

async function refresh(jid) {
  clearTimeout(pollTimer);
  if (location.hash !== `#/job/${jid}`) return;
  try {
    const j = await api("GET", `/api/jobs/${jid}`);
    const firstVideo = !job || (!job.media?.duration && j.media?.duration);
    job = j;
    renderJob();
    if (firstVideo && j.media?.duration) { video.src = `/api/jobs/${jid}/video`; }
    if (j.lines_rev !== linesRev) {
      if (editing()) dirtyWhileEditing = true;
      else { lines = await api("GET", `/api/jobs/${jid}/lines`); linesRev = j.lines_rev; renderLines(); }
    }
  } catch (ex) {
    $("#jobError").textContent = ex.message;
  }
  pollTimer = setTimeout(() => refresh(jid), job && job.busy ? 1000 : 4000);
}

function editing() {
  const a = document.activeElement;
  return a && a.closest && a.closest("#lines") && (a.isContentEditable || a.tagName === "INPUT");
}

function renderJob() {
  $("#topTitle").textContent = job.title || "";
  document.title = (job.title ? job.title + " – " : "") + "AutoCaption";
  const st = $("#status");
  const failed = !!job.error && !job.busy;
  st.classList.toggle("idle", !job.busy && !failed);
  st.classList.toggle("failed", failed);
  $("#statusText").textContent = failed ? "Stopped" : (job.label || STATE_WORDS[job.state] || "Working");
  $("#jobError").textContent = failed ? job.error : "";
  $("#retry").hidden = !failed;
  const known = typeof job.progress === "number";
  $("#bar").classList.toggle("unknown", !known || !job.busy);
  $("#barFill").style.width = known ? `${Math.round(job.progress * 100)}%` : "0";

  $("#export").disabled = !!job.busy || !(job.counts && job.counts.lines);
  $("#fixNow").disabled = !!job.busy;

  // exports
  $("#exports").replaceChildren(...(job.exports || []).map(x => {
    const li = document.createElement("li");
    const b = document.createElement("button"); b.type = "button";
    b.textContent = x.path.split("/").pop();
    b.title = "Show in Finder";
    b.onclick = () => api("POST", "/api/reveal", { path: x.path }).catch(ex => alert(ex.message));
    li.append(b); return li;
  }));

  // helpers
  const hs = job.helpers || [];
  $("#helperCount").textContent = hs.length || "";
  $("#helperList").replaceChildren(...hs.map(h => {
    const li = document.createElement("li");
    const s = document.createElement("span");
    const what = h.kind === "original" ? "Thai" : "Translation";
    const n = (h.pictures || []).length;
    s.innerHTML = `<b></b> <small></small>`;
    s.querySelector("b").textContent = h.label;
    s.querySelector("small").textContent = `${what}${n ? `, ${n} picture${n > 1 ? "s" : ""}` : ""}${h.used ? "" : ", not used yet"}`;
    const x = document.createElement("button"); x.type = "button"; x.textContent = "Remove";
    x.onclick = async () => { await api("DELETE", `/api/jobs/${job.id}/helpers/${h.id}`); refresh(job.id); };
    li.append(s, x); return li;
  }));
  $("#redoAll").hidden = !hs.some(h => !h.used) || !!job.busy || !(job.counts && job.counts.lines);

  // activity
  $("#log").replaceChildren(...(job.activity || []).slice().reverse().map(a => {
    const li = document.createElement("li");
    li.className = a.kind || "";
    const tm = document.createElement("time");
    tm.textContent = new Date(a.at * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    li.append(tm, document.createTextNode(a.msg));
    return li;
  }));
  if ((job.activity || []).some(a => a.kind === "learn")) loadMemoryCount();
  updateFixbar();
}

$("#retry").onclick = async () => {
  try { await api("POST", `/api/jobs/${job.id}/retry`); refresh(job.id); } catch (ex) { alert(ex.message); }
};

/* ---------------------------------------------------------- caption lines */

const tpl = $("#lineTpl");
const UNSURE = 0.55;

function renderLines() {
  dirtyWhileEditing = false;
  $("#emptyLines").hidden = lines.length > 0;
  const ol = $("#lines");
  const open = new Set($$(".line .flagbox:not([hidden])", ol).map(b => +b.closest(".line").dataset.id));
  ol.replaceChildren(...lines.map(l => lineEl(l, open.has(l.id))));
  updateFixbar();
  current = null; tick();
}

function lineEl(l, flagOpen) {
  const li = tpl.content.firstElementChild.cloneNode(true);
  li.dataset.id = l.id;
  const unsure = l.status === "auto" && l.kind === "speech" && l.conf < UNSURE;
  li.classList.toggle("unsure", unsure);
  li.classList.toggle("fixed", l.status === "fixed");
  li.classList.toggle("edited", l.status === "edited");
  li.classList.toggle("flagged", !!l.flag);
  li.classList.add(l.kind || "speech");
  $(".time", li).textContent = fmtTime(l.start);
  $(".time", li).title = `${fmtTime(l.start)} – ${fmtTime(l.end)}. Play from here`;
  $(".th", li).textContent = l.th;
  $(".zh", li).textContent = l.zh || "";
  $(".dot", li).title = unsure ? "It wasn't sure it heard this right" : l.status === "fixed" ? "It fixed this line" : l.status === "edited" ? "You typed this" : "";

  // why: what it changed, what it first heard, your note
  const why = $(".why", li);
  const bits = [];
  if (l.status === "fixed" && l.explain) bits.push(`<b>Fixed:</b> ${esc(l.explain)}`);
  if (l.feedback) bits.push(`Your note: “${esc(l.feedback)}”`);
  if (l.th_before && l.th_before !== l.th) bits.push(`Before: <span class="heard">${esc(l.th_before)}</span>${l.zh_before ? " / " + esc(l.zh_before) : ""}`);
  else if (l.zh_before && l.zh_before !== l.zh && l.status !== "edited") bits.push(`Before: ${esc(l.zh_before)}`);
  if (l.kind === "song") bits.push("Sung lyrics: not translated. Type your own if you like.");
  why.innerHTML = bits.join("<br>");

  // flag box
  const box = $(".flagbox", li);
  box.hidden = !(flagOpen || l.flag);
  $$(".flag-types button", box).forEach(b => {
    b.setAttribute("role", "radio");
    b.setAttribute("aria-checked", String(b.dataset.flag === l.flag));
  });
  $(".note", box).value = l.note || "";
  $(".timing", box).hidden = l.flag !== "timing";
  return li;
}

function esc(s) { return String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]); }
function lineOf(el) { const li = el.closest(".line"); return li && lines.find(l => l.id === +li.dataset.id); }

async function patch(l, changes) {
  try {
    const out = await api("PATCH", `/api/jobs/${job.id}/lines/${l.id}`, changes);
    Object.assign(l, out);
    linesRev = -1;           // the server bumped its revision; the next poll picks it up
    const li = $(`.line[data-id="${l.id}"]`);
    if (li && !editing()) li.replaceWith(lineEl(l, !$(".flagbox", li).hidden));
    updateFixbar();
  } catch (ex) { alert(ex.message); }
}

const ol = $("#lines");
ol.addEventListener("click", e => {
  const l = lineOf(e.target);
  if (!l) return;
  if (e.target.closest(".time")) { video.currentTime = l.start + 0.01; video.play(); return; }
  if (e.target.closest(".flag")) {
    const box = $(".flagbox", e.target.closest(".line"));
    if (l.flag) { box.hidden = false; $(".note", box).focus(); return; }
    box.hidden = !box.hidden;
    if (!box.hidden) $(".note", box).focus();
    return;
  }
  const ft = e.target.closest(".flag-types button");
  if (ft) { patch(l, { flag: ft.dataset.flag === l.flag ? "" : ft.dataset.flag }); return; }
  if (e.target.closest(".unflag")) { patch(l, { flag: "", note: "" }); return; }
  const tb = e.target.closest(".timing button");
  if (tb) {
    const [k, op] = [tb.dataset.t.slice(0, -1), tb.dataset.t.slice(-1)];
    const v = op === "=" ? video.currentTime : l[k] + (op === "+" ? 0.2 : -0.2);
    patch(l, { [k]: Math.round(v * 1000) / 1000 });
  }
});
ol.addEventListener("focusout", e => {
  const l = lineOf(e.target);
  if (!l) return;
  const el = e.target;
  if (el.classList.contains("th") || el.classList.contains("zh")) {
    const k = el.classList.contains("th") ? "th" : "zh";
    const v = el.textContent.replace(/\s+\n/g, "\n").trim();
    if (v !== (l[k] || "")) patch(l, { [k]: v });
  } else if (el.classList.contains("note")) {
    const v = el.value.trim();
    if (v !== (l.note || "")) patch(l, { note: v, ...(l.flag ? {} : { flag: v ? "other" : "" }) });
  }
  if (dirtyWhileEditing) setTimeout(() => !editing() && job && refresh(job.id), 50);
});
ol.addEventListener("keydown", e => {
  if (e.key === "Enter" && !e.shiftKey && (e.target.isContentEditable || e.target.classList.contains("note"))) {
    e.preventDefault(); e.target.blur();
  }
  if (e.key === "Escape" && e.target.isContentEditable) {
    const l = lineOf(e.target);
    e.target.textContent = e.target.classList.contains("th") ? l.th : (l.zh || "");
    e.target.blur();
  }
});

function updateFixbar() {
  const n = lines.filter(l => l.flag).length;
  $("#fixbar").hidden = n === 0;
  $("#flagCount").textContent = `${n} line${n > 1 ? "s" : ""} flagged. It will listen again where needed, fix them, and remember what your notes teach it.`;
}
$("#fixNow").onclick = async () => {
  try { await api("POST", `/api/jobs/${job.id}/fix`); refresh(job.id); } catch (ex) { alert(ex.message); }
};
$("#redoAll").onclick = async () => {
  try { await api("POST", `/api/jobs/${job.id}/redo`, { what: "all" }); refresh(job.id); } catch (ex) { alert(ex.message); }
};

/* ---------------------------------------------------------- helpers added later */

$("#addHelper").onclick = async () => {
  const files = $("#helperFiles").files, text = $("#helperText").value.trim();
  if (!files.length && !text) { $("#helperFiles").click(); return; }
  const f = new FormData();
  f.append("kind", $("#helperKind").value); f.append("text", text);
  [...files].forEach(x => f.append("files", x));
  try {
    await api("POST", `/api/jobs/${job.id}/helpers`, f);
    $("#helperFiles").value = ""; $("#helperText").value = "";
    refresh(job.id);
  } catch (ex) { alert(ex.message); }
};
$("#helperFiles").addEventListener("change", () => {
  const n = $("#helperFiles").files.length;
  $("#helperFiles").parentElement.lastChild.textContent = n ? `${n} file${n > 1 ? "s" : ""} chosen` : "Add screenshots or files";
});

/* ---------------------------------------------------------- export */

$("#size").addEventListener("input", () => { $("#sizeVal").textContent = Math.round($("#size").value * 100) + "%"; placeOverlay(); });
$("#export").onclick = async () => {
  const burn = $("input[name=burn]:checked").value;
  try {
    await api("POST", `/api/jobs/${job.id}/export`, { srt: true, burn, size: +$("#size").value, position: $("input[name=pos]:checked").value });
    refresh(job.id);
  } catch (ex) { alert(ex.message); }
};

/* ---------------------------------------------------------- video + overlay */

let current = null;
function lineAt(t) {
  let lo = 0, hi = lines.length - 1, best = null;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (lines[mid].start <= t) { best = mid; lo = mid + 1; } else hi = mid - 1;
  }
  return best !== null && t <= lines[best].end ? lines[best] : null;
}
function tick() {
  const l = lines.length ? lineAt(video.currentTime) : null;
  if (l !== current) {
    current = l;
    $$(".line.now").forEach(x => x.classList.remove("now"));
    const show = $("input[name=show]:checked").value;
    $("#ovTh").textContent = l && show !== "zh" && l.kind !== "sound" ? l.th : "";
    $("#ovZh").textContent = l && show !== "th" ? (l.zh || "") : "";
    if (l) {
      const li = $(`.line[data-id="${l.id}"]`);
      if (li) {
        li.classList.add("now");
        if ($("#follow").checked && !editing() && !video.paused) {
          const r = li.getBoundingClientRect();
          if (r.top < 110 || r.bottom > innerHeight - 80) li.scrollIntoView({ block: "center", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
        }
      }
    }
  }
}
function loop() { tick(); if (!video.paused) requestAnimationFrame(loop); }
video.addEventListener("play", loop);
video.addEventListener("seeked", tick);
video.addEventListener("timeupdate", tick);
$$("input[name=show]").forEach(r => r.addEventListener("change", () => { current = undefined; tick(); }));
$$("input[name=pos]").forEach(r => r.addEventListener("change", placeOverlay));
// What's shown on the video follows what will be burned in.
$$("input[name=burn]").forEach(r => r.addEventListener("change", () => {
  const v = r.value === "none" ? "both" : r.value;
  $(`input[name=show][value="${v}"]`).checked = true; current = undefined; tick();
}));

// Size the overlay like the burned-in captions: by the picture's short side (see captions.ass).
function placeOverlay() {
  const vw = video.videoWidth, vh = video.videoHeight;
  const box = $("#player").getBoundingClientRect();
  if (!vw || !vh || !box.width) return;
  const scale = Math.min(box.width / vw, video.clientHeight / vh);
  const pw = vw * scale, ph = vh * scale;
  const left = (box.width - pw) / 2, top = (video.clientHeight - ph) / 2;
  const short = Math.min(vw, vh) * scale, size = +$("#size").value;
  const ov = $("#overlay");
  ov.style.left = `${left + pw * 0.06}px`;
  ov.style.width = `${pw * 0.88}px`;
  const atTop = $("input[name=pos]:checked").value === "top";
  ov.style.top = atTop ? `${top + ph * 0.06}px` : "auto";
  ov.style.bottom = atTop ? "auto" : `${box.height - (top + ph) + ph * 0.06}px`;
  ov.classList.toggle("at-top", atTop);
  $("#ovZh").style.fontSize = `${short * 0.058 * size}px`;
  $("#ovTh").style.fontSize = `${short * 0.044 * size}px`;
}
video.addEventListener("loadedmetadata", placeOverlay);
new ResizeObserver(placeOverlay).observe($("#player"));

/* ============================================================ memory */

async function loadMemoryCount() {
  try {
    const m = await api("GET", "/api/memory");
    const n = m.names.length + m.words.length + m.rules.length;
    $("#memCount").textContent = n || "";
    return m;
  } catch { return null; }
}
async function renderMemory() {
  const m = await loadMemoryCount();
  if (!m) return;
  for (const kind of ["names", "words", "rules"]) {
    $(`[data-mem="${kind}"]`).replaceChildren(...m[kind].map(e => {
      const li = document.createElement("li");
      if (kind === "rules") {
        const t = document.createElement("span"); t.className = "mtext"; t.textContent = e.text; li.append(t);
      } else {
        const a = document.createElement("span"); a.className = "mth"; a.textContent = e.th || "—";
        const b = document.createElement("span"); b.className = "mzh"; b.textContent = e.zh || "—";
        li.append(a, b);
      }
      const x = document.createElement("button"); x.type = "button"; x.textContent = "Remove";
      x.onclick = async () => { await api("DELETE", `/api/memory/${kind}/${e.id}`); renderMemory(); };
      li.append(x);
      if (e.note || e.source) {
        const s = document.createElement("small");
        s.textContent = [e.note, e.source && `from ${e.source}`].filter(Boolean).join(". ");
        li.append(s);
      }
      return li;
    }));
  }
  $("#redoTranslation").hidden = !job || $("#jobView").hidden || !!job.busy;
}
$("#openMemory").onclick = () => { renderMemory(); $("#memory").showModal(); };
$$(".mem-add").forEach(f => f.addEventListener("submit", async e => {
  e.preventDefault();
  const data = Object.fromEntries(new FormData(f));
  if (!Object.values(data).some(v => v.trim())) return;
  try { await api("POST", "/api/memory", { kind: f.dataset.kind, ...data }); f.reset(); renderMemory(); }
  catch (ex) { alert(ex.message); }
}));
$("#redoTranslation").onclick = async () => {
  $("#memory").close();
  try { await api("POST", `/api/jobs/${job.id}/redo`, { what: "translation" }); refresh(job.id); } catch (ex) { alert(ex.message); }
};

/* ============================================================ routing */

async function route() {
  const m = location.hash.match(/^#\/job\/([0-9a-f]{12})$/);
  if (m) return openJob(m[1]);
  clearTimeout(pollTimer);
  job = null;
  video.pause();
  $("#jobView").hidden = true; $("#startView").hidden = false;
  $("#topTitle").textContent = ""; document.title = "AutoCaption";
  loadJobList();
}
$("#home").onclick = () => { location.hash = ""; };
addEventListener("hashchange", route);
api("GET", "/api/status").then(s => {
  $("#outDir").textContent = s.out;
  if (!s.claude) $("#formError").textContent = "The Claude command-line tool isn't installed, so it can only listen, not translate. Install Claude Code and sign in once.";
}).catch(() => {});
loadMemoryCount();
route();
setInterval(() => { if (!$("#startView").hidden) loadJobList(); }, 5000);
