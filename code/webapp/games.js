// Nexora Social — classic button-phone games (owner request, Oct 31):
// the favourites from the first mobile phones. Pure client-side, no
// backend: Snake (Nokia), Tetris (brick game), Breakout, Memory match.
const GameRegistry = [];
// Phase 208: the Games section is dark green — the 2D canvases
// share one very-dark-green board colour. Snake and Archery
// keep their Nokia-LCD green and Flappy keeps its sky: those
// colours ARE the games' look, and their pieces stay legible.
const GX_CANVAS_BG = "#0C2115";
function registerGame(def) { GameRegistry.push(def); }

// Phase 97 (audit): saved game progress belongs to ONE account,
// like the theme (Phase 96) — the old plain keys were shared by
// every Telegram account on the same phone, so a second account
// inherited the first account's Archery run and best scores. The
// old shared value is claimed once by the account signed in now.
function nxUid() {
  try {
    return (typeof me !== "undefined" && me && me.telegram_id)
      ? String(me.telegram_id) : "anon";
  } catch (e) { return "anon"; }
}
function nxGet(k) {
  try {
    const mine = localStorage.getItem(k + "_" + nxUid());
    if (mine !== null) return mine;
    if (nxUid() === "anon") return null;
    const legacy = localStorage.getItem(k);
    if (legacy !== null) {
      localStorage.setItem(k + "_" + nxUid(), legacy);
      localStorage.removeItem(k);
      return legacy;
    }
  } catch (e) { /* storage blocked */ }
  return null;
}
function nxSet(k, v) {
  try { localStorage.setItem(k + "_" + nxUid(), v); } catch (e) {}
}

let gameCleanup = null;
function stopGame() {
  if (gameCleanup) {
    try { gameCleanup(); } catch (e) { /* already gone */ }
    gameCleanup = null;
  }
  const stage = document.getElementById("game-stage");
  if (stage) stage.innerHTML = "";
}

function openGame(id) {
  const def = GameRegistry.find(g => g.id === id);
  if (!def) return;
  stopGame();
  showView("game");
  const _gt = $("game-title");
  _gt.innerHTML = "";
  const _gi = document.createElement("span");
  _gi.className = "gt-icon";
  _gi.innerHTML = def.icon;
  const _tx = document.createElement("span");
  _tx.textContent = " " + def.title;
  _gt.append(_gi, _tx);
  $("game-score").textContent = "";
  $("game-help").textContent = def.help || "";
  gameCleanup = def.start($("game-stage"), s => {
    $("game-score").textContent = s;
  }) || null;
}

function dpad(stage, onDir, extra) {
  const pad = document.createElement("div");
  pad.className = "dpad";
  const mk = (label, dx, dy, pos) => {
    const b = document.createElement("button");
    b.textContent = label;
    b.style.gridColumn = pos[0];
    b.style.gridRow = pos[1];
    b.onclick = () => onDir(dx, dy);
    pad.appendChild(b);
  };
  mk("▲", 0, -1, [2, 1]);
  mk("◀", -1, 0, [1, 2]);
  mk("▼", 0, 1, [2, 2]);
  mk("▶", 1, 0, [3, 2]);
  stage.appendChild(pad);
  if (extra) {
    const row = document.createElement("div");
    row.className = "grow";
    extra.forEach(([label, fn]) => {
      const b = document.createElement("button");
      b.textContent = label;
      b.onclick = fn;
      row.appendChild(b);
    });
    stage.appendChild(row);
  }
  return pad;
}

function swipe(el, onDir) {
  let sx = 0, sy = 0;
  el.addEventListener("touchstart", e => {
    sx = e.touches[0].clientX; sy = e.touches[0].clientY;
  }, { passive: true });
  el.addEventListener("touchend", e => {
    const dx = e.changedTouches[0].clientX - sx;
    const dy = e.changedTouches[0].clientY - sy;
    if (Math.max(Math.abs(dx), Math.abs(dy)) < 24) return;
    if (Math.abs(dx) > Math.abs(dy)) onDir(Math.sign(dx), 0);
    else onDir(0, Math.sign(dy));
  }, { passive: true });
}

// ------------------------------------------------------------------ Snake --
registerGame({
  id: "snake", icon: '<svg viewBox="0 0 64 64"><rect x="2" y="2" width="60" height="60" rx="14" fill="#DFF3D8"/><circle cx="49" cy="15" r="5" fill="#E5484D"/><path d="M13 46 Q25 30 38 39 T54 25" stroke="#2FA84F" stroke-width="7" fill="none" stroke-linecap="round"/><circle cx="54" cy="25" r="6" fill="#2FA84F"/><circle cx="56.5" cy="22.5" r="1.8" fill="#fff"/><path d="M59 29 l2.5 4 M59 29 l-1 4.5" stroke="#E5484D" stroke-width="2" stroke-linecap="round"/></svg>', name: "Snake", title: "Snake",
  desc: "The Nokia classic — eat, grow, don't bite yourself.",
  help: "Swipe on the board or use the arrow keys.",
  start(stage, setScore) {
    const N = 20, C = 15;
    const cv = document.createElement("canvas");
    cv.width = N * C; cv.height = N * C;
    stage.appendChild(cv);
    const ctx = cv.getContext("2d");
    let snake, dir, next, food, score, timer = null, dead = false;
    const reset = () => {
      snake = [{ x: 10, y: 10 }, { x: 9, y: 10 }];
      dir = { x: 1, y: 0 }; next = dir; score = 0; dead = false;
      place(); draw(); setScore("Score: 0");
    };
    const place = () => {
      do { food = { x: (Math.random() * N) | 0, y: (Math.random() * N) | 0 }; }
      while (snake.some(s => s.x === food.x && s.y === food.y));
    };
    const draw = () => {
      ctx.fillStyle = "#b7c25e";  // Nokia LCD green
      ctx.fillRect(0, 0, cv.width, cv.height);
      ctx.fillStyle = "#26300a";
      snake.forEach(s => ctx.fillRect(s.x * C + 1, s.y * C + 1, C - 2, C - 2));
      ctx.fillRect(food.x * C + 3, food.y * C + 3, C - 6, C - 6);
      if (dead) {
        ctx.fillStyle = "rgba(38,48,10,.85)";
        ctx.fillRect(0, cv.height / 2 - 26, cv.width, 52);
        ctx.fillStyle = "#eef2c8";
        ctx.font = "bold 18px monospace";
        ctx.textAlign = "center";
        ctx.fillText("GAME OVER", cv.width / 2, cv.height / 2 + 6);
      }
    };
    const step = () => {
      dir = next;
      const head = { x: snake[0].x + dir.x, y: snake[0].y + dir.y };
      if (head.x < 0 || head.y < 0 || head.x >= N || head.y >= N ||
          snake.some(s => s.x === head.x && s.y === head.y)) {
        dead = true; draw();
        setScore("Game over — Score: " + score);
        clearInterval(timer); timer = null;
        return;
      }
      snake.unshift(head);
      if (head.x === food.x && head.y === food.y) {
        score += 10; place(); setScore("Score: " + score);
      } else snake.pop();
      draw();
    };
    const setDir = (dx, dy) => {
      if (dx === -dir.x && dy === -dir.y) return;
      if (dx === dir.x && dy === dir.y) return;
      next = { x: dx, y: dy };
    };
    const toggle = () => {
      if (dead) reset();
      if (timer) { clearInterval(timer); timer = null; toggleBtn.textContent = "▶ Start"; }
      else { timer = setInterval(step, 135); toggleBtn.textContent = "⏸ Pause"; }
    };
    const pad = dpad(stage, setDir, []);
    const toggleBtn = document.createElement("button");
    toggleBtn.textContent = "▶ Start";
    toggleBtn.onclick = toggle;
    pad.after(toggleBtn);
    toggleBtn.className = "";
    toggleBtn.style.cssText = "padding:10px 22px;border-radius:12px;font-size:15px;background:#EC4899;color:#121212;font-weight:700;";
    const wrap = document.createElement("div");
    wrap.className = "grow";
    wrap.appendChild(toggleBtn);
    stage.appendChild(wrap);
    swipe(cv, setDir);
    const keys = e => {
      const k = { ArrowUp: [0, -1], ArrowDown: [0, 1], ArrowLeft: [-1, 0], ArrowRight: [1, 0] }[e.key];
      if (k) { setDir(k[0], k[1]); e.preventDefault(); }
    };
    document.addEventListener("keydown", keys);
    reset();
    return () => {
      if (timer) clearInterval(timer);
      document.removeEventListener("keydown", keys);
    };
  },
});

// ----------------------------------------------------------------- Tetris --
registerGame({
  id: "tetris", icon: '<svg viewBox="0 0 64 64"><rect x="2" y="2" width="60" height="60" rx="14" fill="#E9E4FB"/><rect x="12" y="12" width="10" height="10" fill="#7C5CFF"/><rect x="22" y="12" width="10" height="10" fill="#7C5CFF"/><rect x="32" y="12" width="10" height="10" fill="#7C5CFF"/><rect x="22" y="22" width="10" height="10" fill="#7C5CFF"/><rect x="12" y="32" width="10" height="10" fill="#FFC53D"/><rect x="22" y="32" width="10" height="10" fill="#FFC53D"/><rect x="12" y="42" width="10" height="10" fill="#FFC53D"/><rect x="22" y="42" width="10" height="10" fill="#FFC53D"/><rect x="38" y="32" width="10" height="10" fill="#22B8CF"/><rect x="48" y="32" width="10" height="10" fill="#22B8CF"/><rect x="38" y="42" width="10" height="10" fill="#FF6B35"/><rect x="48" y="42" width="10" height="10" fill="#FF6B35"/></svg>', name: "Tetris", title: "Tetris",
  desc: "The brick-game legend. Stack, clear lines, survive.",
  help: "Buttons or arrow keys: move, ▲ rotate, ▼ drop faster.",
  start(stage, setScore) {
    const W = 10, H = 20, C = 18;
    const cv = document.createElement("canvas");
    cv.width = W * C; cv.height = H * C;
    stage.appendChild(cv);
    const ctx = cv.getContext("2d");
    const SHAPES = [
      [[1, 1, 1, 1]],
      [[1, 1], [1, 1]],
      [[0, 1, 0], [1, 1, 1]],
      [[0, 1, 1], [1, 1, 0]],
      [[1, 1, 0], [0, 1, 1]],
      [[1, 0, 0], [1, 1, 1]],
      [[0, 0, 1], [1, 1, 1]],
    ];
    const COLORS = ["#22d3ee", "#facc15", "#c084fc", "#4ade80", "#f87171", "#60a5fa", "#fb923c"];
    let grid, piece, px, py, color, score, timer = null, dead = false;
    const collide = (shape, ox, oy) => shape.some((row, y) =>
      row.some((v, x) => v && (ox + x < 0 || ox + x >= W || oy + y >= H ||
        (oy + y >= 0 && grid[oy + y][ox + x]))));
    const spawn = () => {
      const i = (Math.random() * SHAPES.length) | 0;
      piece = SHAPES[i].map(r => r.slice());
      color = COLORS[i];
      px = ((W - piece[0].length) / 2) | 0; py = 0;
      if (collide(piece, px, py)) {
        dead = true; setScore("Game over — Score: " + score);
        clearInterval(timer); timer = null;
      }
    };
    const reset = () => {
      grid = Array.from({ length: H }, () => Array(W).fill(null));
      score = 0; dead = false;
      spawn(); draw(); setScore("Score: 0");
    };
    const lock = () => {
      piece.forEach((row, y) => row.forEach((v, x) => {
        if (v && py + y >= 0) grid[py + y][px + x] = color;
      }));
      grid = grid.filter(row => row.some(c => !c));
      const cleared = H - grid.length;
      while (grid.length < H) grid.unshift(Array(W).fill(null));
      if (cleared) { score += cleared * 100; setScore("Score: " + score); }
      spawn();
    };
    const step = () => {
      if (dead) return;
      if (!collide(piece, px, py + 1)) py++;
      else lock();
      draw();
    };
    const draw = () => {
      ctx.fillStyle = GX_CANVAS_BG;
      ctx.fillRect(0, 0, cv.width, cv.height);
      grid.forEach((row, y) => row.forEach((c, x) => {
        if (c) { ctx.fillStyle = c; ctx.fillRect(x * C + 1, y * C + 1, C - 2, C - 2); }
      }));
      if (piece && !dead) {
        ctx.fillStyle = color;
        piece.forEach((row, y) => row.forEach((v, x) => {
          if (v) ctx.fillRect((px + x) * C + 1, (py + y) * C + 1, C - 2, C - 2);
        }));
      }
    };
    const move = dx => { if (!collide(piece, px + dx, py)) { px += dx; draw(); } };
    const rotate = () => {
      const r = piece[0].map((_, i) => piece.map(row => row[i]).reverse());
      for (const off of [0, -1, 1]) if (!collide(r, px + off, py)) {
        piece = r; px += off; draw(); return;
      }
    };
    const drop = () => { while (!collide(piece, px, py + 1)) py++; lock(); draw(); };
    const toggle = () => {
      if (dead) reset();
      if (timer) { clearInterval(timer); timer = null; tBtn.textContent = "▶ Start"; }
      else { timer = setInterval(step, 480); tBtn.textContent = "⏸ Pause"; }
    };
    const pad = dpad(stage, (dx, dy) => {
      if (dx) move(dx);
      if (dy > 0) step();
      if (dy < 0) rotate();
    }, [["⟳ Rotate", rotate], ["⤓ Drop", drop]]);
    const tBtn = document.createElement("button");
    tBtn.textContent = "▶ Start";
    tBtn.onclick = toggle;
    tBtn.style.cssText = "padding:10px 22px;border-radius:12px;font-size:15px;background:#EC4899;color:#121212;font-weight:700;";
    const wrap = document.createElement("div");
    wrap.className = "grow";
    wrap.appendChild(tBtn);
    stage.appendChild(wrap);
    swipe(cv, (dx, dy) => { if (dx) move(dx); if (dy > 0) step(); if (dy < 0) rotate(); });
    const keys = e => {
      if (e.key === "ArrowLeft") move(-1);
      else if (e.key === "ArrowRight") move(1);
      else if (e.key === "ArrowDown") step();
      else if (e.key === "ArrowUp") rotate();
      else return;
      e.preventDefault();
    };
    document.addEventListener("keydown", keys);
    reset();
    return () => {
      if (timer) clearInterval(timer);
      document.removeEventListener("keydown", keys);
    };
  },
});

// --------------------------------------------------------------- Breakout --
registerGame({
  id: "breakout", icon: '<svg viewBox="0 0 64 64"><rect x="2" y="2" width="60" height="60" rx="14" fill="#FFF3D6"/><rect x="10" y="10" width="14" height="8" rx="2" fill="#E5484D"/><rect x="25" y="10" width="14" height="8" rx="2" fill="#FFC53D"/><rect x="40" y="10" width="14" height="8" rx="2" fill="#2FA84F"/><rect x="10" y="20" width="14" height="8" rx="2" fill="#3E8FD0"/><rect x="25" y="20" width="14" height="8" rx="2" fill="#7C5CFF"/><rect x="40" y="20" width="14" height="8" rx="2" fill="#E5484D"/><circle cx="32" cy="40" r="5" fill="#1F2937"/><rect x="18" y="50" width="28" height="6" rx="3" fill="#1F2937"/></svg>', name: "Breakout", title: "Breakout",
  desc: "Brick-breaker: bounce the ball, smash every brick.",
  help: "Move your finger/mouse on the board, or use ◀ ▶.",
  start(stage, setScore) {
    const W = 300, H = 360;
    const cv = document.createElement("canvas");
    cv.width = W; cv.height = H;
    stage.appendChild(cv);
    const ctx = cv.getContext("2d");
    const COLORS = ["#f87171", "#fb923c", "#facc15", "#4ade80", "#60a5fa"];
    let paddle, ball, bricks, score, lives, raf = null, running = false, keysDown = {};
    const reset = () => {
      paddle = { x: W / 2 - 35, w: 70 };
      ball = { x: W / 2, y: H - 60, dx: 2.4, dy: -2.8, r: 6 };
      bricks = [];
      for (let r = 0; r < 5; r++) for (let c = 0; c < 6; c++)
        bricks.push({ x: 8 + c * 48, y: 36 + r * 20, w: 44, h: 14, color: COLORS[r], on: true });
      score = 0; lives = 3;
      setScore("Score: 0 · Lives: 3");
      draw();
    };
    const draw = () => {
      ctx.fillStyle = GX_CANVAS_BG;
      ctx.fillRect(0, 0, W, H);
      bricks.forEach(b => {
        if (b.on) { ctx.fillStyle = b.color; ctx.fillRect(b.x, b.y, b.w, b.h); }
      });
      ctx.fillStyle = "#e5e7eb";
      ctx.fillRect(paddle.x, H - 24, paddle.w, 9);
      ctx.beginPath();
      ctx.arc(ball.x, ball.y, ball.r, 0, Math.PI * 2);
      ctx.fillStyle = "#fff";
      ctx.fill();
    };
    const frame = () => {
      if (keysDown.left) paddle.x = Math.max(0, paddle.x - 5);
      if (keysDown.right) paddle.x = Math.min(W - paddle.w, paddle.x + 5);
      ball.x += ball.dx; ball.y += ball.dy;
      if (ball.x < ball.r || ball.x > W - ball.r) ball.dx *= -1;
      if (ball.y < ball.r) ball.dy *= -1;
      if (ball.y > H - 28 && ball.y < H - 12 && ball.x > paddle.x &&
          ball.x < paddle.x + paddle.w && ball.dy > 0) {
        ball.dy *= -1;
        ball.dx += (ball.x - (paddle.x + paddle.w / 2)) / 28;
      }
      for (const b of bricks) {
        if (b.on && ball.x > b.x && ball.x < b.x + b.w &&
            ball.y > b.y && ball.y < b.y + b.h) {
          b.on = false; ball.dy *= -1; score += 10;
          setScore("Score: " + score + " · Lives: " + lives);
          break;
        }
      }
      if (bricks.every(b => !b.on)) {
        setScore("You win! Score: " + score);
        stop(); draw(); return;
      }
      if (ball.y > H) {
        lives--;
        if (lives <= 0) {
          setScore("Game over — Score: " + score);
          stop(); draw(); return;
        }
        setScore("Score: " + score + " · Lives: " + lives);
        ball = { x: W / 2, y: H - 60, dx: 2.4, dy: -2.8, r: 6 };
      }
      draw();
      raf = requestAnimationFrame(frame);
    };
    const stop = () => { running = false; if (raf) cancelAnimationFrame(raf); raf = null; tBtn.textContent = "▶ Start"; };
    const toggle = () => {
      if (lives <= 0 || bricks.every(b => !b.on)) reset();
      if (running) stop();
      else { running = true; tBtn.textContent = "⏸ Pause"; raf = requestAnimationFrame(frame); }
    };
    const point = e => {
      const rect = cv.getBoundingClientRect();
      const cx = (e.touches ? e.touches[0].clientX : e.clientX) - rect.left;
      paddle.x = Math.max(0, Math.min(W - paddle.w, cx * (W / rect.width) - paddle.w / 2));
      if (!running) draw();
    };
    cv.addEventListener("pointermove", point);
    cv.addEventListener("touchmove", point, { passive: true });
    dpad(stage, (dx) => {
      paddle.x = Math.max(0, Math.min(W - paddle.w, paddle.x + dx * 18));
      if (!running) draw();
    }, []);
    const tBtn = document.createElement("button");
    tBtn.textContent = "▶ Start";
    tBtn.onclick = toggle;
    tBtn.style.cssText = "padding:10px 22px;border-radius:12px;font-size:15px;background:#EC4899;color:#121212;font-weight:700;";
    const wrap = document.createElement("div");
    wrap.className = "grow";
    wrap.appendChild(tBtn);
    stage.appendChild(wrap);
    const kd = e => {
      if (e.key === "ArrowLeft") keysDown.left = true;
      if (e.key === "ArrowRight") keysDown.right = true;
    };
    const ku = e => {
      if (e.key === "ArrowLeft") keysDown.left = false;
      if (e.key === "ArrowRight") keysDown.right = false;
    };
    document.addEventListener("keydown", kd);
    document.addEventListener("keyup", ku);
    reset();
    return () => {
      stop();
      document.removeEventListener("keydown", kd);
      document.removeEventListener("keyup", ku);
    };
  },
});

// ----------------------------------------------------------------- Memory --
registerGame({
  id: "memory", icon: '<svg viewBox="0 0 64 64"><rect x="2" y="2" width="60" height="60" rx="14" fill="#FDE8EF"/><rect x="9" y="14" width="20" height="28" rx="4" fill="#3E8FD0"/><circle cx="19" cy="28" r="6" fill="#8ED4F7"/><circle cx="19" cy="28" r="2.5" fill="#3E8FD0"/><rect x="35" y="14" width="20" height="28" rx="4" fill="#fff" stroke="#E5C07B" stroke-width="2"/><path d="M45 20 l2.4 4.9 5.4.8 -3.9 3.8 .9 5.4 -4.8-2.5 -4.8 2.5 .9-5.4 -3.9-3.8 5.4-.8z" fill="#FFC53D"/></svg>', name: "Memory", title: "Memory Match",
  desc: "The card-flip memory game from the button-phone days.",
  help: "Tap two cards. Match all 8 pairs in as few moves as you can.",
  start(stage, setScore) {
    const EMOJI = ["🍎", "🍌", "🍇", "🍓", "🍒", "🍋", "🍉", "🍍"];
    const grid = document.createElement("div");
    grid.className = "mem-grid";
    stage.appendChild(grid);
    let first = null, lock = false, moves = 0, found = 0;
    const deck = [...EMOJI, ...EMOJI].sort(() => Math.random() - 0.5);
    deck.forEach(emoji => {
      const b = document.createElement("button");
      b.className = "mem-card";
      b.textContent = "✦";
      b.onclick = () => {
        if (lock || b.classList.contains("open") || b.classList.contains("done")) return;
        b.textContent = emoji;
        b.classList.add("open");
        if (!first) { first = { b, emoji }; return; }
        moves++;
        if (first.emoji === emoji) {
          first.b.classList.add("done");
          b.classList.add("done");
          first = null;
          found++;
          setScore("Moves: " + moves);
          if (found === EMOJI.length)
            setScore("🎉 Solved in " + moves + " moves!");
        } else {
          lock = true;
          const f = first;
          first = null;
          setScore("Moves: " + moves);
          setTimeout(() => {
            f.b.textContent = "✦"; f.b.classList.remove("open");
            b.textContent = "✦"; b.classList.remove("open");
            lock = false;
          }, 650);
        }
      };
      grid.appendChild(b);
    });
    setScore("Moves: 0");
    const again = document.createElement("button");
    again.textContent = "↻ Shuffle & restart";
    again.style.cssText = "padding:10px 22px;border-radius:12px;font-size:15px;background:#EC4899;color:#121212;font-weight:700;";
    again.onclick = () => openGame("memory");
    const wrap = document.createElement("div");
    wrap.className = "grow";
    wrap.appendChild(again);
    stage.appendChild(wrap);
    return () => {};
  },
});

// ------------------------------------------------------------------ Pong --
// Phase 47 (owner: more old-time games): the 1972 arcade original.
registerGame({
  id: "pong", icon: '<svg viewBox="0 0 64 64"><rect x="2" y="2" width="60" height="60" rx="14" fill="#DFF1FB"/><line x1="32" y1="8" x2="32" y2="56" stroke="#9DB8C6" stroke-width="2" stroke-dasharray="4 4"/><rect x="10" y="22" width="5" height="20" rx="2.5" fill="#1F2937"/><rect x="49" y="22" width="5" height="20" rx="2.5" fill="#1F2937"/><circle cx="32" cy="32" r="5" fill="#E5484D"/></svg>', name: "Pong", title: "Pong",
  desc: "The 1972 arcade original — you vs the machine, first to 7.",
  help: "Drag on the board, use ▲ ▼, or the arrow keys to move your paddle.",
  start(stage, setScore) {
    const W = 300, H = 300, PH = 56, PW = 8;
    const cv = document.createElement("canvas");
    cv.width = W; cv.height = H;
    stage.appendChild(cv);
    const ctx = cv.getContext("2d");
    let py = H / 2 - PH / 2, ay = py, ball, you = 0, cpu = 0,
        timer = null, over = false;
    const serve = dir => {
      ball = { x: W / 2, y: H / 2, vx: 3.2 * dir,
               vy: (Math.random() * 2 - 1) * 2.2 };
    };
    serve(1);
    const draw = () => {
      ctx.fillStyle = GX_CANVAS_BG;
      ctx.fillRect(0, 0, W, H);
      ctx.strokeStyle = "rgba(238,242,200,.35)";
      ctx.setLineDash([6, 8]);
      ctx.beginPath(); ctx.moveTo(W / 2, 0); ctx.lineTo(W / 2, H); ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = "#eef2c8";
      ctx.fillRect(8, py, PW, PH);
      ctx.fillRect(W - 8 - PW, ay, PW, PH);
      ctx.beginPath(); ctx.arc(ball.x, ball.y, 5, 0, 7); ctx.fill();
      ctx.font = "bold 22px monospace"; ctx.textAlign = "center";
      ctx.fillText(you, W / 2 - 26, 30);
      ctx.fillText(cpu, W / 2 + 26, 30);
      if (over) {
        ctx.fillStyle = "rgba(16,20,8,.85)";
        ctx.fillRect(0, H / 2 - 26, W, 52);
        ctx.fillStyle = "#eef2c8"; ctx.font = "bold 17px monospace";
        ctx.fillText(you > cpu ? "YOU WIN! 🏆" : "CPU WINS",
                     W / 2, H / 2 + 6);
      }
    };
    const score = () => setScore("You " + you + " — " + cpu + " CPU");
    const step = () => {
      ball.x += ball.vx; ball.y += ball.vy;
      if (ball.y < 6 || ball.y > H - 6) ball.vy *= -1;
      // the machine: tracks the ball with a human-ish lag
      const target = ball.y - PH / 2;
      ay += Math.max(-2.7, Math.min(2.7, target - ay));
      ay = Math.max(0, Math.min(H - PH, ay));
      if (ball.vx < 0 && ball.x - 5 <= 8 + PW && ball.x > 8 &&
          ball.y >= py && ball.y <= py + PH) {
        ball.vx = Math.min(7, -ball.vx * 1.06);
        ball.vy += (ball.y - (py + PH / 2)) / PH * 2.4;
      }
      if (ball.vx > 0 && ball.x + 5 >= W - 8 - PW && ball.x < W - 8 &&
          ball.y >= ay && ball.y <= ay + PH) {
        ball.vx = -Math.min(7, ball.vx * 1.06);
        ball.vy += (ball.y - (ay + PH / 2)) / PH * 2.4;
      }
      if (ball.x < -8 || ball.x > W + 8) {
        if (ball.x < 0) cpu++; else you++;
        score();
        if (you >= 7 || cpu >= 7) {
          over = true; draw();
          clearInterval(timer); timer = null;
          toggleBtn.textContent = "▶ Start";
          return;
        }
        serve(ball.x < 0 ? -1 : 1);
      }
      draw();
    };
    const move = dy => {
      py = Math.max(0, Math.min(H - PH, py + dy * 14));
      if (!timer && !over) draw();
    };
    const toggle = () => {
      if (over) { you = 0; cpu = 0; over = false; serve(1); score(); }
      if (timer) { clearInterval(timer); timer = null; toggleBtn.textContent = "▶ Start"; }
      else { timer = setInterval(step, 20); toggleBtn.textContent = "⏸ Pause"; }
    };
    dpad(stage, (dx, dy) => move(dy), []);
    const toggleBtn = document.createElement("button");
    toggleBtn.textContent = "▶ Start";
    toggleBtn.onclick = toggle;
    toggleBtn.style.cssText = "padding:10px 22px;border-radius:12px;font-size:15px;background:#EC4899;color:#121212;font-weight:700;";
    const wrap = document.createElement("div");
    wrap.className = "grow";
    wrap.appendChild(toggleBtn);
    stage.appendChild(wrap);
    let dragY = null;
    cv.addEventListener("touchstart", e => {
      dragY = e.touches[0].clientY;
    }, { passive: true });
    cv.addEventListener("touchmove", e => {
      const y = e.touches[0].clientY;
      if (dragY !== null) {
        py = Math.max(0, Math.min(H - PH, py + (y - dragY) * 1.6));
        if (!timer && !over) draw();
      }
      dragY = y;
    }, { passive: true });
    const keys = e => {
      if (e.key === "ArrowUp") { move(-1); e.preventDefault(); }
      if (e.key === "ArrowDown") { move(1); e.preventDefault(); }
    };
    document.addEventListener("keydown", keys);
    score(); draw();
    return () => {
      if (timer) clearInterval(timer);
      document.removeEventListener("keydown", keys);
    };
  },
});

// ---------------------------------------------------------- Space Invaders --
// Phase 47: the 1978 arcade legend — emoji invaders, auto-fire.
registerGame({
  id: "invaders", icon: '<svg viewBox="0 0 64 64"><rect x="2" y="2" width="60" height="60" rx="14" fill="#E4F7E8"/><g fill="#2FA84F"><rect x="22" y="12" width="20" height="6"/><rect x="16" y="18" width="32" height="6"/><rect x="12" y="24" width="40" height="6"/><rect x="18" y="30" width="10" height="6"/><rect x="36" y="30" width="10" height="6"/><rect x="14" y="36" width="8" height="6"/><rect x="42" y="36" width="8" height="6"/><rect x="20" y="42" width="6" height="6"/><rect x="38" y="42" width="6" height="6"/></g><circle cx="23" cy="27" r="2" fill="#fff"/><circle cx="41" cy="27" r="2" fill="#fff"/></svg>', name: "Invaders", title: "Space Invaders",
  desc: "The 1978 arcade legend. Blast the invaders before they land.",
  help: "Drag left/right to steer — your cannon fires on its own. 3 lives.",
  start(stage, setScore) {
    const W = 300, H = 330;
    const cv = document.createElement("canvas");
    cv.width = W; cv.height = H;
    stage.appendChild(cv);
    const ctx = cv.getContext("2d");
    let shipX, aliens, dirX, offY, shots, enemyShots, lives, score,
        wave, tick, timer = null, over = false;
    const reset = full => {
      shipX = W / 2;
      aliens = [];
      for (let r = 0; r < 4; r++)
        for (let c = 0; c < 5; c++)
          aliens.push({ x: 45 + c * 42, y: 38 + r * 30, alive: true });
      dirX = 0.55 + wave * 0.12; offY = 0;
      shots = []; enemyShots = []; tick = 0;
      if (full) { lives = 3; score = 0; wave = 1; over = false; }
      paint();
    };
    const paint = () => setScore(
      "Score: " + score + " · Lives: " + "❤️".repeat(Math.max(0, lives)) +
      " · Wave " + wave);
    const draw = () => {
      ctx.fillStyle = GX_CANVAS_BG;
      ctx.fillRect(0, 0, W, H);
      ctx.fillStyle = "#fff";
      for (let i = 0; i < 40; i++)
        ctx.fillRect((i * 67) % W, (i * 41) % H, 1.4, 1.4);
      ctx.font = "19px serif"; ctx.textAlign = "center";
      aliens.forEach(a => { if (a.alive) ctx.fillText("👾", a.x, a.y + offY); });
      ctx.fillStyle = "#4ADE80";
      ctx.beginPath();
      ctx.moveTo(shipX, H - 26); ctx.lineTo(shipX - 11, H - 8);
      ctx.lineTo(shipX + 11, H - 8); ctx.closePath(); ctx.fill();
      ctx.fillStyle = "#FFD166";
      shots.forEach(s => ctx.fillRect(s.x - 1.5, s.y, 3, 9));
      ctx.fillStyle = "#FF5C7A";
      enemyShots.forEach(s => ctx.fillRect(s.x - 1.5, s.y, 3, 9));
      if (over) {
        ctx.fillStyle = "rgba(12,33,21,.85)";
        ctx.fillRect(0, H / 2 - 26, W, 52);
        ctx.fillStyle = "#eef2c8"; ctx.font = "bold 17px monospace";
        ctx.fillText("GAME OVER", W / 2, H / 2 + 6);
      }
    };
    const step = () => {
      tick++;
      let edge = false;
      aliens.forEach(a => {
        if (!a.alive) return;
        a.x += dirX;
        if (a.x > W - 18 || a.x < 18) edge = true;
      });
      if (edge) { dirX *= -1; offY += 11; }
      if (tick % 16 === 0)
        shots.push({ x: shipX, y: H - 30 });
      shots = shots.filter(s => s.y > -10);
      shots.forEach(s => { s.y -= 6; });
      if (tick % 34 === 0) {
        const alive = aliens.filter(a => a.alive);
        if (alive.length) {
          const a = alive[(Math.random() * alive.length) | 0];
          enemyShots.push({ x: a.x, y: a.y + offY + 8 });
        }
      }
      enemyShots = enemyShots.filter(s => s.y < H);
      enemyShots.forEach(s => { s.y += 3.4; });
      // hits on invaders
      shots.forEach(s => {
        aliens.forEach(a => {
          if (a.alive && Math.abs(s.x - a.x) < 12 &&
              Math.abs(s.y - (a.y + offY)) < 11) {
            a.alive = false; s.y = -99; score += 10; paint();
          }
        });
      });
      // hits on the ship
      enemyShots.forEach(s => {
        if (Math.abs(s.x - shipX) < 11 && s.y > H - 28 && s.y < H - 4) {
          s.y = H + 99; lives--; paint();
          if (lives <= 0) { over = true; }
        }
      });
      const landed = aliens.some(a => a.alive && a.y + offY > H - 40);
      if (landed) over = true;
      if (aliens.every(a => !a.alive)) {
        wave++; reset(false); paint();
      }
      draw();
      if (over) {
        clearInterval(timer); timer = null;
        toggleBtn.textContent = "▶ Start";
        setScore("Game over — Score: " + score);
      }
    };
    const steer = dx => {
      shipX = Math.max(14, Math.min(W - 14, shipX + dx));
      if (!timer && !over) draw();
    };
    const toggle = () => {
      if (over) reset(true);
      if (timer) { clearInterval(timer); timer = null; toggleBtn.textContent = "▶ Start"; }
      else { timer = setInterval(step, 30); toggleBtn.textContent = "⏸ Pause"; }
    };
    dpad(stage, dx => steer(dx * 12), []);
    const toggleBtn = document.createElement("button");
    toggleBtn.textContent = "▶ Start";
    toggleBtn.onclick = toggle;
    toggleBtn.style.cssText = "padding:10px 22px;border-radius:12px;font-size:15px;background:#EC4899;color:#121212;font-weight:700;";
    const wrap = document.createElement("div");
    wrap.className = "grow";
    wrap.appendChild(toggleBtn);
    stage.appendChild(wrap);
    let lastX = null;
    cv.addEventListener("touchstart", e => {
      lastX = e.touches[0].clientX;
    }, { passive: true });
    cv.addEventListener("touchmove", e => {
      const x = e.touches[0].clientX;
      if (lastX !== null) steer((x - lastX) * 1.4);
      lastX = x;
    }, { passive: true });
    const keys = e => {
      if (e.key === "ArrowLeft") steer(-12);
      if (e.key === "ArrowRight") steer(12);
    };
    document.addEventListener("keydown", keys);
    wave = 1; reset(true);
    return () => {
      if (timer) clearInterval(timer);
      document.removeEventListener("keydown", keys);
    };
  },
});

// ------------------------------------------------------------ Minesweeper --
// Phase 47: the classic desktop mine-hunt.
registerGame({
  id: "mines", icon: '<svg viewBox="0 0 64 64"><rect x="2" y="2" width="60" height="60" rx="14" fill="#EDEFF3"/><g fill="#fff" stroke="#B9C2CC" stroke-width="1.5"><rect x="12" y="12" width="13" height="13"/><rect x="25" y="12" width="13" height="13"/><rect x="38" y="12" width="13" height="13"/><rect x="12" y="25" width="13" height="13"/><rect x="25" y="25" width="13" height="13"/><rect x="38" y="25" width="13" height="13"/><rect x="12" y="38" width="13" height="13"/><rect x="25" y="38" width="13" height="13"/><rect x="38" y="38" width="13" height="13"/></g><circle cx="31.5" cy="31.5" r="7" fill="#1F2937"/><rect x="29" y="20" width="5" height="6" fill="#1F2937"/><path d="M31.5 20 L35 15 M31.5 20 L39 17 M31.5 20 L25 14" stroke="#1F2937" stroke-width="2" stroke-linecap="round"/><circle cx="29" cy="29" r="2" fill="#fff"/></svg>', name: "Minesweeper", title: "Minesweeper",
  desc: "The classic desktop mine-hunt. Clear the field, dodge the bombs.",
  help: "Tap to dig. Turn flag mode on to mark a mine with 🚩. First tap is always safe.",
  start(stage, setScore) {
    const N = 9, MINES = 10;
    const COLORS = ["", "#2563EB", "#16A34A", "#DC2626", "#7C3AED",
                    "#B45309", "#0891B2", "#111827", "#4B5563"];
    const grid = document.createElement("div");
    grid.className = "mine-grid";
    stage.appendChild(grid);
    let mines, open, flags, started, dead, won, flagMode = false;
    const cells = [];
    const idx = (x, y) => y * N + x;
    const around = (x, y) => {
      const out = [];
      for (let dy = -1; dy <= 1; dy++)
        for (let dx = -1; dx <= 1; dx++) {
          const nx = x + dx, ny = y + dy;
          if ((dx || dy) && nx >= 0 && ny >= 0 && nx < N && ny < N)
            out.push([nx, ny]);
        }
      return out;
    };
    const count = (x, y) =>
      around(x, y).filter(([nx, ny]) => mines.has(idx(nx, ny))).length;
    function status() {
      if (won) setScore("You cleared the field! 🏆");
      else if (dead) setScore("Boom! 💥 Game over.");
      else setScore("🚩 " + (MINES - flags.size) + " mines left to mark");
    }
    function plant(safeIdx) {
      mines = new Set();
      while (mines.size < MINES) {
        const m = (Math.random() * N * N) | 0;
        if (m !== safeIdx) mines.add(m);
      }
    }
    function reveal(x, y) {
      const i = idx(x, y);
      if (open.has(i) || flags.has(i) || dead || won) return;
      if (!started) { plant(i); started = true; }
      if (mines.has(i)) {
        dead = true;
        mines.forEach(m => {
          cells[m].textContent = "💣";
          cells[m].classList.add("mine-hit");
        });
        cells[i].textContent = "💥";
        status();
        return;
      }
      const stack = [[x, y]];
      while (stack.length) {
        const [cx, cy] = stack.pop();
        const ci = idx(cx, cy);
        if (open.has(ci) || flags.has(ci)) continue;
        open.add(ci);
        const n = count(cx, cy);
        const cell = cells[ci];
        cell.classList.add("mine-open");
        if (n) {
          cell.textContent = n;
          cell.style.color = COLORS[n];
        } else {
          around(cx, cy).forEach(([nx, ny]) => {
            if (!open.has(idx(nx, ny))) stack.push([nx, ny]);
          });
        }
      }
      if (open.size === N * N - MINES) { won = true; }
      status();
    }
    function build() {
      grid.innerHTML = "";
      cells.length = 0;
      mines = new Set(); open = new Set(); flags = new Set();
      started = false; dead = false; won = false;
      for (let y = 0; y < N; y++)
        for (let x = 0; x < N; x++) {
          const b = document.createElement("button");
          b.className = "mine-cell";
          b.onclick = () => {
            const i = idx(x, y);
            if (dead || won) return;
            if (flagMode) {
              if (open.has(i)) return;
              if (flags.has(i)) { flags.delete(i); b.textContent = ""; }
              else { flags.add(i); b.textContent = "🚩"; }
              status();
            } else reveal(x, y);
          };
          cells.push(b);
          grid.appendChild(b);
        }
      status();
    }
    const row = document.createElement("div");
    row.className = "grow";
    const flagBtn = document.createElement("button");
    flagBtn.textContent = "🚩 Flag: Off";
    flagBtn.onclick = () => {
      flagMode = !flagMode;
      flagBtn.textContent = "🚩 Flag: " + (flagMode ? "On" : "Off");
    };
    const again = document.createElement("button");
    again.textContent = "↻ New game";
    again.onclick = build;
    row.append(flagBtn, again);
    stage.appendChild(row);
    build();
    return () => {};
  },
});

// --------------------------------------------------------------- Flappy --
// Phase 52 (owner: more games): the 2013 one-tap legend.
registerGame({
  id: "flappy", icon: '<svg viewBox="0 0 64 64"><rect x="2" y="2" width="60" height="60" rx="14" fill="#CFEFFF"/><rect x="42" y="4" width="14" height="20" fill="#2FA84F"/><rect x="40" y="20" width="18" height="6" fill="#2FA84F"/><rect x="42" y="40" width="14" height="20" fill="#2FA84F"/><rect x="40" y="38" width="18" height="6" fill="#2FA84F"/><circle cx="24" cy="32" r="11" fill="#FFC53D"/><circle cx="28" cy="28" r="3" fill="#fff"/><circle cx="29" cy="28" r="1.5" fill="#1F2937"/><path d="M34 32 l6 2 -6 3z" fill="#E8833A"/><path d="M16 34 q6 6 12 2" stroke="#E8A33D" stroke-width="3" fill="none" stroke-linecap="round"/></svg>', name: "Flappy", title: "Flappy Bird",
  desc: "The one-tap legend. Flap through the pipes, don't clip one.",
  help: "Tap the sky (or press Space) to flap. One touch is all it takes — and all it forgives.",
  start(stage, setScore) {
    const W = 300, H = 340, GY = H - 34;
    const cv = document.createElement("canvas");
    cv.width = W; cv.height = H;
    stage.appendChild(cv);
    const ctx = cv.getContext("2d");
    let y, vy, pipes, score, tick, timer = null, state = "ready";
    const reset = () => {
      y = H / 2; vy = 0; pipes = []; score = 0; tick = 0;
      state = "ready"; draw(); setScore("Score: 0");
    };
    const draw = () => {
      ctx.fillStyle = "#8ED6F2";
      ctx.fillRect(0, 0, W, H);
      ctx.fillStyle = "#AEE7FB";
      ctx.beginPath();
      ctx.arc(52, 52, 21, 0, 7); ctx.arc(76, 46, 26, 0, 7);
      ctx.arc(240, 74, 18, 0, 7); ctx.arc(260, 68, 22, 0, 7);
      ctx.fill();
      pipes.forEach(p => {
        ctx.fillStyle = "#3FA34D";
        ctx.fillRect(p.x, 0, 54, p.top);
        ctx.fillRect(p.x, p.top + 108, 54, GY - p.top - 108);
        ctx.fillStyle = "#2F7D3B";
        ctx.fillRect(p.x - 3, p.top - 18, 60, 18);
        ctx.fillRect(p.x - 3, p.top + 108, 60, 18);
      });
      ctx.fillStyle = "#7BC96F";
      ctx.fillRect(0, GY, W, H - GY);
      ctx.fillStyle = "#5DA851";
      ctx.fillRect(0, GY, W, 5);
      // the bird: body, wing, eye, beak
      ctx.fillStyle = "#FFD93D";
      ctx.beginPath(); ctx.arc(70, y, 15, 0, 7); ctx.fill();
      ctx.fillStyle = "#F4A259";
      ctx.beginPath();
      ctx.ellipse(63, y + 3, 8, 5, -0.5, 0, 7); ctx.fill();
      ctx.fillStyle = "#fff";
      ctx.beginPath(); ctx.arc(76, y - 5, 5.5, 0, 7); ctx.fill();
      ctx.fillStyle = "#222";
      ctx.beginPath(); ctx.arc(77.5, y - 5, 2.6, 0, 7); ctx.fill();
      ctx.fillStyle = "#FF7B54";
      ctx.beginPath();
      ctx.moveTo(83, y - 1); ctx.lineTo(93, y + 2); ctx.lineTo(83, y + 5);
      ctx.closePath(); ctx.fill();
      ctx.fillStyle = "#fff";
      ctx.font = "bold 26px monospace"; ctx.textAlign = "center";
      ctx.fillText(score, W / 2, 52);
      if (state !== "play") {
        ctx.fillStyle = "rgba(10, 30, 46, .55)";
        ctx.fillRect(0, H / 2 - 24, W, 48);
        ctx.fillStyle = "#fff"; ctx.font = "bold 16px monospace";
        ctx.fillText(state === "ready" ? "TAP TO FLAP" : "GAME OVER",
                     W / 2, H / 2 + 6);
      }
    };
    const die = () => {
      state = "dead";
      clearInterval(timer); timer = null;
      toggleBtn.textContent = "▶ Start";
      setScore("Game over — Score: " + score);
      draw();
    };
    const step = () => {
      tick++;
      vy = Math.min(9.5, vy + 0.45);
      y += vy;
      if (tick % 88 === 0)
        pipes.push({ x: W + 8, top: 36 + Math.random() * (GY - 190),
                     passed: false });
      pipes.forEach(p => { p.x -= 2.3; });
      pipes = pipes.filter(p => p.x > -60);
      for (const p of pipes) {
        if (!p.passed && p.x + 54 < 70 - 15) {
          p.passed = true; score++;
          setScore("Score: " + score);
        }
        if (70 + 13 > p.x && 70 - 13 < p.x + 54 &&
            (y - 13 < p.top || y + 13 > p.top + 108)) return die();
      }
      if (y + 15 >= GY || y - 15 <= 0) return die();
      draw();
    };
    const flap = () => {
      if (state === "dead") return;
      if (state === "ready") {
        state = "play";
        timer = setInterval(step, 20);
        toggleBtn.textContent = "⏸ Pause";
      }
      vy = -7.4;
    };
    const toggle = () => {
      if (state === "dead" || !timer && state === "ready" && pipes.length === 0 && score === 0) {
        reset(); flap(); return;
      }
      if (timer) {
        clearInterval(timer); timer = null;
        toggleBtn.textContent = "▶ Start";
      } else if (state === "play") {
        timer = setInterval(step, 20);
        toggleBtn.textContent = "⏸ Pause";
      } else flap();
    };
    const toggleBtn = document.createElement("button");
    toggleBtn.textContent = "▶ Start";
    toggleBtn.onclick = toggle;
    toggleBtn.style.cssText = "padding:10px 22px;border-radius:12px;font-size:15px;background:#EC4899;color:#121212;font-weight:700;";
    const wrap = document.createElement("div");
    wrap.className = "grow";
    wrap.appendChild(toggleBtn);
    stage.appendChild(wrap);
    cv.addEventListener("pointerdown", e => {
      e.preventDefault(); flap();
    });
    const keys = e => {
      if (e.code === "Space" || e.key === "ArrowUp") {
        flap(); e.preventDefault();
      }
    };
    document.addEventListener("keydown", keys);
    reset();
    return () => {
      if (timer) clearInterval(timer);
      document.removeEventListener("keydown", keys);
    };
  },
});

// ----------------------------------------------------------------- 2048 --
// Phase 52: the sliding-tile puzzle everyone lost hours to.
registerGame({
  id: "g2048", icon: '<svg viewBox="0 0 64 64"><rect x="2" y="2" width="60" height="60" rx="14" fill="#F7EEDD"/><g font-family="Arial, sans-serif" font-weight="800" text-anchor="middle"><rect x="10" y="10" width="20" height="20" rx="4" fill="#EEE4DA"/><text x="20" y="25" font-size="13" fill="#776E65">2</text><rect x="34" y="10" width="20" height="20" rx="4" fill="#EDE0C8"/><text x="44" y="25" font-size="13" fill="#776E65">4</text><rect x="10" y="34" width="20" height="20" rx="4" fill="#F2B179"/><text x="20" y="49" font-size="13" fill="#fff">8</text><rect x="34" y="34" width="20" height="20" rx="4" fill="#F59563"/><text x="44" y="49" font-size="13" fill="#fff">16</text></g></svg>', name: "2048", title: "2048",
  desc: "Slide the tiles, merge the numbers, chase the 2048 tile.",
  help: "Swipe on the board, use the arrow pad, or the arrow keys.",
  start(stage, setScore) {
    const TILE = { 0: "#EFE3EC", 2: "#FBEFF5", 4: "#FADCEC",
      8: "#F7A8C4", 16: "#F27FB0", 32: "#EC4899", 64: "#DB2777",
      128: "#F6C453", 256: "#F0B429", 512: "#DE911D",
      1024: "#C77414", 2048: "#9A3412" };
    const grid = document.createElement("div");
    grid.className = "g2048-grid";
    stage.appendChild(grid);
    const cells = [];
    for (let i = 0; i < 16; i++) {
      const c = document.createElement("div");
      c.className = "g2048-cell";
      cells.push(c); grid.appendChild(c);
    }
    let board, score, over, won;
    const spawn = () => {
      const free = board.map((v, i) => v ? -1 : i).filter(i => i >= 0);
      if (!free.length) return;
      board[free[(Math.random() * free.length) | 0]] =
        Math.random() < 0.9 ? 2 : 4;
    };
    const draw = () => {
      board.forEach((v, i) => {
        cells[i].textContent = v || "";
        cells[i].style.background = TILE[v] || "#9A3412";
        cells[i].style.color = v >= 8 ? "#fff" : "#472A3E";
        cells[i].style.fontSize = v >= 1000 ? "15px" :
          v >= 100 ? "18px" : "21px";
      });
      setScore(over ? "No moves left — Score: " + score :
               (won ? "🎉 2048! Keep going — Score: " + score :
                      "Score: " + score));
    };
    const line = (a, b, c, d) => {
      const vals = [board[a], board[b], board[c], board[d]]
        .filter(v => v);
      const out = [];
      for (let i = 0; i < vals.length; i++) {
        if (vals[i] === vals[i + 1]) {
          out.push(vals[i] * 2);
          score += vals[i] * 2;
          if (vals[i] * 2 === 2048) won = true;
          i++;
        } else out.push(vals[i]);
      }
      while (out.length < 4) out.push(0);
      return out;
    };
    const move = (dx, dy) => {
      if (over) return;
      const before = board.join(",");
      for (let k = 0; k < 4; k++) {
        // idxs run from the edge the tiles move TOWARD, and
        // line() compacts toward its first cell.
        let idxs;
        if (dx === -1) idxs = [k * 4, k * 4 + 1, k * 4 + 2, k * 4 + 3];
        else if (dx === 1) idxs = [k * 4 + 3, k * 4 + 2, k * 4 + 1, k * 4];
        else if (dy === -1) idxs = [k, 4 + k, 8 + k, 12 + k];
        else idxs = [12 + k, 8 + k, 4 + k, k];
        const merged = line(idxs[0], idxs[1], idxs[2], idxs[3]);
        idxs.forEach((cell, j) => { board[cell] = merged[j]; });
      }
      if (board.join(",") === before) return;
      spawn();
      over = !board.includes(0) &&
        ![0, 1, 2, 3].some(k =>
          [0, 1, 2].some(j =>
            board[k * 4 + j] === board[k * 4 + j + 1] ||
            board[j * 4 + k] === board[(j + 1) * 4 + k]));
      draw();
    };
    const reset = () => {
      board = Array(16).fill(0);
      score = 0; over = false; won = false;
      spawn(); spawn(); draw();
    };
    dpad(stage, move, []);
    const again = document.createElement("button");
    again.textContent = "↻ New game";
    again.onclick = reset;
    const wrap = document.createElement("div");
    wrap.className = "grow";
    wrap.appendChild(again);
    stage.appendChild(wrap);
    swipe(grid, move);
    const keys = e => {
      const k = { ArrowUp: [0, -1], ArrowDown: [0, 1],
                  ArrowLeft: [-1, 0], ArrowRight: [1, 0] }[e.key];
      if (k) { move(k[0], k[1]); e.preventDefault(); }
    };
    document.addEventListener("keydown", keys);
    reset();
    return () => document.removeEventListener("keydown", keys);
  },
});

// -------------------------------------------------------------- Pac-Man --
// Phase 52: the 1980 maze legend — dots, two ghosts, three lives.
registerGame({
  id: "pacman", icon: '<svg viewBox="0 0 64 64"><rect x="2" y="2" width="60" height="60" rx="14" fill="#232946"/><path d="M32 32 L50 19 A22 22 0 1 0 50 45 Z" fill="#FFD93D"/><circle cx="36" cy="20" r="2.5" fill="#232946"/><circle cx="56" cy="14" r="2" fill="#FFD93D"/><circle cx="56" cy="32" r="2" fill="#FFD93D"/><circle cx="56" cy="50" r="2" fill="#FFD93D"/></svg>', name: "Pac-Man", title: "Pac-Man",
  desc: "The 1980 maze legend. Eat every dot — the ghosts are hungry too.",
  help: "Swipe, use the arrow pad, or the arrow keys to steer.",
  start(stage, setScore) {
    const MAP = [
      "###############",
      "#.....#.......#",
      "#.##..#..##.#.#",
      "#.............#",
      "#.##.#####.##.#",
      "#......#......#",
      "####.#.###.####",
      "#......#......#",
      "#.##.#####.##.#",
      "#.............#",
      "#.##.#.#.#.##.#",
      "#.....#.......#",
      "###############",
    ];
    const COLS = 15, ROWS = 13, T = 20;
    const cv = document.createElement("canvas");
    cv.width = COLS * T; cv.height = ROWS * T;
    stage.appendChild(cv);
    const ctx = cv.getContext("2d");
    let walls, dots, pac, ghosts, lives, score, level, tick,
        timer = null, over = false;
    const wall = (x, y) => walls.has(y * COLS + x);
    const reset = full => {
      walls = new Set(); dots = new Set();
      MAP.forEach((row, y) => row.split("").forEach((ch, x) => {
        if (ch === "#") walls.add(y * COLS + x);
        else dots.add(y * COLS + x);
      }));
      pac = { x: 7, y: 9, dx: -1, dy: 0, nx: -1, ny: 0 };
      dots.delete(9 * COLS + 7);
      ghosts = [
        { x: 6, y: 5, dx: 1, dy: 0, color: "#FF5C5C" },
        { x: 8, y: 5, dx: -1, dy: 0, color: "#FF9DE2" },
      ];
      tick = 0;
      if (full) { lives = 3; score = 0; level = 1; over = false; }
      paint();
    };
    const paint = () => setScore(
      "Score: " + score + " · Lives: " + "❤️".repeat(Math.max(0, lives)) +
      " · Level " + level);
    const draw = () => {
      ctx.fillStyle = GX_CANVAS_BG;
      ctx.fillRect(0, 0, cv.width, cv.height);
      ctx.fillStyle = "#2B3A8F";
      walls.forEach(i => {
        const x = (i % COLS) * T, y = ((i / COLS) | 0) * T;
        ctx.fillRect(x + 1.5, y + 1.5, T - 3, T - 3);
      });
      ctx.fillStyle = "#FFE9A8";
      dots.forEach(i => {
        ctx.beginPath();
        ctx.arc((i % COLS) * T + T / 2, ((i / COLS) | 0) * T + T / 2,
                2.6, 0, 7);
        ctx.fill();
      });
      ghosts.forEach(g => {
        const gx = g.x * T, gy = g.y * T;
        ctx.fillStyle = g.color;
        ctx.beginPath();
        ctx.arc(gx + T / 2, gy + T / 2 + 1, 8, Math.PI, 0);
        ctx.rect(gx + 2, gy + T / 2 + 1, T - 4, 7);
        ctx.fill();
        ctx.fillStyle = "#fff";
        ctx.beginPath();
        ctx.arc(gx + 7, gy + 9, 2.6, 0, 7);
        ctx.arc(gx + 13, gy + 9, 2.6, 0, 7);
        ctx.fill();
      });
      const px = pac.x * T + T / 2, py = pac.y * T + T / 2;
      const ang = Math.atan2(pac.dy, pac.dx);
      const mouth = (tick % 2 === 0) ? 0.28 : 0.05;
      ctx.fillStyle = "#FFD93D";
      ctx.beginPath();
      ctx.moveTo(px, py);
      ctx.arc(px, py, 8.5, ang + mouth * Math.PI,
              ang + (2 - mouth) * Math.PI);
      ctx.closePath(); ctx.fill();
      if (over) {
        ctx.fillStyle = "rgba(12,33,21,.85)";
        ctx.fillRect(0, cv.height / 2 - 24, cv.width, 48);
        ctx.fillStyle = "#eef2c8";
        ctx.font = "bold 16px monospace"; ctx.textAlign = "center";
        ctx.fillText("GAME OVER", cv.width / 2, cv.height / 2 + 6);
      }
    };
    const step = () => {
      tick++;
      if (!wall(pac.x + pac.nx, pac.y + pac.ny)) {
        pac.dx = pac.nx; pac.dy = pac.ny;
      }
      if (!wall(pac.x + pac.dx, pac.y + pac.dy)) {
        pac.x += pac.dx; pac.y += pac.dy;
      }
      const pi = pac.y * COLS + pac.x;
      if (dots.has(pi)) { dots.delete(pi); score += 10; paint(); }
      ghosts.forEach(g => {
        const opts = [[1, 0], [-1, 0], [0, 1], [0, -1]].filter(
          ([dx, dy]) => !wall(g.x + dx, g.y + dy) &&
                        !(dx === -g.dx && dy === -g.dy));
        if (!opts.length) { g.dx *= -1; g.dy *= -1; }
        else {
          opts.sort((a, b) => {
            const da = Math.abs(g.x + a[0] - pac.x) +
                       Math.abs(g.y + a[1] - pac.y);
            const db = Math.abs(g.x + b[0] - pac.x) +
                       Math.abs(g.y + b[1] - pac.y);
            return da - db;
          });
          const pick = Math.random() < 0.62 ? opts[0] :
            opts[(Math.random() * opts.length) | 0];
          g.dx = pick[0]; g.dy = pick[1];
        }
        g.x += g.dx; g.y += g.dy;
      });
      if (ghosts.some(g => g.x === pac.x && g.y === pac.y)) {
        lives--; paint();
        if (lives <= 0) {
          over = true; draw();
          clearInterval(timer); timer = null;
          toggleBtn.textContent = "▶ Start";
          setScore("Game over — Score: " + score);
          return;
        }
        pac = { x: 7, y: 9, dx: -1, dy: 0, nx: -1, ny: 0 };
        ghosts.forEach((g, i) => {
          g.x = i ? 8 : 6; g.y = 5;
        });
      }
      if (!dots.size) {
        level++;
        const keepScore = score, keepLives = lives;
        reset(false);
        score = keepScore; lives = keepLives;
        paint();
        restartTimer();
      }
      draw();
    };
    const restartTimer = () => {
      if (timer) clearInterval(timer);
      timer = setInterval(step, Math.max(95, 150 - level * 9));
    };
    const steer = (dx, dy) => { pac.nx = dx; pac.ny = dy; };
    const toggle = () => {
      if (over) reset(true);
      if (timer) {
        clearInterval(timer); timer = null;
        toggleBtn.textContent = "▶ Start";
      } else {
        restartTimer();
        toggleBtn.textContent = "⏸ Pause";
      }
    };
    dpad(stage, steer, []);
    const toggleBtn = document.createElement("button");
    toggleBtn.textContent = "▶ Start";
    toggleBtn.onclick = toggle;
    toggleBtn.style.cssText = "padding:10px 22px;border-radius:12px;font-size:15px;background:#EC4899;color:#121212;font-weight:700;";
    const wrap = document.createElement("div");
    wrap.className = "grow";
    wrap.appendChild(toggleBtn);
    stage.appendChild(wrap);
    swipe(cv, steer);
    const keys = e => {
      const k = { ArrowUp: [0, -1], ArrowDown: [0, 1],
                  ArrowLeft: [-1, 0], ArrowRight: [1, 0] }[e.key];
      if (k) { steer(k[0], k[1]); e.preventDefault(); }
    };
    document.addEventListener("keydown", keys);
    reset(true);
    draw();
    return () => {
      if (timer) clearInterval(timer);
      document.removeEventListener("keydown", keys);
    };
  },
});

// ------------------------------------------------------------- game grid --
// --------------------------------------------------------------- Archery --
// Phase 88 (owner, from the screenshot he shared): the
// overthinker is still aiming — the doer is already shooting.
// Phase 89 (owner): make it prettier, give it LEVELS that get
// harder step by step, and design each level change so the
// player can SEE it is a new level — every level wears its own
// sky, opens with a big LEVEL card naming what is new, and the
// difficulty (bars, target, wind) is table-driven per level.
registerGame({
  id: "archery", icon: '<svg viewBox="0 0 64 64"><rect x="2" y="2" width="60" height="60" rx="14" fill="#FDE8E8"/><circle cx="29" cy="34" r="20" fill="#fff" stroke="#E5E7EB" stroke-width="2"/><circle cx="29" cy="34" r="15" fill="#E5484D"/><circle cx="29" cy="34" r="10" fill="#fff"/><circle cx="29" cy="34" r="5" fill="#E5484D"/><line x1="29" y1="34" x2="54" y2="12" stroke="#8B5E34" stroke-width="3" stroke-linecap="round"/><path d="M54 12 l-8 1 M54 12 l-1 8" stroke="#8B5E34" stroke-width="2.5" fill="none" stroke-linecap="round"/></svg>', name: "Archery",
  title: "Archery — Aim Less, Shoot More",
  desc: "Level by level, sky by sky: thread the moving bars, hit SUCCESS, climb.",
  help: "Drag to aim — the dotted line previews your shot. Release to loose. Solo is a level climb: score the quota in 10 arrows to advance. Bars speed up, multiply, the target shrinks, starts moving, and wind joins in. 2 Players: 6 arrows each on one phone. Invite: a challenge message to a friend.",
  start(stage, setScore) {
    const W = 340, H = 460, GY = H - 44;
    const cv = document.createElement("canvas");
    cv.width = W; cv.height = H;
    cv.style.touchAction = "none";
    stage.appendChild(cv);
    const ctx = cv.getContext("2d");
    const TGT = { x: 252, y: 96, r: 46 };
    const TGT_Y = 96;
    const HAND = { x: 64, y: GY - 60 };
    const PCOL = ["#FFFFFF", "#58B0E6"];
    const THEMES = [
      { name: "Night Range", top: "#0B0B0E", bot: "#1A1A28", hill: "#0D0D14", stars: true },
      { name: "Dawn Ridge", top: "#1B2340", bot: "#51386B", hill: "#120E24", stars: true },
      { name: "Ember Dusk", top: "#2A1428", bot: "#7A3038", hill: "#180B18", stars: false },
      { name: "Meadow Dark", top: "#0C241C", bot: "#22573E", hill: "#07170F", stars: false },
      { name: "Storm Field", top: "#141C26", bot: "#3A5A68", hill: "#0B131B", stars: false },
      { name: "Moonlight", top: "#0A1030", bot: "#2C3C7A", hill: "#090D22", stars: true },
    ];
    const NEW_AT = { 2: "The bars move faster", 3: "One more bar!",
      4: "The target moves!", 5: "Faster bars, smaller target",
      6: "Wind joins the game 💨", 7: "One more bar!",
      8: "The wind picks up", 9: "One more bar!",
      10: "Everything is faster now" };
    function levelCfg(n) {
      const spMul = Math.min(2.2, 1 + (n - 1) * 0.14);
      const count = Math.min(5, 3 + Math.floor((n - 1) / 2));
      const w = n >= 4 ? 84 : 70;
      const base = [
        { y: 180, x: 150, v: -0.7 }, { y: 232, x: 40, v: 0.9 },
        { y: 282, x: 196, v: -1.1 }, { y: 148, x: 60, v: 1.2 },
        { y: 258, x: 236, v: -1.45 },
      ].slice(0, count).map(bb => ({ y: bb.y, x: bb.x, w, v: bb.v * spMul }));
      return {
        quota: Math.min(240, 50 + (n - 1) * 20),
        bars: base,
        tgtR: Math.max(30, 46 - (n - 1) * 2),
        moveAmp: n >= 4 ? Math.min(34, 8 + (n - 4) * 5) : 0,
        moveSp: 0.55 + Math.max(0, n - 4) * 0.09,
        wind: n >= 6 ? (n % 2 ? 1 : -1) *
          Math.min(0.055, 0.02 + (n - 6) * 0.008) : 0,
      };
    }
    let bars = [], arrow = null, stuck = [], aim = null;
    let parts = [];                        // confetti / hit sparks
    let scores = [0, 0], shots = [0, 0], turn = 0;
    let mode = "solo", state = "intro", note = "", noteT = 0;
    let frame = 0, raf = 0, dead = false;
    let level = 1, cfg = levelCfg(1), banked = 0;
    let best = +(nxGet("nx_archery_best") || 0);
    let bestLevel = +(nxGet("nx_archery_level") || 1);
    // Phase 94 (owner: "যে লেভেলে রেখে আসবো সেখান থেকে পরে
    // আসে না কেনো"): bestLevel above is only a display
    // record — the run itself always restarted at Level 1.
    // Now the solo run is saved as {level, banked} and
    // RESUMED on open; a 🆕 New run button starts over.
    let resumed = false;
    const loadRun = () => {
      try {
        const r = JSON.parse(nxGet("nx_archery_run") || "null");
        return r && r.level >= 1 ? r : null;
      } catch (e) { return null; }
    };
    const saveRun = (lv, bk) => {
      if (mode !== "solo") return;
      try {
        nxSet("nx_archery_run",
          JSON.stringify({ level: lv, banked: bk }));
      } catch (e) { /* storage full/blocked: play on */ }
    };
    const theme = () => THEMES[(level - 1) % THEMES.length];
    const perPlayer = () => (mode === "solo" ? 10 : 6);
    const leftFor = p => perPlayer() - shots[p];

    function startLevel(n, keepBanked) {
      level = n; cfg = levelCfg(n);
      if (!keepBanked) banked = 0;
      TGT.r = cfg.tgtR; TGT.y = TGT_Y;
      bars = cfg.bars.map(bb => ({ ...bb }));
      arrow = null; stuck = []; aim = null; parts = [];
      scores = [0, 0]; shots = [0, 0]; turn = 0;
      state = mode === "solo" ? "intro" : "aim";
      note = ""; noteT = 0;
      if (n > bestLevel) {
        bestLevel = n;
        nxSet("nx_archery_level", bestLevel);
      }
      saveRun(level, banked);
      showScore();
    }
    const reset = () => (mode === "solo" ? startSolo()
                                         : startLevel(1, false));
    function showScore() {
      if (mode === "solo")
        setScore("🏹 Level " + level + " · " + scores[0] + "/" +
          cfg.quota + " · Arrows: " + leftFor(0) +
          " · Total: " + (banked + scores[0]));
      else
        setScore("P1 " + scores[0] + " · P2 " + scores[1] +
          (state === "over" ? " · Finished" :
            " · Player " + (turn + 1) + " · Arrows: " + leftFor(turn)));
    }
    const burst = (x, y, cols, n) => {
      for (let i = 0; i < n; i++)
        parts.push({ x, y, vx: (Math.random() - 0.5) * 4.4,
          vy: -Math.random() * 3.6 - 0.6, life: 46 + Math.random() * 26,
          c: cols[i % cols.length], s: 2 + Math.random() * 3 });
    };
    const finishShot = (pts, msg) => {
      scores[turn] += pts;
      shots[turn] += 1;
      note = msg; noteT = 55; state = "show";
      if (arrow) {
        if (pts > 0)
          burst(arrow.x, arrow.y, ["#FFD93D", "#58B0E6", "#FFFFFF"], 16);
        stuck.push(arrow); arrow = null;
      }
      if (stuck.length > 14) stuck.shift();
      showScore();
      return true;
    };
    const advance = () => {
      if (mode === "solo") {
        if (shots[0] < perPlayer()) { state = "aim"; showScore(); return; }
        if (scores[0] >= cfg.quota) {
          banked += scores[0];
          if (banked > best) {
            best = banked;
            nxSet("nx_archery_best", best);
          }
          burst(TGT.x, TGT.y, ["#FFD93D", "#58B0E6", "#7BE0A3", "#FFFFFF"], 70);
          state = "clear"; noteT = 110;
          saveRun(level + 1, banked);
        } else {
          if (banked + scores[0] > best) {
            best = banked + scores[0];
            nxSet("nx_archery_best", best);
          }
          state = "fail";
        }
      } else {
        const other = 1 - turn;
        if (shots[other] < perPlayer()) turn = other;
        state = shots[0] >= perPlayer() && shots[1] >= perPlayer()
          ? "over" : "aim";
      }
      showScore();
    };
    // The target is a board standing at x = TGT.x: the arrow
    // scores where it crosses that plane, by height from the
    // centre — not at the rim, where every shot would land.
    const planeHit = () => {
      if (!(arrow.px < TGT.x && arrow.x >= TGT.x)) return false;
      const t = (TGT.x - arrow.px) / (arrow.x - arrow.px);
      const yc = arrow.py + (arrow.y - arrow.py) * t;
      const dy = Math.abs(yc - TGT.y);
      if (dy > TGT.r) return false;
      arrow.x = TGT.x; arrow.y = yc;
      if (dy <= TGT.r * 0.33) return finishShot(50, "🎯 BULLSEYE! +50");
      if (dy <= TGT.r * 0.65) return finishShot(25, "Great shot! +25");
      return finishShot(10, "On target! +10");
    };
    const resolveHit = () => {
      for (const b of bars)
        if (arrow.x >= b.x && arrow.x <= b.x + b.w &&
            arrow.y >= b.y - 4 && arrow.y <= b.y + 11)
          return finishShot(0, "Blocked by a bar!");
      if (arrow.y >= GY) return finishShot(0, "Into the ground.");
      if (arrow.x > W + 12 || arrow.x < -12 || arrow.y < -24)
        return finishShot(0, "Missed — it flew away.");
      return false;
    };
    const drawArcher = (ang) => {
      const col = PCOL[turn];
      ctx.strokeStyle = col; ctx.fillStyle = col;
      ctx.lineWidth = 4; ctx.lineCap = "round";
      const bx = 52, by = GY;
      ctx.beginPath();
      ctx.moveTo(bx, by - 34);
      ctx.lineTo(bx - 9, by); ctx.moveTo(bx, by - 34);
      ctx.lineTo(bx + 11, by);
      ctx.moveTo(bx, by - 34);
      ctx.lineTo(bx + 3, by - 62);
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(bx + 5, by - 70, 8, 0, 7); ctx.fill();
      const hx = bx + 12, hy = by - 60;
      ctx.beginPath();
      ctx.moveTo(bx + 3, by - 58);
      ctx.lineTo(hx + Math.cos(ang) * 14, hy + Math.sin(ang) * 14);
      ctx.moveTo(bx + 3, by - 58);
      ctx.lineTo(bx - 8, by - 50);
      ctx.stroke();
      ctx.save();
      ctx.translate(hx, hy); ctx.rotate(ang);
      ctx.beginPath(); ctx.arc(10, 0, 20, -1.15, 1.15); ctx.stroke();
      ctx.lineWidth = 1.6;
      ctx.beginPath();
      ctx.moveTo(10 + 20 * Math.cos(-1.15), 20 * Math.sin(-1.15));
      ctx.lineTo(4, 0);
      ctx.lineTo(10 + 20 * Math.cos(1.15), 20 * Math.sin(1.15));
      ctx.stroke();
      ctx.restore();
      ctx.font = "bold 12px system-ui"; ctx.textAlign = "center";
      ctx.fillText(mode === "solo" ? "" : "P" + (turn + 1), bx, by + 18);
    };
    const drawArrowShape = (a, col) => {
      const ang = Math.atan2(a.vy, a.vx);
      ctx.strokeStyle = col; ctx.fillStyle = col; ctx.lineWidth = 3;
      ctx.beginPath();
      ctx.moveTo(a.x - Math.cos(ang) * 22, a.y - Math.sin(ang) * 22);
      ctx.lineTo(a.x, a.y);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(a.x + Math.cos(ang) * 6, a.y + Math.sin(ang) * 6);
      ctx.lineTo(a.x - Math.cos(ang + 2.6) * 8,
                 a.y - Math.sin(ang + 2.6) * 8);
      ctx.lineTo(a.x - Math.cos(ang - 2.6) * 8,
                 a.y - Math.sin(ang - 2.6) * 8);
      ctx.closePath(); ctx.fill();
    };
    const panel = (lines) => {
      ctx.fillStyle = "rgba(6,6,12,.78)";
      ctx.beginPath(); ctx.roundRect(28, H / 2 - 92, W - 56, 184, 18);
      ctx.fill();
      ctx.strokeStyle = "rgba(255,143,190,.65)"; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.roundRect(28, H / 2 - 92, W - 56, 184, 18);
      ctx.stroke();
      ctx.textAlign = "center";
      lines.forEach(([txt, font, col, dy]) => {
        ctx.font = font; ctx.fillStyle = col;
        ctx.fillText(txt, W / 2, H / 2 + dy);
      });
    };
    const draw = () => {
      const th = mode === "solo" ? theme() : THEMES[0];
      const sky = ctx.createLinearGradient(0, 0, 0, H);
      sky.addColorStop(0, th.top); sky.addColorStop(1, th.bot);
      ctx.fillStyle = sky; ctx.fillRect(0, 0, W, H);
      if (th.stars) {
        ctx.fillStyle = "rgba(255,255,255,.75)";
        for (let i = 0; i < 26; i++) {
          const sx = (i * 67 + 23) % W, sy = (i * 41 + 11) % 150;
          ctx.fillRect(sx, sy, i % 3 === 0 ? 2 : 1, i % 3 === 0 ? 2 : 1);
        }
        ctx.fillStyle = "#F4F1DE";                    // the moon
        ctx.beginPath(); ctx.arc(38, 40, 13, 0, 7); ctx.fill();
        ctx.fillStyle = th.top;
        ctx.beginPath(); ctx.arc(45, 36, 11, 0, 7); ctx.fill();
      }
      // distant hills + ground
      ctx.fillStyle = th.hill;
      ctx.beginPath();
      ctx.moveTo(0, GY);
      ctx.quadraticCurveTo(80, GY - 46, 170, GY);
      ctx.quadraticCurveTo(255, GY - 34, W, GY);
      ctx.closePath(); ctx.fill();
      ctx.strokeStyle = "rgba(255,255,255,.28)"; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.moveTo(8, GY); ctx.lineTo(W - 8, GY);
      ctx.stroke();
      // HUD chip: level + theme name, so a new level is obvious
      ctx.textAlign = "left";
      ctx.font = "bold 12px system-ui";
      const chip = mode === "solo"
        ? "LEVEL " + level + " · " + th.name : "2 PLAYERS";
      const cw = ctx.measureText(chip).width + 18;
      ctx.fillStyle = "rgba(6,6,12,.55)";
      ctx.beginPath(); ctx.roundRect(10, 10, cw, 22, 11); ctx.fill();
      ctx.fillStyle = "#FFD9E8";
      ctx.fillText(chip, 19, 25);
      if (cfg.wind) {
        ctx.textAlign = "right"; ctx.fillStyle = "#BFE3FF";
        ctx.font = "bold 13px system-ui";
        ctx.fillText("💨 WIND " + (cfg.wind > 0 ? "→" : "←"),
                     W - 12, 25);
      }
      ctx.textAlign = "center";
      ctx.fillStyle = "#F2F3F5";
      ctx.font = "bold 15px system-ui";
      ctx.fillText("S U C C E S S", TGT.x, TGT.y - TGT.r - 16);
      // target on its pole, rings by the level's radius
      ctx.strokeStyle = "rgba(0,0,0,.45)"; ctx.lineWidth = 5;
      ctx.beginPath(); ctx.moveTo(TGT.x, TGT.y + TGT.r);
      ctx.lineTo(TGT.x, GY); ctx.stroke();
      const rings = [[1, "#F2F3F5"], [0.78, "#17171C"],
                     [0.58, "#F2F3F5"], [0.33, "#E23A3A"]];
      rings.forEach(([f, c]) => {
        ctx.fillStyle = c;
        ctx.beginPath(); ctx.arc(TGT.x, TGT.y, TGT.r * f, 0, 7);
        ctx.fill();
      });
      ctx.fillStyle = "#C9CDD4";
      bars.forEach(b => {
        ctx.beginPath();
        ctx.roundRect(b.x, b.y, b.w, 7, 3.5); ctx.fill();
        ctx.fillStyle = "rgba(255,255,255,.5)";
        ctx.fillRect(b.x + 3, b.y + 1, b.w - 6, 2);
        ctx.fillStyle = "#C9CDD4";
      });
      const ang = aim ? aim.ang
        : (arrow ? Math.atan2(arrow.vy, arrow.vx) : -0.72);
      drawArcher(state === "over" ? -0.72 : ang);
      stuck.forEach(a => drawArrowShape(a, "rgba(230,230,235,.75)"));
      if (arrow) drawArrowShape(arrow, "#FFFFFF");
      if (aim && state === "aim") {
        let px = HAND.x, py = HAND.y;
        let vx = Math.cos(aim.ang) * aim.sp,
            vy = Math.sin(aim.ang) * aim.sp;
        ctx.fillStyle = "rgba(255,255,255,.8)";
        for (let i = 0; i < 30; i++) {
          vy += 0.35; vx += cfg.wind; px += vx; py += vy;
          if (i % 2 === 0) {
            ctx.beginPath(); ctx.arc(px, py, 2.2, 0, 7); ctx.fill();
          }
          if (py > GY) break;
        }
      }
      parts.forEach(pt => {
        ctx.globalAlpha = Math.max(0, pt.life / 60);
        ctx.fillStyle = pt.c;
        ctx.fillRect(pt.x - pt.s / 2, pt.y - pt.s / 2, pt.s, pt.s);
      });
      ctx.globalAlpha = 1;
      if (note && (state === "show" || state === "aim")) {
        ctx.font = "bold 17px system-ui"; ctx.textAlign = "center";
        ctx.fillStyle = note.includes("+") ? "#FFD93D" : "#E8E4DA";
        ctx.fillText(note, W / 2, 336);
      }
      // quota progress, solo only
      if (mode === "solo" && state !== "intro") {
        ctx.fillStyle = "rgba(255,255,255,.18)";
        ctx.beginPath(); ctx.roundRect(60, H - 26, W - 120, 8, 4);
        ctx.fill();
        ctx.fillStyle = scores[0] >= cfg.quota ? "#7BE0A3" : "#58B0E6";
        ctx.beginPath();
        ctx.roundRect(60, H - 26,
          (W - 120) * Math.min(1, scores[0] / cfg.quota), 8, 4);
        ctx.fill();
      }
      if (state === "intro") {
        panel([
          ["LEVEL " + level, "bold 40px system-ui", "#FFD93D", -52],
          [th.name, "bold 17px system-ui", "#FFFFFF", -22],
          ["Score " + cfg.quota + " in 10 arrows to advance",
           "13px system-ui", "#E8E4DA", 8],
          [NEW_AT[level] || (level === 1
             ? "Thread the bars. Hit SUCCESS."
             : "Faster, smaller, trickier…"),
           "bold 13px system-ui", "#58B0E6", 34],
          [resumed
             ? "↩ Resumed — your saved run continues here"
             : "Best level reached: " + bestLevel,
           "12px system-ui", resumed ? "#7BE0A3" : "#B9BDC7", 58],
          ["— tap to start —", "bold 13px system-ui", "#FFFFFF", 80],
        ]);
      } else if (state === "clear") {
        panel([
          ["🎉 LEVEL " + level + " CLEARED!", "bold 24px system-ui",
           "#7BE0A3", -34],
          ["You scored " + scores[0] + " of " + cfg.quota + " needed",
           "14px system-ui", "#FFFFFF", -4],
          ["Total so far: " + banked, "13px system-ui", "#E8E4DA", 20],
          ["— tap for Level " + (level + 1) + " —",
           "bold 14px system-ui", "#FFD93D", 52],
        ]);
      } else if (state === "fail") {
        panel([
          ["Out of arrows", "bold 24px system-ui", "#FF9C9C", -34],
          ["You scored " + scores[0] + " — the level needs " +
           cfg.quota, "13px system-ui", "#FFFFFF", -4],
          ["The doer shoots again 😉", "13px system-ui", "#E8E4DA", 20],
          ["— tap to retry Level " + level + " —",
           "bold 14px system-ui", "#FFD93D", 52],
        ]);
      } else if (state === "over") {
        panel([
          [scores[0] === scores[1] ? "🤝 It's a draw!"
            : "🏆 Player " + (scores[0] > scores[1] ? 1 : 2) + " wins!",
           "bold 22px system-ui", "#FFD93D", -26],
          ["P1 " + scores[0] + " · P2 " + scores[1],
           "15px system-ui", "#FFFFFF", 4],
          ["— ↻ Restart to play again —", "13px system-ui",
           "#E8E4DA", 34],
        ]);
      }
    };
    const step = () => {
      if (dead) return;
      frame++;
      bars.forEach(b => {
        b.x += b.v;
        if (b.x > W + 6) b.x = -b.w - 6;
        if (b.x + b.w < -6) b.x = W + 6;
      });
      if (cfg.moveAmp)
        TGT.y = TGT_Y + Math.sin(frame * cfg.moveSp * 0.03) * cfg.moveAmp;
      parts = parts.filter(pt => pt.life > 0);
      parts.forEach(pt => {
        pt.x += pt.vx; pt.y += pt.vy; pt.vy += 0.12; pt.life--;
      });
      if (state === "fly" && arrow) {
        let done = false;
        for (let k = 0; k < 2 && !done; k++) {   // sub-steps: no tunnelling
          arrow.px = arrow.x; arrow.py = arrow.y;
          arrow.vy += 0.35 / 2;
          arrow.vx += cfg.wind / 2;
          arrow.x += arrow.vx / 2;
          arrow.y += arrow.vy / 2;
          done = planeHit() || resolveHit();
        }
      } else if (state === "show") {
        if (--noteT <= 0) { note = ""; advance(); }
      } else if (state === "clear") {
        if (--noteT <= 0) startLevel(level + 1, true);
      }
      draw();
      raf = requestAnimationFrame(step);
    };
    const pos = e => {
      const r = cv.getBoundingClientRect();
      return { x: (e.clientX - r.left) * W / r.width,
               y: (e.clientY - r.top) * H / r.height };
    };
    const setAim = e => {
      const p = pos(e);
      const dx = p.x - HAND.x, dy = p.y - HAND.y;
      let ang = Math.atan2(dy, dx);
      ang = Math.max(-1.35, Math.min(0.12, ang));
      const sp = Math.max(11, Math.min(27,
        Math.hypot(dx, dy) / 8));
      aim = { ang, sp };
    };
    cv.addEventListener("pointerdown", e => {
      e.preventDefault();
      if (state === "intro") { state = "aim"; resumed = false; return; }
      if (state === "clear") { startLevel(level + 1, true); return; }
      if (state === "fail") { startLevel(level, true); return; }
      if (state !== "aim") return;
      setAim(e);
    });
    cv.addEventListener("pointermove", e => {
      if (aim && state === "aim") setAim(e);
    });
    const release = () => {
      if (!aim || state !== "aim") { aim = null; return; }
      arrow = { x: HAND.x, y: HAND.y, px: HAND.x, py: HAND.y,
                vx: Math.cos(aim.ang) * aim.sp,
                vy: Math.sin(aim.ang) * aim.sp };
      aim = null; state = "fly";
    };
    cv.addEventListener("pointerup", release);
    cv.addEventListener("pointercancel", () => { aim = null; });

    // Solo entry: resume the saved run when there is one,
    // otherwise a fresh Level 1 (Phase 94).
    const startSolo = () => {
      mode = "solo";
      const r = loadRun();
      if (r && (r.level > 1 || r.banked > 0)) {
        banked = r.banked; resumed = true;
        startLevel(r.level, true);
      } else {
        resumed = false;
        startLevel(1, false);
      }
    };

    // controls row
    const row = document.createElement("div");
    row.className = "grow arch-row";
    const mkBtn = (label, fn) => {
      const b = document.createElement("button");
      b.textContent = label; b.onclick = fn;
      row.appendChild(b); return b;
    };
    mkBtn("👤 Solo", startSolo);
    mkBtn("👥 2 Players", () => { mode = "2p"; startLevel(1, false); });
    const inviteBox = document.createElement("div");
    inviteBox.className = "arch-invite";
    inviteBox.hidden = true;
    mkBtn("🏹 Invite friend", async () => {
      inviteBox.hidden = !inviteBox.hidden;
      if (inviteBox.hidden) return;
      inviteBox.textContent = "Loading friends…";
      let users = [];
      try {
        const r = await api("/me/following");
        users = r.users || [];
      } catch (e) { users = []; }
      inviteBox.innerHTML = "";
      const head = document.createElement("div");
      head.className = "arch-invite-head";
      head.textContent = users.length
        ? "Challenge a friend — they get a message with your best:"
        : "You are not following anyone yet — follow a friend first, then invite them.";
      inviteBox.appendChild(head);
      users.slice(0, 12).forEach(u => {
        const b = document.createElement("button");
        b.className = "arch-invite-row";
        b.textContent = "🏹 " + (u.name || "Friend");
        b.onclick = async () => {
          b.disabled = true;
          const text = "🏹 I challenge you to Archery on Nexora " +
            "Social! I reached Level " + bestLevel + " with a " +
            "best total of " + best + " — open the Games page " +
            "and beat it. The doer is already shooting 😉";
          try {
            await api("/messages/" + u.telegram_id,
              { method: "POST", body: JSON.stringify({ text }) });
            b.textContent = "✓ Challenge sent to " + (u.name || "friend");
          } catch (e) {
            b.disabled = false;
            b.textContent = "Could not send — tap to retry";
          }
        };
        inviteBox.appendChild(b);
      });
    });
    mkBtn("↻ Restart", () => startLevel(mode === "solo" ? level : 1,
                                        mode === "solo"));
    mkBtn("🆕 New run", () => {
      if (mode !== "solo") return;
      resumed = false;
      startLevel(1, false);
    });
    stage.appendChild(row);
    stage.appendChild(inviteBox);

    startSolo();
    raf = requestAnimationFrame(step);
    return () => { dead = true; cancelAnimationFrame(raf); };
  }
});

// --------------------------------------------- Phase 195: Forest Drive --
// Owner (Nov 27, 11:08 Dhaka): "Game Section এ এটা এড করবা" — the
// 3D autumn-forest driving game from his reference video, rebuilt in
// our stack (vanilla JS + vendored Three.js r149, no React, no CDN):
// a red jeep on a dirt-road loop through low-poly autumn trees, a
// lake, chase camera, minimap, speed in km/h, WASD/arrows + touch
// buttons. Arcade physics: gas/brake/reverse, speed-sensitive
// steering, grass slows you down, trees stop you (no damage model).
// Best speed is stored per account (nxGet/nxSet), like Archery's
// best — games award no points. The video's look (orange dirt,
// autumn trees, lake, minimap bottom-left, speed bottom-right) is
// matched from its frames; its React animation-library code is NOT
// reused.
registerGame({
  id: "forest-drive", icon: '<svg viewBox="0 0 64 64"><rect x="2" y="2" width="60" height="60" rx="14" fill="#BFE3F2"/><circle cx="50" cy="13" r="6" fill="#FFD93D"/><path d="M12 30 l5-10 h4 l5 10z" fill="#2FA84F"/><rect x="16" y="30" width="2" height="6" fill="#8B5E34"/><path d="M46 28 l5-8 h4 l5 8z" fill="#2FA84F"/><rect x="50" y="28" width="2" height="8" fill="#8B5E34"/><rect x="6" y="42" width="52" height="12" rx="6" fill="#6B7280"/><line x1="10" y1="48" x2="54" y2="48" stroke="#F9FAFB" stroke-width="2" stroke-dasharray="6 6"/><path d="M16 42 v-6 h10 l4-6 h8 l4 6 h6 v6z" fill="#E5484D"/><circle cx="22" cy="43" r="4" fill="#1F2937"/><circle cx="22" cy="43" r="1.6" fill="#D1D5DB"/><circle cx="42" cy="43" r="4" fill="#1F2937"/><circle cx="42" cy="43" r="1.6" fill="#D1D5DB"/></svg>', name: "Forest Drive",
  title: "Forest Drive",
  desc: "Drive the red jeep around the autumn forest — dirt roads, lake views, 90 km/h.",
  help: "WASD or arrow keys to drive. On your phone use the ◀ ▶ steer and GAS / BRAKE buttons below.",
  start(stage, setScore) {
    if (typeof THREE === "undefined" || !window.WebGLRenderingContext) {
      const p = document.createElement("p");
      p.className = "hint";
      p.textContent = "3D is not available on this device — try another phone or browser.";
      stage.appendChild(p);
      return () => {};
    }
    // --- deterministic world: the same forest on every load ---
    let seed = 195195;
    const rng = () => {
      seed |= 0; seed = seed + 0x6D2B79F5 | 0;
      let t = Math.imul(seed ^ seed >>> 15, 1 | seed);
      t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
      return ((t ^ t >>> 14) >>> 0) / 4294967296;
    };
    const WORLD = 200, ROAD_RX = 58, ROAD_RZ = 40, ROAD_W = 5;
    const LAKE = { x: -42, z: -30, r: 13 };
    const roadDist = (x, z) => {
      const q = Math.sqrt((x / ROAD_RX) * (x / ROAD_RX) + (z / ROAD_RZ) * (z / ROAD_RZ));
      if (q < 0.0001) return Math.min(ROAD_RX, ROAD_RZ);
      return Math.hypot(x - x / q, z - z / q);
    };
    // --- ground: orange dirt + fallen leaves + the road loop ---
    const groundTex = (() => {
      const c = document.createElement("canvas");
      c.width = 1024; c.height = 1024;
      const g = c.getContext("2d");
      g.fillStyle = "#C9712F"; g.fillRect(0, 0, 1024, 1024);
      const leaf = ["#A85A24", "#D98A45", "#8F4A1E", "#E0A35C", "#7A3E16"];
      for (let i = 0; i < 2400; i++) {
        g.fillStyle = leaf[(rng() * leaf.length) | 0];
        g.beginPath();
        g.arc(rng() * 1024, rng() * 1024, 1 + rng() * 2.6, 0, 6.2832);
        g.fill();
      }
      const S = 1024 / WORLD;
      const road = (style, w) => {
        g.strokeStyle = style; g.lineWidth = w * S;
        g.beginPath();
        g.ellipse(512, 512, ROAD_RX * S, ROAD_RZ * S, 0, 0, 6.2832);
        g.stroke();
      };
      road("#A85A24", (ROAD_W + 1.6) * 2);
      road("#D89A5B", ROAD_W * 2);
      g.strokeStyle = "rgba(120, 66, 22, 0.4)"; g.lineWidth = 4;
      g.setLineDash([18, 26]);
      g.beginPath();
      g.ellipse(512, 512, (ROAD_RX - 1.6) * S, (ROAD_RZ - 1.6) * S, 0, 0, 6.2832);
      g.stroke();
      g.beginPath();
      g.ellipse(512, 512, (ROAD_RX + 1.6) * S, (ROAD_RZ + 1.6) * S, 0, 0, 6.2832);
      g.stroke();
      g.setLineDash([]);
      const tex = new THREE.CanvasTexture(c);
      tex.encoding = THREE.sRGBEncoding;
      return tex;
    })();
    // --- trees + grass tufts (seeded, clear of road / lake / start) ---
    const CANOPY = [0xD94F2B, 0xE8862E, 0xE9B949, 0xC23B22, 0x5A8C3C, 0x7BAE4A];
    const trees = [];
    let guard = 0;
    while (trees.length < 64 && guard++ < 1200) {
      const x = (rng() * 2 - 1) * 92, z = (rng() * 2 - 1) * 92;
      if (roadDist(x, z) < ROAD_W + 4) continue;
      if (Math.hypot(x - LAKE.x, z - LAKE.z) < LAKE.r + 4) continue;
      if (Math.hypot(x, z) < 9) continue;
      let near = false;
      for (const t of trees) if (Math.hypot(t.x - x, t.z - z) < 6) { near = true; break; }
      if (near) continue;
      trees.push({ x, z, s: 0.8 + rng() * 0.9, pine: rng() < 0.35,
                   c: CANOPY[(rng() * CANOPY.length) | 0] });
    }
    const tufts = [];
    guard = 0;
    while (tufts.length < 46 && guard++ < 800) {
      const a = rng() * 6.2832;
      const rx = Math.cos(a) * ROAD_RX, rz = Math.sin(a) * ROAD_RZ;
      const off = ROAD_W + 0.6 + rng() * 2.6;
      const d = Math.hypot(rx, rz) || 1;
      const x = rx + rx / d * off, z = rz + rz / d * off;
      if (Math.hypot(x - LAKE.x, z - LAKE.z) < LAKE.r + 2) continue;
      tufts.push({ x, z, s: 0.7 + rng() * 0.8 });
    }
    // --- DOM: canvas + HUD (panel, minimap, speed, touch buttons) ---
    const wrap = document.createElement("div");
    wrap.className = "fd-wrap";
    stage.appendChild(wrap);
    const cv = document.createElement("canvas");
    cv.className = "fd-canvas";
    wrap.appendChild(cv);
    const panel = document.createElement("div");
    panel.className = "fd-panel";
    const pTitle = document.createElement("b");
    pTitle.textContent = "Controls";
    const pClose = document.createElement("button");
    pClose.className = "fd-x";
    pClose.textContent = "×";
    pClose.onclick = () => { panel.hidden = true; };
    panel.append(pTitle, pClose);
    [["W / ↑", "Gas"], ["S / ↓", "Brake / Reverse"], ["A D / ← →", "Steer"],
     ["🌿 Grass", "slows you down"]].forEach((r) => {
      const row = document.createElement("div");
      row.className = "fd-row";
      const k = document.createElement("span");
      k.className = "fd-key";
      k.textContent = r[0];
      const v = document.createElement("span");
      v.textContent = r[1];
      row.append(k, v);
      panel.appendChild(row);
    });
    wrap.appendChild(panel);
    const mapCv = document.createElement("canvas");
    mapCv.className = "fd-map";
    mapCv.width = 104; mapCv.height = 104;
    wrap.appendChild(mapCv);
    const mapCtx = mapCv.getContext("2d");
    const speedEl = document.createElement("div");
    speedEl.className = "fd-speed";
    const speedNum = document.createElement("b");
    speedNum.textContent = "0";
    const speedUnit = document.createElement("span");
    speedUnit.textContent = "km/h";
    speedEl.append(speedNum, speedUnit);
    wrap.appendChild(speedEl);
    const input = { gas: false, brake: false, left: false, right: false };
    const touch = document.createElement("div");
    touch.className = "fd-touch";
    const mkBtn = (parent, label, key, cls) => {
      const b = document.createElement("button");
      b.className = "fd-btn " + cls;
      b.textContent = label;
      const on = (e) => { if (e) e.preventDefault(); input[key] = true; };
      const off = (e) => { if (e) e.preventDefault(); input[key] = false; };
      b.addEventListener("pointerdown", on);
      b.addEventListener("pointerup", off);
      b.addEventListener("pointercancel", off);
      b.addEventListener("pointerleave", off);
      parent.appendChild(b);
      return b;
    };
    const steerBox = document.createElement("div");
    steerBox.className = "fd-steer";
    mkBtn(steerBox, "◀", "left", "fd-left");
    mkBtn(steerBox, "▶", "right", "fd-right");
    const pedalBox = document.createElement("div");
    pedalBox.className = "fd-pedals";
    mkBtn(pedalBox, "BRAKE", "brake", "fd-brake");
    mkBtn(pedalBox, "GAS", "gas", "fd-gas");
    touch.append(steerBox, pedalBox);
    wrap.appendChild(touch);
    // --- Three.js scene ---
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x9A86C8);
    scene.fog = new THREE.Fog(0xA990C8, 55, 175);
    const camera = new THREE.PerspectiveCamera(62, 3 / 2, 0.1, 320);
    const renderer = new THREE.WebGLRenderer({ canvas: cv, antialias: true, powerPreference: "low-power" });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.outputEncoding = THREE.sRGBEncoding;
    scene.add(new THREE.HemisphereLight(0xC9B8E8, 0x8A5A2E, 0.95));
    const sun = new THREE.DirectionalLight(0xFFE0B3, 0.85);
    sun.position.set(40, 60, 20);
    scene.add(sun);
    const ground = new THREE.Mesh(
      new THREE.PlaneGeometry(WORLD, WORLD),
      new THREE.MeshLambertMaterial({ map: groundTex }));
    ground.rotation.x = -Math.PI / 2;
    scene.add(ground);
    const lake = new THREE.Mesh(
      new THREE.CircleGeometry(LAKE.r, 28),
      new THREE.MeshLambertMaterial({ color: 0x4A90D9, emissive: 0x143C66 }));
    lake.rotation.x = -Math.PI / 2;
    lake.position.set(LAKE.x, 0.06, LAKE.z);
    scene.add(lake);
    const trunkGeo = new THREE.CylinderGeometry(0.22, 0.34, 1.5, 6);
    const trunkMat = new THREE.MeshLambertMaterial({ color: 0x6B4226 });
    const blobGeo = new THREE.IcosahedronGeometry(1.9, 0);
    const pineGeo = new THREE.ConeGeometry(1.7, 3.4, 7);
    const canopyMats = {};
    const canopyMat = (c) => {
      if (!canopyMats[c]) canopyMats[c] = new THREE.MeshLambertMaterial({ color: c, flatShading: true });
      return canopyMats[c];
    };
    const pineMat = new THREE.MeshLambertMaterial({ color: 0x2F6B33, flatShading: true });
    for (const t of trees) {
      const trunk = new THREE.Mesh(trunkGeo, trunkMat);
      trunk.position.set(t.x, 0.75, t.z);
      trunk.scale.setScalar(t.s);
      const top = new THREE.Mesh(t.pine ? pineGeo : blobGeo, t.pine ? pineMat : canopyMat(t.c));
      top.position.set(t.x, t.pine ? 3.1 * t.s : 2.9 * t.s, t.z);
      top.scale.setScalar(t.s);
      scene.add(trunk, top);
    }
    const tuftGeo = new THREE.ConeGeometry(0.4, 1.2, 4);
    const tuftMat = new THREE.MeshLambertMaterial({ color: 0x3E6B2F, flatShading: true });
    for (const t of tufts) {
      const tuft = new THREE.Mesh(tuftGeo, tuftMat);
      tuft.position.set(t.x, 0.55 * t.s, t.z);
      tuft.scale.setScalar(t.s);
      tuft.rotation.y = rng() * 6.2832;
      scene.add(tuft);
    }
    // --- the red jeep (primitives, front faces +Z) ---
    const jeep = new THREE.Group();
    const redMat = new THREE.MeshLambertMaterial({ color: 0xC0392B });
    const darkMat = new THREE.MeshLambertMaterial({ color: 0x1F2937 });
    const blackMat = new THREE.MeshLambertMaterial({ color: 0x111111 });
    const tyreMat = new THREE.MeshLambertMaterial({ color: 0x161616 });
    const hubMat = new THREE.MeshLambertMaterial({ color: 0x9AA5B1 });
    const lightMat = new THREE.MeshLambertMaterial({ color: 0xFFE9A8, emissive: 0xAA7722 });
    const add = (geo, mat, x, y, z) => {
      const m = new THREE.Mesh(geo, mat);
      m.position.set(x, y, z);
      jeep.add(m);
      return m;
    };
    add(new THREE.BoxGeometry(1.9, 0.55, 3.4), redMat, 0, 0.55, 0);
    add(new THREE.BoxGeometry(1.6, 0.5, 1.6), darkMat, 0, 1.05, -0.3);
    add(new THREE.BoxGeometry(1.66, 0.12, 1.7), redMat, 0, 1.36, -0.3);
    add(new THREE.BoxGeometry(1.5, 0.07, 1.3), blackMat, 0, 1.46, -0.3);
    add(new THREE.BoxGeometry(0.24, 0.14, 0.08), lightMat, -0.6, 0.62, 1.72);
    add(new THREE.BoxGeometry(0.24, 0.14, 0.08), lightMat, 0.6, 0.62, 1.72);
    const spare = add(new THREE.CylinderGeometry(0.44, 0.44, 0.24, 14), tyreMat, 0, 0.85, -1.78);
    spare.rotation.x = Math.PI / 2;
    const spareHub = add(new THREE.CylinderGeometry(0.2, 0.2, 0.26, 10), hubMat, 0, 0.85, -1.78);
    spareHub.rotation.x = Math.PI / 2;
    const wheelGeo = new THREE.CylinderGeometry(0.42, 0.42, 0.32, 14);
    const hubGeo = new THREE.CylinderGeometry(0.2, 0.2, 0.34, 10);
    const wheels = [];
    const steerGroups = [];
    [[-0.95, 1.15, true], [0.95, 1.15, true], [-0.95, -1.15, false], [0.95, -1.15, false]].forEach((w) => {
      const pivot = new THREE.Group();
      pivot.position.set(w[0], 0.42, w[1]);
      const spin = new THREE.Group();
      const tyre = new THREE.Mesh(wheelGeo, tyreMat);
      tyre.rotation.z = Math.PI / 2;
      const hub = new THREE.Mesh(hubGeo, hubMat);
      hub.rotation.z = Math.PI / 2;
      spin.add(tyre, hub);
      pivot.add(spin);
      jeep.add(pivot);
      wheels.push(spin);
      if (w[2]) steerGroups.push(pivot);
    });
    scene.add(jeep);
    // --- arcade physics + chase camera + HUD ---
    let best = +(nxGet("nx_forestdrive_best") || 0);
    setScore("🚗 0 km/h · Best: " + best + " km/h");
    const pos = { x: ROAD_RX, z: 0 };
    let heading = 0, speed = 0, lastKmh = -1;
    const camTarget = new THREE.Vector3(ROAD_RX, 4.6, -9.5);
    camera.position.set(ROAD_RX, 4.6, -9.5);
    camera.lookAt(ROAD_RX, 1.2, 6);
    const drawMinimap = () => {
      const S = 104 / WORLD;
      mapCtx.clearRect(0, 0, 104, 104);
      mapCtx.fillStyle = "rgba(10, 18, 28, 0.72)";
      mapCtx.fillRect(0, 0, 104, 104);
      mapCtx.fillStyle = "#4A90D9";
      mapCtx.beginPath();
      mapCtx.arc((LAKE.x + 100) * S, (LAKE.z + 100) * S, LAKE.r * S, 0, 6.2832);
      mapCtx.fill();
      mapCtx.strokeStyle = "#D89A5B";
      mapCtx.lineWidth = 3;
      mapCtx.beginPath();
      mapCtx.ellipse(52, 52, ROAD_RX * S, ROAD_RZ * S, 0, 0, 6.2832);
      mapCtx.stroke();
      mapCtx.fillStyle = "#7BAE4A";
      for (const t of trees) mapCtx.fillRect((t.x + 100) * S - 1, (t.z + 100) * S - 1, 2, 2);
      const jx = (pos.x + 100) * S, jz = (pos.z + 100) * S;
      mapCtx.strokeStyle = "#FFFFFF";
      mapCtx.lineWidth = 1.5;
      mapCtx.beginPath();
      mapCtx.moveTo(jx, jz);
      mapCtx.lineTo(jx + Math.sin(heading) * 7, jz + Math.cos(heading) * 7);
      mapCtx.stroke();
      mapCtx.fillStyle = "#EF4444";
      mapCtx.beginPath();
      mapCtx.arc(jx, jz, 3, 0, 6.2832);
      mapCtx.fill();
    };
    const step = (dt) => {
      const onRoad = roadDist(pos.x, pos.z) < ROAD_W + 1;
      const maxF = onRoad ? 26 : 14;
      const accel = onRoad ? 15 : 7;
      if (input.gas) speed += accel * dt;
      else if (input.brake) speed -= (speed > 0.5 ? 30 : 8) * dt;
      else speed -= Math.sign(speed) * Math.min(Math.abs(speed), 6 * dt);
      if (speed > maxF) speed = maxF;
      if (speed < -8) speed = -8;
      if (Math.abs(speed) < 0.05 && !input.gas && !input.brake) speed = 0;
      const steerIn = (input.left ? 1 : 0) - (input.right ? 1 : 0);
      const steerMax = 0.55 - Math.min(0.35, Math.abs(speed) * 0.012);
      const steer = steerIn * steerMax;
      heading += steer * (speed / 7) * dt * 1.15;
      const fx = Math.sin(heading), fz = Math.cos(heading);
      pos.x += fx * speed * dt;
      pos.z += fz * speed * dt;
      for (const t of trees) {
        const dx = pos.x - t.x, dz = pos.z - t.z;
        const d = Math.hypot(dx, dz), min = 1.7 + 1.1 * t.s;
        if (d < min && d > 0.001) {
          pos.x = t.x + dx / d * min;
          pos.z = t.z + dz / d * min;
          speed *= 0.35;
        }
      }
      const r = Math.hypot(pos.x, pos.z);
      if (r > 96) { pos.x *= 96 / r; pos.z *= 96 / r; speed *= 0.5; }
      jeep.position.set(pos.x, 0, pos.z);
      jeep.rotation.y = heading;
      const spin = speed * dt / 0.42;
      for (const w of wheels) w.rotation.x += spin;
      for (const g of steerGroups) g.rotation.y = steer * 0.9;
      camTarget.set(pos.x - fx * 9.5, 4.6, pos.z - fz * 9.5);
      camera.position.lerp(camTarget, 1 - Math.pow(0.001, dt));
      camera.lookAt(pos.x + fx * 6, 1.2, pos.z + fz * 6);
      const kmh = Math.round(Math.abs(speed) * 3.6);
      if (kmh !== lastKmh) {
        lastKmh = kmh;
        speedNum.textContent = String(kmh);
        if (kmh > best) {
          best = kmh;
          nxSet("nx_forestdrive_best", best);
          setScore("🚗 " + kmh + " km/h · Best: " + best + " km/h");
        }
      }
      drawMinimap();
      renderer.render(scene, camera);
    };
    const KEYS = { KeyW: "gas", ArrowUp: "gas", KeyS: "brake", ArrowDown: "brake",
                   KeyA: "left", ArrowLeft: "left", KeyD: "right", ArrowRight: "right" };
    const onKeyDown = (e) => {
      const k = KEYS[e.code];
      if (!k) return;
      e.preventDefault();
      input[k] = true;
    };
    const onKeyUp = (e) => {
      const k = KEYS[e.code];
      if (k) input[k] = false;
    };
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);
    const sizeRenderer = () => {
      const w = wrap.clientWidth || 360;
      // Phase 197: in the immersive game view the wrap fills
      // the screen, so the canvas fills the wrap instead of a
      // fixed 3:2 box. The node harness has no getElementById
      // — guard it — and fall back to 3:2 whenever the wrap
      // has no laid-out height yet.
      const _vg197 = (typeof document !== "undefined" && document.getElementById)
        ? document.getElementById("view-game") : null;
      const _imm197 = !!(_vg197 && _vg197.classList && _vg197.classList.contains("immersive"));
      const h = (_imm197 && wrap.clientHeight > 0)
        ? wrap.clientHeight : Math.round(w * 2 / 3);
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    };
    sizeRenderer();
    const onResize = () => sizeRenderer();
    window.addEventListener("resize", onResize);
    let raf = 0, dead = false, paused = false, last = 0;
    const loop = (t) => {
      if (dead || paused) return;
      const dt = Math.min(0.05, Math.max(0, last ? (t - last) / 1000 : 0.016));
      last = t;
      step(dt);
      raf = requestAnimationFrame(loop);
    };
    const onVis = () => {
      if (document.hidden) { paused = true; cancelAnimationFrame(raf); }
      else if (!dead) { paused = false; last = 0; raf = requestAnimationFrame(loop); }
    };
    document.addEventListener("visibilitychange", onVis);
    raf = requestAnimationFrame(loop);
    const cleanup = () => {
      dead = true;
      cancelAnimationFrame(raf);
      document.removeEventListener("visibilitychange", onVis);
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup", onKeyUp);
      window.removeEventListener("resize", onResize);
      renderer.dispose();
      scene.traverse((o) => {
        if (o.geometry && o.geometry.dispose) o.geometry.dispose();
        if (o.material) {
          const ms = Array.isArray(o.material) ? o.material : [o.material];
          ms.forEach((m) => { if (m.map && m.map.dispose) m.map.dispose(); if (m.dispose) m.dispose(); });
        }
      });
    };
    // Test hook (handy while tuning too): read-only state + teleport.
    cleanup._fd = {
      state: () => ({ x: pos.x, z: pos.z, speed, heading, best }),
      teleport: (x, z, h) => { pos.x = x; pos.z = z; if (typeof h === "number") heading = h; speed = 0; },
      trees: () => trees.map((t) => ({ x: t.x, z: t.z, s: t.s })),
      setInput: (k, v) => { input[k] = v; },
    };
    return cleanup;
  }
});

// --------------------------------------------- Phase 196: Runner Rush --
// Owner (Nov 27, 13:03 Dhaka): two reference videos — a bike runner
// over water and a carrot runner on a sky track — merged into ONE
// Games-section game: pick Bike Run or Carrot Run when starting.
// Rebuilt in our stack (vanilla JS + vendored Three.js r149, no
// React, no CDN): a shared 3-lane auto-runner engine, per-mode
// worlds restyled so nobody can say it is the source creators'
// game — teal lagoon + sunset + amber track + teal tide gates for
// the bike; purple dusk + mint track + star saws + a juice jar for
// the carrot. Collect, smash, dodge, finish for the multiplier.
// Best level is stored per account (nxGet/nxSet) — games award no
// points. Pauses on visibilitychange; cleanup cancels rAF, removes
// listeners and disposes the renderer.
registerGame({
  id: "runner-rush", icon: '<svg viewBox="0 0 64 64"><rect x="2" y="2" width="60" height="60" rx="14" fill="#D9F2EC"/><circle cx="18" cy="44" r="7" fill="none" stroke="#1F2937" stroke-width="2.5"/><circle cx="42" cy="44" r="7" fill="none" stroke="#1F2937" stroke-width="2.5"/><path d="M18 44 L27 32 L42 44 M27 32 L35 32 M35 32 L38 26 M27 32 L24 26" stroke="#1F2937" stroke-width="2.5" fill="none" stroke-linecap="round" stroke-linejoin="round"/><path d="M48 12 h12 l-3 16 -3 6 -3-6 -3-16z" fill="#F97316"/><path d="M54 12 q-4-6 -8-6 M54 12 q0-7 2-8 M54 12 q4-6 8-5" stroke="#2FA84F" stroke-width="2.5" fill="none" stroke-linecap="round"/></svg>', name: "Runner Rush",
  title: "Runner Rush",
  desc: "Pick your ride — pedal the lagoon track or sprint the sky track. Collect, smash, dodge, finish big.",
  help: "← → or swipe to steer. Bike: collect wheels to smash walls. Carrot: dodge the saws. Finish for the multiplier.",
  start(stage, setScore) {
    if (typeof THREE === "undefined" || !window.WebGLRenderingContext) {
      const p = document.createElement("p");
      p.className = "hint";
      p.textContent = "3D is not available on this device — try another phone or browser.";
      stage.appendChild(p);
      return () => {};
    }
    // --- deterministic world: same spawns on every load ---
    let seed = 196196;
    const rng = () => {
      seed |= 0; seed = seed + 0x6D2B79F5 | 0;
      let t = Math.imul(seed ^ seed >>> 15, 1 | seed);
      t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
      return ((t ^ t >>> 14) >>> 0) / 4294967296;
    };
    const LANES = [-2.2, 0, 2.2];
    const laneX = (l) => (l < 0 ? -4.4 : l > 2 ? 4.4 : LANES[l]);
    const TRACK_W = 7.6;
    const GATE_VALS = [2, 3, 4, 5, 6];
    let level = 1;
    let best = +(nxGet("nx_runnerrush_best") || 0);
    let mode = null;             // "bike" | "carrot"
    let status = "picker";       // picker | running | over | done
    let lane = 1, px = 0, pz = 0, speed = 0;
    let wheels = 0, gems = 0, carrots = 0, mult = 1, lastScore = 0;
    let checkpoint = 0, invuln = 0, respawnT = 0, blinkT = 0, levelLen = 600;
    let spawnZ = -24, nextFlagZ = -150;
    let rowsSinceGate = 0, rowsSinceSaw = 0;
    let ents = [];
    let modeGroup = null, player = null;
    let spinWheels = [], spinSaws = [];
    let sliceParts = [];
    const input = { left: false, right: false };
    // --- DOM: picker + canvas + HUD + touch + overlay ---
    const wrap = document.createElement("div");
    wrap.className = "rr-wrap";
    stage.appendChild(wrap);
    const cv = document.createElement("canvas");
    cv.className = "rr-canvas";
    wrap.appendChild(cv);
    const hud = document.createElement("div");
    hud.className = "rr-hud";
    hud.hidden = true;
    const modesBtn = document.createElement("button");
    modesBtn.className = "rr-modes";
    modesBtn.textContent = "‹ Modes";
    modesBtn.onclick = () => toPicker();
    const hudLevel = document.createElement("span");
    hudLevel.className = "rr-level";
    hudLevel.textContent = "Lv 1";
    const hudCount = document.createElement("span");
    hudCount.className = "rr-count";
    hudCount.textContent = "🛞 0";
    const hudGems = document.createElement("span");
    hudGems.className = "rr-gems";
    hudGems.textContent = "💎 0";
    const hudMult = document.createElement("span");
    hudMult.className = "rr-mult";
    hudMult.textContent = "×1";
    const prog = document.createElement("div");
    prog.className = "rr-progress";
    const progFill = document.createElement("div");
    progFill.className = "rr-progress-fill";
    prog.appendChild(progFill);
    hud.append(modesBtn, hudLevel, hudCount, hudGems, hudMult, prog);
    wrap.appendChild(hud);
    const picker = document.createElement("div");
    picker.className = "rr-picker";
    const pickTitle = document.createElement("div");
    pickTitle.className = "rr-pick-title";
    pickTitle.textContent = "Choose your run";
    const pickBest = document.createElement("div");
    pickBest.className = "rr-best";
    pickBest.textContent = "Best level: " + best;
    const mkPick = (label, desc, m) => {
      const b = document.createElement("button");
      b.className = "rr-pick-card";
      b.textContent = label;
      const d = document.createElement("span");
      d.className = "rr-pick-desc";
      d.textContent = desc;
      b.appendChild(d);
      b.onclick = () => startMode(m);
      return b;
    };
    picker.append(pickTitle,
      mkPick("🚲 Bike Run", "Pedal the lagoon track, collect wheels, smash numbered walls", "bike"),
      mkPick("🥕 Carrot Run", "Sprint the sky track, grab carrots, dodge the spinning saws", "carrot"),
      pickBest);
    wrap.appendChild(picker);
    const overlay = document.createElement("div");
    overlay.className = "rr-overlay";
    overlay.hidden = true;
    const ovTitle = document.createElement("div");
    ovTitle.className = "rr-ov-title";
    const ovBody = document.createElement("div");
    ovBody.className = "rr-ov-body";
    const ovBtns = document.createElement("div");
    ovBtns.className = "rr-ov-btns";
    const retryBtn = document.createElement("button");
    retryBtn.className = "rr-btn rr-retry";
    retryBtn.textContent = "↻ Retry";
    retryBtn.onclick = () => startMode(mode);
    const nextBtn = document.createElement("button");
    nextBtn.className = "rr-btn rr-next";
    nextBtn.textContent = "Next level ›";
    nextBtn.onclick = () => { level++; startMode(mode); };
    const ovModesBtn = document.createElement("button");
    ovModesBtn.className = "rr-btn rr-ov-modes";
    ovModesBtn.textContent = "Back to modes";
    ovModesBtn.onclick = () => toPicker();
    ovBtns.append(retryBtn, nextBtn, ovModesBtn);
    overlay.append(ovTitle, ovBody, ovBtns);
    wrap.appendChild(overlay);
    const touch = document.createElement("div");
    touch.className = "rr-touch";
    touch.hidden = true;
    const mkSteer = (label, dir) => {
      const b = document.createElement("button");
      b.className = "rr-btn rr-steer";
      b.textContent = label;
      const on = (e) => { if (e && e.preventDefault) e.preventDefault(); shiftLane(dir); };
      b.addEventListener("pointerdown", on);
      touch.appendChild(b);
      return b;
    };
    mkSteer("◀", -1);
    mkSteer("▶", 1);
    wrap.appendChild(touch);
    // --- Three.js scene (one renderer, per-mode world groups) ---
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0xFF9E57);
    scene.fog = new THREE.Fog(0xFFB37A, 60, 170);
    const camera = new THREE.PerspectiveCamera(62, 3 / 2, 0.1, 400);
    const camTarget = new THREE.Vector3(0, 5.2, 9.5);
    const renderer = new THREE.WebGLRenderer({ canvas: cv, antialias: true, powerPreference: "low-power" });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.outputEncoding = THREE.sRGBEncoding;
    scene.add(new THREE.HemisphereLight(0xFFE8C8, 0x2E6B6B, 0.95));
    const sun = new THREE.DirectionalLight(0xFFE0B3, 0.9);
    sun.position.set(30, 60, 20);
    scene.add(sun);
    const textTex = (txt, fg, bg) => {
      const c = document.createElement("canvas");
      c.width = 128; c.height = 128;
      const g = c.getContext("2d");
      if (bg) { g.fillStyle = bg; g.fillRect(0, 0, 128, 128); }
      g.fillStyle = fg; g.font = "bold 52px sans-serif";
      g.textAlign = "center"; g.textBaseline = "middle";
      g.fillText(txt, 64, 68);
      return new THREE.CanvasTexture(c);
    };
    const stripeTex = () => {
      const c = document.createElement("canvas");
      c.width = 32; c.height = 128;
      const g = c.getContext("2d");
      for (let i = 0; i < 8; i++) {
        g.fillStyle = i % 2 ? "#F8FAFC" : "#7C3AED";
        g.fillRect(0, i * 16, 32, 16);
      }
      return new THREE.CanvasTexture(c);
    };
    const lam = (color, extra) => {
      const p = { color: color };
      if (extra) for (const k in extra) p[k] = extra[k];
      return new THREE.MeshLambertMaterial(p);
    };
    const box = (w, h, d, mat, x, y, z) => {
      const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat);
      m.position.set(x, y, z);
      modeGroup.add(m);
      return m;
    };
    // --- bike world: teal lagoon, sunset sky, amber track, palms ---
    const buildRider = () => {
      player = new THREE.Group();
      const frameMat = lam(0x0F766E);
      const tyreMat = lam(0x1F2937);
      const hubMat = lam(0xD1D5DB);
      const jerseyMat = lam(0xEA580C);
      const skinMat = lam(0xF2C29B);
      const helmetMat = lam(0x0D9488);
      const bar = (x, y, z, rz) => {
        const m = new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.05, 1.1, 6), frameMat);
        m.position.set(x, y, z);
        m.rotation.x = rz;
        player.add(m);
        return m;
      };
      bar(0, 0.75, 0.35, 0.9);
      bar(0, 0.75, -0.35, -0.9);
      const top = new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.05, 1.15, 6), frameMat);
      top.rotation.x = Math.PI / 2; top.position.set(0, 1.0, 0);
      player.add(top);
      const wheelGeo = new THREE.TorusGeometry(0.42, 0.09, 8, 18);
      spinWheels = [];
      [0.75, -0.75].forEach((wz) => {
        const pivot = new THREE.Group();
        pivot.position.set(0, 0.42, wz);
        const tyre = new THREE.Mesh(wheelGeo, tyreMat);
        tyre.rotation.y = Math.PI / 2;
        const hub = new THREE.Mesh(new THREE.CylinderGeometry(0.09, 0.09, 0.12, 8), hubMat);
        hub.rotation.z = Math.PI / 2;
        pivot.add(tyre, hub);
        player.add(pivot);
        spinWheels.push(pivot);
      });
      const torso = new THREE.Mesh(new THREE.BoxGeometry(0.55, 0.7, 0.4), jerseyMat);
      torso.position.set(0, 1.35, -0.1);
      torso.rotation.x = 0.35;
      player.add(torso);
      const helmet = new THREE.Mesh(new THREE.SphereGeometry(0.3, 12, 8), helmetMat);
      helmet.position.set(0, 1.85, 0.05);
      player.add(helmet);
      const armGeo = new THREE.CylinderGeometry(0.06, 0.06, 0.62, 6);
      const armL = new THREE.Mesh(armGeo, jerseyMat);
      armL.position.set(-0.32, 1.45, 0.35); armL.rotation.x = 0.9;
      const armR = new THREE.Mesh(armGeo, jerseyMat);
      armR.position.set(0.32, 1.45, 0.35); armR.rotation.x = 0.9;
      player.add(armL, armR);
      const legGeo = new THREE.BoxGeometry(0.14, 0.55, 0.14);
      const legL = new THREE.Mesh(legGeo, skinMat);
      legL.position.set(-0.18, 0.95, 0.15);
      const legR = new THREE.Mesh(legGeo, skinMat);
      legR.position.set(0.18, 0.95, 0.15);
      player.add(legL, legR);
      modeGroup.add(player);
    };
    const buildBikeFinish = () => {
      const gold = lam(0xF59E0B, { emissive: 0x92400E });
      const fz = -levelLen;
      [-2.6, 2.6].forEach((x) => {
        const post = new THREE.Mesh(new THREE.CylinderGeometry(0.22, 0.3, 2.6, 8), gold);
        post.position.set(x, 1.3, fz);
        modeGroup.add(post);
      });
      const arch = new THREE.Mesh(new THREE.TorusGeometry(2.6, 0.24, 8, 20, Math.PI), gold);
      arch.position.set(0, 0.4, fz);
      modeGroup.add(arch);
      const chest = new THREE.Mesh(new THREE.BoxGeometry(1.5, 0.85, 0.9), lam(0x7C2D12));
      chest.position.set(0, 0.45, fz - 2);
      modeGroup.add(chest);
      const lid = new THREE.Mesh(new THREE.BoxGeometry(1.5, 0.4, 0.9), lam(0x9A3412));
      lid.position.set(0, 1.05, fz - 2);
      modeGroup.add(lid);
      const band = new THREE.Mesh(new THREE.BoxGeometry(1.56, 0.14, 0.96), gold);
      band.position.set(0, 0.85, fz - 2);
      modeGroup.add(band);
    };
    const buildBikeWorld = () => {
      scene.background = new THREE.Color(0xFF9E57);
      scene.fog = new THREE.Fog(0xFFB37A, 60, 170);
      const water = new THREE.Mesh(new THREE.PlaneGeometry(320, 320), lam(0x0E7C7B));
      water.rotation.x = -Math.PI / 2;
      water.position.set(0, -0.2, -levelLen / 2);
      modeGroup.add(water);
      const track = new THREE.Mesh(new THREE.PlaneGeometry(TRACK_W, levelLen + 90), lam(0xE8A33D));
      track.rotation.x = -Math.PI / 2;
      track.position.set(0, 0, -levelLen / 2 + 10);
      modeGroup.add(track);
      box(TRACK_W + 0.5, 0.18, levelLen + 90, lam(0xC77F22), 0, -0.11, -levelLen / 2 + 10);
      const sandMat = lam(0xE8C98A);
      const trunkMat = lam(0x7A4A21);
      const leafMat = lam(0x2F7D4F, { flatShading: true });
      for (let i = 0; i < 9; i++) {
        const side = i % 2 ? 1 : -1;
        const ix = side * (11 + rng() * 18);
        const iz = -20 - rng() * (levelLen - 40);
        const ir = 3 + rng() * 3.5;
        const isl = new THREE.Mesh(new THREE.CylinderGeometry(ir, ir * 1.15, 0.6, 10), sandMat);
        isl.position.set(ix, -0.05, iz);
        modeGroup.add(isl);
        const trunk = new THREE.Mesh(new THREE.CylinderGeometry(0.16, 0.26, 2.4, 6), trunkMat);
        trunk.position.set(ix, 1.2, iz);
        trunk.rotation.z = (rng() - 0.5) * 0.25;
        modeGroup.add(trunk);
        for (let l = 0; l < 4; l++) {
          const leaf = new THREE.Mesh(new THREE.ConeGeometry(0.5, 1.9, 4), leafMat);
          const a = l * 1.5708 + rng() * 0.5;
          leaf.position.set(ix + Math.cos(a) * 0.7, 2.6, iz + Math.sin(a) * 0.7);
          leaf.rotation.z = Math.cos(a) * 1.1;
          leaf.rotation.x = -Math.sin(a) * 1.1;
          modeGroup.add(leaf);
        }
      }
      buildRider();
      buildBikeFinish();
    };
    // --- carrot world: purple dusk, mint sky track, pastel clouds ---
    const buildCarrot = () => {
      player = new THREE.Group();
      const bodyMat = lam(0xF97316);
      const leafMat = lam(0x16A34A, { flatShading: true });
      const body = new THREE.Mesh(new THREE.CylinderGeometry(0.55, 0.1, 1.7, 10), bodyMat);
      body.position.y = 1.05;
      player.add(body);
      for (let i = 0; i < 3; i++) {
        const leaf = new THREE.Mesh(new THREE.ConeGeometry(0.16, 0.7, 5), leafMat);
        leaf.position.set((i - 1) * 0.18, 2.1, 0);
        leaf.rotation.z = (i - 1) * -0.35;
        player.add(leaf);
      }
      const lensMat = lam(0x1E3A8A);
      const rimMat = lam(0xF8FAFC);
      [-0.22, 0.22].forEach((x) => {
        const rim = new THREE.Mesh(new THREE.TorusGeometry(0.16, 0.045, 6, 14), rimMat);
        rim.position.set(x, 1.45, -0.5);
        const lens = new THREE.Mesh(new THREE.CylinderGeometry(0.13, 0.13, 0.05, 10), lensMat);
        lens.rotation.x = Math.PI / 2;
        lens.position.set(x, 1.45, -0.5);
        player.add(rim, lens);
      });
      const strap = new THREE.Mesh(new THREE.TorusGeometry(0.5, 0.04, 6, 16), rimMat);
      strap.rotation.x = Math.PI / 2;
      strap.position.set(0, 1.45, 0);
      player.add(strap);
      const scarf = new THREE.Mesh(new THREE.TorusGeometry(0.5, 0.13, 8, 16), lam(0x5EEAD4));
      scarf.rotation.x = Math.PI / 2;
      scarf.position.set(0, 1.15, 0);
      player.add(scarf);
      const scarfTail = new THREE.Mesh(new THREE.BoxGeometry(0.18, 0.6, 0.06), lam(0x5EEAD4));
      scarfTail.position.set(0.3, 0.95, 0.35);
      scarfTail.rotation.z = 0.25;
      player.add(scarfTail);
      const armGeo = new THREE.CylinderGeometry(0.06, 0.06, 0.6, 6);
      const armL = new THREE.Mesh(armGeo, bodyMat);
      armL.position.set(-0.62, 1.2, 0);
      armL.rotation.z = 0.9;
      const armR = new THREE.Mesh(armGeo, bodyMat);
      armR.position.set(0.62, 1.2, 0);
      armR.rotation.z = -0.9;
      player.add(armL, armR);
      player.userData = { armL: armL, armR: armR };
      modeGroup.add(player);
    };
    const buildJarFinish = () => {
      const fz = -levelLen;
      const glass = new THREE.Mesh(new THREE.CylinderGeometry(2.3, 2.3, 4.4, 18),
        lam(0xE0F2FE, { transparent: true, opacity: 0.45 }));
      glass.position.set(0, 2.2, fz);
      modeGroup.add(glass);
      const juice = new THREE.Mesh(new THREE.CylinderGeometry(1.95, 1.95, 3.4, 18), lam(0xF97316));
      juice.position.set(0, 1.7, fz);
      modeGroup.add(juice);
      const rim = new THREE.Mesh(new THREE.TorusGeometry(2.3, 0.16, 8, 22), lam(0xF8FAFC));
      rim.rotation.x = Math.PI / 2;
      rim.position.set(0, 4.4, fz);
      modeGroup.add(rim);
      const zoneCols = [0x22C55E, 0x3B82F6, 0xA855F7, 0xF59E0B];
      const zoneTxt = ["×2", "×4", "×6", "×8"];
      zoneCols.forEach((c, i) => {
        const band = new THREE.Mesh(new THREE.CylinderGeometry(2.0, 2.0, 0.8, 18), lam(c));
        band.position.set(0, 0.45 + i * 0.85, fz);
        modeGroup.add(band);
        const lbl = new THREE.Mesh(new THREE.PlaneGeometry(1.1, 1.1),
          new THREE.MeshBasicMaterial({ map: textTex(zoneTxt[i], "#FFFFFF", null), transparent: true }));
        lbl.position.set(0, 0.45 + i * 0.85, fz + 2.05);
        modeGroup.add(lbl);
      });
    };
    const buildCarrotWorld = () => {
      scene.background = new THREE.Color(0x6B4FA1);
      scene.fog = new THREE.Fog(0x8A6BC0, 60, 170);
      const track = new THREE.Mesh(new THREE.PlaneGeometry(TRACK_W, levelLen + 90), lam(0x7FE3B0));
      track.rotation.x = -Math.PI / 2;
      track.position.set(0, 0, -levelLen / 2 + 10);
      modeGroup.add(track);
      box(TRACK_W + 0.5, 0.18, levelLen + 90, lam(0x4CC98A), 0, -0.11, -levelLen / 2 + 10);
      const cloudCols = [0xFDF6EC, 0xFDE68A, 0xFBCFE8, 0xE0E7FF];
      for (let i = 0; i < 14; i++) {
        const side = i % 2 ? 1 : -1;
        box(2 + rng() * 3, 1 + rng() * 1.6, 2 + rng() * 2, lam(cloudCols[i % cloudCols.length]),
            side * (9 + rng() * 16), 2 + rng() * 6, -20 - rng() * (levelLen - 40));
      }
      const bCols = [0xF9A8D4, 0xA5B4FC, 0xFCD34D, 0x6EE7B7, 0xFDA4AF];
      for (let i = 0; i < 10; i++) {
        const side = i % 2 ? 1 : -1;
        const h = 4 + rng() * 7;
        box(3 + rng() * 2, h, 3 + rng() * 2, lam(bCols[i % bCols.length]),
            side * (10 + rng() * 14), -h / 2 - 0.5, -30 - rng() * (levelLen - 60));
      }
      buildCarrot();
      buildJarFinish();
    };
    // --- spawns (rows ahead of the player, removed behind) ---
    const spawnWheelRow = (z) => {
      const ln = (rng() * 3) | 0;
      const n = 3 + ((rng() * 3) | 0);
      for (let i = 0; i < n; i++) {
        const g = new THREE.Group();
        const tyre = new THREE.Mesh(new THREE.TorusGeometry(0.42, 0.13, 8, 16), lam(0x374151));
        tyre.rotation.y = Math.PI / 2;
        const hub = new THREE.Mesh(new THREE.CylinderGeometry(0.12, 0.12, 0.16, 8), lam(0xF59E0B));
        hub.rotation.z = Math.PI / 2;
        g.add(tyre, hub);
        g.position.set(LANES[ln], 0.55, z - i * 2.6);
        modeGroup.add(g);
        ents.push({ kind: "wheel", g: g, z: z - i * 2.6, lane: ln, done: false });
      }
    };
    const spawnGemRow = (z) => {
      const ln = (rng() * 3) | 0;
      for (let i = 0; i < 2; i++) {
        const g = new THREE.Mesh(new THREE.OctahedronGeometry(0.5, 0), lam(0xEC4899, { emissive: 0x9D174D }));
        g.position.set(LANES[ln], 0.9, z - i * 3);
        modeGroup.add(g);
        ents.push({ kind: "gem", g: g, z: z - i * 3, lane: ln, done: false });
      }
    };
    const spawnWall = (z) => {
      const g = new THREE.Group();
      const costs = [0, 1, 2].map(() => 2 + ((rng() * (6 + level)) | 0));
      const panels = [];
      const panelMat = lam(0x0D9488);
      for (let i = 0; i < 3; i++) {
        const p = new THREE.Group();
        const blk = new THREE.Mesh(new THREE.BoxGeometry(2.0, 2.2, 0.5), panelMat);
        blk.position.y = 1.1;
        p.add(blk);
        const num = new THREE.Mesh(new THREE.PlaneGeometry(1.5, 1.5),
          new THREE.MeshBasicMaterial({ map: textTex(String(costs[i]), "#FFFFFF", "#0F766E") }));
        num.position.set(0, 1.1, 0.28);
        p.add(num);
        p.position.set(LANES[i], 0, 0);
        g.add(p);
        panels.push(p);
      }
      const beam = new THREE.Mesh(new THREE.BoxGeometry(7.2, 0.35, 0.6), lam(0x0F766E));
      beam.position.y = 2.35;
      g.add(beam);
      g.position.set(0, 0, z);
      modeGroup.add(g);
      ents.push({ kind: "wall", g: g, z: z, lane: -1, costs: costs, panels: panels, done: false });
    };
    const spawnGate = (z) => {
      const val = GATE_VALS[(rng() * GATE_VALS.length) | 0];
      const g = new THREE.Group();
      const postMat = lam(0xF59E0B, { emissive: 0x92400E });
      [-3.1, 3.1].forEach((x) => {
        const post = new THREE.Mesh(new THREE.CylinderGeometry(0.14, 0.14, 2.6, 8), postMat);
        post.position.set(x, 1.3, 0);
        g.add(post);
      });
      const bar = new THREE.Mesh(new THREE.BoxGeometry(6.6, 0.3, 0.3), postMat);
      bar.position.y = 2.6;
      g.add(bar);
      const lbl = new THREE.Mesh(new THREE.PlaneGeometry(1.8, 1.8),
        new THREE.MeshBasicMaterial({ map: textTex(val + "X", "#7C2D12", "#FDE68A") }));
      lbl.position.set(0, 2.6, 0.2);
      g.add(lbl);
      g.position.set(0, 0, z);
      modeGroup.add(g);
      ents.push({ kind: "gate", g: g, z: z, lane: -1, val: val, done: false });
    };
    const spawnCarrotRow = (z) => {
      const ln = (rng() * 3) | 0;
      const n = 3 + ((rng() * 3) | 0);
      for (let i = 0; i < n; i++) {
        const g = new THREE.Group();
        const body = new THREE.Mesh(new THREE.ConeGeometry(0.28, 0.7, 8), lam(0xFBBF24));
        body.rotation.x = Math.PI;
        body.position.y = 0.55;
        g.add(body);
        const leaf = new THREE.Mesh(new THREE.ConeGeometry(0.12, 0.35, 5), lam(0x16A34A));
        leaf.position.y = 1.0;
        g.add(leaf);
        g.position.set(LANES[ln], 0, z - i * 2.4);
        modeGroup.add(g);
        ents.push({ kind: "carrot", g: g, z: z - i * 2.4, lane: ln, done: false });
      }
    };
    const spawnSawRow = (z) => {
      const lanes = [0, 1, 2].sort(() => rng() - 0.5);
      const n = rng() < 0.6 ? 1 : 2;
      for (let i = 0; i < n; i++) {
        const ln = lanes[i];
        const g = new THREE.Group();
        const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.12, 0.12, 2.4, 8),
          new THREE.MeshLambertMaterial({ map: stripeTex() }));
        pole.position.y = 1.2;
        g.add(pole);
        const blade = new THREE.Group();
        blade.position.y = 1.1;
        const disc = new THREE.Mesh(new THREE.CylinderGeometry(0.85, 0.85, 0.12, 18), lam(0x7C3AED));
        disc.rotation.x = Math.PI / 2;
        blade.add(disc);
        for (let s = 0; s < 8; s++) {
          const spike = new THREE.Mesh(new THREE.ConeGeometry(0.22, 0.55, 4), lam(0xA855F7));
          const a = s * Math.PI / 4;
          spike.position.set(Math.cos(a) * 1.0, Math.sin(a) * 1.0, 0);
          spike.rotation.z = a - Math.PI / 2;
          blade.add(spike);
        }
        g.add(blade);
        g.position.set(LANES[ln], 0, z);
        modeGroup.add(g);
        ents.push({ kind: "saw", g: g, z: z, lane: ln, blade: blade, done: false });
        spinSaws.push(blade);
      }
    };
    const spawnFlag = (z) => {
      const g = new THREE.Group();
      const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.07, 0.07, 2.2, 6), lam(0xE5E7EB));
      pole.position.y = 1.1;
      g.add(pole);
      const flag = new THREE.Mesh(new THREE.PlaneGeometry(0.9, 0.55),
        new THREE.MeshBasicMaterial({ color: 0x22C55E }));
      flag.position.set(0.5, 1.9, 0);
      g.add(flag);
      g.position.set(3.4, 0, z);
      modeGroup.add(g);
      ents.push({ kind: "flag", g: g, z: z, lane: -1, done: false });
    };
    const spawnRow = (z) => {
      if (z < -levelLen + 30) return;
      const r = rng();
      if (mode === "bike") {
        // A multiplier gate is guaranteed at least every 9 rows so the
        // multiplier is never out of reach for a whole level.
        if (rowsSinceGate >= 8) { spawnGate(z); rowsSinceGate = 0; }
        else if (r < 0.30) { spawnWheelRow(z); rowsSinceGate++; }
        else if (r < 0.42) { spawnGemRow(z); rowsSinceGate++; }
        else if (r < 0.62) { spawnWall(z); rowsSinceGate++; }
        else if (r < 0.76) { spawnGate(z); rowsSinceGate = 0; }
        else rowsSinceGate++;
      } else {
        // A saw is guaranteed at least every 9 rows so the dodge
        // challenge never vanishes for a whole level.
        if (rowsSinceSaw >= 8) { spawnSawRow(z); rowsSinceSaw = 0; }
        else if (r < 0.34) { spawnCarrotRow(z); rowsSinceSaw++; }
        else if (r < 0.58) { spawnSawRow(z); rowsSinceSaw = 0; }
        else rowsSinceSaw++;
      }
    };
    const nextEnt = (kind) => {
      let bestE = null;
      for (const e of ents) {
        if (e.kind !== kind || e.done) continue;
        if (e.z > pz) continue;
        if (!bestE || e.z > bestE.z) bestE = e;
      }
      if (!bestE) return null;
      const out = { z: bestE.z };
      if (kind === "wall") out.costs = bestE.costs.slice();
      if (kind === "saw" || kind === "carrot" || kind === "wheel" || kind === "gem") out.lane = bestE.lane;
      if (kind === "gate") out.val = bestE.val;
      return out;
    };
    // --- HUD / overlays / scoring ---
    const carrotMult = (c) => (c < 10 ? 2 : c < 20 ? 4 : c < 30 ? 6 : 8);
    const updateHUD = () => {
      hudLevel.textContent = "Lv " + level;
      if (mode === "bike") {
        hudCount.textContent = "🛞 " + wheels;
        hudGems.hidden = false;
        hudGems.textContent = "💎 " + gems;
        hudMult.textContent = "×" + mult;
      } else if (mode === "carrot") {
        hudCount.textContent = "🥕 " + carrots;
        hudGems.hidden = true;
        mult = carrotMult(carrots);
        hudMult.textContent = "×" + mult;
      }
      setScore("🏁 Lv " + level + " · " + (mode === "bike"
        ? "🛞 " + wheels + " · 💎 " + gems + " · ×" + mult
        : "🥕 " + carrots + " · ×" + mult) + " · Best Lv " + best);
    };
    const confetti = () => {
      const cols = ["#F59E0B", "#EF4444", "#22C55E", "#3B82F6", "#A855F7", "#FACC15"];
      for (let i = 0; i < 36; i++) {
        const d = document.createElement("div");
        d.className = "rr-confetti";
        d.style.left = (rng() * 100).toFixed(1) + "%";
        d.style.background = cols[i % cols.length];
        d.style.animationDelay = (rng() * 0.4).toFixed(2) + "s";
        wrap.appendChild(d);
        setTimeout(() => { if (d.remove) d.remove(); }, 1600);
      }
    };
    const showOverlay = (title, body, showRetry, showNext) => {
      ovTitle.textContent = title;
      ovBody.textContent = body;
      retryBtn.hidden = !showRetry;
      nextBtn.hidden = !showNext;
      overlay.hidden = false;
    };
    const crash = (reason) => {
      if (status !== "running") return;
      status = "over";
      showOverlay("💥 Crashed!", reason + " Best level: " + best + ".", true, false);
      setScore("🏁 Lv " + level + " · Crashed · Best Lv " + best);
    };
    const finishRun = () => {
      if (status !== "running") return;
      status = "done";
      if (mode === "bike") lastScore = (wheels + gems) * mult;
      else lastScore = carrots * carrotMult(carrots);
      if (level > best) { best = level; nxSet("nx_runnerrush_best", best); }
      pickBest.textContent = "Best level: " + best;
      confetti();
      showOverlay("🏆 Level Clear!",
        (mode === "bike"
          ? "Score: " + lastScore + "  (" + wheels + " wheels + " + gems + " gems) × " + mult
          : "Score: " + lastScore + "  (" + carrots + " carrots × " + carrotMult(carrots) + ")")
        + "  ·  Best level: " + best + ".", false, true);
      setScore("🏁 Lv " + level + " clear! Score " + lastScore + " · Best Lv " + best);
    };
    const spawnSlices = () => {
      for (let i = 0; i < 3; i++) {
        const m = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.35, 0.3),
          new THREE.MeshLambertMaterial({ color: 0xF97316, transparent: true, opacity: 1 }));
        m.position.set(px + (i - 1) * 0.4, 1.0 + i * 0.2, pz);
        modeGroup.add(m);
        sliceParts.push({ m: m, vx: (i - 1) * 2.2, vy: 3 + i, vz: 1.5, life: 0.8 });
      }
    };
    const respawn = () => {
      pz = checkpoint;
      lane = 1; px = 0;
      invuln = 1.5;
      respawnT = 0.6;
      player.visible = false;
      spawnSlices();
    };
    const sawHit = () => {
      if (carrots >= 5) {
        carrots -= 5;
        respawn();
        updateHUD();
      } else {
        crash("Sliced by a star saw! You needed 5 carrots banked to keep going.");
      }
    };
    const edgeFall = () => {
      carrots = Math.max(0, carrots - 3);
      respawn();
      updateHUD();
    };
    const hitWall = (ent) => {
      const cost = ent.costs[lane];
      if (wheels >= cost) {
        wheels -= cost;
        const p = ent.panels[lane];
        if (p) ent.g.remove(p);
        ent.done = true;
        updateHUD();
      } else {
        crash("The tide gate needed " + cost + " wheels — you only had " + wheels + ".");
      }
    };
    const shiftLane = (dir) => {
      if (status !== "running") return;
      const min = mode === "carrot" ? -1 : 0;
      const max = mode === "carrot" ? 3 : 2;
      lane = Math.max(min, Math.min(max, lane + dir));
    };
    // --- mode lifecycle ---
    const disposeModeGroup = () => {
      if (!modeGroup) return;
      modeGroup.traverse((o) => {
        if (o.geometry && o.geometry.dispose) o.geometry.dispose();
        if (o.material) {
          const ms = Array.isArray(o.material) ? o.material : [o.material];
          ms.forEach((m) => { if (m.map && m.map.dispose) m.map.dispose(); if (m.dispose) m.dispose(); });
        }
      });
      scene.remove(modeGroup);
      modeGroup = null;
    };
    const startMode = (m) => {
      disposeModeGroup();
      mode = m;
      levelLen = 600 + 150 * (level - 1);
      lane = 1; px = 0; pz = 0; speed = 0;
      wheels = 0; gems = 0; carrots = 0; mult = 1; lastScore = 0;
      checkpoint = 0; invuln = 0; respawnT = 0; blinkT = 0;
      spawnZ = -24; nextFlagZ = -150;
      rowsSinceGate = 0; rowsSinceSaw = 0;
      ents = []; spinSaws = []; spinWheels = []; sliceParts = [];
      modeGroup = new THREE.Group();
      scene.add(modeGroup);
      if (m === "bike") buildBikeWorld(); else buildCarrotWorld();
      camera.position.set(0, 5.2, 9.5);
      camera.lookAt(0, 1.0, -8);
      status = "running";
      picker.hidden = true;
      overlay.hidden = true;
      hud.hidden = false;
      touch.hidden = false;
      updateHUD();
    };
    const toPicker = () => {
      disposeModeGroup();
      mode = null;
      status = "picker";
      ents = []; spinSaws = []; spinWheels = []; sliceParts = [];
      picker.hidden = false;
      hud.hidden = true;
      touch.hidden = true;
      overlay.hidden = true;
      pickBest.textContent = "Best level: " + best;
      setScore("🏁 Pick your ride — Bike Run or Carrot Run. Best Lv " + best);
    };
    // --- per-frame step ---
    const step = (dt) => {
      if (status !== "running" || !modeGroup) return;
      if (respawnT > 0) {
        respawnT -= dt;
        for (const s of sliceParts) {
          s.m.position.x += s.vx * dt;
          s.m.position.y += s.vy * dt;
          s.m.position.z += s.vz * dt;
          s.vy -= 9 * dt;
          s.life -= dt;
          if (s.m.material) s.m.material.opacity = Math.max(0, s.life / 0.8);
        }
        if (respawnT <= 0) {
          player.visible = true;
          for (const s of sliceParts) modeGroup.remove(s.m);
          sliceParts = [];
        }
        renderer.render(scene, camera);
        return;
      }
      if (invuln > 0) {
        invuln -= dt;
        blinkT += dt;
        player.visible = Math.floor(blinkT * 8) % 2 === 0;
        if (invuln <= 0) player.visible = true;
      }
      const base = mode === "bike" ? 13 : 12;
      speed = base + level * 1.2 + Math.min(6, -pz * 0.004);
      pz -= speed * dt;
      const targetX = laneX(lane);
      px += (targetX - px) * Math.min(1, dt * 10);
      player.position.set(px, 0, pz);
      player.rotation.z = -(targetX - px) * 0.1;
      if (mode === "bike") {
        for (const w of spinWheels) w.rotation.x += speed * dt / 0.42;
      } else {
        player.position.y = Math.abs(Math.sin(-pz * 0.35)) * 0.16;
        const a = player.userData;
        if (a && a.armL) {
          a.armL.rotation.z = 0.9 + Math.sin(-pz * 0.5) * 0.5;
          a.armR.rotation.z = -0.9 - Math.sin(-pz * 0.5) * 0.5;
        }
        if (Math.abs(px) > 3.6) edgeFall();
      }
      if (respawnT > 0) { renderer.render(scene, camera); return; }
      if (mode === "carrot") {
        while (-pz > -nextFlagZ && -nextFlagZ < levelLen - 20) {
          spawnFlag(nextFlagZ - 5);
          nextFlagZ -= 150;
        }
      }
      while (spawnZ > pz - 170) { spawnRow(spawnZ); spawnZ -= 13 + rng() * 8; }
      for (const s of spinSaws) s.rotation.z += dt * 7;
      for (let i = ents.length - 1; i >= 0; i--) {
        const e = ents[i];
        if (e.z > pz + 14) {
          modeGroup.remove(e.g);
          ents.splice(i, 1);
          continue;
        }
        if (e.done) continue;
        if (e.kind === "wheel" || e.kind === "gem" || e.kind === "carrot") {
          e.g.rotation.y += dt * 3;
          if (Math.abs(e.z - pz) < 1.3 && e.lane === lane) {
            e.done = true;
            modeGroup.remove(e.g);
            if (e.kind === "wheel") wheels++;
            else if (e.kind === "gem") gems++;
            else carrots++;
            updateHUD();
          }
        } else if (e.kind === "wall") {
          if (pz <= e.z) hitWall(e);
        } else if (e.kind === "gate") {
          if (pz <= e.z) { e.done = true; mult = e.val; updateHUD(); }
        } else if (e.kind === "saw") {
          if (Math.abs(e.z - pz) < 1.3 && e.lane === lane && invuln <= 0) {
            e.done = true;
            modeGroup.remove(e.g);
            sawHit();
          }
        } else if (e.kind === "flag") {
          if (pz <= e.z) { e.done = true; checkpoint = e.z; }
        }
      }
      if (pz <= -levelLen) finishRun();
      progFill.style.width = Math.max(0, Math.min(100, Math.round(-pz / levelLen * 100))) + "%";
      camTarget.set(px * 0.55, 5.2, pz + 9.5);
      camera.position.lerp(camTarget, 1 - Math.pow(0.001, dt));
      camera.lookAt(px * 0.8, 1.0, pz - 8);
      renderer.render(scene, camera);
    };
    // --- input: keyboard + swipe + touch buttons ---
    const KEYS = { ArrowLeft: -1, KeyA: -1, ArrowRight: 1, KeyD: 1 };
    const onKeyDown = (e) => {
      const d = KEYS[e.code];
      if (d === undefined) return;
      if (e.preventDefault) e.preventDefault();
      shiftLane(d);
    };
    window.addEventListener("keydown", onKeyDown);
    let tsX = 0, tsY = 0;
    const onTouchStart = (e) => {
      const t = e.touches && e.touches[0];
      if (!t) return;
      tsX = t.clientX; tsY = t.clientY;
    };
    const onTouchEnd = (e) => {
      const t = e.changedTouches && e.changedTouches[0];
      if (!t) return;
      const dx = t.clientX - tsX, dy = t.clientY - tsY;
      if (Math.max(Math.abs(dx), Math.abs(dy)) < 24) return;
      if (Math.abs(dx) > Math.abs(dy)) shiftLane(Math.sign(dx));
    };
    cv.addEventListener("touchstart", onTouchStart, { passive: true });
    cv.addEventListener("touchend", onTouchEnd, { passive: true });
    const sizeRenderer = () => {
      const w = wrap.clientWidth || 360;
      // Phase 197: same immersive fill as Forest Drive — the
      // canvas fills the wrap instead of a fixed 3:2 box.
      const _vg197 = (typeof document !== "undefined" && document.getElementById)
        ? document.getElementById("view-game") : null;
      const _imm197 = !!(_vg197 && _vg197.classList && _vg197.classList.contains("immersive"));
      const h = (_imm197 && wrap.clientHeight > 0)
        ? wrap.clientHeight : Math.round(w * 2 / 3);
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    };
    sizeRenderer();
    const onResize = () => sizeRenderer();
    window.addEventListener("resize", onResize);
    let raf = 0, dead = false, paused = false, last = 0;
    const loop = (t) => {
      if (dead || paused) return;
      const dt = Math.min(0.05, Math.max(0, last ? (t - last) / 1000 : 0.016));
      last = t;
      step(dt);
      if (status === "picker" || !modeGroup) renderer.render(scene, camera);
      raf = requestAnimationFrame(loop);
    };
    const onVis = () => {
      if (document.hidden) { paused = true; cancelAnimationFrame(raf); }
      else if (!dead) { paused = false; last = 0; raf = requestAnimationFrame(loop); }
    };
    document.addEventListener("visibilitychange", onVis);
    raf = requestAnimationFrame(loop);
    setScore("🏁 Pick your ride — Bike Run or Carrot Run. Best Lv " + best);
    const cleanup = () => {
      dead = true;
      cancelAnimationFrame(raf);
      document.removeEventListener("visibilitychange", onVis);
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("resize", onResize);
      cv.removeEventListener("touchstart", onTouchStart);
      cv.removeEventListener("touchend", onTouchEnd);
      renderer.dispose();
      scene.traverse((o) => {
        if (o.geometry && o.geometry.dispose) o.geometry.dispose();
        if (o.material) {
          const ms = Array.isArray(o.material) ? o.material : [o.material];
          ms.forEach((m) => { if (m.map && m.map.dispose) m.map.dispose(); if (m.dispose) m.dispose(); });
        }
      });
    };
    // Test hook: read-only state + driving controls for the harness.
    cleanup._rr = {
      mode: () => mode,
      state: () => ({
        mode: mode, status: status, lane: lane, x: px, z: pz,
        speed: speed, level: level, wheels: wheels, gems: gems,
        carrots: carrots, mult: mult, score: lastScore, best: best,
        checkpoint: checkpoint, invuln: invuln, dist: -pz,
        finishZ: -levelLen,
        nextWall: nextEnt("wall"), nextSaw: nextEnt("saw"),
        nextGate: nextEnt("gate"), nextFlag: nextEnt("flag"),
      }),
      setInput: (k, v) => {
        input[k] = v;
        if (v && k === "left") shiftLane(-1);
        if (v && k === "right") shiftLane(1);
      },
      teleport: (z, laneIdx) => {
        pz = z;
        if (typeof laneIdx === "number") { lane = laneIdx; px = laneX(laneIdx); }
      },
      collect: (n, kind) => {
        if (mode === "carrot") carrots += n;
        else if (kind === "gem") gems += n;
        else wheels += n;
        updateHUD();
      },
      setCount: (kind, n) => {
        if (kind === "wheel") wheels = n;
        else if (kind === "gem") gems = n;
        else if (kind === "carrot") carrots = n;
        else if (kind === "mult") mult = n;
        updateHUD();
      },
      hitObstacle: () => {
        if (status !== "running") return;
        if (mode === "bike") {
          const w = nextEnt("wall");
          if (w) {
            const cost = w.costs[lane];
            if (wheels >= cost) { wheels -= cost; updateHUD(); }
            else crash("The tide gate needed " + cost + " wheels — you only had " + wheels + ".");
          }
        } else {
          sawHit();
        }
      },
      finish: () => { if (status === "running") finishRun(); },
      toPicker: () => toPicker(),
    };
    return cleanup;
  }
});


// --------------------------------------------- Phase 209: Island Plane Landing --
// Owner (Nov 27, 23:14 Dhaka): "এই গেমটি এড করবা" — the "Crazy Plane
// Landing" video's jet game, rebuilt in our stack (vanilla JS +
// vendored Three.js r149, no React, no CDN): a teal-and-gold jet on
// a tropical island runway — taxi, take off, thread three golden
// rings over the lagoon and the palms, then land gently back on the
// runway. Yoke bottom-left (drag to steer, ← → keys), throttle
// slider bottom-right (drag, ↑ ↓ keys). The video's look (white jet
// with a red tail, hands on the controls, "Crazy Plane Landing"
// title) is NOT copied: our jet wears a teal + gold livery, the
// island is deep emerald green to match the Games section, the HUD
// is dark-green glass, and the loop adds rings + a scored landing
// (centreline + gentle touchdown) with a crash on a hard or
// off-runway touchdown. Best score is stored per account
// (nxGet/nxSet), like Forest Drive's best — games award no points.
// The loop pauses on visibilitychange; cleanup cancels rAF, removes
// listeners and disposes the renderer.
registerGame({
  id: "plane-landing", icon: '<svg viewBox="0 0 64 64"><rect x="2" y="2" width="60" height="60" rx="14" fill="#BFE3F2"/><circle cx="50" cy="14" r="6" fill="#FFD93D"/><path d="M2 44 Q32 38 62 44 L62 62 L2 62z" fill="#1E7A46"/><rect x="28" y="40" width="8" height="22" fill="#0C2115"/><line x1="32" y1="44" x2="32" y2="60" stroke="#F9FAFB" stroke-width="1.6" stroke-dasharray="3 3"/><path d="M32 8 l3 6 -3 22 -3-22z" fill="#0D9488"/><path d="M29 20 h6 l1 4 h-8z" fill="#F59E0B"/><path d="M20 26 l12-4 12 4 -12 3z" fill="#0D9488"/><circle cx="32" cy="14" r="2.4" fill="#F8FAFC"/></svg>', name: "Island Plane Landing",
  title: "Island Plane Landing",
  desc: "Taxi the teal jet down the island runway, lift off, thread the golden rings, then land her home — smooth and on the centreline.",
  help: "Throttle: drag the slider or hold ↑ / ↓. Steer: drag the yoke or use ← →. Take off, fly the 3 rings, then land gently on the runway.",
  start(stage, setScore) {
    if (typeof THREE === "undefined" || !window.WebGLRenderingContext) {
      const p = document.createElement("p");
      p.className = "hint";
      p.textContent = "3D is not available on this device — try another phone or browser.";
      stage.appendChild(p);
      return () => {};
    }
    // --- deterministic world: the same island on every load ---
    let seed = 209209;
    const rng = () => {
      seed |= 0; seed = seed + 0x6D2B79F5 | 0;
      let t = Math.imul(seed ^ seed >>> 15, 1 | seed);
      t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
      return ((t ^ t >>> 14) >>> 0) / 4294967296;
    };
    const WORLD = 260, ISLAND_R = 122;
    const RW = { z0: -85, z1: 85, half: 4.5 };
    const RINGS = [
      { x: 0, y: 20, z: -112 },
      { x: -55, y: 26, z: -45 },
      { x: 48, y: 22, z: 35 },
    ];
    const MOUNTAIN = { x: -75, z: -75, r: 14, h: 20 };
    const LAGOON = { x: 55, z: -55, r: 16 };
    // --- ground: emerald grass + sand ring + the runway ---
    const groundTex = (() => {
      const c = document.createElement("canvas");
      c.width = 1024; c.height = 1024;
      const g = c.getContext("2d");
      g.fillStyle = "#1E7A46"; g.fillRect(0, 0, 1024, 1024);
      const leaf = ["#17663A", "#2A9155", "#14522D", "#35995E"];
      for (let i = 0; i < 1600; i++) {
        g.fillStyle = leaf[(rng() * leaf.length) | 0];
        g.beginPath();
        g.arc(rng() * 1024, rng() * 1024, 1 + rng() * 3, 0, 6.2832);
        g.fill();
      }
      const S = 1024 / WORLD;
      g.strokeStyle = "#E8D9A8"; g.lineWidth = 9 * S;
      g.beginPath();
      g.arc(512, 512, ISLAND_R * S, 0, 6.2832);
      g.stroke();
      const rx = 512, rz0 = (RW.z0 + 130) * S, rz1 = (RW.z1 + 130) * S;
      g.fillStyle = "#3A3F45";
      g.fillRect(rx - RW.half * S - 3, rz0, RW.half * 2 * S + 6, rz1 - rz0);
      g.fillStyle = "#F5F5F5";
      for (let z = RW.z0 + 6; z < RW.z1 - 4; z += 12) {
        g.fillRect(rx - 1, (z + 130) * S, 2, 7 * S);
      }
      g.fillRect(rx - RW.half * S, rz0 + 2, RW.half * 2 * S, 3);
      g.fillRect(rx - RW.half * S, rz1 - 5, RW.half * 2 * S, 3);
      const tex = new THREE.CanvasTexture(c);
      tex.encoding = THREE.sRGBEncoding;
      return tex;
    })();
    // --- palms (seeded, clear of runway / lagoon / mountain / start) ---
    const palms = [];
    let guard = 0;
    while (palms.length < 42 && guard++ < 1500) {
      const x = (rng() * 2 - 1) * 112, z = (rng() * 2 - 1) * 112;
      if (Math.hypot(x, z) > 114) continue;
      if (Math.abs(x) < 9 && z > RW.z0 - 8 && z < RW.z1 + 8) continue;
      if (Math.hypot(x - LAGOON.x, z - LAGOON.z) < LAGOON.r + 5) continue;
      if (Math.hypot(x - MOUNTAIN.x, z - MOUNTAIN.z) < MOUNTAIN.r + 5) continue;
      if (Math.hypot(x, z - 70) < 8) continue;
      let near = false;
      for (const t of palms) if (Math.hypot(t.x - x, t.z - z) < 6) { near = true; break; }
      if (near) continue;
      palms.push({ x, z, s: 0.8 + rng() * 0.7, lean: (rng() - 0.5) * 0.3 });
    }

    // --- DOM: canvas + HUD (panel, phase, speed, minimap, yoke, throttle, overlay) ---
    const wrap = document.createElement("div");
    wrap.className = "pl-wrap";
    stage.appendChild(wrap);
    const cv = document.createElement("canvas");
    cv.className = "pl-canvas";
    wrap.appendChild(cv);
    const panel = document.createElement("div");
    panel.className = "pl-panel";
    const pTitle = document.createElement("b");
    pTitle.textContent = "Controls";
    const pClose = document.createElement("button");
    pClose.className = "pl-x";
    pClose.textContent = "×";
    pClose.onclick = () => { panel.hidden = true; };
    panel.append(pTitle, pClose);
    [["↑ / ↓", "Throttle"], ["← →", "Steer (yoke)"],
     ["Drag yoke", "steer on touch"], ["Drag slider", "throttle on touch"]].forEach((r) => {
      const row = document.createElement("div");
      row.className = "pl-row";
      const k = document.createElement("span");
      k.className = "pl-key";
      k.textContent = r[0];
      const v = document.createElement("span");
      v.textContent = r[1];
      row.append(k, v);
      panel.appendChild(row);
    });
    wrap.appendChild(panel);
    const phaseEl = document.createElement("div");
    phaseEl.className = "pl-phase";
    const phaseMain = document.createElement("b");
    const phaseSub = document.createElement("span");
    phaseEl.append(phaseMain, phaseSub);
    wrap.appendChild(phaseEl);
    const speedEl = document.createElement("div");
    speedEl.className = "pl-speed";
    const speedNum = document.createElement("b");
    speedNum.textContent = "0";
    const speedUnit = document.createElement("span");
    speedUnit.textContent = "kt";
    const altEl = document.createElement("div");
    altEl.className = "pl-alt";
    altEl.textContent = "ALT 0 m · RINGS 0/3";
    speedEl.append(speedNum, speedUnit, altEl);
    wrap.appendChild(speedEl);
    const mapCv = document.createElement("canvas");
    mapCv.className = "pl-map";
    mapCv.width = 104; mapCv.height = 104;
    wrap.appendChild(mapCv);
    const mapCtx = mapCv.getContext("2d");
    const touch = document.createElement("div");
    touch.className = "pl-touch";
    const yoke = document.createElement("div");
    yoke.className = "pl-yoke";
    yoke.innerHTML = '<svg viewBox="0 0 100 100"><circle cx="50" cy="50" r="44" fill="none" stroke="#E2E8F0" stroke-width="7"/><line x1="50" y1="50" x2="50" y2="8" stroke="#CBD5E1" stroke-width="6" stroke-linecap="round"/><line x1="50" y1="50" x2="14" y2="71" stroke="#CBD5E1" stroke-width="6" stroke-linecap="round"/><line x1="50" y1="50" x2="86" y2="71" stroke="#CBD5E1" stroke-width="6" stroke-linecap="round"/><circle cx="50" cy="50" r="12" fill="#94A3B8"/><circle cx="50" cy="50" r="6" fill="#0D9488"/></svg>';
    const thr = document.createElement("div");
    thr.className = "pl-throttle";
    const thrTrack = document.createElement("div");
    thrTrack.className = "pl-thr-track";
    const thrHandle = document.createElement("div");
    thrHandle.className = "pl-thr-handle";
    thrTrack.appendChild(thrHandle);
    const thrLabel = document.createElement("div");
    thrLabel.className = "pl-thr-label";
    thrLabel.textContent = "THROTTLE";
    thr.append(thrTrack, thrLabel);
    touch.append(yoke, thr);
    wrap.appendChild(touch);
    const over = document.createElement("div");
    over.className = "pl-over";
    over.hidden = true;
    const overTitle = document.createElement("b");
    const overDetail = document.createElement("div");
    overDetail.className = "pl-over-detail";
    const overScore = document.createElement("div");
    overScore.className = "pl-over-score";
    const retryBtn = document.createElement("button");
    retryBtn.className = "pl-retry";
    retryBtn.textContent = "Retry";
    over.append(overTitle, overDetail, overScore, retryBtn);
    wrap.appendChild(over);
    // --- input: yoke drag (steer), throttle drag, keyboard ---
    const input = { left: false, right: false, thrUp: false, thrDown: false, yoke: 0 };
    let throttle = 0;
    let yokeStartX = null, yokeStart = 0;
    yoke.addEventListener("pointerdown", (e) => {
      if (e) e.preventDefault();
      yokeStartX = e.clientX; yokeStart = input.yoke;
      try { yoke.setPointerCapture(e.pointerId); } catch (err) {}
    });
    yoke.addEventListener("pointermove", (e) => {
      if (yokeStartX === null) return;
      input.yoke = Math.max(-1, Math.min(1, yokeStart + (e.clientX - yokeStartX) / 70));
    });
    const yokeEnd = () => { yokeStartX = null; input.yoke = 0; };
    yoke.addEventListener("pointerup", yokeEnd);
    yoke.addEventListener("pointercancel", yokeEnd);
    let thrDrag = false;
    const thrSet = (e) => {
      const r = thrTrack.getBoundingClientRect ? thrTrack.getBoundingClientRect() : { top: 0, height: 148 };
      const h = r.height || 148;
      throttle = Math.max(0, Math.min(1, 1 - (e.clientY - r.top) / h));
    };
    thrTrack.addEventListener("pointerdown", (e) => {
      if (e) e.preventDefault();
      thrDrag = true; thrSet(e);
      try { thrTrack.setPointerCapture(e.pointerId); } catch (err) {}
    });
    thrTrack.addEventListener("pointermove", (e) => { if (thrDrag) thrSet(e); });
    const thrEnd = () => { thrDrag = false; };
    thrTrack.addEventListener("pointerup", thrEnd);
    thrTrack.addEventListener("pointercancel", thrEnd);
    // --- Three.js scene ---
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x8ED6F2);
    scene.fog = new THREE.Fog(0x8ED6F2, 90, 260);
    const camera = new THREE.PerspectiveCamera(62, 3 / 2, 0.1, 500);
    const renderer = new THREE.WebGLRenderer({ canvas: cv, antialias: true, powerPreference: "low-power" });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.outputEncoding = THREE.sRGBEncoding;
    scene.add(new THREE.HemisphereLight(0xBFE3F2, 0x1E7A46, 0.95));
    const sun = new THREE.DirectionalLight(0xFFF2CC, 0.9);
    sun.position.set(60, 80, 40);
    scene.add(sun);
    const ground = new THREE.Mesh(
      new THREE.CircleGeometry(ISLAND_R, 48),
      new THREE.MeshLambertMaterial({ map: groundTex }));
    ground.rotation.x = -Math.PI / 2;
    scene.add(ground);
    const sea = new THREE.Mesh(
      new THREE.CircleGeometry(400, 48),
      new THREE.MeshLambertMaterial({ color: 0x35B5C9, emissive: 0x0E5A66 }));
    sea.rotation.x = -Math.PI / 2;
    sea.position.y = -0.15;
    scene.add(sea);
    const lagoon = new THREE.Mesh(
      new THREE.CircleGeometry(LAGOON.r, 28),
      new THREE.MeshLambertMaterial({ color: 0x3EC6C6, emissive: 0x0E5A66 }));
    lagoon.rotation.x = -Math.PI / 2;
    lagoon.position.set(LAGOON.x, 0.05, LAGOON.z);
    scene.add(lagoon);
    const mountain = new THREE.Mesh(
      new THREE.ConeGeometry(MOUNTAIN.r, MOUNTAIN.h, 9),
      new THREE.MeshLambertMaterial({ color: 0x5B7A4A, flatShading: true }));
    mountain.position.set(MOUNTAIN.x, MOUNTAIN.h / 2, MOUNTAIN.z);
    scene.add(mountain);
    const trunkGeo = new THREE.CylinderGeometry(0.22, 0.34, 3.6, 6);
    const trunkMat = new THREE.MeshLambertMaterial({ color: 0x6B4226 });
    const frondGeo = new THREE.ConeGeometry(0.55, 3.2, 4);
    const frondMat = new THREE.MeshLambertMaterial({ color: 0x2F8F4E, flatShading: true });
    for (const t of palms) {
      const trunk = new THREE.Mesh(trunkGeo, trunkMat);
      trunk.position.set(t.x, 1.8 * t.s, t.z);
      trunk.scale.setScalar(t.s);
      trunk.rotation.z = t.lean;
      scene.add(trunk);
      for (let i = 0; i < 4; i++) {
        const frond = new THREE.Mesh(frondGeo, frondMat);
        const a = i * Math.PI / 2 + 0.4;
        frond.position.set(t.x + Math.cos(a) * 1.1 * t.s, 4.0 * t.s, t.z + Math.sin(a) * 1.1 * t.s);
        frond.scale.setScalar(t.s);
        frond.rotation.z = Math.cos(a) * 1.1;
        frond.rotation.x = -Math.sin(a) * 1.1;
        scene.add(frond);
      }
    }
    const cloudMat = new THREE.MeshLambertMaterial({ color: 0xFFFFFF, emissive: 0x888888 });
    for (let i = 0; i < 8; i++) {
      const cx = (rng() * 2 - 1) * 120, cz = (rng() * 2 - 1) * 120, cy = 42 + rng() * 16;
      const c1 = new THREE.Mesh(new THREE.SphereGeometry(4 + rng() * 3, 8, 6), cloudMat);
      c1.position.set(cx, cy, cz); c1.scale.y = 0.45;
      const c2 = new THREE.Mesh(new THREE.SphereGeometry(3 + rng() * 2, 8, 6), cloudMat);
      c2.position.set(cx + 5, cy + 0.5, cz + 1); c2.scale.y = 0.45;
      scene.add(c1, c2);
    }
    // --- the teal-and-gold jet (primitives, nose faces +Z) ---
    const jet = new THREE.Group();
    const tealMat = new THREE.MeshLambertMaterial({ color: 0x0D9488 });
    const goldMat = new THREE.MeshLambertMaterial({ color: 0xF59E0B });
    const whiteMat = new THREE.MeshLambertMaterial({ color: 0xF8FAFC });
    const darkMat = new THREE.MeshLambertMaterial({ color: 0x1F2937 });
    const engineMat = new THREE.MeshLambertMaterial({ color: 0x334155 });
    const add = (geo, mat, x, y, z) => {
      const m = new THREE.Mesh(geo, mat);
      m.position.set(x, y, z);
      jet.add(m);
      return m;
    };
    const fus = add(new THREE.CylinderGeometry(0.55, 0.75, 5.2, 10), tealMat, 0, 1.0, 0);
    fus.rotation.x = Math.PI / 2;
    const nose = add(new THREE.ConeGeometry(0.55, 1.6, 10), tealMat, 0, 1.0, 3.4);
    nose.rotation.x = Math.PI / 2;
    const tailCone = add(new THREE.ConeGeometry(0.75, 1.2, 10), tealMat, 0, 1.0, -3.0);
    tailCone.rotation.x = -Math.PI / 2;
    add(new THREE.BoxGeometry(0.9, 0.5, 1.2), darkMat, 0, 1.45, 2.2);
    add(new THREE.BoxGeometry(7.6, 0.18, 1.5), whiteMat, 0, 0.85, 0.4);
    add(new THREE.BoxGeometry(3.0, 0.14, 0.9), whiteMat, 0, 1.0, -2.6);
    add(new THREE.BoxGeometry(0.16, 1.6, 1.2), goldMat, 0, 1.9, -2.7);
    add(new THREE.BoxGeometry(0.3, 0.2, 1.5), goldMat, -3.7, 0.85, 0.4);
    add(new THREE.BoxGeometry(0.3, 0.2, 1.5), goldMat, 3.7, 0.85, 0.4);
    [[-1.6, 0.6], [1.6, 0.6]].forEach((e) => {
      const eng = add(new THREE.CylinderGeometry(0.42, 0.42, 1.6, 10), engineMat, e[0], 0.55, e[1]);
      eng.rotation.x = Math.PI / 2;
    });
    const wheelGeo = new THREE.CylinderGeometry(0.28, 0.28, 0.2, 10);
    [[0, 2.2], [-0.8, -0.6], [0.8, -0.6]].forEach((w) => {
      const wh = add(wheelGeo, darkMat, w[0], 0.28, w[1]);
      wh.rotation.z = Math.PI / 2;
    });
    scene.add(jet);
    // --- the three golden rings ---
    const ringMeshes = RINGS.map((r) => {
      const mat = new THREE.MeshLambertMaterial({ color: 0xF59E0B, emissive: 0x7A4A00 });
      const mesh = new THREE.Mesh(new THREE.TorusGeometry(6, 0.5, 8, 24), mat);
      mesh.position.set(r.x, r.y, r.z);
      scene.add(mesh);
      return mesh;
    });

    // --- arcade flight model + chase camera + HUD ---
    let best = +(nxGet("nx_planelanding_best") || 0);
    setScore("✈️ Score: 0 · Best: " + best);
    const pos = { x: 0, z: 70 };
    let y = 0, heading = Math.PI, speed = 0, vy = 0;
    let airborne = false, phase = "TAXI", score = 0, ringsGot = 0, steerVis = 0;
    const camTarget = new THREE.Vector3(0, 4.5, 81);
    camera.position.set(0, 4.5, 81);
    camera.lookAt(0, 1, 62);
    const addScore = (n) => {
      score += n;
      if (score > best) { best = score; nxSet("nx_planelanding_best", best); }
      setScore("✈️ Score: " + score + " · Best: " + best);
    };
    const showOver = (title, detail) => {
      over.hidden = false;
      overTitle.textContent = title;
      overDetail.textContent = detail;
      overScore.textContent = "Score: " + score + " · Best: " + best;
    };
    const crash = (reason) => {
      if (phase === "CRASH" || phase === "DONE") return;
      phase = "CRASH";
      showOver("Crashed!", reason);
    };
    const finish = () => {
      if (phase === "DONE") return;
      phase = "DONE";
      showOver("Landed!", "Smooth touchdown — welcome to the island!");
    };
    const reset = () => {
      pos.x = 0; pos.z = 70; y = 0; heading = Math.PI; speed = 0; vy = 0;
      throttle = 0; input.yoke = 0;
      score = 0; ringsGot = 0; airborne = false; phase = "TAXI";
      for (let i = 0; i < RINGS.length; i++) {
        RINGS[i].done = false;
        ringMeshes[i].material.color.set(0xF59E0B);
      }
      over.hidden = true;
      setScore("✈️ Score: 0 · Best: " + best);
    };
    retryBtn.onclick = () => reset();
    const PHASE_TEXT = {
      TAXI: ["Taxi", "Throttle up — roll down the runway"],
      TAKEOFF: ["Takeoff!", "Keep her straight"],
      FLY: ["Fly the rings", ""],
      LAND: ["Land now", "Gentle — on the centreline"],
      ROLLOUT: ["Rolling out…", ""],
      DONE: ["Landed!", ""],
      CRASH: ["Crashed!", ""],
    };
    const ARROWS = ["↑", "↗", "→", "↘", "↓", "↙", "←", "↖"];
    const nextTarget = () => {
      for (let i = 0; i < RINGS.length; i++) {
        if (!RINGS[i].done) return { x: RINGS[i].x, z: RINGS[i].z, label: "Ring " + (i + 1) };
      }
      return { x: 0, z: 0, label: "Runway" };
    };
    let lastKt = -1, lastAlt = "", lastPhaseMain = "", lastPhaseSub = "";
    const syncHud = () => {
      const kt = Math.round(speed * 1.94);
      if (kt !== lastKt) { lastKt = kt; speedNum.textContent = String(kt); }
      const altTxt = "ALT " + Math.round(y) + " m · RINGS " + ringsGot + "/3";
      if (altTxt !== lastAlt) { lastAlt = altTxt; altEl.textContent = altTxt; }
      const ph = PHASE_TEXT[phase] || PHASE_TEXT.TAXI;
      const tgt = nextTarget();
      const bearing = Math.atan2(tgt.x - pos.x, tgt.z - pos.z);
      let rel = heading - bearing;
      while (rel > Math.PI) rel -= 2 * Math.PI;
      while (rel < -Math.PI) rel += 2 * Math.PI;
      const ai = ((Math.round(rel / (Math.PI / 4)) % 8) + 8) % 8;
      const sub = (phase === "FLY" || phase === "LAND")
        ? ARROWS[ai] + " " + tgt.label + " · " + Math.round(Math.hypot(tgt.x - pos.x, tgt.z - pos.z)) + " m"
        : ph[1];
      const main = ph[0] + (phase === "FLY" ? " " + ringsGot + "/3" : "");
      if (main !== lastPhaseMain) { lastPhaseMain = main; phaseMain.textContent = main; }
      if (sub !== lastPhaseSub) { lastPhaseSub = sub; phaseSub.textContent = sub; }
      yoke.style.transform = "rotate(" + Math.round(steerVis * 65) + "deg)";
      const th = thrTrack.clientHeight || 148;
      thrHandle.style.top = Math.round((1 - throttle) * (th - 34)) + "px";
    };
    const drawMinimap = () => {
      const S = 104 / WORLD;
      mapCtx.clearRect(0, 0, 104, 104);
      mapCtx.fillStyle = "rgba(6, 26, 17, 0.78)";
      mapCtx.fillRect(0, 0, 104, 104);
      mapCtx.fillStyle = "#1E7A46";
      mapCtx.beginPath();
      mapCtx.arc(52, 52, ISLAND_R * S, 0, 6.2832);
      mapCtx.fill();
      mapCtx.fillStyle = "#3EC6C6";
      mapCtx.beginPath();
      mapCtx.arc((LAGOON.x + 130) * S, (LAGOON.z + 130) * S, LAGOON.r * S, 0, 6.2832);
      mapCtx.fill();
      mapCtx.fillStyle = "#3A3F45";
      mapCtx.fillRect((0 + 130) * S - 2, (RW.z0 + 130) * S, 4, (RW.z1 - RW.z0) * S);
      mapCtx.fillStyle = "#2F8F4E";
      for (const t of palms) mapCtx.fillRect((t.x + 130) * S - 1, (t.z + 130) * S - 1, 2, 2);
      for (let i = 0; i < RINGS.length; i++) {
        const r = RINGS[i];
        mapCtx.fillStyle = r.done ? "#22C55E" : "#F59E0B";
        mapCtx.beginPath();
        mapCtx.arc((r.x + 130) * S, (r.z + 130) * S, 3.5, 0, 6.2832);
        mapCtx.fill();
      }
      const jx = (pos.x + 130) * S, jz = (pos.z + 130) * S;
      mapCtx.strokeStyle = "#FFFFFF";
      mapCtx.lineWidth = 1.5;
      mapCtx.beginPath();
      mapCtx.moveTo(jx, jz);
      mapCtx.lineTo(jx + Math.sin(heading) * 7, jz + Math.cos(heading) * 7);
      mapCtx.stroke();
      mapCtx.fillStyle = "#F8FAFC";
      mapCtx.beginPath();
      mapCtx.arc(jx, jz, 3, 0, 6.2832);
      mapCtx.fill();
    };
    const step = (dt) => {
      if (phase === "CRASH" || phase === "DONE") {
        renderer.render(scene, camera);
        return;
      }
      const steerKey = (input.right ? 1 : 0) - (input.left ? 1 : 0);
      const steer = Math.max(-1, Math.min(1, steerKey + input.yoke));
      steerVis = steer;
      if (input.thrUp) throttle = Math.min(1, throttle + 0.7 * dt);
      if (input.thrDown) throttle = Math.max(0, throttle - 0.7 * dt);
      const turn = airborne
        ? 0.55 * (0.45 + Math.min(1, speed / 42))
        : 0.5 * (0.35 + Math.min(1, speed / 30));
      heading -= steer * turn * dt;
      const fx = Math.sin(heading), fz = Math.cos(heading);
      if (!airborne) {
        if (phase === "ROLLOUT") {
          speed = Math.max(0, speed - 14 * dt);
          if (speed < 0.5) finish();
        } else {
          speed += throttle * 18 * dt;
          speed -= speed * 0.22 * dt;
          if (speed > 30) speed = 30;
          if (speed < 0) speed = 0;
          if (speed >= 26 && throttle >= 0.55) {
            airborne = true; vy = 2.5; phase = "FLY";
          }
        }
      } else {
        const target = 12 + throttle * 30;
        speed += Math.max(-10 * dt, Math.min(10 * dt, target - speed));
        const vyT = Math.max(-8, Math.min(8, (throttle - 0.52) * 16));
        vy += Math.max(-6 * dt, Math.min(6 * dt, vyT - vy));
        if (y > 60 && vy > 0) vy = 0;
        y += vy * dt;
      }
      pos.x += fx * speed * dt;
      pos.z += fz * speed * dt;
      if (phase === "TAXI" && speed > 5) phase = "TAKEOFF";
      if (airborne) {
        for (let i = 0; i < RINGS.length; i++) {
          const r = RINGS[i];
          if (!r.done) {
            const d = Math.hypot(pos.x - r.x, y - r.y, pos.z - r.z);
            if (d < 7) {
              r.done = true;
              ringMeshes[i].material.color.set(0x22C55E);
              addScore(100);
              ringsGot++;
              if (ringsGot === RINGS.length) phase = "LAND";
            }
          }
        }
        if (y < 7) {
          for (const t of palms) {
            if (Math.hypot(pos.x - t.x, pos.z - t.z) < 2.4) {
              crash("You hit a palm tree!");
              break;
            }
          }
        }
        if (phase !== "CRASH" && y < 20 &&
            Math.hypot(pos.x - MOUNTAIN.x, pos.z - MOUNTAIN.z) < MOUNTAIN.r) {
          crash("You hit the mountain!");
        }
        if (phase !== "CRASH" && y <= 0 && vy < 0) {
          y = 0;
          const overSea = Math.hypot(pos.x, pos.z) > ISLAND_R + 4;
          const onRunway = Math.abs(pos.x) <= RW.half && pos.z >= RW.z0 && pos.z <= RW.z1;
          if (overSea) crash("Ditched in the sea!");
          else if (!onRunway) crash("Off the runway!");
          else if (vy < -5) crash("Too hard — the landing gear gave way!");
          else {
            const bonus = Math.max(100, Math.round(500 - Math.abs(pos.x) * 45 - Math.abs(vy) * 55));
            addScore(bonus);
            airborne = false; vy = 0; phase = "ROLLOUT";
          }
        }
      }
      jet.position.set(pos.x, y, pos.z);
      jet.rotation.y = heading;
      jet.rotation.z = steerVis * 0.45;
      jet.rotation.x = -vy * 0.02;
      camTarget.set(pos.x - fx * 11, 4.5 + y * 0.55, pos.z - fz * 11);
      camera.position.lerp(camTarget, 1 - Math.pow(0.001, dt));
      camera.lookAt(pos.x + fx * 8, 1 + y * 0.8, pos.z + fz * 8);
      syncHud();
      drawMinimap();
      renderer.render(scene, camera);
    };
    const KEYS = { KeyW: "thrUp", ArrowUp: "thrUp", KeyS: "thrDown", ArrowDown: "thrDown",
                   KeyA: "left", ArrowLeft: "left", KeyD: "right", ArrowRight: "right" };
    const onKeyDown = (e) => {
      const k = KEYS[e.code];
      if (!k) return;
      e.preventDefault();
      input[k] = true;
    };
    const onKeyUp = (e) => {
      const k = KEYS[e.code];
      if (k) input[k] = false;
    };
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);
    const sizeRenderer = () => {
      const w = wrap.clientWidth || 360;
      // Phase 197: in the immersive game view the wrap fills
      // the screen, so the canvas fills the wrap instead of a
      // fixed 3:2 box. The node harness has no getElementById
      // — guard it — and fall back to 3:2 whenever the wrap
      // has no laid-out height yet.
      const _vg209 = (typeof document !== "undefined" && document.getElementById)
        ? document.getElementById("view-game") : null;
      const _imm209 = !!(_vg209 && _vg209.classList && _vg209.classList.contains("immersive"));
      const h = (_imm209 && wrap.clientHeight > 0)
        ? wrap.clientHeight : Math.round(w * 2 / 3);
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    };
    sizeRenderer();
    const onResize = () => sizeRenderer();
    window.addEventListener("resize", onResize);
    let raf = 0, dead = false, paused = false, last = 0;
    const loop = (t) => {
      if (dead || paused) return;
      const dt = Math.min(0.05, Math.max(0, last ? (t - last) / 1000 : 0.016));
      last = t;
      step(dt);
      raf = requestAnimationFrame(loop);
    };
    const onVis = () => {
      if (document.hidden) { paused = true; cancelAnimationFrame(raf); }
      else if (!dead) { paused = false; last = 0; raf = requestAnimationFrame(loop); }
    };
    document.addEventListener("visibilitychange", onVis);
    raf = requestAnimationFrame(loop);
    const cleanup = () => {
      dead = true;
      cancelAnimationFrame(raf);
      document.removeEventListener("visibilitychange", onVis);
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup", onKeyUp);
      window.removeEventListener("resize", onResize);
      renderer.dispose();
      scene.traverse((o) => {
        if (o.geometry && o.geometry.dispose) o.geometry.dispose();
        if (o.material) {
          const ms = Array.isArray(o.material) ? o.material : [o.material];
          ms.forEach((m) => { if (m.map && m.map.dispose) m.map.dispose(); if (m.dispose) m.dispose(); });
        }
      });
    };
    // Test hook (handy while tuning too): read-only state + teleport.
    cleanup._pl = {
      state: () => ({ x: pos.x, y, z: pos.z, speed, vy, throttle, heading, airborne, phase, rings: ringsGot, score, best }),
      setInput: (k, v) => { input[k] = v; },
      setThrottle: (v) => { throttle = v; },
      teleport: (x, yy, z, h) => { pos.x = x; y = yy; pos.z = z; if (typeof h === "number") heading = h; speed = 0; vy = 0; if (yy > 0) airborne = true; },
      palms: () => palms.map((t) => ({ x: t.x, z: t.z, s: t.s })),
      rings: () => RINGS.map((r) => ({ x: r.x, y: r.y, z: r.z, done: r.done })),
    };
    return cleanup;
  }
});

// Built last: every game above must be registered first.
(function buildGrid() {
  const grid = $("game-grid");
  GameRegistry.forEach(g => {
    const card = document.createElement("button");
    card.className = "game-card";
    const ic = document.createElement("div");
    ic.className = "g-icon";
    ic.innerHTML = g.icon;
    const nm = document.createElement("div");
    nm.className = "g-name";
    nm.textContent = g.name;
    const ds = document.createElement("div");
    ds.className = "g-desc";
    ds.textContent = g.desc;
    const pl = document.createElement("span");
    pl.className = "g-play";
    pl.textContent = "▶ Play";
    card.append(ic, nm, ds, pl);
    card.onclick = () => openGame(g.id);
    grid.appendChild(card);
  });
  $("game-back").onclick = () => showView("games");
})();

// --------------------------------------------- Phase 37: the Games lamp --
// Owner: the Games section opens in darkness with only a lamp
// visible and a rope hanging beside it — pull the rope, the light
// comes on, and only then do the games appear. Once lit it stays
// lit for the rest of the session; a fresh app launch starts
// dark again.
(function () {
  const dark = document.getElementById("games-dark");
  if (!dark) return;
  const grid = document.getElementById("game-grid");
  if (sessionStorage.getItem("nx_games_lit") === "1") {
    dark.hidden = true;
    return;
  }
  if (grid) grid.style.visibility = "hidden";
  const rope = document.getElementById("pull-rope");
  let startY = null;
  let dy = 0;
  function lightOn() {
    if (dark.classList.contains("lit")) return;
    dark.classList.add("lit");
    sessionStorage.setItem("nx_games_lit", "1");
    setTimeout(() => { dark.style.opacity = "0"; }, 600);
    setTimeout(() => {
      dark.hidden = true;
      if (grid) grid.style.visibility = "";
    }, 950);
  }
  rope.addEventListener("pointerdown", e => {
    startY = e.clientY;
    dy = 0;
    rope.style.transition = "none";
    try { rope.setPointerCapture(e.pointerId); } catch (err) {}
    e.preventDefault();
  });
  rope.addEventListener("pointermove", e => {
    if (startY === null) return;
    dy = Math.max(0, Math.min(64, e.clientY - startY));
    rope.style.transform = "translateY(" + dy + "px)";
  });
  function release() {
    if (startY === null) return;
    const pulled = dy;
    startY = null;
    rope.style.transition =
      "transform .35s cubic-bezier(.2, 2.2, .4, 1)";
    rope.style.transform = "";
    if (pulled > 30) lightOn();
  }
  rope.addEventListener("pointerup", release);
  rope.addEventListener("pointercancel", release);
  rope.addEventListener("click", lightOn);
})();
