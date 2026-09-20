#!/usr/bin/env python3
"""Генерация картинок через MiniMax (image-01) — для ассетов игры.

Использование:
    python3 mmgen.py "промпт" /путь/куда/сохранить.png [--ratio 16:9|1:1|9:16]

Ключ берётся из ~/.hermes/.env (MINIMAX_API_KEY), в коде и в выводе не печатается.
"""
import argparse
import json
import os
import pathlib
import sys
import urllib.request

ENV = pathlib.Path("/home/orangepi/.hermes/.env")
API = "https://api.minimax.io/v1/image_generation"


def read_key() -> str:
    for line in ENV.read_text(encoding="utf-8").splitlines():
        if line.startswith("MINIMAX_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    sys.exit("не нашёл MINIMAX_API_KEY в ~/.hermes/.env")


def generate(prompt: str, out_path: str, ratio: str = "16:9") -> str:
    key = read_key()
    body = json.dumps({
        "model": "image-01",
        "prompt": prompt,
        "aspect_ratio": ratio,
        "response_format": "url",
        "n": 1,
        "prompt_optimizer": True,
    }).encode()

    req = urllib.request.Request(API, data=body, headers={
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = json.loads(resp.read())

    base = data.get("base_resp", {})
    if base.get("status_code") not in (0, None):
        sys.exit(f"ошибка API {base.get('status_code')}: {base.get('status_msg')}")

    urls = data.get("data", {}).get("image_urls", [])
    if not urls:
        sys.exit(f"нет ссылки на картинку в ответе: {str(data)[:200]}")

    target = pathlib.Path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(urls[0], timeout=180) as img:
        raw = img.read()

    # MiniMax image-01 отдаёт JPEG — перекодируем в настоящий PNG.
    import io

    from PIL import Image

    with Image.open(io.BytesIO(raw)) as im:
        src_fmt = im.format
        im.convert("RGB").save(target, format="PNG", optimize=True)

    return f"{target} ({target.stat().st_size // 1024} КБ, источник {src_fmt})"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("prompt")
    ap.add_argument("out")
    ap.add_argument("--ratio", default="16:9", choices=["16:9", "1:1", "9:16"])
    args = ap.parse_args()
    print("готово:", generate(args.prompt, args.out, args.ratio))


if __name__ == "__main__":
    main()
