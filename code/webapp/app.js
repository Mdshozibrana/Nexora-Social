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

function setStatus(msg) { $("status").textContent = msg || ""; }

function showView(name) {
  const navFor = { feed: "nav-feed", videos: "nav-videos", games: "nav-games",
                   game: "nav-games", tasks: "nav-tasks",
                   leaderboard: "nav-ranks", profile: "nav-me" };
  ["feed", "videos", "search", "tasks", "leaderboard", "profile", "saved", "shared", "games", "game"].forEach(v => {
    $("view-" + v).hidden = v !== name;
    const btn = navFor[v];
    if (btn) $(btn).classList.toggle("active", v === name);
  });
  if (name !== "game" && typeof stopGame === "function") stopGame();
  if (name === "tasks") loadTasks();
  if (name === "saved") loadSaved();
  if (name === "shared") loadShared();
  if (name === "videos") loadVideos(true);
  else document.querySelectorAll("#video-list video").forEach(v => v.pause());
  if (name === "leaderboard") loadRanks();
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
    const img = document.createElement("img");
    img.src = "/media/" + encodeURIComponent(p.media_file_id);
    img.loading = "lazy";
    img.alt = "photo";
    el.appendChild(img);
  } else if (p.media_file_id && p.type === "video") {
    const vid = document.createElement("video");
    vid.src = "/media/" + encodeURIComponent(p.media_file_id);
    vid.controls = true;
    vid.preload = "metadata";
    el.appendChild(vid);
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
async function loadMe() {
  me = await api("/auth", { method: "POST", body: JSON.stringify({ initData }) });
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
  if (!me.photo_file_id) {
    api("/me/photo/sync", { method: "POST" }).then(r => {
      if (r && r.photo_file_id) me.photo_file_id = r.photo_file_id;
    }).catch(() => {});
  }
}

$("composer-post").onclick = async () => {
  const text = $("composer-text").value.trim();
  if (!text) return;
  try {
    await api("/posts", { method: "POST",
      body: JSON.stringify({ type: "text", caption: text }) });
    $("composer-text").value = "";
    setTab("explore");
    loadMe().catch(() => {});
  } catch (e) { setStatus("Could not post."); }
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
