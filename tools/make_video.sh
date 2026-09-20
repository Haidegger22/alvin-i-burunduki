#!/bin/bash
# Сборка видео из кадров, снятых через tools/shoot.js
#
# Использование:
#   tools/make_video.sh <каталог-кадров> <выходной-файл.mp4> [аудио.ogg] [кадров/с]
#
# Пример:
#   tools/make_video.sh /tmp/game_frames video/alvin-level1.mp4 assets/audio/level.ogg 12
set -euo pipefail

FRAMES="${1:?укажите каталог с кадрами}"
OUT="${2:?укажите выходной файл}"
AUDIO="${3:-}"
FPS="${4:-12}"
FFMPEG="${FFMPEG:-/home/orangepi/bin/ffmpeg}"

mkdir -p "$(dirname "$OUT")"

if [ -n "$AUDIO" ] && [ -f "$AUDIO" ]; then
  "$FFMPEG" -y -loglevel error \
    -framerate "$FPS" -i "$FRAMES/frame_%04d.png" \
    -i "$AUDIO" \
    -vf "scale=960:576:flags=neighbor" \
    -c:v libx264 -pix_fmt yuv420p -crf 20 -preset veryfast \
    -c:a aac -b:a 128k -shortest \
    -movflags +faststart "$OUT"
else
  "$FFMPEG" -y -loglevel error \
    -framerate "$FPS" -i "$FRAMES/frame_%04d.png" \
    -vf "scale=960:576:flags=neighbor" \
    -c:v libx264 -pix_fmt yuv420p -crf 20 -preset veryfast \
    -movflags +faststart "$OUT"
fi

echo "готово: $OUT ($(du -h "$OUT" | cut -f1))"
