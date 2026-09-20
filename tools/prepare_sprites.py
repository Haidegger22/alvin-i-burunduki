#!/usr/bin/env python3
"""Подготовка спрайтов игры из сырых картинок MiniMax.

Что делает:
  1. читает сырой PNG из raw/ (сгенерированный MiniMax),
  2. вырезает magenta-фон (chroma key) и делает пиксели прозрачными,
  3. находит границы объекта по непрозрачным пикселям и обрезает лишнее,
  4. масштабирует до нужного размера методом NEAREST (пиксель-в-пиксель),
  5. сохраняет в assets/sprites/ с прозрачностью.

Если какого-то сырого файла нет — просто пропускает его (игра нарисует
запасную фигуру сама), в конце печатает отчёт: что сделано, что пропущено.
"""
import pathlib
import sys

from PIL import Image

ROOT = pathlib.Path("/home/orangepi/games/alvin-chipmunks")
RAW = ROOT / "raw"
OUT = ROOT / "assets" / "sprites"

# имя_файла: (ширина, высота) итогового спрайта
SPEC = {
    # персонажи: 5 кадров на каждого бурундука
    **{f"chr_{who}_{pose}": (28, 28)
       for who in ("alvin", "simon", "theodore")
       for pose in ("stand", "run1", "run2", "jump", "throw")},
    # враги
    **{f"en_{who}_{pose}": (26, 26)
       for who, poses in (("bulldog", ("walk", "charge")),
                          ("rat", ("walk", "jump")),
                          ("bee", ("fly", "dive")))
       for pose in poses},
    # предметы
    "obj_crate": (16, 16),
    "obj_crate_broken": (16, 16),
    "obj_star": (14, 14),
    "obj_flower": (14, 14),
    "obj_acorn": (14, 14),
    "obj_heart": (12, 12),
    "obj_door": (28, 40),
}

# Определяем фон автоматически: берём самый частый цвет по краям картинки и
# считаем фоном всё, что близко к нему по допуску. Так надёжнее фиксированного
# порога: генератор может дать и чистую magenta, и розово-малиновый оттенок.
BG_TOLERANCE = 60      # максимальная разница по каналу, при которой пиксель — фон
CROP_PAD = 1           # запас вокруг объекта при обрезке


def border_color(img: Image.Image) -> tuple[int, int, int]:
    """Самый частый цвет по периметру картинки — это и есть фон."""
    w, h = img.size
    px = img.load()
    from collections import Counter
    samples = []
    step = max(1, w // 60)
    for x in range(0, w, step):
        samples.append(px[x, 0])
        samples.append(px[x, h - 1])
    for y in range(0, h, step):
        samples.append(px[0, y])
        samples.append(px[w - 1, y])
    return Counter(samples).most_common(1)[0][0]


def is_background(r: int, g: int, b: int, bg: tuple[int, int, int]) -> bool:
    return (abs(r - bg[0]) < BG_TOLERANCE
            and abs(g - bg[1]) < BG_TOLERANCE
            and abs(b - bg[2]) < BG_TOLERANCE)


def clean_halo(img: Image.Image, bg: tuple[int, int, int]) -> None:
    """Второй проход: убирает розовую кайму — смешанные пиксели по краю объекта."""
    w, h = img.size
    px = img.load()
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a == 0:
                continue
            # рядом есть прозрачный пиксель?
            edge = False
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (2, 0), (-2, 0), (0, 2), (0, -2)):
                nx, ny = x + dx, y + dy
                if 0 <= nx < w and 0 <= ny < h and px[nx, ny][3] == 0:
                    edge = True
                    break
            if not edge:
                continue
            if (abs(r - bg[0]) < 115 and abs(g - bg[1]) < 115 and abs(b - bg[2]) < 115):
                px[x, y] = (0, 0, 0, 0)


def process(name: str, size: tuple[int, int]) -> str | None:
    src = RAW / f"{name}.png"
    if not src.exists():
        return None

    img = Image.open(src).convert("RGBA")
    px = img.load()
    w, h = img.size
    bg = border_color(img)

    for y in range(h):
        for x in range(w):
            r, g, b, _ = px[x, y]
            if is_background(r, g, b, bg):
                px[x, y] = (0, 0, 0, 0)

    clean_halo(img, bg)

    bbox = img.getbbox()
    if bbox is None:
        return f"{name}: пусто после вырезания фона (фон {bg} занял всю картинку?)"

    left = max(0, bbox[0] - CROP_PAD)
    top = max(0, bbox[1] - CROP_PAD)
    right = min(w, bbox[2] + CROP_PAD)
    bottom = min(h, bbox[3] + CROP_PAD)
    obj = img.crop((left, top, right, bottom))

    # вписываем в целевой размер с сохранением пропорций
    tw, th = size
    ow, oh = obj.size
    scale = min(tw / ow, th / oh)
    new_size = (max(1, round(ow * scale)), max(1, round(oh * scale)))
    small = obj.resize(new_size, Image.LANCZOS)

    # альфа — жёсткая (пиксельные края), цвета — упрощаем до палитры 24
    alpha = small.getchannel("A").point(lambda v: 255 if v > 110 else 0)
    rgb = small.convert("RGB").convert("P", palette=Image.ADAPTIVE, colors=24).convert("RGB")
    obj = rgb.convert("RGBA")
    obj.putalpha(alpha)

    canvas = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    canvas.paste(obj, ((tw - new_size[0]) // 2, th - new_size[1]))  # прижимаем к низу
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / f"{name}.png"
    canvas.save(target)
    return f"{name}: {ow}x{oh} -> {new_size[0]}x{new_size[1]} в {tw}x{th} ({target.stat().st_size // 1024} КБ)"


def prepare_backgrounds() -> list[str]:
    """Фоны: без вырезания, только масштаб до 960x192 (дальний) и 960x192 (ближний)."""
    report = []
    targets = {"bg_title": (640, 360), "bg_level_far": (960, 192), "bg_level_near": (960, 192)}
    for name, size in targets.items():
        src = RAW / f"{name}.png"
        if not src.exists():
            continue
        img = Image.open(src).convert("RGB").resize(size, Image.LANCZOS)
        target = OUT / f"{name}.png"
        img.save(target, optimize=True)
        report.append(f"{name}: -> {size[0]}x{size[1]} ({target.stat().st_size // 1024} КБ)")
    return report


def main() -> None:
    if not RAW.exists():
        sys.exit(f"нет каталога {RAW}")

    done, skipped, problems = [], [], []
    for name, size in SPEC.items():
        try:
            result = process(name, size)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{name}: ошибка {type(exc).__name__}: {exc}")
            continue
        if result is None:
            skipped.append(name)
        elif result.startswith(name + ": пусто"):
            problems.append(result)
        else:
            done.append(result)

    print("=== подготовлено:")
    for line in done:
        print("  ", line)

    for line in prepare_backgrounds():
        print("  ", line)

    if skipped:
        print(f"=== пропущено (нет сырого файла, {len(skipped)}):")
        print("  ", ", ".join(skipped))
    if problems:
        print("=== проблемы:")
        for line in problems:
            print("  ", line)


if __name__ == "__main__":
    main()
