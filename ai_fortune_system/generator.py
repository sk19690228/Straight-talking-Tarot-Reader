"""OpenAI API連携モジュール — 辛口タロット占いの文章・画像生成を担当する。"""

import base64
import json
import logging
import os
import random
import uuid

from openai import OpenAI

logger = logging.getLogger(__name__)

TEXT_MODEL = "gpt-4o"
IMAGE_MODEL = "gpt-image-1"

DAILY_THEMES = [
    "恋愛運",
    "仕事運",
    "人間関係",
    "お金の悩み",
    "結婚・将来設計",
    "自分の性格",
    "家族との関係",
    "転職・キャリア",
]

SYSTEM_PROMPT = """あなたはSNSで人気の辛口タロット占い師です。
毒舌だが的確な指摘で知られるコメンテーター2人（歯に衣着せぬ女性コメンテーターと、
論理的に矛盾を突く男性論客）が掛け合っているようなトーンで鑑定します。
ターゲット読者は30〜40代の女性です。人格否定はせず、あくまで「耳の痛いけど納得できる」
辛口アドバイスに徹してください。

出力は必ず次のキーを持つJSONオブジェクトのみとします。
- "catchphrase": 鑑定書の画像に載せる短いキャッチコピー（全角20文字以内、体言止め推奨）
- "sns_text": SNS投稿本文（120文字以内、選択肢Aへのリプライは「A」、Bへのリプライは「B」と
  送るよう読者に促す一文を含める。絵文字は控えめに1〜2個まで）
- "option_a_label": 選択肢Aの短い見出し（10文字以内）
- "option_b_label": 選択肢Bの短い見出し（10文字以内）
- "option_a_result": 選択肢Aを選んだ人向けの辛口鑑定結果本文（150文字以内）
- "option_b_result": 選択肢Bを選んだ人向けの辛口鑑定結果本文（150文字以内）
"""


class GeneratorError(Exception):
    """コンテンツ生成処理に関するエラー。"""


class ContentGenerator:
    def __init__(self, api_key: str | None = None):
        api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise GeneratorError("OPENAI_API_KEY が設定されていません。")
        self._client = OpenAI(api_key=api_key)

    def pick_daily_theme(self) -> str:
        return random.choice(DAILY_THEMES)

    def generate_fortune_content(self, theme: str) -> dict:
        """お悩みテーマからキャッチコピー・投稿文・選択肢A/Bの鑑定結果を生成する。"""
        try:
            response = self._client.chat.completions.create(
                model=TEXT_MODEL,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"本日のお悩みテーマ: {theme}"},
                ],
                temperature=0.9,
            )
            content = json.loads(response.choices[0].message.content)
            required_keys = {
                "catchphrase",
                "sns_text",
                "option_a_label",
                "option_b_label",
                "option_a_result",
                "option_b_result",
            }
            missing = required_keys - content.keys()
            if missing:
                raise GeneratorError(f"生成結果に必須キーが不足しています: {missing}")
            return content
        except GeneratorError:
            raise
        except Exception as exc:
            logger.exception("文章生成中にエラーが発生しました")
            raise GeneratorError(str(exc)) from exc

    def generate_background_image(self, theme: str, output_dir: str) -> str:
        """gpt-image-1で古びたタロットカード風の背景画像を生成し、ローカルに保存してパスを返す。"""
        prompt = (
            "An ornate, aged antique tarot card background, mystical and vintage, "
            "sepia and deep purple tones, intricate border filigree, no text, no words, "
            f"evoking the theme of '{theme}', high detail illustration style"
        )
        try:
            response = self._client.images.generate(
                model=IMAGE_MODEL,
                prompt=prompt,
                size="1024x1024",
                n=1,
            )
            image_bytes = base64.b64decode(response.data[0].b64_json)

            os.makedirs(output_dir, exist_ok=True)
            output_path = os.path.join(output_dir, f"bg_{uuid.uuid4().hex}.png")
            with open(output_path, "wb") as f:
                f.write(image_bytes)
            return output_path
        except Exception as exc:
            logger.exception("画像生成中にエラーが発生しました")
            raise GeneratorError(str(exc)) from exc
