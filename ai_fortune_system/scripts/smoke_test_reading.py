"""個別鑑定フロー（タロット3枚の選定・合成＋Gemini鑑定文生成）を、Xには一切
触れずに動作確認するスクリプト。

架空の返信内容（生年月日・血液型・家族構成）を使って
generator.generate_personal_reading() と image_processor.compose_three_card_image()
を実際に呼び出し（Gemini呼び出しは本物）、結果を state/smoke_test_reading.json に
保存する。reply-check.py本体の動作確認に、実際のXの投稿・返信を用意する必要はない。

使い方:
    GEMINI_API_KEY=xxx python3 scripts/smoke_test_reading.py
"""

import base64
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from generator import ContentGenerator  # noqa: E402
from image_processor import compose_three_card_image  # noqa: E402

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_DIR = os.path.join(BASE_DIR, "state")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

FAKE_THEME = "浮気疑惑のある恋人と、この先も一緒にいるべきか"
FAKE_USER_MESSAGE = (
    "1990年5月3日生まれ、A型です。両親は私が10歳の時に離婚していて、"
    "父とは疎遠なまま育ちました。人を信じきれないところがあると思います。"
)


def main() -> None:
    generator = ContentGenerator()

    cards = generator.pick_three_cards()
    card_paths = [path for path, _name in cards]
    card_names = [name for _path, name in cards]

    image_path = compose_three_card_image(card_paths, OUTPUT_DIR)
    reading_text = generator.generate_personal_reading(FAKE_THEME, FAKE_USER_MESSAGE, card_names)

    with open(image_path, "rb") as f:
        image_bytes = f.read()

    os.makedirs(STATE_DIR, exist_ok=True)
    data = {
        "theme": FAKE_THEME,
        "fake_user_message": FAKE_USER_MESSAGE,
        "card_names": card_names,
        "reading_text": reading_text,
        "image_b64": base64.b64encode(image_bytes).decode("ascii"),
    }
    with open(os.path.join(STATE_DIR, "smoke_test_reading.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print("テーマ:", FAKE_THEME)
    print("架空の返信内容:", FAKE_USER_MESSAGE)
    print("引かれたカード:", card_names)
    print("生成された鑑定文:", reading_text)


if __name__ == "__main__":
    main()
