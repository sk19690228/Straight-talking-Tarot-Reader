"""Xの返信監視・個別タロット鑑定の自動返信ロジック。

流れ:
  当日の投稿（テーマ確認＋生年月日・血液型・家族構成の入力依頼）への直接リプライを
  検知するたびに、タロットカード3枚をランダムに選んで1枚の画像に合成し、
  返信内容（生年月日・血液型・家族構成など自由記述）とお悩みテーマを踏まえた
  個別の辛口鑑定文を生成して、画像付きで返信する。
"""

import base64
import json
import logging
import os
import tempfile

import tweepy

from generator import ContentGenerator, GeneratorError
from image_processor import ImageProcessorError, compose_three_card_image

logger = logging.getLogger(__name__)

STATE_DIR = os.path.join(os.path.dirname(__file__), "state")
DAILY_STATE_PATH = os.path.join(STATE_DIR, "daily_fortune.json")
SINCE_ID_PATH = os.path.join(STATE_DIR, "since_id.json")
LAST_READING_PATH = os.path.join(STATE_DIR, "last_reading.json")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")


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
    image_bytes: bytes,
) -> None:
    """直近1件分の個別鑑定結果（画像込み）を保存する。GitHub Actions Artifactsを
    経由しなくても、コミット済みのこの状態ファイルから直接画像を取り出せるように
    するため（リポジトリの肥大化を避けるため、保持するのは直近1件のみ）。"""
    os.makedirs(STATE_DIR, exist_ok=True)
    data = {
        "reply_tweet_id": reply_tweet_id,
        "username": username,
        "user_message": user_message,
        "card_names": card_names,
        "reading_text": reading_text,
        "image_b64": base64.b64encode(image_bytes).decode("ascii"),
    }
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
        """当日の投稿への直接リプライを確認し、タロット3枚＋辛口鑑定文で自動返信する。"""
        daily_state = _load_json(DAILY_STATE_PATH)
        if not daily_state:
            logger.info("本日の鑑定データが未登録のため、リプライ確認をスキップします。")
            return
        if not daily_state.get("tweet_id"):
            logger.info(
                "本日のツイートIDが未登録のため、リプライ確認をスキップします。"
                "手動投稿後に register_tweet_id.py でツイートIDを登録してください。"
            )
            return

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
        # 本文だけの返信は上記だけでは検知できない。そのため、当日の投稿の
        # conversation_id配下の返信を直接検索して補完する。
        # ※投稿アカウント自身が動作確認のためにリプライするケース(自己リプライ)も
        # 拾えるよう、投稿者での除外はしない。bot自身の自動返信はmentionへの
        # リプライであり当日の投稿への直接リプライにはならないため、下の
        # daily_state["tweet_id"]チェックで自然に除外される。
        try:
            conversation = self._client.search_recent_tweets(
                query=f"conversation_id:{daily_state['tweet_id']}",
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
            if str(daily_state["tweet_id"]) not in replied_to_ids:
                # 当日の投稿への直接リプライのみを鑑定対象にする
                # （bot自身の返信へのさらなる返信などは対象外）。
                latest_processed_id = mention.id
                continue

            user_message = (mention.text or "").strip()
            if not user_message:
                latest_processed_id = mention.id
                continue

            username = users_by_id[mention.author_id].username if mention.author_id in users_by_id else "あなた"

            try:
                cards = self._generator.pick_three_cards()
                card_paths = [path for path, _name in cards]
                card_names = [name for _path, name in cards]
                image_path = compose_three_card_image(card_paths, OUTPUT_DIR)
                reading_text = self._generator.generate_personal_reading(
                    daily_state["theme"], user_message, card_names
                )
                reply_text = f"@{username} {reading_text}"

                with open(image_path, "rb") as f:
                    image_bytes = f.read()

                self._post_reply(mention.id, reply_text, image_bytes)
                _save_last_reading(mention.id, username, user_message, card_names, reading_text, image_bytes)
                latest_processed_id = mention.id
                logger.info("個別鑑定の自動返信に成功しました: mention_id=%s", mention.id)
            except (GeneratorError, ImageProcessorError):
                # since_idを進めないことで、次回実行時にこのリプライを再試行する。
                logger.exception("個別鑑定の生成に失敗しました: mention_id=%s", mention.id)
                break
            except Exception:
                # since_idを進めないことで、次回実行時にこのリプライを再試行する。
                logger.exception("個別鑑定の自動返信に失敗しました: mention_id=%s", mention.id)
                break

        if latest_processed_id:
            _save_since_id(latest_processed_id)
