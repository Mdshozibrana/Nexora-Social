// Nexora Social — classic button-phone games (owner request, Oct 31):
// the favourites from the first mobile phones. Pure client-side, no
// backend: Snake (Nokia), Tetris (brick game), Breakout, Memory match.
const GameRegistry = [];
function registerGame(def) { GameRegistry.push(def); }

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
  $("game-title").textContent = def.title;
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
  id: "snake", icon: "🐍", name: "Snake", title: "🐍 Snake",
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
    toggleBtn.style.cssText = "padding:10px 22px;border-radius:12px;font-size:15px;background:linear-gradient(120deg,#4f46e5,#db2777);color:#fff;font-weight:700;";
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
  id: "tetris", icon: "🧱", name: "Tetris", title: "🧱 Tetris",
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
      ctx.fillStyle = "#14141f";
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
    tBtn.style.cssText = "padding:10px 22px;border-radius:12px;font-size:15px;background:linear-gradient(120deg,#4f46e5,#db2777);color:#fff;font-weight:700;";
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
  id: "breakout", icon: "🏓", name: "Breakout", title: "🏓 Breakout",
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
      ctx.fillStyle = "#14141f";
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
    tBtn.style.cssText = "padding:10px 22px;border-radius:12px;font-size:15px;background:linear-gradient(120deg,#4f46e5,#db2777);color:#fff;font-weight:700;";
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
  id: "memory", icon: "🃏", name: "Memory", title: "🃏 Memory Match",
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
    again.style.cssText = "padding:10px 22px;border-radius:12px;font-size:15px;background:linear-gradient(120deg,#4f46e5,#db2777);color:#fff;font-weight:700;";
    again.onclick = () => openGame("memory");
    const wrap = document.createElement("div");
    wrap.className = "grow";
    wrap.appendChild(again);
    stage.appendChild(wrap);
    return () => {};
  },
});

// ------------------------------------------------------------- game grid --
// Built last: every game above must be registered first.
(function buildGrid() {
  const grid = $("game-grid");
  GameRegistry.forEach(g => {
    const card = document.createElement("button");
    card.className = "game-card";
    const ic = document.createElement("div");
    ic.className = "g-icon";
    ic.textContent = g.icon;
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
