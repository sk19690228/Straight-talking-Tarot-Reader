"""Xのメンション監視・A/Bリプライ自動検知＆辛口自動返信ロジック。"""

import json
import logging
import os
import re

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


def save_daily_state(tweet_id: str, content: dict, theme: str) -> None:
    """当日の投稿内容（選択肢A/Bの鑑定結果）をリプライ照合用に保存する。"""
    os.makedirs(STATE_DIR, exist_ok=True)
    data = {
        "tweet_id": tweet_id,
        "theme": theme,
        "option_a_label": content.get("option_a_label"),
        "option_b_label": content.get("option_b_label"),
        "option_a_result": content.get("option_a_result"),
        "option_b_result": content.get("option_b_result"),
    }
    with open(DAILY_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


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

    def _build_reply_text(self, username: str, answer: str, daily_state: dict) -> str:
        is_a = answer.upper() == "A"
        label = daily_state["option_a_label"] if is_a else daily_state["option_b_label"]
        result = daily_state["option_a_result"] if is_a else daily_state["option_b_result"]
        return f"@{username} 「{label}」を選んだあなたへ。\n{result}"

    def check_and_respond(self) -> None:
        """メンションを確認し、A/Bの回答リプライにのみ辛口鑑定結果で自動返信する。"""
        daily_state = _load_json(DAILY_STATE_PATH)
        if not daily_state:
            logger.info("本日の鑑定データが未登録のため、リプライ確認をスキップします。")
            return

        since_id = (_load_json(SINCE_ID_PATH) or {}).get("since_id")

        try:
            me = self._client.get_me().data
        except Exception:
            logger.exception("Xの認証ユーザー情報取得に失敗しました")
            return

        try:
            mentions = self._client.get_users_mentions(
                id=me.id,
                since_id=since_id,
                tweet_fields=["referenced_tweets", "author_id"],
                expansions=["author_id"],
                user_fields=["username"],
            )
        except Exception:
            logger.exception("メンション取得に失敗しました")
            return

        if not mentions.data:
            return

        users_by_id = {u.id: u for u in (mentions.includes.get("users", []) if mentions.includes else [])}
        latest_processed_id = since_id

        for mention in reversed(mentions.data):
            latest_processed_id = mention.id
            referenced = mention.referenced_tweets or []
            is_reply_to_daily_tweet = any(
                ref.type == "replied_to" and str(ref.id) == str(daily_state["tweet_id"]) for ref in referenced
            )
            if not is_reply_to_daily_tweet:
                continue

            match = ANSWER_PATTERN.match(mention.text or "")
            if not match:
                continue

            answer = match.group(1).upper()
            username = users_by_id.get(mention.author_id).username if mention.author_id in users_by_id else "あなた"

            try:
                reply_text = self._build_reply_text(username, answer, daily_state)
                self._client.create_tweet(text=reply_text, in_reply_to_tweet_id=mention.id)
                logger.info("リプライ自動返信に成功しました: mention_id=%s", mention.id)
            except Exception:
                logger.exception("リプライ自動返信に失敗しました: mention_id=%s", mention.id)

        if latest_processed_id:
            _save_since_id(latest_processed_id)
