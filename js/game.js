/* Элвин и бурундуки — платформер в духе NES «Чип и Дейл».
 * Оружия нет: всё решают ящики — поднять, бросить, спрятаться внутри.
 */

const GRAV = 0.46;
const HOLD_GRAV = 0.30;
const MAX_FALL = 7.0;
const RUN_SPEED = 1.6;
const ACCEL = 0.28;
const FRICTION = 0.22;
const JUMP_V = -6.0;
const THROW_VX = 4.2;

const CHARS = [
  { id: "alvin", name: "Элвин", color: "#d8342c", accent: "#f2d24b" },
  { id: "simon", name: "Саймон", color: "#2f6fd0", accent: "#e8e8e8" },
  { id: "theodore", name: "Теодор", color: "#3f9a4a", accent: "#f0a63c" },
];

/* ------------------------- ввод ------------------------- */
const Input = {
  keys: new Set(),
  pressed: new Set(),
  init() {
    window.addEventListener("keydown", (e) => {
      if (!this.keys.has(e.code)) this.pressed.add(e.code);
      this.keys.add(e.code);
      if (["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Space"].includes(e.code)) {
        e.preventDefault();
      }
      Sound.ctxInit();
    });
    window.addEventListener("keyup", (e) => this.keys.delete(e.code));
    window.addEventListener("blur", () => this.keys.clear());
  },
  down(code) { return this.keys.has(code); },
  hit(code) { return this.pressed.has(code); },
  clearFrame() { this.pressed.clear(); },
};

function makeControls() {
  return {
    p1: { left: "ArrowLeft", right: "ArrowRight", up: "ArrowUp", down: "ArrowDown", jump: "KeyZ", action: "KeyX" },
    p2: { left: "KeyA", right: "KeyD", up: "KeyW", down: "KeyS", jump: "KeyW", action: "KeyC" },
  };
}

/* ------------------------- сущности ------------------------- */
class Entity {
  constructor(x, y, w, h) {
    this.x = x; this.y = y; this.w = w; this.h = h;
    this.vx = 0; this.vy = 0;
    this.dead = false;
    this.facing = 1;
    this.onGround = false;
  }

  get cx() { return this.x + this.w / 2; }
  get cy() { return this.y + this.h / 2; }
  get by() { return this.y + this.h; }

  moveAndCollide(world, { gravity = GRAV } = {}) {
    // по горизонтали
    this.x += this.vx;
    if (world.rectHits(this.x, this.y, this.w, this.h)) {
      const step = this.vx > 0 ? -0.5 : 0.5;
      while (world.rectHits(this.x, this.y, this.w, this.h)) this.x += step;
      this.vx = 0;
    }
    // по вертикали
    this.vy = Math.min(this.vy + gravity, MAX_FALL);
    this.y += this.vy;
    this.onGround = false;
    if (world.rectHits(this.x, this.y, this.w, this.h)) {
      const step = this.vy > 0 ? -0.5 : 0.5;
      while (world.rectHits(this.x, this.y, this.w, this.h)) this.y += step;
      if (this.vy > 0) this.onGround = true;
      this.vy = 0;
    }
    if (this.y > world.height + 40) this.dead = true; // улетел в яму
  }
}

class Crate extends Entity {
  constructor(x, y) {
    super(x, y, 16, 16);
    this.state = "rest"; // rest | held | thrown | broken
    this.spin = 0;
    this.holder = null;
  }

  update(world, game) {
    if (this.state === "held" && this.holder) {
      const h = this.holder;
      this.x = h.cx - 8;
      this.y = h.y - 15;
      this.facing = h.facing;
      return;
    }
    if (this.state === "thrown") {
      this.spin += 0.35 * this.facing;
      this.moveAndCollide(world, { gravity: 0.30 });
      if (this.vx === 0) { // ударился о стену
        this.shatter(game);
        return;
      }
      if (this.onGround) { // приземлился — снова можно взять
        this.state = "rest";
        this.spin = 0;
        this.vx = 0;
        return;
      }
      this.vx = this.facing * THROW_VX; // летит по прямой
    }
    if (this.state === "rest") {
      this.moveAndCollide(world, { gravity: GRAV });
    }
  }

  shatter(game) {
    this.state = "broken";
    this.dead = true;
    Sound.crateBreak();
    for (let i = 0; i < 6; i += 1) {
      game.particles.push(new Particle(this.cx, this.y + 8, -1.6 + i * 0.6, -2.2 - (i % 3) * 0.7));
    }
  }
}

class Particle {
  constructor(x, y, vx, vy) {
    this.x = x; this.y = y; this.vx = vx; this.vy = vy; this.life = 32;
  }
  update() {
    this.vy += 0.28;
    this.x += this.vx;
    this.y += this.vy;
    this.life -= 1;
  }
}

class Item extends Entity {
  constructor(type, x, y) {
    super(x, y, 12, 12);
    this.type = type;
    this.bob = Math.random() * Math.PI * 2;
  }
  update() { this.bob += 0.09; }
}

class Enemy extends Entity {
  constructor(type, x, y, opts = {}) {
    super(x, y, 14, 14);
    this.type = type;
    this.from = (opts.from ?? 0) * TILE;
    this.to = (opts.to ?? 0) * TILE;
    this.baseY = y;
    this.timer = 0;
    this.speed = type === "bulldog" ? 0.5 : 0.55;
    this.charge = 0;
    this.dive = 0;
    this.vx = this.speed;
  }

  update(world, game) {
    this.timer += 1;
    const players = game.players.filter((p) => !p.dead);

    if (this.type === "bulldog") {
      const target = players.find((p) => Math.abs(p.cy - this.cy) < 24 && Math.abs(p.cx - this.cx) < 130);
      if (target) {
        this.charge = 60;
        this.facing = target.cx > this.cx ? 1 : -1;
      } else if (this.charge > 0) {
        this.charge -= 1;
      }
      const speed = this.charge > 0 ? 1.35 : this.speed;
      this.vx = speed * this.facing;
    } else if (this.type === "rat") {
      this.vx = this.speed * this.facing;
      const near = players.some((p) => Math.abs(p.cx - this.cx) < 90);
      if (this.onGround && this.timer % (near ? 45 : 110) === 0) this.vy = -4.4;
    } else if (this.type === "bee") {
      this.vx = this.speed * this.facing;
      this.y = this.baseY + Math.sin(this.timer / 22) * 10;
      const target = players.find((p) => Math.abs(p.cx - this.cx) < 110 && p.cy > this.cy);
      if (target) this.dive = 40;
      if (this.dive > 0) {
        this.dive -= 1;
        this.vy = 2.1;
        this.y += this.vy;
      }
    }

    if (this.type !== "bee") {
      this.moveAndCollide(world, { gravity: GRAV });
      if (this.x <= this.from || this.x + this.w >= this.to + TILE) this.facing *= -1;
      if (this.vx === 0) this.facing *= -1; // упёрся в стену
    } else {
      this.x += this.vx;
      if (this.x <= this.from || this.x + this.w >= this.to + TILE) this.facing *= -1;
      if (this.y > this.baseY + 90) this.y = this.baseY - 60;
    }
    this.x = Math.max(0, Math.min(this.x, world.width - this.w));
  }

  hit(game) {
    this.dead = true;
    game.score += 200;
    Sound.crateBreak();
    for (let i = 0; i < 5; i += 1) {
      game.particles.push(new Particle(this.cx, this.cy, -1.4 + i * 0.7, -1.8 - (i % 2)));
    }
  }
}

class Player extends Entity {
  constructor(char, controls, x, y) {
    super(x, y, 12, 16);
    this.char = char;
    this.controls = controls;
    this.hearts = 3;
    this.lives = 3;
    this.score = 0;
    this.anim = "stand";
    this.animTime = 0;
    this.invuln = 0;
    this.holding = null;
    this.ducking = false;
    this.spawn = { x, y };
    this.lastSafe = { x, y };
  }

  get cy() { return this.y + this.h / 2; }

  /** Возврат на безопасное место (после ямы или потери жизни). */
  respawnAt(pos) {
    this.x = pos.x;
    this.y = pos.y;
    this.vx = 0;
    this.vy = 0;
    this.invuln = 90;
    this.ducking = false;
    if (this.holding) {
      this.holding.state = "rest";
      this.holding.holder = null;
      this.holding = null;
    }
  }

  respawn() {
    this.hearts = 3;
    this.respawnAt(this.spawn);
  }

  /** Ящики, стоящие на земле, — твёрдые: на них можно стоять, они загораживают путь. */
  resolveCrates(game) {
    for (const crate of game.crates) {
      if (crate.state !== "rest" || crate.dead) continue;
      const overlapX = this.x < crate.x + crate.w && this.x + this.w > crate.x;
      const overlapY = this.y < crate.y + crate.h && this.y + this.h > crate.y;
      if (!overlapX || !overlapY) continue;

      const penTop = (this.y + this.h) - crate.y;   // сколько влезли сверху
      const penBottom = (crate.y + crate.h) - this.y;
      const penLeft = (this.x + this.w) - crate.x;
      const penRight = (crate.x + crate.w) - this.x;
      const minPen = Math.min(penTop, penBottom, penLeft, penRight);

      if (minPen === penTop && this.vy >= 0) {
        this.y = crate.y - this.h;
        this.vy = 0;
        this.onGround = true;
      } else if (minPen === penBottom && this.vy < 0) {
        this.y = crate.y + crate.h;
        this.vy = 0;
      } else if (minPen === penLeft) {
        this.x = crate.x - this.w;
        this.vx = 0;
      } else {
        this.x = crate.x + crate.w;
        this.vx = 0;
      }
    }
  }

  damage(game, source) {
    if (this.invuln > 0 || this.dead) return;
    if (this.ducking && this.holding) { // ящик-укрытие: гасит удар, враг гибнет
      this.holding.shatter(game);
      this.holding = null;
      this.ducking = false;
      if (source instanceof Enemy) source.hit(game);
      this.invuln = 45;
      return;
    }
    this.hearts -= 1;
    this.invuln = 90;
    Sound.damage();
    if (this.hearts <= 0) {
      this.lives -= 1;
      if (this.lives < 0) {
        this.dead = true;
        game.players.forEach((p) => { p.dead = true; });
        game.state = "gameover";
        Sound.stopMusic();
        Sound.gameover();
      } else {
        this.respawn();
      }
    }
  }

  pickupNearby(game) {
    if (this.holding) return;
    let best = null;
    let bestDist = 22;
    for (const crate of game.crates) {
      if (crate.state !== "rest") continue;
      const dist = Math.hypot(crate.cx - this.cx, crate.cy - this.cy);
      if (dist < bestDist && Math.abs(crate.by - this.by) < 26) {
        best = crate;
        bestDist = dist;
      }
    }
    if (best) {
      best.state = "held";
      best.holder = this;
      this.holding = best;
      Sound.beep({ freq: 420, dur: 0.06 });
    }
  }

  throwCrate() {
    const crate = this.holding;
    if (!crate) return;
    crate.state = "thrown";
    crate.holder = null;
    crate.facing = this.facing;
    crate.vx = THROW_VX * this.facing;
    crate.vy = -0.8;
    this.holding = null;
    this.ducking = false;
    Sound.throwCrate();
  }

  update(world, game) {
    if (this.dead || this.invuln === -999) return;
    const c = this.controls;
    if (this.invuln > 0) this.invuln -= 1;

    if (this.ducking) {
      this.vx = 0;
      this.vy = 0;
      if (Input.hit(c.action)) { // выпрыгнуть из укрытия
        this.ducking = false;
      }
      // пока сидим в ящике — враг, коснувшийся укрытия, гибнет сам
      for (const enemy of game.enemies) {
        if (!enemy.dead && this.overlaps(enemy)) this.damage(game, enemy);
      }
      return;
    }

    const moveLeft = Input.down(c.left);
    const moveRight = Input.down(c.right);
    const wantJump = Input.hit(c.jump);
    const wantAction = Input.hit(c.action);
    const wantDuck = Input.down(c.down);

    if (moveLeft && !moveRight) {
      this.vx -= ACCEL;
      this.facing = -1;
    } else if (moveRight && !moveLeft) {
      this.vx += ACCEL;
      this.facing = 1;
    } else {
      if (Math.abs(this.vx) < FRICTION) this.vx = 0;
      else this.vx -= Math.sign(this.vx) * FRICTION;
    }
    this.vx = Math.max(-RUN_SPEED, Math.min(RUN_SPEED, this.vx));

    if (wantJump && this.onGround) {
      this.vy = JUMP_V;
      Sound.jump();
    }
    // удержание прыжка — выше прыжок
    const gravity = (this.vy < 0 && Input.down(c.jump)) ? HOLD_GRAV : GRAV;

    if (wantAction) {
      if (this.holding) this.throwCrate();
      else this.pickupNearby(game);
    }
    if (wantDuck && this.holding) {
      this.ducking = true;
    }

    this.moveAndCollide(world, { gravity });
    this.resolveCrates(game);

    // запоминаем безопасное место, пока стоим на твёрдой земле
    if (this.onGround && world.groundBelow(this.x, this.y + this.h, this.w)) {
      this.lastSafe = { x: this.x, y: this.y };
    }

    // анимация
    if (!this.onGround) this.anim = "jump";
    else if (this.holding) this.anim = "run2";
    else if (Math.abs(this.vx) > 0.25) {
      this.animTime += Math.abs(this.vx);
      this.anim = Math.floor(this.animTime / 6) % 2 === 0 ? "run1" : "run2";
    } else this.anim = "stand";

    // упал в яму: теряем сердце и возвращаемся на безопасное место
    if (this.dead) {
      this.dead = false;
      this.hearts -= 1;
      Sound.damage();
      if (this.hearts <= 0) {
        this.lives -= 1;
        this.hearts = 3;
        if (this.lives < 0) {
          game.state = "gameover";
          Sound.stopMusic();
          Sound.gameover();
          return;
        }
        this.respawnAt(this.spawn);
      } else {
        this.respawnAt(this.lastSafe);
      }
      return;
    }

    // предметы
    for (const item of game.items) {
      if (item.dead) continue;
      if (Math.hypot(item.cx - this.cx, item.cy - this.cy) < 14) {
        item.dead = true;
        if (item.type === "acorn") {
          this.hearts = Math.min(3, this.hearts + 1);
          game.score += 50;
        } else {
          game.score += item.type === "flower" ? 100 : 50;
        }
        Sound.item();
      }
    }

    // враги
    for (const enemy of game.enemies) {
      if (enemy.dead) continue;
      if (this.overlaps(enemy)) this.damage(game, enemy);
    }

    // выход
    const door = game.door;
    if (door && Math.abs(this.cx - door.x) < 14 && Math.abs(this.by - door.y) < 24) {
      game.state = "victory";
      Sound.stopMusic();
      Sound.victory();
    }
  }

  overlaps(other) {
    return this.x < other.x + other.w && this.x + this.w > other.x
      && this.y < other.y + other.h && this.y + this.h > other.y;
  }
}

/* ------------------------- рисование ------------------------- */
const Draw = {
  sprite(ctx, name, x, y, w, h, flip = false) {
    const img = SpriteBank.get(name);
    if (img) {
      ctx.save();
      if (flip) {
        ctx.translate(Math.round(x + w), Math.round(y));
        ctx.scale(-1, 1);
        ctx.drawImage(img, 0, 0, w, h);
      } else {
        ctx.drawImage(img, Math.round(x), Math.round(y), w, h);
      }
      ctx.restore();
      return true;
    }
    return false;
  },

  /** Запасной бурундук, если спрайта нет. */
  chipmunk(ctx, char, x, y, flip, pose) {
    const w = 20; const h = 22;
    ctx.save();
    if (flip) {
      ctx.translate(Math.round(x + w), Math.round(y));
      ctx.scale(-1, 1);
      x = 0; y = 0;
    } else { x = Math.round(x); y = Math.round(y); }
    // хвост
    ctx.fillStyle = "#a9743c";
    ctx.beginPath();
    ctx.ellipse(x + 3, y + 9, 5, 8, -0.4, 0, Math.PI * 2);
    ctx.fill();
    // тело (свитер)
    ctx.fillStyle = char.color;
    ctx.fillRect(x + 4, y + 10, 12, 9);
    // голова
    ctx.fillStyle = "#c98d4b";
    ctx.fillRect(x + 5, y + 3, 11, 8);
    // морда и глаза
    ctx.fillStyle = "#f3dcb8";
    ctx.fillRect(x + 9, y + 6, 6, 4);
    ctx.fillStyle = "#22160c";
    ctx.fillRect(x + 12, y + 5, 2, 2);
    // уши
    ctx.fillRect(x + 4, y + 1, 3, 3);
    ctx.fillRect(x + 14, y + 1, 3, 3);
    // лапы
    ctx.fillStyle = "#8a5a2b";
    if (pose === "jump") {
      ctx.fillRect(x + 2, y + 8, 4, 3);
      ctx.fillRect(x + 14, y + 8, 4, 3);
    } else {
      ctx.fillRect(x + 4, y + 19, 4, 3);
      ctx.fillRect(x + 12, y + 19, 4, 3);
    }
    ctx.restore();
  },

  /** Запасной враг-робот. */
  robot(ctx, type, x, y, flip) {
    const w = 16; const h = 14;
    ctx.save();
    if (flip) {
      ctx.translate(Math.round(x + w), Math.round(y));
      ctx.scale(-1, 1);
      x = 0; y = 0;
    } else { x = Math.round(x); y = Math.round(y); }
    ctx.fillStyle = "#8d949c";
    ctx.fillRect(x, y + 4, w, h - 4);
    ctx.fillStyle = "#5d646b";
    ctx.fillRect(x + 1, y + 1, w - 2, 4);
    ctx.fillStyle = "#e03a2f";
    if (type === "bee") {
      ctx.fillStyle = "#e8c545";
      ctx.fillRect(x + 1, y + 3, w - 2, h - 4);
      ctx.fillStyle = "#2b2b2b";
      ctx.fillRect(x + 4, y + 3, 3, h - 4);
      ctx.fillRect(x + 10, y + 3, 3, h - 4);
      ctx.fillRect(x + 14, y + 4, 2, 2);
    } else {
      ctx.fillRect(x + 3, y + 5, 3, 3);
      ctx.fillRect(x + 10, y + 5, 3, 3);
      if (type === "bulldog") {
        ctx.fillStyle = "#4a4f55";
        ctx.fillRect(x + 12, y + 8, 4, 3);
      }
    }
    ctx.restore();
  },
};

/* ------------------------- игра ------------------------- */
class Game {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.ctx.imageSmoothingEnabled = false;
    this.controls = makeControls();
    this.state = "title";
    this.menuIndex = 0;
    this.twoPlayers = false;
    this.frame = 0;
    this.reset();
  }

  reset() {
    this.world = new World(LEVELS[0]);
    this.players = [];
    this.crates = [];
    this.enemies = [];
    this.items = [];
    this.particles = [];
    this.score = 0;
    this.camera = 0;
    this.doorWorld = null;
  }

  startGame(twoPlayers = false) {
    this.reset();
    const def = this.world.def;
    const spawnX = def.spawn.x * TILE;
    const spawnY = def.spawn.y * TILE;
    const chosen = CHARS[this.menuIndex];
    const second = CHARS[(this.menuIndex + 1) % CHARS.length];

    const p1 = new Player(chosen, this.controls.p1, spawnX, spawnY);
    this.players.push(p1);
    if (twoPlayers) {
      const p2 = new Player(second, this.controls.p2, spawnX + 20, spawnY);
      this.players.push(p2);
    }

    for (const crate of def.crates) {
      const y = (crate.y === undefined ? def.groundTop - 1 : crate.y) * TILE;
      this.crates.push(new Crate(crate.x * TILE, y));
    }
    for (const e of def.enemies) {
      const y = (e.y === undefined ? def.groundTop - 1 : e.y) * TILE;
      this.enemies.push(new Enemy(e.type, e.x * TILE, y, { from: e.from ?? e.x - 4, to: e.to ?? e.x + 4 }));
    }
    for (const it of def.items) {
      this.items.push(new Item(it.type, it.x * TILE, it.y * TILE));
    }
    this.doorWorld = { x: def.door.x * TILE, y: (def.groundTop - 2.5) * TILE };
    this.state = "play";
    Sound.playMusic("level", { volume: 0.5 });
  }

  update() {
    this.frame += 1;
    if (this.state === "title") {
      if (Input.hit("ArrowLeft")) this.menuIndex = (this.menuIndex + CHARS.length - 1) % CHARS.length;
      if (Input.hit("ArrowRight")) this.menuIndex = (this.menuIndex + 1) % CHARS.length;
      if (Input.hit("Enter") || Input.hit("KeyZ") || Input.hit("Space")) {
        Sound.playMusic("title", { volume: 0.4 });
        this.startGame(false);
      }
      if (Input.hit("Digit2")) {
        this.twoPlayers = true;
        this.startGame(true);
      }
      return;
    }
    if (this.state === "victory" || this.state === "gameover") {
      if (Input.hit("Enter") || Input.hit("Space")) {
        this.state = "title";
        this.reset();
        Sound.playMusic("title", { volume: 0.4 });
      }
      return;
    }

    for (const p of this.players) p.update(this.world, this);
    for (const crate of this.crates) crate.update(this.world, this);
    for (const e of this.enemies) e.update(this.world, this);
    for (const it of this.items) it.update();
    for (const p of this.particles) p.update();

    // враги, погибшие от брошенного ящика
    for (const crate of this.crates) {
      if (crate.state !== "thrown") continue;
      for (const enemy of this.enemies) {
        if (enemy.dead) continue;
        if (crate.x < enemy.x + enemy.w && crate.x + crate.w > enemy.x
          && crate.y < enemy.y + enemy.h && crate.y + crate.h > enemy.y) {
          enemy.hit(this);
          crate.shatter(this);
        }
      }
    }

    this.crates = this.crates.filter((c) => !c.dead);
    this.enemies = this.enemies.filter((e) => !e.dead);
    this.items = this.items.filter((i) => !i.dead);
    this.particles = this.particles.filter((p) => p.life > 0);
    this.score = Math.max(this.score, ...this.players.map((p) => p.score));

    // камера: следит за игроками
    const alive = this.players.filter((p) => !p.dead);
    if (alive.length) {
      const mid = alive.reduce((sum, p) => sum + p.cx, 0) / alive.length;
      const target = mid - VIEW_W / 2;
      this.camera += (target - this.camera) * 0.12;
      this.camera = Math.max(0, Math.min(this.camera, this.world.width - VIEW_W));
    }
  }

  draw() {
    const ctx = this.ctx;
    ctx.clearRect(0, 0, VIEW_W, VIEW_H);

    if (this.state === "title") return this.drawTitle();

    this.drawBackground(ctx);
    this.drawTiles(ctx);

    // ящики
    for (const crate of this.crates) {
      const sx = Math.round(crate.x - this.camera);
      const sy = Math.round(crate.y);
      if (crate.state === "thrown") {
        ctx.save();
        ctx.translate(sx + 8, sy + 8);
        ctx.rotate(crate.spin);
        this.drawCrate(ctx, -8, -8);
        ctx.restore();
      } else {
        this.drawCrate(ctx, sx, sy);
      }
    }

    // предметы
    for (const item of this.items) {
      const sx = Math.round(item.x - this.camera);
      const sy = Math.round(item.y + Math.sin(item.bob) * 2);
      const name = { star: "obj_star", flower: "obj_flower", acorn: "obj_acorn" }[item.type];
      if (!Draw.sprite(ctx, name, sx, sy, 14, 14)) {
        ctx.fillStyle = { star: "#f5d33a", flower: "#e8556d", acorn: "#a3702c" }[item.type];
        ctx.fillRect(sx + 3, sy + 3, 8, 8);
      }
    }

    // дверь-выход
    if (this.doorWorld) {
      const sx = Math.round(this.doorWorld.x - this.camera);
      if (!Draw.sprite(ctx, "obj_door", sx, this.doorWorld.y, 28, 40)) {
        ctx.fillStyle = "#7a4a22";
        ctx.fillRect(sx, this.doorWorld.y, 28, 40);
        ctx.fillStyle = "#c9a227";
        ctx.fillRect(sx + 20, this.doorWorld.y + 20, 3, 3);
      }
    }

    // враги
    for (const enemy of this.enemies) {
      const sx = Math.round(enemy.x - this.camera);
      const alt = { bulldog: "en_bulldog_walk", rat: "en_rat_walk", bee: "en_bee_fly" }[enemy.type];
      const busy = { bulldog: "en_bulldog_charge", rat: "en_rat_jump", bee: "en_bee_dive" }[enemy.type];
      const excited = enemy.charge > 0 || enemy.dive > 0 || (enemy.type === "rat" && !enemy.onGround);
      const pose = excited ? busy : alt;
      if (!Draw.sprite(ctx, pose, sx, Math.round(enemy.y), 22, 22, enemy.facing < 0)) {
        Draw.robot(ctx, enemy.type, sx, Math.round(enemy.y), enemy.facing < 0);
      }
    }

    // игроки
    for (const p of this.players) {
      if (p.dead) continue;
      if (p.invuln > 0 && Math.floor(this.frame / 4) % 2 === 0) continue;
      const sx = Math.round(p.x - this.camera - 8);
      const sy = Math.round(p.y - 8);
      const pose = `chr_${p.char.id}_${p.anim}`;
      if (!Draw.sprite(ctx, pose, sx, sy, 28, 28, p.facing < 0)) {
        Draw.chipmunk(ctx, p.char, p.x - this.camera - 4, p.y - 6, p.facing < 0, p.anim);
      }
      if (p.holding) {
        this.drawCrate(ctx, Math.round(p.holding.x - this.camera), Math.round(p.holding.y));
      }
      if (p.ducking) {
        ctx.fillStyle = "rgba(120,80,30,0.45)";
        ctx.fillRect(Math.round(p.x - this.camera - 2), Math.round(p.y - 2), 16, 18);
      }
    }

    // осколки
    for (const p of this.particles) {
      ctx.fillStyle = "#a9743c";
      ctx.fillRect(Math.round(p.x - this.camera), Math.round(p.y), 3, 3);
    }

    this.drawHud(ctx);
    if (this.state === "victory") this.drawCenterBox(ctx, "УРОВЕНЬ ПРОЙДЕН!", `Очки: ${this.score}`, "#3f9a4a");
    if (this.state === "gameover") this.drawCenterBox(ctx, "ИГРА ОКОНЧЕНА", `Очки: ${this.score}`, "#b03a2e");
  }

  drawCrate(ctx, x, y) {
    if (!Draw.sprite(ctx, "obj_crate", x, y, 16, 16)) {
      ctx.fillStyle = "#a9743c";
      ctx.fillRect(x, y, 16, 16);
      ctx.strokeStyle = "#6f4a20";
      ctx.strokeRect(x + 0.5, y + 0.5, 15, 15);
      ctx.beginPath();
      ctx.moveTo(x, y); ctx.lineTo(x + 16, y + 16);
      ctx.moveTo(x + 16, y); ctx.lineTo(x, y + 16);
      ctx.stroke();
    }
  }

  drawBackground(ctx) {
    const far = SpriteBank.get("bg_level_far");
    const near = SpriteBank.get("bg_level_near");
    ctx.fillStyle = "#5fa8de";
    ctx.fillRect(0, 0, VIEW_W, VIEW_H);
    if (far) {
      const off = (this.camera * 0.25) % VIEW_W;
      ctx.drawImage(far, -off, -8, VIEW_W, 168);
      ctx.drawImage(far, VIEW_W - off, -8, VIEW_W, 168);
    } else {
      ctx.fillStyle = "#7bc07b";
      ctx.fillRect(0, 100, VIEW_W, 60);
    }
    if (near) {
      const off = (this.camera * 0.55) % VIEW_W;
      ctx.drawImage(near, -off, 52, VIEW_W, 140);
      ctx.drawImage(near, VIEW_W - off, 52, VIEW_W, 140);
    }
  }

  drawTiles(ctx) {
    const startTile = Math.floor(this.camera / TILE);
    const def = this.world.def;
    const groundTop = def.groundTop * TILE;
    for (let tx = startTile; tx < startTile + VIEW_W / TILE + 1; tx += 1) {
      for (let ty = def.groundTop; ty < this.world.heightTiles; ty += 1) {
        if (!this.world.solidAt(tx, ty)) continue;
        const sx = Math.round(tx * TILE - this.camera);
        const sy = ty * TILE;
        const grass = ty === def.groundTop;
        ctx.fillStyle = grass ? "#4f9a3f" : "#7a5230";
        ctx.fillRect(sx, sy, TILE, TILE);
        if (grass) {
          ctx.fillStyle = "#3d7a30";
          ctx.fillRect(sx, sy + 4, TILE, 2);
        } else {
          ctx.fillStyle = "#5f3d22";
          for (let i = 0; i < 3; i += 1) {
            ctx.fillRect(sx + 2 + i * 5, sy + 4 + ((tx + ty + i) % 2) * 4, 3, 3);
          }
        }
      }
      for (let ty = 0; ty < def.groundTop; ty += 1) {
        if (this.world.solidAt(tx, ty)) { // деревянная платформа
          const sx = Math.round(tx * TILE - this.camera);
          const sy = ty * TILE;
          ctx.fillStyle = "#b07a3c";
          ctx.fillRect(sx, sy, TILE, 8);
          ctx.fillStyle = "#8a5a26";
          ctx.fillRect(sx, sy + 6, TILE, 3);
        }
      }
    }
  }

  drawHud(ctx) {
    ctx.font = "8px monospace";
    ctx.textBaseline = "top";
    const p1 = this.players[0];
    ctx.fillStyle = "rgba(0,0,0,0.45)";
    ctx.fillRect(0, 0, VIEW_W, 12);
    if (p1) {
      // сердца
      for (let i = 0; i < 3; i += 1) {
        const filled = i < p1.hearts;
        if (!Draw.sprite(ctx, "obj_heart", 3 + i * 12, 1, 10, 10)) {
          ctx.fillStyle = filled ? "#e03a2f" : "#5b2b28";
          ctx.fillRect(3 + i * 12, 1, 10, 10);
        }
        if (!filled) {
          ctx.fillStyle = "rgba(0,0,0,0.45)";
          ctx.fillRect(3 + i * 12, 1, 10, 10);
        }
      }
      ctx.fillStyle = "#fff";
      ctx.fillText(`${p1.char.name}   x${Math.max(0, p1.lives)}`, 42, 2);
      ctx.textAlign = "right";
      ctx.fillText(`ОЧКИ ${String(this.score).padStart(5, "0")}`, VIEW_W - 3, 2);
      ctx.textAlign = "left";
    }
  }

  drawCenterBox(ctx, title, subtitle, color) {
    ctx.fillStyle = "rgba(0,0,0,0.65)";
    ctx.fillRect(40, 60, VIEW_W - 80, 60);
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.strokeRect(41, 61, VIEW_W - 82, 58);
    ctx.fillStyle = "#fff";
    ctx.font = "bold 12px monospace";
    ctx.textAlign = "center";
    ctx.fillText(title, VIEW_W / 2, 72);
    ctx.font = "9px monospace";
    ctx.fillText(subtitle, VIEW_W / 2, 92);
    ctx.fillText("Enter — снова", VIEW_W / 2, 104);
    ctx.textAlign = "left";
  }

  drawTitle() {
    const ctx = this.ctx;
    const bg = SpriteBank.get("bg_title");
    if (bg) ctx.drawImage(bg, 0, 0, VIEW_W, VIEW_H);
    else {
      const grad = ctx.createLinearGradient(0, 0, 0, VIEW_H);
      grad.addColorStop(0, "#5fa8de");
      grad.addColorStop(1, "#2f6b3a");
      ctx.fillStyle = grad;
      ctx.fillRect(0, 0, VIEW_W, VIEW_H);
    }

    ctx.fillStyle = "rgba(0,0,0,0.45)";
    ctx.fillRect(20, 12, VIEW_W - 40, 26);
    // подложки, чтобы подсказки читались поверх нарисованной обложки
    ctx.fillStyle = "rgba(6,8,16,0.55)";
    ctx.fillRect(0, 58, VIEW_W, 74);
    ctx.fillRect(0, 134, VIEW_W, VIEW_H - 134);
    ctx.fillStyle = "#ffd94a";
    ctx.font = "bold 16px monospace";
    ctx.textAlign = "center";
    ctx.fillText("ЭЛВИН И БУРУНДУКИ", VIEW_W / 2, 16);
    ctx.font = "8px monospace";
    ctx.fillStyle = "#fff";
    ctx.fillText("по мотивам NES «Чип и Дейл»", VIEW_W / 2, 32);

    // выбор героя
    CHARS.forEach((char, i) => {
      const x = 70 + i * 60;
      const selected = i === this.menuIndex;
      if (selected) {
        ctx.fillStyle = "rgba(255,255,255,0.2)";
        ctx.fillRect(x - 16, 66, 52, 62);
      }
      const pose = `chr_${char.id}_stand`;
      if (!Draw.sprite(ctx, pose, x - 14, 70, 48, 48)) {
        Draw.chipmunk(ctx, char, x - 10, 72, false, "stand");
      }
      ctx.fillStyle = selected ? "#ffd94a" : "#fff";
      ctx.font = "9px monospace";
      ctx.fillText(char.name, x + 10, 122);
    });

    ctx.fillStyle = "#fff";
    ctx.font = "8px monospace";
    ctx.fillText("← → — выбор героя    Enter — играть", VIEW_W / 2, 142);
    ctx.fillText("2 — вдвоём (второй игрок: A/D, W, C, S)", VIEW_W / 2, 154);
    ctx.fillText("Z — прыжок, X — взять/бросить ящик, ↓ — спрятаться", VIEW_W / 2, 166);
    ctx.fillStyle = "#ffe9a8";
    ctx.fillText(this.twoPlayers ? "режим: двое игроков" : "режим: один игрок", VIEW_W / 2, 178);
    ctx.textAlign = "left";
  }
}

/* Режим демонстрации: index.html#demo — игра стартует сама, а «игрока» ведёт
 * простой авто-пилот: идёт вправо, прыгает перед ямой или ящиком, берёт и
 * бросает ящики во врагов. Нужен для проверки без рук и для записи видео. */
const Demo = {
  active: false,
  cooldown: 0,
  restartDelay: 0,
  jumpHold: 0,
  retreat: 0,
  start(game) {
    this.active = true;
    game.startGame(false);
  },

  act(code) {
    Input.keys.add(code);
    if (code === "KeyZ" || code === "KeyX") Input.pressed.add(code);
  },

  update(game) {
    if (!this.active || !game) return;
    Input.keys.clear();
    if (game.state !== "play") {
      this.restartDelay += 1;
      if ((game.state === "gameover" || game.state === "victory") && this.restartDelay > 90) {
        this.restartDelay = 0;
        game.startGame(false);
      }
      return;
    }

    const p = game.players[0];
    if (!p || p.dead) return;
    const world = game.world;
    const feet = p.y + p.h;

    this.act("ArrowRight");

    // удержание прыжка для высокой дуги
    if (this.jumpHold > 0) {
      this.jumpHold -= 1;
      Input.keys.add("KeyZ");
    }

    const crateAt = (minDx, maxDx) => game.crates.find((c) => c.state === "rest"
      && c.x - p.x > minDx && c.x - p.x < maxDx && Math.abs(c.y + c.h - feet) < 22);
    const enemy = game.enemies.find((e) => !e.dead && e.x - p.x > -10 && e.x - p.x < 80
      && Math.abs(e.y - p.y) < 26);

    // 1) яма впереди — прыгаем заранее и держим jump
    const openAt = (dx) => {
      const tx = Math.floor((p.x + p.w + dx) / TILE);
      const ty = Math.floor((feet + 2) / TILE);
      return !world.solidAt(tx, ty) && !world.solidAt(tx, ty + 1);
    };
    const pitAhead = openAt(10) || openAt(20) || openAt(30);
    if (pitAhead && p.onGround && this.jumpHold === 0) {
      this.act("KeyZ");
      this.jumpHold = 16;
    }

    // 1б) впереди стенка (низкая платформа или уступ) — тоже прыгаем
    const wallAt = (dx) => {
      const tx = Math.floor((p.x + p.w + dx) / TILE);
      const ty = Math.floor((feet - 2) / TILE);
      return world.solidAt(tx, ty) || world.solidAt(tx, ty - 1);
    };
    if (!pitAhead && wallAt(4) && p.onGround && this.jumpHold === 0) {
      this.act("KeyZ");
      this.jumpHold = 14;
    }

    // 2) рядом ящик — берём, а не перепрыгиваем
    if (this.cooldown > 0) this.cooldown -= 1;
    else if (!p.holding) {
      const crate = crateAt(-6, 22);
      if (crate) { this.act("KeyX"); this.cooldown = 12; }
    }

    // 3) несём ящик и видим врага — бросаем; иначе уворачиваемся
    const enemyDist = enemy ? enemy.x - p.x : Infinity;
    if (p.holding && enemy && this.cooldown === 0 && enemyDist < 70) {
      this.act("KeyX");
      this.cooldown = 16;
    } else if (enemy && !p.holding && p.onGround && !pitAhead) {
      if (enemyDist < 22) {           // слишком близко — отходим
        Input.keys.delete("ArrowRight");
        Input.keys.add("ArrowLeft");
        this.retreat = 10;
      } else if (enemyDist < 44) {    // прыгаем через врага
        this.act("KeyZ");
        this.jumpHold = 16;
      }
    }
    if (this.retreat > 0) {
      this.retreat -= 1;
      Input.keys.delete("ArrowRight");
      Input.keys.add("ArrowLeft");
    }

    // 4) упёрлись в стенку-ящик — прыгаем
    if (crateAt(-2, 14) && p.onGround && this.jumpHold === 0 && this.retreat === 0) {
      this.act("KeyZ");
      this.jumpHold = 14;
    }
  },
};

/* ------------------------- запуск ------------------------- */
const SPRITE_NAMES = [
  ...CHARS.flatMap((c) => ["stand", "run1", "run2", "jump", "throw"].map((p) => `chr_${c.id}_${p}`)),
  "en_bulldog_walk", "en_bulldog_charge", "en_rat_walk", "en_rat_jump", "en_bee_fly", "en_bee_dive",
  "obj_crate", "obj_crate_broken", "obj_star", "obj_flower", "obj_acorn", "obj_heart", "obj_door",
];

async function boot() {
  const canvas = document.getElementById("game");
  canvas.width = VIEW_W;
  canvas.height = VIEW_H;
  const game = new Game(canvas);
  Input.init();
  window.__game = game; // для отладки и скриншотов

  await SpriteBank.load(SPRITE_NAMES, "assets/");
  await SpriteBank.load(["bg_title", "bg_level_far", "bg_level_near"], "assets/");
  await Sound.useFiles("assets/");
  Sound.playMusic("title", { volume: 0.35 });

  /* Пошаговый режим (index.html#demo): игру двигает не таймер браузера, а
   * внешняя команда через window.__step(n). Так запись кадров не зависит от
   * того, тормозит ли браузер фоновую вкладку. */
  if (location.hash.includes("demo")) {
    Demo.start(game);
    window.__step = (n = 1) => {
      for (let i = 0; i < n; i += 1) {
        Demo.update(game);
        game.update();
        Input.clearFrame();
      }
      game.draw();
      const p = game.players[0];
      return JSON.stringify({
        state: game.state,
        px: Math.round(p ? p.x : 0),
        hearts: p ? p.hearts : 0,
        lives: p ? p.lives : 0,
        holding: Boolean(p && p.holding),
        score: game.score,
        enemies: game.enemies.length,
        crates: game.crates.length,
      });
    };
    window.__press = (code) => { Input.keys.add(code); Input.pressed.add(code); };
    window.__step(1);
    return;
  }

  function loop() {
    Demo.update(game);
    game.update();
    game.draw();
    Input.clearFrame();
    requestAnimationFrame(loop);
  }
  loop();
}

window.addEventListener("DOMContentLoaded", boot);
