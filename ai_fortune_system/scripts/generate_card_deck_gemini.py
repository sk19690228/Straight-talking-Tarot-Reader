"""Google Gemini画像生成APIで、大アルカナ22枚のタロットカード画像を作るスクリプト。

これまでの scripts/generate_templates.py はPillowだけで手続き的に図案を
描いていたが、このスクリプトはGemini画像生成モデルに実際に絵を描かせて
assets/templates/positive・negative を上書きする。

1回限りの資産生成スクリプトであり、生成した22枚をリポジトリにコミットして
使い回すため、日次のコンテンツ生成(daily-post)では画像生成コストは一切
発生しない — generator.pyは引き続きこれらの静的ファイルからランダムに
選ぶだけ。

画像生成にはネットワーク接続とGEMINI_API_KEYが必要なため、ローカルか、
GitHub Actionsの「Generate Card Deck (Gemini)」ワークフローで実行する。

使い方:
    GEMINI_API_KEY=xxx python3 scripts/generate_card_deck_gemini.py
    # 特定のカードだけ再生成したい場合
    GEMINI_API_KEY=xxx python3 scripts/generate_card_deck_gemini.py the_tower the_devil
"""

import base64
import io
import os
import sys
import time

import requests
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from generate_templates import CANVAS_SIZE, MAJOR_ARCANA, TEMPLATES_DIR  # noqa: E402
from image_processor import _resize_cover  # noqa: E402

GEMINI_IMAGE_MODEL = os.getenv("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")
GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
MODELS_LIST_URL = "https://generativelanguage.googleapis.com/v1beta/models"

BASE_STYLE = (
    "In the painterly style of the Visconti-Sforza tarot deck, one of the oldest surviving tarot "
    "decks (15th-century Milan). Hand-painted illuminated-manuscript aesthetic: solid gold-leaf "
    "background, rich saturated medieval pigments, courtly figures in period dress, a thin ornate "
    "gold border, aged parchment texture with fine craquelure. Portrait-orientation tarot card "
    "artwork. No modern text, no numerals, no captions, no watermark, no signature."
)

# 大アルカナ22枚それぞれの図案指示。伝統的な意匠をベースに、
# 「深い悩みのある恋愛」というテーマ上のpositive/negativeの位置づけに合わせている。
CARD_DESCRIPTIONS = {
    "the_fool": (
        "The Fool: a carefree young traveler in bright clothes stepping toward a sunlit cliff "
        "edge, a small white dog at his heel, a bindle stick over one shoulder, blue sky."
    ),
    "the_magician": (
        "The Magician: a robed figure at a table, one hand raising a wand to the sky and the "
        "other pointing to the ground, cup, sword, coin, and wand laid on the table before him."
    ),
    "the_high_priestess": (
        "The High Priestess: a veiled woman seated between two dark pillars, holding a scroll "
        "in her lap, a crescent moon at her feet, an air of hidden secrets."
    ),
    "the_empress": (
        "The Empress: a crowned woman seated on a cushioned throne in a blooming garden, wearing "
        "a flowing pomegranate-patterned gown, holding a scepter."
    ),
    "the_emperor": (
        "The Emperor: a stern bearded king in armor seated on a stone throne carved with ram's "
        "heads, holding an orb and scepter, rigid and commanding."
    ),
    "the_hierophant": (
        "The Hierophant: a solemn robed high priest seated between two pillars, one hand raised "
        "in blessing, two acolytes kneeling before him."
    ),
    "the_lovers": (
        "The Lovers: a man and woman standing close together beneath a radiant winged figure in "
        "the sky, hands joined, a blossoming tree beside them."
    ),
    "the_chariot": (
        "The Chariot: an armored figure standing in a chariot pulled by two sphinxes facing "
        "opposite directions, straining against one another."
    ),
    "strength": (
        "Strength: a woman in flowing robes gently closing the jaws of a lion with her bare "
        "hands, calm and serene expression."
    ),
    "the_hermit": (
        "The Hermit: an old bearded man in a grey cloak standing alone on a mountain path at "
        "night, holding up a lantern with a single star inside it."
    ),
    "wheel_of_fortune": (
        "Wheel of Fortune: a great wheel in the sky with mythical creatures at its four corners, "
        "turning amid parting clouds."
    ),
    "justice": (
        "Justice: a robed figure seated on a throne, a raised sword in one hand and a balanced "
        "scale in the other, stern and impartial."
    ),
    "the_hanged_man": (
        "The Hanged Man: a young man hanging upside down by one foot from a wooden gallows, his "
        "face calm, hands bound behind his back."
    ),
    "death": (
        "Death: a skeletal armored figure riding a pale horse across a darkened field, a black "
        "banner bearing a white rose, fallen figures in the grass."
    ),
    "temperance": (
        "Temperance: a winged angelic figure standing with one foot on land and one in water, "
        "pouring liquid between two golden cups."
    ),
    "the_devil": (
        "The Devil: a horned demonic figure enthroned above two small chained human figures, "
        "dark red and black tones, an ominous presence."
    ),
    "the_tower": (
        "The Tower: a tall stone tower struck by lightning, its crown ablaze and crumbling, two "
        "figures falling from the high windows."
    ),
    "the_star": (
        "The Star: a woman kneeling by a pool at night, pouring water from two jugs, a great "
        "luminous star and smaller stars above her."
    ),
    "the_moon": (
        "The Moon: a pale crescent moon with a troubled face over a winding path between two "
        "towers, a wolf and a dog howling below, a crayfish emerging from the water."
    ),
    "the_sun": (
        "The Sun: a radiant golden sun with a face shining over a joyful child on a white horse, "
        "sunflowers in the background."
    ),
    "judgement": (
        "Judgement: an angel blowing a golden trumpet in the sky, figures below rising from open "
        "graves with arms raised in awe."
    ),
    "the_world": (
        "The World: a graceful dancing figure draped in cloth inside a great laurel wreath, four "
        "winged creatures (angel, eagle, lion, bull) in the corners."
    ),
}


class DeckGenerationError(Exception):
    """カード画像生成処理に関するエラー。"""


def _call_gemini_image(model: str, api_key: str, prompt: str, modalities: list[str]) -> requests.Response:
    url = GEMINI_ENDPOINT.format(model=model)
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"responseModalities": modalities},
    }
    return requests.post(url, params={"key": api_key}, json=payload, timeout=120)


def _extract_image_bytes(data: dict) -> bytes:
    parts = data["candidates"][0]["content"]["parts"]
    for part in parts:
        inline = part.get("inlineData") or part.get("inline_data")
        if inline and inline.get("data"):
            return base64.b64decode(inline["data"])
    raise DeckGenerationError(f"レスポンスに画像データが含まれていませんでした: {data}")


def _discover_image_model(api_key: str) -> str:
    response = requests.get(MODELS_LIST_URL, params={"key": api_key}, timeout=30)
    response.raise_for_status()
    models = response.json().get("models", [])
    candidates = [
        m["name"].removeprefix("models/")
        for m in models
        if "generateContent" in m.get("supportedGenerationMethods", []) and "image" in m.get("name", "").lower()
    ]
    if not candidates:
        raise DeckGenerationError("画像生成に対応するGeminiモデルが見つかりませんでした。")
    unstable_tags = ("preview", "exp", "experimental")
    stable = [c for c in candidates if not any(tag in c for tag in unstable_tags)]
    pool = stable or candidates
    pool.sort(reverse=True)
    return pool[0]


def generate_card_image(slug: str, api_key: str, model: str) -> bytes:
    """1枚分のカード画像バイト列(PNG)を生成する。モデル名の404・リクエスト形式の
    不一致・一時的なエラーに対しては、自動フォールバック・再試行を行う。"""
    prompt = f"{BASE_STYLE}\n\n{CARD_DESCRIPTIONS[slug]}"
    modalities = ["IMAGE"]
    current_model = model
    last_error: Exception | None = None

    for attempt in range(4):
        try:
            response = _call_gemini_image(current_model, api_key, prompt, modalities)
            if response.status_code == 404:
                current_model = _discover_image_model(api_key)
                print(f"    モデル切り替え: {current_model}")
                continue
            if response.status_code == 400 and modalities == ["IMAGE"]:
                modalities = ["TEXT", "IMAGE"]
                print("    responseModalitiesを['TEXT','IMAGE']に変更して再試行")
                continue
            response.raise_for_status()
            return _extract_image_bytes(response.json())
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            wait = 5 * (attempt + 1)
            print(f"    試行{attempt + 1}失敗: {exc}({wait}秒後に再試行)")
            time.sleep(wait)

    raise DeckGenerationError(f"{slug}の画像生成に失敗しました: {last_error}")


def main() -> None:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY が設定されていません。", file=sys.stderr)
        sys.exit(1)

    only_slugs = set(sys.argv[1:]) or None

    positive_dir = os.path.join(TEMPLATES_DIR, "positive")
    negative_dir = os.path.join(TEMPLATES_DIR, "negative")
    os.makedirs(positive_dir, exist_ok=True)
    os.makedirs(negative_dir, exist_ok=True)

    model = GEMINI_IMAGE_MODEL
    for slug, mood, _numeral in MAJOR_ARCANA:
        if only_slugs and slug not in only_slugs:
            continue
        print(f"生成中: {slug} ({mood})")
        image_bytes = generate_card_image(slug, api_key, model)
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        img = _resize_cover(img, CANVAS_SIZE)
        target_dir = positive_dir if mood == "positive" else negative_dir
        path = os.path.join(target_dir, f"{slug}.png")
        img.save(path, optimize=True)
        print(f"  保存: {path} ({os.path.getsize(path) // 1024}KB)")


if __name__ == "__main__":
    main()
