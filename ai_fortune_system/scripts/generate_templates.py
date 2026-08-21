"""静的タロット風テンプレート素材を手続き的に生成するスクリプト。

OpenAIの画像生成APIを使わない構成にするため、AIで毎回画像を作る代わりに、
あらかじめこのスクリプトでPillowのみを使って「前向き」「厳しい現実」を
対比的に表す最古のタロットカード風アートを複数パターン生成し、
assets/templates/ 配下に静的素材としてコミットしておく。
本番実行時（generator.py）はこの中からランダムに1枚を選ぶだけなので、
画像生成AI・追加コストは一切発生しない。

再実行すると同じシードから同じ画像が再生成される（既存ファイルは上書き）。

使い方:
    python3 scripts/generate_templates.py
"""

import math
import os
import random

from PIL import Image, ImageDraw, ImageFilter

CANVAS_SIZE = (1024, 1536)
VARIANTS_PER_MOOD = 6

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


def _add_parchment_noise(img: Image.Image, rng: random.Random, amount: int = 10) -> Image.Image:
    """PILの効果的なC実装（effect_noise/blend）でパーチメント風の斑を軽く重ねる。"""
    w, h = img.size
    noise = Image.effect_noise((w, h), 40)
    noise_rgb = noise.convert("RGB").filter(ImageFilter.GaussianBlur(1))
    alpha = min(max(amount / 255, 0.0), 0.3)
    return Image.blend(img, noise_rgb, alpha)


def _draw_ornate_border(draw: ImageDraw.ImageDraw, size: tuple[int, int], color, rng: random.Random) -> None:
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

    # 上下中央の小さな飾り
    for cy in (margin, h - margin):
        cx = w // 2
        draw.ellipse([cx - 16, cy - 16, cx + 16, cy + 16], outline=color, width=3)


def _draw_radiant_sun(draw: ImageDraw.ImageDraw, center, radius, color, rng: random.Random) -> None:
    cx, cy = center
    draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=color)
    ray_count = 16
    for i in range(ray_count):
        angle = (2 * math.pi / ray_count) * i + rng.uniform(-0.05, 0.05)
        inner = radius * 1.15
        outer = radius * (1.6 + 0.3 * ((i % 3) / 2))
        x1, y1 = cx + inner * math.cos(angle), cy + inner * math.sin(angle)
        x2, y2 = cx + outer * math.cos(angle), cy + outer * math.sin(angle)
        draw.line([(x1, y1), (x2, y2)], fill=color, width=5)


def _draw_blooming_motif(draw: ImageDraw.ImageDraw, center, size, color, rng: random.Random) -> None:
    cx, cy = center
    petal_count = 8
    for i in range(petal_count):
        angle = (2 * math.pi / petal_count) * i
        px = cx + size * math.cos(angle)
        py = cy + size * math.sin(angle)
        draw.ellipse([px - size * 0.45, py - size * 0.3, px + size * 0.45, py + size * 0.3], outline=color, width=4)
    draw.ellipse([cx - size * 0.3, cy - size * 0.3, cx + size * 0.3, cy + size * 0.3], fill=color)


def _draw_crescent_moon(draw: ImageDraw.ImageDraw, center, radius, color, bg_color) -> None:
    cx, cy = center
    draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=color)
    offset = radius * 0.5
    draw.ellipse(
        [cx - radius + offset, cy - radius, cx + radius + offset, cy + radius],
        fill=bg_color,
    )


def _draw_thorny_vine(draw: ImageDraw.ImageDraw, start, end, color, rng: random.Random) -> None:
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
        draw.line(
            [(x, y), (x + thorn_len * math.cos(angle), y + thorn_len * math.sin(angle))],
            fill=color,
            width=3,
        )


def _draw_cracked_lines(draw: ImageDraw.ImageDraw, size, color, rng: random.Random, count: int = 5) -> None:
    w, h = size
    for _ in range(count):
        x, y = rng.uniform(0, w), rng.uniform(0, h)
        segments = rng.randint(3, 6)
        for _ in range(segments):
            nx = x + rng.uniform(-60, 60)
            ny = y + rng.uniform(-60, 60)
            draw.line([(x, y), (nx, ny)], fill=color, width=2)
            x, y = nx, ny


def _generate_positive(index: int) -> Image.Image:
    rng = random.Random(f"positive-{index}")
    top_color, bottom_color = rng.choice(POSITIVE_PALETTES)
    line_color = (255, 235, 200)
    accent_color = (255, 220, 150)

    img = _gradient_background(CANVAS_SIZE, top_color, bottom_color)
    img = _add_parchment_noise(img, rng, amount=14)
    draw = ImageDraw.Draw(img)

    w, h = CANVAS_SIZE
    _draw_radiant_sun(draw, (w // 2, int(h * 0.36)), radius=90, color=accent_color, rng=rng)
    _draw_blooming_motif(draw, (w // 2, int(h * 0.7)), size=120, color=line_color, rng=rng)
    for dx in (-0.28, 0.28):
        _draw_blooming_motif(draw, (int(w * (0.5 + dx)), int(h * 0.78)), size=60, color=line_color, rng=rng)

    _draw_ornate_border(draw, CANVAS_SIZE, line_color, rng)
    img = img.filter(ImageFilter.SMOOTH_MORE)
    return img


def _generate_negative(index: int) -> Image.Image:
    rng = random.Random(f"negative-{index}")
    top_color, bottom_color = rng.choice(NEGATIVE_PALETTES)
    line_color = (150, 160, 190)
    accent_color = (110, 118, 150)

    img = _gradient_background(CANVAS_SIZE, top_color, bottom_color)
    img = _add_parchment_noise(img, rng, amount=16)
    draw = ImageDraw.Draw(img)

    w, h = CANVAS_SIZE
    _draw_crescent_moon(draw, (w // 2, int(h * 0.34)), radius=80, color=accent_color, bg_color=top_color)
    _draw_thorny_vine(draw, (int(w * 0.25), int(h * 0.55)), (int(w * 0.75), int(h * 0.85)), line_color, rng)
    _draw_thorny_vine(draw, (int(w * 0.75), int(h * 0.55)), (int(w * 0.25), int(h * 0.85)), line_color, rng)
    _draw_cracked_lines(draw, CANVAS_SIZE, line_color, rng, count=6)

    _draw_ornate_border(draw, CANVAS_SIZE, line_color, rng)
    img = img.filter(ImageFilter.SMOOTH_MORE)
    return img


def main() -> None:
    positive_dir = os.path.join(TEMPLATES_DIR, "positive")
    negative_dir = os.path.join(TEMPLATES_DIR, "negative")
    os.makedirs(positive_dir, exist_ok=True)
    os.makedirs(negative_dir, exist_ok=True)

    for i in range(1, VARIANTS_PER_MOOD + 1):
        pos_img = _generate_positive(i).quantize(colors=128, method=Image.Quantize.MEDIANCUT)
        pos_path = os.path.join(positive_dir, f"positive_{i:02d}.png")
        pos_img.save(pos_path, optimize=True)
        print(f"生成: {pos_path} ({os.path.getsize(pos_path) // 1024}KB)")

        neg_img = _generate_negative(i).quantize(colors=128, method=Image.Quantize.MEDIANCUT)
        neg_path = os.path.join(negative_dir, f"negative_{i:02d}.png")
        neg_img.save(neg_path, optimize=True)
        print(f"生成: {neg_path} ({os.path.getsize(neg_path) // 1024}KB)")


if __name__ == "__main__":
    main()
