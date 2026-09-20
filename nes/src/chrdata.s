; Данные графического ПЗУ (8 КБ плиток), подключены в сегмент CHARS.
; Файл chr/tiles.chr создаётся скриптом tools/make_chr.py.

.segment "CHARS"

.export _chr_data
_chr_data:
    .incbin "chr/tiles.chr"
