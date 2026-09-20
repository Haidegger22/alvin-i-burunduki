#!/usr/bin/env python3
"""Пакетная генерация всех ассетов игры через MiniMax + валидация + перегенерация.

Запуск:
    cd /home/orangepi/games/alvin-chipmunks
    python3 tools/build_assets.py [--workers 3] [--only chr_ ,bg_] [--force]

Логика: для каждого ассета пытаемся до MAX_ATTEMPTS раз. После каждой попытки
файл валидируется (PNG / размеры / % magenta / не однотонная). Если не прошёл —
меняем промпт на более настойчивый вариант и пробуем снова.
"""
import argparse
import concurrent.futures as cf
import pathlib
import subprocess
import sys
import threading
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from assets_def import build_list                      # noqa: E402
from validate_assets import check                      # noqa: E402

ROOT = pathlib.Path("/home/orangepi/games/alvin-chipmunks")
RAW = ROOT / "raw"
MMGEN = ROOT / "tools" / "mmgen.py"
MAX_ATTEMPTS = 4

_print_lock = threading.Lock()


def log(msg: str) -> None:
    with _print_lock:
        print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# --------------------------------------------------------- варианты промпта
def prompt_variants(item: dict) -> list:
    """Список промптов: базовый + уточнённые для повторных попыток."""
    base = item["prompt"]
    kind = item["kind"]

    if kind == "bg":
        return [
            base,
            base + ", wide panoramic landscape scene, flat shaded pixel art",
            base + ", 16-bit inspired pixel art scenery, lots of detail, blue sky",
            base + ", retro videogame background art, rich detail, no text",
        ]

    # спрайты
    v2 = (base.rstrip(".")
          + ", the single subject is isolated and centred, filling most of the frame, "
            "every empty area is pure flat magenta #FF00FF")
    v3 = (base.rstrip(".")
          + ", absolutely only one object in the whole image, no extra objects, "
            "no border frame, no background pattern, pure magenta #FF00FF fills the rest")
    core = base.replace("plain solid magenta #FF00FF background, ", "")
    v4 = ("8-bit NES game sprite asset, " + core
          + ", drawn on a pure flat magenta #FF00FF chroma-key backdrop, one isolated object")
    return [base, v2, v3, v4]


# --------------------------------------------------------------- генерация
def gen_one(item: dict, force: bool = False) -> dict:
    fname = item["file"]
    out = RAW / fname

    if force and out.exists():
        out.unlink()

    if out.exists():
        r = check(str(out), item["kind"])
        if r["ok"]:
            log(f"SKIP {fname:26s} уже готов и валиден ({r['px']}, {r['kb']}КБ)")
            return {"file": fname, "ok": True, "attempts": 0, "skipped": True, "result": r}

    variants = prompt_variants(item)
    history = []

    for attempt in range(1, MAX_ATTEMPTS + 1):
        prompt = variants[min(attempt - 1, len(variants) - 1)]
        log(f"GEN  {fname:26s} попытка {attempt}/{MAX_ATTEMPTS} ({item['ratio']})")
        try:
            p = subprocess.run(
                [sys.executable, str(MMGEN), prompt, str(out), "--ratio", item["ratio"]],
                capture_output=True, text=True, timeout=300, cwd=str(ROOT),
            )
        except subprocess.TimeoutExpired:
            history.append("timeout")
            log(f"TMO  {fname:26s} таймаут")
            continue

        if p.returncode != 0:
            err = (p.stderr or p.stdout).strip().splitlines()[-1:] or ["?"]
            history.append(f"ошибка запуска: {err[0]}")
            log(f"ERR  {fname:26s} {err[0]}")
            time.sleep(4)
            continue

        r = check(str(out), item["kind"])
        if r["ok"]:
            log(f"OK   {fname:26s} попытка {attempt}: {r['px']} {r['kb']}КБ "
                f"magenta={r['magenta']}% colors={r['colors']}")
            return {"file": fname, "ok": True, "attempts": attempt,
                    "skipped": False, "result": r, "history": history}

        history.append(f"попытка {attempt}: {r['reason']}")
        log(f"BAD  {fname:26s} попытка {attempt}: {r['reason']}")
        time.sleep(2)

    r = check(str(out), item["kind"])
    return {"file": fname, "ok": False, "attempts": MAX_ATTEMPTS, "skipped": False,
            "result": r, "history": history}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--only", default="", help="фильтр имени файла (через запятую)")
    ap.add_argument("--force", action="store_true", help="перегенерировать даже готовые")
    a = ap.parse_args()

    RAW.mkdir(parents=True, exist_ok=True)
    items = build_list()
    if a.only:
        keys = [k.strip() for k in a.only.split(",") if k.strip()]
        items = [i for i in items if any(k in i["file"] for k in keys)]

    log(f"старт: {len(items)} ассетов, воркеров {a.workers}")
    t0 = time.time()

    results = []
    with cf.ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(gen_one, it, a.force): it for it in items}
        for f in cf.as_completed(futs):
            results.append(f.result())

    dt = time.time() - t0
    ok = [r for r in results if r["ok"]]
    bad = [r for r in results if not r["ok"]]

    log(f"ГОТОВО за {dt/60:.1f} мин: успешно {len(ok)}/{len(results)}")
    if bad:
        log("НЕ ПРОШЛИ ВАЛИДАЦИЮ:")
        for r in bad:
            log(f"   {r['file']}: {r['result'].get('reason')} | {r.get('history')}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
