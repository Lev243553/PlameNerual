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
    if not r: v = d
    else:
        try: v = int(r)
        except: raise SystemExit(f"ENV {n} not int")
    if m and v < m: raise SystemExit(f"ENV {n} < {m}")
    return v
def _env_float(n, d):
    r = os.getenv(n); return float(r) if r else d

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
    if is_admin(uid): return True
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
                cls._rate = v; cls._ts = time.time()
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
    # Картинки (CLODEX)
    "wan-2.7-image": {"name":"💨 Schnell", "type":"image", "price":4, "provider":"clodex"},
    "flux-3-image": {"name":"⚡ Flux", "type":"image", "price":8, "provider":"clodex"},
    "gpt-image-2.5": {"name":"✨ GPT-2.5", "type":"image", "price":12, "provider":"clodex"},
    "gpt-image-2.6": {"name":"👑 Ultra 2.6", "type":"image", "price":20, "provider":"clodex"},

    # Текст (CLODEX/OpenRouter)
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

# Видео (теперь цена за 1 секунду базового качества)
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
    _pool = None; _sem = None; path = ""
    @classmethod
    def init(cls, path, size):
        cls.path = path; cls._pool = queue.Queue(maxsize=size); cls._sem = threading.BoundedSemaphore(size)
        for _ in range(size): cls._pool.put(cls._make())
    @classmethod
    def _make(cls):
        c = sqlite3.connect(cls.path, timeout=30, isolation_level=None, check_same_thread=False)
        c.execute("PRAGMA journal_mode=WAL"); c.execute("PRAGMA synchronous=NORMAL")
        return c
    @classmethod
    def acquire(cls):
        cls._sem.acquire()
        try: return cls._pool.get(timeout=30)
        except Exception: cls._sem.release(); raise
    @classmethod
    def release(cls, conn):
        try: cls._pool.put_nowait(conn)
        except queue.Full: conn.close()
        finally: cls._sem.release()

class DbConn:
    def __enter__(self): self.conn = Db.acquire(); return self.conn
    def __exit__(self, *a): Db.release(self.conn); return False

def _migrate(cur, table, cols):
    cur.execute(f"PRAGMA table_info({table})")
    ex = {r[1] for r in cur.fetchall()}
    if not ex: return
    for col, ddl in cols:
        if col not in ex:
            try: cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
            except Exception: pass

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
            tasks_done TEXT DEFAULT '', custom_key TEXT DEFAULT '', custom_model TEXT DEFAULT '')''')
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
        _migrate(cur, "users", [("consent_at","REAL DEFAULT 0")])

def get_user(uid):
    with DbConn() as c:
        cur = c.cursor(); cur.execute("SELECT * FROM users WHERE user_id=?", (uid,))
        r = cur.fetchone()
        if not r: return None
        cols = [d[0] for d in cur.description]
    return dict(zip(cols, r))

def add_user(uid, uname, ref_by=0):
    with DbConn() as c:
        c.cursor().execute("INSERT OR IGNORE INTO users(user_id, username, created_at, last_seen, referred_by) VALUES(?,?,?,?,?)",
                           (uid, uname, time.time(), time.time(), ref_by))

def upd(uid, **kw):
    bad = set(kw) - ALLOWED_COLS
    if bad: raise ValueError(f"bad cols: {bad}")
    with DbConn() as c:
        cols = ", ".join(f"{k}=?" for k in kw)
        c.cursor().execute(f"UPDATE users SET {cols} WHERE user_id=?", (*kw.values(), uid))

def add_balance(uid, field, amount):
    if field not in BALANCE_FIELDS: raise ValueError(f"bad balance field {field}")
    with DbConn() as c:
        c.cursor().execute(f"UPDATE users SET {field} = {field} + ? WHERE user_id=?", (amount, uid))

def sub_balance(uid, field, amount=1):
    if field not in BALANCE_FIELDS: return False
    with DbConn() as c:
        cur = c.cursor()
        cur.execute(f"SELECT {field} FROM users WHERE user_id=?", (uid,))
        r = cur.fetchone()
        if not r or r[0] < amount: return False
        cur.execute(f"UPDATE users SET {field} = {field} - ? WHERE user_id=?", (amount, uid))
        return True

def safe_send(uid, text, **kw):
    for i in range(3):
        try: return bot.send_message(uid, text, **kw)
        except ApiTelegramException as e:
            if e.error_code in (429, 502, 503, 504): time.sleep(2 ** i); continue
            return None
        except requests.exceptions.RequestException: time.sleep(2 ** i); continue
        except Exception: return None
    return None

def safe_photo(uid, photo, caption=None, **kw):
    for i in range(3):
        try: return bot.send_photo(uid, photo, caption=caption, **kw)
        except Exception as e:
            if "502" in str(e) or "504" in str(e) or "ReadTimeout" in str(e) or "Connection" in str(e):
                time.sleep(2 ** i); continue
            if caption:
                try: return bot.send_message(uid, caption, **kw)
                except Exception: return None
            return None
    return None

def send_image_bytes(uid, url, caption="", parse_mode="Markdown"):
    try:
        r = requests.get(url, timeout=60)
        if r.status_code == 200 and r.content:
            bot.send_photo(uid, r.content, caption=caption, parse_mode=parse_mode)
            return True
    except Exception as e: log.warning(f"send_image_bytes fail: {e}")
    try:
        bot.send_photo(uid, url, caption=caption, parse_mode=parse_mode)
        return True
    except Exception: pass
    safe_send(uid, caption or "✅ Готово, но не удалось отправить фото.")
    return False

def send_video_bytes(uid, url, caption=""):
    try:
        r = requests.get(url, timeout=180)
        if r.status_code == 200 and r.content:
            bot.send_video(uid, r.content, caption=caption, parse_mode="Markdown")
            return True
    except Exception as e: log.warning(f"send_video_bytes fail: {e}")
    try:
        bot.send_video(uid, url, caption=caption, parse_mode="Markdown")
        return True
    except Exception: pass
    safe_send(uid, caption or "✅ Готово, но не удалось отправить видео.")
    return False

def log_ev(uid, action, details=""):
    with DbConn() as c:
        c.cursor().execute("INSERT INTO logs(user_id,action,details,ts) VALUES(?,?,?,?)", (uid, action, details, time.time()))

def save_history(uid, role, content):
    with DbConn() as c:
        c.cursor().execute("INSERT INTO chat_history(user_id,role,content,ts) VALUES(?,?,?,?)", (uid, role, content, time.time()))
        c.cursor().execute("DELETE FROM chat_history WHERE user_id=? AND id NOT IN (SELECT id FROM chat_history WHERE user_id=? ORDER BY id DESC LIMIT ?)", (uid, uid, MAX_HISTORY*2))

def get_history(uid, limit=MAX_HISTORY):
    with DbConn() as c:
        cur = c.cursor(); cur.execute("SELECT role,content FROM chat_history WHERE user_id=? ORDER BY id DESC LIMIT ?", (uid, limit))
        rows = cur.fetchall()
    return [{"role": r, "content": c} for r, c in reversed(rows)]

def process_referral(new_uid):
    u = get_user(new_uid) or {}
    ref_by = u.get("referred_by", 0)
    if not ref_by or ref_by == new_uid: return
    with DbConn() as c:
        cur = c.cursor()
        cur.execute("SELECT id FROM referrals WHERE referred_id=?", (new_uid,))
        if cur.fetchone(): return
        cur.execute("INSERT INTO referrals(referrer_id, referred_id, ts) VALUES(?,?,?)", (ref_by, new_uid, time.time()))
        cur.execute("UPDATE users SET ref_count = ref_count + 1 WHERE user_id=?", (ref_by,))
    add_balance(ref_by, "balance_img", REF_BONUS_REFERRER)
    add_balance(new_uid, "balance_img", REF_BONUS_REFERRED)
    safe_send(ref_by, f"🎉 Новый реферал! +{REF_BONUS_REFERRER}₽")

def claim_daily(uid):
    today = time.strftime("%Y-%m-%d")
    u = get_user(uid) or {}
    if u.get("daily_last") == today:
        return False, "🎁 Уже получил сегодня. Приходи завтра! ❄️"
    yesterday = time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400))
    streak = (u.get("daily_streak") or 0)
    streak = streak + 1 if u.get("daily_last") == yesterday else 1
    bonus_img = DAILY_BONUS_IMG + min(streak // 3, 2)
    add_balance(uid, "balance_img", bonus_img)
    upd(uid, daily_last=today, daily_streak=streak)
    return True, f"🎁 **Ежедневка!** ❄️\n\n🔥 Стрик: {streak} дн.\n🖼 +{bonus_img}₽\n"

def check_tasks(uid):
    u = get_user(uid) or {}
    done = set(filter(None, (u.get("tasks_done") or "").split(",")))
    with DbConn() as c:
        cur = c.cursor()
        cur.execute("SELECT COUNT(*) FROM works WHERE user_id=? AND m_type='image'", (uid,))
        wi = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM works WHERE user_id=? AND m_type='text'", (uid,))
        wt = cur.fetchone()[0]
    ctx = {"works_img": wi, "works_text": wt, "refs": u.get("ref_count", 0)}
    new = []
    for tid, t in TASKS.items():
        if tid in done: continue
        try:
            var, val = t["check"].split(">=")
            if ctx.get(var.strip(), 0) >= int(val): new.append(tid)
        except: pass
    if not new: return []
    for tid in new: add_balance(uid, TASKS[tid]["field"], TASKS[tid]["amount"])
    upd(uid, tasks_done=",".join(done | set(new)))
    return new

def _hash_key(k): return hashlib.sha256(k.encode()).hexdigest()

def generate_api_key(uid, days=30):
    raw = f"sk_v103_{uuid.uuid4().hex[:16]}"
    with DbConn() as c:
        c.cursor().execute("INSERT INTO api_keys(key_hash, user_id, created_at, expires_at) VALUES(?,?,?,?)",
                           (_hash_key(raw), uid, time.time(), time.time() + days*86400))
    return raw

def check_api_key(raw):
    with DbConn() as c:
        cur = c.cursor()
        cur.execute("SELECT user_id, expires_at FROM api_keys WHERE key_hash=?", (_hash_key(raw),))
        r = cur.fetchone()
        if not r or r[1] < time.time(): return None
        return r[0]

def api_access_ok(uid, est=2000):
    now = time.time()
    with DbConn() as c:
        cur = c.cursor()
        cur.execute("SELECT plan, expires_at, requests_used, tokens_used FROM api_subs WHERE user_id=?", (uid,))
        r = cur.fetchone()
        if not r or r[1] < now: return False, "no_sub"
        plan, _, req, tok = r
        p = API_SUB_PLANS.get(plan)
        if not p: return False, "no_sub"
        if req >= p["requests"]: return False, "limit_requests"
        if tok + est > p["tokens"]: return False, "limit_tokens"
        cur.execute("UPDATE api_subs SET requests_used=requests_used+1, tokens_used=tokens_used+? WHERE user_id=?", (est, uid))
        return True, "ok"

_flood = {}; _fl = threading.Lock()
def anti_flood(uid, min_sec=2):
    now = time.time()
    with _fl:
        if now - _flood.get(uid, 0) < min_sec: return False
        _flood[uid] = now; return True

def input_kb():
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(types.InlineKeyboardButton("⬅️ Назад в меню", callback_data="menu_main"))
    return kb

def _prov(provider):
    if provider == "clodex":
        return f"{CLODEX_API_URL}/chat/completions", {"Authorization": f"Bearer {CLODEX_API_KEY}", "Content-Type": "application/json; charset=utf-8"}
    if provider == "ranvik":
        return f"{RANVIK_API_URL}/chat/completions", {"Authorization": f"Bearer {RANVIK_API_KEY}", "Content-Type": "application/json; charset=utf-8"}
    return "https://openrouter.ai/api/v1/chat/completions", {"Authorization": f"Bearer {OPENROUTER_KEY}", "Content-Type": "application/json; charset=utf-8"}

def _stream(url, headers, body, attempts=3):
    last = None
    for i in range(attempts):
        try:
            r = requests.post(url, headers=headers, json=body, timeout=(15, HTTP_TIMEOUT_LONG[1]), stream=True)
            r.encoding = 'utf-8'
            if r.status_code in (429,502,503,504): last = r.status_code; time.sleep(2**i); continue
            if r.status_code != 200: return False, r.text[:300], r.status_code
            full = []
            for raw in r.iter_lines(decode_unicode="utf-8"):
                if not raw or not raw.startswith("data:"): continue
                p = raw[5:].strip()
                if p == "[DONE]": break
                try: c = json.loads(p)
                except: continue
                ch = c.get("choices") or []
                if ch:
                    pc = (ch[0].get("delta") or {}).get("content")
                    if pc: full.append(pc)
                elif c.get("type") == "content_block_delta":
                    pc = (c.get("delta") or {}).get("text")
                    if pc: full.append(pc)
            ans = "".join(full).strip()
            if not ans: return False, "❄️ Пустой ответ.", 0
            return True, ans, 200
        except requests.RequestException as e:
            last = str(e); time.sleep(2**i)
    return False, f"❄️ Недоступно. ({last})", 0

def gen_text(uid, mid, prompt, use_history=True, max_tokens=2048, thinking_level=None):
    if mid not in MODELS: return f"❌ Модель {mid} не найдена"
    p = MODELS[mid]["provider"]
    url, headers = _prov(p)
    msgs = []
    if mid == "nvidia/nemotron-3-ultra-550b-a55b:free":
        msgs.append({"role": "system", "content": "Ты — ИИ Нейро. Никогда не говори, что ты ChatGPT или OpenAI. Ты в Нейро-Студии."})
    if use_history: msgs.extend(get_history(uid))
    msgs.append({"role":"user","content":prompt})
    
    body = {"model": mid, "messages": msgs, "stream": True, "max_tokens": max_tokens}
    if mid.startswith("gemini-4-") and thinking_level:
        body["thinking_level"] = thinking_level
        
    ok, res, code = _stream(url, headers, body)
    if not ok and code == 400 and "cyber" in str(res).lower() and p != "clodex":
        u2, h2 = _prov("clodex")
        ok2, res2, _ = _stream(u2, h2, {**body, "model":"deepseek-v4.1-flash"})
        if ok2: return res2 + "\n\n_🔄 (фолбэк)_"
    if not ok:
        if code == 400 and "cyber" in str(res).lower(): return "🛡 Цензор. Переформулируй."
        return res
    if use_history:
        save_history(uid, "user", prompt); save_history(uid, "assistant", res)
    try: res = res.encode('latin-1').decode('utf-8')
    except Exception: pass
    return res

def gen_image(uid, mid, prompt):
    m = MODELS[mid]; cost = m["price"]
    if m["provider"] == "clodex":
        url = f"{CLODEX_API_URL}/images/generations"
        headers = {"Authorization": f"Bearer {CLODEX_API_KEY}", "Content-Type": "application/json"}
    else: return None, cost
    body = {"model": mid, "prompt": prompt, "n": 1, "size": "1024x1024"}
    for i in range(3):
        try:
            r = requests.post(url, headers=headers, json=body, timeout=HTTP_TIMEOUT_LONG)
            if r.status_code in (429,502,503,504): time.sleep(2**i); continue
            if r.status_code != 200:
                log.warning(f"gen_image {mid}: {r.status_code} {r.text[:200]}"); return None, cost
            d = r.json()
            return (d["data"][0].get("url") if d.get("data") else None), cost
        except Exception as e:
            log.warning(f"gen_image {mid}: {e}"); time.sleep(2**i)
    return None, cost

def calc_video_price(mid, duration, resolution, aspect):
    base_price = VIDEO_MODELS[mid]["price"]
    res_mult = {"720p": 1.0, "1080p": 1.5, "4k": 3.0}.get(resolution, 1.0)
    aspect_mult = {"16:9": 1.0, "9:16": 1.2, "1:1": 1.1}.get(aspect, 1.0)
    return int(round(base_price * duration * res_mult * aspect_mult))

def gen_video(uid, mid, prompt, duration=5, resolution="720p", aspect="16:9"):
    cost = calc_video_price(mid, duration, resolution, aspect)
    url = f"{CLODEX_API_URL}/videos/generations"
    headers = {"Authorization": f"Bearer {CLODEX_API_KEY}", "Content-Type": "application/json"}
    
    body = {
        "model": mid,
        "prompt": prompt,
        "duration": duration,
        "resolution": resolution,
        "aspect_ratio": aspect
    }
    try:
        r = requests.post(url, headers=headers, json=body, timeout=HTTP_TIMEOUT_LONG)
        if r.status_code != 200:
            log.warning(f"gen_video {mid}: {r.status_code} {r.text[:200]}")
            return None, cost
        d = r.json()
        video_url = d.get("url") or (d.get("data",[{}])[0].get("url") if d.get("data") else None)
        return video_url, cost
    except Exception as e:
        log.warning(f"gen_video {mid}: {e}")
        return None, cost

def fulfill_by_payload(uid, payload, amount, provider="", charge_id="", stars=0):
    if payload.startswith("custom_"):
        try: real = int(payload.rsplit("_", 1)[1])
        except: real = amount
        add_balance(uid, "balance_img", real)
        safe_photo(uid, IMG_BAL, f"✅ **Пополнено на {real}₽** ❄️\n\n🎁 Баланс картинок: +{real}₽", parse_mode="Markdown")
        with DbConn() as c:
            c.cursor().execute("INSERT INTO payments(user_id,package_id,amount,status,provider_id,ts,kind,provider,stars_amount) VALUES(?,?,?,?,?,?,?,?,?)",
                               (uid, payload, real, "paid", charge_id, time.time(), "balance", provider, stars))
        log_ev(uid, "paid", f"custom {real} via {provider}")
        if ADMIN_ID:
            safe_send(ADMIN_ID, f"💰 **Оплата (своя сумма)** ❄️\n\n👤 {uid}\n💵 {real}₽\n💳 {provider}", parse_mode="Markdown")
        return

    kind = "balance"
    if payload.startswith("sub_"): kind = "sub"
    elif payload in API_SUB_PLANS: kind = "api_sub"
    recognized = False

    if payload in TEXT_SUB_TARIFFS:
        recognized = True
        t = TEXT_SUB_TARIFFS[payload]
        u = get_user(uid) or {}
        until = max(u.get("sub_until",0), time.time()) + t["days"]*86400
        upd(uid, sub_plan=payload, sub_until=until, sub_used=0, sub_tokens_used=0)
        safe_photo(uid, IMG_SUB, f"✅ **«{t['title']}» активирована!**\n\n🎁 {t['tokens']:,} токенов\n⏳ {t['days']} дней", parse_mode="Markdown")
    elif payload in BALANCE_PACKS:
        recognized = True
        p = BALANCE_PACKS[payload]
        add_balance(uid, p["field"], p["amount"])
        safe_photo(uid, IMG_BAL, f"✅ **{p['title']} зачислено!**\n\n🎁 +{p['amount']}₽", parse_mode="Markdown")
        kb = types.InlineKeyboardMarkup(row_width=1)
        if p["field"] == "balance_img": kb.add(types.InlineKeyboardButton("🎨 Сгенерировать картинку", callback_data="menu_images"))
        elif p["field"] == "balance_vid": kb.add(types.InlineKeyboardButton("🎬 Сгенерировать видео", callback_data="menu_video"))
        kb.add(types.InlineKeyboardButton("💠 Мой баланс", callback_data="menu_balance"))
        safe_send(uid, "👉 Что дальше?", reply_markup=kb)
    elif payload in API_SUB_PLANS:
        recognized = True
        p = API_SUB_PLANS[payload]; now = time.time()
        with DbConn() as c:
            cur = c.cursor()
            cur.execute("SELECT expires_at FROM api_subs WHERE user_id=?", (uid,))
            r = cur.fetchone(); base = max(r[0] if r else 0, now)
            cur.execute("INSERT OR REPLACE INTO api_subs(user_id, plan, expires_at, requests_used, tokens_used) VALUES(?,?,?,0,0)",
                        (uid, payload, base + p["days"]*86400))
        safe_photo(uid, IMG_BAL, f"✅ **{p['title']} активирован!**", parse_mode="Markdown")

    with DbConn() as c:
        c.cursor().execute("INSERT INTO payments(user_id,package_id,amount,status,provider_id,ts,kind,provider,stars_amount) VALUES(?,?,?,?,?,?,?,?,?)",
                           (uid, payload, amount, "paid", charge_id, time.time(), kind, provider, stars))
    if not recognized:
        log.error(f"UNRECOGNIZED PAYLOAD: {payload} uid={uid}")
        if ADMIN_ID: safe_send(ADMIN_ID, f"⚠️ Неизвестный payload: {payload} uid={uid}")

def send_stars_invoice(uid, title, description, payload, rub_price):
    stars = rub_to_stars(rub_price)
    try:
        bot.send_invoice(chat_id=uid, title=title[:32], description=description[:255], invoice_payload=payload,
                         provider_token="", currency="XTR", prices=[types.LabeledPrice(label=title[:32], amount=stars)])
        return True
    except Exception: return False

def platega_create(uid, rub, desc, pkg, kind="balance"):
    if not PLATEGA_ID or not PLATEGA_SECRET: return None, None
    idem = f"pay_{uid}_{int(time.time())}_{uuid.uuid4().hex[:6]}"
    payload = {"paymentMethod": 2, "paymentDetails": {"amount": rub, "currency": "RUB"}, "description": desc,
               "return": RETURN_URL or "https://t.me", "failedUrl": RETURN_URL or "https://t.me",
               "payload": idem, "metadata": {"userId": str(uid)}}
    headers = {"X-MerchantId": PLATEGA_ID, "X-Secret": PLATEGA_SECRET, "Content-Type": "application/json"}
    try:
        r = requests.post(f"{PLATEGA_URL}/v2/transaction/process", headers=headers, json=payload, timeout=HTTP_TIMEOUT_MED)
        if r.status_code not in (200, 201): return None, None
        d = r.json(); url = d.get("url") or d.get("redirect")
        if not url: return None, None
        pid = None
        with DbConn() as c:
            cur = c.cursor()
            cur.execute("INSERT INTO payments(user_id,package_id,amount,status,provider_id,ts,kind,provider) VALUES(?,?,?,?,?,?,?,?)",
                        (uid, pkg, rub, "pending", d.get("transactionId",""), time.time(), kind, "platega"))
            pid = cur.lastrowid
        return url, pid
    except Exception: return None, None

def platega_check(pid):
    with DbConn() as c:
        cur = c.cursor(); cur.execute("SELECT provider_id, user_id, package_id, amount FROM payments WHERE id=?", (pid,))
        r = cur.fetchone()
    if not r: return "failed"
    prov, uid, pkg, amt = r
    if not prov or not PLATEGA_ID: return "pending"
    headers = {"X-MerchantId": PLATEGA_ID, "X-Secret": PLATEGA_SECRET}
    try:
        resp = requests.get(f"{PLATEGA_URL}/transaction/{prov}", headers=headers, timeout=HTTP_TIMEOUT_MED)
        if resp.status_code != 200: return "pending"
        st = (resp.json().get("status") or "").upper()
        if st in ("CONFIRMED","SUCCESS","PAID"):
            _fulfill_platega(pid, uid, pkg, amt); return "paid"
        if st in ("CANCELED","FAILED","EXPIRED"): return "failed"
    except Exception: pass
    return "pending"

def _fulfill_platega(pid, uid, pkg, amt):
    with DbConn() as c:
        cur = c.cursor(); cur.execute("SELECT status FROM payments WHERE id=?", (pid,))
        r = cur.fetchone()
        if not r or r[0] == "paid": return
        cur.execute("UPDATE payments SET status='paid' WHERE id=?", (pid,))
    fulfill_by_payload(uid, pkg, amt, "platega")

def grosh_create(uid, rub, desc, pkg, kind="balance"):
    if not GROSH_API_KEY: return None, None
    idem = f"grosh_{uid}_{int(time.time())}_{uuid.uuid4().hex[:6]}"
    usd = FxAnalyzer.rub_to_usd(rub)
    body = {"amount": usd, "label": desc[:100], "payload": idem, "webhook": f"{RETURN_URL or 'https://t.me'}/grosh_webhook", "success_url": RETURN_URL or "https://t.me"}
    headers = {"Authorization": f"Bearer {GROSH_API_KEY}", "Content-Type": "application/json"}
    try:
        r = requests.post(f"{GROSH_API_URL}/api/payments", headers=headers, json=body, timeout=HTTP_TIMEOUT_MED)
        if r.status_code not in (200, 201): return None, None
        d = r.json(); url = d.get("url") or d.get("payment_url") or d.get("redirect")
        pay_id = d.get("paymentId") or d.get("id")
        if not url or not pay_id: return None, None
        pid = None
        with DbConn() as c:
            cur = c.cursor()
            cur.execute("INSERT INTO payments(user_id,package_id,amount,status,provider_id,ts,kind,provider) VALUES(?,?,?,?,?,?,?,?)",
                        (uid, pkg, rub, "pending", pay_id, time.time(), kind, "grosh"))
            pid = cur.lastrowid
        return url, pid
    except Exception: return None, None

def grosh_check(pid):
    with DbConn() as c:
        cur = c.cursor(); cur.execute("SELECT provider_id, user_id, package_id, amount FROM payments WHERE id=?", (pid,))
        r = cur.fetchone()
    if not r: return "failed"
    prov, uid, pkg, amt = r
    if not prov: return "pending"
    try:
        resp = requests.get(f"{GROSH_API_URL}/api/payments/{prov}", timeout=HTTP_TIMEOUT_MED)
        if resp.status_code != 200: return "pending"
        st = (resp.json().get("status") or "").lower()
        if st == "paid":
            _fulfill_grosh(pid, uid, pkg, amt); return "paid"
        if st in ("expired","cancelled","failed"): return "failed"
    except Exception: pass
    return "pending"

def _fulfill_grosh(pid, uid, pkg, amt):
    with DbConn() as c:
        cur = c.cursor(); cur.execute("SELECT status FROM payments WHERE id=?", (pid,))
        r = cur.fetchone()
        if not r or r[0] == "paid": return
        cur.execute("UPDATE payments SET status='paid' WHERE id=?", (pid,))
    fulfill_by_payload(uid, pkg, amt, "grosh")

def _notify_paid(uid, pkg):
    title = "товар"
    if pkg in BALANCE_PACKS: title = BALANCE_PACKS[pkg]["title"]
    elif pkg in TEXT_SUB_TARIFFS: title = TEXT_SUB_TARIFFS[pkg]["title"]
    elif pkg in API_SUB_PLANS: title = API_SUB_PLANS[pkg]["title"]
    elif pkg.startswith("custom_"): title = "пополнение"
    safe_send(uid, f"✅ **Оплата получена!**\n\n📦 {title}\n\nСпасибо! ❄️", parse_mode="Markdown")

def payment_poller():
    while not SHUTDOWN.is_set():
        try:
            with DbConn() as c:
                cur = c.cursor()
                cur.execute("SELECT id, user_id, package_id FROM payments WHERE status='pending' AND provider='platega' AND ts > ? LIMIT 20", (time.time()-86400,))
                for pid, uid, pkg in cur.fetchall():
                    if platega_check(pid) == "paid": _notify_paid(uid, pkg)
                if grosh_enabled():
                    cur.execute("SELECT id, user_id, package_id FROM payments WHERE status='pending' AND provider='grosh' AND ts > ? LIMIT 20", (time.time()-86400,))
                    for pid, uid, pkg in cur.fetchall():
                        if grosh_check(pid) == "paid": _notify_paid(uid, pkg)
        except Exception as e: log.error(f"poller: {e}")
        time.sleep(PAYMENT_POLL_SEC)

def start_health(port):
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/health":
                b = b'{"status":"ok"}'; self.send_response(200); self.send_header("Content-Type","application/json"); self.end_headers(); self.wfile.write(b)
            else: self.send_response(404); self.end_headers()
        def do_POST(self):
            if self.path == "/api/v1/generate":
                try:
                    ln = int(self.headers.get('Content-Length',0))
                    auth = self.headers.get("Authorization","")
                    if not auth.startswith("Bearer "): self._j(401, {"error":"no token"}); return
                    uid = check_api_key(auth.split(" ")[1])
                    if not uid: self._j(403, {"error":"invalid"}); return
                    ok, reason = api_access_ok(uid)
                    if not ok: self._j(429, {"error": reason}); return
                    d = json.loads(self.rfile.read(ln))
                    t, m, p = d.get("type","text"), d.get("model","gpt-6-astra"), d.get("prompt","")
                    if not p: self._j(400, {"error":"empty"}); return
                    if t == "text":
                        self._j(200, {"status":"ok","content": gen_text(uid, m, p)})
                    elif t == "image":
                        cost = MODELS.get(m, {}).get("price", 4)
                        if not is_admin(uid) and not charge(uid, "balance_img", cost):
                            self._j(402, {"error": "insufficient balance"}); return
                        u, _ = gen_image(uid, m, p)
                        if u: self._j(200, {"status":"ok","url":u})
                        else:
                            if REFUND_ON_ERROR and not is_admin(uid): add_balance(uid, "balance_img", cost)
                            self._j(500, {"error": "img", "refunded": bool(REFUND_ON_ERROR)})
                    else: self._j(400, {"error":"bad type"})
                except Exception as e: self._j(500, {"error": str(e)})
            else: self.send_response(404); self.end_headers()
        def _j(self, c, d):
            b = json.dumps(d).encode(); self.send_response(c); self.send_header("Content-Type","application/json"); self.end_headers(); self.wfile.write(b)
        def log_message(self,*a): pass
    srv = http.server.ThreadingHTTPServer(("0.0.0.0", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

# ==========================================================
# 🎨 МЕНЮ И ЭКРАНЫ
# ==========================================================
def payment_choice_kb(payload, rub_price):
    kb = types.InlineKeyboardMarkup(row_width=1)
    stars = rub_to_stars(rub_price)
    kb.add(types.InlineKeyboardButton(f"⭐ Оплатить {stars}⭐", callback_data=f"stars_{payload}"))
    kb.add(types.InlineKeyboardButton(f"💳 СБП {rub_price}₽", callback_data=f"platega_{payload}"))
    if grosh_enabled(): kb.add(types.InlineKeyboardButton(f"🟢 Grosh {rub_price}₽", callback_data=f"grosh_{payload}"))
    kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="menu_main"))
    return kb

def show_main_menu(uid):
    kb = types.InlineKeyboardMarkup(row_width=MENU_MAIN_COLS)
    kb.add(types.InlineKeyboardButton("🖼 Картинки", callback_data="menu_images"))
    kb.add(types.InlineKeyboardButton("💬 Текст / ИИ", callback_data="menu_text"))
    kb.add(types.InlineKeyboardButton("🎬 Видео", callback_data="menu_video"))
    kb.add(types.InlineKeyboardButton("💳 Пополнить", callback_data="menu_topup"))
    kb.add(types.InlineKeyboardButton("⚙️ Ещё", callback_data="menu_more"))
    safe_photo(uid, IMG_MAIN, "❄️ **Нейро-Студия** ❄️\n\n🖼 Картинка от **4₽**\n💬 Вопрос от **1₽**\n🎬 Видео от **19₽**\n\n🎁 **Бесплатно:** 1 картинка + 2 вопроса\n🛡 Ошибка? Вернём баланс.\n\nВыбери раздел 👇", reply_markup=kb, parse_mode="Markdown")

def show_text_menu(uid):
    u = get_user(uid) or {}
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(types.InlineKeyboardButton("🧠 Carbon — 7₽ (сложные)", callback_data="txt_carbon"))
    kb.add(types.InlineKeyboardButton("🔥 Fable 5.2 — 5₽ (топ)", callback_data="txt_fable"))
    kb.add(types.InlineKeyboardButton("🌟 Astra — 3₽", callback_data="txt_astra"))
    kb.add(types.InlineKeyboardButton("☀️ Sol Ultra — 3₽", callback_data="txt_sol"))
    kb.add(types.InlineKeyboardButton("🎭 Opus 5 — 3₽", callback_data="txt_opus5"))
    kb.add(types.InlineKeyboardButton("🚀 Hydrogen — 2₽", callback_data="txt_hydrogen"))
    kb.add(types.InlineKeyboardButton("🤖 Grok Fast — 2₽", callback_data="txt_grok"))
    kb.add(types.InlineKeyboardButton("⚡ Luna — 1₽", callback_data="txt_luna"))
    kb.add(types.InlineKeyboardButton("🇨🇳 GLM 5.3 — 1₽", callback_data="txt_glm"))
    kb.add(types.InlineKeyboardButton("🔬 DeepSeek — 1₽", callback_data="txt_deepseek"))
    kb.add(types.InlineKeyboardButton("🆓 Nemotron (Бесплатно)", callback_data="txt_free"))
    kb.add(types.InlineKeyboardButton("🤖 3 мнения ИИ", callback_data="menu_agents"))
    kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="menu_main"))
    safe_photo(uid, IMG_TEXT, f"💬 **Текст / ИИ** ❄️\n\n🎟 Бесплатных: {max(0, FREE_TEXT_LIMIT - u.get('text_free_used',0))}/{FREE_TEXT_LIMIT}\n\nВыбери модель 👇", reply_markup=kb, parse_mode="Markdown")

def show_more_menu(uid):
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(types.InlineKeyboardButton("💠 Баланс", callback_data="menu_balance"))
    kb.add(types.InlineKeyboardButton("📚 Подписки", callback_data="menu_subs"))
    kb.add(types.InlineKeyboardButton("🎁 Ежедневка", callback_data="daily_bonus"))
    kb.add(types.InlineKeyboardButton("🏆 Задания", callback_data="menu_tasks"))
    kb.add(types.InlineKeyboardButton("👥 Рефералы", callback_data="menu_refs"))
    kb.add(types.InlineKeyboardButton("📜 История", callback_data="menu_history"))
    kb.add(types.InlineKeyboardButton("🔑 API", callback_data="menu_api"))
    kb.add(types.InlineKeyboardButton("💱 Курс", callback_data="menu_rate"))
    kb.add(types.InlineKeyboardButton("📸 Примеры", callback_data="menu_examples"))
    kb.add(types.InlineKeyboardButton("🆘 Помощь", callback_data="menu_help"))
    if uid == ADMIN_ID: kb.add(types.InlineKeyboardButton("🛡 Админ", callback_data="admin_root"))
    kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="menu_main"))
    safe_photo(uid, IMG_TEXT, "⚙️ **Ещё** ❄️", reply_markup=kb, parse_mode="Markdown")

def show_examples(uid):
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(types.InlineKeyboardButton("🖼 Картинки", callback_data="menu_images"))
    kb.add(types.InlineKeyboardButton("💬 Текст", callback_data="menu_text"))
    kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="menu_more"))
    safe_photo(uid, IMG_EXAMPLES, "📸 **Примеры** ❄️\n\n🖼 Картинка — 4₽\n💬 Текст — 1₽\n🎬 Видео — 19₽\n\n🎁 Первая картинка + 2 вопроса бесплатно", reply_markup=kb, parse_mode="Markdown")

def show_help(uid):
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(types.InlineKeyboardButton("🆘 Поддержка", url=SUPPORT_URL))
    if TERMS_URL: kb.add(types.InlineKeyboardButton("📄 Соглашение", url=TERMS_URL))
    if PRIVACY_URL: kb.add(types.InlineKeyboardButton("🔒 Политика", url=PRIVACY_URL))
    kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="menu_more"))
    safe_photo(uid, IMG_HELP, "🆘 **Помощь** ❄️\n\n1️⃣ Пополнить → пакет или своя сумма\n2️⃣ Оплати ⭐ / 💳 СБП / 🟢 Grosh\n3️⃣ Баланс зачислится (до 1 мин)\n\n🛡 **Гарантия:** ошибка генерации → возврат баланса", reply_markup=kb, parse_mode="Markdown")

def show_consent(uid, ref_by=0):
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(types.InlineKeyboardButton("✅ Принимаю", callback_data=f"consent_yes_{ref_by}"))
    if TERMS_URL: kb.add(types.InlineKeyboardButton("📄 Соглашение", url=TERMS_URL))
    if PRIVACY_URL: kb.add(types.InlineKeyboardButton("🔒 Политика", url=PRIVACY_URL))
    safe_photo(uid, IMG_MAIN, "❄️ **Добро пожаловать!** ❄️\n\n✅ Принимаю соглашение\n✅ Согласен с политикой\n✅ Мне 18+\n✅ Не буду использовать для незаконного\n\nНажми **✅ Принимаю**", reply_markup=kb, parse_mode="Markdown")

def show_insufficient(uid, need, field="balance_img"):
    label = "картинки" if field == "balance_img" else ("видео" if field == "balance_vid" else "текст")
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(types.InlineKeyboardButton(f"💎 Пополнить ровно на {need}₽", callback_data=f"payneed_{field}_{need}"))
    kb.add(types.InlineKeyboardButton("💳 Пополнить пакетом", callback_data="menu_topup"))
    kb.add(types.InlineKeyboardButton("⬅️ Назад в меню", callback_data="menu_main"))
    safe_send(uid, f"❌ Не хватает баланса\n\n💰 Нужно: **{need}₽** на {label}\n\n💡 Можешь пополнить ровно на {need}₽ или выбрать пакет:", reply_markup=kb, parse_mode="Markdown")

def show_video_settings(uid, mid):
    if mid not in VIDEO_MODELS: return
    u = get_user(uid) or {}
    state = u.get("state", "")
    parts = state.split("_")
    
    dur = int(parts[3]) if len(parts) > 3 else VIDEO_MODELS[mid]["base_sec"]
    res = parts[4] if len(parts) > 4 else "720p"
    asp = parts[5] if len(parts) > 5 else "16:9"
    
    new_state = f"vid_setup_{mid}_{dur}_{res}_{asp}"
    upd(uid, state=new_state, temp_model_id=mid)
    
    price = calc_video_price(mid, dur, res, asp)
    
    txt = (f"🎬 **{VIDEO_MODELS[mid]['name']}** ❄️\n\n"
           f"⏱ **Время:** {dur} сек\n"
           f"📺 **Разрешение:** {res}\n"
           f"📐 **Формат:** {asp}\n\n"
           f"💰 **Итого: {price}₽**\n"
           f"🎟 Баланс: {u.get('balance_vid',0)}₽\n\n"
           f"Настрой параметры или жми «Подтвердить»:")
           
    kb = types.InlineKeyboardMarkup(row_width=3)
    
    kb.add(types.InlineKeyboardButton("⏱ Время", callback_data="ignore"))
    for d in [3, 5, 10]:
        check = "✅ " if d == dur else ""
        kb.add(types.InlineKeyboardButton(f"{check}{d}с", callback_data=f"vset_{mid}_d_{d}_{res}_{asp}"))
        
    kb.add(types.InlineKeyboardButton("📺 Качество", callback_data="ignore"))
    for r in ["720p", "1080p", "4k"]:
        check = "✅ " if r == res else ""
        kb.add(types.InlineKeyboardButton(f"{check}{r}", callback_data=f"vset_{mid}_r_{dur}_{r}_{asp}"))
        
    kb.add(types.InlineKeyboardButton("📐 Формат", callback_data="ignore"))
    for a in ["16:9", "9:16", "1:1"]:
        check = "✅ " if a == asp else ""
        kb.add(types.InlineKeyboardButton(f"{check}{a}", callback_data=f"vset_{mid}_a_{dur}_{res}_{a}"))
        
    kb.add(types.InlineKeyboardButton("✅ Подтвердить и написать промпт", callback_data="vid_confirm"))
    kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="menu_video"))
    
    safe_photo(uid, IMG_VIDEO, txt, reply_markup=kb, parse_mode="Markdown")

# ==========================================================
# 🎯 HANDLERS
# ==========================================================
def register_handlers():

    @bot.pre_checkout_query_handler(func=lambda q: True)
    def pre_checkout(q): bot.answer_pre_checkout_query(q.id, ok=True)

    @bot.message_handler(content_types=["successful_payment"])
    def on_stars_paid(m):
        p = m.successful_payment; uid = m.from_user.id
        try: fulfill_by_payload(uid, p.invoice_payload, p.total_amount, "stars", p.payment_charge_id, p.total_amount)
        except Exception as e: log.error(f"STARS FULFILL FAIL: {e}")

    @bot.message_handler(commands=["start"])
    def start(m):
        uid = m.from_user.id; args = m.text.split(); ref_by = 0
        if len(args) > 1 and args[1].startswith("ref_"):
            try: ref_by = int(args[1][4:])
            except: pass
        add_user(uid, m.from_user.username or f"id{uid}", ref_by)
        u = get_user(uid) or {}
        if not u.get("consent_at"): return show_consent(uid, ref_by)
        if not u.get("free_image") and FREE_WELCOME_IMG > 0:
            add_balance(uid, "balance_img", FREE_WELCOME_IMG); upd(uid, free_image=1)
            safe_send(uid, f"🎁 Подарок: **+{FREE_WELCOME_IMG}₽**!", parse_mode="Markdown")
        upd(uid, state="", last_seen=time.time())
        show_main_menu(uid)

    @bot.callback_query_handler(func=lambda c: c.data.startswith("consent_yes"))
    def cb_consent(c):
        uid = c.from_user.id
        try:
            upd(uid, consent_at=time.time(), consent_version=CONSENT_VERSION, onboarded=1)
            process_referral(uid); log_ev(uid, "consent", CONSENT_VERSION)
            bot.answer_callback_query(c.id, "✅ Принято!")
            u = get_user(uid) or {}
            if not u.get("free_image") and FREE_WELCOME_IMG > 0:
                add_balance(uid, "balance_img", FREE_WELCOME_IMG); upd(uid, free_image=1)
            show_main_menu(uid)
        except Exception: bot.answer_callback_query(c.id, "❌ Ошибка. /start", show_alert=True)

    @bot.callback_query_handler(func=lambda c: c.data == "menu_main")
    def cb_main(c):
        bot.answer_callback_query(c.id); upd(c.from_user.id, state=""); show_main_menu(c.from_user.id)

    @bot.callback_query_handler(func=lambda c: c.data == "menu_more")
    def cb_more(c): bot.answer_callback_query(c.id); show_more_menu(c.from_user.id)

    @bot.callback_query_handler(func=lambda c: c.data == "menu_text")
    def cb_text(c): bot.answer_callback_query(c.id); show_text_menu(c.from_user.id)

    @bot.callback_query_handler(func=lambda c: c.data == "menu_examples")
    def cb_ex(c): bot.answer_callback_query(c.id); show_examples(c.from_user.id)

    @bot.callback_query_handler(func=lambda c: c.data == "menu_help")
    def cb_help(c): bot.answer_callback_query(c.id); show_help(c.from_user.id)

    @bot.callback_query_handler(func=lambda c: c.data == "menu_rate")
    def cb_rate(c):
        bot.answer_callback_query(c.id)
        rate = FxAnalyzer.current()
        safe_send(c.from_user.id, f"💱 **Курс USD** ❄️\n\nЦБ РФ: {rate:.2f}₽\nС наценкой: {rate * (1 + FX_MARKUP_PCT/100):.2f}₽", parse_mode="Markdown")

    @bot.callback_query_handler(func=lambda c: c.data == "daily_bonus")
    def cb_daily(c):
        ok, msg = claim_daily(c.from_user.id)
        bot.answer_callback_query(c.id, "🎁" if ok else "⏳", show_alert=not ok)
        safe_send(c.from_user.id, msg)

    @bot.callback_query_handler(func=lambda c: c.data == "cancel_gen")
    def cb_cancel(c):
        upd(c.from_user.id, state="")
        bot.answer_callback_query(c.id, "❌ Отменено", show_alert=True)
        try: bot.delete_message(c.from_user.id, c.message.message_id)
        except: pass
        show_main_menu(c.from_user.id)
        
    @bot.callback_query_handler(func=lambda c: c.data == "ignore")
    def cb_ignore(c): bot.answer_callback_query(c.id)

    # ---------- ТЕКСТ ----------
    @bot.callback_query_handler(func=lambda c: c.data in ("txt_hydrogen", "txt_carbon", "txt_luna", "txt_deepseek", "txt_astra", "txt_opus5", "txt_fable", "txt_free", "txt_sol", "txt_grok", "txt_glm"))
    def cb_txt_model(c):
        mapping = {
            "txt_hydrogen": "gemini-4-hydrogen",
            "txt_carbon": "gemini-4-carbon",
            "txt_fable": "claude-fable-5.2",
            "txt_astra": "gpt-6-astra",
            "txt_opus5": "claude-opus-5",
            "txt_sol": "gpt-6.1-sol-ultrafast",
            "txt_grok": "grok-4.7-build-fast",
            "txt_glm": "glm-5.3",
            "txt_luna": "gpt-6-luna",
            "txt_deepseek": "deepseek-v4.1-flash",
            "txt_free": "nvidia/nemotron-3-ultra-550b-a55b:free",
        }
        mid = mapping.get(c.data)
        if not mid: return bot.answer_callback_query(c.id, "❌")
        bot.answer_callback_query(c.id); u = get_user(c.from_user.id) or {}
        
        if mid in ("gemini-4-hydrogen", "gemini-4-carbon"):
            kb = types.InlineKeyboardMarkup(row_width=1)
            kb.add(types.InlineKeyboardButton("🟢 Low (быстро)", callback_data=f"think_{mid}_low"))
            kb.add(types.InlineKeyboardButton("🟡 Medium (баланс)", callback_data=f"think_{mid}_medium"))
            kb.add(types.InlineKeyboardButton("🔴 High (глубоко)", callback_data=f"think_{mid}_high"))
            kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="menu_text"))
            return safe_photo(c.from_user.id, IMG_TEXT, f"{MODELS[mid]['name']} ❄️\n\nВыбери глубину мышления:\n🟢 **Low** — мгновенный ответ\n🟡 **Medium** — баланс\n🔴 **High** — глубокий анализ", reply_markup=kb, parse_mode="Markdown")
        
        upd(c.from_user.id, state=f"txt_{mid}")
        price = "Бесплатно" if MODELS[mid]["price"] == 0 else f"{MODELS[mid]['price']}₽"
        safe_photo(c.from_user.id, IMG_TEXT, f"{MODELS[mid]['name']} ❄️\n\n💰 {price}\n{MODEL_HINTS.get(mid,'')}\n🧠 Бесплатных: {max(0, FREE_TEXT_LIMIT - u.get('text_free_used',0))}/{FREE_TEXT_LIMIT}\n\n✍️ Вопрос:", reply_markup=input_kb(), parse_mode="Markdown")

    @bot.callback_query_handler(func=lambda c: c.data.startswith("think_"))
    def cb_think_level(c):
        parts = c.data.split("_")
        if len(parts) < 3: return bot.answer_callback_query(c.id, "❌")
        mid, level = parts[1], parts[2]
        if mid not in MODELS: return bot.answer_callback_query(c.id, "❌")
        bot.answer_callback_query(c.id); u = get_user(c.from_user.id) or {}
        upd(c.from_user.id, state=f"txt_{mid}_{level}")
        price = f"{MODELS[mid]['price']}₽"
        level_name = {"low": "Low 🟢", "medium": "Medium 🟡", "high": "High 🔴"}.get(level, level)
        safe_photo(c.from_user.id, IMG_TEXT, f"{MODELS[mid]['name']} ({level_name}) ❄️\n\n💰 {price}\n{MODEL_HINTS.get(mid,'')}\n🧠 Бесплатных: {max(0, FREE_TEXT_LIMIT - u.get('text_free_used',0))}/{FREE_TEXT_LIMIT}\n\n✍️ Вопрос:", reply_markup=input_kb(), parse_mode="Markdown")

    @bot.callback_query_handler(func=lambda c: c.data == "menu_agents")
    def cb_ag(c):
        bot.answer_callback_query(c.id); u = get_user(c.from_user.id) or {}
        price_line = "🆓 Бесплатно (админ)" if is_admin(c.from_user.id) else f"💰 Цена: {AGENT_PRICE_IMG}₽"
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("➕ Создать агента", callback_data="create_agent"))
        kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="menu_text"))
        safe_photo(c.from_user.id, IMG_TEXT, f"🤖 **3 мнения ИИ** ❄️\n\nПолучишь 3 ответа от разных моделей.\n\n{price_line}\n🎟 Баланс: {u.get('balance_img',0)}₽", reply_markup=kb, parse_mode="Markdown")

    @bot.callback_query_handler(func=lambda c: c.data == "create_agent")
    def cb_cag(c):
        u = get_user(c.from_user.id) or {}
        if not is_admin(c.from_user.id) and u.get("balance_img", 0) < AGENT_PRICE_IMG:
            return show_insufficient(c.from_user.id, AGENT_PRICE_IMG, "balance_img")
        bot.answer_callback_query(c.id, "✍️ Напиши вопрос!", show_alert=True)
        upd(c.from_user.id, state="agent_wait_prompt")

    # ---------- БАЛАНС ----------
    @bot.callback_query_handler(func=lambda c: c.data == "menu_balance")
    def cb_bal(c):
        bot.answer_callback_query(c.id)
        u = get_user(c.from_user.id) or {}
        sub = "—"
        if u.get("sub_until", 0) > time.time():
            sub = f"{u.get('sub_plan','')} ({(u['sub_until']-time.time())//86400:.0f}д)"
        txt = f"💠 **Баланс** ❄️\n\n🖼 Картинки: {u.get('balance_img',0)}₽\n💬 Текст: {u.get('balance_tts',0)}₽\n🎬 Видео: {u.get('balance_vid',0)}₽\n\n📝 Подписка: {sub}\n👥 Рефералов: {u.get('ref_count',0)}"
        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(types.InlineKeyboardButton("💳 Пополнить", callback_data="menu_topup"))
        kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="menu_more"))
        safe_photo(c.from_user.id, IMG_BAL, txt, reply_markup=kb, parse_mode="Markdown")

    @bot.callback_query_handler(func=lambda c: c.data == "menu_topup")
    def cb_top(c):
        bot.answer_callback_query(c.id)
        kb = types.InlineKeyboardMarkup(row_width=1)
        for code, p in BALANCE_PACKS.items():
            kb.add(types.InlineKeyboardButton(f"{p['title']} — {p['price']}₽", callback_data=f"buy_pack_{code}"))
        kb.add(types.InlineKeyboardButton("💎 Своя сумма", callback_data="custom_amount"))
        kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="menu_balance"))
        safe_photo(c.from_user.id, IMG_BAL, "💳 **Пополнение** ❄️\n\nВыбери пакет или введи свою сумму:", reply_markup=kb, parse_mode="Markdown")

    @bot.callback_query_handler(func=lambda c: c.data == "custom_amount")
    def cb_custom(c):
        bot.answer_callback_query(c.id)
        upd(c.from_user.id, state="custom_amount_wait")
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("⬅️ Отмена", callback_data="menu_topup"))
        safe_send(c.from_user.id, "💎 **Своя сумма** ❄️\n\nВведи сумму от **10₽ до 5000₽**.\n\nПример: `150`\n\n💡 Начислим ровно столько, сколько заплатил.", reply_markup=kb, parse_mode="Markdown")

    @bot.callback_query_handler(func=lambda c: c.data.startswith("buy_pack_"))
    def cb_buy_pack(c):
        code = c.data[9:]
        if code not in BALANCE_PACKS: return bot.answer_callback_query(c.id, "❌", show_alert=True)
        p = BALANCE_PACKS[code]
        bot.answer_callback_query(c.id)
        safe_photo(c.from_user.id, IMG_BAL, f"{p['title']} ❄️\n\n💰 {p['price']}₽\n🎁 +{p['amount']}₽\n\nОплата:", reply_markup=payment_choice_kb(code, p["price"]), parse_mode="Markdown")

    @bot.callback_query_handler(func=lambda c: c.data.startswith("payneed_"))
    def cb_payneed(c):
        parts = c.data.split("_")
        if len(parts) < 3: return bot.answer_callback_query(c.id, "❌")
        field, amount_s = parts[1], parts[2]
        try: amount = int(amount_s)
        except: return bot.answer_callback_query(c.id, "❌")
        if amount < 10: amount = 10
        payload = f"custom_{c.from_user.id}_{amount}"
        bot.answer_callback_query(c.id)
        safe_send(c.from_user.id, f"💎 **Пополнение на {amount}₽** ❄️\n\nВыбери способ:", reply_markup=payment_choice_kb(payload, amount), parse_mode="Markdown")

    @bot.callback_query_handler(func=lambda c: c.data == "menu_subs")
    def cb_subs(c):
        bot.answer_callback_query(c.id)
        kb = types.InlineKeyboardMarkup(row_width=1)
        for code, t in TEXT_SUB_TARIFFS.items():
            hint = SUB_HINTS.get(code, "")
            kb.add(types.InlineKeyboardButton(f"{t['title']} — {t['price']}₽ ({hint})", callback_data=f"buy_sub_{code}"))
        kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="menu_more"))
        safe_photo(c.from_user.id, IMG_SUB, "📝 **Подписки** ❄️", reply_markup=kb, parse_mode="Markdown")

    @bot.callback_query_handler(func=lambda c: c.data.startswith("buy_sub_"))
    def cb_buy_sub(c):
        code = c.data[8:]
        if code not in TEXT_SUB_TARIFFS: return bot.answer_callback_query(c.id, "❌", show_alert=True)
        t = TEXT_SUB_TARIFFS[code]
        bot.answer_callback_query(c.id)
        safe_send(c.from_user.id, f"{t['title']} ❄️\n\n💰 {t['price']}₽\n🎁 {t['tokens']:,} токенов\n⏳ {t['days']} дней\n\nОплата:", reply_markup=payment_choice_kb(f"sub_{code}", t["price"]), parse_mode="Markdown")

    # ---------- ОПЛАТА ----------
    @bot.callback_query_handler(func=lambda c: c.data.startswith("stars_"))
    def cb_pay_stars(c):
        payload = c.data[6:]
        rub = 0; title = "Оплата"
        if payload.startswith("custom_"):
            try: rub = int(payload.rsplit("_", 1)[1])
            except: rub = 0
            title = f"Пополнение {rub}₽"
        elif payload.startswith("sub_") and payload[4:] in TEXT_SUB_TARIFFS:
            t = TEXT_SUB_TARIFFS[payload[4:]]; rub = t["price"]; title = t["title"]
        elif payload in BALANCE_PACKS:
            p = BALANCE_PACKS[payload]; rub = p["price"]; title = p["title"]
        elif payload in API_SUB_PLANS:
            p = API_SUB_PLANS[payload]; rub = p["price"]; title = p["title"]
        else: return bot.answer_callback_query(c.id, "❌", show_alert=True)
        if rub < 1: return bot.answer_callback_query(c.id, "❌", show_alert=True)
        bot.answer_callback_query(c.id)
        if not send_stars_invoice(c.from_user.id, title, f"Оплата {rub}₽", payload, rub):
            safe_send(c.from_user.id, "❌ Stars недоступны. Попробуй 💳 СБП или 🟢 Grosh")

    @bot.callback_query_handler(func=lambda c: c.data.startswith("platega_"))
    def cb_pay_platega(c):
        payload = c.data[8:]
        rub = 0; desc = "Оплата"
        if payload.startswith("custom_"):
            try: rub = int(payload.rsplit("_", 1)[1])
            except: rub = 0
            desc = f"Пополнение {rub}₽"
        elif payload.startswith("sub_") and payload[4:] in TEXT_SUB_TARIFFS:
            t = TEXT_SUB_TARIFFS[payload[4:]]; rub = t["price"]; desc = t["title"]
        elif payload in BALANCE_PACKS:
            p = BALANCE_PACKS[payload]; rub = p["price"]; desc = p["title"]
        elif payload in API_SUB_PLANS:
            p = API_SUB_PLANS[payload]; rub = p["price"]; desc = p["title"]
        else: return bot.answer_callback_query(c.id, "❌", show_alert=True)
        if rub < 1: return bot.answer_callback_query(c.id, "❌", show_alert=True)
        bot.answer_callback_query(c.id, "💳 Создаю СБП...")
        url, pid = platega_create(c.from_user.id, rub, desc, payload)
        if not url: return safe_send(c.from_user.id, "❌ Platega не работает.")
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("💳 Оплатить СБП", url=url))
        kb.add(types.InlineKeyboardButton("🔄 Проверить", callback_data=f"checkpay_platega_{pid}"))
        safe_send(c.from_user.id, f"💳 {desc} ❄️\n💰 {rub}₽\n\nНажми «Оплатить СБП»", reply_markup=kb)

    @bot.callback_query_handler(func=lambda c: c.data.startswith("grosh_"))
    def cb_pay_grosh(c):
        payload = c.data[6:]
        if not grosh_enabled(): return bot.answer_callback_query(c.id, "🟢 Grosh не настроен", show_alert=True)
        rub = 0; desc = "Оплата"
        if payload.startswith("custom_"):
            try: rub = int(payload.rsplit("_", 1)[1])
            except: rub = 0
            desc = f"Пополнение {rub}₽"
        elif payload.startswith("sub_") and payload[4:] in TEXT_SUB_TARIFFS:
            t = TEXT_SUB_TARIFFS[payload[4:]]; rub = t["price"]; desc = t["title"]
        elif payload in BALANCE_PACKS:
            p = BALANCE_PACKS[payload]; rub = p["price"]; desc = p["title"]
        elif payload in API_SUB_PLANS:
            p = API_SUB_PLANS[payload]; rub = p["price"]; desc = p["title"]
        else: return bot.answer_callback_query(c.id, "❌", show_alert=True)
        if rub < 1: return bot.answer_callback_query(c.id, "❌", show_alert=True)
        bot.answer_callback_query(c.id, "🟢 Создаю...")
        url, pid = grosh_create(c.from_user.id, rub, desc, payload)
        if not url: return safe_send(c.from_user.id, "❌ Grosh не отвечает.")
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🟢 Оплатить", url=url))
        kb.add(types.InlineKeyboardButton("🔄 Проверить", callback_data=f"checkpay_grosh_{pid}"))
        safe_send(c.from_user.id, f"🟢 {desc} ❄️\n💰 {rub}₽\n\nНажми «Оплатить»", reply_markup=kb)

    @bot.callback_query_handler(func=lambda c: c.data.startswith("checkpay_"))
    def cb_check(c):
        parts = c.data.split("_", 2)
        if len(parts) < 3: return bot.answer_callback_query(c.id, "⏳")
        prov, pid_str = parts[1], parts[2]
        try: pid = int(pid_str)
        except: return bot.answer_callback_query(c.id, "⏳")
        st = platega_check(pid) if prov == "platega" else grosh_check(pid)
        msg = {"paid":"✅ Оплачено!","failed":"❌ Не прошёл","pending":"⏳ Не оплачено"}.get(st,"⏳")
        bot.answer_callback_query(c.id, msg, show_alert=True)

    # ---------- КАРТИНКИ / ВИДЕО ----------
    @bot.callback_query_handler(func=lambda c: c.data == "menu_images")
    def cb_imgs(c):
        bot.answer_callback_query(c.id)
        kb = types.InlineKeyboardMarkup(row_width=1)
        for mid, m in MODELS.items():
            if m["type"] == "image": kb.add(types.InlineKeyboardButton(f"{m['name']} — {m['price']}₽", callback_data=f"imgsel_{mid}"))
        kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="menu_main"))
        safe_photo(c.from_user.id, IMG_IMAGE, "🖼 **Картинки** ❄️\n\nВыбери модель:", reply_markup=kb, parse_mode="Markdown")

    @bot.callback_query_handler(func=lambda c: c.data.startswith("imgsel_"))
    def cb_isel(c):
        mid = c.data[7:]
        if mid not in MODELS: return
        bot.answer_callback_query(c.id); u = get_user(c.from_user.id) or {}
        upd(c.from_user.id, state="img_wait", temp_model_id=mid)
        safe_photo(c.from_user.id, IMG_IMAGE, f"{MODELS[mid]['name']} ❄️\n\n💰 {MODELS[mid]['price']}₽\n{MODEL_HINTS.get(mid,'')}\n🎟 Баланс: {u.get('balance_img',0)}₽\n\n✍️ Промпт:", reply_markup=input_kb(), parse_mode="Markdown")

    @bot.callback_query_handler(func=lambda c: c.data == "menu_video")
    def cb_vid(c):
        bot.answer_callback_query(c.id)
        kb = types.InlineKeyboardMarkup(row_width=1)
        for mid, m in VIDEO_MODELS.items():
            kb.add(types.InlineKeyboardButton(f"{m['name']} — {m['price']}₽/сек", callback_data=f"vidsel_{mid}"))
        kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="menu_main"))
        u = get_user(c.from_user.id) or {}
        safe_photo(c.from_user.id, IMG_VIDEO, f"🎬 **Видео** ❄️\n\n🎟 Баланс: {u.get('balance_vid',0)}₽", reply_markup=kb, parse_mode="Markdown")

    @bot.callback_query_handler(func=lambda c: c.data.startswith("vidsel_"))
    def cb_vsel(c):
        mid = c.data[7:]
        if mid not in VIDEO_MODELS: return
        bot.answer_callback_query(c.id)
        show_video_settings(c.from_user.id, mid)

    @bot.callback_query_handler(func=lambda c: c.data.startswith("vset_"))
    def cb_vset(c):
        bot.answer_callback_query(c.id)
        parts = c.data.split("_")
        if len(parts) < 6: return
        mid, typ, dur, res, asp = parts[1], parts[2], int(parts[3]), parts[4], parts[5]
        show_video_settings(c.from_user.id, mid)

    @bot.callback_query_handler(func=lambda c: c.data == "vid_confirm")
    def cb_vid_confirm(c):
        u = get_user(c.from_user.id) or {}
        state = u.get("state", "")
        if not state.startswith("vid_setup_"):
            return bot.answer_callback_query(c.id, "❌ Ошибка настроек", show_alert=True)
        bot.answer_callback_query(c.id)
        parts = state.split("_")
        new_state = f"vid_wait_{parts[2]}_{parts[3]}_{parts[4]}_{parts[5]}"
        upd(c.from_user.id, state=new_state)
        safe_send(c.from_user.id, f"✍️ Напиши промпт для видео:\n(Время: {parts[3]}с, Качество: {parts[4]}, Формат: {parts[5]})")

    # ---------- ЗАДАНИЯ / РЕФЕРАЛЫ / ИСТОРИЯ / API ----------
    @bot.callback_query_handler(func=lambda c: c.data == "menu_tasks")
    def cb_tasks(c):
        bot.answer_callback_query(c.id)
        new = check_tasks(c.from_user.id)
        if new:
            txt = "🏆 **Выполнено!** ❄️\n\n"
            for tid in new: txt += f"✅ {TASKS[tid]['title']} → +{TASKS[tid]['amount']}₽\n"
            safe_send(c.from_user.id, txt, parse_mode="Markdown")
        u = get_user(c.from_user.id) or {}
        done = set(filter(None, (u.get("tasks_done") or "").split(",")))
        txt = "🏆 **Задания** ❄️\n\n"
        for tid, t in TASKS.items(): txt += f"{'✅' if tid in done else '⬜'} {t['title']} → +{t['amount']}₽\n"
        kb = types.InlineKeyboardMarkup(); kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="menu_more"))
        safe_send(c.from_user.id, txt[:4000], parse_mode="Markdown", reply_markup=kb)

    @bot.callback_query_handler(func=lambda c: c.data == "menu_refs")
    def cb_refs(c):
        bot.answer_callback_query(c.id); u = get_user(c.from_user.id) or {}
        link = f"https://t.me/{BOT_USERNAME}?start=ref_{c.from_user.id}"
        txt = f"👥 **Рефералы** ❄️\n\n🔗 <code>{link}</code>\n\n🎁 Тебе: +{REF_BONUS_REFERRER}₽\n🎁 Другу: +{REF_BONUS_REFERRED}₽\n\n👥 Приглашено: {u.get('ref_count',0)}"
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("📤 Поделиться", url=f"https://t.me/share/url?url={link}&text=Попробуй! ❄️"))
        kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="menu_more"))
        safe_send(c.from_user.id, txt, reply_markup=kb, parse_mode="HTML")

    @bot.callback_query_handler(func=lambda c: c.data == "menu_history")
    def cb_hist(c):
        bot.answer_callback_query(c.id)
        with DbConn() as db_c:
            cur = db_c.cursor(); cur.execute("SELECT m_type, model_id, prompt, ts FROM works WHERE user_id=? ORDER BY id DESC LIMIT 10", (c.from_user.id,))
            rows = cur.fetchall()
        kb = types.InlineKeyboardMarkup(); kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="menu_more"))
        if not rows: return safe_send(c.from_user.id, "📜 История пуста ❄️", reply_markup=kb)
        txt = "📜 **История** ❄️\n\n"
        for mt, mid, pr, ts in rows: txt += f"• {datetime.fromtimestamp(ts).strftime('%d.%m %H:%M')} · {mt} · {mid}\n  {pr[:40]}\n\n"
        safe_send(c.from_user.id, txt[:4000], parse_mode="Markdown", reply_markup=kb)

    @bot.callback_query_handler(func=lambda c: c.data == "menu_api")
    def cb_api(c):
        bot.answer_callback_query(c.id)
        with DbConn() as db_c:
            cur = db_c.cursor(); cur.execute("SELECT plan, expires_at, requests_used, tokens_used FROM api_subs WHERE user_id=? AND expires_at>?", (c.from_user.id, time.time()))
            sub = cur.fetchone()
        if sub:
            plan, exp, req, tok = sub; p = API_SUB_PLANS.get(plan, {})
            txt = f"🔑 **API активен** ❄️\n\n{p.get('title','')}\n⏳ {(exp-time.time())//86400:.0f} дн.\n📊 {req}/{p.get('requests','?')} запросов\n\n🔑 Ключ: /gen_api"
            kb = types.InlineKeyboardMarkup(); kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="menu_more"))
            return safe_send(c.from_user.id, txt, reply_markup=kb, parse_mode="Markdown")
        kb = types.InlineKeyboardMarkup(row_width=1)
        for code, p in API_SUB_PLANS.items(): kb.add(types.InlineKeyboardButton(f"{p['title']} — {p['price']}₽", callback_data=f"buy_api_{code}"))
        kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="menu_more"))
        safe_send(c.from_user.id, "🔑 **API** ❄️\n\nВыбери тариф:", reply_markup=kb, parse_mode="Markdown")

    @bot.callback_query_handler(func=lambda c: c.data.startswith("buy_api_"))
    def cb_buy_api(c):
        code = c.data[8:]
        if code not in API_SUB_PLANS: return
        p = API_SUB_PLANS[code]; bot.answer_callback_query(c.id)
        safe_send(c.from_user.id, f"{p['title']} ❄️\n\n💰 {p['price']}₽\n⏳ {p['days']} дней\n📊 {p['requests']} запросов\n\nОплата:", reply_markup=payment_choice_kb(code, p["price"]), parse_mode="Markdown")

    @bot.message_handler(commands=["gen_api"])
    def gen_api(m):
        uid = m.from_user.id
        if uid == ADMIN_ID:
            with DbConn() as c:
                c.cursor().execute("INSERT OR REPLACE INTO api_subs(user_id, plan, expires_at, requests_used, tokens_used) VALUES(?,?,?,0,0)", (uid, "api_week_pro", time.time() + 3650*86400))
        with DbConn() as db_c:
            cur = db_c.cursor(); cur.execute("SELECT plan FROM api_subs WHERE user_id=? AND expires_at>?", (uid, time.time()))
            sub = cur.fetchone()
        if not sub: return safe_send(uid, "❌ Нет активной подписки. Купи в «🔑 API».")
        raw = generate_api_key(uid)
        safe_send(uid, f"🔑 **Ключ** ❄️\n\n<code>{raw}</code>\n\n⚠️ Сохрани!", parse_mode="HTML")

    # ---------- АДМИН ----------
    @bot.callback_query_handler(func=lambda c: c.data == "admin_root")
    def cb_admin(c):
        if c.from_user.id != ADMIN_ID: return bot.answer_callback_query(c.id, "⛔", show_alert=True)
        bot.answer_callback_query(c.id)
        with DbConn() as db_c:
            cur = db_c.cursor(); cur.execute("SELECT COUNT(*) FROM users"); total = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*), COALESCE(SUM(amount),0) FROM payments WHERE status='paid'"); row = cur.fetchone()
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(types.InlineKeyboardButton("👥 Юзеры", callback_data="admin_users"), types.InlineKeyboardButton("💳 Платежи", callback_data="admin_payments"))
        kb.add(types.InlineKeyboardButton("📊 Стата", callback_data="admin_stats"), types.InlineKeyboardButton("🎁 Выдать", callback_data="admin_give_menu"))
        kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="menu_more"))
        safe_send(c.from_user.id, f"🛡 **Админ** ❄️\n\n👥 Юзеров: {total}\n💳 Платежей: {row[0]} на {row[1]}₽", reply_markup=kb, parse_mode="Markdown")

    @bot.callback_query_handler(func=lambda c: c.data == "admin_users")
    def cb_au(c):
        if c.from_user.id != ADMIN_ID: return
        with DbConn() as db_c:
            cur = db_c.cursor(); cur.execute("SELECT user_id,username,balance_img,balance_vid,last_seen FROM users ORDER BY last_seen DESC LIMIT 20")
            rows = cur.fetchall()
        txt = "👥 **Юзеры** ❄️\n\n"
        for uid, un, bi, bv, ls in rows:
            last = datetime.fromtimestamp(ls).strftime("%d.%m %H:%M") if ls else "—"
            txt += f"• <code>{uid}</code> @{un or '—'} 🖼{bi}₽ 🎬{bv}₽ ({last})\n"
        bot.answer_callback_query(c.id); safe_send(c.from_user.id, txt[:4000], parse_mode="HTML")

    @bot.callback_query_handler(func=lambda c: c.data == "admin_payments")
    def cb_ap(c):
        if c.from_user.id != ADMIN_ID: return
        with DbConn() as db_c:
            cur = db_c.cursor(); cur.execute("SELECT user_id,package_id,amount,status,provider,ts FROM payments ORDER BY id DESC LIMIT 20")
            rows = cur.fetchall()
        txt = "💳 **Платежи** ❄️\n\n"
        for uid, pkg, amt, st, prov, ts in rows:
            t = datetime.fromtimestamp(ts).strftime("%d.%m %H:%M")
            em = "✅" if st == "paid" else ("⏳" if st == "pending" else "❌")
            txt += f"{em} {t} · {uid} · {pkg} · {amt} · {prov}\n"
        bot.answer_callback_query(c.id); safe_send(c.from_user.id, txt[:4000], parse_mode="HTML")

    @bot.callback_query_handler(func=lambda c: c.data == "admin_stats")
    def cb_as(c):
        if c.from_user.id != ADMIN_ID: return
        with DbConn() as db_c:
            cur = db_c.cursor()
            cur.execute("SELECT COALESCE(SUM(amount),0) FROM payments WHERE status='paid' AND ts > ?", (time.time()-86400,)); p = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM users WHERE created_at > ?", (time.time()-86400,)); new = cur.fetchone()[0]
        bot.answer_callback_query(c.id)
        safe_send(c.from_user.id, f"📊 **24ч** ❄️\n\n💵 Оплачено: {p}₽\n👥 Новых: +{new}", parse_mode="Markdown")

    @bot.callback_query_handler(func=lambda c: c.data == "admin_give_menu")
    def cb_agm(c):
        if c.from_user.id != ADMIN_ID: return
        bot.answer_callback_query(c.id)
        safe_send(c.from_user.id, "🎁 **Выдача** ❄️\n\nФормат: `ID поле количество`\nПоля: `img/vid`\n\nПример: `123456 img 50`", parse_mode="Markdown")
        upd(c.from_user.id, state="admin_give_wait")

    # ---------- ТЕКСТ ----------
    @bot.message_handler(content_types=["text"])
    def handle_text(m):
        uid = m.from_user.id
        if not m.text: return
        u = get_user(uid) or {}
        if u.get("is_banned"): return safe_send(uid, "⛔ Забанен.")
        text = m.text.strip(); state = u.get("state", "")

        if text == "/start": upd(uid, state=""); return start(m)
        if text == "/rate":
            rate = FxAnalyzer.current()
            return safe_send(uid, f"💱 **Курс** ❄️\n\nЦБ РФ: {rate:.2f}₽\nС наценкой: {rate * (1 + FX_MARKUP_PCT/100):.2f}₽", parse_mode="Markdown")

        if state == "admin_give_wait" and uid == ADMIN_ID:
            try:
                target, field, amount = text.split(); target, amount = int(target), int(amount)
                fm = {"img":"balance_img","vid":"balance_vid"}
                if field not in fm: raise ValueError
                add_balance(target, fm[field], amount); upd(uid, state="")
                return safe_send(uid, f"✅ Выдано {amount}₽ ({field}) → {target}")
            except: return safe_send(uid, "❌ Формат: `123456 img 50`", parse_mode="Markdown")

        if state == "custom_amount_wait":
            try: amount = int(text.strip())
            except ValueError: return safe_send(uid, "❌ Введи число. Пример: `150`", parse_mode="Markdown")
            if amount < 10: return safe_send(uid, "❌ Минимум 10₽.")
            if amount > 5000: return safe_send(uid, "❌ Максимум 5000₽.")
            upd(uid, state="")
            payload = f"custom_{uid}_{amount}"
            return safe_send(uid, f"💎 **Пополнение на {amount}₽** ❄️\n\nВыбери способ:", reply_markup=payment_choice_kb(payload, amount), parse_mode="Markdown")

        if state.startswith("txt_"):
            parts = state.split("_")
            mid = parts[1]
            thinking_level = parts[2] if len(parts) > 2 else None
            
            if mid not in MODELS: upd(uid, state=""); return safe_send(uid, "❌ Модель потеряна.")
            price = MODELS[mid]["price"]
            free_left = max(0, FREE_TEXT_LIMIT - (u.get("text_free_used") or 0))
            used_free = False
            if price > 0 and free_left > 0:
                upd(uid, text_free_used=(u.get("text_free_used") or 0) + 1); used_free = True
            elif price > 0 and not charge(uid, "balance_tts", price):
                upd(uid, state="")
                return show_insufficient(uid, price, "balance_tts")
            upd(uid, state="")
            
            lvl_text = f" ({thinking_level})" if thinking_level else ""
            status = safe_send(uid, f"❄️ {MODELS[mid]['name']}{lvl_text} думает..." + (" (бесплатно)" if used_free else ""))
            
            ans = gen_text(uid, mid, text, thinking_level=thinking_level)
            
            try: bot.delete_message(uid, status.message_id)
            except: pass
            if ans: safe_send(uid, ans[:4000])
            with DbConn() as c:
                c.cursor().execute("INSERT INTO works(user_id,m_type,model_id,prompt,file_id,ts) VALUES(?,?,?,?,?,?)", (uid,"text",mid,text[:500],"",time.time()))
            check_tasks(uid)
            return

        if state == "agent_wait_prompt":
            upd(uid, state="")
            if not charge(uid, "balance_img", AGENT_PRICE_IMG): return show_insufficient(uid, AGENT_PRICE_IMG, "balance_img")
            status = safe_send(uid, "🤖 Три модели думают... ❄️")
            f1 = AGENT_EXECUTOR.submit(gen_text, uid, "gpt-6-astra", text, False, 1024)
            f2 = AGENT_EXECUTOR.submit(gen_text, uid, "claude-fable-5.2", text, False, 1024)
            f3 = AGENT_EXECUTOR.submit(gen_text, uid, "deepseek-v4.1-flash", text, False, 1024)
            try:
                r1, r2, r3 = f1.result(), f2.result(), f3.result()
            except Exception as e:
                log.error(f"Agents error: {e}"); r1, r2, r3 = "Ошибка", "Ошибка", "Ошибка"
            try: bot.delete_message(uid, status.message_id)
            except: pass
            safe_send(uid, f"💬 **GPT-6:**\n{r1[:1000]}")
            safe_send(uid, f"🔥 **Fable:**\n{r2[:1000]}")
            safe_send(uid, f"🔬 **DeepSeek:**\n{r3[:1000]}")
            safe_send(uid, "👆 Выбери лучший ответ. Это 3 мнения.", parse_mode="Markdown")
            return

        if state == "img_wait":
            mid = u.get("temp_model_id")
            if not mid or mid not in MODELS: upd(uid, state=""); return safe_send(uid, "❌ Модель потеряна.")
            cost = MODELS[mid]["price"]
            if not charge(uid, "balance_img", cost):
                upd(uid, state="")
                return show_insufficient(uid, cost, "balance_img")
            upd(uid, state="")
            status = safe_send(uid, f"🎨 Рисую... ({cost}₽) ❄️")
            url, real_cost = gen_image(uid, mid, text)
            try: bot.delete_message(uid, status.message_id)
            except: pass
            if real_cost != cost:
                diff = real_cost - cost
                if diff > 0: charge(uid, "balance_img", diff)
                elif diff < 0: add_balance(uid, "balance_img", -diff)
            if url:
                with DbConn() as c:
                    c.cursor().execute("INSERT INTO works(user_id,m_type,model_id,prompt,file_id,ts) VALUES(?,?,?,?,?,?)", (uid,"image",mid,text[:500],url,time.time()))
                send_image_bytes(uid, url, f"✅ {MODELS[mid]['name']} ❄️")
                check_tasks(uid)
            else:
                if REFUND_ON_ERROR:
                    add_balance(uid, "balance_img", cost)
                    safe_send(uid, f"❌ Ошибка генерации.\n💰 Баланс **{cost}₽ возвращён**.", parse_mode="Markdown")
                else: safe_send(uid, "❌ Ошибка. Попробуй ещё раз.")
            return

        if state.startswith("vid_wait_"):
            parts = state.split("_")
            if len(parts) < 6: upd(uid, state=""); return safe_send(uid, "❌ Ошибка параметров.")
            mid = parts[2]; dur = int(parts[3]); res = parts[4]; asp = parts[5]
            if mid not in VIDEO_MODELS: upd(uid, state=""); return safe_send(uid, "❌ Модель потеряна.")
            
            cost = calc_video_price(mid, dur, res, asp)
            if not charge(uid, "balance_vid", cost):
                upd(uid, state="")
                return show_insufficient(uid, cost, "balance_vid")
                
            upd(uid, state="")
            status = safe_send(uid, f"🎬 Рендерю видео ({dur}с, {res})... ({cost}₽) ❄️")
            url, _ = gen_video(uid, mid, text, duration=dur, resolution=res, aspect=asp)
            
            try: bot.delete_message(uid, status.message_id)
            except: pass
            if url:
                with DbConn() as c:
                    c.cursor().execute("INSERT INTO works(user_id,m_type,model_id,prompt,file_id,ts) VALUES(?,?,?,?,?,?)", (uid,"video",mid,text[:500],url,time.time()))
                send_video_bytes(uid, url, f"✅ {VIDEO_MODELS[mid]['name']} ({dur}с, {res}) ❄️")
                check_tasks(uid)
            else:
                if REFUND_ON_ERROR:
                    add_balance(uid, "balance_vid", cost)
                    safe_send(uid, f"❌ Ошибка генерации.\n💰 Баланс **{cost}₽ возвращён**.", parse_mode="Markdown")
                else: safe_send(uid, "❌ Ошибка. Попробуй ещё раз.")
            return

        # ОБЫЧНЫЙ ЧАТ
        free_left = max(0, FREE_TEXT_LIMIT - (u.get("text_free_used") or 0))
        used_free = False
        if free_left > 0:
            upd(uid, text_free_used=(u.get("text_free_used") or 0) + 1); used_free = True
        elif not charge(uid, "balance_tts", 3):
            return show_insufficient(uid, 3, "balance_tts")
        status = safe_send(uid, "❄️ Думаю..." + (" (бесплатно)" if used_free else " (3₽)"))
        ans = gen_text(uid, "gpt-6-astra", text)
        try: bot.delete_message(uid, status.message_id)
        except: pass
        if ans: safe_send(uid, ans[:4000])

# ==========================================================
# 🚀 MAIN
# ==========================================================
def safe_polling():
    backoff = 2.0
    while not SHUTDOWN.is_set():
        try:
            log.info("Polling start...")
            bot.infinity_polling(timeout=20, long_polling_timeout=30, skip_pending=True)
        except (requests.exceptions.ConnectionError, requests.exceptions.RequestException, ConnectionResetError, OSError) as e:
            log.warning(f"Polling network error: {e}. Restart in {backoff:.1f}s...")
        except Exception as e:
            log.error(f"Polling crashed: {e}. Restart in {backoff:.1f}s...")
        if SHUTDOWN.is_set(): break
        try: bot.stop_polling()
        except Exception: pass
        time.sleep(backoff)
        backoff = min(backoff * 1.5, 30.0)

def main():
    global bot
    if not TOKEN or not CLODEX_API_KEY: raise SystemExit("BOT_TOKEN / CLODEX_API_KEY не заданы")
    os.makedirs(DATA_DIR, exist_ok=True)
    Db.init(os.path.join(DATA_DIR, "media_bot.db"), DB_POOL_SIZE)
    init_db()
    bot = telebot.TeleBot(TOKEN, threaded=False)
    register_handlers()
    signal.signal(signal.SIGTERM, lambda s,f: SHUTDOWN.set())
    signal.signal(signal.SIGINT, lambda s,f: SHUTDOWN.set())
    start_health(HEALTH_PORT)
    threading.Thread(target=payment_poller, daemon=True).start()
    threading.Thread(target=safe_polling, daemon=True).start()
    log.info("❄️ Neuro Studio v103 started ❄️")
    while not SHUTDOWN.is_set(): time.sleep(1)

if __name__ == "__main__":
    main()
