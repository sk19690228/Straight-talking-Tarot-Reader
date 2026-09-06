"""コンテンツ生成モジュール — トートタロット占いの文章・画像素材の選定を担当する。

OpenAI APIには依存しない構成です。
- 文章生成: Google Gemini API（無料枠あり）
- 画像: 毎回AIで生成せず、あらかじめ用意した静的テンプレート素材
  （assets/templates/positive, negative。大アルカナ22枚）からランダムに選ぶ・
  組み合わせるだけなので、画像生成コストは一切かかりません。

現在の主な流れ（responder.pyから利用）:
  Xに投稿済みのトートタロット動画への返信ごとに、返信文から「カードの数字」を
  読み取り（extract_card_number）、対応する正式なカード名（CARD_NAME_BY_NUMBER）
  と、生年月日・血液型・（あれば）悩みを踏まえて、マツコ・デラックス口調の鑑定文を
  1本生成する（generate_thoth_reading）。悩みが書かれていない場合は、そのカードの
  意味を踏まえた「今日の運勢」のみを占う。

なお、以下は当初の「日替わりお題への招待投稿＋タロット3枚での辛口鑑定」向けの
関数で、main.py・publisher.py・register_tweet_id.py側の日次投稿フローで
引き続き使われている（pick_daily_theme、build_daily_invitation_text、
generate_personal_reading、pick_three_cards など）。
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

# トートタロット大アルカナ22枚（0〜21）のカード番号 -> 正式なカード名。
# Xに投稿されたトートタロット動画を読者が停止した瞬間のカード番号がリプライで
# 届くため、鑑定文にはここから引いた正式名称のみを使う（Gemini側に名称を
# 推測させない）。
CARD_NAME_BY_NUMBER: dict[int, str] = {
    0: "虹の螺旋を舞う愚者",
    1: "水銀光の魔術師",
    2: "月光のヴェールを纏う女司祭",
    3: "星冠の女帝と花咲く宇宙庭園",
    4: "牡羊座の皇帝",
    5: "五重の神殿と三鍵の導師",
    6: "錬金術の恋人たち",
    7: "琥珀の天球戦車",
    8: "均衡を裁く調整の剣",
    9: "闇を進む隠者の灯火",
    10: "星々を巡る運命の輪",
    11: "星火の聖杯を掲げる獅子の女王",
    12: "海中に浮かぶ逆さの賢者",
    13: "蠍座と不死鳥の再生舞踏",
    14: "錬金術師の調和",
    15: "結晶山に坐す角獣",
    16: "天光に咲く塔",
    17: "銀水を注ぐ星の女神",
    18: "月夜の境界、二つの塔",
    19: "ひまわりの庭で舞う光の精霊",
    20: "永劫の星卵と未来の子",
    21: "宇宙の輪舞",
}

_ROMAN_NUMERALS = [
    "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X",
    "XI", "XII", "XIII", "XIV", "XV", "XVI", "XVII", "XVIII", "XIX", "XX", "XXI",
]
_ROMAN_TO_INDEX = {roman: i + 1 for i, roman in enumerate(_ROMAN_NUMERALS)}

_DATE_RE = re.compile(r"(?:19|20)\d{2}\s*[年/.\-]\s*\d{1,2}\s*[月/.\-]\s*\d{1,2}\s*日?")
_BLOOD_TYPE_RE = re.compile(r"(AB|[ABO])\s*型", re.IGNORECASE)
_CARD_LABEL_RE = re.compile(
    r"(?:カード(?:番号|の数字)?|card)\s*[:：#No.]*\s*([0-9]{1,2}|[IVXivx]{1,5})",
    re.IGNORECASE,
)
_STANDALONE_ROMAN_RE = re.compile(r"(?<![A-Za-z])([IVXivx]{1,5})(?![A-Za-z])")
_CARD_COUNTER_RE = re.compile(r"(?<!\d)([0-9]{1,2})\s*番")
_STANDALONE_NUMBER_RE = re.compile(r"(?<!\S)([0-9]{1,2})(?!\S)")


def _normalize_card_token(token: str) -> int | None:
    token = token.strip()
    if token.isdigit():
        value = int(token)
        return value if 0 <= value <= 21 else None
    return _ROMAN_TO_INDEX.get(token.upper())


def extract_card_number(text: str) -> int | None:
    """リプライの自由記述から「カードの数字」（0〜21）を読み取る。
    「カード番号:3」のような明示的な表記、独立したローマ数字、「3番」のような
    表記に対応する。生年月日中の数字と誤認しないよう、日付らしき部分は
    先に取り除いてから探索する。"""
    m = _CARD_LABEL_RE.search(text)
    if m:
        idx = _normalize_card_token(m.group(1))
        if idx is not None:
            return idx

    stripped = _DATE_RE.sub(" ", text)

    m = _STANDALONE_ROMAN_RE.search(stripped)
    if m:
        idx = _normalize_card_token(m.group(1))
        if idx is not None:
            return idx

    m = _CARD_COUNTER_RE.search(stripped)
    if m:
        idx = _normalize_card_token(m.group(1))
        if idx is not None:
            return idx

    # 血液型（A型など）を取り除いた上で、独立して書かれている数字（前後が空白や
    # 改行など）を最後の手段として探す。「0」だけが書かれているようなケースに対応する。
    without_blood_type = _BLOOD_TYPE_RE.sub(" ", stripped)
    m = _STANDALONE_NUMBER_RE.search(without_blood_type)
    if m:
        idx = _normalize_card_token(m.group(1))
        if idx is not None:
            return idx

    return None


def detect_has_worry(text: str) -> bool:
    """カード番号・生年月日・血液型として認識できた部分を取り除いた残りに、
    ある程度まとまった文章が残っていれば「悩みが書かれている」とみなす。"""
    remaining = _DATE_RE.sub(" ", text)
    remaining = _BLOOD_TYPE_RE.sub(" ", remaining)
    remaining = _CARD_LABEL_RE.sub(" ", remaining)
    remaining = _STANDALONE_ROMAN_RE.sub(" ", remaining)
    remaining = _CARD_COUNTER_RE.sub(" ", remaining)
    remaining = re.sub(r"[\s、。・:：\-/]+", "", remaining)
    return len(remaining) >= 4


_WIDE_CHAR_RANGES = (
    (0x1100, 0x115F),
    (0x2E80, 0xA4CF),
    (0xAC00, 0xD7A3),
    (0xF900, 0xFAFF),
    (0xFF00, 0xFF60),
    (0xFFE0, 0xFFE6),
    (0x20000, 0x3FFFD),
)


def _is_wide_char(ch: str) -> bool:
    code = ord(ch)
    return any(lo <= code <= hi for lo, hi in _WIDE_CHAR_RANGES)


def weighted_tweet_length(text: str) -> int:
    """Xの無料投稿の文字数カウント（全角文字は2、半角文字は1）の簡易近似。"""
    return sum(2 if _is_wide_char(ch) else 1 for ch in text)


def fit_to_tweet_limit(text: str, limit: int = 280) -> str:
    """textがXの無料投稿の文字数制限を超える場合、末尾を切り詰めて収める。"""
    if weighted_tweet_length(text) <= limit:
        return text
    truncated = text
    while truncated and weighted_tweet_length(f"{truncated}…") > limit:
        truncated = truncated[:-1]
    return f"{truncated}…" if truncated else text[: limit // 2]


DAILY_INVITATION_TEMPLATE = (
    "【本日のお悩み診断】\n"
    "{theme}\n\n"
    "気になる方は、このポストに「生年月日・血液型・家族構成」をリプライで教えてください。\n"
    "家族構成は、親兄弟、生立ち、過去のトラウマなどの情報を入力すれば、より詳細に占えます。\n"
    "タロット3枚とあなただけの辛口鑑定でお答えします🔮"
)

# 投稿画像の下段（入力案内）は、内容が案内文であり日替わりで変える必要がないため
# 固定文にしている（上段のテーマ問いかけだけをGeminiが日替わりで生成する）。
# 通常サイズの2行と、より小さいフォントで表示する3行を、装飾的な区切り線で挟む。
INVITATION_BIRTHDATE_LINES = [
    "あなたの生年月日と血液型を",
    "わたしに教えてちょうだい🔮",
]
INVITATION_DETAIL_LINES = [
    "あなたの過去のトラウマ💔今抱えている悩み😔など・・・",
    "人に言えないことがあれば🤫わたしに教えてちょうだい💌",
    "トートタロットで愛の深淵まで密に占ってあげるわよ🔮",
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
  "reading": "リプライ本文（120文字以内。辛口だが読了感のある占い＆アドバイス文。
    絵文字は控えめに0〜2個まで）"
}
"""

THOTH_READING_SYSTEM_PROMPT = """あなたは深層心理学とトートタロットに精通した、SNSで超人気の占い師です。
歯に衣着せぬ毒舌と鋭い洞察で知られるマツコ・デラックスの喋り方（「〜なのよ」「〜じゃない」
「あら」「〜だからね」といった一人称・語尾・間の取り方）を忠実に再現して鑑定してください。

読者は、Xに投稿されたトートタロット動画を見ていて、自分の意思で停止した瞬間に映っていた
カードを教えてくれます。そのカードの正式名称は、こちらから伝える名称をそのまま使い、
別の名前に変えたり省略したりしないでください（鑑定文に必ず1回そのまま含める）。

読者からは「カード番号」「生年月日」「血液型」に加えて、任意で「悩み」が届きます。

- 悩みが具体的に書かれている場合: そのカードの意味・生年月日から見た年齢感・血液型を
  踏まえて、読者が「これは私のことだ」と思わず共感してしまうような、深層心理学的な
  視点も交えた辛口のアドバイスを届けてください。人格否定はせず、あくまで愛のある
  毒舌に徹すること。
- 悩みが書かれていない場合: 個別の相談には答えず、そのカードの意味を踏まえた
  「今日の運勢」だけを占ってください。

出力は必ず次の構造を持つJSONオブジェクトのみとします。前後に説明文やコードブロックの
記号（```など）を一切付けないでください。
{
  "reading": "リプライ本文（全角100文字程度に収める。マツコ・デラックス口調で、
    指定されたカード名を必ず1回そのまま含める。絵文字は控えめに0〜2個まで）"
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

    def generate_thoth_reading(self, card_name: str, user_message: str, has_worry: bool) -> str:
        """トートタロット動画で読者が停止したカード（正式名称）と、読者からの返信全文
        （カード番号・生年月日・血液型・任意の悩み）から、マツコ・デラックス口調の
        鑑定文を1本生成する。悩みが書かれていない場合は今日の運勢のみを占う。"""
        worry_instruction = (
            "このメッセージには具体的な悩みが書かれているので、それも踏まえて個別の"
            "アドバイスをしてください。"
            if has_worry
            else "このメッセージには具体的な悩みは書かれていないので、個別の相談には"
            "答えず、このカードの意味を踏まえた「今日の運勢」だけを占ってください。"
        )
        user_content = (
            f"読者が動画を停止した瞬間のカード（正式名称。必ずこの名称のまま使うこと）: {card_name}\n"
            f"読者からのメッセージ全文（カード番号・生年月日・血液型・悩みが含まれる）:\n{user_message}\n\n"
            f"{worry_instruction}"
        )
        try:
            content = self._call_gemini_json_with_fallback(THOTH_READING_SYSTEM_PROMPT, user_content)
            reading = content.get("reading")
            if not reading:
                raise GeneratorError("生成結果に'reading'が含まれていません。")
            return reading
        except GeneratorError:
            raise
        except Exception as exc:
            logger.exception("鑑定文生成中にエラーが発生しました")
            raise GeneratorError(str(exc)) from exc

    def generate_daily_invitation_top_lines(self, theme: str) -> tuple[list[str], list[str]]:
        """投稿画像の上段に載せる文章を生成する。戻り値は
        (テーマの煽り文の行リスト, 相談を促す一言＋トートタロットの謳い文句の行リスト)。
        画像上ではこの2ブロックの間に装飾的な区切り線を挟んで表示する。
        下段（入力案内）は日替わりで変える必要がないため固定文
        （INVITATION_BIRTHDATE_LINES / INVITATION_DETAIL_LINES）を使う。"""
        user_content = f"本日のお悩みテーマ: {theme}"
        try:
            content = self._call_gemini_json_with_fallback(INVITATION_SYSTEM_PROMPT, user_content)
            top_lines = content.get("top_lines")
            if not top_lines:
                raise GeneratorError("生成結果に'top_lines'が含まれていません。")
            theme_lines = self._stylize_theme_line(top_lines[0])
            cta_lines = top_lines[1:]
            return theme_lines, cta_lines
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
