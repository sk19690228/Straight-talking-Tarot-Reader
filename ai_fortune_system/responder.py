"""Xのメンション監視・2段階分岐（Q1→Q2→最終診断）の自動返信ロジック。

流れ:
  Q1（当日の投稿）へ A/B で返信
    -> Q2-A または Q2-B を画像付きでリプライ（この時点でθ/δ or η/φのどちらかに
       進んでいるが、読者への指示は常に「A」「B」の1文字）
  そのQ2への返信 A/B
    -> 4パターン（A→θ, A→δ, B→η, B→φ）のいずれかの最終診断をリプライ
"""

import base64
import json
import logging
import os
import re
import tempfile

import tweepy

logger = logging.getLogger(__name__)

STATE_DIR = os.path.join(os.path.dirname(__file__), "state")
DAILY_STATE_PATH = os.path.join(STATE_DIR, "daily_fortune.json")
SINCE_ID_PATH = os.path.join(STATE_DIR, "since_id.json")

# 全角/半角・大文字小文字を問わず「A」「B」単体の返信のみを回答として扱う。
# Xはリプライ時に "@元ツイート主 " を本文の先頭に自動付与するため、
# 先頭の@メンション（複数可）は許容しつつ、それ以外の文字が混じる場合は除外する。
ANSWER_PATTERN = re.compile(r"^\s*(?:[@＠][^\s@＠]+\s+)*([AaＡａ]|[BbＢｂ])\s*$")


class ResponderError(Exception):
    """リプライ監視・自動返信処理に関するエラー。"""


def save_daily_state(
    tweet_id: str | None,
    content: dict,
    theme: str,
    level2_a_image_bytes: bytes,
    level2_b_image_bytes: bytes,
) -> None:
    """当日の分岐コンテンツ一式（Q1/Q2/最終診断・Q2用画像）を保存する。"""
    os.makedirs(STATE_DIR, exist_ok=True)
    data = {
        "tweet_id": tweet_id,
        "theme": theme,
        "level1": content["level1"],
        "level2_a": content["level2_a"],
        "level2_b": content["level2_b"],
        "results": content["results"],
        "level2_a_image_b64": base64.b64encode(level2_a_image_bytes).decode("ascii"),
        "level2_b_image_b64": base64.b64encode(level2_b_image_bytes).decode("ascii"),
        "level2_threads": {},
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


class ReplyResponder:
    def __init__(self):
        self._client = tweepy.Client(
            bearer_token=os.getenv("X_BEARER_TOKEN"),
            consumer_key=os.getenv("X_API_KEY"),
            consumer_secret=os.getenv("X_API_SECRET"),
            access_token=os.getenv("X_ACCESS_TOKEN"),
            access_token_secret=os.getenv("X_ACCESS_TOKEN_SECRET"),
        )

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

    def _build_level2_reply_text(self, username: str, question: str) -> str:
        return f"@{username} {question}"

    def _build_final_reply_text(self, username: str, result: str) -> str:
        return f"@{username} {result}"

    def check_and_respond(self) -> None:
        """メンションを確認し、Q1→Q2→最終診断の2段階分岐で自動返信する。"""
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
        # 「A」とだけ書かれたような返信は上記だけでは検知できない。そのため、
        # 当日の投稿(Q1)のconversation_id配下の返信を直接検索して補完する
        # (Q1→Q2→最終診断は同じ返信スレッドなので、1回の検索で両方拾える)。
        try:
            conversation = self._client.search_recent_tweets(
                query=f"conversation_id:{daily_state['tweet_id']} -from:{me.username}",
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
        level2_threads: dict = daily_state.get("level2_threads", {})
        state_changed = False
        latest_processed_id = since_id

        for mention in mention_list:
            latest_processed_id = mention.id

            match = ANSWER_PATTERN.match(mention.text or "")
            if not match:
                continue
            answer = match.group(1).upper()

            referenced = mention.referenced_tweets or []
            replied_to_ids = {str(ref.id) for ref in referenced if ref.type == "replied_to"}
            username = users_by_id.get(mention.author_id).username if mention.author_id in users_by_id else "あなた"

            if str(daily_state["tweet_id"]) in replied_to_ids:
                # Q1への回答 -> Q2-A または Q2-B を画像付きで返信
                branch = "A" if answer == "A" else "B"
                level2 = daily_state["level2_a"] if branch == "A" else daily_state["level2_b"]
                image_b64 = daily_state["level2_a_image_b64"] if branch == "A" else daily_state["level2_b_image_b64"]
                try:
                    reply_text = self._build_level2_reply_text(username, level2["question"])
                    new_tweet_id = self._post_reply(mention.id, reply_text, base64.b64decode(image_b64))
                    if new_tweet_id:
                        level2_threads[new_tweet_id] = branch
                        state_changed = True
                    logger.info("Q2への自動返信に成功しました: mention_id=%s branch=%s", mention.id, branch)
                except Exception:
                    logger.exception("Q2への自動返信に失敗しました: mention_id=%s", mention.id)
                continue

            matched_branch = next((level2_threads[ref_id] for ref_id in replied_to_ids if ref_id in level2_threads), None)
            if matched_branch is None:
                continue

            # Q2への回答 -> 4パターンの最終診断を返信
            if matched_branch == "A":
                result_key = "a_theta" if answer == "A" else "a_delta"
            else:
                result_key = "b_eta" if answer == "A" else "b_phi"

            try:
                reply_text = self._build_final_reply_text(username, daily_state["results"][result_key])
                self._post_reply(mention.id, reply_text)
                logger.info("最終診断の自動返信に成功しました: mention_id=%s result=%s", mention.id, result_key)
            except Exception:
                logger.exception("最終診断の自動返信に失敗しました: mention_id=%s", mention.id)

        if state_changed:
            daily_state["level2_threads"] = level2_threads
            with open(DAILY_STATE_PATH, "w", encoding="utf-8") as f:
                json.dump(daily_state, f, ensure_ascii=False, indent=2)

        if latest_processed_id:
            _save_since_id(latest_processed_id)
