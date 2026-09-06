"""動作確認用: 指定したツイートへテキストのみのリプライを1件投稿する。

reply-check.pyの自動返信ロジックは自己リプライも鑑定対象にするため、動作確認したい
対象ポストへこのスクリプトでテスト用のリプライ（カード番号・生年月日・血液型・悩みを
含む文面）を投稿しておくと、次回のreply-check実行で実際に鑑定文が自動生成・返信
されるかを確認できる。

使い方（GitHub Actionsの「Post Test Reply」ワークフロー、または手元で）:
    TWEET_ID=xxx REPLY_TEXT="カード番号:16 1990年5月3日 A型 最近眠れません" \
        python3 scripts/post_test_reply.py
"""

import os

import tweepy


def main() -> None:
    tweet_id = os.environ["TWEET_ID"]
    text = os.environ["REPLY_TEXT"]

    client = tweepy.Client(
        bearer_token=os.getenv("X_BEARER_TOKEN"),
        consumer_key=os.getenv("X_API_KEY"),
        consumer_secret=os.getenv("X_API_SECRET"),
        access_token=os.getenv("X_ACCESS_TOKEN"),
        access_token_secret=os.getenv("X_ACCESS_TOKEN_SECRET"),
    )
    response = client.create_tweet(text=text, in_reply_to_tweet_id=tweet_id)
    print("投稿完了:", response.data)


if __name__ == "__main__":
    main()
