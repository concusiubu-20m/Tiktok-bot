"""
TikTok View Bot v6.0 – Playwright Edition
Dùng browser thật để xem video → TikTok đếm view chính xác
"""

import asyncio
import logging
import os
import random
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
#  Proxy Manager
# ─────────────────────────────────────────────

class ProxyManager:
    def __init__(self, proxy_list: Optional[List[str]] = None, proxy_file: str = "proxies.txt"):
        self.proxies: List[str] = list(proxy_list or [])
        self._index = 0
        self._lock = asyncio.Lock()
        if not self.proxies:
            self._load_file(proxy_file)

    def _load_file(self, path: str):
        if not os.path.exists(path):
            return
        for line in open(path):
            p = parse_proxy_line(line)
            if p:
                self.proxies.append(p)
        if self.proxies:
            logger.info(f"Loaded {len(self.proxies)} proxies from {path}")

    async def get_proxy(self) -> Optional[str]:
        async with self._lock:
            if not self.proxies:
                return None
            p = self.proxies[self._index % len(self.proxies)]
            self._index += 1
            return p

    def has_proxies(self) -> bool:
        return bool(self.proxies)


def parse_proxy_line(line: str) -> Optional[str]:
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    if line.startswith(("http://", "https://", "socks5://")):
        return line
    if "@" in line:
        return f"http://{line}"
    parts = line.split(":")
    if len(parts) == 2:
        try:
            int(parts[1])
            return f"http://{line}"
        except ValueError:
            return None
    if len(parts) == 4:
        ip, port, user, pwd = parts
        try:
            int(port)
            return f"http://{user}:{pwd}@{ip}:{port}"
        except ValueError:
            return None
    return None


# ─────────────────────────────────────────────
#  Thống kê
# ─────────────────────────────────────────────

@dataclass
class BotStats:
    total_views: int = 0
    successful: int = 0
    failed: int = 0
    start_time: float = field(default_factory=time.time)
    peak_speed: float = 0.0

    def speed(self) -> float:
        elapsed = time.time() - self.start_time
        return self.total_views / elapsed if elapsed > 0 else 0.0

    def success_rate(self) -> float:
        total = self.successful + self.failed
        return (self.successful / total * 100) if total > 0 else 0.0

    def elapsed(self) -> float:
        return time.time() - self.start_time

    def as_dict(self) -> Dict:
        spd = self.speed()
        if spd > self.peak_speed:
            self.peak_speed = spd
        return {
            "total_views":      self.total_views,
            "successful":       self.successful,
            "failed":           self.failed,
            "elapsed_s":        round(self.elapsed(), 1),
            "views_per_second": round(spd, 3),
            "views_per_minute": round(spd * 60, 1),
            "views_per_hour":   round(spd * 3600, 0),
            "peak_speed":       round(self.peak_speed, 3),
            "success_rate":     round(self.success_rate(), 1),
        }

    def summary(self) -> str:
        d = self.as_dict()
        return (
            f"📊 Tổng view: {d['total_views']:,}\n"
            f"⏱️ Thời gian: {d['elapsed_s']}s\n"
            f"⚡ Tốc độ: {d['views_per_second']} view/s\n"
            f"🏆 Peak: {d['peak_speed']} view/s\n"
            f"📈 Dự kiến/phút: {d['views_per_minute']:,.1f}\n"
            f"📈 Dự kiến/giờ: {d['views_per_hour']:,.0f}\n"
            f"✅ Thành công: {d['successful']:,}\n"
            f"❌ Thất bại: {d['failed']:,}\n"
            f"🎯 Tỷ lệ: {d['success_rate']}%"
        )


# ─────────────────────────────────────────────
#  User Agents thật của Chrome/Android
# ─────────────────────────────────────────────

DESKTOP_UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3.1 Safari/605.1.15",
]

MOBILE_UAS = [
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_3_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/122.0.6261.89 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.6261.90 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.6261.90 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; Xiaomi 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.6167.178 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_7_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
]


# ─────────────────────────────────────────────
#  Playwright View Worker
# ─────────────────────────────────────────────

async def _resolve_url(url: str) -> str:
    """Giải quyết URL rút gọn (vt.tiktok.com/xxx) thành URL đầy đủ."""
    if "vt.tiktok.com" in url or "vm.tiktok.com" in url:
        try:
            import aiohttp
            async with aiohttp.ClientSession() as sess:
                async with sess.get(
                    url,
                    allow_redirects=True,
                    timeout=aiohttp.ClientTimeout(total=10),
                    headers={"User-Agent": DESKTOP_UAS[0]},
                ) as r:
                    final = str(r.url)
                    logger.info(f"Resolved: {url} → {final}")
                    return final
        except Exception as e:
            logger.warning(f"Không giải quyết được URL rút gọn: {e}")
    return url


class ViewWorker:
    """
    Một browser context chạy liên tục, mở video, xem đủ thời gian, lặp lại.
    """

    def __init__(
        self,
        worker_id: int,
        video_url: str,
        watch_seconds: int,
        proxy_str: Optional[str],
        stats: BotStats,
        is_running_ref: list,  # [True/False]
        use_mobile: bool = False,
    ):
        self.worker_id   = worker_id
        self.video_url   = video_url
        self.watch_seconds = watch_seconds
        self.proxy_str   = proxy_str
        self.stats       = stats
        self.is_running  = is_running_ref
        self.use_mobile  = use_mobile

    def _proxy_kwargs(self) -> dict:
        if not self.proxy_str:
            return {}
        # playwright proxy format: {server, username, password}
        p = self.proxy_str
        if p.startswith("http://"):
            p = p[7:]
        if "@" in p:
            auth, hostport = p.rsplit("@", 1)
            if ":" in auth:
                user, pwd = auth.split(":", 1)
                return {"proxy": {"server": f"http://{hostport}", "username": user, "password": pwd}}
            return {"proxy": {"server": f"http://{hostport}"}}
        return {"proxy": {"server": f"http://{p}"}}

    async def run(self, playwright):
        from playwright.async_api import TimeoutError as PWTimeout

        ua = random.choice(MOBILE_UAS if self.use_mobile else DESKTOP_UAS)
        proxy_kw = self._proxy_kwargs()

        try:
            browser = await playwright.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-infobars",
                    "--window-size=1280,720",
                ],
                **proxy_kw,
            )
        except Exception as e:
            logger.error(f"Worker {self.worker_id}: Không mở được browser: {e}")
            return

        ctx = None
        try:
            ctx = await browser.new_context(
                user_agent=ua,
                viewport={"width": 1280, "height": 720} if not self.use_mobile else {"width": 390, "height": 844},
                locale="vi-VN",
                timezone_id="Asia/Ho_Chi_Minh",
                java_script_enabled=True,
                extra_http_headers={
                    "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
                },
            )
            # Ẩn dấu hiệu automation
            await ctx.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3] });
                window.chrome = { runtime: {} };
            """)

            page = await ctx.new_page()

            while self.is_running[0]:
                try:
                    # Mở trang TikTok
                    await page.goto(
                        self.video_url,
                        wait_until="domcontentloaded",
                        timeout=30_000,
                    )

                    # Đợi phần tử video xuất hiện
                    try:
                        await page.wait_for_selector("video", timeout=15_000)
                    except PWTimeout:
                        logger.debug(f"Worker {self.worker_id}: Không tìm thấy video element")
                        self.stats.failed += 1
                        await asyncio.sleep(3)
                        continue

                    # Unmute và play video bằng JS
                    await page.evaluate("""
                        () => {
                            const v = document.querySelector('video');
                            if (v) {
                                v.muted = true;
                                v.play().catch(() => {});
                            }
                        }
                    """)

                    # Đợi video bắt đầu phát (currentTime > 0)
                    try:
                        await page.wait_for_function(
                            "() => { const v = document.querySelector('video'); return v && v.currentTime > 0.5; }",
                            timeout=10_000,
                        )
                    except PWTimeout:
                        logger.debug(f"Worker {self.worker_id}: Video không phát được")
                        self.stats.failed += 1
                        await asyncio.sleep(2)
                        continue

                    # Xem đủ thời gian yêu cầu
                    elapsed = 0
                    interval = 1.0
                    watched = False
                    while elapsed < self.watch_seconds and self.is_running[0]:
                        await asyncio.sleep(interval)
                        elapsed += interval
                        # Kiểm tra video vẫn đang chạy
                        still_playing = await page.evaluate("""
                            () => {
                                const v = document.querySelector('video');
                                return v && !v.paused && !v.ended;
                            }
                        """)
                        if not still_playing:
                            # Thử play lại nếu bị pause
                            await page.evaluate("() => { const v = document.querySelector('video'); if(v) v.play().catch(()=>{}); }")

                    # Đã xem đủ → tính 1 view
                    self.stats.total_views += 1
                    self.stats.successful  += 1
                    logger.info(f"Worker {self.worker_id}: +1 view (tổng {self.stats.total_views})")

                    # Delay ngẫu nhiên trước lần tiếp theo
                    await asyncio.sleep(random.uniform(1.5, 4.0))

                except PWTimeout:
                    self.stats.failed += 1
                    await asyncio.sleep(3)
                except Exception as e:
                    logger.debug(f"Worker {self.worker_id} lỗi: {e}")
                    self.stats.failed += 1
                    await asyncio.sleep(5)

        finally:
            try:
                if ctx:
                    await ctx.close()
                await browser.close()
            except Exception:
                pass


# ─────────────────────────────────────────────
#  Core Bot
# ─────────────────────────────────────────────

class TikTokViewBot:
    """
    TikTok View Bot v6.0 – Playwright Edition
    Dùng browser thật, proxy thật → view thật
    """

    def __init__(
        self,
        proxy_manager: Optional[ProxyManager] = None,
        max_workers: int = 0,
        watch_seconds: int = 15,
        use_mobile: bool = False,
        on_progress=None,
    ):
        self.proxy_manager  = proxy_manager or ProxyManager()
        self.watch_seconds  = watch_seconds
        self.use_mobile     = use_mobile
        self.on_progress    = on_progress
        self.stats          = BotStats()
        self.is_running     = False
        self._running_ref   = [False]
        self._tasks: List[asyncio.Task] = []

        # Số workers mặc định = số proxy (tối đa 20)
        # Nếu không có proxy thì 3 workers (dùng IP thật)
        cpu = os.cpu_count() or 2
        if max_workers > 0:
            self.max_workers = max_workers
        elif self.proxy_manager.has_proxies():
            self.max_workers = min(len(self.proxy_manager.proxies), 15)
        else:
            self.max_workers = min(cpu, 3)

    async def start(self, video_url: str):
        """Bắt đầu buff view."""
        # Giải quyết URL rút gọn
        video_url = await _resolve_url(video_url)

        self.stats = BotStats()
        self.is_running = True
        self._running_ref[0] = True

        # Khởi động workers
        self._tasks = [
            asyncio.create_task(self._run_worker(i, video_url))
            for i in range(self.max_workers)
        ]

        # Progress callback
        if self.on_progress:
            asyncio.create_task(self._progress_loop())

        logger.info(f"Đã khởi động {self.max_workers} workers | URL: {video_url}")

    async def _run_worker(self, worker_id: int, video_url: str):
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.error("Playwright chưa được cài. Chạy: pip install playwright && playwright install chromium")
            self.stats.failed += 1
            return

        proxy = await self.proxy_manager.get_proxy()
        worker = ViewWorker(
            worker_id=worker_id,
            video_url=video_url,
            watch_seconds=self.watch_seconds,
            proxy_str=proxy,
            stats=self.stats,
            is_running_ref=self._running_ref,
            use_mobile=self.use_mobile,
        )
        try:
            async with async_playwright() as pw:
                await worker.run(pw)
        except Exception as e:
            logger.error(f"Worker {worker_id} crashed: {e}")

    async def _progress_loop(self):
        while self.is_running:
            await asyncio.sleep(10)
            if self.on_progress and self.is_running:
                await self.on_progress(self.stats)

    async def stop(self):
        self.is_running = False
        self._running_ref[0] = False
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        logger.info("Bot đã dừng")

    async def run_cli(self, video_url: str):
        """CLI mode."""
        await self.start(video_url)
        try:
            while True:
                await asyncio.sleep(3)
                d = self.stats.as_dict()
                print(
                    f"\r✅ {d['total_views']:,} view | "
                    f"⚡ {d['views_per_minute']:.1f}/min | "
                    f"🏆 peak {d['peak_speed']:.3f}/s | "
                    f"🎯 {d['success_rate']}% | "
                    f"⏱️ {d['elapsed_s']}s",
                    end="", flush=True
                )
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        finally:
            await self.stop()
            print("\n\n" + "=" * 60)
            print(self.stats.summary())


# ─────────────────────────────────────────────
#  CLI entry
# ─────────────────────────────────────────────

async def _cli_main():
    import argparse
    parser = argparse.ArgumentParser(description="TikTok View Bot v6.0 (Playwright)")
    parser.add_argument("url",           help="URL video TikTok")
    parser.add_argument("--workers",     type=int, default=0,   help="Số browser workers")
    parser.add_argument("--watch",       type=int, default=15,  help="Giây xem mỗi video")
    parser.add_argument("--proxy-file",  default="proxies.txt", help="File proxy")
    parser.add_argument("--mobile",      action="store_true",   help="Dùng UA mobile")
    args = parser.parse_args()

    pm  = ProxyManager(proxy_file=args.proxy_file)
    bot = TikTokViewBot(
        proxy_manager=pm,
        max_workers=args.workers,
        watch_seconds=args.watch,
        use_mobile=args.mobile,
    )
    await bot.run_cli(args.url)


if __name__ == "__main__":
    import sys
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(_cli_main())
