import asyncio
import logging
import sys
from pathlib import Path

import httpx
import uvicorn
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .config import AppConfig, load_config
from .dedup import DeduplicationStore
from .matcher import Matcher
from .models import Notification
from .monitors import create_monitor
from .notify import NtfyNotifier

logger = logging.getLogger("notifier")


def setup_logging(level: str):
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


async def poll_channel(monitor, matcher: Matcher, notifier: NtfyNotifier,
                       dedup: DeduplicationStore, channel_name: str,
                       priority: int | None, notify_on_first_run: bool):
    """Poll a single channel, match keywords, send notifications."""
    is_first_run = not dedup.has_source(channel_name)

    try:
        items = await monitor.fetch()
        logger.debug(f"[{channel_name}] Fetched {len(items)} items")

        for item in items:
            if not dedup.is_new(item.item_id):
                continue

            matched_keywords = matcher.matches(item)

            if matched_keywords and not (is_first_run and not notify_on_first_run):
                title = f"[{channel_name}] {item.title[:80]}"
                body = item.body[:500] if item.body else ""
                tags = [monitor.config.type] + matched_keywords[:3]

                await notifier.send(Notification(
                    title=title,
                    body=body,
                    url=item.url,
                    priority=priority or notifier.default_priority,
                    tags=tags,
                ))

            dedup.mark_seen(item.item_id, channel_name)

        if is_first_run and items:
            logger.info(f"[{channel_name}] First run: marked {len(items)} items as seen")

    except Exception:
        logger.exception(f"[{channel_name}] Error during poll")


async def run(config: AppConfig):
    client = httpx.AsyncClient(
        timeout=30,
        headers={"User-Agent": "notifier/1.0 (personal keyword monitor)"},
        follow_redirects=True,
    )
    dedup = DeduplicationStore("data/seen.db")
    notifier = NtfyNotifier(
        server=config.ntfy.server,
        topic=config.ntfy.topic,
        default_priority=config.ntfy.default_priority,
        client=client,
    )

    scheduler = AsyncIOScheduler()

    for ch in config.channels:
        monitor = create_monitor(ch, client)
        matcher = Matcher(config.global_keywords, ch.keywords)

        async def make_job(mon=monitor, mat=matcher, name=ch.name,
                           prio=ch.priority, first_run=config.notify_on_first_run):
            await poll_channel(mon, mat, notifier, dedup, name, prio, first_run)

        # Schedule recurring poll
        scheduler.add_job(make_job, "interval", seconds=ch.poll_interval,
                          id=ch.name, name=ch.name, max_instances=1)
        # Run once immediately at startup
        scheduler.add_job(make_job, id=f"{ch.name}_init", name=f"{ch.name}_init")

        logger.info(f"Scheduled '{ch.name}' (type={ch.type}) every {ch.poll_interval}s")

    # Daily cleanup at 3 AM
    scheduler.add_job(dedup.cleanup, "cron", hour=3, id="dedup_cleanup")

    scheduler.start()
    logger.info("Notifier started. Monitoring channels...")

    # Start web UI if enabled
    web_task = None
    if config.web.enabled:
        from .web import create_app
        app = create_app()
        web_config = uvicorn.Config(app, host="0.0.0.0", port=config.web.port, log_level="warning")
        server = uvicorn.Server(web_config)
        web_task = asyncio.create_task(server.serve())
        logger.info(f"Web UI available at http://localhost:{config.web.port}")

    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutting down...")
    finally:
        scheduler.shutdown(wait=False)
        dedup.close()
        await client.aclose()
        if web_task:
            web_task.cancel()


def main():
    config_path = Path("config.yaml")
    if not config_path.exists():
        print("ERROR: config.yaml not found. Copy config.example.yaml and edit it.")
        sys.exit(1)

    config = load_config(config_path)
    setup_logging(config.log_level)
    asyncio.run(run(config))


if __name__ == "__main__":
    main()
