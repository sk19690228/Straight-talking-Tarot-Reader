"""Xへ手動投稿した後、そのツイートIDを本日の鑑定データに登録するスクリプト。

使い方: python3 register_tweet_id.py <ツイートID>

登録すると、main.pyのリプライ確認ジョブ（run_reply_check_job）が
そのツイートへのA/Bリプライを検知して自動返信できるようになる。
"""

import sys

from dotenv import load_dotenv

from responder import ResponderError, update_tweet_id

load_dotenv()


def main() -> None:
    if len(sys.argv) != 2:
        print("使い方: python3 register_tweet_id.py <ツイートID>")
        sys.exit(1)

    tweet_id = sys.argv[1]
    try:
        update_tweet_id(tweet_id)
        print(f"ツイートID {tweet_id} を登録しました。リプライの自動応答が有効になります。")
    except ResponderError as exc:
        print(f"エラー: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
