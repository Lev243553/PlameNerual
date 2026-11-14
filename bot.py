# -*- coding: utf-8 -*-
"""
❄️ Нейро-Студия v103 — Video Builder Edition ❄️
🌟 Конструктор видео (время, разрешение, формат). CLODEX API. Уровни мышления.
"""
import os, sys, io, time, uuid, sqlite3, logging, threading, signal, json, queue, http.server, hashlib
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv
import telebot
from telebot import types
from telebot.apihelper import ApiTelegramException
import requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

load_dotenv(override=False)
log = logging.getLogger("neuro")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

# ==========================================================
# ❄️ КАРТИНКИ И НАСТРОЙКИ
# ==========================================================
NEW_IMG_EXAMPLES_URL = os.getenv("NEW_IMG_EXAMPLES_URL", "https://i.postimg.cc/0QN2QW2X/IMG-20261110-204842-470.jpg")
REFUND_ON_ERROR = int(os.getenv("REFUND_ON_ERROR", "1"))

IMG_MAIN  = "https://i.postimg.cc/0QN2QW2X/IMG-20261110-204842-470.jpg"
IMG_IMAGE = "https://i.postimg.cc/Bn1hW45b/IMG-20261110-205555-782.jpg"
IMG_VIDEO = "https://i.postimg.cc/ZKn7crC0/IMG-20261110-205715-247.jpg"
IMG_TEXT  = "https://i.postimg.cc/xjtpMsj5/IMG-20261110-205814-215.jpg"
IMG_BAL   = "https://i.postimg.cc/BbYh3v7z/IMG-20261110-205911-386.jpg"
IMG_SUB   = "https://i.postimg.cc/0QCWtnY8/IMG-20261110-210033-656.jpg"
IMG_EXAMPLES = NEW_IMG_EXAMPLES_URL
IMG_HELP     = "https://i.postimg.cc/0QN2QW2X/IMG-20261110-204842-470.jpg"

def _env_int(n, d, m=None):
    r = os.getenv(n)
    if not r:
        v = d
    else:
        try:
            v = int(r)
        except Exception:
            raise SystemExit(f"ENV {n} not int")
    if m is not None and v < m:
        raise SystemExit(f"ENV {n} < {m}")
    return v

def _env_float(n, d):
    r = os.getenv(n)
    return float(r) if r else d

# ==========================================================
# ⚙️ ENV
# ==========================================================
TOKEN = os.getenv("BOT_TOKEN")
POLZA_KEY = os.getenv("POLZA_API_KEY")
POLZA_BASE = os.getenv("POLZA_API_URL", "https://polza.ai/api/v1")
DATA_DIR = os.getenv("DATA_DIR", "./data")
SUPPORT_URL = os.getenv("SUPPORT_URL", "https://t.me/your_support")
PRIVACY_URL = os.getenv("PRIVACY_URL", "https://telegra.ph/Politika-konfidencialnosti-11-11")
TERMS_URL = os.getenv("TERMS_URL", "https://telegra.ph/Polzovatelskoe-soglashenie-11-11")
CONSENT_VERSION = os.getenv("CONSENT_VERSION", "v1.0")
BOT_USERNAME = os.getenv("BOT_USERNAME", "Plamenerualbot")

PLATEGA_ID = os.getenv("PLATEGA_MERCHANT_ID", "")
PLATEGA_SECRET = os.getenv("PLATEGA_SECRET_KEY", "")
PLATEGA_URL = os.getenv("PLATEGA_API_URL", "https://app.platega.io")
RETURN_URL = os.getenv("RETURN_URL", "")

GROSH_API_KEY = os.getenv("GROSH_API_KEY", "")
GROSH_API_URL = os.getenv("GROSH_API_URL", "https://pay.grosh.me")

STARS_RUB_PER_STAR = _env_float("STARS_RUB_PER_STAR", 1.3)

OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY", "")
RANVIK_API_KEY = os.getenv("RANVIK_API_KEY", "")
RANVIK_API_URL = os.getenv("RANVIK_API_URL", "https://api.ranvik.ru/v1")
CLODEX_API_KEY = os.getenv("CLODEX_API_KEY", "")
CLODEX_API_URL = os.getenv("CLODEX_API_URL", "https://api.clodex.xyz/v1")

FX_API_URL = os.getenv("FX_API_URL", "https://www.cbr-xml-daily.ru/daily_json.js")
FX_FALLBACK_RATE = _env_float("FX_FALLBACK_RATE", 82.54)
FX_MARKUP_PCT = _env_float("FX_MARKUP_PCT", 3.0)

FREE_TEXT_LIMIT = 2
MAX_HISTORY = 10
HEALTH_PORT = _env_int("HEALTH_PORT", 3000, 0)
DB_POOL_SIZE = 16
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
API_RATE_PER_DAY = _env_int("API_RATE_PER_DAY", 200, 1)

REF_BONUS_REFERRER = 3
REF_BONUS_REFERRED = 2
DAILY_BONUS_IMG = 1
AGENT_PRICE_IMG = 10

FREE_WELCOME_IMG = 1
PAYMENT_POLL_SEC = 5
MENU_MAIN_COLS = 1

TASKS = {
    "gen_first":  {"title":"🎨 Сгенери первую картинку", "field":"balance_img", "amount":2, "check":"works_img>=1"},
    "gen_5":      {"title":"🖼 Сгенери 5 картинок", "field":"balance_img", "amount":5, "check":"works_img>=5"},
    "text_first": {"title":"💬 Задай вопрос ИИ", "field":"balance_img", "amount":2, "check":"works_text>=1"},
    "ref_1":      {"title":"👥 Пригласи 1 друга", "field":"balance_img", "amount":5, "check":"refs>=1"},
    "ref_3":      {"title":"👥 Пригласи 3 друзей", "field":"balance_vid", "amount":19, "check":"refs>=3"},
    "ref_10":     {"title":"👥 Пригласи 10 друзей", "field":"balance_vid", "amount":57, "check":"refs>=10"},
}

bot = None
SHUTDOWN = threading.Event()
HTTP_TIMEOUT_MED = (5, 90)
HTTP_TIMEOUT_LONG = (5, 180)
AGENT_EXECUTOR = ThreadPoolExecutor(max_workers=8)

def rub_to_stars(rub: int) -> int:
    return max(1, int(round(rub / STARS_RUB_PER_STAR)))

def is_admin(uid):
    return uid == ADMIN_ID

def charge(uid, field, amount=1):
    if is_admin(uid):
        return True
    return sub_balance(uid, field, amount)

def grosh_enabled():
    return bool(GROSH_API_KEY)

class FxAnalyzer:
    _rate = 0.0
    _ts = 0.0
    _lock = threading.Lock()

    @classmethod
    def current(cls) -> float:
        with cls._lock:
            if cls._rate > 0 and (time.time() - cls._ts) < 1800:
                return cls._rate
            try:
                r = requests.get(FX_API_URL, timeout=5)
                v = r.json()["Valute"]["USD"]["Value"]
                cls._rate = v
                cls._ts = time.time()
                return v
            except Exception:
                return FX_FALLBACK_RATE

    @classmethod
    def rub_to_usd(cls, rub: int) -> float:
        return round((float(rub) / cls.current()) * (1 + FX_MARKUP_PCT / 100), 2)

# ==========================================================
# 🤖 МОДЕЛИ
# ==========================================================
MODELS = {
    "wan-2.7-image": {"name":"💨 Schnell", "type":"image", "price":4, "provider":"clodex"},
    "flux-3-image": {"name":"⚡ Flux", "type":"image", "price":8, "provider":"clodex"},
    "gpt-image-2.5": {"name":"✨ GPT-2.5", "type":"image", "price":12, "provider":"clodex"},
    "gpt-image-2.6": {"name":"👑 Ultra 2.6", "type":"image", "price":20, "provider":"clodex"},

    "gemini-4-carbon":   {"name":"🧠 Carbon",   "type":"text", "price":7, "provider":"clodex"},
    "claude-fable-5.2":  {"name":"🔥 Fable 5.2", "type":"text", "price":5, "provider":"clodex"},
    "gpt-6-astra":       {"name":"🌟 Astra",     "type":"text", "price":3, "provider":"clodex"},
    "claude-opus-5":     {"name":"🎭 Opus 5",    "type":"text", "price":3, "provider":"clodex"},

    "gemini-4-hydrogen": {"name":"🚀 Hydrogen", "type":"text", "price":2, "provider":"clodex"},
    "grok-4.7-build-fast":   {"name":"🤖 Grok Fast", "type":"text", "price":2, "provider":"clodex"},
    "gpt-6.1-sol-ultrafast": {"name":"☀️ Sol Ultra", "type":"text", "price":3, "provider":"clodex"},
    "glm-5.3":               {"name":"🇨🇳 GLM 5.3", "type":"text", "price":1, "provider":"clodex"},
    "gpt-6-luna":        {"name":"⚡ Luna",      "type":"text", "price":1, "provider":"clodex"},
    "deepseek-v4.1-flash": {"name":"🔬 DeepSeek","type":"text", "price":1, "provider":"clodex"},

    "nvidia/nemotron-3-ultra-550b-a55b:free": {"name":"🆓 Free", "type":"text", "price":0, "provider":"openrouter"},
}

VIDEO_MODELS = {
    "clodex-video/hailuo-2.3-fast": {"name":"💨 Hailuo Fast", "price":3, "base_sec":6},
    "clodex-video/wan-2.6": {"name":"🎥 Wan 2.6", "price":5, "base_sec":5},
    "clodex-video/kling-3.0-turbo": {"name":"🔥 Kling Turbo", "price":10, "base_sec":5},
    "clodex-video/veo-3.1-fast": {"name":"🎬 Veo Fast", "price":10, "base_sec":8},
}

# ==========================================================
# 📝 ТАРИФЫ И ПАКЕТЫ
# ==========================================================
TEXT_SUB_TARIFFS = {
    "text_start": {"title":"❄️ Текст Старт", "price": 249,  "tokens": 500_000,  "days":30},
    "text_pro":   {"title":"🌟 Текст Про",   "price": 690,  "tokens": 1_500_000,"days":30},
    "text_max":   {"title":"👑 Текст Макс",  "price": 1290, "tokens": 3_500_000,"days":30},
}
SUB_HINTS = {"text_start":"≈ 250 вопросов","text_pro":"≈ 700 вопросов","text_max":"≈ 1700 вопросов"}

BALANCE_PACKS = {
    "img_40":  {"title":"🖼 40₽ на картинки", "price": 49, "field":"balance_img", "amount":40},
    "img_120": {"title":"🖼 120₽ на картинки", "price": 129, "field":"balance_img", "amount":120},
    "img_400": {"title":"🖼 400₽ на картинки", "price": 349, "field":"balance_img", "amount":400},
    "vid_57":  {"title":"🎬 57₽ на видео", "price": 49, "field":"balance_vid", "amount":57},
    "vid_190": {"title":"🎬 190₽ на видео", "price": 149, "field":"balance_vid", "amount":190},
    "img_bonus_100": {"title":"🎁 100₽ + 10₽ бонус", "price": 100, "field":"balance_img", "amount":110},
    "vid_bonus_100": {"title":"🎁 100₽ + 10₽ бонус (видео)", "price": 100, "field":"balance_vid", "amount":110},
}

API_SUB_PLANS = {
    "api_week": {"title": "🔑 API Неделя", "price": 149, "days": 7, "requests": 500, "tokens": 1_000_000},
    "api_week_pro": {"title": "🚀 API Неделя PRO", "price": 299, "days": 7, "requests": 1500, "tokens": 3_000_000},
}

MODEL_HINTS = {
    "wan-2.7-image": "💨 Самая дешёвая.",
    "flux-3-image": "⚡ Баланс цена/качество.",
    "gpt-image-2.5": "✨ Умная, понимает промпты.",
    "gpt-image-2.6": "👑 Топ: детализация, скорость.",
    "gemini-4-carbon": "🧠 Топ-мозг для сложных задач.",
    "claude-fable-5.2": "🔥 Самая умная (Anthropic).",
    "gpt-6-astra": "🌟 Умный универсал.",
    "claude-opus-5": "🎭 Глубокие рассуждения.",
    "gemini-4-hydrogen": "🚀 Быстрая и умная база.",
    "grok-4.7-build-fast": "🤖 Свободный стиль xAI.",
    "gpt-6.1-sol-ultrafast": "☀️ Очень быстрый и умный.",
    "glm-5.3": "🇨🇳 Отлично следует инструкциям.",
    "gpt-6-luna": "⚡ Быстрый и дешёвый.",
    "deepseek-v4.1-flash": "🔬 Самый дешёвый.",
    "nvidia/nemotron-3-ultra-550b-a55b:free": "🆓 Бесплатно.",
}

VIDEO_HINTS = {
    "clodex-video/hailuo-2.3-fast": "💨 6 сек. Дешёвый вход.",
    "clodex-video/wan-2.6": "🎥 5 сек. Рабочая лошадка.",
    "clodex-video/kling-3.0-turbo": "🔥 5 сек. Высокое качество.",
    "clodex-video/veo-3.1-fast": "🎬 8 сек. Флагман.",
}

ALLOWED_COLS = {
    "username","is_banned","balance_img","balance_aud","balance_vid","balance_tts","balance_stt",
    "balance_edit","balance_anim","balance_up","text_free_used","sub_plan","sub_until","sub_used",
    "sub_tokens_used","state","temp_model_id","temp_price","admin_state","admin_target","admin_ts",
    "free_image","onboarded","last_seen","created_at","consent_at","consent_version","api_day","api_calls",
    "referred_by","ref_count","daily_last","daily_streak","tasks_done","custom_key","custom_model"
}
BALANCE_FIELDS = {"balance_img","balance_vid","balance_tts","balance_stt","balance_aud","balance_edit","balance_anim","balance_up"}

# ==========================================================
# 🗄️ DB
# ==========================================================
class Db:
    _pool = None
    _sem = None
    path = ""

    @classmethod
    def init(cls, path, size):
        cls.path = path
        cls._pool = queue.Queue(maxsize=size)
        cls._sem = threading.BoundedSemaphore(size)
        for _ in range(size):
            cls._pool.put(cls._make())

    @classmethod
    def _make(cls):
        c = sqlite3.connect(cls.path, timeout=30, isolation_level=None, check_same_thread=False)
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        return c

    @classmethod
    def acquire(cls):
        cls._sem.acquire()
        try:
            return cls._pool.get(timeout=30)
        except Exception:
            cls._sem.release()
            raise

    @classmethod
    def release(cls, conn):
        try:
            cls._pool.put_nowait(conn)
        except queue.Full:
            conn.close()
        finally:
            cls._sem.release()

class DbConn:
    def __enter__(self):
        self.conn = Db.acquire()
        return self.conn

    def __exit__(self, *a):
        Db.release(self.conn)
        return False

def _migrate(cur, table, cols):
    cur.execute(f"PRAGMA table_info({table})")
    ex = {r[1] for r in cur.fetchall()}
    if not ex:
        return
    for col, ddl in cols:
        if col not in ex:
            try:
                cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
            except Exception:
                pass

def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    with DbConn() as c:
        cur = c.cursor()
        cur.execute('''CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY, username TEXT, is_banned INTEGER DEFAULT 0,
            balance_img INTEGER DEFAULT 0, balance_aud INTEGER DEFAULT 0, balance_vid INTEGER DEFAULT 0,
            balance_tts INTEGER DEFAULT 0, balance_stt INTEGER DEFAULT 0, balance_edit INTEGER DEFAULT 0,
            balance_anim INTEGER DEFAULT 0, balance_up INTEGER DEFAULT 0, text_free_used INTEGER DEFAULT 0,
            sub_plan TEXT DEFAULT '', sub_until REAL DEFAULT 0, sub_used INTEGER DEFAULT 0,
            sub_tokens_used INTEGER DEFAULT 0, state TEXT DEFAULT '', temp_model_id TEXT DEFAULT '',
            temp_price INTEGER DEFAULT 0, free_image INTEGER DEFAULT 0, onboarded INTEGER DEFAULT 0,
            last_seen REAL DEFAULT 0, created_at REAL DEFAULT 0, consent_at REAL DEFAULT 0,
            consent_version TEXT DEFAULT '', api_day TEXT DEFAULT '', api_calls INTEGER DEFAULT 0,
            referred_by INTEGER DEFAULT 0, ref_count INTEGER DEFAULT 0,
            daily_last TEXT DEFAULT '', daily_streak INTEGER DEFAULT 0,
            tasks_done TEXT DEFAULT '', custom_key TEXT DEFAULT '', custom_model TEXT DEFAULT '',
            admin_state TEXT DEFAULT '', admin_target INTEGER DEFAULT 0, admin_ts REAL DEFAULT 0)''')
        cur.execute('''CREATE TABLE IF NOT EXISTS api_keys(key_hash TEXT PRIMARY KEY, user_id INTEGER, created_at REAL, expires_at REAL)''')
        cur.execute('''CREATE TABLE IF NOT EXISTS api_subs(user_id INTEGER PRIMARY KEY, plan TEXT DEFAULT '', expires_at REAL DEFAULT 0, requests_used INTEGER DEFAULT 0, tokens_used INTEGER DEFAULT 0)''')
        cur.execute('''CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, package_id TEXT, amount INTEGER, status TEXT, provider_id TEXT, ts REAL, kind TEXT, provider TEXT, stars_amount INTEGER DEFAULT 0)''')
        cur.execute('''CREATE TABLE IF NOT EXISTS chat_history(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, role TEXT, content TEXT, ts REAL)''')
        cur.execute('''CREATE TABLE IF NOT EXISTS logs(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, action TEXT, details TEXT, ts REAL)''')
        cur.execute('''CREATE TABLE IF NOT EXISTS works(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, m_type TEXT, model_id TEXT, prompt TEXT, file_id TEXT, ts REAL)''')
        cur.execute('''CREATE TABLE IF NOT EXISTS user_facts(user_id INTEGER, fact TEXT, ts REAL)''')
        cur.execute('''CREATE TABLE IF NOT EXISTS prompt_market(id INTEGER PRIMARY KEY AUTOINCREMENT, seller_id INTEGER, title TEXT, prompt TEXT, price INTEGER, sales INTEGER DEFAULT 0, ts REAL)''')
        cur.execute('''CREATE TABLE IF NOT EXISTS referrals(id INTEGER PRIMARY KEY AUTOINCREMENT, referrer_id INTEGER, referred_id INTEGER UNIQUE, ts REAL)''')
        cur.execute('''CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT)''')
        _migrate(cur, "users", [
            ("consent_at", "REAL DEFAULT 0"),
            ("admin_state", "TEXT DEFAULT ''"),
            ("admin_target", "INTEGER DEFAULT 0"),
            ("admin_ts", "REAL DEFAULT 0"),
        ])

def get_user(uid):
    with DbConn() as c:
        cur = c.cursor()
        cur.execute("SELECT * FROM users WHERE user_id=?", (uid,))
        r = cur.fetchone()
        if not r:
            return None
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, r))

def add_user(uid, uname, ref_by=0):
    with DbConn() as c:
        c.cursor().execute(
            "INSERT OR IGNORE INTO users(user_id, username, created_at, last_seen, referred_by) VALUES(?,?,?,?,?)",
            (uid, uname, time.time(), time.time(), ref_by)
        )

def upd(uid, **kw):
    bad = set(kw) - ALLOWED_COLS
    if bad:
        raise ValueError(f"bad cols: {bad}")
    with DbConn() as c:
        cols = ", ".join(f"{k}=?" for k in kw)
        c.cursor().execute(f"UPDATE users SET {cols} WHERE user_id=?", (*kw.values(), uid))

def add_balance(uid, field, amount):
    if field not in BALANCE_FIELDS:
        raise ValueError(f"bad balance field {field}")
    with DbConn() as c:
        c.cursor().execute(f"UPDATE users SET {field} = {field} + ? WHERE user_id=?", (amount, uid))

def sub_balance(uid, field, amount=1):
    if field not in BALANCE_FIELDS:
        return False
    with DbConn() as c:
        cur = c.cursor()
        cur.execute(f"SELECT {field} FROM users WHERE user_id=?", (uid,))
        r = cur.fetchone()
        if not r or r[0] < amount:
            return False
        cur.execute(f"UPDATE users SET {field} = {field} - ? WHERE user_id=?", (amount, uid))
        return True

def safe_send(uid, text, **kw):
    for i in range(3):
        try:
            return bot.send_message(uid, text, **kw)
        except ApiTelegramException as e:
            if e.error_code in (429, 502, 503, 504):
                time.sleep(2 ** i)
                continue
            return None
        except requests.exceptions.RequestException:
            time.sleep(2 ** i)
            continue
        except Exception:
            return None
    return None

def safe_photo(uid, photo, caption=None, **kw):
    for i in range(3):
        try:
            return bot.send_photo(uid, photo, caption=caption, **kw)
        except Exception as e:
            if "502" in str(e) or "504" in str(e) or "ReadTimeout" in str(e) or "Connection" in str(e):
                time.sleep(2 ** i)
                continue
            if caption:
                try:
                    return bot.send_message(uid, caption, **kw)
                except Exception:
                    return None
            return None
    return None

def send_image_bytes(uid, url, caption="", parse_mode="Markdown"):
    try:
        r = requests.get(url, timeout=60)
        if r.status_code == 200 and r.content:
            bot.send_photo(uid, r.content, caption=caption, parse_mode=parse_mode)
            return True
    except Exception as e:
        log.warning(f"send_image_bytes fail: {e}")
    try:
        bot.send_photo(uid, url, caption=caption, parse_mode=parse_mode)
        return True
    except Exception:
        pass
    safe_send(uid, caption or "✅ Готово, но не удалось отправить фото.")
    return False

def send_video_bytes(uid, url, caption=""):
    try:
        r = requests.get(url, timeout=180)
        if r.status_code == 200 and r.content:
            bot.send_video(uid, r.content, caption=caption, parse_mode="Markdown")
            return True
    except Exception as e:
        log.warning(f"send_video_bytes fail: {e}")
    try:
        bot.send_video(uid, url, caption=caption, parse_mode="Markdown")
        return True
    except Exception:
        pass
    safe_send(uid, caption or "✅ Готово, но не удалось отправить видео.")