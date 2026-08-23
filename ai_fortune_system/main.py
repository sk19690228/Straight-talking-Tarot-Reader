"""AI占い自動化・マルチプラットフォーム配信システム — エントリーポイント兼スケジューラー。"""

import logging
import os

from apscheduler.schedulers.blocking import BlockingScheduler
from dotenv import load_dotenv

from generator import ContentGenerator, GeneratorError
from image_processor import ImageProcessorError, compose_dual_fortune_image
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
    """日替わりの辛口タロット占いコンテンツ（Q1→Q2→最終診断の分岐一式）を
    生成し、Q1をSNSへ配信する。Q2・最終診断はリプライ確認ジョブが自動投稿する。"""
    logger.info("日次コンテンツ生成ジョブを開始します。")
    try:
        generator = ContentGenerator()
        theme = generator.pick_daily_theme()
        logger.info("本日のテーマ: %s", theme)

        content = generator.generate_branching_content(theme)
        level1, level2_a, level2_b = content["level1"], content["level2_a"], content["level2_b"]

        image_a_path, image_b_path = generator.generate_pair_images(
            level1["option_a_label"], level1["option_b_label"], OUTPUT_DIR, "l1"
        )
        image_path = compose_dual_fortune_image(image_a_path, image_b_path, level1["catchphrase"], OUTPUT_DIR)

        theta_path, delta_path = generator.generate_pair_images(
            level2_a["option_theta_label"], level2_a["option_delta_label"], OUTPUT_DIR, "l2a"
        )
        level2_a_image_path = compose_dual_fortune_image(theta_path, delta_path, level2_a["catchphrase"], OUTPUT_DIR)

        eta_path, phi_path = generator.generate_pair_images(
            level2_b["option_eta_label"], level2_b["option_phi_label"], OUTPUT_DIR, "l2b"
        )
        level2_b_image_path = compose_dual_fortune_image(eta_path, phi_path, level2_b["catchphrase"], OUTPUT_DIR)

        auto_post_to_x = os.getenv("AUTO_POST_TO_X", "true").lower() == "true"
        results = SNSPublisher().publish_all(image_path, level1["question"], post_to_x=auto_post_to_x)
        logger.info("配信結果: %s", results)

        with open(image_path, "rb") as f:
            level1_image_bytes = f.read()
        with open(level2_a_image_path, "rb") as f:
            level2_a_image_bytes = f.read()
        with open(level2_b_image_path, "rb") as f:
            level2_b_image_bytes = f.read()

        # 最終診断4パターンそれぞれに添える1枚のタロットカード画像を選ぶ。
        # a_theta/b_etaは各分岐の中でも前向きな結末、a_delta/b_phiは厳しい
        # 現実を直視する結末なので、対応するpositive/negativeの山から選ぶ。
        result_moods = {"a_theta": "positive", "a_delta": "negative", "b_eta": "positive", "b_phi": "negative"}
        results_images = {}
        for result_key, mood in result_moods.items():
            result_image_path = generator.pick_result_image(mood)
            with open(result_image_path, "rb") as f:
                results_images[result_key] = f.read()

        # tweet_idがNone（手動投稿モード、またはX投稿失敗）でも、Q1/Q2/最終診断一式は
        # ここで保存しておく。手動投稿後にregister_tweet_id.pyでツイートIDだけ登録すれば、
        # Q2以降のリプライ自動応答が有効になる。
        save_daily_state(
            results.get("x_tweet_id"), content, theme, level1_image_bytes, level2_a_image_bytes, level2_b_image_bytes, results_images
        )

        if not auto_post_to_x:
            logger.info("=== Xへ手動投稿してください ===")
            logger.info("画像: %s", image_path)
            logger.info("投稿文:\n%s", level1["question"])
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
