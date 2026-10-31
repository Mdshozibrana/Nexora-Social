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
  const navFor = { feed: "nav-feed", search: "nav-search",
                   tasks: "nav-tasks", profile: "nav-me" };
  ["feed", "search", "tasks", "profile"].forEach(v => {
    $("view-" + v).hidden = v !== name;
    $(navFor[v]).classList.toggle("active", v === name);
  });
  if (name === "tasks") loadTasks();
}

function avatarEl(name, id, big) {
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
  const sub = document.createElement("span");
  sub.className = "post-sub";
  sub.textContent = p.author_username ? "@" + p.author_username : "";
  who.append(nm, sub);
  head.append(avatarEl(p.author_name, p.author_id, false), who);
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
  const who = document.createElement("b");
  who.textContent = cm.author_name + ": ";
  row.appendChild(who);
  row.appendChild(document.createTextNode(cm.text));
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
      row.textContent = u.first_name + (u.username ? " @" + u.username : "");
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
    const sub = document.createElement("div");
    sub.className = "profile-sub";
    sub.textContent = u.username ? "@" + u.username : "";
    col.append(name, sub);
    headWrap.append(avatarEl(u.first_name, u.telegram_id, true), col);
    const bio = document.createElement("p");
    bio.textContent = u.bio || "";
    const stats = document.createElement("div");
    stats.className = "stats";
    stats.textContent = u.posts + " posts · " + u.followers + " followers · " +
      u.following_count + " following · ⭐ " + u.points + " points";
    box.append(headWrap, bio, stats);

    if (me && userId !== me.telegram_id) {
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
      prog.textContent = t.progress + " / " + t.target;
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
  $("stats").textContent = me.posts + " posts · " + me.followers +
    " followers · " + me.following + " following";
  $("points-chip").textContent = "⭐ " + me.points;
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
$("nav-search").onclick = () => showView("search");
$("nav-tasks").onclick = () => showView("tasks");
$("nav-me").onclick = () => { if (me) openProfile(me.telegram_id); };

loadMe().then(() => loadFeed(true)).catch(() => {
  $("profile-line").textContent = "Please open this app from inside Telegram.";
});
