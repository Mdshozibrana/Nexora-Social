// Nexora Mini App — feed, posting, likes, comments, profiles, follow,
// search, referrals and points, all against the FastAPI backend.
// Login is the Telegram initData sent with every request (see /auth).
const tg = window.Telegram.WebApp;
tg.ready();
tg.expand();
// Phase 23: stop Telegram's sheet gestures from fighting the page's
// own scrolling (Bot API 7.7+; older clients simply ignore this).
if (tg.disableVerticalSwipes) tg.disableVerticalSwipes();

const initData = tg.initData || "";
let me = null;
// Phase 28: /media requires the short-lived signed token issued by
// /auth — <img>/<video> tags cannot send the login header, so the
// capability rides in the URL and expires (see mediaUrl).
let mediaToken = "";
function mediaUrl(id) {
  return "/media/" + encodeURIComponent(id || "") +
    (mediaToken ? "?mt=" + encodeURIComponent(mediaToken) : "");
}
let tab = "explore";
let feedCursor = null;
let profileId = null;
let profileCursor = null;

const $ = id => document.getElementById(id);

// Phase 20: while the admin acts as a managed user, every request
// carries the act-as header and the server resolves the caller to
// that managed member (admins only, managed targets only).
function actAsId() { return sessionStorage.getItem("nx_actas") || ""; }

async function api(path, options = {}) {
  const res = await fetch(path, {
    ...options,
    headers: { "X-Init-Data": initData, "Content-Type": "application/json",
               ...(actAsId() ? { "X-Act-As": actAsId() } : {}),
               ...(options.headers || {}) },
  });
  if (!res.ok) throw new Error("API " + res.status);
  return res.json();
}

async function apiForm(path, form) {
  const res = await fetch(path, { method: "POST",
    headers: { "X-Init-Data": initData,
               ...(actAsId() ? { "X-Act-As": actAsId() } : {}) },
    body: form });
  if (!res.ok) {
    let msg = "API " + res.status;
    try { const j = await res.json(); if (j.detail) msg = j.detail; }
    catch (e) { /* keep the generic message */ }
    throw new Error(msg);
  }
  return res.json();
}

// Phase 19: uploads of real phone videos can take a while on mobile
// data, and a frozen "Uploading…" made members give up. XHR reports
// real progress; onProgress(percent|null) — null once the file is with
// the server and it is converting/processing.
function apiFormProgress(path, form, onProgress, uploadId) {
  return new Promise((resolve, reject) => {
    // Phase 27: when the XHR dies at network level (the Telegram
    // WebView drops some file uploads outright — the owner watched
    // it happen), retry ONCE over fetch with the same upload id.
    // The server dedupes by that id, so a retry can never create a
    // duplicate post even if the first attempt secretly landed.
    let retried = false;
    const fetchRetry = async () => {
      if (retried) return;
      retried = true;
      onProgress(null);
      try {
        const res = await fetch(path, { method: "POST",
          headers: { "X-Init-Data": initData,
                     ...(actAsId() ? { "X-Act-As": actAsId() } : {}),
                     ...(uploadId ? { "X-Upload-Id": uploadId } : {}) },
          body: form });
        let j = null;
        try { j = await res.json(); } catch (e) {}
        if (res.status >= 200 && res.status < 300) resolve(j || {});
        else reject(new Error((j && j.detail) || ("API " + res.status)));
      } catch (e) {
        reject(new Error("Upload failed — check your connection " +
                         "and try again"));
      }
    };
    const xhr = new XMLHttpRequest();
    xhr.open("POST", path);
    xhr.setRequestHeader("X-Init-Data", initData);
    if (actAsId()) xhr.setRequestHeader("X-Act-As", actAsId());
    if (uploadId) xhr.setRequestHeader("X-Upload-Id", uploadId);
    xhr.upload.onprogress = e => {
      if (e.lengthComputable) onProgress(Math.round(e.loaded / e.total * 100));
    };
    xhr.upload.onload = () => onProgress(null);
    xhr.onload = () => {
      let j = null;
      try { j = JSON.parse(xhr.responseText); } catch (e) {}
      if (xhr.status >= 200 && xhr.status < 300) resolve(j || {});
      else reject(new Error((j && j.detail) || ("API " + xhr.status)));
    };
    xhr.onerror = () => fetchRetry();
    xhr.timeout = 180000;
    xhr.ontimeout = () => fetchRetry();
    xhr.send(form);
  });
}

function newUploadId() {
  return "u" + Date.now().toString(36) +
    Math.random().toString(36).slice(2, 10);
}

// Phase 33: shrink photos IN THE BROWSER before upload. The
// owner's remaining upload failures are network-level deaths of
// the phone → server request (both XHR and the fetch retry die
// without any response): a 3–8 MB camera JPG is exactly the kind
// of payload that fragile path drops. The same photo at max
// 1600px is typically 300–700 KB — five to ten times less data in
// flight — while staying far sharper than any size the app ever
// displays (feed and gallery render below 800px wide). Videos are
// untouched (they take the background path), HEIC is untouched
// (the server converts it), PNG keeps its format (transparency),
// and ANY failure falls back to the original file untouched.
async function shrinkForUpload(file) {
  try {
    if (!file || !/^image\//.test(file.type || "")) return file;
    if (/heic|heif/i.test(file.type)
        || /\.(heic|heif)$/i.test(file.name || "")) return file;
    if (file.size <= 700 * 1024) return file;
    const url = URL.createObjectURL(file);
    try {
      const img = await new Promise((res, rej) => {
        const i = new Image();
        i.onload = () => res(i);
        i.onerror = rej;
        i.src = url;
      });
      const MAX = 1600;
      const scale = Math.min(
        1, MAX / Math.max(img.naturalWidth, img.naturalHeight));
      if (scale >= 1) return file;
      const canvas = document.createElement("canvas");
      canvas.width = Math.round(img.naturalWidth * scale);
      canvas.height = Math.round(img.naturalHeight * scale);
      canvas.getContext("2d").drawImage(
        img, 0, 0, canvas.width, canvas.height);
      const isPng = /png/i.test(file.type);
      const blob = await new Promise(
        res => canvas.toBlob(res, isPng ? "image/png" : "image/jpeg",
                             0.85));
      if (!blob || blob.size >= file.size) return file;
      const base = (file.name || "photo").replace(/\.\w+$/, "");
      return new File([blob], base + (isPng ? ".png" : ".jpg"),
                      { type: blob.type });
    } finally { URL.revokeObjectURL(url); }
  } catch (e) { return file; }
}

function setStatus(msg) { $("status").textContent = msg || ""; }

// ---------------------------------------------------------------
// Phase 30 (owner report): a video kept playing after being
// scrolled past and after switching to another page. One lifecycle
// now governs every <video> in the app:
//  · only one video plays at a time (a starting video pauses the
//    rest, via the capture-phase "play" listener below);
//  · feed/profile videos pause when scrolled out of the shell
//    (feedVidObserver, observed at creation in postCard);
//  · every view switch pauses everything (showView);
//  · hiding the app (switching chats, minimising) pauses everything.
// Reels keep their own observer for autoplay; this layer only ever
// pauses, so the two never fight.
function pauseAllVideos(except) {
  document.querySelectorAll("video").forEach(v => {
    if (v !== except && !v.paused) v.pause();
  });
}
document.addEventListener("play", e => {
  if (e.target && e.target.tagName === "VIDEO") pauseAllVideos(e.target);
}, true);
document.addEventListener("visibilitychange", () => {
  if (document.hidden) pauseAllVideos();
});
const feedVidObserver = new IntersectionObserver(entries => {
  entries.forEach(en => { if (!en.isIntersecting) en.target.pause(); });
}, { root: document.getElementById("app-scroll"), threshold: 0.2 });

// Phase 31 (owner request): UNIQUE view counting. The client fires
// one view event per item per session (Set-guarded); the server
// dedupes per member forever, so the 👁 counts are real people,
// not replays. onViews receives the server's fresh total.
const viewedItems = new Set();
function markViewed(kind, id, onViews) {
  const key = kind + ":" + id;
  if (viewedItems.has(key)) return;
  viewedItems.add(key);
  api("/" + kind + "/" + id + "/view", { method: "POST" })
    .then(r => { if (onViews) onViews(r.views); })
    .catch(() => {});
}

function showView(name, viaBack) {
  // Phase 20: defense in depth — the admin view refuses to open for
  // non-admins even if triggered programmatically (the API is guarded
  // too; this keeps the shell itself private as the owner expects).
  if (name === "admin" && !(me && me.is_admin)) name = "feed";
  // Phase 77: remember where we came from, so Telegram's back
  // button walks back through the app instead of leaving it.
  if (!viaBack && name !== currentView) {
    if (viewStack[viewStack.length - 1] !== currentView)
      viewStack.push(currentView);
    if (viewStack.length > 30) viewStack.shift();
  }
  currentView = name;
  // Phase 30: no video may follow the member to another page.
  pauseAllVideos();
  // Phase 23: each view starts at the top of the app shell.
  const sc = $("app-scroll");
  if (sc) sc.scrollTop = 0;
  const navFor = { feed: "nav-feed", videos: "nav-videos",
                   designs: "nav-design",
                   games: "nav-games",
                   game: "nav-games", tasks: "nav-tasks",
                   leaderboard: "nav-ranks", profile: "nav-me" };
  ["feed", "videos", "designs", "search", "tasks", "leaderboard", "profile", "saved", "shared", "games", "game", "admin", "notifications", "messages", "chat", "assistant", "nearby", "museum"].forEach(v => {
    $("view-" + v).hidden = v !== name;
  });
  // Phase 21: only tab views move the highlight. Views without a tab
  // (search, saved, shared, admin, notifications) keep the previous
  // tab lit, so the bottom bar looks identical on every screen and
  // its pink pill never vanishes (owner: the bar must always stay
  // the same).
  const activeBtn = navFor[name];
  if (activeBtn) NAV_IDS.forEach(id =>
    $(id).classList.toggle("active", id === activeBtn));
  if (name !== "game" && typeof stopGame === "function") stopGame();
  if (name === "tasks") loadTasks();
  if (name === "saved") loadSaved();
  if (name === "shared") loadShared();
  if (name === "admin") loadAdmin();
  if (name === "notifications") loadNotifications(true);
  if (name === "messages") loadMessages();
  if (name !== "chat") stopChatPoll();
  if (name === "videos") { loadVideos(true); maybeShowAd(); }
  if (name === "leaderboard") loadRanks();
  if (name === "designs") loadDesigns(true);
  if (name === "assistant") openAssistant();
  if (name !== "assistant") nexaStop();
  if (name === "museum") openMuseum();
  if (name === "nearby") openNearby();
  if (name !== "nearby") stopNearby();
  syncRainFx();
  moveNavPill();
  updateBackButton();
}

// ---------- Phase 77: the back button stays inside the app ----
// Telegram routes the Android back button to the app ONLY while
// the app shows Telegram's own BackButton; with it hidden, back
// closes the Mini App from any screen (owner: "বটে ব্যাক করলে
// বের হয়ে আসে কেনো?"). So: back first closes whatever is open
// (design popup, a sheet, the design sheet, the sidebar), then
// walks back through the view history, and the button hides
// only on the home screen — Feed, nothing open, empty history —
// where leaving the app is the expected behaviour.
let viewStack = [];
let currentView = "feed";

function anyOverlayOpen() {
  const pop = $("design-pop");
  return !$("reel-sheet-wrap").hidden
    || !$("design-sheet-wrap").hidden
    || !$("photo-viewer").hidden
    || (pop && !pop.hidden)
    || $("glassbar").classList.contains("open");
}

function updateBackButton() {
  if (!tg.BackButton) return;
  if (anyOverlayOpen() || viewStack.length || currentView !== "feed")
    tg.BackButton.show();
  else tg.BackButton.hide();
}

function onAppBack() {
  const pop = $("design-pop");
  if (!$("photo-viewer").hidden) closePhotoViewer();
  else if (pop && !pop.hidden) hideDesignPop();
  else if (!$("reel-sheet-wrap").hidden) closeReelMenu();
  else if (!$("design-sheet-wrap").hidden) closeDesignSheet();
  else if ($("glassbar").classList.contains("open")) closeSidebar();
  else if (viewStack.length) showView(viewStack.pop(), true);
  else if (currentView !== "feed") showView("feed", true);
  updateBackButton();
}
if (tg.BackButton) tg.BackButton.onClick(onAppBack);

// ---------- Phase 78: Nearby — live map of members around you --
// Opt-in only: nothing is sent or shown until the member turns
// sharing on. While the view is open, the app refreshes its own
// fix and the people list every 20 s; leaving the view stops the
// timers (and a closed Mini App cannot be tracked anyway).
let nbMap = null, nbMeMarker = null, nbMarkers = {}, nbRouteLine = null;
let nbTimer = null, nbPos = null, nbSharing = false, nbTarget = null;
let nbLastSent = 0, nbLastLat = null, nbLastLon = null;
const NB_DIRS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];

function nbDir(b) { return NB_DIRS[Math.round(b / 45) % 8]; }
function nbEsc(t) { const d = document.createElement("div");
  d.textContent = t == null ? "" : String(t); return d.innerHTML; }

// Phase 80 (owner's pick: Sample F — Story Circles): markers
// are bubble pins carrying the member's photo; the stories row
// up top mirrors the same people.
const NB_PALS = [["#81C7FF", "#1E88E5"], ["#FFCC80", "#FB8C00"],
                 ["#B39DFF", "#673AB7"], ["#8CE8C3", "#00A86B"],
                 ["#FFABBC", "#E84393"]];
function nbPal(id) { return NB_PALS[Math.abs(id) % NB_PALS.length]; }

function nbAvaHTML(q, cls) {
  if (q.photo_file_id)
    return '<img class="' + cls + '" src="' +
      mediaUrl(q.photo_file_id) + '" alt="">';
  const pal = nbPal(q.id);
  return '<span class="' + cls + ' nb-ini" style="background:linear-gradient(160deg,' +
    pal[0] + "," + pal[1] + ')">' +
    nbEsc((q.name || "?").trim().charAt(0).toUpperCase()) + "</span>";
}

function nbBubbleIcon(q) {
  return L.divIcon({ className: "nb-wrap",
    html: '<div class="nb-pin">' + nbAvaHTML(q, "nb-pin-img") + "</div>",
    iconSize: [46, 56], iconAnchor: [23, 52], popupAnchor: [0, -50] });
}

function nbMeIcon() {
  return L.divIcon({ className: "nb-wrap",
    html: '<div class="nb-me-pin"><svg viewBox="0 0 24 24" width="24" height="24" fill="#fff"><circle cx="12" cy="8" r="4.2"/><path d="M3.5 20.5c.8-4 4.2-6 8.5-6s7.7 2 8.5 6"/></svg></div>',
    iconSize: [46, 46], iconAnchor: [23, 23] });
}

function nbGeo(res) {
  if (!navigator.geolocation) return res(null);
  navigator.geolocation.getCurrentPosition(
    q => res({ lat: q.coords.latitude, lon: q.coords.longitude }),
    () => res(null),
    { enableHighAccuracy: true, timeout: 12000, maximumAge: 30000 });
}

function nbLocate() {
  // Telegram's LocationManager (Bot API 8.0+) where offered,
  // the browser geolocation API everywhere else.
  return new Promise(res => {
    const lm = tg.LocationManager;
    if (!lm) return nbGeo(res);
    const go = () => {
      if (lm.isLocationAvailable)
        lm.getLocation(d => d
          ? res({ lat: d.latitude, lon: d.longitude }) : nbGeo(res));
      else nbGeo(res);
    };
    if (lm.isInited) go(); else lm.init(go);
  });
}

function nbSetStatus(t) { const el = $("nearby-status"); if (el) el.textContent = t; }
function nbPaintToggle() { $("nearby-toggle").classList.toggle("on", nbSharing); }

async function nbSendLocation() {
  if (!nbSharing || !nbPos) return;
  const now = Date.now();
  const moved = nbLastLat === null ? 9999 :
    (Math.abs(nbPos.lat - nbLastLat) + Math.abs(nbPos.lon - nbLastLon)) * 111320;
  if (now - nbLastSent < 25000 && moved < 15) return;
  nbLastSent = now; nbLastLat = nbPos.lat; nbLastLon = nbPos.lon;
  try { await api("/me/location", { method: "POST", body: JSON.stringify(
    { lat: nbPos.lat, lon: nbPos.lon, share: true }) }); } catch (e) {}
}

function nbPaintPeople(people) {
  const seen = {};
  people.forEach(q => {
    seen[q.id] = 1;
    const popup = '<div class="nb-pop"><b>' + nbEsc(q.name) + "</b>" +
      (q.username ? '<div class="muted">@' + nbEsc(q.username) + "</div>" : "") +
      '<div class="nb-pop-meta">🧭 ' + nbDir(q.bearing) + " · " +
      q.distance_m + " m away</div>" +
      '<button class="nb-pop-btn" data-nb-profile="' + q.id +
      '">👤 View profile</button>' +
      '<button class="nb-pop-btn alt" data-nb-route="' + q.id +
      '">🚶 Show route</button></div>';
    if (nbMarkers[q.id]) {
      nbMarkers[q.id].setLatLng([q.lat, q.lon]);
      nbMarkers[q.id].setPopupContent(popup);
      nbMarkers[q.id]._nb = q;
    } else {
      const m = L.marker([q.lat, q.lon],
        { icon: nbBubbleIcon(q) }).addTo(nbMap);
      m.bindPopup(popup); m._nb = q; nbMarkers[q.id] = m;
    }
  });
  Object.keys(nbMarkers).forEach(id => {
    if (!seen[id]) { nbMap.removeLayer(nbMarkers[id]); delete nbMarkers[id]; }
  });
  nbPaintStories(people);
  const list = $("nearby-list");
  list.innerHTML = "";
  if (!people.length) {
    list.innerHTML = '<p class="muted nb-empty">No one nearby right now. ' +
      "When other members open Nexora within 500 metres of you with " +
      "sharing on, they appear here.</p>";
    nbSetStatus("Sharing is on — nobody within 500 m right now.");
    return;
  }
  people.forEach(q => {
    const row = document.createElement("div");
    row.className = "nb-card";
    row.innerHTML = nbAvaHTML(q, "nb-card-ava") +
      '<span class="nb-row-main"><b>' + nbEsc(q.name) +
      (q.verified ? ' <span class="verified">✔</span>' : "") +
      '</b><span class="muted">' +
      (q.username ? "@" + nbEsc(q.username) + "  ·  " : "") +
      nbDir(q.bearing) + "  ·  " + q.distance_m + " m</span></span>" +
      '<button class="nb-route-btn">Route</button>';
    row.onclick = () => { if (nbMap) { nbMap.setView([q.lat, q.lon], 17);
      nbMarkers[q.id].openPopup(); } };
    row.querySelector(".nb-route-btn").onclick = e => {
      e.stopPropagation();
      if (nbMarkers[q.id]) nbRoute(nbMarkers[q.id]._nb);
    };
    list.append(row);
  });
  nbSetStatus("Sharing is on — " + people.length +
    " member(s) within 500 m.");
}

function nbPaintStories(people) {
  const head = $("nearby-stories-head");
  const wrap = $("nearby-stories");
  wrap.innerHTML = "";
  if (!people.length) { head.hidden = true; return; }
  head.hidden = false;
  $("nearby-count").textContent = people.length + " online";
  people.forEach((q, i) => {
    const b = document.createElement("button");
    b.className = "nb-story";
    b.innerHTML = '<span class="nb-ring r' + (i % 4) + '">' +
      '<span class="nb-ring-in">' + nbAvaHTML(q, "nb-story-img") +
      "</span></span>" +
      '<span class="nb-story-name">' +
      nbEsc((q.name || "").split(" ")[0]) + "</span>" +
      '<span class="nb-story-dist">' + q.distance_m + " m</span>";
    b.onclick = () => { if (nbMap) { nbMap.setView([q.lat, q.lon], 17);
      nbMarkers[q.id].openPopup(); } };
    wrap.append(b);
  });
  const inv = document.createElement("button");
  inv.className = "nb-story";
  inv.innerHTML = '<span class="nb-ring invite"><span class="nb-ring-in">' +
    '<span class="nb-story-img nb-plus">+</span></span></span>' +
    '<span class="nb-story-name">Invite</span>' +
    '<span class="nb-story-dist">&nbsp;</span>';
  inv.onclick = () => {
    const url = "https://t.me/share/url?url=" +
      encodeURIComponent("https://t.me/NexoraSocial_bot") +
      "&text=" + encodeURIComponent("Join me on Nexora Social!");
    if (tg.openLink) tg.openLink(url); else window.open(url);
  };
  wrap.append(inv);
}

async function nbRefresh() {
  if (!nbSharing) return;
  const pos = await nbLocate();
  if (pos) {
    nbPos = pos;
    nbSendLocation();
    if (nbMap) {
      if (!nbMeMarker) {
        nbMeMarker = L.marker([pos.lat, pos.lon],
          { icon: nbMeIcon() }).addTo(nbMap);
        nbMeMarker.bindPopup("<b>You are here</b>");
        nbMap.setView([pos.lat, pos.lon], 16);
      } else nbMeMarker.setLatLng([pos.lat, pos.lon]);
    }
  }
  let r;
  try { r = await api("/me/nearby"); } catch (e) { return; }
  if (!r.sharing) {
    nbSharing = false; nbPaintToggle();
    nbSetStatus("Off — nobody can see you on the map.");
    return;
  }
  nbPaintPeople(r.people || []);
  if (nbTarget) {
    const t = (r.people || []).find(q => q.id === nbTarget);
    if (t) nbRoute(t, true); else nbClearRoute();
  }
}

async function nbRoute(q, silent) {
  if (!nbPos || !nbMap) return;
  nbTarget = q.id;
  const url = "https://routing.openstreetmap.de/routed-foot/route/v1/" +
    "driving/" + nbPos.lon + "," + nbPos.lat + ";" + q.lon + "," +
    q.lat + "?overview=full&geometries=geojson";
  let pts = null, dist = q.distance_m, dur = null;
  try {
    const resp = await fetch(url);
    const j = await resp.json();
    if (j.routes && j.routes[0]) {
      pts = j.routes[0].geometry.coordinates.map(c => [c[1], c[0]]);
      dist = Math.round(j.routes[0].distance);
      dur = Math.max(1, Math.round(j.routes[0].duration / 60));
    }
  } catch (e) {}
  if (!pts) pts = [[nbPos.lat, nbPos.lon], [q.lat, q.lon]];
  if (nbRouteLine) nbMap.removeLayer(nbRouteLine);
  nbRouteLine = L.polyline(pts, { color: "#3E8FD0", weight: 5,
    opacity: .9, dashArray: dur === null ? "2 8" : null }).addTo(nbMap);
  if (!silent) nbMap.fitBounds(nbRouteLine.getBounds(),
    { padding: [30, 30] });
  const bar = $("nearby-route");
  bar.hidden = false;
  bar.innerHTML = "🚶 Walking route to <b>" + nbEsc(q.name) + "</b>: " +
    dist + " m" + (dur ? " · about " + dur + " min" : "") +
    ' <button class="nb-route-x" id="nb-route-x">✕ Clear</button>';
  $("nb-route-x").onclick = nbClearRoute;
}

function nbClearRoute() {
  nbTarget = null;
  if (nbRouteLine && nbMap) nbMap.removeLayer(nbRouteLine);
  nbRouteLine = null;
  $("nearby-route").hidden = true;
}

function openNearby() {
  if (typeof L === "undefined") {
    nbSetStatus("The map is still loading — reopen Nearby in a moment.");
    return;
  }
  if (!nbMap) {
    nbMap = L.map("nearby-map", { zoomControl: false });
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png",
      { maxZoom: 19, attribution: "© OpenStreetMap" }).addTo(nbMap);
    nbMap.setView([23.8103, 90.4125], 13);
    nbMap.on("popupopen", e => {
      const el = e.popup.getElement();
      if (!el) return;
      const pb = el.querySelector("[data-nb-profile]");
      if (pb) pb.onclick = () => { nbMap.closePopup();
        openProfile(+pb.dataset.nbProfile); };
      const rb = el.querySelector("[data-nb-route]");
      if (rb) rb.onclick = () => { const m = nbMarkers[rb.dataset.nbRoute];
        if (m) { nbMap.closePopup(); nbRoute(m._nb); } };
    });
  }
  setTimeout(() => { if (nbMap) nbMap.invalidateSize(); }, 60);
  api("/me/nearby").then(r => {
    nbSharing = !!r.sharing;
    nbPaintToggle();
    nbSetStatus(nbSharing ? "Sharing is on."
      : "Off — nobody can see you on the map.");
    if (nbSharing) nbRefresh();
  }).catch(() => {});
  if (nbTimer) clearInterval(nbTimer);
  nbTimer = setInterval(() => { if (nbSharing) nbRefresh(); }, 20000);
}

function stopNearby() {
  if (nbTimer) { clearInterval(nbTimer); nbTimer = null; }
}

$("nearby-toggle").onclick = async () => {
  if (nbSharing) {
    nbSharing = false;
    nbPaintToggle();
    nbClearRoute();
    Object.keys(nbMarkers).forEach(id => {
      if (nbMap) nbMap.removeLayer(nbMarkers[id]);
      delete nbMarkers[id];
    });
    $("nearby-list").innerHTML = "";
    $("nearby-stories").innerHTML = "";
    $("nearby-stories-head").hidden = true;
    nbSetStatus("Off — nobody can see you on the map.");
    try { await api("/me/location", { method: "POST", body: JSON.stringify(
      { lat: 0, lon: 0, share: false }) }); } catch (e) {}
    return;
  }
  nbSetStatus("Getting your location… allow the permission if asked.");
  const pos = await nbLocate();
  if (!pos) {
    nbSetStatus("Location is not available. Turn on your phone's " +
      "location and allow it for Telegram, then try again.");
    return;
  }
  nbPos = pos;
  try {
    const r = await api("/me/location", { method: "POST",
      body: JSON.stringify({ lat: pos.lat, lon: pos.lon, share: true }) });
    if (r && r.sharing) {
      nbSharing = true;
      nbPaintToggle();
      nbLastSent = Date.now(); nbLastLat = pos.lat; nbLastLon = pos.lon;
      nbRefresh();
    }
  } catch (e) { nbSetStatus("Could not turn sharing on — try again."); }
};


const NAV_IDS = ["nav-feed", "nav-videos", "nav-design", "nav-games", "nav-tasks",
                 "nav-ranks", "nav-me"];

function moveNavPill() {
  const pill = $("nav-pill");
  if (!pill) return;
  const idx = NAV_IDS.findIndex(id => $(id) && $(id).classList.contains("active"));
  if (idx < 0) { pill.style.opacity = "0"; return; }
  pill.style.opacity = "1";
  pill.style.transform = "translateX(" + idx * 100 + "%)";
}

function verifiedBadge() {
  const b = document.createElement("span");
  b.className = "verified";
  b.textContent = "✓";
  b.title = "Verified";
  return b;
}

function avatarEl(name, id, big, photoId) {
  if (photoId) {
    const img = document.createElement("img");
    img.className = "avatar" + (big ? " big" : "");
    img.src = mediaUrl(photoId);
    img.alt = name || "";
    img.loading = "lazy";
    img.draggable = false;
    // Phase 112 (owner): tap a profile picture to see it big.
    // stopPropagation so a tap opens the viewer instead of the
    // parent's action (open profile / open chat); pointerdown/up
    // stopPropagation (Phase 99 pattern) so a hold on the avatar
    // never arms a parent card's long-press menu.
    img.onclick = e => { e.stopPropagation();
      openPhotoViewer(photoId, name); };
    img.addEventListener("pointerdown", e => e.stopPropagation());
    img.addEventListener("pointerup", e => e.stopPropagation());
    img.onerror = () => img.replaceWith(avatarEl(name, id, big));
    return img;
  }
  const el = document.createElement("div");
  el.className = "avatar" + (big ? " big" : "");
  const parts = (name || "?").trim().split(/\s+/);
  el.textContent = (parts[0][0] || "?") + (parts.length > 1 ? parts[parts.length - 1][0] : "");
  const hue = Math.abs(Number(id) || 0) % 360;
  el.style.background = "linear-gradient(135deg, hsl(" + hue +
    ",70%,45%), hsl(" + ((hue + 50) % 360) + ",75%,55%))";
  return el;
}

// ---------- Phase 112: full-screen profile photo viewer ----------
// Tap any profile picture (avatarEl wires it) to see the photo big,
// whole and uncropped; tap anywhere or ✕ (or the app back button)
// to close. The image loads from the Phase 111 /media cache, so
// reopening is instant.
function openPhotoViewer(photoId, name) {
  $("pv-img").src = mediaUrl(photoId);
  $("pv-img").alt = name || "Profile photo";
  $("pv-name").textContent = name || "";
  $("photo-viewer").hidden = false;
  updateBackButton();
}
function closePhotoViewer() {
  const v = $("photo-viewer");
  if (v.hidden) return;
  v.hidden = true;
  $("pv-img").src = "";
  updateBackButton();
}
$("photo-viewer").onclick = () => closePhotoViewer();
$("pv-close").onclick = e => { e.stopPropagation(); closePhotoViewer(); };

// ---------------------------------------------------------------- posts ---
function postCard(p) {
  const el = document.createElement("article");
  el.className = "post";

  const head = document.createElement("button");
  head.className = "post-top";
  const who = document.createElement("span");
  who.className = "post-who";
  const nm = document.createElement("span");
  nm.className = "post-name";
  nm.textContent = p.author_name;
  if (p.author_verified) nm.appendChild(verifiedBadge());
  const sub = document.createElement("span");
  sub.className = "post-sub";
  sub.textContent = p.author_username ? "@" + p.author_username : "";
  who.append(nm, sub);
  head.append(avatarEl(p.author_name, p.author_id, false, p.author_photo), who);
  head.onclick = () => openProfile(p.author_id);
  el.appendChild(head);

  if (p.media_file_id && p.type === "photo") {
    // Social-media frame: 4:5 portrait (the Instagram/Facebook feed
    // standard, 1080x1350). Display crop only — the original file in
    // Telegram is never touched.
    const frame = document.createElement("div");
    frame.className = "post-media";
    const img = document.createElement("img");
    img.src = mediaUrl(p.media_file_id);
    img.loading = "lazy";
    img.alt = "photo";
    frame.appendChild(img);
    el.appendChild(frame);
  } else if (p.media_file_id && p.type === "video") {
    const frame = document.createElement("div");
    frame.className = "post-media";
    const vid = document.createElement("video");
    vid.src = mediaUrl(p.media_file_id);
    vid.controls = true;
    vid.preload = "metadata";
    vid.playsInline = true;
    // Phase 51: a preview frame before play — Telegram's own
    // thumbnail as the poster; posts too old to have one get a
    // seek-paint nudge (preload=metadata alone paints nothing
    // inside the Telegram WebView, just a blank pink frame).
    if (p.thumb_file_id) vid.poster = mediaUrl(p.thumb_file_id);
    else vid.addEventListener("loadedmetadata", () => {
      try { vid.currentTime = 0.1; } catch (e) {}
    }, { once: true });
    // Phase 30: feed/profile videos stop when scrolled away.
    feedVidObserver.observe(vid);
    frame.appendChild(vid);
    const playBadge = document.createElement("div");
    playBadge.className = "play-badge";
    playBadge.textContent = "▶";
    playBadge.onclick = () => { vid.play(); };
    vid.onplay = () => {
      playBadge.style.display = "none";
      // Phase 31: a feed video that actually plays earns its view.
      markViewed("posts", p.id, views => { p.views = views; });
    };
    vid.onpause = () => { playBadge.style.display = ""; };
    frame.appendChild(playBadge);
    el.appendChild(frame);
  }

  if (p.caption) {
    const body = document.createElement("p");
    body.className = "caption";
    body.textContent = p.caption;
    el.appendChild(body);
  }

  if (p.hashtags) {
    const tags = document.createElement("div");
    tags.className = "tags";
    p.hashtags.split(" ").filter(Boolean).forEach(t => {
      const chip = document.createElement("button");
      chip.className = "chip";
      chip.textContent = "#" + t;
      chip.onclick = () => searchTag(t);
      tags.appendChild(chip);
    });
    el.appendChild(tags);
  }

  const actions = document.createElement("div");
  actions.className = "actions";

  const likeBtn = document.createElement("button");
  const paintLike = () => {
    likeBtn.textContent = (p.liked ? "❤️ " : "🤍 ") + p.like_count;
    likeBtn.classList.toggle("liked", !!p.liked);
  };
  paintLike();
  likeBtn.onclick = async () => {
    try {
      const r = await api("/posts/" + p.id + "/like", { method: "POST" });
      p.liked = r.liked; p.like_count = r.like_count; paintLike();
    } catch (e) { setStatus("Could not update like."); }
  };
  actions.appendChild(likeBtn);

  const cBtn = document.createElement("button");
  cBtn.textContent = "💬 " + p.comment_count;
  actions.appendChild(cBtn);

  const spacer = document.createElement("span");
  spacer.className = "spacer";
  actions.appendChild(spacer);

  // Phase 54 (owner): every post gets a Facebook-style ⋮
  // options button — the old lone 🗑/⚑ icons were all a feed
  // post had. The sheet (built for reels, fully generic) has
  // Save, Share, Copy link, Download, View profile, Follow,
  // Not interested, Report and Delete.
  const menuBtn = document.createElement("button");
  menuBtn.textContent = "⋮";
  menuBtn.title = "Options";
  menuBtn.onclick = () => openReelMenu(p, el);
  actions.appendChild(menuBtn);
  el.appendChild(actions);

  const cBox = document.createElement("div");
  cBox.className = "comments";
  cBox.hidden = true;
  const cList = document.createElement("div");
  const cForm = document.createElement("div");
  cForm.className = "comment-form";
  const cInput = document.createElement("input");
  cInput.type = "text";
  cInput.placeholder = "Write a comment…";
  cInput.maxLength = 500;
  const cSend = document.createElement("button");
  cSend.textContent = "Send";
  cForm.append(cInput, cSend);
  cBox.append(cList, cForm);
  el.appendChild(cBox);

  let commentsLoaded = false;
  cBtn.onclick = async () => {
    cBox.hidden = !cBox.hidden;
    if (!cBox.hidden && !commentsLoaded) {
      commentsLoaded = true;
      try {
        const data = await api("/posts/" + p.id + "/comments");
        data.comments.forEach(cm => cList.appendChild(commentRow(cm)));
      } catch (e) { setStatus("Could not load comments."); }
    }
  };
  cSend.onclick = async () => {
    const text = cInput.value.trim();
    if (!text) return;
    try {
      const cm = await api("/posts/" + p.id + "/comments", {
        method: "POST", body: JSON.stringify({ text }) });
      cList.appendChild(commentRow(cm));
      cInput.value = "";
      p.comment_count += 1;
      cBtn.textContent = "💬 " + p.comment_count;
    } catch (e) { setStatus("Could not send the comment."); }
  };
  return el;
}

function commentRow(cm) {
  const row = document.createElement("div");
  row.className = "comment";
  row.appendChild(avatarEl(cm.author_name, cm.user_id, false, cm.author_photo));
  const who = document.createElement("b");
  who.textContent = cm.author_name;
  row.appendChild(who);
  if (cm.author_verified) row.appendChild(verifiedBadge());
  row.appendChild(document.createTextNode(": " + cm.text));
  return row;
}

// ----------------------------------------------------------------- feed ---
// Phase 95 (owner): the bot suggests people to follow, in
// the Feed, while scrolling — a little way down, after the
// 4th post (not at the very top, not buried at the bottom).
const SUGGEST_AFTER_POSTS = 4;
let suggestInserted = false;
let suggestDismissed = false;
let feedPostCount = 0;

async function loadFeed(reset) {
  try {
    const url = "/feed?tab=" + tab + (reset || !feedCursor ? "" : "&cursor=" + feedCursor);
    const data = await api(url);
    if (reset) {
      $("feed-list").innerHTML = "";
      feedPostCount = 0;
      suggestInserted = false;
    }
    let suggestSlot = null;
    data.posts.forEach(p => {
      $("feed-list").appendChild(postCard(p));
      feedPostCount += 1;
      if (reset && tab === "explore" && !suggestInserted &&
          !suggestDismissed && feedPostCount === SUGGEST_AFTER_POSTS) {
        suggestSlot = document.createElement("div");
        suggestSlot.className = "suggest-slot";
        $("feed-list").appendChild(suggestSlot);
        suggestInserted = true;
      }
    });
    // A short feed (fewer posts than the slot position)
    // still gets the card — at the end, after the last post.
    if (reset && tab === "explore" && !suggestInserted &&
        !suggestDismissed && data.posts.length > 0) {
      suggestSlot = document.createElement("div");
      suggestSlot.className = "suggest-slot";
      $("feed-list").appendChild(suggestSlot);
      suggestInserted = true;
    }
    if (suggestSlot) loadSuggestedInto(suggestSlot);
    feedCursor = data.next_cursor;
    $("feed-more").hidden = !feedCursor;
    $("feed-empty").hidden = data.posts.length > 0 || !reset;
  } catch (e) { setStatus("Could not load the feed."); }
}

async function loadSuggestedInto(slot) {
  try {
    const data = await api("/suggested-users?limit=10");
    if (!slot.isConnected) return;
    if (!data.users || !data.users.length) { slot.remove(); return; }
    slot.replaceWith(suggestCard(data.users));
  } catch (e) { if (slot.isConnected) slot.remove(); }
}

function suggestCard(users) {
  const el = document.createElement("section");
  el.className = "suggest-card blob";
  el.id = "suggest-card";
  const head = document.createElement("div");
  head.className = "suggest-head";
  const hcol = document.createElement("div");
  const title = document.createElement("div");
  title.className = "suggest-title";
  title.textContent = "👥 Suggested for you";
  const sub = document.createElement("div");
  sub.className = "suggest-sub";
  sub.textContent = "People you may like to follow";
  hcol.append(title, sub);
  const close = document.createElement("button");
  close.className = "suggest-close";
  close.textContent = "✕";
  close.title = "Hide suggestions";
  close.onclick = () => { suggestDismissed = true; el.remove(); };
  head.append(hcol, close);
  el.appendChild(head);
  const scroll = document.createElement("div");
  scroll.className = "suggest-scroll";
  users.forEach(u => {
    const person = document.createElement("div");
    person.className = "suggest-person";
    const avBtn = document.createElement("button");
    avBtn.className = "suggest-ava";
    avBtn.appendChild(avatarEl(u.first_name, u.telegram_id, true,
                               u.photo_file_id));
    avBtn.onclick = () => openProfile(u.telegram_id);
    person.appendChild(avBtn);
    const nm = document.createElement("div");
    nm.className = "suggest-name";
    const nmText = document.createElement("span");
    nmText.className = "suggest-name-text";
    nmText.textContent = u.first_name;
    nm.appendChild(nmText);
    if (u.is_verified) nm.appendChild(verifiedBadge());
    nm.onclick = () => openProfile(u.telegram_id);
    person.appendChild(nm);
    const sub2 = document.createElement("div");
    sub2.className = "suggest-user";
    sub2.textContent = u.username ? "@" + String(u.username).replace(/^@+/, "") : "";
    person.appendChild(sub2);
    const reason = document.createElement("div");
    reason.className = "suggest-reason";
    reason.textContent = u.reason || (u.followers + " followers");
    person.appendChild(reason);
    const fBtn = document.createElement("button");
    fBtn.className = "suggest-follow";
    let following = false;
    const paint = () => {
      fBtn.textContent = following ? "Following ✓" : "Follow";
      fBtn.classList.toggle("on", following);
    };
    paint();
    fBtn.onclick = async () => {
      fBtn.disabled = true;
      try {
        const r = await api("/users/" + u.telegram_id + "/follow",
                            { method: "POST" });
        following = !!r.following;
        paint();
        setStatus(following ? "Following " + u.first_name + "."
                            : "Unfollowed " + u.first_name + ".");
      } catch (e) { setStatus("Could not update follow."); }
      fBtn.disabled = false;
    };
    person.appendChild(fBtn);
    scroll.appendChild(person);
  });
  el.appendChild(scroll);
  return el;
}

function setTab(next) {
  tab = next;
  feedCursor = null;
  $("tab-explore").classList.toggle("active", tab === "explore");
  $("tab-following").classList.toggle("active", tab === "following");
  loadFeed(true);
}

// --------------------------------------------------------------- videos ---
// Reels mode (owner request, Oct 31): full-screen vertical videos that
// autoplay (muted) as they snap into view, like other social apps.
// Tap a video to pause/resume; the corner button toggles sound.
let vtab = "explore";
let vCursor = null;
let reelMuted = true;

const reelObserver = new IntersectionObserver(entries => {
  entries.forEach(en => {
    const v = en.target.querySelector("video");
    if (!v) return;
    if (en.isIntersecting) {
      v.play().catch(() => {});
      // Phase 31: a reel on screen is a view (unique per member).
      if (en.target.dataset.pid) {
        markViewed("posts", en.target.dataset.pid, views => {
          if (en.target._viewCount) en.target._viewCount.textContent = views;
        });
      }
    }
    else v.pause();
  });
}, { root: document.getElementById("view-videos"), threshold: 0.6 });

function reelCard(p) {
  const el = document.createElement("section");
  el.className = "reel";
  el.dataset.pid = p.id;

  const vid = document.createElement("video");
  vid.src = mediaUrl(p.media_file_id);
  vid.loop = true;
  vid.muted = reelMuted;
  vid.playsInline = true;
  vid.preload = "metadata";
  if (p.thumb_file_id) vid.poster = mediaUrl(p.thumb_file_id);
  vid.onclick = () => { if (vid.paused) vid.play().catch(() => {}); else vid.pause(); };
  el.appendChild(vid);

  const shade = document.createElement("div");
  shade.className = "reel-shade";
  const author = document.createElement("button");
  author.className = "reel-author";
  const nm = document.createElement("span");
  nm.className = "post-name";
  nm.textContent = p.author_name;
  if (p.author_verified) nm.appendChild(verifiedBadge());
  const who = document.createElement("span");
  who.className = "post-who";
  const sub = document.createElement("span");
  sub.className = "post-sub";
  sub.textContent = p.author_username ? "@" + p.author_username : "";
  who.append(nm, sub);
  author.append(avatarEl(p.author_name, p.author_id, false, p.author_photo), who);
  author.onclick = () => openProfile(p.author_id);
  shade.appendChild(author);
  if (p.caption) {
    const cap = document.createElement("p");
    cap.className = "reel-caption";
    cap.textContent = p.caption;
    shade.appendChild(cap);
  }
  el.appendChild(shade);

  const side = document.createElement("div");
  side.className = "reel-side";
  const likeWrap = document.createElement("div");
  likeWrap.className = "reel-act";
  const likeBtn = document.createElement("button");
  const likeCount = document.createElement("span");
  const paintLike = () => {
    likeBtn.textContent = p.liked ? "❤️" : "🤍";
    likeBtn.classList.toggle("liked", !!p.liked);
    likeCount.textContent = p.like_count;
  };
  paintLike();
  likeBtn.onclick = async () => {
    try {
      const r = await api("/posts/" + p.id + "/like", { method: "POST" });
      p.liked = r.liked; p.like_count = r.like_count; paintLike();
    } catch (e) { setStatus("Could not update like."); }
  };
  likeWrap.append(likeBtn, likeCount);
  const cWrap = document.createElement("div");
  cWrap.className = "reel-act";
  const cBtn = document.createElement("button");
  cBtn.textContent = "💬";
  const cCount = document.createElement("span");
  cCount.textContent = p.comment_count;
  cWrap.append(cBtn, cCount);
  // Phase 31: the 👁 unique-view count, under comments.
  const vWrap = document.createElement("div");
  vWrap.className = "reel-act";
  const vBtn = document.createElement("button");
  vBtn.textContent = "👁";
  vBtn.title = "Views";
  const vCount = document.createElement("span");
  vCount.textContent = p.views || 0;
  vWrap.append(vBtn, vCount);
  el._viewCount = vCount;
  const mWrap = document.createElement("div");
  mWrap.className = "reel-act";
  const mBtn = document.createElement("button");
  mBtn.textContent = "⋮";
  mBtn.title = "Options";
  mBtn.onclick = () => openReelMenu(p, el);
  mWrap.appendChild(mBtn);
  side.append(likeWrap, cWrap, vWrap, mWrap);
  el.appendChild(side);

  const cBox = document.createElement("div");
  cBox.className = "comments";
  cBox.hidden = true;
  const cList = document.createElement("div");
  const cForm = document.createElement("div");
  cForm.className = "comment-form";
  const cInput = document.createElement("input");
  cInput.type = "text";
  cInput.placeholder = "Write a comment…";
  cInput.maxLength = 500;
  const cSend = document.createElement("button");
  cSend.textContent = "Send";
  cForm.append(cInput, cSend);
  cBox.append(cList, cForm);
  el.appendChild(cBox);

  let commentsLoaded = false;
  cBtn.onclick = async () => {
    cBox.hidden = !cBox.hidden;
    if (!cBox.hidden && !commentsLoaded) {
      commentsLoaded = true;
      try {
        const data = await api("/posts/" + p.id + "/comments");
        data.comments.forEach(cm => cList.appendChild(commentRow(cm)));
      } catch (e) { setStatus("Could not load comments."); }
    }
  };
  cSend.onclick = async () => {
    const text = cInput.value.trim();
    if (!text) return;
    try {
      const cm = await api("/posts/" + p.id + "/comments", {
        method: "POST", body: JSON.stringify({ text }) });
      cList.appendChild(commentRow(cm));
      cInput.value = "";
      p.comment_count += 1;
      cCount.textContent = p.comment_count;
    } catch (e) { setStatus("Could not send the comment."); }
  };
  return el;
}

// ------------------------------------------------------- options sheet ---
function closeReelMenu() { $("reel-sheet-wrap").hidden = true; updateBackButton(); }

async function openReelMenu(p, reelEl) {
  const sheet = $("reel-sheet");
  sheet.innerHTML = "";
  const row = (icon, label, fn, danger) => {
    const b = document.createElement("button");
    b.className = "sheet-row" + (danger ? " danger" : "");
    const ic = document.createElement("span");
    ic.className = "ic";
    ic.textContent = icon;
    b.append(ic, document.createTextNode(label));
    b.onclick = async () => { closeReelMenu(); await fn(); };
    sheet.appendChild(b);
    return b;
  };
  const appLink = "https://t.me/" +
    (me && me.bot_username ? me.bot_username : "NexoraSocial_bot");
  const mine = me && p.author_id === me.telegram_id;

  row("🔖", p.saved ? "Saved — tap to remove" : "Save", async () => {
    try {
      const r = await api("/posts/" + p.id + "/save", { method: "POST" });
      p.saved = r.saved;
      setStatus(r.saved ? "Saved to your collection." : "Removed from Saved.");
    } catch (e) { setStatus("Could not save."); }
  });
  row("📤", "Share", () => openSharePicker(p));
  row("🔗", "Copy link", async () => {
    const link = appLink + "?start=post_" + p.id;
    try {
      await navigator.clipboard.writeText(link);
      setStatus("Link copied.");
    } catch (e) { setStatus(link); }
  });
  if (p.media_file_id) row("⬇️", "Download", () => {
    const a = document.createElement("a");
    a.href = mediaUrl(p.media_file_id);
    a.download = "";
    document.body.appendChild(a);
    a.click();
    a.remove();
  });
  row("👤", "View profile", () => openProfile(p.author_id));
  if (!mine) {
    const fRow = row("➕", "Follow @" + (p.author_username || p.author_name),
                     async () => {});
    try {
      const u = await api("/users/" + p.author_id);
      if (u.is_official) fRow.remove();
      else {
        fRow.lastChild.textContent =
          (u.following ? "Unfollow @" : "Follow @") +
          (p.author_username || p.author_name);
        fRow.onclick = async () => {
          closeReelMenu();
          try {
            const r = await api("/users/" + p.author_id + "/follow",
                                { method: "POST" });
            setStatus(r.following ? "Following " + p.author_name + "."
                                  : "Unfollowed " + p.author_name + ".");
          } catch (e) { setStatus("Could not update follow."); }
        };
      }
    } catch (e) { /* keep the generic row */ }
    row("🚫", "Not interested", () => {
      reelEl.remove();
      setStatus("Got it — this post was hidden.");
    });
    row("⚑", "Report", async () => {
      try {
        await api("/reports", { method: "POST",
          body: JSON.stringify({ post_id: p.id, reason: "user report" }) });
        setStatus("Thanks, the post was reported.");
      } catch (e) { setStatus("Could not report."); }
    }, true);
  }
  if (mine) row("✏️", "Edit", () => openPostEditor(p, reelEl));
  if (mine) row("🗑", "Delete", async () => {
    try {
      await api("/posts/" + p.id, { method: "DELETE" });
      reelEl.remove();
      setStatus("Deleted.");
    } catch (e) { setStatus("Could not delete."); }
  }, true);
  row("✕", "Cancel", () => {});
  $("reel-sheet-wrap").hidden = false;
  updateBackButton();
}

// Phase 59: caption editor for your own post, inside the
// same sheet. On save the card's caption + hashtag chips
// repaint in place (feed/profile cards); reels just keep
// the updated data.
function openPostEditor(p, cardEl) {
  const sheet = $("reel-sheet");
  sheet.innerHTML = "";
  const title = document.createElement("div");
  title.className = "sheet-title";
  title.textContent = "Edit post";
  const ta = document.createElement("textarea");
  ta.className = "sheet-edit-ta";
  ta.maxLength = 2000;
  ta.rows = 4;
  ta.value = p.caption || "";
  const save = document.createElement("button");
  save.className = "sheet-row";
  const sic = document.createElement("span");
  sic.className = "ic";
  sic.textContent = "💾";
  save.append(sic, document.createTextNode("Save changes"));
  save.onclick = async () => {
    try {
      const r = await api("/posts/" + p.id + "/edit", {
        method: "POST",
        body: JSON.stringify({ caption: ta.value }) });
      p.caption = r.caption;
      p.hashtags = r.hashtags;
      const actions = cardEl.querySelector(".actions");
      if (actions) {
        let cap = cardEl.querySelector(".caption");
        if (r.caption) {
          if (!cap) {
            cap = document.createElement("p");
            cap.className = "caption";
            actions.before(cap);
          }
          cap.textContent = r.caption;
        } else if (cap) cap.remove();
        const oldTags = cardEl.querySelector(".tags");
        if (oldTags) oldTags.remove();
        if (r.hashtags) {
          const tags = document.createElement("div");
          tags.className = "tags";
          r.hashtags.split(" ").filter(Boolean).forEach(t => {
            const chip = document.createElement("button");
            chip.className = "chip";
            chip.textContent = "#" + t;
            chip.onclick = () => searchTag(t);
            tags.appendChild(chip);
          });
          actions.before(tags);
        }
      }
      closeReelMenu();
      setStatus("Post updated.");
    } catch (e) { setStatus("Could not update the post."); }
  };
  const cancel = document.createElement("button");
  cancel.className = "sheet-row";
  const cic = document.createElement("span");
  cic.className = "ic";
  cic.textContent = "✕";
  cancel.append(cic, document.createTextNode("Cancel"));
  cancel.onclick = () => closeReelMenu();
  sheet.append(title, ta, save, cancel);
  $("reel-sheet-wrap").hidden = false;
  updateBackButton();
  ta.focus();
}

// ------------------------------------------------------------- sharing ---
function shareViaTelegram(p) {
  const appLink = "https://t.me/" +
    (me && me.bot_username ? me.bot_username : "NexoraSocial_bot");
  const text = (p.caption || "Check this out on Nexora Social").slice(0, 200);
  const url = "https://t.me/share/url?url=" + encodeURIComponent(appLink) +
    "&text=" + encodeURIComponent(text);
  if (tg.openTelegramLink) tg.openTelegramLink(url);
  else window.open(url, "_blank");
}

async function openSharePicker(p) {
  const sheet = $("reel-sheet");
  sheet.innerHTML = "";
  const title = document.createElement("div");
  title.className = "sheet-title";
  title.textContent = "Send to…";
  const searchRow = document.createElement("div");
  searchRow.className = "sheet-search";
  const input = document.createElement("input");
  input.type = "text";
  input.placeholder = "Search people…";
  searchRow.appendChild(input);
  const list = document.createElement("div");
  sheet.append(title, searchRow, list);

  const render = users => {
    list.innerHTML = "";
    const visible = users.filter(u => !me || u.telegram_id !== me.telegram_id);
    if (!visible.length) {
      const e = document.createElement("p");
      e.className = "hint";
      e.textContent = "No people here yet. Follow someone, or search by name.";
      list.appendChild(e);
    }
    visible.forEach(u => {
      const r = document.createElement("div");
      r.className = "pick-row";
      const nm = document.createElement("span");
      nm.className = "pick-name";
      nm.textContent = u.first_name;
      if (u.is_verified) nm.appendChild(verifiedBadge());
      if (u.username) {
        const sm = document.createElement("small");
        sm.textContent = "@" + u.username;
        nm.appendChild(sm);
      }
      const send = document.createElement("button");
      send.className = "pick-send";
      send.textContent = "Send";
      send.onclick = async () => {
        send.disabled = true;
        try {
          await api("/posts/" + p.id + "/share", { method: "POST",
            body: JSON.stringify({ to_user_id: u.telegram_id }) });
          send.textContent = "Sent ✓";
          send.classList.add("sent");
          setStatus("Shared with " + u.first_name + ".");
        } catch (e) {
          send.disabled = false;
          setStatus("Could not share.");
        }
      };
      r.append(avatarEl(u.first_name, u.telegram_id, false, u.photo_file_id), nm, send);
      list.appendChild(r);
    });
    const tgRow = document.createElement("button");
    tgRow.className = "sheet-row";
    const ic = document.createElement("span");
    ic.className = "ic";
    ic.textContent = "↗";
    tgRow.append(ic, document.createTextNode("Share via Telegram"));
    tgRow.onclick = () => { closeReelMenu(); shareViaTelegram(p); };
    const cancel = document.createElement("button");
    cancel.className = "sheet-row";
    const ic2 = document.createElement("span");
    ic2.className = "ic";
    ic2.textContent = "✕";
    cancel.append(ic2, document.createTextNode("Cancel"));
    cancel.onclick = () => closeReelMenu();
    list.append(tgRow, cancel);
  };

  try {
    const data = await api("/me/following");
    render(data.users);
  } catch (e) { render([]); }
  let timer = null;
  input.oninput = () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const q = input.value.trim();
      try {
        const d = q ? await api("/search?q=" + encodeURIComponent(q))
                    : await api("/me/following");
        render(d.users);
      } catch (e) { /* keep the current list */ }
    }, 250);
  };
  $("reel-sheet-wrap").hidden = false;
  updateBackButton();
}

async function loadShared() {
  const box = $("shared-list");
  box.innerHTML = "Loading…";
  try {
    const data = await api("/me/shared");
    box.innerHTML = "";
    data.posts.forEach(p => {
      const head = document.createElement("div");
      head.className = "shared-by";
      head.textContent = "📤 Shared by " + p.shared_by_name;
      box.append(head, postCard(p));
    });
    // Phase 66: designs shared via the long-press popup.
    const dd = await api("/me/design-shared");
    const grid = $("shared-designs");
    grid.innerHTML = "";
    dd.designs.forEach(d => {
      const wrap = document.createElement("div");
      const head = document.createElement("div");
      head.className = "shared-by";
      head.textContent = "🎨 Shared by " + d.shared_by_name;
      wrap.append(head, designCard(d));
      grid.appendChild(wrap);
    });
    $("shared-designs-title").hidden = dd.designs.length === 0;
    $("shared-empty").hidden =
      data.posts.length > 0 || dd.designs.length > 0;
  } catch (e) { box.textContent = "Could not load shared posts."; }
}

// ---------------------------------------------------------------- saved ---
async function loadSaved() {
  const box = $("saved-list");
  box.innerHTML = "Loading…";
  try {
    const data = await api("/me/saved");
    box.innerHTML = "";
    data.posts.forEach(p => box.appendChild(postCard(p)));
    // Phase 66: designs saved via the long-press popup's 📌.
    const dd = await api("/me/design-saved");
    const grid = $("saved-designs");
    grid.innerHTML = "";
    dd.designs.forEach(d => grid.appendChild(designCard(d)));
    $("saved-designs-title").hidden = dd.designs.length === 0;
    $("saved-empty").hidden =
      data.posts.length > 0 || dd.designs.length > 0;
  } catch (e) { box.textContent = "Could not load your saved posts."; }
}

async function loadVideos(reset) {
  try {
    const url = "/feed?type=video&tab=" + vtab +
      (reset || !vCursor ? "" : "&cursor=" + vCursor);
    const data = await api(url);
    if (reset) {
      $("video-list").querySelectorAll(".reel").forEach(r => reelObserver.unobserve(r));
      $("video-list").innerHTML = "";
    }
    data.posts.forEach(p => {
      const card = reelCard(p);
      $("video-list").appendChild(card);
      reelObserver.observe(card);
    });
    vCursor = data.next_cursor;
    $("video-more").hidden = !vCursor;
    $("video-empty").hidden = data.posts.length > 0 || !reset;
  } catch (e) { setStatus("Could not load videos."); }
}

function setVTab(next) {
  vtab = next;
  vCursor = null;
  $("vtab-explore").classList.toggle("active", vtab === "explore");
  $("vtab-following").classList.toggle("active", vtab === "following");
  loadVideos(true);
}

// ----------------------------------------------------------- leaderboard ---
async function loadRanks() {
  const box = $("rank-list");
  box.innerHTML = "Loading…";
  try {
    const data = await api("/leaderboard");
    box.innerHTML = "";
    const medals = { 1: "🥇", 2: "🥈", 3: "🥉" };
    const rowFor = (r, isMe) => {
      const row = document.createElement("div");
      row.className = "rank-row" + (isMe ? " rank-me" : "");
      const num = document.createElement("span");
      num.className = "rank-num";
      num.textContent = medals[r.rank] || r.rank;
      const nm = document.createElement("span");
      nm.className = "rank-name";
      // Phase 65 (owner): the name must stay on ONE line — a long
      // name plus " (You)" used to wrap under itself. The name gets
      // its own ellipsis span and " (You)" moves to the muted
      // username line, where there is room.
      const title = document.createElement("span");
      title.className = "rank-title";
      title.textContent = r.first_name;
      nm.appendChild(title);
      if (r.is_verified) nm.appendChild(verifiedBadge());
      if (r.username || isMe) {
        const small = document.createElement("small");
        small.textContent = [
          r.username ? "@" + r.username : "",
          isMe ? "(You)" : ""].filter(Boolean).join(" ");
        nm.appendChild(small);
      }
      // Phase 82 (owner): tapping the NAME opens the profile
      // too — the avatar button already did, the name did not.
      nm.classList.add("rank-link");
      nm.onclick = () => openProfile(r.telegram_id);
      const pts = document.createElement("span");
      pts.className = "rank-points";
      pts.textContent = "⭐ " + r.points;
      const btn = document.createElement("button");
      btn.append(avatarEl(r.first_name, r.telegram_id, false, r.photo_file_id));
      btn.className = "post-top";
      btn.style.width = "auto";
      btn.onclick = () => openProfile(r.telegram_id);
      row.append(num, btn, nm, pts);
      return row;
    };
    let meInList = false;
    data.leaders.forEach(r => {
      const isMe = me && r.telegram_id === me.telegram_id;
      if (isMe) meInList = true;
      box.appendChild(rowFor(r, isMe));
    });
    if (!meInList && data.me) {
      const sep = document.createElement("div");
      sep.className = "rank-sep";
      sep.textContent = "···";
      box.append(sep, rowFor(data.me, true));
    }
  } catch (e) { box.textContent = "Could not load the leaderboard."; }
}

// --------------------------------------------------------------- search ---
async function runSearch(q) {
  try {
    const data = await api("/search?q=" + encodeURIComponent(q));
    const usersBox = $("search-users");
    const postsBox = $("search-posts");
    usersBox.innerHTML = "";
    postsBox.innerHTML = "";
    data.users.forEach(u => {
      const row = document.createElement("button");
      row.className = "user-row";
      row.appendChild(avatarEl(u.first_name, u.telegram_id, false, u.photo_file_id));
      row.appendChild(document.createTextNode(
        u.first_name + (u.username
          ? " @" + String(u.username).replace(/^@+/, "") : "")));
      if (u.is_verified) row.appendChild(verifiedBadge());
      row.onclick = () => openProfile(u.telegram_id);
      usersBox.appendChild(row);
    });
    data.posts.forEach(p => postsBox.appendChild(postCard(p)));
    if (!data.users.length && !data.posts.length) setStatus("No results.");
    else setStatus("");
  } catch (e) { setStatus("Search failed."); }
}

function searchTag(tag) {
  showView("search");
  $("search-input").value = "#" + tag;
  runSearch("#" + tag);
}


// ------------------------------------------------------------ themes -----
// Phase 90 (owner): every member picks colour shades in the
// Me section and the whole site takes those colours. One
// shade can dress everything, or shades can be assigned per
// zone (background / cards / accent) so different places
// wear different colours. The palettes are the owner's own
// screenshots (uiux.build / byo.ch colour posts, Nov 5).
// Text can never blend into the background: the derivation
// below darkens the ink until its WCAG contrast against the
// card colour clears 7:1, dim text clears 4.2:1, and button
// text picks whichever of white / near-black reads better
// on the accent gradient.
// THEME-ENGINE-BEGIN
const THEME_PALETTES = [
  { id: "navy-mirage", name: "Navy Mirage",
    stops: ["#141E30", "#35577D"] },
  { id: "emerald-depth", name: "Emerald Depth",
    stops: ["#0F2027", "#28623A"] },
  { id: "obsidian-plum", name: "Obsidian Plum",
    stops: ["#2D1E2F", "#4E2A4F"] },
  { id: "walnut-noir", name: "Walnut Noir",
    stops: ["#2E1F1B", "#5E4B43"] },
  { id: "crimson-velvet", name: "Crimson Velvet",
    stops: ["#2C0F12", "#6B1E23"] },
  { id: "marple", name: "Marple",
    stops: ["#CA2851", "#FF6766", "#FFB173", "#FFE3B3"] },
  { id: "sunset", name: "Sunset",
    stops: ["#EA6113", "#F88F22", "#FBB931", "#FFE3B3"] },
  { id: "forest-mist", name: "Forest Mist",
    stops: ["#051F20", "#0B2B26", "#163832", "#235347",
            "#8EB69B", "#DAF1DE"] },
  { id: "berry-rose", name: "Berry Rose",
    stops: ["#2A0F1E", "#5A1F3D", "#8E3560", "#C0628C",
            "#E7A5BF", "#FAE3EC"] },
  { id: "terracotta", name: "Terracotta",
    stops: ["#2B1410", "#5C2A1E", "#9C4A2F", "#D07A4F",
            "#EBB68A", "#F8E6D0"] },
  { id: "copper-bordeaux", name: "Copper Bordeaux",
    stops: ["#2B0A0F", "#5E1A22", "#8F2D35", "#C46A4A",
            "#E8A988", "#FBE8DA"] },
  { id: "mustard-anthracite", name: "Mustard Anthracite",
    stops: ["#181818", "#3A3935", "#75705F", "#C29A2E",
            "#E8CF7F", "#FAF3D6"] },
  { id: "sage-cream", name: "Sage Cream",
    stops: ["#A3B18A", "#F2E8CF"] },
  { id: "rose-olive", name: "Rose Olive",
    stops: ["#C9A0A0", "#8A8F68"] },
  { id: "lavender-beige", name: "Lavender Beige",
    stops: ["#A89BBE", "#D8C3A8"] },
  // Phase 93: eight more from the owner's second batch
  // (uxintace combos, dopely wedding sets, aayudesigns103
  // pairs) — none duplicated the first fifteen.
  { id: "milk-plum", name: "Milk & Plum",
    stops: ["#381932", "#FFF3E6"] },
  { id: "night-kiwi", name: "Night & Kiwi",
    stops: ["#222222", "#89E900"] },
  { id: "black-gold", name: "Black & Gold",
    stops: ["#050505", "#2B2B2B", "#C9B27A", "#F7F1E6", "#FFFFFF"] },
  { id: "peach-bloom", name: "Peach Bloom",
    stops: ["#FFB4A2", "#E5989B", "#FDE2D2", "#FFF8F0", "#5C4034"] },
  { id: "champagne-slate", name: "Champagne & Slate",
    stops: ["#5A5D64", "#E7D28F"] },
  { id: "cocoa-cloud", name: "Cocoa & Cloud",
    stops: ["#53332A", "#B8CDE3"] },
  { id: "meadow-violet", name: "Meadow & Violet",
    stops: ["#5E397F", "#9FB354"] },
  { id: "winter-cherry", name: "Winter & Cherry",
    stops: ["#C10015", "#93B4D7"] },
  // Phase 98: four more from the owner's third batch of Pinterest
  // screenshots — Natural Leaf sampled from the leaf board's flat
  // discs, Teal Ribbon sampled from the infographic bands, Modern
  // Palette read from its printed hex labels, Copper Pay read from
  // the Rel-Pay brand sheet's printed hex labels (two cross-checked
  // by sampling). None duplicates the existing twenty-three.
  { id: "natural-leaf", name: "Natural Leaf",
    stops: ["#1E4634", "#459566", "#84BB71", "#B19468", "#F5DC9A"] },
  { id: "teal-ribbon", name: "Teal Ribbon",
    stops: ["#155F7A", "#49AEC0", "#FFEFCE", "#EA781E", "#131723"] },
  { id: "modern-palette", name: "Modern Palette",
    stops: ["#051A2D", "#A60E35", "#FEA24F", "#10BBC3", "#068187"] },
  { id: "copper-pay", name: "Copper Pay",
    stops: ["#100F0F", "#653615", "#B66120", "#FFFFFF"] },
  // Phase 104: six more from the owner's fourth batch of
  // screenshots — Instagram colour posts by
  // illustrator.blog_artist (Nov 12), each a nature photo
  // with its printed hex labels below it. Labels used
  // as printed and cross-checked by sampling the pills'
  // own fills (band order and hues match within JPEG
  // tolerance). None duplicates the existing twenty-seven.
  { id: "pink-hibiscus", name: "Pink Hibiscus",
    stops: ["#8B004E", "#E91584", "#FF6BB1", "#FFB6D9",
            "#FFE4F1", "#6B8E23", "#2D4D1E"] },
  { id: "blue-hibiscus", name: "Blue Hibiscus",
    stops: ["#8B0022", "#E11D48", "#58B0E6", "#8ED4F7",
            "#D4F0FF", "#4F8F2D", "#1B4D2E"] },
  { id: "ripe-mango", name: "Ripe Mango",
    stops: ["#E30A17", "#F57C00", "#F4A261", "#F7D117",
            "#A4C639", "#4E8F2D", "#1F4D1F"] },
  { id: "red-rose", name: "Red Rose",
    stops: ["#6B0013", "#A80D22", "#E1223B", "#2E5D2F",
            "#4F8F3A", "#A7C957", "#D7E7B8"] },
  { id: "autumn-maple", name: "Autumn Maple",
    stops: ["#8B0D0D", "#D71919", "#F04A20", "#F7931E",
            "#FFD43B", "#8FB326", "#4E3F0C"] },
  { id: "avocado", name: "Avocado",
    stops: ["#0E2010", "#253C1B", "#3E5B2E", "#5B7F49",
            "#83A56D", "#E5EDDE"] },
];
const TH_WHITE = [255, 255, 255], TH_BLACK = [0, 0, 0];
function thRgb(hex) {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
function thHex(c) {
  return "#" + c.map(v => Math.max(0, Math.min(255, Math.round(v)))
    .toString(16).padStart(2, "0")).join("");
}
function thRgba(c, a) {
  return "rgba(" + c.map(v => Math.round(v)).join(",") + "," + a + ")";
}
function thMix(a, b, t) {
  return a.map((v, i) => v + (b[i] - v) * t);
}
function thLum(c) {
  const f = v => {
    v /= 255;
    return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
  };
  return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]);
}
function thContrast(a, b) {
  const x = thLum(a), y = thLum(b);
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
}
function thSat(c) {
  const mx = Math.max(...c) / 255, mn = Math.min(...c) / 255;
  if (mx === mn) return 0;
  const l = (mx + mn) / 2;
  return (mx - mn) / (1 - Math.abs(2 * l - 1) || 1);
}
function deriveTheme(stops) {
  const rgbs = stops.map(thRgb);
  const byLum = [...rgbs].sort((a, b) => thLum(a) - thLum(b));
  const dark = byLum[0], light = byLum[byLum.length - 1];
  // Cards are always a light surface: ramps that end in a
  // pale stop use it as-is, while the dark pairs (Navy
  // Mirage and friends) get lifted toward white until the
  // surface is light enough for dark text — the palette's
  // deep colour then lives in the ink and the accents.
  let card = light;
  for (let i = 0; i < 12 && thLum(card) < 0.72; i++)
    card = thMix(card, TH_WHITE, 0.12);
  const bgDeep = byLum.length > 2 ? byLum[byLum.length - 2] : dark;
  const bg = thMix(card, bgDeep, byLum.length > 2 ? 0.18 : 0.12);
  const input = thMix(card, TH_WHITE, 0.45);
  let ink = dark;
  for (let i = 0; i < 16 && thContrast(ink, card) < 7; i++)
    ink = thMix(ink, TH_BLACK, 0.14);
  let dim = thMix(ink, card, 0.36);
  for (let i = 0; i < 10 && thContrast(dim, card) < 4.2; i++)
    dim = thMix(dim, ink, 0.22);
  const faint = thMix(ink, card, 0.58);
  const bySat = [...rgbs].sort((a, b) => thSat(b) - thSat(a));
  let accDeep = bySat.find(c => thLum(c) <= 0.45) || thMix(bySat[0], TH_BLACK, 0.25);
  let accLight = bySat.find(c => c !== accDeep && thLum(c) > thLum(accDeep));
  if (!accLight) accLight = thMix(accDeep, TH_WHITE, 0.30);
  const accMid = thMix(accLight, accDeep, 0.5);
  const nearBlack = thRgb("#14090F");
  const onAcc = thContrast(TH_WHITE, accMid) >= thContrast(nearBlack, accMid)
    ? "#FFFFFF" : "#14090F";
  let accText = accDeep;
  for (let i = 0; i < 12 && thContrast(accText, card) < 4.5; i++)
    accText = thMix(accText, TH_BLACK, 0.12);
  const tint = thMix(dark, accDeep, 0.3);
  return {
    bg: thHex(bg), glow1: thRgba(accLight, 0.50),
    glow2: thRgba(accDeep, 0.38),
    card: thHex(card), cardA: thRgba(card, 0.92),
    input: thHex(input), line: thRgba(ink, 0.10),
    ink: thHex(ink), dim: thHex(dim), faint: thHex(faint),
    acc1: thHex(accLight), acc2: thHex(accDeep), onAcc,
    accText: thHex(accText), chip: thHex(thMix(accLight, TH_WHITE, 0.78)),
    tile: thHex(thMix(card, accDeep, 0.12)),
    shadow: thRgba(tint, 0.38), shadowIn: thRgba(tint, 0.30),
  };
}
// THEME-ENGINE-END

let themeState = { zone: "all",
                   picks: { bg: null, card: null, accent: null } };
let themeDropOpen = false;
// Phase 96: a theme belongs to ONE account, never to the device.
// The server stores each member's picks on their own account (sent
// back by /auth); locally they are cached under a per-account key.
// Before Phase 96 one shared "nx_theme" key was used, so on a phone
// with two Telegram accounts the second account saw the first
// account's theme — it looked like everyone's theme changed.
function themeKey() {
  return "nx_theme_" + (me && me.telegram_id ? me.telegram_id : "anon");
}
function loadAccountTheme() {
  let picks = null;
  if (me && me.theme && (me.theme.bg || me.theme.card ||
      me.theme.accent)) picks = me.theme;
  if (!picks) {
    try {
      const s = JSON.parse(localStorage.getItem(themeKey()) || "null");
      if (s && s.picks) picks = s.picks;
    } catch (e) { /* no cache for this account yet */ }
  }
  if (!picks) {
    // One-time migration: claim the old shared key for the account
    // that is signed in now, then delete it for everyone else.
    try {
      const legacy = JSON.parse(
        localStorage.getItem("nx_theme") || "null");
      if (legacy && legacy.picks) picks = legacy.picks;
    } catch (e) { /* nothing to migrate */ }
  }
  try { localStorage.removeItem("nx_theme"); } catch (e) {}
  themeState = { zone: "all", picks: {
    bg: (picks && picks.bg) || null,
    card: (picks && picks.card) || null,
    accent: (picks && picks.accent) || null } };
  applyUserTheme();
  saveTheme();
}
function palById(id) {
  return THEME_PALETTES.find(p => p.id === id) || null;
}
function saveTheme() {
  try { localStorage.setItem(themeKey(), JSON.stringify(themeState)); }
  catch (e) { /* private mode: the theme lasts for the session */ }
  if (me && me.telegram_id) {
    api("/me/theme", { method: "POST", body: JSON.stringify(
      { picks: themeState.picks }) }).catch(() => {});
  }
}
const TH_CARD_VARS = ["--t-card", "--t-carda", "--t-input", "--t-line",
  "--t-tile", "--ink", "--ink-dim", "--ink-faint", "--glass-bg",
  "--clay-shadow", "--clay-shadow-sm", "--clay-inset"];
const TH_ACC_VARS = ["--t-acc1", "--t-acc2", "--t-onacc", "--t-chip",
  "--t-acctext"];
function applyUserTheme() {
  const root = document.documentElement;
  const st = root.style;
  const any = themeState.picks.bg || themeState.picks.card ||
              themeState.picks.accent;
  if (!any) {
    delete root.dataset.theme;
    ["--t-bg", "--t-glow1", "--t-glow2", ...TH_CARD_VARS,
     ...TH_ACC_VARS].forEach(v => st.removeProperty(v));
    return;
  }
  root.dataset.theme = "on";
  const bgP = palById(themeState.picks.bg);
  if (bgP) {
    const d = deriveTheme(bgP.stops);
    st.setProperty("--t-bg", d.bg);
    st.setProperty("--t-glow1", d.glow1);
    st.setProperty("--t-glow2", d.glow2);
  } else {
    ["--t-bg", "--t-glow1", "--t-glow2"]
      .forEach(v => st.removeProperty(v));
  }
  const cardP = palById(themeState.picks.card);
  if (cardP) {
    const d = deriveTheme(cardP.stops);
    st.setProperty("--t-card", d.card);
    st.setProperty("--t-carda", d.cardA);
    st.setProperty("--t-input", d.input);
    st.setProperty("--t-line", d.line);
    st.setProperty("--t-tile", d.tile);
    st.setProperty("--ink", d.ink);
    st.setProperty("--ink-dim", d.dim);
    st.setProperty("--ink-faint", d.faint);
    st.setProperty("--glass-bg", d.cardA);
    st.setProperty("--clay-shadow",
      "10px 14px 28px " + d.shadow +
      ", -6px -6px 14px rgba(255,255,255,.9)" +
      ", inset 2px 2px 4px rgba(255,255,255,.95)" +
      ", inset -6px -8px 12px " + d.shadowIn);
    st.setProperty("--clay-shadow-sm",
      "6px 8px 16px " + d.shadow +
      ", -4px -4px 10px rgba(255,255,255,.85)" +
      ", inset 1px 1px 3px rgba(255,255,255,.9)" +
      ", inset -4px -5px 9px " + d.shadowIn);
    st.setProperty("--clay-inset",
      "inset 5px 6px 12px " + d.shadow +
      ", inset -5px -5px 10px rgba(255,255,255,.95)");
  } else {
    TH_CARD_VARS.forEach(v => st.removeProperty(v));
  }
  const accP = palById(themeState.picks.accent);
  if (accP) {
    const d = deriveTheme(accP.stops);
    st.setProperty("--t-acc1", d.acc1);
    st.setProperty("--t-acc2", d.acc2);
    st.setProperty("--t-onacc", d.onAcc);
    st.setProperty("--t-chip", d.chip);
    st.setProperty("--t-acctext", d.accText);
  } else {
    TH_ACC_VARS.forEach(v => st.removeProperty(v));
  }
}
applyUserTheme();

// The picker card that lives in the Me section (own profile).
// Phase 100 (owner: "Data Control থেকে ডাটা এক্সপোর্ট হয়না"): the
// /me/export endpoint has existed since Phase 28, but the app never
// had ANY export button — Nexa even promised one in the profile.
// This card is the missing Data Control: two routes to the same
// JSON file. Download suits desktop browsers; sending the file
// through the bot chat is the reliable route on phones, where a
// WebView blob download can silently do nothing.
function dataCard() {
  const card = document.createElement("div");
  card.className = "card data-card";
  const title = document.createElement("b");
  title.textContent = "🗂️ Data Control";
  card.appendChild(title);
  const hint = document.createElement("p");
  hint.className = "hint";
  hint.textContent = "Download everything Nexora holds about " +
    "your account — profile, posts, comments, points history, " +
    "followers and following — as one JSON file.";
  card.appendChild(hint);
  const row = document.createElement("div");
  row.className = "data-actions";
  const dl = document.createElement("button");
  dl.className = "data-btn";
  dl.textContent = "⬇️ Download my data";
  dl.onclick = async () => {
    dl.disabled = true;
    setStatus("Preparing your export…");
    try {
      const data = await api("/me/export");
      const blob = new Blob([JSON.stringify(data, null, 1)],
                            { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = "nexora-export.json";
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 4000);
      setStatus("Export downloaded ✓");
    } catch (e) {
      setStatus("Download did not work here — try \u201cSend to " +
                "my Telegram\u201d instead.");
    }
    dl.disabled = false;
  };
  const send = document.createElement("button");
  send.className = "data-btn";
  send.textContent = "📩 Send to my Telegram";
  send.onclick = async () => {
    send.disabled = true;
    setStatus("Sending your export to the bot chat…");
    try {
      const r = await api("/me/export/send", { method: "POST" });
      if (r.sent) setStatus("Sent ✓ — check your chat with the " +
                            "bot for nexora-export.json.");
      else setStatus("The bot could not message you (it may be " +
                     "blocked) — use Download instead.");
    } catch (e) { setStatus("Could not send the export."); }
    send.disabled = false;
  };
  row.append(dl, send);
  card.appendChild(row);
  // The delete endpoint has existed since Phase 28 with the same
  // problem — no button anywhere. It lives here, behind a typed
  // DELETE confirmation exactly as the server demands: the first
  // tap only reveals the confirmation; nothing is sent until the
  // member types DELETE and taps the final button.
  const delBtn = document.createElement("button");
  delBtn.className = "data-btn danger";
  delBtn.textContent = "🗑️ Delete my account";
  const delBox = document.createElement("div");
  delBox.className = "data-del-box";
  delBox.hidden = true;
  const delHint = document.createElement("p");
  delHint.className = "hint";
  delHint.textContent = "This permanently deletes your account, " +
    "posts, comments and points. It cannot be undone. Type " +
    "DELETE to confirm.";
  const delInput = document.createElement("input");
  delInput.type = "text";
  delInput.placeholder = "Type DELETE";
  delInput.autocomplete = "off";
  const delGo = document.createElement("button");
  delGo.className = "data-btn danger";
  delGo.textContent = "Permanently delete";
  delGo.disabled = true;
  delInput.oninput = () => {
    delGo.disabled = delInput.value !== "DELETE";
  };
  delBtn.onclick = () => {
    delBox.hidden = !delBox.hidden;
    if (!delBox.hidden) delInput.focus();
  };
  delGo.onclick = async () => {
    delGo.disabled = true;
    try {
      await api("/me/delete-account", { method: "POST",
        body: JSON.stringify({ confirm: "DELETE" }) });
      localStorage.removeItem("nx_remember");
      sessionStorage.removeItem("nx_entered");
      sessionStorage.removeItem("nx_actas");
      sessionStorage.removeItem("nx_actas_name");
      entryMode = "login";
      paintEntry();
      setStatus("Your account has been deleted.");
    } catch (e) {
      setStatus("Could not delete the account.");
      delGo.disabled = false;
    }
  };
  delBox.append(delHint, delInput, delGo);
  card.append(delBtn, delBox);
  return card;
}

// ---------- Phase 101: After Rain Effect (Me view) ----------
// Owner (Nov 8): "Bot এ Me তে After Rain Effect এড করো" — an
// after-rain look on the Me screen: droplets resting on glass,
// gathering and growing, and now and then one slides down leaving
// a fading trail, under a soft post-rain mist. Purely local and
// per-account (the choice is saved under nx_rain_<telegram_id>,
// the Phase 96/97 pattern), OFF by default, and the canvas runs
// only while the Me (profile) view is on screen. pointer-events
// are off, so it never blocks a tap; prefers-reduced-motion keeps
// it still. No server state, no other member sees it.
let rainRAF = null;
let rainDrops = [];
let rainDpr = 1;
function rainKey() {
  return "nx_rain_" + (me && me.telegram_id ? me.telegram_id : "anon");
}
function rainEnabled() {
  try { return localStorage.getItem(rainKey()) === "1"; }
  catch (e) { return false; }
}
function rainCanvas() {
  let c = $("rain-fx");
  if (!c) {
    c = document.createElement("canvas");
    c.id = "rain-fx";
    c.hidden = true;
    document.body.appendChild(c);
  }
  return c;
}
function rainResize(c) {
  rainDpr = Math.min(window.devicePixelRatio || 1, 2);
  c.width = Math.floor(window.innerWidth * rainDpr);
  c.height = Math.floor(window.innerHeight * rainDpr);
}
function rainSpawn(w, h) {
  return { x: Math.random() * w, y: Math.random() * h,
           r: (0.8 + Math.random() * 2.2) * rainDpr, slide: 0,
           vy: 0, a: 0.25 + Math.random() * 0.4 };
}
function rainStep() {
  const c = rainCanvas();
  if (c.width !== Math.floor(window.innerWidth * rainDpr))
    rainResize(c);
  const ctx = c.getContext("2d");
  const w = c.width, h = c.height;
  ctx.clearRect(0, 0, w, h);
  const maxDrops = Math.min(110, Math.floor(w / 9));
  if (rainDrops.length < maxDrops && Math.random() < 0.5)
    rainDrops.push(rainSpawn(w, h));
  rainDrops = rainDrops.filter(d => d.y - d.r < h + 8);
  const trail = [];
  for (const d of rainDrops) {
    if (!d.slide) {
      if (d.r < 4.6 * rainDpr) d.r += (0.006 + Math.random() * 0.01) * rainDpr;
      if (d.r > 3.4 * rainDpr && Math.random() < 0.004) {
        d.slide = 1; d.vy = 0.4;
      }
    } else {
      d.vy = Math.min(d.vy + 0.06, 3.2);
      d.y += d.vy * rainDpr * 1.4;
      d.r = Math.max(1.1 * rainDpr, d.r - 0.012 * rainDpr);
      if (Math.random() < 0.35)
        trail.push({ x: d.x + (Math.random() - 0.5) * 3 * rainDpr,
          y: d.y - d.r * 2, r: Math.max(0.7 * rainDpr, d.r * 0.4),
          slide: 0, vy: 0, a: d.a * 0.8 });
    }
    const g = ctx.createRadialGradient(
      d.x - d.r * 0.35, d.y - d.r * 0.35, d.r * 0.1,
      d.x, d.y, d.r);
    g.addColorStop(0, "rgba(255,255,255," + (d.a * 0.9) + ")");
    g.addColorStop(0.55, "rgba(190,220,250," + (d.a * 0.45) + ")");
    g.addColorStop(1, "rgba(150,190,235," + (d.a * 0.12) + ")");
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.arc(d.x, d.y, d.r, 0, Math.PI * 2);
    ctx.fill();
  }
  if (trail.length) rainDrops = rainDrops.concat(trail);
  rainRAF = requestAnimationFrame(rainStep);
}
function rainStart() {
  if (rainRAF !== null) return;
  if (window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches)
    return;
  const c = rainCanvas();
  rainResize(c);
  c.hidden = false;
  rainDrops = [];
  rainRAF = requestAnimationFrame(rainStep);
}
function rainStop() {
  if (rainRAF !== null) cancelAnimationFrame(rainRAF);
  rainRAF = null;
  const c = $("rain-fx");
  if (c) {
    c.hidden = true;
    const ctx = c.getContext("2d");
    if (ctx) ctx.clearRect(0, 0, c.width, c.height);
  }
}
function syncRainFx() {
  if (currentView === "profile" && rainEnabled()) rainStart();
  else rainStop();
}
function rainCard() {
  const card = document.createElement("div");
  card.className = "card data-card rain-card";
  const title = document.createElement("b");
  title.textContent = "🌧️ After Rain Effect";
  card.appendChild(title);
  const hint = document.createElement("p");
  hint.className = "hint";
  hint.textContent = "Raindrops rest on the glass over your Me " +
    "screen — they gather, grow, and slide down, like the moments " +
    "just after rain. Only on this screen, and only for you.";
  card.appendChild(hint);
  const btn = document.createElement("button");
  btn.className = "data-btn rain-toggle";
  const paint = () => {
    btn.textContent = rainEnabled()
      ? "🌧️ Rain is ON — tap to turn off"
      : "🌦️ Turn on the rain";
  };
  paint();
  btn.onclick = () => {
    try {
      localStorage.setItem(rainKey(), rainEnabled() ? "0" : "1");
    } catch (e) { /* storage unavailable; the card still paints */ }
    paint();
    syncRainFx();
    setStatus(rainEnabled() ? "After Rain Effect on 🌧️"
                            : "After Rain Effect off");
  };
  card.appendChild(btn);
  return card;
}

function themeCard() {
  const card = document.createElement("div");
  card.className = "card theme-card";
  const head = document.createElement("div");
  head.className = "theme-head";
  const title = document.createElement("b");
  title.textContent = "🎨 Theme Colours";
  const reset = document.createElement("button");
  reset.className = "theme-reset";
  reset.textContent = "Reset";
  reset.onclick = () => {
    themeState.picks = { bg: null, card: null, accent: null };
    themeDropOpen = false;
    saveTheme(); applyUserTheme();
    card.replaceWith(themeCard());
  };
  head.append(title, reset);
  card.appendChild(head);
  const hint = document.createElement("p");
  hint.className = "hint";
  hint.textContent = "Pick a shade and the whole app wears it. " +
    "Choose a zone first to give the background, cards and " +
    "buttons different shades. Text colours adjust on their " +
    "own so everything stays easy to read.";
  card.appendChild(hint);
  const zLabel = document.createElement("div");
  zLabel.className = "theme-label";
  zLabel.textContent = "Apply the shade to:";
  card.appendChild(zLabel);
  const zones = document.createElement("div");
  zones.className = "theme-zones";
  [["all", "🌈 All"], ["bg", "Background"], ["card", "Cards"],
   ["accent", "Accent"]].forEach(([z, label]) => {
    const b = document.createElement("button");
    b.className = "theme-zone" + (themeState.zone === z ? " on" : "");
    b.textContent = label;
    b.onclick = () => {
      themeState.zone = z; themeDropOpen = false; saveTheme();
      card.replaceWith(themeCard());
    };
    zones.appendChild(b);
  });
  card.appendChild(zones);
  // Phase 91 (owner): the fifteen shades as one tidy
  // dropdown instead of the long grid — a button showing
  // the current shade for the chosen zone, opening a neat
  // scrollable list; picking applies at once and closes it.
  const drop = document.createElement("div");
  drop.className = "theme-drop";
  const dropBtn = document.createElement("button");
  dropBtn.className = "theme-drop-btn";
  const curFor = z => z === "all"
    ? (themeState.picks.bg &&
       themeState.picks.bg === themeState.picks.card &&
       themeState.picks.bg === themeState.picks.accent
         ? palById(themeState.picks.bg) : null)
    : palById(themeState.picks[z]);
  const cur = curFor(themeState.zone);
  const swatch = document.createElement("span");
  swatch.className = "theme-drop-swatch";
  swatch.style.background = cur
    ? "linear-gradient(90deg," + cur.stops.join(",") + ")"
    : "linear-gradient(90deg,#8ED4F7,#FBB931,#7BE0A3,#38BDF8)";
  const dtext = document.createElement("span");
  dtext.className = "theme-drop-text";
  dtext.textContent = cur ? "Shade: " + cur.name : "Choose your shade";
  const chev = document.createElement("span");
  chev.className = "theme-drop-chev";
  chev.textContent = themeDropOpen ? "▲" : "▼";
  dropBtn.append(swatch, dtext, chev);
  dropBtn.onclick = () => {
    themeDropOpen = !themeDropOpen;
    card.replaceWith(themeCard());
  };
  drop.appendChild(dropBtn);
  if (themeDropOpen) {
    const list = document.createElement("div");
    list.className = "theme-drop-list";
    const lhead = document.createElement("div");
    lhead.className = "theme-drop-head";
    lhead.textContent = "🎨 Choose a shade";
    list.appendChild(lhead);
    THEME_PALETTES.forEach(p => {
      const row = document.createElement("button");
      const onThisZone = themeState.zone === "all"
        ? themeState.picks.bg === p.id &&
          themeState.picks.card === p.id &&
          themeState.picks.accent === p.id
        : themeState.picks[themeState.zone] === p.id;
      row.className = "theme-drop-item" + (onThisZone ? " on" : "");
      const strip = document.createElement("span");
      strip.className = "theme-strip";
      strip.style.background = "linear-gradient(90deg," +
        p.stops.join(",") + ")";
      const nm = document.createElement("span");
      nm.className = "theme-name";
      nm.textContent = p.name;
      row.append(strip, nm);
      const where = [];
      if (themeState.picks.bg === p.id) where.push("Bg");
      if (themeState.picks.card === p.id) where.push("Cards");
      if (themeState.picks.accent === p.id) where.push("Accent");
      if (where.length) {
        const w = document.createElement("span");
        w.className = "theme-where";
        w.textContent = "✓ " + where.join(" · ");
        row.appendChild(w);
      }
      row.onclick = () => {
        const z = themeState.zone;
        if (z === "all")
          themeState.picks = { bg: p.id, card: p.id, accent: p.id };
        else themeState.picks[z] = p.id;
        themeDropOpen = false;
        saveTheme(); applyUserTheme();
        card.replaceWith(themeCard());
      };
      list.appendChild(row);
    });
    drop.appendChild(list);
  }
  card.appendChild(drop);
  const now = document.createElement("p");
  now.className = "hint theme-now";
  const nmOf = id => (palById(id) || {}).name || "Default pink";
  now.textContent = "Now: Background " + nmOf(themeState.picks.bg) +
    " · Cards " + nmOf(themeState.picks.card) +
    " · Accent " + nmOf(themeState.picks.accent);
  card.appendChild(now);
  return card;
}

// -------------------------------------------------------------- profile ---
async function openProfile(userId) {
  profileId = userId;
  profileCursor = null;
  showView("profile");
  const box = $("profile-box");
  box.innerHTML = "Loading…";
  $("profile-posts").innerHTML = "";
  try {
    const u = await api("/users/" + userId);
    box.innerHTML = "";
    // Phase 40: the cover banner tops every profile (a soft
    // gradient placeholder until the member sets one).
    const cover = document.createElement("div");
    cover.className = "profile-cover";
    if (u.cover_file_id) {
      const ci = document.createElement("img");
      ci.src = mediaUrl(u.cover_file_id);
      ci.alt = "";
      cover.appendChild(ci);
    }
    const ownProfile = me && userId === me.telegram_id;
    if (ownProfile) {
      // Phase 55 (owner): no wide "Change cover photo" button —
      // a camera badge ON the cover does the job.
      const cam = document.createElement("button");
      cam.className = "cam-badge cover-cam";
      cam.textContent = "📷";
      cam.title = "Change cover photo";
      cam.onclick = () => $("cover-file").click();
      cover.appendChild(cam);
    }
    // Phase 105 (owner): the profile header is a two-tone hero —
    // cover + avatar + name + bio + followers in one gradient zone,
    // with a glowing snake wave where it meets the body below.
    const hero = document.createElement("div");
    hero.className = "profile-hero";
    hero.appendChild(cover);
    const headWrap = document.createElement("div");
    headWrap.className = "profile-head";
    const col = document.createElement("div");
    const name = document.createElement("div");
    name.className = "profile-name";
    name.textContent = u.first_name;
    if (u.is_verified) name.appendChild(verifiedBadge());
    const sub = document.createElement("div");
    sub.className = "profile-sub";
    sub.textContent = u.username ? "@" + u.username : "";
    col.append(name, sub);
    const avEl = avatarEl(u.first_name, u.telegram_id, true,
                          u.photo_file_id);
    if (ownProfile) {
      // Phase 55: same for the profile photo — camera badge on
      // the avatar itself opens the photo picker.
      const avWrap = document.createElement("div");
      avWrap.className = "avatar-wrap";
      const cam = document.createElement("button");
      cam.className = "cam-badge avatar-cam";
      cam.textContent = "📷";
      cam.title = "Change profile photo";
      cam.onclick = () => $("profile-file").click();
      avWrap.append(avEl, cam);
      headWrap.append(avWrap, col);
    } else {
      headWrap.append(avEl, col);
    }
    const bio = document.createElement("p");
    bio.textContent = u.bio || "";
    const stats = document.createElement("div");
    stats.className = "stats";
    // Phase 57 (owner): no posts count and no points in this
    // line — posts are listed below and points have their own
    // card. Followers / following only.
    stats.textContent = u.followers + " followers · " +
      u.following_count + " following";
    hero.append(headWrap, bio, stats);
    box.appendChild(hero);
    const wave = document.createElement("div");
    wave.className = "wave-div";
    wave.innerHTML = '<svg viewBox="0 0 720 56" preserveAspectRatio="none" aria-hidden="true">'
      + '<path class="wave-fill" d="M0,30 C120,8 240,52 360,30 C480,8 600,52 720,30 L720,56 L0,56 Z"/>'
      + '<path class="wave-line" d="M0,30 C120,8 240,52 360,30 C480,8 600,52 720,30" fill="none"/>'
      + '</svg>';
    box.appendChild(wave);

    if (u.is_official) {
      const chip = document.createElement("button");
      chip.className = "wide";
      chip.disabled = true;
      chip.textContent = "✓ Following — Official account";
      box.appendChild(chip);
      const omBtn = document.createElement("button");
      omBtn.className = "wide";
      omBtn.textContent = "💬 Message";
      omBtn.onclick = () => openChat(userId);
      box.appendChild(omBtn);
    } else if (me && userId !== me.telegram_id) {
      const fBtn = document.createElement("button");
      fBtn.className = "wide btn";
      const paint = () => { fBtn.textContent = u.following ? "Unfollow" : "Follow"; };
      paint();
      fBtn.onclick = async () => {
        try {
          const r = await api("/users/" + userId + "/follow", { method: "POST" });
          u.following = r.following;
          u.followers = r.followers;
          stats.textContent = u.followers + " followers · " +
            u.following_count + " following";
          paint();
        } catch (e) { setStatus("Could not update follow."); }
      };
      box.appendChild(fBtn);
      const mBtn = document.createElement("button");
      mBtn.className = "wide";
      mBtn.textContent = "💬 Message";
      mBtn.onclick = () => openChat(userId);
      box.appendChild(mBtn);
      // R5 (security §5): Block/Unblock — the member's self-help
      // control. While blocked, the follow button hides (the server
      // refuses follows between blocked pairs anyway).
      const bBtn = document.createElement("button");
      bBtn.className = "wide block-btn";
      const paintBlock = () => {
        bBtn.textContent = u.blocked_by_me
          ? "🚫 Blocked — tap to unblock" : "🚫 Block this member";
        fBtn.hidden = !!u.blocked_by_me;
        mBtn.hidden = !!u.blocked_by_me;
      };
      paintBlock();
      bBtn.onclick = async () => {
        try {
          const r = await api("/users/" + userId + "/block",
                              { method: "POST" });
          u.blocked_by_me = r.blocked;
          if (r.blocked) { u.following = false; paint(); }
          paintBlock();
          setStatus(r.blocked
            ? "Member blocked — you will no longer see each other's posts."
            : "Member unblocked.");
        } catch (e) { setStatus("Could not update block."); }
      };
      box.appendChild(bBtn);
    }

    if (me && userId === me.telegram_id) {
      // Phase 55: the wide Change-photo / Change-cover buttons
      // are gone — camera badges on the photo and cover above
      // open the same pickers.
      // Phase 40: write your own name + bio.
      const eBtn = document.createElement("button");
      eBtn.className = "wide";
      eBtn.textContent = "✏️ Edit name & bio";
      const form = document.createElement("div");
      form.className = "card profile-edit";
      form.hidden = true;
      const nameIn = document.createElement("input");
      nameIn.type = "text";
      nameIn.maxLength = 128;
      nameIn.placeholder = "Your name";
      nameIn.value = u.first_name || "";
      // Phase 42: the name changes once every 60 days — while
      // the lock runs, the field is disabled and says why.
      if (u.name_locked_days > 0) nameIn.disabled = true;
      const bioIn = document.createElement("textarea");
      bioIn.maxLength = 500;
      bioIn.rows = 3;
      bioIn.placeholder = "Write something about yourself…";
      bioIn.value = u.bio || "";
      const saveBtn = document.createElement("button");
      saveBtn.className = "wide";
      saveBtn.textContent = "Save profile";
      saveBtn.onclick = async () => {
        try {
          const r = await api("/me/profile", { method: "POST",
            body: JSON.stringify({ first_name: nameIn.value,
                                   bio: bioIn.value }) });
          if (me) { me.first_name = r.first_name; }
          setStatus("Profile updated.");
          openProfile(userId);
        } catch (e) { setStatus("Could not save the profile."); }
      };
      form.append(nameIn, bioIn, saveBtn);
      if (u.name_locked_days > 0) {
        const note = document.createElement("div");
        note.className = "gb-foot-sub";
        note.textContent = "🔒 Name can be changed once every"
          + " 60 days — available again in " + u.name_locked_days
          + " day" + (u.name_locked_days === 1 ? "" : "s")
          + ". Your bio can still be edited anytime.";
        form.insertBefore(note, bioIn);
      }
      eBtn.onclick = () => { form.hidden = !form.hidden; };
      box.append(eBtn, form);
    }

    if (me && userId === me.telegram_id) box.appendChild(await myExtras());
    await loadProfilePosts(true);
  } catch (e) { box.textContent = "Could not load the profile."; }
}

async function loadProfilePosts(reset) {
  try {
    const url = "/users/" + profileId + "/posts" +
      (reset || !profileCursor ? "" : "?cursor=" + profileCursor);
    const data = await api(url);
    if (reset) $("profile-posts").innerHTML = "";
    data.posts.forEach(p => $("profile-posts").appendChild(postCard(p)));
    profileCursor = data.next_cursor;
    $("profile-more").hidden = !profileCursor;
  } catch (e) { setStatus("Could not load posts."); }
}

async function myExtras() {
  const wrap = document.createElement("div");
  wrap.className = "extras";
  try {
    const pts = await api("/me/points");
    const refs = await api("/me/referrals");
    // Phase 55 (owner): the points section was a plain bullet
    // list of raw ledger codes — now a proper card: gradient
    // balance header (+ today's earnings chip) and friendly
    // labelled history rows with icons and amount pills.
    const REASON_META = {
      "task:checkin": ["📅", "Daily check-in"],
      "task:follow2": ["👥", "Follow task"],
      "task:follow3": ["👥", "Follow task"],
      "task:comment5": ["💬", "Comment task"],
      "task:react6": ["❤️", "React task"],
      "task:adwatch": ["📺", "Ad task"],
      "referral": ["🔗", "Referral bonus"],
      "post": ["📝", "New post"],
      "admin_adjust": ["🛡️", "Admin adjustment"],
    };
    const card = document.createElement("div");
    card.className = "points-card";
    const pHead = document.createElement("div");
    pHead.className = "points-head";
    const star = document.createElement("div");
    star.className = "points-star";
    star.textContent = "⭐";
    const pCol = document.createElement("div");
    const pLabel = document.createElement("div");
    pLabel.className = "points-label";
    pLabel.textContent = "My Points";
    const pBal = document.createElement("div");
    pBal.className = "points-balance";
    pBal.textContent = pts.balance;
    pCol.append(pLabel, pBal);
    pHead.append(star, pCol);
    const todayStr = new Date().toDateString();
    const todaySum = pts.entries
      .filter(e => e.created_at &&
              new Date(e.created_at).toDateString() === todayStr)
      .reduce((s, e) => s + e.amount, 0);
    if (todaySum > 0) {
      const chip = document.createElement("div");
      chip.className = "points-today";
      chip.textContent = "+" + todaySum + " today";
      pHead.appendChild(chip);
    }
    card.appendChild(pHead);
    pts.entries.forEach(e => {
      const meta = REASON_META[e.reason] || ["⭐", e.reason];
      const rowEl = document.createElement("div");
      rowEl.className = "ph-row";
      const ic = document.createElement("span");
      ic.className = "ph-ic";
      ic.textContent = meta[0];
      const main = document.createElement("div");
      main.className = "ph-main";
      const lb = document.createElement("div");
      lb.className = "ph-label";
      lb.textContent = meta[1];
      main.appendChild(lb);
      if (e.created_at) {
        const dt = document.createElement("div");
        dt.className = "ph-date";
        dt.textContent = new Date(e.created_at)
          .toLocaleDateString(undefined,
            { day: "numeric", month: "short" });
        main.appendChild(dt);
      }
      const amt = document.createElement("span");
      amt.className = "ph-amt " + (e.amount >= 0 ? "plus" : "minus");
      amt.textContent = (e.amount >= 0 ? "+" : "") + e.amount;
      rowEl.append(ic, main, amt);
      card.appendChild(rowEl);
    });
    wrap.appendChild(card);
    if (me.bot_username) {
      const link = "https://t.me/" + me.bot_username + "?start=ref_" + me.telegram_id;
      const rh = document.createElement("h3");
      rh.textContent = "🔗 Referrals: " + refs.total +
        " (" + refs.referrals.filter(r => r.qualified).length + " qualified)";
      const a = document.createElement("a");
      a.href = link;
      a.textContent = link;
      const copy = document.createElement("button");
      copy.textContent = "Copy link";
      copy.onclick = () => {
        if (navigator.clipboard) navigator.clipboard.writeText(link);
        setStatus("Referral link copied.");
      };
      wrap.append(rh, a, copy);
    }
  } catch (e) { setStatus("Could not load points/referrals."); }
  const savedBtn = document.createElement("button");
  savedBtn.className = "wide";
  savedBtn.textContent = "🔖 Saved posts & videos";
  savedBtn.onclick = () => showView("saved");
  wrap.appendChild(savedBtn);
  const sharedBtn = document.createElement("button");
  sharedBtn.className = "wide";
  sharedBtn.textContent = "📥 Shared with me";
  sharedBtn.onclick = () => showView("shared");
  wrap.appendChild(sharedBtn);
  try {
    const mon = await api("/me/monetization");
    const card = document.createElement("div");
    card.className = "mon-card fancy";
    // Phase 57 (owner): decorate the monetization section —
    // gold hero header, an overall progress bar, and one
    // icon + progress-bar row per target.
    const hero = document.createElement("div");
    hero.className = "mon-hero";
    const blob = document.createElement("div");
    blob.className = "mon-blob";
    blob.textContent = "💰";
    const hCol = document.createElement("div");
    const hSub = document.createElement("div");
    hSub.className = "mon-sub";
    hSub.textContent = "Creator earnings";
    const hTitle = document.createElement("div");
    hTitle.className = "mon-title";
    hTitle.textContent = "Monetization";
    hCol.append(hSub, hTitle);
    const badge = document.createElement("span");
    badge.className = "mon-badge" + (mon.unlocked ? " open" : "");
    badge.textContent = mon.unlocked ? "Unlocked ✓" : "🔒 Locked";
    hero.append(blob, hCol, badge);
    card.appendChild(hero);
    const doneCount = mon.checks.filter(c => c.done).length;
    const ov = document.createElement("div");
    ov.className = "mon-overall";
    const ovL = document.createElement("span");
    ovL.textContent = doneCount + " of " + mon.checks.length +
      " targets met";
    const ovR = document.createElement("span");
    ovR.textContent = mon.checks.length
      ? Math.round(doneCount / mon.checks.length * 100) + "%" : "";
    ov.append(ovL, ovR);
    const ovBar = document.createElement("div");
    ovBar.className = "mon-bar big";
    const ovFill = document.createElement("i");
    ovFill.style.width = (mon.checks.length
      ? doneCount / mon.checks.length * 100 : 0) + "%";
    ovBar.appendChild(ovFill);
    card.append(ov, ovBar);
    const MON_ICONS = [
      ["Referral", "🔗"],
      ["Follower", "👥"], ["Posts", "📝"], ["age", "📅"],
      ["points", "⭐"], ["streak", "🔥"],
    ];
    mon.checks.forEach(c => {
      const row = document.createElement("div");
      row.className = "mon-check";
      const ic = document.createElement("span");
      ic.className = "ph-ic";
      const found = MON_ICONS.find(([k]) => c.label.includes(k));
      ic.textContent = found ? found[1] : "🎯";
      const main = document.createElement("div");
      main.className = "mc-main";
      const lb = document.createElement("div");
      lb.className = "mc-label";
      lb.textContent = c.label + (c.done ? " ✅" : "");
      const bar = document.createElement("div");
      bar.className = "mon-bar";
      const fill = document.createElement("i");
      fill.style.width = Math.min(100, c.required
        ? c.current / c.required * 100 : 0) + "%";
      if (c.done) fill.className = "done";
      bar.appendChild(fill);
      main.append(lb, bar);
      const right = document.createElement("span");
      right.className = "mc-count" + (c.done ? " done" : "");
      right.textContent = c.current + " / " + c.required;
      row.append(ic, main, right);
      card.appendChild(row);
    });
    const note = document.createElement("p");
    note.className = "hint";
    note.textContent = mon.unlocked
      ? "You meet every target — monetization is unlocked for your account."
      : "Meet every target to unlock monetization for your account.";
    card.appendChild(note);
    wrap.appendChild(card);
  } catch (e) { /* monetization card is optional decoration */ }
  try {
    // Phase 22: blue-tick verification card (owner rule: applications
    // open at 1,000 followers; the admin reviews them).
    const ver = await api("/me/verification");
    const card = document.createElement("div");
    card.className = "mon-card";
    const vh = document.createElement("div");
    vh.className = "mon-head";
    const vt = document.createElement("b");
    vt.textContent = "🛡️ Verification";
    const vb = document.createElement("span");
    if (ver.is_verified) {
      vb.className = "mon-badge open";
      vb.textContent = "Verified ✓";
    } else if (ver.pending) {
      vb.className = "mon-badge";
      vb.textContent = "Under review ⏳";
    } else {
      vb.className = "mon-badge";
      vb.textContent = ver.can_apply ? "You can apply" : "Locked";
    }
    vh.append(vt, vb);
    card.appendChild(vh);
    const row = document.createElement("div");
    row.className = "mon-row";
    const left = document.createElement("span");
    left.textContent = (ver.followers >= ver.required ? "✅ " : "⬜ ") +
      "👥 Followers for the blue tick";
    const right = document.createElement("span");
    right.className = ver.followers >= ver.required ? "done" : "";
    right.textContent = ver.followers + " / " + ver.required;
    row.append(left, right);
    card.appendChild(row);
    const note = document.createElement("p");
    note.className = "hint";
    if (ver.is_verified) {
      note.textContent = "Your account carries the blue tick ✓.";
      card.appendChild(note);
    } else if (ver.pending) {
      note.textContent = "Your application is with the admin team. " +
        "You will get a notification when it is decided.";
      card.appendChild(note);
    } else if (ver.can_apply) {
      note.textContent = ver.last_status === "rejected"
        ? "Your last application was not approved. You may apply again."
        : "You have enough followers to apply for the blue tick.";
      card.appendChild(note);
      const btn = document.createElement("button");
      btn.className = "wide";
      btn.textContent = "Apply for the Blue Tick ✓";
      btn.onclick = async () => {
        btn.disabled = true;
        try {
          await api("/me/verification/apply", { method: "POST" });
          btn.textContent = "⏳ Application sent — under review";
          setStatus("Verification application sent.");
        } catch (e) {
          btn.disabled = false;
          setStatus("Could not send the application.");
        }
      };
      card.appendChild(btn);
    } else {
      note.textContent = "Reach " + ver.required +
        " followers to apply for the blue tick.";
      card.appendChild(note);
    }
    wrap.appendChild(card);
  } catch (e) { /* verification card is optional decoration */ }
  // Phase 90 (owner): the theme-shade picker lives in the Me
  // section, under the points and monetization cards. It is
  // purely local, so it renders even if the cards above fail.
  wrap.appendChild(themeCard());
  // Phase 100: Data Control sits under Theme Colours and renders
  // unconditionally, like the theme card.
  wrap.appendChild(dataCard());
  // Phase 101: the After Rain toggle sits under Data
  // Control and, like the cards above, always renders.
  wrap.appendChild(rainCard());
  return wrap;
}

// ---------------------------------------------------------------- tasks ---
async function loadTasks() {
  const box = $("task-list");
  box.innerHTML = "Loading…";
  try {
    const data = await api("/me/tasks");
    box.innerHTML = "";
    data.tasks.forEach(t => {
      const card = document.createElement("div");
      card.className = "task-card";
      const top = document.createElement("div");
      top.className = "task-top";
      const icon = document.createElement("span");
      icon.className = "task-icon";
      icon.textContent = t.icon;
      const title = document.createElement("span");
      title.className = "task-title";
      title.textContent = t.title;
      const pts = document.createElement("span");
      pts.className = "task-points";
      pts.textContent = "+" + t.points + " pts";
      top.append(icon, title, pts);
      const bar = document.createElement("div");
      bar.className = "bar";
      const fill = document.createElement("div");
      fill.style.width = Math.round(100 * t.progress / t.target) + "%";
      bar.appendChild(fill);
      const meta = document.createElement("div");
      meta.className = "task-meta";
      const prog = document.createElement("span");
      prog.textContent = t.progress + " / " + t.target +
        (t.streak != null ? " · 🔥 " + t.streak + " day streak" : "");
      const btn = document.createElement("button");
      if (t.claimed) {
        btn.textContent = "✓ Claimed";
        btn.className = "task-claim claimed btn";
        btn.disabled = true;
      } else if (t.claimable) {
        btn.textContent = "Claim";
        btn.className = "task-claim btn";
        btn.onclick = async () => {
          try {
            const r = await api("/me/tasks/" + t.key + "/claim", { method: "POST" });
            setStatus("+" + r.points_awarded + " points! Balance: " + r.balance);
            loadMe().catch(() => {});
            loadTasks();
          } catch (e) { setStatus("Could not claim this task."); }
        };
      } else if (t.key === "adwatch") {
        // Phase 113 (owner): the ad task is done by tapping to watch
        // an ad — a real completed show reports /ads/shown, which is
        // what unlocks the claim. No fill, no points.
        btn.textContent = "▶️ Watch ad";
        btn.className = "task-claim btn";
        btn.onclick = () => showTaskAd(btn);
      } else {
        btn.textContent = "In progress";
        btn.disabled = true;
      }
      meta.append(prog, btn);
      card.append(top, bar, meta);
      box.appendChild(card);
    });
  } catch (e) { box.textContent = "Could not load tasks."; }
}

// ----------------------------------------------------------------- init ---
// ---------------------------------------------------------------------------
// Phase 19: heartbeat — while the app is open, a beat every 30s lets the
// server measure real time-in-app and "active now" for the dashboard.
// ---------------------------------------------------------------------------
let heartbeatTimer = null;
function sendHeartbeat() {
  api("/me/heartbeat", { method: "POST" }).catch(() => {});
}
function startHeartbeat() {
  if (heartbeatTimer) return;
  sendHeartbeat();
  heartbeatTimer = setInterval(sendHeartbeat, 30000);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) sendHeartbeat();
  });
}

async function loadMe() {
  me = await api("/auth", { method: "POST", body: JSON.stringify({ initData }) });
  if (me.media_token) mediaToken = me.media_token;
  loadAccountTheme();
  startHeartbeat();
  // Phase 53 (owner): the hero identity strip (name, counts,
  // points chip) is gone — it sat on every user's screen and
  // looked cluttered; all of it still lives on the profile
  // and in Tasks.
  $("entry-name").textContent = me.first_name || "Full name";
  $("entry-user").textContent = me.username ? "@" + me.username : "Username";
  entryMode = me.is_new ? "signup" : "login";
  paintEntry();
  applyAdminVisibility();
  maybeOpenAdmin();
  refreshBell();
  refreshMsgBadge();
  paintGlassFoot();
  initAds();
  if (!me.photo_file_id) {
    api("/me/photo/sync", { method: "POST" }).then(r => {
      if (r && r.photo_file_id) me.photo_file_id = r.photo_file_id;
    }).catch(() => {});
  }
}

function composerStatus(msg) {
  const el = $("composer-status");
  if (el) el.textContent = msg || "";
}

let composerFile = null;
let composerUploadId = null;

function paintAttach() {
  const chip = $("composer-attach");
  if (!composerFile) { chip.hidden = true; chip.textContent = ""; return; }
  chip.hidden = false;
  chip.textContent = (composerFile.type.startsWith("video") ? "🎬 " : "🖼 ") +
    composerFile.name + " ";
  const x = document.createElement("button");
  x.className = "attach-x";
  x.textContent = "✕";
  x.title = "Remove";
  x.onclick = () => { composerFile = null; composerUploadId = null; $("composer-file").value = ""; paintAttach(); };
  chip.appendChild(x);
}

$("composer-media").onclick = () => $("composer-file").click();
$("composer-file").onchange = () => {
  composerFile = $("composer-file").files[0] || null;
  composerStatus("");
  if (composerFile) {
    // Phase 19 caps: photos 20 MB; videos up to 60 MB (the server
    // shrinks them to fit Telegram before posting). Phase 26: some
    // phone pickers report an empty or generic MIME type, so the
    // file-name extension decides the kind when the type is vague.
    const t = (composerFile.type || "").toLowerCase();
    const ext = (composerFile.name || "").split(".").pop()
      .toLowerCase();
    const isVideo = t.startsWith("video") ||
      ["mp4", "mov", "webm", "mkv", "3gp", "avi", "m4v"].includes(ext);
    const cap = (isVideo ? 60 : 20) * 1024 * 1024;
    if (composerFile.size > cap) {
      composerStatus(isVideo
        ? "That video is over 60 MB — please trim it or record at a lower resolution."
        : "That file is over 20 MB — please pick a smaller one.");
      composerFile = null;
      composerUploadId = null;
      $("composer-file").value = "";
    } else {
      composerUploadId = newUploadId();
      composerStatus("Attached ✓ — now tap Post.");
    }
  }
  paintAttach();
};

$("composer-post").onclick = async () => {
  const text = $("composer-text").value.trim();
  if (!text && !composerFile) {
    // Phase 26: never a silent no-op — say what is missing, right
    // under the button where the member is looking.
    composerStatus("Write something or attach a photo/video first 📷");
    return;
  }
  const btn = $("composer-post");
  btn.disabled = true;
  composerStatus("");
  try {
    if (composerFile) {
      btn.textContent = "Uploading…";
      const form = new FormData();
      form.append("file", await shrinkForUpload(composerFile));
      form.append("caption", text);
      // Phase 83 (owner): a visible progress bar, not just the
      // button text — real % while the bytes go up, an animated
      // "Posting…" state while the server finishes (Telegram send
      // + safety check), then the outcome.
      const bar = $("composer-progress"),
            fill = $("composer-progress-fill"),
            lab = $("composer-progress-label");
      bar.hidden = false;
      fill.classList.remove("busy", "done");
      fill.style.width = "0%";
      lab.textContent = "Uploading… 0%";
      const res = await apiFormProgress("/posts/upload", form, pct => {
        if (pct === null) {
          fill.style.width = "100%";
          fill.classList.add("busy");
          lab.textContent = "Posting…";
          btn.textContent = "Sending… keep the app open";
        } else {
          fill.style.width = pct + "%";
          lab.textContent = "Uploading… " + pct + "%";
          btn.textContent = "Uploading… " + pct + "%";
        }
      }, composerUploadId);
      if (res && res.status === "processing") {
        lab.textContent = "🎬 Processing video…";
        setStatus("🎬 Video received! It's being processed — the bot " +
          "will message you when it's live in Videos.");
        composerStatus("🎬 Video received — the bot will message " +
          "you when it's live in Videos.");
      } else {
        fill.classList.remove("busy");
        fill.classList.add("done");
        lab.textContent = "Posted ✓";
      }
      setTimeout(() => { bar.hidden = true; }, 3000);
      composerFile = null;
      composerUploadId = null;
      $("composer-file").value = "";
      paintAttach();
    } else {
      await api("/posts", { method: "POST",
        body: JSON.stringify({ type: "text", caption: text }) });
    }
    $("composer-text").value = "";
    setTab("explore");
    loadMe().catch(() => {});
  } catch (e) {
    $("composer-progress").hidden = true;
    composerStatus(e.message || "Could not post.");
    setStatus(e.message || "Could not post.");
  }
  btn.disabled = false;
  btn.textContent = "Post";
};

$("profile-file").onchange = async () => {
  const f = $("profile-file").files[0];
  $("profile-file").value = "";
  if (!f) return;
  const form = new FormData();
  form.append("file", await shrinkForUpload(f));
  try {
    const r = await apiForm("/me/photo/upload", form);
    if (me) me.photo_file_id = r.photo_file_id;
    setStatus("Profile photo updated.");
    if (me) openProfile(me.telegram_id);
  } catch (e) { setStatus(e.message || "Could not update the photo."); }
};
$("cover-file").onchange = async () => {
  const f = $("cover-file").files[0];
  $("cover-file").value = "";
  if (!f) return;
  const form = new FormData();
  form.append("file", await shrinkForUpload(f));
  try {
    await apiForm("/me/cover/upload", form);
    setStatus("Cover photo updated.");
    if (me) openProfile(me.telegram_id);
  } catch (e) { setStatus(e.message || "Could not update the cover."); }
};
$("tab-explore").onclick = () => setTab("explore");
$("tab-following").onclick = () => setTab("following");
$("feed-more").onclick = () => loadFeed(false);
$("profile-more").onclick = () => loadProfilePosts(false);
$("search-go").onclick = () => runSearch($("search-input").value.trim());
// Phase 63 (owner): pressing Enter in the search bar must search
// too — the button was the only trigger, and the input sits in no
// form, so Enter did nothing at all.
$("search-input").addEventListener("keydown", e => {
  if (e.key === "Enter") {
    e.preventDefault();
    runSearch($("search-input").value.trim());
    $("search-input").blur();
  }
});
$("nav-feed").onclick = () => showView("feed");
$("nav-videos").onclick = () => showView("videos");
$("nav-design").onclick = () => showView("designs");
$("nav-games").onclick = () => showView("games");
$("nav-tasks").onclick = () => showView("tasks");
$("nav-ranks").onclick = () => showView("leaderboard");
$("nav-me").onclick = () => { if (me) openProfile(me.telegram_id); };
$("hero-search").onclick = () => showView("search");
$("vtab-explore").onclick = () => setVTab("explore");
$("vtab-following").onclick = () => setVTab("following");
$("video-more").onclick = () => loadVideos(false);
$("reel-close").onclick = () => showView("feed");
$("reel-sheet-backdrop").onclick = () => closeReelMenu();
$("saved-back").onclick = () => { if (me) openProfile(me.telegram_id); };
$("shared-back").onclick = () => { if (me) openProfile(me.telegram_id); };
$("reel-sound").onclick = () => {
  reelMuted = !reelMuted;
  document.querySelectorAll("#video-list video").forEach(v => { v.muted = reelMuted; });
  $("reel-sound").textContent = reelMuted ? "🔇" : "🔊";
};

function bootFailed() {
  $("status").textContent = "Please open this app from inside Telegram.";
  $("entry-go").disabled = true;
  $("entry-note").textContent =
    "Please open Nexora Social from inside Telegram to continue.";
}
loadMe().then(() => loadFeed(true)).catch(() => {
  // Phase 76: the first attempt can fail while the free server
  // wakes up — retry once before showing the fallback above.
  setTimeout(() => {
    loadMe().then(() => loadFeed(true)).catch(bootFailed);
  }, 2000);
});

// Phase 76 (owner screenshot: every image on the site broken
// after a slow first open, while the data itself loaded fine):
// the WebView never retries a failed image, so one cold-start
// hiccup left the whole gallery broken until a manual reload.
// Any /media image or video that fails now retries itself with
// a short pause and a cache-buster, up to three times.
document.addEventListener("error", (e) => {
  const t = e.target;
  if (!t || (t.tagName !== "IMG" && t.tagName !== "VIDEO")) return;
  const src = t.getAttribute("src") || "";
  if (!src.includes("/media/")) return;
  const tries = Number(t.dataset.mr || 0);
  if (tries >= 3) return;
  t.dataset.mr = tries + 1;
  const bust = (src.includes("?") ? "&r=" : "?r=") + (tries + 1);
  setTimeout(() => { t.src = src + bust; }, 800 * (tries + 1));
}, true);

// ---------------------------------------------------- entry (Sign Up/Login) ---
// Neumorphic entry screens in the owner's chosen design (Oct 31).
// Inside Telegram there is no password: Telegram itself is the secure
// sign-in, so the fields show the member's real name/username and the
// button simply enters the app. "Remember me" skips this screen on
// future opens; without it, the screen greets every fresh open.
let entryMode = "login";

function paintEntry() {
  const signup = entryMode === "signup";
  $("entry-title").textContent = signup ? "Sign Up" : "Login";
  $("entry-sub").textContent = signup
    ? "Create your account" : "Sign in to your account";
  $("entry-go").textContent = signup ? "CREATE ACCOUNT" : "SIGN IN";
  $("entry-switch-text").textContent = signup
    ? "Already have an account?" : "Don't have an account?";
  $("entry-toggle").textContent = signup ? "Login" : "Sign up";
  $("entry-field-name").hidden = !signup;
  $("entry-remember-row").hidden = signup;
}

$("entry-toggle").onclick = e => {
  e.preventDefault();
  entryMode = entryMode === "signup" ? "login" : "signup";
  paintEntry();
};
$("entry-forgot").onclick = e => {
  e.preventDefault();
  $("entry-note").textContent =
    "No password to reset — your Telegram account is your key. 🔐";
};
$("entry-go").onclick = () => {
  if ($("entry-remember").checked) localStorage.setItem("nx_remember", "1");
  else localStorage.removeItem("nx_remember");
  sessionStorage.setItem("nx_entered", "1");
  $("entry-screen").hidden = true;
};
if (localStorage.getItem("nx_remember") === "1" ||
    sessionStorage.getItem("nx_entered") === "1") {
  $("entry-screen").hidden = true;
}
paintEntry();

// ------------------------------------------------- glassy sidebar (P39) --
// Owner reference: a "Glassy SideBar" video — a slim frosted-glass
// icon rail floats at the left edge; tapping its chevron expands
// it with a spring animation into a wide glass
// panel with labels, sections and the member's profile at the
// bottom. This REPLACES the old slide-in drawer entirely; every
// destination the drawer had lives here.
// Phase 45 (owner): the hero ☰ button duplicated this control —
// removed; the pill is the ONE way to open the sidebar.
function openSidebar() {
  $("glassbar").classList.add("open");
  updateBackButton();
  // Phase 48: the inline top belongs to the dragged pill spot;
  // the open panel always docks to the top of its side.
  $("glassbar").style.top = "";
  $("gb-backdrop").hidden = false;
  syncSidebarActive();
  api("/me/saved").then(list => {
    const b = $("badge-saved");
    b.textContent = list.length;
    b.hidden = !list.length;
  }).catch(() => {});
  api("/me/shared").then(list => {
    const b = $("badge-shared");
    b.textContent = list.length;
    b.hidden = !list.length;
  }).catch(() => {});
}
function closeSidebar() {
  $("glassbar").classList.remove("open");
  updateBackButton();
  $("gb-backdrop").hidden = true;
  gbRestorePos();  // Phase 48: the pill returns to its dragged spot
}
function toggleSidebar() {
  if ($("glassbar").classList.contains("open")) closeSidebar();
  else openSidebar();
}
function syncSidebarActive() {
  const current = ["feed", "videos", "designs", "search", "tasks",
    "leaderboard", "profile", "saved", "shared", "games", "game",
    "nearby", "messages", "notifications"]
    .find(v => !$("view-" + v).hidden) || "feed";
  const key = current === "game" ? "games" : current;
  document.querySelectorAll(".gb-item[data-go]").forEach(b =>
    b.classList.toggle("active", b.dataset.go === key));
}
function paintGlassFoot() {
  if (!me) return;
  const av = $("gb-foot-avatar");
  av.innerHTML = "";
  av.appendChild(avatarEl(me.first_name, me.telegram_id, false,
                          me.photo_file_id));
  $("gb-foot-name").textContent = me.first_name || "Member";
}
$("gb-toggle").onclick = toggleSidebar;
$("gb-backdrop").onclick = closeSidebar;

// ------------------------------------------- draggable sidebar (P48) --
// Owner: the sidebar must be movable — drag it wherever is
// convenient. The COLLAPSED pill can be dragged anywhere on
// screen; on release it snaps to the nearer edge (left/right)
// and keeps its height, and the open panel grows from that
// same side. The spot persists in localStorage (nx_gb_pos).
const gbBar = $("glassbar");
let gbDrag = null, gbSuppressClick = false;
function gbApplyPos(side, y) {
  gbBar.classList.toggle("gb-right", side === "right");
  gbBar.style.top = y + "px";
}
function gbRestorePos() {
  try {
    const p = JSON.parse(localStorage.getItem("nx_gb_pos") || "null");
    if (p && (p.side === "left" || p.side === "right") &&
        isFinite(p.y)) {
      gbApplyPos(p.side, Math.max(44, Math.min(
        window.innerHeight - 44, p.y)));
    }
  } catch (e) {}
}
gbRestorePos();
gbBar.addEventListener("pointerdown", e => {
  if (gbBar.classList.contains("open")) return;
  const r = gbBar.getBoundingClientRect();
  gbDrag = { id: e.pointerId, sx: e.clientX, sy: e.clientY,
             cx: r.left + r.width / 2, cy: r.top + r.height / 2,
             nx: null, ny: null, moved: false,
             onItem: !!e.target.closest(".gb-item, #gb-foot") };
});
window.addEventListener("pointermove", e => {
  if (!gbDrag || e.pointerId !== gbDrag.id) return;
  const dx = e.clientX - gbDrag.sx, dy = e.clientY - gbDrag.sy;
  if (!gbDrag.moved && Math.hypot(dx, dy) < 12) return;
  gbDrag.moved = true;
  gbBar.classList.add("gb-drag");
  gbDrag.nx = gbDrag.cx + dx;
  gbDrag.ny = gbDrag.cy + dy;
  gbBar.style.left = (gbDrag.nx - gbBar.offsetWidth / 2) + "px";
  gbBar.style.top = (gbDrag.ny - gbBar.offsetHeight / 2) + "px";
  gbBar.style.transform = "none";
});
function gbEndDrag(e) {
  if (!gbDrag || e.pointerId !== gbDrag.id) return;
  const d = gbDrag;
  gbDrag = null;
  gbBar.classList.remove("gb-drag");
  if (!d.moved) {
    // Phase 62 (owner: the sidebar often ignores the first tap):
    // a tap anywhere on the collapsed pill now opens it — before,
    // only the small chevron button did, and a slightly wobbly tap
    // counted as a drag and ate the click. Taps that land on rail
    // items keep their own click actions (navigation).
    if (e.type === "pointerup" && !d.onItem) {
      gbSuppressClick = true;
      toggleSidebar();
    }
    return;
  }
  gbSuppressClick = true;
  const side = d.nx < window.innerWidth / 2 ? "left" : "right";
  const y = Math.max(44, Math.min(window.innerHeight - 44, d.ny));
  gbBar.style.left = "";
  gbBar.style.transform = "";
  gbApplyPos(side, y);
  try {
    localStorage.setItem("nx_gb_pos",
                         JSON.stringify({ side, y }));
  } catch (err) {}
}
window.addEventListener("pointerup", gbEndDrag);
window.addEventListener("pointercancel", gbEndDrag);
gbBar.addEventListener("click", e => {
  if (gbSuppressClick) {
    gbSuppressClick = false;
    e.stopPropagation();
    e.preventDefault();
  }
}, true);
document.querySelectorAll(".gb-item[data-go]").forEach(b => {
  b.onclick = () => {
    const go = b.dataset.go;
    closeSidebar();
    showView(go);
    if (go === "profile") loadMe();
  };
});
$("gb-foot").onclick = () => {
  closeSidebar();
  showView("profile");
  loadMe();
};
$("gb-official").onclick = () => {
  closeSidebar();
  startActAs(1, "Nexora Social (Official)");
};
$("gb-logout").onclick = () => {
  closeSidebar();
  localStorage.removeItem("nx_remember");
  sessionStorage.removeItem("nx_entered");
  // Phase 23: logging out FULLY returns to the owner's own ID — any
  // act-as session ends here, so the next login is purely his own
  // account (with the Admin Panel), never a leftover identity.
  sessionStorage.removeItem("nx_actas");
  sessionStorage.removeItem("nx_actas_name");
  entryMode = "login";
  paintEntry();
  $("entry-screen").hidden = false;
};
moveNavPill();

// ---------------------------------------------------------------- admin --
// Owner-only panel (Phase 18). The sidebar item stays hidden unless /auth
// says this account is in ADMIN_IDS; every /admin/* endpoint re-checks
// that server-side, so the panel is a convenience, not the security.
function applyAdminVisibility() {
  const it = $("gb-admin");
  if (it) it.hidden = !(me && me.is_admin);
  const off = $("gb-official");
  if (off) off.hidden = !(me && me.is_admin);
  paintComposerAs();
}

function statCard(label, val) {
  const d = document.createElement("div");
  d.className = "stat-card";
  const n = document.createElement("div");
  n.className = "stat-num"; n.textContent = val;
  const l = document.createElement("div");
  l.className = "stat-label"; l.textContent = label;
  d.append(n, l);
  return d;
}

// ------------------------------------------------------- Phase 20: bell --
// In-app notifications: badge in the hero, list in view-notifications.
function paintBell(count) {
  const b = $("bell-badge");
  if (b) {
    b.hidden = !count;
    b.textContent = count > 99 ? "99+" : String(count || "");
  }
  const g = $("gb-bell-badge");
  if (g) {
    g.hidden = !count;
    g.textContent = count > 99 ? "99+" : String(count || "");
  }
  gbBellCount = count || 0;
  paintGbDot();
}
async function refreshBell() {
  try {
    const r = await api("/me/notifications?limit=1");
    paintBell(r.unread_count);
  } catch (e) { /* badge just stays as-is */ }
}

let notifCursor = null;
const NOTIF_ICONS = { like: "❤️", comment: "💬", follow: "👥",
                      share: "📤", post_live: "🎬", announcement: "📣",
                      verification: "🛡️" };
async function loadNotifications(reset) {
  const box = $("notif-list");
  if (reset) { box.innerHTML = ""; notifCursor = null; }
  try {
    const r = await api("/me/notifications?limit=30" +
      (notifCursor ? "&cursor=" + notifCursor : ""));
    notifCursor = r.next_cursor;
    $("notif-more").hidden = !notifCursor;
    $("notif-empty").hidden = box.children.length > 0 ||
      r.notifications.length > 0;
    r.notifications.forEach(n => {
      const row = document.createElement("div");
      row.className = "card notif-row" + (n.is_read ? "" : " unread");
      if (n.actor_id) {
        row.appendChild(avatarEl(n.actor_name || "?", n.actor_id,
                                 false, n.actor_photo));
      } else {
        const ic = document.createElement("div");
        ic.className = "avatar notif-ic";
        ic.textContent = NOTIF_ICONS[n.type] || "🔔";
        row.appendChild(ic);
      }
      const info = document.createElement("div");
      info.className = "admin-info";
      const t = document.createElement("div");
      t.className = "notif-text";
      if (n.actor_name) {
        const nm = document.createElement("b");
        nm.textContent = n.actor_name + (n.actor_verified ? " ✓" : "");
        t.append(nm, document.createTextNode(" " + n.text));
      } else {
        t.textContent = (NOTIF_ICONS[n.type] || "🔔") + " " + n.text;
      }
      const s = document.createElement("div");
      s.className = "admin-sub";
      s.textContent = relTime(n.created_at);
      info.append(t, s);
      row.appendChild(info);
      if (!n.is_read) {
        const dot = document.createElement("span");
        dot.className = "notif-dot";
        row.appendChild(dot);
      }
      if (n.actor_id) {
        row.style.cursor = "pointer";
        row.onclick = () => openProfile(n.actor_id);
      }
      box.appendChild(row);
    });
    // Opening the list marks everything read.
    await api("/me/notifications/read", { method: "POST" });
    paintBell(0);
  } catch (e) { box.textContent = "Could not load notifications."; }
}
$("notif-more").onclick = () => loadNotifications(false);
$("hero-bell").onclick = () => showView("notifications");

// ------------------------------------------------- Phase 20: act-as mode --
function paintActAs() {
  const on = !!actAsId();
  $("actas-banner").hidden = !on;
  if (on) {
    $("actas-text").textContent = "🎭 Acting as " +
      (sessionStorage.getItem("nx_actas_name") || "a managed user") +
      " — posts, likes, comments and follows are theirs.";
  }
  paintComposerAs();
}
$("actas-stop").onclick = () => stopActAs();
paintActAs();

// ---------------------------------------------------- Phase 25: designs --
// Pinterest-style gallery. Posting is official-only (the server
// enforces it); admins on their own ID get a one-tap switch card,
// the official identity gets the upload card.
let designCursor = null;
let designFile = null;
let designUploadId = null;
let currentDesign = null;

function paintDesignAccess() {
  // Phase 34 (owner directive): the upload card belongs to the
  // admin's OWN account only — never while acting as anyone
  // (not even Official). Members simply never see it; they can
  // browse, open, like and copy prompts like any other post.
  const canPost = !!(me && me.is_admin) && !actAsId();
  $("design-upload").hidden = !canPost;
}

function paintDesignLike(d) {
  document.querySelectorAll('[data-did="' + d.id + '"]')
    .forEach(b => {
      b.textContent = (d.liked ? "❤️ " : "🤍 ") + d.like_count;
      b.classList.toggle("liked", !!d.liked);
    });
  if (currentDesign && currentDesign.id === d.id) {
    $("ds-like").textContent =
      (d.liked ? "❤️ " : "🤍 ") + d.like_count;
  }
}

async function toggleDesignLike(d) {
  try {
    const r = await api("/designs/" + d.id + "/like",
                        { method: "POST" });
    d.liked = r.liked; d.like_count = r.like_count;
    paintDesignLike(d);
  } catch (e) { setStatus("Could not update the like."); }
}

// ------------------------------------------------- phase 66: the design
// long-press popup. HOLD a design (owner, Pinterest-style) and four
// round icon buttons float on its right side — every one working:
// 🔍 similar designs, 💬 WhatsApp share, 📤 in-app share, 📌 save.
let lpTimer = null, lpFired = false, lpSX = 0, lpSY = 0;
let popDesign = null, popAnchor = null;
let designSimilar = null;

function attachLongPress(el, fire) {
  el.addEventListener("pointerdown", e => {
    lpFired = false; lpSX = e.clientX; lpSY = e.clientY;
    clearTimeout(lpTimer);
    lpTimer = setTimeout(() => {
      lpFired = true; fire();
      setTimeout(() => { lpFired = false; }, 400);
    }, 450);
  });
  const cancel = e => {
    if (e && e.type === "pointermove" &&
        Math.hypot(e.clientX - lpSX, e.clientY - lpSY) < 10) return;
    clearTimeout(lpTimer);
  };
  el.addEventListener("pointermove", cancel);
  el.addEventListener("pointerup", cancel);
  el.addEventListener("pointercancel", cancel);
  el.addEventListener("contextmenu", e => e.preventDefault());
}

function showDesignPop(d, anchorEl) {
  popDesign = d; popAnchor = anchorEl;
  const pop = $("design-pop");
  const r = anchorEl.getBoundingClientRect();
  pop.hidden = false;
  $("design-pop-backdrop").hidden = false;
  updateBackButton();
  const railH = 222;
  let top = r.top + (r.height - railH) / 2;
  top = Math.max(10, Math.min(top, window.innerHeight - railH - 10));
  let left = r.right - 58;
  left = Math.max(8, Math.min(left, window.innerWidth - 56));
  pop.style.top = top + "px";
  pop.style.left = left + "px";
  $("dp-save").classList.toggle("on", !!d.saved);
  if (anchorEl.classList) anchorEl.classList.add("lp-on");
  if (navigator.vibrate) { try { navigator.vibrate(15); } catch (e) {} }
}

function hideDesignPop() {
  $("design-pop").hidden = true;
  $("design-pop-backdrop").hidden = true;
  updateBackButton();
  if (popAnchor && popAnchor.classList)
    popAnchor.classList.remove("lp-on");
  popAnchor = null; popDesign = null;
}

async function designPopSave() {
  const d = popDesign; if (!d) return;
  try {
    const r = await api("/designs/" + d.id + "/save",
                        { method: "POST" });
    d.saved = r.saved;
    $("dp-save").classList.toggle("on", r.saved);
    setStatus(r.saved ? "Design saved 📌 — find it in Saved."
                      : "Removed from Saved.");
  } catch (e) { setStatus("Could not save the design."); }
}

function designPopWhatsApp() {
  const d = popDesign; if (!d) return;
  const text = "🎨 " + (d.prompt || "Design").slice(0, 140) +
    "\n— via Nexora Social https://t.me/NexoraSocial_bot";
  const url = "https://wa.me/?text=" + encodeURIComponent(text);
  hideDesignPop();
  if (window.Telegram && tg && tg.openLink) tg.openLink(url);
  else window.open(url, "_blank");
}

function designPopShare() {
  const d = popDesign; if (!d) return;
  hideDesignPop();
  if (!$("design-sheet-wrap").hidden) closeDesignSheet();
  openDesignSharePicker(d);
}

function designPopSimilar() {
  const d = popDesign; if (!d) return;
  hideDesignPop();
  if (!$("design-sheet-wrap").hidden) closeDesignSheet();
  setSimilarMode(d);
  $("app-scroll").scrollTop = 0;
  loadDesigns(true);
}

function setSimilarMode(d) {
  designSimilar = d;
  $("design-similar-bar").hidden = !d;
  if (d) $("design-similar-text").textContent =
    (d.prompt || "this design").slice(0, 42);
}

async function openDesignSharePicker(d) {
  const sheet = $("reel-sheet");
  sheet.innerHTML = "";
  const title = document.createElement("div");
  title.className = "sheet-title";
  title.textContent = "Send design to…";
  const searchRow = document.createElement("div");
  searchRow.className = "sheet-search";
  const input = document.createElement("input");
  input.type = "text";
  input.placeholder = "Search people…";
  searchRow.appendChild(input);
  const list = document.createElement("div");
  sheet.append(title, searchRow, list);

  const render = users => {
    list.innerHTML = "";
    const visible = users.filter(u => !me || u.telegram_id !== me.telegram_id);
    if (!visible.length) {
      const e = document.createElement("p");
      e.className = "hint";
      e.textContent = "No people here yet. Follow someone, or search by name.";
      list.appendChild(e);
    }
    visible.forEach(u => {
      const r = document.createElement("div");
      r.className = "pick-row";
      const nm = document.createElement("span");
      nm.className = "pick-name";
      nm.textContent = u.first_name;
      if (u.is_verified) nm.appendChild(verifiedBadge());
      if (u.username) {
        const sm = document.createElement("small");
        sm.textContent = "@" + u.username;
        nm.appendChild(sm);
      }
      const send = document.createElement("button");
      send.className = "pick-send";
      send.textContent = "Send";
      send.onclick = async () => {
        send.disabled = true;
        try {
          await api("/designs/" + d.id + "/share", { method: "POST",
            body: JSON.stringify({ to_user_id: u.telegram_id }) });
          send.textContent = "Sent ✓";
          send.classList.add("sent");
          setStatus("Design shared with " + u.first_name + ".");
        } catch (e) {
          send.disabled = false;
          setStatus("Could not share the design.");
        }
      };
      r.append(avatarEl(u.first_name, u.telegram_id, false, u.photo_file_id), nm, send);
      list.appendChild(r);
    });
    const cancel = document.createElement("button");
    cancel.className = "sheet-row";
    const ic2 = document.createElement("span");
    ic2.className = "ic";
    ic2.textContent = "✕";
    cancel.append(ic2, document.createTextNode("Cancel"));
    cancel.onclick = () => closeReelMenu();
    list.appendChild(cancel);
  };

  try {
    const data = await api("/me/following");
    render(data.users);
  } catch (e) { render([]); }
  let timer = null;
  input.oninput = () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const q = input.value.trim();
      try {
        const dd = q ? await api("/search?q=" + encodeURIComponent(q))
                     : await api("/me/following");
        render(dd.users);
      } catch (e) { /* keep the current list */ }
    }, 250);
  };
  $("reel-sheet-wrap").hidden = false;
  updateBackButton();
}

$("dp-save").onclick = designPopSave;
$("dp-wa").onclick = designPopWhatsApp;
$("dp-share").onclick = designPopShare;
$("dp-similar").onclick = designPopSimilar;
$("design-pop-backdrop").onclick = hideDesignPop;
$("design-similar-clear").onclick = () => {
  setSimilarMode(null); loadDesigns(true);
};
$("app-scroll").addEventListener("scroll",
  () => clearTimeout(lpTimer), { passive: true });
// Phase 67: the sheet's hold target is the media WRAPPER (the
// shield over the image takes the touch, never the <img> itself).
attachLongPress($("ds-media"), () => {
  if (currentDesign) showDesignPop(currentDesign, $("ds-media"));
});

function designCard(d) {
  const el = document.createElement("div");
  el.className = "design-card";
  const img = document.createElement("img");
  img.src = mediaUrl(d.image_file_id);
  img.loading = "lazy";
  img.alt = "Design";
  img.draggable = false;
  // Phase 67: a transparent shield over the image takes the touch,
  // so Telegram's WebView never treats a hold as an IMAGE hold and
  // pops its own Open in…/Download/Copy Link menu (owner report).
  const media = document.createElement("div");
  media.className = "design-media";
  const shield = document.createElement("div");
  shield.className = "img-shield";
  media.append(img, shield);
  const body = document.createElement("div");
  body.className = "design-card-body";
  const p = document.createElement("p");
  p.className = "design-prompt";
  p.textContent = d.prompt || "";
  const like = document.createElement("button");
  like.className = "design-like" + (d.liked ? " liked" : "");
  like.dataset.did = d.id;
  like.textContent = (d.liked ? "❤️ " : "🤍 ") + d.like_count;
  like.onclick = e => { e.stopPropagation(); if (lpFired) return;
    toggleDesignLike(d); };
  // Phase 99 (owner): a tap that starts on the react button belongs
  // to the button alone — it must never arm the card's long-press
  // (a slow careful tap used to pop the whole-post menu instead of
  // liking) and never fall through to the card.
  like.addEventListener("pointerdown", e => e.stopPropagation());
  like.addEventListener("pointerup", e => e.stopPropagation());
  // Phase 31: like + unique views share one compact stats row,
  // Pinterest-style, under the prompt snippet.
  const stats = document.createElement("div");
  stats.className = "design-stats";
  const views = document.createElement("span");
  views.className = "design-views";
  views.dataset.dviews = d.id;
  views.textContent = "👁 " + (d.views || 0);
  stats.append(like, views);
  body.append(p, stats);
  el.append(media, body);
  // Phase 66 (owner): HOLD a design and the icon popup appears
  // (Pinterest-style). A fired long-press swallows the tap that
  // would otherwise open the sheet.
  attachLongPress(el, () => showDesignPop(d, el));
  el.onclick = e => { if (lpFired) return;
    if (e.target && e.target.closest &&
        e.target.closest(".design-like")) return;
    openDesignSheet(d); };
  return el;
}


// ---------- Phase 86: Museum (owner: a Museum section in the
// sidebar, with many rooms full of pictures; you drag or scroll
// along the wall to walk from room to room, and every room has
// its own design). The exhibits are the Design gallery's
// pictures, five to a room; tapping one opens its design sheet.
const MUSEUM_THEMES = [
  { name: "Rose Hall", wall: "linear-gradient(180deg,#F7C8DA,#EFA8C4)",
    floor: "#B76E8E", frame: "#C9A227", mat: "#FFF7EA",
    glow: "rgba(255,214,130,.55)" },
  { name: "Midnight Gallery", wall: "linear-gradient(180deg,#2E2140,#1D1530)",
    floor: "#120C20", frame: "#C0C6D4", mat: "#EDEFF5",
    glow: "rgba(170,190,255,.5)" },
  { name: "Emerald Room", wall: "linear-gradient(180deg,#BFE3CF,#8FC7A6)",
    floor: "#4E7A5F", frame: "#7A5230", mat: "#FFFDF4",
    glow: "rgba(255,240,190,.5)" },
  { name: "Sky Gallery", wall: "linear-gradient(180deg,#D6ECFF,#A9D2F5)",
    floor: "#6E97B8", frame: "#FFFFFF", mat: "#FFFFFF",
    glow: "rgba(255,255,255,.65)" },
  { name: "Sunset Salon", wall: "linear-gradient(180deg,#FFD9A8,#F2A56B)",
    floor: "#9A5B33", frame: "#5C3A21", mat: "#FFF6E8",
    glow: "rgba(255,196,100,.55)" },
  { name: "Marble Hall", wall: "linear-gradient(180deg,#F4F4F6,#DCDCE2)",
    floor: "#9A9AA4", frame: "#23232A", mat: "#FFFFFF",
    glow: "rgba(255,255,255,.7)" },
  { name: "Living Lounge", wall: "linear-gradient(180deg,#F6E3CE,#EBC49C)",
    floor: "#A9714B", frame: "#B08D57", mat: "#FFFBF2",
    glow: "rgba(255,220,160,.55)" },
  { name: "The Library", wall: "linear-gradient(180deg,#5C6650,#3E4A38)",
    floor: "#3A2A1C", frame: "#C9A227", mat: "#F7EFDA",
    glow: "rgba(255,226,150,.5)" },
  { name: "Studio Loft", wall: "linear-gradient(180deg,#D9A184,#B97A5C)",
    floor: "#6E6E72", frame: "#23232A", mat: "#F5EFE8",
    glow: "rgba(255,235,210,.5)" },
  { name: "Garden Room", wall: "linear-gradient(180deg,#E4F4DC,#BEE3B0)",
    floor: "#B0704F", frame: "#FFFFFF", mat: "#FFFFFF",
    glow: "rgba(255,255,230,.6)" },
  { name: "Attic Gallery", wall: "linear-gradient(180deg,#D9CFE8,#B4A6D4)",
    floor: "#7A6248", frame: "#8A6D4A", mat: "#FBF7EE",
    glow: "rgba(240,230,255,.55)" },
  { name: "Terrace Hall", wall: "linear-gradient(180deg,#CDEFF7,#9FD8E8)",
    floor: "#C2A878", frame: "#FFFFFF", mat: "#FFFFFF",
    glow: "rgba(255,255,255,.65)" },
];
let museumRooms = null, museumIdx = 0, museumX = 0, museumMoved = 0,
    museumZ = 1;

function openMuseum() { loadMuseum(false); }

async function loadMuseum(force) {
  if (museumRooms && !force) { openMuseumRoom(museumIdx); return; }
  let designs = [];
  try {
    let r = await api("/designs?limit=40");
    designs = r.designs || [];
    if (r.next_cursor) {
      r = await api("/designs?limit=40&cursor=" + r.next_cursor);
      designs = designs.concat(r.designs || []);
    }
  } catch (e) { designs = []; }
  museumRooms = [];
  for (let i = 0; i < designs.length; i += 5)
    museumRooms.push(designs.slice(i, i + 5));
  $("museum-empty").hidden = museumRooms.length > 0;
  $("museum-stage").hidden = museumRooms.length === 0;
  openMuseumRoom(0);
}

function paintMuseumPlan() {
  const wrap = $("museum-rooms");
  wrap.innerHTML = "";
  (museumRooms || []).forEach((room, i) => {
    const b = document.createElement("button");
    b.className = "plan-room" + (i === museumIdx ? " on" : "");
    b.innerHTML = "";
    const nm = document.createElement("span");
    nm.className = "plan-name";
    nm.textContent = MUSEUM_THEMES[i % MUSEUM_THEMES.length].name;
    const ct = document.createElement("span");
    ct.className = "plan-count";
    ct.textContent = room.length + " pictures";
    b.appendChild(nm);
    b.appendChild(ct);
    b.onclick = () => openMuseumRoom(i);
    wrap.appendChild(b);
  });
}

function museumApply() {
  const stage = $("museum-stage"), room = $("museum-room");
  const min = Math.min(0, stage.clientWidth -
                           room.scrollWidth * museumZ);
  museumX = Math.max(min, Math.min(0, museumX));
  room.style.transform = "translateX(" + museumX + "px) scale(" +
    museumZ + ")";
  $("museum-zlabel").textContent = Math.round(museumZ * 100) + "%";
}

function museumSetX(x) { museumX = x; museumApply(); }

// Phase 87 (owner): zoom in / out — buttons, pinch, double-tap
// and Ctrl+scroll all land here. Zooms around a stage x (the
// stage centre by default) so the wall point under it stays.
function museumZoom(nz, cx) {
  const stage = $("museum-stage");
  if (cx === undefined) cx = stage.clientWidth / 2;
  nz = Math.max(1, Math.min(2.5, nz));
  const point = (cx - museumX) / museumZ;
  museumZ = nz;
  museumX = cx - point * museumZ;
  museumApply();
}

function openMuseumRoom(i) {
  if (!museumRooms || !museumRooms.length) return;
  museumIdx = Math.max(0, Math.min(museumRooms.length - 1, i));
  const theme = MUSEUM_THEMES[museumIdx % MUSEUM_THEMES.length];
  const designs = museumRooms[museumIdx];
  $("museum-name").textContent = "🏛️ " + theme.name +
    "  ·  Room " + (museumIdx + 1) + " of " + museumRooms.length;
  paintMuseumPlan();
  const room = $("museum-room");
  room.style.setProperty("--m-wall", theme.wall);
  room.style.setProperty("--m-floor", theme.floor);
  room.style.setProperty("--m-frame", theme.frame);
  room.style.setProperty("--m-mat", theme.mat);
  room.style.setProperty("--m-glow", theme.glow);
  room.innerHTML = "";
  const wall = document.createElement("div");
  wall.className = "m-wall";
  room.appendChild(wall);
  const floor = document.createElement("div");
  floor.className = "m-floor";
  room.appendChild(floor);
  const stage = $("museum-stage");
  const slotW = 300, n = designs.length;
  const width = Math.max(stage.clientWidth, 210 + n * slotW + 190);
  room.style.width = width + "px";
  designs.forEach((d, k) => {
    const cx = 150 + k * slotW;
    const spot = document.createElement("div");
    spot.className = "m-spot";
    spot.style.left = cx + "px";
    room.appendChild(spot);
    const f = document.createElement("button");
    f.className = "mframe";
    f.style.left = cx + "px";
    const img = document.createElement("img");
    img.alt = "";
    img.src = mediaUrl(d.image_file_id);
    f.appendChild(img);
    f.onclick = () => { if (museumMoved < 8) openDesignSheet(d); };
    room.appendChild(f);
    const plate = document.createElement("div");
    plate.className = "mplate";
    plate.style.left = cx + "px";
    plate.textContent = (d.prompt || "Untitled").slice(0, 44);
    room.appendChild(plate);
  });
  const bench = document.createElement("div");
  bench.className = "m-bench";
  bench.style.left = Math.round(width * 0.45) + "px";
  room.appendChild(bench);
  const mkDoor = (label, sub, target, leftPx) => {
    const door = document.createElement("button");
    door.className = "m-door";
    door.style.left = leftPx + "px";
    door.innerHTML = "";
    door.appendChild(document.createTextNode(label));
    const sm = document.createElement("span");
    sm.textContent = sub;
    door.appendChild(sm);
    door.onclick = () => { if (museumMoved < 8) openMuseumRoom(target); };
    room.appendChild(door);
  };
  if (museumIdx > 0)
    mkDoor("← Room " + museumIdx,
           MUSEUM_THEMES[(museumIdx - 1) % MUSEUM_THEMES.length].name,
           museumIdx - 1, 18);
  if (museumIdx < museumRooms.length - 1)
    mkDoor("Room " + (museumIdx + 2) + " →",
           MUSEUM_THEMES[(museumIdx + 1) % MUSEUM_THEMES.length].name,
           museumIdx + 1, width - 122);
  room.classList.remove("mfade");
  void room.offsetWidth;
  room.classList.add("mfade");
  museumZ = 1;
  museumSetX(0);
}

// Walking: drag with mouse or finger, or scroll — the room
// pans. Phase 87: pinch with two fingers zooms, a double-tap
// toggles the zoom, Ctrl+scroll zooms, and the + / − buttons
// on the stage zoom too.
(() => {
  const stage = $("museum-stage");
  let drag = null;
  const pointers = new Map();
  let pinch = null;
  stage.addEventListener("pointerdown", e => {
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pointers.size === 2) {
      const [p1, p2] = [...pointers.values()];
      pinch = { d: Math.hypot(p1.x - p2.x, p1.y - p2.y), z: museumZ };
      drag = null;
    } else {
      drag = { x: e.clientX, start: museumX };
    }
    museumMoved = 0;
  });
  window.addEventListener("pointermove", e => {
    if (pointers.has(e.pointerId))
      pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pinch && pointers.size === 2) {
      const [p1, p2] = [...pointers.values()];
      const d = Math.hypot(p1.x - p2.x, p1.y - p2.y);
      museumMoved = 99;
      if (pinch.d > 0) museumZoom(pinch.z * d / pinch.d);
      return;
    }
    if (!drag) return;
    const dx = e.clientX - drag.x;
    museumMoved = Math.max(museumMoved, Math.abs(dx));
    museumSetX(drag.start + dx);
  });
  const drop = e => {
    pointers.delete(e.pointerId);
    if (pointers.size < 2) pinch = null;
    if (pointers.size === 0) drag = null;
  };
  ["pointerup", "pointercancel"].forEach(ev =>
    window.addEventListener(ev, drop));
  stage.addEventListener("wheel", e => {
    e.preventDefault();
    if (e.ctrlKey) {  // trackpad pinch arrives as Ctrl+scroll
      museumZoom(museumZ * (e.deltaY < 0 ? 1.08 : 0.92));
      return;
    }
    const d = Math.abs(e.deltaY) >= Math.abs(e.deltaX)
      ? e.deltaY : e.deltaX;
    museumSetX(museumX - d);
  }, { passive: false });
  stage.addEventListener("dblclick", e => {
    const r = stage.getBoundingClientRect();
    museumZoom(museumZ > 1.05 ? 1 : 1.8, e.clientX - r.left);
  });
  $("museum-zin").onclick = () => museumZoom(museumZ + 0.25);
  $("museum-zout").onclick = () => museumZoom(museumZ - 0.25);
  $("museum-zlabel").onclick = () => museumZoom(1);
  // Keep the app-level pull-to-refresh out of museum drags.
  stage.addEventListener("touchstart", e => e.stopPropagation(),
                         { passive: true });
  stage.addEventListener("touchmove", e => e.stopPropagation(),
                         { passive: true });
})();

async function loadDesigns(reset) {
  paintDesignAccess();
  const grid = $("design-grid");
  if (reset) { designCursor = null; grid.innerHTML = ""; }
  try {
    const url = "/designs?limit=20" +
      (designSimilar ? "&similar_to=" + designSimilar.id : "") +
      (designCursor ? "&cursor=" + designCursor : "");
    const r = await api(url);
    r.designs.forEach(d => grid.appendChild(designCard(d)));
    designCursor = r.next_cursor;
    $("design-more").hidden = !designCursor;
    $("design-empty").hidden = grid.children.length > 0;
  } catch (e) {
    if (reset) $("design-empty").hidden = false;
  }
}
$("design-more").onclick = () => loadDesigns(false);

// Phase 61 (owner): pull-to-refresh on the Design gallery — pull
// down from the very top and the gallery reloads fresh; the server
// orders the fresh page by the member's interests (Phase 61 API).
(() => {
  const sc = $("app-scroll");
  const ind = $("design-ptr");
  if (!sc || !ind) return;
  let startY = null, pull = 0, busy = false;
  const THRESH = 70;
  sc.addEventListener("touchstart", e => {
    if (busy || $("view-designs").hidden || sc.scrollTop > 0) return;
    startY = e.touches[0].clientY;
    pull = 0;
  }, { passive: true });
  sc.addEventListener("touchmove", e => {
    if (startY === null || busy) return;
    const dy = e.touches[0].clientY - startY;
    if (dy <= 0 || sc.scrollTop > 0) {
      startY = null;
      ind.hidden = true;
      ind.style.height = "0px";
      return;
    }
    e.preventDefault();
    pull = dy;
    ind.hidden = false;
    ind.style.height = Math.min(dy * 0.6, 84) + "px";
    ind.textContent = dy >= THRESH ? "↑ Release to refresh"
                                   : "↓ Pull to refresh";
  }, { passive: false });
  const finish = async () => {
    if (startY === null) return;
    const go = pull >= THRESH && !busy;
    startY = null;
    pull = 0;
    if (!go) {
      ind.hidden = true;
      ind.style.height = "0px";
      return;
    }
    busy = true;
    ind.hidden = false;
    ind.style.height = "40px";
    ind.textContent = "⟳ Refreshing…";
    await loadDesigns(true);
    ind.hidden = true;
    ind.style.height = "0px";
    busy = false;
  };
  sc.addEventListener("touchend", finish);
  sc.addEventListener("touchcancel", finish);
})();

// Phase 72 (owner): pull-to-refresh on EVERY main page, just
// like Design's — pulling down from the top reloads whichever
// page is open with its own loader. Design keeps its own
// handler above; views without a loader (search, games, chat,
// assistant) are skipped.
(() => {
  const sc = $("app-scroll");
  const ind = $("ptr-global");
  if (!sc || !ind) return;
  const LOADERS = {
    feed: () => loadFeed(true),
    videos: () => loadVideos(true),
    tasks: () => loadTasks(),
    leaderboard: () => loadRanks(),
    saved: () => loadSaved(),
    shared: () => loadShared(),
    notifications: () => loadNotifications(true),
    messages: () => loadMessages(),
    profile: () => { if (me) openProfile(me.telegram_id); },
    admin: () => loadAdmin(),
    museum: () => loadMuseum(true),
  };
  let startY = null, pull = 0, busy = false;
  const THRESH = 70;
  const current = () => Object.keys(LOADERS)
    .find(v => !$("view-" + v).hidden);
  sc.addEventListener("touchstart", e => {
    if (busy || !current() || sc.scrollTop > 0) return;
    startY = e.touches[0].clientY;
    pull = 0;
  }, { passive: true });
  sc.addEventListener("touchmove", e => {
    if (startY === null || busy) return;
    const dy = e.touches[0].clientY - startY;
    if (dy <= 0 || sc.scrollTop > 0) {
      startY = null;
      ind.hidden = true;
      ind.style.height = "0px";
      return;
    }
    e.preventDefault();
    pull = dy;
    ind.hidden = false;
    ind.style.height = Math.min(dy * 0.6, 84) + "px";
    ind.textContent = dy >= THRESH ? "↑ Release to refresh"
                                   : "↓ Pull to refresh";
  }, { passive: false });
  const finish = async () => {
    if (startY === null) return;
    const go = pull >= THRESH && !busy;
    const view = current();
    startY = null;
    pull = 0;
    if (!go || !view) {
      ind.hidden = true;
      ind.style.height = "0px";
      return;
    }
    busy = true;
    ind.hidden = false;
    ind.style.height = "40px";
    ind.textContent = "⟳ Refreshing…";
    try { await LOADERS[view](); } catch (e) { /* keep the page */ }
    ind.hidden = true;
    ind.style.height = "0px";
    busy = false;
  };
  sc.addEventListener("touchend", finish);
  sc.addEventListener("touchcancel", finish);
})();

function openDesignSheet(d) {
  currentDesign = d;
  $("ds-img").src = mediaUrl(d.image_file_id);
  // Phase 31 (owner request): the caption opens PARTLY — a few
  // lines — and "See more" unfolds the rest, Pinterest-style.
  const promptEl = $("ds-prompt");
  promptEl.textContent = d.prompt || "(no prompt saved)";
  promptEl.classList.add("clamped");
  $("ds-more").textContent = "See more";
  $("ds-views").textContent = "👁 " + (d.views || 0) + " views";
  $("ds-like").textContent =
    (d.liked ? "❤️ " : "🤍 ") + d.like_count;
  $("ds-remove").hidden = !(me && (me.telegram_id === 1 || me.is_admin));
  // Phase 46: only the admin, on his own account (never while
  // acting as someone), may edit a design — the Phase 34 rule.
  $("ds-edit").hidden = !(me && me.is_admin && !actAsId());
  $("ds-edit-box").hidden = true;
  $("ds-edit-status").textContent = "";
  dsEditFile = null;
  $("ds-copy").textContent = "📋 Copy Prompt";
  $("ds-download").textContent = "⬇️ Download";
  $("design-sheet-wrap").hidden = false;
  $("app-scroll").classList.add("sheet-open");
  updateBackButton();
  // "See more" only earns its place when the prompt truly overflows.
  requestAnimationFrame(() => {
    $("ds-more").hidden =
      promptEl.scrollHeight <= promptEl.clientHeight + 2;
  });
  // Opening the sheet is the design's view (unique per member).
  markViewed("designs", d.id, views => {
    d.views = views;
    $("ds-views").textContent = "👁 " + views + " views";
    const card = document.querySelector(
      '[data-dviews="' + d.id + '"]');
    if (card) card.textContent = "👁 " + views;
  });
}
function closeDesignSheet() {
  $("design-sheet-wrap").hidden = true;
  $("app-scroll").classList.remove("sheet-open");
  updateBackButton();
  currentDesign = null;
}
$("design-sheet-backdrop").onclick = closeDesignSheet;
$("ds-close").onclick = closeDesignSheet;
$("ds-more").onclick = () => {
  const el = $("ds-prompt");
  const clamped = el.classList.toggle("clamped");
  $("ds-more").textContent = clamped ? "See more" : "See less";
};
$("ds-like").onclick = () => {
  if (currentDesign) toggleDesignLike(currentDesign);
};
async function copyText(t) {
  try { await navigator.clipboard.writeText(t); return true; }
  catch (e) {
    const ta = document.createElement("textarea");
    ta.value = t;
    document.body.appendChild(ta);
    ta.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch (e2) {}
    ta.remove();
    return ok;
  }
}
$("ds-copy").onclick = async () => {
  if (!currentDesign) return;
  const ok = await copyText(currentDesign.prompt || "");
  $("ds-copy").textContent = ok ? "✅ Copied!" : "📋 Copy Prompt";
  if (ok) setStatus("Prompt copied 📋 — paste it anywhere.");
};

// Phase 110 (owner: the anchor download silently does nothing
// in the Telegram WebView): use Telegram's native downloadFile
// (WebApp 8.0+) — the client shows its own download popup and
// reports back whether the download started — and show the
// outcome on the button. Fallbacks: openLink on old Telegram,
// the anchor on desktop browsers.
$("ds-download").onclick = async () => {
  if (!currentDesign) return;
  const btn = $("ds-download");
  if (btn.textContent !== "⬇️ Download") return;
  const url = location.origin + mediaUrl(currentDesign.image_file_id);
  const done = () => {
    btn.textContent = "✅ Downloaded!";
    setStatus("Image downloaded ✓ — check your gallery / Downloads.");
    setTimeout(() => { btn.textContent = "⬇️ Download"; }, 4000);
  };
  const anchorDownload = () => {
    const a = document.createElement("a");
    a.href = url;
    a.download = "";
    document.body.appendChild(a);
    a.click();
    a.remove();
    done();
  };
  const openInBrowser = () => {
    if (window.Telegram && tg && tg.openLink) {
      tg.openLink(url);
      btn.textContent = "⬇️ Download";
      setStatus("Opened in your browser — save the image from there.");
    } else anchorDownload();
  };
  btn.textContent = "⬇️ Downloading…";
  try {
    if (window.Telegram && tg && tg.downloadFile) {
      let ext = "jpg";
      try {
        const head = await fetch(url, { method: "HEAD" });
        const ct = (head.headers.get("content-type") || "").toLowerCase();
        if (ct.includes("png")) ext = "png";
        else if (ct.includes("webp")) ext = "webp";
        else if (ct.includes("gif")) ext = "gif";
      } catch (e) {}
      tg.downloadFile(
        { url, file_name: "nexora-design-" + currentDesign.id + "." + ext },
        (downloading) => {
          if (downloading) done();
          else {
            btn.textContent = "⬇️ Download";
            setStatus("Download cancelled.");
          }
        });
    } else openInBrowser();
  } catch (e) {
    openInBrowser();
  }
};
$("ds-remove").onclick = async () => {
  if (!currentDesign) return;
  if (!confirm("Remove this design from the gallery?")) return;
  const id = currentDesign.id;
  try {
    if (me.telegram_id === 1) {
      await api("/designs/" + id, { method: "DELETE" });
    } else {
      await api("/admin/designs/" + id, { method: "DELETE" });
    }
    closeDesignSheet();
    loadDesigns(true);
  } catch (e) { setStatus("Could not remove the design."); }
};

// Phase 46: edit a posted design — prompt text and/or a
// replacement image, from the detail sheet (admin only).
let dsEditFile = null;
$("ds-edit").onclick = () => {
  if (!currentDesign) return;
  const box = $("ds-edit-box");
  box.hidden = !box.hidden;
  if (!box.hidden) {
    $("ds-edit-prompt").value = currentDesign.prompt || "";
    if (paintDsEditCount) paintDsEditCount();
    $("ds-edit-status").textContent = "";
  }
};
$("ds-edit-img").onclick = () => $("ds-edit-file").click();
$("ds-edit-file").onchange = () => {
  dsEditFile = $("ds-edit-file").files[0] || null;
  $("ds-edit-file").value = "";
  $("ds-edit-status").textContent = dsEditFile
    ? "New image picked: " + dsEditFile.name : "";
};
$("ds-edit-save").onclick = async () => {
  if (!currentDesign) return;
  const st = $("ds-edit-status");
  const form = new FormData();
  form.append("prompt", $("ds-edit-prompt").value);
  if (dsEditFile) {
    st.textContent = "Uploading…";
    form.append("file", await shrinkForUpload(dsEditFile));
  }
  try {
    const updated = await apiForm(
      "/designs/" + currentDesign.id + "/edit", form);
    dsEditFile = null;
    setStatus("Design updated.");
    openDesignSheet(updated);
    loadDesigns(true);
  } catch (e) {
    st.textContent = e.message || "Could not save the changes.";
  }
};

$("design-pick").onclick = () => $("design-file").click();
$("design-file").onchange = () => {
  designFile = $("design-file").files[0] || null;
  designUploadId = designFile ? newUploadId() : null;
  const chip = $("design-attach");
  chip.hidden = !designFile;
  chip.textContent = designFile ? "🖼️ " + designFile.name : "";
  $("design-status").textContent = "";
};
// Phase 84 (owner): long prompts were silently cut at 2,000
// characters — the limit is now 10,000, and a live counter
// under each prompt box shows where you stand.
function wireCharCount(inputId, countId) {
  const ta = $(inputId), el = $(countId);
  if (!ta || !el) return;
  const paint = () => { el.textContent =
    ta.value.length + " / " + ta.maxLength; };
  ta.addEventListener("input", paint);
  paint();
  return paint;
}
const paintDesignCount = wireCharCount("design-prompt",
                                       "design-prompt-count");
const paintDsEditCount = wireCharCount("ds-edit-prompt",
                                       "ds-edit-count");

$("design-post").onclick = async () => {
  if (!designFile) {
    $("design-status").textContent = "Pick a design image first 🖼️";
    return;
  }
  const btn = $("design-post");
  btn.disabled = true;
  const fd = new FormData();
  fd.append("file", await shrinkForUpload(designFile));
  fd.append("prompt", $("design-prompt").value.trim());
  try {
    await apiFormProgress("/designs/upload", fd,
      pct => { $("design-status").textContent = pct === null
        ? "Sending… keep the app open"
        : "Uploading… " + pct + "%"; }, designUploadId);
    designFile = null;
    designUploadId = null;
    $("design-file").value = "";
    $("design-attach").hidden = true;
    $("design-prompt").value = "";
    if (paintDesignCount) paintDesignCount();
    $("design-status").textContent = "Design posted ✨";
    btn.classList.add("is-success");
    setTimeout(() => btn.classList.remove("is-success"), 1500);
    loadDesigns(true);
  } catch (e) {
    $("design-status").textContent =
      "Upload failed — designs are images only, up to 20 MB.";
  }
  btn.disabled = false;
};

// ------------------------------------------------------- Phase 19: dashboard
function fmtDur(sec) {
  sec = Math.max(0, Math.round(sec || 0));
  if (sec < 60) return sec + "s";
  if (sec < 3600) return Math.floor(sec / 60) + "m";
  return Math.floor(sec / 3600) + "h " + Math.floor((sec % 3600) / 60) + "m";
}
function relTime(iso) {
  if (!iso) return "never";
  const then = new Date(iso + (iso.endsWith("Z") ? "" : "Z")).getTime();
  const diff = Math.max(0, Date.now() - then);
  if (diff < 60000) return "just now";
  if (diff < 3600000) return Math.floor(diff / 60000) + "m ago";
  if (diff < 86400000) return Math.floor(diff / 3600000) + "h ago";
  return Math.floor(diff / 86400000) + "d ago";
}
function barRows(box, rows, fmt) {
  box.innerHTML = "";
  if (!rows.length) {
    box.innerHTML = '<p class="hint">No data yet.</p>';
    return;
  }
  const max = Math.max(...rows.map(r => r.count), 1);
  rows.forEach(r => {
    const row = document.createElement("div");
    row.className = "bar-row";
    const lab = document.createElement("span");
    lab.className = "bar-label"; lab.textContent = r.label;
    const track = document.createElement("div");
    track.className = "bar-track";
    const fill = document.createElement("div");
    fill.className = "bar-fill";
    fill.style.width = Math.max(3, r.count / max * 100) + "%";
    track.appendChild(fill);
    const val = document.createElement("span");
    val.className = "bar-val";
    val.textContent = fmt ? fmt(r.count) : r.count;
    row.append(lab, track, val);
    box.appendChild(row);
  });
}

async function loadDashboard() {
  const tiles = $("dash-tiles");
  try {
    const d = await api("/admin/dashboard");
    tiles.innerHTML = "";
    [["👥 Total members", d.total_members], ["🆕 New today", d.new_today],
     ["🟢 Active now", d.active_now], ["⏰ Active (1h)", d.active_last_hour],
     ["📅 Active today", d.active_today], ["📝 Posts", d.posts],
     ["🤖 Managed", d.managed_members || 0],
     ["📺 Ads today", d.ads_today], ["📺 Ads total", d.ads_total],
     ["⏱️ Time today", fmtDur(d.time_today_seconds)],
     ["⏱️ Avg / member", fmtDur(d.avg_time_today_seconds)]
    ].forEach(([l, v]) => tiles.appendChild(statCard(l, v)));
    // Phase 43: the hero banner mirrors the headline numbers.
    const ahM = $("ah-members"); if (ahM) ahM.textContent = d.total_members;
    const ahA = $("ah-active"); if (ahA) ahA.textContent = d.active_now;
    const ahP = $("ah-posts"); if (ahP) ahP.textContent = d.posts;
    const dayLabel = iso => {
      const dt = new Date(iso + "T00:00:00");
      return dt.toLocaleDateString(undefined, { day: "numeric", month: "short" });
    };
    barRows($("dash-signups"),
      d.signups_14d.map(r => ({ label: dayLabel(r.day), count: r.count })));
    barRows($("dash-active"),
      d.active_14d.map(r => ({ label: dayLabel(r.day), count: r.count })));
    barRows($("dash-countries"),
      d.countries.map(r => ({ label: r.name, count: r.count })));
    barRows($("dash-languages"),
      d.languages.map(r => ({ label: r.name, count: r.count })));
    const tt = $("dash-top-time");
    tt.innerHTML = "";
    if (!d.top_time_today.length) {
      tt.innerHTML = '<p class="hint">Nobody has spent time yet today.</p>';
    }
    d.top_time_today.forEach(u => {
      const row = document.createElement("div");
      row.className = "bar-row";
      const lab = document.createElement("span");
      lab.className = "bar-label";
      lab.textContent = u.first_name + (u.username ? " @" + u.username : "");
      const val = document.createElement("span");
      val.className = "bar-val";
      val.textContent = fmtDur(u.seconds) + " · " + u.sessions + " visits";
      row.append(lab, val);
      tt.appendChild(row);
    });
  } catch (e) { tiles.textContent = "Could not load the dashboard."; }
}

// ------------------------------------------------- Phase 44: earnings --
// The Earning Panel (owner's spec, structured after his reference
// video — dark glass KPI cards, a column chart, ranked lists).
// Impressions and points are real platform data; money figures
// are impressions × the owner-set rate — an estimate, since the
// actual ad revenue lives in the AdsGram partner panel.
const fmtTk = n => "৳" + Number(n || 0).toLocaleString(undefined,
  { minimumFractionDigits: 2, maximumFractionDigits: 2 });

function earnRows(boxId, rows, valText) {
  const box = $(boxId);
  box.innerHTML = "";
  if (!rows.length) {
    box.innerHTML = '<p class="earn-empty">No data yet.</p>';
    return;
  }
  rows.forEach((u, i) => {
    const row = document.createElement("div");
    row.className = "earn-row";
    const rank = document.createElement("span");
    rank.className = "earn-rank";
    rank.textContent = i + 1;
    const nm = document.createElement("span");
    nm.className = "earn-name";
    nm.textContent = u.first_name +
      (u.username ? " @" + u.username : "");
    const val = document.createElement("span");
    val.className = "earn-val";
    val.textContent = valText(u);
    row.append(rank, nm, val);
    box.appendChild(row);
  });
}

async function loadEarnings() {
  try {
    const e = await api("/admin/earnings");
    $("earn-ads-today").textContent = e.ads_today;
    $("earn-est-today").textContent = fmtTk(e.est_today);
    $("earn-ads-month").textContent = e.ads_month;
    $("earn-ads-total").textContent = e.ads_total + " all time";
    $("earn-est-month").textContent = fmtTk(e.est_month);
    $("earn-per-ad").textContent =
      "৳" + parseFloat(e.rate_per_ad.toFixed(4));
    $("earn-per-1000").textContent = fmtTk(e.rate_per_1000);
    if (document.activeElement !== $("earn-rate-in"))
      $("earn-rate-in").value = e.rate_per_1000 || "";
    const chart = $("earn-chart");
    chart.innerHTML = "";
    const max = Math.max(...e.daily_14d.map(d => d.ads), 1);
    e.daily_14d.forEach(d => {
      const col = document.createElement("div");
      col.className = "earn-col";
      const v = document.createElement("div");
      v.className = "earn-col-val";
      v.textContent = d.ads || "";
      const bar = document.createElement("div");
      bar.className = "earn-col-bar";
      bar.style.height = Math.max(3, d.ads / max * 100) + "%";
      bar.title = d.day + ": " + d.ads + " ads";
      const lab = document.createElement("div");
      lab.className = "earn-col-lab";
      const dt = new Date(d.day + "T00:00:00");
      lab.textContent = dt.getDate() + "/" + (dt.getMonth() + 1);
      col.append(v, bar, lab);
      chart.appendChild(col);
    });
    earnRows("earn-top-points", e.top_points, u => u.points + " pts");
    earnRows("earn-top-today", e.top_earners_today,
             u => "+" + u.earned + " pts");
  } catch (err) { /* the panel keeps its dashes */ }
}

async function openUserDetail(telegramId) {
  const box = $("admin-user-detail");
  box.hidden = false;
  box.innerHTML = '<p class="hint">Loading member details…</p>';
  box.scrollIntoView({ behavior: "smooth", block: "nearest" });
  try {
    const u = await api("/admin/users/" + telegramId);
    box.innerHTML = "";
    const card = document.createElement("div");
    card.className = "card detail-card";
    const head = document.createElement("div");
    head.className = "admin-row";
    const info = document.createElement("div");
    info.className = "admin-info";
    const t = document.createElement("div");
    t.className = "admin-title";
    t.textContent = "👤 " + u.first_name + (u.is_verified ? " ✓" : "") +
      (u.is_banned ? " 🚫" : "");
    const s = document.createElement("div");
    s.className = "admin-sub";
    s.textContent = (u.username ? "@" + u.username + " · " : "") +
      "ID " + u.telegram_id;
    info.append(t, s);
    const close = document.createElement("button");
    close.textContent = "✕ Close";
    close.onclick = () => { box.hidden = true; box.innerHTML = ""; };
    head.append(info, close);
    const grid = document.createElement("div");
    grid.className = "detail-grid";
    const joined = u.created_at ? u.created_at.slice(0, 10) : "—";
    [["🌍 Country", u.country || "Unknown"],
     ["🗣️ Language", u.language_code || "—"],
     ["📅 Joined", joined],
     ["👀 Last seen", relTime(u.last_seen_at)],
     ["📝 Posts", u.posts], ["💬 Comments", u.comments],
     ["👥 Followers", u.followers], ["➡️ Following", u.following],
     ["⭐ Points", u.points], ["🏆 Earned total", u.points_earned_total],
     ["📺 Ads watched", u.ads_watched],
     ["⏱️ Time in app (total)", fmtDur(u.seconds_total)],
     ["⏱️ Time today", fmtDur(u.seconds_today)],
     ["🔁 Visits today", u.sessions_today],
     ["📆 Active days", u.active_days],
     ["🔗 Invited by", u.referrer_id || "—"],
    ].forEach(([k, v]) => {
      const cell = document.createElement("div");
      cell.className = "detail-cell";
      const kk = document.createElement("div");
      kk.className = "detail-k"; kk.textContent = k;
      const vv = document.createElement("div");
      vv.className = "detail-v"; vv.textContent = v;
      cell.append(kk, vv);
      grid.appendChild(cell);
    });
    card.append(head, grid);
    if (u.bio) {
      const bio = document.createElement("p");
      bio.className = "hint"; bio.textContent = "“" + u.bio + "”";
      card.appendChild(bio);
    }
    // Phase 24: full-control tools on every member's detail card.
    const ctl = document.createElement("div");
    ctl.className = "detail-controls";
    const ctlHead = document.createElement("div");
    ctlHead.className = "admin-sub";
    ctlHead.textContent = "🛠️ Admin controls";
    ctl.appendChild(ctlHead);
    const prow = document.createElement("div");
    prow.className = "ctl-row";
    const pin = document.createElement("input");
    pin.type = "number"; pin.value = "100"; pin.min = "1";
    pin.placeholder = "Points amount";
    const pAdd = document.createElement("button");
    pAdd.textContent = "⭐ Add";
    pAdd.onclick = () =>
      adjustPoints(u.telegram_id, Math.abs(parseInt(pin.value || "0", 10)));
    const pSub = document.createElement("button");
    pSub.textContent = "⭐ Deduct";
    pSub.onclick = () =>
      adjustPoints(u.telegram_id, -Math.abs(parseInt(pin.value || "0", 10)));
    prow.append(pin, pAdd, pSub);
    ctl.appendChild(prow);
    if (u.telegram_id !== 1) {
      const vBtn = document.createElement("button");
      vBtn.className = "wide";
      vBtn.textContent = u.is_verified
        ? "Remove blue tick ✓" : "Grant blue tick ✓";
      vBtn.onclick = () => toggleVerify(u.telegram_id, !u.is_verified);
      ctl.appendChild(vBtn);
    }
    const peName = document.createElement("input");
    peName.id = "pe-name"; peName.type = "text"; peName.maxLength = 128;
    peName.value = u.first_name; peName.placeholder = "Name";
    const peBio = document.createElement("textarea");
    peBio.id = "pe-bio"; peBio.rows = 2; peBio.maxLength = 1000;
    peBio.value = u.bio || ""; peBio.placeholder = "Bio";
    const peSave = document.createElement("button");
    peSave.className = "wide";
    peSave.textContent = "Save name & bio";
    peSave.onclick = () => saveMemberProfile(u.telegram_id);
    ctl.append(peName, peBio, peSave);
    if (u.telegram_id !== 1 && me && u.telegram_id !== me.telegram_id) {
      const del = document.createElement("button");
      del.className = "danger-btn wide";
      del.textContent = "🗑️ Delete this member completely";
      del.onclick = () => deleteMember(u.telegram_id, u.first_name);
      ctl.appendChild(del);
    }
    card.appendChild(ctl);
    box.appendChild(card);
  } catch (e) { box.innerHTML = '<p class="hint">Could not load details.</p>'; }
}

async function loadAdminStats() {
  const box = $("admin-stats");
  box.innerHTML = "";
  try {
    const s = await api("/admin/stats");
    [["👥 Members", s.users], ["📝 Posts", s.posts],
     ["💬 Comments", s.comments], ["🚩 Reports", s.open_reports],
     ["🚫 Banned", s.banned_users], ["⭐ Points", s.total_points]
    ].forEach(([l, v]) => box.appendChild(statCard(l, v)));
    const ahR = $("ah-reports");
    if (ahR) ahR.textContent = s.open_reports;
  } catch (e) { box.textContent = "Could not load stats."; }
}

// ------------------------------------------------- Phase 107: backup --
// Admin-only full-site backup: download / send-to-Telegram /
// restore-from-file. The file lives with the owner (phone or bot
// chat); the server keeps no copy. Restore is destructive by
// design, so the button stays inert until a file is picked AND
// RESTORE is typed — the server demands the same.
let backupPicked = null;
function wireBackupCard() {
  const dl = $("backup-download");
  if (!dl || dl.dataset.wired) return;
  dl.dataset.wired = "1";
  const st = $("backup-status");
  const say = t => { if (st) st.textContent = t; };
  dl.onclick = async () => {
    dl.disabled = true;
    say("Preparing the full backup…");
    try {
      const data = await api("/admin/backup");
      const blob = new Blob([JSON.stringify(data, null, 1)],
                            { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "nexora-full-backup-" +
        new Date().toISOString().slice(0, 10) + ".json";
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 4000);
      say("Backup downloaded ✓ — keep the file safe.");
    } catch (e) {
      say("Download did not work here — try “Send to my Telegram” instead.");
    }
    dl.disabled = false;
  };
  const send = $("backup-send");
  send.onclick = async () => {
    send.disabled = true;
    say("Sending the backup to your bot chat…");
    try {
      const r = await api("/admin/backup/send", { method: "POST" });
      if (r.sent) say("Sent ✓ — check your chat with the bot for the backup file.");
      else say("The bot could not message you — use Download instead.");
    } catch (e) { say("Could not send the backup."); }
    send.disabled = false;
  };
  const fileIn = $("backup-file");
  $("backup-pick").onclick = () => fileIn.click();
  fileIn.onchange = () => {
    const f = fileIn.files && fileIn.files[0];
    if (!f) return;
    const rd = new FileReader();
    rd.onload = () => {
      try {
        const parsed = JSON.parse(rd.result);
        if (parsed.format !== "nexora-backup" || parsed.version !== 1) {
          say("That file is not a Nexora backup.");
          backupPicked = null;
          return;
        }
        backupPicked = parsed;
        const n = Object.values(parsed.tables || {})
          .reduce((a, rows) => a + rows.length, 0);
        say("Backup file ready: " + n + " rows from " +
            (parsed.exported_at || "an earlier backup") +
            ". Type RESTORE below, then tap Restore now.");
      } catch (e) {
        backupPicked = null;
        say("Could not read that file — pick a Nexora backup JSON.");
      }
    };
    rd.readAsText(f);
  };
  $("backup-restore").onclick = async () => {
    if (!backupPicked) { say("Pick a backup file first."); return; }
    const typed = ($("backup-confirm").value || "").trim();
    if (typed !== "RESTORE") {
      say("Type RESTORE in the box above to confirm the restore.");
      return;
    }
    const btn = $("backup-restore");
    btn.disabled = true;
    say("Restoring the whole site — do not close the app…");
    try {
      const r = await api("/admin/restore", { method: "POST",
        body: JSON.stringify({ confirm: "RESTORE", backup: backupPicked }) });
      const total = Object.values(r.restored || {})
        .reduce((a, n) => a + n, 0);
      say("Restored ✓ — " + total + " rows back in place. Reloading…");
      backupPicked = null;
      $("backup-confirm").value = "";
      setTimeout(() => location.reload(), 1500);
    } catch (e) {
      say("Restore failed — nothing was changed. " + (e.message || ""));
    }
    btn.disabled = false;
  };
}

function loadAdmin() {
  if (!me || !me.is_admin) return;
  loadEarnings();
  loadDashboard();
  loadAdminStats();
  loadAdminReports();
  loadAdminUsers($("admin-user-q").value.trim());
  loadVerifications();
  loadManaged();
  loadAdminComments();
  prefillOfficial();
  loadAdminPosts();
  wireBackupCard();
}

async function loadAdminReports() {
  const box = $("admin-reports");
  box.innerHTML = "";
  try {
    const r = await api("/admin/reports?status=open");
    if (!r.reports.length) {
      box.innerHTML = '<p class="hint">No open reports. 🎉</p>';
      return;
    }
    r.reports.forEach(rep => {
      const card = document.createElement("div");
      card.className = "card admin-row";
      const info = document.createElement("div");
      info.className = "admin-info";
      const t = document.createElement("div");
      t.className = "admin-title";
      t.textContent = "Post #" + rep.post_id + " — " + (rep.reason || "reported");
      const s = document.createElement("div");
      s.className = "admin-sub";
      s.textContent = "by " + (rep.reporter_name || rep.reporter_id) +
        (rep.post_caption ? " · “" + rep.post_caption + "”" : "") +
        (rep.post_deleted ? " · post already removed" : "");
      info.append(t, s);
      const rm = document.createElement("button");
      rm.className = "danger-btn"; rm.textContent = "Remove post";
      rm.onclick = async () => {
        await api("/admin/reports/" + rep.id + "/resolve",
          { method: "POST", body: JSON.stringify({ action: "remove_post" }) });
        loadAdminReports(); loadAdminPosts();
      };
      const dis = document.createElement("button");
      dis.textContent = "Dismiss";
      dis.onclick = async () => {
        await api("/admin/reports/" + rep.id + "/resolve",
          { method: "POST", body: JSON.stringify({ action: "dismiss" }) });
        loadAdminReports();
      };
      card.append(info, rm, dis);
      box.appendChild(card);
    });
  } catch (e) { box.textContent = "Could not load reports."; }
}

async function loadAdminUsers(q) {
  const box = $("admin-users");
  box.innerHTML = "";
  try {
    const r = await api("/admin/users?q=" + encodeURIComponent(q || ""));
    if (!r.users.length) {
      box.innerHTML = '<p class="hint">No members found.</p>';
      return;
    }
    r.users.forEach(u => {
      const row = document.createElement("div");
      row.className = "card admin-row";
      const info = document.createElement("div");
      info.className = "admin-info";
      const t = document.createElement("div");
      t.className = "admin-title";
      t.textContent = u.first_name + (u.is_verified ? " ✓" : "") +
        (u.is_managed ? " 🤖" : "") +
        (u.is_banned ? " 🚫" : "");
      const s = document.createElement("div");
      s.className = "admin-sub";
      s.textContent = (u.username ? "@" + u.username + " · " : "") +
        "ID " + u.telegram_id + " · ⭐ " + u.points +
        (u.country ? " · 🌍 " + u.country : "") +
        " · seen " + relTime(u.last_seen_at);
      info.append(t, s);
      const details = document.createElement("button");
      details.textContent = "Details";
      details.onclick = () => openUserDetail(u.telegram_id);
      const btn = document.createElement("button");
      btn.textContent = u.is_banned ? "Unban" : "Ban";
      if (!u.is_banned) btn.className = "danger-btn";
      btn.onclick = async () => {
        if (!u.is_banned &&
            !confirm("Ban " + u.first_name + "? They will lose access.")) return;
        try {
          await api("/admin/ban", { method: "POST", body: JSON.stringify(
            { telegram_id: u.telegram_id, banned: !u.is_banned }) });
          loadAdminUsers($("admin-user-q").value.trim());
          loadAdminStats();
        } catch (e) { alert(e.message || "Action failed"); }
      };
      row.append(info, details, btn);
      box.appendChild(row);
    });
  } catch (e) { box.textContent = "Could not load members."; }
}

async function loadManaged() {
  const box = $("admin-managed");
  box.innerHTML = "";
  try {
    const r = await api("/admin/users?managed=1&limit=100");
    if (!r.users.length) {
      box.innerHTML = '<p class="hint">No managed users yet — create ' +
        'the first one above.</p>';
      return;
    }
    r.users.forEach(u => {
      const row = document.createElement("div");
      row.className = "card admin-row";
      const info = document.createElement("div");
      info.className = "admin-info";
      const t = document.createElement("div");
      t.className = "admin-title";
      t.textContent = "🤖 " + u.first_name + (u.is_banned ? " 🚫" : "");
      const s = document.createElement("div");
      s.className = "admin-sub";
      s.textContent = (u.username ? "@" + u.username + " · " : "") +
        "ID " + u.telegram_id + " · ⭐ " + u.points;
      info.append(t, s);
      const act = document.createElement("button");
      act.textContent = "🎭 Act as";
      act.onclick = () => {
        sessionStorage.setItem("nx_actas", String(u.telegram_id));
        sessionStorage.setItem("nx_actas_name", u.first_name);
        location.reload();
      };
      const del = document.createElement("button");
      del.className = "danger-btn";
      del.textContent = "Delete";
      del.onclick = async () => {
        if (!confirm("Delete managed user " + u.first_name +
            " completely, including all their posts?")) return;
        try {
          await api("/admin/fake-users/" + u.telegram_id,
                    { method: "DELETE" });
          loadManaged(); loadDashboard();
        } catch (e) {
          alert("Could not delete this managed user.");
        }
      };
      row.append(info, act, del);
      box.appendChild(row);
    });
  } catch (e) { box.textContent = "Could not load managed users."; }
}

// Phase 21/23: act-as entry points share one helper pair, so every
// door (Admin Panel button, drawer item, composer switch) behaves
// identically — and every exit fully returns to the owner's own ID.
function startActAs(id, name) {
  sessionStorage.setItem("nx_actas", String(id));
  sessionStorage.setItem("nx_actas_name", name);
  location.reload();
}
function stopActAs() {
  sessionStorage.removeItem("nx_actas");
  sessionStorage.removeItem("nx_actas_name");
  location.reload();
}

// The official system account (telegram id 1) — the owner posts and
// manages the platform's own page by acting as it.
$("official-actas").onclick = () =>
  startActAs(1, "Nexora Social (Official)");

// Phase 24: the act-as banner's Admin Panel button — one tap from
// any acting session back to the owner's own ID with the Admin
// Panel open (the flag survives the act-as reload).
$("actas-admin").onclick = () => {
  sessionStorage.setItem("nx_open_admin", "1");
  stopActAs();
};
function maybeOpenAdmin() {
  if (sessionStorage.getItem("nx_open_admin")) {
    sessionStorage.removeItem("nx_open_admin");
    if (me && me.is_admin) showView("admin");
  }
}

// Phase 24: edit the official account's public name/bio right from
// its Admin Panel section (photo is changed by acting as it).
async function prefillOfficial() {
  try {
    const off = await api("/users/1");
    $("off-name").value = off.first_name || "";
    $("off-bio").value = off.bio || "";
  } catch (e) { /* prefill is best-effort */ }
}
$("off-save").onclick = async () => {
  try {
    const r = await api("/admin/users/1/profile", { method: "POST",
      body: JSON.stringify({ first_name: $("off-name").value,
                             bio: $("off-bio").value }) });
    $("off-result").textContent = "Saved — the official profile now " +
      "shows as “" + r.first_name + "”.";
  } catch (e) {
    $("off-result").textContent = "Could not save (the name cannot " +
      "be empty).";
  }
};

// Phase 23: the composer shows who you are posting as. Admins get a
// one-tap switch to the Official account; while acting as anyone,
// the same row offers the way back to their own account.
function paintComposerAs() {
  const row = $("composer-as");
  if (!row) return;
  if (actAsId()) {
    row.hidden = false;
    $("composer-as-label").textContent = "Posting as " +
      (sessionStorage.getItem("nx_actas_name") || "another account");
    $("composer-as-btn").textContent = "Back to my account";
  } else if (me && me.is_admin) {
    row.hidden = false;
    $("composer-as-label").textContent = "Posting as you";
    $("composer-as-btn").textContent = "Post as Official 📣";
  } else {
    row.hidden = true;
  }
}
$("composer-as-btn").onclick = () => {
  if (actAsId()) stopActAs();
  else startActAs(1, "Nexora Social (Official)");
};

$("mu-create").onclick = async () => {
  const name = $("mu-name").value.trim();
  if (!name) { $("mu-result").textContent = "Give the user a name first."; return; }
  const btn = $("mu-create");
  btn.disabled = true;
  try {
    const r = await api("/admin/fake-users", { method: "POST",
      body: JSON.stringify({
        first_name: name,
        username: $("mu-username").value.trim() || null,
        count: parseInt($("mu-count").value || "1", 10) || 1 }) });
    $("mu-result").textContent = "Created " + r.created.length +
      " managed user(s): " +
      r.created.map(u => u.first_name).join(", ") +
      ". Use 🎭 Act as to operate one.";
    $("mu-name").value = ""; $("mu-username").value = "";
    loadManaged(); loadDashboard(); loadAdminStats();
  } catch (e) { $("mu-result").textContent = "Could not create the user."; }
  btn.disabled = false;
};

async function loadVerifications() {
  const box = $("admin-verifications");
  box.innerHTML = "";
  try {
    const r = await api("/admin/verifications");
    if (!r.requests.length) {
      box.innerHTML = '<p class="hint">No verification applications ' +
        'yet. Members can apply from their Me page at 1,000 ' +
        'followers.</p>';
      return;
    }
    r.requests.forEach(q => {
      const rowEl = document.createElement("div");
      rowEl.className = "card admin-row";
      rowEl.appendChild(avatarEl(q.first_name, q.telegram_id,
                                 false, q.photo_file_id));
      const info = document.createElement("div");
      info.className = "admin-info";
      const t = document.createElement("div");
      t.className = "admin-title";
      t.textContent = q.first_name +
        (q.username ? " (@" + q.username + ")" : "");
      const s = document.createElement("div");
      s.className = "admin-sub";
      s.textContent = "👥 " + q.followers + " followers · 📝 " +
        q.posts + " posts · applied " + relTime(q.created_at) +
        " · " + q.status.toUpperCase();
      info.append(t, s);
      rowEl.appendChild(info);
      if (q.status === "pending") {
        const ok = document.createElement("button");
        ok.textContent = "✓ Approve";
        ok.onclick = () => decideVerification(q.id, true);
        const no = document.createElement("button");
        no.className = "danger-btn";
        no.textContent = "Reject";
        no.onclick = () => decideVerification(q.id, false);
        rowEl.append(ok, no);
      }
      box.appendChild(rowEl);
    });
  } catch (e) { box.textContent = "Could not load applications."; }
}

async function decideVerification(id, approve) {
  try {
    await api("/admin/verifications/" + id + "/decide",
              { method: "POST", body: JSON.stringify({ approve }) });
    setStatus(approve ? "Application approved — blue tick granted."
                      : "Application rejected.");
    loadVerifications();
  } catch (e) { setStatus("Could not decide that application."); }
}

// ------------------------------------------------ Phase 24: full control --
// Comment moderation plus the member-detail power tools (points,
// verification, profile edit, full delete). Every action re-checks
// admin rights on the server; these buttons are only a front end.
async function loadAdminComments() {
  const box = $("admin-comments");
  box.innerHTML = "";
  try {
    const r = await api("/admin/comments");
    if (!r.comments.length) {
      box.innerHTML = '<p class="hint">No comments yet.</p>';
      return;
    }
    r.comments.forEach(cm => {
      const row = document.createElement("div");
      row.className = "card admin-row";
      row.appendChild(avatarEl(cm.author_name, cm.author_id,
                               false, cm.author_photo));
      const info = document.createElement("div");
      info.className = "admin-info";
      const t = document.createElement("div");
      t.className = "admin-title";
      t.textContent = cm.text.length > 90
        ? cm.text.slice(0, 90) + "…" : cm.text;
      const s = document.createElement("div");
      s.className = "admin-sub";
      s.textContent = cm.author_name + " · post #" + cm.post_id +
        " · " + relTime(cm.created_at);
      info.append(t, s);
      const rm = document.createElement("button");
      rm.className = "danger-btn";
      rm.textContent = "Remove";
      rm.onclick = async () => {
        if (!confirm("Remove this comment?")) return;
        try {
          await api("/admin/comments/" + cm.id + "/remove",
                    { method: "POST" });
          loadAdminComments();
        } catch (e) { setStatus("Could not remove the comment."); }
      };
      row.append(info, rm);
      box.appendChild(row);
    });
  } catch (e) { box.textContent = "Could not load comments."; }
}

async function adjustPoints(tid, delta) {
  if (!delta) { setStatus("Enter a points amount first."); return; }
  try {
    const r = await api("/admin/users/" + tid + "/points",
      { method: "POST", body: JSON.stringify({ delta }) });
    setStatus("Points updated — balance is now " + r.points + " ⭐.");
    openUserDetail(tid);
  } catch (e) { setStatus("Could not adjust points."); }
}

async function toggleVerify(tid, verified) {
  try {
    await api("/admin/users/" + tid + "/verify",
      { method: "POST", body: JSON.stringify({ verified }) });
    setStatus(verified ? "Blue tick granted ✓." : "Blue tick removed.");
    openUserDetail(tid);
    loadAdminUsers($("admin-user-q").value.trim());
  } catch (e) { setStatus("Could not change verification."); }
}

async function saveMemberProfile(tid) {
  try {
    await api("/admin/users/" + tid + "/profile",
      { method: "POST",
        body: JSON.stringify({ first_name: $("pe-name").value,
                               bio: $("pe-bio").value }) });
    setStatus("Profile saved.");
    openUserDetail(tid);
    loadAdminUsers($("admin-user-q").value.trim());
  } catch (e) { setStatus("Could not save (name cannot be empty)."); }
}

async function deleteMember(tid, name) {
  if (!confirm("DELETE " + name + " completely?\n\nTheir posts, " +
      "comments, likes, points and the account itself will be gone. " +
      "This cannot be undone.")) return;
  try {
    await api("/admin/users/" + tid, { method: "DELETE" });
    setStatus(name + " has been deleted completely.");
    const box = $("admin-user-detail");
    box.hidden = true; box.innerHTML = "";
    loadAdminUsers($("admin-user-q").value.trim());
    loadDashboard(); loadAdminStats();
  } catch (e) { setStatus("Could not delete that member."); }
}

async function loadAdminPosts() {
  const box = $("admin-posts");
  box.innerHTML = "";
  try {
    const r = await api("/admin/posts?limit=30");
    if (!r.posts.length) {
      box.innerHTML = '<p class="hint">No posts yet.</p>';
      return;
    }
    r.posts.forEach(p => {
      const row = document.createElement("div");
      row.className = "card admin-row";
      const info = document.createElement("div");
      info.className = "admin-info";
      const t = document.createElement("div");
      t.className = "admin-title";
      t.textContent = (p.type === "video" ? "🎬 " :
                       p.type === "photo" ? "🖼️ " : "📝 ") +
        "#" + p.id + " · " + p.author_name;
      const s = document.createElement("div");
      s.className = "admin-sub";
      s.textContent = (p.caption || "(no caption)") +
        (p.is_deleted ? " · REMOVED" : "");
      info.append(t, s);
      row.appendChild(info);
      if (!p.is_deleted) {
        const btn = document.createElement("button");
        btn.className = "danger-btn"; btn.textContent = "Remove";
        btn.onclick = async () => {
          if (!confirm("Remove post #" + p.id + "?")) return;
          await api("/admin/posts/" + p.id + "/remove", { method: "POST" });
          loadAdminPosts(); loadAdminStats();
        };
        row.appendChild(btn);
      }
      box.appendChild(row);
    });
  } catch (e) { box.textContent = "Could not load posts."; }
}

$("admin-user-go").onclick = () =>
  loadAdminUsers($("admin-user-q").value.trim());
$("admin-user-q").addEventListener("keydown", e => {
  if (e.key === "Enter") loadAdminUsers(e.target.value.trim());
});
$("earn-rate-save").onclick = async () => {
  const v = parseFloat($("earn-rate-in").value);
  if (isNaN(v) || v < 0) { setStatus("Enter a valid rate."); return; }
  try {
    await api("/admin/earnings/rate", { method: "POST",
      body: JSON.stringify({ rate_per_1000: v }) });
    setStatus("Earnings rate saved.");
    loadEarnings();
  } catch (e) { setStatus("Could not save the rate."); }
};
$("admin-bc-send").onclick = async () => {
  const text = $("admin-bc-text").value.trim();
  if (!text) return;
  if (!confirm("Send this announcement to ALL members via the bot?")) return;
  $("admin-bc-send").disabled = true;
  try {
    const r = await api("/admin/broadcast",
      { method: "POST", body: JSON.stringify({ text }) });
    $("admin-bc-result").textContent =
      "Sent to " + r.sent + " of " + r.recipients + " members.";
    $("admin-bc-text").value = "";
  } catch (e) { $("admin-bc-result").textContent = "Broadcast failed."; }
  $("admin-bc-send").disabled = false;
};

// ------------------------------------------------------------------ ads --
// AdsGram (Telegram Mini App ad network). Active only when the owner has
// registered the bot at adsgram.ai and set ADSGRAM_BLOCK_ID — /auth
// carries it as me.adsgram_block_id; empty means ads stay off. One
// interstitial per session, shown when the Videos tab is opened.
let adController = null;
let adShownThisSession = false;

function initAds() {
  const blockId = me && me.adsgram_block_id;
  if (!blockId || adController) return;
  const s = document.createElement("script");
  s.src = "https://sad.adsgram.ai/js/sad.min.js";
  s.onload = () => {
    try { adController = window.Adsgram.init({ blockId: String(blockId) }); }
    catch (e) { /* ads stay off if the SDK fails to load */ }
  };
  document.head.appendChild(s);
}

function maybeShowAd() {
  if (!adController || adShownThisSession) return;
  adShownThisSession = true;
  try {
    const p = adController.show();
    if (p && p.then) p.then(() => {
      // Phase 19: count real impressions on the owner's dashboard.
      api("/ads/shown", { method: "POST" }).catch(() => {});
    }).catch(() => {});
  } catch (e) {}
}

// Phase 113 (owner): the ad task's explicit "Watch ad" button. Unlike
// the once-per-session auto ad above, this is user-initiated, so it
// shows on demand; a completed show reports /ads/shown (awaited, so
// the task list refreshes only after the report lands) and that is
// the progress the task counts. No fill means no report, no points.
async function showTaskAd(btn) {
  if (!adController) {
    setStatus("Ads are not available right now.");
    return;
  }
  btn.disabled = true;
  btn.textContent = "Loading ad…";
  try {
    const p = adController.show();
    if (p && p.then) {
      await p;
      await api("/ads/shown", { method: "POST" }).catch(() => {});
      setStatus("Ad finished — you can claim the task now.");
    } else {
      setStatus("No ad available right now — try again later.");
    }
  } catch (e) {
    setStatus("No ad available right now — try again later.");
  }
  loadTasks();
}

// ------------------------------------------- Phase 36: messages + stories --
// Owner: a Facebook-style messenger in the top corner (💬 in the
// hero) — stories strip on top, conversation list, chat threads,
// and a start-a-chat list of the people you follow.
// Phase 41: while the sidebar is collapsed to its small pill,
// one pink dot on the logo stands in for both unread badges.
let gbBellCount = 0;
let gbMsgCount = 0;
function paintGbDot() {
  const d = $("gb-dot");
  if (d) d.hidden = !(gbBellCount > 0 || gbMsgCount > 0);
}
function paintMsgBadge(count) {
  const label = count > 99 ? "99+" : String(count || "");
  const b = $("msg-badge");
  if (b) { b.hidden = !count; b.textContent = label; }
  const d = $("gb-msg-badge");
  if (d) { d.hidden = !count; d.textContent = label; }
  gbMsgCount = count || 0;
  paintGbDot();
}
async function refreshMsgBadge() {
  try {
    const r = await api("/messages/unread");
    paintMsgBadge(r.count);
  } catch (e) { /* badge just stays as-is */ }
}
$("hero-msg").onclick = () => showView("messages");

function loadMessages() {
  loadStories();
  loadConversations();
  loadPeople();
}

function personRow(u, subText, onClick) {
  const row = document.createElement("div");
  row.className = "card conv-row";
  row.appendChild(avatarEl(u.first_name, u.telegram_id, false,
                           u.photo_file_id));
  const info = document.createElement("div");
  info.className = "admin-info";
  const nm = document.createElement("div");
  nm.className = "conv-name";
  nm.textContent = u.first_name + (u.verified ? " ✓" : "");
  const pv = document.createElement("div");
  pv.className = "admin-sub conv-prev";
  pv.textContent = subText || "";
  info.append(nm, pv);
  row.appendChild(info);
  row.style.cursor = "pointer";
  row.onclick = onClick;
  return row;
}

async function loadConversations() {
  const box = $("conv-list");
  box.innerHTML = "";
  try {
    const r = await api("/messages");
    $("conv-empty").hidden = r.conversations.length > 0;
    r.conversations.forEach(cv => {
      const row = personRow(cv.user,
        (cv.last.mine ? "You: " : "") + cv.last.text,
        () => openChat(cv.user.telegram_id));
      const right = document.createElement("div");
      right.className = "conv-right";
      const tm = document.createElement("div");
      tm.className = "admin-sub";
      tm.textContent = relTime(cv.last.created_at);
      right.appendChild(tm);
      if (cv.unread) {
        const pill = document.createElement("span");
        pill.className = "conv-unread";
        pill.textContent = cv.unread;
        right.appendChild(pill);
      }
      row.appendChild(right);
      box.appendChild(row);
    });
  } catch (e) { box.textContent = "Could not load chats."; }
}

async function loadPeople() {
  const box = $("people-list");
  box.innerHTML = "";
  try {
    const r = await api("/me/following");
    const people = r.users.filter(u =>
      !me || u.telegram_id !== me.telegram_id);
    $("people-empty").hidden = people.length > 0;
    people.forEach(u => box.appendChild(personRow(u,
      u.username ? "@" + u.username : "Tap to chat",
      () => openChat(u.telegram_id))));
  } catch (e) { /* the section just stays empty */ }
}

// ------------------------------------------------------------- chat thread --
let chatWith = null;
let chatTimer = null;
function stopChatPoll() {
  if (chatTimer) { clearInterval(chatTimer); chatTimer = null; }
}
async function openChat(uid) {
  chatWith = uid;
  showView("chat");
  $("chat-thread").innerHTML = "";
  await loadThread(true);
  stopChatPoll();
  chatTimer = setInterval(() => {
    if (chatWith === uid) loadThread(false);
  }, 8000);
}
async function loadThread(scroll) {
  if (!chatWith) return;
  try {
    const r = await api("/messages/" + chatWith);
    $("chat-title").textContent = r.user.first_name +
      (r.user.verified ? " ✓" : "");
    const av = $("chat-avatar");
    av.innerHTML = "";
    av.appendChild(avatarEl(r.user.first_name, r.user.telegram_id,
                            false, r.user.photo_file_id));
    const box = $("chat-thread");
    box.innerHTML = "";
    $("chat-empty").hidden = r.messages.length > 0;
    r.messages.forEach(m => {
      const b = document.createElement("div");
      b.className = "bubble " + (m.mine ? "mine" : "theirs");
      b.appendChild(document.createTextNode(m.text));
      const t = document.createElement("div");
      t.className = "bubble-time";
      t.textContent = relTime(m.created_at) +
        (m.mine && m.read ? " · seen" : "");
      b.appendChild(t);
      box.appendChild(b);
    });
    refreshMsgBadge();
    if (scroll) {
      const sc = $("app-scroll");
      if (sc) sc.scrollTop = sc.scrollHeight;
    }
  } catch (e) { setStatus("Could not load the chat."); }
}
async function sendChat() {
  const inp = $("chat-input");
  const text = inp.value.trim();
  if (!text || !chatWith) return;
  inp.value = "";
  try {
    await api("/messages/" + chatWith,
      { method: "POST", body: JSON.stringify({ text }) });
    loadThread(true);
  } catch (e) {
    inp.value = text;
    setStatus("Message could not be sent.");
  }
}
$("chat-send").onclick = sendChat;
$("chat-input").addEventListener("keydown", e => {
  if (e.key === "Enter") sendChat();
});
$("chat-back").onclick = () => showView("messages");

// ----------------------------------------------------------------- stories --
let storyGroups = [];
let storyPos = null;
let storyTimer = null;
let ownStoryGroup = null;

async function loadStories() {
  const strip = $("stories-strip");
  strip.innerHTML = "";
  ownStoryGroup = null;
  // Your own circle is always first (Facebook-style): tap it to
  // view your story, tap the + to add one.
  const own = document.createElement("div");
  own.className = "story-item";
  const oWrap = document.createElement("div");
  oWrap.className = "story-ring own-ring";
  if (me) oWrap.appendChild(avatarEl(me.first_name, me.telegram_id,
                                     true, me.photo_file_id));
  const plus = document.createElement("span");
  plus.className = "story-plus";
  plus.textContent = "+";
  plus.onclick = e => { e.stopPropagation(); $("story-file").click(); };
  oWrap.appendChild(plus);
  const oLabel = document.createElement("div");
  oLabel.className = "story-label";
  oLabel.textContent = "Your story";
  own.append(oWrap, oLabel);
  own.onclick = () => {
    if (ownStoryGroup) {
      const gi = storyGroups.indexOf(ownStoryGroup);
      if (gi >= 0) openStory(gi, 0);
    } else {
      $("story-file").click();
    }
  };
  strip.appendChild(own);
  try {
    const r = await api("/stories");
    storyGroups = r.groups;
    storyGroups.forEach((g, gi) => {
      if (me && g.author.telegram_id === me.telegram_id) {
        ownStoryGroup = g;
        return;
      }
      const item = document.createElement("div");
      item.className = "story-item";
      const ring = document.createElement("div");
      ring.className = "story-ring" + (g.has_unviewed ? " unviewed" : "");
      ring.appendChild(avatarEl(g.author.first_name,
                                g.author.telegram_id, true,
                                g.author.photo_file_id));
      const label = document.createElement("div");
      label.className = "story-label";
      label.textContent = g.author.first_name.split(" ")[0];
      item.append(ring, label);
      item.onclick = () => openStory(gi, 0);
      strip.appendChild(item);
    });
  } catch (e) { /* strip keeps just your own circle */ }
}

$("story-file").addEventListener("change", async () => {
  const f = $("story-file").files[0];
  $("story-file").value = "";
  if (!f) return;
  setStatus("Posting your story…");
  try {
    const form = new FormData();
    form.append("file", await shrinkForUpload(f));
    await apiFormProgress("/stories/upload", form, pct => {
      setStatus(pct === null ? "Posting your story… finishing"
                             : "Posting your story… " + pct + "%");
    }, null);
    setStatus("📸 Story posted — it stays up for 24 hours.");
    loadStories();
  } catch (e) {
    setStatus("Story upload failed — check your connection and try again.");
  }
});

function stopStoryTimer() {
  if (storyTimer) { clearTimeout(storyTimer); storyTimer = null; }
}
function openStory(gi, si) {
  storyPos = { g: gi, s: si || 0 };
  $("story-wrap").hidden = false;
  paintStory();
}
function paintStory() {
  stopStoryTimer();
  const g = storyGroups[storyPos.g];
  if (!g) { closeStory(); return; }
  const s = g.stories[storyPos.s];
  if (!s) { nextStory(); return; }
  $("story-img").src = mediaUrl(s.media_file_id);
  $("story-author").textContent = g.author.first_name +
    (g.author.verified ? " ✓" : "");
  $("story-time").textContent = relTime(s.created_at);
  $("story-views").textContent = s.mine ? "👁 " + s.views + " views" : "";
  $("story-del").hidden = !s.mine && !(me && me.is_admin);
  const fill = $("story-progress-fill");
  fill.style.transition = "none";
  fill.style.width = "0%";
  requestAnimationFrame(() => {
    fill.style.transition = "width 6s linear";
    fill.style.width = "100%";
  });
  if (!s.mine && !s.viewed) {
    api("/stories/" + s.id + "/view", { method: "POST" })
      .then(r => { s.views = r.views; s.viewed = true; })
      .catch(() => {});
  }
  storyTimer = setTimeout(nextStory, 6000);
}
function nextStory() {
  if (!storyPos) return;
  const g = storyGroups[storyPos.g];
  if (g && storyPos.s + 1 < g.stories.length) {
    storyPos = { g: storyPos.g, s: storyPos.s + 1 };
    paintStory();
  } else if (storyPos.g + 1 < storyGroups.length) {
    storyPos = { g: storyPos.g + 1, s: 0 };
    paintStory();
  } else {
    closeStory();
  }
}
function prevStory() {
  if (!storyPos) return;
  if (storyPos.s > 0) {
    storyPos = { g: storyPos.g, s: storyPos.s - 1 };
  } else if (storyPos.g > 0) {
    const pg = storyGroups[storyPos.g - 1];
    storyPos = { g: storyPos.g - 1, s: pg.stories.length - 1 };
  }
  paintStory();
}
function closeStory() {
  stopStoryTimer();
  storyPos = null;
  $("story-wrap").hidden = true;
  loadStories();
}
$("story-close").onclick = closeStory;
$("story-backdrop").onclick = closeStory;
$("story-next").onclick = nextStory;
$("story-prev").onclick = prevStory;
$("story-del").onclick = async () => {
  const g = storyGroups[storyPos.g];
  const s = g && g.stories[storyPos.s];
  if (!s) return;
  try {
    await api("/stories/" + s.id, { method: "DELETE" });
    setStatus("Story deleted.");
  } catch (e) { setStatus("Could not delete the story."); }
  closeStory();
};

// ---------- Phase 69: Nexa, the AI assistant ----------
// She lives behind the sidebar: her chat opens only from her
// sidebar card. Replies are spoken aloud (Gemini voice when the
// server has a key, otherwise the phone's own speech voice at a
// cute high pitch) while her picture switches to the talking
// pose.
let nexaHist = [];
let nexaGreeted = false;
let nexaBusy = false;
let nexaPairShown = false;
function nexaPose(p) {
  const im = $("nexa-img");
  if (im) im.src = "nexa/" + p + ".webp";
}

// Phase 73 (owner): Nexa lives her own little life — when she
// is not answering, she is always busy doing something, and the
// stage rotates through her day. And the chat is ephemeral:
// asking a new question clears the previous question + answer.
const NEXA_LIFE = [
  { img: "life-work", label: "Nexa is working 💻" },
  { img: "life-cooking", label: "Nexa is cooking 🍳" },
  { img: "life-study", label: "Nexa is studying 📚" },
  { img: "life-gym", label: "Nexa is at the gym 🏋️" },
  { img: "life-cleaning", label: "Nexa is cleaning her room 🧹" },
  { img: "life-run", label: "Nexa is out running 🏃‍♀️" },
  { img: "life-garden", label: "Nexa is watering her plants 🌿" },
  { img: "life-painting", label: "Nexa is painting 🎨" },
  { img: "life-guitar", label: "Nexa is playing guitar 🎸" },
  { img: "life-yoga", label: "Nexa is doing yoga 🧘" },
];
let nexaLifeIdx = 0;
let nexaLifeTimer = null;

function nexaLifeTick() {
  if (nexaBusy) return;
  const view = $("view-assistant");
  if (!view || view.hidden) return;
  const step = NEXA_LIFE[nexaLifeIdx % NEXA_LIFE.length];
  nexaLifeIdx += 1;
  nexaPose(step.img);
  const st = $("nexa-status");
  if (st) st.textContent = step.label;
}

function nexaLifeStart() {
  if (nexaLifeTimer) return;
  nexaLifeTimer = setInterval(nexaLifeTick, 6000);
}

function nexaLifeStop() {
  if (nexaLifeTimer) clearInterval(nexaLifeTimer);
  nexaLifeTimer = null;
}

function nexaBubble(text, who) {
  const log = $("nexa-log");
  if (!log) return null;
  const b = document.createElement("div");
  b.className = "nexa-msg " + who;
  b.textContent = text;
  log.appendChild(b);
  const sc = $("app-scroll");
  if (sc) sc.scrollTop = sc.scrollHeight;
  return b;
}

function openAssistant() {
  nexaLifeStart();
  nexaPose(nexaGreeted ? "idle" : "wave");
  if (!nexaGreeted) {
    nexaGreeted = true;
    const hello = "Hi! I'm Nexa, your AI friend inside Nexora "
      + "Social. Ask me about posts, points, tasks or designs — "
      + "or just chat with me!";
    nexaBubble(hello, "bot");
    nexaHist.push({ role: "nexa", text: hello });
  }
}

function nexaStop() {
  nexaLifeStop();
  nexaBusy = false;
}

async function sendNexa(prefill) {
  const inp = $("nexa-input");
  const text = (prefill || (inp ? inp.value : "") || "").trim();
  if (!text) return;
  if (!prefill && inp) inp.value = "";
  if (nexaPairShown) $("nexa-log").innerHTML = "";
  nexaBusy = true;
  nexaBubble(text, "me");
  nexaHist.push({ role: "user", text: text });
  nexaPose("think");
  const st = $("nexa-status");
  if (st) st.textContent = "Nexa is thinking…";
  const typing = nexaBubble("…", "bot typing");
  try {
    const r = await api("/assistant/chat", {
      method: "POST",
      body: JSON.stringify({ message: text,
                             history: nexaHist.slice(0, -1) }) });
    if (typing) typing.remove();
    const reply = (r && r.reply)
      || "Sorry, I missed that — could you say it again?";
    if (st) st.textContent = (r && r.ai)
      ? "AI mode · Gemini" : "Guide mode";
    nexaBubble(reply, "bot");
    nexaHist.push({ role: "nexa", text: reply });
    if (nexaHist.length > 12) nexaHist = nexaHist.slice(-12);
    nexaPairShown = true;
    nexaBusy = false;
    nexaPose("idle");
  } catch (e) {
    if (typing) typing.remove();
    if (st) st.textContent = "Your AI friend — ask me anything!";
    nexaBubble("Hmm, I can't think right now. Please try again "
      + "in a moment!", "bot");
    nexaPairShown = true;
    nexaBusy = false;
    nexaPose("idle");
  }
}

$("nexa-send").onclick = () => sendNexa();
$("nexa-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    sendNexa();
    $("nexa-input").blur();
  }
});
document.querySelectorAll(".nexa-chip").forEach(c =>
  c.onclick = () => sendNexa(c.dataset.q));

// ---------- Phase 70: no long-press menus anywhere ----------
// A long-press on anything (image, video, button, text) must
// never pop the WebView's native menu — it shows the hosting
// (Render) URL. Text fields keep their menu: paste must work.
document.addEventListener("contextmenu", (e) => {
  const t = e.target;
  if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA")) return;
  e.preventDefault();
}, true);
document.addEventListener("dragstart", (e) => {
  if (e.target && e.target.tagName === "IMG") e.preventDefault();
}, true);
