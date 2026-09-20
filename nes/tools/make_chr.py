#!/usr/bin/env python3
"""Сборка графического ПЗУ (CHR) и палитр для NES-версии игры.

Что делает:
  1. Рисует служебные плитки 8x8 (небо, трава, земля, ящик, платформа) — пока
     заглушки из простых фигур, чтобы ROM запускался и проверялся сразу.
  2. При наличии assets/sprites/*.png умеет вставлять настоящие спрайты:
     картинка уменьшается до нужного размера, приводится к трём цветам
     (плюс прозрачный), режется на плитки 8x8 и укладывается в мозаику 2x2.
  3. Пишет chr/tiles.chr (8 КБ, 512 плиток в формате NES: два битовых слоя)
     и chr/tiles.h — номера нужных плиток и таблицы палитр для C-кода.

Формат плитки NES: 16 байт — 8 байт младшего бита (по строке на байт),
затем 8 байт старшего бита. Значение пикселя 0..3 — индекс в палитре.
"""
import pathlib
import struct
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT_CHR = ROOT / "chr" / "tiles.chr"
OUT_H = ROOT / "chr" / "tiles.h"
SPRITES = ROOT.parent / "assets" / "sprites"

TILE_COUNT = 512        # 8 КБ графического ПЗУ, дальше — пустые плитки

# ---------------------------------------------------------------- рисование
def blank() -> list[list[int]]:
    return [[0] * 8 for _ in range(8)]


def from_art(rows: list[str]) -> list[list[int]]:
    """Плитка из строк вида '01122330' (цифра = индекс цвета палитры)."""
    assert len(rows) == 8, "нужно ровно 8 строк"
    return [[int(ch) for ch in row] for row in rows]


def solid(color: int) -> list[list[int]]:
    return [[color] * 8 for _ in range(8)]


def make_sky() -> list[list[int]]:
    return solid(0)


def make_grass() -> list[list[int]]:
    return from_art([
        "11111111",
        "22222112",
        "22222222",
        "22222222",
        "22322222",
        "22222232",
        "22232222",
        "22222222",
    ])


def make_dirt() -> list[list[int]]:
    return from_art([
        "22222222",
        "23222222",
        "22222322",
        "22222222",
        "22322232",
        "22222222",
        "32232222",
        "22222222",
    ])


def make_platform() -> list[list[int]]:
    return from_art([
        "11111111",
        "22222222",
        "22222222",
        "22222222",
        "00000000",
        "00000000",
        "00000000",
        "00000000",
    ])


def make_crate() -> list[list[int]]:
    return from_art([
        "33333333",
        "32222223",
        "32322323",
        "32233223",
        "32233223",
        "32322323",
        "32222223",
        "33333333",
    ])


def make_font_digit(digit: int) -> list[list[int]]:
    """Цифры 0-9 для счёта и жизней (палитра: 0 фон, 1 белый)."""
    glyphs = {
        0: ["11111100", "11001100", "11001100", "11001100", "11001100", "11001100", "11111100", "00000000"],
        1: ["00110000", "01110000", "00110000", "00110000", "00110000", "00110000", "01111000", "00000000"],
        2: ["11111100", "00001100", "00001100", "11111100", "11000000", "11000000", "11111100", "00000000"],
        3: ["11111100", "00001100", "00001100", "01111100", "00001100", "00001100", "11111100", "00000000"],
        4: ["11001100", "11001100", "11001100", "11111100", "00001100", "00001100", "00001100", "00000000"],
        5: ["11111100", "11000000", "11000000", "11111100", "00001100", "00001100", "11111100", "00000000"],
        6: ["11111100", "11000000", "11000000", "11111100", "11001100", "11001100", "11111100", "00000000"],
        7: ["11111100", "00001100", "00001100", "00011000", "00110000", "00110000", "00110000", "00000000"],
        8: ["11111100", "11001100", "11001100", "11111100", "11001100", "11001100", "11111100", "00000000"],
        9: ["11111100", "11001100", "11001100", "11111100", "00001100", "00001100", "11111100", "00000000"],
    }
    return from_art(glyphs[digit])


def make_heart() -> list[list[int]]:
    return from_art([
        "01100110",
        "11111111",
        "11111111",
        "11111111",
        "01111110",
        "00111100",
        "00011000",
        "00000000",
    ])


# -------------------------------------------------- настоящие спрайты из PNG
def sprite_tiles(path: pathlib.Path, size: int = 16) -> list[list[list[int]]]:
    """PNG -> список плиток 8x8 (мозаика 2x2 для 16x16).

    Палитра спрайта жёсткая, как на NES: 0 — прозрачный, 1 — свитер (цвет
    задаёт палитра), 2 — шерсть, 3 — контур. Картинка приводится к ней по
    яркости и насыщенности.
    """
    from PIL import Image

    img = Image.open(path).convert("RGBA").resize((size, size), Image.LANCZOS)
    px = img.load()
    grid = [[0] * size for _ in range(size)]
    for y in range(size):
        for x in range(size):
            r, g, b, a = px[x, y]
            if a < 96:
                grid[y][x] = 0                      # прозрачный
                continue
            lum = 0.299 * r + 0.587 * g + 0.114 * b
            if lum < 70:
                grid[y][x] = 3                      # контур
            elif r > g + 30 and r > b + 30:
                grid[y][x] = 1                      # красноватое — свитер
            elif b > r + 25 and b > g + 15:
                grid[y][x] = 1                      # синеватое — свитер
            elif g > r + 20 and g > b + 20:
                grid[y][x] = 1                      # зелёное — свитер
            else:
                grid[y][x] = 2                      # всё остальное — шерсть
    tiles = []
    for ty in range(size // 8):
        for tx in range(size // 8):
            tile = [[grid[ty * 8 + y][tx * 8 + x] for x in range(8)] for y in range(8)]
            tiles.append(tile)
    return tiles


def encode_tile(tile: list[list[int]]) -> bytes:
    low = bytearray(8)
    high = bytearray(8)
    for y in range(8):
        for x in range(8):
            v = tile[y][x] & 3
            if v & 1:
                low[y] |= 0x80 >> x
            if v & 2:
                high[y] |= 0x80 >> x
    return bytes(low + high)


# ---------------------------------------------------------------- сборка
def main() -> None:
    tiles: list[list[list[int]]] = []

    def add(tile: list[list[int]]) -> int:
        tiles.append(tile)
        return len(tiles) - 1

    index = {}
    index["TILE_SKY"] = add(make_sky())
    index["TILE_GRASS"] = add(make_grass())
    index["TILE_DIRT"] = add(make_dirt())
    index["TILE_PLATFORM"] = add(make_platform())
    index["TILE_CRATE"] = add(make_crate())
    index["TILE_HEART"] = add(make_heart())
    for d in range(10):
        index[f"TILE_DIGIT{d}"] = add(make_font_digit(d))

    # спрайт игрока: настоящая картинка, если она есть, иначе простая фигура
    used_real = False
    art = SPRITES / "chr_alvin_stand.png"
    if art.exists():
        try:
            player = sprite_tiles(art, 16)
            index["TILE_PLAYER_TL"] = add(player[0])
            index["TILE_PLAYER_TR"] = add(player[1])
            index["TILE_PLAYER_BL"] = add(player[2])
            index["TILE_PLAYER_BR"] = add(player[3])
            used_real = True
        except Exception as exc:  # noqa: BLE001
            print(f"не смог взять настоящий спрайт ({exc}), рисую простой")

    if not used_real:
        index["TILE_PLAYER_TL"] = add(from_art([
            "00111100", "01222210", "12222221", "12233221",
            "12222221", "00111100", "00111100", "01100110",
        ]))
        index["TILE_PLAYER_TR"] = add(from_art([
            "00110000", "11221100", "22222100", "23322100",
            "22222100", "00111100", "01100110", "01100110",
        ]))
        index["TILE_PLAYER_BL"] = add(from_art([
            "01100110", "01100110", "01100110", "01100110",
            "00111100", "00111100", "00110000", "01100000",
        ]))
        index["TILE_PLAYER_BR"] = add(from_art([
            "01100110", "01100110", "01100110", "01100110",
            "00111100", "00111100", "00001100", "00000110",
        ]))

    # записываем 8 КБ графического ПЗУ
    OUT_CHR.parent.mkdir(parents=True, exist_ok=True)
    data = bytearray()
    for tile in tiles:
        data += encode_tile(tile)
    used = len(tiles)
    data += bytes((TILE_COUNT - used) * 16)
    OUT_CHR.write_bytes(bytes(data))

    # заголовок для C: номера плиток и палитры
    lines = [
        "/* Файл создан tools/make_chr.py — не править руками. */",
        "#ifndef TILES_H",
        "#define TILES_H",
        "",
    ]
    for name, value in index.items():
        lines.append(f"#define {name} {value}")
    lines += [
        "",
        f"#define TILES_USED {used}",
        "",
        "/* Палитры: 16 байт фоновых, 16 байт спрайтовых (значения цветов NES) */",
        "static const unsigned char palette_bg[16] = {",
        "    0x21, 0x19, 0x07, 0x0F,   /* небо, трава, земля, контур */",
        "    0x21, 0x27, 0x17, 0x0F,   /* платформа */",
        "    0x21, 0x16, 0x27, 0x0F,   /* ящик */",
        "    0x21, 0x30, 0x00, 0x0F,",
        "};",
        "static const unsigned char palette_spr[16] = {",
        "    0x0F, 0x16, 0x17, 0x0F,   /* Элвин: контур, свитер, шерсть */",
        "    0x0F, 0x11, 0x17, 0x0F,   /* Саймон */",
        "    0x0F, 0x1A, 0x17, 0x0F,   /* Теодор */",
        "    0x0F, 0x30, 0x00, 0x0F,   /* враги */",
        "};",
        "",
        "#endif",
    ]
    OUT_H.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"плиток использовано: {used} из {TILE_COUNT} (файл {OUT_CHR.stat().st_size} байт)")
    print(f"заголовок: {OUT_H}")
    print(f"спрайт игрока: {'настоящая картинка' if used_real else 'простая фигура'}")


if __name__ == "__main__":
    sys.exit(main())
