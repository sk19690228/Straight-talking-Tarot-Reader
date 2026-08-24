"""コンテンツ生成モジュール — 辛口タロット占いの文章・画像素材の選定を担当する。

OpenAI APIには依存しない構成です。
- 文章生成: Google Gemini API（無料枠あり）
- 画像: 毎回AIで生成せず、あらかじめ用意した静的テンプレート素材
  （assets/templates/positive, negative。大アルカナ22枚）からランダムに選ぶ・
  組み合わせるだけなので、画像生成コストは一切かかりません。

流れ:
  1. 当日のお悩みテーマを問いかけ、生年月日・血液型・家族構成の入力を促す投稿を作る
     （build_daily_invitation_text。Gemini呼び出し不要のテンプレート文）。
  2. その投稿への返信ごとに、タロットカード3枚をランダムに選び（pick_three_cards）、
     返信内容（生年月日・血液型・家族構成など自由記述）とテーマを踏まえた
     個別の辛口鑑定文を1本生成する（generate_personal_reading）。
"""

import json
import logging
import os
import random
import re

import requests

logger = logging.getLogger(__name__)

TEXT_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
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

# 大アルカナ22枚のスラッグ -> 鑑定文生成の材料として使う日本語名。
# 画像自体（assets/templates配下）には英語名が描き込まれているが、
# 鑑定文の生成にはこちらの伝統的な日本語名を使う。
CARD_DISPLAY_NAMES = {
    "the_fool": "愚者",
    "the_magician": "魔術師",
    "the_high_priestess": "女教皇",
    "the_empress": "女帝",
    "the_emperor": "皇帝",
    "the_hierophant": "教皇",
    "the_lovers": "恋人",
    "the_chariot": "戦車",
    "strength": "力",
    "the_hermit": "隠者",
    "wheel_of_fortune": "運命の輪",
    "justice": "正義",
    "the_hanged_man": "吊るされた男",
    "death": "死神",
    "temperance": "節制",
    "the_devil": "悪魔",
    "the_tower": "塔",
    "the_star": "星",
    "the_moon": "月",
    "the_sun": "太陽",
    "judgement": "審判",
    "the_world": "世界",
}

DAILY_INVITATION_TEMPLATE = (
    "【本日のお悩み診断】\n"
    "{theme}\n\n"
    "気になる方は、このポストに「生年月日・血液型・家族構成」をリプライで教えてください。\n"
    "家族構成は、親兄弟、生立ち、過去のトラウマなどの情報を入力すれば、より詳細に占えます。\n"
    "タロット3枚とあなただけの辛口鑑定でお答えします🔮"
)

# 投稿画像の下段（入力案内）は、内容が案内文であり日替わりで変える必要がないため
# 固定文にしている（上段のテーマ問いかけだけをGeminiが日替わりで生成する）。
# 通常サイズの2行と、より小さいフォントで表示する3行に分かれる。
INVITATION_BIRTHDATE_LINES = [
    "まずは、あなたの生まれた日と",
    "血液型を教えてちょうだい🔮",
]
INVITATION_DETAIL_LINES = [
    "家族構成や過去の生い立ち・トラウマ",
    "いま抱えている悩みも教えて頂戴",
    "愛の深淵まで密に占ってあげるわよ",
]

READING_SYSTEM_PROMPT = """あなたはSNSで人気の辛口タロット占い師です。
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

読者から、本日のお悩みテーマに対して「生年月日・血液型・家族構成（親兄弟、生立ち、
過去のトラウマなど）」を書いた自由記述のメッセージが届く。そこから読み取れる情報
（年齢のおおよその見当・血液型・家族背景や生立ち）を、個人が特定されない範囲で
分析材料として活用し、精神分析的な視点も交えた鑑定をする。記載が不十分・不明瞭な
項目があっても構わず、書かれている情報の範囲で鑑定すること（欠けている情報を
指摘したり、再入力を求めたりしない）。

引かれたタロットカード3枚（提示された順）の伝統的な意味も踏まえ、今回のお悩みに対する
辛口の占い＆アドバイスをまとめる。

出力は必ず次の構造を持つJSONオブジェクトのみとします。前後に説明文やコードブロックの
記号（```など）を一切付けないでください。
{
  "reading": "リプライ本文（220文字以内。辛口だが読了感のある占い＆アドバイス文。
    絵文字は控えめに0〜2個まで）"
}
"""

INVITATION_SYSTEM_PROMPT = """あなたはSNSで人気の、自信家で色気のある女性タロット占い師の
ペルソナです。「〜わよ」「〜しなさい」のような、はっきりした物言いの一人称で話します。
ターゲット読者は30〜40代の、深い恋愛の悩みを抱える女性です。

本日のお悩みテーマをもとに、投稿画像の上段に載せる文章を、絵文字を使って作成してください。
文中で「？」を使う場合は、必ずその直後で文を区切ってください（「？」の後にすぐ他の文言を
続けない）。

出力は必ず次の構造を持つJSONオブジェクトのみとします。前後に説明文やコードブロックの
記号（```など）を一切付けないでください。
{
  "top_lines": [
    "1行目: 本日のお悩みテーマを、一目で刺さる形で提案する一文（全角24文字以内。「、」で
      文を区切ってよい。「？」を使う場合は文末に置く）",
    "2行目: 悩みがあれば私に相談してね、という趣旨の一文。前後に絵文字を配置する（全角20文字以内）",
    "3行目: 神秘のトートタロットで占うわよ、という趣旨の一文。絵文字は1〜2個程度に控えめにし、
      1行に収まる長さにする（全角18文字以内）"
  ]
}
"""

# 1行目（テーマ提案文）の「、」を絵文字に置き換えて改行する際に使う絵文字。
THEME_SEPARATOR_EMOJI = ["💔", "😢", "🥀", "💭", "😔", "😞"]
THEME_ENDING_EMOJI = ["🔥", "💋", "✨", "🌙", "⭐"]

# 文末が既に絵文字で終わっているかどうかの判定用（重複して追加しないため）。
_TRAILING_EMOJI_RE = re.compile(
    r"[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U00002B00-\U00002BFF\U0001F1E6-\U0001F1FF]"
    r"[\U0000FE0F\U0001F3FB-\U0001F3FF]*$"
)


class GeneratorError(Exception):
    """コンテンツ生成処理に関するエラー。"""


class _ModelNotFoundError(Exception):
    """指定したGeminiモデル名がAPI側に存在しない(404)場合の内部例外。"""


class ContentGenerator:
    def __init__(self, api_key: str | None = None):
        self._api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not self._api_key:
            raise GeneratorError("GEMINI_API_KEY が設定されていません。")

    def pick_daily_theme(self) -> str:
        return random.choice(DAILY_THEMES)

    def build_daily_invitation_text(self, theme: str) -> str:
        """当日のお悩みテーマを問いかけ、生年月日・血液型・家族構成の入力を促す投稿文を作る。
        Gemini呼び出しは不要（毎回同じ定型文にテーマだけ差し込む）。"""
        return DAILY_INVITATION_TEMPLATE.format(theme=theme)

    def generate_personal_reading(self, theme: str, user_message: str, card_names: list[str]) -> str:
        """お悩みテーマ・読者の自由記述（生年月日・血液型・家族構成など）・引かれたタロット
        3枚から、個別分析を反映した辛口の占い＆アドバイス文を1本生成する。"""
        user_content = (
            f"本日のお悩みテーマ: {theme}\n"
            f"引かれたタロットカード（3枚、提示順）: {'、'.join(card_names)}\n"
            f"読者からのメッセージ:\n{user_message}"
        )
        try:
            content = self._call_gemini_json_with_fallback(READING_SYSTEM_PROMPT, user_content)
            reading = content.get("reading")
            if not reading:
                raise GeneratorError("生成結果に'reading'が含まれていません。")
            return reading
        except GeneratorError:
            raise
        except Exception as exc:
            logger.exception("鑑定文生成中にエラーが発生しました")
            raise GeneratorError(str(exc)) from exc

    def generate_daily_invitation_top_lines(self, theme: str) -> list[str]:
        """投稿画像の上段に載せる、テーマ問いかけの文章（3行）を生成する。
        下段（入力案内）は日替わりで変える必要がないため固定文
        （INVITATION_BIRTHDATE_LINES / INVITATION_DETAIL_LINES）を使う。"""
        user_content = f"本日のお悩みテーマ: {theme}"
        try:
            content = self._call_gemini_json_with_fallback(INVITATION_SYSTEM_PROMPT, user_content)
            top_lines = content.get("top_lines")
            if not top_lines:
                raise GeneratorError("生成結果に'top_lines'が含まれていません。")
            return self._stylize_theme_line(top_lines[0]) + top_lines[1:]
        except GeneratorError:
            raise
        except Exception as exc:
            logger.exception("投稿画像用の文章生成中にエラーが発生しました")
            raise GeneratorError(str(exc)) from exc

    @staticmethod
    def _stylize_theme_line(line: str) -> list[str]:
        """1行目（テーマ提案文）の「、」を絵文字に置き換え、その位置で改行されるよう
        複数行に分割する。最後のセグメントに絵文字が無ければ、文末にも1つ追加する。"""
        segments = [seg for seg in line.split("、") if seg]
        if not segments:
            return [line]
        styled: list[str] = []
        for i, segment in enumerate(segments):
            is_last = i == len(segments) - 1
            if not is_last:
                styled.append(f"{segment}{random.choice(THEME_SEPARATOR_EMOJI)}")
            elif _TRAILING_EMOJI_RE.search(segment):
                styled.append(segment)
            else:
                styled.append(f"{segment}{random.choice(THEME_ENDING_EMOJI)}")
        return styled

    def _call_gemini_json_with_fallback(self, system_prompt: str, user_content: str) -> dict:
        try:
            return self._call_gemini_json(TEXT_MODEL, system_prompt, user_content)
        except _ModelNotFoundError as exc:
            # Geminiのモデル名は時間の経過で変わることがある(実際に
            # gemini-2.0-flashが404になるケースを確認済み)。404のエラー
            # メッセージ自体に後継モデル名(例: "use models/gemini-3.6-flash")
            # が含まれていることが多いのでまずそれを使い、含まれていない
            # 場合のみモデル一覧からプレビュー版を避けて自動選定する。
            fallback_model = self._extract_suggested_model(str(exc)) or self._discover_fallback_model()
            logger.warning(
                "モデル '%s' が見つからなかったため、'%s' にフォールバックします。",
                TEXT_MODEL,
                fallback_model,
            )
            return self._call_gemini_json(fallback_model, system_prompt, user_content)

    def _call_gemini_json(self, model: str, system_prompt: str, user_content: str) -> dict:
        url = GEMINI_ENDPOINT_TEMPLATE.format(model=model)
        payload = {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_content}]}],
            "generationConfig": {
                "temperature": 0.9,
                "responseMimeType": "application/json",
            },
        }
        response = requests.post(url, params={"key": self._api_key}, json=payload, timeout=60)
        if response.status_code == 404:
            raise _ModelNotFoundError(response.text)
        response.raise_for_status()
        data = response.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(text)

    @staticmethod
    def _extract_suggested_model(error_text: str) -> str | None:
        """404エラーメッセージ中の "models/xxx" への言及から、後継モデル名を推測する。
        通常「models/(無効になった名前)」と「models/(後継モデル名)」の2箇所が
        現れるため、2箇所目を後継モデルとみなす(1箇所しかない場合は判断しない)。"""
        matches = re.findall(r"models/([A-Za-z0-9][\w.\-]*)", error_text)
        return matches[-1] if len(matches) >= 2 else None

    def _discover_fallback_model(self) -> str:
        response = requests.get(
            "https://generativelanguage.googleapis.com/v1beta/models",
            params={"key": self._api_key},
            timeout=30,
        )
        response.raise_for_status()
        models = response.json().get("models", [])
        all_candidates = [
            m["name"].removeprefix("models/")
            for m in models
            if "generateContent" in m.get("supportedGenerationMethods", [])
        ]
        if not all_candidates:
            raise GeneratorError("generateContentに対応するGeminiモデルが見つかりませんでした。")

        # preview/exp系はレート制限が厳しく不安定なことが多いので、安定版を優先する。
        unstable_tags = ("preview", "exp", "experimental")
        stable_candidates = [c for c in all_candidates if not any(tag in c for tag in unstable_tags)]
        pool = stable_candidates or all_candidates
        flash_pool = [c for c in pool if "flash" in c] or pool
        flash_pool.sort(reverse=True)
        return flash_pool[0]

    def pick_cover_image(self) -> str:
        """当日の投稿に添える表紙用のタロットカード画像を1枚ランダムに選ぶ。"""
        try:
            mood = random.choice(("positive", "negative"))
            return self._pick_random_template(os.path.join(TEMPLATES_DIR, mood))
        except Exception as exc:
            logger.exception("表紙画像の選定中にエラーが発生しました")
            raise GeneratorError(str(exc)) from exc

    def pick_three_cards(self) -> list[tuple[str, str]]:
        """タロットカード3枚を、大アルカナ22枚（positive/negative問わず）から
        重複なくランダムに選ぶ。戻り値は (画像パス, 日本語表示名) のリスト。"""
        try:
            all_paths = []
            for mood in ("positive", "negative"):
                directory = os.path.join(TEMPLATES_DIR, mood)
                if not os.path.isdir(directory):
                    continue
                all_paths.extend(
                    os.path.join(directory, name)
                    for name in os.listdir(directory)
                    if name.lower().endswith((".png", ".jpg", ".jpeg"))
                )
            if len(all_paths) < 3:
                raise GeneratorError(f"タロットカード素材が3枚未満しかありません: {len(all_paths)}枚")
            chosen = random.sample(all_paths, 3)
            return [(path, self._display_name_from_path(path)) for path in chosen]
        except Exception as exc:
            logger.exception("タロットカード3枚の選定中にエラーが発生しました")
            raise GeneratorError(str(exc)) from exc

    @staticmethod
    def _display_name_from_path(path: str) -> str:
        slug = os.path.splitext(os.path.basename(path))[0]
        return CARD_DISPLAY_NAMES.get(slug, slug)

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
            if name.lower().endswith((".png", ".jpg", ".jpeg"))
        ]
        if not candidates:
            raise GeneratorError(f"テンプレート素材が1枚も見つかりません: {directory}")
        return random.choice(candidates)
