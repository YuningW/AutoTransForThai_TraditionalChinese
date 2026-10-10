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
  reviewing: "Listening again to a stretch", touches: "Picking moments for emoji", speakers: "Working out who's talking", filling: "Filling in skipped talking",
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
  const about = $("#about").value.trim(), clean = $("#cleanVoice").checked, fast = $("#fast").checked, vsubs = $("#videoSubs").checked, scheck = vsubs && $("#subsCheck").checked;
  try {
    let job;
    if (pending.video) {
      const f = new FormData();
      f.append("file", pending.video); f.append("about", about); f.append("clean_voice", clean); f.append("fast", fast); f.append("video_subs", vsubs); f.append("subs_check", scheck);
      job = await uploadVideo(f, p => { go.textContent = `Copying the video… ${Math.round(p * 100)}%`; });
    } else {
      go.textContent = "Starting…";
      job = await api("POST", "/api/jobs", { url: $("#link").value.trim(), about, clean_voice: clean, fast, video_subs: vsubs, subs_check: scheck });
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
  if (settings) { $("#cleanVoice").checked = settings.clean_voice = $("#cleanVoice").checked; settings.fast = $("#fast").checked;
    settings.video_subs = $("#videoSubs").checked; settings.subs_check = $("#subsCheck").checked; }
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
  $("#lines").replaceChildren(); $("#touchEdit").hidden = true; $("#brandEdit").hidden = true; $("#rangeBox").hidden = true;
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
    if (job && job.id === j.id) { j.style = job.style; j.speakers = job.speakers; j.reel = job.reel; }   // the page owns these while you edit
    job = j;
    renderJob();
    if (first) { renderStylePanel(); renderPeople(); placeOverlay(); picked.clear(); renderSavedLogos(); loadShape(); }
    else if (job.speakers && !document.activeElement?.closest?.("#peopleList")) { /* keep the page's copy */ }
    if ((j.touches_rev || 0) !== touchesRev) await loadTouches();
    if (firstVideo && j.media?.duration) { video.src = `/api/jobs/${jid}/video`; loadWave(jid); }
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
  $("#fillSkipped").disabled = noVideo || !!job.busy || !(job.counts && job.counts.lines);
  $("#retime").disabled = noVideo || !!job.busy || !(job.counts && job.counts.lines);
  $("#weakSpots").disabled = noVideo || !!job.busy || !(job.counts && job.counts.lines);
  $("#suggestTouches").disabled = !!job.busy || !(job.counts && job.counts.lines);
  if (!$("#rangeBox").hidden) renderRange();
  const music = !!job.options?.clean_voice, done = job.state === "ready" && !job.busy && job.counts?.lines;
  $("#againBtn").hidden = !done;
  $("#againText").textContent = music ? "It listened with the background music removed; try the original sound"
    : "Background music drowning out words? Take it out and listen again";
  $("#againLabel").textContent = music ? "Listen again without removing music" : "Listen again with the music removed";
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
    const n = (h.pictures || []).length;
    s.innerHTML = `<b></b> <small></small>`;
    s.querySelector("b").textContent = h.label;
    s.querySelector("small").textContent = `${n ? `${n} picture${n > 1 ? "s" : ""}` : ""}${h.used ? "" : `${n ? ", " : ""}not used yet`}`;
    // what it is: you can always correct it (it's used that way from the next redo)
    const kind = document.createElement("select"); kind.className = "field helper-kind"; kind.setAttribute("aria-label", `What “${h.label}” is`);
    kind.append(new Option("Thai: what they say", "original"), new Option("A translation (English, Chinese…)", "translation"));
    if (h.kind === "auto") kind.prepend(new Option("Reading the pictures…", "auto"));
    kind.value = h.kind;
    kind.onchange = async () => {
      try { job = { ...job, ...(await api("PATCH", `/api/jobs/${job.id}/helpers/${h.id}`, { kind: kind.value })) }; renderJob(); toast("Changed: press Redo the captions with this help to use it"); }
      catch (ex) { alert(ex.message); }
    };
    const x = document.createElement("button"); x.type = "button"; x.textContent = "Remove";
    x.onclick = async () => { await api("DELETE", `/api/jobs/${job.id}/helpers/${h.id}`); refresh(job.id); };
    li.append(s, kind, x); return li;
  }));
  $("#redoAll").hidden = !hs.some(h => !h.used) || !!job.busy || !(job.counts && job.counts.lines);
  $("#findVideoSubs").disabled = !!job.busy || !job.media?.duration;

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
  const looks = new Set($$(".line .lookbox:not([hidden])", ol).map(b => +b.closest(".line").dataset.id));
  ol.replaceChildren(...lines.map(l => lineEl(l, open.has(l.id), looks.has(l.id))));
  if (!$("#findBox").hidden && $("#findText").value) find.hits.forEach(l => $(`.line[data-id="${l.id}"]`)?.classList.add("match"));
  updateFixbar();
  updateTooFast();
  if (peopleOn() && !pv.on) showPeoplePick();       // the list of parts follows the captions
  for (const id of [...picked]) if (!lines.some(l => l.id === id)) picked.delete(id);
  renderBulk();
  current = null; tick();
}

function lineEl(l, flagOpen, lookOpen) {
  const li = tpl.content.firstElementChild.cloneNode(true);
  li.dataset.id = l.id;
  const unsure = l.status === "auto" && l.kind === "speech" && l.conf < UNSURE;
  li.classList.toggle("unsure", unsure);
  li.classList.toggle("fixed", l.status === "fixed");
  li.classList.toggle("edited", l.status === "edited");
  li.classList.toggle("flagged", !!l.flag);
  li.classList.add(l.kind || "speech");
  $(".time", li).textContent = fmtTime(l.start);
  const sp = readSpeed(l);
  $(".speed", li).hidden = !sp;
  if (sp) { $(".speed", li).textContent = sp.label; $(".speed", li).title = sp.why; }
  $(".time", li).title = `${fmtTime(l.start)} – ${fmtTime(l.end)}. Play from here`;
  paintWho(li, l);
  fillPainted($(".th", li), l.th, l.paint, "th");
  fillPainted($(".zh", li), l.zh || "", l.paint, "zh");
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
  fillLook(li, l, lookOpen);
  return li;
}

/* ---------------------------------------------------------- one line's own look */

function fillLook(li, l, open) {
  const look = l.look || {}, st = fullStyle() || {}, box = $(".lookbox", li);
  li.classList.toggle("has-look", Object.keys(look).length > 0);
  box.hidden = !open;
  $(".lookbtn", li).setAttribute("aria-expanded", String(!!open));
  $$(".seg", box).forEach(seg => $$("button", seg).forEach(b => {
    b.setAttribute("role", "radio"); b.setAttribute("aria-checked", String((look[seg.dataset.k] || "") === b.dataset.v));
  }));
  $(".look-size", box).value = look.size || 1;
  $(".look-size-out", box).textContent = `${Math.round((look.size || 1) * 100)}%`;
  $(".look-color", box).value = hex6(look.color || ownColour(l) || st.color);
  $(".look-color-reset", box).hidden = !look.color;
  $(".look-bold", box).checked = look.bold ?? !!st.bold;
  if (open) fontMenu($(".look-font", box), look.font, ownFont(l) ? "Like this person's" : "Like the rest");
  const n = [...picked].filter(id => id !== l.id).length;
  $(".look-apply", box).hidden = !n || !Object.keys(look).length;
  $(".look-apply", box).textContent = `Use this look on the ${n} ticked line${n === 1 ? "" : "s"}`;
}
const ownColour = l => ((job.speakers || []).find(p => p.id === l.speaker) || {}).color;
const ownFont = l => ((job.speakers || []).find(p => p.id === l.speaker) || {}).font;
// a font menu: "like the rest" first, then every Chinese caption font, each shown in itself
function fontMenu(sel, value, first) {
  const o0 = document.createElement("option"); o0.value = ""; o0.textContent = first;
  sel.replaceChildren(o0, ...(settings?.fonts?.zh || []).map(f => {
    const o = document.createElement("option"); o.value = f.family; o.textContent = f.label; o.style.fontFamily = `"${f.family}"`; return o;
  }));
  sel.value = value || "";
}

function setLook(l, changes, now = true) {
  const look = { ...(l.look || {}), ...changes };
  for (const k of Object.keys(look)) if (look[k] === "" || look[k] === null || look[k] === undefined) delete look[k];
  if (look.position === "custom" && look.y == null) {
    const st = fullStyle();
    look.y = st.position === "top" ? 0.2 : st.position === "custom" ? Math.max(0.2, st.y - 0.12) : 0.8;   // a little above the rest, so you see it move
  }
  if (look.position !== "custom") delete look.y;
  if (look.size && Math.abs(look.size - 1) < 0.01) delete look.size;
  l.look = look;
  const li = $(`.line[data-id="${l.id}"]`);
  if (li) fillLook(li, l, !$(".lookbox", li).hidden);
  current = undefined; tick();
  if (now) patch(l, { look });
}

// Too fast to read: Netflix's limit for Traditional Chinese is 9 characters a second; and a line needs time on screen
const MAX_CPS = 9, MIN_SECONDS = 0.7;
function readSpeed(l) {
  const zh = (l.zh || "").replace(/[\s，。、！？：；…（）「」『』,.!?:;()"'~～-]/g, "")
    .replace(/[A-Za-z0-9]+/g, w => "x".repeat(Math.ceil(w.length / 2)));      // a Latin word reads faster than as many 字
  const dur = l.end - l.start;
  if (!zh || l.kind === "sound" || (l.look && l.look.show === "none")) return null;
  if (dur < MIN_SECONDS && zh.length >= 3) return { label: `${dur.toFixed(1)} s`, why: `Only ${dur.toFixed(1)} s on screen: too short to read. Make it longer on the timeline, or join it with the next line (M).` };
  const cps = zh.length / dur;
  if (cps > MAX_CPS) return { label: `${cps.toFixed(0)}字/秒`, why: `${zh.length} characters in ${dur.toFixed(1)} s is ${cps.toFixed(1)} a second; most people read up to ${MAX_CPS}. Make it longer on the timeline, or shorten the Chinese.` };
  return null;
}
let fastAt = -1;
function updateTooFast() {
  const n = lines.filter(readSpeed).length, b = $("#tooFast");
  b.hidden = !n;
  b.textContent = `${n} too fast to read`;
}
$("#tooFast").onclick = () => {
  const fast = lines.filter(readSpeed);
  if (!fast.length) return;
  const t = video.currentTime, next = fast.find(l => l.start > t + 0.05) || fast[0];
  video.currentTime = next.start + 0.01;
  $(`.line[data-id="${next.id}"]`)?.scrollIntoView({ block: "center" });
};

/* ---------------------------------------------------------- a few words in their own colour */

// Same as style.py paint_ranges: a mark is {f: "zh"|"th", text, n: which occurrence, color}
function paintRanges(text, marks, field) {
  const out = [];
  for (const m of marks || []) {
    if (m.f !== field || !m.text) continue;
    let at = -1;
    for (let k = 0; k <= (m.n || 0); k++) { at = text.indexOf(m.text, at + 1); if (at < 0) break; }
    if (at >= 0) out.push([at, at + m.text.length, m.color]);
  }
  return out.sort((a, b) => a[0] - b[0]);
}
function fillPainted(el, text, marks, field) {
  const ranges = paintRanges(text || "", marks, field);
  if (!ranges.length) { el.textContent = text || ""; return; }
  const bits = []; let at = 0;
  for (const [a, b, c] of ranges) {
    if (a < at) continue;
    if (a > at) bits.push(document.createTextNode(text.slice(at, a)));
    const s = document.createElement("span"); s.className = "painted"; s.style.color = c; s.textContent = text.slice(a, b);
    bits.push(s); at = b;
  }
  if (at < text.length) bits.push(document.createTextNode(text.slice(at)));
  el.replaceChildren(...bits);
}

// Select words in a line's Thai or Chinese: a small bar offers each person's colour, any colour, or clear.
const paintSel = { l: null, field: null, text: "", n: 0, a: 0, b: 0 };
function showPaintBar() {
  const sel = getSelection(), bar = $("#paintBar");
  if (!sel.rangeCount || sel.isCollapsed) { bar.hidden = true; return; }
  const r = sel.getRangeAt(0), field = r.commonAncestorContainer.nodeType === 1 ? r.commonAncestorContainer.closest?.(".th, .zh")
    : r.commonAncestorContainer.parentElement?.closest(".th, .zh");
  const l = field && lineOf(field);
  const picked = sel.toString();
  if (!l || !picked.trim()) { bar.hidden = true; return; }
  const pre = document.createRange(); pre.setStart(field, 0); pre.setEnd(r.startContainer, r.startOffset);
  const a = pre.toString().length, all = field.textContent;
  let n = 0, at = all.indexOf(picked);
  while (at >= 0 && at < a) { n++; at = all.indexOf(picked, at + 1); }
  Object.assign(paintSel, { l, field: field.classList.contains("th") ? "th" : "zh", text: picked, n, a, b: a + picked.length });
  const people = (job.speakers || []).filter(p => p.color);
  $("#paintPeople").replaceChildren(...people.map(p => {
    const b = document.createElement("button"); b.type = "button"; b.className = "paint-dot";
    b.style.background = p.color; b.title = `${p.name || "Person"}'s colour`; b.setAttribute("aria-label", b.title);
    b.dataset.color = p.color; return b;
  }));
  const box = r.getBoundingClientRect();
  bar.hidden = false;
  bar.style.left = `${Math.max(8, Math.min(innerWidth - bar.offsetWidth - 8, box.left + box.width / 2 - bar.offsetWidth / 2))}px`;
  bar.style.top = `${Math.max(8, box.top - bar.offsetHeight - 8)}px`;
}
function applyPaint(color) {
  const { l, field, text, n, a, b } = paintSel;
  if (!l) return;
  const txt = l[field] || "";
  const keep = (l.paint || []).filter(m => {     // marks that overlap the words you picked are replaced
    if (m.f !== field) return true;
    const [r] = paintRanges(txt, [m], field);
    return !r || r[1] <= a || r[0] >= b;
  });
  if (color) keep.push({ f: field, text, n, color });
  $("#paintBar").hidden = true;
  getSelection().removeAllRanges();
  document.activeElement?.blur?.();
  patch(l, { paint: keep });
}
document.addEventListener("selectionchange", () => {
  clearTimeout(paintSel.timer);
  paintSel.timer = setTimeout(showPaintBar, 120);
});
$("#paintBar").addEventListener("mousedown", e => { if (e.target.type !== "color") e.preventDefault(); });   // keep the selection
$("#paintBar").addEventListener("click", e => {
  const dot = e.target.closest(".paint-dot");
  if (dot) applyPaint(dot.dataset.color);
  else if (e.target.closest("#paintClear")) applyPaint(null);
});
$("#paintAny").addEventListener("change", e => applyPaint(e.target.value.toUpperCase()));

function esc(s) { return String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]); }
function lineOf(el) { const li = el.closest(".line"); return li && lines.find(l => l.id === +li.dataset.id); }

async function patch(l, changes) {
  try {
    const out = await api("PATCH", `/api/jobs/${job.id}/lines/${l.id}`, changes);
    Object.assign(l, out);
    linesRev = -1;           // the server bumped its revision; the next poll picks it up
    const li = $(`.line[data-id="${l.id}"]`);
    if (li && !editing()) li.replaceWith(lineEl(l, !$(".flagbox", li).hidden, !$(".lookbox", li).hidden));
    updateFixbar(); updateTooFast();
    if ("look" in changes || "paint" in changes || "start" in changes || "end" in changes) { current = undefined; tick(); }
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
  if (e.target.closest(".lookbtn")) {
    const li = e.target.closest(".line"), box = $(".lookbox", li);
    fillLook(li, l, box.hidden);
    if (!box.hidden) { video.pause(); video.currentTime = Math.min(l.end - 0.05, l.start + 0.3); }   // show the line on the video
    return;
  }
  const sb = e.target.closest(".lookbox .seg button");
  if (sb) { setLook(l, { [sb.closest(".seg").dataset.k]: sb.dataset.v }); video.pause(); video.currentTime = Math.min(l.end - 0.05, l.start + 0.3); return; }
  if (e.target.closest(".look-color-reset")) { setLook(l, { color: "" }); return; }
  if (e.target.closest(".cut-here")) { cutLine(l); return; }
  if (e.target.closest(".join-next")) { joinLine(l); return; }
  if (e.target.closest(".look-reset")) { setLook(l, {}, false); l.look = {}; patch(l, { look: {} }); return; }
  if (e.target.closest(".look-apply")) {
    const others = lines.filter(x => picked.has(x.id) && x.id !== l.id);
    Promise.all(others.map(x => { x.look = { ...l.look }; return patch(x, { look: x.look }); })).then(() => { current = undefined; tick(); });
    return;
  }
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
      showTab("peoplePanel"); $("#addPerson").scrollIntoView({ block: "center" });
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
  const l = lineOf(e.target);
  if (!l) return;
  if (e.target.classList.contains("who")) patch(l, { speaker: e.target.value });
  else if (e.target.classList.contains("look-size")) setLook(l, { size: +e.target.value });
  else if (e.target.classList.contains("look-color")) setLook(l, { color: e.target.value });
  else if (e.target.classList.contains("look-bold")) setLook(l, { bold: e.target.checked });
  else if (e.target.classList.contains("look-font")) setLook(l, { font: e.target.value });
});
ol.addEventListener("input", e => {             // see it on the video while you slide
  const l = lineOf(e.target);
  if (!l) return;
  if (e.target.classList.contains("look-size")) {
    setLook(l, { size: +e.target.value }, false);
    $(".look-size-out", e.target.closest(".lookbox")).textContent = `${Math.round(e.target.value * 100)}%`;
  } else if (e.target.classList.contains("look-color")) setLook(l, { color: e.target.value }, false);
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
  $("#flagCount").textContent = `${n} flagged`;
  $("#flagCount").title = "It listens again where needed, fixes them, and remembers what your notes teach it.";
  renderRail();
}

// Flagged lines down the right edge (the whole video, top to bottom): see where they are, click one to go there
function railBox() {
  const s = $(".script").getBoundingClientRect();
  const top = Math.max(s.top, 66) + 44, bottom = Math.min(innerHeight, s.bottom) - ($("#fixbar").hidden ? 12 : 64);
  return { left: s.right + 6, top, height: Math.max(60, bottom - top) };
}
function renderRail() {
  const rail = $("#flagRail"), flagged = lines.filter(l => l.flag), dur = video.duration || job?.media?.duration || 0;
  rail.hidden = !flagged.length || !dur || $("#jobView").hidden;
  if (rail.hidden) return;
  const b = railBox();
  Object.assign(rail.style, { left: `${Math.min(innerWidth - 16, b.left)}px`, top: `${b.top}px`, height: `${b.height}px` });
  $$("button", rail).forEach(x => x.remove());
  rail.append(...flagged.map(l => {
    const m = document.createElement("button"); m.type = "button";
    m.style.top = `${(l.start / dur) * 100}%`;
    m.title = `${fmtTime(l.start)} ⚑ ${l.note || l.flag}\n${l.zh || l.th}`;
    m.setAttribute("aria-label", `Flagged line at ${fmtTime(l.start)}`);
    m.onclick = () => goToLine(l);
    return m;
  }));
  railNowTick();
}
function railNowTick() {
  const dur = video.duration || job?.media?.duration;
  if (!$("#flagRail").hidden && dur) $("#railNow").style.top = `${(video.currentTime / dur) * 100}%`;
}
function goToLine(l) {
  video.pause(); video.currentTime = l.start + 0.01;
  const li = $(`.line[data-id="${l.id}"]`);
  if (li) { li.scrollIntoView({ block: "center" }); li.classList.add("jumped"); setTimeout(() => li.classList.remove("jumped"), 1200); }
}
function stepFlag(d) {                 // previous / next flagged line from where you are
  const f = lines.filter(l => l.flag).sort((a, b) => a.start - b.start);
  if (!f.length) return;
  const t = video.currentTime;
  const n = d > 0 ? (f.find(l => l.start > t + 0.05) || f[0]) : ([...f].reverse().find(l => l.start < t - 0.05) || f[f.length - 1]);
  goToLine(n);
  toast(`Flagged line ${f.indexOf(n) + 1} of ${f.length}`);
}
$("#clearFlags").onclick = async () => {
  const n = lines.filter(l => l.flag).length;
  if (!n || !confirm(`Take the flag off all ${n} line${n > 1 ? "s" : ""}? Their notes go too.`)) return;
  try {
    await api("POST", `/api/jobs/${job.id}/clear-flags`);
    await reloadLines(); toast(`Cleared ${n} flag${n > 1 ? "s" : ""}`);
  } catch (ex) { alert(ex.message); }
};
$("#flagPrev").onclick = () => stepFlag(-1);
$("#flagNext").onclick = () => stepFlag(1);
addEventListener("resize", renderRail);
addEventListener("scroll", () => { if (!$("#flagRail").hidden) renderRail(); }, { passive: true });
// Fixes can use their own Claude model and effort (e.g. Opus for a hard stretch while Models says Sonnet).
// One choice for both Fix a stretch and Fix flagged lines, remembered on this Mac; "" = as under Models.
function fixClaude() {
  try { return JSON.parse(localStorage.getItem("ac-fix-claude") || "{}"); } catch { return {}; }
}
function renderClaudePicks() {
  if (!settings) return;
  const now = fixClaude();
  const nameOf = k => (settings.claude_models.find(m => m.key === k) || {}).label || k;
  const effOf = k => (settings.efforts.find(e => e.key === k) || {}).label || k;
  $$("[data-claude-pick]").forEach(box => {
    const m = $("[data-pick=model]", box), e = $("[data-pick=effort]", box);
    m.replaceChildren(new Option(`${nameOf(settings.claude_model).replace("Claude ", "")} · as set`, ""),
      ...settings.claude_models.map(x => new Option(x.label.replace("Claude ", ""), x.key)));
    m.title = "Claude model for this fix. \"as set\" = the one under Models";
    e.title = "How hard Claude thinks for this fix. \"as set\" = the setting under Models";
    e.replaceChildren(new Option(`${effOf(settings.claude_effort || "auto")} · as set`, ""),
      ...settings.efforts.map(x => new Option(x.label, x.key)));
    m.value = now.model || ""; e.value = now.effort || "";
    m.onchange = e.onchange = () => {
      try { localStorage.setItem("ac-fix-claude", JSON.stringify({ model: m.value, effort: e.value })); } catch { /* fine */ }
      renderClaudePicks();
    };
  });
}
$("#fixNow").onclick = async () => {
  try { await api("POST", `/api/jobs/${job.id}/fix`, { model: fixClaude().model || null, effort: fixClaude().effort || null }); refresh(job.id); }
  catch (ex) { alert(ex.message); }
};
$("#findVideoSubs").onclick = async () => {
  try { await api("POST", `/api/jobs/${job.id}/video-subs`); refresh(job.id); } catch (ex) { alert(ex.message); }
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
    const part = partNow();
    if (part === false) return;
    if (clipsOn()) await saveReel();
    const srt = $$("input[name=srt]:checked").map(b => b.value);
    try { localStorage.setItem("ac-srt", JSON.stringify(srt)); } catch { /* fine */ }
    if (burn === "none" && !srt.length) { alert("Nothing to save: tick an SRT file or choose a video to burn."); return; }
    await api("POST", `/api/jobs/${job.id}/export`, { srt, burn, shape: shapeNow(), part });
    refresh(job.id);
  } catch (ex) { alert(ex.message); }
};

// Just a part of the video: from..to, marked with the playhead, typed, or the ticked lines' span
const part = { start: null, end: null };
function parseTime(s) {               // "1:23.4", "83.4", "1:02:03"
  const bits = String(s || "").trim().split(":").map(Number);
  if (!bits.length || bits.some(isNaN)) return null;
  return bits.reduce((t, x) => t * 60 + x, 0);
}
function partOn() { return $("input[name=part]:checked").value === "part"; }
function peopleOn() { return $("input[name=part]:checked").value === "people"; }
const whoPicked = new Set();
// the stretches where the ticked people talk, as the app would cut them (jobs.py _spans); you can then drop
// some or nudge their ends in the list (cuts), and that edited list is what's previewed and saved
const cuts = { key: "", list: [] };
function peopleSpans() {
  const raw = rawPeopleSpans(), key = raw.map(s => s.join("-")).join(",");
  if (key !== cuts.key) {
    cuts.key = key;
    const kept = raw.length ? cuts.restore : null;      // the parts as you left them last time
    if (kept) cuts.restore = null;
    cuts.list = raw.map(([a, b]) => {
      const k = kept && kept.find(([x, y]) => x < b && y > a);
      return kept ? (k ? { a: k[0], b: k[1], keep: true } : { a, b, keep: false }) : { a, b, keep: true };
    });
  }
  return cuts.list.filter(c => c.keep && c.b - c.a >= 0.3).map(c => [c.a, c.b]);
}
function renderCuts() {
  const full = video.duration || job?.media?.duration || 1e9;
  $("#cutList").replaceChildren(...cuts.list.map((c, i) => {
    const li = document.createElement("li"); li.classList.toggle("off", !c.keep); li.dataset.i = i;
    const keep = document.createElement("input"); keep.type = "checkbox"; keep.checked = c.keep; keep.setAttribute("aria-label", `Keep part ${i + 1}`);
    keep.onchange = () => { c.keep = keep.checked; showPeoplePick(); };
    const play = document.createElement("button"); play.type = "button"; play.textContent = "Play"; play.title = "Play this part";
    play.onclick = () => { stopPreview(false); pv.on = true; pv.spans = [[c.a, c.b]]; pv.i = 0; previewJump(); video.play(); };
    const t = document.createElement("span"); t.className = "cut-t";
    t.textContent = `${i + 1}. ${fmtTime(c.a)}–${fmtTime(c.b)}`;
    const said = lines.filter(l => l.end > c.a && l.start < c.b).map(l => l.zh || l.th).join(" ");
    const tx = document.createElement("span"); tx.className = "cut-text"; tx.textContent = said; tx.title = said;
    const nudge = (label, title, f) => { const b = document.createElement("button"); b.type = "button"; b.textContent = label; b.title = title; b.onclick = () => { f(); showPeoplePick(); }; return b; };
    const st = document.createElement("span"); st.className = "nudge";
    st.append("start", nudge("−", "Start half a second earlier", () => { c.a = Math.max(0, c.a - 0.5); }),
              nudge("+", "Start half a second later", () => { c.a = Math.min(c.b - 0.3, c.a + 0.5); }));
    const en = document.createElement("span"); en.className = "nudge";
    en.append("end", nudge("−", "End half a second earlier", () => { c.b = Math.max(c.a + 0.3, c.b - 0.5); }),
              nudge("+", "End half a second later", () => { c.b = Math.min(full, c.b + 0.5); }));
    li.append(keep, t, tx, st, en, play);
    return li;
  }));
}
function rawPeopleSpans() {
  const mine = lines.filter(l => whoPicked.has(l.speaker) && l.kind !== "sound").sort((a, b) => a.start - b.start), out = [];
  for (const l of mine) {
    const a = Math.max(0, l.start - 0.3), b = l.end + 0.5;
    if (out.length && a - out[out.length - 1][1] < 1.5) out[out.length - 1][1] = Math.max(out[out.length - 1][1], b);
    else out.push([a, b]);
  }
  return out;
}
function showPeoplePick() {
  showSizes();
  $("#peopleBox").hidden = !peopleOn();
  if (!peopleOn()) return;
  const people = (job.speakers || []).filter(p => p.name);
  if (!people.length) { $("#whoPicks").textContent = "Add people first (Caption style → People) and pick who says each line."; $("#whoLen").textContent = ""; return; }
  $("#whoPicks").replaceChildren(...people.map(p => {
    const lab = document.createElement("label"), box = document.createElement("input"), dot = document.createElement("i");
    box.type = "checkbox"; box.checked = whoPicked.has(p.id); dot.style.background = p.color;
    const n = lines.filter(l => l.speaker === p.id).length;
    box.onchange = () => { box.checked ? whoPicked.add(p.id) : whoPicked.delete(p.id); showPeoplePick(); };
    lab.append(box, dot, `${p.name} (${n} line${n === 1 ? "" : "s"})`);
    return lab;
  }));
  const sp = peopleSpans(), len = sp.reduce((s, [a, b]) => s + b - a, 0);
  const dropped = cuts.list.filter(c => !c.keep).length;
  $("#whoLen").textContent = sp.length ? `${sp.length} part${sp.length === 1 ? "" : "s"}, ${fmtTime(len).replace(/\.\d$/, "")} in all, joined into one video` +
    (dropped ? ` (${dropped} left out)` : "") + ". Untick a part to leave it out; − + move its start or end by half a second." : "Tick who to keep.";
  renderCuts();
  drawTimeline(video.currentTime, true);
}
function partNow() {                  // null: the whole video; false: not ready (says why)
  if (clipsOn()) {
    if (!reelSpans().length) { alert(starOnly() ? "No ★ clips yet: star the ones you want in the Clips tab, or turn off ★ only." : "Add clips first: open the Clips tab and press I where a scene starts, O where it ends."); return false; }
    return { reel: true, starred: starOnly() };
  }
  if (peopleOn()) {
    if (!whoPicked.size || !peopleSpans().length) { alert("Tick the people to keep (and at least one part). Their lines need to be marked as theirs (the chip on each line)."); return false; }
    return { people: [...whoPicked], spans: peopleSpans().map(([a, b]) => [Math.round(a * 1000) / 1000, Math.round(b * 1000) / 1000]) };
  }
  if (!partOn()) return null;
  if (part.start == null || part.end == null || part.end - part.start < 0.5) {
    alert("Choose the part to save: From here and To here (at least half a second)."); return false;
  }
  return { start: Math.round(part.start * 1000) / 1000, end: Math.round(part.end * 1000) / 1000 };
}
// how big the saved video will be, roughly: the bitrates are media.py SIZES (+ sound); full ≈ like the original
function savedSeconds() {
  const full = job?.media?.duration || 0;
  if (clipsOn()) return reelSpans().reduce((s, [a, b]) => s + b - a, 0);
  if (peopleOn()) return peopleSpans().reduce((s, [a, b]) => s + b - a, 0);
  if (partOn() && part.start != null && part.end != null) return Math.max(0, part.end - part.start);
  return full;
}
function showSizes() {
  if (!job) return;
  $("#pvGo").hidden = !(partOn() || peopleOn() || clipsOn());
  const apart = $("input[name=apart]:checked").value === "1";
  $("#apartRow").hidden = !(peopleOn() || clipsOn());
  $("#fadeRow").hidden = !(peopleOn() || clipsOn()) || apart;
  if (pv.on) stopPreview();
  const sec = savedSeconds(), vertical = shapeNow().vertical;
  const px = vertical ? 1080 * 1920 : (job.media?.width || 1920) * (job.media?.height || 1080);
  // original quality: measured about 6.7 Mbit/s for 1080p (h264_videotoolbox -q:v 65), by the number of pixels
  const est = { full: sec * (6700 * px / (1920 * 1080) + 192) / 8 / 1000, "720": sec * (2500 + 128) / 8 / 1000, "480": sec * (1000 + 96) / 8 / 1000 };
  const short = vertical ? 1080 : Math.min(job.media?.width || 1920, job.media?.height || 1080);
  if (short <= 720) est["720"] = Math.min(est["720"], est.full);
  if (short <= 480) est["480"] = Math.min(est["480"], est.full);
  const mb = x => x == null ? "" : x >= 1000 ? `about ${(x / 1000).toFixed(1)} GB` : `about ${Math.max(1, Math.round(x))} MB`;
  $$("[data-est]").forEach(el => {
    el.textContent = `(${mb(est[el.dataset.est])})`;
  });
}
function showPart() {
  showSizes();
  $("#partBox").hidden = !partOn();
  if (document.activeElement !== $("#partStart")) $("#partStart").value = part.start == null ? "" : fmtTime(part.start);
  if (document.activeElement !== $("#partEnd")) $("#partEnd").value = part.end == null ? "" : fmtTime(part.end);
  const ok = part.start != null && part.end != null && part.end > part.start;
  const n = ok ? lines.filter(l => l.end > part.start && l.start < part.end).length : 0;
  $("#partLen").textContent = ok ? `${fmtTime(part.end - part.start)} long, ${n} caption${n === 1 ? "" : "s"}` : "";
  drawTimeline(video.currentTime, true);
}
function setPart(k, v) {
  part[k] = Math.max(0, Math.min(video.duration || 1e9, v));
  if (part.start != null && part.end != null && part.end < part.start) [part.start, part.end] = [part.end, part.start];
  showPart();
}
$$("input[name=part]").forEach(r => r.addEventListener("change", showPeoplePick));
$$("input[name=part]").forEach(r => r.addEventListener("change", () => {
  if (partOn() && part.start == null) {            // a start: the ticked lines, or a minute from the playhead
    const ticked = lines.filter(l => picked.has(l.id));
    if (ticked.length) { part.start = ticked[0].start; part.end = ticked[ticked.length - 1].end; }
    else { part.start = video.currentTime; part.end = Math.min(video.duration || 1e9, video.currentTime + 60); }
  }
  showPart();
}));
$("#partFrom").onclick = () => setPart("start", video.currentTime);
$("#partTo").onclick = () => setPart("end", video.currentTime);
$("#partTicked").onclick = () => {
  const ticked = lines.filter(l => picked.has(l.id));
  if (!ticked.length) { alert("Tick lines in the list first (Shift-click ticks a range)."); return; }
  part.start = ticked[0].start; part.end = ticked[ticked.length - 1].end; showPart();
};
/* preview: play just what will be saved, part after part, skipping the rest */
function savedSpans() {               // null when the whole video is saved
  if (clipsOn()) return reelSpans();
  if (peopleOn()) return peopleSpans();
  if (partOn() && part.start != null && part.end != null && part.end > part.start) return [[part.start, part.end]];
  return null;
}
const pv = { on: false, spans: [], i: 0, jumping: false };
function startPreview(from = 0) {
  const spans = savedSpans();
  if (!spans || !spans.length) { alert(peopleOn() ? "Tick the people to keep first." : "Choose the part first: From here and To here."); return; }
  Object.assign(pv, { on: true, spans, i: Math.min(from, spans.length - 1) });
  previewJump();
  video.play();
}
function previewJump() { pv.jumping = true; video.currentTime = pv.spans[pv.i][0]; showPreview(); }
function stopPreview(pause = true) {
  if (!pv.on) return;
  pv.on = false; $("#pvBar").hidden = true;
  if (pause) video.pause();
}
function showPreview() {
  $("#pvBar").hidden = !pv.on;
  if (!pv.on) return;
  const [a] = pv.spans[pv.i], t = Math.max(a, video.currentTime);
  const before = pv.spans.slice(0, pv.i).reduce((s, [x, y]) => s + y - x, 0), all = pv.spans.reduce((s, [x, y]) => s + y - x, 0);
  $("#pvText").textContent = `Preview${pv.spans.length > 1 ? `: part ${pv.i + 1} of ${pv.spans.length}` : ""} · ${fmtTime(before + t - a).replace(/\.\d$/, "")} of ${fmtTime(all).replace(/\.\d$/, "")}`;
}
function previewTick(t) {             // called on every frame while it plays
  if (!pv.on || pv.jumping) return;
  const [a, b] = pv.spans[pv.i];
  if (t >= b - 0.03) {
    if (++pv.i >= pv.spans.length) { stopPreview(); video.currentTime = b; return; }
    previewJump();
  } else if (t < a - 0.6 || t > b + 0.6) stopPreview(false);   // you moved somewhere else: the preview ends
  else showPreview();
}
video.addEventListener("seeked", () => { pv.jumping = false; });
$("#pvGo").onclick = () => startPreview();
$("#pvStop").onclick = () => stopPreview();
$("#pvNext").onclick = () => { if (pv.on && pv.i < pv.spans.length - 1) { pv.i++; previewJump(); } };
$("#pvPrev").onclick = () => { if (pv.on) { pv.i = Math.max(0, video.currentTime - pv.spans[pv.i][0] > 1.5 ? pv.i : pv.i - 1); previewJump(); } };
addEventListener("keydown", e => { if (e.key === "Escape" && pv.on) stopPreview(); });
["partStart", "partEnd"].forEach(id => $("#" + id).addEventListener("change", e => {
  const t = parseTime(e.target.value);
  if (t == null) { showPart(); return; }
  setPart(id === "partStart" ? "start" : "end", t);
}));

// Vertical 9:16: "fill" crops the sides (the frame on the video picks which part stays), "fit" keeps all of it
let cropPos = 0.5;
function shapeNow() {
  const vertical = $("input[name=shape]:checked").value === "vertical";
  const size = $("input[name=vsize]:checked").value, fade = $("#fadeJoins").checked;
  const apart = (peopleOn() || clipsOn()) && $("input[name=apart]:checked").value === "1";
  return vertical ? { vertical, fit: $("input[name=fit]:checked").value, pos: Math.round(cropPos * 1000) / 1000, size, fade, apart }
    : { size, fade, apart };
}
function showShape() {
  const s = shapeNow();
  showSizes();
  $("#fitRow").hidden = !s.vertical;
  $("#fitHint").hidden = !s.vertical || s.fit !== "fill";
  placeCrop();
}
function placeCrop() {
  const s = shapeNow(), g = $("#cropGuide");
  g.hidden = !(s.vertical && s.fit === "fill") || !frame.w;
  if (g.hidden) return;
  Object.assign(g.style, { left: `${frame.left}px`, top: `${frame.top}px`, width: `${frame.w}px`, height: `${frame.h}px` });
  const w = Math.min(frame.w, frame.h * 9 / 16);
  Object.assign($("#cropWin").style, { width: `${w}px`, left: `${(frame.w - w) * cropPos}px` });
}
function loadShape() {           // what you chose last time for this video
  const s = job.shape || {};
  $(`input[name=shape][value="${s.vertical ? "vertical" : "original"}"]`).checked = true;
  $(`input[name=fit][value="${s.fit === "fit" ? "fit" : "fill"}"]`).checked = true;
  cropPos = s.pos ?? 0.5;
  $("#fadeJoins").checked = s.fade !== false;
  $(`input[name=apart][value="${s.apart ? "1" : ""}"]`).checked = true;
  $(`input[name=vsize][value="${["720", "480"].includes(s.size) ? s.size : "full"}"]`).checked = true;
  showShape();
  part.start = job.part?.start ?? null; part.end = job.part?.end ?? null;     // what you saved last time
  whoPicked.clear(); (job.part?.people || []).forEach(id => whoPicked.add(id));
  cuts.key = ""; cuts.list = []; cuts.restore = job.part?.spans || null;   // dropped parts stay out, nudged ends stay moved
  $(`input[name=part][value="${job.part?.reel ? "clips" : job.part?.people ? "people" : job.part ? "part" : "all"}"]`).checked = true;
  let srtPick = ["zh", "both", "th"];
  try { srtPick = JSON.parse(localStorage.getItem("ac-srt") || "null") || srtPick; } catch { /* fine */ }
  $$("input[name=srt]").forEach(b => { b.checked = srtPick.includes(b.value); });
  renderClips();
  showPart(); showPeoplePick();
}
$$("input[name=shape], input[name=fit], input[name=vsize], input[name=apart]").forEach(r => r.addEventListener("change", showShape));
$("#cropWin").addEventListener("pointerdown", e => {
  e.preventDefault(); video.pause();
  const el = $("#cropWin"), x0 = e.clientX, p0 = cropPos, room = frame.w - el.offsetWidth;
  el.setPointerCapture(e.pointerId);
  el.onpointermove = ev => { cropPos = room > 0 ? Math.max(0, Math.min(1, p0 + (ev.clientX - x0) / room)) : 0.5; placeCrop(); };
  el.onpointerup = () => { el.onpointermove = null; };
});

/* ---------------------------------------------------------- settings: models, themes, fonts */

// Safari only lets a page use fonts built into macOS, not ones you installed; the free caption
// fonts are handed to the page by the app instead (loaded only when something uses them).
let fontFacesAdded = false;
function addFontFaces(faces) {
  if (fontFacesAdded || !faces.length) return;
  fontFacesAdded = true;
  const css = faces.map(f => `@font-face { font-family: "${f.family}"; src: url("/api/fonts/${encodeURIComponent(f.file)}");` +
    ` font-weight: ${f.weight}; font-display: swap; }`).join("\n");
  const el = document.createElement("style"); el.textContent = css; document.head.append(el);
}

let settings = null;
async function loadSettings() {
  settings = await api("GET", "/api/settings");
  addFontFaces(settings.font_faces || []);
  setTimeout(renderClaudePicks, 0);
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
    $("#videoSubs").checked = settings.video_subs !== false;
    $("#subsCheck").checked = !!settings.subs_check;
    $("#subsCheck").disabled = !$("#videoSubs").checked;
    showOptsNow();
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
$$("[data-st]").forEach(el => el.addEventListener(el.tagName === "SELECT" ? "change" : "input", () => {
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
const PERSON_DOTS = ["#FFFFFF", "#FFE14D", "#FFC48A", "#FF8A80", "#FFB3D1", "#F48FB1", "#D7B8FF", "#9FD8FF", "#80DEEA", "#B8F5A4", "#C5E1A5", "#BCAAA4"];
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
    const setColour = col => { const q = personById(p.id); if (q) { q.color = col; c.value = hex6(col); dots.querySelectorAll("button").forEach(d => d.setAttribute("aria-pressed", String(d.dataset.c === col.toUpperCase()))); peopleChanged(); } };
    c.addEventListener("input", () => setColour(c.value.toUpperCase()));
    c.addEventListener("change", () => setColour(c.value.toUpperCase()));
    c.title = "Any colour";
    // one click: ready-made colours that read well on video
    const dots = document.createElement("div"); dots.className = "dots";
    dots.append(...PERSON_DOTS.map(col => {
      const d = document.createElement("button"); d.type = "button"; d.dataset.c = col; d.style.background = col;
      d.setAttribute("aria-label", `Use ${col}`); d.setAttribute("aria-pressed", String(col === (p.color || "").toUpperCase()));
      d.onclick = () => setColour(col);
      return d;
    }));
    n.addEventListener("input", () => { const q = personById(p.id); if (q) { q.name = n.value.trim(); peopleChanged(); } });
    const f = document.createElement("select"); f.className = "field pfont"; f.setAttribute("aria-label", "This person's Chinese font");
    fontMenu(f, p.font, "Font: like the rest");
    f.addEventListener("change", () => { const q = personById(p.id); if (q) { q.font = f.value || undefined; peopleChanged(true); } });
    x.onclick = () => { job.speakers = (job.speakers || []).filter(q => q.id !== p.id); peopleChanged(true); renderPeople(); };
    li.append(c, n, x, dots, f); return li;
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
  $("#lines").classList.toggle("picking", picked.size > 0);      // tick boxes show on every line once you tick one
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
    showTab("peoplePanel"); $("#addPerson").scrollIntoView({ block: "center" });
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
  previewTick(t);
  loopTick(t);
  railNowTick();
  markPlayingClip(t);
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
  drawTimeline(t);
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
  placeCrop();
  current = undefined; tick();
}
video.addEventListener("loadedmetadata", placeOverlay);
new ResizeObserver(placeOverlay).observe($("#player"));

// Where a line sits: like the rest, or its own place (then it's drawn in a box of its own). Same as style.py place_of.
function placeOf(l, st) {
  const lk = l.look || {}, pos = lk.position || st.position;
  return `${pos}:${lk.position === "custom" ? lk.y : st.y}`;
}

function drawCaption(on) {
  const st = fullStyle(), own = $("#ovOwn");
  own.replaceChildren();
  fillBox($("#ovBox"), [], st);
  if (!on.length || !st) return;
  const home = placeOf({}, st), groups = new Map();
  for (const l of on) {
    const k = placeOf(l, st);
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k).push(l);
  }
  for (const [k, group] of groups) {
    if (k === home) { fillBox($("#ovBox"), group, st); continue; }
    const pos = k.split(":")[0], y = +k.split(":")[1];
    const wrap = document.createElement("div"), box = document.createElement("div");
    wrap.className = "ov-own"; box.className = "ov-box";
    wrap.append(box); own.append(wrap);
    const pb = $("#player").getBoundingClientRect();
    Object.assign(wrap.style, { left: `${frame.left + frame.w * 0.06}px`, width: `${frame.w * 0.88}px` });
    if (pos === "top") wrap.style.top = `${frame.top + frame.h * 0.05}px`;
    else wrap.style.bottom = `${pb.height - (frame.top + frame.h * (pos === "custom" ? y : 0.94))}px`;
    fillBox(box, group, st);
    if (pos === "custom") { box.classList.add("draggable"); box.onpointerdown = e => dragLine(e, group[0], box); }
  }
}

function fillBox(boxEl, group, st) {
  boxEl.replaceChildren(); boxEl.style.background = "none"; boxEl.style.padding = "0";
  if (!group.length || !st) return;
  const which = $("input[name=show]:checked").value;
  const basePx = Math.min(frame.vw, frame.vh) * frame.scale * 0.058 * st.size;
  const rows = [];
  let biggest = 0;
  for (const l of group) {
    const lk = l.look || {};
    if (lk.show === "none" || (lk.show && which !== "both" && lk.show !== which)) continue;
    const mine = lk.show && which === "both" ? lk.show : which;
    const zhPx = basePx * (lk.size || 1), thPx = mine === "both" ? zhPx * st.th_scale : zhPx;
    biggest = Math.max(biggest, zhPx);
    const th = l.kind === "sound" ? "" : (l.th || ""), zh = l.zh || "", colour = lk.color || ownColour(l);
    const zf = lk.font || ownFont(l);                 // the line's font, the person's, or the video's
    const pair = [];
    if (mine !== "zh" && th) pair.push([th, thPx, true]);
    if (mine !== "th" && zh) pair.push([zh, zhPx, false]);
    if (st.order === "zh_above") pair.reverse();
    pair.forEach(r => rows.push([...r, colour, lk.bold, mine, zf, l]));
  }
  rows.forEach(([text, px, isTh, colour, bold, mine, zf, line], i) => {
    const el = document.createElement("div");
    el.className = "ov-row"; fillPainted(el, text, line.paint, isTh ? "th" : "zh");
    Object.assign(el.style, rowCss(st, px, isTh && mine === "both"), { marginTop: i ? `${biggest * 0.12}px` : "0" });
    if (colour) el.style.color = colour;
    if (bold !== undefined) el.style.fontWeight = bold ? "700" : "500";
    if (zf && !isTh) el.style.fontFamily = `"${zf}", "PingFang TC", sans-serif`;
    boxEl.append(el);
  });
  if (st.box && rows.length) Object.assign(boxEl.style, { background: st.box_color, padding: `${biggest * 0.19}px ${biggest * 0.32}px`, borderRadius: `${biggest * 0.25}px` });
}

// drag one line that has its own place
function dragLine(e, l, el) {
  e.preventDefault(); e.stopPropagation(); video.pause();
  const pb = $("#player").getBoundingClientRect(), wrap = el.parentElement;
  el.setPointerCapture(e.pointerId);
  let y = l.look.y;
  el.onpointermove = ev => {
    y = Math.max(0.08, Math.min(0.99, Math.round(((ev.clientY - pb.top - frame.top + el.offsetHeight / 2) / frame.h) * 1000) / 1000));
    wrap.style.bottom = `${pb.height - (frame.top + frame.h * y)}px`;
  };
  el.onpointerup = () => { el.onpointermove = null; setLook(l, { y }); };
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
  if (dragging) return;
  const on = touches.filter(t => t.whole || (t.start <= time && time < t.end) || t.id === selTouch);
  const key = on.map(t => t.id + JSON.stringify(t)).join("|") + frame.w + JSON.stringify(fullStyle());
  if (key === shownTouches && !force) return;
  shownTouches = key;
  const st = fullStyle() || {};
  $("#touchLayer").replaceChildren(...on.map(t => {
    if (t.kind === "image") {
      const img = document.createElement("img");
      img.className = "touch logo" + (t.id === selTouch ? " sel" : ""); img.dataset.id = t.id; img.draggable = false;
      img.src = `/api/logos/${t.image}`; img.alt = "";
      Object.assign(img.style, { left: `${frame.left + t.x * frame.w}px`, top: `${frame.top + t.y * frame.h}px`,
        width: `${(t.w || 0.15) * frame.w}px`, opacity: t.opacity ?? 1 });
      Object.assign(img.style, standoutCss(t));
      img.onpointerdown = e => dragTouch(e, t, img);
      moveStyle(img, t);
      return img;
    }
    const el = document.createElement("div");
    const px = touchPx(t);
    el.className = "touch" + (t.kind === "bubble" ? " bubble" : "") + (t.pending ? " pending" : "") + (t.id === selTouch ? " sel" : "");
    el.textContent = t.text;
    el.dataset.id = t.id;
    Object.assign(el.style, {
      left: `${frame.left + t.x * frame.w}px`, top: `${frame.top + t.y * frame.h}px`, fontSize: `${px}px`,
      fontFamily: `"${t.font || st.zh_font}", "PingFang TC", sans-serif`,
    });
    el.style.opacity = t.opacity ?? 1;
    if (t.kind === "text") Object.assign(el.style, { color: t.color || "#fff", fontWeight: t.bold === false ? "500" : "700",
      webkitTextStroke: `${px * (t.outline ?? 0.08) * 2}px ${t.outline_color || "#000"}`, paintOrder: "stroke fill",
      textShadow: `0 ${px * 0.015}px ${px * 0.04}px rgba(0,0,0,.6)` });
    else if (t.kind === "bubble") Object.assign(el.style, { padding: `${px * 0.2}px ${px * 0.35}px`, borderRadius: `${px * 0.6}px` });
    else Object.assign(el.style, { color: t.color || "#fff", webkitTextStroke: `${px * 0.2}px ${t.outline_color || "#F06A9F"}`, paintOrder: "stroke fill" });
    el.onpointerdown = e => dragTouch(e, t, el);
    moveStyle(el, t);
    return el;
  }));
}
// Drag an emoji, note, text or logo. Nothing on the video is redrawn while you drag: redrawing
// replaces the element under the pointer and the drag stops (that was the bug).
let dragging = false;
function dragTouch(e, t, el) {
  if (e.button !== undefined && e.button !== 0) return;
  e.preventDefault(); video.pause();
  dragging = true;
  $$("#touchLayer .sel").forEach(x => x.classList.remove("sel")); el.classList.add("sel");
  const box = $("#player").getBoundingClientRect();
  const start = { x: e.clientX, y: e.clientY, tx: t.x, ty: t.y };
  try { el.setPointerCapture(e.pointerId); } catch { /* */ }
  let moved = false;
  const move = ev => {
    if (!moved && Math.hypot(ev.clientX - start.x, ev.clientY - start.y) < 3) return;
    moved = true;
    t.x = Math.max(0, Math.min(1, start.tx + (ev.clientX - start.x) / frame.w));
    t.y = Math.max(0, Math.min(1, start.ty + (ev.clientY - start.y) / frame.h));
    el.style.left = `${frame.left + t.x * frame.w}px`; el.style.top = `${frame.top + t.y * frame.h}px`;
  };
  const up = () => {
    el.removeEventListener("pointermove", move); el.removeEventListener("pointerup", up); el.removeEventListener("pointercancel", up);
    dragging = false;
    if (moved) patchTouch(t, { x: Math.round(t.x * 1000) / 1000, y: Math.round(t.y * 1000) / 1000 });
    selectTouch(t.id);                       // open its editor now that the drag is over
  };
  el.addEventListener("pointermove", move); el.addEventListener("pointerup", up); el.addEventListener("pointercancel", up);
}
// Changes wait a moment so typing and dragging sliders don't send a request each time. They pile up
// per item and all go together, so a quick second change (a corner button) never drops the first.
let touchTimer = null;
const touchPending = {};
function patchTouch(t, ch, later) {
  Object.assign(t, ch);
  touchPending[t.id] = { ...(touchPending[t.id] || {}), ...ch };
  drawTouches(video.currentTime, true); renderTouchList();
  clearTimeout(touchTimer);
  if (later) touchTimer = setTimeout(flushTouches, 500); else flushTouches();
}
function flushTouches() {
  clearTimeout(touchTimer);
  for (const [id, ch] of Object.entries(touchPending)) {
    delete touchPending[id];
    api("PATCH", `/api/jobs/${job.id}/touches/${id}`, ch).catch(ex => alert(ex.message));
  }
}
addEventListener("pagehide", flushTouches);
const isBrand = t => t.kind === "text" || t.kind === "image";
function renderTouchList() {
  renderBrandList();
  const emoji = touches.filter(t => !isBrand(t));
  $("#touchCount").textContent = emoji.length || "";
  const pend = emoji.filter(t => t.pending).length;
  $("#touchList").replaceChildren(...emoji.map(t => {
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
  $("#touchEdit").hidden = !t || isBrand(t);
  $("#brandEdit").hidden = !t || !isBrand(t);
  if (t && isBrand(t)) { fillBrandEditor(t); renderTouchList(); drawTouches(video.currentTime, true); return; }
  if (t) {
    showTab("touchPanel");
    $("#teText").value = t.text;
    $("#teSize").value = t.size || 1.3; $("#teSizeOut").textContent = Math.round((t.size || 1.3) * 100) + "%";
    const d = Math.round((t.end - t.start) * 2) / 2; $("#teDur").value = d; $("#teDurOut").textContent = d + "s";
    $$("input[name=te-kind]").forEach(r => { r.checked = r.value === (t.kind || "plain"); });
    $("#teColor").value = hex6(t.color || "#FFFFFF"); $("#teOutline").value = hex6(t.outline_color || "#F06A9F");
    $("#teMotion").value = t.motion || ""; $("#teSpeed").value = 8.5 - (t.period || 2);
    $("#teSpeedOut").textContent = speedLabel(t.period || 2); $("#teSpeed").disabled = !t.motion;
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

/* ---------------------------------------------------------- movement preview */

// the same movements the saved video gets (style.motion_filters), in step with the video's time
function moveStyle(el, t) {
  if (!t.motion || t.id === selTouch && dragging) return;
  const p = t.period || 2;
  el.classList.add("mv", `mv-${t.motion}`);
  if (video.paused) el.classList.add("paused");
  el.style.setProperty("--p", `${p}s`);
  el.style.setProperty("--ay", `${(t.motion === "fly" ? 0.045 : 0.015) * frame.h}px`);
  el.style.setProperty("--ax", `${0.07 * frame.w}px`);
  const left = frame.left + t.x * frame.w;
  el.style.setProperty("--x0", `${frame.left - left - frame.w * 0.06}px`);
  el.style.setProperty("--x1", `${frame.left + frame.w - left + frame.w * 0.06}px`);
  el.style.animationDelay = `-${(video.currentTime % p).toFixed(2)}s`;
}
function syncMoves() {
  $$("#touchLayer .mv").forEach(el => {
    el.classList.toggle("paused", video.paused);
    const t = touches.find(x => x.id === el.dataset.id);
    if (t) el.style.animationDelay = `-${(video.currentTime % (t.period || 2)).toFixed(2)}s`;
  });
}
["play", "pause", "seeked"].forEach(ev => video.addEventListener(ev, syncMoves));
function speedLabel(p) { return p <= 1 ? "fast" : p <= 2.5 ? "medium" : p <= 4.5 ? "slow" : "very slow"; }

/* ---------------------------------------------------------- your text and logo */

// the same looks as the renderer (style.py touch_block): outline, soft shadow, badge, circle
function standoutCss(t) {
  const wpx = (t.w || 0.15) * frame.w, edge = t.edge ?? 0.012, c = t.edge_color || "#000000";
  const r = Math.max(1, edge * wpx);
  if (t.standout === "outline")
    return { filter: [[r, 0], [-r, 0], [0, r], [0, -r]].map(([x, y]) => `drop-shadow(${x}px ${y}px 0 ${c})`).join(" ") };
  if (t.standout === "shadow") return { filter: `drop-shadow(0 0 ${edge * 2.5 * wpx}px ${c}) drop-shadow(0 0 ${edge * 2.5 * wpx}px ${c})` };
  if (t.standout === "badge" || t.standout === "circle")
    return { background: t.plate_color || "#FFFFFFD9", padding: `${0.12 * wpx}px`,
             borderRadius: t.standout === "circle" ? "50%" : `${0.25 * wpx}px`, boxSizing: "content-box" };
  return {};
}
let logoList = [];
const logoTone = id => (logoList.find(l => l.id === id) || {}).tone || "light";
// a logo that contrasts with itself: dark edges for a light logo, light ones for a dark logo
function contrastFor(id) {
  return logoTone(id) === "light" ? { edge_color: "#1F1F1F", plate_color: "#1D2550CC" } : { edge_color: "#FFFFFF", plate_color: "#FFFFFFD9" };
}

function renderBrandList() {
  const items = touches.filter(isBrand);
  $("#brandCount").textContent = items.length || "";
  $("#brandList").replaceChildren(...items.map(t => {
    const li = document.createElement("li"); li.className = t.id === selTouch ? "sel" : "";
    const tm = document.createElement("span"); tm.className = "tt"; tm.textContent = t.whole ? "whole" : fmtTime(t.start);
    let what;
    if (t.kind === "image") { what = document.createElement("img"); what.src = `/api/logos/${t.image}`; what.className = "logo-thumb"; what.alt = "Logo"; }
    else { what = document.createElement("span"); what.className = "tx"; what.textContent = t.text; }
    const ed = document.createElement("button"); ed.type = "button"; ed.textContent = "Edit";
    ed.onclick = () => { if (!t.whole) { video.currentTime = t.start + 0.01; } video.pause(); selectTouch(t.id); };
    const del = document.createElement("button"); del.type = "button"; del.textContent = "Remove"; del.onclick = () => removeTouch(t);
    li.append(tm, what, ed, del); return li;
  }));
}
async function renderSavedLogos() {
  let list = [];
  try { list = await api("GET", "/api/logos"); } catch { /* */ }
  logoList = list;
  $("#savedLogos").replaceChildren(...list.map(l => {
    const b = document.createElement("span"); b.className = "saved-logo";
    const use = document.createElement("button"); use.type = "button"; use.title = `Add ${l.name}`;
    const img = document.createElement("img"); img.src = `/api/logos/${l.id}`; img.alt = l.name; use.append(img);
    use.onclick = () => addBrand({ kind: "image", image: l.id, text: "", x: 0.1, y: 0.09, w: 0.14, opacity: 0.95, whole: true,
                                    standout: "outline", edge: 0.012, ...contrastFor(l.id) });
    const x = document.createElement("button"); x.type = "button"; x.className = "x"; x.textContent = "×"; x.title = "Forget this logo";
    x.onclick = async () => { if (confirm("Forget this logo? Videos already saved keep it.")) { await api("DELETE", `/api/logos/${l.id}`); renderSavedLogos(); } };
    b.append(use, x); return b;
  }));
}
async function addBrand(t) {
  video.pause();
  try {
    const n = await api("POST", `/api/jobs/${job.id}/touches`, { start: video.currentTime, end: video.currentTime + 5, ...t });
    touches.push(n); touches.sort((a, b) => a.start - b.start);
    showTab("brandPanel"); selectTouch(n.id);
    if (t.kind === "text") { $("#beText").select(); $("#beText").focus(); }
  } catch (ex) { alert(ex.message); }
}
$("#addText").onclick = () => addBrand({ kind: "text", text: "中字 by ", x: 0.84, y: 0.07, size: 0.7, opacity: 0.85,
  color: "#FFFFFF", outline_color: "#000000", outline: 0.08, bold: true, whole: true });
$("#logoFile").addEventListener("change", async () => {
  const f = $("#logoFile").files[0]; $("#logoFile").value = "";
  if (!f) return;
  const form = new FormData(); form.append("file", f);
  try {
    const l = await api("POST", "/api/logos", form);
    await renderSavedLogos();
    addBrand({ kind: "image", image: l.id, text: "", x: 0.1, y: 0.09, w: 0.14, opacity: 0.95, whole: true,
               standout: "outline", edge: 0.012, ...contrastFor(l.id) });
  } catch (ex) { alert(ex.message); }
});

function fillBrandEditor(t) {
  const img = t.kind === "image";
  $$(".be-text", $("#brandEdit")).forEach(el => { el.hidden = img; });
  $$(".be-image", $("#brandEdit")).forEach(el => { el.hidden = !img; });
  if (img) {
    const how = t.standout || "none";
    $$("input[name=be-standout]").forEach(r => { r.checked = r.value === how; });
    $$(".be-edge").forEach(el => { el.hidden = !(how === "outline" || how === "shadow"); });
    $$(".be-plate").forEach(el => { el.hidden = !(how === "badge" || how === "circle"); });
    $("#beEdgeColor").value = hex6(t.edge_color || "#000000"); $("#beEdge").value = t.edge ?? 0.012;
    const pc = t.plate_color || "#FFFFFFD9";
    $("#bePlateColor").value = hex6(pc); $("#bePlateOp").value = pc.length === 9 ? (parseInt(pc.slice(7), 16) / 255).toFixed(2) : 1;
  }
  $("#beText").hidden = img;
  if (!$("#beFont").options.length && settings) {
    const all = [...settings.fonts.zh, ...settings.fonts.th];
    $("#beFont").replaceChildren(...all.map(f => { const o = new Option(f.label, f.family); o.style.fontFamily = `"${f.family}"`; return o; }));
  }
  $("#beText").value = t.text || "";
  $("#beFont").value = t.font || fullStyle()?.zh_font || "PingFang TC";
  $("#beSizeName").textContent = img ? "Width" : "Size";
  const size = img ? (t.w || 0.15) : (t.size || 0.7);
  $("#beSize").min = img ? "0.03" : "0.3"; $("#beSize").max = img ? "0.6" : "3"; $("#beSize").step = img ? "0.01" : "0.05";
  $("#beSize").value = size; $("#beSizeOut").textContent = Math.round(size * 100) + "%";
  $("#beOpacity").value = t.opacity ?? 1; $("#beOpOut").textContent = Math.round((t.opacity ?? 1) * 100) + "%";
  $("#beOutline").value = t.outline ?? 0.08; $("#beOutOut").textContent = Math.round((t.outline ?? 0.08) * 100) + "%";
  $("#beColor").value = hex6(t.color || "#FFFFFF"); $("#beOutlineColor").value = hex6(t.outline_color || "#000000");
  $("#beBold").checked = t.bold !== false;
  $("#beWhole").checked = !!t.whole; $("#bePart").hidden = !!t.whole;
  $("#beMotion").value = t.motion || ""; $("#beSpeed").value = 8.5 - (t.period || 2);
  $("#beSpeedOut").textContent = speedLabel(t.period || 2); $("#beSpeed").disabled = !t.motion;
  const d = Math.round((t.end - t.start) * 2) / 2; $("#beDur").value = d; $("#beDurOut").textContent = d + "s";
}
const bt = () => { const t = selT(); return t && isBrand(t) ? t : null; };
$("#beText").addEventListener("input", () => { const t = bt(); if (t && $("#beText").value.trim()) patchTouch(t, { text: $("#beText").value }, true); });
$("#beFont").addEventListener("change", () => { const t = bt(); if (t) patchTouch(t, { font: $("#beFont").value }); });
$("#beSize").addEventListener("input", () => {
  const t = bt(); if (!t) return; const v = +$("#beSize").value; $("#beSizeOut").textContent = Math.round(v * 100) + "%";
  patchTouch(t, t.kind === "image" ? { w: v } : { size: v }, true);
});
$("#beOpacity").addEventListener("input", () => { const t = bt(); if (t) { $("#beOpOut").textContent = Math.round($("#beOpacity").value * 100) + "%"; patchTouch(t, { opacity: +$("#beOpacity").value }, true); } });
$("#beOutline").addEventListener("input", () => { const t = bt(); if (t) { $("#beOutOut").textContent = Math.round($("#beOutline").value * 100) + "%"; patchTouch(t, { outline: +$("#beOutline").value }, true); } });
$("#beColor").addEventListener("input", () => { const t = bt(); if (t) patchTouch(t, { color: $("#beColor").value }, true); });
$("#beOutlineColor").addEventListener("input", () => { const t = bt(); if (t) patchTouch(t, { outline_color: $("#beOutlineColor").value }, true); });
$("#beBold").addEventListener("change", () => { const t = bt(); if (t) patchTouch(t, { bold: $("#beBold").checked }); });
$("#beWhole").addEventListener("change", () => {
  const t = bt(); if (!t) return; $("#bePart").hidden = $("#beWhole").checked;
  patchTouch(t, $("#beWhole").checked ? { whole: true } : { whole: false, start: video.currentTime, end: video.currentTime + 5 });
});
$("#beDur").addEventListener("input", () => { const t = bt(); if (t) { $("#beDurOut").textContent = $("#beDur").value + "s"; patchTouch(t, { end: t.start + +$("#beDur").value }, true); } });
$("#beStartHere").onclick = () => { const t = bt(); if (t) { const d = t.end - t.start; patchTouch(t, { start: video.currentTime, end: video.currentTime + d }); } };
$("#beDelete").onclick = () => { const t = bt(); if (t) removeTouch(t); };
$("#beDone").onclick = () => selectTouch(null);
for (const [m, sp, out] of [["#beMotion", "#beSpeed", "#beSpeedOut"], ["#teMotion", "#teSpeed", "#teSpeedOut"]]) {
  $(m).addEventListener("change", () => {
    const t = selT(); if (!t) return;
    patchTouch(t, { motion: $(m).value || "", period: t.period || 2 }); $(sp).disabled = !$(m).value;
  });
  // the slider reads as speed (right = faster); what's stored is the seconds one round takes
  $(sp).addEventListener("input", () => {
    const t = selT(); if (!t) return;
    const period = Math.round((8.5 - +$(sp).value) * 4) / 4;
    $(out).textContent = speedLabel(period); patchTouch(t, { period }, true);
  });
}
$$("input[name=be-standout]").forEach(r => r.addEventListener("change", () => {
  const t = bt(); if (!t) return;
  const ch = { standout: r.value };
  if (!t.edge_color || !t.plate_color) Object.assign(ch, contrastFor(t.image));
  patchTouch(t, ch); fillBrandEditor(t);
}));
$("#beEdgeColor").addEventListener("input", () => { const t = bt(); if (t) patchTouch(t, { edge_color: $("#beEdgeColor").value }, true); });
$("#beEdge").addEventListener("input", () => { const t = bt(); if (t) patchTouch(t, { edge: +$("#beEdge").value }, true); });
const plateColour = () => $("#bePlateColor").value + Math.round(+$("#bePlateOp").value * 255).toString(16).padStart(2, "0").toUpperCase();
$("#bePlateColor").addEventListener("input", () => { const t = bt(); if (t) patchTouch(t, { plate_color: plateColour() }, true); });
$("#bePlateOp").addEventListener("input", () => { const t = bt(); if (t) patchTouch(t, { plate_color: plateColour() }, true); });
// corners: measured from the item as drawn, so it sits fully inside the picture with a small margin
$$("#brandEdit [data-corner]").forEach(b => b.addEventListener("click", () => {
  const t = bt(); if (!t) return;
  const el = $(`#touchLayer [data-id="${t.id}"]`);
  const hw = el ? el.offsetWidth / 2 / frame.w : 0.08, hh = el ? el.offsetHeight / 2 / frame.h : 0.05;
  const m = 0.03, c = b.dataset.corner;
  const x = c.endsWith("l") ? m + hw : c.endsWith("r") ? 1 - m - hw : 0.5;
  const y = c === "c" ? 0.5 : c.startsWith("t") ? m + hh : 1 - m - hh;
  patchTouch(t, { x: Math.round(x * 1000) / 1000, y: Math.round(y * 1000) / 1000 });
}));

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
  $("#rangeGo").textContent = timingOnly() ? "Line up the timing here" : "Listen again and fix";
  $$(".line").forEach(li => {
    const l = lines.find(x => x.id === +li.dataset.id);
    li.classList.toggle("in-range", !$("#rangeBox").hidden && f !== null && t !== null && l && l.end > f && l.start < t);
  });
}
$("#markRange").onclick = () => {
  const box = $("#rangeBox"); box.hidden = !box.hidden;
  if (!box.hidden) { range.from = range.from ?? video.currentTime; $("#rangeNote").focus(); }
  else endListening();
  renderRange();
};
$("#rangeFrom").onclick = () => { range.from = video.currentTime; if (range.to !== null && range.to < range.from) range.to = null; renderRange(); };
$("#rangeTo").onclick = () => { range.to = video.currentTime; if (range.from !== null && range.to < range.from) [range.from, range.to] = [range.to, range.from]; renderRange(); };
$("#rangeCancel").onclick = () => { endListening(); $("#rangeBox").hidden = true; range.from = range.to = null; fixPicked.clear(); renderReasons(); renderRange(); };
$("#rangePlay").onclick = () => {
  if (range.from === null) return;
  setLoop(false);
  video.currentTime = range.from; video.play();
  const stop = () => { if (range.to !== null && video.currentTime >= range.to) { video.pause(); video.removeEventListener("timeupdate", stop); } };
  video.addEventListener("timeupdate", stop);
};

// Listen closely: the stretch over and over, and slower (the browser keeps the pitch), to hear what's really said
let looping = false;
function setLoop(on) {
  looping = !!on && range.from !== null && range.to !== null && range.to > range.from;
  $("#rangeLoop").setAttribute("aria-pressed", String(looping));
  if (looping) { stopPreview(false); video.currentTime = range.from; video.play(); }
}
function loopTick(t) {                 // every frame while it plays
  if (!looping) return;
  if (range.from === null || range.to === null || range.to <= range.from) { setLoop(false); return; }
  if (t >= range.to - 0.02 || t < range.from - 1) video.currentTime = range.from;
}
function setRate(r) {
  video.playbackRate = r;
  video.preservesPitch = video.mozPreservesPitch = video.webkitPreservesPitch = true;
  const el = $(`input[name=rate][value="${r}"]`); if (el) el.checked = true;
}
$("#rangeLoop").onclick = () => {
  if (range.from === null || range.to === null) { alert("Mark the stretch first: From here and To here."); return; }
  setLoop(!looping);
};
$$("input[name=rate]").forEach(r => r.addEventListener("change", () => setRate(+r.value)));
function endListening() { setLoop(false); setRate(1); }
$("#fillSkipped").onclick = async () => {
  try { await api("POST", `/api/jobs/${job.id}/fill-skipped`); refresh(job.id); } catch (ex) { alert(ex.message); }
};
// What's wrong, in one tap: the reasons that come up again and again. Each becomes part of the note Claude reads;
// "timing" alone only lines the stretch up with the speech (no listening again, no Claude).
const FIX_REASONS = [
  ["overlap", "Two people talk at once", "Two people talk over each other here: listen again and give each person their own line."],
  ["timing", "Timing doesn't match", "The captions here don't line up with when it's said."],
  ["skipped", "Words were skipped", "Some talking here has no captions: listen again and fill in what's missing."],
  ["music", "Music drowns them out", "Background music or noise covers the voices here: rely on the voice with the music removed."],
  ["english", "They speak English", "They speak English here: keep the English as said, and translate it."],
  ["misheard", "Words misheard", "Some words or names here are misheard: listen again carefully."],
  ["translation", "Translation is off", "The Chinese here doesn't match what they say: translate it again."],
];
const fixPicked = new Set();
function myNotes() { try { return JSON.parse(localStorage.getItem("ac-fix-notes") || "{}"); } catch { return {}; } }
function renderReasons() {
  $("#fixReasons").replaceChildren(...FIX_REASONS.map(([k, label, note]) => {
    const b = document.createElement("button"); b.type = "button"; b.textContent = label; b.title = note;
    b.setAttribute("aria-pressed", String(fixPicked.has(k)));
    b.onclick = () => { fixPicked.has(k) ? fixPicked.delete(k) : fixPicked.add(k); renderReasons(); renderRange(); };
    return b;
  }));
  // the notes you typed most often, one tap to use again
  const mine = Object.entries(myNotes()).sort((a, b) => b[1].n - a[1].n || b[1].at - a[1].at).slice(0, 5);
  $("#fixMine").replaceChildren(...mine.map(([text]) => {
    const b = document.createElement("button"); b.type = "button"; b.textContent = text; b.title = text;
    b.onclick = () => { const i = $("#rangeNote"); i.value = i.value.trim() ? `${i.value.trim()}; ${text}` : text; renderRange(); };
    return b;
  }));
}
function timingOnly() { return fixPicked.size === 1 && fixPicked.has("timing") && !$("#rangeNote").value.trim(); }
function fixNote() {
  return [...FIX_REASONS.filter(([k]) => fixPicked.has(k)).map(([, , n]) => n), $("#rangeNote").value.trim()].filter(Boolean).join(" ");
}
$("#rangeNote").addEventListener("input", () => renderRange());
$("#rangeGo").onclick = async () => {
  const typed = $("#rangeNote").value.trim();
  try {
    await api("POST", `/api/jobs/${job.id}/review`, { start: range.from, end: range.to, note: fixNote(), timing_only: timingOnly(),
      model: fixClaude().model || null, effort: fixClaude().effort || null });
    if (typed) {                     // remembered on this Mac, so it's one tap next time
      const m = myNotes(); m[typed] = { n: (m[typed]?.n || 0) + 1, at: Date.now() };
      try { localStorage.setItem("ac-fix-notes", JSON.stringify(Object.fromEntries(Object.entries(m).sort((a, b) => b[1].at - a[1].at).slice(0, 30)))); } catch { /* fine */ }
    }
    endListening();
    $("#rangeBox").hidden = true; $("#rangeNote").value = ""; fixPicked.clear(); range.from = range.to = null; renderRange(); renderReasons();
    refresh(job.id);
  } catch (ex) { alert(ex.message); }
};
renderReasons();

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

/* ============================================================ timeline */

// A strip under the video: the sound as a wave, each caption as a block you can drag (move it) or pull by
// its edges (change when it starts or ends), and the playhead. It follows the video while it plays.
const tl = { span: 20, from: 0, wave: null, rate: 50, drag: null, lastT: -1 };

async function loadWave(jid) {
  tl.wave = null; tl.from = 0;
  try {
    const r = await fetch(`/api/jobs/${jid}/waveform`);
    if (r.ok) { tl.rate = +r.headers.get("X-Rate") || 50; tl.wave = new Uint8Array(await r.arrayBuffer()); }
  } catch { /* the timeline still shows the captions */ }
  drawTimeline(video.currentTime, true);
}

function tlWidth() { return $("#tlView").clientWidth || 600; }
function tlTime(clientX) {
  const b = $("#tlView").getBoundingClientRect();
  return tl.from + (clientX - b.left) / b.width * tl.span;
}
function tlClamp() {
  const dur = video.duration || job?.media?.duration || 0;
  tl.span = Math.max(4, Math.min(tl.span, Math.max(8, dur || 600)));
  tl.from = Math.max(0, Math.min(tl.from, Math.max(0, dur - tl.span)));
}

let tlLastKey = "";
function drawTimeline(t, force) {
  if (!job || $("#timeline").hidden) return;
  if (!tl.drag && t !== tl.lastT) {                // the video moved: keep the playhead in view
    if (t < tl.from || t > tl.from + tl.span * 0.85) tl.from = t - tl.span * 0.25;
  }
  tl.lastT = t;
  tlClamp();
  const W = tlWidth(), pps = W / tl.span;
  $("#tlHead").style.left = `${(t - tl.from) * pps}px`;
  const spans = clipsOn() ? [] : savedSpans() || [];       // what will be saved, shaded (clips have their own bands)
  drawClipBands(pps);
  const pkey = spans.map(s => s.join("-")).join(",");
  if (pkey + pps + tl.from !== tl.partKey) {
    tl.partKey = pkey + pps + tl.from;
    $("#tlParts").replaceChildren(...spans.filter(([a, b]) => b > tl.from && a < tl.from + tl.span).map(([a, b]) => {
      const el = document.createElement("div"); el.className = "tl-part";
      Object.assign(el.style, { left: `${(a - tl.from) * pps}px`, width: `${Math.max(2, (b - a) * pps)}px` });
      return el;
    }));
  }
  const key = `${tl.from.toFixed(2)}|${tl.span}|${W}|${linesRev}|${current}|${tl.drag ? Math.random() : ""}`;
  if (key === tlLastKey && !force) return;
  tlLastKey = key;
  drawWave(W, pps);
  // time labels
  const step = [1, 2, 5, 10, 15, 30, 60, 120, 300].find(s => s * pps >= 70) || 600;
  const ticks = [];
  for (let s = Math.ceil(tl.from / step) * step; s < tl.from + tl.span; s += step) {
    const el = document.createElement("span"); el.style.left = `${(s - tl.from) * pps}px`; el.textContent = fmtTime(s).replace(/\.\d$/, "");
    ticks.push(el);
  }
  $("#tlTicks").replaceChildren(...ticks);
  // caption blocks; two people at once go on two rows
  const shown = lines.filter(l => l.end > tl.from && l.start < tl.from + tl.span);
  let rowEnd = -1;
  const blocks = shown.map(l => {
    const row = l.start < rowEnd - 0.05 ? 1 : 0;
    if (!row) rowEnd = l.end;
    const el = document.createElement("div");
    el.className = `tl-line${l.flag ? " flagged" : ""}${readSpeed(l) ? " fast" : ""}${row ? " row1" : ""}${linesAt(t).includes(l) ? " now" : ""}${tl.drag?.l === l ? " moving" : ""}`;
    el.dataset.id = l.id;
    el.style.left = `${(l.start - tl.from) * pps}px`;
    el.style.width = `${Math.max(6, (l.end - l.start) * pps)}px`;
    const c = (l.look && l.look.color) || ownColour(l);
    if (c) el.style.setProperty("--c", c);
    el.textContent = l.zh || l.th || "…";
    el.title = `${fmtTime(l.start)}–${fmtTime(l.end)}  ${l.th || ""}\n${l.zh || ""}`;
    const hl = document.createElement("i"), hr = document.createElement("i");
    hl.className = "h l"; hr.className = "h r";
    el.append(hl, hr);
    return el;
  });
  $("#tlLines").replaceChildren(...blocks);
}

function drawWave(W, pps) {
  const cv = $("#tlWave"), H = cv.clientHeight || 96, dpr = devicePixelRatio || 1;
  if (cv.width !== Math.round(W * dpr) || cv.height !== Math.round(H * dpr)) { cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); }
  const g = cv.getContext("2d");
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, W, H);
  if (!tl.wave) return;
  g.fillStyle = getComputedStyle(document.documentElement).getPropertyValue("--ink-3").trim() || "#8a90ad";
  g.globalAlpha = 0.45;
  const mid = 20 + (H - 26) / 2, half = (H - 26) / 2;
  for (let x = 0; x < W; x++) {
    const a = Math.floor((tl.from + x / pps) * tl.rate), b = Math.max(a + 1, Math.floor((tl.from + (x + 1) / pps) * tl.rate));
    let m = 0;
    for (let i = a; i < b && i < tl.wave.length; i++) if (tl.wave[i] > m) m = tl.wave[i];
    const h = Math.max(0.5, m / 255 * half);
    g.fillRect(x, mid - h, 1, h * 2);
  }
  g.globalAlpha = 1;
}

$("#tlView").addEventListener("pointerdown", e => {
  if (e.button !== 0) return;
  const band = e.target.closest(".tl-clip");
  if (band && !band.classList.contains("pending")) {
    const c = reel().find(x => x.id === band.dataset.id);
    const mode = e.target.classList.contains("l") ? "start" : e.target.classList.contains("r") ? "end" : "move";
    tl.drag = { clip: c, mode, x0: e.clientX, t0: tlTime(e.clientX), s0: c.start, e0: c.end, moved: false };
    $("#tlView").setPointerCapture(e.pointerId); video.pause();
    return;
  }
  const block = e.target.closest(".tl-line");
  const l = block && lines.find(x => x.id === +block.dataset.id);
  const mode = !l ? "pan" : e.target.classList.contains("l") ? "start" : e.target.classList.contains("r") ? "end" : "move";
  tl.drag = { l, mode, x0: e.clientX, t0: tlTime(e.clientX), from0: tl.from, s0: l?.start, e0: l?.end, moved: false };
  $("#tlView").setPointerCapture(e.pointerId);
  if (l) video.pause();
});
$("#tlView").addEventListener("pointermove", e => {
  const d = tl.drag;
  if (!d) return;
  if (Math.abs(e.clientX - d.x0) > 3) d.moved = true;
  if (!d.moved) return;
  if (d.clip) {                                       // a clip: move it or pull an edge (0.05 s steps)
    const dt = tlTime(e.clientX) - d.t0, snap = v => Math.round(v * 20) / 20, c = d.clip, full = video.duration || 1e9;
    if (d.mode === "move") { const len = d.e0 - d.s0; c.start = Math.max(0, Math.min(full - len, snap(d.s0 + dt))); c.end = c.start + len; }
    else if (d.mode === "start") c.start = Math.max(0, Math.min(d.e0 - 0.2, snap(d.s0 + dt)));
    else c.end = Math.min(full, Math.max(d.s0 + 0.2, snap(d.e0 + dt)));
    video.currentTime = d.mode === "end" ? c.end - 0.05 : c.start + 0.01;
    drawTimeline(video.currentTime, true); renderClips(true);
    return;
  }
  const dt = tlTime(e.clientX) - d.t0, snap = v => Math.round(v * 20) / 20;
  if (d.mode === "pan") { tl.from = d.from0 - (e.clientX - d.x0) / tlWidth() * tl.span; tlClamp(); }
  else if (d.mode === "move") { const len = d.e0 - d.s0; d.l.start = Math.max(0, snap(d.s0 + dt)); d.l.end = d.l.start + len; }
  else if (d.mode === "start") d.l.start = Math.max(0, Math.min(d.e0 - 0.2, snap(d.s0 + dt)));
  else d.l.end = Math.max(d.s0 + 0.2, snap(d.e0 + dt));
  if (d.l) { current = undefined; video.currentTime = d.mode === "end" ? d.l.end - 0.05 : d.l.start + 0.01; }
  drawTimeline(video.currentTime, true);
});
$("#tlView").addEventListener("pointerup", e => {
  const d = tl.drag;
  tl.drag = null;
  if (!d) return;
  if (d.clip) {
    if (!d.moved) { video.currentTime = d.clip.start + 0.01; showTab("clipsPanel"); }
    else clipTimesChanged();
    drawTimeline(video.currentTime, true);
    return;
  }
  if (!d.moved) {                                     // a click: go there (and to that line in the list)
    video.currentTime = d.l ? d.l.start + 0.01 : Math.max(0, tlTime(e.clientX));
    if (d.l) $(`.line[data-id="${d.l.id}"]`)?.scrollIntoView({ block: "center" });
  } else if (d.l && (d.l.start !== d.s0 || d.l.end !== d.e0)) {
    const l = d.l, before = lines.map(x => x.id).join();
    lines.sort((a, b) => a.start - b.start || a.end - b.end);
    const reordered = lines.map(x => x.id).join() !== before;
    patch(l, { start: Math.round(l.start * 1000) / 1000, end: Math.round(l.end * 1000) / 1000 })
      .then(() => { if (reordered) renderLines(); });
  }
  drawTimeline(video.currentTime, true);
});
$("#tlView").addEventListener("wheel", e => {
  e.preventDefault();
  if (e.ctrlKey || e.metaKey) {                       // pinch or ⌘-scroll: zoom around the pointer
    const at = tlTime(e.clientX), f = Math.exp(e.deltaY * 0.01);
    tl.span *= f; tl.from = at - (at - tl.from) * f;
  } else tl.from += (Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY) / tlWidth() * tl.span;
  tlClamp();
  tl.drag = null;
  drawTimeline(video.currentTime, true);
}, { passive: false });
$("#tlIn").onclick = () => { const mid = tl.from + tl.span / 2; tl.span /= 1.6; tl.from = mid - tl.span / 2; tlClamp(); drawTimeline(video.currentTime, true); };
$("#tlOut").onclick = () => { const mid = tl.from + tl.span / 2; tl.span *= 1.6; tl.from = mid - tl.span / 2; tlClamp(); drawTimeline(video.currentTime, true); };
new ResizeObserver(() => drawTimeline(video.currentTime, true)).observe($("#tlView"));

/* ============================================================ find and replace */

const find = { hits: [], at: -1 };
function findMatches() {
  const q = $("#findText").value.trim().toLowerCase(), where = $("#findWhere").value;
  $$(".line.match").forEach(li => li.classList.remove("match", "match-on"));
  find.hits = []; find.at = -1;
  if (q) {
    const keys = where === "both" ? ["th", "zh"] : [where];
    let n = 0;
    for (const l of lines) {
      const c = keys.reduce((s, k) => s + ((l[k] || "").toLowerCase().split(q).length - 1), 0);
      if (c) { find.hits.push(l); n += c; $(`.line[data-id="${l.id}"]`)?.classList.add("match"); }
    }
    $("#findCount").textContent = n ? `${n} match${n === 1 ? "" : "es"} in ${find.hits.length} line${find.hits.length === 1 ? "" : "s"}` : "Not found.";
  } else $("#findCount").textContent = "Type something to find.";
  $("#findGo").disabled = !find.hits.length;
}
function findStep(d) {
  if (!find.hits.length) return;
  find.at = (find.at + d + find.hits.length) % find.hits.length;
  const l = find.hits[find.at];
  $$(".line.match-on").forEach(li => li.classList.remove("match-on"));
  const li = $(`.line[data-id="${l.id}"]`);
  li?.classList.add("match-on"); li?.scrollIntoView({ block: "center" });
  video.currentTime = l.start + 0.01;
}
// Weak spots: the stretches most likely wrong (doubtful words, people talking over each other…), listed so you
// can check each and fix it with Fix a stretch, its reasons already ticked. You judge; it just finds them.
const WEAK_REASON = { "two people talking at once": "overlap", "words that look misheard": "misheard",
  "words it wasn't sure of": "misheard", "talking with too few words": "skipped" };
async function showWeakSpots() {
  try {
    const spots = await api("GET", `/api/jobs/${job.id}/weak-spots`);
    $("#weakSum").textContent = spots.length ? `${spots.length} found, in time order. Play one; if it's wrong, Fix this… opens Fix a stretch with the reasons ticked.` : "None stand out: no stretches with several doubtful lines.";
    $("#weakList").replaceChildren(...spots.map(s => {
      const li = document.createElement("li");
      const t = document.createElement("span"); t.className = "cut-t"; t.textContent = `${fmtTime(s.start).replace(/\.\d$/, "")}–${fmtTime(s.end).replace(/\.\d$/, "")}`;
      const why = document.createElement("span"); why.className = "cut-text"; why.textContent = s.why;
      const play = document.createElement("button"); play.type = "button"; play.textContent = "Play";
      play.onclick = () => { stopPreview(false); pv.on = true; pv.spans = [[s.start, s.end]]; pv.i = 0; previewJump(); video.play(); };
      const fix = document.createElement("button"); fix.type = "button"; fix.textContent = "Fix this…";
      fix.onclick = () => {
        range.from = s.start; range.to = s.end; fixPicked.clear();
        s.why.split(", ").forEach(w => WEAK_REASON[w] && fixPicked.add(WEAK_REASON[w]));
        $("#rangeBox").hidden = false; renderReasons(); renderRange();
        video.currentTime = s.start; $("#rangeBox").scrollIntoView({ block: "nearest" });
      };
      li.append(t, why, play, fix);
      return li;
    }));
    $("#weakBox").hidden = false;
  } catch (ex) { alert(ex.message); }
}
$("#weakSpots").onclick = showWeakSpots;
$("#weakClose").onclick = () => { $("#weakBox").hidden = true; };
$("#retime").onclick = async () => {
  try { await api("POST", `/api/jobs/${job.id}/retime`); refresh(job.id); } catch (ex) { alert(ex.message); }
};
$("#findOpen").onclick = () => { $("#findBox").hidden = false; $("#findText").focus(); findMatches(); };
$("#findClose").onclick = () => { $("#findBox").hidden = true; $("#findText").value = ""; findMatches(); };
["input", "change"].forEach(ev => { $("#findText").addEventListener(ev, findMatches); $("#findWhere").addEventListener(ev, findMatches); });
$("#findNext").onclick = () => findStep(1);
$("#findPrev").onclick = () => findStep(-1);
$("#findText").addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); findStep(e.shiftKey ? -1 : 1); } });
$("#findGo").onclick = async () => {
  const find_ = $("#findText").value.trim(), repl = $("#replText").value.trim();
  try {
    const r = await api("POST", `/api/jobs/${job.id}/replace`, { find: find_, replace: repl, where: $("#findWhere").value, remember: $("#findRemember").checked });
    await reloadLines();
    findMatches();
    $("#findCount").textContent = `Replaced ${r.count} in ${r.lines} line${r.lines === 1 ? "" : "s"}.` + (r.learned ? " Remembered for next time." : "");
    if (r.learned) loadMemoryCount();
  } catch (ex) { alert(ex.message); }
};

/* ============================================================ splitting, joining, keyboard */

async function reloadLines() {
  lines = await api("GET", `/api/jobs/${job.id}/lines`); linesRev = -1; renderLines(); drawTimeline(video.currentTime, true);
}
async function cutLine(l) {
  try { await api("POST", `/api/jobs/${job.id}/lines/${l.id}/cut`, { at: Math.round(video.currentTime * 1000) / 1000 }); await reloadLines(); }
  catch (ex) { alert(ex.message); }
}
async function joinLine(l) {
  try { await api("POST", `/api/jobs/${job.id}/lines/${l.id}/join`); await reloadLines(); }
  catch (ex) { alert(ex.message); }
}

// the line at the playhead, else the last one before it
function lineHere() {
  const t = video.currentTime, on = linesAt(t);
  if (on.length) return on[on.length - 1];
  let best = null;
  for (const l of lines) { if (l.start <= t) best = l; else break; }
  return best;
}

// After you click a button, tab, menu, slider or the video, the keyboard goes back to the shortcuts (otherwise
// Space presses that button again, arrows switch tabs, letters change a speaker menu, the video eats arrows).
// Moving around with Tab (keyboard only) keeps the focus where it is.
let viaKeyboard = false;
document.addEventListener("keydown", e => { if (e.key === "Tab") viaKeyboard = true; }, true);
document.addEventListener("pointerdown", () => { viaKeyboard = false; }, true);
function handBack() {
  const a = document.activeElement;
  if (viaKeyboard || !a || a === document.body || !a.closest("#jobView, header")) return;
  if (/^(BUTTON|SUMMARY|VIDEO|SELECT)$/.test(a.tagName) || (a.tagName === "INPUT" && /^(radio|checkbox|range)$/.test(a.type))) a.blur();
}
document.addEventListener("pointerup", () => setTimeout(handBack, 0));
document.addEventListener("change", e => { if (e.target.tagName === "SELECT") setTimeout(handBack, 0); });

// a small note that a shortcut did something
let toastTimer = null;
function toast(text) {
  const t = $("#toast"); t.textContent = text; t.hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => { t.hidden = true; }, 1400);
}

document.addEventListener("keydown", e => {
  if (!job || $("#jobView").hidden || e.metaKey || e.ctrlKey || e.altKey) return;
  const el = e.target;
  const typing = el.isContentEditable || /^(TEXTAREA|SELECT)$/.test(el.tagName) ||
    (el.tagName === "INPUT" && !/^(radio|checkbox|range|color)$/.test(el.type));
  if (typing || document.querySelector("dialog[open]")) return;
  if (el.tagName === "INPUT" && el.type === "range" && e.key.startsWith("Arrow")) return;            // a slider you're moving
  if (/^(BUTTON|INPUT|SUMMARY)$/.test(el.tagName) && (e.key === " " || e.key === "Enter")) return;   // Tab-focused: press it
  const l = lineHere(), t = video.currentTime;
  const go = s => { video.currentTime = Math.max(0, Math.min(video.duration || 1e9, s)); };
  let done = true;
  switch (e.key) {
    case " ": video.paused ? video.play() : video.pause(); break;
    case "ArrowLeft": go(t - (e.shiftKey ? 5 : 1)); break;
    case "ArrowRight": go(t + (e.shiftKey ? 5 : 1)); break;
    case "ArrowUp": case "ArrowDown": {
      const i = l ? lines.indexOf(l) : -1;
      const n = e.key === "ArrowUp" ? (l && t > l.start + 0.3 ? l : lines[Math.max(0, i - 1)]) : lines[Math.min(lines.length - 1, i + 1)];
      if (n) { go(n.start + 0.01); $(`.line[data-id="${n.id}"]`)?.scrollIntoView({ block: "center" }); }
      break;
    }
    case "[": if (l) { patch(l, { start: Math.round(t * 1000) / 1000 }).then(() => drawTimeline(t, true)); toast(`Starts at ${fmtTime(t)}`); } break;
    case "]": if (l) { patch(l, { end: Math.round(t * 1000) / 1000 }).then(() => drawTimeline(t, true)); toast(`Ends at ${fmtTime(t)}`); } break;
    case "s": case "S": if (l) { cutLine(l); toast("Split at the playhead"); } break;
    case "m": case "M": if (l) { joinLine(l); toast("Joined with the next line"); } break;
    case "n": case "N": stepFlag(e.shiftKey ? -1 : 1); break;
    case "f": case "F": if (l) { const li = $(`.line[data-id="${l.id}"]`); li?.scrollIntoView({ block: "center" }); $(".flag", li)?.click(); } break;
    case "Enter": if (l) { video.pause(); const z = $(`.line[data-id="${l.id}"] .zh`); z?.scrollIntoView({ block: "center" }); z?.focus(); } break;
    case "Delete": case "Backspace": if (l) $(`.line[data-id="${l.id}"] .delline`)?.click(); break;
    case "?": $("#keys").showModal(); break;
    case "i": case "I": clipIn(); break;
    case "o": case "O": clipOut(); break;
    case "l": case "L": if (!$("#rangeBox").hidden) $("#rangeLoop").click(); else done = false; break;
    default: done = false;
  }
  if (done) e.preventDefault();
});
$("#keysBtn").onclick = () => $("#keys").showModal();

/* ============================================================ tabs, More, quieter lines */

// one panel at a time under the video; the last one you used comes back
function showTab(id) {
  $$("#tabs [data-tab]").forEach(b => {
    const on = b.dataset.tab === id;
    b.setAttribute("aria-selected", String(on)); b.tabIndex = on ? 0 : -1;
    const panel = $("#" + b.dataset.tab);
    panel.hidden = !on; panel.open = on;
  });
  try { localStorage.setItem("ac-tab", id); } catch { /* fine */ }
}
$("#tabs").addEventListener("click", e => { const b = e.target.closest("[data-tab]"); if (b) showTab(b.dataset.tab); });
$("#tabs").addEventListener("keydown", e => {
  if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
  const tabs = $$("#tabs [data-tab]"), i = tabs.findIndex(b => b.getAttribute("aria-selected") === "true");
  const n = tabs[(i + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
  showTab(n.dataset.tab); n.focus(); e.preventDefault(); e.stopPropagation();
});
showTab((() => { try { return localStorage.getItem("ac-tab"); } catch { return null; } })() || "stylePanel");
$$(".stage-rest > details.panel > summary").forEach(s => s.addEventListener("click", e => e.preventDefault()));   // tabs open them

// Style → people's own fonts live with each person (People tab)
$("#toPeopleFonts").onclick = () => {
  showTab("peoplePanel");
  const f = $("#peopleList .pfont"); if (f) { f.scrollIntoView({ block: "center" }); f.focus(); }
};

// More ▾ closes after a choice, or a click anywhere else
$("#moreMenu").addEventListener("click", e => { if (e.target.closest(".more-list button")) $("#moreMenu").open = false; });
document.addEventListener("click", e => { if (!e.target.closest("#moreMenu")) $("#moreMenu").open = false; });
$("#keysBtn2").onclick = () => $("#keys").showModal();

// a line's note (what it fixed, what it first heard) shows one line until you click it
$("#lines").addEventListener("click", e => { const w = e.target.closest(".why"); if (w && !w.classList.contains("open")) w.classList.add("open"); });

/* ============================================================ clips: the scenes you like, as one video */

// Kept with the video (job.reel), in the order you put them. I starts a clip at the playhead, O ends it.
const reel = () => (job.reel = job.reel || []);
const starOnly = () => $("#starOnly").checked;
const usedClips = () => reel().filter(c => c.end - c.start >= 0.3 && (c.star || !starOnly()));
const reelSpans = () => usedClips().map(c => [c.start, c.end]);
function clipsOn() { return $("input[name=part]:checked")?.value === "clips"; }
let clipStart = null, reelTimer = null;
function reelChanged() { renderClips(); clearTimeout(reelTimer); reelTimer = setTimeout(saveReel, 500); }
function clipTimesChanged() { renderClips(true); clearTimeout(reelTimer); reelTimer = setTimeout(saveReel, 500); }   // keeps focus
async function saveReel() {
  clearTimeout(reelTimer);
  try { await api("PUT", `/api/jobs/${job.id}/reel`, { clips: reel() }); } catch (ex) { alert(ex.message); }
}
function clipIn() {
  clipStart = video.currentTime;
  $("#clipPending").textContent = `Starts at ${fmtTime(clipStart)}: press O (End it here) where it ends.`;
  toast(`Clip starts at ${fmtTime(clipStart)}`);
  drawTimeline(video.currentTime, true);
}
function clipOut() {
  const t = video.currentTime;
  if (clipStart === null || t - clipStart < 0.3) {
    toast(clipStart === null ? "Press I where the scene starts first" : "The end must be after the start");
    return;
  }
  reel().push({ id: Math.random().toString(36).slice(2, 8), start: Math.round(clipStart * 1000) / 1000, end: Math.round(t * 1000) / 1000, label: "" });
  clipStart = null; $("#clipPending").textContent = "";
  toast(`Clip ${reel().length} added (${fmtTime(t - reel()[reel().length - 1].start)})`);
  reelChanged(); drawTimeline(t, true);
}
$("#clipIn").onclick = clipIn;
$("#clipOut").onclick = clipOut;
$("#clipTicked").onclick = () => {
  const ticked = lines.filter(l => picked.has(l.id));
  if (!ticked.length) { alert("Tick lines in the list first (Shift-click ticks a range)."); return; }
  reel().push({ id: Math.random().toString(36).slice(2, 8), start: Math.max(0, ticked[0].start - 0.3), end: ticked[ticked.length - 1].end + 0.5, label: "" });
  reelChanged(); drawTimeline(video.currentTime, true);
};
function playClips(spans) { stopPreview(false); pv.on = true; pv.spans = spans; pv.i = 0; previewJump(); video.play(); }
// Only when these people talk → clips: the same parts, with all the trimming tools of the Clips tab
$("#peopleToClips").onclick = () => {
  const parts = peopleSpans();
  if (!parts.length) { alert("Tick the people first."); return; }
  const names = (job.speakers || []).filter(p => whoPicked.has(p.id)).map(p => p.name).join(" + ");
  const made = parts.map(([a, b]) => {
    const said = lines.filter(l => l.end > a && l.start < b && whoPicked.has(l.speaker)).map(l => l.zh || l.th)[0] || "";
    return { id: Math.random().toString(36).slice(2, 8), start: Math.round(a * 1000) / 1000, end: Math.round(b * 1000) / 1000,
             label: `${names}${said ? `: ${said.slice(0, 24)}` : ""}` };
  });
  if (reel().length && !confirm(`You already have ${reel().length} clip${reel().length > 1 ? "s" : ""}. Replace them with these ${made.length}?\n\n(Cancel adds these after them instead.)`)) reel().push(...made);
  else job.reel = made;
  $('input[name=part][value="clips"]').checked = true; showPart(); showPeoplePick();
  reelChanged(); drawTimeline(video.currentTime, true);
  showTab("clipsPanel");
  toast(`${made.length} parts are now clips: trim them here`);
};
$("#clipPlay").onclick = () => { if (reelSpans().length) playClips(reelSpans()); else if (starOnly()) toast("No ★ clips yet"); };
$("#starOnly").addEventListener("change", () => {
  try { localStorage.setItem("ac-star-only", $("#starOnly").checked ? "1" : ""); } catch { /* fine */ }
  renderClips(); drawTimeline(video.currentTime, true);
});
try { $("#starOnly").checked = localStorage.getItem("ac-star-only") === "1"; } catch { /* fine */ }
$("#clipSave").onclick = () => {
  $('input[name=part][value="clips"]').checked = true; showPart(); showPeoplePick(); showTab("exportPanel");
  $("#export").scrollIntoView({ block: "center" });
};

// the list: name, exact times (type them, or ↑ ↓ for 0.1 s, Shift 1 s), to the playhead, order, play, remove
function renderClips(timesOnly) {
  const cs = reel(), full = video.duration || job?.media?.duration || 1e9;
  $("#clipCount").textContent = cs.length || "";
  $("#clipsHere").textContent = cs.length ? `(${cs.length})` : "";
  const len = cs.reduce((s, c) => s + Math.max(0, c.end - c.start), 0);
  const stars = cs.filter(c => c.star), used = usedClips(), usedLen = used.reduce((s, c) => s + c.end - c.start, 0);
  $("#clipTotal").textContent = !cs.length ? "" : starOnly()
    ? `★ ${stars.length} of ${cs.length} clips, ${fmtTime(usedLen).replace(/\.\d$/, "")}`
    : `${cs.length} clip${cs.length > 1 ? "s" : ""}${stars.length ? ` (★ ${stars.length})` : ""}, ${fmtTime(len).replace(/\.\d$/, "")} in all`;
  $("#clipList").classList.toggle("star-only", starOnly());
  $("#clipsHere").textContent = cs.length ? (starOnly() ? `(★ ${stars.length})` : `(${cs.length})`) : "";
  if (timesOnly) {                        // while dragging on the timeline: just the numbers
    cs.forEach(c => { const li = $(`#clipList li[data-id="${c.id}"]`); if (!li) return;
      if (document.activeElement !== $(".clip-t.s", li)) $(".clip-t.s", li).value = fmtTime(c.start);
      if (document.activeElement !== $(".clip-t.e", li)) $(".clip-t.e", li).value = fmtTime(c.end);
      $(".clip-len", li).textContent = `${(c.end - c.start).toFixed(1)} s`; });
    return;
  }
  $("#clipList").replaceChildren(...cs.map((c, i) => {
    const li = document.createElement("li"); li.dataset.id = c.id; li.classList.toggle("playing", c.id === playingClip);
    const btn = (label, title, f) => { const b = document.createElement("button"); b.type = "button"; b.textContent = label; b.title = title; b.onclick = f; return b; };
    const n = document.createElement("span"); n.className = "clip-n"; n.textContent = i + 1;
    li.classList.toggle("starred", !!c.star);
    const star = document.createElement("button"); star.type = "button"; star.className = "clip-star";
    star.textContent = c.star ? "★" : "☆"; star.setAttribute("aria-pressed", String(!!c.star));
    star.title = c.star ? "A favourite (click to unstar)" : "Mark as a favourite";
    star.onclick = () => { c.star = !c.star || undefined; reelChanged(); drawTimeline(video.currentTime, true); };
    n.append(star);
    const name = document.createElement("input"); name.className = "field clip-label"; name.value = c.label || "";
    name.placeholder = lines.filter(l => l.end > c.start && l.start < c.end).map(l => l.zh || l.th)[0] || `Clip ${i + 1}`;
    name.oninput = () => { c.label = name.value; clearTimeout(reelTimer); reelTimer = setTimeout(saveReel, 600); };
    const time = (k, cls) => {
      const box = document.createElement("input"); box.className = `field clip-t ${cls}`; box.value = fmtTime(c[k]);
      box.setAttribute("aria-label", k === "start" ? `Clip ${i + 1} starts` : `Clip ${i + 1} ends`);
      const set = v => {
        if (v == null) { box.value = fmtTime(c[k]); return; }
        c[k] = Math.round(Math.max(0, Math.min(full, v)) * 1000) / 1000;
        if (c.end - c.start < 0.2) { if (k === "start") c.start = c.end - 0.2; else c.end = c.start + 0.2; }
        box.value = fmtTime(c[k]); video.currentTime = k === "end" ? c.end - 0.05 : c.start + 0.01;
        clipTimesChanged(); drawTimeline(video.currentTime, true);
      };
      box.onchange = () => set(parseTime(box.value));
      box.onkeydown = e => {
        if (e.key === "ArrowUp" || e.key === "ArrowDown") {
          e.preventDefault();
          set(c[k] + (e.key === "ArrowUp" ? 1 : -1) * (e.shiftKey ? 1 : 0.1));
          box.focus(); box.select();
        } else if (e.key === "Enter") box.blur();
      };
      return box;
    };
    const times = document.createElement("div"); times.className = "clip-times";
    const lenEl = document.createElement("span"); lenEl.className = "clip-len"; lenEl.textContent = `${(c.end - c.start).toFixed(1)} s`;
    times.append(btn("⇤ now", "Start at the playhead", () => { c.start = Math.min(video.currentTime, c.end - 0.2); clipTimesChanged(); drawTimeline(video.currentTime, true); }),
      time("start", "s"), "→", time("end", "e"),
      btn("now ⇥", "End at the playhead", () => { c.end = Math.max(video.currentTime, c.start + 0.2); clipTimesChanged(); drawTimeline(video.currentTime, true); }), lenEl);
    li.append(n, name,
      btn("▶", "Play this clip", () => playClips([[c.start, c.end]])),
      btn("↑", "Earlier in the reel", () => { if (i > 0) { [cs[i - 1], cs[i]] = [cs[i], cs[i - 1]]; reelChanged(); } }),
      btn("✕", "Remove this clip", () => { cs.splice(i, 1); reelChanged(); drawTimeline(video.currentTime, true); }),
      times);
    return li;
  }));
  showSizes();
}
// the clip being played (or under the playhead) stands out, in the list and on the timeline
let playingClip = null;
function markPlayingClip(t) {
  let id = null;
  if (job?.reel?.length) {
    const inPreview = pv.on && pv.spans[pv.i] && job.reel.find(c => Math.abs(c.start - pv.spans[pv.i][0]) < 0.01 && Math.abs(c.end - pv.spans[pv.i][1]) < 0.01);
    id = inPreview ? inPreview.id : (job.reel.find(c => t >= c.start && t < c.end) || {}).id || null;
  }
  if (id === playingClip) return;
  playingClip = id;
  $$("#clipList li, .tl-clip").forEach(el => el.classList.toggle("playing", !!id && el.dataset.id === id));
  // the list follows: the clip playing comes into view (unless you're typing in the list)
  const li = id && $(`#clipList li[data-id="${id}"]`);
  if (li && !$("#clipsPanel").hidden && !li.closest("#clipList").contains(document.activeElement)) {
    li.scrollIntoView({ block: "nearest", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  }
}
let clipBandsKey = "";
function drawClipBands(pps) {
  const bands = reel().map((c, i) => ({ ...c, n: i + 1 }));
  if (clipStart !== null) bands.push({ id: "pending", start: clipStart, end: Math.max(clipStart + 0.1, video.currentTime), n: "…" });
  const key = JSON.stringify(bands.map(b => [b.id, b.start, b.end, b.label, b.star])) + tl.from.toFixed(2) + pps;
  if (key === clipBandsKey) return;                 // nothing moved: leave them be
  clipBandsKey = key;
  $("#tlClips").replaceChildren(...bands.filter(c => c.end > tl.from && c.start < tl.from + tl.span).map(c => {
    const el = document.createElement("div"); el.className = `tl-clip${c.id === "pending" ? " pending" : ""}`; el.dataset.id = c.id;
    Object.assign(el.style, { left: `${(c.start - tl.from) * pps}px`, width: `${Math.max(6, (c.end - c.start) * pps)}px` });
    el.textContent = c.n; el.title = `Clip ${c.n}${c.star ? " ★" : ""}: ${fmtTime(c.start)}–${fmtTime(c.end)}${c.label ? ` · ${c.label}` : ""}`;
    if (c.star) el.classList.add("starred");
    if (c.id === playingClip) el.classList.add("playing");
    if (c.id !== "pending") { const l = document.createElement("i"), r = document.createElement("i"); l.className = "h l"; r.className = "h r"; el.append(l, r); }
    return el;
  }));
}

/* ============================================================ layout: the toolbar's place, the captions' width */

// Wide screens: the toolbar and its boxes (Fix a stretch, weak spots, find) sit under the timeline in the left
// column, next to the video they work on; the middle column keeps the tabs. Narrow: back above the tabs.
const wideLayout = matchMedia("(min-width: 1500px)");
function placeActions() {
  const a = $("#stageActions");
  if (wideLayout.matches) { if (a.parentElement !== $("#pinned")) $("#pinned").append(a); }
  else if (a.parentElement !== $("#stageRest")) $("#stageRest").prepend(a);
  applyCaptionWidth();
}
wideLayout.addEventListener("change", placeActions);

// The captions' column width: drag its left edge; remembered on this Mac (separately for 2 and 3 columns)
function captionWidthKey() { return wideLayout.matches ? "ac-capw-3" : "ac-capw-2"; }
function applyCaptionWidth(w) {
  const jobEl = $("#jobView");
  if (w === undefined) { try { w = +localStorage.getItem(captionWidthKey()) || 0; } catch { w = 0; } }
  if (!w) { jobEl.style.gridTemplateColumns = ""; return; }
  jobEl.style.gridTemplateColumns = wideLayout.matches ? `minmax(520px, 1.5fr) minmax(380px, .9fr) ${w}px` : `minmax(340px, 1fr) ${w}px`;
  requestAnimationFrame(() => { placeOverlay(); renderRail(); drawTimeline(video.currentTime, true); });
}
$("#colGrip").addEventListener("pointerdown", e => {
  e.preventDefault();
  const grip = $("#colGrip"), right = $("#jobView").getBoundingClientRect().right - 20;
  grip.setPointerCapture(e.pointerId); grip.classList.add("dragging"); document.body.classList.add("resizing");
  const min = 320, max = Math.max(min, innerWidth - (wideLayout.matches ? 940 : 380));
  let w = 0;
  grip.onpointermove = ev => { w = Math.round(Math.max(min, Math.min(max, right - ev.clientX))); applyCaptionWidth(w); };
  grip.onpointerup = () => {
    grip.onpointermove = null; grip.classList.remove("dragging"); document.body.classList.remove("resizing");
    if (w) try { localStorage.setItem(captionWidthKey(), String(w)); } catch { /* fine */ }
  };
});
$("#colGrip").addEventListener("dblclick", () => {
  try { localStorage.removeItem(captionWidthKey()); } catch { /* fine */ }
  applyCaptionWidth(0); requestAnimationFrame(() => { placeOverlay(); renderRail(); });
});
placeActions();

/* ============================================================ routing */

async function route() {
  const m = location.hash.match(/^#\/job\/([0-9a-f]{12})$/);
  if (m) return openJob(m[1]);
  clearTimeout(pollTimer);
  job = null;
  video.pause();
  $("#jobView").hidden = true; $("#startView").hidden = false; $("#flagRail").hidden = true;
  $("#topTitle").textContent = ""; document.title = "AutoCaption";
  loadJobList();
}
$("#home").onclick = () => { location.hash = ""; };
addEventListener("hashchange", route);
$("#quitApp").onclick = async () => {
  if (!confirm("Quit AutoCaption? Your work is saved.")) return;
  const quit = async force => {
    const r = await fetch("/api/quit", { method: "POST", headers: { "x-ac": "1", "content-type": "application/json" }, body: JSON.stringify({ force }) });
    if (r.status === 409) {
      const msg = (await r.json().catch(() => ({}))).detail || "A video is still being worked on.";
      if (!confirm(`${msg}\n\nQuit anyway? That step stops and you'd press it again next time.`)) return false;
      return quit(true);
    }
    return r.ok;
  };
  try {
    if (!(await quit(false))) return;
  } catch { /* already gone */ }
  clearTimeout(pollTimer); video.pause();
  $$("main, .update-bar").forEach(el => { el.hidden = true; });
  $("#closedView").hidden = false;
};

// the page is always the newest; the app behind it only after you reopen it: say so when they differ
function checkStale() { api("GET", "/api/status").then(s => { $("#updateBar").hidden = !s.stale; }).catch(() => {}); }
setInterval(checkStale, 60000);
api("GET", "/api/status").then(s => {
  $("#updateBar").hidden = !s.stale;
  $("#outDir").textContent = s.out;
  if (!s.claude) $("#formError").textContent = "The Claude command-line tool isn't installed, so it can only listen, not translate. Install Claude Code and sign in once.";
}).catch(() => {});
loadMemoryCount();
loadSettings().catch(() => {});
route();
setInterval(() => { if (!$("#startView").hidden) loadJobList(); }, 5000);

$("#videoSubs").addEventListener("change", () => { $("#subsCheck").disabled = !$("#videoSubs").checked; });
// Options stays folded; its line says what's on, so you can see it without opening it
function showOptsNow() {
  const on = [["cleanVoice", "music removed"], ["fast", "quicker listening"], ["videoSubs", "video's subtitles"], ["subsCheck", "checked against them"]]
    .filter(([id]) => $("#" + id).checked && !$("#" + id).disabled).map(([, t]) => t);
  $("#optsNow").textContent = on.length ? on.join(", ") : "none";
}
["cleanVoice", "fast", "videoSubs", "subsCheck"].forEach(id => $("#" + id).addEventListener("change", showOptsNow));
showOptsNow();
