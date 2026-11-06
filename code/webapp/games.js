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
  id: "pong", icon: "🎾", name: "Pong", title: "🎾 Pong",
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
      ctx.fillStyle = "#101408";
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
  id: "invaders", icon: "👾", name: "Invaders", title: "👾 Space Invaders",
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
      ctx.fillStyle = "#070714";
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
        ctx.fillStyle = "rgba(7,7,20,.85)";
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
  id: "mines", icon: "💣", name: "Minesweeper", title: "💣 Minesweeper",
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
  id: "flappy", icon: "🐦", name: "Flappy", title: "🐦 Flappy Bird",
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
  id: "g2048", icon: "🔢", name: "2048", title: "🔢 2048",
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
  id: "pacman", icon: "🟡", name: "Pac-Man", title: "🟡 Pac-Man",
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
      ctx.fillStyle = "#0B1035";
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
        ctx.fillStyle = "rgba(7,7,20,.85)";
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
  id: "archery", icon: "🏹", name: "Archery",
  title: "🏹 Archery — Aim Less, Shoot More",
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
    const PCOL = ["#FFFFFF", "#FF8FBE"];
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
    let best = +(localStorage.getItem("nx_archery_best") || 0);
    let bestLevel = +(localStorage.getItem("nx_archery_level") || 1);
    // Phase 94 (owner: "যে লেভেলে রেখে আসবো সেখান থেকে পরে
    // আসে না কেনো"): bestLevel above is only a display
    // record — the run itself always restarted at Level 1.
    // Now the solo run is saved as {level, banked} and
    // RESUMED on open; a 🆕 New run button starts over.
    let resumed = false;
    const loadRun = () => {
      try {
        const r = JSON.parse(
          localStorage.getItem("nx_archery_run") || "null");
        return r && r.level >= 1 ? r : null;
      } catch (e) { return null; }
    };
    const saveRun = (lv, bk) => {
      if (mode !== "solo") return;
      try {
        localStorage.setItem("nx_archery_run",
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
        localStorage.setItem("nx_archery_level", bestLevel);
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
          burst(arrow.x, arrow.y, ["#FFD93D", "#FF8FBE", "#FFFFFF"], 16);
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
            localStorage.setItem("nx_archery_best", best);
          }
          burst(TGT.x, TGT.y, ["#FFD93D", "#FF8FBE", "#7BE0A3", "#FFFFFF"], 70);
          state = "clear"; noteT = 110;
          saveRun(level + 1, banked);
        } else {
          if (banked + scores[0] > best) {
            best = banked + scores[0];
            localStorage.setItem("nx_archery_best", best);
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
        ctx.fillStyle = scores[0] >= cfg.quota ? "#7BE0A3" : "#FF8FBE";
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
           "bold 13px system-ui", "#FF8FBE", 34],
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
