#!/usr/bin/env python3
"""Список ассетов игры «Элвин и бурундуки» (NES-платформер).

Каждый ассет: (имя_файла, промпт, aspect_ratio, тип)
тип: 'sprite' (нужен magenta-фон) | 'bg' (фон, без magenta)
"""

SPRITE_TMPL = (
    "pixel art sprite, retro NES 8-bit style, black outlines, flat bright colors, "
    "single cartoon chipmunk character wearing a {color} sweater, {pose}, side view, "
    "centered, plain solid magenta #FF00FF background, no text, no letters, no signature, "
    "no watermark, no logo, no shadow, no ground line"
)

ENEMY_TMPL = (
    "pixel art sprite, retro NES 8-bit style, black outlines, flat bright colors, "
    "single {what}, {pose}, side view, centered, plain solid magenta #FF00FF background, "
    "no text, no letters, no signature, no watermark, no logo, no shadow, no ground line"
)

OBJ_TMPL = (
    "pixel art sprite, retro NES 8-bit style, black outlines, flat bright colors, "
    "single {what}, {pose}, centered, plain solid magenta #FF00FF background, "
    "no text, no letters, no signature, no watermark, no logo, no shadow, no ground line"
)

BG_TMPL = (
    "retro NES 8-bit pixel art background, {what}, black outlines, flat bright colors, "
    "no text, no characters"
)

# ---------------------------------------------------------------- персонажи
CHARS = [
    ("alvin", "red", "standing smiling"),
    ("simon", "blue", "standing smiling, clever smart look"),
    ("theodore", "green", "standing smiling, chubby good-natured look"),
]

CHAR_POSES = [
    ("stand", "standing smiling"),
    ("run1", "running, legs in mid running stride"),
    ("run2", "running, second frame with legs in opposite position"),
    ("jump", "jumping upward with both arms raised"),
    ("throw", "throwing a wooden crate forward with both paws, wooden crate right next to the paws in front"),
]

# ------------------------------------------------------------------- враги
ENEMIES = [
    ("en_bulldog_walk", "mechanical robot bulldog, grey metal body, red glowing eyes, walking", "@1"),
    ("en_bulldog_charge", "mechanical robot bulldog, grey metal body, red glowing eyes, charging forward leaning forward", "@1"),
    ("en_rat_walk", "robotic metal rat with antenna on head, red glowing eyes, walking", "@2"),
    ("en_rat_jump", "robotic metal rat with antenna on head, red glowing eyes, jumping up", "@2"),
    ("en_bee_fly", "robot bee, yellow and black striped metal body, small wings, red glowing eyes, flying", "@3"),
    ("en_bee_dive", "robot bee, yellow and black striped metal body, small wings, red glowing eyes, diving downward", "@3"),
]

# --------------------------------------------------------------- предметы
OBJECTS = [
    ("obj_crate", "wooden crate box, side view, wooden planks, nails", "game item"),
    ("obj_crate_broken", "broken smashed wooden crate, several wooden plank fragments scattered around", "game item"),
    ("obj_star", "shiny yellow five-pointed star bonus", "game item"),
    ("obj_flower", "bright flower with red petals and yellow center", "game item"),
    ("obj_acorn", "acorn with brown cap", "game item"),
    ("obj_heart", "red heart shape", "game item"),
    ("obj_door", "wooden door in a wooden frame with a round handle", "game item"),
]

BACKGROUNDS = [
    ("bg_title", "three cartoon chipmunks standing together on a sunny forest meadow, "
                 "one chipmunk wearing a red sweater, one wearing a blue sweater, one wearing a green sweater, "
                 "sunny day, blue sky, trees around"),
    ("bg_level_far", "distant forest layer, treetops, blue sky, light haze, no characters"),
    ("bg_level_near", "foreground layer, large tree trunks, bushes, grass in the foreground"),
]


def build_list():
    """Возвращает список dict(filename, prompt, ratio, kind)."""
    out = []

    # персонажи
    for name, color, _ in CHARS:
        for pose_key, pose_text in CHAR_POSES:
            prompt = SPRITE_TMPL.format(color=color, pose=pose_text)
            out.append({
                "file": f"chr_{name}_{pose_key}.png",
                "prompt": prompt,
                "ratio": "1:1",
                "kind": "sprite",
            })

    # враги — уточняем «one» через other/different в шаблоне
    for fname, what, _grp in ENEMIES:
        # what = "<объект>, <поза>" -> разделяем по последней запятой с известными позами
        obj, pose = _split_enemy(what)
        prompt = ENEMY_TMPL.format(what=obj, pose=pose)
        out.append({"file": f"{fname}.png", "prompt": prompt, "ratio": "1:1", "kind": "sprite"})

    # предметы
    for fname, what, _ in OBJECTS:
        prompt = OBJ_TMPL.format(what=what, pose="side view")
        out.append({"file": f"{fname}.png", "prompt": prompt, "ratio": "1:1", "kind": "sprite"})

    # фоны
    for fname, what in BACKGROUNDS:
        prompt = BG_TMPL.format(what=what)
        out.append({"file": f"{fname}.png", "prompt": prompt, "ratio": "16:9", "kind": "bg"})

    return out


ENEMY_POSES = {"walking", "charging forward leaning forward", "jumping up", "flying",
               "diving downward"}


def _split_enemy(what: str):
    for p in sorted(ENEMY_POSES, key=len, reverse=True):
        if what.endswith(", " + p):
            return what[: -(len(p) + 2)], p
    return what, "shown in action"


if __name__ == "__main__":
    items = build_list()
    print(f"всего ассетов: {len(items)}")
    for it in items:
        print(f"  {it['file']:28s} {it['ratio']:5s} {it['kind']}")
