#!/usr/bin/env python3
"""Валидация PNG-ассетов: PNG валиден, размеры, вес, % magenta, не однотонная.

Использование:
    python3 validate_assets.py raw/*.png            # просто отчёт
    python3 validate_assets.py --kind sprite raw/x.png ...

Печатает по строке на файл:
    OK   <file> <WxH>  <КБ>КБ  magenta=<%>  colors=<N>
    FAIL <file> причина
"""
import argparse
import pathlib
import sys

from PIL import Image

MAGENTA_MIN_SPRITE = 20.0   # для спрайтов


def _pixels(img: Image.Image):
    """Список (r,g,b) — через tobytes(), совместимо с любой версией PIL."""
    raw = img.convert("RGB").tobytes()
    return list(zip(raw[0::3], raw[1::3], raw[2::3]))
MAGENTA_MAX_BG = 5.0        # у фонов magenta быть не должно
MIN_UNIQUE_COLORS = 8       # защита от однотонной картинки


def magenta_pct(img: Image.Image) -> float:
    """Доля пикселей, близких к magenta-хромакею.

    MiniMax рисует magenta как #FF00FF, но чаще как насыщенный розово-малиновый
    (#FA3C84 и подобные). Поэтому ловим всё семейство: R сильно больше G,
    B в среднем диапазоне, цвет насыщенный.
    """
    small = img.convert("RGB")
    if small.width * small.height > 400_000:
        small = small.resize((320, int(320 * small.height / small.width)))
    px = _pixels(small)
    hit = 0
    for r, g, b in px:
        if r > 170 and g < 130 and b > 90 and (r - g) > 80 and (b - g) > 15:
            hit += 1
    return 100.0 * hit / len(px)


def dominant_bg_pct(img: Image.Image) -> float:
    """Доля пикселей, совпадающих с доминирующим цветом по краям картинки.

    Это честная мера «сколько занимает однотонный фон» — не зависит от того,
    какой именно оттенок magenta выбрала модель.
    """
    small = img.convert("RGB")
    if small.width * small.height > 200_000:
        small = small.resize((256, int(256 * small.height / small.width)))
    w, h = small.size
    samples = []
    for x in range(0, w, 2):
        samples.append(small.getpixel((x, 0)))
        samples.append(small.getpixel((x, h - 1)))
    for y in range(0, h, 2):
        samples.append(small.getpixel((0, y)))
        samples.append(small.getpixel((w - 1, y)))
    if not samples:
        return 0.0
    from collections import Counter
    bg = Counter(samples).most_common(1)[0][0]
    br, bg_, bb = bg
    px = _pixels(small)
    hit = sum(1 for r, g, b in px
              if abs(r - br) < 45 and abs(g - bg_) < 45 and abs(b - bb) < 45)
    return 100.0 * hit / len(px)


def unique_colors(img: Image.Image, cap: int = 20000) -> int:
    small = img.convert("RGB")
    if small.width * small.height > 200_000:
        small = small.resize((320, int(320 * small.height / small.width)))
    return len(set(_pixels(small)))


def check(path: str, kind: str = "auto") -> dict:
    p = pathlib.Path(path)
    res = {"file": p.name, "ok": False, "reason": "", "px": "", "kb": 0.0,
           "magenta": 0.0, "colors": 0}

    if not p.exists():
        res["reason"] = "файл отсутствует"
        return res

    res["kb"] = round(p.stat().st_size / 1024, 1)

    # 1. валидный ли PNG и не битый
    try:
        with Image.open(p) as im:
            im.verify()
    except Exception as e:
        res["reason"] = f"PNG повреждён: {e}"
        return res

    with Image.open(p) as im:
        fmt = im.format
        w, h = im.size
        img = im.convert("RGB")

    if fmt != "PNG":
        res["reason"] = f"формат не PNG ({fmt})"
        return res
    if w < 64 or h < 64:
        res["reason"] = f"слишком маленькая картинка {w}x{h}"
        return res

    res["px"] = f"{w}x{h}"
    mp = magenta_pct(img)
    dp = dominant_bg_pct(img)
    uc = unique_colors(img)
    res["magenta"] = round(mp, 1)
    res["bgshare"] = round(dp, 1)
    res["colors"] = uc

    # 2. не однотонная
    if uc < MIN_UNIQUE_COLORS:
        res["reason"] = f"почти однотонная картинка (уникальных цветов {uc})"
        return res

    # 3. magenta-фон. Основная метрика — chroma-детектор; если модель сдвинула
    #    оттенок, спасает доля однотонного фона по краям картинки.
    if kind == "sprite":
        if mp < MAGENTA_MIN_SPRITE and dp < MAGENTA_MIN_SPRITE:
            res["reason"] = (f"мало magenta-фона (chroma {mp:.1f}%, "
                             f"однотонный фон {dp:.1f}% < {MAGENTA_MIN_SPRITE}%)")
            return res
    elif kind == "bg":
        if mp > MAGENTA_MAX_BG:
            res["reason"] = f"лишний magenta в фоне ({mp:.1f}%)"
            return res

    res["ok"] = True
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--kind", default="auto", choices=["auto", "sprite", "bg"])
    a = ap.parse_args()

    bad = 0
    for f in a.files:
        kind = a.kind
        if kind == "auto":
            kind = "bg" if pathlib.Path(f).name.startswith("bg_") else "sprite"
        r = check(f, kind)
        if r["ok"]:
            print(f"OK   {r['file']:26s} {r['px']:>9s} {r['kb']:7.1f}КБ  "
                  f"magenta={r['magenta']:5.1f}%  фон={r.get('bgshare', 0):5.1f}%  "
                  f"colors={r['colors']}")
        else:
            bad += 1
            print(f"FAIL {r['file']:26s} {r['px']:>9s} {r['kb']:7.1f}КБ  — {r['reason']}")
    print(f"\nитого: {len(a.files)} файлов, проблем: {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
