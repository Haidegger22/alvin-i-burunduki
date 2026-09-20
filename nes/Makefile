# Сборка NES-версии «Элвина и бурундуков» (NROM-256, mapper 0)
#
#   make          — собрать ROM в build/alvin.nes
#   make chr      — пересобрать графическое ПЗУ из assets/sprites/*.png
#   make clean    — убрать сборку
#   make run      — запустить в RetroArch (ядро nestopia)
#
# Требуется cc65 (пакет Debian: cc65) и python3-pil для сборки графики.

CL65    = cl65
CFG     = cfg/nrom.cfg
ROM     = build/alvin.nes
TARGET  = nes
CORE    = /usr/lib/aarch64-linux-gnu/libretro/nestopia_libretro.so

SOURCES = src/crt0.s src/chrdata.s src/game.c
HEADERS = src/hw.h chr/tiles.h

# -Oirs: оптимизация, без лишних проверок времени выполнения
CFLAGS  = -t $(TARGET) -C $(CFG) -I chr -Oirs -T -g

DEMOROM = build/alvin-demo.nes

all: $(ROM)

# демо-сборка: игру ведёт встроенный авто-пилот, удобно для проверки и записи видео
demo: $(SOURCES) $(HEADERS) chr/tiles.chr
	@mkdir -p build
	$(CL65) $(CFLAGS) -DDEMO_AUTOPILOT -o $(DEMOROM) $(SOURCES) -m build/alvin-demo.map
	@ls -l $(DEMOROM) | awk '{print "готово:", $$9, $$5, "байт"}'

chr:
	python3 tools/make_chr.py

$(ROM): $(SOURCES) $(HEADERS) chr/tiles.chr
	@mkdir -p build
	$(CL65) $(CFLAGS) -o $(ROM) $(SOURCES) -m build/alvin.map
	@ls -l $(ROM) | awk '{print "готово:", $$9, $$5, "байт"}'

chr/tiles.chr: tools/make_chr.py ../assets/sprites/chr_alvin_stand.png
	python3 tools/make_chr.py

run: $(ROM)
	retroarch -L $(CORE) $(ROM)

clean:
	rm -rf build chr/tiles.chr chr/tiles.h

.PHONY: all demo chr run clean

