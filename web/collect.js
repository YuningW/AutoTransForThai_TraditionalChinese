"use strict";
/* Collections: clips from any of your videos, under a name, in your order; saved as one video (or one file per
   clip). Uses the helpers in app.js ($, $$, api, fmtTime, parseTime, toast). The server side is ac/collect.py. */

let coll = null, collTimer = null, collPoll = null;
const cvideo = $("#cvideo");

async function collList() { try { return await api("GET", "/api/collections"); } catch { return []; } }

// ---------------------------------------------------------------- the start page and the top bar
async function renderCollHome() {
  const cs = await collList();
  $("#collCount").textContent = cs.length || "";
  $("#noColls").hidden = cs.length > 0;
  $("#collList").replaceChildren(...cs.map(c => {
    const li = document.createElement("li");
    const a = document.createElement("a"); a.href = `#/collections/${c.id}`;
    const t = document.createElement("span"); t.className = "jt"; t.textContent = c.name;
    const m = document.createElement("span"); m.className = "js"; m.textContent = `${c.count} clip${c.count === 1 ? "" : "s"}, ${fmtTime(c.seconds).replace(/\.\d$/, "")}`;
    a.append(t, m); li.append(a); return li;
  }));
}
async function newCollection(goThere = true) {
  const name = prompt("Name the new collection:", "");
  if (name === null) return null;
  const c = await api("POST", "/api/collections", { name: name.trim() || "New collection" });
  if (goThere) location.hash = `#/collections/${c.id}`;
  return c;
}
$("#openCollections").onclick = async () => {
  const cs = await collList();
  location.hash = cs.length ? `#/collections/${cs[0].id}` : "#/collections";
};
$("#newCollectionHome").onclick = () => newCollection();

// ---------------------------------------------------------------- a video's Clips tab: Add to collection
async function renderAddColl() {
  const pick = $("#addCollPick"), keep = pick.value || localStorage.getItem("ac-coll") || "";
  const cs = await collList();
  pick.replaceChildren(...cs.map(c => new Option(`${c.name} (${c.count})`, c.id)), new Option("+ New collection…", "new"));
  pick.value = cs.some(c => c.id === keep) ? keep : (cs[0]?.id || "new");
}
async function addToCollection(clips) {
  let cid = $("#addCollPick").value;
  if (cid === "new" || !cid) { const c = await newCollection(false); if (!c) return; cid = c.id; }
  try { localStorage.setItem("ac-coll", cid); } catch { /* fine */ }
  if (!clips.length) { toast("Make clips first (I and O)"); return; }
  try {
    const r = await api("POST", `/api/collections/${cid}/add`, { jid: job.id, clips });
    await renderAddColl(); renderCollHome();
    toast(`Added ${r.added} clip${r.added === 1 ? "" : "s"} to “${r.name}”`, "Open", () => { location.hash = `#/collections/${cid}`; });
  } catch (ex) { alert(ex.message); }
}
$("#addCollGo").onclick = () => addToCollection(usedClips().map(c => ({ start: c.start, end: c.end, star: c.star, no_music: c.no_music,
  label: c.label || (lines.find(l => l.end > c.start && l.start < c.end) || {}).zh || "" })));    // unnamed: its first caption
$("#addCollPick").addEventListener("change", async e => {
  if (e.target.value === "new") { const c = await newCollection(false); if (c) { localStorage.setItem("ac-coll", c.id); await renderAddColl(); } }
  else try { localStorage.setItem("ac-coll", e.target.value); } catch { /* fine */ }
});
$("[data-tab=clipsPanel]").addEventListener("click", renderAddColl);

// ---------------------------------------------------------------- the collection page
async function openCollection(cid) {
  $("#startView").hidden = true; $("#jobView").hidden = true; $("#collView").hidden = false; $("#flagRail").hidden = true;
  document.title = "Collections · AutoCaption";
  const cs = await collList();
  if (!cid) {
    if (cs.length) { location.hash = `#/collections/${cs[0].id}`; return; }
    const c = await newCollection(false);
    location.hash = c ? `#/collections/${c.id}` : ""; return;
  }
  $("#collPick").replaceChildren(...cs.map(c => new Option(c.name, c.id)), new Option("+ New collection…", "new"));
  $("#collPick").value = cid;
  try { coll = await api("GET", `/api/collections/${cid}`); } catch (ex) { alert(ex.message); location.hash = ""; return; }
  $("#topTitle").textContent = coll.name;
  $("#collName").value = coll.name;
  $("#cfileName").value = "";
  try { $("#cStarOnly").checked = localStorage.getItem("ac-cstar") === "1"; } catch { /* fine */ }
  renderColl(); renderCollStatus();
}
function closeCollection() { $("#collView").hidden = true; cvideo.pause(); clearTimeout(collPoll); coll = null; }
$("#collPick").addEventListener("change", async e => {
  if (e.target.value === "new") { const c = await newCollection(); if (!c) e.target.value = coll?.id || ""; }
  else location.hash = `#/collections/${e.target.value}`;
});
$("#collNew").onclick = () => newCollection();
$("#collName").addEventListener("change", async e => {
  const name = e.target.value.trim();
  if (!coll || !name || name === coll.name) return;
  coll = await api("PATCH", `/api/collections/${coll.id}`, { name });
  $("#topTitle").textContent = coll.name; toast("Renamed"); renderCollHome();
  const o = [...$("#collPick").options].find(o => o.value === coll.id); if (o) o.textContent = coll.name;
});
$("#collDelete").onclick = async () => {
  if (!coll || !confirm(`Delete the collection “${coll.name}”? Your videos and their clips stay; only this list goes.`)) return;
  await api("DELETE", `/api/collections/${coll.id}`);
  location.hash = "#/collections";
};

const cItems = () => coll?.items || [];
const cUsed = () => cItems().filter(i => i.end - i.start >= 0.3 && (i.star || !$("#cStarOnly").checked));
function collChanged(redraw = true) {
  if (redraw) renderColl(); else renderCollTotals();
  clearTimeout(collTimer);
  collTimer = setTimeout(async () => {
    try { const c = await api("PATCH", `/api/collections/${coll.id}`, { items: cItems() }); coll.videos = c.videos; }
    catch (ex) { alert(ex.message); }
  }, 500);
}
function renderCollTotals() {
  const all = cItems(), used = cUsed(), stars = all.filter(i => i.star).length;
  const len = used.reduce((s, i) => s + i.end - i.start, 0);
  $("#cTotal").textContent = all.length ? `${used.length} of ${all.length} clip${all.length === 1 ? "" : "s"}${stars ? ` (★ ${stars})` : ""}, ${fmtTime(len).replace(/\.\d$/, "")}` : "";
  $("#cEmpty").hidden = all.length > 0;
  $("#cList").classList.toggle("star-only", $("#cStarOnly").checked);
}
function renderColl() {
  renderCollTotals();
  const items = cItems();
  $("#cList").replaceChildren(...items.map((it, i) => {
    const li = document.createElement("li"); li.dataset.id = it.id;
    li.classList.toggle("starred", !!it.star); li.classList.toggle("playing", it.id === cvPlaying);
    const btn = (label, title, f, cls = "") => { const b = document.createElement("button"); b.type = "button"; b.textContent = label; b.title = title; b.onclick = f; if (cls) b.className = cls; return b; };
    const n = document.createElement("span"); n.className = "clip-n"; n.textContent = i + 1;
    const star = btn(it.star ? "★" : "☆", it.star ? "A favourite (click to unstar)" : "Mark as a favourite", () => { it.star = !it.star || undefined; collChanged(); }, "clip-star");
    star.setAttribute("aria-pressed", String(!!it.star)); n.append(star);
    const name = document.createElement("input"); name.className = "field clip-label"; name.value = it.label || "";
    name.placeholder = `Clip ${i + 1}`; name.oninput = () => { it.label = name.value; collChanged(false); };
    const music = btn("♪", it.no_music ? "Music will be taken out of this clip (click to keep it)" : "Take the music out of this clip when saved",
      () => { it.no_music = !it.no_music || undefined; collChanged(); }, "clip-music");
    music.setAttribute("aria-pressed", String(!!it.no_music));
    const v = coll.videos?.[it.jid] || {};
    const src = document.createElement("div"); src.className = "clip-src";
    const link = document.createElement("a"); link.href = `#/job/${it.jid}`; link.textContent = v.title || "a video"; link.title = "Open that video";
    src.append("from ", link);
    const time = k => {
      const box = document.createElement("input"); box.className = `field clip-t`; box.value = fmtTime(it[k]);
      const set = t => {
        if (t == null) { box.value = fmtTime(it[k]); return; }
        it[k] = Math.round(Math.max(0, Math.min(v.duration || 1e9, t)) * 1000) / 1000;
        if (it.end - it.start < 0.3) { if (k === "start") it.start = it.end - 0.3; else it.end = it.start + 0.3; }
        box.value = fmtTime(it[k]); $(".clip-len", li).textContent = `${(it.end - it.start).toFixed(1)} s`;
        cvShow(it, k === "end" ? it.end - 0.05 : it.start + 0.01); collChanged(false);
      };
      box.onchange = () => set(parseTime(box.value));
      box.onkeydown = e => {
        if (e.key === "ArrowUp" || e.key === "ArrowDown") { e.preventDefault(); set(it[k] + (e.key === "ArrowUp" ? 1 : -1) * (e.shiftKey ? 1 : 0.1)); }
        else if (e.key === "Enter") box.blur();
      };
      return box;
    };
    const times = document.createElement("div"); times.className = "clip-times";
    const lenEl = document.createElement("span"); lenEl.className = "clip-len"; lenEl.textContent = `${(it.end - it.start).toFixed(1)} s`;
    times.append(time("start"), "→", time("end"), lenEl);
    li.append(n, name, btn("▶", "Play this clip", () => cvPlay([it])), music,
      btn("↑", "Earlier", () => { if (i > 0) { [items[i - 1], items[i]] = [items[i], items[i - 1]]; collChanged(); } }),
      btn("✕", "Remove from the collection", () => { items.splice(i, 1); collChanged(); }),
      src, times);
    return li;
  }));
}
$("#cStarOnly").addEventListener("change", () => {
  try { localStorage.setItem("ac-cstar", $("#cStarOnly").checked ? "1" : ""); } catch { /* fine */ }
  renderCollTotals();
});

// ---------------------------------------------------------------- playing clips from different videos, in order
let cvQueue = [], cvAt = 0, cvPlaying = null;
function cvShow(it, t) {                          // show one moment of a clip (loads its video if needed)
  const src = `/api/jobs/${it.jid}/video`;
  if (!cvideo.src.endsWith(src)) { cvideo.src = src; cvideo.addEventListener("loadedmetadata", () => { cvideo.currentTime = t; }, { once: true }); }
  else cvideo.currentTime = t;
}
function cvPlay(list) { cvQueue = list; cvAt = 0; cvStart(); }
function cvStart() {
  const it = cvQueue[cvAt];
  if (!it) { cvideo.pause(); cvMark(null); $("#cvNow").textContent = "Done."; return; }
  cvMark(it.id);
  const v = coll.videos?.[it.jid] || {};
  $("#cvNow").textContent = `Clip ${cItems().indexOf(it) + 1}${it.label ? `: ${it.label}` : ""} · from ${v.title || "a video"}${cvQueue.length > 1 ? ` · ${cvAt + 1} of ${cvQueue.length}` : ""}`;
  const go = () => { cvideo.currentTime = it.start; cvideo.play(); };
  const src = `/api/jobs/${it.jid}/video`;
  if (!cvideo.src.endsWith(src)) { cvideo.src = src; cvideo.addEventListener("loadedmetadata", go, { once: true }); } else go();
}
function cvMark(id) {
  cvPlaying = id;
  $$("#cList li").forEach(li => li.classList.toggle("playing", li.dataset.id === id));
  const li = id && $(`#cList li[data-id="${id}"]`);
  if (li) li.scrollIntoView({ block: "nearest", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
}
cvideo.addEventListener("timeupdate", () => {
  const it = cvQueue[cvAt];
  if (it && cvideo.currentTime >= it.end - 0.03) { cvAt++; cvStart(); }
});
cvideo.addEventListener("pause", () => { if (cvideo.currentTime < (cvQueue[cvAt]?.end ?? 0) - 0.1) { /* paused by you: keep the place */ } });
$("#cPlayAll").onclick = () => { if (cUsed().length) cvPlay(cUsed()); };

// ---------------------------------------------------------------- saving
$$("input[name=cshape]").forEach(r => r.addEventListener("change", () => { $("#cfitRow").hidden = $("input[name=cshape]:checked").value !== "vertical"; }));
$("#cfitRow").hidden = true;
try {
  const srt = JSON.parse(localStorage.getItem("ac-srt") || "null") || ["zh", "both", "th"];
  $$("input[name=csrt]").forEach(b => { b.checked = srt.includes(b.value); });
} catch { /* fine */ }
$("#cSave").onclick = async () => {
  if (!coll) return;
  clearTimeout(collTimer);
  try { await api("PATCH", `/api/collections/${coll.id}`, { items: cItems() }); } catch { /* the save below says what's wrong */ }
  const vertical = $("input[name=cshape]:checked").value === "vertical";
  const shape = { vertical, fit: $("#cfit").value, size: $("input[name=csize]:checked").value, apart: $("input[name=capart]:checked").value === "1",
                  fade: $("#cfade").checked, no_music: $("#cnomusic").checked, starred: $("#cStarOnly").checked };
  try {
    coll = await api("POST", `/api/collections/${coll.id}/export`, {
      burn: $("input[name=cburn]:checked").value, srt: $$("input[name=csrt]:checked").map(b => b.value), shape, name: $("#cfileName").value.trim() || null });
    renderCollStatus();
  } catch (ex) { alert(ex.message); }
};
async function renderCollStatus() {
  clearTimeout(collPoll);
  if (!coll) return;
  try { const c = await api("GET", `/api/collections/${coll.id}`); coll.busy = c.busy; coll.label = c.label; coll.progress = c.progress; coll.error = c.error; coll.exports = c.exports; }
  catch { return; }
  $("#cStatus").hidden = !coll.busy;
  $("#cStatusText").textContent = coll.label || "Saving";
  $("#cBar").style.width = `${Math.round((coll.progress || 0) * 100)}%`;
  $("#cError").textContent = coll.error || "";
  $("#cSave").disabled = !!coll.busy;
  $("#cExports").replaceChildren(...(coll.exports || []).map(x => {
    const li = document.createElement("li"), b = document.createElement("button");
    b.type = "button"; b.className = "linkish"; b.textContent = x.path.split("/").pop(); b.title = "Show in Finder";
    b.onclick = () => api("POST", "/api/reveal", { path: x.path }).catch(ex => alert(ex.message));
    li.append(b); return li;
  }));
  if (coll.busy) collPoll = setTimeout(renderCollStatus, 1000);
}

// ---------------------------------------------------------------- routing (app.js asks us for #/collections)
window.openCollections = cid => openCollection(cid);
window.renderCollHome = renderCollHome;
window.closeCollections = closeCollection;
renderCollHome();
if (location.hash.startsWith("#/collections")) route();
