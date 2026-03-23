import asyncio
import logging
import os
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

CONFIG_PATH = Path("config.yaml")


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


def schedule_channels(scheduler: AsyncIOScheduler, config: AppConfig,
                      client: httpx.AsyncClient, notifier: NtfyNotifier,
                      dedup: DeduplicationStore):
    """Add all channel jobs to the scheduler."""
    for ch in config.channels:
        monitor = create_monitor(ch, client)
        matcher = Matcher(config.global_keywords, ch.keywords)

        async def make_job(mon=monitor, mat=matcher, name=ch.name,
                           prio=ch.priority, first_run=config.notify_on_first_run):
            await poll_channel(mon, mat, notifier, dedup, name, prio, first_run)

        scheduler.add_job(make_job, "interval", seconds=ch.poll_interval,
                          id=ch.name, name=ch.name, max_instances=1)
        scheduler.add_job(make_job, id=f"{ch.name}_init", name=f"{ch.name}_init")
        logger.info(f"Scheduled '{ch.name}' (type={ch.type}) every {ch.poll_interval}s")


async def run(config: AppConfig):
    client = httpx.AsyncClient(
        timeout=30,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
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
    schedule_channels(scheduler, config, client, notifier, dedup)
    scheduler.add_job(dedup.cleanup, "cron", hour=3, id="dedup_cleanup")
    scheduler.start()
    logger.info("Notifier started. Monitoring channels...")

    # Hot-reload callback: re-read config, rebuild scheduler jobs
    async def reload_config():
        logger.info("Reloading configuration...")
        try:
            new_config = load_config(CONFIG_PATH)

            # Update notifier settings
            notifier.url = f"{new_config.ntfy.server.rstrip('/')}/{new_config.ntfy.topic}"
            notifier.default_priority = new_config.ntfy.default_priority

            # Remove all existing channel jobs (keep dedup_cleanup)
            for job in scheduler.get_jobs():
                if job.id != "dedup_cleanup":
                    job.remove()

            # Re-add channels from new config
            schedule_channels(scheduler, new_config, client, notifier, dedup)
            logger.info("Configuration reloaded successfully")
        except Exception:
            logger.exception("Failed to reload configuration")
            raise

    # Start web UI if enabled
    web_task = None
    if config.web.enabled:
        from .web import create_app, set_reload_callback
        set_reload_callback(reload_config)
        app = create_app()
        port = int(os.environ.get("PORT", config.web.port))
        web_config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="warning")
        server = uvicorn.Server(web_config)
        web_task = asyncio.create_task(server.serve())
        logger.info(f"Web UI available at http://localhost:{port}")

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
    if not CONFIG_PATH.exists():
        print("ERROR: config.yaml not found. Copy config.example.yaml and edit it.")
        sys.exit(1)

    config = load_config(CONFIG_PATH)
    setup_logging(config.log_level)
    asyncio.run(run(config))


if __name__ == "__main__":
    main()
