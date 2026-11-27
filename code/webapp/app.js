// Nexora Mini App — feed, posting, likes, comments, profiles, follow,
// search, referrals and points, all against the FastAPI backend.
// Login is the Telegram initData sent with every request (see /auth).
// Phase 188 (Job 1): telegram-web-app.js is an external script —
// when it fails to load (slow or flaky connection) window.Telegram
// is undefined and the old `window.Telegram.WebApp` dereference
// killed the WHOLE script before any UI painted: a blank page,
// i.e. "the whole site doesn't load". Fall back to a no-op stub
// so the app always reaches the entry screen, where bootFailed
// explains the failure and offers a working RETRY instead of a
// blank page. Normal Telegram opens are untouched — tg is the
// real WebApp object there, and every guarded tg.* use below
// (BackButton, openLink, downloadFile, LocationManager) already
// tolerates the stub's nulls/undefineds.
const tg = (window.Telegram && window.Telegram.WebApp) || {
  ready() {}, expand() {}, initData: "", initDataUnsafe: {},
  BackButton: null, LocationManager: null,
};
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
// Phase 164: the token is user-bound and lives 1 hour — the app
// refreshes it while open (refreshMediaToken) so long sessions
// keep their images.
let mediaToken = "";
function mediaUrl(id) {
  return "/media/" + encodeURIComponent(id || "") +
    (mediaToken ? "?mt=" + encodeURIComponent(mediaToken) : "");
}
let tab = "explore";
let feedCursor = null;
let profileId = null;
let profileCursor = null;
// Phase 199: Portfolio — the profile view has two tabs (Profile
// default, Portfolio when enabled); no new showView view, so the
// back button, nav and mascot behaviour are unchanged.
let profileTab = "profile";
let profileUser = null;

const $ = id => document.getElementById(id);

// Phase 20: while the admin acts as a managed user, every request
// carries the act-as header and the server resolves the caller to
// that managed member (admins only, managed targets only).
function actAsId() { return sessionStorage.getItem("nx_actas") || ""; }

async function api(path, options = {}) {
  // Phase 183 (audit M17): opt-in client timeout — pass
  // timeoutMs and the request aborts instead of hanging.
  // Only the assistant call uses it today; other calls keep
  // no timeout (uploads go through XHR).
  const { timeoutMs, ...rest } = options;
  const ctrl = timeoutMs ? new AbortController() : null;
  const timer = ctrl ? setTimeout(() => ctrl.abort(), timeoutMs) : null;
  let res;
  try {
    res = await fetch(path, {
      ...rest,
      ...(ctrl ? { signal: ctrl.signal } : {}),
      headers: { "X-Init-Data": initData, "Content-Type": "application/json",
                 ...(actAsId() ? { "X-Act-As": actAsId() } : {}),
                 ...(options.headers || {}) },
    });
  } finally {
    if (timer) clearTimeout(timer);
  }
  if (!res.ok) {
    // Phase 164: surface the server's message (the admin step-up
    // 401 tells the admin to reopen the app — "API 401" would not).
    let msg = "API " + res.status;
    try { const j = await res.json(); if (j.detail) msg = j.detail; }
    catch (e) { /* keep the generic message */ }
    // Phase 190: keep the status on the error — bootFailed tells
    // a dead server (5xx) from a refused login (401) by it, since
    // the message itself may be the server's detail text.
    const err = new Error(msg);
    err.status = res.status;
    throw err;
  }
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
  // Phase 146: leaving the profile view forgets the remembered
  // profile — only a reload while still on a profile restores it.
  if (name !== "profile") forgetProfile();
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
  // Phase 197: immersive game view — the game section goes
  // full-screen (a fixed overlay covering the page header +
  // bottom nav) and the mascot hides while a game is open;
  // leaving the view restores both.
  const _vg197 = $("view-game");
  if (_vg197) _vg197.classList.toggle("immersive", name === "game");
  if (document.body) document.body.classList.toggle("game-open", name === "game");
  // Phase 156: the mascot tips follow the page — reset on switch.
  if (typeof mascotOnView === "function") mascotOnView(name);
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
  ["feed", "videos", "designs", "search", "tasks", "leaderboard", "profile", "saved", "shared", "games", "game", "admin", "notifications", "messages", "chat", "assistant", "nearby", "qr", "trending", "settings", "blood", "skills", "museum"].forEach(v => {
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
  if (name !== "museum" && typeof stopMuseum === "function") stopMuseum();
  if (name === "tasks") loadTasks();
  if (name === "qr") loadMyQr();
  if (name === "saved") loadSaved();
  if (name === "shared") loadShared();
  if (name === "admin") loadAdmin();
  if (name === "notifications") loadNotifications(true);
  if (name === "settings") loadSettings();
  if (name === "messages") loadMessages();
  if (name !== "chat") stopChatPoll();
  if (name === "videos") { loadVideos(true); maybeShowAd(); }
  if (name === "leaderboard") loadRanks();
  if (name === "designs") loadDesigns(true);
  if (name === "trending") loadTrending();
  if (name === "blood") loadBlood();
  if (name === "skills") loadSkills();
  if (name === "assistant") openAssistant();
  if (name !== "assistant") nexaStop();
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
  else if (currentView === "museum" && !$("mu-sheet").hidden) closeMuseumSheet();
  else if (settingsDetailKey) renderSettingsHub();
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
// Phase 147 (owner): Nearby goes 3D — MapLibre GL JS (vendored)
// over the free OpenFreeMap "liberty" style, whose building-3d
// layer extrudes OSM buildings (no API key anywhere). Leaflet
// stays as the automatic 2D fallback: if MapLibre is missing,
// WebGL is unavailable, or the 3D style fails to load, the old
// 2D map is used instead and the map never goes blank. All
// people/route/toggle code below talks to the engine through
// the nb* adapter helpers and never touches L.* or
// maplibregl.* directly.
let nbML = null, nbMLMarkers = {}, nbMLMe = null, nbMLPopup = null;
let nbEngine = null;      // "3d" | "2d" once a map exists
let nb3DFailed = false;   // 3D tried and failed this session
let nb3DFailKind = null;   // Phase 148: "webgl" | "style" — why the last 3D attempt failed
let nbInitPromise = null; // in-flight engine initialisation
let nbModePref = null;    // "3d" | "2d" | null (auto)
try { nbModePref = localStorage.getItem("nx_nb_mode"); } catch (e) {}
if (nbModePref !== "3d" && nbModePref !== "2d") nbModePref = null;
const NB_3D_STYLE = "https://tiles.openfreemap.org/styles/liberty";
const NB_3D_PITCH = 60;

function nbCan3D() {
  if (nb3DFailed || nbModePref === "2d") return false;
  try {
    return typeof maplibregl !== "undefined" && maplibregl.supported();
  } catch (e) { return false; }
}

function nbMLEl(q) {
  const d = document.createElement("div");
  d.className = "nb-ml-pin";
  d.innerHTML = '<div class="nb-pin">' + nbAvaHTML(q, "nb-pin-img") + "</div>";
  return d;
}

function nbMLMeEl() {
  const d = document.createElement("div");
  d.className = "nb-ml-me";
  d.innerHTML = nbMePinHTML();
  return d;
}

function nbClosePopups() {
  if (nbEngine === "3d") {
    if (nbMLPopup) { try { nbMLPopup.remove(); } catch (e) {}
      nbMLPopup = null; }
  } else if (nbMap) nbMap.closePopup();
}

function nbWirePopupEl(el) {
  if (!el) return;
  const pb = el.querySelector("[data-nb-profile]");
  if (pb) pb.onclick = () => { nbClosePopups();
    openProfile(+pb.dataset.nbProfile); };
  const rb = el.querySelector("[data-nb-route]");
  if (rb) rb.onclick = () => {
    const m = nbMarkers[rb.dataset.nbRoute] ||
      nbMLMarkers[rb.dataset.nbRoute];
    if (m && m._nb) { nbClosePopups(); nbRoute(m._nb); }
  };
  // Phase 149: Street View — the popup's marker (or "me")
  // carries the point; the map popup closes first, then the
  // full-screen viewer opens over the map.
  const sv = el.querySelector("[data-nb-streetview]");
  if (sv) sv.onclick = () => {
    const id = sv.dataset.nbStreetview;
    let q = null;
    if (id === "me") {
      if (nbPos) q = { lat: nbPos.lat, lon: nbPos.lon, name: "You are here" };
    } else {
      const m = nbMarkers[id] || nbMLMarkers[id];
      if (m && m._nb) q = m._nb;
    }
    if (q) { nbClosePopups(); nbSVOpen(q.lat, q.lon, q.name || ""); }
  };
}

function nbGoTo(lat, lon, zoom) {
  if (nbEngine === "3d" && nbML)
    nbML.easeTo({ center: [lon, lat], zoom: zoom, duration: 500 });
  else if (nbMap) nbMap.setView([lat, lon], zoom);
}

function nbOpenPersonPopup(id) {
  if (nbEngine === "3d") {
    const m = nbMLMarkers[id];
    if (!m) return;
    const pop = m.getPopup();
    if (!pop) return;
    if (nbMLPopup && nbMLPopup !== pop) nbMLPopup.remove();
    nbMLPopup = pop;
    pop.addTo(nbML);
  } else {
    const m = nbMarkers[id];
    if (m) m.openPopup();
  }
}

function nbDrawRoute3D(pts) {
  const gj = { type: "Feature", geometry: { type: "LineString",
    coordinates: pts.map(p => [p[1], p[0]]) } };
  const src = nbML.getSource("nb-route");
  if (src) { src.setData(gj); return; }
  nbML.addSource("nb-route", { type: "geojson", data: gj });
  // Glowing green route, like the owner's reference: a wide soft
  // casing under a bright core line.
  nbML.addLayer({ id: "nb-route-glow", type: "line", source: "nb-route",
    paint: { "line-color": "#00E676", "line-width": 12,
      "line-opacity": 0.28, "line-blur": 3 } });
  nbML.addLayer({ id: "nb-route-core", type: "line", source: "nb-route",
    paint: { "line-color": "#00E676", "line-width": 5,
      "line-opacity": 0.95 } });
}

function nbClearRoute3D() {
  if (!nbML) return;
  ["nb-route-glow", "nb-route-core"].forEach(id => {
    if (nbML.getLayer(id)) nbML.removeLayer(id);
  });
  if (nbML.getSource("nb-route")) nbML.removeSource("nb-route");
}

function nbFitRoute3D(pts) {
  const b = new maplibregl.LngLatBounds();
  pts.forEach(p => b.extend([p[1], p[0]]));
  nbML.fitBounds(b, { padding: 30, duration: 500 });
}

function nbInit3D() {
  return new Promise(res => {
    let done = false;
    // Phase 148: the failure kind is recorded so the Nearby
    // view can say honestly why 3D is off (and offer a retry)
    // instead of failing silently.
    const fail = (kind) => {
      if (done) return;
      done = true; nb3DFailed = true;
      nb3DFailKind = kind || "style";
      try { if (nbML) nbML.remove(); } catch (e) {}
      nbML = null; res(false);
    };
    try {
      const map = new maplibregl.Map({
        container: "nearby-map",
        style: NB_3D_STYLE,
        center: [90.4125, 23.8103], zoom: 15,
        pitch: NB_3D_PITCH, maxPitch: 70, bearing: 0
      });
      nbML = map;
      const to = setTimeout(fail, 12000);
      map.once("load", () => {
        if (done) return;
        done = true; clearTimeout(to); nb3DFailKind = null;
        nbEngine = "3d"; res(true);
      });
      map.on("error", () => { if (!done) fail("style"); });
    } catch (e) { fail(/webgl/i.test(String((e && e.message) || e)) ? "webgl" : "style"); }
  });
}

function nbInit2D() {
  nbMap = L.map("nearby-map", { zoomControl: false });
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    { maxZoom: 19, attribution: "© OpenStreetMap" }).addTo(nbMap);
  nbMap.setView([23.8103, 90.4125], 13);
  nbMap.on("popupopen", e => nbWirePopupEl(e.popup.getElement()));
  nbEngine = "2d";
}

// Phase 148: one honest line under the map when 3D is off, so a
// missing 3D map never looks like a silent failure. The reason
// is computed live: a missing library (old shell / blocked
// script), no WebGL on this phone, or a style that failed to
// load. No note when the member chose 2D on purpose or when
// 3D is on.
const NB_3D_NOTES = {
  lib: "3D didn't start — the 3D library didn't load on this phone. The flat map is showing instead. Tap 🧊 Try 3D to try again.",
  webgl: "3D isn't available on this phone — it needs WebGL, which this phone doesn't offer. The flat map is showing instead.",
  style: "3D couldn't load its map in time — showing the flat map. Tap 🧊 Try 3D to try again."
};

function nb3DWhy() {
  if (nbModePref === "2d" || nbEngine === "3d") return null;
  if (typeof maplibregl === "undefined") return "lib";
  try {
    if (!maplibregl.supported()) return "webgl";
  } catch (e) { return "webgl"; }
  if (nb3DFailKind) return nb3DFailKind;
  if (nb3DFailed) return "style";
  return null;
}

function nbPaint3DNote() {
  const n = $("nearby-3d-note");
  if (!n) return;
  const why = nb3DWhy();
  n.hidden = !why;
  n.textContent = why ? NB_3D_NOTES[why] : "";
}

function nbPaintModeBtn() {
  const b = $("nearby-mode");
  if (!b) return;
  // Phase 148: the switch is ALWAYS visible. Hiding it when 3D
  // was unavailable failed silently — the owner saw no button
  // at all. When 3D is off it offers a retry instead.
  b.hidden = false;
  if (nbEngine === "3d") b.textContent = "🧊 3D view";
  else if (nb3DWhy()) b.textContent = "🧊 Try 3D";
  else b.textContent = "🗺 2D view";
}

function nbDestroyEngine() {
  nbClearRoute();
  if (nbEngine === "3d" && nbML) {
    try { nbML.remove(); } catch (e) {}
    nbML = null; nbMLMarkers = {}; nbMLMe = null; nbMLPopup = null;
  }
  if (nbEngine === "2d" && nbMap) {
    try { nbMap.remove(); } catch (e) {}
    nbMap = null; nbMarkers = {}; nbMeMarker = null; nbRouteLine = null;
  }
  nbEngine = null; nbInitPromise = null;
}

function nbEnsureMap() {
  if (nbEngine) {
    if (nbEngine === "3d" && nbML) nbML.resize();
    else if (nbMap) nbMap.invalidateSize();
    return Promise.resolve(true);
  }
  if (nbInitPromise) return nbInitPromise;
  nbInitPromise = (async () => {
    try {
      if (nbCan3D()) {
        if (await nbInit3D()) { nbPaintModeBtn(); nbPaint3DNote(); return true; }
      }
      if (typeof L === "undefined") {
        nbSetStatus("The map is still loading — reopen Nearby in a moment.");
        nbPaintModeBtn(); nbPaint3DNote();
        return false;
      }
      nbInit2D();
      nbPaintModeBtn(); nbPaint3DNote();
      return true;
    } finally { nbInitPromise = null; }
  })();
  return nbInitPromise;
}
// Phase 149 (owner): Nearby Street View via Mapillary (free).
// Tapping 📷 Street View in a member popup (or the "You are
// here" popup) opens a full-screen street-level viewer for
// the nearest Mapillary photo to that point. MapillaryJS
// v4.1.2 is vendored (webapp/vendor/mapillary/) like
// MapLibre — no CDN at runtime. The token is a free
// read-only CLIENT token from mapillary.com/dashboard/
// developers; it arrives from the server via /auth as
// me.mapillary_client_token (empty = not set up yet).
// MapillaryJS renders with WebGL — the owner's phone most
// likely fails WebGL (the Phase 147 3D diagnosis) — so when
// the interactive viewer cannot start, the nearest photo is
// shown as a plain image instead. Street View never fails
// silently: no token -> "not set up yet", no photo nearby
// -> "no photo here yet", viewer fails -> static photo +
// one honest line. Attribution is required (CC BY-SA 4.0):
// Phase 182 (audit M21/L18): lookup budget is 9 s total
// (radius, then bbox only with time left); 401/403 from a
// bad/revoked token shows an honest "couldn't load" line,
// not "no photo here"; fetches really abort on timeout.
// "© Mapillary contributors" + the photo's creator/date +
// a "View on Mapillary" link ride with every picture.
const NB_SV_GRAPH = "https://graph.mapillary.com/images";
const NB_SV_FIELDS = "id,computed_geometry,thumb_1024_url,thumb_512_url,captured_at,creator,is_pano";
let nbSVViewer = null;

function nbSVToken() {
  return (me && me.mapillary_client_token) || "";
}

function nbSVWebGL() {
  try {
    const c = document.createElement("canvas");
    return !!(c.getContext("webgl2") || c.getContext("webgl"));
  } catch (e) { return false; }
}

function nbSVCanInteractive() {
  try {
    return typeof mapillary !== "undefined" && !!mapillary.Viewer && nbSVWebGL();
  } catch (e) { return false; }
}

function nbSVPickNearest(lat, lon, imgs) {
  let best = null, bestD = Infinity;
  (imgs || []).forEach(im => {
    const g = im.computed_geometry || im.geometry;
    if (!g || !g.coordinates) return;
    const dLat = (g.coordinates[1] - lat) * 111320;
    const dLon = (g.coordinates[0] - lon) * 111320 * Math.cos(lat * Math.PI / 180);
    const d = dLat * dLat + dLon * dLon;
    if (d < bestD) { bestD = d; best = im; }
  });
  return best;
}

// Phase 182 (audit L18): the timeout ABORTS the fetch — the
// old Promise.race only stopped waiting while the request
// kept running in the background.
function nbFetchTimeout(url, ms) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), ms);
  return fetch(url, { signal: ctl.signal })
    .finally(() => clearTimeout(timer));
}

// Phase 182 (audit M21/L18): the lookup has ONE overall
// budget (NB_SV_LOOKUP_BUDGET_MS) — a radius attempt first
// (at most NB_SV_ATTEMPT_MS), then a bbox attempt only with
// whatever budget is left, so the no-imagery answer lands
// in ~9 s instead of ~16 s (two 8 s attempts). Returns the
// nearest image, null when the API answered OK with no
// imagery, {auth: true} on HTTP 401/403 (a bad/revoked
// token is a setup problem, not an empty map), or
// {error: true} when the lookup itself failed (timeout /
// network / other HTTP error). The 10 s viewer race in
// nbSVOpen is unchanged.
async function nbSVLookup(lat, lon) {
  // Lookup budget lives HERE (not at module scope) so the
  // Phase 149 node harness, which extracts this function
  // alone, still runs it.
  const NB_SV_LOOKUP_BUDGET_MS = 9000;
  const NB_SV_ATTEMPT_MS = 5000;
  const tok = nbSVToken();
  if (!tok) return null;
  const base = NB_SV_GRAPH + "?access_token=" + encodeURIComponent(tok) +
    "&fields=" + NB_SV_FIELDS;
  const deadline = Date.now() + NB_SV_LOOKUP_BUDGET_MS;
  const left = () => Math.max(0, deadline - Date.now());
  const get = async (url) => {
    const r = await nbFetchTimeout(
      url, Math.min(NB_SV_ATTEMPT_MS, left()));
    if (r.status === 401 || r.status === 403) return { auth: true };
    // Explicit `ok === false` only: a Response-like without ok
    // (the Phase 149 harness mock) must not read as an error;
    // real fetch always sets ok.
    if (r.ok === false) return { error: true };
    return r.json();
  };
  try {
    let j = await get(base + "&lat=" + lat + "&lng=" + lon +
      "&radius=50&limit=5");
    if (j && (j.auth || j.error)) return j;
    let imgs = (j && j.data) || [];
    if (!imgs.length && left() > 0) {
      // Radius search is capped at 50 m; widen to a small
      // bbox (0.003 deg square — far under the 0.01 deg API
      // limit) and take the nearest of those.
      const d = 0.0015;
      const bbox = [lon - d, lat - d, lon + d, lat + d].join(",");
      j = await get(base + "&bbox=" + bbox + "&limit=10");
      if (j && (j.auth || j.error)) return j;
      imgs = (j && j.data) || [];
    }
    return nbSVPickNearest(lat, lon, imgs);
  } catch (e) {
    // Timeout / network failure: not "no photo here" — the
    // lookup itself failed, so the caller shows the honest
    // line instead.
    return { error: true };
  }
}

function nbSVAttribution(img) {
  let by = "";
  const c = img && img.creator;
  if (typeof c === "string" && c) by = c;
  else if (c && typeof c === "object" && c.username) by = c.username;
  let date = "";
  if (img && img.captured_at) {
    try { date = new Date(img.captured_at).toISOString().slice(0, 10); } catch (e) {}
  }
  return {
    text: "© Mapillary contributors" + (by ? " · photo by " + by : "") +
      (date ? " · " + date : ""),
    link: "https://www.mapillary.com/app/?pKey=" + (img && img.id ? img.id : "")
  };
}

function nbSVShowNote(t) {
  const n = $("sv-note");
  if (!n) return;
  n.hidden = !t;
  n.textContent = t || "";
}

function nbSVHideNote() { nbSVShowNote(""); }

function nbSVShowStatic(img, why) {
  const box = $("sv-viewer");
  if (box) { box.hidden = true; box.innerHTML = ""; }
  const ph = $("sv-photo");
  if (ph) {
    ph.src = img.thumb_1024_url || img.thumb_512_url || "";
    ph.hidden = false;
  }
  nbSVShowNote(why || "");
}

async function nbSVOpen(lat, lon, label) {
  const ov = $("streetview");
  if (!ov) return;
  nbSVClose();
  ov.hidden = false;
  const t = $("sv-title");
  if (t) t.textContent = "Street View" + (label ? " — " + label : "");
  if (!nbSVToken()) {
    nbSVShowNote("Street View isn't set up yet — the Mapillary token is missing.");
    return;
  }
  nbSVShowNote("Looking for a street-level photo…");
  const img = await nbSVLookup(lat, lon);
  if (img && img.auth) {
    nbSVShowNote("Couldn't load Street View — access was refused. "
      + "The Mapillary token may be invalid or revoked.");
    return;
  }
  if (img && img.error) {
    nbSVShowNote("Couldn't load Street View right now — "
      + "check your connection and try again.");
    return;
  }
  if (!img) {
    nbSVShowNote("No street-level photo here yet.");
    return;
  }
  const att = nbSVAttribution(img);
  const cr = $("sv-credit");
  if (cr) cr.textContent = att.text;
  const lk = $("sv-mapillary-link");
  if (lk) lk.href = att.link;
  if (nbSVCanInteractive()) {
    let ok = false;
    try {
      const box = $("sv-viewer");
      box.hidden = false;
      const viewer = new mapillary.Viewer({
        accessToken: nbSVToken(), container: box,
        imageId: String(img.id), component: { cover: false }
      });
      nbSVViewer = viewer;
      ok = await Promise.race([
        viewer.moveTo(String(img.id)).then(() => true, () => false),
        new Promise(res => setTimeout(() => res(false), 10000))
      ]);
      if (!ok) { try { viewer.remove(); } catch (e) {} nbSVViewer = null; }
    } catch (e) {
      try { if (nbSVViewer) nbSVViewer.remove(); } catch (e2) {}
      nbSVViewer = null;
    }
    if (ok) { nbSVHideNote(); return; }
  }
  nbSVShowStatic(img, "Interactive view needs WebGL on this phone — showing the photo instead.");
}

function nbSVClose() {
  if (nbSVViewer) { try { nbSVViewer.remove(); } catch (e) {} nbSVViewer = null; }
  const box = $("sv-viewer");
  if (box) { box.hidden = true; box.innerHTML = ""; }
  const ph = $("sv-photo");
  if (ph) { ph.hidden = true; ph.src = ""; }
  nbSVHideNote();
  const ov = $("streetview");
  if (ov) ov.hidden = true;
}

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

function nbMePinHTML() {
  return '<div class="nb-me-pin"><svg viewBox="0 0 24 24" width="24" height="24" fill="#fff"><circle cx="12" cy="8" r="4.2"/><path d="M3.5 20.5c.8-4 4.2-6 8.5-6s7.7 2 8.5 6"/></svg></div>';
}
function nbMeIcon() {
  return L.divIcon({ className: "nb-wrap",
    html: nbMePinHTML(),
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
      '">🚶 Show route</button>' +
      '<button class="nb-pop-btn" data-nb-streetview="' + q.id +
      '">📷 Street View</button></div>';
    // Phase 147: markers live on the active engine (3D or 2D).
    if (nbEngine === "3d") {
      const ex = nbMLMarkers[q.id];
      if (ex) {
        ex.setLngLat([q.lon, q.lat]); ex._nb = q;
        if (ex.getPopup()) ex.getPopup().setHTML(popup);
      } else {
        const pop = new maplibregl.Popup({ offset: 30 })
          .setHTML(popup);
        const m = new maplibregl.Marker({ element: nbMLEl(q),
          anchor: "bottom", offset: [0, -8] })
          .setLngLat([q.lon, q.lat]).setPopup(pop).addTo(nbML);
        pop.on("open", () => {
          if (nbMLPopup && nbMLPopup !== pop) nbMLPopup.remove();
          nbMLPopup = pop;
          nbWirePopupEl(pop.getElement());
        });
        m._nb = q; nbMLMarkers[q.id] = m;
      }
    } else if (nbMarkers[q.id]) {
      nbMarkers[q.id].setLatLng([q.lat, q.lon]);
      nbMarkers[q.id].setPopupContent(popup);
      nbMarkers[q.id]._nb = q;
    } else {
      const m = L.marker([q.lat, q.lon],
        { icon: nbBubbleIcon(q) }).addTo(nbMap);
      m.bindPopup(popup); m._nb = q; nbMarkers[q.id] = m;
    }
  });
  // Phase 147: drop stale markers on both engines.
  Object.keys(nbMarkers).forEach(id => {
    if (!seen[id]) { if (nbMap) nbMap.removeLayer(nbMarkers[id]); delete nbMarkers[id]; }
  });
  Object.keys(nbMLMarkers).forEach(id => {
    if (!seen[id]) { nbMLMarkers[id].remove(); delete nbMLMarkers[id]; }
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
      '<span class="nb-row-main"><b class="vname"><span class="vname-text">' + nbEsc(q.name) +
      '</span>' + (q.verified ? '<span class="verified">✔</span>' : "") +
      '</b><span class="muted">' +
      (q.username ? "@" + nbEsc(q.username) + "  ·  " : "") +
      nbDir(q.bearing) + "  ·  " + q.distance_m + " m</span></span>" +
      '<button class="nb-route-btn">Route</button>';
    // Phase 147: list rows pan the live engine.
    row.onclick = () => { nbGoTo(q.lat, q.lon, 17);
      nbOpenPersonPopup(q.id); };
    row.querySelector(".nb-route-btn").onclick = e => {
      e.stopPropagation();
      if (nbMarkers[q.id]) nbRoute(nbMarkers[q.id]._nb);
    };
    list.append(row);
  });
  fitVerifiedNames(list);
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
    // Phase 147: story circles pan the live engine.
    b.onclick = () => { nbGoTo(q.lat, q.lon, 17);
      nbOpenPersonPopup(q.id); };
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
    // Phase 147: the 'You are here' pin lives on the live engine.
    if (nbEngine === "3d" && nbML) {
      if (!nbMLMe) {
        nbMLMe = new maplibregl.Marker({ element: nbMLMeEl(),
          anchor: "center" }).setLngLat([pos.lon, pos.lat])
          .addTo(nbML);
        nbMLMe.setPopup(new maplibregl.Popup({ offset: 20 })
          .setHTML("<b>You are here</b><br><button class=\"nb-pop-btn\" data-nb-streetview=\"me\">📷 Street View</button>"));
        nbMLMe.getPopup().on("open", () => nbWirePopupEl(nbMLMe.getPopup().getElement()));
        nbML.easeTo({ center: [pos.lon, pos.lat], zoom: 16,
          duration: 600 });
      } else nbMLMe.setLngLat([pos.lon, pos.lat]);
    } else if (nbMap) {
      if (!nbMeMarker) {
        nbMeMarker = L.marker([pos.lat, pos.lon],
          { icon: nbMeIcon() }).addTo(nbMap);
        nbMeMarker.bindPopup("<b>You are here</b><br><button class=\"nb-pop-btn\" data-nb-streetview=\"me\">📷 Street View</button>");
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
  if (!nbPos || (!nbMap && !nbML)) return;
  nbTarget = q.id;
  // Phase 182 (audit L17): the FOOT profile — the URL used
  // to say driving on the routed-foot service while the label
  // says "Walking route" and the PRD says foot routing.
  const url = "https://routing.openstreetmap.de/routed-foot/route/v1/" +
    "foot/" + nbPos.lon + "," + nbPos.lat + ";" + q.lon + "," +
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
  // Phase 147: the route is a glowing green line in 3D.
  if (nbEngine === "3d" && nbML) {
    nbDrawRoute3D(pts);
    if (!silent) nbFitRoute3D(pts);
  } else {
    if (nbRouteLine) nbMap.removeLayer(nbRouteLine);
    nbRouteLine = L.polyline(pts, { color: "#3E8FD0", weight: 5,
      opacity: .9, dashArray: dur === null ? "2 8" : null }).addTo(nbMap);
    if (!silent) nbMap.fitBounds(nbRouteLine.getBounds(),
      { padding: [30, 30] });
  }
  const bar = $("nearby-route");
  bar.hidden = false;
  bar.innerHTML = "🚶 Walking route to <b>" + nbEsc(q.name) + "</b>: " +
    dist + " m" + (dur ? " · about " + dur + " min" : "") +
    ' <button class="nb-route-x" id="nb-route-x">✕ Clear</button>';
  $("nb-route-x").onclick = nbClearRoute;
}

function nbClearRoute() {
  nbTarget = null;
  if (nbEngine === "3d") nbClearRoute3D();
  if (nbRouteLine && nbMap) nbMap.removeLayer(nbRouteLine);
  nbRouteLine = null;
  $("nearby-route").hidden = true;
}

async function openNearby() {
  // Phase 147: the map engine (3D first, 2D fallback) is ready
  // before any people or route is painted, so a slow 3D style
  // load can never paint markers onto a missing map.
  const ok = await nbEnsureMap();
  if (!ok) return;
  setTimeout(() => {
    if (nbEngine === "3d" && nbML) nbML.resize();
    else if (nbMap) nbMap.invalidateSize();
  }, 60);
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
    // Phase 147: turning sharing off clears 3D markers too.
    Object.keys(nbMarkers).forEach(id => {
      if (nbMap) nbMap.removeLayer(nbMarkers[id]);
      delete nbMarkers[id];
    });
    Object.keys(nbMLMarkers).forEach(id => {
      nbMLMarkers[id].remove(); delete nbMLMarkers[id];
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

// Phase 147: let the member switch between the 3D map and the
// flat 2D map (e.g. a slow phone). The choice is remembered
// on the device; switching rebuilds the map and repaints
// people and the route from the next refresh.
$("nearby-mode").onclick = async () => {
  if (!nbEngine) return;
  const want3D = nbEngine !== "3d";
  nbModePref = want3D ? "3d" : "2d";
  if (want3D) { nb3DFailed = false; nb3DFailKind = null; }
  try { localStorage.setItem("nx_nb_mode", nbModePref); } catch (e) {}
  nbDestroyEngine();
  if (await nbEnsureMap()) nbRefresh();
};

// Phase 149: Street View close button (the overlay is a plain
// fixed div — closing it returns to the map exactly as it was).
const svCloseBtn = $("sv-close");
if (svCloseBtn) svCloseBtn.onclick = nbSVClose;


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

// Phase 160: ONE shared verified-name fit for the whole app
// (owner: "সবখানেই এই নিয়ম এপ্লাই করো"). Every name + tick
// renders as a .vname line with a .vname-text span; this one
// function shrinks the text until title + tick fit the line.
// It starts at the name's normal size, steps down 0.5px at a
// time while truncated, and never goes below the 12px floor
// (at the floor the text ellipsizes — the tick is never
// shrunk, wrapped or hidden). Re-fit after fonts load and
// whenever the viewport changes, so a resize/rotation re-grows
// names that fit again.
const VNAME_FLOOR = 12;
function fitVerifiedNames(root) {
  const scope = root || document;
  scope.querySelectorAll(".vname-text").forEach(text => {
    text.style.fontSize = "";
    const base = parseFloat(getComputedStyle(text).fontSize) || 16;
    let size = base;
    while (size > VNAME_FLOOR &&
           text.scrollWidth > text.clientWidth) {
      size -= 0.5;
      text.style.fontSize = size + "px";
    }
    if (size >= base) text.style.fontSize = "";
  });
}
// Card/row builders schedule their fit for the next frame,
// when the element is attached and laid out.
function fitVerifiedNamesSoon(el) {
  requestAnimationFrame(() => fitVerifiedNames(el || document));
}
let vnameFitTimer = null;
window.addEventListener("resize", () => {
  clearTimeout(vnameFitTimer);
  vnameFitTimer = setTimeout(() => fitVerifiedNames(), 150);
});
if (document.fonts && document.fonts.ready) {
  document.fonts.ready.then(() => fitVerifiedNames());
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
// Phase 171: the viewer now swipes through an album — pass the
// item list + index. The Phase 112 open lines stay verbatim (the
// first photo is already showing); the list only adds ‹ › swipe.
let pvList = null, pvIdx = 0;
function openPhotoViewer(photoId, name, list, index) {
  $("pv-img").src = mediaUrl(photoId);
  $("pv-img").alt = name || "Profile photo";
  $("pv-name").textContent = name || "";
  pvList = (list && list.length > 1) ? list : null;
  pvIdx = index || 0;
  $("pv-count").textContent = pvList ? (pvIdx + 1) + "/" + pvList.length : "";
  $("pv-prev").hidden = !pvList;
  $("pv-next").hidden = !pvList;
  $("photo-viewer").hidden = false;
  updateBackButton();
}
function paintPhotoViewer(name) {
  const it = pvList ? pvList[pvIdx] : null;
  if (!it) return;
  $("pv-img").src = mediaUrl(it.file_id);
  $("pv-img").alt = name || "Photo";
  $("pv-name").textContent = name || "";
  $("pv-count").textContent = (pvIdx + 1) + "/" + pvList.length;
}
function stepPhotoViewer(d) {
  if (!pvList) return;
  pvIdx = (pvIdx + d + pvList.length) % pvList.length;
  paintPhotoViewer();
}
function closePhotoViewer() {
  const v = $("photo-viewer");
  if (v.hidden) return;
  v.hidden = true;
  $("pv-img").src = "";
  pvList = null;
  updateBackButton();
}
$("photo-viewer").onclick = () => closePhotoViewer();
$("pv-close").onclick = e => { e.stopPropagation(); closePhotoViewer(); };
$("pv-prev").onclick = e => { e.stopPropagation(); stepPhotoViewer(-1); };
$("pv-next").onclick = e => { e.stopPropagation(); stepPhotoViewer(1); };

// ---------------------------------------------------------------- posts ---
// -------------------------------------------------------- phase 123 --
// A poll rides under the caption — tappable options with live
// percentage bars. Before voting the options are buttons; after
// voting the results stay, the member's own choice is marked,
// and the rows stop being clickable (a vote is final).
function pollBlock(p) {
  const box = document.createElement("div");
  box.className = "poll-block";
  const q = document.createElement("div");
  q.className = "poll-q";
  q.textContent = "📊 " + p.poll.question;
  const paint = () => {
    box.innerHTML = "";
    box.appendChild(q);
    const total = p.poll.total_votes || 0;
    p.poll.options.forEach(o => {
      const pct = total ? Math.round(o.votes * 100 / total) : 0;
      const rowEl = document.createElement("button");
      rowEl.className = "poll-opt" +
        (p.poll.voted_option_id === o.id ? " voted" : "");
      rowEl.type = "button";
      const fill = document.createElement("span");
      fill.className = "poll-fill";
      fill.style.width = pct + "%";
      const label = document.createElement("span");
      label.className = "poll-label";
      label.textContent = o.text;
      const num = document.createElement("span");
      num.className = "poll-num";
      num.textContent = (p.poll.voted_option_id != null
        ? pct + "% · " + o.votes
        : o.votes + (o.votes === 1 ? " vote" : " votes"));
      rowEl.append(fill, label, num);
      if (p.poll.voted_option_id == null) {
        rowEl.onclick = async () => {
          try {
            const r = await api("/posts/" + p.id + "/poll/vote",
              { method: "POST",
                body: JSON.stringify({ option_id: o.id }) });
            p.poll = r;
            paint();
          } catch (e) { setStatus("Could not vote."); }
        };
      } else rowEl.disabled = true;
      box.appendChild(rowEl);
    });
    const foot = document.createElement("div");
    foot.className = "poll-foot";
    foot.textContent = total + (total === 1 ? " vote" : " votes") +
      (p.poll.voted_option_id != null ? " · You voted ✓" : "");
    box.appendChild(foot);
  };
  paint();
  return box;
}

// Phase 170: @mentions — render a caption/comment with tappable
// mention links. Only usernames the server resolved (mentions)
// become links; unknown names stay plain text. The text is
// escaped by construction (text nodes only, never innerHTML).
function renderRichText(el, text, mentions) {
  el.innerHTML = "";
  const list = (mentions || []).filter(m => m && m.username);
  if (!text) return;
  if (!list.length) { el.textContent = text; return; }
  const byName = {};
  list.forEach(m => { byName[m.username.toLowerCase()] = m; });
  const re = /(^|[^\w@])@([A-Za-z0-9_]{3,32})/g;
  let last = 0, m;
  while ((m = re.exec(text))) {
    const hit = byName[m[2].toLowerCase()];
    if (!hit) continue;
    const at = m.index + m[1].length;
    if (at > last) el.appendChild(document.createTextNode(text.slice(last, at)));
    const a = document.createElement("a");
    a.className = "mention";
    a.href = "javascript:void(0)";
    a.textContent = "@" + m[2];
    a.onclick = (e) => { e.stopPropagation(); openProfile(hit.telegram_id); };
    el.appendChild(a);
    last = at + 1 + m[2].length;
  }
  if (last < text.length) el.appendChild(document.createTextNode(text.slice(last)));
}

// Phase 170: @ autocomplete — type @ + a prefix in the composer
// or a comment box and pick a member from the dropdown (uses the
// existing GET /search). Tap inserts "@username ".
function attachMentionAutocomplete(ta) {
  if (!ta || ta._mentionWired) return;
  ta._mentionWired = true;
  let drop = null, timer = null;
  const close = () => { if (drop) { drop.remove(); drop = null; } };
  ta.addEventListener("input", () => {
    clearTimeout(timer);
    const pos = ta.selectionStart;
    const before = ta.value.slice(0, pos == null ? 0 : pos);
    const m = /@([A-Za-z0-9_]{1,32})$/.exec(before);
    if (!m) { close(); return; }
    timer = setTimeout(async () => {
      try {
        const d = await api("/search?q=" + encodeURIComponent(m[1]));
        const users = (d.users || []).filter(u => u.username).slice(0, 5);
        close();
        if (!users.length) return;
        drop = document.createElement("div");
        drop.className = "mention-drop";
        users.forEach(u => {
          const b = document.createElement("button");
          b.type = "button";
          b.textContent = "@" + u.username + (u.first_name ? " — " + u.first_name : "");
          b.addEventListener("mousedown", (e) => {
            e.preventDefault();
            const start = pos - m[1].length - 1;
            ta.value = ta.value.slice(0, start) + "@" + u.username + " " + ta.value.slice(pos);
            ta.focus();
            ta.selectionStart = ta.selectionEnd = start + u.username.length + 2;
            close();
          });
          drop.appendChild(b);
        });
        const r = ta.getBoundingClientRect();
        drop.style.left = Math.max(8, r.left) + "px";
        drop.style.top = (r.bottom + 4) + "px";
        document.body.appendChild(drop);
      } catch (e) { close(); }
    }, 200);
  });
  ta.addEventListener("blur", () => setTimeout(close, 250));
}
attachMentionAutocomplete($("composer-text"));

// Phase 171: albums — one photo renders exactly as before;
// 2-10 photos render as a swipeable carousel (dots + counter).
function albumItems(p) {
  if (p.media && p.media.length) {
    return p.media.slice().sort((a, b) => (a.position || 0) - (b.position || 0));
  }
  if (p.media_file_id) return [{ file_id: p.media_file_id, media_type: p.type, position: 0 }];
  return [];
}
function albumFrame(p) {
  const items = albumItems(p);
  const frame = document.createElement("div");
  frame.className = "post-media";
  if (items.length <= 1) {
    const img = document.createElement("img");
    img.src = mediaUrl(items[0].file_id);
    img.loading = "lazy";
    img.alt = "photo";
    img.onclick = () => openPhotoViewer(items[0].file_id, "", items, 0);
    frame.appendChild(img);
    return frame;
  }
  const track = document.createElement("div");
  track.className = "carousel-track";
  items.forEach((it, i) => {
    const img = document.createElement("img");
    img.src = mediaUrl(it.file_id);
    img.loading = "lazy";
    img.alt = "photo " + (i + 1);
    img.onclick = () => openPhotoViewer(it.file_id, "", items, i);
    track.appendChild(img);
  });
  frame.appendChild(track);
  const dots = document.createElement("div");
  dots.className = "carousel-dots";
  const count = document.createElement("div");
  count.className = "carousel-count";
  let idx = 0;
  const paint = () => {
    track.style.transform = "translateX(-" + (idx * 100) + "%)";
    count.textContent = (idx + 1) + "/" + items.length;
    [...dots.children].forEach((d, i) => d.classList.toggle("on", i === idx));
  };
  items.forEach((_, i) => {
    const d = document.createElement("button");
    d.className = "carousel-dot";
    d.onclick = (e) => { e.stopPropagation(); idx = i; paint(); };
    dots.appendChild(d);
  });
  const prev = document.createElement("button");
  prev.className = "carousel-arrow left";
  prev.textContent = "‹";
  prev.onclick = (e) => { e.stopPropagation(); idx = (idx - 1 + items.length) % items.length; paint(); };
  const next = document.createElement("button");
  next.className = "carousel-arrow right";
  next.textContent = "›";
  next.onclick = (e) => { e.stopPropagation(); idx = (idx + 1) % items.length; paint(); };
  frame.append(prev, next, dots, count);
  let sx = null;
  track.addEventListener("touchstart", (e) => { sx = e.touches[0].clientX; }, { passive: true });
  track.addEventListener("touchend", (e) => {
    if (sx == null) return;
    const dx = e.changedTouches[0].clientX - sx;
    if (Math.abs(dx) > 40) idx = (idx + (dx < 0 ? 1 : -1) + items.length) % items.length;
    sx = null; paint();
  }, { passive: true });
  paint();
  return frame;
}

function postCard(p) {
  const el = document.createElement("article");
  el.className = "post";

  const head = document.createElement("button");
  head.className = "post-top";
  const who = document.createElement("span");
  who.className = "post-who";
  const nm = document.createElement("span");
  nm.className = "post-name vname";
  const nmText = document.createElement("span");
  nmText.className = "vname-text";
  nmText.textContent = p.author_name;
  nm.appendChild(nmText);
  if (p.author_verified) nm.appendChild(verifiedBadge());
  const sub = document.createElement("span");
  sub.className = "post-sub";
  sub.textContent = p.author_username ? "@" + p.author_username : "";
  who.append(nm, sub);
  head.append(avatarEl(p.author_name, p.author_id, false, p.author_photo), who);
  head.onclick = () => openProfile(p.author_id);
  // Phase 118: a repost card says who shared it, on top.
  if (p.reposted) {
    const rp = document.createElement("button");
    rp.className = "repost-banner";
    rp.textContent = "🔁 " + p.reposted_by_name + " reposted";
    rp.onclick = () => openProfile(p.reposted_by_id);
    el.appendChild(rp);
  }
  el.appendChild(head);
  // Phase 123: a pinned post wears its badge on every card.
  if (p.is_pinned) {
    const pin = document.createElement("div");
    pin.className = "pin-badge";
    pin.textContent = "📌 Pinned";
    el.appendChild(pin);
  }

  if (p.media_file_id && p.type === "photo") {
    // Phase 171: albums render through albumFrame (one photo
    // exactly as before; 2-10 as a swipeable carousel).
    el.appendChild(albumFrame(p));
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
    renderRichText(body, p.caption, p.mentions);
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

  // Phase 123: a poll rides under the caption.
  if (p.poll) el.appendChild(pollBlock(p));

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
  cBtn.className = "cmt-btn";
  cBtn.textContent = "💬 " + p.comment_count;
  actions.appendChild(cBtn);

  // Phase 118: repost — share a post to your own feed (toggle).
  const rpBtn = document.createElement("button");
  const paintRepost = () => {
    rpBtn.textContent = "🔁 " + (p.repost_count || 0);
    rpBtn.classList.toggle("reposted", !!p.reposted_by_me);
  };
  paintRepost();
  rpBtn.onclick = async () => {
    try {
      const r = await api("/posts/" + p.id + "/repost", { method: "POST" });
      p.reposted_by_me = r.reposted;
      p.repost_count = r.repost_count;
      paintRepost();
      if (!r.reposted && p.reposted &&
          p.reposted_by_id === (me && me.telegram_id)) el.remove();
      setStatus(r.reposted ? "Reposted to your feed."
                           : "Repost removed.");
    } catch (e) { setStatus("Could not repost."); }
  };
  actions.appendChild(rpBtn);

  // Phase 133: Stars tip — not on your own posts.
  if (!me || p.author_id !== me.telegram_id) {
    const tipBtn = document.createElement("button");
    tipBtn.className = "tip-btn";
    tipBtn.textContent = "⭐ Tip";
    tipBtn.onclick = () => openTipSheet({
      postId: p.id, name: p.author_name });
    actions.appendChild(tipBtn);
  }

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
  // Phase 118: replying to a comment — tap Reply under it,
  // the chip shows who you answer, Send posts it nested.
  let replyTarget = null;
  const replyChip = document.createElement("div");
  replyChip.className = "reply-chip";
  replyChip.hidden = true;
  const paintReplyChip = () => {
    if (replyTarget) {
      replyChip.hidden = false;
      replyChip.textContent = "Replying to " + replyTarget.author_name + "  ✕";
    } else replyChip.hidden = true;
  };
  replyChip.onclick = () => { replyTarget = null; paintReplyChip(); };
  const cForm = document.createElement("div");
  cForm.className = "comment-form";
  const cInput = document.createElement("input");
  cInput.type = "text";
  cInput.placeholder = "Write a comment…";
  cInput.maxLength = 500;
  attachMentionAutocomplete(cInput);
  const cSend = document.createElement("button");
  cSend.textContent = "Send";
  cForm.append(cInput, cSend);
  const onReply = (cm) => {
    replyTarget = cm;
    paintReplyChip();
    cInput.focus();
  };
  cBox.append(replyChip, cList, cForm);
  el.appendChild(cBox);

  let commentsLoaded = false;
  cBtn.onclick = async () => {
    cBox.hidden = !cBox.hidden;
    if (!cBox.hidden && !commentsLoaded) {
      commentsLoaded = true;
      try {
        const data = await api("/posts/" + p.id + "/comments");
        data.comments.forEach(cm => cList.appendChild(commentRow(cm, onReply)));
      } catch (e) { setStatus("Could not load comments."); }
    }
  };
  cSend.onclick = async () => {
    const text = cInput.value.trim();
    if (!text) return;
    const body = { text };
    if (replyTarget) body.parent_id = replyTarget.id;
    try {
      const cm = await api("/posts/" + p.id + "/comments", {
        method: "POST", body: JSON.stringify(body) });
      if (replyTarget) {
        const parentRow = cList.querySelector(
          '[data-comment-id="' + replyTarget.id + '"]');
        if (parentRow && parentRow._repliesBox)
          parentRow._repliesBox.appendChild(commentRow(cm, onReply));
        else cList.appendChild(commentRow(cm, onReply));
      } else cList.appendChild(commentRow(cm, onReply));
      cInput.value = "";
      replyTarget = null;
      paintReplyChip();
      p.comment_count += 1;
      cBtn.textContent = "💬 " + p.comment_count;
    } catch (e) { setStatus("Could not send the comment."); }
  };
  fitVerifiedNamesSoon(el);
  return el;
}

function commentRow(cm, onReply) {
  const row = document.createElement("div");
  row.className = "comment";
  row.dataset.commentId = cm.id;
  row.appendChild(avatarEl(cm.author_name, cm.user_id, false, cm.author_photo));
  const who = document.createElement("b");
  who.className = "vname-text";
  who.textContent = cm.author_name;
  const nm = document.createElement("span");
  nm.className = "vname";
  nm.appendChild(who);
  if (cm.author_verified) nm.appendChild(verifiedBadge());
  row.appendChild(nm);
  row.appendChild(document.createTextNode(": "));
  const cmText = document.createElement("span");
  renderRichText(cmText, cm.text, cm.mentions);
  row.appendChild(cmText);
  // Phase 118: answer a comment directly — the reply nests
  // under it instead of starting a new top-level comment.
  if (onReply) {
    const rb = document.createElement("button");
    rb.className = "comment-reply-btn";
    rb.textContent = "Reply";
    rb.onclick = () => onReply(cm);
    row.appendChild(rb);
  }
  // Phase 123: a small heart on every comment — the count
  // rides on the row, in the feed and in reels alike.
  const lb = document.createElement("button");
  lb.className = "comment-like-btn";
  const paintCl = () => {
    lb.textContent = (cm.liked_by_me ? "❤️ " : "♡ ") +
      (cm.like_count || 0);
    lb.classList.toggle("liked", !!cm.liked_by_me);
  };
  paintCl();
  lb.onclick = async () => {
    try {
      const r = await api("/posts/" + cm.post_id + "/comments/" +
        cm.id + "/like", { method: "POST" });
      cm.liked_by_me = r.liked;
      cm.like_count = r.like_count;
      paintCl();
    } catch (e) { setStatus("Could not like the comment."); }
  };
  row.appendChild(lb);
  const replies = document.createElement("div");
  replies.className = "comment-replies";
  (cm.replies || []).forEach(r => replies.appendChild(commentRow(r, onReply)));
  row.appendChild(replies);
  row._repliesBox = replies;
  fitVerifiedNamesSoon(row);
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
    // Phase 140: the Hashtags tab reads the followed-hashtag
    // feed instead of the Explore/Following tabs.
    const url = tab === "hashtags"
      ? "/feed/hashtags" + (reset || !feedCursor ? "" : "?cursor=" + feedCursor)
      : "/feed?tab=" + tab + (reset || !feedCursor ? "" : "&cursor=" + feedCursor);
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
    if (tab === "hashtags") {
      $("feed-empty").textContent = "Follow a hashtag to see its " +
        "posts here — tap any #tag to follow it.";
    } else {
      $("feed-empty").textContent = "No posts yet. Be the first to post!";
    }
    fitVerifiedNames($("feed-list"));
  } catch (e) { setStatus("Could not load the feed."); }
}

// ------------------------------------------------------------- trending ---
// Phase 122: what is hot right now. Hashtag chips on top (tap
// one to see every post with that tag, via the existing search
// flow), ranked posts below. Each card is the normal postCard()
// — likes, comments, repost, save and share all work exactly
// as in the feed — wrapped with a rank line that says WHY it
// ranks: its engagement in the last 24 hours, or its 7-day
// total when nothing happened in the last day.
async function loadTrending() {
  const list = $("trend-list");
  const tagsBox = $("trend-tags");
  const empty = $("trend-empty");
  if (!list) return;
  try {
    const [posts, tags] = await Promise.all([
      api("/trending/posts"),
      api("/trending/hashtags"),
    ]);
    tagsBox.innerHTML = "";
    (tags.hashtags || []).forEach(h => {
      const chip = document.createElement("button");
      chip.className = "chip trend-tag";
      chip.textContent = "#" + h.tag + " · " + h.count;
      chip.onclick = () => searchTag(h.tag);
      tagsBox.appendChild(chip);
    });
    list.innerHTML = "";
    (posts.posts || []).forEach((p, i) => {
      const wrap = document.createElement("div");
      wrap.className = "trend-item";
      const rank = document.createElement("div");
      rank.className = "trend-rank";
      const hot = (p.trend_24h || 0) > 0
        ? "🔥 " + p.trend_24h + " in 24h"
        : "🔥 " + (p.trend_7d || 0) + " this week";
      rank.textContent = "#" + (i + 1) + " · " + hot;
      wrap.append(rank, postCard(p));
      list.appendChild(wrap);
    });
    empty.hidden = (posts.posts || []).length > 0;
    fitVerifiedNames(list);
  } catch (e) { setStatus("Could not load Trending."); }
}


// ---------- Phase 151: blood donors ----------
const BLOOD_GROUPS = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"];
let bloodTab = "donors";
let bloodGroupFilter = "";

function bloodGroupBadge(group) {
  const b = document.createElement("span");
  b.className = "blood-group-badge";
  b.textContent = "🩸 " + group;
  return b;
}

// Phase 152: donor distance — under 1 km in metres, else km with
// one decimal. Null/undefined means nobody shares location.
function bloodDistance(d) {
  if (d == null) return "";
  if (d < 1) return Math.round(d * 1000) + " m away";
  return d.toFixed(1) + " km away";
}

// Phase 153: ask for location when the Blood page opens, so donor
// distances can show. At most once per app session (bloodLocAsked
// is in-memory: a reload starts a new session). A denial — or an
// unavailable location — shows an inline hint with a retry button
// instead of nagging. Reuses nbLocate() and POST /me/location;
// Nearby's own toggle, timer and map behaviour are untouched.
let bloodLocAsked = false;

async function bloodMaybeAskLocation() {
  if (bloodLocAsked) return;
  bloodLocAsked = true;
  const hint = $("blood-loc-hint");
  let sharing = false;
  try { sharing = !!(await api("/me/nearby")).sharing; } catch (e) {}
  if (sharing) { if (hint) hint.hidden = true; return; }
  const pos = await nbLocate();
  if (!pos) { if (hint) hint.hidden = false; return; }
  try {
    const r = await api("/me/location", { method: "POST",
      body: JSON.stringify({ lat: pos.lat, lon: pos.lon, share: true }) });
    if (r && r.sharing) {
      if (hint) hint.hidden = true;
      nbSharing = true;
      if (bloodTab === "donors") loadBloodDonors(); else loadBloodRequests();
    } else if (hint) hint.hidden = false;
  } catch (e) { if (hint) hint.hidden = false; }
}

// Phase 153: the hint's retry button — user-initiated, so it is
// NOT gated by the once-per-session flag.
async function bloodRetryLocation() {
  const hint = $("blood-loc-hint");
  const pos = await nbLocate();
  if (!pos) return;
  try {
    const r = await api("/me/location", { method: "POST",
      body: JSON.stringify({ lat: pos.lat, lon: pos.lon, share: true }) });
    if (r && r.sharing) {
      if (hint) hint.hidden = true;
      nbSharing = true;
      if (bloodTab === "donors") loadBloodDonors(); else loadBloodRequests();
    }
  } catch (e) {}
}

async function loadBlood() {
  const dTab = $("blood-tab-donors");
  const rTab = $("blood-tab-requests");
  if (!dTab) return;
  // Phase 153: location permission for donor distances — once
  // per session, only when sharing is off; a denial shows the
  // inline hint with a retry button instead of re-prompting.
  bloodMaybeAskLocation();
  $("blood-loc-on").onclick = () => bloodRetryLocation();
  // Tabs + new-request form (bound every open; .onclick replaces).
  dTab.onclick = () => { bloodTab = "donors"; loadBlood(); };
  rTab.onclick = () => { bloodTab = "requests"; loadBlood(); };
  const form = $("blood-form");
  $("blood-new-btn").onclick = () => { form.hidden = !form.hidden; };
  const gsel = $("blood-form-group");
  if (!gsel.options.length) BLOOD_GROUPS.forEach(g => {
    const o = document.createElement("option");
    o.value = g; o.textContent = g; gsel.appendChild(o);
  });
  $("blood-form-send").onclick = async () => {
    const units = parseInt($("blood-form-units").value, 10);
    try {
      await api("/blood/requests", { method: "POST",
        body: JSON.stringify({ blood_group: gsel.value,
          hospital: $("blood-form-hospital").value,
          city: $("blood-form-city").value,
          units: isNaN(units) ? 1 : units,
          note: $("blood-form-note").value,
          contact: $("blood-form-contact").value }) });
      form.hidden = true;
      $("blood-form-hospital").value = "";
      $("blood-form-city").value = "";
      $("blood-form-note").value = "";
      $("blood-form-contact").value = "";
      setStatus("Blood request posted — matching donors have been notified. 🩸");
      loadBloodRequests();
    } catch (e) { setStatus("Could not post the request — check the hospital, city and units."); }
  };
  dTab.classList.toggle("active", bloodTab === "donors");
  rTab.classList.toggle("active", bloodTab === "requests");
  $("blood-donor-filters").hidden = bloodTab !== "donors";
  $("blood-donor-list").hidden = bloodTab !== "donors";
  $("blood-request-pane").hidden = bloodTab !== "requests";
  if (bloodTab === "donors") loadBloodDonors();
  else loadBloodRequests();
}

async function loadBloodDonors() {
  const box = $("blood-donor-list");
  const filters = $("blood-donor-filters");
  const empty = $("blood-empty");
  if (!box) return;
  filters.innerHTML = "";
  const mkChip = (label, val) => {
    const c = document.createElement("button");
    c.className = "chip" + (bloodGroupFilter === val ? " active" : "");
    c.textContent = label;
    c.onclick = () => { bloodGroupFilter = val; loadBloodDonors(); };
    filters.appendChild(c);
  };
  mkChip("All groups", "");
  BLOOD_GROUPS.forEach(g => mkChip(g, g));
  box.innerHTML = "Loading…";
  empty.hidden = true;
  try {
    const d = await api("/blood/donors" +
      (bloodGroupFilter ? "?group=" + encodeURIComponent(bloodGroupFilter) : ""));
    box.innerHTML = "";
    (d.donors || []).forEach(u => {
      // Phase 152: two-row card — top row avatar + full name on
      // ONE line + group badge; bottom row country (+ distance)
      // + Message. No username anywhere on donor cards.
      const card = document.createElement("div");
      card.className = "card blood-card blood-donor-card";
      const top = document.createElement("div");
      top.className = "blood-top";
      // Phase 154: the real profile photo — avatarEl falls back
      // to initials when photo_file_id is null (member has no photo).
      const av = avatarEl(u.first_name, u.telegram_id, false, u.photo_file_id);
      const info = document.createElement("div");
      info.className = "blood-info";
      // Phase 163 (owner): verified donors show the blue tick
      // on the card, on the shared .vname line — long names
      // shrink (floor 12px) and the tick hugs the name, exactly
      // as everywhere else (Phases 160/162).
      const nm = document.createElement("div");
      nm.className = "blood-name vname";
      const nmText = document.createElement("span");
      nmText.className = "vname-text";
      nmText.textContent = u.first_name;
      nm.appendChild(nmText);
      if (u.is_verified) nm.appendChild(verifiedBadge());
      info.append(nm);
      top.append(av, info, bloodGroupBadge(u.blood_group));
      const bottom = document.createElement("div");
      bottom.className = "blood-bottom";
      const sub = document.createElement("div");
      sub.className = "muted";
      const dist = bloodDistance(u.distance_km);
      sub.textContent = [u.country || "", dist].filter(Boolean)
        .join(" · ");
      const msg = document.createElement("button");
      msg.className = "btn blood-msg";
      msg.textContent = "💬 Message";
      msg.onclick = () => openChat(u.telegram_id);
      bottom.append(sub, msg);
      card.append(top, bottom);
      box.appendChild(card);
    });
    fitVerifiedNamesSoon(box);
    if (!(d.donors || []).length) {
      empty.hidden = false;
      empty.textContent = bloodGroupFilter
        ? "No donors of " + bloodGroupFilter + " yet — opt in from Settings to be the first."
        : "No donors yet — opt in from Settings → Profile to be the first.";
    }
  } catch (e) { box.innerHTML = ""; empty.hidden = false; empty.textContent = "Could not load donors."; }
}

async function loadBloodRequests() {
  const box = $("blood-request-list");
  const empty = $("blood-empty");
  if (!box) return;
  box.innerHTML = "Loading…";
  empty.hidden = true;
  try {
    const d = await api("/blood/requests");
    box.innerHTML = "";
    (d.requests || []).forEach(r => {
      const card = document.createElement("div");
      card.className = "card blood-card blood-req";
      const info = document.createElement("div");
      info.className = "blood-info";
      const head = document.createElement("div");
      head.className = "blood-name";
      head.textContent = r.hospital + " · " + r.city;
      const sub = document.createElement("div");
      sub.className = "muted";
      sub.textContent = r.units + " unit" + (r.units === 1 ? "" : "s") + " · by " + (r.author_name || "?") + (r.note ? " · " + r.note : "") + (r.contact ? " · " + r.contact : "");
      info.append(head, sub);
      card.append(bloodGroupBadge(r.blood_group), info);
      if (r.mine) {
        const done = document.createElement("button");
        done.className = "btn blood-act";
        done.textContent = "Fulfilled ✓";
        done.onclick = async () => {
          try { await api("/blood/requests/" + r.id + "/fulfill", { method: "POST" }); setStatus("Marked fulfilled — thank you! 🩸"); loadBloodRequests(); }
          catch (e) { setStatus("Could not update the request."); }
        };
        const cancel = document.createElement("button");
        cancel.className = "btn blood-act";
        cancel.textContent = "Cancel";
        cancel.onclick = async () => {
          try { await api("/blood/requests/" + r.id + "/cancel", { method: "POST" }); setStatus("Request cancelled."); loadBloodRequests(); }
          catch (e) { setStatus("Could not update the request."); }
        };
        card.append(done, cancel);
      } else {
        const go = document.createElement("button");
        go.className = "btn blood-act";
        go.textContent = "আমি দেবো";
        go.onclick = async () => {
          try {
            const res = await api("/blood/requests/" + r.id + "/respond", { method: "POST" });
            setStatus("The requester has been notified — opening your chat with them. 🩸");
            openChat(res.author_id);
          } catch (e) { setStatus("Could not respond to the request."); }
        };
        card.appendChild(go);
      }
      box.appendChild(card);
    });
    if (!(d.requests || []).length) {
      empty.hidden = false;
      empty.textContent = "No open requests right now.";
    }
  } catch (e) { box.innerHTML = ""; empty.hidden = false; empty.textContent = "Could not load requests."; }
}

// ---------- Phase 158: Skill Swap (দক্ষতা বিনিময়) ----------
// Directory (search + teach/learn filter) and computed matches.
// Connect notifies the member and opens a DM — the swap itself is
// arranged there, never in the app. No points, no payments.
let skillTab = "directory";
let skillKindFilter = "";
let skillQuery = "";

async function loadSkills() {
  const dTab = $("skill-tab-directory");
  const mTab = $("skill-tab-matches");
  if (!dTab) return;
  dTab.onclick = () => { skillTab = "directory"; loadSkills(); };
  mTab.onclick = () => { skillTab = "matches"; loadSkills(); };
  const search = $("skill-search");
  search.onkeydown = (e) => {
    if (e.key === "Enter") {
      skillQuery = search.value.trim();
      loadSkillsDirectory();
    }
  };
  $("skill-search-btn").onclick = () => {
    skillQuery = search.value.trim();
    loadSkillsDirectory();
  };
  const filters = $("skill-kind-filters");
  filters.innerHTML = "";
  const mkChip = (label, val) => {
    const c = document.createElement("button");
    c.className = "chip" + (skillKindFilter === val ? " active" : "");
    c.textContent = label;
    c.onclick = () => { skillKindFilter = val; loadSkillsDirectory(); };
    filters.appendChild(c);
  };
  mkChip("All", "");
  mkChip("🎓 Teach", "teach");
  mkChip("📚 Learn", "learn");
  dTab.classList.toggle("active", skillTab === "directory");
  mTab.classList.toggle("active", skillTab === "matches");
  $("skill-directory-pane").hidden = skillTab !== "directory";
  $("skill-match-pane").hidden = skillTab !== "matches";
  if (skillTab === "directory") loadSkillsDirectory();
  else loadSkillsMatches();
}

function skillChip(text, kind) {
  const c = document.createElement("span");
  c.className = "skill-chip skill-chip-" + kind;
  c.textContent = (kind === "teach" ? "🎓 " : "📚 ") + text;
  return c;
}

function skillMemberCard(m) {
  const card = document.createElement("div");
  card.className = "card skill-card";
  const top = document.createElement("div");
  top.className = "skill-top";
  const av = avatarEl(m.first_name, m.telegram_id, false, m.photo_file_id);
  av.onclick = () => openProfile(m.telegram_id);
  const info = document.createElement("div");
  info.className = "skill-info";
  const nm = document.createElement("div");
  nm.className = "skill-name";
  nm.textContent = m.first_name;
  info.append(nm);
  const lists = document.createElement("div");
  lists.className = "skill-lists";
  (m.teach || []).forEach(s => lists.appendChild(skillChip(s, "teach")));
  (m.learn || []).forEach(s => lists.appendChild(skillChip(s, "learn")));
  info.append(lists);
  const go = document.createElement("button");
  go.className = "btn skill-connect";
  go.textContent = "🤝 Connect";
  go.onclick = async () => {
    try {
      const res = await api("/skills/" + m.telegram_id + "/connect",
                            { method: "POST" });
      setStatus("🤝 " + m.first_name +
        " has been notified — opening your chat to arrange the swap.");
      openChat(res.user_id);
    } catch (e) { setStatus("Could not connect."); }
  };
  top.append(av, info, go);
  card.appendChild(top);
  return card;
}

async function loadSkillsDirectory() {
  const box = $("skill-directory-list");
  const empty = $("skill-empty");
  if (!box) return;
  box.innerHTML = "Loading…";
  empty.hidden = true;
  try {
    const params = new URLSearchParams();
    if (skillQuery) params.set("q", skillQuery);
    if (skillKindFilter) params.set("kind", skillKindFilter);
    const qs = params.toString();
    const d = await api("/skills/directory" + (qs ? "?" + qs : ""));
    box.innerHTML = "";
    (d.members || []).forEach(m => box.appendChild(skillMemberCard(m)));
    if (!(d.members || []).length) {
      empty.hidden = false;
      empty.textContent = skillQuery
        ? "Nobody lists “" + skillQuery +
          "” yet — add it in Settings → Profile → My skills."
        : "Nobody lists skills yet — be the first from Settings → Profile → My skills.";
    }
  } catch (e) { box.innerHTML = ""; empty.hidden = false; empty.textContent = "Could not load skills."; }
}

async function loadSkillsMatches() {
  const box = $("skill-match-list");
  const empty = $("skill-empty");
  if (!box) return;
  box.innerHTML = "Loading…";
  empty.hidden = true;
  try {
    const d = await api("/skills/matches");
    box.innerHTML = "";
    (d.matches || []).forEach(m => {
      const card = skillMemberCard(m);
      const note = document.createElement("div");
      note.className = "skill-match-note";
      const bits = [];
      if (m.match.teach_for_me.length)
        bits.push("Teaches what you want to learn: " +
                  m.match.teach_for_me.join(", "));
      if (m.match.learn_from_me.length)
        bits.push("Wants to learn what you teach: " +
                  m.match.learn_from_me.join(", "));
      note.textContent = "🤝 " + bits.join(" · ");
      card.appendChild(note);
      box.appendChild(card);
    });
    if (!(d.matches || []).length) {
      empty.hidden = false;
      empty.textContent = "No matches yet — list what you teach and want to learn in Settings → Profile → My skills.";
    }
  } catch (e) { box.innerHTML = ""; empty.hidden = false; empty.textContent = "Could not load matches."; }
}

async function loadMySkills() {
  const box = $("settings-skill-list");
  if (!box) return;
  box.innerHTML = "Loading…";
  try {
    const d = await api("/me/skills");
    box.innerHTML = "";
    (d.skills || []).forEach(e => {
      const row = document.createElement("div");
      row.className = "settings-skill-row";
      row.appendChild(skillChip(e.skill, e.kind));
      if (e.note) {
        const nt = document.createElement("span");
        nt.className = "muted";
        nt.textContent = e.note;
        row.appendChild(nt);
      }
      const rm = document.createElement("button");
      rm.className = "btn";
      rm.textContent = "Remove";
      rm.onclick = async () => {
        try {
          await api("/me/skills/" + e.id, { method: "DELETE" });
          loadMySkills();
        } catch (err) { setStatus("Could not remove the skill."); }
      };
      row.appendChild(rm);
      box.appendChild(row);
    });
    if (!(d.skills || []).length)
      box.textContent = "No skills listed yet.";
  } catch (e) { box.innerHTML = ""; box.textContent = "Could not load your skills."; }
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
    nm.className = "suggest-name vname";
    const nmText = document.createElement("span");
    nmText.className = "suggest-name-text vname-text";
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
    let following = false, requested = false;
    // Phase 136: a private account shows Requested until the
    // owner accepts the follow request.
    const paint = () => {
      fBtn.textContent = requested ? "Requested ✓"
        : following ? "Following ✓" : "Follow";
      fBtn.classList.toggle("on", following || requested);
    };
    paint();
    fBtn.onclick = async () => {
      fBtn.disabled = true;
      try {
        // Phase 136: while a request is pending, tapping
        // cancels it (a second POST /follow would be a 400).
        if (requested) {
          await api("/users/" + u.telegram_id + "/follow-request",
                    { method: "DELETE" });
          requested = false;
          paint();
          setStatus("Follow request to " + u.first_name + " cancelled.");
        } else {
          const r = await api("/users/" + u.telegram_id + "/follow",
                              { method: "POST" });
          following = !!r.following;
          requested = !!r.requested;
          paint();
          setStatus(r.requested ? "Follow request sent to " + u.first_name + "."
                    : following ? "Following " + u.first_name + "."
                    : "Unfollowed " + u.first_name + ".");
        }
      } catch (e) { setStatus("Could not update follow."); }
      fBtn.disabled = false;
    };
    person.appendChild(fBtn);
    scroll.appendChild(person);
  });
  el.appendChild(scroll);
  fitVerifiedNamesSoon(el);
  return el;
}

function setTab(next) {
  tab = next;
  feedCursor = null;
  $("tab-explore").classList.toggle("active", tab === "explore");
  $("tab-following").classList.toggle("active", tab === "following");
  $("tab-hashtags").classList.toggle("active", tab === "hashtags");
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
  nm.className = "post-name vname";
  const nmText = document.createElement("span");
  nmText.className = "vname-text";
  nmText.textContent = p.author_name;
  nm.appendChild(nmText);
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
  // Phase 118: a reposted video says who shared it.
  if (p.reposted) {
    const rp = document.createElement("div");
    rp.className = "reel-repost";
    rp.textContent = "🔁 " + p.reposted_by_name + " reposted";
    rp.onclick = () => openProfile(p.reposted_by_id);
    shade.appendChild(rp);
  }
  if (p.caption) {
    const cap = document.createElement("p");
    cap.className = "reel-caption";
    renderRichText(cap, p.caption, p.mentions);
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
  // Phase 118: repost — same toggle as the Feed's 🔁 button.
  const rWrap = document.createElement("div");
  rWrap.className = "reel-act";
  const rBtn = document.createElement("button");
  const rCount = document.createElement("span");
  const paintRepost = () => {
    rBtn.textContent = "🔁";
    rBtn.classList.toggle("reposted", !!p.reposted_by_me);
    rCount.textContent = p.repost_count || 0;
  };
  paintRepost();
  rBtn.onclick = async () => {
    try {
      const r = await api("/posts/" + p.id + "/repost", { method: "POST" });
      p.reposted_by_me = r.reposted;
      p.repost_count = r.repost_count;
      paintRepost();
      if (!r.reposted && p.reposted &&
          p.reposted_by_id === (me && me.telegram_id)) el.remove();
      setStatus(r.reposted ? "Reposted to your feed."
                           : "Repost removed.");
    } catch (e) { setStatus("Could not repost."); }
  };
  rWrap.append(rBtn, rCount);
  // Phase 133: Stars tip on the reel rail.
  const tWrap = document.createElement("div");
  tWrap.className = "reel-act";
  const tBtn = document.createElement("button");
  tBtn.textContent = "⭐";
  tBtn.title = "Tip";
  tBtn.onclick = () => openTipSheet({
    postId: p.id, name: p.author_name });
  tWrap.appendChild(tBtn);
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
  const rail = [likeWrap, cWrap, rWrap];
  if (!me || p.author_id !== me.telegram_id) rail.push(tWrap);
  rail.push(vWrap, mWrap);
  side.append(...rail);
  el.appendChild(side);

  const cBox = document.createElement("div");
  cBox.className = "comments";
  cBox.hidden = true;
  const cList = document.createElement("div");
  // Phase 118: replying to a comment — tap Reply under it,
  // the chip shows who you answer, Send posts it nested.
  let replyTarget = null;
  const replyChip = document.createElement("div");
  replyChip.className = "reply-chip";
  replyChip.hidden = true;
  const paintReplyChip = () => {
    if (replyTarget) {
      replyChip.hidden = false;
      replyChip.textContent = "Replying to " + replyTarget.author_name + "  ✕";
    } else replyChip.hidden = true;
  };
  replyChip.onclick = () => { replyTarget = null; paintReplyChip(); };
  const cForm = document.createElement("div");
  cForm.className = "comment-form";
  const cInput = document.createElement("input");
  cInput.type = "text";
  cInput.placeholder = "Write a comment…";
  cInput.maxLength = 500;
  attachMentionAutocomplete(cInput);
  const cSend = document.createElement("button");
  cSend.textContent = "Send";
  cForm.append(cInput, cSend);
  const onReply = (cm) => {
    replyTarget = cm;
    paintReplyChip();
    cInput.focus();
  };
  cBox.append(replyChip, cList, cForm);
  el.appendChild(cBox);

  let commentsLoaded = false;
  cBtn.onclick = async () => {
    cBox.hidden = !cBox.hidden;
    if (!cBox.hidden && !commentsLoaded) {
      commentsLoaded = true;
      try {
        const data = await api("/posts/" + p.id + "/comments");
        data.comments.forEach(cm => cList.appendChild(commentRow(cm, onReply)));
      } catch (e) { setStatus("Could not load comments."); }
    }
  };
  cSend.onclick = async () => {
    const text = cInput.value.trim();
    if (!text) return;
    const body = { text };
    if (replyTarget) body.parent_id = replyTarget.id;
    try {
      const cm = await api("/posts/" + p.id + "/comments", {
        method: "POST", body: JSON.stringify(body) });
      if (replyTarget) {
        const parentRow = cList.querySelector(
          '[data-comment-id="' + replyTarget.id + '"]');
        if (parentRow && parentRow._repliesBox)
          parentRow._repliesBox.appendChild(commentRow(cm, onReply));
        else cList.appendChild(commentRow(cm, onReply));
      } else cList.appendChild(commentRow(cm, onReply));
      cInput.value = "";
      replyTarget = null;
      paintReplyChip();
      p.comment_count += 1;
      cCount.textContent = p.comment_count;
    } catch (e) { setStatus("Could not send the comment."); }
  };
  fitVerifiedNamesSoon(el);
  return el;
}

// ------------------------------------------------------- options sheet ---
function closeReelMenu() { $("reel-sheet-wrap").hidden = true; updateBackButton(); }

// Phase 133: Stars tipping — a Mini App cannot take a Stars
// payment itself, so the sheet asks the bot to send an XTR
// invoice into the member's Telegram chat; the member pays
// there. The tip is recorded only once that payment lands.
const TIP_AMOUNTS = [10, 50, 100, 250];
async function openTipSheet(target) {
  const sheet = $("reel-sheet");
  sheet.innerHTML = "";
  const title = document.createElement("div");
  title.className = "sheet-title";
  title.textContent = "⭐ Tip " + (target.name || "this creator");
  sheet.appendChild(title);
  const chips = document.createElement("div");
  chips.className = "tip-chips";
  let amount = 50;
  const chipBtns = [];
  TIP_AMOUNTS.forEach(n => {
    const b = document.createElement("button");
    b.className = "tip-chip" + (n === amount ? " active" : "");
    b.textContent = n + " ⭐";
    b.onclick = () => {
      amount = n; custom.value = "";
      chipBtns.forEach(c => c.classList.remove("active"));
      b.classList.add("active");
    };
    chips.appendChild(b); chipBtns.push(b);
  });
  sheet.appendChild(chips);
  const custom = document.createElement("input");
  custom.type = "number"; custom.min = "1"; custom.max = "10000";
  custom.placeholder = "Custom amount (1–10000 Stars)";
  custom.className = "tip-custom";
  custom.oninput = () => {
    const v = parseInt(custom.value, 10);
    if (v > 0) {
      amount = v;
      chipBtns.forEach(c => c.classList.remove("active"));
    }
  };
  sheet.appendChild(custom);
  const note = document.createElement("p");
  note.className = "tip-note";
  note.textContent = "Payment happens in your Telegram chat with "
    + "the bot — the invoice arrives there right after you send "
    + "this. Stars go to the creator's total.";
  sheet.appendChild(note);
  const send = document.createElement("button");
  send.className = "wide btn";
  send.textContent = "Send tip invoice";
  send.onclick = async () => {
    if (!amount || amount < 1 || amount > 10000) {
      setStatus("Pick an amount between 1 and 10000 Stars.");
      return;
    }
    send.disabled = true; send.textContent = "Sending…";
    const body = { amount_stars: amount };
    if (target.postId) body.post_id = target.postId;
    else body.user_id = target.userId;
    try {
      const r = await api("/tips/create", {
        method: "POST", body: JSON.stringify(body) });
      sheet.innerHTML = "";
      const done = document.createElement("div");
      done.className = "sheet-title";
      done.textContent = "⭐ Invoice sent — pay in the bot chat";
      sheet.appendChild(done);
      const dNote = document.createElement("p");
      dNote.className = "tip-note";
      dNote.textContent = "বট চ্যাটে পেমেন্ট করুন — টেলিগ্রাম "
        + "থেকে ইনভয়েস এসেছে। " + r.amount_stars + " Stars for "
        + r.to_name + ".";
      sheet.appendChild(dNote);
      const open = document.createElement("a");
      open.className = "wide btn";
      open.href = "https://t.me/" + (me && me.bot_username
        ? me.bot_username : "NexoraSocial_bot");
      open.target = "_blank";
      open.textContent = "Open chat with bot";
      sheet.appendChild(open);
      const close = document.createElement("button");
      close.className = "wide";
      close.textContent = "Close";
      close.onclick = () => closeReelMenu();
      sheet.appendChild(close);
    } catch (e) {
      send.disabled = false; send.textContent = "Send tip invoice";
      setStatus("Could not send the tip invoice.");
    }
  };
  sheet.appendChild(send);
  const cancel = document.createElement("button");
  cancel.className = "wide";
  cancel.textContent = "Cancel";
  cancel.onclick = () => closeReelMenu();
  sheet.appendChild(cancel);
  $("reel-sheet-wrap").hidden = false;
  updateBackButton();
}

// Phase 175: pick collections for a post — tap toggles membership,
// so the same sheet moves a post between collections or removes it.
async function openSaveToCollection(p) {
  const sheet = $("reel-sheet");
  sheet.innerHTML = "";
  const title = document.createElement("div");
  title.className = "sheet-title";
  title.textContent = "Save to collection";
  sheet.appendChild(title);
  const list = document.createElement("div");
  sheet.appendChild(list);
  const draw = async () => {
    list.innerHTML = "";
    try {
      const d = await api("/saved/collections?post_id=" + p.id);
      if (!d.collections.length) {
        const none = document.createElement("p");
        none.className = "hint";
        none.textContent = "No collections yet — create one below.";
        list.appendChild(none);
      }
      d.collections.forEach(coll => {
        const b = document.createElement("button");
        b.className = "sheet-row";
        b.textContent = (coll.has_post ? "✓ " : "") + coll.name +
          " (" + coll.post_count + ")";
        b.onclick = async () => {
          try {
            if (coll.has_post) {
              await api("/saved/collections/" + coll.id +
                "/posts/" + p.id, { method: "DELETE" });
              setStatus("Removed from " + coll.name + ".");
            } else {
              await api("/saved/collections/" + coll.id + "/posts",
                { method: "POST",
                  body: JSON.stringify({ post_id: p.id }) });
              p.saved = true;
              setStatus("Saved to " + coll.name + ".");
            }
            closeReelMenu();
          } catch (e) { setStatus("Could not update the collection."); }
        };
        list.appendChild(b);
      });
    } catch (e) {
      const err = document.createElement("p");
      err.className = "hint";
      err.textContent = "Could not load collections.";
      list.appendChild(err);
    }
  };
  await draw();
  const row = document.createElement("div");
  row.className = "saved-new-row";
  const inp = document.createElement("input");
  inp.type = "text"; inp.maxLength = 50;
  inp.placeholder = "New collection name";
  const ok = document.createElement("button");
  ok.textContent = "Create + save here";
  ok.onclick = async () => {
    if (!inp.value.trim()) return;
    try {
      const r = await api("/saved/collections", { method: "POST",
        body: JSON.stringify({ name: inp.value.trim() }) });
      await api("/saved/collections/" + r.id + "/posts",
        { method: "POST", body: JSON.stringify({ post_id: p.id }) });
      p.saved = true;
      setStatus("Saved to " + r.name + ".");
      closeReelMenu();
    } catch (e) { setStatus("Could not create the collection."); }
  };
  row.append(inp, ok);
  sheet.appendChild(row);
  const cancel = document.createElement("button");
  cancel.className = "wide";
  cancel.textContent = "Cancel";
  cancel.onclick = () => closeReelMenu();
  sheet.appendChild(cancel);
  $("reel-sheet-wrap").hidden = false;
  updateBackButton();
}

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
  row("📁", "Save to collection", () => openSaveToCollection(p));
  row("📤", "Share", () => openSharePicker(p));
  // Phase 118: repost — a post to your own feed.
  if (!mine) row("🔁", p.reposted_by_me ? "Reposted — tap to remove" : "Repost", async () => {
    try {
      const r = await api("/posts/" + p.id + "/repost", { method: "POST" });
      p.reposted_by_me = r.reposted;
      p.repost_count = r.repost_count;
      setStatus(r.reposted ? "Reposted to your feed." : "Repost removed.");
      if (!r.reposted && p.reposted &&
          p.reposted_by_id === (me && me.telegram_id)) reelEl.remove();
    } catch (e) { setStatus("Could not repost."); }
  });
  row("🔗", "Copy link", async () => {
    const link = appLink + "?start=post_" + p.id;
    try {
      await navigator.clipboard.writeText(link);
      setStatus("Link copied.");
    } catch (e) { setStatus(link); }
  });
  // Phase 176: the public link opens the post outside Telegram.
  row("🔗", "Copy public link", async () => {
    try {
      const r = await api("/posts/" + p.id + "/share-link");
      await navigator.clipboard.writeText(r.share_link);
      setStatus("Public link copied.");
    } catch (e) { setStatus("Could not get the public link."); }
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
          (u.has_pending_request ? "Requested ✓ @"
           : u.following ? "Unfollow @" : "Follow @") +
          (p.author_username || p.author_name);
        fRow.onclick = async () => {
          closeReelMenu();
          try {
            // Phase 136: while a request is pending, tapping
            // cancels it (a second POST /follow would be a 400).
            if (u.has_pending_request) {
              await api("/users/" + p.author_id + "/follow-request",
                        { method: "DELETE" });
              setStatus("Follow request to " + p.author_name + " cancelled.");
              return;
            }
            const r = await api("/users/" + p.author_id + "/follow",
                                { method: "POST" });
            setStatus(r.requested ? "Follow request sent to " + p.author_name + "."
                      : r.following ? "Following " + p.author_name + "."
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
  // Phase 123: pin one of your own posts (a repost cannot be
  // pinned — only your own originals); pinning a second post
  // unpins the first.
  if (mine && !p.reposted) row("📌", p.is_pinned ? "Pinned — tap to unpin" : "Pin to profile", async () => {
    try {
      const r = await api("/posts/" + p.id + "/pin", { method: "POST" });
      p.is_pinned = r.pinned;
      setStatus(r.pinned ? "Pinned to your profile 📌" : "Pin removed.");
      if (profileId === (me && me.telegram_id)) loadProfilePosts(true);
    } catch (e) { setStatus("Could not pin this post."); }
  });
  if (mine) row("✏️", "Edit", () => openPostEditor(p, reelEl));
  // Phase 134: per-post analytics for the author — originals
  // and reposts of your own posts (the endpoint resolves a
  // repost to its original).
  if (mine) row("📊", "Insights", () => openInsights(p.id, p));
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
// Phase 134: per-post analytics sheet for the author —
// totals, a 14-day bar chart of daily views (plain divs,
// no chart library) and a daily table.
async function openInsights(postId, p) {
  const sheet = $("reel-sheet");
  sheet.innerHTML = "";
  const title = document.createElement("div");
  title.className = "sheet-title";
  title.textContent = "📊 Insights";
  sheet.appendChild(title);
  const load = document.createElement("div");
  load.className = "hint";
  load.textContent = "Loading insights…";
  sheet.appendChild(load);
  $("reel-sheet-wrap").hidden = false;
  updateBackButton();
  try {
    const ins = await api("/posts/" + postId + "/insights");
    load.remove();
    const t = ins.totals;
    const totals = document.createElement("div");
    totals.className = "ins-totals";
    [["👁", t.views, "Views"], ["🤍", t.likes, "Likes"],
     ["💬", t.comments, "Comments"], ["🔁", t.reposts, "Reposts"],
     ["⭐", t.tips_stars, "Tips"]].forEach(([ic, n, label]) => {
      const cell = document.createElement("div");
      cell.className = "ins-total";
      const v = document.createElement("div");
      v.className = "ins-num";
      v.textContent = ic + " " + n;
      const l = document.createElement("div");
      l.className = "ins-label";
      l.textContent = label;
      cell.append(v, l);
      totals.appendChild(cell);
    });
    sheet.appendChild(totals);
    if (ins.best_day) {
      const best = document.createElement("div");
      best.className = "hint";
      best.textContent = "Best day: " + ins.best_day.date + " · " +
        ins.best_day.views + " views";
      sheet.appendChild(best);
    }
    const maxV = Math.max(1, ...ins.daily.map(d => d.views));
    const chart = document.createElement("div");
    chart.className = "ins-chart";
    ins.daily.forEach(d => {
      const col = document.createElement("div");
      col.className = "ins-col";
      const wrap = document.createElement("div");
      wrap.className = "ins-barwrap";
      const bar = document.createElement("div");
      bar.className = "ins-bar";
      bar.style.height = Math.max(2, Math.round(d.views / maxV * 100)) + "%";
      bar.title = d.date + ": " + d.views + " views";
      wrap.appendChild(bar);
      const lab = document.createElement("div");
      lab.className = "ins-day";
      lab.textContent = Number(d.date.slice(8, 10));
      col.append(wrap, lab);
      chart.appendChild(col);
    });
    sheet.appendChild(chart);
    const table = document.createElement("table");
    table.className = "ins-table";
    const head = document.createElement("tr");
    ["Date", "Views", "Likes", "Comments"].forEach(h => {
      const th = document.createElement("th");
      th.textContent = h;
      head.appendChild(th);
    });
    table.appendChild(head);
    ins.daily.forEach(d => {
      const tr = document.createElement("tr");
      [d.date, d.views, d.likes, d.comments].forEach(v => {
        const td = document.createElement("td");
        td.textContent = v;
        tr.appendChild(td);
      });
      table.appendChild(tr);
    });
    sheet.appendChild(table);
  } catch (e) { load.textContent = "Could not load insights."; }
  const cancel = document.createElement("button");
  cancel.className = "sheet-row";
  cancel.textContent = "✕ Close";
  cancel.onclick = () => closeReelMenu();
  sheet.appendChild(cancel);
}

// Phase 134: open one post (from the My-insights top list) as
// a full card inside the sheet — the app has no single-post
// view, so the card itself is the view.
async function openTopPost(postId) {
  const sheet = $("reel-sheet");
  sheet.innerHTML = "";
  const load = document.createElement("div");
  load.className = "hint";
  load.textContent = "Loading post…";
  sheet.appendChild(load);
  $("reel-sheet-wrap").hidden = false;
  updateBackButton();
  try {
    const p = await api("/posts/" + postId);
    load.remove();
    sheet.appendChild(postCard(p));
  } catch (e) { load.textContent = "Could not load this post."; }
  const cancel = document.createElement("button");
  cancel.className = "sheet-row";
  cancel.textContent = "✕ Close";
  cancel.onclick = () => closeReelMenu();
  sheet.appendChild(cancel);
}

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
          renderRichText(cap, r.caption, r.mentions);
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
      const line = document.createElement("span");
      line.className = "vname";
      const nmText = document.createElement("span");
      nmText.className = "vname-text";
      nmText.textContent = u.first_name;
      line.appendChild(nmText);
      if (u.is_verified) line.appendChild(verifiedBadge());
      nm.appendChild(line);
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
    fitVerifiedNames(list);
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

async function loadShared(more) {
  const box = $("shared-list");
  if (!more) {
    box.innerHTML = "Loading…";
    sharedCursor = null;
  } else {
    const old = $("shared-more");
    if (old) old.remove();
  }
  try {
    const data = await api("/me/shared"
      + (sharedCursor ? "?cursor=" + sharedCursor : ""));
    if (!more) box.innerHTML = "";
    data.posts.forEach(p => {
      const head = document.createElement("div");
      head.className = "shared-by";
      head.textContent = "📤 Shared by " + p.shared_by_name;
      box.append(head, postCard(p));
    });
    sharedCursor = data.next_cursor;
    if (sharedCursor) {
      const mb = document.createElement("button");
      mb.id = "shared-more";
      mb.className = "wide";
      mb.textContent = "Load more";
      mb.onclick = () => loadShared(true);
      box.appendChild(mb);
    }
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
  } catch (e) {
    if (!more) box.textContent = "Could not load shared posts.";
    else setStatus("Could not load more shared posts.");
  }
}

// Phase 184 (audit L9): tappable followers / following lists.
// The profile counts open this sheet (the shared reel-sheet
// container): avatar + name + follow state per member; tapping
// a row opens their profile. Private lists stay followers-only
// and blocked pairs 404 on the server.
async function openFollowList(userId, kind) {
  const sheet = $("reel-sheet");
  sheet.innerHTML = "";
  const title = document.createElement("div");
  title.className = "sheet-title";
  title.textContent = kind === "followers" ? "👥 Followers"
    : "➡️ Following";
  sheet.appendChild(title);
  const list = document.createElement("div");
  list.id = "follow-list";
  list.dataset.kind = kind;
  list.dataset.userId = userId;
  sheet.appendChild(list);
  const show = users => {
    list.innerHTML = "";
    if (!users.length) {
      const em = document.createElement("div");
      em.className = "sheet-row";
      em.textContent = "Nobody here yet.";
      list.appendChild(em);
    }
    users.forEach(u => {
      const row = document.createElement("button");
      row.className = "sheet-row follow-list-row";
      row.type = "button";
      row.append(avatarEl(u.first_name, u.telegram_id, false,
        u.photo_file_id));
      const nm = document.createElement("span");
      nm.className = "follow-list-name";
      nm.textContent = (u.first_name || "Member")
        + (u.username ? " @" + u.username : "");
      const st = document.createElement("span");
      st.className = "follow-list-state";
      st.textContent = u.telegram_id === (me && me.telegram_id)
        ? "You" : u.following ? "Following ✓" : "Follow";
      row.append(nm, st);
      row.onclick = () => { closeReelMenu(); openProfile(u.telegram_id); };
      list.appendChild(row);
    });
    const cancel = document.createElement("button");
    cancel.className = "sheet-row";
    const ic = document.createElement("span");
    ic.className = "ic";
    ic.textContent = "✕";
    cancel.append(ic, document.createTextNode("Cancel"));
    cancel.onclick = closeReelMenu;
    sheet.appendChild(cancel);
    fitVerifiedNames(sheet);
  };
  try {
    const data = await api("/users/" + userId + "/" + kind);
    show(data.users || []);
  } catch (e) {
    list.innerHTML = "";
    const em = document.createElement("div");
    em.className = "sheet-row";
    em.textContent = "Could not load this list.";
    list.appendChild(em);
    const cancel = document.createElement("button");
    cancel.className = "sheet-row";
    cancel.textContent = "✕ Cancel";
    cancel.onclick = closeReelMenu;
    sheet.appendChild(cancel);
  }
  $("reel-sheet-wrap").hidden = false;
  updateBackButton();
}

// ---------------------------------------------------------------- saved ---
let savedCollectionOpen = null; // Phase 175: open collection id, or null = All saved
let savedCursor = null; // Phase 184 (audit L3): Saved "Load more" cursor
let sharedCursor = null; // Phase 184 (audit L3): Shared "Load more" cursor
async function loadSavedCollections() {
  const bar = $("saved-collections");
  if (!bar) return;
  bar.innerHTML = "";
  const mkChip = (label, active, fn) => {
    const b = document.createElement("button");
    b.className = "saved-chip" + (active ? " active" : "");
    b.textContent = label;
    b.onclick = fn;
    bar.appendChild(b);
    return b;
  };
  mkChip("📌 All saved", savedCollectionOpen === null, () => {
    savedCollectionOpen = null; loadSaved();
  });
  try {
    const d = await api("/saved/collections");
    d.collections.forEach(coll => {
      mkChip("📁 " + coll.name + " (" + coll.post_count + ")",
        savedCollectionOpen === coll.id, () => {
          savedCollectionOpen = coll.id; loadSaved();
        });
    });
    mkChip("+ New", false, () => {
      const row = document.createElement("div");
      row.className = "saved-new-row";
      const inp = document.createElement("input");
      inp.type = "text"; inp.maxLength = 50;
      inp.placeholder = "Collection name";
      const ok = document.createElement("button");
      ok.textContent = "Create";
      ok.onclick = async () => {
        if (!inp.value.trim()) return;
        try {
          const r = await api("/saved/collections", { method: "POST",
            body: JSON.stringify({ name: inp.value.trim() }) });
          savedCollectionOpen = r.id;
          setStatus("Collection created.");
          loadSaved();
        } catch (e) { setStatus("Could not create the collection."); }
      };
      const cx = document.createElement("button");
      cx.textContent = "Cancel";
      cx.onclick = () => loadSavedCollections();
      row.append(inp, ok, cx);
      bar.appendChild(row);
      inp.focus();
    });
  } catch (e) { /* collections stay hidden; All saved still works */ }
}
async function loadSaved(more) {
  const box = $("saved-list");
  if (!more) {
    box.innerHTML = "Loading…";
    savedCursor = null;
    await loadSavedCollections();
  } else {
    const old = $("saved-more");
    if (old) old.remove();
  }
  let shownPosts = 0;
  try {
    if (savedCollectionOpen === null) {
      const data = await api("/me/saved"
        + (savedCursor ? "?cursor=" + savedCursor : ""));
      if (!more) box.innerHTML = "";
      data.posts.forEach(p => box.appendChild(postCard(p)));
      shownPosts = data.posts.length;
      savedCursor = data.next_cursor;
      if (savedCursor) {
        const mb = document.createElement("button");
        mb.id = "saved-more";
        mb.className = "wide";
        mb.textContent = "Load more";
        mb.onclick = () => loadSaved(true);
        box.appendChild(mb);
      }
    } else {
      const data = await api("/saved/collections/" + savedCollectionOpen
        + (savedCursor ? "?cursor=" + savedCursor : ""));
      if (!more) box.innerHTML = "";
      const head = document.createElement("div");
      head.className = "saved-coll-head";
      const nm = document.createElement("span");
      nm.className = "saved-coll-name";
      nm.textContent = "📁 " + data.name + " (" + data.post_count + ")";
      head.appendChild(nm);
      const ren = document.createElement("button");
      ren.textContent = "Rename";
      ren.onclick = () => {
        const inp = document.createElement("input");
        inp.type = "text"; inp.maxLength = 50; inp.value = data.name;
        const ok = document.createElement("button");
        ok.textContent = "Save";
        ok.onclick = async () => {
          try {
            await api("/saved/collections/" + data.id,
              { method: "PATCH",
                body: JSON.stringify({ name: inp.value.trim() }) });
            setStatus("Collection renamed.");
            loadSaved();
          } catch (e) { setStatus("Could not rename."); }
        };
        head.innerHTML = "";
        head.append(inp, ok);
        inp.focus();
      };
      head.appendChild(ren);
      // Phase 184 (audit L3): on "Load more" the collection head
      // (name + Rename/Delete) is built but not re-appended.
      const del = document.createElement("button");
      del.textContent = "Delete";
      del.onclick = async () => {
        if (del.dataset.armed) {
          try {
            await api("/saved/collections/" + data.id,
              { method: "DELETE" });
            savedCollectionOpen = null;
            setStatus("Collection deleted — its posts stay saved.");
            loadSaved();
          } catch (e) { setStatus("Could not delete."); }
        } else {
          del.dataset.armed = "1";
          del.textContent = "Tap again to delete";
        }
      };
      head.appendChild(del);
      if (!more) box.appendChild(head);
      data.posts.forEach(p => box.appendChild(postCard(p)));
      shownPosts = data.posts.length;
      savedCursor = data.next_cursor;
      if (savedCursor) {
        const mb = document.createElement("button");
        mb.id = "saved-more";
        mb.className = "wide";
        mb.textContent = "Load more";
        mb.onclick = () => loadSaved(true);
        box.appendChild(mb);
      }
    }
    // Phase 66: designs saved via the long-press popup's 📌.
    const dd = await api("/me/design-saved");
    const grid = $("saved-designs");
    grid.innerHTML = "";
    dd.designs.forEach(d => grid.appendChild(designCard(d)));
    $("saved-designs-title").hidden = dd.designs.length === 0;
    $("saved-empty").hidden =
      shownPosts > 0 || dd.designs.length > 0;
  } catch (e) {
    if (!more) box.textContent = "Could not load your saved posts.";
    else setStatus("Could not load more saved posts.");
  }
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
      title.className = "rank-title vname-text";
      title.textContent = r.first_name;
      // Phase 160 (owner): a long name pushed the blue tick
      // onto the second line. Title + tick now live in one
      // shared .vname line and shrink until they fit.
      const line = document.createElement("span");
      line.className = "rank-title-line vname";
      line.appendChild(title);
      if (r.is_verified) line.appendChild(verifiedBadge());
      nm.appendChild(line);
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
    fitVerifiedNames(box);
  } catch (e) { box.textContent = "Could not load the leaderboard."; }
}

// --------------------------------------------------------------- search ---
// Phase 140: the set of hashtags the caller follows, cached
// for the search page's Follow button and the Me card.
let followedTags = new Set();
let followedTagsLoaded = false;


async function runSearch(q) {
  try {
    // Phase 140: a #tag search shows a Follow button for the
    // tag; its label comes from the cached followed set.
    const tagBtn = $("search-tag-follow");
    const tagMatch = q.trim().match(/^#([^\s#]{1,50})$/);
    if (tagMatch) {
      const tag = tagMatch[1].toLowerCase();
      tagBtn.hidden = false;
      const paintTagBtn = () => {
        tagBtn.textContent = followedTags.has(tag)
          ? "✓ Following #" + tag : "Follow #" + tag;
      };
      paintTagBtn();
      tagBtn.onclick = async () => {
        try {
          if (followedTags.has(tag)) {
            await api("/hashtags/" + tag + "/follow", { method: "DELETE" });
            followedTags.delete(tag);
          } else {
            await api("/hashtags/" + tag + "/follow", { method: "POST" });
            followedTags.add(tag);
          }
          paintTagBtn();
          setStatus(followedTags.has(tag) ? "Following #" + tag + "."
                    : "Unfollowed #" + tag + ".");
        } catch (e) { setStatus("Could not update hashtag follow."); }
      };
      if (!followedTagsLoaded) {
        followedTagsLoaded = true;
        try {
          const mine = await api("/me/hashtags");
          mine.hashtags.forEach(h => followedTags.add(h.tag));
          paintTagBtn();
        } catch (e) { /* label stays "Follow" until it loads */ }
      }
    } else {
      tagBtn.hidden = true;
    }
    const data = await api("/search?q=" + encodeURIComponent(q));
    const usersBox = $("search-users");
    const postsBox = $("search-posts");
    usersBox.innerHTML = "";
    postsBox.innerHTML = "";
    data.users.forEach(u => {
      const row = document.createElement("button");
      row.className = "user-row";
      row.appendChild(avatarEl(u.first_name, u.telegram_id, false, u.photo_file_id));
      const nm = document.createElement("span");
      nm.className = "vname";
      const nmText = document.createElement("span");
      nmText.className = "vname-text";
      nmText.textContent = u.first_name;
      nm.appendChild(nmText);
      if (u.is_verified) nm.appendChild(verifiedBadge());
      row.appendChild(nm);
      if (u.username) row.appendChild(document.createTextNode(
        " @" + String(u.username).replace(/^@+/, "")));
      row.onclick = () => openProfile(u.telegram_id);
      usersBox.appendChild(row);
    });
    data.posts.forEach(p => postsBox.appendChild(postCard(p)));
    fitVerifiedNames();
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
// Phase 137: Levels & badges — one shared renderer for the
// profile hero and the Me "My level" card. Earned badges in
// colour, locked ones greyed with their requirement as a hint.
function renderLevelBlock(level, badges) {
  const wrap = document.createElement("div");
  wrap.className = "level-block";
  if (!level) { wrap.textContent = ""; return wrap; }
  const head = document.createElement("div");
  head.className = "level-head";
  head.textContent = "Level " + level.level + " · " + level.name;
  wrap.appendChild(head);
  const bar = document.createElement("div");
  bar.className = "level-bar";
  const fill = document.createElement("div");
  fill.className = "level-fill";
  fill.style.width = Math.round(level.progress * 100) + "%";
  bar.appendChild(fill);
  wrap.appendChild(bar);
  const sub = document.createElement("div");
  sub.className = "level-sub";
  sub.textContent = level.next_level
    ? (level.next_level.points_needed + " points to Level "
       + level.next_level.level + " · " + level.next_level.name)
    : "Max level — " + level.name;
  wrap.appendChild(sub);
  if (badges && badges.length) {
    const row = document.createElement("div");
    row.className = "badge-row";
    badges.forEach(b => {
      const chip = document.createElement("span");
      chip.className = "badge-chip" + (b.earned ? "" : " badge-locked");
      chip.title = b.hint || b.name;
      chip.textContent = b.icon + " " + b.name;
      row.appendChild(chip);
    });
    wrap.appendChild(row);
  }
  return wrap;
}

// Phase 146 (owner): a reload must re-open the profile being
// viewed, not the viewer's own. The viewed id is remembered
// in sessionStorage (same pattern as nx_open_admin / nx_actas):
// it survives a reload in the same WebView and dies with the
// session. Leaving the profile view forgets it, so a reload
// from anywhere else boots normally.
function rememberProfile(id) {
  try { sessionStorage.setItem("nx_profile", String(id)); }
  catch (e) {}
}
function forgetProfile() {
  try { sessionStorage.removeItem("nx_profile"); } catch (e) {}
}
function readRememberedProfile() {
  let id = 0;
  try {
    id = parseInt(sessionStorage.getItem("nx_profile") || "", 10)
      || 0;
  } catch (e) {}
  return id;
}
function restoreProfile() {
  const id = readRememberedProfile();
  if (id > 0) openProfile(id);
}

async function openProfile(userId) {
  profileId = userId;
  // Phase 146: remember the profile being viewed so a reload
  // re-opens it instead of defaulting to the viewer's own.
  rememberProfile(userId);
  profileCursor = null;
  showView("profile");
  const box = $("profile-box");
  box.innerHTML = "Loading…";
  $("profile-posts").innerHTML = "";
  try {
    const u = await api("/users/" + userId);
    // Phase 199: the portfolio tab renders from this user —
    // the default tab is always Profile.
    profileTab = "profile";
    profileUser = u;
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
    name.className = "profile-name vname";
    const nameText = document.createElement("span");
    nameText.className = "vname-text";
    nameText.textContent = u.first_name;
    name.appendChild(nameText);
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
    // Phase 184 (audit L9): the counts are tappable — they open
    // the followers / following list sheet.
    const refreshStats = () => {
      stats.textContent = "";
      const mkStat = (label, kind) => {
        const b = document.createElement("button");
        b.className = "stats-link";
        b.type = "button";
        b.textContent = label;
        b.onclick = () => openFollowList(userId, kind);
        return b;
      };
      stats.append(mkStat(u.followers + " followers", "followers"),
        document.createTextNode(" · "),
        mkStat(u.following_count + " following", "following"));
    };
    refreshStats();
    hero.append(headWrap, bio, stats);
    // Phase 151: blood-donor badge — only when the member opted
    // in (the API sends blood_group only for opted-in donors).
    if (u.blood_group) {
      const bb = document.createElement("div");
      bb.className = "blood-badge";
      bb.textContent = "🩸 Blood donor · " + u.blood_group;
      hero.appendChild(bb);
    }
    // Phase 158: skills the member teaches / wants to learn —
    // the API sends them only when the viewer may see this
    // profile (private strangers get empty lists).
    if (u.skills && (u.skills.teach.length || u.skills.learn.length)) {
      const sk = document.createElement("div");
      sk.className = "skill-block";
      if (u.skills.teach.length) {
        const t = document.createElement("div");
        t.className = "skill-line";
        t.textContent = "🎓 Teaches: " + u.skills.teach.join(", ");
        sk.appendChild(t);
      }
      if (u.skills.learn.length) {
        const l = document.createElement("div");
        l.className = "skill-line";
        l.textContent = "📚 Wants to learn: " + u.skills.learn.join(", ");
        sk.appendChild(l);
      }
      hero.appendChild(sk);
    }
    // Phase 145 (owner): Stars-received line removed from the
    // profile hero — it already lives in Settings ("My tips").
    // Phase 145 (owner): level + badges removed from the profile
    // hero — they already live in Settings ("My level"). The
    // shared level renderer stays: Settings still uses it.
    box.appendChild(hero);
    await loadHighlights(userId, box);
    // Phase 199: Profile/Portfolio dropdown — only when this
    // member's portfolio is on and the viewer may see it
    // (a muted member's portfolio stays hidden, as does a
    // private-not-followed one; the server 404s it too).
    if (u.portfolio_enabled && !u.muted_by_me
        && (ownProfile || !u.is_private || u.following)) {
      box.insertBefore(portfolioDropdownEl(userId, "profile"),
                       box.firstChild);
    }
    // Phase 201: Museum button on one side of the profile —
    // same visibility as the portfolio dropdown (a muted
    // member's museum stays hidden, as does a private-not-
    // followed one; the server 404s it too). The button never
    // carries the member's name, so the verified-name rule
    // has nothing to shrink here.
    if (!u.muted_by_me
        && (ownProfile || !u.is_private || u.following)) {
      const muBtn = document.createElement("button");
      muBtn.className = "wide";
      muBtn.textContent = "🏛️ Museum — walk through the gallery";
      muBtn.onclick = () => openMuseum(userId);
      box.appendChild(muBtn);
    }
    fitVerifiedNames(box);
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
      // Phase 136: a private account shows Requested until the
      // owner accepts; tapping again cancels the request.
      const paint = () => {
        fBtn.textContent = u.has_pending_request
          ? "Requested ✓ — tap to cancel"
          : u.following ? "Unfollow" : "Follow";
      };
      paint();
      fBtn.onclick = async () => {
        try {
          // Phase 136: while a request is pending, tapping
          // cancels it (a second POST /follow would be a 400).
          if (u.has_pending_request) {
            await api("/users/" + userId + "/follow-request",
                      { method: "DELETE" });
            u.has_pending_request = false;
            paint();
            setStatus("Follow request cancelled.");
            return;
          }
          const r = await api("/users/" + userId + "/follow", { method: "POST" });
          u.following = r.following;
          u.has_pending_request = !!r.requested;
          u.followers = r.followers;
          refreshStats();
          paint();
          if (r.requested) setStatus("Follow request sent — you'll see their posts once it's accepted 👥");
        } catch (e) { setStatus("Could not update follow."); }
      };
      box.appendChild(fBtn);
      // Phase 133: tip this member, beside Follow.
      const tBtn = document.createElement("button");
      tBtn.className = "wide btn";
      tBtn.textContent = "⭐ Tip " + u.first_name;
      tBtn.onclick = () => openTipSheet({
        userId, name: u.first_name });
      box.appendChild(tBtn);
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
        tBtn.hidden = !!u.blocked_by_me;
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
      // Phase 174: Mute/Unmute — hides their posts, comments
      // and stories from YOUR feed only; DMs and follows are
      // untouched, and they can still see your posts.
      const muBtn = document.createElement("button");
      muBtn.className = "wide";
      const paintMute = () => {
        muBtn.textContent = u.muted_by_me
          ? "🔇 Muted — tap to unmute" : "🔇 Mute this member";
      };
      paintMute();
      muBtn.onclick = async () => {
        try {
          const r = await api("/users/" + userId + "/mute",
                              { method: "POST" });
          u.muted_by_me = r.muted;
          paintMute();
          setStatus(r.muted
            ? "Member muted — their posts, comments and stories "
              + "won't show in your feed."
            : "Member unmuted.");
        } catch (e) { setStatus("Could not update mute."); }
      };
      box.appendChild(muBtn);
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
      // Phase 144 (owner): the private-account toggle moved to
      // Settings (Privacy) — the edit form keeps name and bio.
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

    // Phase 188 (Job 3): the Settings button lived here (Me) — it
    // moved to the sidebar (ACCOUNT section). Me keeps only name,
    // photo, bio, cover and posts.
    // Phase 136: a private account's posts stay hidden until a
    // follow request is accepted — show the lock, not the posts.
    if (u.is_private && !u.following && !ownProfile) {
      const lock = document.createElement("div");
      lock.className = "card private-lock";
      lock.textContent = "🔒 This account is private — follow to see their posts.";
      $("profile-posts").appendChild(lock);
      $("profile-more").hidden = true;
    } else {
      await loadProfilePosts(true);
    }
  } catch (e) { box.textContent = "Could not load the profile."; }
}


// ---------- Phase 199: Portfolio -----------------------------------------
// A member's showcase page (owner pick: sample #1 Organic Clay):
// full-bleed cover photo + soft shadow + name/role over it, About,
// Work grid. Invisible until the owner turns it on in Settings.
// The portfolio renders inside the profile view — openProfile
// stays the Profile tab and renderPortfolioTab the Portfolio tab.
function portfolioDropdownEl(userId, currentTab) {
  const wrap = document.createElement("div");
  wrap.className = "pf-dd-wrap";
  const btn = document.createElement("button");
  btn.className = "pf-dd-btn";
  btn.type = "button";
  btn.textContent = (currentTab === "portfolio" ? "Portfolio" : "Profile") + " ▾";
  const menu = document.createElement("div");
  menu.className = "pf-dd-menu";
  menu.hidden = true;
  const mkOpt = (label, tab) => {
    const b = document.createElement("button");
    b.className = "pf-dd-opt" + (tab === currentTab ? " active" : "");
    b.type = "button";
    b.textContent = (tab === currentTab ? "✓ " : "") + label;
    b.onclick = async () => {
      menu.hidden = true;
      if (tab === currentTab) return;
      if (tab === "portfolio") {
        profileTab = "portfolio";
        await renderPortfolioTab(userId);
      } else {
        await openProfile(userId);
      }
    };
    return b;
  };
  menu.append(mkOpt("Profile", "profile"), mkOpt("Portfolio", "portfolio"));
  btn.onclick = () => { menu.hidden = !menu.hidden; };
  wrap.append(btn, menu);
  return wrap;
}

async function renderPortfolioTab(userId) {
  const box = $("profile-box");
  const postsEl = $("profile-posts");
  const moreBtn = $("profile-more");
  if (postsEl) postsEl.innerHTML = "";
  if (moreBtn) moreBtn.hidden = true;
  if (!box) return;
  box.innerHTML = "Loading…";
  try {
    const pf = await api("/users/" + userId + "/portfolio");
    box.innerHTML = "";
    box.appendChild(portfolioDropdownEl(userId, "portfolio"));
    // Cover: full-bleed photo with a soft light gradient shadow
    // across the lower part; name + role sit over the shadow.
    const cover = document.createElement("div");
    cover.className = "pf-cover";
    if (pf.cover_file_id) {
      const img = document.createElement("img");
      img.src = mediaUrl(pf.cover_file_id);
      img.alt = "";
      cover.appendChild(img);
    } else {
      cover.classList.add("pf-cover-empty");
    }
    const shade = document.createElement("div");
    shade.className = "pf-shade";
    const nm = document.createElement("div");
    nm.className = "pf-name vname";
    const nmText = document.createElement("span");
    nmText.className = "vname-text";
    nmText.textContent = pf.first_name || "";
    nm.appendChild(nmText);
    if (pf.is_verified) nm.appendChild(verifiedBadge());
    const role = document.createElement("div");
    role.className = "pf-role";
    role.textContent = pf.role || "";
    shade.append(nm, role);
    cover.appendChild(shade);
    box.appendChild(cover);
    // Follow / Message — the same actions as the profile hero.
    const ownPf = me && userId === me.telegram_id;
    if (!ownPf) {
      const row = document.createElement("div");
      row.className = "pf-actions";
      const fBtn = document.createElement("button");
      fBtn.className = "pf-follow";
      fBtn.type = "button";
      const paintF = () => {
        fBtn.textContent = profileUser && profileUser.has_pending_request
          ? "Requested ✓"
          : (profileUser && profileUser.following ? "Unfollow" : "Follow");
      };
      paintF();
      fBtn.onclick = async () => {
        try {
          if (profileUser && profileUser.has_pending_request) {
            await api("/users/" + userId + "/follow-request",
                      { method: "DELETE" });
            profileUser.has_pending_request = false;
            paintF();
            return;
          }
          const r = await api("/users/" + userId + "/follow",
                              { method: "POST" });
          if (profileUser) {
            profileUser.following = r.following;
            profileUser.has_pending_request = !!r.requested;
          }
          paintF();
        } catch (e) { setStatus("Could not update follow."); }
      };
      const mBtn = document.createElement("button");
      mBtn.className = "pf-msg";
      mBtn.type = "button";
      mBtn.textContent = "💬 Message";
      mBtn.onclick = () => openChat(userId);
      row.append(fBtn, mBtn);
      box.appendChild(row);
    }
    // About.
    const aboutH = document.createElement("div");
    aboutH.className = "pf-sec-title";
    aboutH.textContent = "About";
    const about = document.createElement("p");
    about.className = "pf-about";
    about.textContent = pf.about || "No about yet.";
    box.append(aboutH, about);
    // Work — 2-column grid of sample cards (title under each).
    const workH = document.createElement("div");
    workH.className = "pf-sec-title";
    workH.textContent = "Work";
    box.appendChild(workH);
    const grid = document.createElement("div");
    grid.className = "pf-work-grid";
    (pf.items || []).forEach(it => {
      const card = document.createElement("div");
      card.className = "pf-work-card";
      const th = document.createElement("img");
      th.src = mediaUrl(it.image_file_id);
      th.alt = "";
      th.loading = "lazy";
      const ti = document.createElement("div");
      ti.className = "pf-work-title";
      ti.textContent = it.title || "";
      card.append(th, ti);
      grid.appendChild(card);
    });
    if (!(pf.items || []).length) {
      const none = document.createElement("p");
      none.className = "hint";
      none.textContent = "No work samples yet.";
      grid.appendChild(none);
    }
    box.appendChild(grid);
    if (ownPf) {
      const eBtn = document.createElement("button");
      eBtn.className = "wide";
      eBtn.textContent = "✏️ Edit portfolio";
      eBtn.onclick = () => openPortfolioEditor();
      box.appendChild(eBtn);
    }
    fitVerifiedNames(box);
    const sc = $("app-scroll");
    if (sc) sc.scrollTop = 0;
  } catch (e) {
    box.textContent = "Portfolio is not available.";
  }
}

// Pickers — everything comes from the member's own content:
// their post photos (cover + project thumbnails), their posts
// (post samples) and the public Design gallery (design samples).
async function portfolioPickPhotos(container, onPick, extraIds) {
  container.innerHTML = "Loading…";
  const seen = new Set();
  const btns = [];
  const addBtn = (fid) => {
    if (!fid || seen.has(fid)) return;
    seen.add(fid);
    const b = document.createElement("button");
    b.type = "button";
    const im = document.createElement("img");
    im.src = mediaUrl(fid);
    im.alt = "";
    im.loading = "lazy";
    b.appendChild(im);
    b.onclick = () => onPick(fid);
    btns.push(b);
  };
  (extraIds || []).forEach(addBtn);
  try {
    const d = await api("/users/" + me.telegram_id + "/posts");
    (d.posts || []).forEach(p => {
      if (p.thumb_file_id) addBtn(p.thumb_file_id);
      if (p.media_file_id) addBtn(p.media_file_id);
      (p.media || []).forEach(m => addBtn(m.file_id));
    });
  } catch (e) { /* picker keeps what it has */ }
  container.innerHTML = "";
  if (!btns.length) {
    container.textContent = "No photos yet — post one first.";
    return;
  }
  btns.forEach(b => container.appendChild(b));
}

async function portfolioPickPosts(container, onPick) {
  container.innerHTML = "Loading…";
  let rows = [];
  try {
    const d = await api("/users/" + me.telegram_id + "/posts");
    rows = (d.posts || []).filter(p => p.media_file_id
      || (p.media && p.media.length) || p.thumb_file_id);
  } catch (e) { rows = []; }
  container.innerHTML = "";
  if (!rows.length) {
    container.textContent = "No posts with photos yet.";
    return;
  }
  rows.forEach(p => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "pf-pick-post";
    const im = document.createElement("img");
    const fid = p.thumb_file_id || p.media_file_id
      || (p.media && p.media[0] && p.media[0].file_id) || "";
    im.src = mediaUrl(fid);
    im.alt = "";
    im.loading = "lazy";
    b.appendChild(im);
    const ti = document.createElement("div");
    ti.className = "pf-pick-title";
    ti.textContent = (p.caption || "").slice(0, 40) || "Post";
    b.appendChild(ti);
    b.onclick = () => onPick(p);
    container.appendChild(b);
  });
}

async function portfolioPickDesigns(container, onPick) {
  container.innerHTML = "Loading…";
  let rows = [];
  try {
    const d = await api("/designs?limit=20");
    rows = d.designs || [];
  } catch (e) { rows = []; }
  container.innerHTML = "";
  if (!rows.length) {
    container.textContent = "No designs yet.";
    return;
  }
  rows.forEach(dg => {
    const b = document.createElement("button");
    b.type = "button";
    const im = document.createElement("img");
    im.src = mediaUrl(dg.image_file_id);
    im.alt = "";
    im.loading = "lazy";
    b.appendChild(im);
    b.onclick = () => onPick(dg);
    container.appendChild(b);
  });
}

async function openPortfolioEditor() {
  const box = $("profile-box");
  if (!box || !me) return;
  profileTab = "portfolio";
  box.innerHTML = "Loading…";
  let pf = null;
  try {
    pf = await api("/me/portfolio");
  } catch (e) {
    box.textContent = "Could not load your portfolio.";
    return;
  }
  box.innerHTML = "";
  const back = document.createElement("button");
  back.className = "settings-back";
  back.type = "button";
  back.textContent = "‹ Portfolio";
  back.onclick = () => renderPortfolioTab(me.telegram_id);
  box.appendChild(back);
  const head = document.createElement("b");
  head.className = "settings-head";
  head.textContent = "🖼️ Edit portfolio";
  box.appendChild(head);
  // Enable toggle — saves immediately, like the Privacy toggle.
  const enRow = document.createElement("label");
  enRow.className = "privacy-row";
  const enChk = document.createElement("input");
  enChk.type = "checkbox";
  enChk.checked = !!pf.enabled;
  const enTx = document.createElement("span");
  enTx.textContent = "Show my portfolio — Profile/Portfolio dropdown appears on my profile.";
  enRow.append(enChk, enTx);
  box.appendChild(enRow);
  // Role + About.
  const roleIn = document.createElement("input");
  roleIn.type = "text";
  roleIn.maxLength = 100;
  roleIn.placeholder = "What you do — e.g. Graphic Designer & Photographer";
  roleIn.value = pf.role || "";
  const aboutIn = document.createElement("textarea");
  aboutIn.rows = 3;
  aboutIn.maxLength = 1000;
  aboutIn.placeholder = "About you…";
  aboutIn.value = pf.about || "";
  box.append(roleIn, aboutIn);
  // Cover photo — pick from your own photos.
  let coverFileId = pf.cover_file_id || null;
  const coverPrev = document.createElement("div");
  coverPrev.className = "pf-edit-cover";
  const paintCover = () => {
    coverPrev.innerHTML = "";
    if (coverFileId) {
      const im = document.createElement("img");
      im.src = mediaUrl(coverFileId);
      im.alt = "";
      coverPrev.appendChild(im);
    } else {
      coverPrev.textContent = "No cover photo yet.";
    }
  };
  paintCover();
  const coverBtn = document.createElement("button");
  coverBtn.className = "wide";
  coverBtn.textContent = "📷 Choose cover photo";
  const coverPick = document.createElement("div");
  coverPick.className = "pf-picker";
  coverBtn.onclick = () => {
    if (coverPick.children.length) { coverPick.innerHTML = ""; return; }
    portfolioPickPhotos(coverPick, (fid) => {
      coverFileId = fid;
      paintCover();
      coverPick.innerHTML = "";
    }, pf.photo_file_id ? [pf.photo_file_id] : []);
  };
  box.append(coverPrev, coverBtn, coverPick);
  // Save.
  const saveBtn = document.createElement("button");
  saveBtn.className = "wide btn";
  saveBtn.textContent = "Save portfolio";
  saveBtn.onclick = async () => {
    try {
      pf = await api("/me/portfolio", { method: "POST",
        body: JSON.stringify({ about: aboutIn.value,
                               role: roleIn.value,
                               cover_file_id: coverFileId,
                               enabled: enChk.checked }) });
      settingsPortfolio = pf;
      setStatus("Portfolio saved.");
      renderPortfolioTab(me.telegram_id);
    } catch (e) { setStatus("Could not save the portfolio."); }
  };
  box.appendChild(saveBtn);
  enChk.onchange = async () => {
    try {
      pf = await api("/me/portfolio", { method: "POST",
        body: JSON.stringify({ about: aboutIn.value,
                               role: roleIn.value,
                               cover_file_id: coverFileId,
                               enabled: enChk.checked }) });
      settingsPortfolio = pf;
      setStatus(enChk.checked ? "Portfolio is now visible on your profile." : "Portfolio hidden.");
    } catch (e) {
      enChk.checked = !!pf.enabled;
      setStatus("Could not change the portfolio setting.");
    }
  };
  // Work samples — list with move/remove, then add.
  const workH = document.createElement("b");
  workH.className = "settings-head";
  workH.textContent = "Work samples";
  box.appendChild(workH);
  const workList = document.createElement("div");
  workList.id = "pf-edit-list";
  box.appendChild(workList);
  const loadWork = () => {
    workList.innerHTML = "";
    (pf.items || []).forEach((it, idx) => {
      const row = document.createElement("div");
      row.className = "pf-edit-row";
      const th = document.createElement("img");
      th.src = mediaUrl(it.image_file_id);
      th.alt = "";
      const ti = document.createElement("span");
      ti.className = "pf-edit-title";
      ti.textContent = it.title || "";
      const up = document.createElement("button");
      up.textContent = "↑";
      up.disabled = idx === 0;
      up.onclick = () => moveWork(idx, -1);
      const dn = document.createElement("button");
      dn.textContent = "↓";
      dn.disabled = idx === pf.items.length - 1;
      dn.onclick = () => moveWork(idx, 1);
      const rm = document.createElement("button");
      rm.textContent = "✕";
      rm.onclick = async () => {
        try {
          await api("/me/portfolio/items/" + it.id, { method: "DELETE" });
          pf.items = pf.items.filter(x => x.id !== it.id);
          loadWork();
        } catch (e) { setStatus("Could not remove the sample."); }
      };
      row.append(th, ti, up, dn, rm);
      workList.appendChild(row);
    });
    if (!(pf.items || []).length) workList.textContent = "No work samples yet.";
  };
  const moveWork = async (idx, dir) => {
    const ids = pf.items.map(x => x.id);
    const j = idx + dir;
    if (j < 0 || j >= ids.length) return;
    const tmp = ids[idx]; ids[idx] = ids[j]; ids[j] = tmp;
    try {
      await api("/me/portfolio/items/reorder", { method: "POST",
        body: JSON.stringify({ item_ids: ids }) });
      const items = pf.items.slice();
      const t2 = items[idx]; items[idx] = items[j]; items[j] = t2;
      pf.items = items;
      loadWork();
    } catch (e) { setStatus("Could not reorder the samples."); }
  };
  loadWork();
  const addSample = async (payload) => {
    try {
      await api("/me/portfolio/items", { method: "POST",
        body: JSON.stringify(payload) });
      pf = await api("/me/portfolio");
      loadWork();
      setStatus("Work sample added.");
    } catch (e) { setStatus("Could not add the sample."); }
  };
  const addH = document.createElement("div");
  addH.className = "settings-sub";
  addH.textContent = "Add a work sample";
  box.appendChild(addH);
  const kindSel = document.createElement("select");
  ["post", "design", "project"].forEach(k => {
    const o = document.createElement("option");
    o.value = k;
    o.textContent = k === "post" ? "From one of my posts"
      : k === "design" ? "From the Design gallery"
      : "Project (my own photo)";
    kindSel.appendChild(o);
  });
  const titleIn = document.createElement("input");
  titleIn.type = "text";
  titleIn.maxLength = 100;
  titleIn.placeholder = "Project title";
  titleIn.hidden = true;
  const pickBtn = document.createElement("button");
  pickBtn.className = "wide";
  const addBox = document.createElement("div");
  addBox.className = "pf-picker";
  const paintAdd = () => {
    addBox.innerHTML = "";
    const kind = kindSel.value;
    titleIn.hidden = kind !== "project";
    if (kind === "post") {
      pickBtn.textContent = "📷 Choose one of my posts";
      pickBtn.onclick = () => portfolioPickPosts(addBox, async (p) => {
        await addSample({ kind: "post", ref_id: p.id,
                          title: titleIn.value });
        addBox.innerHTML = "";
      });
    } else if (kind === "design") {
      pickBtn.textContent = "🎨 Choose a design";
      pickBtn.onclick = () => portfolioPickDesigns(addBox, async (dg) => {
        await addSample({ kind: "design", ref_id: dg.id,
                          title: titleIn.value });
        addBox.innerHTML = "";
      });
    } else {
      pickBtn.textContent = "🖼️ Choose a photo";
      pickBtn.onclick = () => portfolioPickPhotos(addBox, async (fid) => {
        if (!titleIn.value.trim()) {
          setStatus("Give the project a title first.");
          return;
        }
        await addSample({ kind: "project", title: titleIn.value,
                          image_file_id: fid });
        addBox.innerHTML = "";
      }, pf.photo_file_id ? [pf.photo_file_id] : []);
    }
  };
  kindSel.onchange = paintAdd;
  paintAdd();
  box.append(kindSel, titleIn, pickBtn, addBox);
}

// ---------- Phase 201: Museum — the member's own 3D gallery -------
// Sidebar opens MY museum; a profile's Museum button opens THAT
// member's museum (view-only for visitors). Wall photos come from
// the owner's own posts/designs (no new upload path — same rule
// as the Portfolio); furniture comes from a built-in catalog.
// Three rooms, four wall frames + four floor spots each. The 3D
// walkthrough uses the vendored Three.js r149 (no CDN); when
// WebGL is missing the rooms fall back to a flat list with the
// same tap actions.
const MUSEUM_ROOMS = [
  { id: "entrance", name: "Entrance Gallery" },
  { id: "lounge", name: "Lounge" },
  { id: "family", name: "Family Room" },
];
const MUSEUM_FURNITURE = [
  { id: "chair", name: "Chair", icon: "🪑" },
  { id: "table", name: "Table", icon: "🪵" },
  { id: "lamp", name: "Lamp", icon: "💡" },
  { id: "plant", name: "Plant", icon: "🪴" },
  { id: "sofa", name: "Sofa", icon: "🛋️" },
  { id: "rug", name: "Rug", icon: "🟫" },
];
const MUSEUM_WALL_SLOTS = 4;
const MUSEUM_FLOOR_SLOTS = 4;
let museumOwnerId = null;
let museumData = null;
let museumRoom = "entrance";
let museumIsOwner = false;
let muScene = null;
let muYaw = 0;
let muPitch = -0.05;

function museumRoomItems(room) {
  if (!museumData || !museumData.rooms) return [];
  return museumData.rooms[room] || [];
}
function museumItemAt(room, kind, slot) {
  return museumRoomItems(room).find(
    it => it.kind === kind && it.slot === slot) || null;
}
function museumStepRoom(d) {
  const idx = MUSEUM_ROOMS.findIndex(r => r.id === museumRoom);
  museumRoom = MUSEUM_ROOMS[
    (idx + d + MUSEUM_ROOMS.length) % MUSEUM_ROOMS.length].id;
  renderMuseum();
}

async function openMuseum(ownerId) {
  museumOwnerId = ownerId;
  museumRoom = "entrance";
  museumData = null;
  museumIsOwner = !!(me && me.telegram_id === ownerId);
  showView("museum");
  const ownerEl = $("mu-owner");
  const statusEl = $("mu-status");
  if (ownerEl) ownerEl.textContent = "Loading the museum…";
  if (statusEl) statusEl.textContent = "";
  try {
    const path = museumIsOwner ? "/me/museum"
      : "/users/" + ownerId + "/museum";
    museumData = await api(path);
    renderMuseum();
  } catch (e) {
    if (ownerEl) ownerEl.textContent = "";
    if (statusEl) statusEl.textContent =
      "This museum isn't visible to you.";
    renderMuseumEmpty();
  }
}
async function reloadMuseum() {
  if (museumOwnerId === null) return;
  try {
    const path = museumIsOwner ? "/me/museum"
      : "/users/" + museumOwnerId + "/museum";
    museumData = await api(path);
    renderMuseum();
  } catch (e) { setStatus("Could not reload the museum."); }
}
function renderMuseumEmpty() {
  const tabs = $("mu-room-tabs");
  if (tabs) tabs.innerHTML = "";
  const chips = $("mu-chips");
  if (chips) chips.innerHTML = "";
  const fb = $("mu-fallback");
  if (fb) { fb.hidden = true; fb.innerHTML = ""; }
  const nameEl = $("mu-room-name");
  if (nameEl) nameEl.textContent = "";
  stopMuseum();
}
function renderMuseum() {
  const d = museumData;
  if (!d) return;
  // Owner line — the shared .vname rule: the name shrinks,
  // the tick never does (fitVerifiedNames, Phases 160/162).
  const ownerEl = $("mu-owner");
  if (ownerEl) {
    ownerEl.innerHTML = "";
    const nm = document.createElement("span");
    nm.className = "vname";
    const nmText = document.createElement("span");
    nmText.className = "vname-text";
    nmText.textContent = d.first_name || "Member";
    nm.appendChild(nmText);
    if (d.is_verified) nm.appendChild(verifiedBadge());
    const sub = document.createElement("span");
    sub.className = "muted";
    sub.textContent = (d.username ? " @" + d.username : "")
      + (museumIsOwner ? " · your museum" : " · museum");
    ownerEl.append(nm, sub);
    fitVerifiedNames(ownerEl);
  }
  const tabs = $("mu-room-tabs");
  if (tabs) {
    tabs.innerHTML = "";
    MUSEUM_ROOMS.forEach(r => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "mu-tab" + (r.id === museumRoom ? " active" : "");
      b.textContent = r.name;
      b.onclick = () => { museumRoom = r.id; renderMuseum(); };
      tabs.appendChild(b);
    });
  }
  const nameEl = $("mu-room-name");
  if (nameEl) {
    const r = MUSEUM_ROOMS.find(x => x.id === museumRoom);
    nameEl.textContent = r ? r.name : "";
  }
  const prev = $("mu-prev");
  if (prev) prev.onclick = () => museumStepRoom(-1);
  const next = $("mu-next");
  if (next) next.onclick = () => museumStepRoom(1);
  renderMuseumChips();
  renderMuseumFallback();
  buildMuseumScene();
}
function renderMuseumChips() {
  const box = $("mu-chips");
  if (!box) return;
  box.innerHTML = "";
  for (let s = 0; s < MUSEUM_WALL_SLOTS; s++) {
    const it = museumItemAt(museumRoom, "photo", s);
    const b = document.createElement("button");
    b.type = "button";
    b.className = "mu-chip";
    if (it && it.image_file_id) {
      const im = document.createElement("img");
      im.src = mediaUrl(it.image_file_id);
      im.alt = "Wall photo " + (s + 1);
      im.loading = "lazy";
      b.appendChild(im);
      const lb = document.createElement("span");
      lb.textContent = "🖼️ Frame " + (s + 1);
      b.appendChild(lb);
    } else {
      b.textContent = museumIsOwner ? "＋ Hang a photo" : "Empty frame";
    }
    b.onclick = () => museumFrameTap(s);
    box.appendChild(b);
  }
  for (let s = 0; s < MUSEUM_FLOOR_SLOTS; s++) {
    const it = museumItemAt(museumRoom, "furniture", s);
    const b = document.createElement("button");
    b.type = "button";
    b.className = "mu-chip";
    if (it) {
      const f = MUSEUM_FURNITURE.find(x => x.id === it.furniture_type);
      b.textContent = (f ? f.icon + " " + f.name : "Furniture")
        + " · spot " + (s + 1);
    } else {
      b.textContent = museumIsOwner ? "＋ Place furniture" : "Empty spot";
    }
    b.onclick = () => museumFloorTap(s);
    box.appendChild(b);
  }
}
function renderMuseumFallback() {
  const fb = $("mu-fallback");
  const stage = $("mu-stage");
  const nogl = $("mu-nogl");
  const has3D = muHas3D();
  if (stage) stage.hidden = !has3D;
  if (nogl) nogl.hidden = has3D;
  if (!fb) return;
  fb.hidden = has3D;
  if (has3D) { fb.innerHTML = ""; return; }
  fb.innerHTML = "";
  const room = MUSEUM_ROOMS.find(r => r.id === museumRoom);
  const h = document.createElement("div");
  h.className = "settings-sub";
  h.textContent = "Room: " + (room ? room.name : "");
  fb.appendChild(h);
  for (let s = 0; s < MUSEUM_WALL_SLOTS; s++) {
    const it = museumItemAt(museumRoom, "photo", s);
    const card = document.createElement("button");
    card.type = "button";
    card.className = "mu-fb-card";
    if (it && it.image_file_id) {
      const im = document.createElement("img");
      im.src = mediaUrl(it.image_file_id);
      im.alt = "Wall photo " + (s + 1);
      im.loading = "lazy";
      card.appendChild(im);
    } else {
      card.textContent = museumIsOwner ? "＋ Hang a photo" : "Empty frame";
    }
    card.onclick = () => museumFrameTap(s);
    fb.appendChild(card);
  }
  for (let s = 0; s < MUSEUM_FLOOR_SLOTS; s++) {
    const it = museumItemAt(museumRoom, "furniture", s);
    const card = document.createElement("button");
    card.type = "button";
    card.className = "mu-fb-card";
    if (it) {
      const f = MUSEUM_FURNITURE.find(x => x.id === it.furniture_type);
      card.textContent = (f ? f.icon + " " + f.name : "Furniture")
        + " · spot " + (s + 1);
    } else {
      card.textContent = museumIsOwner ? "＋ Place furniture" : "Empty spot";
    }
    card.onclick = () => museumFloorTap(s);
    fb.appendChild(card);
  }
}
// The vendored Three.js script is the only 3D dependency — no CDN.
// A device whose WebGL context cannot start throws inside the
// WebGLRenderer constructor, which buildMuseumScene catches and
// turns into the flat fallback below.
function muHas3D() {
  return typeof window !== "undefined" && !!window.THREE;
}
function muDragStart(ev) {
  if (!muScene) return;
  muScene.drag = { x: ev.clientX || 0, y: ev.clientY || 0 };
}
function muDragMove(ev) {
  if (!muScene || !muScene.drag) return;
  const dx = (ev.clientX || 0) - muScene.drag.x;
  const dy = (ev.clientY || 0) - muScene.drag.y;
  muScene.drag = { x: ev.clientX || 0, y: ev.clientY || 0 };
  muYaw = Math.max(-0.9, Math.min(0.9, muYaw - dx * 0.005));
  muPitch = Math.max(-0.35, Math.min(0.3, muPitch - dy * 0.004));
}
function muDragEnd() { if (muScene) muScene.drag = null; }
function muDisposeGroup(group) {
  if (!group || typeof group.traverse !== "function") return;
  group.traverse(o => {
    if (o.geometry && o.geometry.dispose) o.geometry.dispose();
    if (o.material) {
      const mats = Array.isArray(o.material) ? o.material : [o.material];
      mats.forEach(m => {
        if (m.map && m.map.dispose) m.map.dispose();
        if (m.dispose) m.dispose();
      });
    }
  });
}
function muFurniture(type) {
  const wood = c => new THREE.MeshStandardMaterial(
    { color: c, roughness: 0.85, metalness: 0 });
  const box = (w, h, d, c, x, y, z) => {
    const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), wood(c));
    m.position.set(x, y, z);
    return m;
  };
  const cyl = (rt, rb, h, c, x, y, z) => {
    const m = new THREE.Mesh(
      new THREE.CylinderGeometry(rt, rb, h, 12), wood(c));
    m.position.set(x, y, z);
    return m;
  };
  const g = new THREE.Group();
  if (type === "chair") {
    g.add(box(0.45, 0.06, 0.45, 0x6b4a2f, 0, 0.45, 0));
    g.add(box(0.45, 0.5, 0.05, 0x6b4a2f, 0, 0.72, -0.2));
    [[-0.19, -0.19], [0.19, -0.19], [-0.19, 0.19], [0.19, 0.19]]
      .forEach(p => g.add(cyl(0.025, 0.025, 0.45, 0x4a3525, p[0], 0.225, p[1])));
  } else if (type === "table") {
    g.add(box(1.2, 0.06, 0.7, 0x6b4a2f, 0, 0.72, 0));
    [[-0.55, -0.3], [0.55, -0.3], [-0.55, 0.3], [0.55, 0.3]]
      .forEach(p => g.add(cyl(0.03, 0.03, 0.72, 0x4a3525, p[0], 0.36, p[1])));
  } else if (type === "lamp") {
    g.add(cyl(0.16, 0.18, 0.04, 0x4a3525, 0, 0.02, 0));
    g.add(cyl(0.02, 0.02, 1.3, 0x8a6f4d, 0, 0.67, 0));
    const shade = new THREE.Mesh(
      new THREE.ConeGeometry(0.24, 0.28, 16, 1, true),
      new THREE.MeshStandardMaterial({ color: 0xf5e6c8, roughness: 0.9,
        metalness: 0, side: THREE.DoubleSide }));
    shade.position.set(0, 1.38, 0);
    g.add(shade);
    const bulb = new THREE.Mesh(new THREE.SphereGeometry(0.06, 12, 8),
      new THREE.MeshBasicMaterial({ color: 0xffe9b8 }));
    bulb.position.set(0, 1.28, 0);
    g.add(bulb);
  } else if (type === "plant") {
    g.add(cyl(0.18, 0.14, 0.3, 0xa44a3f, 0, 0.15, 0));
    [[0, 0.62, 0, 0.26], [-0.14, 0.5, 0.08, 0.18], [0.13, 0.52, -0.07, 0.19]]
      .forEach(p => {
        const leaf = new THREE.Mesh(
          new THREE.IcosahedronGeometry(p[3], 0), wood(0x4a7a3f));
        leaf.position.set(p[0], p[1], p[2]);
        g.add(leaf);
      });
  } else if (type === "sofa") {
    g.add(box(1.8, 0.35, 0.8, 0x7a6a5f, 0, 0.28, 0));
    g.add(box(1.8, 0.5, 0.2, 0x7a6a5f, 0, 0.65, -0.3));
    g.add(box(0.2, 0.35, 0.8, 0x6b5d52, -0.8, 0.55, 0));
    g.add(box(0.2, 0.35, 0.8, 0x6b5d52, 0.8, 0.55, 0));
    g.add(box(0.78, 0.12, 0.62, 0x8a7a6e, -0.42, 0.5, 0.04));
    g.add(box(0.78, 0.12, 0.62, 0x8a7a6e, 0.42, 0.5, 0.04));
  } else if (type === "rug") {
    const rug = new THREE.Mesh(new THREE.CircleGeometry(0.95, 24),
      new THREE.MeshStandardMaterial({ color: 0xa44a3f, roughness: 1,
        metalness: 0 }));
    rug.rotation.x = -Math.PI / 2;
    rug.position.y = 0.015;
    g.add(rug);
  } else { return null; }
  return g;
}
function muBuildRoom() {
  if (!muScene) return;
  if (muScene.roomGroup) {
    muScene.scene.remove(muScene.roomGroup);
    muDisposeGroup(muScene.roomGroup);
  }
  const g = new THREE.Group();
  const mat = (c, extra) => new THREE.MeshStandardMaterial(
    Object.assign({ color: c, roughness: 0.9, metalness: 0 }, extra || {}));
  // Warm wood floor, warm plaster walls — the reference video's
  // bar / lounge palette, kept dark enough for the photos.
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(8, 6), mat(0x8a6f4d));
  floor.rotation.x = -Math.PI / 2;
  g.add(floor);
  const wallMat = mat(0xe8dcc8);
  const back = new THREE.Mesh(new THREE.PlaneGeometry(8, 3.2), wallMat);
  back.position.set(0, 1.6, -3);
  g.add(back);
  const left = new THREE.Mesh(new THREE.PlaneGeometry(6, 3.2), wallMat);
  left.rotation.y = Math.PI / 2;
  left.position.set(-4, 1.6, 0);
  g.add(left);
  const right = new THREE.Mesh(new THREE.PlaneGeometry(6, 3.2), wallMat);
  right.rotation.y = -Math.PI / 2;
  right.position.set(4, 1.6, 0);
  g.add(right);
  // Four wall frames: slots 0-1 on the back wall, 2 on the left,
  // 3 on the right. A hung photo becomes the frame's texture.
  const frameSpots = [
    { x: -2, y: 1.7, z: -2.96, ry: 0 },
    { x: 2, y: 1.7, z: -2.96, ry: 0 },
    { x: -3.96, y: 1.7, z: -1.2, ry: Math.PI / 2 },
    { x: 3.96, y: 1.7, z: -1.2, ry: -Math.PI / 2 },
  ];
  for (let s = 0; s < MUSEUM_WALL_SLOTS; s++) {
    const sp = frameSpots[s];
    const fg = new THREE.Group();
    fg.add(new THREE.Mesh(new THREE.BoxGeometry(1.15, 1.45, 0.06),
      mat(0x4a3525, { roughness: 0.6 })));
    const it = museumItemAt(museumRoom, "photo", s);
    let inner;
    if (it && it.image_file_id) {
      let tex = null;
      try { tex = new THREE.TextureLoader().load(mediaUrl(it.image_file_id)); }
      catch (e) { tex = null; }
      inner = new THREE.Mesh(new THREE.PlaneGeometry(0.95, 1.25),
        tex ? new THREE.MeshBasicMaterial({ map: tex }) : mat(0xf6f1e7));
    } else {
      inner = new THREE.Mesh(new THREE.PlaneGeometry(0.95, 1.25),
        mat(0xf6f1e7));
    }
    inner.position.z = 0.04;
    fg.add(inner);
    fg.position.set(sp.x, sp.y, sp.z);
    fg.rotation.y = sp.ry;
    g.add(fg);
  }
  const floorSpots = [
    { x: -2.2, z: -0.6 }, { x: 2.2, z: -0.6 },
    { x: -2.2, z: 1.3 }, { x: 2.2, z: 1.3 },
  ];
  for (let s = 0; s < MUSEUM_FLOOR_SLOTS; s++) {
    const it = museumItemAt(museumRoom, "furniture", s);
    if (!it) continue;
    const fg = muFurniture(it.furniture_type);
    if (!fg) continue;
    fg.position.set(floorSpots[s].x, 0, floorSpots[s].z);
    g.add(fg);
  }
  muScene.scene.add(g);
  muScene.roomGroup = g;
}
function buildMuseumScene() {
  const stage = $("mu-stage");
  const cv = $("mu-canvas");
  if (!stage || !cv) return;
  if (!muHas3D()) { stopMuseum(); renderMuseumFallback(); return; }
  if (!muScene) {
    let renderer;
    try {
      renderer = new THREE.WebGLRenderer({ canvas: cv, antialias: true });
    } catch (e) { stopMuseum(); renderMuseumFallback(); return; }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x241c14);
    scene.fog = new THREE.Fog(0x241c14, 9, 18);
    const camera = new THREE.PerspectiveCamera(62, 4 / 3, 0.1, 60);
    camera.position.set(0, 1.6, 2.3);
    camera.rotation.order = "YXZ";
    scene.add(new THREE.HemisphereLight(0xfff2df, 0x5a4632, 0.9));
    const warm1 = new THREE.PointLight(0xffd9a0, 0.9, 12);
    warm1.position.set(-2.4, 2.9, 1.2);
    scene.add(warm1);
    const warm2 = new THREE.PointLight(0xffd9a0, 0.9, 12);
    warm2.position.set(2.4, 2.9, 1.2);
    scene.add(warm2);
    muScene = { renderer, scene, camera, raf: 0, roomGroup: null,
      drag: null, active: true };
    cv.addEventListener("pointerdown", muDragStart);
    cv.addEventListener("pointermove", muDragMove);
    cv.addEventListener("pointerup", muDragEnd);
    cv.addEventListener("pointercancel", muDragEnd);
    const loop = () => {
      if (!muScene || !muScene.active) return;
      if (!document.hidden && currentView === "museum") {
        muScene.camera.rotation.y = muYaw;
        muScene.camera.rotation.x = muPitch;
        muScene.renderer.render(muScene.scene, muScene.camera);
      }
      muScene.raf = requestAnimationFrame(loop);
    };
    muScene.raf = requestAnimationFrame(loop);
  }
  muBuildRoom();
  const w = stage.clientWidth || 360;
  const h = Math.round(w * 0.62);
  try {
    muScene.renderer.setSize(w, h, false);
    muScene.camera.aspect = w / h;
    muScene.camera.updateProjectionMatrix();
  } catch (e) { /* stub renderers may not size — the loop still runs */ }
}
function stopMuseum() {
  if (!muScene) return;
  muScene.active = false;
  if (muScene.raf) cancelAnimationFrame(muScene.raf);
  try { muDisposeGroup(muScene.roomGroup); } catch (e) {}
  try { muScene.renderer.dispose(); } catch (e) {}
  const cv = $("mu-canvas");
  if (cv) {
    cv.removeEventListener("pointerdown", muDragStart);
    cv.removeEventListener("pointermove", muDragMove);
    cv.removeEventListener("pointerup", muDragEnd);
    cv.removeEventListener("pointercancel", muDragEnd);
  }
  muScene = null;
}
function openMuseumSheet(title, build) {
  const sheet = $("mu-sheet");
  if (!sheet) return;
  sheet.innerHTML = "";
  sheet.hidden = false;
  const head = document.createElement("div");
  head.className = "mu-sheet-head";
  const t = document.createElement("span");
  t.textContent = title;
  const x = document.createElement("button");
  x.type = "button";
  x.className = "mu-sheet-x";
  x.textContent = "✕";
  x.onclick = closeMuseumSheet;
  head.append(t, x);
  sheet.appendChild(head);
  const body = document.createElement("div");
  body.className = "mu-sheet-body";
  sheet.appendChild(body);
  build(body);
  updateBackButton();
}
function closeMuseumSheet() {
  const sheet = $("mu-sheet");
  if (!sheet) return;
  sheet.hidden = true;
  sheet.innerHTML = "";
  updateBackButton();
}
async function museumSaveItem(payload) {
  await api("/me/museum/items", { method: "POST",
    body: JSON.stringify(payload) });
}
async function museumRemoveItem(itemId) {
  try {
    await api("/me/museum/items/" + itemId, { method: "DELETE" });
    closeMuseumSheet();
    await reloadMuseum();
    setStatus("Removed.");
  } catch (e) { setStatus("Could not remove it."); }
}
function museumFrameTap(slot) {
  const it = museumItemAt(museumRoom, "photo", slot);
  if (!it) {
    if (!museumIsOwner) { setStatus("This frame is empty."); return; }
    museumPickPhoto(slot);
    return;
  }
  openMuseumSheet("🖼️ Frame " + (slot + 1), body => {
    const viewBtn = document.createElement("button");
    viewBtn.type = "button";
    viewBtn.className = "wide";
    viewBtn.textContent = "View photo";
    viewBtn.onclick = () => {
      closeMuseumSheet();
      openPhotoViewer(it.image_file_id, "Museum photo");
    };
    body.appendChild(viewBtn);
    if (!museumIsOwner) return;
    const repBtn = document.createElement("button");
    repBtn.type = "button";
    repBtn.className = "wide";
    repBtn.textContent = "Replace photo";
    repBtn.onclick = () => museumPickPhoto(slot);
    body.appendChild(repBtn);
    const rmBtn = document.createElement("button");
    rmBtn.type = "button";
    rmBtn.className = "wide";
    rmBtn.textContent = "Remove from wall";
    rmBtn.onclick = async () => { await museumRemoveItem(it.id); };
    body.appendChild(rmBtn);
  });
}
function museumFloorTap(slot) {
  const it = museumItemAt(museumRoom, "furniture", slot);
  if (!it) {
    if (!museumIsOwner) {
      setStatus("Only the owner can decorate this museum.");
      return;
    }
    openMuseumSheet("Place furniture — spot " + (slot + 1), body => {
      MUSEUM_FURNITURE.forEach(f => {
        const b = document.createElement("button");
        b.type = "button";
        b.className = "wide mu-cat-row";
        b.textContent = f.icon + " " + f.name;
        b.onclick = async () => {
          try {
            await museumSaveItem({ room: museumRoom, kind: "furniture",
              slot, furniture_type: f.id });
            closeMuseumSheet();
            await reloadMuseum();
            setStatus(f.name + " placed.");
          } catch (e) { setStatus("Could not place the furniture."); }
        };
        body.appendChild(b);
      });
    });
    return;
  }
  if (!museumIsOwner) {
    setStatus("Only the owner can decorate this museum.");
    return;
  }
  const f = MUSEUM_FURNITURE.find(x => x.id === it.furniture_type);
  openMuseumSheet((f ? f.icon + " " + f.name : "Furniture")
    + " — spot " + (slot + 1), body => {
    const rmBtn = document.createElement("button");
    rmBtn.type = "button";
    rmBtn.className = "wide";
    rmBtn.textContent = "Remove it";
    rmBtn.onclick = async () => { await museumRemoveItem(it.id); };
    body.appendChild(rmBtn);
  });
}
function museumPickPhoto(slot) {
  openMuseumSheet("Hang a photo — frame " + (slot + 1), body => {
    const save = async payload => {
      try {
        await museumSaveItem(Object.assign(
          { room: museumRoom, kind: "photo", slot }, payload));
        closeMuseumSheet();
        await reloadMuseum();
        setStatus("Photo hung on the wall.");
      } catch (e) { setStatus("Could not hang the photo."); }
    };
    const mkH = txt => {
      const h = document.createElement("div");
      h.className = "settings-sub";
      h.textContent = txt;
      body.appendChild(h);
    };
    mkH("From one of my posts");
    const postBox = document.createElement("div");
    postBox.className = "pf-picker";
    body.appendChild(postBox);
    portfolioPickPosts(postBox, async p => {
      const fid = p.type === "video" ? p.thumb_file_id : p.media_file_id;
      if (!fid) { setStatus("That post has no photo to hang."); return; }
      await save({ ref_kind: "post", ref_id: p.id });
    });
    mkH("From the Design gallery");
    const dgBox = document.createElement("div");
    dgBox.className = "pf-picker";
    body.appendChild(dgBox);
    portfolioPickDesigns(dgBox, async dg => {
      await save({ ref_kind: "design", ref_id: dg.id });
    });
    mkH("From my photos");
    const phBox = document.createElement("div");
    phBox.className = "pf-picker";
    body.appendChild(phBox);
    portfolioPickPhotos(phBox, async fid => {
      await save({ image_file_id: fid });
    });
  });
}


async function loadProfilePosts(reset) {
  try {
    const url = "/users/" + profileId + "/posts" +
      (reset || !profileCursor ? "" : "?cursor=" + profileCursor);
    const data = await api(url);
    // Phase 136: the server locks a private account's posts
    // for non-followers — show the lock, not an error.
    if (data.locked) {
      if (reset) $("profile-posts").innerHTML = "";
      const lock = document.createElement("div");
      lock.className = "card private-lock";
      lock.textContent = "🔒 This account is private — follow to see their posts.";
      $("profile-posts").appendChild(lock);
      $("profile-more").hidden = true;
      return;
    }
    if (reset) $("profile-posts").innerHTML = "";
    data.posts.forEach(p => $("profile-posts").appendChild(postCard(p)));
    profileCursor = data.next_cursor;
    $("profile-more").hidden = !profileCursor;
  } catch (e) { setStatus("Could not load posts."); }
}

async function myExtras() {
  const wrap = document.createElement("div");
  wrap.className = "extras";
  // Phase 144 (owner): myExtras no longer renders on Me — it
  // renders inside Settings only. The cards are grouped by
  // headings (Creator / Library / Posts / Social / Account);
  // Theme, Data Control and Rain live in their own Settings
  // sections, not here.
  const creatorHead = document.createElement("b");
  creatorHead.className = "settings-head";
  creatorHead.textContent = "⭐ Points & creator";
  wrap.appendChild(creatorHead);
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
      "payout": ["💸", "Payout"],
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
    // Phase 124 (owner): the history was one big row per entry —
    // long, jumbled, space-hungry. Now: grouped by day (newest
    // first, "Today" / "Yesterday" / date), compact one-line rows,
    // filter chips per reason type, and "Show more" paging (the
    // server caps at 20 rows; /me/points?before=<id> fetches older
    // ones). Grouping only re-orders — no entry is ever dropped.
    const phState = { all: pts.entries.slice(), filter: "all",
                      shown: 20, more: pts.entries.length === 20 };
    const phWrap = document.createElement("div");
    phWrap.className = "ph-wrap";
    card.appendChild(phWrap);
    const phDayLabel = (d) => {
      const today = new Date(), yest = new Date();
      yest.setDate(today.getDate() - 1);
      if (d.toDateString() === today.toDateString()) return "Today";
      if (d.toDateString() === yest.toDateString()) return "Yesterday";
      const opts = { day: "numeric", month: "short" };
      if (d.getFullYear() !== today.getFullYear()) opts.year = "numeric";
      return d.toLocaleDateString(undefined, opts);
    };
    const renderPh = () => {
      phWrap.innerHTML = "";
      const list = phState.all.filter(e =>
        phState.filter === "all" || e.reason === phState.filter);
      const seen = [];
      list.forEach(e => {
        if (seen.indexOf(e.reason) < 0) seen.push(e.reason);
      });
      const chips = document.createElement("div");
      chips.className = "ph-chips";
      const mkChip = (key, label) => {
        const ch = document.createElement("button");
        ch.className = "ph-chip" +
          (phState.filter === key ? " active" : "");
        ch.textContent = label;
        ch.onclick = () => {
          phState.filter = key; phState.shown = 20; renderPh();
        };
        chips.appendChild(ch);
      };
      mkChip("all", "All");
      seen.forEach(r => mkChip(r, (REASON_META[r] || ["⭐", r])[1]));
      phWrap.appendChild(chips);
      let lastDay = "";
      list.slice(0, phState.shown).forEach(e => {
        const dt = e.created_at ? new Date(e.created_at) : null;
        const day = dt ? dt.toDateString() : "";
        if (day !== lastDay) {
          lastDay = day;
          const hd = document.createElement("div");
          hd.className = "ph-day";
          hd.textContent = dt ? phDayLabel(dt) : "Unknown date";
          phWrap.appendChild(hd);
        }
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
        if (dt) {
          const when = document.createElement("span");
          when.className = "ph-when";
          when.textContent = " · " + dt.toLocaleDateString(undefined,
            { day: "numeric", month: "short" }) + ", " +
            dt.toLocaleTimeString(undefined,
              { hour: "numeric", minute: "2-digit" });
          lb.appendChild(when);
        }
        main.appendChild(lb);
        const amt = document.createElement("span");
        amt.className = "ph-amt " + (e.amount >= 0 ? "plus" : "minus");
        amt.textContent = (e.amount >= 0 ? "+" : "") + e.amount;
        rowEl.append(ic, main, amt);
        phWrap.appendChild(rowEl);
      });
      const hiddenCount = list.length - phState.shown;
      if (hiddenCount > 0 || phState.more) {
        const more = document.createElement("button");
        more.className = "ph-more btn";
        more.textContent = hiddenCount > 0
          ? "Show more (" + hiddenCount + " more)" : "Show more";
        more.onclick = async () => {
          if (hiddenCount > 0) { phState.shown += 20; renderPh(); return; }
          more.disabled = true;
          more.textContent = "Loading…";
          try {
            const oldest = phState.all[phState.all.length - 1];
            const next = await api("/me/points?before=" + oldest.id);
            phState.all = phState.all.concat(next.entries || []);
            phState.more = (next.entries || []).length === 20;
            phState.shown += 20;
          } catch (e) { setStatus("Could not load older entries."); }
          renderPh();
        };
        phWrap.appendChild(more);
      }
      if (!list.length) {
        const empty = document.createElement("div");
        empty.className = "ph-empty";
        empty.textContent = "No entries of this type yet.";
        phWrap.appendChild(empty);
      }
    };
    renderPh();
    wrap.appendChild(card);
    // Phase 133: My tips — Stars sent and received.
    const tipsBtn = document.createElement("button");
    tipsBtn.className = "wide";
    tipsBtn.textContent = "⭐ My tips";
    const tipsBox = document.createElement("div");
    tipsBox.className = "card tips-card";
    tipsBox.hidden = true;
    let tipsLoaded = false;
    tipsBtn.onclick = async () => {
      tipsBox.hidden = !tipsBox.hidden;
      if (tipsBox.hidden || tipsLoaded) return;
      tipsLoaded = true;
      try {
        const t = await api("/me/tips");
        const mkList = (title, rows, other) => {
          const h = document.createElement("div");
          h.className = "tips-head";
          h.textContent = title;
          tipsBox.appendChild(h);
          if (!rows.length) {
            const e = document.createElement("div");
            e.className = "hint";
            e.textContent = "Nothing yet.";
            tipsBox.appendChild(e);
            return;
          }
          rows.forEach(r => {
            const row = document.createElement("div");
            row.className = "tips-row";
            row.textContent = (other === "to" ? r.to_name
              : r.from_name) + " · " + r.amount_stars + " ⭐";
            tipsBox.appendChild(row);
          });
        };
        mkList("Received", t.received, "from");
        mkList("Sent", t.sent, "to");
      } catch (e) { tipsBox.textContent = "Could not load tips."; }
    };
    wrap.append(tipsBtn, tipsBox);
    // Phase 134: My insights — totals across your posts plus
    // your top 5 posts by views; tap a post to open it.
    const insBtn = document.createElement("button");
    insBtn.className = "wide";
    insBtn.textContent = "📊 My insights";
    const insBox = document.createElement("div");
    insBox.className = "card ins-card";
    insBox.hidden = true;
    let insLoaded = false;
    insBtn.onclick = async () => {
      insBox.hidden = !insBox.hidden;
      if (insBox.hidden || insLoaded) return;
      insLoaded = true;
      try {
        const ins = await api("/me/insights");
        const t = ins.totals;
        const head = document.createElement("div");
        head.className = "ins-totals";
        [["👁", t.views, "Views"], ["🤍", t.likes, "Likes"],
         ["💬", t.comments, "Comments"],
         ["📝", t.posts, "Posts"],
         ["⭐", t.tips_stars, "Tips"]].forEach(([ic, n, label]) => {
          const cell = document.createElement("div");
          cell.className = "ins-total";
          const v = document.createElement("div");
          v.className = "ins-num";
          v.textContent = ic + " " + n;
          const l = document.createElement("div");
          l.className = "ins-label";
          l.textContent = label;
          cell.append(v, l);
          head.appendChild(cell);
        });
        insBox.appendChild(head);
        const h = document.createElement("div");
        h.className = "tips-head";
        h.textContent = "Top posts";
        insBox.appendChild(h);
        if (!ins.top_posts.length) {
          const e = document.createElement("div");
          e.className = "hint";
          e.textContent = "No posts yet.";
          insBox.appendChild(e);
        }
        ins.top_posts.forEach(tp => {
          const r = document.createElement("button");
          r.className = "sheet-row ins-top-row";
          r.textContent = "👁 " + tp.views + " · 🤍 " + tp.likes +
            " — " + (tp.caption_excerpt || "(no caption)");
          r.onclick = () => openTopPost(tp.id);
          insBox.appendChild(r);
        });
      } catch (e) { insBox.textContent = "Could not load insights."; }
    };
    wrap.append(insBtn, insBox);
    // Phase 137: My level — current level, progress to the
    // next, and the full badge list (earned + locked). Fetched
    // fresh from your own profile so points earned this session
    // already count.
    const lvlBtn = document.createElement("button");
    lvlBtn.className = "wide";
    lvlBtn.textContent = "🏆 My level";
    const lvlBox = document.createElement("div");
    lvlBox.className = "card level-card";
    lvlBox.hidden = true;
    let lvlLoaded = false;
    lvlBtn.onclick = async () => {
      lvlBox.hidden = !lvlBox.hidden;
      if (lvlBox.hidden || lvlLoaded) return;
      lvlLoaded = true;
      try {
        const prof = await api("/users/" + me.telegram_id);
        lvlBox.appendChild(renderLevelBlock(prof.level, prof.badges));
      } catch (e) { lvlBox.textContent = "Could not load your level."; }
    };
    wrap.append(lvlBtn, lvlBox);

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
  const libHead = document.createElement("b");
  libHead.className = "settings-head";
  libHead.textContent = "🔖 Library";
  wrap.appendChild(libHead);
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
  // Phase 123: My drafts — unfinished posts saved from the
  // composer. Resume loads the text back into the composer,
  // Publish posts it (and earns its points), Delete drops it.
  const postsHead = document.createElement("b");
  postsHead.className = "settings-head";
  postsHead.textContent = "📝 Posts";
  wrap.appendChild(postsHead);
  const draftsBtn = document.createElement("button");
  draftsBtn.className = "wide";
  draftsBtn.textContent = "📝 My drafts";
  const draftsBox = document.createElement("div");
  draftsBox.className = "drafts-box";
  draftsBox.hidden = true;
  const loadDrafts = async () => {
    draftsBox.innerHTML = "Loading…";
    try {
      const data = await api("/drafts");
      draftsBox.innerHTML = "";
      if (!data.drafts.length) {
        draftsBox.textContent = "No drafts yet — write something in the composer and tap 💾 Save draft.";
        return;
      }
      data.drafts.forEach(d => {
        const rowEl = document.createElement("div");
        rowEl.className = "draft-row";
        const tx = document.createElement("span");
        tx.className = "draft-text";
        tx.textContent = (d.text || (d.media_type ? "📷 " + d.media_type : "…")).slice(0, 120);
        rowEl.appendChild(tx);
        const resume = document.createElement("button");
        resume.textContent = "Resume";
        resume.onclick = () => {
          $("composer-text").value = d.text || "";
          showView("feed");
          setTab("explore");
          window.scrollTo(0, 0);
          $("composer-text").focus();
        };
        const pub = document.createElement("button");
        pub.textContent = "Publish";
        pub.onclick = async () => {
          try {
            await api("/drafts/" + d.id + "/publish", { method: "POST" });
            setStatus("Draft published 📝");
            loadDrafts();
            loadMe().catch(() => {});
          } catch (e) { setStatus("Could not publish the draft."); }
        };
        const del = document.createElement("button");
        del.textContent = "Delete";
        del.onclick = async () => {
          try {
            await api("/drafts/" + d.id, { method: "DELETE" });
            loadDrafts();
          } catch (e) { setStatus("Could not delete the draft."); }
        };
        rowEl.append(resume, pub, del);
        draftsBox.appendChild(rowEl);
      });
    } catch (e) { draftsBox.textContent = "Could not load drafts."; }
  };
  draftsBtn.onclick = () => {
    draftsBox.hidden = !draftsBox.hidden;
    if (!draftsBox.hidden) loadDrafts();
  };
  wrap.appendChild(draftsBtn);
  wrap.appendChild(draftsBox);
  // Phase 135: Scheduled posts — what is queued, what went out,
  // what failed (with the reason), and Cancel for pending rows.
  const schedBtn = document.createElement("button");
  schedBtn.className = "wide";
  schedBtn.textContent = "📅 Scheduled";
  const schedBox = document.createElement("div");
  schedBox.className = "drafts-box";
  schedBox.hidden = true;
  const loadScheduled = async () => {
    schedBox.innerHTML = "Loading…";
    try {
      const data = await api("/scheduled-posts");
      schedBox.innerHTML = "";
      if (!data.scheduled_posts.length) {
        schedBox.textContent = "Nothing scheduled — write something in the composer and tap 🕐 Schedule.";
        return;
      }
      data.scheduled_posts.forEach(s => {
        const rowEl = document.createElement("div");
        rowEl.className = "draft-row";
        const tx = document.createElement("span");
        tx.className = "draft-text";
        const when = new Date(s.scheduled_at).toLocaleString();
        const st = s.status === "pending" ? "⏳ Pending" :
                   s.status === "posted" ? "✅ Posted" :
                   s.status === "failed" ? "❌ Failed" : "🚫 Cancelled";
        tx.textContent = st + " · " + when + " — " +
          (s.text || (s.media_type ? "📷 " + s.media_type : "…")).slice(0, 100);
        if (s.status === "failed" && s.error) {
          tx.textContent += " (" + s.error + ")";
        }
        rowEl.appendChild(tx);
        if (s.status === "pending") {
          const cancel = document.createElement("button");
          cancel.textContent = "Cancel";
          cancel.onclick = async () => {
            try {
              await api("/scheduled-posts/" + s.id, { method: "DELETE" });
              loadScheduled();
            } catch (e) { setStatus("Could not cancel."); }
          };
          rowEl.appendChild(cancel);
        }
        schedBox.appendChild(rowEl);
      });
    } catch (e) { schedBox.textContent = "Could not load scheduled posts."; }
  };
  schedBtn.onclick = () => {
    schedBox.hidden = !schedBox.hidden;
    if (!schedBox.hidden) loadScheduled();
  };
  wrap.appendChild(schedBtn);
  wrap.appendChild(schedBox);
  // Phase 136: Follow requests — people waiting to follow your
  // private account. Accept lets them in, Reject turns them away.
  const socHead = document.createElement("b");
  socHead.className = "settings-head";
  socHead.textContent = "👥 Social";
  wrap.appendChild(socHead);
  const frBtn = document.createElement("button");
  frBtn.className = "wide";
  frBtn.textContent = "👥 Follow requests";
  const frBox = document.createElement("div");
  frBox.className = "drafts-box";
  frBox.hidden = true;
  const loadFollowRequests = async () => {
    frBox.innerHTML = "Loading…";
    try {
      const data = await api("/me/follow-requests");
      frBox.innerHTML = "";
      if (!data.follow_requests.length) {
        frBox.textContent = "No follow requests — turn on 🔒 Private account and requests will show up here.";
        return;
      }
      data.follow_requests.forEach(fr => {
        const rowEl = document.createElement("div");
        rowEl.className = "draft-row";
        const tx = document.createElement("span");
        tx.className = "draft-text";
        tx.textContent = (fr.first_name || "?") +
          (fr.username ? " (@" + fr.username + ")" : "");
        rowEl.appendChild(tx);
        const ok = document.createElement("button");
        ok.textContent = "Accept";
        ok.onclick = async () => {
          try {
            await api("/follow-requests/" + fr.id + "/accept", { method: "POST" });
            setStatus("Follow request accepted 👥");
            loadFollowRequests();
          } catch (e) { setStatus("Could not accept the request."); }
        };
        const no = document.createElement("button");
        no.textContent = "Reject";
        no.onclick = async () => {
          try {
            await api("/follow-requests/" + fr.id + "/reject", { method: "POST" });
            loadFollowRequests();
          } catch (e) { setStatus("Could not reject the request."); }
        };
        rowEl.append(ok, no);
        frBox.appendChild(rowEl);
      });
      frBtn.textContent = "👥 Follow requests (" + data.follow_requests.length + ")";
    } catch (e) { frBox.textContent = "Could not load follow requests."; }
  };
  frBtn.onclick = () => {
    frBox.hidden = !frBox.hidden;
    if (!frBox.hidden) loadFollowRequests();
  };
  wrap.appendChild(frBtn);
  wrap.appendChild(frBox);
  // Show the pending count on the button without opening it.
  api("/me/follow-requests").then(d => {
    if (d.follow_requests && d.follow_requests.length) {
      frBtn.textContent = "👥 Follow requests (" + d.follow_requests.length + ")";
    }
  }).catch(() => {});
  // Phase 140: Hashtags I follow — each followed tag with its
  // live post count, and an Unfollow button per row.
  const htagBtn = document.createElement("button");
  htagBtn.className = "wide";
  htagBtn.textContent = "🏷️ Hashtags I follow";
  const htagBox = document.createElement("div");
  htagBox.className = "card hashtag-card";
  htagBox.hidden = true;
  const renderHtagList = async () => {
    htagBox.innerHTML = "";
    try {
      const mine = await api("/me/hashtags");
      if (!mine.hashtags.length) {
        const e = document.createElement("div");
        e.className = "hint";
        e.textContent = "No hashtags followed yet — tap any #tag " +
          "in a post or search to follow it.";
        htagBox.appendChild(e);
        return;
      }
      mine.hashtags.forEach(h => {
        const row = document.createElement("div");
        row.className = "tips-row hashtag-row";
        const label = document.createElement("span");
        label.textContent = "#" + h.tag + " · " + h.count + " posts";
        const un = document.createElement("button");
        un.textContent = "Unfollow";
        un.onclick = async () => {
          try {
            await api("/hashtags/" + h.tag + "/follow",
                      { method: "DELETE" });
            followedTags.delete(h.tag);
            renderHtagList();
          } catch (e) { setStatus("Could not unfollow #" + h.tag + "."); }
        };
        row.append(label, un);
        htagBox.appendChild(row);
      });
    } catch (e) { htagBox.textContent = "Could not load hashtags."; }
  };
  htagBtn.onclick = async () => {
    htagBox.hidden = !htagBox.hidden;
    if (htagBox.hidden) return;
    renderHtagList();
  };
  wrap.append(htagBtn, htagBox);
  const acctHead = document.createElement("b");
  acctHead.className = "settings-head";
  acctHead.textContent = "💰 Account";
  wrap.appendChild(acctHead);
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
    loadPayoutBox(card, mon);
    wrap.appendChild(card);
  } catch (e) { /* monetization card is optional decoration */ }
  try {
    // Phase 22: blue-tick verification card. Phase 117 (owner):
    // TWO conditions, either one qualifies — 50 qualified
    // referrals or 1,000 followers; the admin reviews them.
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
    const mkRow = (done, label, have, need) => {
      const row = document.createElement("div");
      row.className = "mon-row";
      const left = document.createElement("span");
      left.textContent = (done ? "✅ " : "⬜ ") + label;
      const right = document.createElement("span");
      right.className = done ? "done" : "";
      right.textContent = have + " / " + need;
      row.append(left, right);
      card.appendChild(row);
    };
    mkRow(ver.followers >= ver.required,
          "👥 Followers for the blue tick",
          ver.followers, ver.required);
    mkRow(ver.referrals >= ver.referrals_required,
          "🔗 Referrals for the blue tick",
          ver.referrals, ver.referrals_required);
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
      const metHow = (ver.met || []).includes("referrals") &&
        (ver.met || []).includes("followers")
        ? "with 1,000 followers and 50 referrals"
        : (ver.met || []).includes("referrals")
        ? "with 50 referrals"
        : "with 1,000 followers";
      note.textContent = (ver.last_status === "rejected"
        ? "Your last application was not approved. You may apply again. "
        : "") + "Either one qualifies — you meet the blue tick " +
        "conditions " + metHow + ".";
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
      note.textContent = "Either one qualifies — reach " + ver.required +
        " followers or " + ver.referrals_required +
        " referrals to apply for the blue tick.";
      card.appendChild(note);
    }
    wrap.appendChild(card);
  } catch (e) { /* verification card is optional decoration */ }
  // Phase 144 (owner): Theme, Data Control and Rain moved to
  // their own Settings sections — no longer in this stack.
  return wrap;
}


// ---------------------------------------------------------------------------
// Phase 144: Settings — one page per member gathering what used to
// be scattered: profile, theme, privacy, notification toggles,
// Data Control and payout wallet. Every section reuses the existing
// endpoint or card builder; nothing here is admin-only and nothing
// touches another member's settings (all calls are /me/...).
// ---------------------------------------------------------------------------
const NOTIF_PREF_META = [
  ["likes", "❤️ Likes", "Someone likes your post"],
  ["comments", "💬 Comments & replies", "Someone comments or replies on your post"],
  ["follows", "👥 New followers", "Someone follows you"],
  ["follow_requests", "👥 Follow requests", "Someone asks to follow your private account"],
  ["tips", "⭐ Tips", "Someone tips you Stars"],
  ["messages", "💬 Direct messages", "Someone sends you a DM"],
  ["system", "🛡️ System", "Payouts, verification decisions, your posts going live, admin announcements"],
  ["blood", "🩸 Blood requests", "A matching blood request needs your group, or a donor answers your request"],
  ["skills", "🤝 Skill swap", "Someone wants to swap skills with you"],
  ["mention", "📣 Mentions", "Someone mentions you in a post or comment"],
];

// ---------------------------------------------------------------------------
// Phase 187: Settings hub (designcharan pattern) — the page is a hub,
// not one long stack: a profile card on top, then ACCOUNT /
// PREFERENCES / SUPPORT grouped cards of icon rows with chevrons.
// Tapping a row opens that section as a detail inside the same
// Settings view (‹ Settings goes back); every one of the 8 existing
// sections is built exactly as before and nothing is removed or
// added. Excluded by the owner's order: a language switcher (never
// ordered), a dark-mode toggle (Nexora has 33 theme shades — the
// Theme row instead) and a log-out button (a Telegram Mini App has
// no logout). The
// About row shows the live build version (?v=NN) read off the
// app.js script tag. Colours follow the member's theme (CSS vars),
// not the screenshot's light palette — a light-only page would
// clash with the dark/themeable app.
// ---------------------------------------------------------------------------
let settingsDetails = {};
let settingsHubUser = null;
// Phase 199: the hub row + detail read the portfolio state.
let settingsPortfolio = null;
let settingsDetailKey = null;
// Phase 200: hub summaries, search query and load guard. The
// summaries are what the hub rows display as current values;
// the query survives hub re-renders so a refresh never wipes
// what the member typed; the load sequence stops a stale
// (superseded) load from repainting over a newer one.
let settingsNotifSummary = null;
let settingsWalletSummary = null;
let settingsSearchQuery = "";
let settingsLoadSeq = 0;

// Phase 200: the hub opens instantly from the last cached render
// (per account, this session only) and fresh data replaces it in
// place — a repeat open never waits on the network first.
function settingsCacheKey() {
  return "nx_settings_hub_" + (me && me.telegram_id ? me.telegram_id : "anon");
}
function settingsCacheRead() {
  try {
    const raw = sessionStorage.getItem(settingsCacheKey());
    if (!raw) return null;
    const d = JSON.parse(raw);
    if (!d || typeof d !== "object") return null;
    return d;
  } catch (e) { return null; }
}
function settingsCacheWrite() {
  try {
    const u = settingsHubUser;
    sessionStorage.setItem(settingsCacheKey(), JSON.stringify({
      name: (u && u.first_name) || (me && me.first_name) || null,
      username: u && u.username ? u.username : null,
      photo_file_id: u && u.photo_file_id ? u.photo_file_id : null,
      is_private: !!(u && u.is_private),
      portfolioEnabled: !!(settingsPortfolio && settingsPortfolio.enabled),
      notifSummary: settingsNotifSummary,
      walletNetwork: settingsWalletSummary,
    }));
  } catch (e) { /* the cache is best-effort; a failed write is silent */ }
}
function settingsThemeName() {
  try {
    const p = themeState && themeState.picks
      ? palById(themeState.picks.bg) : null;
    if (p) return p.name;
  } catch (e) { /* theme state unreadable; keep the default label */ }
  return "Default pink";
}

function settingsVersion() {
  const s = document.querySelector('script[src*="app.js?v="]');
  const m = s && /[?&]v=(\d+)/.exec(s.src || "");
  return m ? m[1] : null;
}

function settingsHubRow(icon, label, sub, valueText, onOpen, valueClass, opts) {
  const b = document.createElement("button");
  b.className = "settings-row-btn";
  b.type = "button";
  // Phase 200: search matches on the label + subtitle only — the
  // value text and chevron are display, not searchable.
  b.dataset.search = (label + " " + (sub || "")).toLowerCase();
  const ic = document.createElement("span");
  ic.className = "settings-row-ic";
  ic.textContent = icon;
  const tx = document.createElement("div");
  tx.className = "settings-row-tx";
  const lb = document.createElement("div");
  lb.className = "settings-row-label";
  lb.textContent = label;
  tx.appendChild(lb);
  if (sub) {
    const s = document.createElement("div");
    s.className = "settings-row-sub";
    s.textContent = sub;
    tx.appendChild(s);
  }
  b.append(ic, tx);
  if (valueText) {
    const v = document.createElement("span");
    v.className = "settings-row-value" + (valueClass ? " " + valueClass : "");
    v.textContent = valueText;
    b.appendChild(v);
  }
  if (opts && opts.toggle) {
    // Phase 200: an inline switch on the hub row — a span, not a
    // nested button (a button inside a button is invalid HTML);
    // its click never opens the detail.
    const sw = document.createElement("span");
    sw.className = "settings-switch";
    sw.setAttribute("role", "switch");
    sw.setAttribute("aria-checked", opts.toggle.checked ? "true" : "false");
    sw.setAttribute("tabindex", "0");
    sw.setAttribute("aria-label", label);
    const knob = document.createElement("span");
    knob.className = "settings-switch-knob";
    sw.appendChild(knob);
    sw.onclick = (e) => {
      e.stopPropagation();
      opts.toggle.onFlip(sw, b);
    };
    sw.onkeydown = (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        e.stopPropagation();
        opts.toggle.onFlip(sw, b);
      }
    };
    b.appendChild(sw);
  }
  const ch = document.createElement("span");
  ch.className = "settings-row-chev";
  ch.textContent = "›";
  b.appendChild(ch);
  b.onclick = onOpen;
  return b;
}

// Phase 200: one shared flip for every inline hub switch —
// optimistic UI (switch + value flip at once), the row's value
// text follows, and a failed save flips it back. The cached
// detail checkbox (if that section was already built) is kept
// in step so the detail agrees with the hub.
function settingsSetToggleUI(switchEl, rowBtn, on, valueText) {
  switchEl.setAttribute("aria-checked", on ? "true" : "false");
  const v = rowBtn.querySelector(".settings-row-value");
  if (v && valueText != null) v.textContent = valueText;
}
function settingsSyncDetailCheckbox(key, checked) {
  const det = settingsDetails && settingsDetails[key];
  if (!det) return;
  const cb = det.querySelector('input[type="checkbox"]');
  if (cb) cb.checked = checked;
}
async function settingsFlipToggle(switchEl, rowBtn, spec) {
  if (switchEl.dataset.busy) return;
  const prev = switchEl.getAttribute("aria-checked") === "true";
  const next = !prev;
  switchEl.dataset.busy = "1";
  settingsSetToggleUI(switchEl, rowBtn, next, spec.valueFor(next));
  try {
    await spec.save(next);
    settingsSyncDetailCheckbox(spec.detailKey, next);
    settingsCacheWrite();
  } catch (e) {
    settingsSetToggleUI(switchEl, rowBtn, prev, spec.valueFor(prev));
    setStatus("Could not save that setting.");
  } finally {
    delete switchEl.dataset.busy;
  }
}
function settingsFlipPortfolio(switchEl, rowBtn) {
  settingsFlipToggle(switchEl, rowBtn, {
    detailKey: "portfolio",
    valueFor: (on) => (on ? "On" : "Off"),
    save: async (next) => {
      const cur = settingsPortfolio || {};
      const r = await api("/me/portfolio", { method: "POST",
        body: JSON.stringify({ about: cur.about || "",
                               role: cur.role || "",
                               cover_file_id: cur.cover_file_id || null,
                               enabled: next }) });
      settingsPortfolio = r;
    },
  });
}
function settingsFlipPrivate(switchEl, rowBtn) {
  settingsFlipToggle(switchEl, rowBtn, {
    detailKey: "privacy",
    valueFor: (on) => (on ? "Private" : "Public"),
    save: async (next) => {
      const r = await api("/me/privacy", { method: "POST",
        body: JSON.stringify({ is_private: next }) });
      if (settingsHubUser) settingsHubUser.is_private = r.is_private;
    },
  });
}

function settingsGroupEl(label, rows) {
  const wrap = document.createElement("div");
  const lab = document.createElement("div");
  lab.className = "settings-group-label";
  lab.textContent = label;
  const card = document.createElement("div");
  card.className = "card settings-group";
  rows.forEach(r => card.appendChild(r));
  wrap.append(lab, card);
  return wrap;
}

// Phase 200: the skeleton — the first paint while the hub data
// loads. Same shape as the hub (search bar + profile card + 3
// groups) so the layout never jumps, theme-aware (tile
// backgrounds), no text.
function renderSettingsSkeleton() {
  const box = $("settings-box");
  if (!box) return;
  settingsDetailKey = null;
  box.innerHTML = "";
  const wrap = document.createElement("div");
  wrap.className = "settings-skel";
  wrap.setAttribute("aria-hidden", "true");
  const search = document.createElement("div");
  search.className = "settings-skel-search";
  wrap.appendChild(search);
  const pc = document.createElement("div");
  pc.className = "card settings-profile-card";
  const ava = document.createElement("span");
  ava.className = "settings-skel-ava";
  const lines = document.createElement("span");
  lines.className = "settings-skel-lines";
  const l1 = document.createElement("span");
  l1.className = "settings-skel-line w60";
  const l2 = document.createElement("span");
  l2.className = "settings-skel-line w40";
  lines.append(l1, l2);
  pc.append(ava, lines);
  wrap.appendChild(pc);
  [["ACCOUNT", 6], ["PREFERENCES", 3], ["SUPPORT", 2]].forEach(([label, n]) => {
    const lab = document.createElement("div");
    lab.className = "settings-group-label";
    const ll = document.createElement("span");
    ll.className = "settings-skel-line w40";
    lab.appendChild(ll);
    wrap.appendChild(lab);
    const card = document.createElement("div");
    card.className = "card settings-group";
    for (let i = 0; i < n; i++) {
      const row = document.createElement("div");
      row.className = "settings-skel-row";
      const ic = document.createElement("span");
      ic.className = "settings-skel-ic";
      const tx = document.createElement("span");
      tx.className = "settings-skel-lines";
      const a = document.createElement("span");
      a.className = "settings-skel-line w60";
      const b2 = document.createElement("span");
      b2.className = "settings-skel-line w40";
      tx.append(a, b2);
      row.append(ic, tx);
      card.appendChild(row);
    }
    wrap.appendChild(card);
  });
  box.appendChild(wrap);
  const sc = $("app-scroll");
  if (sc) sc.scrollTop = 0;
}

function renderSettingsHub() {
  const box = $("settings-box");
  if (!box) return;
  settingsDetailKey = null;
  box.innerHTML = "";
  const u = settingsHubUser;
  const name = (u && u.first_name) || (me && me.first_name) || "Member";
  const uname = u && u.username;
  // Profile card — the mockup's email line cannot be copied:
  // Nexora members are Telegram-identified and have no email on
  // file, so the second line is the @username.
  const card = document.createElement("div");
  card.className = "card settings-profile-card";
  card.appendChild(avatarEl(name, me.telegram_id, true,
                            u && u.photo_file_id));
  const col = document.createElement("div");
  col.className = "settings-profile-col";
  const nm = document.createElement("div");
  nm.className = "settings-profile-name";
  nm.textContent = name;
  const sub = document.createElement("div");
  sub.className = "settings-profile-sub";
  sub.textContent = uname ? "@" + uname : "Nexora member";
  col.append(nm, sub);
  card.appendChild(col);
  const edit = document.createElement("button");
  edit.className = "settings-edit";
  edit.type = "button";
  edit.textContent = "✎ Edit";
  edit.onclick = () => openSettingsDetail("profile");
  card.appendChild(edit);
  box.appendChild(card);
  // Phase 200: search sits above the groups and filters the hub
  // rows live; the query survives re-renders.
  const search = document.createElement("input");
  search.type = "search";
  search.className = "settings-search";
  search.placeholder = "Search settings…";
  search.setAttribute("aria-label", "Search settings");
  search.value = settingsSearchQuery;
  search.oninput = () => {
    settingsSearchQuery = search.value;
    applySettingsSearch();
  };
  box.appendChild(search);
  const ver = settingsVersion();
  const themeName = settingsThemeName();
  box.appendChild(settingsGroupEl("ACCOUNT", [
    settingsHubRow("👤", "Profile", null, null,
                   () => openSettingsDetail("profile")),
    settingsHubRow("🖼️", "Portfolio", null,
                   settingsPortfolio
                     ? (settingsPortfolio.enabled ? "On" : "Off") : null,
                   () => openSettingsDetail("portfolio"), null,
                   { toggle: { checked: !!(settingsPortfolio && settingsPortfolio.enabled),
                               onFlip: settingsFlipPortfolio } }),
    settingsHubRow("🔒", "Privacy", null,
                   u ? (u.is_private ? "Private" : "Public") : null,
                   () => openSettingsDetail("privacy"), null,
                   { toggle: { checked: !!(u && u.is_private),
                               onFlip: settingsFlipPrivate } }),
    settingsHubRow("💰", "Payout wallet", null, settingsWalletSummary,
                   () => openSettingsDetail("wallet")),
    settingsHubRow("🔳", "My QR", null, null,
                   () => openSettingsDetail("qr")),
    settingsHubRow("📦", "From your profile", null, null,
                   () => openSettingsDetail("extras")),
  ]));
  box.appendChild(settingsGroupEl("PREFERENCES", [
    settingsHubRow("🎨", "Theme", null, themeName,
                   () => openSettingsDetail("theme")),
    settingsHubRow("🔔", "Notifications", "In-app & Telegram bot",
                   settingsNotifSummary,
                   () => openSettingsDetail("notif")),
    settingsHubRow("🗂️", "Data Control", null, null,
                   () => openSettingsDetail("data")),
  ]));
  box.appendChild(settingsGroupEl("SUPPORT", [
    settingsHubRow("❓", "Help & Support", null, null,
                   () => openSettingsDetail("help")),
    settingsHubRow("ℹ️", "About", null, ver ? "v" + ver : null,
                   () => openSettingsDetail("about"),
                   "settings-ver-pill"),
  ]));
  // Phase 200: empty state for search, then re-apply a preserved
  // query and refresh the instant-open cache with fresh data.
  const empty = document.createElement("div");
  empty.className = "settings-search-empty";
  empty.hidden = true;
  empty.textContent = "No settings match your search.";
  box.appendChild(empty);
  if (settingsSearchQuery) applySettingsSearch();
  settingsCacheWrite();
  const sc = $("app-scroll");
  if (sc) sc.scrollTop = 0;
  updateBackButton();
}

// Phase 200: live search over the hub rows — matches the label +
// subtitle only; a group with no matching row hides whole; when
// nothing matches, the empty state shows instead.
function applySettingsSearch() {
  const box = $("settings-box");
  if (!box) return;
  const q = (settingsSearchQuery || "").trim().toLowerCase();
  const empty = box.querySelector(".settings-search-empty");
  let visible = 0;
  box.querySelectorAll(".settings-group").forEach(card => {
    let groupVisible = 0;
    card.querySelectorAll(".settings-row-btn").forEach(btn => {
      const show = !q || (btn.dataset.search || "").includes(q);
      btn.hidden = !show;
      if (show) groupVisible++;
    });
    const wrap = card.parentElement;
    if (wrap) wrap.hidden = groupVisible === 0;
    visible += groupVisible;
  });
  if (empty) empty.hidden = visible !== 0;
}

function openSettingsDetail(key) {
  const box = $("settings-box");
  const node = settingsDetails[key];
  if (!box || !node) return;
  settingsDetailKey = key;
  box.innerHTML = "";
  const back = document.createElement("button");
  back.className = "settings-back";
  back.type = "button";
  back.textContent = "‹ Settings";
  back.onclick = () => renderSettingsHub();
  const wrap = document.createElement("div");
  wrap.className = "settings-detail";
  wrap.appendChild(node);
  box.append(back, wrap);
  const sc = $("app-scroll");
  if (sc) sc.scrollTop = 0;
  updateBackButton();
}

async function loadSettings() {
  const box = $("settings-box");
  if (!box || !me) return;
  const seq = ++settingsLoadSeq;
  // Phase 200 (owner bug, Nov 27): the first paint is never the
  // half-built section stack. The sections used to be appended to
  // the visible box one by one while their fetches resolved, so
  // the member watched the raw stacked sections pile up for 1–2 s
  // before the hub replaced them. Now the first paint is the
  // skeleton — or the cached hub on a repeat open — and the
  // sections are built in a hidden, attached container (the
  // builders that look their targets up by id need the nodes in
  // the document) and only surface as the hub at the end.
  const cached = settingsCacheRead();
  if (cached) {
    settingsHubUser = { first_name: cached.name,
                        username: cached.username || null,
                        photo_file_id: cached.photo_file_id || null,
                        is_private: !!cached.is_private };
    settingsPortfolio = { enabled: !!cached.portfolioEnabled };
    settingsNotifSummary = cached.notifSummary || null;
    settingsWalletSummary = cached.walletNetwork || null;
    renderSettingsHub();
  } else {
    renderSettingsSkeleton();
  }
  // Hidden build container: attached (so id lookups work) but
  // never visible.
  const buildBox = document.createElement("div");
  buildBox.className = "settings-build";
  buildBox.style.display = "none";
  box.appendChild(buildBox);
  try {
    // Phase 183 (audit L13): sections render independently
    // — the profile fetch failing must not kill the whole
    // page. A failed fetch leaves u null: the Profile
    // section shows its own inline error and the other
    // sections still load.
    let u = null;
    try {
      u = await api("/users/" + me.telegram_id);
    } catch (e) {
      u = null;
    }
    if (seq !== settingsLoadSeq) return;
    // Phase 199: the hub row + detail need the portfolio state.
    try {
      settingsPortfolio = await api("/me/portfolio");
    } catch (e) {
      settingsPortfolio = null;
    }
    if (seq !== settingsLoadSeq) return;
    // Phase 187: sections are built exactly as before, but each is
    // registered under a hub key instead of staying stacked — the
    // hub renders at the end of this function and a row tap moves
    // the registered node into the detail view (DOM moves keep
    // listeners and input state). Builders that look their target
    // up by id (loadMySkills, loadMyQrInto) run while the section
    // is still attached, exactly as today.
    const details = {};
    const reg = (key, node) => { details[key] = node; return node; };
    const sec = (title) => {
      const s = document.createElement("div");
      s.className = "card settings-sec";
      const h = document.createElement("b");
      h.className = "settings-head";
      h.textContent = title;
      s.appendChild(h);
      buildBox.appendChild(s);
      return s;
    };
    // 1. Profile — the same name/bio save as the profile edit
    // form, plus the same photo/cover pickers (the pickers live
    // in the profile view; after a photo change the app shows
    // your profile, as it does from Me today).
    const prof = reg("profile", sec("👤 Profile"));
    const nameIn = document.createElement("input");
    nameIn.type = "text";
    nameIn.maxLength = 128;
    nameIn.placeholder = "Your name";
    nameIn.value = u ? u.first_name || "" : "";
    if (u && u.name_locked_days > 0) nameIn.disabled = true;
    const bioIn = document.createElement("textarea");
    bioIn.rows = 3;
    bioIn.maxLength = 500;
    bioIn.placeholder = "Write something about yourself…";
    bioIn.value = u ? u.bio || "" : "";
    const saveBtn = document.createElement("button");
    saveBtn.className = "wide";
    saveBtn.textContent = "Save profile";
    saveBtn.onclick = async () => {
      try {
        const r = await api("/me/profile", { method: "POST",
          body: JSON.stringify({ first_name: nameIn.value,
                                 bio: bioIn.value }) });
        if (me) me.first_name = r.first_name;
        setStatus("Profile updated.");
      } catch (e) { setStatus("Could not save the profile."); }
    };
    prof.append(nameIn, bioIn, saveBtn);
    if (!u) {
      const err = document.createElement("p");
      err.className = "hint";
      err.textContent = "Could not load your profile — your name "
        + "and bio are unavailable right now, but the rest of "
        + "Settings still works.";
      prof.appendChild(err);
    }
    if (u && u.name_locked_days > 0) {
      const note = document.createElement("div");
      note.className = "hint";
      note.textContent = "🔒 Name can be changed once every 60 days — available again in " + u.name_locked_days + " day" + (u.name_locked_days === 1 ? "" : "s") + ". Your bio can still be edited anytime.";
      prof.appendChild(note);
    }
    // Phase 55 (owner): no wide Change-photo/cover buttons anywhere
    // — the camera badges ON the photo and cover do that job. So
    // Settings links to the profile instead of duplicating them.
    const photoHint = document.createElement("p");
    photoHint.className = "hint";
    photoHint.textContent = "To change your photo or cover, tap the 📷 badge on your photo or cover on your profile.";
    const photoBtn = document.createElement("button");
    photoBtn.className = "btn";
    photoBtn.id = "settings-open-profile";
    photoBtn.textContent = "👤 Open my profile";
    photoBtn.onclick = () => openProfile(me.telegram_id);
    prof.append(photoHint, photoBtn);
    // Phase 151: blood donor opt-in — group picker + toggle.
    // The group is shown to others ONLY while opted in.
    const bloodHead = document.createElement("div");
    bloodHead.className = "settings-sub";
    bloodHead.textContent = "🩸 Blood donor";
    const bloodSel = document.createElement("select");
    bloodSel.id = "settings-blood-group";
    const noGroup = document.createElement("option");
    noGroup.value = "";
    noGroup.textContent = "No blood group set";
    bloodSel.appendChild(noGroup);
    BLOOD_GROUPS.forEach(g => {
      const o = document.createElement("option");
      o.value = g;
      o.textContent = g;
      bloodSel.appendChild(o);
    });
    bloodSel.value = u ? u.blood_group || "" : "";
    const bloodRow = document.createElement("label");
    bloodRow.className = "privacy-row";
    const bloodChk = document.createElement("input");
    bloodChk.type = "checkbox";
    bloodChk.checked = !!(u && u.blood_donor);
    const bloodTx = document.createElement("span");
    bloodTx.textContent = "আমি রক্ত দিতে চাই — show me as a donor of this group.";
    bloodRow.append(bloodChk, bloodTx);
    const bloodSave = document.createElement("button");
    bloodSave.className = "btn";
    bloodSave.id = "settings-blood-save";
    bloodSave.textContent = "Save blood donor status";
    bloodSave.onclick = async () => {
      try {
        const r = await api("/me/blood-group", { method: "POST",
          body: JSON.stringify({ blood_group: bloodSel.value || null,
                                 is_donor: bloodChk.checked }) });
        setStatus(r.blood_donor ? "You are now listed as a 🩸 " + r.blood_group + " donor." : "Blood donor status cleared.");
      } catch (e) { setStatus("Could not save blood donor status."); }
    };
    const bloodHint = document.createElement("p");
    bloodHint.className = "hint";
    bloodHint.textContent = "Your blood group is shown only while you opt in as a donor. Contact happens only by DM — no phone number is ever shown.";
    prof.append(bloodHead, bloodSel, bloodRow, bloodSave, bloodHint);
    // Phase 158: Skill Swap — list what you teach / want to learn.
    // No money, no scheduling: the swap is arranged in a DM after
    // someone taps Connect on your card. Removing all skills
    // removes you from the directory.
    const skillHead = document.createElement("div");
    skillHead.className = "settings-sub";
    skillHead.textContent = "🤝 My skills";
    const skillName = document.createElement("input");
    skillName.id = "settings-skill-name";
    skillName.type = "text";
    skillName.maxLength = 80;
    skillName.placeholder = "Skill — e.g. English, Guitar, Coding";
    const skillKind = document.createElement("select");
    skillKind.id = "settings-skill-kind";
    ["teach", "learn"].forEach(k => {
      const o = document.createElement("option");
      o.value = k;
      o.textContent = k === "teach" ? "🎓 I can teach this" : "📚 I want to learn this";
      skillKind.appendChild(o);
    });
    const skillNote = document.createElement("input");
    skillNote.id = "settings-skill-note";
    skillNote.type = "text";
    skillNote.maxLength = 200;
    skillNote.placeholder = "Note (optional) — e.g. weekends, beginner level";
    const skillAdd = document.createElement("button");
    skillAdd.className = "btn";
    skillAdd.id = "settings-skill-add";
    skillAdd.textContent = "Add skill";
    skillAdd.onclick = async () => {
      try {
        await api("/me/skills", { method: "POST",
          body: JSON.stringify({ skill: skillName.value,
                                 kind: skillKind.value,
                                 note: skillNote.value }) });
        skillName.value = "";
        skillNote.value = "";
        setStatus("Skill added — you now appear in the Skills directory. 🤝");
        loadMySkills();
      } catch (e) { setStatus("Could not add the skill."); }
    };
    const skillList = document.createElement("div");
    skillList.id = "settings-skill-list";
    const skillHint = document.createElement("p");
    skillHint.className = "hint";
    skillHint.textContent = "Teach what you know, learn what you don't — no money, just time. Your skills show on your profile and in the Skills directory.";
    prof.append(skillHead, skillName, skillKind, skillNote, skillAdd, skillList, skillHint);
    loadMySkills();
    // Phase 199: Portfolio — the toggle lives here (Settings is
    // where the owner asked for it); the editor itself opens
    // from the profile page.
    const pfSec = reg("portfolio", sec("🖼️ Portfolio"));
    const pfRow = document.createElement("label");
    pfRow.className = "privacy-row";
    const pfChk = document.createElement("input");
    pfChk.type = "checkbox";
    pfChk.checked = !!(settingsPortfolio && settingsPortfolio.enabled);
    const pfTx = document.createElement("span");
    pfTx.textContent = "Show my portfolio — Profile/Portfolio dropdown appears on my profile.";
    pfRow.append(pfChk, pfTx);
    pfSec.appendChild(pfRow);
    pfChk.onchange = async () => {
      try {
        const cur = settingsPortfolio || {};
        const r = await api("/me/portfolio", { method: "POST",
          body: JSON.stringify({ about: cur.about || "",
                                 role: cur.role || "",
                                 cover_file_id: cur.cover_file_id || null,
                                 enabled: pfChk.checked }) });
        settingsPortfolio = r;
        settingsCacheWrite();
        setStatus(pfChk.checked ? "Portfolio is now visible on your profile." : "Portfolio hidden.");
      } catch (e) {
        pfChk.checked = !!(settingsPortfolio && settingsPortfolio.enabled);
        setStatus("Could not change the portfolio setting.");
      }
    };
    const pfHint = document.createElement("p");
    pfHint.className = "hint";
    pfHint.textContent = "Your portfolio shows a full-screen cover photo, your role, an About text and your work samples. Add samples from your posts, the Design gallery or your own photos.";
    pfSec.appendChild(pfHint);
    const pfEdit = document.createElement("button");
    pfEdit.className = "wide";
    pfEdit.textContent = "✏️ Edit portfolio";
    pfEdit.onclick = async () => {
      await openProfile(me.telegram_id);
      await renderPortfolioTab(me.telegram_id);
      openPortfolioEditor();
    };
    pfSec.appendChild(pfEdit);
    // 2. Theme — the same picker as Me (themeCard is reused).
    const themeNode = reg("theme", themeCard());
    buildBox.appendChild(themeNode);
    // 3. Privacy — the same toggle as the profile edit form,
    // plus the blocked list with Unblock (GET /me/blocked,
    // POST /users/{id}/block toggles the block off).
    const priv = reg("privacy", sec("🔒 Privacy"));
    const privRow = document.createElement("label");
    privRow.className = "privacy-row";
    const privChk = document.createElement("input");
    privChk.type = "checkbox";
    privChk.checked = !!(u && u.is_private);
    const privTx = document.createElement("span");
    privTx.textContent = "🔒 Private account — only approved followers will see your posts.";
    privRow.append(privChk, privTx);
    privChk.onchange = async () => {
      try {
        const r = await api("/me/privacy", { method: "POST",
          body: JSON.stringify({ is_private: privChk.checked }) });
        if (u) u.is_private = r.is_private;
        settingsCacheWrite();
        setStatus(r.is_private ? "Your account is now private 🔒" : "Your account is now public.");
      } catch (e) {
        privChk.checked = !!(u && u.is_private);
        setStatus("Could not change privacy.");
      }
    };
    priv.appendChild(privRow);
    const blkHead = document.createElement("div");
    blkHead.className = "settings-sub";
    blkHead.textContent = "🚫 Blocked members";
    priv.appendChild(blkHead);
    const blkBox = document.createElement("div");
    blkBox.className = "settings-blocked";
    priv.appendChild(blkBox);
    const loadBlocked = async () => {
      blkBox.innerHTML = "Loading…";
      try {
        const d = await api("/me/blocked");
        blkBox.innerHTML = "";
        if (!d.blocked.length) {
          blkBox.textContent = "Nobody blocked.";
          return;
        }
        d.blocked.forEach(b => {
          const row = document.createElement("div");
          row.className = "settings-blocked-row";
          const nm = document.createElement("span");
          nm.textContent = (b.first_name || "?") + (b.username ? " (@" + b.username + ")" : "");
          const un = document.createElement("button");
          un.textContent = "Unblock";
          un.onclick = async () => {
            try {
              await api("/users/" + b.telegram_id + "/block", { method: "POST" });
              setStatus("Member unblocked.");
              loadBlocked();
            } catch (e) { setStatus("Could not unblock."); }
          };
          row.append(nm, un);
          blkBox.appendChild(row);
        });
      } catch (e) { blkBox.textContent = "Could not load blocked members."; }
    };
    loadBlocked();
    // Phase 174: Muted members — same list shape as blocked,
    // Unmute toggles the mute off (POST /users/{id}/mute).
    const mutHead = document.createElement("div");
    mutHead.className = "settings-sub";
    mutHead.textContent = "🔇 Muted members";
    priv.appendChild(mutHead);
    const mutBox = document.createElement("div");
    mutBox.className = "settings-blocked";
    priv.appendChild(mutBox);
    const loadMuted = async () => {
      mutBox.innerHTML = "Loading…";
      try {
        const d = await api("/me/muted");
        mutBox.innerHTML = "";
        if (!d.muted.length) {
          mutBox.textContent = "Nobody muted.";
          return;
        }
        d.muted.forEach(b => {
          const row = document.createElement("div");
          row.className = "settings-blocked-row";
          const nm = document.createElement("span");
          nm.textContent = (b.first_name || "?") +
            (b.username ? " (@" + b.username + ")" : "");
          const un = document.createElement("button");
          un.textContent = "Unmute";
          un.onclick = async () => {
            try {
              await api("/users/" + b.telegram_id + "/mute",
                        { method: "POST" });
              setStatus("Member unmuted.");
              loadMuted();
            } catch (e) { setStatus("Could not unmute."); }
          };
          row.append(nm, un);
          mutBox.appendChild(row);
        });
      } catch (e) { mutBox.textContent = "Could not load muted members."; }
    };
    loadMuted();
    // 4. Notifications — per-type toggles, all ON by default.
    // Every change posts the full prefs object, so toggling one
    // type never resets the others.
    const notif = reg("notif", sec("🔔 Notifications"));
    const notifHint = document.createElement("p");
    notifHint.className = "hint";
    notifHint.textContent = "Turn off a type to stop getting those notifications — in the app and from the bot. Everything is on until you change it.";
    notif.appendChild(notifHint);
    const notifBox = document.createElement("div");
    notif.appendChild(notifBox);
    try {
      const d = await api("/me/notification-prefs");
      const prefs = d.prefs || {};
      // Phase 200: the hub row shows the current state.
      const offCount = NOTIF_PREF_META.filter(([key]) => prefs[key] === false).length;
      settingsNotifSummary = offCount === 0 ? "All on"
        : (offCount === NOTIF_PREF_META.length ? "All off" : offCount + " off");
      NOTIF_PREF_META.forEach(([key, label, desc]) => {
        const row = document.createElement("label");
        row.className = "privacy-row notif-row";
        row.id = "notif-row-" + key;
        const chk = document.createElement("input");
        chk.type = "checkbox";
        chk.checked = prefs[key] !== false;
        const tx = document.createElement("span");
        tx.textContent = label + " — " + desc;
        row.append(chk, tx);
        chk.onchange = async () => {
          prefs[key] = chk.checked;
          try {
            await api("/me/notification-prefs", { method: "POST",
              body: JSON.stringify(prefs) });
            setStatus(chk.checked ? label + " notifications on." : label + " notifications off.");
          } catch (e) {
            chk.checked = !chk.checked;
            prefs[key] = chk.checked;
            setStatus("Could not save notification settings.");
          }
        };
        notifBox.appendChild(row);
      });
    } catch (e) {
      notifBox.textContent = "Could not load notification settings.";
    }
    // 5. Data Control — the same card as Me (dataCard is reused).
    // Phase 187: Data Control and the After Rain card share one
    // detail — Phase 144 (owner): the After Rain toggle sat under
    // Data Control in Me, so it sits under it here too.
    const dataWrap = document.createElement("div");
    dataWrap.className = "settings-detail-body";
    dataWrap.append(dataCard(), rainCard());
    buildBox.appendChild(reg("data", dataWrap));
    // 6. Payout wallet — the same /me/wallet save as the
    // Monetization card. A small standalone form: loadPayoutBox
    // uses fixed ids (payout-network, payout-address), so calling
    // it twice would duplicate ids in the DOM. Payout requests
    // themselves stay in the Monetization card below (💰 Account).
    const wal = reg("wallet", sec("💰 Payout wallet"));
    const walHint = document.createElement("p");
    walHint.className = "hint";
    walHint.textContent = "The wallet your crypto payouts go to. Payout requests live in the Monetization card below (💰 Account).";
    wal.appendChild(walHint);
    try {
      const w = await api("/me/wallet");
      // Phase 200: the hub row shows the current network.
      settingsWalletSummary = w.wallet_network || null;
      const netSel = document.createElement("select");
      netSel.id = "settings-wallet-network";
      ["TON", "Gram", "USDT"].forEach(n => {
        const o = document.createElement("option");
        o.value = n;
        o.textContent = n;
        netSel.appendChild(o);
      });
      if (w.wallet_network) netSel.value = w.wallet_network;
      const addr = document.createElement("input");
      addr.id = "settings-wallet-address";
      addr.type = "text";
      addr.maxLength = 256;
      addr.placeholder = "Your wallet address";
      addr.value = w.wallet_address || "";
      const walSave = document.createElement("button");
      walSave.id = "settings-wallet-save";
      walSave.textContent = "Save wallet";
      walSave.onclick = async () => {
        try {
          await api("/me/wallet", { method: "POST",
            body: JSON.stringify({ network: netSel.value,
                                   address: addr.value.trim() }) });
          setStatus("Wallet saved.");
        } catch (e) { setStatus("Could not save the wallet."); }
      };
      wal.append(netSel, addr, walSave);
    } catch (e) {
      const err = document.createElement("p");
      err.className = "hint";
      err.textContent = "Could not load the payout wallet.";
      wal.appendChild(err);
    }
    // 7. Everything that used to live on Me — points, tips,
    //    insights, level, referrals, saved, shared, drafts,
    //    scheduled, follow requests, hashtags, monetization
    //    and verification — same cards, same buttons, now here.
    const more = reg("extras", sec("📦 From your profile"));
    const moreHint = document.createElement("p");
    moreHint.className = "hint";
    moreHint.textContent = "Everything that used to live on your profile — same cards, same buttons, now gathered here.";
    more.appendChild(moreHint);
    try {
      more.appendChild(await myExtras());
    } catch (e) {
      const err = document.createElement("p");
      err.className = "hint";
      err.textContent = "Could not load the rest of your profile cards.";
      more.appendChild(err);
    }
    buildBox.appendChild(more);
    // 8. My QR — rendered inline (same loader as the QR view).
    const qrSec = reg("qr", sec("🔳 My QR"));
    const qrBox = document.createElement("div");
    qrBox.id = "settings-qr-box";
    qrSec.appendChild(qrBox);
    buildBox.appendChild(qrSec);
    try {
      await loadMyQrInto("settings-qr-box");
    } catch (e) {
      const err = document.createElement("p");
      err.className = "hint";
      err.textContent = "Could not load your QR code.";
      qrSec.appendChild(err);
    }
    if (seq !== settingsLoadSeq) return;
    // Phase 187: every section built — hand the nodes to the hub
    // and show the hub (profile card + ACCOUNT / PREFERENCES /
    // SUPPORT groups). The About detail is built here too: it is
    // information only (app name + live build version), not a
    // setting.
    const aboutSec = document.createElement("div");
    aboutSec.className = "card settings-sec";
    const aboutHead = document.createElement("b");
    aboutHead.className = "settings-head";
    aboutHead.textContent = "ℹ️ About";
    const aboutName = document.createElement("div");
    aboutName.className = "settings-about-name";
    aboutName.textContent = "Nexora Social";
    const aboutVer = document.createElement("div");
    aboutVer.className = "hint";
    const ver = settingsVersion();
    aboutVer.textContent = ver
      ? "Version v" + ver + " (build ?v=" + ver + ")"
      : "Version unknown";
    const aboutHint = document.createElement("p");
    aboutHint.className = "hint";
    aboutHint.textContent = "Runs inside Telegram — your account is "
      + "your Telegram account.";
    aboutSec.append(aboutHead, aboutName, aboutVer, aboutHint);
    // Phase 188 (Job 2): Help & Support — FAQ with real facts only,
    // drawn from the app itself. There are no contact details to give
    // (no email, no phone, no external links) — help actions stay
    // in-app: "Ask Nexa" opens the assistant, "Report a problem"
    // opens a DM to Nexora Social (id 1, OFFICIAL_ID), which the
    // admin reads. The existing /reports endpoint is post-scoped
    // (needs a post_id), so a general problem has no report endpoint
    // to reuse — the DM route is the existing in-app channel, and
    // the post-report flow is documented in the FAQ below.
    const helpSec = document.createElement("div");
    helpSec.className = "card settings-sec";
    const helpHead = document.createElement("b");
    helpHead.className = "settings-head";
    helpHead.textContent = "❓ Help & Support";
    helpSec.appendChild(helpHead);
    const helpFaq = [
      ["How do I post a photo or video?",
       "Send it to @NexoraSocial_bot in chat with a caption and it becomes a post. In-app upload is not available."],
      ["How do I earn points?",
       "Every post earns 10 points. Daily tasks on the Tasks page earn more: check-in 20, follow 3 people 10, comment 5 times 5, react 6 times 10 — each once a day, tap Claim."],
      ["How do I unlock monetisation?",
       "Six targets, all shown in Settings under From your profile: 500 followers, 12 qualified referrals, 25 posts, an account 14 days old, 5000 lifetime points, and a 30-day check-in streak."],
      ["What is a qualified referral?",
       "A friend who joins from your invite link AND makes their first post. Your link is in Settings, under From your profile. A qualified referral also earns you 20 points."],
      ["How do Stars tips work?",
       "Tap ⭐ on a post to tip 10, 50, 100 or 250 Stars, or a custom amount. Stars go to the bot's balance; payouts to creators are in crypto (TON, Gram or USDT) — see Payout wallet in Settings."],
      ["How do Blood donors work?",
       "Opt in from Settings → Profile and pick your blood group. Donors are listed by group. No phone numbers are shown anywhere — you contact a donor by DM."],
      ["What is Skill Swap?",
       "List a skill you teach and one you want to learn (Settings → Profile → My skills). Matches show on the Skills page; Connect opens a DM."],
      ["Can I send voice messages?",
       "Yes, in DMs — tap the mic. A voice note can be up to 120 seconds and 5 MB."],
      ["What is Nexa?",
       "Nexa is the in-app AI assistant (sidebar, top). She answers in text only — no voice messages."],
      ["How do I stay safe?",
       "Report any post from its ⋮ menu. Block or mute someone from their profile — a blocked person cannot see your posts or message you. A private account (Settings → Privacy) shows posts to followers only."],
    ];
    helpFaq.forEach(([q, a]) => {
      const qEl = document.createElement("b");
      qEl.textContent = q;
      const aEl = document.createElement("p");
      aEl.className = "hint";
      aEl.textContent = a;
      helpSec.append(qEl, aEl);
    });
    const helpAsk = document.createElement("button");
    helpAsk.className = "wide";
    helpAsk.type = "button";
    helpAsk.textContent = "💬 Ask Nexa";
    helpAsk.onclick = () => showView("assistant");
    const helpReport = document.createElement("button");
    helpReport.className = "wide";
    helpReport.type = "button";
    helpReport.textContent = "⚑ Report a problem";
    helpReport.onclick = () => openChat(1);
    const helpHint = document.createElement("p");
    helpHint.className = "hint";
    helpHint.textContent = "Reporting a problem opens a message to Nexora Social — describe the problem and the admin will read it. To report a post, tap ⋮ on the post, then Report.";
    helpSec.append(helpAsk, helpReport, helpHint);
    details.help = helpSec;
    details.about = aboutSec;
    settingsDetails = details;
    settingsHubUser = u;
    if (seq !== settingsLoadSeq) return;
    renderSettingsHub();
  } catch (e) {
    if (!cached) box.textContent = "Could not load Settings.";
    else setStatus("Could not refresh Settings.");
  }
}

// ---------------------------------------------------------------- tasks ---
// Phase 124 (owner): an incomplete task card is a door, not a
// label — tap it and you land where the task is done. Claimed
// tasks go nowhere. The feed is already loaded at boot, so the
// helpers just wait briefly for the target element to exist.
function goFeedTo(selector) {
  showView("feed");
  let tries = 0;
  const tick = () => {
    const el = document.querySelector(selector);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
      return;
    }
    if (++tries < 15) setTimeout(tick, 200);
  };
  tick();
}
function goFeedToFirstComment() {
  showView("feed");
  let tries = 0;
  const tick = () => {
    const btn = document.querySelector("#feed-list .post .cmt-btn");
    if (btn) {
      btn.scrollIntoView({ behavior: "smooth", block: "center" });
      btn.click();
      return;
    }
    if (++tries < 15) setTimeout(tick, 200);
  };
  tick();
}

async function loadTasks() {
  const box = $("task-list");
  box.innerHTML = "Loading…";
  try {
    const data = await api("/me/tasks");
    box.innerHTML = "";
    data.tasks.forEach(t => {
      const card = document.createElement("div");
      card.className = "task-card";
      if (!t.claimed) card.classList.add("task-go");
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
      if (!t.claimed) {
        const chev = document.createElement("span");
        chev.className = "task-go-chev";
        chev.textContent = "›";
        top.appendChild(chev);
      }
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
      let doClaim = null;
      if (t.claimed) {
        btn.textContent = "✓ Claimed";
        btn.className = "task-claim claimed btn";
        btn.disabled = true;
      } else if (t.claimable) {
        btn.textContent = "Claim";
        btn.className = "task-claim btn";
        doClaim = async () => {
          try {
            const r = await api("/me/tasks/" + t.key + "/claim", { method: "POST" });
            setStatus("+" + r.points_awarded + " points! Balance: " + r.balance);
            loadMe().catch(() => {});
            loadTasks();
          } catch (e) { setStatus("Could not claim this task."); }
        };
        btn.onclick = doClaim;
      } else if (t.key === "adwatch" && t.available === false) {
        // Phase 180 (audit H14): no ad provider is live (AdsGram
        // declined) — the task is paused, not claimable, and there
        // is no Watch button to tap. It returns with a provider.
        btn.textContent = "No ad available";
        btn.className = "task-claim btn";
        btn.disabled = true;
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
      card.onclick = (ev) => {
        // Phase 124: a tap on a button keeps that button's own
        // handler; a tap anywhere else on an incomplete card goes
        // where the task is done. Claimed cards go nowhere.
        if (ev.target.closest("button")) return;
        if (t.claimed) return;
        if (t.key === "checkin" && doClaim) { doClaim(); return; }
        if (t.key === "follow3") { goFeedTo("#suggest-card"); return; }
        if (t.key === "comment5") { goFeedToFirstComment(); return; }
        if (t.key === "react6") { showView("feed"); return; }
        // adwatch: the same flow as its Watch ad button (showTaskAd
        // disables the button first, so a second tap — card or
        // button — cannot start another show).
        if (t.key === "adwatch" && !btn.disabled) showTaskAd(btn);
      };
      box.appendChild(card);
    });
  } catch (e) { box.textContent = "Could not load tasks."; }
}

// ------------------------------------------- Phase 114: My QR --------
// Each member's own profile link as a QR code: the image comes from
// /me/qr (server-generated, branded with NEXORA SOCIAL), the link is
// shown for copying, and Download uses Telegram's native downloadFile
// (Phase 110 pattern — anchor downloads are ignored in the WebView).
async function loadMyQr() { return loadMyQrInto("qr-box"); }
async function loadMyQrInto(boxId) {
  const box = $(boxId);
  box.innerHTML = "Loading…";
  try {
    const link = "https://t.me/" + me.bot_username +
      "?start=profile_" + me.telegram_id;
    const tok = await api("/me/qr-token");
    const qrUrl = "/me/qr?qt=" + encodeURIComponent(tok.token);
    box.innerHTML = "";
    const card = document.createElement("div");
    card.className = "card qr-card";
    const head = document.createElement("div");
    head.className = "qr-head";
    head.appendChild(avatarEl(me.first_name, me.telegram_id, false,
                              me.photo_file_id));
    const nm = document.createElement("div");
    nm.className = "qr-name";
    nm.textContent = me.first_name || "Member";
    head.appendChild(nm);
    const img = document.createElement("img");
    img.className = "qr-img";
    img.alt = "My Nexora profile QR code";
    img.src = qrUrl;
    const a = document.createElement("a");
    a.className = "qr-link";
    a.href = link;
    a.textContent = link;
    const row = document.createElement("div");
    row.className = "qr-actions";
    const copy = document.createElement("button");
    copy.className = "btn";
    copy.textContent = "📋 Copy link";
    copy.onclick = () => {
      if (navigator.clipboard) navigator.clipboard.writeText(link);
      setStatus("Profile link copied.");
    };
    const dl = document.createElement("button");
    dl.className = "btn";
    dl.id = boxId === "qr-box" ? "qr-download" : "settings-qr-download";
    dl.textContent = "⬇️ Download";
    dl.onclick = () => downloadQr(dl, qrUrl);
    row.append(copy, dl);
    const note = document.createElement("p");
    note.className = "hint qr-note";
    note.textContent = "Scan this with any phone camera or Telegram — " +
      "it opens your profile in Nexora Social.";
    card.append(head, img, a, row, note);
    box.appendChild(card);
  } catch (e) { box.textContent = "Could not load your QR code."; }
}

async function downloadQr(btn, qrUrl) {
  if (btn.textContent !== "⬇️ Download") return; // double-tap guard
  btn.textContent = "⬇️ Downloading…";
  try {
    const head = await fetch(qrUrl, { method: "HEAD" });
    const ct = (head.headers.get("content-type") || "").toLowerCase();
    const ext = ct.indexOf("png") >= 0 ? "png" : "jpg";
    const fileName = "nexora-qr-" +
      String(me.first_name || "profile").toLowerCase()
        .replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") + "." + ext;
    const fullUrl = location.origin + qrUrl;
    if (window.Telegram && tg && tg.downloadFile) {
      try {
        await tg.downloadFile({ url: fullUrl, file_name: fileName });
        btn.textContent = "✅ Downloaded!";
        setStatus("QR code downloaded ✓ — check your gallery / Downloads.");
        setTimeout(() => { btn.textContent = "⬇️ Download"; }, 4000);
        return;
      } catch (e) { /* fall through to openLink below */ }
    }
    if (window.Telegram && tg && tg.openLink) {
      tg.openLink(fullUrl);
      setStatus("Opened in your browser — save the image from there.");
    } else {
      const a = document.createElement("a");
      a.href = fullUrl;
      a.download = fileName;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setStatus("QR code downloaded.");
    }
  } catch (e) { setStatus("Could not download the QR code."); }
  btn.textContent = "⬇️ Download";
}

// ----------------------------------------------------------------- init ---
// ---------------------------------------------------------------------------
// Phase 19: heartbeat — while the app is open, a beat every 30s lets the
// server measure real time-in-app and "active now" for the dashboard.
// ---------------------------------------------------------------------------
let heartbeatTimer = null;
let mediaTimer = null;
function sendHeartbeat() {
  api("/me/heartbeat", { method: "POST" }).catch(() => {});
}
function startHeartbeat() {
  if (heartbeatTimer) return;
  sendHeartbeat();
  heartbeatTimer = setInterval(sendHeartbeat, 30000);
  // Phase 164: the media token lives 1 hour — refresh it while the
  // app stays open so long sessions keep their images.
  if (!mediaTimer) mediaTimer = setInterval(refreshMediaToken, 2700000);
  // Phase 170 rider: Telegram's WebView suspends timers in
  // background, so the 45-min token refresh never fires there —
  // refresh the 1-hour media token the moment the app comes back
  // to the foreground, or every image 401s until the next tick.
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) { sendHeartbeat(); refreshMediaToken(); }
  });
}

// Phase 164: re-issue the media token (1-hour, user-bound) without
// disturbing the open app — /auth answers with the act-as identity
// when the admin is acting as a managed user, same as loadMe.
let mediaTokenRefresh = null;
async function refreshMediaToken() {
  // Phase 170 rider: a gallery of stale images can fire many
  // refreshes at once — share one in-flight /auth call.
  if (mediaTokenRefresh) return mediaTokenRefresh;
  mediaTokenRefresh = (async () => {
    try {
      // Phase 190: same 25s bound as loadMe — a hung refresh must
      // not leave mediaTokenRefresh pending forever (its catch
      // already swallows errors; a timeout just retries next time).
      const r = await api("/auth", { method: "POST",
        body: JSON.stringify({ initData }), timeoutMs: 25000 });
      if (r && r.media_token) mediaToken = r.media_token;
    } catch (e) { /* next refresh retries; images retry meanwhile */ }
  })();
  try { await mediaTokenRefresh; } finally { mediaTokenRefresh = null; }
}

async function loadMe() {
  // Phase 190: bounded /auth — without timeoutMs a wedged server
  // (Nov 26 pool outage) hangs this fetch forever and the app
  // sits on "Loading…" with no way out. Warm /auth answers in
  // <1s; 25s + 2s Phase 76 retry + 25s = 52s, inside the 60s
  // shell watchdog, so bootFailed's server message normally wins.
  me = await api("/auth", { method: "POST", body: JSON.stringify({ initData }),
    timeoutMs: 25000 });
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
let composerFiles = [];  // Phase 171: multi-pick album staging
let composerUploadId = null;

function paintAttach() {
  const chip = $("composer-attach");
  if (!composerFile) { chip.hidden = true; chip.textContent = ""; return; }
  chip.hidden = false;
  if (composerFiles.length > 1) {
    chip.textContent = "🖼 " + composerFiles.length + " photos ";
  } else {
    chip.textContent = (composerFile.type.startsWith("video") ? "🎬 " : "🖼 ") +
      composerFile.name + " ";
  }
  const x = document.createElement("button");
  x.className = "attach-x";
  x.textContent = "✕";
  x.title = "Remove";
  x.onclick = () => { composerFile = null; composerFiles = []; composerUploadId = null; $("composer-file").value = ""; paintAttach(); };
  chip.appendChild(x);
}

$("composer-media").onclick = () => $("composer-file").click();
$("composer-file").onchange = () => {
  // Phase 171: multi-pick — up to 10 photos in one album. A video
  // among photos is dropped (albums hold photos only; a video
  // still posts on its own). A single pick keeps the old flow.
  const picked = [...($("composer-file").files || [])];
  composerFiles = [];
  composerFile = null;
  composerStatus("");
  let droppedVideo = false, droppedOver = false;
  for (const f of picked) {
    const t = (f.type || "").toLowerCase();
    const ext = (f.name || "").split(".").pop().toLowerCase();
    const isVideo = t.startsWith("video") ||
      ["mp4", "mov", "webm", "mkv", "3gp", "avi", "m4v"].includes(ext);
    if (isVideo && picked.length > 1) { droppedVideo = true; continue; }
    if (composerFiles.length >= 10) { droppedOver = true; continue; }
    const cap = (isVideo ? 60 : 20) * 1024 * 1024;
    if (f.size > cap) {
      composerStatus(isVideo
        ? "That video is over 60 MB — please trim it or record at a lower resolution."
        : "That file is over 20 MB — please pick a smaller one.");
      composerFiles = [];
      composerFile = null;
      $("composer-file").value = "";
      paintAttach();
      return;
    }
    composerFiles.push(f);
  }
  if (composerFiles.length === 1) composerFile = composerFiles[0];
  if (composerFiles.length) composerUploadId = newUploadId();
  if (droppedVideo) composerStatus("Videos can't join an album — the video was left out.");
  else if (droppedOver) composerStatus("Up to 10 photos in one album — the rest were left out.");
  else if (composerFiles.length > 1) composerStatus(composerFiles.length + " photos attached ✓ — now tap Post.");
  else if (composerFile) composerStatus("Attached ✓ — now tap Post.");
  paintAttach();
  return;
};

// Phase 123: creator tools in the composer — an optional poll
// (question + 2–4 options, hidden until 📊 is tapped) and
// 💾 Draft, which keeps the text for later.
let composerPollOn = false;
$("composer-poll-toggle").onclick = () => {
  composerPollOn = !composerPollOn;
  $("composer-poll").hidden = !composerPollOn;
  $("composer-poll-toggle").classList.toggle("on", composerPollOn);
};
function composerPoll() {
  if (!composerPollOn) return null;
  const q = $("composer-poll-q").value.trim();
  const opts = [...document.querySelectorAll(".composer-poll-opt")]
    .map(i => i.value.trim()).filter(Boolean);
  if (!q && !opts.length) return null;
  return { question: q, options: opts };
}
function clearComposerPoll() {
  composerPollOn = false;
  $("composer-poll").hidden = true;
  $("composer-poll-toggle").classList.remove("on");
  $("composer-poll-q").value = "";
  document.querySelectorAll(".composer-poll-opt")
    .forEach(i => { i.value = ""; });
}
$("composer-draft").onclick = async () => {
  const text = $("composer-text").value.trim();
  if (!text) {
    composerStatus("Write something first, then save it as a draft 💾");
    return;
  }
  try {
    await api("/drafts", { method: "POST",
      body: JSON.stringify({ text }) });
    composerStatus("Draft saved ✓ — find it under 📝 My drafts in ⚙️ Settings.");
    setStatus("Draft saved.");
  } catch (e) { composerStatus("Could not save the draft."); }
};

// Phase 135: schedule this post — pick a date + time and the
// server posts it then. Text only from the composer: a photo or
// video attached here is posted right away instead (the composer
// has no media-only upload), and a poll cannot be scheduled —
// both are refused here with a plain message, never silently
// dropped. The API itself accepts media_file_id.
let composerSchedOn = false;
function schedLocalInput(d) {
  const p = n => String(n).padStart(2, "0");
  return d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate()) +
    "T" + p(d.getHours()) + ":" + p(d.getMinutes());
}
$("composer-schedule-toggle").onclick = () => {
  composerSchedOn = !composerSchedOn;
  $("composer-schedule").hidden = !composerSchedOn;
  $("composer-schedule-toggle").classList.toggle("on", composerSchedOn);
  if (composerSchedOn) {
    const inp = $("composer-sched-datetime");
    inp.min = schedLocalInput(new Date(Date.now() + 5 * 60000));
    if (!inp.value) {
      inp.value = schedLocalInput(new Date(Date.now() + 3600000));
    }
  }
};
$("composer-sched-send").onclick = async () => {
  const text = $("composer-text").value.trim();
  if (!text && !composerFile) {
    composerStatus("Write something or attach a photo/video first 📷");
    return;
  }
  if (composerFile) {
    composerStatus("Scheduling with a photo/video isn't supported yet — post it now, or remove the attachment to schedule the text 🕐");
    return;
  }
  if (composerPoll()) {
    composerStatus("Polls can't be scheduled — post it now, or clear the poll 📊");
    return;
  }
  const val = $("composer-sched-datetime").value;
  if (!val) {
    composerStatus("Pick a date and time first 🕐");
    return;
  }
  const at = new Date(val);
  if (isNaN(at.getTime()) || at.getTime() <= Date.now() + 5 * 60000) {
    composerStatus("Pick a time at least 5 minutes from now 🕐");
    return;
  }
  try {
    const row = await api("/scheduled-posts", { method: "POST",
      body: JSON.stringify({ text, scheduled_at: at.toISOString() }) });
    composerStatus("Scheduled ✓ — it will post on " +
      new Date(row.scheduled_at).toLocaleString() +
      ". See 📅 Scheduled in ⚙️ Settings.");
    setStatus("Post scheduled.");
    $("composer-text").value = "";
    composerSchedOn = false;
    $("composer-schedule").hidden = true;
    $("composer-schedule-toggle").classList.remove("on");
  } catch (e) { composerStatus("Could not schedule the post."); }
};

$("composer-post").onclick = async () => {
  const text = $("composer-text").value.trim();
  if (!text && !composerFiles.length) {
    // Phase 26: never a silent no-op — say what is missing, right
    // under the button where the member is looking.
    composerStatus("Write something or attach a photo/video first 📷");
    return;
  }
  // Phase 123: a poll needs a question and at least 2 options.
  const poll = composerPoll();
  if (poll && (!poll.question || poll.options.length < 2)) {
    composerStatus("A poll needs a question and at least 2 options 📊");
    return;
  }
  const btn = $("composer-post");
  btn.disabled = true;
  composerStatus("");
  try {
    if (composerFiles.length > 1) {
      // Phase 171: album — stage each photo (screened, no post
      // yet), then create one album post with the file_ids.
      btn.textContent = "Uploading…";
      const bar = $("composer-progress"),
            fill = $("composer-progress-fill"),
            lab = $("composer-progress-label");
      bar.hidden = false;
      fill.classList.remove("busy", "done");
      const ids = [];
      for (let i = 0; i < composerFiles.length; i++) {
        fill.style.width = Math.round(i / composerFiles.length * 100) + "%";
        lab.textContent = "Uploading photo " + (i + 1) + "/" + composerFiles.length + "…";
        btn.textContent = "Uploading photo " + (i + 1) + "/" + composerFiles.length + "…";
        const form = new FormData();
        form.append("file", await shrinkForUpload(composerFiles[i]));
        const r = await apiFormProgress("/posts/upload-media", form, () => {});
        ids.push(r.file_id);
      }
      fill.style.width = "100%";
      fill.classList.add("busy");
      lab.textContent = "Posting…";
      btn.textContent = "Sending… keep the app open";
      await api("/posts", { method: "POST",
        body: JSON.stringify({ type: "photo", caption: text,
                               media_file_ids: ids }) });
      fill.classList.remove("busy");
      fill.classList.add("done");
      lab.textContent = "Posted ✓";
      setTimeout(() => { bar.hidden = true; }, 3000);
      composerFiles = [];
      composerFile = null;
      composerUploadId = null;
      $("composer-file").value = "";
      paintAttach();
      // Phase 123: polls only go with text posts.
      if (composerPollOn) {
        composerStatus("Posted without the poll — polls only go with text posts 📊");
        clearComposerPoll();
      }
    } else if (composerFile) {
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
      composerFiles = [];
      composerUploadId = null;
      $("composer-file").value = "";
      paintAttach();
      // Phase 123: polls only go with text posts.
      if (composerPollOn) {
        composerStatus("Posted without the poll — polls only go with text posts 📊");
        clearComposerPoll();
      }
    } else {
      // Phase 123: the poll rides on text posts only.
      const body = { type: "text", caption: text };
      if (poll) body.poll = poll;
      await api("/posts", { method: "POST",
        body: JSON.stringify(body) });
      clearComposerPoll();
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
$("tab-hashtags").onclick = () => setTab("hashtags");
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
  $("trend-refresh").onclick = () => loadTrending();
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

// Phase 114: a scanned profile QR opens the app with a start
// parameter (t.me startapp link, or the WebApp URL's ?startapp=).
// After login, jump straight to that member's profile; a bad id
// just shows the profile view's usual load error.
let startParamRouted = false;
function routeStartParam() {
  if (startParamRouted) return;
  startParamRouted = true;
  let p = "";
  try {
    p = (tg.initDataUnsafe && tg.initDataUnsafe.start_param) || "";
  } catch (e) {}
  if (!p) {
    try { p = new URLSearchParams(location.search).get("startapp") || ""; }
    catch (e) {}
  }
  if (p && p.indexOf("profile_") === 0) {
    const id = parseInt(p.slice(8), 10);
    if (id) { openProfile(id); return true; }
  }
  return false;
}
function bootOk() {
  // Phase 190: disarm the inline shell watchdog — the app booted.
  // Also clear #status: if the watchdog already fired on a slow
  // boot, its "could not reach the server" line must not linger
  // on screen while the feed loads.
  window.__nxBootDone = true;
  setStatus("");
  loadAnnouncementBar();
  loadFeed(true);
  // Phase 146: a deep link (start param) wins; otherwise a
  // reload re-opens the profile the member was viewing.
  if (!routeStartParam()) restoreProfile();
}

function bootFailed(err) {
  // Phase 190: disarm the inline shell watchdog — the app did
  // reach a boot outcome (even a failed one), so the watchdog
  // must not overwrite this message with its own.
  window.__nxBootDone = true;
  // Phase 188 (Job 1): when Telegram's own script never arrived
  // the app cannot sign in at all — say so plainly and offer a
  // RETRY (reload) instead of the dead "open from inside Telegram"
  // line with a disabled button. A reload re-fetches
  // telegram-web-app.js, which is the part that failed.
  if (!window.Telegram || !window.Telegram.WebApp) {
    $("status").textContent =
      "Could not reach Telegram. Check your connection, then tap RETRY.";
    $("entry-note").textContent =
      "Telegram did not load, so the app cannot sign you in. If you opened this inside Telegram, tap RETRY to reload; if you opened it in a browser, open Nexora Social from inside Telegram instead.";
    const go = $("entry-go");
    go.disabled = false;
    go.textContent = "↻ RETRY";
    go.onclick = () => location.reload();
    return;
  }
  // Phase 190: /auth can fail because the SERVER is unreachable
  // (Nov 26 outage: pool exhausted, every request hung) — that
  // is not "opened outside Telegram". A hung /auth aborts
  // (timeoutMs) or the fetch rejects (TypeError); a 5xx is the
  // server failing — api() keeps the status on the error, since
  // the message itself may be the server's detail text. Show the
  // server message with a working RETRY instead of the dead "open
  // from inside Telegram" line with a disabled button.
  if (err && (err.name === "AbortError" || err instanceof TypeError ||
              (err.status && err.status >= 500) ||
              /^API 5/.test(err.message || ""))) {
    $("status").textContent =
      "Could not reach the server. Check your connection, then tap RETRY.";
    $("entry-note").textContent =
      "The server did not answer. Tap RETRY to reload — if it keeps happening, the service may be down, so try again in a few minutes.";
    const go = $("entry-go");
    go.disabled = false;
    go.textContent = "\u21bb RETRY";
    go.onclick = () => location.reload();
    return;
  }
  $("status").textContent = "Please open this app from inside Telegram.";
  $("entry-go").disabled = true;
  $("entry-note").textContent =
    "Please open Nexora Social from inside Telegram to continue.";
}
loadMe().then(bootOk).catch(() => {
  // Phase 76: the first attempt can fail while the free server
  // wakes up — retry once before showing the fallback above.
  setTimeout(() => {
    loadMe().then(bootOk).catch(bootFailed);
  }, 2000);
});

// Phase 76 (owner screenshot: every image on the site broken
// after a slow first open, while the data itself loaded fine):
// the WebView never retries a failed image, so one cold-start
// hiccup left the whole gallery broken until a manual reload.
// Any /media image or video that fails now retries itself with
// a short pause and a cache-buster, up to three times.
// Phase 189: when the retries are spent the image is not
// silently left as a zero-height hole (the Design gallery then
// looks text-only, exactly the owner's Nov 24 + Nov 26
// screenshots). Mark the .design-media so the card keeps its
// shape (CSS min-height) and shows its tap-to-retry button.
function markDesignImgFailed(t) {
  const media = t.closest ? t.closest(".design-media") : null;
  if (media) media.classList.add("design-img-failed");
}
// Retry one design image from scratch: clear the once-only
// guards, re-issue the token, rebuild the URL. Used by the
// card's retry button and the sheet's retry button.
async function retryDesignImg(img) {
  if (!img) return;
  const media = img.closest ? img.closest(".design-media") : null;
  if (media) media.classList.remove("design-img-failed");
  delete img.dataset.mtok; delete img.dataset.mr;
  await refreshMediaToken();
  const m = (img.getAttribute("src") || "").match(/\/media\/([^?]+)/);
  if (m) img.src = mediaUrl(decodeURIComponent(m[1]));
}
document.addEventListener("error", async (e) => {
  const t = e.target;
  if (!t || (t.tagName !== "IMG" && t.tagName !== "VIDEO")) return;
  const src = t.getAttribute("src") || "";
  if (!src.includes("/media/")) return;
  // Phase 170 rider: the URL's token may be the STALE one the app
  // itself still holds (background >1h suspends the refresh timer)
  // — re-issue first, then rebuild only if the fresh token differs
  // from the one in the URL; otherwise fall through to the
  // cache-buster retries below. The mtok guard keeps it once-only.
  const m = src.match(/\/media\/([^?]+)/);
  if (m && !t.dataset.mtok) {
    t.dataset.mtok = "1";
    await refreshMediaToken();
    if (mediaToken && !src.includes(encodeURIComponent(mediaToken))) {
      t.src = mediaUrl(decodeURIComponent(m[1]));
      return;
    }
  }
  const tries = Number(t.dataset.mr || 0);
  if (tries >= 3) { markDesignImgFailed(t); return; }
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
  // Phase 184 (audit L22): admin / chat / assistant / settings /
  // blood / skills all have sidebar entries (data-go) but were
  // missing here, so the sidebar wrongly highlighted Feed.
  const current = ["feed", "videos", "designs", "search", "tasks",
    "leaderboard", "profile", "saved", "shared", "games", "game",
    "nearby", "messages", "notifications", "qr", "trending",
    "admin", "chat", "assistant", "settings", "blood", "skills",
    "museum"]
    .find(v => !$("view-" + v).hidden) || "feed";
  // Phase 184 (audit L22): "chat" has no sidebar entry of its
  // own — it opens from Messages — so Messages stays highlighted
  // while chatting (same idea as "game" -> "games" above).
  const key = current === "game" ? "games"
    : current === "chat" ? "messages" : current;
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
    // Phase 146: "My Profile" must open the viewer's own
    // profile — showView("profile") alone would keep showing
    // whichever profile was last rendered.
    if (go === "profile" && me) openProfile(me.telegram_id);
    else if (go === "museum" && me) openMuseum(me.telegram_id);
    else showView(go);
    if (go === "profile") loadMe();
  };
});
$("gb-foot").onclick = () => {
  closeSidebar();
  // Phase 146: same as the sidebar "My Profile" item — open
  // the viewer's own profile, not the last-rendered one.
  if (me) openProfile(me.telegram_id); else showView("profile");
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
                      follow_request: "👥",
                      share: "📤", post_live: "🎬", announcement: "📣",
                      verification: "🛡️", repost: "🔁", reply: "↩️",
                      tip: "⭐", blood_request: "🩸",
                      blood_respond: "🩸",
                      skill_connect: "🤝",
                      mention: "📣" };
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
        const nm = document.createElement("span");
        nm.className = "vname";
        const nmText = document.createElement("b");
        nmText.className = "vname-text";
        nmText.textContent = n.actor_name;
        nm.appendChild(nmText);
        if (n.actor_verified) nm.appendChild(verifiedBadge());
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
    fitVerifiedNames(box);
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
let designShuffleSeed = 0;
let designLoading = false;
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
      const line = document.createElement("span");
      line.className = "vname";
      const nmText = document.createElement("span");
      nmText.className = "vname-text";
      nmText.textContent = u.first_name;
      line.appendChild(nmText);
      if (u.is_verified) line.appendChild(verifiedBadge());
      nm.appendChild(line);
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
    fitVerifiedNames(list);
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
  // Phase 189: eager, not lazy — the design IS the card's
  // content, and lazy images inside the gallery's 2-column
  // masonry never fired at all on the owner's phone (Nov 24 +
  // Nov 26: every card text-only, zero-height media area). Feed
  // images keep lazy — they work; do not touch what works.
  img.loading = "eager";
  img.alt = "Design";
  img.draggable = false;
  // Phase 67: a transparent shield over the image takes the touch,
  // so Telegram's WebView never treats a hold as an IMAGE hold and
  // pops its own Open in…/Download/Copy Link menu (owner report).
  const media = document.createElement("div");
  media.className = "design-media";
  const shield = document.createElement("div");
  shield.className = "img-shield";
  // Phase 189: a loaded image clears any earlier failed state;
  // the retry button only shows when the media is marked failed
  // (CSS). It sits above the shield (z-index) so the tap reaches
  // it, and it swallows the tap + the long-press, like the like
  // button (Phase 99).
  img.onload = () => media.classList.remove("design-img-failed");
  const retry = document.createElement("button");
  retry.type = "button";
  retry.className = "design-retry";
  retry.textContent = "↻ Couldn't load — tap to retry";
  retry.onclick = e => { e.stopPropagation(); retryDesignImg(img); };
  retry.addEventListener("pointerdown", e => e.stopPropagation());
  retry.addEventListener("pointerup", e => e.stopPropagation());
  media.append(img, shield, retry);
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



async function loadDesigns(reset) {
  paintDesignAccess();
  const grid = $("design-grid");
  if (reset) {
    // Phase 116: every fresh load mints a new shuffle seed, so a
    // refresh shows the designs in new positions; paging reuses
    // the seed, so one load never repeats or skips a design.
    designShuffleSeed = Math.floor(Math.random() * 1e9);
    designCursor = null; grid.innerHTML = "";
  }
  if (designLoading) return;
  designLoading = true;
  try {
    const url = "/designs?limit=20" +
      (designSimilar ? "&similar_to=" + designSimilar.id : "") +
      "&shuffle=" + designShuffleSeed +
      (designCursor ? "&cursor=" + designCursor : "");
    const r = await api(url);
    r.designs.forEach(d => grid.appendChild(designCard(d)));
    designCursor = r.next_cursor;
    // Phase 116: no more Load More button — the gallery keeps
    // loading itself as you scroll, until every design is shown.
    // The button stays in the DOM (other code references it).
    $("design-more").hidden = true;
    $("design-empty").hidden = grid.children.length > 0;
    maybeLoadMoreDesigns();
  } catch (e) {
    if (reset) $("design-empty").hidden = false;
  } finally {
    designLoading = false;
  }
}

// Phase 116: infinite scroll — while the Design gallery is open,
// near the bottom (or when the page is not even scrollable yet)
// the next page loads itself. The guard keeps it to one load.
function maybeLoadMoreDesigns() {
  if ($("view-designs").hidden || designLoading || !designCursor) return;
  const sc = $("app-scroll");
  if (sc.scrollHeight <= sc.clientHeight + 100 ||
      sc.scrollTop + sc.clientHeight >= sc.scrollHeight - 600) {
    loadDesigns(false);
  }
}
$("app-scroll").addEventListener("scroll", maybeLoadMoreDesigns,
                                 { passive: true });
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
    // Phase 146 (owner): pull-to-refresh on a profile re-opens
    // the profile being viewed — the old code always opened
    // the viewer's own profile instead.
    profile: () => { if (profileId) openProfile(profileId);
                     else if (me) openProfile(me.telegram_id); },
    admin: () => loadAdmin(),
  };
  let startY = null, pull = 0, busy = false;
  const THRESH = 70;
  const current = () => Object.keys(LOADERS)
    .find(v => !$("view-" + v).hidden);

  // Phase 125: the Videos page scrolls inside its own fixed overlay
  // (#view-videos), so #app-scroll never moves there and the old
  // scrollTop guard never disarmed — every upward drag was eaten as
  // a pull-to-refresh. Guard on the scroller of the open view.
  const topScroller = () => current() === "videos"
    ? document.getElementById("view-videos") : sc;
  sc.addEventListener("touchstart", e => {
    if (busy || !current() || topScroller().scrollTop > 0) return;
    startY = e.touches[0].clientY;
    pull = 0;
  }, { passive: true });
  sc.addEventListener("touchmove", e => {
    if (startY === null || busy) return;
    const dy = e.touches[0].clientY - startY;
    if (dy <= 0 || topScroller().scrollTop > 0) {
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
  const isNew = !currentDesign || currentDesign.id !== d.id;
  currentDesign = d;
  // Phase 189: a new design starts clean — a failed state (or
  // spent retry guards) from the previous design must not linger.
  const dsMedia = $("ds-media");
  if (dsMedia) dsMedia.classList.remove("design-img-failed");
  const dsImg = $("ds-img");
  delete dsImg.dataset.mtok; delete dsImg.dataset.mr;
  dsImg.src = mediaUrl(d.image_file_id);
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
  // Phase 115: a new design starts at the top of the sheet and
  // earns its own related set below; a refresh of the SAME design
  // (like / edit save) keeps its scroll place and its set.
  if (isNew) {
    $("design-sheet").scrollTop = 0;
    loadRelatedDesigns(d);
  }
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

// Phase 115 (owner: Pinterest-style related designs under an opened
// design): the sheet's "More like this" strip — the server's
// similar_to ranking (prompt-word overlap, the same engine as the
// 🔍 Similar button) — as image-only thumbnails; tapping one opens
// that design in the sheet, which then loads its own related set.
let dsRelatedSeq = 0;
async function loadRelatedDesigns(d) {
  const box = $("ds-related");
  const grid = $("ds-related-grid");
  const token = ++dsRelatedSeq;
  grid.innerHTML = "";
  box.hidden = true;
  try {
    const r = await api("/designs?similar_to=" + d.id + "&limit=12");
    if (token !== dsRelatedSeq || !currentDesign ||
        currentDesign.id !== d.id) return;
    (r.designs || []).forEach(rel => {
      const card = document.createElement("div");
      card.className = "design-card";
      const media = document.createElement("div");
      media.className = "design-media";
      const img = document.createElement("img");
      img.src = mediaUrl(rel.image_file_id);
      // Phase 189: eager, like the gallery card — same
      // never-load failure mode in the masonry strip.
      img.loading = "eager";
      img.alt = "Design";
      img.draggable = false;
      const shield = document.createElement("div");
      shield.className = "img-shield";
      img.onload = () => media.classList.remove("design-img-failed");
      const retry = document.createElement("button");
      retry.type = "button";
      retry.className = "design-retry";
      retry.textContent = "↻ Couldn't load — tap to retry";
      retry.onclick = e => { e.stopPropagation(); retryDesignImg(img); };
      retry.addEventListener("pointerdown", e => e.stopPropagation());
      retry.addEventListener("pointerup", e => e.stopPropagation());
      media.append(img, shield, retry);
      card.append(media);
      card.onclick = () => openDesignSheet(rel);
      grid.appendChild(card);
    });
    box.hidden = grid.children.length === 0;
  } catch (e) { /* related is a bonus, never the view itself */ }
}
$("design-sheet-backdrop").onclick = closeDesignSheet;
$("ds-close").onclick = closeDesignSheet;
// Phase 189: the sheet's retry button + load clearing,
// mirroring the gallery card. The sheet image is static HTML,
// so it is wired once here instead of per card.
$("ds-retry").onclick = () => retryDesignImg($("ds-img"));
$("ds-img").onload = () => {
  const m = $("ds-media");
  if (m) m.classList.remove("design-img-failed");
};
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
    syncObsDial();
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
    // Phase 133: Stars tips in the Earning Panel.
    try {
      const t = await api("/admin/tips");
      $("earn-tips-total").textContent = t.total_stars + " ⭐";
      $("earn-tips-top").textContent = t.top.length
        ? ("Top: " + t.top[0].name + " — "
          + t.top[0].total_stars + " ⭐") : "No tips yet";
    } catch (err) { /* the tips line keeps its dashes */ }
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
    t.className = "admin-title vname";
    t.appendChild(document.createTextNode("👤 "));
    const tText = document.createElement("span");
    tText.className = "vname-text";
    tText.textContent = u.first_name;
    t.appendChild(tText);
    if (u.is_verified) t.appendChild(verifiedBadge());
    if (u.is_banned) t.appendChild(document.createTextNode(" 🚫"));
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
    fitVerifiedNames(box);
  } catch (e) { box.innerHTML = '<p class="hint">Could not load details.</p>'; }
}

// --------------------------------------- Phase 121: Obsidian dial --
// The hero dial shows active members as a purple arc of total
// members. syncObsDial() reads the two hero numbers (filled by
// loadDashboard) and drives the SVG arc; it never throws — a
// missing element just leaves the arc empty.
function syncObsDial() {
  const arc = $("obs-dial-arc");
  if (!arc) return;
  const members = parseInt(($("ah-members") || {}).textContent, 10) || 0;
  const active = parseInt(($("ah-active") || {}).textContent, 10) || 0;
  let ratio = members > 0 ? active / members : 0;
  ratio = Math.min(1, Math.max(0, ratio));
  arc.setAttribute("stroke-dasharray", "527.8");
  arc.setAttribute("stroke-dashoffset", (527.8 * (1 - ratio)).toFixed(1));
}

// Phase 121: the four round buttons around the hero dial jump to
// the matching Control Panel action. Guarded by dataset on
// #view-admin so repeated loadAdmin() calls stay inert.
function wireObsQuickActions() {
  const root = $("view-admin");
  if (!root || root.dataset.obsWired) return;
  root.dataset.obsWired = "1";
  const qa = (id, fn) => { const b = $(id); if (b) b.onclick = fn; };
  qa("obs-qa-maint", () => {
    const t = $("maint-toggle");
    if (t) t.click();
  });
  qa("obs-qa-announce", () => {
    const s = $("cp-sec-site");
    if (s) s.scrollIntoView({ behavior: "smooth", block: "start" });
    const a = $("announce-text");
    if (a) a.focus();
  });
  qa("obs-qa-backup", () => {
    const s = $("cp-sec-backup");
    if (s) s.scrollIntoView({ behavior: "smooth", block: "start" });
  });
  qa("obs-qa-refresh", () => loadAdmin());
}

async function loadAdminStats() {
  const box = $("admin-stats");
  box.innerHTML = "";
  try {
    const s = await api("/admin/stats");
    [["👥 Members", s.users], ["📝 Posts", s.posts],
     ["💬 Comments", s.comments], ["🚩 Reports", s.open_reports],
     ["🚫 Banned", s.banned_users], ["⭐ Points", s.total_points],
     ["🎨 Designs", s.designs],
     ["🛡️ Verifications", s.pending_verifications]
    ].forEach(([l, v]) => box.appendChild(statCard(l, v)));
    const ahR = $("ah-reports");
    if (ahR) ahR.textContent = s.open_reports;
    // Phase 119: hero cells + Control Panel nav badges (live counts).
    const ahD = $("ah-designs"); if (ahD) ahD.textContent = s.designs;
    const ahV = $("ah-verifs");
    if (ahV) ahV.textContent = s.pending_verifications;
    const cpR = $("cp-count-reports");
    if (cpR) cpR.textContent = s.open_reports;
    const cpM = $("cp-count-members");
    if (cpM) cpM.textContent = s.users;
    const cpV = $("cp-count-verifs");
    if (cpV) cpV.textContent = s.pending_verifications;
    const cpP = $("cp-count-payouts");
    if (cpP) cpP.textContent = s.pending_payouts;
    syncObsDial();
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
      // Phase 164: download with a plain fetch — an encrypted backup
      // arrives as bytes, not JSON, so api() cannot parse it.
      const res = await fetch("/admin/backup", { headers: {
        "X-Init-Data": initData,
        ...(actAsId() ? { "X-Act-As": actAsId() } : {}) } });
      if (!res.ok) throw new Error("API " + res.status);
      const ct = res.headers.get("content-type") || "";
      const today = new Date().toISOString().slice(0, 10);
      if (ct.includes("application/octet-stream")) {
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "nexora-full-backup-" + today + ".json.enc";
        document.body.appendChild(a); a.click(); a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 4000);
        say("Backup downloaded (encrypted) ✓ — keep the file AND your key safe.");
      } else {
        const data = await res.json();
        const blob = new Blob([JSON.stringify(data, null, 1)],
                              { type: "application/json" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "nexora-full-backup-" + today + ".json";
        document.body.appendChild(a); a.click(); a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 4000);
        say("Backup downloaded ✓ — keep the file safe.");
      }
      loadBackupStatus();
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
      if (r.sent) {
        say("Sent ✓ — check your chat with the bot for the backup file.");
        loadBackupStatus();
      }
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
        // Phase 164: not JSON — it may be an encrypted backup
        // (.json.enc, a Fernet token). Hand it to the server to
        // decrypt; the server rejects it when the key is wrong.
        const text = String(rd.result || "").trim();
        if (text.startsWith("gAAAAA")) {
          backupPicked = { __encrypted: text };
          say("Encrypted backup file ready — type RESTORE below, then tap Restore now.");
        } else {
          backupPicked = null;
          say("Could not read that file — pick a Nexora backup JSON.");
        }
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
      const body = backupPicked.__encrypted
        ? { confirm: "RESTORE", backup_encrypted: backupPicked.__encrypted }
        : { confirm: "RESTORE", backup: backupPicked };
      const r = await api("/admin/restore", { method: "POST",
        body: JSON.stringify(body) });
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

// Phase 132: backup reminder — when was the last backup / restore?
// Reads GET /admin/backup-status (derived from the audit log) and
// shows it under the Backup card; warns in amber when no backup
// exists yet or the last one is more than 7 days old.
async function loadBackupStatus() {
  const el = $("backup-reminder");
  if (!el) return;
  try {
    const s = await api("/admin/backup-status");
    const fmt = iso => iso ? new Date(iso).toLocaleString() : null;
    const lb = fmt(s.last_backup_at);
    const lr = fmt(s.last_restore_at);
    el.textContent = "Last backup: " +
      (lb ? lb + " (" + (s.last_backup_kind || "backup") + ")"
          : "never") +
      " · Last restore: " + (lr || "—");
    const warn = $("backup-warn");
    if (warn) {
      if (!s.last_backup_at) {
        warn.hidden = false;
        warn.textContent = "⚠️ No backup taken yet — take one now.";
      } else {
        const days = Math.floor(
          (Date.now() - new Date(s.last_backup_at).getTime()) / 86400000);
        if (days > 7) {
          warn.hidden = false;
          warn.textContent = "⚠️ No backup in " + days +
            " days — take one now.";
        } else {
          warn.hidden = true;
        }
      }
    }
    // Phase 184 (audit L6): a backup taken while the key is
    // absent/malformed is PLAINTEXT — say so on the panel,
    // not just in the server log.
    const pw = $("backup-plaintext-warn");
    if (pw) {
      if (s.plaintext_warning) {
        pw.hidden = false;
        pw.textContent = "⚠️ Backups are currently PLAINTEXT — "
          + "BACKUP_ENCRYPTION_KEY is not set on the server. "
          + "Set it in Render before the next backup.";
      } else {
        pw.hidden = true;
      }
    }
  } catch (e) {
    el.textContent = "Last backup: unknown";
  }
}

// Phase 141: weekly auto-backup — toggle + last auto-backup line
// on the admin Backup card. Reads GET /admin/auto-backup.
async function loadAutoBackup() {
  const line = $("auto-backup-line");
  const tog = $("auto-backup-toggle");
  if (!line || !tog) return;
  try {
    const s = await api("/admin/auto-backup");
    const fmt = iso => iso ? new Date(iso).toLocaleString() : null;
    const last = fmt(s.last_auto_backup_at);
    const next = fmt(s.next_due_at);
    line.textContent = "Auto-backup: " + (s.enabled ? "on (weekly)" : "off") +
      " · Last auto-backup: " + (last || "never") +
      (s.enabled && next ? " · Next: " + next : "");
    tog.checked = !!s.enabled;
    tog.onchange = async () => {
      tog.disabled = true;
      try {
        const r = await api("/admin/auto-backup", { method: "POST",
          body: JSON.stringify({ enabled: tog.checked }) });
        tog.checked = !!r.enabled;
        loadAutoBackup();
      } catch (e) { tog.checked = !tog.checked; }
      tog.disabled = false;
    };
  } catch (e) { line.textContent = "Auto-backup: unknown"; }
}

// ------------------------------------------- Phase 119: Control Panel --
// One home for everything admin: the section nav jumps to each part
// of the panel (counts on the nav come from loadAdminStats), Site
// Controls flips maintenance + the feed banner, the Audit Log shows
// every privileged action, and Content gains the design list.
function wireControlPanel() {
  const nav = $("cp-nav");
  if (!nav || nav.dataset.wired) return;
  nav.dataset.wired = "1";
  nav.querySelectorAll("button[data-target]").forEach(btn => {
    btn.onclick = () => {
      const el = $(btn.dataset.target);
      if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
    };
  });
}

function wireCpButtons() {
  const mt = $("maint-toggle");
  if (mt && !mt.dataset.wired) {
    mt.dataset.wired = "1"; mt.onclick = toggleMaintenance;
  }
  const as = $("announce-save");
  if (as && !as.dataset.wired) {
    as.dataset.wired = "1"; as.onclick = saveAnnouncement;
  }
  const ac = $("announce-clear");
  if (ac && !ac.dataset.wired) {
    ac.dataset.wired = "1"; ac.onclick = clearAnnouncement;
  }
  const ar = $("audit-refresh");
  if (ar && !ar.dataset.wired) {
    ar.dataset.wired = "1"; ar.onclick = loadAuditLog;
  }
  const aa = $("audit-apply");
  if (aa && !aa.dataset.wired) {
    aa.dataset.wired = "1"; aa.onclick = applyAuditFilters;
  }
  const acl = $("audit-clear");
  if (acl && !acl.dataset.wired) {
    acl.dataset.wired = "1"; acl.onclick = clearAuditFilters;
  }
  const am = $("audit-more");
  if (am && !am.dataset.wired) {
    am.dataset.wired = "1"; am.onclick = loadAuditMore;
  }
  const cg = $("admin-content-go");
  if (cg && !cg.dataset.wired) {
    cg.dataset.wired = "1"; cg.onclick = searchAdminContent;
  }
  const cc = $("admin-content-clear");
  if (cc && !cc.dataset.wired) {
    cc.dataset.wired = "1"; cc.onclick = () => {
      const q = $("admin-content-q"); if (q) q.value = "";
      const st = $("admin-content-status");
      if (st) st.textContent = "";
      loadAdminPosts();
    };
  }
  const ba = $("bw-add");
  if (ba && !ba.dataset.wired) {
    ba.dataset.wired = "1"; ba.onclick = addBannedWord;
  }
  const sr = $("sec-refresh");
  if (sr && !sr.dataset.wired) {
    sr.dataset.wired = "1"; sr.onclick = loadSecurityLog;
  }
  const hr = $("health-refresh");
  if (hr && !hr.dataset.wired) {
    hr.dataset.wired = "1"; hr.onclick = loadHealth;
  }
}

async function loadSiteControls() {
  const st = $("maint-status"), tg = $("maint-toggle");
  if (!st || !tg) return;
  try {
    const m = await api("/admin/maintenance");
    st.textContent = m.maintenance
      ? (m.env_locked
        ? "Maintenance is ON (set by the server — the panel cannot switch it off)."
        : "Maintenance is ON — members see \u201cdown for maintenance\u201d.")
      : "Maintenance is OFF — the app is open to everyone.";
    tg.textContent = m.maintenance
      ? "Switch maintenance OFF" : "Switch maintenance ON";
    tg.disabled = !!m.env_locked;
    tg.dataset.maintOn = m.maintenance ? "1" : "0";
  } catch (e) { st.textContent = "Could not load maintenance state."; }
  const ann = $("announce-text");
  if (ann && !ann.dataset.filled) {
    try {
      const a = await api("/announcement");
      ann.value = a.text || "";
      ann.dataset.filled = "1";
    } catch (e) { /* banner read is best-effort */ }
  }
}

async function toggleMaintenance() {
  const tg = $("maint-toggle"), st = $("maint-status");
  if (!tg) return;
  const wantOn = tg.dataset.maintOn !== "1";
  if (!confirm(wantOn
      ? "Switch maintenance ON? Members will see the app as down."
      : "Switch maintenance OFF? The app opens again.")) return;
  tg.disabled = true;
  try {
    await api("/admin/maintenance", { method: "POST",
      body: JSON.stringify({ on: wantOn }) });
    setStatus(wantOn ? "Maintenance ON." : "Maintenance OFF — app is open.");
    loadSiteControls();
  } catch (e) { setStatus("Could not change maintenance."); }
  tg.disabled = false;
}

async function saveAnnouncement() {
  const box = $("announce-text"), st = $("announce-status");
  if (!box) return;
  try {
    const r = await api("/admin/announcement", { method: "POST",
      body: JSON.stringify({ text: box.value }) });
    if (st) st.textContent = r.text
      ? "Announcement is live on every feed ✓"
      : "Announcement cleared.";
    loadAnnouncementBar();
  } catch (e) {
    if (st) st.textContent = "Could not save the announcement.";
  }
}

async function clearAnnouncement() {
  const box = $("announce-text");
  if (box) box.value = "";
  saveAnnouncement();
}

// --------------------------------------- Phase 142: Audit Log filter -------
// The Audit Log was a bare newest-50 list. It now filters by action,
// actor (id or username) and date range, with paging (Show more).
let auditFilter = { action: "", actor: "", from: "", to: "" };
let auditOffset = 0;
let auditTotal = 0;
let auditActions = [];
function auditQuery() {
  const p = new URLSearchParams({ limit: "50", offset: String(auditOffset) });
  if (auditFilter.action) p.set("action", auditFilter.action);
  if (auditFilter.actor) p.set("actor", auditFilter.actor);
  if (auditFilter.from) p.set("from", auditFilter.from);
  if (auditFilter.to) p.set("to", auditFilter.to);
  return "/admin/audit-log?" + p.toString();
}
function renderAuditRow(box, e) {
  const row = document.createElement("div");
  row.className = "audit-row";
  const t = document.createElement("div");
  t.className = "admin-title";
  t.textContent = e.action + (e.target_id ? " → " + e.target_id : "");
  const s = document.createElement("div");
  s.className = "admin-sub";
  s.textContent = "admin " + e.admin_id + " · " +
    (e.detail || "") + " · " + relTime(e.created_at);
  row.append(t, s);
  box.appendChild(row);
}
function fillAuditActions() {
  const sel = $("audit-action");
  if (!sel) return;
  const cur = sel.value;
  sel.innerHTML = '<option value="">All actions</option>';
  auditActions.forEach(a => {
    const o = document.createElement("option");
    o.value = a; o.textContent = a;
    sel.appendChild(o);
  });
  if (auditActions.includes(cur)) sel.value = cur;
}
function updateAuditMore() {
  const btn = $("audit-more");
  if (btn) btn.hidden = !(auditTotal > auditOffset + 50);
}
async function loadAuditLog() {
  const box = $("admin-audit-log");
  if (!box) return;
  box.innerHTML = "";
  auditOffset = 0;
  try {
    const r = await api(auditQuery());
    auditTotal = r.total || 0;
    auditActions = [...new Set((r.entries || []).map(e => e.action))];
    fillAuditActions();
    if (!r.entries.length) {
      box.innerHTML = '<p class="hint">No admin actions match.</p>';
    } else {
      r.entries.forEach(e => renderAuditRow(box, e));
    }
    updateAuditMore();
  } catch (e) { box.textContent = "Could not load the audit log."; }
}
async function loadAuditMore() {
  const box = $("admin-audit-log");
  if (!box) return;
  auditOffset += 50;
  try {
    const r = await api(auditQuery());
    auditTotal = r.total || 0;
    (r.entries || []).forEach(e => renderAuditRow(box, e));
    updateAuditMore();
  } catch (e) { /* keep what is shown */ }
}
function applyAuditFilters() {
  auditFilter = {
    action: ($("audit-action") || {}).value || "",
    actor: (($("audit-actor") || {}).value || "").trim(),
    from: ($("audit-from") || {}).value || "",
    to: ($("audit-to") || {}).value || "",
  };
  loadAuditLog();
}
function clearAuditFilters() {
  auditFilter = { action: "", actor: "", from: "", to: "" };
  const set = (id, v) => { const el = $(id); if (el) el.value = v; };
  set("audit-action", ""); set("audit-actor", "");
  set("audit-from", ""); set("audit-to", "");
  loadAuditLog();
}

// ------------------------------------- Phase 131: broadcast history ------
// The Broadcast section used to be fire-and-forget. Past broadcasts
// now list here (newest first) with the target group and how many
// of the targeted members actually got the DM.
const BC_TARGET_LABELS = {
  all: "Everyone", verified: "Verified only",
  new_7d: "Joined in last 7 days", inactive_30d: "Inactive 30+ days",
};
async function loadBroadcasts() {
  const box = $("admin-bc-history");
  if (!box) return;
  box.innerHTML = "";
  try {
    const r = await api("/admin/broadcasts?limit=20");
    if (!r.broadcasts.length) {
      box.innerHTML = '<p class="hint">No broadcasts sent yet.</p>';
      return;
    }
    r.broadcasts.forEach(b => {
      const row = document.createElement("div");
      row.className = "audit-row";
      const t = document.createElement("div");
      t.className = "admin-title";
      t.textContent = (BC_TARGET_LABELS[b.target] || b.target) +
        " \u00b7 " + b.delivered_count + " of " + b.total_count +
        " delivered";
      const s = document.createElement("div");
      s.className = "admin-sub";
      s.textContent = b.text.slice(0, 120) + " \u00b7 " + relTime(b.sent_at);
      row.append(t, s);
      box.appendChild(row);
    });
  } catch (e) { box.textContent = "Could not load broadcast history."; }
}


let secKind = "";
let secEntries = [];
async function loadSecurityLog() {
  const box = $("admin-security-log");
  if (!box) return;
  box.innerHTML = "";
  try {
    const r = await api("/admin/security-log?limit=100");
    secEntries = r.entries || [];
    renderSecLog();
  } catch (e) { box.textContent = "Could not load the security log."; }
}
function renderSecLog() {
  const box = $("admin-security-log");
  if (!box) return;
  const chips = $("sec-chips");
  if (chips) {
    chips.innerHTML = "";
    const kinds = ["", ...new Set(secEntries.map(e => e.kind))];
    kinds.forEach(k => {
      const ch = document.createElement("button");
      ch.type = "button";
      ch.className = "ph-chip" + (secKind === k ? " active" : "");
      ch.textContent = k === "" ? "All" : k;
      ch.onclick = () => { secKind = k; renderSecLog(); };
      chips.appendChild(ch);
    });
  }
  box.innerHTML = "";
  const rows = secEntries.filter(e => !secKind || e.kind === secKind);
  if (!rows.length) {
    box.innerHTML = '<p class="hint">No security events yet.</p>';
    return;
  }
  rows.forEach(e => {
    const row = document.createElement("div");
    row.className = "audit-row";
    const t = document.createElement("div");
    t.className = "admin-title";
    t.textContent = e.kind + (e.actor_id ? " · " + e.actor_id : "");
    const s = document.createElement("div");
    s.className = "admin-sub";
    s.textContent = (e.detail || "") + " · " + relTime(e.created_at);
    row.append(t, s);
    box.appendChild(row);
  });
}

// --------------------------------------- Phase 130: System Health --------
// The Admin Panel had no in-app view of the platform's health — a
// failed deploy was only visible in the Render dashboard. The new
// System Health section shows the live version, commit, uptime,
// database size, row counts for the key tables, and recent server
// errors (from the Phase 128 security log).
function fmtUptime(sec) {
  sec = Math.max(0, Math.floor(sec || 0));
  const d = Math.floor(sec / 86400);
  const h = Math.floor((sec % 86400) / 3600);
  const m = Math.floor((sec % 3600) / 60);
  if (d) return d + "d " + h + "h " + m + "m";
  if (h) return h + "h " + m + "m";
  return m + "m";
}

function fmtBytes(n) {
  if (n == null) return "—";
  if (n < 1024) return n + " B";
  if (n < 1048576) return (n / 1024).toFixed(1) + " KB";
  return (n / 1048576).toFixed(1) + " MB";
}

// Phase 191 (pool leak): "checked out / size" for the DB pool.
function poolText(p) {
  if (!p || p.size == null || p.checkedout == null) return "—";
  return p.checkedout + " / " + p.size + " checked out";
}

async function loadHealth() {
  const box = $("admin-health");
  if (!box) return;
  box.innerHTML = "";
  try {
    const h = await api("/admin/health");
    const grid = document.createElement("div");
    grid.className = "admin-stats";
    grid.appendChild(statCard("🔖 Version",
      h.version == null ? "—" : "?v=" + h.version));
    grid.appendChild(statCard("💾 Commit", h.commit || "—"));
    grid.appendChild(statCard("⏱️ Uptime", fmtUptime(h.uptime_seconds)));
    grid.appendChild(statCard("🗄️ Database", fmtBytes(h.db_size_bytes)));
    // Phase 191 (pool leak): live pool gauges on the System Health
    // card, so a future wedge is visible before it kills the site.
    grid.appendChild(statCard("🔌 DB pool", poolText(h.pool)));
    box.appendChild(grid);
    // Phase 183 (audit M18): screening must never be silently
    // off — the Admin Panel says so when the Gemini key is absent.
    if (h.screening_active === false) {
      const warn = document.createElement("div");
      warn.className = "admin-title";
      warn.textContent = "⚠️ " + (h.screening_warning ||
        "Media screening is OFF — GEMINI_API_KEY is not set.");
      box.appendChild(warn);
    }
    const title = document.createElement("div");
    title.className = "admin-title";
    title.textContent = "📊 Rows";
    box.appendChild(title);
    Object.entries(h.tables || {}).forEach(([name, n]) => {
      const row = document.createElement("div");
      row.className = "audit-row";
      const t = document.createElement("div");
      t.className = "admin-title";
      t.textContent = name;
      const s = document.createElement("div");
      s.className = "admin-sub";
      s.textContent = String(n);
      row.append(t, s);
      box.appendChild(row);
    });
    const err = document.createElement("div");
    err.className = "admin-title";
    err.textContent = "⚠️ Server errors (24h): " + h.errors_24h;
    box.appendChild(err);
    (h.recent_errors || []).forEach(e => {
      const row = document.createElement("div");
      row.className = "audit-row";
      const t = document.createElement("div");
      t.className = "admin-title";
      t.textContent = "server_error #" + e.id;
      const s = document.createElement("div");
      s.className = "admin-sub";
      s.textContent = (e.detail || "") + " · " + relTime(e.created_at);
      row.append(t, s);
      box.appendChild(row);
    });
    if (!h.recent_errors || !h.recent_errors.length) {
      const none = document.createElement("p");
      none.className = "hint";
      none.textContent = "No server errors recorded.";
      box.appendChild(none);
    }
    const chk = $("health-checked");
    if (chk) chk.textContent = "Last checked: " + new Date().toLocaleString();
  } catch (e) { box.textContent = "Could not load system health."; }
}

async function loadAdminDesigns() {
  const box = $("admin-designs");
  if (!box) return;
  box.innerHTML = "";
  try {
    const r = await api("/admin/designs?limit=30");
    if (!r.designs.length) {
      box.innerHTML = '<p class="hint">No designs yet.</p>';
      return;
    }
    r.designs.forEach(d => {
      const row = document.createElement("div");
      row.className = "card admin-row";
      const info = document.createElement("div");
      info.className = "admin-info";
      const t = document.createElement("div");
      t.className = "admin-title";
      t.textContent = "🎨 #" + d.id + " · 🤍 " + d.like_count;
      const s = document.createElement("div");
      s.className = "admin-sub";
      s.textContent = d.prompt || "(no prompt)";
      info.append(t, s);
      row.appendChild(info);
      const btn = document.createElement("button");
      btn.className = "danger-btn"; btn.textContent = "Remove";
      btn.onclick = async () => {
        if (!confirm("Remove design #" + d.id + "?")) return;
        await api("/admin/designs/" + d.id, { method: "DELETE" });
        loadAdminDesigns(); loadAdminStats();
      };
      row.appendChild(btn);
      box.appendChild(row);
    });
  } catch (e) { box.textContent = "Could not load designs."; }
}

async function loadAnnouncementBar() {
  const bar = $("announce-bar");
  if (!bar) return;
  try {
    const a = await api("/announcement");
    if (a.text) { bar.textContent = "📣 " + a.text; bar.hidden = false; }
    else bar.hidden = true;
  } catch (e) { bar.hidden = true; }
}

// Phase 164 (H1): authenticator gate for the Admin Panel. When a
// TOTP secret is configured, the panel stays hidden until the admin
// proves a fresh code; the server enforces the same rule on every
// admin call, so this is UX, not the security boundary.
async function totpGateAdmin() {
  let ts = null;
  try { ts = await api("/admin/totp/status"); } catch (e) { return false; }
  wireTotpCard(ts);
  if (!ts || !ts.configured || ts.verified) return false;
  const view = $("view-admin");
  if (!view) return false;
  if ($("totp-gate")) return true;
  // Phase 165: the setup card stays visible next to the gate.
  // Phase 166: the card carries no setup button any more — the
  // secret must never be visible on this screen, in any form.
  [...view.children].forEach(el => { if (el.id !== "totp-card") el.hidden = true; });
  const gate = document.createElement("div");
  gate.className = "card totp-glass";
  gate.id = "totp-gate";
  const title = document.createElement("b");
  title.textContent = "🔐 Admin verification";
  const hint = document.createElement("p");
  hint.className = "hint";
  hint.textContent = "Enter the 6-digit code from your authenticator app to open the Admin Panel.";
  const msg = document.createElement("p");
  msg.className = "hint";
  msg.id = "totp-msg";
  // Phase 194: glassy OTP — six digit boxes in the style of the
  // owner's "Glassy OTP V4" reference video (4 boxes there; TOTP
  // codes are 6 digits, so 6 boxes here). Typing auto-advances,
  // paste fills all boxes, a full code auto-verifies — no button.
  const row = document.createElement("div");
  row.className = "totp-otp-row";
  const boxes = [];
  let verifying = false;
  const readCode = () => boxes.map(b => b.value).join("");
  const clearBoxes = () => { boxes.forEach(b => { b.value = ""; }); };
  const verify = async () => {
    if (verifying) return;
    const code = readCode();
    if (code.length !== 6) return;
    verifying = true;
    msg.textContent = "Checking…";
    try {
      await api("/admin/totp/verify", { method: "POST",
        body: JSON.stringify({ code }) });
      // Success state (video): green check + "Verified" + a small
      // confetti burst, then the panel opens as before.
      row.hidden = true;
      msg.hidden = true;
      const ok = document.createElement("div");
      ok.className = "totp-success";
      const tick = document.createElement("span");
      tick.className = "totp-check";
      tick.textContent = "✓";
      const okText = document.createElement("b");
      okText.textContent = "Verified";
      const burst = document.createElement("div");
      burst.className = "totp-confetti";
      const colours = ["#34D399", "#60A5FA", "#FBBF24", "#F8FAFC", "#22D3EE"];
      for (let i = 0; i < 24; i++) {
        const piece = document.createElement("span");
        piece.className = "totp-confetti-piece";
        piece.style.background = colours[i % colours.length];
        piece.style.left = (8 + (i * 37) % 84) + "%";
        piece.style.setProperty("--dx", (((i * 53) % 120) - 60) + "px");
        piece.style.animationDelay = ((i % 8) * 40) + "ms";
        burst.appendChild(piece);
      }
      ok.append(tick, okText, burst);
      gate.appendChild(ok);
      setTimeout(() => {
        gate.remove();
        [...view.children].forEach(el => { el.hidden = false; });
        loadAdmin();
      }, 900);
    } catch (e) {
      verifying = false;
      msg.textContent = e.message || "Wrong code — try again.";
      row.classList.add("totp-shake");
      boxes.forEach(b => b.classList.add("totp-error"));
      clearBoxes();
      boxes[0].focus();
      setTimeout(() => { row.classList.remove("totp-shake"); }, 500);
    }
  };
  for (let i = 0; i < 6; i++) {
    const box = document.createElement("input");
    box.className = "totp-digit";
    box.type = "text";
    box.inputMode = "numeric";
    box.maxLength = 1;
    box.autocomplete = "one-time-code";
    box.setAttribute("aria-label", "Digit " + (i + 1));
    box.addEventListener("input", () => {
      box.value = box.value.replace(/\D/g, "").slice(0, 1);
      boxes.forEach(b => b.classList.remove("totp-error"));
      if (box.value && i < 5) boxes[i + 1].focus();
      if (readCode().length === 6) verify();
    });
    box.addEventListener("keydown", (ev) => {
      if (ev.key === "Backspace" && !box.value && i > 0) {
        ev.preventDefault();
        boxes[i - 1].value = "";
        boxes[i - 1].focus();
      }
    });
    box.addEventListener("paste", (ev) => {
      ev.preventDefault();
      const pasted = ev.clipboardData && ev.clipboardData.getData
        ? ev.clipboardData.getData("text") : "";
      const digits = pasted.replace(/\D/g, "").slice(0, 6);
      if (!digits) return;
      for (let j = 0; j < digits.length; j++) boxes[j].value = digits[j];
      boxes.forEach(b => b.classList.remove("totp-error"));
      boxes[Math.min(digits.length, 5)].focus();
      if (digits.length === 6) verify();
    });
    boxes.push(box);
    row.appendChild(box);
  }
  gate.append(title, hint, row, msg);
  view.prepend(gate);
  boxes[0].focus();
  return true;
}

function wireTotpCard(ts) {
  const view = $("view-admin");
  if (!view || $("totp-card")) return;
  const card = document.createElement("div");
  card.className = "card";
  card.id = "totp-card";
  const title = document.createElement("b");
  title.textContent = "🔐 Admin verification (TOTP)";
  const st = document.createElement("p");
  st.className = "hint";
  st.textContent = ts && ts.configured
    ? "Authenticator verification is ON for admins."
    : "Authenticator verification is OFF — set ADMIN_TOTP_SECRET in Render to turn it on.";
  card.append(title, st);
  view.prepend(card);
}

async function loadAdmin() {
// Phase 127: crypto payout — wallet form, payout request and the
// member's own requests, inside the Monetization card on Me.
async function loadPayoutBox(card, mon) {
  const box = document.createElement("div");
  box.className = "payout-box";
  box.id = "payout-box";
  const title = document.createElement("b");
  title.textContent = "💸 Payout (crypto)";
  box.appendChild(title);
  const hint = document.createElement("p");
  hint.className = "hint";
  hint.textContent = "Save your wallet, then request a payout in " +
    "points. The admin reviews it, sets the crypto amount and pays " +
    "it manually.";
  box.appendChild(hint);
  try {
    const w = await api("/me/wallet");
    const netSel = document.createElement("select");
    netSel.id = "payout-network";
    ["TON", "Gram", "USDT"].forEach(n => {
      const o = document.createElement("option");
      o.value = n;
      o.textContent = n;
      netSel.appendChild(o);
    });
    if (w.wallet_network) netSel.value = w.wallet_network;
    const addr = document.createElement("input");
    addr.id = "payout-address";
    addr.type = "text";
    addr.maxLength = 256;
    addr.placeholder = "Your wallet address";
    addr.value = w.wallet_address || "";
    const saveBtn = document.createElement("button");
    saveBtn.id = "payout-save-wallet";
    saveBtn.textContent = "Save wallet";
    saveBtn.onclick = async () => {
      try {
        await api("/me/wallet", { method: "POST",
          body: JSON.stringify({ network: netSel.value,
                                 address: addr.value.trim() }) });
        setStatus("Wallet saved.");
      } catch (e) { setStatus("Could not save the wallet."); }
    };
    box.append(netSel, addr, saveBtn);
    const pts = document.createElement("input");
    pts.id = "payout-points";
    pts.type = "number";
    pts.min = "1";
    pts.placeholder = "Points";
    const reqBtn = document.createElement("button");
    reqBtn.id = "payout-request";
    reqBtn.textContent = "Request payout";
    if (!mon.unlocked) {
      reqBtn.disabled = true;
      const lockNote = document.createElement("p");
      lockNote.className = "hint";
      lockNote.textContent = "Payout unlocks with monetization — " +
        "meet every target above first.";
      box.appendChild(lockNote);
    }
    reqBtn.onclick = async () => {
      const n = parseInt(pts.value, 10);
      if (!n || n <= 0) { setStatus("Enter the points to pay out."); return; }
      try {
        await api("/me/payout/request", { method: "POST",
          body: JSON.stringify({ points: n }) });
        setStatus("Payout requested — the admin will review it.");
        loadPayoutList();
      } catch (e) { setStatus(e.message || "Could not request the payout."); }
    };
    box.append(pts, reqBtn);
    const list = document.createElement("div");
    list.id = "payout-my-list";
    box.appendChild(list);
    loadPayoutList();
  } catch (e) {
    const err = document.createElement("p");
    err.className = "hint";
    err.textContent = "Could not load the payout section.";
    box.appendChild(err);
  }
  card.appendChild(box);
}

async function loadPayoutList() {
  const list = $("payout-my-list");
  if (!list) return;
  list.innerHTML = "";
  try {
    const r = await api("/me/payouts");
    if (!r.requests.length) {
      list.innerHTML = '<p class="hint">No payout requests yet.</p>';
      return;
    }
    r.requests.forEach(q => {
      const row = document.createElement("div");
      row.className = "mon-row";
      const left = document.createElement("span");
      left.textContent = "💸 " + q.points + " points · " +
        q.status.toUpperCase() +
        (q.amount ? " · " + q.amount + " " + (q.currency || "") : "") +
        (q.tx_ref ? " · tx " + q.tx_ref : "");
      row.appendChild(left);
      list.appendChild(row);
    });
  } catch (e) { list.textContent = "Could not load payout requests."; }
}

// Phase 127: admin payout queue — approve (set amount), reject,
// and mark paid with the transaction reference.
async function loadPayouts() {
  const box = $("admin-payouts");
  if (!box) return;
  box.innerHTML = "";
  try {
    const r = await api("/admin/payouts");
    if (!r.requests.length) {
      box.innerHTML = '<p class="hint">No payout requests yet.</p>';
      return;
    }
    r.requests.forEach(q => {
      const rowEl = document.createElement("div");
      rowEl.className = "card admin-row";
      const info = document.createElement("div");
      info.className = "admin-info";
      const t = document.createElement("div");
      t.className = "admin-title";
      t.textContent = (q.first_name || ("ID " + q.user_id)) +
        (q.username ? " (@" + q.username + ")" : "") +
        " — " + q.points + " points · " + q.status.toUpperCase();
      const s = document.createElement("div");
      s.className = "admin-sub";
      s.textContent = (q.wallet_network || "") + " " +
        (q.wallet_address || "") +
        (q.amount ? " · " + q.amount + " " + (q.currency || "") : "") +
        (q.tx_ref ? " · tx " + q.tx_ref : "") +
        " · requested " + relTime(q.requested_at);
      info.append(t, s);
      rowEl.appendChild(info);
      if (q.status === "pending") {
        const amt = document.createElement("input");
        amt.id = "payout-amount-" + q.id;
        amt.type = "text";
        amt.placeholder = "Amount";
        amt.style.width = "90px";
        const cur = document.createElement("select");
        cur.id = "payout-currency-" + q.id;
        ["TON", "Gram", "USDT"].forEach(n => {
          const o = document.createElement("option");
          o.value = n; o.textContent = n; cur.appendChild(o);
        });
        const ok = document.createElement("button");
        ok.textContent = "✓ Approve";
        ok.onclick = () => decidePayout(q.id, "approve");
        const no = document.createElement("button");
        no.className = "danger-btn";
        no.textContent = "Reject";
        no.onclick = () => decidePayout(q.id, "reject");
        rowEl.append(amt, cur, ok, no);
      } else if (q.status === "approved") {
        const tx = document.createElement("input");
        tx.id = "payout-tx-" + q.id;
        tx.type = "text";
        tx.placeholder = "Transaction reference";
        const paid = document.createElement("button");
        paid.textContent = "Mark paid";
        paid.onclick = () => markPayoutPaid(q.id);
        rowEl.append(tx, paid);
      }
      box.appendChild(rowEl);
    });
  } catch (e) { box.textContent = "Could not load payout requests."; }
}

async function decidePayout(id, action) {
  try {
    const body = { action };
    if (action === "approve") {
      body.amount = ($("payout-amount-" + id) || {}).value || "";
      body.currency = ($("payout-currency-" + id) || {}).value || "";
    }
    await api("/admin/payouts/" + id + "/decide",
              { method: "POST", body: JSON.stringify(body) });
    setStatus(action === "approve" ? "Payout approved."
                                   : "Payout rejected.");
    loadPayouts();
  } catch (e) { setStatus(e.message || "Could not decide that payout."); }
}

async function markPayoutPaid(id) {
  try {
    const tx = (($("payout-tx-" + id) || {}).value || "").trim();
    if (!tx) { setStatus("Enter the transaction reference first."); return; }
    await api("/admin/payouts/" + id + "/paid",
              { method: "POST", body: JSON.stringify({ tx_ref: tx }) });
    setStatus("Payout marked as paid.");
    loadPayouts();
  } catch (e) { setStatus(e.message || "Could not mark the payout paid."); }
}

  if (!me || !me.is_admin) return;
  if (await totpGateAdmin()) return;
  loadEarnings();
  loadDashboard();
  loadAdminStats();
  loadAdminReports();
  refreshAdminMembers();
  loadVerifications();
  loadPayouts();
  loadManaged();
  loadAdminComments();
  prefillOfficial();
  loadAdminPosts();
  wireControlPanel();
  wireCpButtons();
  loadSiteControls();
  loadAuditLog();
  loadBannedWords();
  loadSecurityLog();
  loadHealth();
  loadAdminDesigns();
  wireVbu();
  wireBackupCard();
  loadBackupStatus();
  loadAutoBackup();
  loadBroadcasts();
  wireObsQuickActions();
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

// --------------------------------------- Phase 129: Members browse ------
// The Members section was search-only. It now also browses: a sort
// dropdown + All/Verified/Banned chips above the list, "All members"
// with a Show more button (offset paging). Searching still shows
// search results instead; clearing the search returns to browse.
const adminBrowse = { sort: "points", filter: "all", nextOffset: 0,
                      loading: false };

function adminBrowseOrder() {
  return adminBrowse.sort === "name" ? "asc" : "desc";
}

function adminMemberRow(u) {
  const row = document.createElement("div");
  row.className = "card admin-row";
  const info = document.createElement("div");
  info.className = "admin-info";
  const t = document.createElement("div");
  t.className = "admin-title vname";
  const tText = document.createElement("span");
  tText.className = "vname-text";
  tText.textContent = u.first_name;
  t.appendChild(tText);
  if (u.is_verified) t.appendChild(verifiedBadge());
  if (u.is_managed) t.appendChild(document.createTextNode(" 🤖"));
  if (u.is_banned) t.appendChild(document.createTextNode(" 🚫"));
  const s = document.createElement("div");
  s.className = "admin-sub";
  s.textContent = (u.username ? "@" + u.username + " · " : "") +
    "ID " + u.telegram_id + " · ⭐ " +
    (u.lifetime_points != null ? u.lifetime_points : u.points) +
    (u.followers != null ? " · 👥 " + u.followers : "") +
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
      refreshAdminMembers();
      loadAdminStats();
    } catch (e) { alert(e.message || "Action failed"); }
  };
  row.append(info, details, btn);
  fitVerifiedNamesSoon(row);
  return row;
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
    r.users.forEach(u => box.appendChild(adminMemberRow(u)));
  } catch (e) { box.textContent = "Could not load members."; }
}

async function loadAdminBrowse(reset) {
  if (adminBrowse.loading) return;
  if (!reset && adminBrowse.nextOffset == null) return;
  adminBrowse.loading = true;
  const box = $("admin-users");
  const more = $("admin-browse-more");
  if (reset) { adminBrowse.nextOffset = 0; box.innerHTML = ""; }
  try {
    const r = await api("/admin/users?sort=" + adminBrowse.sort +
      "&order=" + adminBrowseOrder() +
      "&filter=" + adminBrowse.filter +
      "&limit=20&offset=" + adminBrowse.nextOffset);
    if (!r.users.length && adminBrowse.nextOffset === 0) {
      box.innerHTML = '<p class="hint">No members found.</p>';
    }
    r.users.forEach(u => box.appendChild(adminMemberRow(u)));
    adminBrowse.nextOffset = r.next_offset;
    more.hidden = r.next_offset == null;
  } catch (e) {
    if (adminBrowse.nextOffset === 0) box.textContent = "Could not load members.";
  }
  adminBrowse.loading = false;
}

function refreshAdminMembers() {
  const q = ($("admin-user-q").value || "").trim();
  const browse = $("admin-browse");
  const more = $("admin-browse-more");
  if (q) {
    browse.hidden = true;
    more.hidden = true;
    loadAdminUsers(q);
  } else {
    browse.hidden = false;
    loadAdminBrowse(true);
  }
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
        'followers or 50 referrals.</p>';
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
      s.textContent = "👥 " + q.followers + " followers · 🔗 " +
        q.referrals + " referrals · 📝 " +
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
    refreshAdminMembers();
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
    refreshAdminMembers();
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
    refreshAdminMembers();
    loadDashboard(); loadAdminStats();
  } catch (e) { setStatus("Could not delete that member."); }
}

// --------------------------------------- Phase 120: Verify by Username --
// Control Panel section: the admin types a @username, sees the
// member's card, and grants or removes the blue tick on the spot.
// A grant/revoke that changes nothing is a no-op on the server.
let vbuUser = null;
function wireVbu() {
  const go = $("vbu-go");
  if (!go || go.dataset.wired) return;
  go.dataset.wired = "1";
  go.onclick = searchVbu;
  const q = $("vbu-q");
  if (q) q.addEventListener("keydown", e => {
    if (e.key === "Enter") searchVbu();
  });
}

async function searchVbu() {
  const q = $("vbu-q"), box = $("vbu-result"), st = $("vbu-status");
  if (!q || !box) return;
  const name = (q.value || "").trim();
  if (!name) {
    if (st) st.textContent = "Type a @username first.";
    return;
  }
  vbuUser = null;
  box.innerHTML = "";
  if (st) st.textContent = "Searching\u2026";
  let u;
  try {
    u = await api("/admin/users/by-username/" +
                  encodeURIComponent(name.replace(/^@/, "")));
  } catch (e) {
    if (st) st.textContent = "";
    box.innerHTML = '<p class="hint">No member with that username — '
      + "check the spelling and try again.</p>";
    return;
  }
  vbuUser = u;
  if (st) st.textContent = "";
  const row = document.createElement("div");
  row.className = "card admin-row";
  row.appendChild(avatarEl(u.first_name, u.telegram_id,
                           false, u.photo_file_id));
  const info = document.createElement("div");
  info.className = "admin-info";
  const t = document.createElement("div");
  t.className = "admin-title";
  t.textContent = u.first_name + (u.is_verified ? " \u2713" : "");
  const s = document.createElement("div");
  s.className = "admin-sub";
  s.textContent = (u.username ? "@" + u.username + " \u00b7 " : "") +
    u.followers + " followers \u00b7 " + u.posts + " posts \u00b7 " +
    (u.is_verified ? "Blue tick ON" : "No blue tick");
  info.append(t, s);
  row.appendChild(info);
  const btn = document.createElement("button");
  if (u.is_verified) {
    btn.className = "danger-btn";
    btn.textContent = "Remove blue tick";
    btn.onclick = () => applyVbu("revoke");
  } else {
    btn.textContent = "\u2705 Give blue tick";
    btn.onclick = () => applyVbu("grant");
  }
  row.appendChild(btn);
  box.appendChild(row);
}

async function applyVbu(action) {
  const st = $("vbu-status");
  if (!vbuUser) return;
  if (!confirm(action === "grant"
      ? "Give the blue tick to @" + vbuUser.username + "?"
      : "Remove the blue tick from @" + vbuUser.username + "?")) return;
  try {
    const r = await api("/admin/verify-by-username", { method: "POST",
      body: JSON.stringify({ username: vbuUser.username,
                             action }) });
    if (st) st.textContent = r.changed
      ? (r.is_verified ? "Blue tick granted \u2713."
                       : "Blue tick removed.")
      : "Already " + (r.is_verified ? "verified." : "not verified.");
    searchVbu();
  } catch (e) { if (st) st.textContent = "Could not change verification."; }
}

function renderAdminPostRows(box, posts) {
  box.innerHTML = "";
  if (!posts.length) {
    box.innerHTML = '<p class="hint">No posts yet.</p>';
    return;
  }
  posts.forEach(p => {
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
        refreshAdminPosts(); loadAdminStats();
      };
      row.appendChild(btn);
    }
    box.appendChild(row);
  });
}
async function loadAdminPosts() {
  const box = $("admin-posts");
  if (!box) return;
  try {
    const r = await api("/admin/posts?limit=30");
    renderAdminPostRows(box, r.posts || []);
  } catch (e) { box.textContent = "Could not load posts."; }
}
function refreshAdminPosts() {
  const q = $("admin-content-q");
  if (q && q.value.trim()) searchAdminContent();
  else loadAdminPosts();
}
async function searchAdminContent() {
  const box = $("admin-posts");
  const qEl = $("admin-content-q"), st = $("admin-content-status");
  if (!box || !qEl) return;
  const q = qEl.value.trim();
  if (!q) { if (st) st.textContent = "Type something to search."; return; }
  box.innerHTML = "";
  try {
    const r = await api("/admin/content/search?q=" +
      encodeURIComponent(q) + "&limit=30");
    renderAdminPostRows(box, r.posts || []);
    if (st) st.textContent = (r.total || 0) + " match" +
      ((r.total || 0) === 1 ? "" : "es") + " for \u201c" + q + "\u201d.";
  } catch (e) { box.textContent = "Could not search content."; }
}

// --------------------------------------- Phase 142: banned words -----------
// Admin-managed word list. Posts and comments carrying a banned
// word are refused server-side (case-insensitive substring);
// DMs are private and are not checked.
async function loadBannedWords() {
  const box = $("admin-banned-words");
  if (!box) return;
  box.innerHTML = "";
  try {
    const r = await api("/admin/banned-words");
    if (!r.words.length) {
      box.innerHTML = '<p class="hint">No banned words yet.</p>';
      return;
    }
    r.words.forEach(w => {
      const row = document.createElement("div");
      row.className = "audit-row";
      const t = document.createElement("div");
      t.className = "admin-title";
      t.textContent = w.word;
      const s = document.createElement("div");
      s.className = "admin-sub";
      s.textContent = "banned " + relTime(w.created_at);
      row.append(t, s);
      const btn = document.createElement("button");
      btn.className = "danger-btn"; btn.textContent = "Remove";
      btn.onclick = async () => {
        if (!confirm("Unban the word \u201c" + w.word + "\u201d?")) return;
        await api("/admin/banned-words/" + w.id, { method: "DELETE" });
        loadBannedWords();
      };
      row.appendChild(btn);
      box.appendChild(row);
    });
  } catch (e) { box.textContent = "Could not load banned words."; }
}
async function addBannedWord() {
  const el = $("bw-word"), st = $("bw-status");
  if (!el) return;
  const word = el.value.trim();
  if (!word) { if (st) st.textContent = "Type a word first."; return; }
  try {
    await api("/admin/banned-words", { method: "POST",
      body: JSON.stringify({ word }) });
    el.value = "";
    if (st) st.textContent = "\u201c" + word.toLowerCase() + "\u201d is now banned.";
    loadBannedWords();
  } catch (e) {
    if (st) st.textContent = "Could not ban that word (already banned?).";
  }
}

$("admin-user-go").onclick = () => refreshAdminMembers();
$("admin-user-q").addEventListener("keydown", e => {
  if (e.key === "Enter") refreshAdminMembers();
});
$("admin-user-q").addEventListener("input", e => {
  if (!e.target.value.trim()) refreshAdminMembers();
});
$("admin-browse-sort").onchange = e => {
  adminBrowse.sort = e.target.value;
  loadAdminBrowse(true);
};
document.querySelectorAll("#admin-browse-chips .ph-chip").forEach(ch => {
  ch.onclick = () => {
    document.querySelectorAll("#admin-browse-chips .ph-chip")
      .forEach(c => c.classList.remove("active"));
    ch.classList.add("active");
    adminBrowse.filter = ch.dataset.filter;
    loadAdminBrowse(true);
  };
});
$("admin-browse-more").onclick = () => loadAdminBrowse(false);
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
  const target = ($("admin-bc-target") || {}).value || "all";
  const label = BC_TARGET_LABELS[target] || "Everyone";
  if (!confirm("Send this announcement to " + label +
               " via the bot?")) return;
  $("admin-bc-send").disabled = true;
  try {
    const r = await api("/admin/broadcast",
      { method: "POST", body: JSON.stringify({ text, target }) });
    $("admin-bc-result").textContent =
      "Delivered " + r.sent + " of " + r.recipients + " members.";
    $("admin-bc-text").value = "";
    loadBroadcasts();
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
  nm.className = "conv-name vname";
  const nmText = document.createElement("span");
  nmText.className = "vname-text";
  nmText.textContent = u.first_name;
  nm.appendChild(nmText);
  if (u.verified) nm.appendChild(verifiedBadge());
  const pv = document.createElement("div");
  pv.className = "admin-sub conv-prev";
  pv.textContent = subText || "";
  info.append(nm, pv);
  row.appendChild(info);
  row.style.cursor = "pointer";
  row.onclick = onClick;
  fitVerifiedNamesSoon(row);
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
        (cv.last.mine ? "You: " : "") +
          (cv.last.text ||
            (cv.last.media_type === "voice" ? "🎤 Voice message"
              : cv.last.media_file_id ? "📷 Photo" : "")),
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
// Phase 183 (audit L12): the oldest id on the loaded thread
// page, or null when the whole history is loaded.
let threadCursor = null;
let voicePlaying = null; // Phase 173: the audio now playing
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
    if (chatWith === uid && !voicePlaying) loadThread(false);
  }, 8000);
}
// Phase 183 (audit L12): one chat bubble, shared by the
// thread load and the older-pages load below.
function buildChatBubble(m) {
      const b = document.createElement("div");
      b.className = "bubble " + (m.mine ? "mine" : "theirs");
      if (m.media_file_id && m.media_type === "voice") {
        b.appendChild(voiceBubble(m));
      } else if (m.media_file_id) {
        const img = document.createElement("img");
        img.className = "bubble-photo";
        img.src = mediaUrl(m.media_file_id);
        img.alt = "Photo";
        img.onclick = e => { e.stopPropagation();
          openPhotoViewer(m.media_file_id, "Photo"); };
        b.appendChild(img);
      }
      // Phase 139: a story reply carries its story preview —
      // tap it to open the story while it is still live.
      if (m.story) {
        const chip = document.createElement("div");
        chip.className = "story-reply-chip";
        if (m.story.live && m.story.media_file_id) {
          const th = document.createElement("img");
          th.className = "story-reply-thumb";
          th.src = mediaUrl(m.story.media_file_id);
          th.alt = "Story";
          chip.appendChild(th);
        }
        const lb = document.createElement("span");
        lb.textContent = m.story.live
          ? "Replied to " + (m.mine ? (m.story.author || "their") +
                             "’s story" : "your story")
          : "Replied to a story (expired)";
        chip.appendChild(lb);
        chip.onclick = e => {
          e.stopPropagation();
          if (m.story.live) openStoryById(m.story.id);
          else setStatus("That story has expired.");
        };
        b.appendChild(chip);
      }
      if (m.text) b.appendChild(document.createTextNode(m.text));
      // Phase 138: reactions under the bubble (tappable chips) +
      // a tap-to-open emoji picker. The 8 s poll rebuilds the
      // thread, so an open picker closes on the next refresh.
      const counts = m.reactions || {};
      if (Object.keys(counts).length) {
        const rx = document.createElement("div");
        rx.className = "bubble-reactions";
        Object.keys(counts).forEach(em => {
          if (!counts[em]) return;
          const chip = document.createElement("button");
          chip.className = "react-chip" +
            (m.my_reaction === em ? " mine" : "");
          chip.textContent = em + " " + counts[em];
          chip.onclick = e => { e.stopPropagation();
            reactToMessage(m.id, em); };
          rx.appendChild(chip);
        });
        b.appendChild(rx);
      }
      const pk = document.createElement("div");
      pk.className = "react-picker";
      pk.hidden = true;
      DM_REACTIONS.forEach(em => {
        const eb = document.createElement("button");
        eb.textContent = em;
        eb.onclick = e => { e.stopPropagation();
          reactToMessage(m.id, em); };
        pk.appendChild(eb);
      });
      b.appendChild(pk);
      b.onclick = () => { pk.hidden = !pk.hidden; };
      const t = document.createElement("div");
      t.className = "bubble-time";
      t.textContent = relTime(m.created_at) +
        (m.mine && m.read ? " · seen" : "");
      b.appendChild(t);
      return b;
}


async function loadThread(scroll) {
  if (!chatWith) return;
  try {
    const r = await api("/messages/" + chatWith);
    // Phase 183 (audit L12): the thread is cursor-paged —
    // next_cursor is the oldest id on this page, or null
    // when this is the whole history.
    threadCursor = r.next_cursor || null;
    const ct = $("chat-title");
    ct.classList.add("vname");
    ct.innerHTML = "";
    const ctText = document.createElement("span");
    ctText.className = "vname-text";
    ctText.textContent = r.user.first_name;
    ct.appendChild(ctText);
    if (r.user.verified) ct.appendChild(verifiedBadge());
    fitVerifiedNames(ct);
    const av = $("chat-avatar");
    av.innerHTML = "";
    av.appendChild(avatarEl(r.user.first_name, r.user.telegram_id,
                            false, r.user.photo_file_id));
    const box = $("chat-thread");
    box.innerHTML = "";
    if (threadCursor) {
      const older = document.createElement("button");
      older.className = "btn";
      older.id = "chat-load-older";
      older.textContent = "↑ Load older messages";
      older.onclick = () => loadOlderThread();
      box.appendChild(older);
    }
    $("chat-empty").hidden = r.messages.length > 0;
    r.messages.forEach(m => box.appendChild(buildChatBubble(m)));
    refreshMsgBadge();
    if (scroll) {
      const sc = $("app-scroll");
      if (sc) sc.scrollTop = sc.scrollHeight;
    }
  } catch (e) { setStatus("Could not load the chat."); }
}
// Phase 183 (audit L12): load the next older page (before_id
// = the oldest id on screen) and prepend it, keeping the
// scroll position so the view does not jump.
async function loadOlderThread() {
  if (!chatWith || !threadCursor) return;
  const btn = $("chat-load-older");
  if (btn) btn.disabled = true;
  try {
    const r = await api("/messages/" + chatWith +
      "?before_id=" + threadCursor);
    threadCursor = r.next_cursor || null;
    const box = $("chat-thread");
    const sc = $("app-scroll");
    const oldH = sc ? sc.scrollHeight : 0;
    const frag = document.createDocumentFragment();
    (r.messages || []).forEach(m => frag.appendChild(buildChatBubble(m)));
    if (btn) {
      if (threadCursor) {
        btn.disabled = false;
        box.insertBefore(frag, btn.nextSibling);
      } else {
        btn.remove();
        box.insertBefore(frag, box.firstChild);
      }
    } else {
      box.insertBefore(frag, box.firstChild);
    }
    if (sc) sc.scrollTop += sc.scrollHeight - oldH;
  } catch (e) {
    if (btn) btn.disabled = false;
    setStatus("Could not load older messages.");
  }
}


let chatSending = false;
async function sendChat() {
  const inp = $("chat-input");
  const text = inp.value.trim();
  // Phase 183 (audit L10): a send already in flight ignores
  // a second tap/Enter, and every attempt carries its own
  // X-Upload-Id — a retry of the same attempt replays the
  // first message instead of double-posting.
  if (!text || !chatWith || chatSending) return;
  chatSending = true;
  inp.value = "";
  try {
    await api("/messages/" + chatWith,
      { method: "POST",
        headers: { "X-Upload-Id": newUploadId() },
        body: JSON.stringify({ text }) });
    loadThread(true);
  } catch (e) {
    inp.value = text;
    setStatus("Message could not be sent.");
  } finally {
    chatSending = false;
  }
}
$("chat-send").onclick = sendChat;
$("chat-input").addEventListener("keydown", e => {
  if (e.key === "Enter") sendChat();
});
// Phase 138: DM photos + message reactions.
const DM_REACTIONS = ["❤️", "👍", "😂", "😮", "😢", "🔥"];
async function reactToMessage(mid, emoji) {
  try {
    await api("/dm/messages/" + mid + "/react",
      { method: "POST", body: JSON.stringify({ emoji }) });
    loadThread(false);
  } catch (e) { setStatus("Reaction failed."); }
}
$("chat-photo").onclick = () => $("chat-file").click();
$("chat-file").addEventListener("change", async () => {
  const f = $("chat-file").files[0];
  $("chat-file").value = "";
  if (!f || !chatWith) return;
  const caption = $("chat-input").value.trim();
  setStatus("Sending photo…");
  try {
    const form = new FormData();
    form.append("file", await shrinkForUpload(f));
    if (caption) form.append("text", caption);
    await apiFormProgress("/messages/" + chatWith + "/upload", form,
      pct => { setStatus(pct === null ? "Sending photo… finishing"
        : "Sending photo… " + pct + "%"); }, newUploadId());
    $("chat-input").value = "";
    setStatus("");
    loadThread(true);
  } catch (e) {
    setStatus(e && e.message ? e.message
      : "Photo could not be sent — check your connection and try again.");
  }
});
// Phase 173: DM voice notes — MediaRecorder, tap to start/stop.
// The 8 s poll skips a rebuild while a voice note is playing, so
// playback is never cut off by a refresh.
function fmtDur(sec) {
  sec = Math.max(0, Math.round(sec || 0));
  return Math.floor(sec / 60) + ":" +
    String(sec % 60).padStart(2, "0");
}
function voiceBubble(m) {
  const wrap = document.createElement("div");
  wrap.className = "bubble-voice";
  const btn = document.createElement("button");
  btn.className = "voice-play";
  btn.type = "button";
  btn.textContent = "▶";
  btn.title = "Play voice message";
  const audio = document.createElement("audio");
  audio.src = mediaUrl(m.media_file_id);
  audio.preload = "metadata";
  const track = document.createElement("div");
  track.className = "voice-track";
  const fill = document.createElement("div");
  fill.className = "voice-fill";
  track.appendChild(fill);
  const dur = document.createElement("span");
  dur.className = "voice-dur";
  dur.textContent = fmtDur(m.media_duration);
  btn.onclick = e => {
    e.stopPropagation();
    if (audio.paused) {
      document.querySelectorAll("#chat-thread audio").forEach(a => {
        if (a !== audio) a.pause();
      });
      audio.play().catch(() =>
        setStatus("Could not play this voice message."));
    } else audio.pause();
  };
  audio.addEventListener("play", () => {
    btn.textContent = "⏸"; voicePlaying = audio;
  });
  audio.addEventListener("pause", () => {
    btn.textContent = "▶";
    if (voicePlaying === audio) voicePlaying = null;
  });
  audio.addEventListener("ended", () => {
    btn.textContent = "▶"; voicePlaying = null;
  });
  audio.addEventListener("timeupdate", () => {
    if (audio.duration)
      fill.style.width =
        (audio.currentTime / audio.duration * 100) + "%";
  });
  audio.addEventListener("loadedmetadata", () => {
    if (audio.duration && !m.media_duration)
      dur.textContent = fmtDur(audio.duration);
  });
  wrap.append(btn, track, dur);
  return wrap;
}
let voiceRec = null;
let voiceRecTimer = null;
function setVoiceRecUI(on, secs) {
  const btn = $("chat-mic");
  if (!btn) return;
  btn.classList.toggle("recording", !!on);
  btn.textContent = on ? "⏺" : "🎤";
  if (on) setStatus("● Recording " + fmtDur(secs) +
    " — tap 🎤 again to stop (max 2:00).");
}
async function toggleVoiceRec() {
  if (voiceRec) { stopVoiceRec(); return; }
  if (!chatWith) return;
  if (!navigator.mediaDevices || !window.MediaRecorder) {
    setStatus("Voice recording isn't available on this device — " +
      "type your message instead.");
    return;
  }
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (e) {
    setStatus("Microphone access was denied — allow it to record " +
      "voice messages.");
    return;
  }
  const mime = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4",
    "audio/ogg"].find(t => {
      try { return MediaRecorder.isTypeSupported(t); }
      catch (e) { return false; }
    }) || "";
  let rec;
  try {
    rec = mime ? new MediaRecorder(stream, { mimeType: mime })
      : new MediaRecorder(stream);
  } catch (e) {
    stream.getTracks().forEach(t => t.stop());
    setStatus("Voice recording isn't available on this device — " +
      "type your message instead.");
    return;
  }
  const chunks = [];
  const startedAt = Date.now();
  rec.ondataavailable = e => {
    if (e.data && e.data.size) chunks.push(e.data);
  };
  rec.onstop = () => {
    stream.getTracks().forEach(t => t.stop());
    clearInterval(voiceRecTimer);
    voiceRec = null;
    setVoiceRecUI(false, 0);
    setStatus("");
    const secs = Math.round((Date.now() - startedAt) / 1000);
    if (!chunks.length || secs < 1) {
      setStatus("That recording was too short.");
      return;
    }
    sendVoiceNote(chunks, rec.mimeType || mime, Math.min(secs, 120));
  };
  rec.start(250);
  voiceRec = { rec, chunks, startedAt };
  setVoiceRecUI(true, 0);
  voiceRecTimer = setInterval(() => {
    const secs = Math.floor((Date.now() - startedAt) / 1000);
    setVoiceRecUI(true, secs);
    if (secs >= 120) stopVoiceRec();
  }, 1000);
}
function stopVoiceRec() {
  if (voiceRec && voiceRec.rec.state !== "inactive")
    voiceRec.rec.stop();
}
async function sendVoiceNote(chunks, mime, secs) {
  if (!chatWith) return;
  setStatus("Sending voice message…");
  const ext = mime.includes("ogg") ? "ogg"
    : mime.includes("mp4") ? "m4a" : "webm";
  const file = new Blob(chunks, { type: mime || "audio/webm" });
  try {
    const form = new FormData();
    form.append("file", file, "voice." + ext);
    form.append("duration", String(secs));
    await apiFormProgress("/messages/" + chatWith + "/upload-voice", form,
      pct => { setStatus(pct === null ? "Sending voice message… finishing"
        : "Sending voice message… " + pct + "%"); }, newUploadId());
    setStatus("");
    loadThread(true);
  } catch (e) {
    setStatus(e && e.message ? e.message
      : "Voice message could not be sent — check your connection " +
        "and try again.");
  }
}
$("chat-mic").onclick = toggleVoiceRec;

$("chat-back").onclick = () => showView("messages");

// ----------------------------------------------------------------- stories --
let storyGroups = [];
let storyPos = null;
let storyTimer = null;
let ownStoryGroup = null;
let hlMode = false;  // Phase 172: replaying a highlight

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
  const sa = $("story-author");
  sa.classList.add("vname");
  sa.innerHTML = "";
  const saText = document.createElement("span");
  saText.className = "vname-text";
  saText.textContent = g.author.first_name;
  sa.appendChild(saText);
  if (g.author.verified) sa.appendChild(verifiedBadge());
  fitVerifiedNames(sa);
  $("story-time").textContent = relTime(s.created_at);
  // Phase 139: the owner sees the viewer count (tap to list
  // viewers); everyone else gets a reply box instead.
  const viewsEl = $("story-views");
  const vc = (s.viewer_count === null || s.viewer_count === undefined)
    ? s.views : s.viewer_count;
  viewsEl.textContent = s.mine ? "👁 " + vc + " viewers" : "";
  viewsEl.style.cursor = s.mine ? "pointer" : "";
  viewsEl.onclick = s.mine ? () => openStoryViewers(s.id) : null;
  const replyRow = $("story-reply");
  replyRow.hidden = hlMode || !!s.mine;
  if (!s.mine) {
    const inp = $("story-reply-input");
    if (document.activeElement !== inp) inp.value = "";
  }
  $("story-del").hidden = hlMode || (!s.mine && !(me && me.is_admin));
  const fill = $("story-progress-fill");
  fill.style.transition = "none";
  fill.style.width = "0%";
  requestAnimationFrame(() => {
    fill.style.transition = "width 6s linear";
    fill.style.width = "100%";
  });
  if (!hlMode && !s.mine && !s.viewed) {
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
  hlMode = false;
  storyPos = null;
  $("story-wrap").hidden = true;
  loadStories();
}
// Phase 139: open a story from a DM reply's preview chip.
async function openStoryById(sid) {
  try {
    const r = await api("/stories");
    storyGroups = r.groups;
    for (let gi = 0; gi < storyGroups.length; gi++) {
      const si = storyGroups[gi].stories.findIndex(s => s.id === sid);
      if (si >= 0) { openStory(gi, si); return; }
    }
    setStatus("That story has expired.");
  } catch (e) { setStatus("Could not open the story."); }
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

// Phase 139: who viewed a story — the owner only. The list
// opens as a panel inside the story viewer (the reel sheet
// sits below it, z-index 70 vs 90, so it cannot be reused).
async function openStoryViewers(sid) {
  const panel = $("story-viewers");
  const list = $("story-viewers-list");
  list.innerHTML = "";
  const load = document.createElement("div");
  load.className = "hint";
  load.textContent = "Loading viewers…";
  list.appendChild(load);
  panel.hidden = false;
  stopStoryTimer();
  try {
    const r = await api("/stories/" + sid + "/viewers");
    load.remove();
    if (!r.viewers.length) {
      const none = document.createElement("div");
      none.className = "hint";
      none.textContent = "No one has viewed this story yet.";
      list.appendChild(none);
    }
    r.viewers.forEach(v => {
      const row = document.createElement("div");
      row.className = "story-viewer-row";
      row.appendChild(avatarEl(v.user.first_name, v.user.telegram_id,
                               false, v.user.photo_file_id));
      const tx = document.createElement("div");
      const nm = document.createElement("div");
      nm.className = "story-viewer-name vname";
      const nmText = document.createElement("span");
      nmText.className = "vname-text";
      nmText.textContent = v.user.first_name;
      nm.appendChild(nmText);
      if (v.user.verified) nm.appendChild(verifiedBadge());
      if (v.user.username) nm.appendChild(document.createTextNode(
        " @" + v.user.username));
      const tm = document.createElement("div");
      tm.className = "story-viewer-time";
      tm.textContent = relTime(v.viewed_at);
      tx.append(nm, tm);
      row.appendChild(tx);
      list.appendChild(row);
    });
    fitVerifiedNames(list);
  } catch (e) { load.textContent = "Could not load viewers."; }
}
function closeStoryViewers() {
  $("story-viewers").hidden = true;
  if (storyPos) {
    stopStoryTimer();
    storyTimer = setTimeout(nextStory, 6000);
  }
}
// Phase 139: a text reply to a story lands as a DM to the
// story owner. The 6 s auto-advance pauses while typing.
async function sendStoryReply() {
  if (!storyPos) return;
  const g = storyGroups[storyPos.g];
  const s = g && g.stories[storyPos.s];
  const inp = $("story-reply-input");
  const text = inp.value.trim();
  if (!s || !text) return;
  inp.value = "";
  try {
    await api("/stories/" + s.id + "/reply",
      { method: "POST", body: JSON.stringify({ text }) });
    setStatus("Reply sent ✉️");
  } catch (e) { setStatus("Reply could not be sent."); }
  if (storyPos) {
    stopStoryTimer();
    storyTimer = setTimeout(nextStory, 6000);
  }
}
$("story-reply-send").onclick = sendStoryReply;
$("story-reply-input").addEventListener("keydown", e => {
  if (e.key === "Enter") sendStoryReply();
});
$("story-reply-input").addEventListener("focus", stopStoryTimer);
$("story-reply-input").addEventListener("blur", () => {
  if (storyPos) {
    stopStoryTimer();
    storyTimer = setTimeout(nextStory, 6000);
  }
});
$("story-viewers-close").onclick = closeStoryViewers;

// ---------- Phase 69: Nexa, the AI assistant ----------
// She lives behind the sidebar: her chat opens only from her
// sidebar card. Replies are TEXT ONLY (Phase 183: the voice
// routes are gone) while her picture switches to the talking
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
    // Phase 183 (audit M17): 30 s client budget (the server
    // caps the whole Gemini chain at 25 s) — a slow Gemini
    // fails fast into an honest "slow" state instead of
    // hanging on "thinking…" for a minute or more.
    const r = await api("/assistant/chat", {
      method: "POST",
      timeoutMs: 30000,
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
    // Phase 183 (audit M17): an aborted fetch is Nexa being
    // slow, not a dead chat — say so honestly instead of
    // the generic line.
    const slow = e && e.name === "AbortError";
    if (st) st.textContent = slow
      ? "Nexa is slow right now — please try again in a moment."
      : "Your AI friend — ask me anything!";
    nexaBubble(slow
      ? "Nexa is slow right now — please try again in a moment."
      : "Hmm, I can't think right now. Please try again "
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


// ---------- Phase 156: real 3D mascot + context-aware tips ----------
// Owner order Nov 20: the mascot is REAL 3D now, not an image, and its
// tips follow the page you are on. The head is built from Three.js
// primitives (vendored r149, no CDN): sky-blue fur, cream pom-pom,
// black button eyes, stitched smile, curved antenna — the owner's
// pick #11, recoloured to Organic Clay sky. Button is 40 px now
// (was 48). If WebGL is unavailable a small CSS face takes its place
// (plain divs — never an image). The bubble NEVER opens on its own —
// only on tap. Every number in every tip is true about a live feature
// (cross-checked in test_phase156 against config / routes / games).
const MASCOT_TIPS_GENERAL = [
  "Check in every day on the Tasks page — each check-in earns you 20 points.",
  "Keep your check-in streak going — 30 days in a row is one of the keys to unlock monetisation.",
  "You can become a blood donor from Settings → Profile — pick your group and turn the donor switch on.",
  "To post a photo, send it to @NexoraSocial_bot in chat with a caption — it appears in your feed.",
  "Nearby shows members within 500 m of you — turn sharing on to appear on the map.",
  "Tap the ⭐ on any post to tip its author with Stars — tips start at 10 Stars.",
  "You can schedule a post from the composer — pick a time and it goes live by itself.",
];
const MASCOT_TIPS_BY_VIEW = {
  feed: [
    "To post a photo or video, send it to @NexoraSocial_bot in chat with a caption — it appears in your feed.",
    "You can schedule a post from the composer — any time from 5 minutes to 90 days ahead.",
    "Tap the ⭐ on any post to tip its author with Stars — tips start at 10 Stars.",
    "Stories disappear after 24 hours — tap a circle at the top to watch one.",
  ],
  videos: [
    "Reels play full-screen — swipe up for the next one.",
    "The rail on the right is for liking and commenting — tap ❤️ or 💬.",
    "From the ⋮ menu you can share a reel with someone you follow, or via Telegram.",
  ],
  designs: [
    "Designs are official Nexora posts — tap one to see it big.",
    "The gallery keeps loading more as you scroll down.",
    "Related designs appear under each design you open.",
  ],
  search: [
    "Search finds members by name or username.",
    "Start your search with # to find posts by hashtag.",
  ],
  tasks: [
    "Check in every day — each check-in earns you 20 points.",
    "Follow 3 people (10 points), write 5 comments (5 points), react to 6 posts (10 points) — each task pays once a day.",
    "A 30-day unbroken check-in streak is one of the keys to unlock monetisation.",
  ],
  leaderboard: [
    "Ranks shows the top 50 members, plus your own rank.",
    "Your level comes from lifetime points — 5,000 points makes you a Star.",
    "The blue tick needs 1,000 followers or 50 qualified referrals.",
  ],
  profile: [
    "Your level and badges live in Settings — open “My level”.",
    "Change your look in Settings → Theme — 33 shades to pick from.",
    "Your QR code is in Settings → My QR — others can scan it to find you.",
  ],
  saved: [
    "Posts you saved live here — tap the bookmark on any post to save it.",
    "Tap a saved post to open it again.",
  ],
  shared: [
    "Posts and designs other members shared with you live here.",
    "Share a post from its ⋮ menu to send it to someone you follow.",
  ],
  games: [
    "13 games are built in — Snake, Tetris, 2048, Pac-Man, Runner Rush and more.",
    "Tap a game card to play it right inside the app.",
  ],
  game: [
    "You are playing inside the app — no download needed.",
    "Use the back button to return to the games list.",
  ],
  admin: [
    "Admin Panel: backups, broadcast, payout requests and the audit log.",
    "If no backup was made in the last 7 days, an amber reminder shows here.",
  ],
  notifications: [
    "Likes, comments, follows, tips and blood requests all land here.",
    "Turn any kind off in Settings → Notification prefs — 10 switches.",
  ],
  messages: [
    "Tap the photo button in a chat to send a photo DM.",
    "Tap a message to open the emoji picker — 6 reactions to pick from.",
    "Photo DMs show as “📷 Photo” in this list.",
  ],
  chat: [
    "Tap the photo button to send a photo in this chat.",
    "Tap a message to open the emoji picker — 6 reactions to pick from.",
    "Tap a photo message to see it full-screen.",
  ],
  nearby: [
    "Nearby shows members within 500 m of you.",
    "Turn sharing on to appear on the map — you can turn it off anytime.",
    "Tap a pin, then Street View, to see the street photo of that spot.",
    "Use the 3D / 2D switch above the map — 3D needs WebGL.",
  ],
  qr: [
    "This is your profile QR — let someone scan it to find you.",
    "Your QR is also in Settings, next to your profile.",
  ],
  trending: [
    "Trending ranks the 20 hottest posts from the last 7 days.",
    "Only posts with likes, comments or views in the last 7 days can trend.",
  ],
  settings: [
    "Theme: pick one of 33 shades — the whole app follows it.",
    "Notification prefs has 10 switches — likes, comments, follows, tips, messages, system, follow requests, blood, skills and mentions.",
    "Payout wallet: save a TON, Gram or USDT address, then request a payout in points.",
  ],
  blood: [
    "Become a donor in Settings → Profile — pick your group and switch the donor toggle on.",
    "Tap “আমি দেবো” on a request — the requester gets notified and a DM opens.",
    "Requests ask for 1 to 10 units — filter donors by any of the 8 blood groups.",
  ],
  skills: [
    "List what you can teach and what you want to learn — no money, just time.",
    "Tap 🤝 Connect on a card — the member is notified and a DM opens to arrange the swap.",
    "Use the search box to find someone who teaches the skill you want.",
  ],
  museum: [
    "Drag on the museum canvas to look around — the room buttons walk you from room to room.",
    "Tap a frame to see the photo big. The owner hangs photos from their own posts and designs.",
    "In your own museum, tap an empty frame to hang a photo, or an empty floor spot to place furniture.",
  ],
};
let mascotTipIdx = 0;
let mascotLastView = "";
function mascotTipsFor(view) {
  return MASCOT_TIPS_BY_VIEW[view] || MASCOT_TIPS_GENERAL;
}
function mascotOnView(name) {
  if (name !== mascotLastView) {
    mascotLastView = name;
    mascotTipIdx = 0;
  }
  mascotHideTip();
}
function mascotShowTip() {
  const b = $("mascot-bubble"); if (!b) return;
  const tips = mascotTipsFor(currentView);
  $("mascot-tip").textContent =
    tips[mascotTipIdx % tips.length];
  mascotTipIdx++;
  b.hidden = false;
}
function mascotHideTip() {
  const b = $("mascot-bubble"); if (b) b.hidden = true;
}
$("mascot-btn").onclick = (e) => { e.stopPropagation(); mascotShowTip(); };
$("mascot-close").onclick = (e) => { e.stopPropagation(); mascotHideTip(); };
document.addEventListener("click", (e) => {
  const w = $("mascot-wrap");
  if (w && !w.contains(e.target)) mascotHideTip();
});

// ---- The 3D head (Three.js r149, vendored, no CDN) ----
function mascotInit3D() {
  const canvas = $("mascot-canvas");
  const fallback = $("mascot-fallback");
  if (!canvas) return;
  function showFallback() {
    canvas.hidden = true;
    if (fallback) fallback.hidden = false;
  }
  try {
    if (typeof THREE === "undefined" || !window.WebGLRenderingContext)
      return showFallback();
    const renderer = new THREE.WebGLRenderer({
      canvas: canvas, alpha: true, antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setSize(80, 80, false);
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 20);
    camera.position.set(0, 0.25, 4.2);
    camera.lookAt(0, 0.25, 0);
    scene.add(new THREE.AmbientLight(0xffffff, 1.0));
    const key = new THREE.DirectionalLight(0xffffff, 0.9);
    key.position.set(2, 3, 4);
    scene.add(key);
    const SKY = 0x8ED4F7, CREAM = 0xF6F1E7, INK = 0x3A2E33;
    const fur = new THREE.MeshStandardMaterial({
      color: SKY, roughness: 0.9, metalness: 0 });
    const head = new THREE.Group();
    const skull = new THREE.Mesh(
      new THREE.SphereGeometry(1, 28, 20), fur);
    skull.scale.y = 0.92;
    head.add(skull);
    // Fluffy tufts: small fur spheres dotted over the top and sides.
    const TUFTS = [
      [0.35, 0.4], [0.7, 1.2], [0.5, 2.2], [0.9, 2.9],
      [1.1, 0.2], [1.3, 1.6], [1.2, 3.0], [0.6, 1.8],
      [1.6, 0.3], [1.4, 2.5]
    ];
    TUFTS.forEach(tp => {
      const th = tp[0], ph = tp[1], r = 0.98;
      const tuft = new THREE.Mesh(
        new THREE.SphereGeometry(0.17, 12, 10), fur);
      tuft.position.set(
        r * Math.sin(th) * Math.cos(ph),
        r * Math.cos(th) * 0.92,
        r * Math.sin(th) * Math.sin(ph));
      head.add(tuft);
    });
    // Curved antenna + cream pom-pom on top.
    const antCurve = new THREE.CatmullRomCurve3([
      new THREE.Vector3(0, 0.82, 0.05),
      new THREE.Vector3(0.12, 1.18, 0.05),
      new THREE.Vector3(0.42, 1.36, 0.05)
    ]);
    head.add(new THREE.Mesh(
      new THREE.TubeGeometry(antCurve, 12, 0.045, 8), fur));
    const pom = new THREE.Mesh(
      new THREE.SphereGeometry(0.17, 16, 12),
      new THREE.MeshStandardMaterial({
        color: CREAM, roughness: 0.9, metalness: 0 }));
    pom.position.set(0.42, 1.36, 0.05);
    head.add(pom);
    // Big black button eyes (+ tiny glints) and the stitched smile.
    const eyeMat = new THREE.MeshStandardMaterial({
      color: 0x1a1a1a, roughness: 0.35, metalness: 0 });
    [-0.36, 0.36].forEach(x => {
      const eye = new THREE.Mesh(
        new THREE.SphereGeometry(0.13, 16, 12), eyeMat);
      eye.position.set(x, 0.15, 0.95);
      eye.scale.z = 0.6;
      head.add(eye);
      const glint = new THREE.Mesh(
        new THREE.SphereGeometry(0.045, 8, 8),
        new THREE.MeshBasicMaterial({ color: 0xffffff }));
      glint.position.set(x - 0.04, 0.21, 1.0);
      head.add(glint);
    });
    const smile = new THREE.Mesh(
      new THREE.TorusGeometry(0.2, 0.032, 8, 20, Math.PI),
      new THREE.MeshStandardMaterial({
        color: INK, roughness: 0.6, metalness: 0 }));
    smile.position.set(0, -0.3, 0.96);
    smile.rotation.set(-0.15, 0, Math.PI);
    head.add(smile);
    head.scale.set(0.9, 0.9, 0.9);
    head.position.y = -0.05;
    scene.add(head);
    // Gentle idle sway + bob; the loop skips rendering while hidden,
    // and requestAnimationFrame already pauses in background tabs.
    function mascotTick(t) {
      requestAnimationFrame(mascotTick);
      if (document.hidden) return;
      const s = t * 0.001;
      head.rotation.y = Math.sin(s * 0.7) * 0.16;
      head.rotation.x = Math.sin(s * 0.5) * 0.05;
      head.position.y = -0.05 + Math.sin(s * 1.4) * 0.05;
      renderer.render(scene, camera);
    }
    requestAnimationFrame(mascotTick);
  } catch (e) { showFallback(); }
}
mascotInit3D();

// Phase 172: Story Highlights — named collections of the member's
// own stories (active + expired) shown as circles under the bio.
// A highlight replays its stories in the story viewer (hlMode:
// view-only, no view-count, no reply, no delete).
function hlCircle(h) {
  const item = document.createElement("div");
  item.className = "hl-item";
  const ring = document.createElement("div");
  ring.className = "hl-ring";
  if (h.cover_media_file_id) {
    const img = document.createElement("img");
    img.src = mediaUrl(h.cover_media_file_id);
    img.alt = h.title || "Highlight";
    img.loading = "lazy";
    ring.appendChild(img);
  } else {
    const init = document.createElement("span");
    init.className = "hl-initial";
    init.textContent = (h.title || "?").trim().charAt(0).toUpperCase();
    ring.appendChild(init);
  }
  const label = document.createElement("div");
  label.className = "hl-label";
  label.textContent = h.title || "";
  item.append(ring, label);
  item.onclick = () => openHighlight(h.id);
  return item;
}

async function loadHighlights(userId, box) {
  const row = document.createElement("div");
  row.className = "hl-row";
  row.id = "profile-highlights";
  try {
    const r = await api("/highlights/user/" + userId);
    (r.highlights || []).forEach(h => row.appendChild(hlCircle(h)));
  } catch (e) { /* no highlights — row stays empty */ }
  if (me && userId === me.telegram_id) {
    const add = document.createElement("div");
    add.className = "hl-item hl-new";
    const ring = document.createElement("div");
    ring.className = "hl-ring";
    const plus = document.createElement("span");
    plus.className = "hl-plus";
    plus.textContent = "+";
    ring.appendChild(plus);
    const label = document.createElement("div");
    label.className = "hl-label";
    label.textContent = "New";
    add.append(ring, label);
    add.onclick = () => openHighlightPicker();
    row.appendChild(add);
  }
  if (row.children.length) box.appendChild(row);
}

async function openHighlight(hid) {
  try {
    const r = await api("/highlights/" + hid);
    const stories = r.stories || [];
    if (!stories.length) { setStatus("This highlight is empty."); return; }
    hlMode = true;
    storyGroups = [{ author: r.owner || { first_name: "Highlights" },
                     stories, has_unviewed: false }];
    openStory(0, 0);
  } catch (e) { setStatus("Could not open this highlight."); }
}

let hlPickerSel = new Set();
async function openHighlightPicker() {
  closeHighlightPicker();
  hlPickerSel = new Set();
  const overlay = document.createElement("div");
  overlay.className = "hl-picker-overlay";
  overlay.id = "hl-picker";
  const sheet = document.createElement("div");
  sheet.className = "hl-sheet";
  const title = document.createElement("div");
  title.className = "sheet-title";
  title.textContent = "✨ Story Highlights";
  sheet.appendChild(title);
  const formTitle = document.createElement("div");
  formTitle.className = "hl-form-title";
  formTitle.textContent = "New highlight";
  sheet.appendChild(formTitle);
  const input = document.createElement("input");
  input.type = "text";
  input.maxLength = 50;
  input.placeholder = "Highlight title";
  input.className = "hl-title-input";
  sheet.appendChild(input);
  const grid = document.createElement("div");
  grid.className = "hl-pick-grid";
  sheet.appendChild(grid);
  const createBtn = document.createElement("button");
  createBtn.className = "wide btn";
  createBtn.textContent = "Create highlight";
  createBtn.disabled = true;
  sheet.appendChild(createBtn);
  const refreshCreate = () => {
    createBtn.disabled = !input.value.trim() || !hlPickerSel.size;
  };
  input.oninput = refreshCreate;
  try {
    const r = await api("/stories/mine");
    (r.stories || []).forEach(s => {
      const cell = document.createElement("div");
      cell.className = "hl-pick-item";
      const img = document.createElement("img");
      img.src = mediaUrl(s.media_file_id);
      img.alt = "";
      img.loading = "lazy";
      cell.appendChild(img);
      if (s.expired) {
        const tag = document.createElement("span");
        tag.className = "hl-expired-tag";
        tag.textContent = "expired";
        cell.appendChild(tag);
      }
      cell.onclick = () => {
        if (hlPickerSel.has(s.id)) {
          hlPickerSel.delete(s.id);
          cell.classList.remove("selected");
        } else {
          hlPickerSel.add(s.id);
          cell.classList.add("selected");
        }
        refreshCreate();
      };
      grid.appendChild(cell);
    });
    if (!grid.children.length) {
      const none = document.createElement("p");
      none.className = "hint";
      none.textContent = "No stories yet — post a story first.";
      grid.appendChild(none);
    }
  } catch (e) {
    const err = document.createElement("p");
    err.className = "hint";
    err.textContent = "Could not load your stories.";
    grid.appendChild(err);
  }
  createBtn.onclick = async () => {
    const t = input.value.trim();
    if (!t || !hlPickerSel.size) return;
    createBtn.disabled = true;
    try {
      await api("/highlights", { method: "POST",
        body: JSON.stringify({ title: t, story_ids: [...hlPickerSel] }) });
      closeHighlightPicker();
      setStatus("✨ Highlight created.");
      if (me) openProfile(me.telegram_id);
    } catch (e) {
      setStatus("Could not create the highlight.");
      createBtn.disabled = false;
    }
  };
  const mgTitle = document.createElement("div");
  mgTitle.className = "hl-form-title";
  mgTitle.textContent = "Your highlights";
  sheet.appendChild(mgTitle);
  const mgList = document.createElement("div");
  mgList.className = "hl-manage-list";
  sheet.appendChild(mgList);
  try {
    const r = await api("/highlights/user/" + (me ? me.telegram_id : 0));
    (r.highlights || []).forEach(h => {
      const row = document.createElement("div");
      row.className = "hl-manage-row";
      const inp = document.createElement("input");
      inp.type = "text";
      inp.maxLength = 50;
      inp.value = h.title;
      row.appendChild(inp);
      const save = document.createElement("button");
      save.className = "tool-btn";
      save.textContent = "Rename";
      save.onclick = async () => {
        const t = inp.value.trim();
        if (!t) { setStatus("A highlight needs a title."); return; }
        try {
          await api("/highlights/" + h.id + "/rename", { method: "POST",
            body: JSON.stringify({ title: t }) });
          setStatus("Highlight renamed.");
        } catch (e) { setStatus("Could not rename."); }
      };
      const del = document.createElement("button");
      del.className = "tool-btn";
      del.textContent = "Delete";
      del.onclick = async () => {
        if (!confirm("Delete this highlight? Your stories stay."))
          return;
        try {
          await api("/highlights/" + h.id, { method: "DELETE" });
          closeHighlightPicker();
          setStatus("Highlight deleted.");
          if (me) openProfile(me.telegram_id);
        } catch (e) { setStatus("Could not delete."); }
      };
      row.append(save, del);
      mgList.appendChild(row);
    });
    if (!mgList.children.length) {
      const none = document.createElement("p");
      none.className = "hint";
      none.textContent = "No highlights yet.";
      mgList.appendChild(none);
    }
  } catch (e) { /* manage list stays empty */ }
  const closeBtn = document.createElement("button");
  closeBtn.className = "wide";
  closeBtn.textContent = "✕ Close";
  closeBtn.onclick = closeHighlightPicker;
  sheet.appendChild(closeBtn);
  overlay.appendChild(sheet);
  overlay.onclick = e => {
    if (e.target === overlay) closeHighlightPicker();
  };
  document.body.appendChild(overlay);
}
function closeHighlightPicker() {
  const el = document.getElementById("hl-picker");
  if (el) el.remove();
}
