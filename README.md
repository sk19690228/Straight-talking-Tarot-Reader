# Straight-talking Tarot Reader

生成AIとSNS APIを活用し、30〜40代女性向けの辛口タロット占いコンテンツ
（マツコ×ひろゆき風）を自動生成・画像合成し、X・Instagram・Threadsへ
自動配信・リプライ対応するシステムです。

文章生成にはGoogle Gemini APIを使用します。OpenAI APIには一切依存しません。
画像は日次のコンテンツ生成のたびにAIで作るのではなく、あらかじめ用意した
静的なタロットカード素材（`assets/templates/`、大アルカナ22枚）を
ランダムに組み合わせる方式のため、日々の投稿にかかる画像生成コストは
かかりません。この22枚自体はご用意いただいたカード画像（JPEG）を
リポジトリにコミットして使い回しています。

ジャンルは「深い悩みのある恋愛」に固定されています。以下の流れで、
読者一人ひとりに合わせた個別の占い体験を提供します。

1. **当日の投稿**: タロットカード1枚に、本日のお悩みテーマの問いかけ（上段）と、
   「生年月日・血液型・家族構成」をリプライで教えてもらうための案内文（下段）を
   絵文字入りで重ねた画像を投稿します（家族構成は、親兄弟、生立ち、過去の
   トラウマなどの情報を書くとより詳細に占える旨も案内文に含めます）。文章は
   毎回Geminiが生成するため、テーマ・言い回し・絵文字が日替わりで変わります。
2. **個別鑑定（リプライへの自動返信）**: その投稿への返信を検知するたびに、
   タロットカード3枚をランダムに選んで1枚の画像に合成します。
3. **辛口の個別分析**: 引かれたタロット3枚の意味と、返信に書かれた生年月日
   （年齢の目安）・血液型・家族構成をもとに分析した、精神分析的な視点も交えた
   辛口の占い＆アドバイス文を、画像付きでリプライします。

返信内容は自由記述で構いません（「A」「B」のような決まった選択肢はありません）。
書かれている情報の範囲で鑑定するため、項目が一部欠けていても鑑定は行われます。

## ディレクトリ構成

```
ai_fortune_system/
├── main.py              # メインの実行ファイル・スケジューラー
├── generator.py          # 文章生成（Gemini API）・タロットカード選定ロジック
├── image_processor.py    # 画像合成処理（当日投稿画像への文章合成、個別鑑定用のカード3枚合成）
├── publisher.py           # 各SNS（X, Instagram, Threads）への配信ロジック
├── responder.py            # リプライ検知・個別鑑定の自動返信ロジック
├── register_tweet_id.py   # 手動投稿したツイートIDを登録するスクリプト
├── scripts/
│   ├── generate_card_deck_gemini.py  # Gemini画像生成で大アルカナ22枚を作る(素材を差し替えたい時用)
│   └── generate_templates.py         # Pillowだけで手続き的に図案を作る無料版(フォールバック用)
├── assets/templates/      # タロットカード素材（positive/negative、大アルカナ22枚、JPEG）
├── fonts/                    # 日本語フォント（同梱、環境依存の文字化け防止。カラー絵文字フォントは別途OS側を利用）
└── requirements.txt
```

## GitHub Actionsで動かす（推奨・常時稼働）

サーバー契約なしで、GitHub Actionsの無料枠だけで常時運用できます。ローカルでの
Python環境構築は不要です。

### 1. リポジトリにSecretsを登録

GitHubのリポジトリで `Settings → Secrets and variables → Actions → New repository secret`
から、以下を1つずつ登録してください（値はご自身のAPIキー）。

- `GEMINI_API_KEY`（文章生成用。[Google AI Studio](https://aistudio.google.com/apikey)で無料取得可能）
- `X_API_KEY`
- `X_API_SECRET`
- `X_ACCESS_TOKEN`
- `X_ACCESS_TOKEN_SECRET`
- `X_BEARER_TOKEN`

### 2. 4つのワークフロー

- **`.github/workflows/daily-post.yml`**: **自動スケジュール実行は停止しています**
  （`Actions`タブから手動実行のみ）。本日のお悩みテーマ＋入力案内の投稿文と、
  添える表紙画像を1枚生成します（`AUTO_POST_TO_X=false`固定のため、Xへの自動投稿は
  しません。投稿文・画像は実行ログと`state/daily_fortune.json`から確認できるほか、
  実行結果画面（Summary）の「Artifacts」から`daily-invitation-image`として画像PNGを
  直接ダウンロードできます）。
  ⚠️ このワークフローを実行すると、`state/`内の前回分のデータ（tweet_id・
  お悩みテーマ）が新しい日付のもので上書きされます。**前日の投稿へのリプライが
  まだ来る可能性がある間は実行しないでください**（自動応答できなくなります）。
- **`.github/workflows/reply-check.yml`**: 15分おきに自動実行。登録済みの当日投稿への
  リプライを検知するたびに、タロットカード3枚の画像と、返信内容（生年月日・血液型・
  家族構成など）を踏まえた個別の辛口鑑定文を自動リプライします。ツイートID未登録の
  間は何もしません。
- **`.github/workflows/register-tweet.yml`**: 手動投稿したツイートのIDを登録します。
  GitHubの「Actions」タブ→「Register Tweet ID」→「Run workflow」から、ツイートIDを
  入力して実行してください。
- **`.github/workflows/generate-card-deck.yml`**: `assets/templates/`のタロットカード
  画像（大アルカナ22枚）をGemini画像生成モデルで作り直します。通常は実行不要です
  （素材はリポジトリに同梱済み）。デザインを変えたい時や特定のカードだけ差し替えたい時に
  手動実行してください（`cards`欄にスラッグをスペース区切りで入力すると、そのカードだけ
  再生成します。例: `the_tower the_devil`。空欄なら22枚すべて）。

いずれも `Actions` タブから「Run workflow」で今すぐ手動実行できます。

### 3. 運用の流れ

1. 準備ができたら`daily-post`を手動実行 → 本日のテーマ＋入力案内の投稿文と表紙画像を生成
   （ログまたは`state/daily_fortune.json`から投稿文・画像を確認）
2. 自分の手でXへ投稿
3. `register-tweet`を手動実行し、投稿したツイートIDを入力
4. 以降は`reply-check`が、その投稿への各リプライに対して、タロット3枚の画像＋
   個別の辛口鑑定文をすべて自動でリプライします（手動投稿が必要なのは当日の
   投稿だけです）
5. その投稿への反応が落ち着いたら、次の`daily-post`を手動実行して次の投稿を作ります
   （上記の理由により、返信が来る余地があるうちは実行しないでください）

状態（本日のテーマ・投稿文・表紙画像、直近1件分の個別鑑定結果）は
`ai_fortune_system/state/`配下のJSONファイルとしてリポジトリに自動コミットされ、
実行のたびに引き継がれます。画像はbase64化して状態ファイルに含めるため、GitHub
ActionsのArtifactsを経由しなくても、コミット済みのこの状態ファイルから直接画像を
取り出せます（`last_reading.json`はリポジトリの肥大化を避けるため、直近1件分のみを
保持します）。

これとは別に、各ワークフロー実行では生成した画像PNGをGitHub Actionsの
Artifactsとしても添付しています（`daily-post`→`daily-invitation-image`、
`reply-check`→`reply-reading-images`、保持期間30日）。該当ワークフローの実行結果
ページ下部の「Artifacts」からZIPでダウンロードできます（リプライがなかった回の
`reply-check`は画像が生成されないため、Artifactsも空になります）。

画像はAIで毎回生成せず、`assets/templates/positive` `assets/templates/negative`
配下の静的なタロットカード素材（大アルカナ22枚）からランダムに選ぶだけなので、
画像生成にかかるAPIコストは一切かかりません。個別鑑定にはそのうち3枚をランダムに
選んで横に並べた1枚の画像を添付します。

## ローカルで動かす場合のセットアップ

```bash
cd ai_fortune_system
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # 各種APIキーを設定
```

`assets/templates/` の静的画像素材はリポジトリに同梱済みのため、通常は
何もする必要はありません。デザインを差し替えたい場合は、次のいずれかで
再生成できます。

```bash
# Gemini画像生成モデルで実際にAIに描かせる(要GEMINI_API_KEY・ネットワーク)
GEMINI_API_KEY=xxx python3 scripts/generate_card_deck_gemini.py

# Pillowだけで手続き的に図案を描く無料版(外部APIなし、フォールバック用)
python3 scripts/generate_templates.py
```

Instagram/Threads APIは画像をローカルファイルとしてアップロードできず、
公開URL経由での参照が必須です。生成画像を公開配信できるURL
（例: S3 + CloudFront、Cloudflare R2など）を `PUBLIC_IMAGE_BASE_URL` に
設定してください。

## 実行

```bash
python main.py
```

毎日 `DAILY_POST_HOUR:DAILY_POST_MINUTE`（既定 8:00）にコンテンツ生成・配信を行い、
`REPLY_CHECK_INTERVAL_MINUTES`（既定5分）ごとにXの返信を確認して、タロット3枚の
画像＋個別の辛口鑑定文を自動返信します。

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
   そのツイートへの返信を検知し、個別鑑定を自動返信します。ツイートID未登録の間は
   リプライ確認自体がスキップされます。

なお `X_API_KEY` 等のXの資格情報は、投稿を手動にしてもリプライ監視・自動返信のために
引き続き必要です（`responder.py` がメンション取得・返信投稿にXの API を使うため）。

## 開発上の注意

- **段階的リリース**: まずXの自動投稿・リプライ機能を確実に動かし、その後
  Instagram/Threads連携へスコープを広げるのが確実です（Meta側API仕様変更の頻度が高いため）。
- **レートリミット**: `publisher.py` は各プラットフォームへの投稿間に
  `time.sleep(3)` のインターバルを挟んでいます。
- **常時起動**: `main.py` の `BlockingScheduler` はローカルPCではなく、
  Render・AWS（Lambda + EventBridgeでcron化）・VPS等の常時稼働環境で実行してください。
- **返信内容のフィルタなし**: 当日の投稿への直接リプライは、内容を問わずすべて
  個別鑑定の対象になります（旧仕様の「A」「B」のようなパターン一致は行いません）。
  スパムや無関係なリプライにも反応する点にご留意ください。
