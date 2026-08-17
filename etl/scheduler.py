from apscheduler.schedulers.background import BackgroundScheduler
import time
import logging
from etl.pipeline import run_etl_pipeline

logger = logging.getLogger(__name__)

def start_scheduler():
    scheduler = BackgroundScheduler()
    # Chạy ETL mỗi 30 phút
    scheduler.add_job(run_etl_pipeline, 'interval', minutes=30, id='pancake_etl_job')
    scheduler.start()
    logger.info("Scheduler started. ETL will run every 30 minutes.")
    
    try:
        # Giữ script chạy liên tục nếu chạy độc lập
        while True:
            time.sleep(2)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        logger.info("Scheduler stopped.")

if __name__ == "__main__":
    start_scheduler()
