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
    "浮気疑惑のある恋人と、この先も一緒にいるべきか",
    "元恋人への未練を断ち切れず、新しい恋に進めない",
    "既婚者・恋人がいる相手を好きになってしまった",
    "何年も遠距離恋愛を続けているが、将来が見えない",
    "友達以上恋人未満の関係から、一歩踏み出すべきか",
    "結婚を渋る恋人と、別れて次に進むべきか",
    "音信不通になった相手を、まだ待つべきか",
    "好きな人に告白すべきか、諦めるべきか",
]

SYSTEM_PROMPT = """あなたはSNSで人気の辛口タロット占い師です。
毒舌だが的確な指摘で知られるコメンテーター2人（歯に衣着せぬ女性コメンテーターと、
論理的に矛盾を突く男性論客）が掛け合っているようなトーンで鑑定します。
ターゲット読者は30〜40代の女性です。人格否定はせず、あくまで「耳の痛いけど納得できる」
辛口アドバイスに徹してください。

このアカウントが扱うジャンルは「深い悩みのある恋愛」に固定されています。
お金・仕事・家族などの相談は一切扱わず、必ず切実な恋愛の悩みを題材にしてください。

選択肢A・Bは、対比がはっきり伝わるように以下の方針で作成してください。
- 選択肢A: 前向き・希望を持てる側の選択（例: 一歩踏み出す、信じる、待つ）
- 選択肢B: 厳しい現実を直視する側の選択（例: 見切りをつける、諦める、離れる）

不倫・既婚者との恋愛がテーマの回では、特に以下を守ってください。
- 相手を美化したり「あなたは特別な存在」と煽ったりしない
- 罪悪感を意図的に取り除いたり、「気持ちに良い悪いはない」のような免罪符となる言い回しを使わない
- 課金・個別鑑定への誘導や、繰り返し読ませることを目的とした言葉選びをしない
- あくまで現実を直視させる辛口な指摘に徹する（他のテーマと同じトーン・厳しさで扱う）

出力は必ず次のキーを持つJSONオブジェクトのみとします。
- "catchphrase": 鑑定書の画像最上部に載せるキャッチコピー。「運命の分岐点」のような
  抽象的な言い回しは避け、悩みの具体的な状況（相手との関係性、迷っている行動など）が
  一目で伝わる、具体的な言い回しにする（全角28文字以内）
- "sns_text": SNS投稿本文（120文字以内、選択肢Aへのリプライは「A」、Bへのリプライは「B」と
  送るよう読者に促す一文を含める。絵文字は控えめに1〜2個まで）
- "option_a_label": 選択肢Aの短い見出し（前向きな選択、10文字以内）
- "option_b_label": 選択肢Bの短い見出し（厳しい現実を選ぶ側、10文字以内）
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

    def generate_option_images(self, theme: str, content: dict, output_dir: str) -> tuple[str, str]:
        """選択肢A(前向き)・B(厳しい現実)を対比的に表すタロット風画像を2枚生成する。"""
        option_a = content.get("option_a_label", theme)
        option_b = content.get("option_b_label", theme)
        prompt_a = (
            "The oldest style of hand-painted medieval tarot card, 15th-century illuminated "
            "manuscript style like the earliest surviving tarot decks, aged gold leaf and "
            "cracked parchment texture, faded pigments, symbolizing hope and a positive turn "
            "in a deep romantic dilemma, warm faded gold and rose tones, blooming flowers, "
            "radiant halo light, hand-drawn ornate medieval border, no text, no words, "
            f"ancient mystical illustration, evoking: '{option_a}'"
        )
        prompt_b = (
            "The oldest style of hand-painted medieval tarot card, 15th-century illuminated "
            "manuscript style like the earliest surviving tarot decks, aged gold leaf and "
            "cracked parchment texture, faded pigments, symbolizing doubt and a harsh, sobering "
            "turn in a deep romantic dilemma, faded indigo and ash-grey tones, wilting flowers, "
            "stormy shadowed light, hand-drawn ornate medieval border, no text, no words, "
            f"ancient mystical illustration, evoking: '{option_b}'"
        )
        try:
            path_a = self._generate_single_image(prompt_a, output_dir, "a")
            path_b = self._generate_single_image(prompt_b, output_dir, "b")
            return path_a, path_b
        except Exception as exc:
            logger.exception("画像生成中にエラーが発生しました")
            raise GeneratorError(str(exc)) from exc

    def _generate_single_image(self, prompt: str, output_dir: str, suffix: str) -> str:
        response = self._client.images.generate(
            model=IMAGE_MODEL,
            prompt=prompt,
            size="1024x1536",
            n=1,
        )
        image_bytes = base64.b64decode(response.data[0].b64_json)

        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, f"bg_{suffix}_{uuid.uuid4().hex}.png")
        with open(output_path, "wb") as f:
            f.write(image_bytes)
        return output_path
