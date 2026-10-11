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
  const cs = await collList(), sig = JSON.stringify(cs.map(c => [c.id, c.name, c.count]));
  if (sig === pick.dataset.sig) return;          // the same list: leave the open menu alone
  pick.dataset.sig = sig;
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
// the list is filled whenever you might use it: opening a video (the Clips tab may already be the open one),
// switching to Clips, and opening the menu itself (a collection made in another window shows up)
$("[data-tab=clipsPanel]").addEventListener("click", renderAddColl);
$("#addCollPick").addEventListener("pointerdown", () => { if ($("#addCollPick").options.length < 2) renderAddColl(); });
$("#addCollPick").addEventListener("focus", renderAddColl);
window.addEventListener("hashchange", () => { if (location.hash.startsWith("#/job/")) renderAddColl(); });
if (location.hash.startsWith("#/job/")) renderAddColl();

// ---------------------------------------------------------------- the collection page
async function openCollection(cid) {
  for (const k of Object.keys(srcData)) delete srcData[k];   // captions may have been edited since: fetch them fresh
  cvCapKey = "";
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

// your text: words, where, colour, size, font, how long (0 = all of the clip); more style under "Style"
const PLACES = [["top-left", "Top left"], ["top", "Top"], ["top-right", "Top right"], ["center", "Middle"], ["lower", "Lower middle"], ["bottom-left", "Bottom left"], ["bottom-right", "Bottom right"], ["custom", "Where you dragged it"]];
const PLACE_XY = { "top-left": [0.18, 0.09], "top": [0.5, 0.09], "top-right": [0.82, 0.09], "center": [0.5, 0.5], "lower": [0.5, 0.72], "bottom-left": [0.18, 0.86], "bottom-right": [0.82, 0.86] };
const placeXY = (x, fallback) => x.place === "custom" && x.x != null ? [x.x, x.y] : PLACE_XY[x.place] || PLACE_XY[fallback];
const MOVES = [["", "Still"], ["float", "Float"], ["wiggle", "Wiggle"], ["flip", "Flip"], ["pulse", "Pulse"], ["spin", "Spin"], ["fly", "Fly around"], ["across", "Fly across"]];
const styleOpen = new WeakSet();          // which overlays have their "Style" row open (kept when the list redraws)
function mkEl(tag, props = {}, ...kids) { const e = document.createElement(tag); Object.assign(e, props); e.append(...kids); return e; }
function placePicker(o, fallback) {
  const place = mkEl("select", { className: "field", title: "Where (or drag it on the picture)" });
  PLACES.forEach(([v, n]) => place.append(new Option(n, v)));
  place.value = o.place || fallback;
  place.addEventListener("input", () => {        // picking "Where you dragged it" before dragging: start from where it was
    if (place.value === "custom" && o.x == null) [o.x, o.y] = PLACE_XY[o.place] || PLACE_XY[fallback];
  }, true);
  return place;
}
// movement, its speed and how see-through: the same for text and logos
function moveControls(o, put) {
  const move = mkEl("select", { className: "field", title: "Movement" }); MOVES.forEach(([v, n]) => move.append(new Option(n, v)));
  move.value = o.motion || "";
  const speed = mkEl("input", { type: "range", min: "0.5", max: "8", step: "0.25", value: 8.5 - (o.period || 2), title: "Speed", disabled: !o.motion });
  const see = mkEl("input", { type: "range", min: "0.2", max: "1", step: "0.05", value: o.opacity || 1, title: "See-through ← → solid" });
  const read = () => {
    speed.disabled = !move.value;
    if (move.value) Object.assign(o, { motion: move.value, period: +(8.5 - speed.value).toFixed(2) }); else { delete o.motion; delete o.period; }
    o.opacity = +see.value; put();
  };
  [move, speed, see].forEach(x => x.addEventListener("input", read));
  return [mkEl("label", {}, "Movement ", move), mkEl("label", {}, "Speed ", speed), mkEl("label", {}, "Solid ", see)];
}
function styleRow(o, box, kids) {
  const more = mkEl("div", { className: "te-more", hidden: !styleOpen.has(o) }, ...kids);
  const btn = mkEl("button", { type: "button", className: "te-stylebtn", textContent: "Style" });
  btn.setAttribute("aria-expanded", String(styleOpen.has(o)));
  btn.onclick = () => {
    more.hidden = !more.hidden; btn.setAttribute("aria-expanded", String(!more.hidden));
    more.hidden ? styleOpen.delete(o) : styleOpen.add(o);
  };
  return [btn, more];
}
function textEditor(t, changed, remove, toAll) {
  const box = mkEl("div", { className: "text-edit" });
  const words = mkEl("input", { className: "field te-text", placeholder: "e.g. EP3 · 中字 by @you", value: t.text || "" });
  const place = placePicker(t, "top-left");
  const colour = mkEl("input", { type: "color", value: t.color || "#FFFFFF", title: "Colour" });
  const size = mkEl("input", { type: "range", min: "0.6", max: "3", step: "0.1", value: t.size || 1.3, title: "Size" });
  const font = mkEl("select", { className: "field" }); font.append(new Option("Font: like the captions", ""));
  (settings?.fonts?.zh || []).forEach(f => { const o = new Option(f.label, f.family); o.style.fontFamily = `"${f.family}"`; font.append(o); });
  font.value = t.font || "";
  const secs = mkEl("select", { className: "field" });
  [[0, "the whole clip"], [2, "first 2 s"], [3, "first 3 s"], [5, "first 5 s"], [8, "first 8 s"]].forEach(([v, l]) => secs.append(new Option(l, v)));
  secs.value = String(t.secs || 0);
  const x = mkEl("button", { type: "button", textContent: "Remove", onclick: remove });
  const look = mkEl("select", { className: "field", title: "Look" });
  [["plain", "Outlined"], ["bubble", "White bubble"]].forEach(([v, n]) => look.append(new Option(n, v)));
  look.value = t.bubble ? "bubble" : "plain";
  const edge = mkEl("input", { type: "color", value: t.outline_color || "#000000", title: "Outline colour" });
  const bold = mkEl("input", { type: "checkbox", checked: t.bold !== false });
  const put = () => {
    Object.assign(t, { text: words.value, place: place.value, color: colour.value, size: +size.value, font: font.value, secs: +secs.value,
      outline_color: edge.value, bold: bold.checked, bubble: look.value === "bubble" });
    colour.disabled = edge.disabled = look.value === "bubble";
    changed();
  };
  colour.disabled = edge.disabled = look.value === "bubble";
  words.oninput = put; [place, colour, size, font, secs, look, edge, bold].forEach(e => e.addEventListener("input", put));
  const [sb, more] = styleRow(t, box, [look, mkEl("label", {}, "Outline ", edge), mkEl("label", {}, bold, " Bold"), ...moveControls(t, put)]);
  box.append(words, place, colour, size, font, "for", secs, sb, ...allButton(toAll, "Same look on all clips",
    "Give every other clip's text this font, colour, size, style, place and timing (their words stay)"), x, more);
  box.ov = t; box.sync = () => { place.value = t.place; };
  return box;
}

// your logo: which one (your saved logos), where, how big, how it stands out, how long; colour, movement under "Style"
let collLogos = null;
async function savedLogos() { if (!collLogos) collLogos = await api("GET", "/api/logos").catch(() => []); return collLogos; }
function logoEditor(l, changed, remove, toAll) {
  const box = mkEl("div", { className: "text-edit" });
  const pick = mkEl("select", { className: "field te-logo" }); pick.append(new Option("Choose a logo…", ""));
  savedLogos().then(ls => { ls.forEach(x => pick.append(new Option(x.name, x.id))); pick.value = l.image || ""; });
  const place = placePicker(l, "top-right");
  const size = mkEl("input", { type: "range", min: "0.05", max: "0.5", step: "0.01", value: l.w || 0.14, title: "Size" });
  const so = mkEl("select", { className: "field", title: "So it shows on any picture" });
  [["none", "as it is"], ["outline", "outline"], ["shadow", "soft shadow"], ["badge", "on a badge"], ["circle", "in a circle"]].forEach(([v, n]) => so.append(new Option(n, v)));
  so.value = l.standout || "none";
  const secs = mkEl("select", { className: "field" });
  [[0, "the whole clip"], [2, "first 2 s"], [3, "first 3 s"], [5, "first 5 s"], [8, "first 8 s"]].forEach(([v, n]) => secs.append(new Option(n, v)));
  secs.value = String(l.secs || 0);
  const x = mkEl("button", { type: "button", textContent: "Remove", onclick: remove });
  // the outline / shadow / badge colour: one that suits the logo, or your own
  const tint = mkEl("select", { className: "field", title: "Outline, shadow or badge colour" });
  [["auto", "Colour: to suit the logo"], ["mine", "Colour: my own"]].forEach(([v, n]) => tint.append(new Option(n, v)));
  tint.value = l.edge_color ? "mine" : "auto";
  const edge = mkEl("input", { type: "color", value: l.edge_color || "#FFFFFF", hidden: !l.edge_color });
  const put = () => {
    Object.assign(l, { image: pick.value, place: place.value, w: +size.value, standout: so.value, secs: +secs.value });
    edge.hidden = tint.value !== "mine";
    if (tint.value === "mine") l.edge_color = edge.value; else delete l.edge_color;
    changed();
  };
  [pick, place, size, so, secs, tint, edge].forEach(e => e.addEventListener("input", put));
  const [sb, more] = styleRow(l, box, [tint, edge, ...moveControls(l, put)]);
  box.append(pick, place, size, so, "for", secs, sb, ...allButton(toAll, "Same on all clips",
    "Give every other clip's logo this logo, size, place, colour, movement and timing"), x, more);
  box.ov = l; box.sync = () => { place.value = l.place; };
  return box;
}

function allButton(f, label, title) {
  return f ? [mkEl("button", { type: "button", className: "te-all", textContent: label, title, onclick: f })] : [];
}

// one clip's text or logo look, given to the others (their own words stay); new ones start with the last look
const TEXT_LOOK = ["place", "x", "y", "color", "outline_color", "bold", "bubble", "opacity", "size", "font", "secs", "motion", "period"];
const LOGO_LOOK = ["image", "place", "x", "y", "w", "standout", "edge_color", "opacity", "secs", "motion", "period"];
const lastLook = { text: null, logo: null };
function lookOf(o, keys) { return Object.fromEntries(keys.filter(k => o[k] !== undefined).map(k => [k, o[k]])); }
function putLook(o, look, keys) { keys.forEach(k => { if (look[k] === undefined) delete o[k]; else o[k] = look[k]; }); }
function startLook(kind, it) {          // the look a new text or logo on a clip starts with
  const keys = kind === "text" ? TEXT_LOOK : LOGO_LOOK;
  const other = cItems().find(x => x !== it && (kind === "text" ? x.text?.text : x.logo?.image));
  return lastLook[kind] || (other ? lookOf(other[kind], keys) : null);
}
function sameOnAll(kind, it) {
  const keys = kind === "text" ? TEXT_LOOK : LOGO_LOOK, look = lookOf(it[kind], keys);
  lastLook[kind] = look;
  const others = cItems().filter(x => x !== it && (kind === "text" ? x.text?.text : x.logo?.image));
  if (!others.length) {
    toast(kind === "text" ? "No other clip has text yet. New ones will start with this look." : "No other clip has a logo yet. New ones will start like this.");
    return;
  }
  const before = others.map(x => lookOf(x[kind], keys));
  others.forEach(x => putLook(x[kind], look, keys));
  const redo = () => {
    $$(".text-edit").forEach(b => { if (others.some(x => x[kind] === b.ov)) b.remove(); });   // their open editors were out of date
    collChanged(false); drawCollTexts(true);
  };
  redo();
  toast(`${kind === "text" ? "Same look" : "Same logo"} on ${others.length} other clip${others.length === 1 ? "" : "s"}`, "Undo", () => {
    others.forEach((x, i) => putLook(x[kind], before[i], keys)); redo();
  });
}

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
function renderEveryText() {
  const t = coll.text || { text: "", place: "bottom-right", color: "#FFFFFF", size: 1.0, secs: 0 };
  $("#everyTextNow").textContent = coll.text?.text ? `“${coll.text.text}”` : "(none)";
  $("#everyTextEdit").replaceChildren(textEditor(t, () => { coll.text = t; $("#everyTextNow").textContent = t.text ? `“${t.text}”` : "(none)"; saveEveryText(); drawCollTexts(true); },
    () => { coll.text = null; saveEveryText(); renderEveryText(); drawCollTexts(true); }));
}
function renderEveryLogo() {
  const l = coll.logo || { image: "", place: "top-right", w: 0.14, standout: "none", secs: 0 };
  const name = () => (collLogos || []).find(x => x.id === coll.logo?.image)?.name;
  $("#everyLogoNow").textContent = coll.logo?.image ? `(${name() || "a logo"})` : "(none)";
  $("#everyLogoEdit").replaceChildren(logoEditor(l, () => { coll.logo = l; $("#everyLogoNow").textContent = l.image ? `(${name() || "a logo"})` : "(none)"; saveEveryLogo(); drawCollTexts(true); },
    () => { coll.logo = null; saveEveryLogo(); renderEveryLogo(); drawCollTexts(true); }));
}
let logoTimer = null;
function saveEveryLogo() {
  clearTimeout(logoTimer);
  logoTimer = setTimeout(() => api("PATCH", `/api/collections/${coll.id}`, { logo: coll.logo?.image ? coll.logo : {} }).catch(ex => alert(ex.message)), 500);
}
let everyTimer = null;
function saveEveryText() {
  clearTimeout(everyTimer);
  everyTimer = setTimeout(() => api("PATCH", `/api/collections/${coll.id}`, { text: coll.text?.text ? coll.text : {} }).catch(ex => alert(ex.message)), 500);
}
function renderColl() {
  renderCollTotals(); renderEveryText(); savedLogos().then(renderEveryLogo);
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
    const tb = btn("T", it.text ? `Text on this clip: “${it.text.text}”` : "Add your own text on this clip", () => {
      if (!it.text) it.text = { text: "", place: "top-left", color: "#FFFFFF", size: 1.3, secs: 0, ...startLook("text", it) };
      const open = li.querySelector(".text-edit:not(.logo-edit)");
      if (open) { open.remove(); return; }
      li.append(textEditor(it.text, () => { lastLook.text = lookOf(it.text, TEXT_LOOK); collChanged(false); drawCollTexts(true); },
        () => { delete it.text; collChanged(); drawCollTexts(true); }, () => sameOnAll("text", it)));
      li.querySelector(".te-text").focus();
    }, "clip-textbtn");
    tb.setAttribute("aria-pressed", String(!!it.text?.text));
    const lb = btn("🖼", it.logo ? "Your logo on this clip" : "Add your logo on this clip", () => {
      if (!it.logo) it.logo = { image: "", place: "top-right", w: 0.14, standout: "none", secs: 0, ...startLook("logo", it) };
      const open = li.querySelector(".logo-edit");
      if (open) { open.remove(); return; }
      const ed = logoEditor(it.logo, () => { lastLook.logo = lookOf(it.logo, LOGO_LOOK); collChanged(false); drawCollTexts(true); },
        () => { delete it.logo; collChanged(); drawCollTexts(true); }, () => sameOnAll("logo", it));
      ed.classList.add("logo-edit"); li.append(ed);
    }, "clip-textbtn");
    lb.setAttribute("aria-pressed", String(!!it.logo?.image));
    li.append(n, name, btn("▶", "Play this clip", () => cvPlay([it])), tb, lb, music,
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

// ---------------------------------------------------------------- captions on the preview, as each video draws them
// Each clip's video has its own captions, style, people (colours, fonts, sizes) and per-line looks: fetched once.
const srcData = {};
async function sourceOf(jid) {
  if (!srcData[jid]) {
    srcData[jid] = Promise.all([api("GET", `/api/jobs/${jid}`), api("GET", `/api/jobs/${jid}/lines`)])
      .then(([j, ls]) => ({ job: j, lines: ls.sort((a, b) => a.start - b.start) })).catch(() => null);
  }
  return srcData[jid];
}
let cvCapKey = "", cvCaptionFont = "PingFang TC";
async function drawCollCaption() {
  const m = cvideo.src.match(/\/api\/jobs\/([0-9a-f]{12})\/video/);
  const box = $("#cOvBox");
  if (!m || !settings) { box.replaceChildren(); cvCapKey = ""; return; }
  const src = await sourceOf(m[1]);
  if (!src) return;
  const t = cvideo.currentTime, on = src.lines.filter(l => l.start <= t && t < l.end);
  const which = { zh: "zh", both: "both", th: "th" }[$("input[name=cburn]:checked").value] || "both";
  const key = m[1] + on.map(l => l.id).join(",") + which + cvideo.clientWidth;
  if (key === cvCapKey) return;
  cvCapKey = key;
  const s = src.job.style || {}, theme = settings.themes.find(x => x.key === (s.theme || "classic"));
  const st = { ...settings.style_default, ...(theme ? theme.style : {}), ...s };
  if (cvCaptionFont !== st.zh_font) { cvCaptionFont = st.zh_font; drawCollTexts(true); }   // "like the captions" texts follow
  // where the picture is inside the player, and how big captions are on it (as style.py: 5.8% of the short side)
  const vw = cvideo.videoWidth || 1920, vh = cvideo.videoHeight || 1080, pb = $("#cplayer").getBoundingClientRect();
  const sc = Math.min(pb.width / vw, (cvideo.clientHeight || pb.height) / vh);
  const fr = { left: (pb.width - vw * sc) / 2, top: ((cvideo.clientHeight || pb.height) - vh * sc) / 2, w: vw * sc, h: vh * sc };
  const ov = $("#cOverlay");
  ov.style.left = `${fr.left + fr.w * 0.06}px`; ov.style.width = `${fr.w * 0.88}px`;
  if (st.position === "top") { ov.style.top = `${fr.top + fr.h * 0.05}px`; ov.style.bottom = "auto"; }
  else { ov.style.top = "auto"; ov.style.bottom = `${pb.height - (fr.top + fr.h * (st.position === "custom" ? st.y : 0.94))}px`; }
  const people = src.job.speakers || [], who = l => people.find(p => p.id === l.speaker) || {};
  const base = Math.min(vw, vh) * sc * 0.058 * st.size;
  const rows = [];
  let biggest = 0;
  for (const l of on) {
    const lk = l.look || {};
    if (lk.show === "none" || (lk.show && which !== "both" && lk.show !== which)) continue;
    const mine = lk.show && which === "both" ? lk.show : which;
    const zhPx = base * (lk.size || who(l).size || 1), thPx = mine === "both" ? zhPx * st.th_scale : zhPx;
    biggest = Math.max(biggest, zhPx);
    const colour = lk.color || who(l).color, zf = lk.font || who(l).font;
    const pair = [];
    if (lk.text) pair.push([lk.text, zhPx, which === "th"]);
    else {
      const th = l.kind === "sound" ? "" : (l.th || ""), zh = l.zh || "";
      if (mine !== "zh" && th) pair.push([th, thPx, true]);
      if (mine !== "th" && zh) pair.push([zh, zhPx, false]);
      if (st.order === "zh_above") pair.reverse();
    }
    pair.forEach(([text, px, isTh]) => {
      const el = document.createElement("div"); el.className = "ov-row";
      fillPainted(el, text, l.paint, isTh ? "th" : "zh");
      Object.assign(el.style, rowCss(st, px, isTh && mine === "both"), { marginTop: rows.length ? `${base * 0.12}px` : "0" });
      if (colour) el.style.color = colour;
      if (lk.bold !== undefined) el.style.fontWeight = lk.bold ? "700" : "500";
      if (zf && !isTh) el.style.fontFamily = `"${zf}", "PingFang TC", sans-serif`;
      rows.push(el);
    });
  }
  box.replaceChildren(...rows);
  box.style.background = "none"; box.style.padding = "0";
  if (st.box && rows.length) Object.assign(box.style, { background: st.box_color, padding: `${biggest * 0.19}px ${biggest * 0.32}px`, borderRadius: `${biggest * 0.25}px` });
}
let cvTextKey = "", cvFrame = null, cvClipStart = 0, cvDrag = null;
function drawCollTexts(force) {
  if (cvDrag) return;                    // not while you're moving one
  const it = cvQueue[cvAt] || cItems().find(i => i.id === cvPlaying);
  const t = cvideo.currentTime, show = [];
  if (it && cvideo.src.endsWith(`/api/jobs/${it.jid}/video`) && t >= it.start - 0.05 && t <= it.end + 0.05) {
    for (const x of [it.text, coll?.text, it.logo, coll?.logo]) if ((x?.text || x?.image) && (!x.secs || t - it.start < x.secs)) show.push(x);
    cvClipStart = it.start;
  }
  const key = JSON.stringify(show) + cvideo.clientWidth;
  if (key === cvTextKey && !force) return;
  cvTextKey = key;
  const vw = cvideo.videoWidth || 1920, vh = cvideo.videoHeight || 1080, pb = $("#cplayer").getBoundingClientRect();
  const sc = Math.min(pb.width / vw, (cvideo.clientHeight || pb.height) / vh);
  const fr = cvFrame = { left: (pb.width - vw * sc) / 2, top: ((cvideo.clientHeight || pb.height) - vh * sc) / 2, w: vw * sc, h: vh * sc };
  const base = Math.min(vw, vh) * sc * 0.058;
  $("#cTexts").replaceChildren(...show.map(x => {
    let node;
    if (x.image) {                       // a logo: its width is a share of the picture's width, as when saved
      const [px, py] = placeXY(x, "top-right");
      node = document.createElement("img");
      node.src = `/api/logos/${x.image}`; node.alt = ""; node.className = x.standout && x.standout !== "none" ? `so-${x.standout}` : "";
      const light = ((collLogos || []).find(g => g.id === x.image) || {}).tone !== "dark";      // a light logo gets a dark badge
      const edge = x.edge_color || (light ? "#000000" : "#FFFFFF");
      if (x.standout === "badge" || x.standout === "circle") node.style.background = x.edge_color ? x.edge_color + "D9" : light ? "rgba(29,37,80,.85)" : "rgba(255,255,255,.85)";
      if (x.standout === "outline") node.style.filter = `drop-shadow(0 0 1.5px ${edge}) drop-shadow(0 0 1.5px ${edge})`;
      if (x.standout === "shadow") node.style.filter = `drop-shadow(0 2px 6px ${edge}D9)`;
      Object.assign(node.style, { left: `${fr.left + fr.w * px}px`, top: `${fr.top + fr.h * py}px`, width: `${fr.w * (x.w || 0.14)}px` });
    } else {
      const [px, py] = placeXY(x, "top-left"), size = base * (x.size || 1.3);
      node = document.createElement("div"); node.textContent = x.text;
      Object.assign(node.style, { left: `${fr.left + fr.w * px}px`, top: `${fr.top + fr.h * py}px`, fontSize: `${size}px`,
        fontFamily: `"${x.font || cvCaptionFont}", "PingFang TC", sans-serif` });
      if (x.bubble) Object.assign(node.style, { color: "#3A2A3A", background: "#FFFFFFEE", padding: `${size * 0.35}px`, borderRadius: `${size * 0.6}px` });
      else Object.assign(node.style, { color: x.color || "#FFFFFF", webkitTextStroke: `${size * 0.2}px ${x.outline_color || "#000000"}`,
        fontWeight: x.bold === false ? "500" : "700" });
    }
    node.style.opacity = x.opacity ?? 1;
    node.ov = x; node.title = "Drag to move it";
    collMove(node, x);
    return node;
  }));
}
// the same movements the saved video gets, starting with the clip
function collMove(node, x) {
  if (!x.motion || !cvFrame) return;
  const p = x.period || 2, fr = cvFrame, [px] = placeXY(x, x.image ? "top-right" : "top-left"), left = fr.left + px * fr.w;
  node.classList.add("mv", `mv-${x.motion}`);
  node.classList.toggle("paused", cvideo.paused);
  node.style.setProperty("--p", `${p}s`);
  node.style.setProperty("--ay", `${(x.motion === "fly" ? 0.045 : 0.015) * fr.h}px`);
  node.style.setProperty("--ax", `${0.07 * fr.w}px`);
  node.style.setProperty("--x0", `${fr.left - left - fr.w * 0.06}px`);
  node.style.setProperty("--x1", `${fr.left + fr.w - left + fr.w * 0.06}px`);
  node.style.animationDelay = `-${(Math.max(0, cvideo.currentTime - cvClipStart) % p).toFixed(2)}s`;
}
["play", "pause", "seeked"].forEach(ev => cvideo.addEventListener(ev, () => $$("#cTexts .mv").forEach(n => {
  n.classList.toggle("paused", cvideo.paused);
  n.style.animationDelay = `-${(Math.max(0, cvideo.currentTime - cvClipStart) % (n.ov?.period || 2)).toFixed(2)}s`;
})));
// drag your text or logo on the picture: it stays where you put it, in the saved video too
$("#cTexts").addEventListener("pointerdown", e => {
  const node = e.target.closest("#cTexts > *");
  if (!node?.ov || !cvFrame || e.button !== 0) return;
  e.preventDefault();
  node.setPointerCapture(e.pointerId);
  node.classList.remove("mv"); node.classList.add("dragging");
  cvDrag = { node, o: node.ov, moved: false };
});
$("#cTexts").addEventListener("pointermove", e => {
  if (!cvDrag) return;
  const pb = $("#cplayer").getBoundingClientRect(), fr = cvFrame;
  const fx = Math.min(0.98, Math.max(0.02, (e.clientX - pb.left - fr.left) / fr.w));
  const fy = Math.min(0.98, Math.max(0.02, (e.clientY - pb.top - fr.top) / fr.h));
  Object.assign(cvDrag, { fx, fy, moved: true });
  Object.assign(cvDrag.node.style, { left: `${fr.left + fr.w * fx}px`, top: `${fr.top + fr.h * fy}px` });
});
function collDrop() {
  if (!cvDrag) return;
  const { o, moved, fx, fy } = cvDrag;
  cvDrag = null;
  if (moved) {
    Object.assign(o, { place: "custom", x: +fx.toFixed(4), y: +fy.toFixed(4) });
    $$(".text-edit").forEach(b => { if (b.ov === o) b.sync(); });
    if (o === coll?.text) saveEveryText(); else if (o === coll?.logo) saveEveryLogo();
    else { if (o.image) lastLook.logo = lookOf(o, LOGO_LOOK); else lastLook.text = lookOf(o, TEXT_LOOK); collChanged(false); }
  }
  drawCollTexts(true);
}
$("#cTexts").addEventListener("pointerup", collDrop);
$("#cTexts").addEventListener("pointercancel", collDrop);
["timeupdate", "seeked", "loadedmetadata"].forEach(ev => cvideo.addEventListener(ev, () => drawCollTexts()));
["timeupdate", "seeked", "loadedmetadata"].forEach(ev => cvideo.addEventListener(ev, drawCollCaption));
cvideo.addEventListener("play", function loop() { drawCollCaption(); if (!cvideo.paused) requestAnimationFrame(loop); });
$$("input[name=cburn]").forEach(r => r.addEventListener("change", () => { cvCapKey = ""; drawCollCaption(); }));
new ResizeObserver(() => { cvCapKey = ""; drawCollCaption(); }).observe($("#cplayer"));

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
window.acOpenCollection = cid => openCollection(cid);
window.renderCollHome = renderCollHome;
window.acCloseCollection = closeCollection;
renderCollHome();
if (location.hash.startsWith("#/collections")) route();
