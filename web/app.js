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
  reviewing: "Listening again to a stretch", touches: "Picking moments for emoji", speakers: "Working out who's talking",
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
  $("#link").value = ""; $("#about").value = "";
  if (settings) { $("#cleanVoice").checked = settings.clean_voice = $("#cleanVoice").checked; settings.fast = $("#fast").checked; }
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
  job = null; lines = []; linesRev = -1; touches = []; touchesRev = -1; selTouch = null;
  $("#lines").replaceChildren(); $("#touchEdit").hidden = true; $("#rangeBox").hidden = true;
  range.from = range.to = null;
  if (!settings) await loadSettings().catch(() => {});
  video.removeAttribute("src"); video.load();
  await refresh(jid);
}

async function refresh(jid) {
  clearTimeout(pollTimer);
  if (location.hash !== `#/job/${jid}`) return;
  try {
    const j = await api("GET", `/api/jobs/${jid}`);
    const firstVideo = !job || (!job.media?.duration && j.media?.duration);
    const first = !job;
    if (job && job.id === j.id) { j.style = job.style; j.speakers = job.speakers; }   // the page owns these while you edit
    job = j;
    renderJob();
    if (first) { renderStylePanel(); renderPeople(); placeOverlay(); picked.clear(); }
    else if (job.speakers && !document.activeElement?.closest?.("#peopleList")) { /* keep the page's copy */ }
    if ((j.touches_rev || 0) !== touchesRev) await loadTouches();
    if (firstVideo && j.media?.duration) { video.src = `/api/jobs/${jid}/video`; }
    if (j.lines_rev !== linesRev) {
      if (editing()) dirtyWhileEditing = true;
      else { lines = await api("GET", `/api/jobs/${jid}/lines`); linesRev = j.lines_rev; renderLines(); renderRange(); }
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
  $("#stopJob").hidden = !job.busy;
  $("#stopJob").disabled = job.label === "Stopping…";
  const known = typeof job.progress === "number";
  $("#bar").classList.toggle("unknown", !known || !job.busy);
  $("#barFill").style.width = known ? `${Math.round(job.progress * 100)}%` : "0";

  $("#export").disabled = !!job.busy || !(job.counts && job.counts.lines);
  const noVideo = !job.media?.duration;
  ["#addLineHere", "#addTouchHere", "#markRange"].forEach(s => { $(s).disabled = noVideo; });
  $("#suggestTouches").disabled = !!job.busy || !(job.counts && job.counts.lines);
  if (!$("#rangeBox").hidden) renderRange();
  const music = !!job.options?.clean_voice, done = job.state === "ready" && !job.busy && job.counts?.lines;
  $("#again").hidden = !done;
  $("#againText").textContent = music ? "Listened with the background music removed."
    : "Background music drowning out words?";
  $("#againBtn").textContent = music ? "Listen again without removing music" : "Listen again with the music removed";
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

$("#againBtn").onclick = async () => {
  const music = !job.options?.clean_voice;
  if (!confirm("Start the listening over? Lines you typed or fixed with a note stay; everything else is redone.")) return;
  try { await api("POST", `/api/jobs/${job.id}/listen-again`, { clean_voice: music }); refresh(job.id); }
  catch (ex) { alert(ex.message); }
};

$("#stopJob").onclick = async () => {
  if (!confirm("Stop what it's doing now? Anything already finished is kept.")) return;
  try { job = { ...job, ...(await api("POST", `/api/jobs/${job.id}/stop`)) }; renderJob(); refresh(job.id); }
  catch (ex) { alert(ex.message); }
};

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
  for (const id of [...picked]) if (!lines.some(l => l.id === id)) picked.delete(id);
  renderBulk();
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
  paintWho(li, l);
  $(".th", li).textContent = l.th;
  $(".zh", li).textContent = l.zh || "";
  $(".dot", li).title = unsure ? "It wasn't sure it heard this right" : l.status === "fixed" ? "It fixed this line" : l.status === "edited" ? "You typed this" : "";

  // why: what it changed, what it first heard, your note
  const why = $(".why", li);
  const bits = [];
  if (l.status === "fixed" && l.explain) bits.push(`<b>Fixed:</b> ${esc(l.explain)}`);
  else if (l.reviewed && l.explain) bits.push(`<b class="guess">It guessed here, please check:</b> ${esc(l.explain)}`);
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
  if (e.target.classList.contains("pick")) {
    const on = e.target.checked;
    if (e.shiftKey && lastPick !== null) {            // Shift: the whole range from the last tick
      const a = lines.findIndex(x => x.id === lastPick), b = lines.findIndex(x => x.id === l.id);
      lines.slice(Math.min(a, b), Math.max(a, b) + 1).forEach(x => on ? picked.add(x.id) : picked.delete(x.id));
    } else if (on) picked.add(l.id); else picked.delete(l.id);
    lastPick = l.id; renderBulk();
    return;
  }
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
  if (e.target.closest(".twoppl")) {
    if (!(job.speakers || []).length) {
      $("#stylePanel").open = true; $("#addPerson").scrollIntoView({ block: "center" });
      alert("Add the people first (Caption style → People), so each line can have its own colour.");
      return;
    }
    api("POST", `/api/jobs/${job.id}/lines/${l.id}/split`).then(async n => {
      lines = await api("GET", `/api/jobs/${job.id}/lines`); linesRev = -1; renderLines();
      const el = $(`.line[data-id="${n.id}"] .zh`); if (el) { el.scrollIntoView({ block: "center" }); el.focus(); }
    }).catch(ex => alert(ex.message));
    return;
  }
  if (e.target.closest(".delline")) {
    if (!confirm("Delete this line?")) return;
    api("DELETE", `/api/jobs/${job.id}/lines/${l.id}`).then(() => {
      lines = lines.filter(x => x.id !== l.id); e.target.closest(".line").remove(); updateFixbar(); current = undefined; tick();
    }).catch(ex => alert(ex.message));
    return;
  }
  const tb = e.target.closest(".timing button");
  if (tb) {
    const [k, op] = [tb.dataset.t.slice(0, -1), tb.dataset.t.slice(-1)];
    const v = op === "=" ? video.currentTime : l[k] + (op === "+" ? 0.2 : -0.2);
    patch(l, { [k]: Math.round(v * 1000) / 1000 });
  }
});
ol.addEventListener("change", e => {
  if (!e.target.classList.contains("who")) return;
  const l = lineOf(e.target);
  if (l) patch(l, { speaker: e.target.value });
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

$("#export").onclick = async () => {
  const burn = $("input[name=burn]:checked").value;
  try {
    await saveStyleNow();
    await api("POST", `/api/jobs/${job.id}/export`, { srt: true, burn });
    refresh(job.id);
  } catch (ex) { alert(ex.message); }
};

/* ---------------------------------------------------------- settings: models, themes, fonts */

let settings = null;
async function loadSettings() {
  settings = await api("GET", "/api/settings");
  const fill = (sel, list) => sel.replaceChildren(...list.map(f => {
    const o = document.createElement("option"); o.value = f.family; o.textContent = f.label;
    o.style.fontFamily = `"${f.family}"`; return o;
  }));
  fill($("#zhFont"), settings.fonts.zh);
  fill($("#thFont"), settings.fonts.th);
  $("#themes").replaceChildren(...settings.themes.map(t => {
    const b = document.createElement("button");
    b.type = "button"; b.className = "theme"; b.dataset.theme = t.key; b.setAttribute("role", "radio");
    const sample = document.createElement("span"); sample.className = "theme-sample"; sample.textContent = "字幕 ซับ";
    Object.assign(sample.style, rowCss(t.style, 20, false));
    if (t.style.box) Object.assign(sample.style, { background: t.style.box_color, padding: "1px 6px", borderRadius: "5px" });
    const name = document.createElement("span"); name.className = "theme-name"; name.textContent = t.label;
    b.append(sample, name);
    b.onclick = () => { job.style = { theme: t.key }; styleChanged(true); };
    return b;
  }));
  renderModels();
  if (!$("#startView").hidden && !pending.video && !$("#link").value) {
    $("#cleanVoice").checked = !!settings.clean_voice; $("#fast").checked = !!settings.fast;
  }
}

function renderModels() {
  const card = (list, current, name, onPick) => list.map(m => {
    const l = document.createElement("label"); l.className = "model";
    const r = document.createElement("input"); r.type = "radio"; r.name = name; r.value = m.key; r.checked = m.key === current;
    r.onchange = () => onPick(m.key);
    const t = document.createElement("span");
    t.innerHTML = `<b></b><small></small>`;
    t.querySelector("b").textContent = m.label + (m.key === current && name !== "ef" ? " (in use)" : "");
    t.querySelector("small").textContent = m.about + ("ready" in m && !m.ready ? " The first time, it downloads (2–6 GB) and gets ready in a few minutes." : "");
    l.append(r, t); return l;
  });
  $("#listenModels").replaceChildren(...card(settings.listen_models, settings.listen_model, "lm", k => pickModel({ listen_model: k })));
  $("#claudeModels").replaceChildren(...card(settings.claude_models, settings.claude_model, "cm", k => pickModel({ claude_model: k })));
  const haiku = settings.claude_model.startsWith("claude-haiku");
  $("#efforts").replaceChildren(...card(settings.efforts, settings.claude_effort, "ef", k => pickModel({ claude_effort: k })));
  $$("#efforts input").forEach(i => { i.disabled = haiku; });
  $("#effortNote").textContent = haiku ? "Claude Haiku 4.5 has no effort setting; it always answers quickly." : "";
  $("#openSettings").textContent = "Models";
  $("#openSettings").title = `Listening: ${label(settings.listen_models, settings.listen_model)}. Claude: ${label(settings.claude_models, settings.claude_model)}.`;
}
const label = (list, key) => (list.find(m => m.key === key) || {}).label || key;
async function pickModel(ch) {
  try { settings = { ...settings, ...(await api("POST", "/api/settings", ch)) }; renderModels(); }
  catch (ex) { alert(ex.message); }
}
$("#openSettings").onclick = () => { renderModels(); $("#settings").showModal(); };

/* ---------------------------------------------------------- caption style */

// The job keeps a theme plus your changes to it; this is the full style the page and the burn use.
function fullStyle() {
  if (!settings) return null;
  const s = job && job.style || {};
  const theme = settings.themes.find(t => t.key === (s.theme || "classic"));
  return { ...settings.style_default, ...(theme ? theme.style : {}), ...s };
}
const hex6 = c => (c || "#000000").slice(0, 7);

function rowCss(st, px, isTh) {
  const stroke = px * st.outline, blur = px * st.shadow;
  return {
    fontFamily: `"${isTh ? st.th_font : st.zh_font}", "PingFang TC", "Sukhumvit Set", sans-serif`,
    fontSize: `${px}px`, fontWeight: st.bold ? "700" : "500",
    color: isTh ? st.th_color : st.color,
    webkitTextStroke: stroke ? `${2 * stroke}px ${st.outline_color}` : "0",
    paintOrder: "stroke fill",
    textShadow: blur ? `0 ${blur * 0.35}px ${blur}px rgba(0,0,0,.75)` : "none",
  };
}

function renderStylePanel() {
  const st = fullStyle();
  if (!st) return;
  $$(".theme").forEach(b => b.setAttribute("aria-checked", String(b.dataset.theme === (job.style?.theme || "classic"))));
  $$("[data-st]").forEach(el => {
    const k = el.dataset.st, v = st[k];
    if (el.type === "checkbox") el.checked = !!v;
    else if (el.type === "color") el.value = hex6(v);
    else el.value = v;
  });
  $$("[data-out]").forEach(o => { o.textContent = Math.round(st[o.dataset.out] * 100) + "%"; });
  $$("input[name=st-position]").forEach(r => { r.checked = r.value === st.position; });
  $$("input[name=st-order]").forEach(r => { r.checked = r.value === st.order; });
  $("#zhFont").style.fontFamily = `"${st.zh_font}"`;
  $("#thFont").style.fontFamily = `"${st.th_font}"`;
}

let styleTimer = null;
function styleChanged(now) {
  renderStylePanel(); current = undefined; tick(); placeOverlay();
  clearTimeout(styleTimer);
  styleTimer = setTimeout(saveStyleNow, now ? 0 : 600);
}
async function saveStyleNow(asDefault = false) {
  clearTimeout(styleTimer);
  if (!job) return;
  await api("POST", `/api/jobs/${job.id}/style`, { style: job.style || {}, as_default: asDefault });
  $("#styleSaved").textContent = asDefault ? "Saved as your default." : "";
}
function setStyle(k, v) { job.style = { ...(job.style || {}), [k]: v }; styleChanged(); }
$$("[data-st]").forEach(el => el.addEventListener("input", () => {
  const k = el.dataset.st;
  setStyle(k, el.type === "checkbox" ? el.checked : el.type === "range" ? +el.value
    : el.type === "color" && k === "box_color" ? el.value + "A0" : el.value);
}));
$$("input[name=st-position]").forEach(r => r.addEventListener("change", () => setStyle("position", r.value)));
$$("input[name=st-order]").forEach(r => r.addEventListener("change", () => setStyle("order", r.value)));
$("#styleDefault").onclick = () => saveStyleNow(true).then(() => loadSettings()).catch(ex => alert(ex.message));
$("#styleReset").onclick = () => { job.style = {}; styleChanged(true); };

/* ---------------------------------------------------------- people (caption colour per person) */

const PERSON_COLOURS = ["#FFE14D", "#9FD8FF", "#FFB3D1", "#B8F5A4", "#FFC48A", "#D7B8FF"];
// Edits look the person up by id each time: the list is replaced by the server's copy after every
// save, so holding on to the object from when the boxes were drawn would edit a stale copy.
const personById = id => (job?.speakers || []).find(p => p.id === id);
function renderPeople() {
  const people = job?.speakers || [];
  $("#peopleList").replaceChildren(...people.map((p, i) => {
    const li = document.createElement("li"); li.dataset.id = p.id;
    const c = document.createElement("input"); c.type = "color"; c.value = hex6(p.color); c.setAttribute("aria-label", "Colour");
    const n = document.createElement("input"); n.className = "field"; n.value = p.name; n.placeholder = `Person ${i + 1} (e.g. Milk)`;
    n.setAttribute("aria-label", "Name");
    const x = document.createElement("button"); x.type = "button"; x.className = "ghost"; x.textContent = "Remove";
    c.addEventListener("input", () => { const q = personById(p.id); if (q) { q.color = c.value; peopleChanged(); } });
    n.addEventListener("input", () => { const q = personById(p.id); if (q) { q.name = n.value.trim(); peopleChanged(); } });
    x.onclick = () => { job.speakers = (job.speakers || []).filter(q => q.id !== p.id); peopleChanged(true); renderPeople(); };
    li.append(c, n, x); return li;
  }));
}
let peopleTimer = null;
// Show the change everywhere at once; save a moment later (typing and dragging the colour don't
// send a request per keystroke, and the boxes are never redrawn under your cursor).
function peopleChanged(now) {
  current = undefined; tick();
  $$(".line").forEach(li => paintWho(li, lines.find(l => l.id === +li.dataset.id)));
  renderBulk();
  clearTimeout(peopleTimer);
  peopleTimer = setTimeout(sendPeople, now ? 0 : 500);
}
async function sendPeople() {
  const sent = JSON.stringify(job.speakers || []);
  try {
    const j = await api("POST", `/api/jobs/${job.id}/speakers`, { speakers: job.speakers || [] });
    if (JSON.stringify(job.speakers || []) === sent) job.speakers = j.speakers;   // unless you changed more meanwhile
    if (j.lines_rev !== linesRev) { lines = await api("GET", `/api/jobs/${job.id}/lines`); linesRev = j.lines_rev; renderLines(); }
  } catch (ex) { alert(ex.message); }
}
$("#addPerson").onclick = () => {
  const people = job.speakers || [];
  people.push({ id: Math.random().toString(36).slice(2, 8), name: "", color: PERSON_COLOURS[people.length % PERSON_COLOURS.length] });
  job.speakers = people; renderPeople(); peopleChanged(true);
  setTimeout(() => $("#peopleList li:last-child .field")?.focus(), 50);
};

/* ---------------------------------------------------------- many lines at once */

const picked = new Set();
let lastPick = null;
function renderBulk() {
  $$(".line").forEach(li => {
    const on = picked.has(+li.dataset.id);
    li.classList.toggle("picked", on); $(".pick", li).checked = on;
  });
  const n = picked.size, people = job?.speakers || [];
  $("#bulkbar").hidden = n === 0;
  $("#selCount").textContent = `${n} line${n === 1 ? "" : "s"} ticked`;
  const keep = $("#bulkWho").value;
  $("#bulkWho").replaceChildren(new Option("Nobody (no colour)", ""), ...people.map((p, i) => new Option(p.name || `Person ${i + 1}`, p.id)));
  if ([...$("#bulkWho").options].some(o => o.value === keep)) $("#bulkWho").value = keep;
  else if (people[0]) $("#bulkWho").value = people[0].id;
  $("#fixbar").classList.toggle("lifted", n > 0);
}
$("#bulkAssign").onclick = async () => {
  if (!(job.speakers || []).length && $("#bulkWho").value === "") {
    $("#stylePanel").open = true; $("#addPerson").scrollIntoView({ block: "center" });
    alert("Add the people first (Caption style → People)."); return;
  }
  try {
    await api("POST", `/api/jobs/${job.id}/assign`, { ids: [...picked], speaker: $("#bulkWho").value });
    picked.clear();
    lines = await api("GET", `/api/jobs/${job.id}/lines`); linesRev = -1; renderLines();
  } catch (ex) { alert(ex.message); }
};
$("#bulkClear").onclick = () => { picked.clear(); renderBulk(); };
$("#recogniseVoices").onclick = async () => {
  try { await api("POST", `/api/jobs/${job.id}/recognise-voices`); refresh(job.id); } catch (ex) { alert(ex.message); }
};
$("#guessWho").onclick = async () => {
  try { await api("POST", `/api/jobs/${job.id}/guess-speakers`); refresh(job.id); } catch (ex) { alert(ex.message); }
};

function paintWho(li, l) {
  const sel = $(".who", li), people = job?.speakers || [];
  if (!l) return;
  sel.hidden = !people.length;
  sel.replaceChildren(new Option("—", ""), ...people.map((p, i) => new Option(p.name || `Person ${i + 1}`, p.id)));
  sel.value = l.speaker || "";
  const p = people.find(x => x.id === l.speaker);
  sel.style.setProperty("--who", p ? p.color : "transparent");
  sel.classList.toggle("set", !!p);
  sel.classList.toggle("guess", !!(p && l.speaker_guess));
  sel.title = !p || !l.speaker_guess ? "" : l.speaker_guess === "voice" ? "Recognised by voice: change it if it's wrong" : "Claude's guess from the words: change it if it's wrong";
}

/* ---------------------------------------------------------- video + overlay */

let current = null, touches = [], touchesRev = -1, selTouch = null;
function linesAt(t) {
  // lines can overlap when two people talk at once: every line covering t, earliest first
  let lo = 0, hi = lines.length - 1, best = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (lines[mid].start <= t) { best = mid; lo = mid + 1; } else hi = mid - 1;
  }
  const on = [];
  for (let i = best; i >= 0 && i > best - 8; i--) if (t <= lines[i].end) on.unshift(lines[i]);
  return on;
}
function tick() {
  const t = video.currentTime;
  $$(".now-t").forEach(x => { x.textContent = fmtTime(t); });
  const on = lines.length ? linesAt(t) : [];
  const key = on.map(x => x.id).join(",");
  if (key !== current) {
    current = key;
    $$(".line.now").forEach(x => x.classList.remove("now"));
    drawCaption(on);
    on.forEach(x => $(`.line[data-id="${x.id}"]`)?.classList.add("now"));
    const l = on[on.length - 1];
    if (l) {
      const li = $(`.line[data-id="${l.id}"]`);
      if (li) {
        if ($("#follow").checked && !editing() && !video.paused) {
          const r = li.getBoundingClientRect();
          if (r.top < 110 || r.bottom > innerHeight - 80) li.scrollIntoView({ block: "center", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
        }
      }
    }
  }
  drawTouches(t);
}
function loop() { tick(); if (!video.paused) requestAnimationFrame(loop); }
video.addEventListener("play", loop);
video.addEventListener("seeked", tick);
video.addEventListener("timeupdate", tick);
$$("input[name=show]").forEach(r => r.addEventListener("change", () => { current = undefined; tick(); }));
// What's shown on the video follows what will be burned in.
$$("input[name=burn]").forEach(r => r.addEventListener("change", () => {
  const v = r.value === "none" ? "both" : r.value;
  $(`input[name=show][value="${v}"]`).checked = true; current = undefined; tick();
}));

// The picture inside the player (letterboxing aside), in px.
let frame = { left: 0, top: 0, w: 0, h: 0, scale: 1, vw: 1920, vh: 1080 };
function placeOverlay() {
  const vw = video.videoWidth || job?.media?.width, vh = video.videoHeight || job?.media?.height;
  const box = $("#player").getBoundingClientRect();
  if (!vw || !vh || !box.width) return;
  const vh_px = video.clientHeight || box.height;
  const scale = Math.min(box.width / vw, vh_px / vh);
  frame = { left: (box.width - vw * scale) / 2, top: (vh_px - vh * scale) / 2, w: vw * scale, h: vh * scale, scale, vw, vh };
  const ov = $("#overlay");
  ov.style.left = `${frame.left + frame.w * 0.06}px`;
  ov.style.width = `${frame.w * 0.88}px`;
  const st = fullStyle();
  if (!st) return;
  if (st.position === "top") {
    ov.style.top = `${frame.top + frame.h * 0.05}px`; ov.style.bottom = "auto";
  } else {
    const y = st.position === "custom" ? st.y : 0.94;
    ov.style.top = "auto"; ov.style.bottom = `${box.height - (frame.top + frame.h * y)}px`;
  }
  ov.classList.toggle("draggable", st.position === "custom");
  current = undefined; tick();
}
video.addEventListener("loadedmetadata", placeOverlay);
new ResizeObserver(placeOverlay).observe($("#player"));

function drawCaption(on) {
  const st = fullStyle(), boxEl = $("#ovBox");
  boxEl.replaceChildren(); boxEl.style.background = "none"; boxEl.style.padding = "0";
  if (!on.length || !st) return;
  const show = $("input[name=show]:checked").value;
  const zhPx = Math.min(frame.vw, frame.vh) * frame.scale * 0.058 * st.size;
  const thPx = show === "both" ? zhPx * st.th_scale : zhPx;
  const colour = id => ((job.speakers || []).find(p => p.id === id) || {}).color;
  const rows = [];
  for (const l of on) {
    const th = l.kind === "sound" ? "" : (l.th || ""), zh = l.zh || "", own = colour(l.speaker);
    const pair = [];
    if (show !== "zh" && th) pair.push([th, thPx, true]);
    if (show !== "th" && zh) pair.push([zh, zhPx, false]);
    if (st.order === "zh_above") pair.reverse();
    pair.forEach(r => rows.push([...r, own]));
  }
  rows.forEach(([text, px, isTh, own], i) => {
    const el = document.createElement("div");
    el.className = "ov-row"; el.textContent = text;
    Object.assign(el.style, rowCss(st, px, isTh && show === "both"), { marginTop: i ? `${zhPx * 0.12}px` : "0" });
    if (own) el.style.color = own;
    boxEl.append(el);
  });
  if (st.box && rows.length) Object.assign(boxEl.style, { background: st.box_color, padding: `${zhPx * 0.19}px ${zhPx * 0.32}px`, borderRadius: `${zhPx * 0.25}px` });
}

// drag the captions (Where: Drag it)
$("#ovBox").addEventListener("pointerdown", e => {
  const st = fullStyle();
  if (!st || st.position !== "custom") return;
  e.preventDefault(); video.pause();
  const box = $("#player").getBoundingClientRect(), el = $("#ovBox");
  el.setPointerCapture(e.pointerId);
  const move = ev => {
    const y = (ev.clientY - box.top - frame.top + el.offsetHeight / 2) / frame.h;
    job.style = { ...(job.style || {}), y: Math.max(0.1, Math.min(0.99, Math.round(y * 1000) / 1000)) };
    placeOverlay();
  };
  el.onpointermove = move;
  el.onpointerup = () => { el.onpointermove = null; styleChanged(); };
});

/* ---------------------------------------------------------- emoji and notes (touches) */

const EMOJI = ["💗", "💕", "🥰", "😍", "😳", "🤭", "😂", "🤣", "😅", "😭", "🥺", "😤", "🙈", "👀", "✨", "🔥", "💦", "💢", "🎉", "🫶", "💋", "🌸", "⭐", "🐱",
  "(臉紅)", "(偷笑)", "(害羞)", "(尷尬)", "(無奈)", "(心動)", "(噗)", "(竊喜)", "(撒嬌)", "(吃醋)"];
$("#emojiPick").replaceChildren(...EMOJI.map(e => {
  const b = document.createElement("button"); b.type = "button"; b.textContent = e;
  b.onclick = () => { const i = $("#teText"); i.value += e; i.dispatchEvent(new Event("input")); };
  return b;
}));

async function loadTouches() {
  touches = await api("GET", `/api/jobs/${job.id}/touches`);
  touchesRev = job.touches_rev || 0;
  renderTouchList(); drawTouches(video.currentTime, true);
}
function touchPx(t) {
  const st = fullStyle();
  return Math.min(frame.vw, frame.vh) * frame.scale * 0.058 * (st ? st.size : 1) * (t.size || 1.3);
}
let shownTouches = "";
function drawTouches(time, force) {
  const on = touches.filter(t => (t.start <= time && time < t.end) || t.id === selTouch);
  const key = on.map(t => t.id + JSON.stringify(t)).join("|") + frame.w + JSON.stringify(fullStyle());
  if (key === shownTouches && !force) return;
  shownTouches = key;
  const st = fullStyle() || {};
  $("#touchLayer").replaceChildren(...on.map(t => {
    const el = document.createElement("div");
    const px = touchPx(t);
    el.className = "touch" + (t.kind === "bubble" ? " bubble" : "") + (t.pending ? " pending" : "") + (t.id === selTouch ? " sel" : "");
    el.textContent = t.text;
    el.dataset.id = t.id;
    Object.assign(el.style, {
      left: `${frame.left + t.x * frame.w}px`, top: `${frame.top + t.y * frame.h}px`, fontSize: `${px}px`,
      fontFamily: `"${t.font || st.zh_font}", "PingFang TC", sans-serif`,
    });
    if (t.kind === "bubble") Object.assign(el.style, { padding: `${px * 0.2}px ${px * 0.35}px`, borderRadius: `${px * 0.6}px` });
    else Object.assign(el.style, { color: t.color || "#fff", webkitTextStroke: `${px * 0.2}px ${t.outline_color || "#F06A9F"}`, paintOrder: "stroke fill" });
    el.onpointerdown = e => dragTouch(e, t, el);
    return el;
  }));
}
function dragTouch(e, t, el) {
  e.preventDefault(); video.pause(); selectTouch(t.id);
  const box = $("#player").getBoundingClientRect();
  el.setPointerCapture(e.pointerId);
  let moved = false;
  el.onpointermove = ev => {
    moved = true;
    t.x = Math.max(0.02, Math.min(0.98, (ev.clientX - box.left - frame.left) / frame.w));
    t.y = Math.max(0.02, Math.min(0.98, (ev.clientY - box.top - frame.top) / frame.h));
    el.style.left = `${frame.left + t.x * frame.w}px`; el.style.top = `${frame.top + t.y * frame.h}px`;
  };
  el.onpointerup = () => { el.onpointermove = null; if (moved) patchTouch(t, { x: t.x, y: t.y }); };
}
let touchTimer = null;
function patchTouch(t, ch, later) {
  Object.assign(t, ch);
  drawTouches(video.currentTime, true); renderTouchList();
  clearTimeout(touchTimer);
  const send = () => api("PATCH", `/api/jobs/${job.id}/touches/${t.id}`, ch).catch(ex => alert(ex.message));
  if (later) touchTimer = setTimeout(send, 500); else send();
}
function renderTouchList() {
  $("#touchCount").textContent = touches.length || "";
  const pend = touches.filter(t => t.pending).length;
  $("#touchList").replaceChildren(...touches.map(t => {
    const li = document.createElement("li");
    li.className = (t.pending ? "pending" : "") + (t.id === selTouch ? " sel" : "");
    const tm = document.createElement("button"); tm.type = "button"; tm.className = "tt"; tm.textContent = fmtTime(t.start);
    tm.onclick = () => { video.currentTime = t.start + 0.01; video.pause(); selectTouch(t.id); };
    const tx = document.createElement("span"); tx.className = "tx"; tx.textContent = t.text;
    if (t.why) tx.title = t.why;
    li.append(tm, tx);
    if (t.pending) {
      const keep = document.createElement("button"); keep.type = "button"; keep.textContent = "Keep";
      keep.onclick = () => patchTouch(t, { pending: false });
      li.append(keep);
    }
    const ed = document.createElement("button"); ed.type = "button"; ed.textContent = "Edit";
    ed.onclick = () => { video.currentTime = t.start + 0.01; video.pause(); selectTouch(t.id); };
    const del = document.createElement("button"); del.type = "button"; del.textContent = "Remove";
    del.onclick = () => removeTouch(t);
    li.append(ed, del);
    if (t.why && t.pending) { const w = document.createElement("small"); w.textContent = t.why; li.append(w); }
    return li;
  }));
  if (pend) {
    const li = document.createElement("li"); li.className = "all";
    const k = document.createElement("button"); k.type = "button"; k.textContent = `Keep all ${pend} suggestions`;
    k.onclick = () => touches.filter(t => t.pending).forEach(t => patchTouch(t, { pending: false }));
    li.append(k); $("#touchList").prepend(li);
  }
}
async function removeTouch(t) {
  await api("DELETE", `/api/jobs/${job.id}/touches/${t.id}`).catch(ex => alert(ex.message));
  touches = touches.filter(x => x.id !== t.id);
  if (selTouch === t.id) selectTouch(null);
  renderTouchList(); drawTouches(video.currentTime, true);
}
function selectTouch(id) {
  selTouch = id;
  const t = touches.find(x => x.id === id);
  $("#touchEdit").hidden = !t;
  if (t) {
    $("#touchPanel").open = true;
    $("#teText").value = t.text;
    $("#teSize").value = t.size || 1.3; $("#teSizeOut").textContent = Math.round((t.size || 1.3) * 100) + "%";
    const d = Math.round((t.end - t.start) * 2) / 2; $("#teDur").value = d; $("#teDurOut").textContent = d + "s";
    $$("input[name=te-kind]").forEach(r => { r.checked = r.value === (t.kind || "plain"); });
    $("#teColor").value = hex6(t.color || "#FFFFFF"); $("#teOutline").value = hex6(t.outline_color || "#F06A9F");
  }
  renderTouchList(); drawTouches(video.currentTime, true);
}
const selT = () => touches.find(x => x.id === selTouch);
$("#teText").addEventListener("input", () => { const t = selT(); if (t && $("#teText").value.trim()) patchTouch(t, { text: $("#teText").value }, true); });
$("#teSize").addEventListener("input", () => { const t = selT(); $("#teSizeOut").textContent = Math.round($("#teSize").value * 100) + "%"; if (t) patchTouch(t, { size: +$("#teSize").value }, true); });
$("#teDur").addEventListener("input", () => { const t = selT(); $("#teDurOut").textContent = $("#teDur").value + "s"; if (t) patchTouch(t, { end: t.start + +$("#teDur").value }, true); });
$$("input[name=te-kind]").forEach(r => r.addEventListener("change", () => { const t = selT(); if (t) patchTouch(t, { kind: r.value }); }));
$("#teColor").addEventListener("input", () => { const t = selT(); if (t) patchTouch(t, { color: $("#teColor").value }, true); });
$("#teOutline").addEventListener("input", () => { const t = selT(); if (t) patchTouch(t, { outline_color: $("#teOutline").value }, true); });
$("#teStartHere").onclick = () => { const t = selT(); if (t) { const d = t.end - t.start; patchTouch(t, { start: video.currentTime, end: video.currentTime + d }); } };
$("#teDelete").onclick = () => { const t = selT(); if (t) removeTouch(t); };
$("#teDone").onclick = () => selectTouch(null);

$("#addTouchHere").onclick = async () => {
  video.pause();
  const t0 = video.currentTime;
  try {
    const t = await api("POST", `/api/jobs/${job.id}/touches`, { start: t0, end: t0 + 2.5, text: "💗", x: 0.8, y: 0.22 });
    touches.push(t); touches.sort((a, b) => a.start - b.start);
    selectTouch(t.id); $("#teText").select(); $("#teText").focus();
  } catch (ex) { alert(ex.message); }
};
$("#suggestTouches").onclick = async () => {
  try { await api("POST", `/api/jobs/${job.id}/touches/suggest`); refresh(job.id); } catch (ex) { alert(ex.message); }
};

/* ---------------------------------------------------------- captions you add, stretches you mark */

$("#addLineHere").onclick = async () => {
  video.pause();
  try {
    const l = await api("POST", `/api/jobs/${job.id}/lines`, { start: video.currentTime });
    lines = await api("GET", `/api/jobs/${job.id}/lines`); linesRev = -1; renderLines();
    const el = $(`.line[data-id="${l.id}"] .zh`);
    if (el) { el.scrollIntoView({ block: "center" }); el.focus(); }
  } catch (ex) { alert(ex.message); }
};

const range = { from: null, to: null };
function renderRange() {
  const f = range.from, t = range.to;
  $("#rangeT").textContent = `${f === null ? "–" : fmtTime(f)}  to  ${t === null ? "–" : fmtTime(t)}`;
  $("#rangeGo").disabled = f === null || t === null || t - f < 0.5 || !!job?.busy;
  $$(".line").forEach(li => {
    const l = lines.find(x => x.id === +li.dataset.id);
    li.classList.toggle("in-range", !$("#rangeBox").hidden && f !== null && t !== null && l && l.end > f && l.start < t);
  });
}
$("#markRange").onclick = () => {
  const box = $("#rangeBox"); box.hidden = !box.hidden;
  if (!box.hidden) { range.from = range.from ?? video.currentTime; $("#rangeNote").focus(); }
  renderRange();
};
$("#rangeFrom").onclick = () => { range.from = video.currentTime; if (range.to !== null && range.to < range.from) range.to = null; renderRange(); };
$("#rangeTo").onclick = () => { range.to = video.currentTime; if (range.from !== null && range.to < range.from) [range.from, range.to] = [range.to, range.from]; renderRange(); };
$("#rangeCancel").onclick = () => { $("#rangeBox").hidden = true; range.from = range.to = null; renderRange(); };
$("#rangePlay").onclick = () => {
  if (range.from === null) return;
  video.currentTime = range.from; video.play();
  const stop = () => { if (range.to !== null && video.currentTime >= range.to) { video.pause(); video.removeEventListener("timeupdate", stop); } };
  video.addEventListener("timeupdate", stop);
};
$("#rangeGo").onclick = async () => {
  try {
    await api("POST", `/api/jobs/${job.id}/review`, { start: range.from, end: range.to, note: $("#rangeNote").value.trim() });
    $("#rangeBox").hidden = true; $("#rangeNote").value = ""; range.from = range.to = null; renderRange();
    refresh(job.id);
  } catch (ex) { alert(ex.message); }
};

/* ============================================================ memory */

async function loadMemoryCount() {
  try {
    const m = await api("GET", "/api/memory");
    const n = m.names.length + m.words.length + m.rules.length + (m.people || []).length;
    $("#memCount").textContent = n || "";
    return m;
  } catch { return null; }
}
async function renderMemory() {
  const m = await loadMemoryCount();
  if (!m) return;
  $('[data-mem="people"]').replaceChildren(...(m.people || []).map(p => {
    const li = document.createElement("li");
    const c = document.createElement("input"); c.type = "color"; c.value = hex6(p.color || "#FFFFFF"); c.setAttribute("aria-label", `${p.name}'s colour`);
    const n = document.createElement("input"); n.className = "field mname"; n.value = p.name; n.setAttribute("aria-label", "Name");
    const v = document.createElement("span"); v.className = "mvoice";
    v.textContent = p.voice ? `voice learned from ${p.voice_n} line${p.voice_n === 1 ? "" : "s"}` : "voice not learned yet";
    const save = ch => api("PATCH", `/api/memory/people/${p.id}`, ch).then(renderMemory).catch(ex => alert(ex.message));
    c.onchange = () => save({ color: c.value });
    n.onchange = () => n.value.trim() && save({ name: n.value.trim() });
    li.append(c, n, v);
    if (p.voice) {
      const f = document.createElement("button"); f.type = "button"; f.textContent = "Forget voice";
      f.onclick = async () => {
        if (!confirm(`Forget ${p.name}'s voice? Lines won't be coloured for ${p.name} automatically until you teach it again.`)) return;
        await api("POST", `/api/memory/people/${p.id}/forget-voice`); renderMemory();
      };
      li.append(f);
    }
    const x = document.createElement("button"); x.type = "button"; x.textContent = "Remove";
    x.onclick = async () => {
      if (!confirm(`Remove ${p.name}? New videos won't start with them, and their voice is forgotten. Videos you already made keep their colours.`)) return;
      await api("DELETE", `/api/memory/people/${p.id}`); renderMemory();
    };
    li.append(x);
    return li;
  }));
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
loadSettings().catch(() => {});
route();
setInterval(() => { if (!$("#startView").hidden) loadJobList(); }, 5000);
