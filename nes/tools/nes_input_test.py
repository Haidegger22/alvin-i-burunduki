#!/usr/bin/env python3
"""Автопроверка кнопок NES-версии: запускает ROM в RetroArch, жмёт клавиши
через xdotool и по кадрам смотрит, сдвинулся ли персонаж и подпрыгнул ли он.

Запуск (нужна графическая сессия X11/Wayland с XWayland):
    python3 tools/nes_input_test.py build/alvin.nes

Что делает:
  1. поднимает RetroArch с указанным ROM на экране :0,
  2. снимает кадр до нажатий и определяет положение персонажа
     (ищет пиксели цвета свитера в игровом поле),
  3. жмёт «вправо», снимает кадр и проверяет смещение,
  4. жмёт «прыжок» и проверяет, что персонаж оказался выше земли,
  5. закрывает RetroArch и печатает отчёт.
"""
import pathlib
import subprocess
import sys
import time

from PIL import Image, ImageChops

CORE = "/usr/lib/aarch64-linux-gnu/libretro/nestopia_libretro.so"
DISPLAY = ":0"
ENV = {"DISPLAY": DISPLAY, "XAUTHORITY": "/home/orangepi/.Xauthority",
       "PATH": "/usr/bin:/bin:/usr/local/bin"}

# цвета NES в кадре (как их рисует nestopia): свитер Элвина и шерсть
SWEATER = (216, 40, 0)


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, env=ENV, **kw)


def window_geometry():
    out = run(["xdotool", "search", "--class", "retroarch"]).stdout.split()
    if not out:
        return None
    wid = out[-1]
    geo = run(["xdotool", "getwindowgeometry", "--shell", wid]).stdout
    data = dict(line.split("=") for line in geo.strip().splitlines() if "=" in line)
    return int(data["X"]), int(data["Y"]), int(data["WIDTH"]), int(data["HEIGHT"])


def shot(path: str, geom):
    subprocess.run(["scrot", "-o", "/tmp/_nes_full.png"], env=ENV, check=True)
    im = Image.open("/tmp/_nes_full.png").convert("RGB")
    x, y, w, h = geom
    im.crop((x, y, x + w, y + h)).save(path)
    return Image.open(path).convert("RGB")


def find_player(im: Image.Image):
    """Ищет пиксели свитера и возвращает (x центра, y центра) или None."""
    w, h = im.size
    xs, ys = [], []
    for yy in range(0, h, 2):
        for xx in range(0, w, 2):
            r, g, b = im.getpixel((xx, yy))
            if abs(r - SWEATER[0]) < 60 and g < 90 and b < 70:
                xs.append(xx)
                ys.append(yy)
    if not xs:
        return None
    return sum(xs) / len(xs), sum(ys) / len(ys)


def key(code: str, hold: float = 0.0, press: bool = True):
    if press:
        run(["xdotool", "keydown", code])
    else:
        run(["xdotool", "keyup", code])
    if hold:
        time.sleep(hold)
        run(["xdotool", "keyup", code])


def main() -> int:
    rom = sys.argv[1] if len(sys.argv) > 1 else "build/alvin.nes"
    rom_path = str(pathlib.Path(rom).resolve())

    proc = subprocess.Popen(
        ["retroarch", "-L", CORE, rom_path, "--verbose", "--appendconfig", "/tmp/ra_test.cfg"],
        env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(9)                      # ждём загрузку ядра и игры
        geom = None
        for _ in range(20):
            geom = window_geometry()
            if geom:
                break
            time.sleep(1)
        if not geom:
            print("не нашёл окно RetroArch")
            return 1
        print("окно RetroArch:", geom)

        run(["xdotool", "windowactivate", "--sync", run(["xdotool", "search", "--class", "retroarch"]).stdout.split()[-1]])
        time.sleep(1)

        before = shot("/tmp/nes_before.png", geom)
        p0 = find_player(before)
        print("персонаж до нажатий:", p0)
        if p0 is None:
            print("не вижу персонажа — возможно, кадр ещё не отрисован")
            return 1

        # вправо: кнопка крестовины
        key("Right", hold=1.6)
        time.sleep(0.4)
        mid = shot("/tmp/nes_after_right.png", geom)
        p1 = find_player(mid)
        print("после «вправо»:", p1)

        # прыжок: кнопка A (по конфигу RetroArch — numpad 0)
        run(["xdotool", "keydown", "KP_0"])
        time.sleep(0.45)                   # ловим кадр в воздухе
        air = shot("/tmp/nes_jump.png", geom)
        run(["xdotool", "keyup", "KP_0"])
        p2 = find_player(air)
        print("в прыжке:", p2)

        dx = (p1[0] - p0[0]) if p1 else 0
        dy_air = (p0[1] - p2[1]) if p2 else 0
        print()
        print("=== результат:")
        print(f"   сдвиг вправо: {dx:.1f} пикселей экрана (ожидается > 5)")
        print(f"   подъём в прыжке: {dy_air:.1f} пикселей (ожидается > 5)")
        ok_move = dx > 5
        ok_jump = dy_air > 5
        print(f"   кнопка «вправо»: {'работает' if ok_move else 'НЕ работает'}")
        print(f"   кнопка «прыжок»: {'работает' if ok_jump else 'НЕ работает'}")
        return 0 if (ok_move and ok_jump) else 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    sys.exit(main())
