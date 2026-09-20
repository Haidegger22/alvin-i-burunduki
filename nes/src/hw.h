/* Регистры и константы NES (адреса процессора и PPU).
 * Подключается и к C-коду, и к ассемблеру через #include — для ассемблера
 * часть определений дублируется в crt0.s.
 */
#ifndef HW_H
#define HW_H

/* --- регистры PPU --- */
#define PPUCTRL   (*(volatile unsigned char*)0x2000)
#define PPUMASK   (*(volatile unsigned char*)0x2001)
#define PPUSTATUS (*(volatile unsigned char*)0x2002)
#define OAMADDR   (*(volatile unsigned char*)0x2003)
#define OAMDATA   (*(volatile unsigned char*)0x2004)
#define PPUSCROLL (*(volatile unsigned char*)0x2005)
#define PPUADDR   (*(volatile unsigned char*)0x2006)
#define PPUDATA   (*(volatile unsigned char*)0x2007)
#define OAMDMA    (*(volatile unsigned char*)0x4014)

/* --- регистры APU и ввода --- */
#define APUSTATUS (*(volatile unsigned char*)0x4015)
#define JOY1      (*(volatile unsigned char*)0x4016)
#define JOY2      (*(volatile unsigned char*)0x4017)

/* --- биты кнопок после чтения геймпада (порядок как на NES) --- */
#define BTN_A      0x01
#define BTN_B      0x02
#define BTN_SELECT 0x04
#define BTN_START  0x08
#define BTN_UP     0x10
#define BTN_DOWN   0x20
#define BTN_LEFT   0x40
#define BTN_RIGHT  0x80

/* --- адреса в PPU --- */
#define PPU_PALETTE  0x3F00
#define PPU_NAMETABLE 0x2000
#define PPU_ATTR      0x23C0

/* --- размеры экрана в плитках --- */
#define SCREEN_W_TILES 32
#define SCREEN_H_TILES 30
#define VIEW_W 256
#define VIEW_H 240

/* --- буфер спрайтов (теневой OAM), заполняется игрой, копируется в NMI --- */
#define OAM_BUF ((unsigned char*)0x0200)

#endif
