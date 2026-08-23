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

ジャンルは「深い悩みのある恋愛」に固定されています。以下の2段階の分岐で、
読者ごとに異なる結末へたどり着く占い体験を提供します。

1. **Q1（当日の投稿）**: 選択肢A（前向き・希望を持てる側）とB（厳しい現実を
   直視する側）を対比する2枚のタロット風画像を左右に並べ、Ａ／Ｂラベル付きの
   1枚の画像として投稿します。
2. **Q2（Q1への回答で自動分岐）**: Aと返信した人にはさらに深掘りした問い
   （選択肢θ/δの対比画像付き）を、Bと返信した人には別の深掘りした問い
   （選択肢η/φの対比画像付き）を、それぞれ画像付きでリプライします。
3. **最終診断**: Q2への回答（A/B）に応じて、A→θ・A→δ・B→η・B→φの
   4パターンのいずれかに沿った、精神分析の視点も交えた辛口の占い＆
   アドバイス文を返信します。

読者から見える返信操作は常に「A」または「B」の1文字のみです。θ/δ/η/φは
内部で分岐を区別するための名称で、画像や返信文には表示されません。

## ディレクトリ構成

```
ai_fortune_system/
├── main.py              # メインの実行ファイル・スケジューラー
├── generator.py          # 文章生成（Gemini API）・画像テンプレート選定ロジック
├── image_processor.py    # Pillowによるテキスト合成処理
├── publisher.py           # 各SNS（X, Instagram, Threads）への配信ロジック
├── responder.py            # リプライ検知・自動返信ロジック
├── register_tweet_id.py   # 手動投稿したツイートIDを登録するスクリプト
├── scripts/
│   ├── generate_card_deck_gemini.py  # Gemini画像生成で大アルカナ22枚を作る(素材を差し替えたい時用)
│   └── generate_templates.py         # Pillowだけで手続き的に図案を作る無料版(フォールバック用)
├── assets/templates/      # タロットカード素材（positive/negative、大アルカナ22枚、JPEG）
├── fonts/                    # 日本語フォント（同梱、環境依存の文字化け防止）
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

日本語フォントは、ワークフロー内で毎回 `apt-get install fonts-noto-cjk` により自動でインストールされるため、`fonts/` への配置は不要です。

### 2. 4つのワークフロー

- **`.github/workflows/daily-post.yml`**: **自動スケジュール実行は停止しています**
  （`Actions`タブから手動実行のみ）。当日のコンテンツと画像を生成します
  （`AUTO_POST_TO_X=false`固定のため、Xへの自動投稿はしません）。生成された画像は、
  その実行の「Artifacts」からダウンロードできます。投稿文は実行ログに出力されます。
  ⚠️ このワークフローを実行すると、`state/`内の前回分のデータ（tweet_id・
  会話スレッドの対応表）が新しい日付のもので上書きされます。**前日の投稿への
  A/B返信がまだ来る可能性がある間は実行しないでください**（自動応答できなくなります）。
- **`.github/workflows/reply-check.yml`**: 15分おきに自動実行。登録済みのQ1ツイートへの
  A/Bリプライを検知し、Q2（画像付き）を自動リプライします。さらにQ2への回答も検知し、
  4パターンの最終診断を自動リプライします。ツイートID未登録の間は何もしません。
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

1. 準備ができたら`daily-post`を手動実行 → Q1・Q2(A用/B用)の3セット、計6枚の画像を生成
   （Q1のArtifactsから画像をダウンロード、ログからQ1の投稿文をコピー）
2. 自分の手でQ1をXへ投稿
3. `register-tweet`を手動実行し、投稿したツイートIDを入力
4. 以降は`reply-check`が、Q1へのA/B回答にはQ2を、Q2へのA/B回答には最終診断を、
   すべて自動でリプライします（手動投稿が必要なのはQ1だけです）
5. その投稿への反応が落ち着いたら、次の`daily-post`を手動実行して次の投稿を作ります
   （上記の理由により、返信が来る余地があるうちは実行しないでください）

状態（Q1/Q2/最終診断の全文、Q1・Q2用の合成画像、最終診断4パターンそれぞれに
添えるタロットカード画像、どのリプライスレッドがどの分岐か）は
`ai_fortune_system/state/`配下のJSONファイルとしてリポジトリに自動コミットされ、
実行のたびに引き継がれます。画像はすべてbase64化して状態ファイルに含めるため、
コミットのたびにリポジトリのサイズが数MB増える点にご注意ください。
その代わり、GitHub ActionsのArtifacts（有効期限あり・ダウンロードにブラウザ操作が
必要）を経由しなくても、コミット済みのこの状態ファイルから直接画像を取り出せます。

画像はAIで毎回生成せず、`assets/templates/positive` `assets/templates/negative`
配下の静的なタロットカード素材（大アルカナ22枚: positive 11枚・negative 11枚）
からランダムに選ぶだけなので、画像生成にかかるAPIコストは一切かかりません。
Q1・Q2-A・Q2-Bはそれぞれ2枚を左右に並べて合成し、最終診断4パターン
（A→θ・A→δ・B→η・B→φ）にはそれぞれ1枚のカード画像をそのまま添付します。

## ローカルで動かす場合のセットアップ

```bash
cd ai_fortune_system
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # 各種APIキーを設定
```

`fonts/` に日本語フォント（例: Noto Sans JP）を配置してください。詳細は
`ai_fortune_system/fonts/README.md` を参照してください。

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
