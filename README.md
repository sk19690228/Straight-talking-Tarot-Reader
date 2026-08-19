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
├── register_tweet_id.py   # 手動投稿したツイートIDを登録するスクリプト
├── fonts/                    # 日本語フォント（同梱、環境依存の文字化け防止）
└── requirements.txt
```

## GitHub Actionsで動かす（推奨・常時稼働）

サーバー契約なしで、GitHub Actionsの無料枠だけで常時運用できます。ローカルでの
Python環境構築は不要です。

### 1. リポジトリにSecretsを登録

GitHubのリポジトリで `Settings → Secrets and variables → Actions → New repository secret`
から、以下を1つずつ登録してください（値はご自身のAPIキー）。

- `OPENAI_API_KEY`
- `X_API_KEY`
- `X_API_SECRET`
- `X_ACCESS_TOKEN`
- `X_ACCESS_TOKEN_SECRET`
- `X_BEARER_TOKEN`

日本語フォントは、ワークフロー内で毎回 `apt-get install fonts-noto-cjk` により自動でインストールされるため、`fonts/` への配置は不要です。

### 2. 3つのワークフロー

- **`.github/workflows/daily-post.yml`**: 毎日08:00 JSTに自動実行。当日のコンテンツと
  画像を生成します（`AUTO_POST_TO_X=false`固定のため、Xへの自動投稿はしません）。
  生成された画像は、その実行の「Artifacts」からダウンロードできます。投稿文は
  実行ログに出力されます。
- **`.github/workflows/reply-check.yml`**: 15分おきに自動実行。登録済みのツイートへの
  A/Bリプライを検知して自動返信します。ツイートID未登録の間は何もしません。
- **`.github/workflows/register-tweet.yml`**: 手動投稿したツイートのIDを登録します。
  GitHubの「Actions」タブ→「Register Tweet ID」→「Run workflow」から、ツイートIDを
  入力して実行してください。

いずれも `Actions` タブから「Run workflow」で今すぐ手動実行できます（スケジュールを
待つ必要はありません）。

### 3. 運用の流れ

1. `daily-post`が自動実行 → Artifactsから画像をダウンロード、ログから投稿文をコピー
2. 自分の手でXへ投稿
3. `register-tweet`を手動実行し、投稿したツイートIDを入力
4. 以降は`reply-check`が自動でA/Bリプライに返信

状態（どのツイートを監視しているか、どこまで返信済みか）は`ai_fortune_system/state/`
配下のJSONファイルとしてリポジトリに自動コミットされ、実行のたびに引き継がれます。

## ローカルで動かす場合のセットアップ

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

## Xへの投稿を手動で行う場合

`.env` で `AUTO_POST_TO_X=false` に設定すると、Xへの自動投稿だけをスキップします
（Instagram/Threadsは設定していれば引き続き自動配信されます）。

1. スケジューラーが動くと、生成した画像のパスと投稿文がログに出力されます。
   すぐに1回分だけ試したい場合は次のコマンドで手動実行できます。
   ```bash
   python3 -c "from main import run_daily_fortune_job; run_daily_fortune_job()"
   ```
2. ログに出た画像・投稿文を使って、自分の手でXへ投稿します。
3. 投稿したツイートのIDを、以下のコマンドで登録します。
   ```bash
   python3 register_tweet_id.py <ツイートID>
   ```
4. 登録後は通常どおり `run_reply_check_job`（`main.py` 実行中なら自動、単体なら
   `python3 -c "from main import run_reply_check_job; run_reply_check_job()"`）が
   そのツイートへのA/Bリプライを検知し、辛口鑑定結果を自動返信します。
   ツイートID未登録の間はリプライ確認自体がスキップされます。

なお `X_API_KEY` 等のXの資格情報は、投稿を手動にしてもリプライ監視・自動返信のために
引き続き必要です（`responder.py` がメンション取得・返信投稿にXの API を使うため）。

## 開発上の注意

- **段階的リリース**: まずXの自動投稿・リプライ機能を確実に動かし、その後
  Instagram/Threads連携へスコープを広げるのが確実です（Meta側API仕様変更の頻度が高いため）。
- **レートリミット**: `publisher.py` は各プラットフォームへの投稿間に
  `time.sleep(3)` のインターバルを挟んでいます。
- **常時起動**: `main.py` の `BlockingScheduler` はローカルPCではなく、
  Render・AWS（Lambda + EventBridgeでcron化）・VPS等の常時稼働環境で実行してください。
