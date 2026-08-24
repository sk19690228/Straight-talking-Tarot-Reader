"""タロットカード画像の合成処理 — カード3枚を1枚の横並び画像にする。

カード素材自体に名称・絵柄が描き込まれているため、テキストのオーバーレイは
行わない（フォント同梱・インストールも不要）。
"""

import logging
import os
import uuid

from PIL import Image

logger = logging.getLogger(__name__)

# 各カードの表示セル（元画像のアスペクト比 1024:1536 = 2:3 を維持）
CARD_CELL_SIZE = (700, 1050)
CARD_GAP = 12
CANVAS_BACKGROUND = (10, 8, 4)


class ImageProcessorError(Exception):
    """画像合成処理に関するエラー。"""


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


def compose_three_card_image(card_paths: list[str], output_dir: str) -> str:
    """タロットカード3枚を横に並べた1枚の画像を作る。"""
    if len(card_paths) != 3:
        raise ImageProcessorError(f"カードは3枚指定してください（{len(card_paths)}枚受信）")
    try:
        cell_w, cell_h = CARD_CELL_SIZE
        canvas_w = cell_w * 3 + CARD_GAP * 2
        canvas = Image.new("RGB", (canvas_w, cell_h), CANVAS_BACKGROUND)

        for i, path in enumerate(card_paths):
            with Image.open(path) as img:
                cell = _resize_cover(img.convert("RGB"), (cell_w, cell_h))
            canvas.paste(cell, (i * (cell_w + CARD_GAP), 0))

        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, f"reading_{uuid.uuid4().hex}.png")
        canvas.save(output_path)
        return output_path
    except Exception as exc:
        logger.exception("タロットカード3枚の合成中にエラーが発生しました")
        raise ImageProcessorError(str(exc)) from exc
