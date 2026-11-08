# -*- coding: utf-8 -*-
"""
Нейро-Студия v57 — Multi-Provider + Grosh (USD) + FX Analyzer.
  - Все нейросети (Polza, CLODEx, SprutDock, Ranvik, OpenRouter).
  - Grosh: цены в ₽, оплата в USD по курсу ЦБ РФ (кэш в БД).
  - Анализатор USD/RUB в реальном времени (фоновый воркер).
"""
import os
import re
import time
import base64
import uuid
import socket
import ipaddress
import sqlite3
import logging
import threading
import signal
import json
import sys
import queue
import http.server
from datetime import datetime, timezone
from typing import Optional, Callable, Tuple
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor
from functools import wraps

from dotenv import load_dotenv
import telebot
from telebot import types
from telebot.apihelper import ApiTelegramException
import requests

load_dotenv(override=False)

# ==========================================================
# ЛОГИРОВАНИЕ
# ==========================================================
LOG_JSON = os.getenv("LOG_JSON", "0") == "1"

class _JsonFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "exc": self.formatException(record.exc_info) if record.exc_info else None,
        }, ensure_ascii=False)

def _setup_logging():
    if LOG_JSON:
        h = logging.StreamHandler(sys.stdout)
        h.setFormatter(_JsonFormatter())
        logging.basicConfig(level=logging.INFO, handlers=[h])
    else:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

log = logging.getLogger("neuro")

# ==========================================================
# ENV И КОНФИГ
# ==========================================================
def _env_int(name: str, default: int, minimum: Optional[int] = None) -> int:
    raw = os.getenv(name)
    if not raw: v = default
    else:
        try: v = int(raw)
        except ValueError: raise SystemExit(f"ENV {name}={raw!r} — не число")
    if minimum is not None and v < minimum: raise SystemExit(f"ENV {name}={v} < {minimum}")
    return v

def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if not raw: return default
    try: return float(raw)
    except ValueError: raise SystemExit(f"ENV {name}={raw!r} — не число")

def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "": return default
    return raw.strip().lower() in ("1", "true", "yes", "on")

TOKEN          = os.getenv("BOT_TOKEN")
POLZA_KEY      = os.getenv("POLZA_API_KEY")
POLZA_BASE     = os.getenv("POLZA_API_URL", "https://polza.ai/api/v1")
DATA_DIR       = os.getenv("DATA_DIR", "./data")
SUPPORT_URL    = os.getenv("SUPPORT_URL", "https://t.me/your_support")
PRIVACY_URL    = os.getenv("PRIVACY_URL", "")
TERMS_URL      = os.getenv("TERMS_URL", "")
PLATEGA_ID     = os.getenv("PLATEGA_MERCHANT_ID", "")
PLATEGA_SECRET = os.getenv("PLATEGA_SECRET_KEY", "")
PLATEGA_URL    = os.getenv("PLATEGA_API_URL", "https://app.platega.io")
RETURN_URL     = os.getenv("RETURN_URL", "")
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY", "")

RANVIK_API_KEY = os.getenv("RANVIK_API_KEY", "")
RANVIK_API_URL = os.getenv("RANVIK_API_URL", "https://api.ranvik.ru/v1")
TEXT_API_KEY   = os.getenv("TEXT_API_KEY", "")
TEXT_API_URL   = os.getenv("TEXT_API_URL", "https://sprutdock.ru/v1")
CLODEX_API_KEY = os.getenv("CLODEX_API_KEY", "")
CLODEX_API_URL = os.getenv("CLODEX_API_URL", "https://api.clodex.xyz/v1")

# GROSH WALLET
GROSH_API_KEY  = os.getenv("GROSH_API_KEY", "")
GROSH_API_URL  = os.getenv("GROSH_API_URL", "https://pay.grosh.me/api")

STARS_RUB_PER_STAR = _env_float("STARS_RUB_PER_STAR", 2.0)
STARS_AUTO_REFUND = _env_bool("STARS_AUTO_REFUND", True)
TERMS_REQUIRED    = _env_bool("TERMS_REQUIRED", False)

# FX ANALYZER
FX_API_URL        = os.getenv("FX_API_URL", "https://www.cbr-xml-daily.ru/daily_json.js")
FX_REFRESH_SEC    = _env_int("FX_REFRESH_SEC", 1800, minimum=60)
FX_MARKUP_PCT     = _env_float("FX_MARKUP_PCT", 3.0)
FX_FALLBACK_RATE  = _env_float("FX_FALLBACK_RATE", 95.0)

REFUND_WINDOW_HOURS     = _env_int("REFUND_WINDOW_HOURS", 24, minimum=1)
PAYMENT_POLL_MAX_ERRORS = _env_int("PAYMENT_POLL_MAX_ERRORS", 6, minimum=1)
PAYMENT_POLL_BACKOFF_MAX = _env_int("PAYMENT_POLL_BACKOFF_MAX", 60, minimum=5)
OUTBOX_MAX_ATTEMPTS     = _env_int("OUTBOX_MAX_ATTEMPTS", 8, minimum=1)
OUTBOX_RETRY_MAX_SEC    = _env_int("OUTBOX_RETRY_MAX_SEC", 3600, minimum=60)
HEALTH_DB_CHECK         = _env_bool("HEALTH_DB_CHECK", True)

FIRST_FREE_IMAGE = _env_bool("FIRST_FREE_IMAGE", True)
REF_BONUS        = 2
RATE_LIMIT       = _env_int("RATE_LIMIT_PER_HOUR", 20, minimum=1)
DAILY_BONUS      = _env_bool("DAILY_BONUS_ENABLED", True)
FREE_TEXT_LIMIT  = 5
MAX_HISTORY      = 10

FILE_MAX_MB           = _env_int("FILE_MAX_MB", 20, minimum=1)
PROMPT_MAX_LEN        = _env_int("PROMPT_MAX_LEN", 1000, minimum=10)
WORKS_RETENTION_DAYS  = _env_int("WORKS_RETENTION_DAYS", 30, minimum=1)
PAYMENT_POLL_TIMEOUT  = _env_int("PAYMENT_POLL_TIMEOUT", 3600, minimum=60)
PAYMENT_POLL_INTERVAL = _env_int("PAYMENT_POLL_INTERVAL", 15, minimum=1)

EXECUTOR_WORKERS   = _env_int("EXECUTOR_WORKERS", 8, minimum=1)
EXECUTOR_QUEUE_MAX = _env_int("EXECUTOR_QUEUE_MAX", 32, minimum=1)
STUCK_TX_TIMEOUT   = _env_int("STUCK_TX_TIMEOUT", 600, minimum=60)
ADMIN_STATE_TTL    = _env_int("ADMIN_STATE_TTL", 300, minimum=30)
ADMIN_MAX_GIFT     = _env_int("ADMIN_MAX_GIFT", 10000, minimum=1)

DB_POOL_SIZE       = _env_int("DB_POOL_SIZE", 16, minimum=2)
OUTBOX_BATCH       = _env_int("OUTBOX_BATCH", 32, minimum=1)
HEALTH_PORT        = _env_int("HEALTH_PORT", 0, minimum=0)

MODERATION_API_URL  = os.getenv("MODERATION_API_URL", "")
MODERATION_API_KEY  = os.getenv("MODERATION_API_KEY", "")
MODERATION_REQUIRED = _env_bool("MODERATION_REQUIRED", False)
MODERATION_FAIL_CLOSED = _env_bool("MODERATION_FAIL_CLOSED", False)
ADMIN_ONLY_IF_NO_MODERATION = _env_bool("ADMIN_ONLY_IF_NO_MODERATION", False)

WORKS_PER_USER    = 100
TG_MSG_CHUNK      = 4000
STT_PREVIEW_LEN   = 3500
ADMIN_PAGE        = 15
DNS_CACHE_TTL     = 60
CLEANUP_BATCH     = 500
RATE_CLEANUP_BATCH = 500

SUB_TARIFFS = {
    "start": {"title":"Старт", "price": 290, "limit": 30, "days":30},
    "pro":   {"title":"Про",   "price": 590, "limit": 70, "days":30},
    "max":   {"title":"Максимум","price": 990, "limit": 130, "days":30},
}

TEXT_SUB_TARIFFS = {
    "text_start": {"title":"Текст Старт", "price": 199, "tokens": 1_000_000, "days":30},
    "text_pro":   {"title":"Текст Про",   "price": 490, "tokens": 3_000_000, "days":30},
    "text_max":   {"title":"Текст Макс",  "price": 990, "tokens": 7_000_000, "days":30},
}
TEXT_GEN_PRICE = 3

bot: Optional[telebot.TeleBot] = None
GEN_EXECUTOR: Optional[ThreadPoolExecutor] = None
PAY_EXECUTOR: Optional[ThreadPoolExecutor] = None
WORKS_EXECUTOR: Optional[ThreadPoolExecutor] = None
QUEUE_SEM: Optional[threading.BoundedSemaphore] = None
BOT_USERNAME: str = ""
ADMIN_ID: int = 0
SHUTDOWN = threading.Event()

HTTP_TIMEOUT_SHORT = (5, 15)
HTTP_TIMEOUT_MED   = (5, 30)
HTTP_TIMEOUT_LONG  = (5, 30)

ALLOWED_CDN = {
    "polza.ai", "cdn.polza.ai", "storage.polza.ai",
    "openrouter.ai", "api.ranvik.ru",
    "sprutdock.ru", "storage.sprutdock.ru", "cdn.sprutdock.ru",
    "clodex.xyz", "api.clodex.xyz", "cdn.clodex.xyz", "storage.clodex.xyz",
    "grosh.me", "pay.grosh.me",
    "cbr-xml-daily.ru",
}

_EXPECTED_CT = {
    "image": ("image/",), "edit": ("image/",), "upscale": ("image/", "video/", "application/octet-stream"),
    "audio": ("audio/", "application/octet-stream"), "tts": ("audio/", "application/octet-stream"),
    "video": ("video/", "application/octet-stream"), "animate": ("video/", "application/octet-stream"),
}

MODELS = {
    # POLZA
    "openai/gpt-image-1.5":               {"name":"GPT Image 1.5",       "type":"image",  "price":7,  "cost":3.0,  "active":1, "provider":"polza"},
    "openai/gpt-5-image":                 {"name":"GPT-5 Image",         "type":"image",  "price":10, "cost":4.5,  "active":1, "provider":"polza"},
    "google/gemini-2.5-flash-image":      {"name":"Gemini 2.5 Flash",    "type":"image",  "price":6,  "cost":2.9,  "active":1, "provider":"polza"},
    "google/gemini-nano-banana-2.1":      {"name":"Nano Banana 2.1",     "type":"image",  "price":7,  "cost":3.0,  "active":1, "provider":"polza"},
    "google/gemini-3.1-flash-lite-image": {"name":"Gemini 3.1 Lite",     "type":"image",  "price":6,  "cost":2.9,  "active":1, "provider":"polza"},
    "black-forest-labs/flux.2-flex":      {"name":"Flux 2 Flex",         "type":"image",  "price":22, "cost":14.0, "active":1, "provider":"polza"},
    "bytedance/seedream-4":               {"name":"Seedream 4",          "type":"image",  "price":7,  "cost":3.0,  "active":1, "provider":"polza"},
    "bytedance/seedream-5-lite":          {"name":"Seedream 5 Lite",     "type":"image",  "price":8,  "cost":4.0,  "active":1, "provider":"polza"},
    "qwen/image":                         {"name":"Qwen Image",          "type":"image",  "price":5,  "cost":2.25, "active":1, "provider":"polza"},
    "qwen/image-2":                       {"name":"Qwen Image 2",        "type":"image",  "price":8,  "cost":4.0,  "active":1, "provider":"polza"},
    "qwen/image-2.1":                     {"name":"Qwen Image 2.1",      "type":"image",  "price":7,  "cost":3.0,  "active":1, "provider":"polza"},
    "tongyi-mai/z-image":                 {"name":"Z-Image",             "type":"image",  "price":5,  "cost":1.4,  "active":1, "provider":"polza"},
    "yandex/yandex-art":                  {"name":"Yandex Art",          "type":"image",  "price":6,  "cost":2.91, "active":1, "provider":"polza"},
    "grok-imagine-image-2-0/text-to-image":{"name":"Grok Image 2.0",     "type":"image",  "price":8,  "cost":3.0,  "active":1, "provider":"polza"},
    "x-ai/grok-image":                    {"name":"Grok Image",          "type":"image",  "price":6,  "cost":2.5,  "active":1, "provider":"polza"},

    "google/lyria-3-pro-preview":         {"name":"Lyria 3 Pro",         "type":"audio",  "price":20, "cost":10.0, "active":1, "provider":"polza"},
    "google/lyria-3-clip-preview":        {"name":"Lyria 3 Clip",        "type":"audio",  "price":12, "cost":6.0,  "active":1, "provider":"polza"},
    "suno/sounds":                        {"name":"Suno Sounds",         "type":"audio",  "price":8,  "cost":4.0,  "active":1, "provider":"polza"},
    "grok-imagine-video-1-5":             {"name":"Grok Imagine Video",  "type":"video",  "price":5,  "cost":2.0,  "active":1, "provider":"polza"},
    "bytedance/seedance-2-mini":          {"name":"Seedance 2 Mini",     "type":"video",  "price":7,  "cost":3.0,  "active":1, "provider":"polza"},
    "google/gemini-3.1-flash-tts-preview":{"name":"Gemini 3.1 TTS",      "type":"tts",    "price":30, "cost":14.0, "active":1, "provider":"polza"},
    "google/gemini-3.8-flash-lite-tts":   {"name":"Gemini 3.8 TTS",      "type":"tts",    "price":15, "cost":7.0,  "active":1, "provider":"polza"},
    "openai/whisper-1":                   {"name":"Whisper 1",           "type":"stt",    "price":5,  "cost":0.43, "active":1, "provider":"polza"},
    "openai/gpt-4o-transcribe":           {"name":"GPT-4o Transcribe",   "type":"stt",    "price":5,  "cost":0.70, "active":1, "provider":"polza"},
    "bytedance/seedream-4.5":             {"name":"Seedream 4.5 Edit",   "type":"edit",   "price":8,  "cost":4.0,  "active":1, "provider":"polza"},
    "bytedance/seedance-2":               {"name":"Seedance 2 (Оживл.)", "type":"animate","price":15, "cost":7.0,  "active":1, "provider":"polza"},
    "kling/v2.6-motion-control":          {"name":"Kling Motion",        "type":"animate","price":20, "cost":10.0, "active":1, "provider":"polza"},
    "topaz/video-upscale":                {"name":"Topaz Video Upscale", "type":"upscale","price":12, "cost":6.0,  "active":1, "provider":"polza"},
    "topaz/image-upscale":                {"name":"Topaz Image Upscale", "type":"upscale","price":5,  "cost":2.0,  "active":1, "provider":"polza"},

    # CLODEX
    "gpt-6-astra":                        {"name":"GPT-6 Astra (CX)",    "type":"text",   "price":3,  "cost":0.0,  "active":0, "provider":"clodex"},
    "gpt-6.1-sol":                        {"name":"GPT-6.1 Sol (CX)",    "type":"text",   "price":3,  "cost":0.0,  "active":0, "provider":"clodex"},
    "gpt-6.1-terra":                      {"name":"GPT-6.1 Terra (CX)",  "type":"text",   "price":3,  "cost":0.0,  "active":0, "provider":"clodex"},
    "claude-opus-5":                      {"name":"Claude Opus 5 (CX)",   "type":"text",   "price":3,  "cost":0.0,  "active":0, "provider":"clodex"},
    "claude-fable-5.1":                   {"name":"Claude Fable 5.1 (CX)","type":"text",   "price":3,  "cost":0.0,  "active":0, "provider":"clodex"},
    "kimi-k3.1-pro":                      {"name":"Kimi K3.1 Pro (CX)",   "type":"text",   "price":3,  "cost":0.0,  "active":0, "provider":"clodex"},
    "qwen3.8-max":                        {"name":"Qwen 3.8 Max (CX)",    "type":"text",   "price":3,  "cost":0.0,  "active":0, "provider":"clodex"},
    "glm-5.3":                            {"name":"GLM-5.3 (CX)",         "type":"text",   "price":3,  "cost":0.0,  "active":0, "provider":"clodex"},

    "flux-schnell":                       {"name":"Flux Schnell (CX)",    "type":"image",  "price":5,  "cost":0.0,  "active":0, "provider":"clodex"},
    "flux-dev":                           {"name":"Flux Dev (CX)",        "type":"image",  "price":5,  "cost":0.0,  "active":0, "provider":"clodex"},
    "muse-image-1.0":                     {"name":"Muse Image 1.0 (CX)",  "type":"image",  "price":5,  "cost":0.0,  "active":0, "provider":"clodex"},
    "gpt-image-2.6-sunburst":             {"name":"GPT Image 2.6 (CX)",   "type":"image",  "price":7,  "cost":0.0,  "active":0, "provider":"clodex"},
    "gpt-image-2.6-flare":                {"name":"GPT Image 2.6 Flare", "type":"image",  "price":7,  "cost":0.0,  "active":0, "provider":"clodex"},

    "clodex-video/kling-2.5-turbo-pro":   {"name":"Kling 2.5 Turbo (CX)","type":"video",  "price":15, "cost":0.0,  "active":0, "provider":"clodex"},
    "clodex-video/happy-horse-1.1":       {"name":"Happy Horse 1.1 (CX)","type":"video",  "price":15, "cost":0.0,  "active":0, "provider":"clodex"},
    "clodex-video/hailuo-2.3-fast":       {"name":"Hailuo 2.3 Fast (CX)", "type":"video",  "price":10, "cost":0.0,  "active":0, "provider":"clodex"},
    "clodex-video/gemini-omni-flash":     {"name":"Gemini Omni (CX)",     "type":"video",  "price":12, "cost":0.0,  "active":0, "provider":"clodex"},

    # SPRUTDOCK
    "scaledown/summarize":                {"name":"ScaleDown Sum (S)",   "type":"text",   "price":3,  "cost":0.0,  "active":0, "provider":"sprut"},
    "scaledown/extract":                  {"name":"ScaleDown Ext (S)",   "type":"text",   "price":3,  "cost":0.0,  "active":0, "provider":"sprut"},
    "xingchen-agi/xing4.0-29b-a4b":       {"name":"XingChen 29B (S)",    "type":"text",   "price":0,  "cost":0.0,  "active":0, "provider":"sprut"},
    "recursive/flint-v1.0":               {"name":"Recursive Flint (S)", "type":"text",   "price":0,  "cost":0.0,  "active":0, "provider":"sprut"},
    "stealth/crouton-alpha":              {"name":"Crouton Alpha (S)",   "type":"text",   "price":0,  "cost":0.0,  "active":0, "provider":"sprut"},
    "flux-schnell-sprut":                 {"name":"Flux Schnell (S)",    "type":"image",  "price":5,  "cost":0.0,  "active":0, "provider":"sprut"},
    "flux-dev-sprut":                     {"name":"Flux Dev (S)",        "type":"image",  "price":5,  "cost":0.0,  "active":0, "provider":"sprut"},

    # RANVIK
    "openai/gpt-6-luna":                  {"name":"GPT-6 Luna (R)",      "type":"text",   "price":3,  "cost":0.0,  "active":0, "provider":"ranvik"},
    "deepseek/deepseek-v4.1-flash":       {"name":"DeepSeek (R)",        "type":"text",   "price":3,  "cost":0.0,  "active":0, "provider":"ranvik"},
    "anthropic/claude-haiku-5.5":         {"name":"Claude Haiku (R)",    "type":"text",   "price":3,  "cost":0.0,  "active":0, "provider":"ranvik"},

    # OPENROUTER
    "nvidia/nemotron-3-ultra-550b-a55b:free": {"name":"Nemotron 3 Ultra", "type":"text", "price":0, "cost":0.0, "active":1, "provider":"openrouter"},
    "google/gemma-4-31b-it:free":         {"name":"Gemma 4 31B",        "type":"text",   "price":0, "cost":0.0,  "active":1, "provider":"openrouter"},
}

PACKAGES = {
    "img_10": {"title":"10 картинок", "type":"image", "count":10, "price":59},
    "img_25": {"title":"25 картинок", "type":"image", "count":25, "price":129},
    "img_50": {"title":"50 картинок", "type":"image", "count":50, "price":239},
    "img_100": {"title":"100 картинок", "type":"image", "count":100,"price":449},
    "aud_10": {"title":"10 музыки", "type":"audio", "count":10, "price":99},
    "aud_25": {"title":"25 музыки", "type":"audio", "count":25, "price":219},
    "vid_5": {"title":"5 видео", "type":"video", "count":5, "price":149},
    "vid_15": {"title":"15 видео", "type":"video", "count":15, "price":399},
    "tts_10": {"title":"10 озвучек", "type":"tts", "count":10, "price":139},
    "stt_10": {"title":"10 расшифровок", "type":"stt", "count":10, "price":59},
    "stt_25": {"title":"25 расшифровок", "type":"stt", "count":25, "price":129},
    "edit_10": {"title":"10 редакций", "type":"edit", "count":10, "price":99},
    "anim_5": {"title":"5 оживлений", "type":"animate", "count":5, "price":99},
    "up_10": {"title":"10 апскейлов", "type":"upscale", "count":10, "price":59},
}

POLL_TIMEOUT = {"image":120,"audio":120,"video":300,"tts":120,"stt":120,"edit":120,"animate":300,"upscale":180}
FILE_REQUIRED = {"edit","animate","upscale","stt"}
BAL_FIELD = {"image":"balance_img","audio":"balance_aud","video":"balance_vid","tts":"balance_tts", "stt":"balance_stt","edit":"balance_edit","animate":"balance_anim","upscale":"balance_up"}
TYPE_NAMES = {"image":"🖼 Картинки", "audio":"🎵 Музыка", "video":"🎬 Видео", "tts":"🗣 Озвучка", "stt":"📝 Расшифровка", "edit":"✏️ Редактор", "animate":"🎞 Оживление", "upscale":"🔍 Апскейл", "text":"💬 Текст"}

USER_COLS = (
    "username","is_banned","total_generated","free_image","free_audio","free_video",
    "balance_img","balance_aud","balance_vid","balance_tts","balance_stt",
    "balance_edit","balance_anim","balance_up","text_free_used","referrals","referrer_id","q_bought","reward_claimed",
    "sub_plan","sub_until","sub_used","sub_auto","sub_id","last_bonus","sub_notified",
    "onboarded","state","temp_model_id","temp_price","admin_state","admin_target","admin_ts",
    "last_seen", "sub_tokens_used"
)

_BALANCE_COLS = frozenset(BAL_FIELD.values())
_PERSONAL_CLEAR_COLS = tuple(c for c in USER_COLS if c not in _BALANCE_COLS and c not in {"sub_plan","sub_until","sub_used","sub_auto","sub_id"})
_STRING_COLS = {"username","sub_plan","sub_id","state","temp_model_id","admin_state"}

def moderation_check(text: str) -> bool:
    if not text or not text.strip(): return True
    if MODERATION_API_URL:
        headers = {"Content-Type": "application/json"}
        if MODERATION_API_KEY: headers["Authorization"] = f"Bearer {MODERATION_API_KEY}"
        try:
            r = requests.post(MODERATION_API_URL, json={"text": text}, headers=headers, timeout=HTTP_TIMEOUT_SHORT)
            if r.status_code == 200: return bool(r.json().get("allowed", True))
        except Exception: pass
    if MODERATION_REQUIRED: return False
    if MODERATION_FAIL_CLOSED: return False
    return True

# ==========================================================
# СЕТЬ / SSRF
# ==========================================================
_dns_cache = {}
_dns_lock = threading.Lock()

def _resolve_ips_cached(host: str) -> Tuple[float, set]:
    now = time.time()
    with _dns_lock:
        hit = _dns_cache.get(host)
        if hit and hit[0] > now: return hit
    try:
        infos = socket.getaddrinfo(host, None)
        ips = {info[4][0] for info in infos}
    except OSError: ips = set()
    entry = (now + DNS_CACHE_TTL, ips)
    with _dns_lock: _dns_cache[host] = entry
    return entry

def _ip_is_unsafe(ip: str) -> bool:
    try: a = ipaddress.ip_address(ip)
    except ValueError: return True
    return (a.is_private or a.is_loopback or a.is_link_local or a.is_multicast or a.is_reserved or a.is_unspecified)

def is_safe_url(url: str) -> bool:
    try: p = urlparse(url)
    except Exception: return False
    if p.scheme not in ("http", "https"): return False
    host = (p.hostname or "").lower()
    if not host or not any(host == d or host.endswith("." + d) for d in ALLOWED_CDN): return False
    _, ips = _resolve_ips_cached(host)
    if not ips: return False
    return not any(_ip_is_unsafe(ip) for ip in ips)

def _read_response(r, max_bytes: int, m_type: str) -> bytes:
    ct = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    prefixes = _EXPECTED_CT.get(m_type)
    if prefixes and ct and not any(ct.startswith(pref) for pref in prefixes): raise RuntimeError(f"unexpected ct {ct!r}")
    cl = r.headers.get("Content-Length")
    if cl:
        try:
            cl_i = int(cl)
            if cl_i < 0 or cl_i > max_bytes: raise RuntimeError("too big")
        except ValueError: pass
    buf = bytearray()
    for chunk in r.iter_content(chunk_size=64 * 1024):
        if not chunk: continue
        buf.extend(chunk)
        if len(buf) > max_bytes: raise RuntimeError("too big")
    return bytes(buf)

def fetch_media(url: str, max_bytes: int = FILE_MAX_MB * 1024 * 1024, m_type: str = "", _redirects: int = 0) -> bytes:
    if not is_safe_url(url): raise RuntimeError("unsafe url")
    for attempt in range(2):
        try:
            with requests.get(url, timeout=(5, 15), allow_redirects=False, stream=True,
                              headers={"User-Agent": "NeuroStudio/57 (+telegram)"}) as r:
                if 300 <= r.status_code < 400:
                    loc = r.headers.get("Location", "")
                    if not loc or _redirects >= 3 or not is_safe_url(loc): raise RuntimeError("unsafe redirect")
                    return fetch_media(loc, max_bytes, m_type, _redirects + 1)
                r.raise_for_status()
                return _read_response(r, max_bytes, m_type)
        except requests.exceptions.ConnectionError as e:
            if "Read timed out" in str(e) or "Connection aborted" in str(e):
                log.warning(f"fetch_media timeout (attempt {attempt+1}/2), retrying in 1s...")
                time.sleep(1)
                continue
            raise
    raise RuntimeError("failed to download media (server timeout)")

def download_tg_file(message) -> Optional[bytes]:
    try:
        if message.content_type == "photo": file_id = message.photo[-1].file_id
        else:
            obj = getattr(message, message.content_type, None)
            if obj is None: return None
            file_id = obj.file_id
        info = bot.get_file(file_id)
        if info.file_size and info.file_size > FILE_MAX_MB * 1024 * 1024: return None
        data = bot.download_file(info.file_path)
        if len(data) > FILE_MAX_MB * 1024 * 1024: return None
        return data
    except Exception: return None

# ==========================================================
# FX ANALYZER (USD/RUB realtime)
# ==========================================================
class FxAnalyzer:
    """Курс USD/RUB с кэшем в БД и фоновым обновлением."""
    _lock = threading.Lock()
    _rate: float = 0.0
    _ts: float = 0.0
    _last_good_ts: float = 0.0

    @classmethod
    def _load_from_db(cls) -> Tuple[float, float]:
        try:
            with DbConn() as c:
                cur = c.cursor()
                cur.execute("SELECT rate, ts FROM currency_rates WHERE pair='USD_RUB' ORDER BY ts DESC LIMIT 1")
                r = cur.fetchone()
                if r: return float(r[0]), float(r[1])
        except Exception:
            pass
        return 0.0, 0.0

    @classmethod
    def _save_to_db(cls, rate: float, ts: float):
        try:
            with DbConn() as c:
                cur = c.cursor()
                cur.execute("INSERT OR REPLACE INTO currency_rates(pair, rate, ts) VALUES(?,?,?)", ("USD_RUB", rate, ts))
        except Exception:
            log.exception("fx save")

    @classmethod
    def current(cls) -> float:
        with cls._lock:
            if cls._rate > 0: return cls._rate
        rate, ts = cls._load_from_db()
        with cls._lock:
            if rate > 0:
                cls._rate = rate; cls._ts = ts
                return rate
        return FX_FALLBACK_RATE

    @classmethod
    def rub_to_usd(cls, rub: int, markup_pct: float = None) -> float:
        rate = cls.current()
        if rate <= 0: rate = FX_FALLBACK_RATE
        markup = FX_MARKUP_PCT if markup_pct is None else markup_pct
        usd = float(rub) / rate
        return round(usd * (1.0 + markup / 100.0), 2)

    @classmethod
    def usd_to_rub(cls, usd: float) -> float:
        return round(float(usd) * cls.current(), 2)

    @classmethod
    def refresh(cls) -> bool:
        try:
            r = requests.get(FX_API_URL, timeout=HTTP_TIMEOUT_SHORT, headers={"User-Agent": "NeuroStudio/57"})
            if r.status_code != 200:
                log.warning(f"fx http {r.status_code}")
                return False
            j = r.json()
            val = j.get("Valute", {}).get("USD", {}).get("Value")
            if not val: 
                log.warning("fx: no USD value")
                return False
            rate = float(val)
            if rate < 10 or rate > 1000:
                log.warning(f"fx: suspicious rate {rate}")
                return False
            ts = time.time()
            with cls._lock:
                cls._rate = rate
                cls._ts = ts
                cls._last_good_ts = ts
            cls._save_to_db(rate, ts)
            log.info(f"fx: USD/RUB = {rate:.4f} ({datetime.fromtimestamp(ts):%H:%M:%S})")
            return True
        except Exception as e:
            log.warning(f"fx refresh failed: {e}")
            return False

    @classmethod
    def status(cls) -> dict:
        rate = cls.current()
        with cls._lock:
            ts = cls._ts
            last_good = cls._last_good_ts
        return {
            "rate": rate,
            "ts": ts,
            "age_sec": int(time.time() - ts) if ts else None,
            "last_good_ts": last_good,
        }

def start_fx_worker():
    def loop():
        # первый refresh сразу
        try: FxAnalyzer.refresh()
        except Exception: log.exception("fx first")
        while not SHUTDOWN.is_set():
            SHUTDOWN.wait(FX_REFRESH_SEC)
            if SHUTDOWN.is_set(): return
            try: FxAnalyzer.refresh()
            except Exception: log.exception("fx loop")
    threading.Thread(target=loop, daemon=True, name="fx").start()

# ==========================================================
# БАЗА ДАННЫХ
# ==========================================================
class Db:
    _pool: Optional[queue.Queue] = None
    _sem: Optional[threading.BoundedSemaphore] = None
    path: str = ""

    @classmethod
    def init(cls, path: str, size: int):
        cls.path = path
        cls._pool = queue.Queue(maxsize=size)
        cls._sem = threading.BoundedSemaphore(size)
        for _ in range(size): cls._pool.put(cls._make())

    @classmethod
    def _make(cls) -> sqlite3.Connection:
        c = sqlite3.connect(cls.path, timeout=30, isolation_level=None, check_same_thread=False)
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        c.execute("PRAGMA busy_timeout=30000")
        c.execute("PRAGMA foreign_keys=ON")
        return c

    @classmethod
    def acquire(cls) -> sqlite3.Connection:
        cls._sem.acquire()
        try: return cls._pool.get(timeout=30)
        except queue.Empty:
            cls._sem.release()
            raise

    @classmethod
    def release(cls, conn: sqlite3.Connection):
        try: cls._pool.put_nowait(conn)
        finally: cls._sem.release()

class DbConn:
    def __enter__(self) -> sqlite3.Connection:
        self.conn = Db.acquire()
        return self.conn
    def __exit__(self, *a):
        Db.release(self.conn)
        return False

def _add_column_if_missing(cur, table: str, col: str, decl: str):
    cur.execute(f"PRAGMA table_info({table})")
    if col not in {r[1] for r in cur.fetchall()}:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")

def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    with DbConn() as c:
        cur = c.cursor()
        cur.execute('''CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY, username TEXT, is_banned INTEGER NOT NULL DEFAULT 0,
            total_generated INTEGER NOT NULL DEFAULT 0, free_image INTEGER NOT NULL DEFAULT 0,
            free_audio INTEGER NOT NULL DEFAULT 0, free_video INTEGER NOT NULL DEFAULT 0,
            balance_img INTEGER NOT NULL DEFAULT 0, balance_aud INTEGER NOT NULL DEFAULT 0,
            balance_vid INTEGER NOT NULL DEFAULT 0, balance_tts INTEGER NOT NULL DEFAULT 0,
            balance_stt INTEGER NOT NULL DEFAULT 0, balance_edit INTEGER NOT NULL DEFAULT 0,
            balance_anim INTEGER NOT NULL DEFAULT 0, balance_up INTEGER NOT NULL DEFAULT 0,
            text_free_used INTEGER NOT NULL DEFAULT 0, referrals INTEGER NOT NULL DEFAULT 0,
            referrer_id INTEGER NOT NULL DEFAULT 0, q_bought INTEGER NOT NULL DEFAULT 0,
            reward_claimed INTEGER NOT NULL DEFAULT 0, sub_plan TEXT DEFAULT '',
            sub_until REAL NOT NULL DEFAULT 0, sub_used INTEGER NOT NULL DEFAULT 0,
            sub_auto INTEGER NOT NULL DEFAULT 0, sub_id TEXT DEFAULT '',
            last_bonus REAL NOT NULL DEFAULT 0, sub_notified INTEGER NOT NULL DEFAULT 0,
            onboarded INTEGER NOT NULL DEFAULT 0, state TEXT DEFAULT '',
            temp_model_id TEXT DEFAULT '', temp_price INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL DEFAULT 0, last_seen REAL NOT NULL DEFAULT 0,
            admin_state TEXT DEFAULT '', admin_target INTEGER NOT NULL DEFAULT 0,
            admin_ts REAL NOT NULL DEFAULT 0, sub_tokens_used INTEGER NOT NULL DEFAULT 0)''')

        _add_column_if_missing(cur, "users", "sub_tokens_used", "INTEGER NOT NULL DEFAULT 0")

        cur.execute('''CREATE TABLE IF NOT EXISTS models(model_id TEXT PRIMARY KEY, active INTEGER NOT NULL DEFAULT 1, price INTEGER NOT NULL DEFAULT 0, cost REAL NOT NULL DEFAULT 0)''')
        _add_column_if_missing(cur, "models", "provider", "TEXT DEFAULT 'polza'")
        cur.execute('''CREATE TABLE IF NOT EXISTS payments(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, package_id TEXT NOT NULL,
            amount INTEGER NOT NULL, status TEXT NOT NULL, platega_id TEXT, ts REAL NOT NULL,
            kind TEXT NOT NULL DEFAULT 'package')''')

        _add_column_if_missing(cur, "payments", "provider", "TEXT NOT NULL DEFAULT 'platega'")
        _add_column_if_missing(cur, "payments", "invoice_payload", "TEXT DEFAULT ''")
        _add_column_if_missing(cur, "payments", "stars_amount", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(cur, "payments", "refunded_at", "REAL NOT NULL DEFAULT 0")
        _add_column_if_missing(cur, "payments", "idempotency_key", "TEXT DEFAULT ''")
        _add_column_if_missing(cur, "payments", "provider_charge_id", "TEXT DEFAULT ''")
        _add_column_if_missing(cur, "payments", "amount_usd", "REAL NOT NULL DEFAULT 0")
        _add_column_if_missing(cur, "payments", "fx_rate", "REAL NOT NULL DEFAULT 0")
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_payments_platega ON payments(platega_id) WHERE platega_id IS NOT NULL AND platega_id != ''")
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_payments_invoice ON payments(invoice_payload) WHERE invoice_payload IS NOT NULL AND invoice_payload != ''")
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_payments_idem ON payments(idempotency_key) WHERE idempotency_key IS NOT NULL AND idempotency_key != ''")
        cur.execute('''CREATE TABLE IF NOT EXISTS logs(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, action TEXT, details TEXT, ts REAL NOT NULL)''')
        cur.execute('''CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT)''')
        cur.execute('''CREATE TABLE IF NOT EXISTS works(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, m_type TEXT NOT NULL, model_id TEXT, prompt TEXT, file_id TEXT, ts REAL NOT NULL)''')
        cur.execute('''CREATE TABLE IF NOT EXISTS rate(user_id INTEGER NOT NULL, ts REAL NOT NULL)''')
        cur.execute('''CREATE TABLE IF NOT EXISTS transactions(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, m_type TEXT NOT NULL, model_id TEXT, status TEXT NOT NULL, ts REAL NOT NULL, resolved_ts REAL NOT NULL DEFAULT 0, reason TEXT DEFAULT '', payment_id INTEGER, charged INTEGER NOT NULL DEFAULT 0)''')
        cur.execute('''CREATE TABLE IF NOT EXISTS chat_history(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL, ts REAL NOT NULL)''')
        cur.execute('''CREATE TABLE IF NOT EXISTS outbox(id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER NOT NULL, text TEXT NOT NULL, kwargs TEXT NOT NULL DEFAULT '{}', ts REAL NOT NULL, sent_at REAL NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0)''')
        _add_column_if_missing(cur, "outbox", "next_try", "REAL NOT NULL DEFAULT 0")
        cur.execute('''CREATE TABLE IF NOT EXISTS payment_poll_state(platega_id TEXT PRIMARY KEY, errors INTEGER NOT NULL DEFAULT 0, next_try REAL NOT NULL DEFAULT 0, last_checked REAL NOT NULL DEFAULT 0)''')
        cur.execute('''CREATE TABLE IF NOT EXISTS payment_events(id INTEGER PRIMARY KEY AUTOINCREMENT, provider TEXT NOT NULL, ref TEXT NOT NULL, event TEXT NOT NULL, details TEXT DEFAULT '', ts REAL NOT NULL)''')
        cur.execute('''CREATE TABLE IF NOT EXISTS currency_rates(pair TEXT PRIMARY KEY, rate REAL NOT NULL, ts REAL NOT NULL)''')

        for mid, m in MODELS.items():
            cur.execute("INSERT OR IGNORE INTO models(model_id, active, price, cost, provider) VALUES(?,?,?,?,?)",
                        (mid, m["active"], m["price"], m["cost"], m.get("provider", "polza")))
        for k, v in {"payments_on":"1","generations_on":"1","schema_version":"57"}.items():
            cur.execute("INSERT OR IGNORE INTO settings VALUES(?,?)", (k, v))

def get_user(uid: int) -> Optional[dict]:
    with DbConn() as c:
        cur = c.cursor()
        cur.execute(f"SELECT {','.join(USER_COLS)} FROM users WHERE user_id=?", (uid,))
        r = cur.fetchone()
    if not r: return None
    d = dict(zip(USER_COLS, r)); d["is_banned"] = bool(d["is_banned"]); return d

def add_user(uid: int, uname: str, ref: int = 0):
    with DbConn() as c:
        cur = c.cursor()
        cur.execute("INSERT OR IGNORE INTO users(user_id,username,referrer_id,created_at,last_seen) VALUES(?,?,?,?,?)", (uid, uname, ref, time.time(), time.time()))

def upd(uid: int, **kw):
    if not kw: return
    for k in kw:
        if k not in USER_COLS: raise ValueError(f"forbidden column: {k}")
    cols = ", ".join(f"{k}=?" for k in kw)
    with DbConn() as c:
        cur = c.cursor(); cur.execute(f"UPDATE users SET {cols} WHERE user_id=?", (*kw.values(), uid))

def incr_field(uid: int, field: str, by: int = 1):
    if field not in USER_COLS: raise ValueError(f"forbidden field: {field}")
    with DbConn() as c:
        cur = c.cursor(); cur.execute(f"UPDATE users SET {field}={field}+? WHERE user_id=?", (by, uid))

def take_free_image(uid: int) -> bool:
    with DbConn() as c:
        cur = c.cursor(); cur.execute("UPDATE users SET free_image=free_image-1 WHERE user_id=? AND free_image>0", (uid,)); return cur.rowcount == 1

def consume_sub_slot(uid: int, plan_limit: int) -> bool:
    with DbConn() as c:
        cur = c.cursor(); cur.execute("UPDATE users SET sub_used=sub_used+1 WHERE user_id=? AND sub_used<?", (uid, plan_limit)); return cur.rowcount == 1

def consume_text_slot(uid: int, limit: int) -> bool:
    with DbConn() as c:
        cur = c.cursor(); cur.execute("UPDATE users SET text_free_used=text_free_used+1 WHERE user_id=? AND text_free_used<?", (uid, limit)); return cur.rowcount == 1

def set_state(uid: int, state: str, mid: str = "", price: int = 0): upd(uid, state=state, temp_model_id=mid, temp_price=price)
def incr_generated(uid: int): incr_field(uid, "total_generated", 1)
def log_ev(uid: int, action: str, details: str = ""):
    with DbConn() as c:
        cur = c.cursor(); cur.execute("INSERT INTO logs(user_id,action,details,ts) VALUES(?,?,?,?)", (uid, action, (details or "")[:500], time.time()))

def payment_event(provider: str, ref: str, event: str, details: str = ""):
    with DbConn() as c:
        cur = c.cursor(); cur.execute("INSERT INTO payment_events(provider,ref,event,details,ts) VALUES(?,?,?,?,?)",
                                       (provider, (ref or "")[:120], event, (details or "")[:500], time.time()))

def setting(k: str, d: str = "1") -> str:
    with DbConn() as c:
        cur = c.cursor(); cur.execute("SELECT value FROM settings WHERE key=?", (k,)); r = cur.fetchone()
    return r[0] if r else d

def set_setting(k: str, v: str):
    with DbConn() as c:
        cur = c.cursor(); cur.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (k, v))

def get_model(mid: str) -> Optional[dict]:
    with DbConn() as c:
        cur = c.cursor(); cur.execute("SELECT active,price,cost FROM models WHERE model_id=?", (mid,)); r = cur.fetchone()
    return {"active":r[0],"price":r[1],"cost":r[2]} if r else None

def active_by_type(m_type: str) -> dict:
    ids = [mid for mid, m in MODELS.items() if m["type"] == m_type]
    if not ids: return {}
    ph = ",".join("?" * len(ids))
    with DbConn() as c:
        cur = c.cursor(); cur.execute(f"SELECT model_id, price FROM models WHERE active=1 AND model_id IN ({ph})", ids); return dict(cur.fetchall())

def add_work(uid: int, m_type: str, model_id: str, prompt: str, file_id: str):
    with DbConn() as c:
        cur = c.cursor()
        cur.execute("INSERT INTO works(user_id,m_type,model_id,prompt,file_id,ts) VALUES(?,?,?,?,?,?)", (uid, m_type, model_id, (prompt or "")[:500], file_id, time.time()))
        cur.execute(f"DELETE FROM works WHERE user_id=? AND id NOT IN (SELECT id FROM works WHERE user_id=? ORDER BY id DESC LIMIT {WORKS_PER_USER})", (uid, uid))

def check_and_add_rate(uid: int, limit: int) -> bool:
    now = time.time(); cutoff = now - 3600
    with DbConn() as c:
        cur = c.cursor()
        cur.execute(f"DELETE FROM rate WHERE rowid IN (SELECT rowid FROM rate WHERE user_id=? AND ts<? LIMIT {RATE_CLEANUP_BATCH})", (uid, cutoff))
        cur.execute("INSERT INTO rate(user_id, ts) SELECT ?, ? WHERE (SELECT COUNT(*) FROM rate WHERE user_id=? AND ts>=?) < ?", (uid, now, uid, cutoff, limit))
        return cur.rowcount == 1

def sub_active(u: dict) -> bool: return bool(u["sub_plan"]) and u["sub_until"] > time.time()
def sub_can_use(u: dict):
    if not sub_active(u): return False, "нет подписки"
    t = SUB_TARIFFS.get(u["sub_plan"])
    if not t: return False, "неизвестный тариф"
    if u["sub_used"] >= t["limit"]: return False, f"лимит {t['limit']}/мес"
    return True, ""

def get_chat_history(uid: int, limit: int = MAX_HISTORY) -> list:
    with DbConn() as c:
        cur = c.cursor(); cur.execute("SELECT role, content FROM chat_history WHERE user_id=? ORDER BY id DESC LIMIT ?", (uid, limit)); rows = cur.fetchall()
    rows.reverse(); return [{"role": r, "content": c} for r, c in rows]

def append_chat(uid: int, role: str, content: str):
    with DbConn() as c:
        cur = c.cursor()
        cur.execute("INSERT INTO chat_history(user_id, role, content, ts) VALUES(?,?,?,?)", (uid, role, content, time.time()))
        cur.execute("DELETE FROM chat_history WHERE user_id=? AND id NOT IN (SELECT id FROM chat_history WHERE user_id=? ORDER BY id DESC LIMIT ?)", (uid, uid, MAX_HISTORY))

def clear_chat_history(uid: int):
    with DbConn() as c:
        cur = c.cursor(); cur.execute("DELETE FROM chat_history WHERE user_id=?", (uid,))

def cleanup_old_data():
    now = time.time()
    with DbConn() as c:
        cur = c.cursor()
        for tbl, cutoff in (("works", now - WORKS_RETENTION_DAYS * 86400), ("rate", now - 7200), ("logs", now - WORKS_RETENTION_DAYS * 86400), ("payment_events", now - WORKS_RETENTION_DAYS * 86400)):
            while not SHUTDOWN.is_set():
                cur.execute(f"DELETE FROM {tbl} WHERE rowid IN (SELECT rowid FROM {tbl} WHERE ts < ? LIMIT {CLEANUP_BATCH})", (cutoff,))
                if cur.rowcount < CLEANUP_BATCH: break
        old_payments_cutoff = now - 365 * 86400
        cur.execute("DELETE FROM payments WHERE ts < ? AND status IN ('REFUNDED', 'EXPIRED')", (old_payments_cutoff,))
        cur.execute("DELETE FROM payment_poll_state WHERE last_checked < ? AND last_checked > 0", (now - 7 * 86400,))

def start_cleanup_worker():
    def loop():
        while not SHUTDOWN.is_set():
            try: cleanup_old_data()
            except Exception: log.exception("cleanup")
            SHUTDOWN.wait(3600)
    threading.Thread(target=loop, daemon=True, name="cleanup").start()

# ==========================================================
# ФИНАНСЫ
# ==========================================================
class InsufficientFunds(Exception): pass

class Finance:
    @staticmethod
    def begin(uid: int, m_type: str, model_id: str, paid_by: str) -> int:
        with DbConn() as c:
            cur = c.cursor()
            try:
                cur.execute("BEGIN IMMEDIATE")
                charged = 0
                if paid_by == "balance":
                    col = BAL_FIELD.get(m_type)
                    if not col: raise InsufficientFunds(f"no balance col for {m_type}")
                    cur.execute(f"UPDATE users SET {col}={col}-1 WHERE user_id=? AND {col}>0", (uid,))
                    if cur.rowcount != 1: raise InsufficientFunds(m_type)
                    charged = 1
                elif paid_by == "sub":
                    # слот уже списан в _charge, но помечаем charged=1 чтобы refund знал
                    charged = 2
                cur.execute("INSERT INTO transactions(user_id,m_type,model_id,status,ts,charged) VALUES(?,?,?,?,?,?)", (uid, m_type, model_id, "PENDING", time.time(), charged))
                tx_id = cur.lastrowid
                cur.execute("COMMIT")
                return tx_id
            except Exception:
                try: cur.execute("ROLLBACK")
                except Exception: pass
                raise

    @staticmethod
    def ok(tx_id: int):
        with DbConn() as c:
            cur = c.cursor(); cur.execute("UPDATE transactions SET status='OK', resolved_ts=? WHERE id=? AND status='PENDING'", (time.time(), tx_id))

    @staticmethod
    def refund(tx_id: int, reason: str = "") -> bool:
        with DbConn() as c:
            cur = c.cursor()
            try:
                cur.execute("BEGIN IMMEDIATE")
                cur.execute("SELECT user_id, m_type, charged FROM transactions WHERE id=? AND status='PENDING'", (tx_id,))
                r = cur.fetchone()
                if not r:
                    cur.execute("ROLLBACK"); return False
                uid, m_type, charged = r
                if charged == 1:
                    col = BAL_FIELD.get(m_type)
                    if col: cur.execute(f"UPDATE users SET {col}={col}+1 WHERE user_id=?", (uid,))
                elif charged == 2:
                    # вернуть слот подписки
                    cur.execute("UPDATE users SET sub_used=MAX(0, sub_used-1) WHERE user_id=?", (uid,))
                cur.execute("UPDATE transactions SET status='REFUNDED', resolved_ts=?, reason=? WHERE id=?", (time.time(), (reason or "")[:200], tx_id))
                cur.execute("COMMIT")
                return True
            except Exception:
                try: cur.execute("ROLLBACK")
                except Exception: pass
                raise

def recover_stuck_transactions():
    cutoff = time.time() - STUCK_TX_TIMEOUT
    with DbConn() as c:
        cur = c.cursor()
        cur.execute("""SELECT t.id, t.payment_id FROM transactions t
                       LEFT JOIN payments p ON p.id = t.payment_id
                       WHERE t.status='PENDING' AND t.ts < ?
                       AND (t.payment_id IS NULL OR p.id IS NULL OR p.status != 'PENDING')""", (cutoff,))
        ids = [r[0] for r in cur.fetchall()]
        cur.execute("UPDATE payments SET status='EXPIRED' WHERE status='PENDING' AND ts < ?", (cutoff,))
    for tid in ids:
        try: Finance.refund(tid, "recovered_stuck")
        except Exception: log.exception(f"recover tx {tid} failed")

def start_recovery_worker():
    def loop():
        while not SHUTDOWN.is_set():
            try: recover_stuck_transactions()
            except Exception: log.exception("recovery")
            SHUTDOWN.wait(60)
    threading.Thread(target=loop, daemon=True, name="recovery").start()

# ==========================================================
# ОПЛАТА
# ==========================================================
def _apply_payment_tx(cur, kind: str, item_id: str, uid: int, payment_row_id: int):
    # гарантируем, что юзер есть в БД (fallback для Grosh-вебхуков)
    cur.execute("INSERT OR IGNORE INTO users(user_id, created_at, last_seen) VALUES(?,?,?)", (uid, time.time(), time.time()))
    if kind == "package":
        p = PACKAGES.get(item_id)
        if not p: raise RuntimeError(f"unknown package {item_id}")
        col = BAL_FIELD[p["type"]]
        cur.execute(f"UPDATE users SET {col}={col}+? WHERE user_id=?", (p["count"], uid))
        if cur.rowcount != 1: raise RuntimeError(f"apply package failed uid={uid}")
        msg = f"✅ Оплата «{p['title']}» зачислена! Баланс пополнен.\n\n🧾 Чек: pay#{payment_row_id}"
    elif kind == "subscription":
        t = SUB_TARIFFS.get(item_id)
        if not t: raise RuntimeError(f"unknown tariff {item_id}")
        cur.execute("UPDATE users SET sub_plan=?, sub_until=?, sub_used=0 WHERE user_id=?", (item_id, time.time() + t["days"]*86400, uid))
        if cur.rowcount != 1: raise RuntimeError(f"apply sub failed uid={uid}")
        msg = f"✅ Подписка «{t['title']}» активирована на {t['days']} дней!\n\n🧾 Чек: pay#{payment_row_id}"
    elif kind == "text_sub":
        t = TEXT_SUB_TARIFFS.get(item_id)
        if not t: raise RuntimeError(f"unknown text sub {item_id}")
        cur.execute("UPDATE users SET sub_plan=?, sub_until=?, sub_used=0, sub_tokens_used=0 WHERE user_id=?", (item_id, time.time() + t["days"]*86400, uid))
        if cur.rowcount != 1: raise RuntimeError(f"apply text_sub failed uid={uid}")
        msg = f"✅ Текстовая подписка «{t['title']}» активирована! ({t['tokens']:,} токенов)\n\n🧾 Чек: pay#{payment_row_id}"
    else:
        raise RuntimeError(f"unknown kind {kind}")
    cur.execute("INSERT INTO logs(user_id,action,details,ts) VALUES(?,?,?,?)", (uid, "payment_paid", f"{kind}:{item_id} pay#{payment_row_id}", time.time()))
    cur.execute("INSERT INTO outbox(uid,text,kwargs,ts,next_try) VALUES(?,?,?,?,?)", (uid, msg, "{}", time.time(), time.time()))

def apply_payment_atomic_platega(platega_id: str) -> bool:
    with DbConn() as c:
        cur = c.cursor()
        try:
            cur.execute("BEGIN IMMEDIATE")
            cur.execute("SELECT id, user_id, package_id, kind FROM payments WHERE platega_id=? AND provider='platega' AND status IN ('PENDING', 'EXPIRED')", (platega_id,))
            row = cur.fetchone()
            if not row: cur.execute("ROLLBACK"); return False
            pay_id, uid, pid, kind = row
            cur.execute("UPDATE payments SET status='PAID' WHERE id=? AND status IN ('PENDING','EXPIRED')", (pay_id,))
            if cur.rowcount != 1: cur.execute("ROLLBACK"); return False
            _apply_payment_tx(cur, kind, pid, uid, pay_id)
            cur.execute("COMMIT")
            payment_event("platega", platega_id, "paid", f"pay#{pay_id}")
            return True
        except Exception:
            try: cur.execute("ROLLBACK")
            except Exception: pass
            log.exception(f"apply_payment_atomic_platega {platega_id}")
            return False

def apply_payment_atomic_stars(invoice_payload: str, tg_charge_id: str, total_amount: int, currency: str) -> Tuple[bool, str]:
    if not tg_charge_id: return False, "empty_charge_id"
    with DbConn() as c:
        cur = c.cursor()
        try:
            cur.execute("BEGIN IMMEDIATE")
            cur.execute("SELECT id, user_id, package_id, kind, stars_amount FROM payments WHERE invoice_payload=? AND provider='stars'", (invoice_payload,))
            row = cur.fetchone()
            if not row: cur.execute("ROLLBACK"); return False, "unknown_payload"
            pay_id, uid, pid, kind, expected_stars = row
            if int(total_amount) != int(expected_stars): cur.execute("ROLLBACK"); return False, "amount_mismatch"
            if (currency or "").upper() != "XTR": cur.execute("ROLLBACK"); return False, "currency_mismatch"
            cur.execute("UPDATE payments SET status='PAID', provider_charge_id=? WHERE id=? AND status='PENDING'", (tg_charge_id, pay_id))
            if cur.rowcount != 1: cur.execute("ROLLBACK"); return False, "already_paid"
            _apply_payment_tx(cur, kind, pid, uid, pay_id)
            cur.execute("COMMIT")
            log_ev(uid, "stars_payment", f"{kind}:{pid} charge={tg_charge_id} pay#{pay_id}")
            payment_event("stars", invoice_payload, "paid", f"pay#{pay_id} charge={tg_charge_id}")
            return True, "ok"
        except Exception:
            try: cur.execute("ROLLBACK")
            except Exception: pass
            log.exception(f"apply_payment_atomic_stars {invoice_payload}")
            return False, "exception"

def apply_payment_atomic_grosh(tx_id: str, remote_amount: Optional[float] = None, remote_currency: Optional[str] = None) -> bool:
    if not tx_id: return False
    with DbConn() as c:
        cur = c.cursor()
        try:
            cur.execute("BEGIN IMMEDIATE")
            cur.execute("SELECT id, user_id, package_id, kind, amount_usd FROM payments WHERE platega_id=? AND provider='grosh' AND status IN ('PENDING','EXPIRED')", (tx_id,))
            row = cur.fetchone()
            if not row: cur.execute("ROLLBACK"); return False
            pay_id, uid, pid, kind, expected_usd = row
            if remote_amount is not None and expected_usd and float(expected_usd) > 0:
                try:
                    got = float(remote_amount)
                    exp = float(expected_usd)
                    if abs(got - exp) > 0.05:
                        log.error(f"grosh amount mismatch {tx_id}: local={exp} remote={got}")
                        cur.execute("ROLLBACK"); return False
                except (TypeError, ValueError):
                    cur.execute("ROLLBACK"); return False
            if remote_currency and remote_currency.upper() not in ("USD", "USDT"):
                log.warning(f"grosh currency {remote_currency} for {tx_id}, expected USD")
            cur.execute("UPDATE payments SET status='PAID' WHERE id=? AND status IN ('PENDING','EXPIRED')", (pay_id,))
            if cur.rowcount != 1: cur.execute("ROLLBACK"); return False
            _apply_payment_tx(cur, kind, pid, uid, pay_id)
            cur.execute("COMMIT")
            payment_event("grosh", tx_id, "paid", f"pay#{pay_id}")
            return True
        except Exception:
            try: cur.execute("ROLLBACK")
            except Exception: pass
            log.exception(f"apply_payment_atomic_grosh {tx_id}")
            return False

def check_payment_status(tx_id: str) -> dict:
    headers = {"X-MerchantId": PLATEGA_ID, "X-Secret": PLATEGA_SECRET}
    try:
        r = requests.get(f"{PLATEGA_URL}/v2/transaction/{tx_id}", headers=headers, timeout=HTTP_TIMEOUT_SHORT)
        if r.status_code != 200: return {"status": "ERROR"}
        return r.json()
    except Exception: return {"status": "ERROR"}

def _poll_one_payment(tx_id: str) -> None:
    j = check_payment_status(tx_id)
    st = (j.get("status") or "PENDING").upper()
    if st == "CONFIRMED":
        with DbConn() as c:
            cur = c.cursor(); cur.execute("SELECT amount FROM payments WHERE platega_id=?", (tx_id,)); row = cur.fetchone()
            if row:
                local_amount = row[0]; remote_amount = (j.get("paymentDetails") or {}).get("amount")
                if remote_amount and int(remote_amount) != int(local_amount):
                    log.error(f"platega amount mismatch {tx_id}: local={local_amount} remote={remote_amount}")
                    notify(ADMIN_ID, f"⚠️ MISMATCH Platega {tx_id}: {local_amount} vs {remote_amount}"); return
        success = apply_payment_atomic_platega(tx_id)
        if success:
            with DbConn() as c: c.cursor().execute("DELETE FROM payment_poll_state WHERE platega_id=?", (tx_id,))
    elif st in ("CANCELED", "CHARGEBACKED"):
        with DbConn() as c:
            cur = c.cursor(); cur.execute("BEGIN IMMEDIATE")
            cur.execute("SELECT id, user_id, package_id, kind FROM payments WHERE platega_id=? AND status IN ('PENDING', 'EXPIRED')", (tx_id,))
            r = cur.fetchone()
            if r:
                pay_id, uid, pid, kind = r; cur.execute("UPDATE payments SET status=? WHERE id=?", (st, pay_id))
                log_ev(uid, "payment_canceled", f"{kind}:{pid} {tx_id}"); payment_event("platega", tx_id, "canceled", f"pay#{pay_id} status={st}")
                try: notify(uid, f"⚠️ Платёж не прошёл (статус {st}). Если деньги списались — напиши в поддержку: {SUPPORT_URL}")
                except Exception: pass
            cur.execute("DELETE FROM payment_poll_state WHERE platega_id=?", (tx_id,)); cur.execute("COMMIT")
    elif st == "ERROR":
        with DbConn() as c:
            cur = c.cursor(); cur.execute("BEGIN IMMEDIATE")
            cur.execute("SELECT errors FROM payment_poll_state WHERE platega_id=?", (tx_id,)); r = cur.fetchone()
            errs = (r[0] if r else 0) + 1
            backoff = PAYMENT_POLL_BACKOFF_MAX if errs >= PAYMENT_POLL_MAX_ERRORS else min(PAYMENT_POLL_BACKOFF_MAX, 2 ** errs)
            cur.execute("INSERT OR REPLACE INTO payment_poll_state(platega_id,errors,next_try,last_checked) VALUES(?,?,?,?)", (tx_id, errs, time.time() + backoff, time.time()))
            cur.execute("COMMIT")

def _poll_future_done(fut):
    try: fut.result()
    except Exception: pass

def payment_poller_single_loop():
    while not SHUTDOWN.is_set():
        SHUTDOWN.wait(PAYMENT_POLL_INTERVAL)
        if SHUTDOWN.is_set(): return
        try:
            horizon = time.time() - PAYMENT_POLL_TIMEOUT; now = time.time()
            with DbConn() as c:
                cur = c.cursor()
                cur.execute("""SELECT p.platega_id, p.user_id FROM payments p
                               LEFT JOIN payment_poll_state s ON s.platega_id = p.platega_id
                               WHERE p.status='PENDING' AND p.provider='platega' AND p.ts > ?
                               AND (s.next_try IS NULL OR s.next_try <= ?)""", (horizon, now))
                rows = cur.fetchall()
            for tx_id, _ in rows:
                try: PAY_EXECUTOR.submit(_poll_one_payment, tx_id).add_done_callback(_poll_future_done)
                except Exception: pass
        except Exception: log.exception("payment_poller loop")

def create_platega_payment(uid: int, item_id: str, amount: int, desc: str, kind: str, prefix: str, idem_key: str = "") -> bool:
    if not (PLATEGA_ID and PLATEGA_SECRET): return False
    if not RETURN_URL: return False
    order_uuid = str(uuid.uuid4()); payload_str = f"{uid}_{prefix}_{item_id}_{int(time.time())}"
    payload = {"paymentMethod": 2, "id": order_uuid, "paymentDetails": {"amount": amount, "currency": "RUB"}, "description": desc, "return": RETURN_URL, "failedUrl": RETURN_URL, "payload": payload_str}
    headers = {"X-MerchantId": PLATEGA_ID, "X-Secret": PLATEGA_SECRET}
    try:
        r = requests.post(f"{PLATEGA_URL}/v2/transaction/process", json=payload, headers=headers, timeout=HTTP_TIMEOUT_SHORT)
        if r.status_code != 200: return False
        j = r.json(); pay_url, tx_id = j.get("url"), j.get("transactionId")
        if not pay_url or not tx_id: return False
        with DbConn() as c:
            cur = c.cursor()
            try: cur.execute("INSERT INTO payments(user_id,package_id,amount,status,platega_id,ts,kind,provider,idempotency_key) VALUES(?,?,?,?,?,?,?, 'platega', ?)", (uid, item_id, amount, "PENDING", tx_id, time.time(), kind, idem_key or ""))
            except sqlite3.IntegrityError: return False
        kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("💳 Оплатить (СБП)", url=pay_url))
        notify(uid, f"💳 {desc} — {amount}₽\n\n🧾 Заказ: {tx_id}\n\n<i>После оплаты нажми «Проверить» через минуту.</i>", reply_markup=kb.to_dict())
        log_ev(uid, "payment_created", f"platega {kind}:{item_id} {tx_id}"); payment_event("platega", tx_id, "created", f"user={uid} {kind}:{item_id}")
        return True
    except Exception: log.exception(f"create_platega_payment {uid} {item_id}"); return False

def create_grosh_payment(uid: int, item_id: str, amount_rub: int, desc: str, kind: str, prefix: str, idem_key: str = "") -> bool:
    """
    Grosh принимает USD. Конвертируем рубли в USD по курсу ЦБ + FX_MARKUP_PCT.
    В payments пишем рубли (amount) и USD (amount_usd) + курс (fx_rate).
    """
    if not GROSH_API_KEY or not GROSH_API_URL:
        log.error("GROSH_API_KEY или GROSH_API_URL не заданы")
        return False
    if not RETURN_URL:
        log.error("Grosh: RETURN_URL пуст — вебхук невозможен, платёж не создаём")
        return False

    fx_rate = FxAnalyzer.current()
    if fx_rate <= 0:
        log.error("Grosh: нет курса USD/RUB")
        return False
    amount_usd = FxAnalyzer.rub_to_usd(amount_rub)
    if amount_usd <= 0:
        log.error(f"Grosh: некорректная сумма {amount_rub}₽ → {amount_usd}$")
        return False

    # Grosh принимает amount в USD (валюту передачи в явном виде не документирует,
    # но по факту работает в USD/USDT).
    payload = {
        "amount": amount_usd,
        "currency": "USD",
        "label": desc,
        "payload": f"{uid}_{prefix}_{item_id}",
        "webhook": f"{RETURN_URL}/webhook/grosh",
        "success_url": RETURN_URL,
    }
    headers = {
        "Authorization": f"Bearer {GROSH_API_KEY}",
        "Content-Type": "application/json"
    }
    try:
        r = requests.post(f"{GROSH_API_URL}/payments", json=payload, headers=headers, timeout=HTTP_TIMEOUT_SHORT)
        if r.status_code not in (200, 201):
            log.error(f"grosh error: {r.status_code} {r.text[:300]}")
            return False

        j = r.json()
        pay_url = j.get("url") or j.get("pay_url") or j.get("payment_url")
        tx_id = j.get("id") or j.get("transaction_id")

        if not pay_url:
            log.error(f"grosh response missing url: {j}")
            return False
        if not tx_id:
            # без реального id Grosh вебхук не сопоставить — не создаём платёж
            log.error(f"grosh response missing id (no tx_id): {j}")
            return False

        with DbConn() as c:
            cur = c.cursor()
            try:
                cur.execute("""INSERT INTO payments(user_id, package_id, amount, status, platega_id, ts, kind, provider, idempotency_key, amount_usd, fx_rate)
                               VALUES(?,?,?,?,?,?,?, 'grosh', ?, ?, ?)""",
                            (uid, item_id, int(amount_rub), "PENDING", str(tx_id), time.time(), kind, idem_key or "", float(amount_usd), float(fx_rate)))
            except sqlite3.IntegrityError:
                log.warning(f"duplicate grosh tx {tx_id}")
                return False

        kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton(f"💳 Оплатить ${amount_usd:.2f} (Grosh)", url=pay_url))
        notify(uid,
               f"💳 {desc}\n"
               f"К оплате: <b>{amount_rub}₽</b> ≈ <b>${amount_usd:.2f}</b>\n"
               f"Курс: 1$ = {fx_rate:.2f}₽ (+{FX_MARKUP_PCT:.1f}%)\n\n"
               f"🧾 Заказ: {tx_id}",
               reply_markup=kb.to_dict())
        log_ev(uid, "payment_created", f"grosh {kind}:{item_id} {tx_id} ${amount_usd}")
        payment_event("grosh", str(tx_id), "created", f"user={uid} {kind}:{item_id} usd={amount_usd} fx={fx_rate}")
        return True
    except Exception as e:
        log.exception(f"create_grosh_payment {uid} {item_id}: {e}")
        return False

def create_stars_invoice(uid: int, item_id: str, amount_rub: int, desc: str, kind: str) -> bool:
    if amount_rub <= 0: return False
    stars_amount = max(1, int(round(amount_rub / STARS_RUB_PER_STAR)))
    invoice_payload = f"stars_{kind}_{item_id}_{uid}_{uuid.uuid4().hex[:12]}"
    with DbConn() as c:
        cur = c.cursor()
        try: cur.execute("INSERT INTO payments(user_id,package_id,amount,status,platega_id,ts,kind,provider,invoice_payload,stars_amount) VALUES(?,?,?,?,?,?,?, 'stars', ?, ?)", (uid, item_id, amount_rub, "PENDING", None, time.time(), kind, invoice_payload, stars_amount))
        except sqlite3.IntegrityError: return False
    prices = [types.LabeledPrice(label=desc, amount=stars_amount)]
    try:
        bot.send_invoice(chat_id=uid, title=desc, description=f"Оплата через Telegram Stars: {desc}", invoice_payload=invoice_payload, provider_token="", currency="XTR", prices=prices)
        log_ev(uid, "stars_invoice_created", f"{kind}:{item_id} {stars_amount} stars"); payment_event("stars", invoice_payload, "created", f"user={uid} {kind}:{item_id} stars={stars_amount}")
        return True
    except Exception:
        with DbConn() as c: c.cursor().execute("DELETE FROM payments WHERE invoice_payload=? AND status='PENDING'", (invoice_payload,))
        return False

def refund_stars(uid: int, charge_id: str) -> bool:
    if not STARS_AUTO_REFUND or not charge_id: return False
    try:
        ok = bot.refund_star_payment(user_id=uid, telegram_payment_charge_id=charge_id)
        payment_event("stars", charge_id, "refunded" if ok else "refund_failed", f"user={uid}"); return bool(ok)
    except Exception: payment_event("stars", charge_id, "refund_exception", f"user={uid}"); return False

# ==========================================================
# SAFE SEND/EDIT
# ==========================================================
def _retry_after_seconds(e: Exception) -> Optional[int]:
    try:
        data = getattr(e, "result_json", None) or getattr(e, "json", None) or {}
        ra = data.get("parameters", {}).get("retry_after"); return int(ra) if ra else None
    except Exception: return None

def _rebuild_markup(kwargs: dict) -> dict:
    kw = dict(kwargs); rm = kw.get("reply_markup")
    if isinstance(rm, dict):
        try: kw["reply_markup"] = types.InlineKeyboardMarkup.de_json(rm)
        except Exception: kw.pop("reply_markup", None)
    return kw

def safe_send(uid: int, text: str, **kwargs):
    kwargs = _rebuild_markup(kwargs)
    for attempt in range(3):
        try: return bot.send_message(uid, text, **kwargs)
        except ApiTelegramException as e:
            ra = _retry_after_seconds(e)
            if ra is not None and attempt < 2: time.sleep(min(ra, 5)); continue
            return None
        except Exception: return None
    return None

def safe_send_media(uid: int, kind: str, file_obj, **kwargs):
    fn = getattr(bot, f"send_{kind}", None)
    if fn is None: return None
    kwargs = _rebuild_markup(kwargs)
    for attempt in range(3):
        try: return fn(uid, file_obj, **kwargs)
        except ApiTelegramException as e:
            ra = _retry_after_seconds(e)
            if ra is not None and attempt < 2: time.sleep(min(ra, 5)); continue
            return None
        except Exception: return None
    return None

def safe_edit(uid: int, msg_id: int, text: str, **kwargs):
    kwargs = _rebuild_markup(kwargs)
    for attempt in range(3):
        try: bot.edit_message_text(text, uid, msg_id, **kwargs); return
        except ApiTelegramException as e:
            s = str(e).lower()
            if "message is not modified" in s: return
            ra = _retry_after_seconds(e)
            if ra is not None and attempt < 2: time.sleep(min(ra, 5)); continue
            return
        except Exception: return

# ==========================================================
# OUTBOX
# ==========================================================
def notify(uid: int, text: str, **kwargs):
    with DbConn() as c:
        cur = c.cursor()
        cur.execute("INSERT INTO outbox(uid,text,kwargs,ts,next_try) VALUES(?,?,?,?,?)", (uid, text, json.dumps(kwargs, ensure_ascii=False, default=str), time.time(), time.time()))

def start_notify_worker():
    def loop():
        while not SHUTDOWN.is_set():
            try:
                now = time.time()
                with DbConn() as c:
                    cur = c.cursor()
                    cur.execute("SELECT id, uid, text, kwargs, attempts FROM outbox WHERE sent_at=0 AND attempts < ? AND next_try <= ? ORDER BY id LIMIT ?", (OUTBOX_MAX_ATTEMPTS, now, OUTBOX_BATCH))
                    rows = cur.fetchall()
                    for oid, uid, text, kw_json, attempts in rows:
                        try:
                            kw = json.loads(kw_json) if kw_json else {}
                            res = safe_send(uid, text, **kw)
                            if res is not None: cur.execute("UPDATE outbox SET sent_at=? WHERE id=?", (time.time(), oid))
                            else: raise RuntimeError("send returned None")
                        except Exception:
                            new_attempts = attempts + 1
                            if new_attempts >= OUTBOX_MAX_ATTEMPTS: cur.execute("UPDATE outbox SET attempts=?, sent_at=-1 WHERE id=?", (new_attempts, oid))
                            else: cur.execute("UPDATE outbox SET attempts=?, next_try=? WHERE id=?", (new_attempts, time.time() + min(OUTBOX_RETRY_MAX_SEC, 2 ** new_attempts), oid))
            except Exception: log.exception("notify loop")
            SHUTDOWN.wait(2)
    threading.Thread(target=loop, daemon=True, name="notify").start()

# ==========================================================
# КЛАВИАТУРЫ
# ==========================================================
def main_menu(uid: int):
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(types.InlineKeyboardButton("🖼 Картинки", callback_data="cat_image"), types.InlineKeyboardButton("🎬 Видео", callback_data="cat_video"))
    kb.add(types.InlineKeyboardButton("🎵 Музыка", callback_data="cat_audio"), types.InlineKeyboardButton("🗣 Озвучка", callback_data="cat_tts"))
    kb.add(types.InlineKeyboardButton("📝 Расшифровка", callback_data="cat_stt"), types.InlineKeyboardButton("✏️ Редактор", callback_data="cat_edit"))
    kb.add(types.InlineKeyboardButton("🎞 Оживление", callback_data="cat_animate"), types.InlineKeyboardButton("🔍 Апскейл", callback_data="cat_upscale"))
    kb.add(types.InlineKeyboardButton("💬 Текст (AI)", callback_data="cat_text"))
    kb.add(types.InlineKeyboardButton("📝 Текст (Подписки)", callback_data="menu_text_sub"))
    kb.add(types.InlineKeyboardButton("💰 Баланс", callback_data="menu_balance"), types.InlineKeyboardButton("🎫 Подписка", callback_data="menu_sub"))
    kb.add(types.InlineKeyboardButton("🛒 Купить", callback_data="menu_buy"), types.InlineKeyboardButton("📚 Работы", callback_data="menu_works"))
    kb.add(types.InlineKeyboardButton("🎁 Бонус дня", callback_data="menu_bonus"), types.InlineKeyboardButton("🏆 Задания", callback_data="menu_quest"))
    kb.add(types.InlineKeyboardButton("💱 Курс USD", callback_data="menu_fx"))
    kb.add(types.InlineKeyboardButton("📄 Условия", callback_data="menu_terms"), types.InlineKeyboardButton("🔒 Приватность", callback_data="menu_privacy"))
    kb.add(types.InlineKeyboardButton("📞 Поддержка", url=SUPPORT_URL))
    if uid == ADMIN_ID: kb.add(types.InlineKeyboardButton("🛡 Админ", callback_data="admin_root"))
    return kb

def back_menu(): return types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("⬅️ В меню", callback_data="menu_main"))
def cancel_kb(): return types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("❌ Отмена", callback_data="menu_main"))
def chat_kb(): return types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🧹 Очистить", callback_data="clear_chat"), types.InlineKeyboardButton("⬅️ В меню", callback_data="menu_main"))
def models_kb(rows, back_cb: str):
    kb = types.InlineKeyboardMarkup(row_width=1)
    for mid, a in rows: kb.add(types.InlineKeyboardButton(f"{'🟢' if a else '🔴'} {MODELS.get(mid, {}).get('name', mid)}", callback_data=f"m_toggle_{mid}"))
    kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data=back_cb)); return kb

# ==========================================================
# ХЕНДЛЕРЫ
# ==========================================================
def register_handlers():

    @bot.message_handler(commands=["start"])
    def start(m):
        uid = m.from_user.id; uname = m.from_user.username or f"id{uid}"; ref = 0
        parts = (m.text or "").split()
        if len(parts) > 1 and parts[1].startswith("ref_"):
            try:
                ref = int(parts[1].split("_")[1])
                if ref == uid: ref = 0
            except Exception: ref = 0

        is_new = get_user(uid) is None
        if is_new:
            add_user(uid, uname, ref)
            if FIRST_FREE_IMAGE: upd(uid, free_image=1)
            if ref:
                r = get_user(ref)
                if r and not r["is_banned"]:
                    incr_field(ref, "referrals", 1); incr_field(ref, "free_image", REF_BONUS)
                    notify(ref, f"🎉 По твоей ссылке пришёл друг! +{REF_BONUS} бесплатных картинок.")
                    incr_field(uid, "free_image", REF_BONUS)
        else: upd(uid, last_seen=time.time(), username=uname)

        u = get_user(uid)
        if not u or u["is_banned"]: return safe_send(uid, "⛔ Вы забанены.")
        set_state(uid, "")

        try:
            msg = bot.send_message(uid, "Очистка...", reply_markup=types.ReplyKeyboardRemove())
            bot.delete_message(uid, msg.message_id)
        except Exception: pass

        bonus = "\n\n🎁 <b>Тебе подарок:</b> 1 бесплатная картинка!" if (is_new and FIRST_FREE_IMAGE) else ""
        safe_send(uid, f"👋 Привет, @{uname}!\n\nЯ — <b>Нейро-Студия</b>.{bonus}\n\nВыбери, что хочешь сгенерировать:", reply_markup=main_menu(uid), parse_mode="HTML")

    @bot.message_handler(commands=["help"])
    def cmd_help(m): safe_send(m.chat.id, f"🤖 <b>Нейро-Студия</b>\n\n• /start — меню\n• /terms — условия\n• /privacy — политика\n• /refund — возврат\n• /delete_me — удалить данные\n• /fx — курс USD/RUB\n\nПоддержка: {SUPPORT_URL}", parse_mode="HTML", disable_web_page_preview=True)

    @bot.message_handler(commands=["fx"])
    def cmd_fx(m):
        st = FxAnalyzer.status()
        age = st["age_sec"]
        age_str = "только что" if age is None or age < 60 else f"{age // 60} мин назад"
        txt = (f"💱 <b>Курс USD/RUB</b>\n\n"
               f"ЦБ РФ: <b>{st['rate']:.4f} ₽</b> за 1$\n"
               f"Наценка при оплате: +{FX_MARKUP_PCT:.1f}%\n"
               f"Итоговый: <b>{st['rate'] * (1 + FX_MARKUP_PCT/100):.4f} ₽</b> за 1$\n"
               f"Обновлено: {age_str}")
        safe_send(m.chat.id, txt, parse_mode="HTML")

    @bot.message_handler(commands=["terms"])
    def cmd_terms(m):
        txt = (
            "📄 <b>Условия оказания услуг</b>\n\n"
            "1. Услуги — генерация медиа через сторонние AI-сервисы.\n"
            "2. Запрещено: ЦП, насилие, экстремизм, нарушение прав третьих лиц.\n"
            f"3. Возврат: в течение {REFUND_WINDOW_HOURS} ч. после оплаты. Для пакетов — пропорционально остатку. "
            f"Для подписок — пропорционально неиспользованным дням. Команда /refund.\n"
            "4. Возврат при техническом сбое генерации — автоматический.\n"
            "5. Платежи через СБП (Platega), Telegram Stars и Grosh (USD по курсу ЦБ).\n"
            f"6. Поддержка: {SUPPORT_URL}\n"
            f"\n{TERMS_URL}"
        )
        safe_send(m.chat.id, txt, parse_mode="HTML", disable_web_page_preview=True)

    @bot.message_handler(commands=["privacy"])
    def cmd_privacy(m): safe_send(m.chat.id, f"🔒 <b>Приватность</b>\n\nХраним ID и промпты до {WORKS_RETENTION_DAYS} дней. <b>Платёжные данные не удаляются (54-ФЗ).</b> Удалить остальное: /delete_me\n\n{PRIVACY_URL}", parse_mode="HTML")

    @bot.message_handler(commands=["refund"])
    def cmd_refund(m):
        uid = m.from_user.id
        cutoff = time.time() - REFUND_WINDOW_HOURS * 3600
        with DbConn() as c:
            cur = c.cursor()
            cur.execute("SELECT id, package_id, amount, ts, kind, provider FROM payments WHERE user_id=? AND status='PAID' AND refunded_at=0 AND ts > ? ORDER BY id DESC LIMIT 5", (uid, cutoff))
            rows = cur.fetchall()
        if not rows:
            return safe_send(uid, f"ℹ️ Нет доступных для возврата покупок за последние {REFUND_WINDOW_HOURS} ч.\nЕсли проблема — напиши в поддержку: {SUPPORT_URL}.")
        kb = types.InlineKeyboardMarkup(row_width=1)
        for pid, pkg, amt, ts, kind, provider in rows:
            label = PACKAGES.get(pkg, {}).get("title") or SUB_TARIFFS.get(pkg, {}).get("title") or TEXT_SUB_TARIFFS.get(pkg, {}).get("title") or pkg
            prov = "⭐" if provider == "stars" else ("💵" if provider == "grosh" else "💳")
            kb.add(types.InlineKeyboardButton(f"↩️ {prov} {label} — {amt}₽ ({datetime.fromtimestamp(ts):%d.%m %H:%M})", callback_data=f"refund_{pid}"))
        kb.add(types.InlineKeyboardButton("⬅️ В меню", callback_data="menu_main"))
        safe_send(uid, "Выбери покупку для возврата:", reply_markup=kb)

    @bot.callback_query_handler(func=lambda c: c.data.startswith("refund_"))
    def cb_refund(c):
        try: pay_id = int(c.data.split("_", 1)[1])
        except ValueError: return bot.answer_callback_query(c.id, "Ошибка.", show_alert=True)
        ok, msg = do_refund_package(c.from_user.id, pay_id)
        bot.answer_callback_query(c.id, msg, show_alert=True)

    def do_refund_package(uid: int, pay_id: int) -> Tuple[bool, str]:
        with DbConn() as c:
            cur = c.cursor()
            try:
                cur.execute("BEGIN IMMEDIATE")
                cur.execute("SELECT user_id, package_id, amount, status, kind, refunded_at, provider, provider_charge_id, invoice_payload FROM payments WHERE id=?", (pay_id,))
                r = cur.fetchone()
                if not r: cur.execute("ROLLBACK"); return False, "❌ Платёж не найден."
                owner, pid, amt, status, kind, refunded_at, provider, charge_id, inv_payload = r
                if owner != uid: cur.execute("ROLLBACK"); return False, "❌ Не твой платёж."
                if status != "PAID" or refunded_at: cur.execute("ROLLBACK"); return False, "❌ Уже возвращён или не оплачен."

                if kind == "package":
                    p = PACKAGES.get(pid)
                    if not p: cur.execute("ROLLBACK"); return False, "❌ Неизвестный пакет."
                    col = BAL_FIELD[p["type"]]; cur.execute(f"SELECT {col} FROM users WHERE user_id=?", (uid,)); bal = cur.fetchone()[0]
                    if bal <= 0: cur.execute("ROLLBACK"); return False, "❌ Пакет полностью использован."
                    used = p["count"] - min(bal, p["count"]); refund_amount = int(round(amt * (p["count"] - used) / p["count"]))
                    if refund_amount <= 0: cur.execute("ROLLBACK"); return False, "❌ Нечего возвращать."
                    to_deduct = min(bal, p["count"]); cur.execute(f"UPDATE users SET {col}={col}-? WHERE user_id=?", (to_deduct, uid))
                    cur.execute("UPDATE payments SET status='REFUNDED', refunded_at=? WHERE id=?", (time.time(), pay_id))
                    log_ev(uid, "refund_requested", f"pay#{pay_id} {refund_amount}₽ (used {used}/{p['count']})"); cur.execute("COMMIT")
                elif kind == "subscription" or kind == "text_sub":
                    t = SUB_TARIFFS.get(pid) or TEXT_SUB_TARIFFS.get(pid)
                    if not t: cur.execute("ROLLBACK"); return False, "❌ Неизвестный тариф."
                    cur.execute("SELECT sub_until, sub_used FROM users WHERE user_id=?", (uid,)); sub_until, sub_used = cur.fetchone()
                    if sub_until <= time.time(): cur.execute("ROLLBACK"); return False, "❌ Подписка уже истекла."
                    days_left = max(0, int((sub_until - time.time()) // 86400))
                    if days_left <= 0: cur.execute("ROLLBACK"); return False, "❌ Меньше дня осталось, возврат невозможен."
                    refund_amount = int(round(amt * days_left / t["days"]))
                    if refund_amount <= 0: cur.execute("ROLLBACK"); return False, "❌ Нечего возвращать."
                    cur.execute("UPDATE users SET sub_plan='', sub_until=0, sub_used=0, sub_tokens_used=0 WHERE user_id=?", (uid,))
                    cur.execute("UPDATE payments SET status='REFUNDED', refunded_at=? WHERE id=?", (time.time(), pay_id))
                    log_ev(uid, "refund_requested", f"pay#{pay_id} {refund_amount}₽ (days_left {days_left}/{t['days']})"); cur.execute("COMMIT")
                else: cur.execute("ROLLBACK"); return False, "❌ Неизвестный тип покупки."

                if provider == "stars" and charge_id:
                    if refund_stars(uid, charge_id): notify(uid, f"✅ Возврат {refund_amount}₽ (⭐ Stars) оформлен. Зачисление — в течение суток.")
                    else: notify(uid, f"⚠️ Возврат {refund_amount}₽ оформлен в базе, но Stars-возврат не удался. Напиши в поддержку: {SUPPORT_URL}"); notify(ADMIN_ID, f"⚠️ Stars refund failed: user={uid} pay#{pay_id} charge={charge_id} amt={refund_amount}₽")
                elif provider == "grosh":
                    notify(uid, f"✅ Заявка на возврат {refund_amount}₽ (Grosh) оформлена. Админ свяжется с вами для возврата в USDT.")
                    notify(ADMIN_ID, f"↩️ REFUND GROSH: user {uid} pay#{pay_id} {refund_amount}₽ — верни вручную в USDT.")
                else: notify(uid, f"✅ Заявка на возврат {refund_amount}₽ оформлена. Админ свяжется с вами для возврата на карту."); notify(ADMIN_ID, f"↩️ REFUND: user {uid} pay#{pay_id} {refund_amount}₽ — верни вручную.")
                return True, "✅ Возврат оформлен."
            except Exception:
                try: cur.execute("ROLLBACK")
                except Exception: pass
                log.exception(f"refund {pay_id}"); return False, "❌ Ошибка возврата."

    @bot.message_handler(commands=["delete_me"])
    def cmd_delete_me(m):
        kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("✅ Удалить", callback_data="delete_confirm"), types.InlineKeyboardButton("❌ Отмена", callback_data="menu_main"))
        safe_send(m.from_user.id, "⚠️ Удалю всё, кроме балансов и платежей. Продолжить?", reply_markup=kb)

    @bot.callback_query_handler(func=lambda c: c.data == "delete_confirm")
    def cb_delete_confirm(c):
        uid = c.from_user.id
        try:
            with DbConn() as db_c:
                cur = db_c.cursor()
                cur.execute("DELETE FROM works WHERE user_id=?", (uid,)); cur.execute("DELETE FROM logs WHERE user_id=?", (uid,)); cur.execute("DELETE FROM rate WHERE user_id=?", (uid,)); cur.execute("DELETE FROM chat_history WHERE user_id=?", (uid,)); cur.execute("DELETE FROM outbox WHERE uid=?", (uid,))
                sets = ", ".join(f"{k}=?" for k in _PERSONAL_CLEAR_COLS); vals = tuple(("" if k in _STRING_COLS else 0) for k in _PERSONAL_CLEAR_COLS)
                cur.execute(f"UPDATE users SET {sets} WHERE user_id=?", (*vals, uid)); cur.execute("UPDATE users SET admin_target=0, admin_ts=0 WHERE user_id=?", (uid,))
            bot.answer_callback_query(c.id, "🗑 Удалено.", show_alert=True)
            safe_edit(uid, c.message.message_id, "🗑 <b>Данные удалены.</b> В меню: /start", parse_mode="HTML")
        except Exception: bot.answer_callback_query(c.id, "⚠️ Ошибка.", show_alert=True)

    @bot.callback_query_handler(func=lambda c: c.data == "menu_main")
    def cb_main(c):
        bot.answer_callback_query(c.id)
        safe_edit(c.message.chat.id, c.message.message_id, "Выбери, что хочешь сгенерировать:", reply_markup=main_menu(c.from_user.id))

    @bot.callback_query_handler(func=lambda c: c.data == "menu_fx")
    def cb_menu_fx(c):
        bot.answer_callback_query(c.id)
        st = FxAnalyzer.status()
        age = st["age_sec"]
        age_str = "только что" if age is None or age < 60 else f"{age // 60} мин назад"
        eff = st['rate'] * (1 + FX_MARKUP_PCT / 100)
        txt = (f"💱 <b>Курс USD/RUB (реальное время)</b>\n\n"
               f"ЦБ РФ: <b>{st['rate']:.4f} ₽</b> за 1$\n"
               f"Наценка (комиссия/волатильность): +{FX_MARKUP_PCT:.1f}%\n"
               f"Эффективный курс для оплаты: <b>{eff:.4f} ₽</b> за 1$\n"
               f"Обновлено: {age_str}\n\n"
               f"<i>Курс обновляется автоматически каждые {FX_REFRESH_SEC // 60} мин. "
               f"Оплата через Grosh производится в USD/USDT по этому курсу.</i>")
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🔄 Обновить", callback_data="menu_fx_refresh"))
        kb.add(types.InlineKeyboardButton("⬅️ В меню", callback_data="menu_main"))
        safe_edit(c.message.chat.id, c.message.message_id, txt, reply_markup=kb, parse_mode="HTML")

    @bot.callback_query_handler(func=lambda c: c.data == "menu_fx_refresh")
    def cb_menu_fx_refresh(c):
        ok = FxAnalyzer.refresh()
        bot.answer_callback_query(c.id, "✅ Курс обновлён." if ok else "⚠️ Не удалось обновить, используется последний.", show_alert=True)
        cb_menu_fx(c)

    @bot.callback_query_handler(func=lambda c: c.data == "menu_text_sub")
    def cb_menu_text_sub(c):
        bot.answer_callback_query(c.id)
        if setting("payments_on") != "1": return bot.answer_callback_query(c.id, "Оплата отключена.", show_alert=True)

        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(types.InlineKeyboardButton("🚀 Текст Старт — 1 млн токенов / 199₽", callback_data="buy_text_sub_text_start"))
        kb.add(types.InlineKeyboardButton("🔥 Текст Про — 3 млн токенов / 490₽", callback_data="buy_text_sub_text_pro"))
        kb.add(types.InlineKeyboardButton("👑 Текст Макс — 7 млн токенов / 990₽", callback_data="buy_text_sub_text_max"))
        kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="menu_main"))

        txt = (
            "📝 <b>Подписки на текстовые нейросети</b>\n\n"
            "Покупая подписку, вы получаете доступ к <b>самым мощным текстовым ИИ</b> (GPT-6, DeepSeek, Claude) без ограничений по количеству сообщений.\n\n"
            "💡 <b>Почему это выгодно?</b>\n"
            "Обычная генерация стоит <b>3₽</b> за запрос. Покупая подписку, вы платите копейки за каждый токен.\n\n"
            "📊 <b>Сколько это в сообщениях?</b>\n"
            "1 млн токенов ≈ <b>500 полноценных ответов</b> (или 1500 коротких). Этого хватит на месяц активного общения!\n\n"
            "⬇️ Выбери свой тариф:"
        )
        safe_edit(c.message.chat.id, c.message.message_id, txt, reply_markup=kb, parse_mode="HTML")

    @bot.callback_query_handler(func=lambda c: c.data.startswith("buy_text_sub_"))
    def cb_buy_text_sub(c):
        bot.answer_callback_query(c.id)
        code = c.data[13:]; t = TEXT_SUB_TARIFFS.get(code)
        if not t: return bot.answer_callback_query(c.id, "Неверный тариф.", show_alert=True)

        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(types.InlineKeyboardButton(f"✅ Подтвердить покупку за {t['price']}₽", callback_data=f"textsubok_{code}"))
        kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="menu_text_sub"))

        txt = (
            f"🛒 <b>Подтверждение подписки</b>\n\n"
            f"Тариф: <b>{t['title']}</b>\n"
            f"Лимит: <b>{t['tokens']:,} токенов</b>\n"
            f"Срок: <b>{t['days']} дней</b>\n"
            f"Сумма: <b>{t['price']}₽</b>\n\n"
            f"<i>Возврат средств доступен через команду /refund (пропорционально остатку токенов).</i>"
        )
        safe_edit(c.message.chat.id, c.message.message_id, txt, reply_markup=kb, parse_mode="HTML")

    @bot.callback_query_handler(func=lambda c: c.data.startswith("textsubok_"))
    def cb_text_sub_ok(c):
        bot.answer_callback_query(c.id)
        code = c.data[10:]; t = TEXT_SUB_TARIFFS.get(code)
        if not t: return bot.answer_callback_query(c.id, "Неверный тариф.", show_alert=True)

        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(types.InlineKeyboardButton("💳 Оплатить (СБП)", callback_data=f"textsubrub_{code}"),
               types.InlineKeyboardButton("⭐ Оплатить Stars", callback_data=f"textsubstars_{code}"))
        kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data=f"buy_text_sub_{code}"))

        safe_edit(c.message.chat.id, c.message.message_id,
                  f"Выбери удобный способ оплаты для <b>«{t['title']}»</b>:",
                  reply_markup=kb, parse_mode="HTML")

    @bot.callback_query_handler(func=lambda c: c.data.startswith("textsubrub_"))
    def cb_text_sub_rub(c):
        bot.answer_callback_query(c.id)
        code = c.data[11:]; t = TEXT_SUB_TARIFFS.get(code)
        if not t: return bot.answer_callback_query(c.id, "Неверный тариф.", show_alert=True)

        idem = f"text_sub:{c.from_user.id}:{code}:{uuid.uuid4().hex[:8]}"
        if not create_platega_payment(c.from_user.id, code, t["price"], t["title"], "text_sub", "txt", idem):
            safe_send(c.from_user.id, "⚠️ Оплата СБП временно недоступна. Попробуй Stars.")

    @bot.callback_query_handler(func=lambda c: c.data.startswith("textsubstars_"))
    def cb_text_sub_stars(c):
        bot.answer_callback_query(c.id)
        code = c.data[13:]; t = TEXT_SUB_TARIFFS.get(code)
        if not t: return bot.answer_callback_query(c.id, "Неверный тариф.", show_alert=True)

        if not create_stars_invoice(c.from_user.id, code, t["price"], t["title"], "text_sub"):
            safe_send(c.from_user.id, "⚠️ Ошибка при создании счета Stars. Попробуй СБП.")

    @bot.callback_query_handler(func=lambda c: c.data == "clear_chat")
    def cb_clear_chat(c):
        bot.answer_callback_query(c.id, "🧹 Очищено.")
        clear_chat_history(c.from_user.id)
        safe_edit(c.message.chat.id, c.message.message_id, "История очищена.", reply_markup=chat_kb())

    @bot.callback_query_handler(func=lambda c: c.data == "menu_terms")
    def cb_terms(c): bot.answer_callback_query(c.id); cmd_terms(c.message)

    @bot.callback_query_handler(func=lambda c: c.data == "menu_privacy")
    def cb_privacy(c): bot.answer_callback_query(c.id); cmd_privacy(c.message)

    @bot.callback_query_handler(func=lambda c: c.data.startswith("cat_"))
    def cb_category(c):
        bot.answer_callback_query(c.id)
        m_type = c.data.split("_", 1)[1]
        if m_type not in TYPE_NAMES: return bot.answer_callback_query(c.id, "Неверная категория.", show_alert=True)
        if m_type == "text":
            u = get_user(c.from_user.id)
            if u["text_free_used"] >= FREE_TEXT_LIMIT and not sub_active(u):
                kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("⬅️ Назад", callback_data="menu_main"))
                return safe_edit(c.message.chat.id, c.message.message_id, f"❌ <b>Лимит ({FREE_TEXT_LIMIT}/{FREE_TEXT_LIMIT})</b>. Купи подписку в меню.", reply_markup=kb, parse_mode="HTML")
        models = active_by_type(m_type)
        if not models: return bot.answer_callback_query(c.id, "Модели выключены.", show_alert=True)
        kb = types.InlineKeyboardMarkup(row_width=1)
        for mid, price in models.items():
            if price > 0: suffix = "/сек" if m_type == "video" else "₽"; label = f"{MODELS[mid]['name']} ({price}{suffix})"
            else: label = f"{MODELS[mid]['name']} (Free)"
            kb.add(types.InlineKeyboardButton(label, callback_data=f"mod_{mid}"))
        kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="menu_main"))
        safe_edit(c.message.chat.id, c.message.message_id, "Выбери модель:", reply_markup=kb)

    @bot.callback_query_handler(func=lambda c: c.data.startswith("mod_"))
    def cb_model(c):
        bot.answer_callback_query(c.id)
        mid = c.data[4:]
        if mid not in MODELS: return bot.answer_callback_query(c.id, "Модель не существует.", show_alert=True)
        m = get_model(mid)
        if not m or not m["active"]: return bot.answer_callback_query(c.id, "Недоступно.", show_alert=True)
        m_type = MODELS[mid]["type"]

        if m_type == "text":
            set_state(c.from_user.id, "waiting_for_prompt", mid, 0)
            return safe_edit(c.message.chat.id, c.message.message_id, f"<b>{MODELS[mid]['name']}</b>.\n\n💬 Чат-режим. Напиши вопрос:", reply_markup=chat_kb(), parse_mode="HTML")

        if m["price"] >= 15 and m_type != "video":
            kb = types.InlineKeyboardMarkup(row_width=2)
            kb.add(types.InlineKeyboardButton(f"✅ Да, {m['price']}₽", callback_data=f"conf_{mid}"), types.InlineKeyboardButton("❌ Нет", callback_data="menu_main"))
            return safe_edit(c.message.chat.id, c.message.message_id, f"<b>{MODELS[mid]['name']}</b> — {m['price']}₽.\nТочно?", reply_markup=kb, parse_mode="HTML")

        if m_type == "video":
            kb = types.InlineKeyboardMarkup(row_width=3)
            for sec in (3, 5, 10): kb.add(types.InlineKeyboardButton(f"{sec}с ({sec*m['price']}₽)", callback_data=f"vdur_{sec}_{mid}"))
            kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="cat_video"))
            return safe_edit(c.message.chat.id, c.message.message_id, f"{MODELS[mid]['name']} — {m['price']}₽/сек.\nДлительность:", reply_markup=kb)

        set_state(c.from_user.id, "waiting_for_prompt", mid, m["price"])
        hint = "Отправь файл (+ подпись = промпт)" if m_type in FILE_REQUIRED else "Напиши запрос"
        safe_edit(c.message.chat.id, c.message.message_id, f"<b>{MODELS[mid]['name']}</b> ({m['price']}₽).\n{hint}:", reply_markup=cancel_kb(), parse_mode="HTML")

    @bot.callback_query_handler(func=lambda c: c.data.startswith("conf_"))
    def cb_confirm(c):
        bot.answer_callback_query(c.id)
        mid = c.data[5:]
        if mid not in MODELS: return bot.answer_callback_query(c.id, "Модель не существует.", show_alert=True)
        m = get_model(mid)
        if not m or not m["active"]: return bot.answer_callback_query(c.id, "Недоступно.", show_alert=True)
        set_state(c.from_user.id, "waiting_for_prompt", mid, m["price"])
        hint = "Отправь файл" if MODELS[mid]["type"] in FILE_REQUIRED else "Напиши запрос"
        safe_edit(c.message.chat.id, c.message.message_id, f"<b>{MODELS[mid]['name']}</b> ({m['price']}₽).\n{hint}:", reply_markup=cancel_kb(), parse_mode="HTML")

    @bot.callback_query_handler(func=lambda c: c.data.startswith("vdur_"))
    def cb_vdur(c):
        bot.answer_callback_query(c.id)
        try: _, sec_s, mid = c.data.split("_", 2); sec = int(sec_s)
        except (ValueError, TypeError): return bot.answer_callback_query(c.id, "Неверный формат.", show_alert=True)
        if sec not in (3, 5, 10): return bot.answer_callback_query(c.id, "Неверная длительность.", show_alert=True)
        if mid not in MODELS or MODELS[mid]["type"] != "video": return bot.answer_callback_query(c.id, "Неверная модель.", show_alert=True)
        m = get_model(mid)
        if not m or not m["active"]: return bot.answer_callback_query(c.id, "Недоступно.", show_alert=True)
        price = m["price"] * sec; set_state(c.from_user.id, "waiting_for_prompt", mid, price)
        safe_edit(c.message.chat.id, c.message.message_id, f"{MODELS[mid]['name']} — {sec} сек ({price}₽).\nЗапрос:", reply_markup=cancel_kb())

    @bot.message_handler(content_types=["text","photo","video","voice","audio","document"])
    def handle_input(m):
        uid = m.from_user.id
        u = get_user(uid)
        if not u or u["is_banned"]: return

        if TERMS_REQUIRED and not u.get("onboarded") and uid != ADMIN_ID:
            if (m.text or "").strip() != "/terms": return safe_send(m.chat.id, "⚠️ Перед использованием бота прочитай и прими условия: /terms")
            else: upd(uid, onboarded=1); return safe_send(m.chat.id, "✅ Условия приняты. Нажми /start для продолжения.")

        if uid == ADMIN_ID and u.get("admin_state"):
            if u["admin_state"] == "find_user":
                try: target_uid = int((m.text or "").strip())
                except ValueError: return safe_send(m.chat.id, "❌ Введи только цифры (ID).")
                upd(ADMIN_ID, admin_state="", admin_target=0, admin_ts=0)
                if get_user(target_uid) is None: add_user(target_uid, f"id{target_uid}"); safe_send(m.chat.id, f"✅ Юзер {target_uid} не нажимал /start. Я создал его вручную в базе.")
                show_user_card(m.chat.id, target_uid); return

            if u["admin_state"].startswith("gift:"):
                if time.time() - (u["admin_ts"] or 0) > ADMIN_STATE_TTL: upd(ADMIN_ID, admin_state="", admin_target=0, admin_ts=0); return safe_send(m.chat.id, "⚠️ Время истекло, попробуй снова.")
                m_type = u["admin_state"].split(":", 1)[1]; target_uid = u["admin_target"]
                try: n = int((m.text or "").strip())
                except ValueError: return safe_send(m.chat.id, "❌ Введи число.")
                if n <= 0 or n > ADMIN_MAX_GIFT: return safe_send(m.chat.id, f"❌ Число от 1 до {ADMIN_MAX_GIFT}.")
                t_user = get_user(target_uid)
                if not t_user: upd(ADMIN_ID, admin_state="", admin_target=0, admin_ts=0); return safe_send(m.chat.id, "❌ Юзер исчез из базы.")
                incr_field(target_uid, BAL_FIELD[m_type], n); upd(ADMIN_ID, admin_state="", admin_target=0, admin_ts=0)
                safe_send(m.chat.id, f"✅ Выдано {n} × {m_type} → ID {target_uid}"); notify(target_uid, f"🎁 Тебе начислено {n} ({m_type})")
                log_ev(target_uid, "admin_gift", f"{m_type} +{n} by admin"); show_user_card(m.chat.id, target_uid); return

        if u["state"] != "waiting_for_prompt": return safe_send(m.chat.id, "Выбери действие: /start")
        mid = u["temp_model_id"]
        if mid not in MODELS: set_state(uid, ""); return safe_send(m.chat.id, "Модель недоступна.")
        m_type = MODELS[mid]["type"]

        if setting("generations_on") != "1" and uid != ADMIN_ID: return safe_send(m.chat.id, "🛑 Генерации отключены.")
        if not MODERATION_API_URL and ADMIN_ONLY_IF_NO_MODERATION and uid != ADMIN_ID: return safe_send(m.chat.id, "🛠 Сервис на тех. обслуживании.")
        if uid != ADMIN_ID and not check_and_add_rate(uid, RATE_LIMIT): return safe_send(m.chat.id, f"⏳ Лимит {RATE_LIMIT} ген/час.")

        ok, err = _validate_input(m, m_type)
        if not ok: return safe_send(m.chat.id, err)
        prompt_text = (m.caption or m.text or "").strip()

        if not moderation_check(prompt_text):
            if m_type != "text": set_state(uid, "")
            return safe_send(m.chat.id, "❌ Запрещённый контент.")

        # Скачиваем файл ОДИН раз, чтобы не качать повторно в ген-воркере
        file_bytes = None
        if m_type in FILE_REQUIRED:
            file_bytes = download_tg_file(m)
            if not file_bytes:
                set_state(uid, "")
                return safe_send(uid, f"❌ Не удалось скачать файл (макс {FILE_MAX_MB} МБ).")
            m._cached_file_bytes = file_bytes

        if m_type != "text": set_state(uid, "")

        paid_by, rollback = _charge(uid, u, m_type)
        if paid_by is None: return

        if not QUEUE_SEM.acquire(blocking=False):
            rollback(); return safe_send(uid, "⏳ Очередь переполнена, попробуйте через минуту.")

        try: tx_id = Finance.begin(uid, m_type, mid, paid_by)
        except InsufficientFunds: QUEUE_SEM.release(); rollback(); set_state(uid, ""); return safe_send(uid, "❌ Нет средств.")
        except Exception: QUEUE_SEM.release(); rollback(); log.exception(f"tx_begin {uid}"); return safe_send(uid, "❌ Ошибка, попробуйте позже.")

        log_ev(uid, "gen_start", f"{mid} paid={paid_by} tx={tx_id}")
        try: GEN_EXECUTOR.submit(gen, uid, m, mid, m_type, u["temp_price"], uid == ADMIN_ID, paid_by, tx_id)
        except Exception: QUEUE_SEM.release(); rollback(); Finance.refund(tx_id, "submit_failed"); log.exception(f"submit {uid}")

    def _validate_input(m, m_type):
        prompt_text = (m.caption or m.text or "").strip()
        if m_type in FILE_REQUIRED:
            if m.content_type == "text": return False, "⚠️ Нужен файл."
        else:
            if m.content_type != "text": return False, "⚠️ Нужен текст."
            if not prompt_text: return False, "⚠️ Пустой запрос."
        if len(prompt_text) > PROMPT_MAX_LEN: return False, f"⚠️ Промпт > {PROMPT_MAX_LEN} символов."
        if m.content_type == "document":
            doc = m.document
            if doc.file_size and doc.file_size > FILE_MAX_MB * 1024 * 1024: return False, f"⚠️ Файл > {FILE_MAX_MB} МБ."
        return True, ""

    def _charge(uid, u, m_type) -> Tuple[Optional[str], Callable[[], None]]:
        noop = lambda: None
        if uid == ADMIN_ID: return "admin", noop
        if m_type == "text":
            if sub_active(u):
                t = TEXT_SUB_TARIFFS.get(u["sub_plan"])
                if t and u["sub_tokens_used"] < t["tokens"]: return "sub", noop
            if not consume_text_slot(uid, FREE_TEXT_LIMIT): set_state(uid, ""); safe_send(uid, "❌ Лимит текстов исчерпан. Купи подписку."); return None, noop
            return "free", lambda: incr_field(uid, "text_free_used", -1)
        can_sub, _ = sub_can_use(u)
        if can_sub and consume_sub_slot(uid, SUB_TARIFFS[u["sub_plan"]]["limit"]):
            # возвращаем слот при фейле
            return "sub", lambda: incr_field(uid, "sub_used", -1)
        if m_type == "image" and take_free_image(uid): return "free", lambda: incr_field(uid, "free_image", 1)
        return "balance", noop

    @bot.callback_query_handler(func=lambda c: c.data == "menu_balance")
    def cb_balance(c):
        bot.answer_callback_query(c.id)
        u = get_user(c.from_user.id)

        text_sub_info = ""
        if sub_active(u) and u["sub_plan"] in TEXT_SUB_TARIFFS:
            t = TEXT_SUB_TARIFFS[u["sub_plan"]]
            used = u["sub_tokens_used"]; total = t["tokens"]; left = max(0, total - used)
            percent = int((used / total) * 100) if total > 0 else 0
            bar = "🟩" * (percent // 10) + "⬜️" * (10 - (percent // 10))
            text_sub_info = f"\n\n📝 <b>Текстовая подписка:</b> {t['title']}\n{bar} {percent}%\nОсталось: <b>{left:,} / {total:,}</b> токенов"

        txt = (f"💰 <b>Твой баланс</b>\n\n"
               f"🖼 Картинки: <b>{u['balance_img']}</b>\n"
               f"🎵 Музыка: <b>{u['balance_aud']}</b>\n"
               f"🎬 Видео: <b>{u['balance_vid']}</b>\n"
               f"🗣 Озвучка: <b>{u['balance_tts']}</b>\n"
               f"📝 Расшифровка: <b>{u['balance_stt']}</b>\n"
               f"✏️ Редактор: <b>{u['balance_edit']}</b>\n"
               f"🎞 Оживление: <b>{u['balance_anim']}</b>\n"
               f"🔍 Апскейл: <b>{u['balance_up']}</b>\n\n"
               f"🎁 Бесплатные картинки: <b>{u['free_image']}</b>\n"
               f"💬 Бесплатные тексты: <b>{u['text_free_used']}/{FREE_TEXT_LIMIT}</b>"
               f"{text_sub_info}")
        safe_edit(c.message.chat.id, c.message.message_id, txt, reply_markup=back_menu(), parse_mode="HTML")

    @bot.callback_query_handler(func=lambda c: c.data == "menu_works")
    def cb_works(c):
        bot.answer_callback_query(c.id)
        with DbConn() as db_c:
            cur = db_c.cursor(); cur.execute("SELECT m_type, model_id, file_id, ts FROM works WHERE user_id=? ORDER BY id DESC LIMIT 5", (c.from_user.id,)); rows = cur.fetchall()
        if not rows: return safe_edit(c.message.chat.id, c.message.message_id, "📚 Пусто. Сгенерируй что-нибудь.", reply_markup=back_menu())
        safe_edit(c.message.chat.id, c.message.message_id, "📚 Отправляю...", reply_markup=back_menu())
        def _send_all():
            for m_type, model_id, file_id, ts in rows:
                if SHUTDOWN.is_set(): return
                caption = f"🕐 {datetime.fromtimestamp(ts):%d.%m %H:%M} | {MODELS.get(model_id,{}).get('name', model_id)}"
                kind = {"image":"photo","tts":"voice","audio":"audio","video":"video","animate":"video"}.get(m_type, "document")
                safe_send_media(c.from_user.id, kind, file_id, caption=caption); time.sleep(0.3)
        WORKS_EXECUTOR.submit(_send_all)

    @bot.callback_query_handler(func=lambda c: c.data == "menu_bonus")
    def cb_bonus(c):
        uid = c.from_user.id; u = get_user(uid)
        if not DAILY_BONUS: return bot.answer_callback_query(c.id, "Отключено.", show_alert=True)
        if sub_active(u): return bot.answer_callback_query(c.id, "У тебя есть подписка!", show_alert=True)
        if time.time() - (u["last_bonus"] or 0) < 86400: return bot.answer_callback_query(c.id, "Жди еще.", show_alert=True)
        upd(uid, last_bonus=time.time()); incr_field(uid, "free_image", 1); bot.answer_callback_query(c.id, "🎁 +1 бесплатная картинка!", show_alert=True)

    @bot.callback_query_handler(func=lambda c: c.data == "menu_quest")
    def cb_quest(c):
        bot.answer_callback_query(c.id)
        uid = c.from_user.id; u = get_user(uid)
        if u["referrals"] >= 1 and not u["reward_claimed"]:
            upd(uid, reward_claimed=1); incr_field(uid, "free_image", 1); notify(uid, "🎉 Задание выполнено! +1 бесплатная картинка!"); u = get_user(uid)
        txt = (f"🏆 <b>Задания</b>\n\n👥 Приглашено: <b>{u['referrals']}/1</b>\n🎁 Награда: <b>{'✅' if u['reward_claimed'] else '⏳'}</b>\n\n<i>За друга — по {REF_BONUS} картинки тебе и другу.</i>")
        kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔗 Пригласить", url=f"https://t.me/{BOT_USERNAME}?start=ref_{uid}"), types.InlineKeyboardButton("⬅️ Назад", callback_data="menu_main"))
        safe_edit(c.message.chat.id, c.message.message_id, txt, reply_markup=kb, parse_mode="HTML")

    @bot.callback_query_handler(func=lambda c: c.data == "menu_buy")
    def cb_buy(c):
        bot.answer_callback_query(c.id)
        if setting("payments_on") != "1": return bot.answer_callback_query(c.id, "Оплата отключена.", show_alert=True)
        kb = types.InlineKeyboardMarkup(row_width=1)
        for pid, p in PACKAGES.items(): kb.add(types.InlineKeyboardButton(f"{p['title']} — {p['price']}₽", callback_data=f"pay_{pid}"))
        kb.add(types.InlineKeyboardButton("📝 Текст (Подписки)", callback_data="menu_text_sub"))
        kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="menu_main"))
        safe_edit(c.message.chat.id, c.message.message_id, "💳 <b>Пакеты</b>", reply_markup=kb, parse_mode="HTML")

    @bot.callback_query_handler(func=lambda c: c.data == "menu_sub")
    def cb_sub(c):
        bot.answer_callback_query(c.id)
        if setting("payments_on") != "1": return bot.answer_callback_query(c.id, "Оплата отключена.", show_alert=True)
        kb = types.InlineKeyboardMarkup(row_width=1)
        for code, t in SUB_TARIFFS.items(): kb.add(types.InlineKeyboardButton(f"{t['title']} — {t['limit']} ген. / {t['price']}₽", callback_data=f"sub_{code}"))
        kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="menu_main"))
        safe_edit(c.message.chat.id, c.message.message_id, "🎫 <b>Подписки (Медиа)</b>", reply_markup=kb, parse_mode="HTML")

    @bot.callback_query_handler(func=lambda c: c.data.startswith("pay_"))
    def cb_pay(c):
        bot.answer_callback_query(c.id)
        pid = c.data[4:]; p = PACKAGES.get(pid)
        if not p: return bot.answer_callback_query(c.id, "Неверный пакет.", show_alert=True)
        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(types.InlineKeyboardButton(f"✅ Подтвердить — {p['price']}₽", callback_data=f"payok_{pid}"))
        kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="menu_buy"))
        safe_edit(c.message.chat.id, c.message.message_id, f"🛒 <b>Подтверждение покупки</b>\n\nТовар: <b>{p['title']}</b>\nСумма: <b>{p['price']}₽</b>\n\nОплата через СБП, Telegram Stars или Grosh (USD по курсу).\nВозврат — /refund.", reply_markup=kb, parse_mode="HTML")

    @bot.callback_query_handler(func=lambda c: c.data.startswith("payok_"))
    def cb_pay_ok(c):
        bot.answer_callback_query(c.id)
        pid = c.data[6:]; p = PACKAGES.get(pid)
        if not p: return bot.answer_callback_query(c.id, "Неверный пакет.", show_alert=True)
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(types.InlineKeyboardButton("💳 СБП (Platega)", callback_data=f"payrub_{pid}"),
               types.InlineKeyboardButton("⭐ Telegram Stars", callback_data=f"paystars_{pid}"))
        if RETURN_URL and GROSH_API_KEY:
            usd = FxAnalyzer.rub_to_usd(p["price"])
            kb.add(types.InlineKeyboardButton(f"💵 Grosh (${usd:.2f})", callback_data=f"paygrosh_{pid}"))
        kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data=f"pay_{pid}"))
        safe_edit(c.message.chat.id, c.message.message_id, f"Выбери способ оплаты для «{p['title']}» ({p['price']}₽):", reply_markup=kb)

    @bot.callback_query_handler(func=lambda c: c.data.startswith("payrub_"))
    def cb_pay_rub(c):
        bot.answer_callback_query(c.id)
        pid = c.data[7:]; p = PACKAGES.get(pid)
        if not p: return bot.answer_callback_query(c.id, "Неверный пакет.", show_alert=True)
        idem = f"platega:{c.from_user.id}:{pid}:{uuid.uuid4().hex[:8]}"
        if not create_platega_payment(c.from_user.id, pid, p["price"], p["title"], "package", "pay", idem): safe_send(c.from_user.id, "⚠️ Оплата СБП временно недоступна. Попробуй Stars или Grosh.")

    @bot.callback_query_handler(func=lambda c: c.data.startswith("paystars_"))
    def cb_pay_stars(c):
        bot.answer_callback_query(c.id)
        pid = c.data[9:]; p = PACKAGES.get(pid)
        if not p: return bot.answer_callback_query(c.id, "Неверный пакет.", show_alert=True)
        if not create_stars_invoice(c.from_user.id, pid, p["price"], p["title"], "package"): safe_send(c.from_user.id, "⚠️ Ошибка при создании счета Stars. Попробуй СБП.")

    @bot.callback_query_handler(func=lambda c: c.data.startswith("paygrosh_"))
    def cb_pay_grosh(c):
        bot.answer_callback_query(c.id)
        pid = c.data[9:]; p = PACKAGES.get(pid)
        if not p: return bot.answer_callback_query(c.id, "Неверный пакет.", show_alert=True)
        idem = f"grosh:{c.from_user.id}:{pid}:{uuid.uuid4().hex[:8]}"
        if not create_grosh_payment(c.from_user.id, pid, p["price"], p["title"], "package", "pay", idem):
            safe_send(c.from_user.id, "⚠️ Оплата Grosh временно недоступна. Попробуй СБП или Stars.")

    @bot.callback_query_handler(func=lambda c: c.data.startswith("sub_"))
    def cb_sub_buy(c):
        bot.answer_callback_query(c.id)
        code = c.data[4:]; t = SUB_TARIFFS.get(code)
        if not t: return bot.answer_callback_query(c.id, "Неверный тариф.", show_alert=True)
        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(types.InlineKeyboardButton(f"✅ Подтвердить — {t['price']}₽", callback_data=f"subok_{code}"))
        kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="menu_sub"))
        safe_edit(c.message.chat.id, c.message.message_id, f"🛒 <b>Подтверждение подписки</b>\n\nТариф: <b>{t['title']}</b>\nЛимит: <b>{t['limit']} генераций / {t['days']} дней</b>\nСумма: <b>{t['price']}₽</b>\n\nВозврат — /refund.", reply_markup=kb, parse_mode="HTML")

    @bot.callback_query_handler(func=lambda c: c.data.startswith("subok_"))
    def cb_sub_ok(c):
        bot.answer_callback_query(c.id)
        code = c.data[6:]; t = SUB_TARIFFS.get(code)
        if not t: return bot.answer_callback_query(c.id, "Неверный тариф.", show_alert=True)
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(types.InlineKeyboardButton("💳 СБП (Platega)", callback_data=f"subrub_{code}"),
               types.InlineKeyboardButton("⭐ Telegram Stars", callback_data=f"substars_{code}"))
        if RETURN_URL and GROSH_API_KEY:
            usd = FxAnalyzer.rub_to_usd(t["price"])
            kb.add(types.InlineKeyboardButton(f"💵 Grosh (${usd:.2f})", callback_data=f"subgrosh_{code}"))
        kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data=f"sub_{code}"))
        safe_edit(c.message.chat.id, c.message.message_id, f"Выбери способ оплаты для «{t['title']}» ({t['price']}₽):", reply_markup=kb)

    @bot.callback_query_handler(func=lambda c: c.data.startswith("subrub_"))
    def cb_sub_rub(c):
        bot.answer_callback_query(c.id)
        code = c.data[7:]; t = SUB_TARIFFS.get(code)
        if not t: return bot.answer_callback_query(c.id, "Неверный тариф.", show_alert=True)
        idem = f"platega:{c.from_user.id}:{code}:{uuid.uuid4().hex[:8]}"
        if not create_platega_payment(c.from_user.id, code, t["price"], f"Подписка «{t['title']}»", "subscription", "sub", idem): safe_send(c.from_user.id, "⚠️ Оплата СБП временно недоступна. Попробуй Stars.")

    @bot.callback_query_handler(func=lambda c: c.data.startswith("substars_"))
    def cb_sub_stars(c):
        bot.answer_callback_query(c.id)
        code = c.data[9:]; t = SUB_TARIFFS.get(code)
        if not t: return bot.answer_callback_query(c.id, "Неверный тариф.", show_alert=True)
        if not create_stars_invoice(c.from_user.id, code, t["price"], f"Подписка «{t['title']}»", "subscription"): safe_send(c.from_user.id, "⚠️ Ошибка при создании счета Stars. Попробуй СБП.")

    @bot.callback_query_handler(func=lambda c: c.data.startswith("subgrosh_"))
    def cb_sub_grosh(c):
        bot.answer_callback_query(c.id)
        code = c.data[9:]; t = SUB_TARIFFS.get(code)
        if not t: return bot.answer_callback_query(c.id, "Неверный тариф.", show_alert=True)
        idem = f"grosh:{c.from_user.id}:{code}:{uuid.uuid4().hex[:8]}"
        if not create_grosh_payment(c.from_user.id, code, t["price"], f"Подписка «{t['title']}»", "subscription", "sub", idem):
            safe_send(c.from_user.id, "⚠️ Оплата Grosh временно недоступна. Попробуй СБП.")

    @bot.pre_checkout_query_handler(func=lambda query: True)
    def process_pre_checkout_query(pre_checkout_query):
        payload = pre_checkout_query.invoice_payload
        with DbConn() as c:
            cur = c.cursor(); cur.execute("SELECT status, stars_amount, user_id FROM payments WHERE invoice_payload=? AND provider='stars'", (payload,)); r = cur.fetchone()
        if not r: return bot.answer_pre_checkout_query(pre_checkout_query.id, ok=False, error_message="Счёт не найден. Открой /start → Купить заново.")
        status, expected_stars, owner_uid = r
        if pre_checkout_query.from_user.id != owner_uid:
            return bot.answer_pre_checkout_query(pre_checkout_query.id, ok=False, error_message="Счёт принадлежит другому пользователю.")
        if status != "PENDING": return bot.answer_pre_checkout_query(pre_checkout_query.id, ok=False, error_message="Счёт уже оплачен. Открой /start → Купить заново.")
        try: total = int(pre_checkout_query.total_amount)
        except Exception: total = -1
        if total != int(expected_stars): return bot.answer_pre_checkout_query(pre_checkout_query.id, ok=False, error_message=f"Сумма не совпадает. Ожидалось {expected_stars}⭐, получено {total}.")
        if (pre_checkout_query.currency or "").upper() != "XTR": return bot.answer_pre_checkout_query(pre_checkout_query.id, ok=False, error_message="Валюта должна быть XTR.")
        bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

    @bot.message_handler(content_types=['successful_payment'])
    def got_payment(message):
        sp = message.successful_payment; payload = sp.invoice_payload or ""; uid = message.from_user.id
        try: charge_id = sp.telegram_payment_charge_id or ""; total = int(sp.total_amount); currency = sp.currency or ""
        except Exception: return
        ok, reason = apply_payment_atomic_stars(payload, charge_id, total, currency)
        if not ok:
            refunded = False
            if reason in ("amount_mismatch", "currency_mismatch", "exception") and charge_id: refunded = refund_stars(uid, charge_id)
            if refunded: safe_send(uid, f"⚠️ Платёж не применён ({reason}), средства возвращены автоматически.")
            else: safe_send(uid, f"⚠️ Платёж получен, но не применён ({reason}). Напиши в поддержку: {SUPPORT_URL}\nУкажи payload: {payload}")
            notify(ADMIN_ID, f"⚠️ STARS PAYMENT NOT APPLIED\nuser={uid}\npayload={payload}\nreason={reason}\ncharge={charge_id}\nrefunded={refunded}")

    # ---------- Админка ----------
    def admin_only(func):
        @wraps(func)
        def wrapper(c, *a, **kw):
            if c.from_user.id != ADMIN_ID: return bot.answer_callback_query(c.id, "Нет доступа.", show_alert=True)
            return func(c, *a, **kw)
        return wrapper

    @bot.callback_query_handler(func=lambda c: c.data == "admin_root")
    @admin_only
    def cb_admin_root(c):
        bot.answer_callback_query(c.id)
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(types.InlineKeyboardButton("📊 Дашборд", callback_data="admin_dash"), types.InlineKeyboardButton("👥 Юзеры", callback_data="admin_users"))
        kb.add(types.InlineKeyboardButton("🔍 Найти по ID", callback_data="admin_find"), types.InlineKeyboardButton("💳 Платежи", callback_data="admin_pays"))
        kb.add(types.InlineKeyboardButton("⚙️ Модели", callback_data="admin_models"), types.InlineKeyboardButton("📜 Логи", callback_data="admin_logs"))
        kb.add(types.InlineKeyboardButton("🔌 Провайдеры", callback_data="admin_providers"))
        kb.add(types.InlineKeyboardButton("💱 FX (USD/RUB)", callback_data="admin_fx"))
        kb.add(types.InlineKeyboardButton("⬅️ В меню", callback_data="menu_main"))
        safe_edit(c.message.chat.id, c.message.message_id, "🛡 <b>Админ</b>", reply_markup=kb, parse_mode="HTML")

    @bot.callback_query_handler(func=lambda c: c.data == "admin_fx")
    @admin_only
    def cb_admin_fx(c):
        bot.answer_callback_query(c.id)
        st = FxAnalyzer.status()
        age = st["age_sec"]
        age_str = "только что" if age is None or age < 60 else f"{age // 60} мин назад"
        eff = st['rate'] * (1 + FX_MARKUP_PCT / 100)
        txt = (f"💱 <b>FX-анализатор</b>\n\n"
               f"Источник: <code>{FX_API_URL}</code>\n"
               f"Курс ЦБ: <b>{st['rate']:.4f} ₽</b> за 1$\n"
               f"Эффективный (с наценкой +{FX_MARKUP_PCT:.1f}%): <b>{eff:.4f} ₽</b>\n"
               f"Обновлено: {age_str}\n"
               f"Интервал: каждые {FX_REFRESH_SEC // 60} мин\n"
               f"Fallback: {FX_FALLBACK_RATE:.2f} ₽")
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🔄 Обновить сейчас", callback_data="admin_fx_refresh"))
        kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="admin_root"))
        safe_edit(c.message.chat.id, c.message.message_id, txt, reply_markup=kb, parse_mode="HTML")

    @bot.callback_query_handler(func=lambda c: c.data == "admin_fx_refresh")
    @admin_only
    def cb_admin_fx_refresh(c):
        ok = FxAnalyzer.refresh()
        bot.answer_callback_query(c.id, "✅ Обновлено." if ok else "⚠️ Ошибка, используется последний.")
        cb_admin_fx(c)

    @bot.callback_query_handler(func=lambda c: c.data == "admin_providers")
    @admin_only
    def cb_admin_providers(c, _answer: bool = True):
        if _answer: bot.answer_callback_query(c.id)
        with DbConn() as db_c:
            cur = db_c.cursor(); cur.execute("SELECT provider, MAX(active) FROM models GROUP BY provider"); rows = cur.fetchall()
        kb = types.InlineKeyboardMarkup(row_width=1)
        for prov, active in rows:
            status_icon = "🟢" if active else "🔴"
            kb.add(types.InlineKeyboardButton(f"{status_icon} {prov.upper()}", callback_data=f"admin_toggle_{prov}"))
        kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="admin_root"))
        safe_edit(c.message.chat.id, c.message.message_id, "🔌 <b>Провайдеры</b>\n\nНажми на провайдера, чтобы включить или выключить ВСЕ его модели:", reply_markup=kb, parse_mode="HTML")

    @bot.callback_query_handler(func=lambda c: c.data.startswith("admin_toggle_"))
    @admin_only
    def cb_admin_toggle_provider(c):
        provider = c.data[len("admin_toggle_"):]
        with DbConn() as db_c:
            cur = db_c.cursor(); cur.execute("SELECT MAX(active) FROM models WHERE provider=?", (provider,)); r = cur.fetchone()
            new_state = 0 if r and r[0] == 1 else 1; cur.execute("UPDATE models SET active=? WHERE provider=?", (new_state, provider))
        bot.answer_callback_query(c.id, f"{provider.upper()}: {'ВКЛ' if new_state else 'ВЫКЛ'}", show_alert=False)
        # перерисовываем без повторного answer
        cb_admin_providers(c, _answer=False)

    @bot.callback_query_handler(func=lambda c: c.data == "admin_find")
    @admin_only
    def cb_admin_find(c):
        bot.answer_callback_query(c.id); upd(ADMIN_ID, admin_state="find_user", admin_target=0, admin_ts=time.time()); safe_send(c.message.chat.id, "Введи <b>ID юзера</b> (только цифры):", parse_mode="HTML")

    @bot.callback_query_handler(func=lambda c: c.data == "admin_dash")
    @admin_only
    def cb_admin_dash(c):
        bot.answer_callback_query(c.id)
        with DbConn() as db_c:
            cur = db_c.cursor()
            cur.execute("SELECT COUNT(*), COALESCE(SUM(total_generated),0) FROM users"); users, gens = cur.fetchone()
            cur.execute("SELECT COUNT(*) FROM users WHERE sub_until > ?", (time.time(),)); subs = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM payments WHERE status='PAID'"); paid = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM transactions WHERE status='PENDING'"); pending_tx = cur.fetchone()[0]
        txt = (f"📊 <b>Дашборд</b>\n\n👥 Юзеров: {users}\n🎨 Генераций: {gens}\n🎫 Подписок: {subs}\n💳 Оплат: {paid}\n⏳ PENDING tx: {pending_tx}\n\nОплата: {'✅' if setting('payments_on')=='1' else '🛑'}\nГенерации: {'✅' if setting('generations_on')=='1' else '🛑'}")
        kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("⬅️ Назад", callback_data="admin_root"))
        safe_edit(c.message.chat.id, c.message.message_id, txt, reply_markup=kb, parse_mode="HTML")

    @bot.callback_query_handler(func=lambda c: c.data == "admin_users")
    @admin_only
    def cb_admin_users(c):
        bot.answer_callback_query(c.id)
        kb = types.InlineKeyboardMarkup(row_width=1)
        with DbConn() as db_c:
            cur = db_c.cursor(); cur.execute("SELECT user_id, username FROM users ORDER BY last_seen DESC LIMIT ?", (ADMIN_PAGE,)); rows = cur.fetchall()
        for uid, uname in rows: kb.add(types.InlineKeyboardButton(f"@{uname} (ID: {uid})", callback_data=f"a_view_{uid}"))
        kb.add(types.InlineKeyboardButton("🔍 Найти по ID", callback_data="admin_find")); kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="admin_root"))
        safe_edit(c.message.chat.id, c.message.message_id, "👥 <b>Последние юзеры:</b>", reply_markup=kb, parse_mode="HTML")

    @bot.callback_query_handler(func=lambda c: c.data == "admin_pays")
    @admin_only
    def cb_admin_pays(c):
        bot.answer_callback_query(c.id)
        with DbConn() as db_c:
            cur = db_c.cursor(); cur.execute("SELECT user_id,package_id,amount,status,provider,ts,amount_usd FROM payments ORDER BY id DESC LIMIT ?", (ADMIN_PAGE,)); rows = cur.fetchall()
        lines = []
        for u, p, a, s, pr, t, usd in rows:
            if pr == "grosh" and usd:
                lines.append(f"• {u} | {p} | {a}₽ (${usd:.2f}) | {s} | {pr} | {datetime.fromtimestamp(t):%d.%m %H:%M}")
            else:
                lines.append(f"• {u} | {p} | {a}₽ | {s} | {pr} | {datetime.fromtimestamp(t):%d.%m %H:%M}")
        txt = "💳 <b>Платежи</b>\n\n" + ("\n".join(lines) if rows else "Пусто")
        kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("⬅️ Назад", callback_data="admin_root"))
        safe_edit(c.message.chat.id, c.message.message_id, txt[:TG_MSG_CHUNK], reply_markup=kb, parse_mode="HTML")

    @bot.callback_query_handler(func=lambda c: c.data == "admin_models")
    @admin_only
    def cb_admin_models(c):
        bot.answer_callback_query(c.id)
        with DbConn() as db_c:
            cur = db_c.cursor(); cur.execute("SELECT model_id, active FROM models"); rows = cur.fetchall()
        safe_edit(c.message.chat.id, c.message.message_id, "⚙️ <b>Модели:</b>", reply_markup=models_kb(rows, "admin_root"))

    @bot.callback_query_handler(func=lambda c: c.data == "admin_logs")
    @admin_only
    def cb_admin_logs(c):
        bot.answer_callback_query(c.id)
        with DbConn() as db_c:
            cur = db_c.cursor(); cur.execute("SELECT user_id,action,details,ts FROM logs ORDER BY id DESC LIMIT ?", (ADMIN_PAGE,)); rows = cur.fetchall()
        txt = "📜 <b>Логи</b>\n\n" + ("\n".join([f"• {datetime.fromtimestamp(t):%d.%m %H:%M} | {u} | {a} | {d}" for u,a,d,t in rows]) if rows else "Пусто")
        kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("⬅️ Назад", callback_data="admin_root"))
        safe_edit(c.message.chat.id, c.message.message_id, txt[:TG_MSG_CHUNK], reply_markup=kb, parse_mode="HTML")

    @bot.callback_query_handler(func=lambda c: c.data.startswith("a_view_"))
    @admin_only
    def cb_view_user(c):
        bot.answer_callback_query(c.id)
        try: uid = int(c.data.split("_", 2)[2])
        except (ValueError, IndexError): return bot.answer_callback_query(c.id, "Неверный uid.", show_alert=True)
        if get_user(uid) is None: return bot.answer_callback_query(c.id, "Нет юзера.", show_alert=True)
        show_user_card(c.message.chat.id, uid, c.message.message_id)

    @bot.callback_query_handler(func=lambda c: c.data.startswith("a_ban_"))
    @admin_only
    def cb_ban_user(c):
        bot.answer_callback_query(c.id)
        try: uid = int(c.data.split("_", 2)[2])
        except (ValueError, IndexError): return bot.answer_callback_query(c.id, "Неверный uid.", show_alert=True)
        u = get_user(uid)
        if not u: return bot.answer_callback_query(c.id, "Нет юзера.", show_alert=True)
        upd(uid, is_banned=0 if u["is_banned"] else 1)
        show_user_card(c.message.chat.id, uid, c.message.message_id)

    @bot.callback_query_handler(func=lambda c: c.data.startswith("a_give_"))
    @admin_only
    def cb_give_start(c):
        bot.answer_callback_query(c.id)
        try: uid = int(c.data.split("_", 2)[2])
        except (ValueError, IndexError): return bot.answer_callback_query(c.id, "Неверный uid.", show_alert=True)
        if get_user(uid) is None: return bot.answer_callback_query(c.id, "Нет юзера.", show_alert=True)
        kb = types.InlineKeyboardMarkup(row_width=2)
        for m_type, name in TYPE_NAMES.items():
            if m_type != "text": kb.add(types.InlineKeyboardButton(name, callback_data=f"a_gtype_{m_type}_{uid}"))
        kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data=f"a_view_{uid}"))
        safe_edit(c.message.chat.id, c.message.message_id, "Что выдать?", reply_markup=kb)

    @bot.callback_query_handler(func=lambda c: c.data.startswith("a_gtype_"))
    @admin_only
    def cb_give_type(c):
        bot.answer_callback_query(c.id)
        parts = c.data.split("_")
        if len(parts) != 4: return bot.answer_callback_query(c.id, "Неверный формат.", show_alert=True)
        m_type, uid_s = parts[2], parts[3]
        if m_type not in BAL_FIELD: return bot.answer_callback_query(c.id, "Неверный тип.", show_alert=True)
        try: uid = int(uid_s)
        except ValueError: return bot.answer_callback_query(c.id, "Неверный uid.", show_alert=True)
        if get_user(uid) is None: return bot.answer_callback_query(c.id, "Нет юзера.", show_alert=True)
        upd(ADMIN_ID, admin_state=f"gift:{m_type}", admin_target=uid, admin_ts=time.time())
        safe_send(c.message.chat.id, f"Введи количество для <b>{TYPE_NAMES[m_type]}</b> (TTL {ADMIN_STATE_TTL}с):", parse_mode="HTML")

    @bot.callback_query_handler(func=lambda c: c.data.startswith("m_toggle_"))
    @admin_only
    def cb_m_toggle(c):
        mid = c.data[len("m_toggle_"):]
        if mid not in MODELS: return bot.answer_callback_query(c.id, "Модель не существует.", show_alert=True)
        with DbConn() as db_c:
            cur = db_c.cursor(); cur.execute("SELECT active FROM models WHERE model_id=?", (mid,)); r = cur.fetchone()
            if r: cur.execute("UPDATE models SET active=? WHERE model_id=?", (0 if r[0] else 1, mid))
            cur.execute("SELECT model_id, active FROM models"); rows = cur.fetchall()
        bot.answer_callback_query(c.id, "Изменено.", show_alert=True)
        safe_edit(c.message.chat.id, c.message.message_id, "⚙️ <b>Модели:</b>", reply_markup=models_kb(rows, "admin_root"))

# ==========================================================
# ГЕНЕРАЦИЯ
# ==========================================================
def gen(uid: int, message, mid: str, m_type: str, price: int, is_admin: bool, paid_by: str, tx_id: int):
    try: _gen_impl(uid, message, mid, m_type, price, is_admin, paid_by, tx_id)
    except Exception as e:
        log.exception(f"gen {uid} tx={tx_id}: {e}")
        try: Finance.refund(tx_id, "exception")
        except Exception: pass
        safe_send(uid, "❌ Сбой. Средства возвращены.")
    finally: QUEUE_SEM.release()

def _gen_impl(uid: int, message, mid: str, m_type: str, price: int, is_admin: bool, paid_by: str, tx_id: int):
    prompt = (message.text or message.caption or "").strip()
    file_bytes = getattr(message, "_cached_file_bytes", None)
    if file_bytes is None and message.content_type in ("photo","video","voice","audio","document"):
        file_bytes = download_tg_file(message)

    if m_type == "text":
        status = safe_send(uid, "💬 Думаю...")
        if not status: Finance.refund(tx_id, "send_failed"); return
        history = get_chat_history(uid, MAX_HISTORY); history.append({"role": "user", "content": prompt})
        if len(history) > MAX_HISTORY: history = history[-MAX_HISTORY:]

        provider = MODELS[mid].get("provider", "openrouter")

        if provider == "ranvik":
            headers = {"Authorization": f"Bearer {RANVIK_API_KEY}", "Content-Type": "application/json"}
            payload = {"model": mid.split("/", 1)[-1], "messages": history}
            api_url = f"{RANVIK_API_URL}/chat/completions"
        elif provider == "sprut":
            headers = {"Authorization": f"Bearer {TEXT_API_KEY}", "Content-Type": "application/json"}
            payload = {"model": mid, "messages": history}
            api_url = f"{TEXT_API_URL}/chat/completions"
        elif provider == "clodex":
            headers = {"Authorization": f"Bearer {CLODEX_API_KEY}", "Content-Type": "application/json"}
            payload = {"model": mid, "messages": history}
            api_url = f"{CLODEX_API_URL}/chat/completions"
        else:
            headers = {"Authorization": f"Bearer {OPENROUTER_KEY}", "Content-Type": "application/json", "HTTP-Referer": "https://t.me/" + (BOT_USERNAME or "bot"), "X-Title": "Neuro Studio"}
            payload = {"model": mid, "messages": history}
            if "nemotron" in mid: payload["reasoning"] = {"enabled": True}
            api_url = "https://openrouter.ai/api/v1/chat/completions"

        try:
            r = requests.post(api_url, headers=headers, json=payload, timeout=HTTP_TIMEOUT_LONG)
            if r.status_code != 200:
                try: err = r.json().get("error", {}).get("message", r.text[:200])
                except Exception: err = r.text[:200]
                safe_edit(uid, status.message_id, f"❌ Ошибка: {err}"); Finance.refund(tx_id, "text_api_error"); return
            data = r.json(); answer = data.get("choices", [{}])[0].get("message", {}).get("content", "")

            if paid_by == "sub" and not is_admin:
                usage = data.get("usage", {}); incr_field(uid, "sub_tokens_used", usage.get("total_tokens", 0))

            if answer: append_chat(uid, "user", prompt); append_chat(uid, "assistant", answer)
            try: bot.delete_message(uid, status.message_id)
            except Exception: pass
            if not answer: Finance.refund(tx_id, "text_empty"); return safe_send(uid, "❌ Пустой ответ.")
            for i in range(0, len(answer), TG_MSG_CHUNK): safe_send(uid, answer[i:i+TG_MSG_CHUNK])
            Finance.ok(tx_id); incr_generated(uid); log_ev(uid, "gen_done", m_type)
        except Exception as e:
            log.exception(f"text {uid}: {e}")
            try: bot.delete_message(uid, status.message_id)
            except Exception: pass
            Finance.refund(tx_id, "text_exception"); safe_send(uid, "❌ Ошибка соединения. Средства возвращены.")
        return

    if m_type == "stt":
        status = safe_send(uid, "⏳ Расшифровка...")
        if not status: Finance.refund(tx_id, "send_failed"); return
        headers = {"Authorization": f"Bearer {POLZA_KEY}"}
        files = {"file": ("audio.ogg", file_bytes or b"", "audio/ogg")}
        text = None
        model_for_stt = mid.split("/", 1)[-1] if mid.startswith("openai/") else mid
        try:
            r = requests.post(f"{POLZA_BASE}/audio/transcriptions", headers=headers, files=files, data={"model": model_for_stt}, timeout=HTTP_TIMEOUT_LONG)
            if r.status_code == 200: text = r.json().get("text")
        except Exception: log.exception("stt")
        try: bot.delete_message(uid, status.message_id)
        except Exception: pass
        if not text: Finance.refund(tx_id, "stt_failed"); return safe_send(uid, "❌ Ошибка. Средства возвращены.")
        safe_send(uid, f"📝 <b>Расшифровка:</b>\n\n{text[:STT_PREVIEW_LEN]}", parse_mode="HTML")
        Finance.ok(tx_id); incr_generated(uid); log_ev(uid, "gen_done", m_type); return

    duration = None
    if m_type == "video":
        try:
            unit = MODELS[mid]["price"]
            if unit > 0: duration = max(1, price // unit)
        except (KeyError, ZeroDivisionError): pass

    inp = {"prompt": prompt}
    if m_type == "image": inp["aspect_ratio"] = "1:1"
    if duration: inp["duration"] = duration
    if file_bytes:
        b64 = base64.b64encode(file_bytes).decode()
        if m_type in ("edit","animate"): inp["images"] = [{"type":"base64","data":f"data:image/jpeg;base64,{b64}"}]
        elif m_type == "upscale": inp["videos" if "video" in mid else "images"] = [{"type":"base64","data":f"data:image/jpeg;base64,{b64}"}]

    payload = {"model": mid, "async": False, "input": inp}
    headers = {"Authorization": f"Bearer {POLZA_KEY}", "Content-Type": "application/json"}
    api_url = f"{POLZA_BASE}/media"

    # --- ЛОГИКА ДЛЯ CLODEX ---
    if MODELS[mid].get("provider") == "clodex":
        api_url = f"{CLODEX_API_URL}/images/generations"
        headers = {"Authorization": f"Bearer {CLODEX_API_KEY}", "Content-Type": "application/json"}
        payload = {"model": mid, "prompt": prompt, "size": "1024x1024", "n": 1}
    # --- ЛОГИКА ДЛЯ SPRUTDOCK ---
    elif MODELS[mid].get("provider") == "sprut":
        api_url = f"{TEXT_API_URL}/images/generations"
        headers = {"Authorization": f"Bearer {TEXT_API_KEY}", "Content-Type": "application/json"}
        payload = {"model": mid, "prompt": prompt, "size": "1024x1024", "n": 1}

    status = safe_send(uid, "⏳ Генерация...")
    if not status: Finance.refund(tx_id, "send_failed"); return
    tmp = None

    try:
        r = requests.post(api_url, headers=headers, json=payload, timeout=HTTP_TIMEOUT_MED)
        if r.status_code != 200:
            try: error_data = r.json(); error_msg = error_data.get("error", {}).get("message", r.text[:200])
            except Exception: error_msg = r.text[:200]
            safe_edit(uid, status.message_id, f"❌ API: {error_msg}"); Finance.refund(tx_id, f"api_{r.status_code}"); return

        data = r.json()

        url = None
        body = None
        if isinstance(data.get("data"), list) and data["data"]:
            item = data["data"][0]
            if "b64_json" in item:
                body = base64.b64decode(item["b64_json"])
            elif "url" in item:
                url = item["url"]
        elif isinstance(data.get("data"), dict):
            item = data["data"]
            if "b64_json" in item:
                body = base64.b64decode(item["b64_json"])
            elif "url" in item:
                url = item["url"]
        elif "url" in data:
            url = data["url"]

        if url:
            body = fetch_media(url, m_type=m_type)

        if not body: raise RuntimeError("no image data")

        # для upscale видео — расширение mp4 и kind video
        if m_type == "upscale" and "video" in mid:
            ext = ".mp4"
        else:
            ext = {"image":".jpg","audio":".mp3","tts":".ogg","video":".mp4","edit":".jpg","animate":".mp4","upscale":".bin"}.get(m_type, ".bin")
        tmp = os.path.join(DATA_DIR, f"temp_{uid}_{uuid.uuid4().hex[:8]}{ext}")
        with open(tmp, "wb") as f: f.write(body)

        try: bot.delete_message(uid, status.message_id)
        except Exception: pass

        if m_type == "upscale" and "video" in mid:
            kind = "video"
        else:
            kind = {"image":"photo","tts":"voice","audio":"audio","video":"video","animate":"video"}.get(m_type, "document")
        with open(tmp, "rb") as f: sent = safe_send_media(uid, kind, f, caption="✅ Готово")

        if not sent:
            Finance.refund(tx_id, "send_media_failed"); return

        try:
            fid = ""
            for attr in ("photo","voice","audio","video","document"):
                obj = getattr(sent, attr, None)
                if obj: fid = obj[-1].file_id if attr == "photo" else obj.file_id; break
            add_work(uid, m_type, mid, prompt, fid)
        except Exception: log.exception("add_work")

        Finance.ok(tx_id); incr_generated(uid); log_ev(uid, "gen_done", m_type)

    except Exception as e:
        log.exception(f"gen {uid} tx={tx_id}: {e}")
        try: bot.delete_message(uid, status.message_id)
        except Exception: pass
        Finance.refund(tx_id, "media_exception")
        raise
    finally:
        if tmp and os.path.exists(tmp):
            try: os.remove(tmp)
            except OSError: pass

# ==========================================================
# ПОКАЗ КАРТОЧКИ И ЗАПУСК
# ==========================================================
def show_user_card(chat_id: int, uid: int, msg_id: int = None):
    u = get_user(uid)
    if not u: return safe_send(chat_id, "❌ Нет юзера.")
    txt = (f"👤 <b>@{u['username']}</b> (ID: <code>{uid}</code>)\nГенераций: {u['total_generated']}\n\n"
           f"🖼{u['balance_img']} 🎵{u['balance_aud']} 🎬{u['balance_vid']}\n🗣{u['balance_tts']} 📝{u['balance_stt']} ✏️{u['balance_edit']}\n"
           f"🎞{u['balance_anim']} 🔍{u['balance_up']}\n\nТекст: {u['text_free_used']}/{FREE_TEXT_LIMIT}\n{'🚫 ЗАБАНЕН' if u['is_banned'] else '✅ Активен'}")
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(types.InlineKeyboardButton("🖼 Баланс", callback_data=f"a_give_{uid}"))

    ban_text = "✅ Разбанить" if u["is_banned"] else "🚫 Забанить"
    kb.add(types.InlineKeyboardButton(ban_text, callback_data=f"a_ban_{uid}"))
    kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="admin_users"))

    if msg_id: safe_edit(chat_id, msg_id, txt, reply_markup=kb, parse_mode="HTML")
    else: safe_send(chat_id, txt, reply_markup=kb, parse_mode="HTML")

def start_health_server(port: int):
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/health":
                ok = True
                if HEALTH_DB_CHECK:
                    try:
                        with DbConn() as c: c.execute("SELECT 1").fetchone()
                    except Exception: ok = False
                body = b'{"status":"ok"}' if ok else b'{"status":"degraded"}'
                self.send_response(200 if ok else 503); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
            elif self.path == "/fx":
                st = FxAnalyzer.status()
                body = json.dumps(st).encode()
                self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
            else: self.send_response(404); self.end_headers()

        def do_POST(self):
            if self.path == "/webhook/grosh":
                try:
                    length = int(self.headers.get('Content-Length', 0))
                    if length <= 0 or length > 64 * 1024:
                        self.send_response(413); self.end_headers(); return
                    raw = self.rfile.read(length)
                    data = json.loads(raw)
                    log.info(f"Grosh webhook: {data}")

                    status = (data.get("status") or "").lower()
                    tx_id = data.get("id") or data.get("transaction_id")
                    remote_amount = data.get("amount")
                    remote_currency = data.get("currency")

                    if status in ("paid", "success", "completed") and tx_id:
                        ok = apply_payment_atomic_grosh(str(tx_id), remote_amount, remote_currency)
                        if not ok:
                            log.warning(f"grosh webhook not applied: tx={tx_id} amount={remote_amount}")

                    self.send_response(200); self.end_headers(); self.wfile.write(b"OK")
                except Exception as e:
                    log.exception(f"Grosh webhook error: {e}")
                    self.send_response(500); self.end_headers()
            else:
                self.send_response(404); self.end_headers()

        def log_message(self, *a): pass

    srv = http.server.ThreadingHTTPServer(("0.0.0.0", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True, name="health").start()
    log.info(f"Health & Webhook server on 0.0.0.0:{port}")

def _shutdown_handler(signum, frame):
    log.warning(f"signal {signum}, graceful shutdown"); SHUTDOWN.set()

def main():
    global bot, GEN_EXECUTOR, PAY_EXECUTOR, WORKS_EXECUTOR, QUEUE_SEM, BOT_USERNAME, ADMIN_ID
    _setup_logging()
    admin_raw = os.getenv("ADMIN_ID", "") or ""
    if not admin_raw: raise SystemExit("ADMIN_ID не задан")
    try: ADMIN_ID = int(admin_raw)
    except ValueError: raise SystemExit(f"ADMIN_ID={admin_raw!r} — не число")
    if ADMIN_ID <= 0: raise SystemExit(f"ADMIN_ID={ADMIN_ID} <= 0")
    if not TOKEN or not POLZA_KEY: raise SystemExit("BOT_TOKEN / POLZA_API_KEY не заданы")
    if MODERATION_REQUIRED and not MODERATION_API_URL: raise SystemExit("MODERATION_REQUIRED=1, но MODERATION_API_URL пуст")
    if TERMS_REQUIRED and not (TERMS_URL and PRIVACY_URL): raise SystemExit("TERMS_REQUIRED=1, но TERMS_URL/PRIVACY_URL пусты")

    os.makedirs(DATA_DIR, exist_ok=True)
    Db.init(os.path.join(DATA_DIR, "media_bot.db"), DB_POOL_SIZE)
    init_db()

    if setting("payments_on", "1") == "1" and (PLATEGA_ID and PLATEGA_SECRET) and not RETURN_URL: log.warning("RETURN_URL пуст, но Platega настроена — пользователь после оплаты останется без редиректа. Задай RETURN_URL.")
    if GROSH_API_KEY and not RETURN_URL: log.warning("Grosh включён, но RETURN_URL пуст — Grosh-платежи не будут создаваться.")

    GEN_EXECUTOR   = ThreadPoolExecutor(max_workers=EXECUTOR_WORKERS, thread_name_prefix="gen")
    PAY_EXECUTOR   = ThreadPoolExecutor(max_workers=4, thread_name_prefix="pay")
    WORKS_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="works")
    QUEUE_SEM      = threading.BoundedSemaphore(EXECUTOR_QUEUE_MAX + EXECUTOR_WORKERS)
    bot = telebot.TeleBot(TOKEN, threaded=True)

    try: BOT_USERNAME = bot.get_me().username or ""
    except Exception: BOT_USERNAME = ""

    register_handlers()
    try: recover_stuck_transactions()
    except Exception: log.exception("recover_stuck_transactions")

    signal.signal(signal.SIGTERM, _shutdown_handler); signal.signal(signal.SIGINT, _shutdown_handler)
    start_fx_worker()
    start_recovery_worker(); start_cleanup_worker(); start_notify_worker()
    threading.Thread(target=payment_poller_single_loop, daemon=True, name="payment_poller").start()
    if HEALTH_PORT > 0: start_health_server(HEALTH_PORT)

    log.info(f"🚀 Neuro Studio v57 started (workers={EXECUTOR_WORKERS}, queue_max={EXECUTOR_QUEUE_MAX}, db_pool={DB_POOL_SIZE}, stars_rate={STARS_RUB_PER_STAR}₽/star, fx_markup={FX_MARKUP_PCT}%, fx_refresh={FX_REFRESH_SEC}s)")
    try: bot.infinity_polling(timeout=10, long_polling_timeout=5)
    except KeyboardInterrupt: log.warning("stopped by KeyboardInterrupt")
    finally:
        SHUTDOWN.set()
        try: bot.stop_polling()
        except Exception: pass
        try: GEN_EXECUTOR.shutdown(wait=True); PAY_EXECUTOR.shutdown(wait=True); WORKS_EXECUTOR.shutdown(wait=True)
        except Exception: pass
        log.info("🛑 stopped")

if __name__ == "__main__":
    main()
