# Straight-talking Tarot Reader

生成AIとSNS APIを活用し、30〜40代女性向けの辛口タロット占いコンテンツ
（マツコ×ひろゆき風）を自動生成・画像合成し、X・Instagram・Threadsへ
自動配信・リプライ対応するシステムです。

## ディレクトリ構成

```
ai_fortune_system/
├── main.py              # メインの実行ファイル・スケジューラー
├── generator.py          # OpenAI API連携（文章・画像生成）
├── image_processor.py    # Pillowによるテキスト合成処理
├── publisher.py           # 各SNS（X, Instagram, Threads）への配信ロジック
├── responder.py            # リプライ検知・自動返信ロジック
├── fonts/                    # 日本語フォント（同梱、環境依存の文字化け防止）
└── requirements.txt
```

## セットアップ

```bash
cd ai_fortune_system
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # 各種APIキーを設定
```

`fonts/` に日本語フォント（例: Noto Sans JP）を配置してください。詳細は
`ai_fortune_system/fonts/README.md` を参照してください。

Instagram/Threads APIは画像をローカルファイルとしてアップロードできず、
公開URL経由での参照が必須です。生成画像を公開配信できるURL
（例: S3 + CloudFront、Cloudflare R2など）を `PUBLIC_IMAGE_BASE_URL` に
設定してください。

## 実行

```bash
python main.py
```

毎日 `DAILY_POST_HOUR:DAILY_POST_MINUTE`（既定 8:00）にコンテンツ生成・配信を行い、
`REPLY_CHECK_INTERVAL_MINUTES`（既定5分）ごとにXのメンションを確認して
「A」「B」のリプライに辛口鑑定結果を自動返信します。

## 開発上の注意

- **段階的リリース**: まずXの自動投稿・リプライ機能を確実に動かし、その後
  Instagram/Threads連携へスコープを広げるのが確実です（Meta側API仕様変更の頻度が高いため）。
- **レートリミット**: `publisher.py` は各プラットフォームへの投稿間に
  `time.sleep(3)` のインターバルを挟んでいます。
- **常時起動**: `main.py` の `BlockingScheduler` はローカルPCではなく、
  Render・AWS（Lambda + EventBridgeでcron化）・VPS等の常時稼働環境で実行してください。
