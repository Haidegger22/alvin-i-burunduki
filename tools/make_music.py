#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_music.py - мини-трекер в стиле NES (2A03) на чистой стандартной библиотеке Python.
numpy НЕ используется.

Каналы:
  pulse  - прямоугольная волна, скважность 12.5% / 25% / 50%, атака/затухание
           (линейный спад как в NES volume envelope) + вибрато,
  tri    - triangle, бас, без затухания, квантование 16 уровней (NES-характер),
  noise  - LFSR 15-бит / 6-бит (ударные: кик, снейр, том, хэт, крэш),
  arp    - быстрый arpeggio-аккорд (классические чиптюн-аккорды ~65 Гц).

Формат: 22050 Гц, моно, 16 бит PCM WAV. Пик нормализуется до 0.85 (без клиппинга),
на границах файла - короткие fade in/out (кликов нет), level.wav = целое число тактов
и бесшовно зацикливается.

Запуск:
  /usr/bin/python3 tools/make_music.py            # сгенерировать wav + ogg
  /usr/bin/python3 tools/make_music.py --verify   # проверить уже готовые файлы
"""

import array
import math
import os
import struct
import subprocess
import sys
import wave

SR = 22050
PEAK_TARGET = 0.85  # нормализация пика

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
OUT_DIR = os.path.join(PROJ, "assets", "audio")

# ---------------------------------------------------------------------------
# нотная нотация
# ---------------------------------------------------------------------------
_STEPS = {'c': 0, 'd': 2, 'e': 4, 'f': 5, 'g': 7, 'a': 9, 'b': 11}
_NAMES = ['c', 'c#', 'd', 'd#', 'e', 'f', 'f#', 'g', 'g#', 'a', 'a#', 'b']


def note_to_midi(tok):
    """'c5' -> 60, 'f#4' -> 66, 'r' -> None."""
    t = tok.strip().lower()
    if not t or t[0] in 'r.':
        return None
    i = 0
    semi = _STEPS.get(t[i])
    if semi is None:
        raise ValueError('плохая нота: %r' % tok)
    i += 1
    while i < len(t) and t[i] in '#b':
        semi += 1 if t[i] == '#' else -1
        i += 1
    octv = int(t[i:])
    return 12 * (octv + 1) + semi


def midi_to_name(m):
    return '%s%d' % (_NAMES[m % 12], m // 12 - 1)


def midi_to_freq(m):
    return 440.0 * (2.0 ** ((m - 69) / 12.0))


def parse_seq(text):
    """Строка нот -> список (midi|None, rows).
    Токен: 'c5' (1 строка), 'c5:4' (4 строки), 'r:8' (пауза), '-:2' (тянуть)."""
    ev = []
    for tok in text.split():
        if ':' in tok:
            name, _, ds = tok.partition(':')
            rows = int(ds)
        else:
            name, rows = tok, 1
        if rows <= 0:
            raise ValueError('нулевая длительность: %r' % tok)
        if name == '-':
            if not ev:
                raise ValueError('тянущаяся нота без ноты')
            ev[-1] = (ev[-1][0], ev[-1][1] + rows)
            continue
        ev.append((note_to_midi(name), rows))
    return ev


def seq(*bars):
    return ' '.join(bars)


def check_rows(name, ev, bars):
    t = sum(r for _, r in ev)
    if t != bars * 16:
        raise SystemExit('[%s] сумма строк %d != %d (тактов %d)'
                         % (name, t, bars * 16, bars))


# ---------------------------------------------------------------------------
# аккорды
# ---------------------------------------------------------------------------
QUAL = {'maj': (0, 4, 7), 'min': (0, 3, 7), 'sus4': (0, 5, 7),
        'dom7': (0, 4, 7, 10), 'maj7': (0, 4, 7, 11)}


def parse_chord(spec):
    """'g2:maj' -> (root_midi, (0,4,7))."""
    root, _, q = spec.partition(':')
    return note_to_midi(root), QUAL[q or 'maj']


def bass_bar(root_midi, fifth_midi, oct_midi=None, pattern='A'):
    """Бас-такт: 'A' - восьмые с пятой ступенью, 'B' - плотные восьмые, 'C' - с октавой."""
    if pattern == 'A':
        steps = [(root_midi, 4), (fifth_midi, 2), (root_midi, 2),
                 (root_midi, 4), (fifth_midi, 2), (root_midi, 2)]
    elif pattern == 'B':
        steps = [(root_midi, 2), (fifth_midi, 2)] * 4
    elif pattern == 'C':
        o = oct_midi if oct_midi is not None else root_midi + 12
        steps = [(root_midi, 2), (root_midi, 2), (fifth_midi, 2), (root_midi, 2),
                 (o, 2), (fifth_midi, 2), (root_midi, 2), (root_midi, 2)]
    else:
        raise ValueError(pattern)
    return ' '.join('%s:%d' % (midi_to_name(m), r) for m, r in steps)


# ---------------------------------------------------------------------------
# рендер волн
# ---------------------------------------------------------------------------
def make_env(n, attack=0.004, release=0.008, decay_s=None, sustain=0.55, power=2.5):
    """Атака, затухание до sustain, релиз. Веса на границах -> 0 (нет кликов)."""
    env = [1.0] * n
    a = max(1, min(n // 2, int(attack * SR)))
    for i in range(a):
        env[i] = (i / a) ** 0.7
    if decay_s:
        dn = max(1.0, decay_s * SR)
        for i in range(a, n):
            t = min(1.0, (i - a) / dn)
            env[i] = 1.0 + (sustain - 1.0) * (t ** power)
    else:
        for i in range(a, n):
            env[i] = sustain
    r = max(1, min(n - 1, int(release * SR)))
    for i in range(n - r, n):
        env[i] *= ((n - i) / r) ** 1.5
    return env


def render_pulse(buf, start, n, freq, duty=0.5, vol=1.0, env=None,
                 vib_depth=0.0, vib_rate=5.8):
    end = min(start + n, len(buf))
    if end <= start:
        return
    ph = 0.0
    inc = freq / SR
    vib = vib_depth * vib_rate * 2.0 * math.pi
    if env is None:
        env = [1.0] * n
    for i in range(end - start):
        if vib_depth:
            step = inc * (1.0 + vib_depth * math.sin(vib * i / SR))
        else:
            step = inc
        v = vol if ph < duty else -vol
        buf[start + i] += v * env[i]
        ph += step
        if ph >= 1.0:
            ph -= int(ph)


def render_pulse_sweep(buf, start, n, f0, f1, duty=0.5, vol=1.0, env=None,
                       mode='exp'):
    end = min(start + n, len(buf))
    if end <= start:
        return
    total = float(end - start)
    if env is None:
        env = [1.0] * n
    ph = 0.0
    for i in range(end - start):
        t = i / total
        if mode == 'exp':
            # плавный (логарифмический) спуск/подъём по высоте
            f = f0 * ((f1 / f0) ** t)
        else:
            f = f0 + (f1 - f0) * t
        v = vol if ph < duty else -vol
        buf[start + i] += v * env[i]
        ph += f / SR
        if ph >= 1.0:
            ph -= int(ph)


def render_tri(buf, start, n, freq, vol=1.0, env=None, quant=16, vib_depth=0.0):
    end = min(start + n, len(buf))
    if end <= start:
        return
    if env is None:
        env = [1.0] * n
    ph = 0.0
    inc = freq / SR
    k = quant / 2.0
    for i in range(end - start):
        if vib_depth:
            step = inc * (1.0 + vib_depth * math.sin(2 * math.pi * 5.0 * i / SR))
        else:
            step = inc
        p = ph
        if p < 0.5:
            v = 4.0 * p - 1.0
        else:
            v = 3.0 - 4.0 * p
        if quant:
            v = round(v * k) / k   # 16 уровней, как triangle на NES
        buf[start + i] += v * vol * env[i]
        ph += step
        if ph >= 1.0:
            ph -= int(ph)


def render_tri_sweep(buf, start, n, f0, f1, pitch_tau, vol=1.0, tau=0.06):
    """Кик/том: triangle с быстрым падением высоты и экспоненциальным затуханием."""
    end = min(start + n, len(buf))
    if end <= start:
        return
    ph = 0.0
    f = f0
    fmul = math.exp(-1.0 / (pitch_tau * SR))
    amul = math.exp(-1.0 / (tau * SR))
    amp = 1.0
    a = max(1, int(0.0008 * SR))
    k = 8.0
    for i in range(end - start):
        p = ph
        if p < 0.5:
            v = 4.0 * p - 1.0
        else:
            v = 3.0 - 4.0 * p
        g = amp * (i / a if i < a else 1.0)
        buf[start + i] += round(v * k) / k * vol * g
        ph += f / SR
        if ph >= 1.0:
            ph -= int(ph)
        f = 45.0 + (f - 45.0) * fmul if f > 45.0 else 45.0
        if f0 > f1:
            f = max(f1, f)
        amp *= amul


def render_noise(buf, start, n, rate, vol=1.0, tau=0.05, short=False,
                 rate_end=None, attack=0.0006):
    """LFSR-шум. rate - тактовая частота регистра, Гц."""
    end = min(start + n, len(buf))
    if end <= start:
        return
    reg = 0x7FFF
    acc = 0.0
    amp = 1.0
    amul = math.exp(-1.0 / (tau * SR)) if tau else 1.0
    a = max(1, int(attack * SR))
    total = float(end - start)
    r0 = float(rate)
    r1 = float(rate_end if rate_end is not None else rate)
    cur = r0
    for i in range(end - start):
        acc += cur
        while acc >= SR:
            acc -= SR
            r = reg
            if short:
                bit = ((r >> 6) ^ r) & 1
            else:
                bit = ((r >> 1) ^ r) & 1
            reg = (r >> 1) | (bit << 14)
        v = 1.0 if (reg & 1) == 0 else -1.0
        g = amp * (i / a if i < a else 1.0)
        buf[start + i] += v * vol * g
        amp *= amul
        if rate_end is not None:
            cur = r0 + (r1 - r0) * (i / total)


# ---------------------------------------------------------------------------
# ударные
# ---------------------------------------------------------------------------
DRUMS = {
    'K': ('kick', 0.42),
    'S': ('snare', 0.30),
    'T': ('tom', 0.26),
    'C': ('crash', 0.24),
    'H': ('hat', 0.15),
    'h': ('hat', 0.095),
    'O': ('ohat', 0.14),
}


def drum(buf, start, kind, vol):
    if start >= len(buf):
        return
    if kind == 'kick':
        render_tri_sweep(buf, start, int(0.16 * SR), 175.0, 45.0, 0.022, vol, tau=0.060)
    elif kind == 'snare':
        render_noise(buf, start, int(0.17 * SR), 4200, vol * 0.85, tau=0.052)
        render_tri_sweep(buf, start, int(0.06 * SR), 215.0, 165.0, 0.045, vol * 0.45, tau=0.022)
    elif kind == 'tom':
        render_tri_sweep(buf, start, int(0.17 * SR), 255.0, 120.0, 0.070, vol, tau=0.070)
    elif kind == 'hat':
        render_noise(buf, start, int(0.048 * SR), 15500, vol, tau=0.0125, short=True)
    elif kind == 'ohat':
        render_noise(buf, start, int(0.16 * SR), 13000, vol, tau=0.055, short=True)
    elif kind == 'crash':
        render_noise(buf, start, int(0.60 * SR), 14000, vol, tau=0.150, short=False)
        render_noise(buf, start, int(0.30 * SR), 7000, vol * 0.5, tau=0.090, short=True)
    else:
        raise ValueError(kind)


# ---------------------------------------------------------------------------
# трек
# ---------------------------------------------------------------------------
class Track(object):
    def __init__(self, name, bpm, bars=None, duration_s=None, tail_s=0.0):
        self.name = name
        self.bpm = bpm
        self.row_s = 60.0 / bpm / 4.0          # 1 строка = 1/16
        if bars is not None:
            self.bars = bars
            self.total_rows = bars * 16
            self.dur = self.total_rows * self.row_s + tail_s
        else:
            self.bars = None
            self.total_rows = None
            self.dur = duration_s
        self.tail_s = tail_s
        self.n = int(round(self.dur * SR))
        self.buf = array.array('f', bytes(4 * self.n))

    def sample(self, row):
        return int(row * self.row_s * SR)

    def rows_n(self, rows):
        return int(rows * self.row_s * SR)

    def add_lead(self, ev, duty=0.5, vol=0.45, decay_long=0.42, decay_short=0.20,
                 sustain=0.50, attack=0.004, release=0.010, vib=True):
        row = 0
        for midi, rows in ev:
            n = self.rows_n(rows)
            if midi is not None and n > 8:
                start = self.sample(row)
                dur_s = rows * self.row_s
                dec = decay_long if rows >= 4 else decay_short
                sus = sustain if rows >= 4 else max(0.30, sustain - 0.15)
                env = make_env(n, attack=attack, release=release,
                               decay_s=dec, sustain=sus)
                vibd = 0.0035 if (vib and dur_s >= 0.45) else 0.0
                render_pulse(self.buf, start, n, midi_to_freq(midi), duty,
                             vol, env, vib_depth=vibd)
            row += rows
        self.lead_ev = ev
        return row

    def add_bass(self, text, vol=0.34, duty_note='triangle'):
        ev = parse_seq(text)
        row = 0
        for midi, rows in ev:
            n = self.rows_n(rows)
            if midi is not None and n > 8:
                env = make_env(n, attack=0.0025, release=0.007, decay_s=None, sustain=1.0)
                render_tri(self.buf, self.sample(row), n, midi_to_freq(midi), vol, env)
            row += rows
        return row

    def add_arp(self, chords, step_div=6.0, duty=0.125, vol=0.135, octave=12):
        """chords: список (spec|None) на каждый такт. Быстрый arpeggio аккорда."""
        step_n = max(4, int(self.row_s * SR / step_div))
        step_s = step_n / float(SR)
        for bi, spec in enumerate(chords):
            if spec is None:
                continue
            root, qual = parse_chord(spec)
            notes = [root + octave + q for q in qual]
            base = self.sample(bi * 16)
            span = self.rows_n(16)
            t = 0
            k = 0
            env = make_env(step_n, attack=0.0004, release=0.0004, decay_s=None, sustain=1.0)
            self.chords = chords
            while t < span:
                m = notes[k % len(notes)]
                render_pulse(self.buf, base + t, step_n, midi_to_freq(m),
                             duty, vol, env)
                k += 1
                t += step_n

    def add_drums(self, patterns, start_bar=0):
        """patterns: список строк по 16 символов (по такту)."""
        for bi, pat in enumerate(patterns):
            bar = start_bar + bi
            base = self.sample(bar * 16)
            for i, ch in enumerate(pat):
                if ch in '. ':
                    continue
                kind, vol = DRUMS[ch]
                drum(self.buf, base + int(i * self.row_s * SR), kind, vol)

    def add_hit(self, at_s, kind, vol=0.3):
        drum(self.buf, int(at_s * SR), kind, vol)

    # ------------------------------------------------------------------
    def finalize(self, peak_target=PEAK_TARGET, fade_in=0.002, fade_out=0.003):
        """Нормализация пика + микро-fade на границах (без кликов)."""
        buf = self.buf
        n = len(buf)
        pk = 0.0
        for v in buf:
            a = v if v >= 0 else -v
            if a > pk:
                pk = a
        if pk <= 0.0:
            raise SystemExit('[%s] пустой буфер' % self.name)
        g = peak_target / pk
        for i in range(n):
            buf[i] *= g
        a = max(1, int(fade_in * SR))
        for i in range(a):
            buf[i] *= (i / a) ** 1.5
        r = max(1, int(fade_out * SR))
        for i in range(n - r, n):
            buf[i] *= ((n - i) / r) ** 1.5
        return pk

    def write_wav(self, path):
        data = array.array('h', bytes(2 * self.n))
        for i, v in enumerate(self.buf):
            s = int(round(v * 32767.0))
            if s > 32767:
                s = 32767
            elif s < -32768:
                s = -32768
            data[i] = s
        with wave.open(path, 'wb') as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes(data.tobytes())
        return self.n / float(SR)


# ---------------------------------------------------------------------------
# =============================  МУЗЫКА  ====================================
# ---------------------------------------------------------------------------

def build_title():
    """Заглавная тема: C-dur, 140 BPM, 16 тактов (~27.4 с). Яркая, с характером."""
    t = Track('title', 140, bars=16)
    chords = ['c2:maj', 'f2:maj', 'g2:maj', 'c2:maj',
              'a2:min', 'f2:maj', 'g2:maj', 'c2:maj',
              'f2:maj', 'g2:maj', 'a2:min', 'g2:maj',
              'c2:maj', 'f2:maj', 'g2:maj', 'c2:maj']
    lead = seq(
        # A - «шагающая» тема
        'g4:2 a4:2 b4:2 c5:2 b4:2 a4:2 g4:4',
        'e5:4 d5:2 c5:2 d5:4 e5:4',
        'g4:2 a4:2 b4:2 c5:2 d5:2 e5:2 d5:4',
        'c5:4 b4:2 a4:2 g4:8',
        # A2 - развитие
        'c5:2 d5:2 e5:2 f5:2 e5:2 d5:2 c5:4',
        'a4:4 b4:2 c5:2 d5:4 e5:4',
        'f5:2 e5:2 d5:2 c5:2 b4:2 a4:2 b4:4',
        'c5:8 g4:8',
        # B - взлёт
        'e5:2 f5:2 g5:4 f5:2 e5:2 d5:4',
        'c5:2 d5:2 e5:2 f5:2 g5:4 e5:4',
        'a5:4 g5:2 f5:2 e5:4 d5:4',
        'e5:2 d5:2 c5:2 b4:2 c5:8',
        # A' - реприза с кодой
        'g4:2 a4:2 b4:2 c5:2 b4:2 a4:2 g4:4',
        'e5:4 d5:2 c5:2 d5:4 e5:4',
        'g4:2 a4:2 b4:2 c5:2 d5:2 e5:2 d5:4',
        'c5:4 e5:4 g5:8')
    ev = parse_seq(lead)
    check_rows('title.lead', ev, 16)
    t.add_lead(ev, duty=0.5, vol=0.46)

    bass = seq(*[bass_bar(parse_chord(c)[0], parse_chord(c)[0] + 7, pattern='A')
                 for c in chords])
    be = parse_seq(bass)
    check_rows('title.bass', be, 16)
    t.add_bass(bass)

    t.add_arp(chords, duty=0.125, vol=0.13)

    groove = 'K.h.S.hhK.h.S.hh'
    groove2 = 'K.h.S.hhK.hKS.hh'
    fill = 'K.h.S.hhK.SSTT..'
    dr = [groove, groove, groove, groove2,
          groove, groove, groove2, fill,
          groove, groove, groove2, groove,
          groove2, groove, groove2, fill]
    t.add_drums(dr)
    return t


def build_level():
    """Основной уровень: G-dur, 138 BPM, 32 такта = 55.65 с, бесшовный луп."""
    t = Track('level', 138, bars=32)
    chords = ['g2:maj', 'c2:maj', 'd2:maj', 'g2:maj',
              'e2:min', 'c2:maj', 'd2:maj', 'g2:maj',
              'c2:maj', 'd2:maj', 'e2:min', 'c2:maj',
              'd2:maj', 'g2:maj', 'c2:maj', 'd2:maj',
              'g2:maj', 'c2:maj', 'd2:maj', 'g2:maj',
              'e2:min', 'c2:maj', 'a2:min', 'd2:maj',
              'c2:maj', 'd2:maj', 'g2:maj', 'e2:min',
              'c2:maj', 'd2:maj', 'd2:maj', 'g2:maj']
    lead = seq(
        # A (1-8)
        'd5:2 e5:2 f#5:2 g5:2 a5:2 g5:2 f#5:4',
        'e5:4 d5:2 c5:2 d5:2 e5:2 f#5:4',
        'd5:2 e5:2 f#5:2 a5:2 g5:2 f#5:2 e5:4',
        'd5:8 b4:8',
        'e5:2 g5:2 b5:2 a5:2 g5:2 e5:2 d5:4',
        'c5:4 e5:4 g5:8',
        'f#5:2 a5:2 d6:2 a5:2 f#5:2 d5:2 a4:4',
        'b5:4 a5:4 g5:8',
        # B (9-16)
        'e5:2 f#5:2 g5:2 a5:2 g5:4 e5:4',
        'f#5:2 g5:2 a5:2 b5:2 a5:4 f#5:4',
        'g5:2 a5:2 b5:2 c6:2 b5:4 g5:4',
        'e5:2 g5:2 a5:2 g5:2 e5:4 c5:4',
        'd5:4 f#5:4 a5:4 f#5:4',
        'g5:4 b5:4 d6:8',
        'c6:2 b5:2 a5:2 g5:2 e5:4 c5:4',
        'd5:2 e5:2 f#5:2 a5:2 d6:4 a5:4',
        # A' (17-24)
        'd5:2 e5:2 f#5:2 g5:2 a5:2 g5:2 f#5:4',
        'e5:4 d5:2 c5:2 d5:2 e5:2 f#5:4',
        'd5:2 e5:2 f#5:2 a5:2 g5:2 f#5:2 e5:4',
        'd5:8 b4:8',
        'e5:2 g5:2 b5:4 a5:2 g5:2 f#5:4',
        'e5:2 f#5:2 g5:4 a5:2 g5:2 e5:4',
        'c5:4 e5:4 a4:8',
        'd5:4 f#5:4 a5:8',
        # C (25-32)
        'c6:4 b5:2 a5:2 g5:4 e5:4',
        'f#5:4 a5:4 d6:4 a5:4',
        'g5:2 b5:2 d6:2 b5:2 g5:4 b4:4',
        'e5:2 g5:2 b5:2 e6:2 b5:4 g5:4',
        'a5:4 g5:4 e5:8',
        'f#5:4 e5:4 d5:8',
        'd5:2 e5:2 f#5:2 g5:2 a5:4 b5:4',
        'g5:4 f#5:2 e5:2 d5:8')
    ev = parse_seq(lead)
    check_rows('level.lead', ev, 32)
    t.add_lead(ev, duty=0.5, vol=0.46)

    bass_a = [bass_bar(parse_chord(c)[0], parse_chord(c)[0] + 7, pattern='A')
              for c in chords[:16]]
    bass_b = [bass_bar(parse_chord(c)[0], parse_chord(c)[0] + 7, pattern='B')
              for c in chords[16:]]
    bass = seq(*(bass_a + bass_b))
    be = parse_seq(bass)
    check_rows('level.bass', be, 32)
    t.add_bass(bass)

    t.add_arp(chords, duty=0.125, vol=0.13)

    groove = 'K.h.S.hhK.h.S.hh'
    groove2 = 'K.h.S.hhK.hKS.hh'
    fill = 'K.h.S.hhK.SSTT..'
    dr = [groove, groove, groove2, groove,
          groove, groove2, groove, fill,
          groove, groove, groove2, groove,
          groove2, groove, groove, fill,
          groove, groove2, groove, groove,
          groove, groove2, groove, fill,
          groove, groove, groove2, groove,
          groove2, groove2, groove, fill]
    t.add_drums(dr)
    return t


def build_victory():
    """Победный джингл: C-dur, 150 BPM, 4 такта = 6.4 с."""
    t = Track('victory', 150, bars=4)
    chords = ['c2:maj', 'g2:maj', 'a2:min', 'c2:maj']
    lead = seq(
        'c5:2 e5:2 g5:2 c6:4 b5:2 a5:2 g5:2',
        'g5:2 a5:2 b5:2 c6:4 e6:4 d6:2',
        'e6:4 d6:2 c6:2 b5:2 a5:2 g5:4',
        'c6:4 g5:4 c5:8')
    ev = parse_seq(lead)
    check_rows('victory.lead', ev, 4)
    t.add_lead(ev, duty=0.5, vol=0.48)

    bass = seq(*[bass_bar(parse_chord(c)[0], parse_chord(c)[0] + 7, pattern='C')
                 for c in chords])
    be = parse_seq(bass)
    check_rows('victory.bass', be, 4)
    t.add_bass(bass, vol=0.32)

    t.add_arp(chords, duty=0.25, vol=0.15)

    groove = 'K.h.S.hhK.h.S.hh'
    t.add_drums([groove, 'K.h.S.hhK.hSSTh', groove, 'K.......C...T...'])
    t.add_hit(0.0, 'crash', 0.30)
    return t


def build_gameover():
    """Мрачный джингл: a-moll, 100 BPM, 2 такта + хвост = ~5.5 с."""
    t = Track('gameover', 100, bars=2, tail_s=0.75)
    chords = ['a2:min', 'e2:maj']
    lead = seq(
        'e5:4 c5:4 a4:6 b4:2',
        'b4:4 g#4:4 a4:4 e4:4')
    ev = parse_seq(lead)
    check_rows('gameover.lead', ev, 2)
    t.add_lead(ev, duty=0.25, vol=0.44, decay_long=0.55, sustain=0.42)

    bass = seq(bass_bar(parse_chord('a2:min')[0], parse_chord('a2:min')[0] + 7, pattern='A'),
               bass_bar(parse_chord('e2:maj')[0], parse_chord('e2:maj')[0] + 7, pattern='A'))
    be = parse_seq(bass)
    check_rows('gameover.bass', be, 2)
    t.add_bass(bass, vol=0.36)

    t.add_arp(chords, step_div=4.0, duty=0.25, vol=0.12)

    # хвост: долгий мрачный аккорд a-moll, угасающий
    tail_start = t.sample(32)
    tail_n = t.n - tail_start
    env = make_env(tail_n, attack=0.01, release=0.25, decay_s=0.5, sustain=0.30)
    render_tri(t.buf, tail_start, tail_n, midi_to_freq(note_to_midi('a2')), 0.30, env)
    for k, nm in enumerate(['a3', 'c4', 'e4', 'a4']):
        st = tail_start + int(k * 0.10 * SR)
        m = note_to_midi(nm)
        e = make_env(int(0.9 * SR), attack=0.004, release=0.030, decay_s=0.45, sustain=0.25)
        render_pulse(t.buf, st, int(0.9 * SR), midi_to_freq(m), 0.25, 0.15, e)

    t.add_drums(['K.......S.......', 'K.......S...TTTT'])
    t.add_hit(0.0, 'tom', 0.20)
    return t


# ---------------------------------------------------------------------------
# =============================  ЭФФЕКТЫ  ===================================
# ---------------------------------------------------------------------------

def build_jump():
    n = int(0.20 * SR)
    t = Track('sfx_jump', 120, duration_s=0.20)
    env = make_env(n, attack=0.002, release=0.035, decay_s=0.13, sustain=0.30)
    render_pulse_sweep(t.buf, 0, n, 300.0, 1050.0, duty=0.125, vol=0.55, env=env)
    env2 = make_env(n, attack=0.002, release=0.030, decay_s=0.10, sustain=0.20)
    render_pulse_sweep(t.buf, 0, n, 600.0, 1500.0, duty=0.25, vol=0.22, env=env2)
    return t


def build_throw():
    n = int(0.28 * SR)
    t = Track('sfx_throw', 120, duration_s=0.28)
    # «свист»: шум, у которого растёт тактовая частота
    env = make_env(n, attack=0.004, release=0.03, decay_s=0.22, sustain=0.12)
    render_noise(t.buf, 0, n, 2200, 0.34, tau=0.09, short=False,
                 rate_end=9500, attack=0.002)
    render_pulse_sweep(t.buf, 0, n, 900.0, 260.0, duty=0.25, vol=0.34, env=env)
    return t


def build_crate():
    n = int(0.35 * SR)
    t = Track('sfx_crate_break', 120, duration_s=0.35)
    # треск (яркий короткий шум) + низкий грохот + короткий «деревянный» тон
    render_noise(t.buf, 0, int(0.10 * SR), 16000, 0.42, tau=0.022, short=True)
    render_noise(t.buf, int(0.045 * SR), int(0.12 * SR), 11000, 0.30, tau=0.028, short=True)
    e = make_env(int(0.35 * SR), attack=0.001, release=0.05, decay_s=0.16, sustain=0.18)
    render_noise(t.buf, 0, n, 3000, 0.30, tau=0.10, short=False)
    render_pulse_sweep(t.buf, 0, n, 320.0, 90.0, duty=0.5, vol=0.30, env=e)
    render_tri_sweep(t.buf, 0, n, 150.0, 60.0, 0.05, 0.30, tau=0.12)
    return t


def build_item():
    n = int(0.60 * SR)
    t = Track('item', 140, duration_s=0.60)
    step = int(0.062 * SR)
    for k, nm in enumerate(['c5', 'e5', 'g5', 'c6']):
        st = k * step
        e = make_env(step, attack=0.001, release=0.004, decay_s=None, sustain=1.0)
        render_pulse(t.buf, st, step, midi_to_freq(note_to_midi(nm)), 0.25, 0.42, e)
    # «блеск» сверху + короткий высокий второй голос
    e2 = make_env(int(0.45 * SR), attack=0.001, release=0.10, decay_s=0.35, sustain=0.10)
    render_pulse(t.buf, int(0.24 * SR), int(0.45 * SR),
                 midi_to_freq(note_to_midi('g6')), 0.125, 0.22, e2)
    e3 = make_env(int(0.3 * SR), attack=0.001, release=0.10, decay_s=0.24, sustain=0.06)
    render_pulse(t.buf, int(0.24 * SR), int(0.3 * SR),
                 midi_to_freq(note_to_midi('e6')), 0.25, 0.18, e3)
    render_noise(t.buf, int(0.22 * SR), int(0.30 * SR), 14000, 0.10, tau=0.06, short=True)
    return t


def build_damage():
    n = int(1.20 * SR)
    t = Track('damage', 120, duration_s=1.20)
    # резкий удар шумом
    render_noise(t.buf, 0, int(0.18 * SR), 6500, 0.35, tau=0.045, short=False)
    e = make_env(n, attack=0.002, release=0.06, decay_s=0.55, sustain=0.22)
    render_pulse_sweep(t.buf, 0, n, 880.0, 170.0, duty=0.5, vol=0.42, env=e)
    e2 = make_env(n, attack=0.002, release=0.05, decay_s=0.45, sustain=0.15)
    # «расстроенный» второй голос -> диссонанс
    render_pulse_sweep(t.buf, 0, n, 1320.0, 300.0, duty=0.5, vol=0.22, env=e2)
    e3 = make_env(int(0.9 * SR), attack=0.006, release=0.10, decay_s=0.6, sustain=0.12)
    render_tri(t.buf, 0, int(0.9 * SR), 140.0, 0.26, e3, quant=16)
    return t


# ---------------------------------------------------------------------------
# запись + конвертация
# ---------------------------------------------------------------------------
def find_ffmpeg():
    for p in (os.environ.get('FFMPEG'), '/home/orangepi/bin/ffmpeg',
              '/usr/bin/ffmpeg', '/usr/local/bin/ffmpeg'):
        if p and os.path.exists(p) and os.access(p, os.X_OK):
            return p
    for d in os.environ.get('PATH', '').split(os.pathsep):
        p = os.path.join(d, 'ffmpeg')
        if os.path.exists(p) and os.access(p, os.X_OK):
            return p
    return None


def to_ogg(ffmpeg, wav_path):
    base = wav_path[:-4]
    ogg = base + '.ogg'
    tries = [(['-c:a', 'libvorbis', '-q:a', '3'], 'libvorbis'),
             (['-c:a', 'libopus', '-b:a', '96k'], 'libopus')]
    for args, codec in tries:
        cmd = [ffmpeg, '-y', '-loglevel', 'error', '-i', wav_path] + args + [ogg]
        try:
            r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        except OSError as exc:
            print('  ffmpeg не запустился: %s' % exc)
            return None, None
        if r.returncode == 0 and os.path.exists(ogg) and os.path.getsize(ogg) > 100:
            return ogg, codec
        print('  %s не сработал (%s): %s' % (codec, r.returncode,
                                             r.stdout.decode('utf-8', 'replace').strip()[:160]))
    return None, None


def generate():
    if not os.path.isdir(OUT_DIR):
        os.makedirs(OUT_DIR)
    builders = [build_title, build_level, build_victory, build_gameover,
                build_jump, build_throw, build_crate, build_item, build_damage]
    made = []
    for b in builders:
        t = b()
        pk = t.finalize()
        wav = os.path.join(OUT_DIR, t.name + '.wav')
        dur = t.write_wav(wav)
        bars = '' if t.bars is None else ' (%d такт.)' % t.bars
        print('%-16s %7.3f с%s  пик до норм. %.3f  -> %s'
              % (t.name + '.wav', dur, bars, pk, os.path.basename(wav)))
        made.append((t.name, wav, dur))

    ffmpeg = find_ffmpeg()
    print('\nffmpeg: %s' % (ffmpeg or 'НЕ НАЙДЕН'))
    for name, wav, _ in made:
        if not ffmpeg:
            print('%-16s ogg пропущен (нет ffmpeg)' % name)
            continue
        ogg, codec = to_ogg(ffmpeg, wav)
        if ogg:
            print('%-16s -> %s (%s, %.1f КБ)'
                  % (name, os.path.basename(ogg), codec, os.path.getsize(ogg) / 1024.0))
        else:
            print('%-16s -> ogg НЕ получился, оставляю WAV' % name)
    print('\nГотово: %s' % OUT_DIR)


# ---------------------------------------------------------------------------
# проверка
# ---------------------------------------------------------------------------
BANDS = {
    'бас<155': (55.0, 155.0, 10),
    'мид 200-430': (200.0, 430.0, 10),
    'мелодия 500-2400': (500.0, 2400.0, 12),
}


def _goertzel_pow(samples, start, n, freq):
    w = 2.0 * math.pi * freq / SR
    c = 2.0 * math.cos(w)
    s1 = 0.0
    s2 = 0.0
    for i in range(n):
        s0 = samples[start + i] + c * s1 - s2
        s2 = s1
        s1 = s0
    return s1 * s1 + s2 * s2 - c * s1 * s2


def band_energies(samples, win=4096, windows=8):
    n = len(samples)
    if n < win * 2:
        return None
    step = max(1, (n - win) // max(1, windows - 1))
    out = {}
    for band, (f0, f1, nb) in BANDS.items():
        freqs = [f0 * ((f1 / f0) ** (i / (nb - 1.0))) for i in range(nb)]
        tot = 0.0
        for w in range(windows):
            st = min(max(0, w * step), n - win)
            for f in freqs:
                tot += _goertzel_pow(samples, st, win, f)
        out[band] = tot / (windows * nb)
    return out


BUILDERS = {'title': build_title, 'level': build_level, 'victory': build_victory,
            'gameover': build_gameover}


def melody_over_bass(t, d, off_s=0.02, win_s=0.09):
    """Медианная разница (дБ) между основным тоном мелодии и основным тоном баса
    на тех же моментах времени. > 0 значит мелодия громче баса в своём диапазоне."""
    if not getattr(t, 'lead_ev', None) or not getattr(t, 'chords', None):
        return None, 0
    row = 0
    ratios = []
    for midi, rows in t.lead_ev:
        dur = rows * t.row_s
        if midi is not None and dur >= 0.20:
            st = t.sample(row) + int(off_s * SR)
            n = int(min(win_s, dur - off_s) * SR)
            if st + n < len(d):
                bar = row // 16
                spec = t.chords[bar] if bar < len(t.chords) else None
                bass = 0.0
                if spec:
                    r = parse_chord(spec)[0]
                    for m in (r, r + 7):
                        pw = _goertzel_pow(d, st, n, midi_to_freq(m))
                        if pw > bass:
                            bass = pw
                mel = _goertzel_pow(d, st, n, midi_to_freq(midi))
                ratios.append(_db(mel) - _db(bass))
        row += rows
    if not ratios:
        return None, 0
    ratios.sort()
    return ratios[len(ratios) // 2], len(ratios)


def _db(x):
    return 10.0 * math.log10(x if x > 1e-12 else 1e-12)


def read_wav_mono16(path):
    with wave.open(path, 'rb') as w:
        ch, sw, fr, nf = (w.getnchannels(), w.getsampwidth(),
                          w.getframerate(), w.getnframes())
        raw = w.readframes(nf)
    d = array.array('h')
    d.frombytes(raw[:len(raw) // 2 * 2])
    return d, ch, sw, fr


def _png_gray(path, w, h, pix):
    """Минимальный PNG (8-bit grayscale) на стандартной библиотеке."""
    import zlib
    raw = bytearray()
    for y in range(h):
        raw.append(0)
        raw += bytes(pix[y * w:(y + 1) * w])

    def chunk(tag, data):
        return (struct.pack('>I', len(data)) + tag + data +
                struct.pack('>I', zlib.crc32(tag + data) & 0xFFFFFFFF))

    png = b'\x89PNG\r\n\x1a\n'
    png += chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 0, 0, 0, 0))
    png += chunk(b'IDAT', zlib.compress(bytes(raw), 6))
    png += chunk(b'IEND', b'')
    with open(path, 'wb') as f:
        f.write(png)
    return path


def spectrogram(name, out_png, seconds=12.0, win=1024, fmin=55.0, fmax=6000.0, nbin=56):
    """Спектрограмма через Goertzel (без numpy) - для визуальной проверки."""
    wav = os.path.join(OUT_DIR, name + '.wav')
    d, ch, sw, fr = read_wav_mono16(wav)
    n = min(len(d), int(seconds * fr))
    hop = win
    frames = max(1, (n - win) // hop + 1)
    freqs = [fmin * ((fmax / fmin) ** (i / (nbin - 1.0))) for i in range(nbin)]
    spec = []
    for fi in range(frames):
        st = fi * hop
        col = [_goertzel_pow(d, st, win, f) for f in freqs]
        spec.append(col)
    mx = 0.0
    for col in spec:
        for v in col:
            if v > mx:
                mx = v
    pix = bytearray(frames * 2 * nbin * 2)
    W = frames * 2
    H = nbin * 2
    for fi, col in enumerate(spec):
        for bi, v in enumerate(col):
            db = _db(v) - _db(mx)
            g = int(max(0.0, min(1.0, (db + 60.0) / 60.0)) * 255)
            y0 = (nbin - 1 - bi) * 2
            for dy in (0, 1):
                y = y0 + dy
                row = y * W
                pix[row + fi * 2] = g
                pix[row + fi * 2 + 1] = g
    _png_gray(out_png, W, H, pix)
    return out_png, W, H


def ffprobe_dur(path):
    for p in ('/home/orangepi/bin/ffprobe', 'ffprobe'):
        try:
            r = subprocess.run([p, '-v', 'error', '-show_entries', 'format=duration',
                                '-of', 'default=nw=1:nk=1', path],
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            if r.returncode == 0:
                return float(r.stdout.decode().strip())
        except (OSError, ValueError):
            continue
    return None


def verify(plot=False):
    names = ['title', 'level', 'victory', 'damage', 'item', 'gameover',
             'sfx_jump', 'sfx_throw', 'sfx_crate_break']
    ok = True
    print('%-20s %9s %9s %6s %7s %7s %8s  %s'
          % ('файл', 'длит.,с', 'КБ', 'пик', 'RMS', 'нонулей', 'мел/бас', 'проверки'))
    print('-' * 118)
    for nm in names:
        for ext in ('.wav', '.ogg'):
            p = os.path.join(OUT_DIR, nm + ext)
            if not os.path.exists(p):
                if ext == '.wav':
                    print('%-20s ОТСУТСТВУЕТ' % (nm + ext))
                    ok = False
                continue
            sz = os.path.getsize(p) / 1024.0
            note = []
            if ext == '.ogg':
                od = ffprobe_dur(p)
                print('%-20s %9.3f %9.1f %6s %7s %7s %8s  %s'
                      % (nm + ext, od if od else float('nan'), sz, '-', '-', '-', '-',
                         'Vorbis (браузерный формат)'))
                continue
            d, ch, sw, fr = read_wav_mono16(p)
            if ch != 1 or sw != 2:
                note.append('ОШИБКА: не моно/16бит')
                ok = False
            if fr != SR:
                note.append('ОШИБКА: частота %d' % fr)
                ok = False
            n = len(d)
            dur = n / float(fr)
            pk = 0
            nz = 0
            ss = 0.0
            zc = 0
            prev = 0
            for v in d:
                a = v if v >= 0 else -v
                if a > pk:
                    pk = a
                if v:
                    nz += 1
                ss += float(v) * v
                if (v >= 0) != (prev >= 0):
                    zc += 1
                prev = v
            rms = math.sqrt(ss / n) if n else 0.0
            nz_pct = 100.0 * nz / n if n else 0.0
            if n == 0 or pk == 0:
                note.append('ОШИБКА: пусто/тишина')
                ok = False
            if nz_pct < 20.0:
                note.append('ОШИБКА: почти тишина')
                ok = False
            if zc < 50:
                note.append('ОШИБКА: однотонный сигнал')
                ok = False
            if abs(pk / 32767.0 - PEAK_TARGET) > 0.005:
                note.append('ОШИБКА: пик %.3f != %.2f' % (pk / 32767.0, PEAK_TARGET))
                ok = False
            if pk < 32000 and pk > 32767:
                note.append('ОШИБКА: клиппинг')
                ok = False
            # границы: нет щелчка / разрыва
            edge = max(abs(d[0]), abs(d[-1]))
            if edge > 0.01 * pk:
                note.append('ОШИБКА: ненулевая граница (щелчок)')
                ok = False
            else:
                note.append('границы 0 (без щелчка)')

            be = band_energies(d)
            ratio = float('nan')
            if be:
                ratio = _db(be['мелодия 500-2400']) - _db(be['бас<155'])
                note.append('[справка] ср.энергия по полосам: <155Гц %.0f / 200-430Гц %.0f / 500-2400Гц %.0f дБ'
                            % (_db(be['бас<155']), _db(be['мид 200-430']),
                               _db(be['мелодия 500-2400'])))
                if nm in BUILDERS:
                    mb, cnt = melody_over_bass(BUILDERS[nm](), d)
                    if mb is None:
                        note.append('не удалось измерить мелодию')
                    else:
                        ratio = mb
                        note.append('мелодия/бас (осн. тоны, n=%d): %+.1f дБ' % (cnt, mb))
                        if mb < 0.0:
                            note.append('ОШИБКА: бас громче мелодии')
                            ok = False
            if nm == 'level':
                row_s = 60.0 / 138 / 4
                bars = dur / row_s / 16.0
                tol = 1.5 / (SR * row_s * 16.0)   # допуск округления до сэмпла
                isint = abs(bars - round(bars)) <= tol
                note.append('тактов %.5f (целое: %s -> %d такт., отклонение %.3f мс)'
                            % (bars, isint, round(bars),
                               1000.0 * (bars - round(bars)) * row_s * 16))
                if not isint:
                    ok = False
                note.append('луп: 1-й сэмпл %d, последний %d (шов %.2f%% пика)'
                            % (d[0], d[-1], 100.0 * abs(d[0] - d[-1]) / pk))
            if nm in ('title', 'level', 'victory', 'gameover'):
                bpm = {'title': 140, 'level': 138, 'victory': 150, 'gameover': 100}[nm]
                note.append('BPM %d, строка %.4f с' % (bpm, 60.0 / bpm / 4))
            print('%-20s %9.3f %9.1f %6.2f %7.0f %6.1f%% %8.1f  %s'
                  % (nm + ext, dur, sz, pk / 32767.0, rms, nz_pct, ratio,
                     '; '.join(note)))
    print('-' * 118)
    print('Пик: нормализован до %.2f (%.0f/32767), клиппинга нет.' % (PEAK_TARGET, PEAK_TARGET * 32767))
    if plot:
        for nm, sec in (('level', 12.0), ('title', 10.0)):
            out = '/tmp/%s_spec.png' % nm
            sp, W, H = spectrogram(nm, out, seconds=sec)
            print('спектрограмма %s: %s (%dx%d)' % (nm, sp, W, H))
    print('ИТОГ: %s' % ('ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ' if ok else 'ЕСТЬ ПРОБЛЕМЫ'))
    return 0 if ok else 1


def main():
    if '--verify' in sys.argv:
        return verify(plot='--plot' in sys.argv)
    generate()
    print()
    return verify(plot='--plot' in sys.argv)


if __name__ == '__main__':
    sys.exit(main())
