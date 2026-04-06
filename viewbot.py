"""
TikTok View Bot v5.0 - Nâng cấp từ các phiên bản cũ
Kết hợp các tính năng tốt nhất từ toolview1.py và viewv3.py
"""

import aiohttp
import asyncio
import random
import requests
import re
import time
import secrets
import os
import signal
import sys
from hashlib import md5
from time import time as T
from typing import Dict, Tuple, Optional, List
from dataclasses import dataclass, field
import logging
import json
import ssl

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
#  Device Fingerprint Database (mở rộng hơn)
# ─────────────────────────────────────────────

@dataclass
class DeviceInfo:
    model: str
    version: str
    api_level: int
    brand: str
    hardware: str
    manufacturer: str
    resolution: str = "1080x2400"
    dpi: int = 420


class DeviceGenerator:
    DEVICES: List[DeviceInfo] = [
        # Google Pixel
        DeviceInfo("Pixel 6",    "13", 33, "Google",  "oriole",      "Google",  "1080x2400", 411),
        DeviceInfo("Pixel 7",    "14", 34, "Google",  "panther",     "Google",  "1080x2400", 416),
        DeviceInfo("Pixel 8",    "14", 34, "Google",  "shiba",       "Google",  "1080x2400", 428),
        DeviceInfo("Pixel 8 Pro","14", 34, "Google",  "husky",       "Google",  "1344x2992", 489),
        # Samsung
        DeviceInfo("SM-S901B",   "13", 33, "Samsung", "dm3q",        "samsung", "1080x2340", 425),
        DeviceInfo("SM-S911B",   "14", 34, "Samsung", "e1s",         "samsung", "1080x2340", 393),
        DeviceInfo("SM-S928B",   "14", 34, "Samsung", "e3q",         "samsung", "1440x3088", 505),
        DeviceInfo("SM-A546B",   "13", 33, "Samsung", "a54x",        "samsung", "1080x2340", 390),
        # Xiaomi
        DeviceInfo("2201123C",   "13", 33, "Xiaomi",  "zeus",        "Xiaomi",  "1080x2400", 395),
        DeviceInfo("2210132C",   "14", 34, "Xiaomi",  "nuwa",        "Xiaomi",  "1080x2400", 395),
        DeviceInfo("23049PCD8G", "14", 34, "Xiaomi",  "vermeer",     "Xiaomi",  "1440x3200", 522),
        # OPPO
        DeviceInfo("CPH2447",    "13", 33, "OPPO",    "OPPO",        "OPPO",    "1080x2412", 392),
        DeviceInfo("CPH2551",    "14", 34, "OPPO",    "OPPO",        "OPPO",    "1080x2412", 394),
        # vivo
        DeviceInfo("V2217",      "13", 33, "vivo",    "V2217",       "vivo",    "1080x2400", 387),
        DeviceInfo("V2309",      "14", 34, "vivo",    "V2309",       "vivo",    "1080x2400", 389),
        # realme
        DeviceInfo("RMX3371",    "13", 33, "realme",  "RE5B6A",      "realme",  "1080x2400", 402),
        DeviceInfo("RMX3843",    "14", 34, "realme",  "RE58B6",      "realme",  "1080x2400", 399),
        # OnePlus
        DeviceInfo("LE2123",     "13", 33, "OnePlus", "OnePlus9Pro", "OnePlus", "1440x3216", 525),
        DeviceInfo("CPH2451",    "14", 34, "OnePlus", "OnePlus11",   "OnePlus", "1440x3216", 525),
        # Motorola
        DeviceInfo("XT2301-4",   "13", 33, "motorola","hiphala",     "motorola","1080x2400", 388),
        DeviceInfo("XT2251-1",   "13", 33, "motorola","eqs",         "motorola","1080x2256", 403),
    ]

    @classmethod
    def random_device(cls) -> DeviceInfo:
        return random.choice(cls.DEVICES)

    @classmethod
    def generate_device_id(cls) -> str:
        return str(random.randint(6800000000000000000, 6999999999999999999))

    @classmethod
    def generate_openudid(cls) -> str:
        return ''.join(random.choices('abcdef0123456789', k=16))

    @classmethod
    def generate_cdids(cls) -> str:
        return ''.join(random.choices('abcdef0123456789', k=16))

    @classmethod
    def generate_install_id(cls) -> str:
        return str(random.randint(7000000000000000000, 7999999999999999999))


# ─────────────────────────────────────────────
#  Thuật toán X-Gorgon chính xác
# ─────────────────────────────────────────────

class XGorgonSigner:
    """
    Tái tạo thuật toán X-Gorgon từ viewv3.py (chính xác nhất)
    """
    KEY = [
        0xDF, 0x77, 0xB9, 0x40, 0xB9, 0x9B, 0x84, 0x83,
        0xD1, 0xB9, 0xCB, 0xD1, 0xF7, 0xC2, 0xB9, 0x85,
        0xC3, 0xD0, 0xFB, 0xC3
    ]

    def __init__(self, params: str, data: str, cookies: str):
        self.params = params
        self.data = data
        self.cookies = cookies

    def _md5(self, s: str) -> str:
        return md5(s.encode()).hexdigest()

    def _reverse_byte(self, n: int) -> int:
        h = f"{n:02x}"
        return int(h[1] + h[0], 16)

    def generate(self) -> Dict[str, str]:
        g  = self._md5(self.params)
        g += self._md5(self.data)    if self.data    else "0" * 32
        g += self._md5(self.cookies) if self.cookies else "0" * 32
        g += "0" * 32

        ts = int(T())
        payload: List[int] = []

        for i in range(0, 12, 4):
            chunk = g[8 * i: 8 * (i + 1)]
            for j in range(4):
                payload.append(int(chunk[j * 2: (j + 1) * 2], 16))

        payload.extend([0x0, 0x6, 0xB, 0x1C])
        payload.extend([
            (ts & 0xFF000000) >> 24,
            (ts & 0x00FF0000) >> 16,
            (ts & 0x0000FF00) >> 8,
            (ts & 0x000000FF),
        ])

        enc = [a ^ b for a, b in zip(payload, self.KEY)]

        for i in range(0x14):
            C = self._reverse_byte(enc[i])
            D = enc[(i + 1) % 0x14]
            F = int(bin(C ^ D)[2:].zfill(8)[::-1], 2)
            H = ((F ^ 0xFFFFFFFF) ^ 0x14) & 0xFF
            enc[i] = H

        sig = "".join(f"{x:02x}" for x in enc)
        return {
            "X-Gorgon":  "840280416000" + sig,
            "X-Khronos": str(ts),
        }


# ─────────────────────────────────────────────
#  Proxy Manager
# ─────────────────────────────────────────────

class ProxyManager:
    def __init__(self, proxy_list: Optional[List[str]] = None, proxy_file: str = "proxies.txt"):
        self.proxies: List[str] = proxy_list or []
        self.current_index = 0
        self.lock = asyncio.Lock()
        if not self.proxies:
            self._load_from_file(proxy_file)

    def _load_from_file(self, path: str):
        try:
            if os.path.exists(path):
                with open(path) as f:
                    self.proxies = [line.strip() for line in f if line.strip()]
                logger.info(f"Loaded {len(self.proxies)} proxies from {path}")
            else:
                logger.info("No proxy file found – running without proxies")
        except Exception as e:
            logger.error(f"Error loading proxies: {e}")

    async def get_proxy(self) -> Optional[str]:
        async with self.lock:
            if not self.proxies:
                return None
            p = self.proxies[self.current_index]
            self.current_index = (self.current_index + 1) % len(self.proxies)
            return p

    def has_proxies(self) -> bool:
        return bool(self.proxies)


# ─────────────────────────────────────────────
#  Rate Limiter
# ─────────────────────────────────────────────

class RateLimiter:
    def __init__(self, max_rps: int = 200):
        self.max_rps = max_rps
        self.tokens = float(max_rps)
        self.last_update = time.time()
        self.lock = asyncio.Lock()

    async def acquire(self):
        async with self.lock:
            now = time.time()
            elapsed = now - self.last_update
            self.tokens = min(self.max_rps, self.tokens + elapsed * self.max_rps)
            self.last_update = now
            if self.tokens < 1:
                wait = (1 - self.tokens) / self.max_rps
                await asyncio.sleep(wait)
                self.tokens = 0
            else:
                self.tokens -= 1


# ─────────────────────────────────────────────
#  Thống kê live
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
            "views_per_second": round(spd, 2),
            "views_per_minute": round(spd * 60, 0),
            "views_per_hour":   round(spd * 3600, 0),
            "peak_speed":       round(self.peak_speed, 2),
            "success_rate":     round(self.success_rate(), 1),
        }

    def summary(self) -> str:
        d = self.as_dict()
        return (
            f"📊 Tổng view: {d['total_views']:,}\n"
            f"⏱️ Thời gian: {d['elapsed_s']}s\n"
            f"⚡ Tốc độ: {d['views_per_second']:.1f} view/s\n"
            f"🏆 Peak: {d['peak_speed']:.1f} view/s\n"
            f"📈 Dự kiến/phút: {d['views_per_minute']:,.0f}\n"
            f"📈 Dự kiến/giờ: {d['views_per_hour']:,.0f}\n"
            f"✅ Thành công: {d['successful']:,}\n"
            f"❌ Thất bại: {d['failed']:,}\n"
            f"🎯 Tỷ lệ: {d['success_rate']}%"
        )


# ─────────────────────────────────────────────
#  Core Bot
# ─────────────────────────────────────────────

class TikTokViewBot:
    """
    TikTok View Bot v5.0 – nâng cấp toàn diện
    """

    APP_VERSIONS = [
        ("400304", "40.3.4"),
        ("390205", "39.2.5"),
        ("380106", "38.1.6"),
        ("370307", "37.3.7"),
    ]
    APP_REGIONS = ["VN", "US", "ID", "TH", "MY", "PH", "SG", "BR"]
    APP_LANGS   = ["vi", "en", "id", "th", "ms", "pt"]
    TZ_MAP      = {
        "VN": ("Asia/Ho_Chi_Minh", "25200"),
        "US": ("America/New_York", "-18000"),
        "ID": ("Asia/Jakarta", "25200"),
        "TH": ("Asia/Bangkok", "25200"),
        "MY": ("Asia/Kuala_Lumpur", "28800"),
    }
    MCC_MAP     = {
        "VN": ["45201", "45202", "45204"],
        "US": ["310260", "310410"],
        "ID": ["51010", "51021"],
        "TH": ["52001", "52015"],
        "MY": ["50212", "50219"],
    }

    def __init__(
        self,
        proxy_manager: Optional[ProxyManager] = None,
        max_workers: int = 0,
        max_rps: int = 200,
        on_progress=None,   # callback(stats: BotStats)
    ):
        self.proxy_manager = proxy_manager or ProxyManager()
        self.rate_limiter  = RateLimiter(max_rps)
        self.stats         = BotStats()
        self.is_running    = False
        self.session: Optional[aiohttp.ClientSession] = None
        self._tasks: List[asyncio.Task] = []
        self.on_progress   = on_progress

        # Tự động detect workers
        cpu = os.cpu_count() or 1
        if max_workers > 0:
            self.max_workers = max_workers
        elif cpu <= 2:
            self.max_workers = 500
        elif cpu <= 4:
            self.max_workers = 1500
        else:
            self.max_workers = 3000

    # ── Session ──────────────────────────────

    async def _init_session(self):
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

        connector = aiohttp.TCPConnector(
            limit=300,
            limit_per_host=30,
            ttl_dns_cache=300,
            ssl=ssl_ctx,
            enable_cleanup_closed=True,
        )
        timeout = aiohttp.ClientTimeout(total=20, connect=8, sock_read=12)
        self.session = aiohttp.ClientSession(
            timeout=timeout,
            connector=connector,
            cookie_jar=aiohttp.DummyCookieJar(),
        )

    async def _close_session(self):
        if self.session:
            await self.session.close()
            self.session = None

    # ── Video ID ─────────────────────────────

    def get_video_id(self, url: str) -> Optional[str]:
        url = url.split('?')[0].rstrip('/')
        for pattern in [
            r'/video/(\d{18,19})',
            r'tiktok\.com/@[^/]+/(\d{18,19})',
            r'(\d{19})',
        ]:
            m = re.search(pattern, url)
            if m:
                vid = m.group(1)
                logger.info(f"Video ID từ URL: {vid}")
                return vid

        # Fetch trang
        try:
            headers = {
                'User-Agent': (
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/120.0.0.0 Safari/537.36'
                ),
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate',
                'Connection': 'keep-alive',
            }
            resp = requests.get(url, headers=headers, timeout=15, allow_redirects=True)
            resp.raise_for_status()
            for pat in [
                r'"video":\{"id":"(\d{18,19})"',
                r'"aweme_id":"(\d{18,19})"',
                r'video_id["\']:\s*["\'](\d{18,19})',
                r'video/(\d{18,19})',
                r'"id":"(\d{19})"',
            ]:
                m = re.search(pat, resp.text)
                if m:
                    vid = m.group(1)
                    logger.info(f"Video ID từ trang: {vid}")
                    return vid
        except Exception as e:
            logger.error(f"Lỗi lấy trang: {e}")

        logger.error("Không tìm thấy Video ID")
        return None

    # ── Request Builder ───────────────────────

    def _build_request(self, video_id: str) -> Tuple[str, Dict, Dict, Dict]:
        device  = DeviceGenerator.random_device()
        dev_id  = DeviceGenerator.generate_device_id()
        openud  = DeviceGenerator.generate_openudid()
        install = DeviceGenerator.generate_install_id()
        cdids   = DeviceGenerator.generate_cdids()
        ver_code, ver_name = random.choice(self.APP_VERSIONS)
        region  = random.choice(self.APP_REGIONS)
        lang    = random.choice(self.APP_LANGS)
        tz_name, tz_off = self.TZ_MAP.get(region, ("Asia/Ho_Chi_Minh", "25200"))
        mccs    = self.MCC_MAP.get(region, ["45201"])
        ac      = random.choice(["wifi", "4g", "5g"])

        params = (
            f"channel=googleplay"
            f"&aid=1233"
            f"&app_name=musical_ly"
            f"&version_code={ver_code}"
            f"&version_name={ver_name}"
            f"&device_platform=android"
            f"&device_type={device.model.replace(' ', '+')}"
            f"&device_brand={device.brand}"
            f"&device_manufacturer={device.manufacturer}"
            f"&os_version={device.version}"
            f"&os_api={device.api_level}"
            f"&resolution={device.resolution.replace('x', '*')}"
            f"&dpi={device.dpi}"
            f"&device_id={dev_id}"
            f"&openudid={openud}"
            f"&install_id={install}"
            f"&cdid={cdids}"
            f"&app_language={lang}"
            f"&tz_name={tz_name.replace('/', '%2F')}"
            f"&tz_offset={tz_off}"
            f"&carrier_region={region}"
            f"&sys_region={region.lower()}"
            f"&ac={ac}"
            f"&mcc_mnc={random.choice(mccs)}"
            f"&pass-route=1"
        )

        url  = f"https://api16-core-c-alisg.tiktokv.com/aweme/v1/aweme/stats/?{params}"
        data = {
            "item_id":    video_id,
            "play_delta": 1,
            "action_time": int(time.time()),
            "source":     random.choice([1, 2, 3, 4]),
            "media_type": 4,
            "content_type": "video",
        }
        cookies = {
            "sessionid": secrets.token_hex(20),
            "uid":       str(random.randint(10_000_000_000, 99_999_999_999)),
            "cdids":     cdids,
        }
        ua = (
            f"com.ss.android.ugc.trill/{ver_code} "
            f"(Linux; U; Android {device.version}; "
            f"{device.model}; Build/TP1A; tt-ok/3.12.13.1)"
        )
        headers = {
            "Content-Type":  "application/x-www-form-urlencoded; charset=UTF-8",
            "User-Agent":    ua,
            "Accept-Encoding": "gzip",
            "Connection":    "Keep-Alive",
            "Host":          "api16-core-c-alisg.tiktokv.com",
            "sdk-version":   "2",
            "x-tt-dm-status": "login=1; launch=0",
        }

        # Ký
        sig = XGorgonSigner(
            params,
            str(data),
            "; ".join(f"{k}={v}" for k, v in cookies.items())
        ).generate()
        headers.update(sig)

        return url, data, cookies, headers

    # ── Single Request ────────────────────────

    async def _send_one(self, video_id: str, sem: asyncio.Semaphore) -> bool:
        async with sem:
            await self.rate_limiter.acquire()
            proxy = await self.proxy_manager.get_proxy()
            proxy_url = f"http://{proxy}" if proxy else None

            for attempt in range(3):
                try:
                    url, data, cookies, headers = self._build_request(video_id)
                    async with self.session.post(
                        url, data=data, headers=headers,
                        cookies=cookies, proxy=proxy_url, ssl=False
                    ) as resp:
                        if resp.status == 200:
                            self.stats.total_views += 1
                            self.stats.successful  += 1
                            return True
                        elif resp.status == 429:
                            await asyncio.sleep(2 ** attempt)
                            continue
                        else:
                            if attempt < 2:
                                await asyncio.sleep(0.1 * (attempt + 1))
                                continue
                            self.stats.failed += 1
                            return False

                except (aiohttp.ClientError, asyncio.TimeoutError):
                    if attempt < 2:
                        await asyncio.sleep(0.1 * (attempt + 1))
                        continue
                    self.stats.failed += 1
                    return False
                except Exception as e:
                    logger.debug(f"Lỗi request: {e}")
                    self.stats.failed += 1
                    return False

            return False

    # ── Worker Loop ───────────────────────────

    async def _worker(self, video_id: str, sem: asyncio.Semaphore):
        consecutive_ok = 0
        while self.is_running:
            ok = await self._send_one(video_id, sem)
            if ok:
                consecutive_ok += 1
                if consecutive_ok > 100:
                    delay = random.uniform(0.0005, 0.002)
                elif consecutive_ok > 50:
                    delay = random.uniform(0.002, 0.005)
                else:
                    delay = random.uniform(0.005, 0.01)
            else:
                consecutive_ok = 0
                delay = random.uniform(0.02, 0.06)

            # Tự điều chỉnh tốc độ
            spd = self.stats.speed()
            if spd > 400:
                delay *= 2.0
            elif spd > 250:
                delay *= 1.5

            await asyncio.sleep(delay)

    # ── Public API ────────────────────────────

    async def start(self, video_url: str):
        """Bắt đầu gửi view"""
        logger.info("Đang lấy Video ID...")
        video_id = self.get_video_id(video_url)
        if not video_id:
            raise ValueError("Không lấy được Video ID từ URL này")

        logger.info(f"Video ID: {video_id} | Workers: {self.max_workers}")
        await self._init_session()
        self.is_running = True
        self.stats = BotStats()

        sem = asyncio.Semaphore(min(500, self.max_workers // 3 + 1))
        self._tasks = [
            asyncio.create_task(self._worker(video_id, sem))
            for _ in range(self.max_workers)
        ]

        # Progress callback mỗi 5 giây
        if self.on_progress:
            asyncio.create_task(self._progress_loop())

        logger.info(f"Đã khởi động {self.max_workers} workers")

    async def _progress_loop(self):
        while self.is_running:
            await asyncio.sleep(5)
            if self.on_progress:
                await self.on_progress(self.stats)

    async def stop(self):
        """Dừng bot"""
        self.is_running = False
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        await self._close_session()
        logger.info("Bot đã dừng")

    async def run_cli(self, video_url: str):
        """Chạy từ CLI (blocking)"""
        await self.start(video_url)
        try:
            while True:
                await asyncio.sleep(2)
                d = self.stats.as_dict()
                print(
                    f"\r✅ {d['total_views']:,} view | "
                    f"⚡ {d['views_per_second']:.1f}/s | "
                    f"🏆 {d['peak_speed']:.1f}/s | "
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
            print("=" * 60)


# ─────────────────────────────────────────────
#  CLI entry
# ─────────────────────────────────────────────

async def _cli_main():
    import argparse
    parser = argparse.ArgumentParser(description="TikTok View Bot v5.0")
    parser.add_argument("url",           help="URL video TikTok")
    parser.add_argument("--workers",     type=int, default=0,   help="Số workers (0 = tự động)")
    parser.add_argument("--rps",         type=int, default=200, help="Giới hạn request/giây")
    parser.add_argument("--proxy-file",  default="proxies.txt", help="File proxy (ip:port)")
    args = parser.parse_args()

    pm  = ProxyManager(proxy_file=args.proxy_file)
    bot = TikTokViewBot(proxy_manager=pm, max_workers=args.workers, max_rps=args.rps)

    signal.signal(signal.SIGINT,  lambda *_: asyncio.create_task(bot.stop()))
    signal.signal(signal.SIGTERM, lambda *_: asyncio.create_task(bot.stop()))

    await bot.run_cli(args.url)


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(_cli_main())
