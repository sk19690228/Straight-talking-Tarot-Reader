# fonts/

日本語フォントファイル（例: `NotoSansJP-Bold.otf`）をこのディレクトリに配置してください。

`image_processor.py` はデフォルトで `fonts/NotoSansJP-Bold.otf` を参照します
（`FONT_PATH` 環境変数で変更可能）。Renderやさくらインターネット等の
Linuxサーバー環境では日本語フォントがプリインストールされていないことが多いため、
フォントファイルをリポジトリに同梱し、相対パスで読み込むことで環境依存の
文字化けを防げます。

Noto Sans JPは [Google Fonts](https://fonts.google.com/noto/specimen/Noto+Sans+JP)
から無償で入手できます（OFL-1.1ライセンス）。

## カラー絵文字について

当日投稿画像の文章にはカラー絵文字も使用します。絵文字の描画には別途
カラー絵文字フォント（例: Noto Color Emoji）が必要です（`EMOJI_FONT_PATH`
環境変数で指定、既定では `/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf`
等の一般的なインストール先を自動的に探します）。GitHub Actions上では
`fonts-noto-color-emoji` パッケージを自動インストールします。見つからない場合、
絵文字は表示されません（エラーにはなりません）。
