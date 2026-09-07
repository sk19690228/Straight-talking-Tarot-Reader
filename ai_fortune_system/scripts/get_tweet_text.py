"""デバッグ用: 指定したツイートIDの本文を取得して表示する（読み取り専用、投稿なし）。

使い方（GitHub Actionsの「Get Tweet Text」ワークフロー、または手元で）:
    TWEET_ID=xxx python3 scripts/get_tweet_text.py
"""

import os

import tweepy


def main() -> None:
    tweet_id = os.environ["TWEET_ID"]

    client = tweepy.Client(
        bearer_token=os.getenv("X_BEARER_TOKEN"),
        consumer_key=os.getenv("X_API_KEY"),
        consumer_secret=os.getenv("X_API_SECRET"),
        access_token=os.getenv("X_ACCESS_TOKEN"),
        access_token_secret=os.getenv("X_ACCESS_TOKEN_SECRET"),
    )
    response = client.get_tweet(
        tweet_id,
        tweet_fields=["author_id", "created_at", "referenced_tweets", "conversation_id", "in_reply_to_user_id"],
        expansions=["author_id"],
        user_fields=["username"],
    )
    tweet = response.data
    users = (response.includes or {}).get("users") or []
    author = users[0].username if users else "?"
    print("author:", author)
    print("conversation_id:", tweet.conversation_id)
    print("in_reply_to_user_id:", tweet.in_reply_to_user_id)
    print("referenced_tweets:", tweet.referenced_tweets)
    print("text:")
    print(tweet.text)


if __name__ == "__main__":
    main()
