"""タロットカード画像の合成処理。

- compose_three_card_image: カード3枚を1枚の横並び画像にする（個別鑑定の返信用）。
  カード素材自体に名称・絵柄が描き込まれているため、テキストのオーバーレイは行わない。
- compose_daily_invitation_image: カード1枚に、当日のテーマ問いかけ・入力案内の
  文章（絵文字を多用）を重ねた投稿画像を作る（当日投稿用）。
"""

import logging
import os
import re
import uuid

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

CANVAS_SIZE = (1024, 1536)

# 各カードの表示セル（元画像のアスペクト比 1024:1536 = 2:3 を維持）
CARD_CELL_SIZE = (700, 1050)
CARD_GAP = 12
CANVAS_BACKGROUND = (10, 8, 4)

BAND_COLOR = (10, 8, 4, 175)
BAND_PADDING_Y = 40

# コンテナ/ローカル環境で日本語フォント・カラー絵文字フォントが見つかりそうな
# 代表的なパス。FONT_PATH/EMOJI_FONT_PATH環境変数が優先され、これらは
# フォールバックとして使われる。
FALLBACK_FONT_PATHS = [
    "fonts/NotoSansJP-Bold.otf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansJP-Bold.otf",
    "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
    "C:/Windows/Fonts/meiryob.ttc",
]
FALLBACK_EMOJI_FONT_PATHS = [
    "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
    "/usr/share/fonts/noto/NotoColorEmoji.ttf",
]
EMOJI_FONT_STRIKE_SIZE = 109  # NotoColorEmojiはこの固定サイズでしかレンダリングできない

# 絵文字とみなす主要なUnicodeブロック（連続する絵文字・修飾子は1つのまとまりとして扱う）。
# ZWJ(U+200D)は結合絵文字（例: 👁️‍🗨️）を作る文字だが、NotoColorEmojiに該当する
# 合成グリフが無い組み合わせだと未定義文字の四角(tofu)として描画されてしまうため、
# あえてここでは絵文字の一部として扱わない。ZWJ自体は通常フォントで幅ゼロ相当に
# 描画されるだけなので、結果として構成要素の絵文字が個別に(見た目上ほぼ同じ位置に)
# 描画される。
_EMOJI_PATTERN = re.compile(
    "(?:"
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U00002B00-\U00002BFF\U0001F1E6-\U0001F1FF]"
    "[\U0000FE0F\U0001F3FB-\U0001F3FF]*"
    ")+"
)

_emoji_font_cache: ImageFont.FreeTypeFont | None = None


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


# ----------------------------------------------------------------------
# フォント読み込み
# ----------------------------------------------------------------------


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
        "FONT_PATH環境変数で指定するか、`fonts-noto-cjk`等をインストールしてください。"
    )
    return ImageFont.load_default(size=size)


def _resolve_emoji_font_path() -> str | None:
    candidates = [os.getenv("EMOJI_FONT_PATH")]
    candidates.extend(FALLBACK_EMOJI_FONT_PATHS)
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate
    return None


def _load_emoji_font() -> ImageFont.FreeTypeFont | None:
    global _emoji_font_cache
    if _emoji_font_cache is None:
        resolved = _resolve_emoji_font_path()
        if not resolved:
            logger.warning(
                "カラー絵文字フォントが見つからないため、絵文字は表示されません。"
                "EMOJI_FONT_PATH環境変数で指定するか、`fonts-noto-color-emoji`等をインストールしてください。"
            )
            return None
        _emoji_font_cache = ImageFont.truetype(resolved, size=EMOJI_FONT_STRIKE_SIZE)
    return _emoji_font_cache


# ----------------------------------------------------------------------
# 日本語＋カラー絵文字が混在するテキストの描画
# ----------------------------------------------------------------------


def _render_emoji_tile(emoji_text: str, target_height: int) -> Image.Image | None:
    """絵文字（1〜数文字のまとまり）を、指定した高さの透過PNGタイルとして描画する。
    NotoColorEmojiは固定サイズ(109px)でしか描画できないため、その等倍で描画してから
    目的の高さにリサイズする。"""
    font = _load_emoji_font()
    if font is None:
        return None
    tmp = Image.new("RGBA", (EMOJI_FONT_STRIKE_SIZE * len(emoji_text) + EMOJI_FONT_STRIKE_SIZE, EMOJI_FONT_STRIKE_SIZE * 2), (0, 0, 0, 0))
    draw = ImageDraw.Draw(tmp)
    draw.text((0, 0), emoji_text, font=font, embedded_color=True)
    bbox = tmp.getbbox()
    if not bbox:
        return None
    cropped = tmp.crop(bbox)
    w, h = cropped.size
    scale = target_height / h
    new_w = max(1, round(w * scale))
    return cropped.resize((new_w, target_height), Image.LANCZOS)


def _split_emoji_runs(text: str) -> list[tuple[str, bool]]:
    runs: list[tuple[str, bool]] = []
    pos = 0
    for m in _EMOJI_PATTERN.finditer(text):
        if m.start() > pos:
            runs.append((text[pos : m.start()], False))
        runs.append((m.group(), True))
        pos = m.end()
    if pos < len(text):
        runs.append((text[pos:], False))
    return runs


def _atomize(text: str) -> list[tuple[str, bool]]:
    """1行分のテキストを折り返し単位に分解する（絵文字ランは1つのまとまり、
    それ以外は1文字ずつ）。"""
    atoms: list[tuple[str, bool]] = []
    for run_text, is_emoji in _split_emoji_runs(text):
        if is_emoji:
            atoms.append((run_text, True))
        else:
            atoms.extend((ch, False) for ch in run_text)
    return atoms


def _measure_atom(draw: ImageDraw.ImageDraw, atom_text: str, is_emoji: bool, jp_font: ImageFont.FreeTypeFont, line_height: int) -> int:
    if is_emoji:
        tile = _render_emoji_tile(atom_text, line_height)
        return tile.width if tile else 0
    bbox = draw.textbbox((0, 0), atom_text, font=jp_font)
    return bbox[2] - bbox[0]


_HARD_BREAK_CHARS = "？?"


def _split_at_hard_breaks(text: str) -> list[str]:
    """「？」（全角/半角）の直後を必ず行の区切りにするため、テキストをその位置で
    分割する（各セグメントは行の折り返し処理へ個別に渡す）。"""
    segments: list[str] = []
    current = ""
    for ch in text:
        current += ch
        if ch in _HARD_BREAK_CHARS:
            segments.append(current)
            current = ""
    if current:
        segments.append(current)
    return segments


def _wrap_mixed_line(
    draw: ImageDraw.ImageDraw, text: str, jp_font: ImageFont.FreeTypeFont, line_height: int, max_width: int
) -> list[list[tuple[str, bool]]]:
    """1行分のテキスト(日本語＋絵文字混在)を、max_widthに収まるよう複数行に折り返す。
    「？」の直後は必ず行を区切る。2行以上になる場合は、単純に行末まで詰め込むと
    最後の行だけ極端に短くなりがちなため、各行の幅ができるだけ揃うように区切り位置を
    調整する。"""
    lines: list[list[tuple[str, bool]]] = []
    for segment in _split_at_hard_breaks(text):
        lines.extend(_wrap_segment(draw, segment, jp_font, line_height, max_width))
    return lines


def _wrap_segment(
    draw: ImageDraw.ImageDraw, text: str, jp_font: ImageFont.FreeTypeFont, line_height: int, max_width: int
) -> list[list[tuple[str, bool]]]:
    atoms = _atomize(text)
    if not atoms:
        return []
    sized = [(t, e, _measure_atom(draw, t, e, jp_font, line_height)) for t, e in atoms]
    total_width = sum(w for _, _, w in sized)
    if total_width <= max_width:
        return [[(t, e) for t, e, _w in sized]]

    # 貪欲法で必要な最小行数を求める(バランス調整後の行数もこれに合わせる)
    n_lines = 1
    acc = 0
    for _t, _e, w in sized:
        if acc + w > max_width:
            n_lines += 1
            acc = w
        else:
            acc += w

    balanced = _balanced_split(sized, n_lines, max_width)
    return [[(t, e) for t, e, _w in line] for line in balanced]


def _balanced_split(
    sized: list[tuple[str, bool, int]], n_lines: int, max_width: int
) -> list[list[tuple[str, bool, int]]]:
    """sized(各要素は(text, is_emoji, width))を、幅のバランスが取れたn_lines行に分割する。
    どの行もmax_widthに収まる分割にならなかった場合は、単純な貪欲法にフォールバックする。"""
    total_width = sum(w for _, _, w in sized)
    target = total_width / n_lines

    cumulative: list[int] = []
    running = 0
    for _t, _e, w in sized:
        running += w
        cumulative.append(running)

    break_after: list[int] = []
    search_start = 0
    for line_no in range(1, n_lines):
        ideal = target * line_no
        reserved_for_rest = n_lines - line_no  # 残りの行に最低1要素ずつ残す
        upper = len(cumulative) - reserved_for_rest
        best_idx = search_start
        best_diff = abs(cumulative[search_start] - ideal)
        for idx in range(search_start + 1, upper):
            diff = abs(cumulative[idx] - ideal)
            if diff <= best_diff:
                best_diff = diff
                best_idx = idx
        break_after.append(best_idx)
        search_start = best_idx + 1

    lines: list[list[tuple[str, bool, int]]] = []
    prev = 0
    for idx in break_after:
        lines.append(sized[prev : idx + 1])
        prev = idx + 1
    lines.append(sized[prev:])

    if any(sum(w for _t, _e, w in line) > max_width for line in lines):
        return _greedy_split(sized, max_width)
    return lines


def _greedy_split(sized: list[tuple[str, bool, int]], max_width: int) -> list[list[tuple[str, bool, int]]]:
    lines: list[list[tuple[str, bool, int]]] = []
    current: list[tuple[str, bool, int]] = []
    current_width = 0
    for t, e, w in sized:
        if current and current_width + w > max_width:
            lines.append(current)
            current = []
            current_width = 0
        current.append((t, e, w))
        current_width += w
    if current:
        lines.append(current)
    return lines


def _draw_atom_line(
    overlay: Image.Image,
    draw: ImageDraw.ImageDraw,
    atoms: list[tuple[str, bool]],
    x: int,
    y: int,
    jp_font: ImageFont.FreeTypeFont,
    line_height: int,
    fill: str,
    stroke_width: int,
    stroke_fill: str,
) -> None:
    cursor_x = x
    for atom_text, is_emoji in atoms:
        if is_emoji:
            tile = _render_emoji_tile(atom_text, line_height)
            if tile:
                overlay.paste(tile, (cursor_x, y), tile)
                cursor_x += tile.width
        else:
            draw.text((cursor_x, y), atom_text, font=jp_font, fill=fill, stroke_width=stroke_width, stroke_fill=stroke_fill)
            bbox = draw.textbbox((0, 0), atom_text, font=jp_font)
            cursor_x += bbox[2] - bbox[0]


LINE_SPACING = 14
BLOCK_GAP = 10  # 下段内の2ブロック(通常サイズ/小サイズ)の間隔


class _TextBlock:
    """1つのフォントサイズで描画する行の集まり(折り返し済み)。"""

    def __init__(self, draw: ImageDraw.ImageDraw, lines: list[str], jp_font: ImageFont.FreeTypeFont, font_size: int, max_width: int):
        self.jp_font = jp_font
        self.line_height = int(font_size * 1.3)
        self.wrapped: list[list[tuple[str, bool]]] = []
        for line in lines:
            self.wrapped.extend(_wrap_mixed_line(draw, line, jp_font, self.line_height, max_width))

    @property
    def height(self) -> int:
        if not self.wrapped:
            return 0
        return len(self.wrapped) * self.line_height + (len(self.wrapped) - 1) * LINE_SPACING


def _draw_text_block(overlay: Image.Image, draw: ImageDraw.ImageDraw, block: "_TextBlock", canvas_width: int, y: int) -> int:
    """ブロックを描画し、描画後のyカーソル位置を返す。"""
    for line_atoms in block.wrapped:
        line_width = sum(_measure_atom(draw, t, e, block.jp_font, block.line_height) for t, e in line_atoms)
        x = (canvas_width - line_width) // 2
        _draw_atom_line(overlay, draw, line_atoms, x, y, block.jp_font, block.line_height, "white", 3, "black")
        y += block.line_height + LINE_SPACING
    return y


def compose_daily_invitation_image(
    card_path: str,
    top_lines: list[str],
    bottom_lines: list[str],
    bottom_small_lines: list[str],
    output_dir: str,
    font_path: str | None = None,
    font_size: int = 50,
    small_font_size: int = 36,
) -> str:
    """タロットカード1枚に、上段(テーマ問いかけ)・下段(入力案内)の文章を重ねた
    投稿画像を作る。下段はさらに、通常サイズのbottom_linesと、より小さい
    small_font_sizeで表示するbottom_small_linesの2ブロックに分かれる。
    絵文字は日本語フォントとは別にカラー絵文字フォントで描画する。"""
    try:
        with Image.open(card_path) as img:
            base = _resize_cover(img.convert("RGB"), CANVAS_SIZE).convert("RGBA")

        jp_font = _load_font(font_path, font_size)
        jp_font_small = _load_font(font_path, small_font_size)
        max_text_width = int(CANVAS_SIZE[0] * 0.90)

        overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        top_block = _TextBlock(draw, top_lines, jp_font, font_size, max_text_width)
        bottom_block = _TextBlock(draw, bottom_lines, jp_font, font_size, max_text_width)
        bottom_small_block = _TextBlock(draw, bottom_small_lines, jp_font_small, small_font_size, max_text_width)

        top_band_top = int(CANVAS_SIZE[1] * 0.03)
        top_band_height = top_block.height + BAND_PADDING_Y * 2

        bottom_content_height = bottom_block.height + BLOCK_GAP + bottom_small_block.height
        bottom_band_bottom = int(CANVAS_SIZE[1] * 0.97)
        bottom_band_height = bottom_content_height + BAND_PADDING_Y * 2
        bottom_band_top = bottom_band_bottom - bottom_band_height

        draw.rectangle([(0, top_band_top), (CANVAS_SIZE[0], top_band_top + top_band_height)], fill=BAND_COLOR)
        draw.rectangle([(0, bottom_band_top), (CANVAS_SIZE[0], bottom_band_bottom)], fill=BAND_COLOR)

        y = top_band_top + (top_band_height - top_block.height) // 2
        _draw_text_block(overlay, draw, top_block, CANVAS_SIZE[0], y)

        y = bottom_band_top + (bottom_band_height - bottom_content_height) // 2
        y = _draw_text_block(overlay, draw, bottom_block, CANVAS_SIZE[0], y)
        y += BLOCK_GAP - LINE_SPACING
        _draw_text_block(overlay, draw, bottom_small_block, CANVAS_SIZE[0], y)

        canvas = Image.alpha_composite(base, overlay).convert("RGB")

        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, f"invitation_{uuid.uuid4().hex}.png")
        canvas.save(output_path)
        return output_path
    except Exception as exc:
        logger.exception("投稿画像の合成中にエラーが発生しました")
        raise ImageProcessorError(str(exc)) from exc
