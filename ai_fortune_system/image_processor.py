"""Pillowによるテキスト合成処理 — 背景画像にキャッチコピーを重ねて鑑定書風画像を作る。"""

import logging
import os
import uuid

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

CANVAS_SIZE = (1080, 1080)
OVERLAY_OPACITY = 110  # 0-255, テキストの可読性を確保するための暗幕の濃さ

# コンテナ/ローカル環境で日本語フォントが見つかりそうな代表的なパス。
# FONT_PATH環境変数が優先され、これらはフォールバックとして使われる。
FALLBACK_FONT_PATHS = [
    "fonts/NotoSansJP-Bold.otf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansJP-Bold.otf",
    "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
    "C:/Windows/Fonts/meiryob.ttc",
]


class ImageProcessorError(Exception):
    """画像合成処理に関するエラー。"""


def _resolve_font_path(font_path: str | None) -> str | None:
    candidates = [font_path] if font_path else []
    candidates.append(os.getenv("FONT_PATH"))
    candidates.extend(FALLBACK_FONT_PATHS)
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate
    return None


def _load_font(font_path: str | None, size: int) -> ImageFont.FreeTypeFont:
    resolved = _resolve_font_path(font_path)
    if resolved:
        return ImageFont.truetype(resolved, size)
    logger.warning(
        "日本語フォントが見つからないため、PIL標準フォントにフォールバックします。"
        "fonts/ ディレクトリにNotoSansJPなどのフォントを配置するか、"
        "FONT_PATH環境変数で指定してください。"
    )
    return ImageFont.load_default(size=size)


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    lines: list[str] = []
    current_line = ""
    for char in text:
        trial_line = current_line + char
        width = draw.textbbox((0, 0), trial_line, font=font)[2]
        if width <= max_width or not current_line:
            current_line = trial_line
        else:
            lines.append(current_line)
            current_line = char
    if current_line:
        lines.append(current_line)
    return lines


def _resize_cover(img: Image.Image, target_size: tuple[int, int]) -> Image.Image:
    """アスペクト比を保ったまま拡大し、target_sizeぴったりに中央でクロップする。"""
    target_w, target_h = target_size
    src_w, src_h = img.size
    scale = max(target_w / src_w, target_h / src_h)
    new_w, new_h = round(src_w * scale), round(src_h * scale)
    img = img.resize((new_w, new_h))
    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    return img.crop((left, top, left + target_w, top + target_h))


def _draw_option_label(draw: ImageDraw.ImageDraw, text: str, center_x: int, top_y: int, font: ImageFont.FreeTypeFont) -> None:
    """【A】【B】のようなラベルを、背景に関わらず見やすい黒バッジ付きで描画する。"""
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    padding_x, padding_y = 24, 16
    box_left = center_x - text_width // 2 - padding_x
    box_right = center_x + text_width // 2 + padding_x
    box_top = top_y
    box_bottom = top_y + (bbox[3] - bbox[1]) + padding_y * 2
    draw.rounded_rectangle([(box_left, box_top), (box_right, box_bottom)], radius=16, fill=(0, 0, 0))
    draw.text((center_x - text_width // 2 - bbox[0], box_top + padding_y - bbox[1]), text, font=font, fill="white")


def compose_dual_fortune_image(
    image_a_path: str,
    image_b_path: str,
    catchphrase: str,
    output_dir: str,
    font_path: str | None = None,
    font_size: int = 64,
    label_font_size: int = 90,
) -> str:
    """選択肢A(前向き)・B(厳しい現実)の2枚を左右に並べ、中央にキャッチコピー、
    各半分の上部に【A】【B】ラベルを大きく配置した鑑定書風画像を生成する。"""
    try:
        half_width = CANVAS_SIZE[0] // 2
        with Image.open(image_a_path) as img_a:
            left_half = _resize_cover(img_a.convert("RGB"), (half_width, CANVAS_SIZE[1]))
        with Image.open(image_b_path) as img_b:
            right_half = _resize_cover(img_b.convert("RGB"), (CANVAS_SIZE[0] - half_width, CANVAS_SIZE[1]))

        canvas = Image.new("RGB", CANVAS_SIZE)
        canvas.paste(left_half, (0, 0))
        canvas.paste(right_half, (half_width, 0))

        overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        band_top = int(CANVAS_SIZE[1] * 0.38)
        band_bottom = int(CANVAS_SIZE[1] * 0.62)
        overlay_draw.rectangle(
            [(0, band_top), (CANVAS_SIZE[0], band_bottom)],
            fill=(10, 10, 20, OVERLAY_OPACITY),
        )
        canvas = Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB")

        draw = ImageDraw.Draw(canvas)
        font = _load_font(font_path, font_size)
        max_text_width = int(CANVAS_SIZE[0] * 0.82)
        lines = _wrap_text(draw, catchphrase, font, max_text_width)

        line_heights = [draw.textbbox((0, 0), line, font=font)[3] for line in lines]
        line_spacing = 16
        total_text_height = sum(line_heights) + line_spacing * (len(lines) - 1)
        y = (CANVAS_SIZE[1] - total_text_height) // 2

        for line, line_height in zip(lines, line_heights):
            line_width = draw.textbbox((0, 0), line, font=font)[2]
            x = (CANVAS_SIZE[0] - line_width) // 2
            # 縁取りを付けて背景の濃淡に関わらず視認性を確保する
            draw.text((x, y), line, font=font, fill="white", stroke_width=3, stroke_fill="black")
            y += line_height + line_spacing

        label_font = _load_font(font_path, label_font_size)
        label_top_y = int(CANVAS_SIZE[1] * 0.06)
        _draw_option_label(draw, "【A】", half_width // 2, label_top_y, label_font)
        _draw_option_label(draw, "【B】", half_width + (CANVAS_SIZE[0] - half_width) // 2, label_top_y, label_font)

        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, f"fortune_{uuid.uuid4().hex}.png")
        canvas.save(output_path)
        return output_path
    except Exception as exc:
        logger.exception("画像合成中にエラーが発生しました")
        raise ImageProcessorError(str(exc)) from exc
