#!/usr/bin/env python3
"""Поиск и удаление мусорных артефактов (мелкие подписи/водяные знаки/крапины)
по углам сгенерированных спрайтов.

Идея: фон спрайта — однотонный chroma-цвет. Всё, что не фон, распадается на
связные компоненты. Самый большой компонент — сам объект. Любая МЕЛКАЯ
компонента, чей bbox не пересекается с bbox объекта, — мусор: заливаем её
цветом фона.

Использование:
    python3 clean_assets.py raw/chr_*.png            # отчёт (dry-run)
    python3 clean_assets.py --apply raw/chr_*.png    # почистить на месте
"""
import argparse
import pathlib
import sys
from collections import Counter, deque

from PIL import Image

SCALE = 256           # анализ на уменьшенной копии
BG_TOL = 70           # насколько пиксель должен отличаться от фона
MAX_STRAY_AREA = 0.8  # % площади картинки: мельче — считаем мусором
MIN_STRAY_PX = 4      # минимальный размер компоненты в пикселях 256x256


def _dist(a, b):
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]), abs(a[2] - b[2]))


def border_bg(im: Image.Image):
    """Доминирующий цвет по периметру картинки."""
    w, h = im.size
    pts = []
    step = max(1, w // 64)
    for x in range(0, w, step):
        pts.append(im.getpixel((x, 0)))
        pts.append(im.getpixel((x, h - 1)))
    for y in range(0, h, step):
        pts.append(im.getpixel((0, y)))
        pts.append(im.getpixel((w - 1, y)))
    return Counter(pts).most_common(1)[0][0]


def components(mask, w, h):
    """Связные компоненты (4-связность) — метки + площади + bbox."""
    labels = [[0] * w for _ in range(h)]
    comps = []
    cur = 0
    for y0 in range(h):
        for x0 in range(w):
            if not mask[y0][x0] or labels[y0][x0]:
                continue
            cur += 1
            q = deque([(x0, y0)])
            labels[y0][x0] = cur
            n = 0
            minx = maxx = x0
            miny = maxy = y0
            while q:
                x, y = q.popleft()
                n += 1
                minx = min(minx, x); maxx = max(maxx, x)
                miny = min(miny, y); maxy = max(maxy, y)
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < w and 0 <= ny < h and mask[ny][nx] and not labels[ny][nx]:
                        labels[ny][nx] = cur
                        q.append((nx, ny))
            comps.append({"label": cur, "n": n, "bbox": (minx, miny, maxx, maxy)})
    return labels, comps


def analyse(path: str):
    """Возвращает (bg, bbox_объекта, [bbox_мусора]) в координатах оригинала."""
    with Image.open(path) as im0:
        im0 = im0.convert("RGB")
        W, H = im0.size
        if W * H > 400_000:
            im = im0.resize((SCALE, max(1, round(SCALE * H / W))))
        else:
            im = im0
    w, h = im.size
    bg = border_bg(im)

    mask = []
    for y in range(h):
        row = []
        for x in range(w):
            row.append(_dist(im.getpixel((x, y)), bg) > BG_TOL)
        mask.append(row)

    labels, comps = components(mask, w, h)
    if not comps:
        return bg, (0, 0, w - 1, h - 1), []

    comps.sort(key=lambda c: -c["n"])
    main = comps[0]
    mx0, my0, mx1, my1 = main["bbox"]
    # небольшой допуск: объект может почти касаться угла
    pad = max(2, int(0.02 * w))
    sx0, sy0, sx1, sy1 = mx0 - pad, my0 - pad, mx1 + pad, my1 + pad

    total = w * h
    margin = 0.08  # внешние 8% картинки — там живут подписи/водяные знаки
    strays = []
    other = []
    for c in comps[1:]:
        area_pct = 100.0 * c["n"] / total
        if c["n"] < MIN_STRAY_PX or area_pct > MAX_STRAY_AREA:
            continue
        x0, y0, x1, y1 = c["bbox"]
        overlaps = not (x1 < sx0 or x0 > sx1 or y1 < sy0 or y0 > sy1)
        if overlaps:
            continue

        near_edge = (x0 < w * margin or y0 < h * margin
                     or x1 > w * (1 - margin) or y1 > h * (1 - margin))
        # тень: широкая плоская полоса прямо под объектом
        wide_flat = ((x1 - x0) > 3 * max(1, y1 - y0)
                     and (y1 - y0) < 0.05 * h
                     and y0 >= my1 - 4 and y0 <= my1 + 0.18 * h)
        if near_edge or wide_flat:
            strays.append((x0, y0, x1, y1, c["n"],
                           "край" if near_edge else "тень"))
        else:
            other.append((x0, y0, x1, y1, c["n"]))

    k = W / w
    main_full = tuple(int(v * k) for v in main["bbox"])
    strays_full = [tuple(int(v * k) for v in s[:4]) + tuple(s[4:]) for s in strays]
    other_full = [tuple(int(v * k) for v in s[:4]) + (s[4],) for s in other]
    return bg, main_full, strays_full, other_full


def clean(path: str, bg, strays, pad: int = 6):
    """Заливает найденный мусор цветом фона."""
    with Image.open(path) as im:
        im = im.convert("RGB")
        W, H = im.size
        from PIL import ImageDraw
        d = ImageDraw.Draw(im)
        for (x0, y0, x1, y1, *_rest) in strays:
            d.rectangle([max(0, x0 - pad), max(0, y0 - pad),
                         min(W - 1, x1 + pad), min(H - 1, y1 + pad)], fill=bg)
        im.save(path, format="PNG", optimize=True)
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--pad", type=int, default=6)
    a = ap.parse_args()

    dirty = 0
    skipped_bg = 0
    for f in a.files:
        p = pathlib.Path(f)
        if not p.exists():
            continue
        # фоны — это цельные сцены, у них нет хромакея, чистить нельзя
        if p.name.startswith("bg_"):
            skipped_bg += 1
            continue
        bg, main, strays, other = analyse(str(p))
        if strays:
            dirty += 1
            print(f"{p.name:26s} фон={bg} объект={main} мусор: "
                  + ", ".join(f"{s[5]} {s[4]}px@{s[:4]}" for s in strays))
            if a.apply:
                clean(str(p), bg, strays, a.pad)
                print(f"{'':26s} -> очищено")
        else:
            print(f"{p.name:26s} чисто")
        if other:
            print(f"{'':26s} (не тронуто, не у края и не тень: "
                  + ", ".join(f"{s[4]}px@{s[:4]}" for s in other) + ")")
    print(f"\nс мусором: {dirty} из {len(a.files)}"
          f" (фонов пропущено: {skipped_bg})"
          + ("  (применено)" if a.apply else "  (dry-run, запусти с --apply)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
