// Nexora Mini App — feed, posting, likes, comments, profiles, follow,
// search, referrals and points, all against the FastAPI backend.
// Login is the Telegram initData sent with every request (see /auth).
const tg = window.Telegram.WebApp;
tg.ready();
tg.expand();

const initData = tg.initData || "";
let me = null;
let tab = "explore";
let feedCursor = null;
let profileId = null;
let profileCursor = null;

const $ = id => document.getElementById(id);

async function api(path, options = {}) {
  const res = await fetch(path, {
    ...options,
    headers: { "X-Init-Data": initData, "Content-Type": "application/json",
               ...(options.headers || {}) },
  });
  if (!res.ok) throw new Error("API " + res.status);
  return res.json();
}

async function apiForm(path, form) {
  const res = await fetch(path, { method: "POST",
    headers: { "X-Init-Data": initData }, body: form });
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
function apiFormProgress(path, form, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", path);
    xhr.setRequestHeader("X-Init-Data", initData);
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
    xhr.onerror = () => reject(new Error("Upload failed — check your connection and try again"));
    xhr.send(form);
  });
}

function setStatus(msg) { $("status").textContent = msg || ""; }

function showView(name) {
  const navFor = { feed: "nav-feed", videos: "nav-videos", games: "nav-games",
                   game: "nav-games", tasks: "nav-tasks",
                   leaderboard: "nav-ranks", profile: "nav-me" };
  ["feed", "videos", "search", "tasks", "leaderboard", "profile", "saved", "shared", "games", "game", "admin"].forEach(v => {
    $("view-" + v).hidden = v !== name;
    const btn = navFor[v];
    if (btn) $(btn).classList.toggle("active", v === name);
  });
  if (name !== "game" && typeof stopGame === "function") stopGame();
  if (name === "tasks") loadTasks();
  if (name === "saved") loadSaved();
  if (name === "shared") loadShared();
  if (name === "admin") loadAdmin();
  if (name === "videos") { loadVideos(true); maybeShowAd(); }
  else document.querySelectorAll("#video-list video").forEach(v => v.pause());
  if (name === "leaderboard") loadRanks();
  moveNavPill();
}

const NAV_IDS = ["nav-feed", "nav-videos", "nav-games", "nav-tasks",
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
    img.src = "/media/" + encodeURIComponent(photoId);
    img.alt = name || "";
    img.loading = "lazy";
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
    img.src = "/media/" + encodeURIComponent(p.media_file_id);
    img.loading = "lazy";
    img.alt = "photo";
    frame.appendChild(img);
    el.appendChild(frame);
  } else if (p.media_file_id && p.type === "video") {
    const frame = document.createElement("div");
    frame.className = "post-media";
    const vid = document.createElement("video");
    vid.src = "/media/" + encodeURIComponent(p.media_file_id);
    vid.controls = true;
    vid.preload = "metadata";
    vid.playsInline = true;
    frame.appendChild(vid);
    const playBadge = document.createElement("div");
    playBadge.className = "play-badge";
    playBadge.textContent = "▶";
    playBadge.onclick = () => { vid.play(); };
    vid.onplay = () => { playBadge.style.display = "none"; };
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

  if (me && p.author_id === me.telegram_id) {
    const del = document.createElement("button");
    del.textContent = "🗑";
    del.title = "Delete post";
    del.onclick = async () => {
      try {
        await api("/posts/" + p.id, { method: "DELETE" });
        el.remove();
      } catch (e) { setStatus("Could not delete the post."); }
    };
    actions.appendChild(del);
  } else {
    const rep = document.createElement("button");
    rep.textContent = "⚑";
    rep.title = "Report post";
    rep.onclick = async () => {
      try {
        await api("/reports", { method: "POST",
          body: JSON.stringify({ post_id: p.id, reason: "user report" }) });
        setStatus("Thanks, the post was reported.");
      } catch (e) { setStatus("Could not report the post."); }
    };
    actions.appendChild(rep);
  }
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
async function loadFeed(reset) {
  try {
    const url = "/feed?tab=" + tab + (reset || !feedCursor ? "" : "&cursor=" + feedCursor);
    const data = await api(url);
    if (reset) $("feed-list").innerHTML = "";
    data.posts.forEach(p => $("feed-list").appendChild(postCard(p)));
    feedCursor = data.next_cursor;
    $("feed-more").hidden = !feedCursor;
    $("feed-empty").hidden = data.posts.length > 0 || !reset;
  } catch (e) { setStatus("Could not load the feed."); }
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
    if (en.isIntersecting) v.play().catch(() => {});
    else v.pause();
  });
}, { root: document.getElementById("view-videos"), threshold: 0.6 });

function reelCard(p) {
  const el = document.createElement("section");
  el.className = "reel";

  const vid = document.createElement("video");
  vid.src = "/media/" + encodeURIComponent(p.media_file_id || "");
  vid.loop = true;
  vid.muted = reelMuted;
  vid.playsInline = true;
  vid.preload = "metadata";
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
  const mWrap = document.createElement("div");
  mWrap.className = "reel-act";
  const mBtn = document.createElement("button");
  mBtn.textContent = "⋮";
  mBtn.title = "Options";
  mBtn.onclick = () => openReelMenu(p, el);
  mWrap.appendChild(mBtn);
  side.append(likeWrap, cWrap, mWrap);
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
function closeReelMenu() { $("reel-sheet-wrap").hidden = true; }

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
    a.href = "/media/" + encodeURIComponent(p.media_file_id);
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
      setStatus("Got it — this video was hidden.");
    });
    row("⚑", "Report", async () => {
      try {
        await api("/reports", { method: "POST",
          body: JSON.stringify({ post_id: p.id, reason: "user report" }) });
        setStatus("Thanks, the video was reported.");
      } catch (e) { setStatus("Could not report."); }
    }, true);
  }
  if (mine) row("🗑", "Delete", async () => {
    try {
      await api("/posts/" + p.id, { method: "DELETE" });
      reelEl.remove();
      setStatus("Deleted.");
    } catch (e) { setStatus("Could not delete."); }
  }, true);
  row("✕", "Cancel", () => {});
  $("reel-sheet-wrap").hidden = false;
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
    $("shared-empty").hidden = data.posts.length > 0;
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
    $("saved-empty").hidden = data.posts.length > 0;
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
      nm.textContent = r.first_name + (isMe ? " (You)" : "");
      if (r.is_verified) nm.appendChild(verifiedBadge());
      if (r.username) {
        const small = document.createElement("small");
        small.textContent = "@" + r.username;
        nm.appendChild(small);
      }
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
        u.first_name + (u.username ? " @" + u.username : "")));
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
    headWrap.append(avatarEl(u.first_name, u.telegram_id, true, u.photo_file_id), col);
    const bio = document.createElement("p");
    bio.textContent = u.bio || "";
    const stats = document.createElement("div");
    stats.className = "stats";
    stats.textContent = u.posts + " posts · " + u.followers + " followers · " +
      u.following_count + " following · ⭐ " + u.points + " points";
    box.append(headWrap, bio, stats);

    if (u.is_official) {
      const chip = document.createElement("button");
      chip.className = "wide";
      chip.disabled = true;
      chip.textContent = "✓ Following — Official account";
      box.appendChild(chip);
    } else if (me && userId !== me.telegram_id) {
      const fBtn = document.createElement("button");
      fBtn.className = "wide";
      const paint = () => { fBtn.textContent = u.following ? "Unfollow" : "Follow"; };
      paint();
      fBtn.onclick = async () => {
        try {
          const r = await api("/users/" + userId + "/follow", { method: "POST" });
          u.following = r.following;
          u.followers = r.followers;
          stats.textContent = u.posts + " posts · " + u.followers +
            " followers · " + u.following_count + " following · ⭐ " +
            u.points + " points";
          paint();
        } catch (e) { setStatus("Could not update follow."); }
      };
      box.appendChild(fBtn);
    }

    if (me && userId === me.telegram_id) {
      const pBtn = document.createElement("button");
      pBtn.className = "wide photo-change";
      pBtn.textContent = "📷 Change profile photo";
      pBtn.onclick = () => $("profile-file").click();
      box.appendChild(pBtn);
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
    const h = document.createElement("h3");
    h.textContent = "⭐ My points: " + pts.balance;
    wrap.appendChild(h);
    if (pts.entries.length) {
      const ul = document.createElement("ul");
      ul.className = "ledger";
      pts.entries.forEach(e => {
        const li = document.createElement("li");
        li.textContent = (e.amount >= 0 ? "+" : "") + e.amount + " — " + e.reason;
        ul.appendChild(li);
      });
      wrap.appendChild(ul);
    }
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
    card.className = "mon-card";
    const mh = document.createElement("div");
    mh.className = "mon-head";
    const mt = document.createElement("b");
    mt.textContent = "💰 Monetization";
    const badge = document.createElement("span");
    badge.className = "mon-badge" + (mon.unlocked ? " open" : "");
    badge.textContent = mon.unlocked ? "Unlocked ✓" : "Locked";
    mh.append(mt, badge);
    card.appendChild(mh);
    mon.checks.forEach(c => {
      const row = document.createElement("div");
      row.className = "mon-row";
      const left = document.createElement("span");
      left.textContent = (c.done ? "✅ " : "⬜ ") + c.label;
      const right = document.createElement("span");
      right.className = c.done ? "done" : "";
      right.textContent = c.current + " / " + c.required;
      row.append(left, right);
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
        btn.className = "task-claim claimed";
        btn.disabled = true;
      } else if (t.claimable) {
        btn.textContent = "Claim";
        btn.className = "task-claim";
        btn.onclick = async () => {
          try {
            const r = await api("/me/tasks/" + t.key + "/claim", { method: "POST" });
            setStatus("+" + r.points_awarded + " points! Balance: " + r.balance);
            loadMe().catch(() => {});
            loadTasks();
          } catch (e) { setStatus("Could not claim this task."); }
        };
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
  startHeartbeat();
  $("profile-line").textContent =
    me.first_name + (me.username ? " @" + me.username : "");
  if (me.is_verified) $("profile-line").appendChild(verifiedBadge());
  $("stats").textContent = me.posts + " posts · " + me.followers +
    " followers · " + me.following + " following";
  $("points-chip").textContent = "⭐ " + me.points;
  $("entry-name").textContent = me.first_name || "Full name";
  $("entry-user").textContent = me.username ? "@" + me.username : "Username";
  entryMode = me.is_new ? "signup" : "login";
  paintEntry();
  applyAdminVisibility();
  initAds();
  if (!me.photo_file_id) {
    api("/me/photo/sync", { method: "POST" }).then(r => {
      if (r && r.photo_file_id) me.photo_file_id = r.photo_file_id;
    }).catch(() => {});
  }
}

let composerFile = null;

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
  x.onclick = () => { composerFile = null; $("composer-file").value = ""; paintAttach(); };
  chip.appendChild(x);
}

$("composer-media").onclick = () => $("composer-file").click();
$("composer-file").onchange = () => {
  composerFile = $("composer-file").files[0] || null;
  if (composerFile) {
    // Phase 19: photos cap at 20 MB; videos may be up to 60 MB — the
    // server shrinks them to fit Telegram before posting.
    const isVideo = composerFile.type.startsWith("video");
    const cap = (isVideo ? 60 : 20) * 1024 * 1024;
    if (composerFile.size > cap) {
      setStatus(isVideo
        ? "That video is over 60 MB — please trim it or record at a lower resolution."
        : "That file is over 20 MB — please pick a smaller one.");
      composerFile = null;
      $("composer-file").value = "";
    }
  }
  paintAttach();
};

$("composer-post").onclick = async () => {
  const text = $("composer-text").value.trim();
  if (!text && !composerFile) return;
  const btn = $("composer-post");
  btn.disabled = true;
  try {
    if (composerFile) {
      btn.textContent = "Uploading…";
      const form = new FormData();
      form.append("file", composerFile);
      form.append("caption", text);
      const res = await apiFormProgress("/posts/upload", form, pct => {
        btn.textContent = pct === null
          ? "Sending… keep the app open"
          : "Uploading… " + pct + "%";
      });
      if (res && res.status === "processing") {
        setStatus("🎬 Video received! It's being processed — the bot " +
          "will message you when it's live in the feed.");
      }
      composerFile = null;
      $("composer-file").value = "";
      paintAttach();
    } else {
      await api("/posts", { method: "POST",
        body: JSON.stringify({ type: "text", caption: text }) });
    }
    $("composer-text").value = "";
    setTab("explore");
    loadMe().catch(() => {});
  } catch (e) { setStatus(e.message || "Could not post."); }
  btn.disabled = false;
  btn.textContent = "Post";
};

$("profile-file").onchange = async () => {
  const f = $("profile-file").files[0];
  $("profile-file").value = "";
  if (!f) return;
  const form = new FormData();
  form.append("file", f);
  try {
    const r = await apiForm("/me/photo/upload", form);
    if (me) me.photo_file_id = r.photo_file_id;
    setStatus("Profile photo updated.");
    if (me) openProfile(me.telegram_id);
  } catch (e) { setStatus(e.message || "Could not update the photo."); }
};
$("tab-explore").onclick = () => setTab("explore");
$("tab-following").onclick = () => setTab("following");
$("feed-more").onclick = () => loadFeed(false);
$("profile-more").onclick = () => loadProfilePosts(false);
$("search-go").onclick = () => runSearch($("search-input").value.trim());
$("nav-feed").onclick = () => showView("feed");
$("nav-videos").onclick = () => showView("videos");
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

loadMe().then(() => loadFeed(true)).catch(() => {
  $("profile-line").textContent = "Please open this app from inside Telegram.";
  $("entry-go").disabled = true;
  $("entry-note").textContent =
    "Please open Nexora Social from inside Telegram to continue.";
});

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

// ---------------------------------------------------------- drawer menu ---
// Side menu in the owner's chosen panel design (Oct 31). Items mirror
// the bottom nav plus Library (Saved / Shared with count badges) and
// Account (My Profile / Search / Log out back to the entry screen).
function openDrawer() {
  $("drawer-wrap").hidden = false;
  requestAnimationFrame(() => $("drawer-wrap").classList.add("open"));
  syncDrawerActive();
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
function closeDrawer() {
  $("drawer-wrap").classList.remove("open");
  setTimeout(() => { $("drawer-wrap").hidden = true; }, 260);
}
function syncDrawerActive() {
  const current = ["feed", "videos", "search", "tasks", "leaderboard",
    "profile", "saved", "shared", "games", "game"]
    .find(v => !$("view-" + v).hidden) || "feed";
  const key = current === "game" ? "games" : current;
  document.querySelectorAll(".drawer-item[data-go]").forEach(b =>
    b.classList.toggle("active", b.dataset.go === key));
}
$("hero-menu").onclick = openDrawer;
$("drawer-close").onclick = closeDrawer;
$("drawer-backdrop").onclick = closeDrawer;
document.querySelectorAll(".drawer-item[data-go]").forEach(b => {
  b.onclick = () => {
    const go = b.dataset.go;
    closeDrawer();
    showView(go);
    if (go === "profile") loadMe();
  };
});
$("drawer-logout").onclick = () => {
  closeDrawer();
  localStorage.removeItem("nx_remember");
  sessionStorage.removeItem("nx_entered");
  entryMode = "login";
  paintEntry();
  $("entry-screen").hidden = false;
};
moveNavPill();

// ---------------------------------------------------------------- admin --
// Owner-only panel (Phase 18). The drawer item stays hidden unless /auth
// says this account is in ADMIN_IDS; every /admin/* endpoint re-checks
// that server-side, so the panel is a convenience, not the security.
function applyAdminVisibility() {
  const it = $("drawer-admin");
  if (it) it.hidden = !(me && me.is_admin);
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
     ["📺 Ads today", d.ads_today], ["📺 Ads total", d.ads_total],
     ["⏱️ Time today", fmtDur(d.time_today_seconds)],
     ["⏱️ Avg / member", fmtDur(d.avg_time_today_seconds)]
    ].forEach(([l, v]) => tiles.appendChild(statCard(l, v)));
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
  } catch (e) { box.textContent = "Could not load stats."; }
}

function loadAdmin() {
  if (!me || !me.is_admin) return;
  loadDashboard();
  loadAdminStats();
  loadAdminReports();
  loadAdminUsers($("admin-user-q").value.trim());
  loadAdminPosts();
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
