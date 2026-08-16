"""X / Instagram / Threads への配信ロジック。

Instagram Graph API・Threads APIはローカルファイルの直接アップロードに対応しておらず、
公開URL経由で画像を参照する必要がある。そのため画像は事前に公開URL
（PUBLIC_IMAGE_BASE_URL + ファイル名）で参照可能な場所に配置されている前提とする。
"""

import logging
import os
import time

import requests
import tweepy

logger = logging.getLogger(__name__)

GRAPH_API_VERSION = "v19.0"
THREADS_API_VERSION = "v1.0"
PUBLISH_INTERVAL_SECONDS = 3  # 各プラットフォームへの連続リクエストを避けるためのインターバル


class SNSPublisher:
    def __init__(self):
        self.public_image_base_url = os.getenv("PUBLIC_IMAGE_BASE_URL", "")

    # ------------------------------------------------------------------
    # X (Twitter)
    # ------------------------------------------------------------------
    def post_to_x(self, image_path: str, text: str) -> str | None:
        """画像付きツイートを投稿し、ツイートIDを返す。"""
        try:
            api_key = os.getenv("X_API_KEY")
            api_secret = os.getenv("X_API_SECRET")
            access_token = os.getenv("X_ACCESS_TOKEN")
            access_token_secret = os.getenv("X_ACCESS_TOKEN_SECRET")

            auth = tweepy.OAuth1UserHandler(api_key, api_secret, access_token, access_token_secret)
            api_v1 = tweepy.API(auth)
            media = api_v1.media_upload(filename=image_path)

            client = tweepy.Client(
                consumer_key=api_key,
                consumer_secret=api_secret,
                access_token=access_token,
                access_token_secret=access_token_secret,
            )
            response = client.create_tweet(text=text, media_ids=[media.media_id])
            tweet_id = response.data["id"]
            logger.info("Xへの投稿に成功しました: tweet_id=%s", tweet_id)
            return tweet_id
        except Exception:
            logger.exception("Xへの投稿に失敗しました")
            return None

    # ------------------------------------------------------------------
    # Instagram Graph API
    # ------------------------------------------------------------------
    def post_to_instagram(self, image_filename: str, text: str) -> str | None:
        try:
            access_token = os.getenv("IG_ACCESS_TOKEN")
            ig_user_id = os.getenv("IG_BUSINESS_ACCOUNT_ID")
            image_url = self._build_public_url(image_filename)
            base_url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{ig_user_id}"

            container = requests.post(
                f"{base_url}/media",
                data={"image_url": image_url, "caption": text, "access_token": access_token},
                timeout=30,
            )
            container.raise_for_status()
            creation_id = container.json()["id"]

            publish = requests.post(
                f"{base_url}/media_publish",
                data={"creation_id": creation_id, "access_token": access_token},
                timeout=30,
            )
            publish.raise_for_status()
            media_id = publish.json()["id"]
            logger.info("Instagramへの投稿に成功しました: media_id=%s", media_id)
            return media_id
        except Exception:
            logger.exception("Instagramへの投稿に失敗しました")
            return None

    # ------------------------------------------------------------------
    # Threads API
    # ------------------------------------------------------------------
    def post_to_threads(self, image_filename: str, text: str) -> str | None:
        try:
            access_token = os.getenv("THREADS_ACCESS_TOKEN")
            threads_user_id = os.getenv("THREADS_USER_ID")
            image_url = self._build_public_url(image_filename)
            base_url = f"https://graph.threads.net/{THREADS_API_VERSION}/{threads_user_id}"

            container = requests.post(
                f"{base_url}/threads",
                data={
                    "media_type": "IMAGE",
                    "image_url": image_url,
                    "text": text,
                    "access_token": access_token,
                },
                timeout=30,
            )
            container.raise_for_status()
            creation_id = container.json()["id"]

            publish = requests.post(
                f"{base_url}/threads_publish",
                data={"creation_id": creation_id, "access_token": access_token},
                timeout=30,
            )
            publish.raise_for_status()
            post_id = publish.json()["id"]
            logger.info("Threadsへの投稿に成功しました: post_id=%s", post_id)
            return post_id
        except Exception:
            logger.exception("Threadsへの投稿に失敗しました")
            return None

    # ------------------------------------------------------------------
    def publish_all(self, image_path: str, text: str, post_to_x: bool = True) -> dict:
        """X・Instagram・Threadsへ順に配信する。1プラットフォームの失敗が他へ波及しないようにする。

        post_to_x=Falseの場合、Xへの自動投稿はスキップする（手動投稿運用向け）。
        """
        image_filename = os.path.basename(image_path)
        results = {}

        if post_to_x:
            results["x_tweet_id"] = self.post_to_x(image_path, text)
            time.sleep(PUBLISH_INTERVAL_SECONDS)
        else:
            results["x_tweet_id"] = None

        results["instagram_media_id"] = self.post_to_instagram(image_filename, text)
        time.sleep(PUBLISH_INTERVAL_SECONDS)

        results["threads_post_id"] = self.post_to_threads(image_filename, text)

        return results

    def _build_public_url(self, image_filename: str) -> str:
        if not self.public_image_base_url:
            raise ValueError(
                "PUBLIC_IMAGE_BASE_URL が未設定です。Instagram/Threads APIは"
                "公開URL経由でしか画像を参照できません。"
            )
        return f"{self.public_image_base_url.rstrip('/')}/{image_filename}"
