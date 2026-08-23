"""静的タロット風テンプレート素材（大アルカナ22枚）を手続き的に生成するスクリプト。

OpenAIの画像生成APIを使わない構成にするため、AIで毎回画像を作る代わりに、
あらかじめこのスクリプトでPillowのみを使い、大アルカナ22枚すべてを
最古のタロットカード風アートとして生成し、assets/templates/ 配下に
静的素材としてコミットしておく。
本番実行時（generator.py）はこの中からランダムに1枚を選ぶだけなので、
画像生成AI・追加コストは一切発生しない。

22枚は「前向き・希望が持てる」(positive/) と「厳しい現実を直視する」
(negative/) の2群に分け、このアプリの「深い悩みのある恋愛」というテーマに
沿って割り当てている(例: 恋人・愛人・悪魔＝執着/不誠実→negative、
恋人たち・太陽・世界＝結びつき/成就→positive)。

再実行すると同じシードから同じ画像が再生成される（既存ファイルは上書き）。

使い方:
    python3 scripts/generate_templates.py
"""

import math
import os
import random

from PIL import Image, ImageDraw, ImageFilter

CANVAS_SIZE = (1024, 1536)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES_DIR = os.path.join(BASE_DIR, "assets", "templates")

POSITIVE_PALETTES = [
    ((214, 168, 88), (176, 92, 78)),
    ((232, 194, 120), (196, 108, 96)),
    ((210, 160, 70), (150, 80, 90)),
]
NEGATIVE_PALETTES = [
    ((60, 66, 92), (26, 28, 40)),
    ((70, 74, 100), (34, 30, 46)),
    ((52, 60, 82), (20, 22, 32)),
]

# 大アルカナ22枚。(スラッグ, 気分, 番号)。気分は恋愛の悩みというテーマに
# 沿った独自の割り当て(伝統的なタロット解釈そのままではない)。
MAJOR_ARCANA = [
    ("the_fool", "positive", "0"),
    ("the_magician", "positive", "I"),
    ("the_high_priestess", "negative", "II"),
    ("the_empress", "positive", "III"),
    ("the_emperor", "negative", "IV"),
    ("the_hierophant", "negative", "V"),
    ("the_lovers", "positive", "VI"),
    ("the_chariot", "negative", "VII"),
    ("strength", "positive", "VIII"),
    ("the_hermit", "negative", "IX"),
    ("wheel_of_fortune", "positive", "X"),
    ("justice", "negative", "XI"),
    ("the_hanged_man", "negative", "XII"),
    ("death", "negative", "XIII"),
    ("temperance", "positive", "XIV"),
    ("the_devil", "negative", "XV"),
    ("the_tower", "negative", "XVI"),
    ("the_star", "positive", "XVII"),
    ("the_moon", "negative", "XVIII"),
    ("the_sun", "positive", "XIX"),
    ("judgement", "positive", "XX"),
    ("the_world", "positive", "XXI"),
]


def _lerp(a: int, b: int, t: float) -> int:
    return int(a + (b - a) * t)


def _gradient_background(size: tuple[int, int], top_color, bottom_color) -> Image.Image:
    w, h = size
    img = Image.new("RGB", size, top_color)
    draw = ImageDraw.Draw(img)
    for y in range(h):
        t = y / max(h - 1, 1)
        color = tuple(_lerp(top_color[i], bottom_color[i], t) for i in range(3))
        draw.line([(0, y), (w, y)], fill=color)
    return img


def _add_parchment_noise(img: Image.Image, amount: int = 10) -> Image.Image:
    """PILの効果的なC実装（effect_noise/blend）でパーチメント風の斑を軽く重ねる。"""
    noise = Image.effect_noise(img.size, 40)
    noise_rgb = noise.convert("RGB").filter(ImageFilter.GaussianBlur(1))
    alpha = min(max(amount / 255, 0.0), 0.3)
    return Image.blend(img, noise_rgb, alpha)


def _draw_ornate_border(draw: ImageDraw.ImageDraw, size: tuple[int, int], color) -> None:
    w, h = size
    margin = 36
    draw.rectangle([margin, margin, w - margin, h - margin], outline=color, width=6)
    draw.rectangle([margin + 14, margin + 14, w - margin - 14, h - margin - 14], outline=color, width=2)

    corner_r = 26
    for cx, cy in [
        (margin, margin),
        (w - margin, margin),
        (margin, h - margin),
        (w - margin, h - margin),
    ]:
        draw.ellipse([cx - corner_r, cy - corner_r, cx + corner_r, cy + corner_r], outline=color, width=4)
        draw.ellipse([cx - corner_r // 2, cy - corner_r // 2, cx + corner_r // 2, cy + corner_r // 2], outline=color, width=2)

    for cy in (margin, h - margin):
        cx = w // 2
        draw.ellipse([cx - 16, cy - 16, cx + 16, cy + 16], outline=color, width=3)


def _draw_roman_numeral_label(draw: ImageDraw.ImageDraw, numeral: str, size: tuple[int, int], color) -> None:
    """カード番号を下部の飾り枠内に小さく描く(専用フォント不要の簡易マーカー)。"""
    w, h = size
    cx = w // 2
    cy = h - 60
    tick_w = 10
    total = len(numeral) * (tick_w + 6)
    x = cx - total // 2
    for ch in numeral:
        if ch == "I":
            draw.line([(x, cy - 10), (x, cy + 10)], fill=color, width=3)
            x += tick_w
        elif ch == "V":
            draw.line([(x, cy - 10), (x + 6, cy + 10), (x + 12, cy - 10)], fill=color, width=2)
            x += tick_w + 6
        elif ch == "X":
            draw.line([(x, cy - 10), (x + 12, cy + 10)], fill=color, width=2)
            draw.line([(x, cy + 10), (x + 12, cy - 10)], fill=color, width=2)
            x += tick_w + 8
        elif ch == "0":
            draw.ellipse([x, cy - 10, x + 12, cy + 10], outline=color, width=2)
            x += tick_w + 8


# --- 図案パーツ(既存のロジックを流用・拡張) ------------------------------

def _draw_radiant_sun(draw, center, radius, color, ray_count=16) -> None:
    cx, cy = center
    draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=color)
    for i in range(ray_count):
        angle = (2 * math.pi / ray_count) * i
        inner = radius * 1.15
        outer = radius * (1.6 + 0.3 * ((i % 3) / 2))
        x1, y1 = cx + inner * math.cos(angle), cy + inner * math.sin(angle)
        x2, y2 = cx + outer * math.cos(angle), cy + outer * math.sin(angle)
        draw.line([(x1, y1), (x2, y2)], fill=color, width=5)


def _draw_blooming_motif(draw, center, size, color) -> None:
    cx, cy = center
    petal_count = 8
    for i in range(petal_count):
        angle = (2 * math.pi / petal_count) * i
        px = cx + size * math.cos(angle)
        py = cy + size * math.sin(angle)
        draw.ellipse([px - size * 0.45, py - size * 0.3, px + size * 0.45, py + size * 0.3], outline=color, width=4)
    draw.ellipse([cx - size * 0.3, cy - size * 0.3, cx + size * 0.3, cy + size * 0.3], fill=color)


def _draw_crescent_moon(draw, center, radius, color, bg_color) -> None:
    cx, cy = center
    draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=color)
    offset = radius * 0.5
    draw.ellipse([cx - radius + offset, cy - radius, cx + radius + offset, cy + radius], fill=bg_color)


def _draw_thorny_vine(draw, start, end, color, rng: random.Random) -> None:
    x1, y1 = start
    x2, y2 = end
    steps = 24
    points = []
    for i in range(steps + 1):
        t = i / steps
        x = x1 + (x2 - x1) * t + math.sin(t * math.pi * 4) * 30
        y = y1 + (y2 - y1) * t
        points.append((x, y))
    draw.line(points, fill=color, width=4, joint="curve")
    for i in range(1, len(points) - 1, 3):
        x, y = points[i]
        angle = rng.uniform(0, 2 * math.pi)
        thorn_len = 14
        draw.line([(x, y), (x + thorn_len * math.cos(angle), y + thorn_len * math.sin(angle))], fill=color, width=3)


def _draw_cracked_lines(draw, size, color, rng: random.Random, count: int = 5) -> None:
    w, h = size
    for _ in range(count):
        x, y = rng.uniform(0, w), rng.uniform(0, h)
        segments = rng.randint(3, 6)
        for _ in range(segments):
            nx = x + rng.uniform(-60, 60)
            ny = y + rng.uniform(-60, 60)
            draw.line([(x, y), (nx, ny)], fill=color, width=2)
            x, y = nx, ny


def _draw_pillars(draw, center, height, gap, color, width=6) -> None:
    cx, cy = center
    for dx in (-gap, gap):
        draw.line([(cx + dx, cy - height / 2), (cx + dx, cy + height / 2)], fill=color, width=width)


def _draw_infinity(draw, center, size, color, width=5) -> None:
    cx, cy = center
    for dx in (-size * 0.55, size * 0.55):
        draw.ellipse([cx + dx - size * 0.55, cy - size * 0.4, cx + dx + size * 0.55, cy + size * 0.4], outline=color, width=width)


def _draw_wreath(draw, center, radius, color, width=5) -> None:
    cx, cy = center
    draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], outline=color, width=width)
    draw.ellipse([cx - radius * 0.6, cy - radius * 0.6, cx + radius * 0.6, cy + radius * 0.6], outline=color, width=2)
    for i in range(4):
        angle = math.pi / 2 * i
        x, y = cx + radius * 1.15 * math.cos(angle), cy + radius * 1.15 * math.sin(angle)
        draw.line([(x - 8, y), (x + 8, y)], fill=color, width=3)
        draw.line([(x, y - 8), (x, y + 8)], fill=color, width=3)


def _draw_scale(draw, center, width_, color) -> None:
    cx, cy = center
    draw.line([(cx, cy - width_ * 0.4), (cx, cy + width_ * 0.25)], fill=color, width=4)
    draw.line([(cx - width_ / 2, cy - width_ * 0.4), (cx + width_ / 2, cy - width_ * 0.4)], fill=color, width=4)
    for dx in (-width_ / 2, width_ / 2):
        draw.line([(cx + dx, cy - width_ * 0.4), (cx + dx, cy - width_ * 0.05)], fill=color, width=2)
        draw.arc([cx + dx - 30, cy - width_ * 0.05, cx + dx + 30, cy + width_ * 0.15], 0, 180, fill=color, width=3)


def _draw_small_stars(draw, center, spread, color, rng: random.Random, count=7) -> None:
    cx, cy = center
    for _ in range(count):
        x = cx + rng.uniform(-spread, spread)
        y = cy + rng.uniform(-spread * 0.7, spread * 0.7)
        r = rng.uniform(8, 16)
        draw.line([(x - r, y), (x + r, y)], fill=color, width=2)
        draw.line([(x, y - r), (x, y + r)], fill=color, width=2)
        draw.line([(x - r * 0.7, y - r * 0.7), (x + r * 0.7, y + r * 0.7)], fill=color, width=2)
        draw.line([(x - r * 0.7, y + r * 0.7), (x + r * 0.7, y - r * 0.7)], fill=color, width=2)


def _draw_chain(draw, start, end, color, links=6) -> None:
    x1, y1 = start
    x2, y2 = end
    for i in range(links):
        t = (i + 0.5) / links
        x = x1 + (x2 - x1) * t
        y = y1 + (y2 - y1) * t
        r = 16
        draw.ellipse([x - r, y - r * 0.6, x + r, y + r * 0.6], outline=color, width=4)


def _draw_tower(draw, center, w_, h_, color, rng: random.Random) -> None:
    cx, cy = center
    left, right = cx - w_ / 2, cx + w_ / 2
    top, bottom = cy - h_ / 2, cy + h_ / 2
    draw.rectangle([left, top, right, bottom], outline=color, width=5)
    for angle_top in range(3):
        x = left + (right - left) * (angle_top + 0.5) / 3
        draw.rectangle([x - 8, top - 16, x + 8, top], outline=color, width=3)
    # 亀裂
    x, y = cx, top
    while y < bottom:
        nx = x + rng.uniform(-30, 30)
        ny = y + rng.uniform(30, 60)
        draw.line([(x, y), (nx, ny)], fill=color, width=3)
        x, y = nx, ny
    # 稲妻
    bolt = [(right + 20, top - 40), (right - 10, top + 20), (right + 30, top + 20), (right - 20, top + 90)]
    draw.line(bolt, fill=color, width=4)


def _draw_hanged_figure(draw, center, size, color) -> None:
    cx, cy = center
    draw.line([(cx - size, cy - size), (cx + size, cy - size)], fill=color, width=5)
    draw.line([(cx, cy - size), (cx, cy - size * 0.3)], fill=color, width=4)
    draw.polygon(
        [(cx, cy - size * 0.3), (cx - size * 0.35, cy + size * 0.4), (cx + size * 0.35, cy + size * 0.4)],
        outline=color,
        width=4,
    )
    draw.ellipse([cx - size * 0.18, cy + size * 0.4, cx + size * 0.18, cy + size * 0.4 + size * 0.36], outline=color, width=4)


def _draw_crossbones(draw, center, size, color) -> None:
    cx, cy = center
    for dx1, dy1, dx2, dy2 in [(-size, -size, size, size), (-size, size, size, -size)]:
        draw.line([(cx + dx1, cy + dy1), (cx + dx2, cy + dy2)], fill=color, width=6)
        for dx, dy in [(dx1, dy1), (dx2, dy2)]:
            ang = math.atan2(dy, dx)
            perp = ang + math.pi / 2
            px, py = cx + dx, cy + dy
            draw.line(
                [
                    (px + 14 * math.cos(perp), py + 14 * math.sin(perp)),
                    (px - 14 * math.cos(perp), py - 14 * math.sin(perp)),
                ],
                fill=color,
                width=4,
            )


def _draw_bowtie(draw, center, size, color) -> None:
    cx, cy = center
    draw.polygon([(cx - size, cy - size * 0.6), (cx, cy), (cx - size, cy + size * 0.6)], outline=color, width=4)
    draw.polygon([(cx + size, cy - size * 0.6), (cx, cy), (cx + size, cy + size * 0.6)], outline=color, width=4)
    draw.line([(cx - size * 1.3, cy), (cx + size * 1.3, cy)], fill=color, width=3)


def _draw_cups(draw, center, size, color) -> None:
    cx, cy = center
    for dx in (-size * 0.6, size * 0.6):
        draw.polygon(
            [(cx + dx - size * 0.35, cy - size * 0.3), (cx + dx + size * 0.35, cy - size * 0.3), (cx + dx, cy + size * 0.35)],
            outline=color,
            width=4,
        )
    draw.line([(cx - size * 0.25, cy - size * 0.05), (cx + size * 0.25, cy - size * 0.05)], fill=color, width=3)


def _draw_trumpet_rise(draw, center, size, color) -> None:
    cx, cy = center
    draw.polygon([(cx, cy - size * 0.4), (cx - size * 0.4, cy + size * 0.5), (cx + size * 0.4, cy + size * 0.5)], outline=color, width=4)
    for i in range(5):
        angle = math.pi * (0.15 + 0.14 * i)
        x1 = cx + size * 0.55 * math.cos(math.pi + angle)
        y1 = cy - size * 0.4 - size * 0.1 * math.sin(angle)
        x2 = cx + size * 0.9 * math.cos(math.pi + angle)
        y2 = cy - size * 0.4 - size * 0.5 * math.sin(angle)
        draw.line([(x1, y1), (x2, y2)], fill=color, width=3)


def _draw_lantern_staff(draw, center, size, color) -> None:
    cx, cy = center
    draw.line([(cx, cy - size * 0.2), (cx, cy + size)], fill=color, width=5)
    _draw_radiant_sun(draw, (cx, cy - size * 0.5), radius=size * 0.28, color=color, ray_count=8)


def _draw_crown(draw, center, size, color) -> None:
    cx, cy = center
    base_y = cy + size * 0.3
    points = [(cx - size, base_y)]
    for i in range(5):
        x = cx - size + (2 * size) * i / 4
        peak_y = base_y - size * (0.8 if i % 2 == 0 else 0.45)
        points.append((x, peak_y))
    points.append((cx + size, base_y))
    draw.line(points, fill=color, width=5, joint="curve")
    draw.line([(cx - size, base_y), (cx + size, base_y)], fill=color, width=5)


def _draw_arch_gate(draw, center, width_, height, color) -> None:
    cx, cy = center
    left, right = cx - width_ / 2, cx + width_ / 2
    top, bottom = cy - height / 2, cy + height / 2
    draw.line([(left, bottom), (left, top)], fill=color, width=5)
    draw.line([(right, bottom), (right, top)], fill=color, width=5)
    draw.arc([left, top - width_ / 2, right, top + width_ / 2], 180, 360, fill=color, width=5)


def _draw_wagon_wheel(draw, center, radius, color, spokes=8) -> None:
    cx, cy = center
    draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], outline=color, width=5)
    draw.ellipse([cx - radius * 0.15, cy - radius * 0.15, cx + radius * 0.15, cy + radius * 0.15], outline=color, width=3)
    for i in range(spokes):
        angle = (2 * math.pi / spokes) * i
        x1, y1 = cx + radius * 0.15 * math.cos(angle), cy + radius * 0.15 * math.sin(angle)
        x2, y2 = cx + radius * math.cos(angle), cy + radius * math.sin(angle)
        draw.line([(x1, y1), (x2, y2)], fill=color, width=3)


def _draw_footpath(draw, center, size, color) -> None:
    cx, cy = center
    draw.line([(cx - size, cy + size * 0.6), (cx + size * 0.3, cy - size * 0.7)], fill=color, width=5)
    draw.ellipse([cx + size * 0.3 - 22, cy - size * 0.7 - 22, cx + size * 0.3 + 22, cy - size * 0.7 + 22], outline=color, width=4)


def _draw_eye_veil(draw, center, size, color) -> None:
    cx, cy = center
    draw.arc([cx - size, cy - size * 0.5, cx + size, cy + size * 0.5], 200, 340, fill=color, width=4)
    draw.ellipse([cx - size * 0.18, cy - size * 0.18, cx + size * 0.18, cy + size * 0.18], outline=color, width=4)
    _draw_pillars(draw, center, size * 1.6, size * 1.3, color, width=4)


CARD_ICONS = {}


def _icon(slug):
    def deco(fn):
        CARD_ICONS[slug] = fn
        return fn

    return deco


@_icon("the_fool")
def _icon_fool(draw, size, color, rng):
    _draw_footpath(draw, (size[0] // 2, int(size[1] * 0.55)), 180, color)


@_icon("the_magician")
def _icon_magician(draw, size, color, rng):
    w, h = size
    _draw_infinity(draw, (w // 2, int(h * 0.42)), 70, color)
    draw.line([(w // 2, int(h * 0.5)), (w // 2, int(h * 0.68))], fill=color, width=5)
    draw.line([(int(w * 0.35), int(h * 0.68)), (int(w * 0.65), int(h * 0.68))], fill=color, width=4)


@_icon("the_high_priestess")
def _icon_high_priestess(draw, size, color, rng):
    w, h = size
    _draw_pillars(draw, (w // 2, int(h * 0.55)), 260, 130, color)
    _draw_crescent_moon(draw, (w // 2, int(h * 0.5)), 46, color, bg_color=(0, 0, 0))


@_icon("the_empress")
def _icon_empress(draw, size, color, rng):
    w, h = size
    _draw_blooming_motif(draw, (w // 2, int(h * 0.55)), 130, color)
    _draw_crown(draw, (w // 2, int(h * 0.32)), 60, color)


@_icon("the_emperor")
def _icon_emperor(draw, size, color, rng):
    w, h = size
    _draw_crown(draw, (w // 2, int(h * 0.4)), 90, color)
    draw.rectangle([int(w * 0.4), int(h * 0.55), int(w * 0.6), int(h * 0.75)], outline=color, width=5)


@_icon("the_hierophant")
def _icon_hierophant(draw, size, color, rng):
    w, h = size
    _draw_arch_gate(draw, (w // 2, int(h * 0.55)), 220, 280, color)
    draw.line([(w // 2 - 30, int(h * 0.55)), (w // 2 + 30, int(h * 0.55))], fill=color, width=4)


@_icon("the_lovers")
def _icon_lovers(draw, size, color, rng):
    w, h = size
    r = 110
    draw.ellipse([w // 2 - r * 1.3, h * 0.5 - r, w // 2 + r * 0.3, h * 0.5 + r], outline=color, width=5)
    draw.ellipse([w // 2 - r * 0.3, h * 0.5 - r, w // 2 + r * 1.3, h * 0.5 + r], outline=color, width=5)


@_icon("the_chariot")
def _icon_chariot(draw, size, color, rng):
    w, h = size
    _draw_bowtie(draw, (w // 2, int(h * 0.55)), 120, color)
    _draw_wagon_wheel(draw, (w // 2, int(h * 0.78)), 50, color)


@_icon("strength")
def _icon_strength(draw, size, color, rng):
    w, h = size
    draw.ellipse([w // 2 - 100, h * 0.5 - 80, w // 2 + 100, h * 0.5 + 80], outline=color, width=5)
    _draw_infinity(draw, (w // 2, int(h * 0.34)), 55, color)


@_icon("the_hermit")
def _icon_hermit(draw, size, color, rng):
    w, h = size
    _draw_lantern_staff(draw, (w // 2, int(h * 0.45)), 260, color)


@_icon("wheel_of_fortune")
def _icon_wheel(draw, size, color, rng):
    w, h = size
    _draw_wagon_wheel(draw, (w // 2, int(h * 0.5)), 130, color)


@_icon("justice")
def _icon_justice(draw, size, color, rng):
    w, h = size
    _draw_scale(draw, (w // 2, int(h * 0.55)), 260, color)


@_icon("the_hanged_man")
def _icon_hanged_man(draw, size, color, rng):
    w, h = size
    _draw_hanged_figure(draw, (w // 2, int(h * 0.42)), 130, color)


@_icon("death")
def _icon_death(draw, size, color, rng):
    w, h = size
    _draw_crossbones(draw, (w // 2, int(h * 0.5)), 110, color)
    _draw_cracked_lines(draw, size, color, rng, count=4)


@_icon("temperance")
def _icon_temperance(draw, size, color, rng):
    w, h = size
    _draw_cups(draw, (w // 2, int(h * 0.55)), 170, color)


@_icon("the_devil")
def _icon_devil(draw, size, color, rng):
    w, h = size
    _draw_chain(draw, (int(w * 0.25), int(h * 0.75)), (int(w * 0.75), int(h * 0.75)), color)
    draw.polygon(
        [
            (w // 2, int(h * 0.3)),
            (int(w * 0.4), int(h * 0.42)),
            (int(w * 0.6), int(h * 0.42)),
        ],
        outline=color,
        width=4,
    )
    draw.arc([w // 2 - 55, int(h * 0.28), w // 2 - 5, int(h * 0.38)], 0, 300, fill=color, width=4)
    draw.arc([w // 2 + 5, int(h * 0.28), w // 2 + 55, int(h * 0.38)], -120, 180, fill=color, width=4)


@_icon("the_tower")
def _icon_tower(draw, size, color, rng):
    w, h = size
    _draw_tower(draw, (w // 2, int(h * 0.5)), 180, 340, color, rng)


@_icon("the_star")
def _icon_star(draw, size, color, rng):
    w, h = size
    _draw_radiant_sun(draw, (w // 2, int(h * 0.38)), radius=60, color=color, ray_count=8)
    _draw_small_stars(draw, (w // 2, int(h * 0.68)), 220, color, rng, count=6)


@_icon("the_moon")
def _icon_moon(draw, size, color, rng):
    w, h = size
    _draw_crescent_moon(draw, (w // 2, int(h * 0.36)), 78, color, bg_color=(0, 0, 0))
    _draw_thorny_vine(draw, (int(w * 0.25), int(h * 0.55)), (int(w * 0.75), int(h * 0.82)), color, rng)


@_icon("the_sun")
def _icon_sun(draw, size, color, rng):
    w, h = size
    _draw_radiant_sun(draw, (w // 2, int(h * 0.4)), radius=90, color=color)
    for dx in (-0.28, 0, 0.28):
        _draw_blooming_motif(draw, (int(w * (0.5 + dx)), int(h * 0.75)), 55 if dx else 100, color)


@_icon("judgement")
def _icon_judgement(draw, size, color, rng):
    w, h = size
    _draw_trumpet_rise(draw, (w // 2, int(h * 0.6)), 220, color)


@_icon("the_world")
def _icon_world(draw, size, color, rng):
    w, h = size
    _draw_wreath(draw, (w // 2, int(h * 0.5)), 150, color)


def _make_card(slug: str, mood: str, numeral: str) -> Image.Image:
    rng = random.Random(f"{slug}-{mood}")
    if mood == "positive":
        top_color, bottom_color = rng.choice(POSITIVE_PALETTES)
        line_color = (255, 235, 200)
    else:
        top_color, bottom_color = rng.choice(NEGATIVE_PALETTES)
        line_color = (150, 160, 190)

    img = _gradient_background(CANVAS_SIZE, top_color, bottom_color)
    img = _add_parchment_noise(img, amount=14 if mood == "positive" else 16)
    draw = ImageDraw.Draw(img)

    icon_fn = CARD_ICONS[slug]
    icon_fn(draw, CANVAS_SIZE, line_color, rng)

    _draw_ornate_border(draw, CANVAS_SIZE, line_color)
    _draw_roman_numeral_label(draw, numeral, CANVAS_SIZE, line_color)
    img = img.filter(ImageFilter.SMOOTH_MORE)
    return img


def main() -> None:
    positive_dir = os.path.join(TEMPLATES_DIR, "positive")
    negative_dir = os.path.join(TEMPLATES_DIR, "negative")
    os.makedirs(positive_dir, exist_ok=True)
    os.makedirs(negative_dir, exist_ok=True)

    # 旧世代の抽象テンプレート(positive_01.png等)が残っていれば削除し、
    # 大アルカナの命名済みファイルだけの構成にする。
    for old_dir in (positive_dir, negative_dir):
        for name in os.listdir(old_dir):
            if name.lower().endswith(".png") and not any(name.startswith(slug) for slug, _, _ in MAJOR_ARCANA):
                os.remove(os.path.join(old_dir, name))

    for slug, mood, numeral in MAJOR_ARCANA:
        target_dir = positive_dir if mood == "positive" else negative_dir
        img = _make_card(slug, mood, numeral).quantize(colors=128, method=Image.Quantize.MEDIANCUT)
        path = os.path.join(target_dir, f"{slug}.png")
        img.save(path, optimize=True)
        print(f"生成: {path} ({os.path.getsize(path) // 1024}KB)")


if __name__ == "__main__":
    main()
