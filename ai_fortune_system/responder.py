"""Xの返信監視・個別タロット鑑定の自動返信ロジック。

流れ:
  固定のポスト（TARGET_TWEET_ID。Xに投稿済みのトートタロット動画）への直接リプライを
  検知するたびに、返信文から「カードの数字」を読み取り、対応する正式なカード名と
  生年月日・血液型・（あれば）悩みを踏まえて、マツコ・デラックス口調の鑑定文を
  生成し、テキストのみで返信する。悩みが書かれていない場合は、そのカードの意味を
  踏まえた「今日の運勢」のみを返信する。
"""

import base64
import json
import logging
import os
import tempfile

import tweepy

from generator import (
    CARD_NAME_BY_NUMBER,
    ContentGenerator,
    GeneratorError,
    detect_has_worry,
    extract_card_number,
    extract_out_of_range_card_number,
    fit_to_tweet_limit,
)

logger = logging.getLogger(__name__)

# カードの数字らしき数字が書かれていたものの0〜21の範囲外だった場合に送る案内文。
OUT_OF_RANGE_CARD_NUMBER_MESSAGE = "カード番号は0〜21の数字で答えてちょうだい💋"

STATE_DIR = os.path.join(os.path.dirname(__file__), "state")
DAILY_STATE_PATH = os.path.join(STATE_DIR, "daily_fortune.json")
SINCE_ID_PATH = os.path.join(STATE_DIR, "since_id.json")
LAST_READING_PATH = os.path.join(STATE_DIR, "last_reading.json")

# 監視・自動返信の対象ポスト（Xに投稿済みのトートタロット動画）のツイートID。
# 環境変数 TARGET_TWEET_ID で上書き可能。
TARGET_TWEET_ID = os.getenv("TARGET_TWEET_ID", "2096687017807778098")


class ResponderError(Exception):
    """リプライ監視・自動返信処理に関するエラー。"""


def save_daily_state(tweet_id: str | None, theme: str, post_text: str, cover_image_bytes: bytes) -> None:
    """当日のお悩みテーマ・投稿文・表紙画像を保存する。

    cover_image_bytesは、GitHub Actionsの実行ログ・Artifactsを経由しなくても、
    リポジトリにコミットされたこの状態ファイルから直接デコードして画像を
    取り出せるようにするために保存する。
    """
    os.makedirs(STATE_DIR, exist_ok=True)
    data = {
        "tweet_id": tweet_id,
        "theme": theme,
        "post_text": post_text,
        "cover_image_b64": base64.b64encode(cover_image_bytes).decode("ascii"),
    }
    with open(DAILY_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def update_tweet_id(tweet_id: str) -> None:
    """手動でXに投稿した後、そのツイートIDを本日の鑑定データに登録する。"""
    daily_state = _load_json(DAILY_STATE_PATH)
    if not daily_state:
        raise ResponderError("本日の鑑定データが見つかりません。先にコンテンツを生成してください。")
    daily_state["tweet_id"] = tweet_id
    with open(DAILY_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(daily_state, f, ensure_ascii=False, indent=2)


def _load_json(path: str) -> dict | None:
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save_since_id(since_id: str) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(SINCE_ID_PATH, "w", encoding="utf-8") as f:
        json.dump({"since_id": since_id}, f)


def _save_last_reading(
    reply_tweet_id: str,
    username: str,
    user_message: str,
    card_names: list[str],
    reading_text: str,
    image_bytes: bytes | None = None,
) -> None:
    """直近1件分の個別鑑定結果を保存する（テキストのみの返信のため、通常は画像なし）。
    GitHub Actions Artifactsを経由しなくても、コミット済みのこの状態ファイルから
    直接内容を確認できるようにするため（リポジトリの肥大化を避けるため、保持するのは
    直近1件のみ）。"""
    os.makedirs(STATE_DIR, exist_ok=True)
    data = {
        "reply_tweet_id": reply_tweet_id,
        "username": username,
        "user_message": user_message,
        "card_names": card_names,
        "reading_text": reading_text,
    }
    if image_bytes is not None:
        data["image_b64"] = base64.b64encode(image_bytes).decode("ascii")
    with open(LAST_READING_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


class ReplyResponder:
    def __init__(self):
        self._client = tweepy.Client(
            bearer_token=os.getenv("X_BEARER_TOKEN"),
            consumer_key=os.getenv("X_API_KEY"),
            consumer_secret=os.getenv("X_API_SECRET"),
            access_token=os.getenv("X_ACCESS_TOKEN"),
            access_token_secret=os.getenv("X_ACCESS_TOKEN_SECRET"),
        )
        self._generator = ContentGenerator()

    def _post_reply(self, in_reply_to_id: str, text: str, image_bytes: bytes | None = None) -> str | None:
        """テキスト（＋任意で画像）をリプライとして投稿し、新しいツイートIDを返す。"""
        media_ids = None
        if image_bytes is not None:
            auth = tweepy.OAuth1UserHandler(
                os.getenv("X_API_KEY"),
                os.getenv("X_API_SECRET"),
                os.getenv("X_ACCESS_TOKEN"),
                os.getenv("X_ACCESS_TOKEN_SECRET"),
            )
            api_v1 = tweepy.API(auth)
            with tempfile.NamedTemporaryFile(suffix=".png") as tmp_file:
                tmp_file.write(image_bytes)
                tmp_file.flush()
                media = api_v1.media_upload(filename=tmp_file.name)
                media_ids = [media.media_id]

        response = self._client.create_tweet(text=text, in_reply_to_tweet_id=in_reply_to_id, media_ids=media_ids)
        return response.data["id"]

    def check_and_respond(self) -> None:
        """TARGET_TWEET_ID（トートタロット動画のポスト）への直接リプライを確認し、
        カード番号・生年月日・血液型・（あれば）悩みを踏まえた個別鑑定を自動返信する。"""
        since_id = (_load_json(SINCE_ID_PATH) or {}).get("since_id")

        try:
            me = self._client.get_me().data
        except Exception:
            logger.exception("Xの認証ユーザー情報取得に失敗しました")
            return

        replies_by_id: dict = {}
        users_by_id: dict = {}

        try:
            mentions = self._client.get_users_mentions(
                id=me.id,
                since_id=since_id,
                tweet_fields=["referenced_tweets", "author_id"],
                expansions=["author_id"],
                user_fields=["username"],
            )
            for tweet in mentions.data or []:
                replies_by_id[tweet.id] = tweet
            for user in (mentions.includes or {}).get("users", []):
                users_by_id[user.id] = user
        except Exception:
            logger.exception("メンション取得に失敗しました")

        # get_users_mentions は本文中に「@ユーザー名」が明示的に含まれるツイートしか
        # 拾えない。Xの返信UIは現在、本文に@メンションを自動挿入しないため、
        # 本文だけの返信は上記だけでは検知できない。そのため、対象ポストの
        # conversation_id配下の返信を直接検索して補完する。
        # ※投稿アカウント自身が動作確認のためにリプライするケース(自己リプライ)も
        # 拾えるよう、投稿者での除外はしない。bot自身の自動返信はmentionへの
        # リプライであり対象ポストへの直接リプライにはならないため、下の
        # TARGET_TWEET_IDチェックで自然に除外される。
        try:
            conversation = self._client.search_recent_tweets(
                query=f"conversation_id:{TARGET_TWEET_ID}",
                since_id=since_id,
                tweet_fields=["referenced_tweets", "author_id"],
                expansions=["author_id"],
                user_fields=["username"],
                max_results=100,
            )
            for tweet in conversation.data or []:
                replies_by_id[tweet.id] = tweet
            for user in (conversation.includes or {}).get("users", []):
                users_by_id[user.id] = user
        except Exception:
            logger.warning(
                "会話スレッドの検索に失敗しました(X APIのアクセス権限不足の可能性があります)。"
                "@メンション付きの返信のみで検知を継続します。",
                exc_info=True,
            )

        if not replies_by_id:
            return

        mention_list = sorted(replies_by_id.values(), key=lambda t: int(t.id))
        latest_processed_id = since_id

        for mention in mention_list:
            referenced = mention.referenced_tweets or []
            replied_to_ids = {str(ref.id) for ref in referenced if ref.type == "replied_to"}
            if TARGET_TWEET_ID not in replied_to_ids:
                # 対象ポストへの直接リプライのみを鑑定対象にする
                # （bot自身の返信へのさらなる返信などは対象外）。
                latest_processed_id = mention.id
                continue

            user_message = (mention.text or "").strip()
            if not user_message:
                latest_processed_id = mention.id
                continue

            username = users_by_id[mention.author_id].username if mention.author_id in users_by_id else "あなた"

            card_index = extract_card_number(user_message)
            if card_index is None:
                out_of_range_number = extract_out_of_range_card_number(user_message)
                if out_of_range_number is not None:
                    try:
                        reply_text = fit_to_tweet_limit(OUT_OF_RANGE_CARD_NUMBER_MESSAGE)
                        self._post_reply(mention.id, reply_text)
                        latest_processed_id = mention.id
                        logger.info(
                            "カード番号が範囲外(%s)だったため案内を返信しました: mention_id=%s",
                            out_of_range_number,
                            mention.id,
                        )
                    except Exception:
                        # since_idを進めないことで、次回実行時にこのリプライを再試行する。
                        logger.exception("範囲外案内の返信に失敗しました: mention_id=%s", mention.id)
                        break
                    continue

                logger.warning(
                    "リプライからカードの数字を読み取れなかったためスキップします: mention_id=%s",
                    mention.id,
                )
                latest_processed_id = mention.id
                continue

            card_name = CARD_NAME_BY_NUMBER[card_index]
            has_worry = detect_has_worry(user_message)

            try:
                reading_text = self._generator.generate_thoth_reading(card_name, user_message, has_worry)
                reply_text = fit_to_tweet_limit(reading_text)

                self._post_reply(mention.id, reply_text)
                _save_last_reading(mention.id, username, user_message, [card_name], reading_text)
                latest_processed_id = mention.id
                logger.info("個別鑑定の自動返信に成功しました: mention_id=%s", mention.id)
            except GeneratorError:
                # since_idを進めないことで、次回実行時にこのリプライを再試行する。
                logger.exception("個別鑑定の生成に失敗しました: mention_id=%s", mention.id)
                break
            except Exception:
                # since_idを進めないことで、次回実行時にこのリプライを再試行する。
                logger.exception("個別鑑定の自動返信に失敗しました: mention_id=%s", mention.id)
                break

        if latest_processed_id:
            _save_since_id(latest_processed_id)
