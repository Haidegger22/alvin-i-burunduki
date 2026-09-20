/* Уровень и физика столкновений.
 * Сетка тайлов 16x16, экран 320x192 (20x12 тайлов), уровень длиной 240 тайлов.
 */

const TILE = 16;
const VIEW_W = 320;
const VIEW_H = 192;

/* Уровень строится описанием: земля отрезками (между ними — ямы),
 * платформы, ящики, враги, бонусы, дверь-выход. */
const LEVELS = [
  {
    name: "Лесная опушка",
    widthTiles: 240,
    groundTop: 10, // верхний ряд земли
    ground: [
      [0, 35], [39, 69], [73, 119], [123, 169], [173, 239],
    ],
    platforms: [
      { x: 20, y: 7, len: 3 },
      { x: 44, y: 6, len: 4 },
      { x: 57, y: 7, len: 3 },
      { x: 78, y: 5, len: 5 },
      { x: 96, y: 7, len: 4 },
      { x: 110, y: 6, len: 3 },
      { x: 132, y: 5, len: 4 },
      { x: 150, y: 7, len: 5 },
      { x: 164, y: 6, len: 3 },
      { x: 180, y: 5, len: 4 },
      { x: 200, y: 7, len: 4 },
      { x: 214, y: 6, len: 3 },
    ],
    crates: [
      { x: 12 }, { x: 17 }, { x: 30 }, { x: 33 },
      { x: 45, y: 6 }, { x: 58, y: 7 },
      { x: 60 }, { x: 65 },
      { x: 80, y: 5 }, { x: 84 }, { x: 97, y: 7 },
      { x: 100 }, { x: 112, y: 6 }, { x: 118 }, { x: 133, y: 5 },
      { x: 140 }, { x: 145 }, { x: 151, y: 7 }, { x: 162 },
      { x: 166, y: 6 }, { x: 181, y: 5 }, { x: 195 }, { x: 201, y: 7 },
      { x: 210 }, { x: 215, y: 6 }, { x: 226 },
    ],
    enemies: [
      { type: "bulldog", x: 26, from: 18, to: 34 },
      { type: "rat", x: 62, from: 56, to: 68 },
      { type: "bee", x: 88, y: 5 },
      { type: "bulldog", x: 104, from: 96, to: 116 },
      { type: "rat", x: 140, from: 132, to: 148 },
      { type: "bee", x: 158, y: 4 },
      { type: "bulldog", x: 188, from: 180, to: 198 },
      { type: "rat", x: 208, from: 200, to: 218 },
    ],
    items: [
      { type: "star", x: 21, y: 7 },
      { type: "flower", x: 46, y: 6 },
      { type: "acorn", x: 71, y: 8 },
      { type: "star", x: 79, y: 5 },
      { type: "star", x: 98, y: 7 },
      { type: "flower", x: 111, y: 6 },
      { type: "acorn", x: 121, y: 8 },
      { type: "star", x: 133, y: 5 },
      { type: "flower", x: 152, y: 7 },
      { type: "star", x: 165, y: 6 },
      { type: "acorn", x: 171, y: 8 },
      { type: "star", x: 181, y: 5 },
      { type: "flower", x: 202, y: 7 },
      { type: "star", x: 215, y: 6 },
    ],
    door: { x: 232, y: 8 },
    spawn: { x: 3, y: 8 },
  },
];

/** Сетка тайлов: 1 — твёрдый блок земли, 2 — деревянная платформа, 0 — пусто. */
class World {
  constructor(def) {
    this.def = def;
    this.widthTiles = def.widthTiles;
    this.heightTiles = 12;
    this.width = this.widthTiles * TILE;
    this.height = this.heightTiles * TILE;
    this.grid = [];
    for (let y = 0; y < this.heightTiles; y += 1) {
      this.grid.push(new Array(this.widthTiles).fill(0));
    }
    for (const [x0, x1] of def.ground) {
      for (let x = x0; x <= x1; x += 1) {
        for (let y = def.groundTop; y < this.heightTiles; y += 1) {
          this.grid[y][x] = 1;
        }
      }
    }
    for (const p of def.platforms) {
      for (let i = 0; i < p.len; i += 1) {
        if (p.x + i < this.widthTiles) this.grid[p.y][p.x + i] = 2;
      }
    }
  }

  tileAt(tx, ty) {
    if (tx < 0 || tx >= this.widthTiles || ty < 0 || ty >= this.heightTiles) return 0;
    return this.grid[ty][tx];
  }

  solidAt(tx, ty) {
    return this.tileAt(tx, ty) !== 0;
  }

  /** Есть ли твёрдый тайл в прямоугольнике (мировые координаты). */
  rectHits(x, y, w, h) {
    const tx0 = Math.floor(x / TILE);
    const tx1 = Math.floor((x + w - 1) / TILE);
    const ty0 = Math.floor(y / TILE);
    const ty1 = Math.floor((y + h - 1) / TILE);
    for (let ty = ty0; ty <= ty1; ty += 1) {
      for (let tx = tx0; tx <= tx1; tx += 1) {
        if (this.solidAt(tx, ty)) return true;
      }
    }
    return false;
  }

  /** Твёрдая ли опора под ногами (для проверки «на земле»). */
  groundBelow(x, y, w) {
    const ty = Math.floor((y + 1) / TILE);
    const tx0 = Math.floor(x / TILE);
    const tx1 = Math.floor((x + w - 1) / TILE);
    if (ty >= this.heightTiles) return false;
    for (let tx = tx0; tx <= tx1; tx += 1) {
      if (this.solidAt(tx, ty)) return true;
    }
    return false;
  }
}
