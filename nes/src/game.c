/* Элвин и бурундуки — NES-версия. Этап 1: каркас, движение, прыжок, кнопки.
 *
 * Ограничения платформы, о которых нужно помнить:
 *   - 2 КБ оперативной памяти, поэтому никаких больших массивов;
 *   - рендеринг только во время vblank, готовая картинка «застывает» между кадрами;
 *   - спрайты 8x8, персонаж 16x16 — это четыре спрайта в буфере OAM;
 *   - читать память PPU обратно нельзя, поэтому карта столкновений живёт в ПЗУ.
 */
#include "hw.h"
#include "tiles.h"

/* --- переменные из crt0.s --- */
extern volatile unsigned char frame_counter;
extern unsigned char scroll_x;
extern unsigned char ppu_ctrl_val;

/* --- данные графического ПЗУ (предоставляет chrdata.s) --- */
extern const unsigned char chr_data[8192];

/* ------------------------------------------------------------------ ввод */
#define PAD_PORT JOY1

static unsigned char pad;          /* текущее состояние кнопок */
static unsigned char pad_new;      /* кнопки, нажатые именно в этом кадре */
static unsigned char pad_prev;

/* объявления заранее: демо-функции ниже вызывают эти помощники */
static void ppu_addr(unsigned int addr);
static void ppu_fill(unsigned int addr, unsigned char tile, unsigned int count);

#ifdef DEMO_AUTOPILOT
/* Авто-пилот демо-сборки: ведёт персонажа вправо и подпрыгивает.
 * Нужен, чтобы проверить игру без внешнего ввода и записать видео. */
static unsigned char demo_timer;
static void demo_input(void) {
    demo_timer++;
    pad = BTN_RIGHT;
    pad_new = 0;
    if ((demo_timer % 40) == 0) pad_new = BTN_A;   /* прыжок раз в 40 кадров */
    pad_prev = pad;
}
#endif

#if defined(DEMO_AUTOPILOT) || defined(BLINK_ALIVE)
/* Мигающее сердце: доказательство того, что кадры идут */
static unsigned char blink_state;
static void demo_blink(void) {
    if ((frame_counter & 0x1F) == 0) {
        blink_state ^= 1;
        ppu_fill(PPU_NAMETABLE + 1 * 32 + 5, blink_state ? TILE_SKY : TILE_HEART, 1);
    }
}
#endif

static void read_pad(void) {
    unsigned char i, v = 0;
    PAD_PORT = 1;
    PAD_PORT = 0;
    for (i = 0; i < 8; i++) {
        v = (unsigned char)(v << 1);
        v |= (unsigned char)(PAD_PORT & 1);
    }
    pad_prev = pad;
    pad = v;
    pad_new = (unsigned char)(pad & ~pad_prev);   /* нажатия в этом кадре */
}

/* ------------------------------------------------------------------ PPU */
static void ppu_addr(unsigned int addr) {
    PPUSTATUS = 0;
    PPUADDR = (unsigned char)(addr >> 8);
    PPUADDR = (unsigned char)(addr & 0xFF);
}

static void ppu_fill(unsigned int addr, unsigned char tile, unsigned int count) {
    unsigned int i;
    ppu_addr(addr);
    for (i = 0; i < count; i++) PPUDATA = tile;
}

static void ppu_copy_palettes(void) {
    /* 32 отдельные записи: так исключаем ошибки циклов и указателей.
     * Первый байт ($3F00) — цвет фона, он виден на пустых местах экрана. */
    ppu_addr(PPU_PALETTE);
    PPUDATA = palette_bg[0];  PPUDATA = palette_bg[1];
    PPUDATA = palette_bg[2];  PPUDATA = palette_bg[3];
    PPUDATA = palette_bg[4];  PPUDATA = palette_bg[5];
    PPUDATA = palette_bg[6];  PPUDATA = palette_bg[7];
    PPUDATA = palette_bg[8];  PPUDATA = palette_bg[9];
    PPUDATA = palette_bg[10]; PPUDATA = palette_bg[11];
    PPUDATA = palette_bg[12]; PPUDATA = palette_bg[13];
    PPUDATA = palette_bg[14]; PPUDATA = palette_bg[15];
    PPUDATA = palette_spr[0];  PPUDATA = palette_spr[1];
    PPUDATA = palette_spr[2];  PPUDATA = palette_spr[3];
    PPUDATA = palette_spr[4];  PPUDATA = palette_spr[5];
    PPUDATA = palette_spr[6];  PPUDATA = palette_spr[7];
    PPUDATA = palette_spr[8];  PPUDATA = palette_spr[9];
    PPUDATA = palette_spr[10]; PPUDATA = palette_spr[11];
    PPUDATA = palette_spr[12]; PPUDATA = palette_spr[13];
    PPUDATA = palette_spr[14]; PPUDATA = palette_spr[15];

    /* ВАЖНО: адрес $3F10 аппаратно зеркалит $3F00, поэтому первая запись
     * палитры спрайтов затирает цвет фона. Возвращаем его на место. */
    ppu_addr(PPU_PALETTE);
    PPUDATA = palette_bg[0];
}

static void ppu_copy_chr(void) {
    unsigned int i;
    ppu_addr(0x0000);
    for (i = 0; i < 8192; i++) PPUDATA = chr_data[i];
}

/* ------------------------------------------------------------- уровень */
/* Платформы: x, y (в пикселях), ширина в тайлах. Лежат в ПЗУ. */
typedef struct {
    unsigned char x;
    unsigned char y;
    unsigned char len;
} platform_t;

static const platform_t platforms[] = {
    { 40, 168, 3 },
    { 96, 136, 4 },
    { 152, 168, 3 },
    { 200, 120, 3 },
    { 56, 104, 3 },
};
#define PLATFORM_COUNT (sizeof(platforms) / sizeof(platforms[0]))

#define GROUND_Y 200            /* верх земли в пикселях (строка 25) */

static void draw_level(void) {
    unsigned char i, t;
    unsigned int addr;

    /* небо на весь экран */
    ppu_fill(PPU_NAMETABLE, TILE_SKY, 32 * 30);

    /* земля: строка травы и две строки грунта */
    ppu_fill(PPU_NAMETABLE + 25 * 32, TILE_GRASS, 32);
    ppu_fill(PPU_NAMETABLE + 26 * 32, TILE_DIRT, 32 * 2);

    /* платформы */
    for (i = 0; i < PLATFORM_COUNT; i++) {
        addr = PPU_NAMETABLE + (unsigned int)platforms[i].y / 8 * 32 + platforms[i].x / 8;
        for (t = 0; t < platforms[i].len; t++) {
            ppu_fill(addr + t, TILE_PLATFORM, 1);
        }
    }

    /* два ящика на земле — их можно будет поднимать на следующем этапе */
    ppu_fill(PPU_NAMETABLE + 24 * 32 + 6, TILE_CRATE, 1);
    ppu_fill(PPU_NAMETABLE + 24 * 32 + 20, TILE_CRATE, 1);

    /* Таблица атрибутов: какие палитры у квадрантов фона.
     * Если её не заполнить, PPU берёт оттуда мусор, и цвета уезжают. */
    ppu_fill(PPU_ATTR, 0, 64);

    /* слоты индикатора кнопок над землёй */
    ppu_fill(PPU_NAMETABLE + 24 * 32 + 12, TILE_PLATFORM, 15);

    /* панель: три сердца слева */
    ppu_fill(PPU_NAMETABLE + 1 * 32 + 1, TILE_HEART, 1);
    ppu_fill(PPU_NAMETABLE + 1 * 32 + 3, TILE_HEART, 1);
    ppu_fill(PPU_NAMETABLE + 1 * 32 + 5, TILE_HEART, 1);
}

/* ------------------------------------------------------------- игрок */
#define PLAYER_W 16
#define PLAYER_H 16

static unsigned char px;          /* позиция (пиксели, целые) */
static unsigned char py;
static signed char pvx;
static signed char pvy;
static unsigned char on_ground;

static unsigned char ground_under(unsigned char x, unsigned char y) {
    /* земля на всю ширину экрана */
    if (y >= GROUND_Y) return 1;
    return 0;
}

static unsigned char platform_under(unsigned char x, unsigned char y) {
    unsigned char i;
    for (i = 0; i < PLATFORM_COUNT; i++) {
        unsigned char left = platforms[i].x;
        unsigned char right = (unsigned char)(platforms[i].x + platforms[i].len * 8);
        if (y >= platforms[i].y && y <= (unsigned char)(platforms[i].y + 6)
            && x + PLAYER_W > left && x < right) {
            return 1;
        }
    }
    return 0;
}

static void update_player(void) {
    if (pad & BTN_LEFT) pvx = (signed char)-2;
    else if (pad & BTN_RIGHT) pvx = 2;
    else pvx = 0;

    if ((pad_new & BTN_A) && on_ground) {
        pvy = (signed char)-6;
        on_ground = 0;
    }

    /* горизонталь */
    if (pvx < 0 && px < 2) pvx = 0;
    if (pvx > 0 && px > (unsigned char)(VIEW_W - PLAYER_W - 2)) pvx = 0;
    px = (unsigned char)(px + pvx);

    /* вертикаль */
    pvy = (signed char)(pvy + 1);           /* гравитация */
    if (pvy > 6) pvy = 6;
    if (pvy < 0) {
        unsigned char ny = (unsigned char)(py + pvy);
        py = ny;                             /* вверх — без проверки потолка */
    } else {
        unsigned char ny = (unsigned char)(py + pvy);
        unsigned char feet = (unsigned char)(ny + PLAYER_H);
        if (ground_under(px, feet) || platform_under(px, feet)) {
            /* приземлились: ставим ноги ровно на опору */
            if (ground_under(px, feet)) py = (unsigned char)(GROUND_Y - PLAYER_H);
            else py = (unsigned char)(ny);
            pvy = 0;
            on_ground = 1;
            if (!ground_under(px, feet)) {
                /* на платформе: подтягиваем к её верхней кромке */
                unsigned char i;
                for (i = 0; i < PLATFORM_COUNT; i++) {
                    unsigned char left = platforms[i].x;
                    unsigned char right = (unsigned char)(platforms[i].x + platforms[i].len * 8);
                    if (feet >= platforms[i].y && feet <= (unsigned char)(platforms[i].y + 6)
                        && px + PLAYER_W > left && px < right) {
                        py = (unsigned char)(platforms[i].y - PLAYER_H);
                    }
                }
            }
        } else {
            py = ny;
            on_ground = 0;
        }
    }
}

/* Индикатор кнопок: восемь «лампочек» над землёй, по одной на кнопку геймпада
 * (A, B, Select, Start, вверх, вниз, влево, вправо). Горит — кнопка нажата.
 * Нужен, чтобы сразу видеть: ввод доходит до игры. */
static void draw_buttons(void) {
    unsigned char i;
    for (i = 0; i < 8; i++) {
        unsigned char lit = (unsigned char)((pad >> i) & 1);
        ppu_fill(PPU_NAMETABLE + 24 * 32 + 12 + i * 2, lit ? TILE_HEART : TILE_PLATFORM, 1);
    }
}

static void draw_player(void) {
    unsigned char pal = 0;                 /* палитра 0 — Элвин */
    unsigned char tile_y = (unsigned char)(py - 1);   /* у спрайтов NES Y на 1 меньше */
    unsigned char *oam = OAM_BUF;

    /* верхний ряд: две плитки */
    oam[0] = tile_y;         oam[1] = TILE_PLAYER_TL; oam[2] = pal;        oam[3] = px;
    oam[4] = tile_y;         oam[5] = TILE_PLAYER_TR; oam[6] = pal;        oam[7] = (unsigned char)(px + 8);
    /* нижний ряд */
    oam[8] = (unsigned char)(tile_y + 8);  oam[9] = TILE_PLAYER_BL;  oam[10] = pal; oam[11] = px;
    oam[12] = (unsigned char)(tile_y + 8); oam[13] = TILE_PLAYER_BR; oam[14] = pal; oam[15] = (unsigned char)(px + 8);

    /* остальные спрайты уводим за экран */
    {
        unsigned char i;
        for (i = 4; i < 64; i++) {
            oam[i * 4] = 0xF0;      /* Y = 240 — невидимо */
            oam[i * 4 + 1] = TILE_SKY;
            oam[i * 4 + 2] = 0;
            oam[i * 4 + 3] = 0;
        }
    }
}

/* --------------------------------------------------------------- запуск */
#ifdef DIAG_BARS
/* Диагностика: две полосы вверху экрана. Верхняя — X персонажа (по 8 пикселей
 * на плитку), нижняя — Y. Позволяет точно измерить реакцию на кнопки. */
static unsigned char last_px_bar, last_py_bar;
static void diag_bars(void) {
    unsigned char bx = (unsigned char)(px / 8);
    unsigned char by = (unsigned char)(py / 8);
    if (bx != last_px_bar) {
        ppu_fill(PPU_NAMETABLE + 1 * 32, TILE_SKY, 32);
        if (bx) ppu_fill(PPU_NAMETABLE + 1 * 32, TILE_HEART, bx);
        last_px_bar = bx;
    }
    if (by != last_py_bar) {
        ppu_fill(PPU_NAMETABLE + 2 * 32, TILE_SKY, 32);
        if (by) ppu_fill(PPU_NAMETABLE + 2 * 32, TILE_HEART, by);
        last_py_bar = by;
    }
}
#endif

static void wait_frame(void) {
    unsigned char f = frame_counter;
    while (frame_counter == f) {
        /* ждём NMI */
    }
}

void main(void) {
    ppu_ctrl_val = 0x80;      /* NMI включён; и фон, и спрайты берут плитки из $0000 */
    scroll_x = 0;

#ifdef TEST_PATTERN
    /* Тестовый рисунок: одна плитка (травa) на весь экран, атрибуты в нули,
     * палитра фона — три ярких цвета. По нему видно, что именно работает. */
    {
        unsigned int a;
        ppu_copy_chr();
        ppu_fill(PPU_NAMETABLE, TILE_GRASS, 32 * 30);
        ppu_fill(PPU_ATTR, 0, 64);
        ppu_addr(PPU_PALETTE);
        PPUDATA = 0x16;   /* красный */
        PPUDATA = 0x19;   /* зелёный */
        PPUDATA = 0x11;   /* синий */
        PPUDATA = 0x0F;   /* чёрный */
        for (a = 0; a < 12; a++) PPUDATA = 0x0F;
        PPUDATA = 0x0F; PPUDATA = 0x16; PPUDATA = 0x17; PPUDATA = 0x0F;
        for (a = 0; a < 12; a++) PPUDATA = 0x0F;
        PPUMASK = 0x1E;
        PPUCTRL = ppu_ctrl_val;
        for (;;) {
            wait_frame();
            draw_player();
        }
    }
#endif

    ppu_copy_chr();      /* сначала плитки */
    draw_level();        /* затем карта уровня */
    ppu_copy_palettes(); /* палитру — последней */

    px = 32;
    py = (unsigned char)(GROUND_Y - PLAYER_H);
    pvx = 0;
    pvy = 0;
    on_ground = 1;

    PPUMASK = 0x1E;           /* показываем фон и спрайты */
    PPUCTRL = ppu_ctrl_val;

    for (;;) {
        wait_frame();
        read_pad();
#ifdef DEMO_AUTOPILOT
        demo_input();
#endif
#if defined(DEMO_AUTOPILOT) || defined(BLINK_ALIVE)
        demo_blink();
#endif
        update_player();
        draw_player();
        draw_buttons();
#ifdef DIAG_BARS
        diag_bars();
#endif
    }
}
