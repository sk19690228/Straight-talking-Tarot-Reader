"""コンテンツ生成モジュール — 辛口タロット占いの文章・画像素材の選定を担当する。

OpenAI APIには依存しない構成です。
- 文章生成: Google Gemini API（無料枠あり）
- 画像: 毎回AIで生成せず、あらかじめ用意した静的テンプレート素材
  （assets/templates/positive, negative。scripts/generate_templates.pyで生成済み）
  からランダムに選ぶだけなので、画像生成コストは一切かかりません。

2段階分岐（Q1: A/B → Q2: θ/δ または η/φ → 最終診断）のコンテンツ一式を
1回のAPI呼び出しで生成する。
"""

import json
import logging
import os
import random

import requests

logger = logging.getLogger(__name__)

TEXT_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
GEMINI_ENDPOINT_TEMPLATE = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "assets", "templates")

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

不倫・既婚者との恋愛がテーマの回では、特に以下を守ってください。
- 相手を美化したり「あなたは特別な存在」と煽ったりしない
- 罪悪感を意図的に取り除いたり、「気持ちに良い悪いはない」のような免罪符となる言い回しを使わない
- 課金・個別鑑定への誘導や、繰り返し読ませることを目的とした言葉選びをしない
- あくまで現実を直視させる辛口な指摘に徹する（他のテーマと同じトーン・厳しさで扱う）

【全体構成】
今回は、Q1への回答に応じてさらに深掘りしたQ2を出し分ける、2段階の分岐鑑定を作成します。

- Q1: 本日のお悩みテーマについての「問いかけ」。
  選択肢A（前向き・希望を持てる側）、選択肢B（厳しい現実を直視する側）。
- Q1でAと答えた人には、Aの選択をさらに深掘りするQ2-Aを出す。
  選択肢θ（シータ。Aの中でもさらに前向きに踏み込む側）、
  選択肢δ（デルタ。Aを選んだはずなのに不安がふと顔を出す側）。
- Q1でBと答えた人には、Bの選択をさらに深掘りするQ2-Bを出す。
  選択肢η（イータ。Bの中に一筋の希望が見える側）、
  選択肢φ（ファイ。Bの中でさらに厳しい現実を突きつけられる側）。
- 最終的な組み合わせ（A→θ、A→δ、B→η、B→φ）ごとに、精神分析の視点も交えた
  辛口の占い＆アドバイス文を作成する。Q1・Q2はどちらも「Aへは『A』、
  該当の選択肢へは『B』とリプライしてね」という形式で読者に促すこと
  （実際の返信は常に「A」または「B」の1文字。θ/δ/η/φはあなたが内部で
  区別するための名称であり、読者に見せる返信の指示は必ずA/Bにする）。

出力は必ず次の構造を持つJSONオブジェクトのみとします。前後に説明文やコードブロックの
記号（```など）を一切付けないでください。
{
  "level1": {
    "question": "Q1の投稿本文（120文字以内。Aへは『A』、Bへは『B』とリプライするよう
      促す一文を含める。絵文字は控えめに1〜2個まで）",
    "catchphrase": "Q1の画像最上部に載せる短いキャッチコピー。抽象的な言い回しは避け、
      悩みの具体的な状況が一目で伝わる言い回しにする（全角28文字以内）",
    "option_a_label": "選択肢Aの短い見出し（前向きな選択、10文字以内）",
    "option_b_label": "選択肢Bの短い見出し（厳しい現実を選ぶ側、10文字以内）"
  },
  "level2_a": {
    "question": "Q1でAと答えた人へのリプライ本文（Aをさらに深掘りする問いかけ、
      100文字以内。θへは『A』、δへは『B』とリプライするよう促す一文を含める）",
    "catchphrase": "Q2-Aの画像最上部に載せる短いキャッチコピー（全角28文字以内）",
    "option_theta_label": "選択肢θの短い見出し（Aの中でもさらに前向きな選択、10文字以内）",
    "option_delta_label": "選択肢δの短い見出し（Aの中で不安が顔を出す選択、10文字以内）"
  },
  "level2_b": {
    "question": "Q1でBと答えた人へのリプライ本文（Bをさらに深掘りする問いかけ、
      100文字以内。ηへは『A』、φへは『B』とリプライするよう促す一文を含める）",
    "catchphrase": "Q2-Bの画像最上部に載せる短いキャッチコピー（全角28文字以内）",
    "option_eta_label": "選択肢ηの短い見出し（Bの中に一筋の希望が見える選択、10文字以内）",
    "option_phi_label": "選択肢φの短い見出し（Bの中でさらに厳しい現実を選ぶ、10文字以内）"
  },
  "results": {
    "a_theta": "A→θと進んだ人向けの、精神分析的な視点を交えた辛口の占い＆アドバイス文（180文字以内）",
    "a_delta": "A→δと進んだ人向けの、同様の辛口アドバイス文（180文字以内）",
    "b_eta": "B→ηと進んだ人向けの、同様の辛口アドバイス文（180文字以内）",
    "b_phi": "B→φと進んだ人向けの、同様の辛口アドバイス文（180文字以内）"
  }
}
"""


class GeneratorError(Exception):
    """コンテンツ生成処理に関するエラー。"""


class ContentGenerator:
    def __init__(self, api_key: str | None = None):
        self._api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not self._api_key:
            raise GeneratorError("GEMINI_API_KEY が設定されていません。")

    def pick_daily_theme(self) -> str:
        return random.choice(DAILY_THEMES)

    def generate_branching_content(self, theme: str) -> dict:
        """お悩みテーマから、Q1(A/B)→Q2(θ/δ または η/φ)→最終診断4パターンの
        コンテンツ一式を生成する。"""
        url = GEMINI_ENDPOINT_TEMPLATE.format(model=TEXT_MODEL)
        payload = {
            "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": [
                {"role": "user", "parts": [{"text": f"本日のお悩みテーマ: {theme}"}]}
            ],
            "generationConfig": {
                "temperature": 0.9,
                "responseMimeType": "application/json",
            },
        }
        try:
            response = requests.post(
                url,
                params={"key": self._api_key},
                json=payload,
                timeout=60,
            )
            response.raise_for_status()
            data = response.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            content = json.loads(text)
            self._validate_branching_content(content)
            return content
        except GeneratorError:
            raise
        except Exception as exc:
            logger.exception("文章生成中にエラーが発生しました")
            raise GeneratorError(str(exc)) from exc

    @staticmethod
    def _validate_branching_content(content: dict) -> None:
        required_structure = {
            "level1": {"question", "catchphrase", "option_a_label", "option_b_label"},
            "level2_a": {"question", "catchphrase", "option_theta_label", "option_delta_label"},
            "level2_b": {"question", "catchphrase", "option_eta_label", "option_phi_label"},
            "results": {"a_theta", "a_delta", "b_eta", "b_phi"},
        }
        for section, keys in required_structure.items():
            if section not in content:
                raise GeneratorError(f"生成結果に必須セクションが不足しています: {section}")
            missing = keys - content[section].keys()
            if missing:
                raise GeneratorError(f"生成結果の'{section}'に必須キーが不足しています: {missing}")

    def generate_pair_images(
        self,
        positive_label: str,
        negative_label: str,
        output_dir: str,
        suffix_prefix: str,
    ) -> tuple[str, str]:
        """前向き・厳しい現実を対比的に表すタロット風画像を、静的テンプレート素材から
        1枚ずつランダムに選んで返す（AIでの画像生成は行わない）。"""
        positive_dir = os.path.join(TEMPLATES_DIR, "positive")
        negative_dir = os.path.join(TEMPLATES_DIR, "negative")
        try:
            path_positive = self._pick_random_template(positive_dir)
            path_negative = self._pick_random_template(negative_dir)
            return path_positive, path_negative
        except Exception as exc:
            logger.exception("画像テンプレートの選定中にエラーが発生しました")
            raise GeneratorError(str(exc)) from exc

    @staticmethod
    def _pick_random_template(directory: str) -> str:
        if not os.path.isdir(directory):
            raise GeneratorError(
                f"テンプレート素材フォルダが見つかりません: {directory}\n"
                "先に `python3 scripts/generate_templates.py` を実行してください。"
            )
        candidates = [
            os.path.join(directory, name)
            for name in os.listdir(directory)
            if name.lower().endswith(".png")
        ]
        if not candidates:
            raise GeneratorError(f"テンプレート素材が1枚も見つかりません: {directory}")
        return random.choice(candidates)
