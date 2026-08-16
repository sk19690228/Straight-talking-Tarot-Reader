"""AI占い自動化・マルチプラットフォーム配信システム — エントリーポイント兼スケジューラー。"""

import logging
import os

from apscheduler.schedulers.blocking import BlockingScheduler
from dotenv import load_dotenv

from generator import ContentGenerator, GeneratorError
from image_processor import ImageProcessorError, compose_fortune_image
from publisher import SNSPublisher
from responder import ReplyResponder, save_daily_state

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(__file__)
OUTPUT_DIR = os.path.join(BASE_DIR, "output")


def run_daily_fortune_job() -> None:
    """日替わりの辛口タロット占いコンテンツを生成し、全SNSへ配信する。"""
    logger.info("日次コンテンツ生成ジョブを開始します。")
    try:
        generator = ContentGenerator()
        theme = generator.pick_daily_theme()
        logger.info("本日のテーマ: %s", theme)

        content = generator.generate_fortune_content(theme)
        background_path = generator.generate_background_image(theme, OUTPUT_DIR)
        image_path = compose_fortune_image(background_path, content["catchphrase"], OUTPUT_DIR)

        auto_post_to_x = os.getenv("AUTO_POST_TO_X", "true").lower() == "true"
        results = SNSPublisher().publish_all(image_path, content["sns_text"], post_to_x=auto_post_to_x)
        logger.info("配信結果: %s", results)

        # tweet_idがNone（手動投稿モード、またはX投稿失敗）でも、選択肢A/Bの
        # 鑑定結果はここで保存しておく。手動投稿後にregister_tweet_id.pyで
        # ツイートIDだけ登録すれば、リプライ自動応答が有効になる。
        save_daily_state(results.get("x_tweet_id"), content, theme)

        if not auto_post_to_x:
            logger.info("=== Xへ手動投稿してください ===")
            logger.info("画像: %s", image_path)
            logger.info("投稿文:\n%s", content["sns_text"])
            logger.info("投稿後は次のコマンドでツイートIDを登録してください:")
            logger.info("  python3 register_tweet_id.py <ツイートID>")
        elif not results.get("x_tweet_id"):
            logger.warning("Xへの自動投稿に失敗しました。リプライ自動応答は無効のままです。")
    except (GeneratorError, ImageProcessorError):
        logger.exception("コンテンツ生成中にエラーが発生したため、本日のジョブを中止します。")
    except Exception:
        logger.exception("日次ジョブで予期しないエラーが発生しました。")


def run_reply_check_job() -> None:
    """Xのメンションを確認し、A/Bリプライへ自動返信する。"""
    try:
        ReplyResponder().check_and_respond()
    except Exception:
        logger.exception("リプライ確認ジョブで予期しないエラーが発生しました。")


def main() -> None:
    daily_hour = int(os.getenv("DAILY_POST_HOUR", "8"))
    daily_minute = int(os.getenv("DAILY_POST_MINUTE", "0"))
    reply_interval_minutes = int(os.getenv("REPLY_CHECK_INTERVAL_MINUTES", "5"))

    scheduler = BlockingScheduler()
    scheduler.add_job(
        run_daily_fortune_job,
        trigger="cron",
        hour=daily_hour,
        minute=daily_minute,
        id="daily_fortune_job",
    )
    scheduler.add_job(
        run_reply_check_job,
        trigger="interval",
        minutes=reply_interval_minutes,
        id="reply_check_job",
    )

    logger.info(
        "スケジューラーを起動しました。毎日 %02d:%02d に投稿、%d分ごとにリプライを確認します。",
        daily_hour,
        daily_minute,
        reply_interval_minutes,
    )
    scheduler.start()


if __name__ == "__main__":
    main()
