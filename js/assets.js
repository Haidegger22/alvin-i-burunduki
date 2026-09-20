/* Ассеты и звук.
 * Картинки грузятся из assets/sprites/, звук — из assets/audio/.
 * Если файла нет, игра не падает: спрайт рисуется запасной фигурой,
 * звук заменяется простым синтезированным сигналом (WebAudio).
 */
const SpriteBank = {
  images: {},
  missing: new Set(),
  basePath: "",
  music: {},
  sfx: {},

  async load(spriteNames, basePath = "") {
    this.basePath = basePath;
    await Promise.all(spriteNames.map((name) => this.loadOne(name)));
  },

  loadOne(name) {
    return new Promise((resolve) => {
      const img = new Image();
      img.onload = () => {
        this.images[name] = img;
        resolve();
      };
      img.onerror = () => {
        this.missing.add(name);
        resolve();
      };
      img.src = `${this.basePath}sprites/${name}.png`;
    });
  },

  has(name) {
    return Boolean(this.images[name]) && !this.missing.has(name);
  },

  get(name) {
    return this.images[name];
  },
};

/* ---------- звук ---------- */
const Sound = {
  ctx: null,
  enabled: true,
  musicEl: null,
  currentTrack: null,
  buffers: {},

  ctxInit() {
    if (!this.ctx) {
      const Ctx = window.AudioContext || window.webkitAudioContext;
      if (Ctx) this.ctx = new Ctx();
    }
    if (this.ctx && this.ctx.state === "suspended") this.ctx.resume();
    return this.ctx;
  },

  /** Простой синтезированный сигнал: используется, если файла звука нет. */
  beep({ freq = 440, dur = 0.12, type = "square", vol = 0.18 } = {}) {
    const ctx = this.ctxInit();
    if (!ctx || !this.enabled) return;
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = type;
    osc.frequency.setValueAtTime(freq, ctx.currentTime);
    gain.gain.setValueAtTime(vol, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + dur);
    osc.connect(gain).connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + dur);
  },

  async useFiles(basePath = "") {
    this.audioPath = basePath + "audio/";
  },

  /** Музыка: обычный <audio loop>, чтобы не грузить память на слабой плате. */
  playMusic(track, { volume = 0.55 } = {}) {
    if (this.currentTrack === track && this.musicEl && !this.musicEl.paused) return;
    this.stopMusic();
    const el = new Audio(`${this.audioPath}${track}.ogg`);
    el.loop = true;
    el.volume = volume;
    el.addEventListener("error", () => {
      /* файла нет — тишина, без падения */
      el.dataset.failed = "1";
    });
    el.play().catch(() => { /* автоплей запрещён до первого клика */ });
    this.musicEl = el;
    this.currentTrack = track;
  },

  stopMusic() {
    if (this.musicEl) {
      this.musicEl.pause();
      this.musicEl.currentTime = 0;
    }
    this.musicEl = null;
    this.currentTrack = null;
  },

  /** Короткий эффект: сначала пробуем файл, иначе синтез. */
  async play(name, fallback = {}) {
    if (!this.enabled) return;
    this.ctxInit();
    const ctx = this.ctx;
    if (!ctx) return;

    if (this.buffers[name]) {
      const src = ctx.createBufferSource();
      src.buffer = this.buffers[name];
      src.connect(ctx.destination);
      src.start();
      return;
    }

    if (!this.buffers[`_tried_${name}`]) {
      this.buffers[`_tried_${name}`] = true;
      try {
        const res = await fetch(`${this.audioPath}${name}.ogg`);
        if (res.ok) {
          const data = await res.arrayBuffer();
          this.buffers[name] = await ctx.decodeAudioData(data);
          const src = ctx.createBufferSource();
          src.buffer = this.buffers[name];
          src.connect(ctx.destination);
          src.start();
          return;
        }
      } catch (err) {
        /* ниже — синтезированный запасной вариант */
      }
    }
    this.beep(fallback);
  },

  jump() { this.play("sfx_jump", { freq: 520, dur: 0.09, type: "square" }); },
  throwCrate() { this.play("sfx_throw", { freq: 300, dur: 0.1, type: "square" }); },
  crateBreak() { this.play("sfx_crate_break", { freq: 180, dur: 0.16, type: "sawtooth" }); },
  item() { this.play("item", { freq: 880, dur: 0.16, type: "triangle" }); },
  damage() { this.play("damage", { freq: 160, dur: 0.3, type: "sawtooth" }); },
  victory() { this.play("victory", { freq: 990, dur: 0.5, type: "triangle" }); },
  gameover() { this.play("gameover", { freq: 120, dur: 0.6, type: "square" }); },
};
