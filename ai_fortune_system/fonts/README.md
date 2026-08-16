# fonts/

日本語フォントファイル（例: `NotoSansJP-Bold.otf`）をこのディレクトリに配置してください。

`image_processor.py` はデフォルトで `fonts/NotoSansJP-Bold.otf` を参照します
（`FONT_PATH` 環境変数で変更可能）。Renderやさくらインターネット等の
Linuxサーバー環境では日本語フォントがプリインストールされていないことが多いため、
フォントファイルをリポジトリに同梱し、相対パスで読み込むことで環境依存の
文字化けを防げます。

Noto Sans JPは [Google Fonts](https://fonts.google.com/noto/specimen/Noto+Sans+JP)
から無償で入手できます（OFL-1.1ライセンス）。
