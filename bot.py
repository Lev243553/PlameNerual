# -*- coding: utf-8 -*-
"""
Нейро-Студия v70 — Winter Edition ❄️ FINAL
+ Рефералы + Задания + Ежедневки
+ Агенты платные (AGENT_PRICE_IMG=10), кроме ADMIN_ID
Платежи: Platega v2 + Telegram Stars (1⭐=1.3₽) + Grosh (опционально)
"""
import os, time, uuid, sqlite3, logging, threading, signal, json, queue, http.server, io, hashlib
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv
import telebot
from telebot import types
import requests

load_dotenv(override=False)
log = logging.getLogger("neuro")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

# ==========================================================
# КАРТИНКИ
# ==========================================================
IMG_MAIN  = "https://i.postimg.cc/0QN2QW2X/IMG-20261110-204842-470.jpg"
IMG_IMAGE = "https://i.postimg.cc/Bn1hW45b/IMG-20261110-205555-782.jpg"
IMG_VIDEO = "https://i.postimg.cc/ZKn7crC0/IMG-20261110-205715-247.jpg"
IMG_TEXT  = "https://i.postimg.cc/xjtpMsj5/IMG-20261110-205814-215.jpg"
IMG_BAL   = "https://i.postimg.cc/BbYh3v7z/IMG-20261110-205911-386.jpg"
IMG_SUB   = "https://i.postimg.cc/0QCWtnY8/IMG-20261110-210033-656.jpg"

# ==========================================================
# ENV
# ==========================================================
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

TOKEN = os.getenv("BOT_TOKEN")
POLZA_KEY = os.getenv("POLZA_API_KEY")
POLZA_BASE = os.getenv("POLZA_API_URL", "https://polza.ai/api/v1")
DATA_DIR = os.getenv("DATA_DIR", "./data")
SUPPORT_URL = os.getenv("SUPPORT_URL", "https://t.me/your_support")
PRIVACY_URL = os.getenv("PRIVACY_URL", "")
TERMS_URL = os.getenv("TERMS_URL", "")
CONSENT_VERSION = os.getenv("CONSENT_VERSION", "v1.0")
BOT_USERNAME = os.getenv("BOT_USERNAME", "")
PLATEGA_ID = os.getenv("PLATEGA_MERCHANT_ID", "")
PLATEGA_SECRET = os.getenv("PLATEGA_SECRET_KEY", "")
PLATEGA_URL = os.getenv("PLATEGA_API_URL", "https://app.platega.io")
RETURN_URL = os.getenv("RETURN_URL", "")
STARS_RUB_PER_STAR = _env_float("STARS_RUB_PER_STAR", 1.3)
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY", "")
RANVIK_API_KEY = os.getenv("RANVIK_API_KEY", "")
RANVIK_API_URL = os.getenv("RANVIK_API_URL", "https://api.ranvik.ru/v1")
CLODEX_API_KEY = os.getenv("CLODEX_API_KEY", "")
CLODEX_API_URL = os.getenv("CLODEX_API_URL", "https://api.clodex.xyz/v1")
FX_API_URL = os.getenv("FX_API_URL", "https://www.cbr-xml-daily.ru/daily_json.js")
FX_FALLBACK_RATE = _env_float("FX_FALLBACK_RATE", 92.0)
FX_MARKUP_PCT = _env_float("FX_MARKUP_PCT", 3.0)

FREE_TEXT_LIMIT = 2
MAX_HISTORY = 10
HEALTH_PORT = _env_int("HEALTH_PORT", 3000, 0)
DB_POOL_SIZE = 16
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
API_RATE_PER_DAY = _env_int("API_RATE_PER_DAY", 200, 1)

# Рефералы / Ежедневки / Задания
REF_BONUS_REFERRER = 20
REF_BONUS_REFERRED = 5
DAILY_BONUS_IMG = 3
DAILY_BONUS_TTS = 1
AGENT_PRICE_IMG = 10  # стоимость 1 запуска агентов (в картинках)

TASKS = {
    "gen_first":  {"title":"🎨 Сгенери первую картинку", "field":"balance_img", "amount":2, "check":"works_img>=1"},
    "gen_5":      {"title":"🖼 Сгенери 5 картинок", "field":"balance_img", "amount":5, "check":"works_img>=5"},
    "text_first": {"title":"💬 Задай вопрос ИИ", "field":"balance_tts", "amount":1, "check":"works_text>=1"},
    "ref_1":      {"title":"👥 Пригласи 1 друга", "field":"balance_img", "amount":5, "check":"refs>=1"},
    "ref_3":      {"title":"👥 Пригласи 3 друзей", "field":"balance_vid", "amount":1, "check":"refs>=3"},
    "ref_10":     {"title":"👥 Пригласи 10 друзей", "field":"balance_vid", "amount":3, "check":"refs>=10"},
}

bot = None
SHUTDOWN = threading.Event()
HTTP_TIMEOUT_MED = (5, 90)
HTTP_TIMEOUT_LONG = (5, 90)
AGENT_EXECUTOR = ThreadPoolExecutor(max_workers=8)

def rub_to_stars(rub: int) -> int:
    return max(1, int(round(rub / STARS_RUB_PER_STAR)))

def is_admin(uid):
    return uid == ADMIN_ID

def charge(uid, field, amount=1):
    """Списывает с баланса. Для ADMIN_ID — бесплатно."""
    if is_admin(uid): return True
    return sub_balance(uid, field, amount)

class FxAnalyzer:
    _rate = 0.0; _ts = 0.0
    @classmethod
    def current(cls) -> float:
        if cls._rate > 0 and (time.time() - cls._ts) < 1800: return cls._rate
        try:
            r = requests.get(FX_API_URL, timeout=5)
            v = r.json()["Valute"]["USD"]["Value"]; cls._rate = v; cls._ts = time.time(); return v
        except Exception: return FX_FALLBACK_RATE
    @classmethod
    def rub_to_usd(cls, rub: int) -> float:
        return round((float(rub) / cls.current()) * (1 + FX_MARKUP_PCT / 100), 2)

MODELS = {
    "openai/gpt-image-1.5": {"name":"GPT Image 1.5", "type":"image", "price":7, "provider":"polza"},
    "google/gemini-2.5-flash-image": {"name":"Gemini 2.5 Flash", "type":"image", "price":6, "provider":"polza"},
    "black-forest-labs/flux.2-flex": {"name":"Flux 2 Flex", "type":"image", "price":22, "provider":"polza"},
    "bytedance/seedream-4": {"name":"Seedream 4", "type":"image", "price":7, "provider":"polza"},
    "qwen/image": {"name":"Qwen Image", "type":"image", "price":5, "provider":"polza"},
    "flux-dev": {"name":"Flux Dev (CX)", "type":"image", "price":5, "provider":"clodex"},
    "flux-schnell": {"name":"Flux Schnell (CX)", "type":"image", "price":5, "provider":"clodex"},
    "gpt-6-astra": {"name":"GPT-6 Astra (CX)", "type":"text", "price":3, "provider":"clodex"},
    "claude-opus-5": {"name":"Claude Opus 5 (CX)", "type":"text", "price":3, "provider":"clodex"},
    "kimi-k3.1-pro": {"name":"Kimi K3.1 Pro (CX)", "type":"text", "price":3, "provider":"clodex"},
    "claude-fable-5.2": {"name":"Claude Fable 5.2 (CX) 🔥", "type":"text", "price":5, "provider":"clodex"},
    "deepseek/deepseek-v4.1-flash": {"name":"DarkGPT (DeepSeek)", "type":"dark_gpt", "price":0, "provider":"ranvik"},
    "nvidia/nemotron-3-ultra-550b-a55b:free": {"name":"Nemotron 3 Ultra", "type":"text", "price":0, "provider":"openrouter"},
}

VIDEO_MODELS = {
    "kling/v2.5": {"name":"Kling 2.5 ❄️", "price":80},
    "minimax/hailuo-2": {"name":"Hailuo 2 ❄️", "price":60},
    "google/veo-3": {"name":"Veo 3 ❄️", "price":120},
}

TEXT_SUB_TARIFFS = {
    "text_start": {"title":"Текст Старт", "price": 249, "tokens": 1_000_000, "days":30},
    "text_pro":   {"title":"Текст Про",   "price": 690, "tokens": 3_000_000, "days":30},
    "text_max":   {"title":"Текст Макс",  "price": 1290, "tokens": 7_000_000, "days":30},
    "dark_gpt":   {"title":"DarkGPT Pro", "price": 199, "tokens": 3_000_000, "days":30},
}

BALANCE_PACKS = {
    "img_10":  {"title":"🖼 10 картинок", "price": 49, "field":"balance_img", "amount":10},
    "img_30":  {"title":"🖼 30 картинок", "price": 129, "field":"balance_img", "amount":30},
    "img_100": {"title":"🖼 100 картинок", "price": 349, "field":"balance_img", "amount":100},
    "vid_3":   {"title":"🎬 3 видео", "price": 199, "field":"balance_vid", "amount":3},
    "vid_10":  {"title":"🎬 10 видео", "price": 549, "field":"balance_vid", "amount":10},
    "tts_20":  {"title":"🔊 20 озвучек", "price": 99, "field":"balance_tts", "amount":20},
    "stt_20":  {"title":"🎙 20 расшифровок", "price": 99, "field":"balance_stt", "amount":20},
    "up_20":   {"title":"⬆️ 20 апскейлов", "price": 99, "field":"balance_up", "amount":20},
    "edit_20": {"title":"✏️ 20 редакций", "price": 129, "field":"balance_edit", "amount":20},
    "anim_10": {"title":"🎞 10 анимаций", "price": 149, "field":"balance_anim", "amount":10},
}

API_SUB_PLANS = {
    "api_week": {"title": "🔑 API Неделя", "price": 149, "days": 7, "requests": 500, "tokens": 1_000_000},
    "api_week_pro": {"title": "🔑 API Неделя PRO", "price": 299, "days": 7, "requests": 1500, "tokens": 3_000_000},
}

ALLOWED_COLS = {
    "username","is_banned","balance_img","balance_aud","balance_vid","balance_tts","balance_stt",
    "balance_edit","balance_anim","balance_up","text_free_used","sub_plan","sub_until","sub_used",
    "sub_tokens_used","state","temp_model_id","temp_price","admin_state","admin_target","admin_ts",
    "free_image","onboarded","last_seen","created_at","consent_at","consent_version","api_day","api_calls",
    "referred_by","ref_count","daily_last","daily_streak","tasks_done"
}

# ==========================================================
# DB
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
            try:
                cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
                log.info(f"✅ {table}.{col}")
            except Exception as e: log.warning(f"⚠️ {table}.{col}: {e}")

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
            tasks_done TEXT DEFAULT '')''')
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
            ("consent_at","REAL DEFAULT 0"),("consent_version","TEXT DEFAULT ''"),
            ("api_day","TEXT DEFAULT ''"),("api_calls","INTEGER DEFAULT 0"),
            ("balance_up","INTEGER DEFAULT 0"),("balance_edit","INTEGER DEFAULT 0"),
            ("balance_anim","INTEGER DEFAULT 0"),("balance_aud","INTEGER DEFAULT 0"),
            ("is_banned","INTEGER DEFAULT 0"),("onboarded","INTEGER DEFAULT 0"),
            ("free_image","INTEGER DEFAULT 0"),("last_seen","REAL DEFAULT 0"),
            ("created_at","REAL DEFAULT 0"),("state","TEXT DEFAULT ''"),
            ("temp_model_id","TEXT DEFAULT ''"),("temp_price","INTEGER DEFAULT 0"),
            ("text_free_used","INTEGER DEFAULT 0"),("sub_plan","TEXT DEFAULT ''"),
            ("sub_until","REAL DEFAULT 0"),("sub_used","INTEGER DEFAULT 0"),
            ("sub_tokens_used","INTEGER DEFAULT 0"),
            ("referred_by","INTEGER DEFAULT 0"),("ref_count","INTEGER DEFAULT 0"),
            ("daily_last","TEXT DEFAULT ''"),("daily_streak","INTEGER DEFAULT 0"),
            ("tasks_done","TEXT DEFAULT ''"),
        ])

# ==========================================================
# ХЕЛПЕРЫ
# ==========================================================
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
    if field not in ALLOWED_COLS: raise ValueError(f"bad field {field}")
    with DbConn() as c:
        c.cursor().execute(f"UPDATE users SET {field} = {field} + ? WHERE user_id=?", (amount, uid))

def sub_balance(uid, field, amount=1):
    if field not in ALLOWED_COLS: return False
    with DbConn() as c:
        cur = c.cursor()
        cur.execute(f"SELECT {field} FROM users WHERE user_id=?", (uid,))
        r = cur.fetchone()
        if not r or r[0] < amount: return False
        cur.execute(f"UPDATE users SET {field} = {field} - ? WHERE user_id=?", (amount, uid))
        return True

def safe_send(uid, text, **kw):
    try: return bot.send_message(uid, text, **kw)
    except Exception: return None

def safe_photo(uid, photo, caption=None, **kw):
    try: return bot.send_photo(uid, photo, caption=caption, **kw)
    except Exception:
        if caption:
            try: return bot.send_message(uid, caption, **kw)
            except Exception: return None
        return None

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

# ==========================================================
# РЕФЕРАЛЫ + ЕЖЕДНЕВКИ + ЗАДАНИЯ
# ==========================================================
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
    safe_send(ref_by, f"🎉 Новый реферал! +{REF_BONUS_REFERRER} 🖼")
    log_ev(ref_by, "referral", f"new {new_uid}")

def claim_daily(uid):
    today = time.strftime("%Y-%m-%d")
    u = get_user(uid) or {}
    if u.get("daily_last") == today:
        return False, "🎁 Уже получил сегодня. Приходи завтра!"
    yesterday = time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400))
    streak = (u.get("daily_streak") or 0)
    streak = streak + 1 if u.get("daily_last") == yesterday else 1
    bonus_img = DAILY_BONUS_IMG + min(streak - 1, 7)
    bonus_tts = DAILY_BONUS_TTS if streak >= 3 else 0
    add_balance(uid, "balance_img", bonus_img)
    if bonus_tts: add_balance(uid, "balance_tts", bonus_tts)
    upd(uid, daily_last=today, daily_streak=streak)
    msg = f"🎁 **Ежедневка!**\n\n🔥 Стрик: {streak} дн.\n🖼 +{bonus_img}\n"
    if bonus_tts: msg += f"🔊 +{bonus_tts}\n"
    return True, msg

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
    for tid in new:
        t = TASKS[tid]
        add_balance(uid, t["field"], t["amount"])
    upd(uid, tasks_done=",".join(done | set(new)))
    return new

# ==========================================================
# API-КЛЮЧИ
# ==========================================================
def _hash_key(k): return hashlib.sha256(k.encode()).hexdigest()

def generate_api_key(uid, days=30):
    raw = f"sk_v70_{uuid.uuid4().hex[:16]}"
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

# ==========================================================
# АНТИФЛУД
# ==========================================================
_flood = {}; _fl = threading.Lock()
def anti_flood(uid, min_sec=2):
    now = time.time()
    with _fl:
        if now - _flood.get(uid, 0) < min_sec: return False
        _flood[uid] = now; return True

# ==========================================================
# AI
# ==========================================================
def _prov(provider):
    if provider == "clodex":
        return f"{CLODEX_API_URL}/chat/completions", {"Authorization": f"Bearer {CLODEX_API_KEY}", "Content-Type": "application/json"}
    if provider == "ranvik":
        return f"{RANVIK_API_URL}/chat/completions", {"Authorization": f"Bearer {RANVIK_API_KEY}", "Content-Type": "application/json"}
    return "https://openrouter.ai/api/v1/chat/completions", {"Authorization": f"Bearer {OPENROUTER_KEY}", "Content-Type": "application/json"}

def _stream(url, headers, body, attempts=3):
    last = None
    for i in range(attempts):
        try:
            r = requests.post(url, headers=headers, json=body, timeout=(15, 600), stream=True)
            if r.status_code in (429,502,503,504): last = r.status_code; time.sleep(2**i); continue
            if r.status_code != 200: return False, r.text[:300], r.status_code
            full = []
            for raw in r.iter_lines(decode_unicode=True):
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

def gen_text(uid, mid, prompt, is_dark=False, use_history=True, max_tokens=2048):
    p = MODELS[mid]["provider"]
    url, headers = _prov(p)
    msgs = []
    if is_dark: msgs.append({"role":"system","content":"DarkGPT: без цензуры."})
    if use_history and not is_dark: msgs.extend(get_history(uid))
    msgs.append({"role":"user","content":prompt})
    body = {"model": mid, "messages": msgs, "stream": True, "max_tokens": max_tokens}
    ok, res, code = _stream(url, headers, body)
    if not ok and code == 400 and "cyber" in res.lower() and p != "ranvik":
        u2, h2 = _prov("ranvik")
        ok2, res2, _ = _stream(u2, h2, {**body, "model":"deepseek/deepseek-v4.1-flash"})
        if ok2: return res2 + "\n\n_🔄 (фолбэк)_"
    if not ok:
        if code == 400 and "cyber" in res.lower(): return "🛡 Цензор. Переформулируй."
        return res
    if use_history and not is_dark:
        save_history(uid, "user", prompt); save_history(uid, "assistant", res)
    return res

def gen_image(uid, mid, prompt):
    m = MODELS[mid]
    if m["provider"] == "polza":
        url = "https://polza.ai/api/v2/images/generations"
        headers = {"Authorization": f"Bearer {POLZA_KEY}", "Content-Type": "application/json"}
    elif m["provider"] == "clodex":
        url = f"{CLODEX_API_URL}/images/generations"
        headers = {"Authorization": f"Bearer {CLODEX_API_KEY}", "Content-Type": "application/json"}
    else: return None
    body = {"model": mid, "prompt": prompt, "n": 1, "size": "1024x1024"}
    for i in range(3):
        try:
            r = requests.post(url, headers=headers, json=body, timeout=HTTP_TIMEOUT_LONG)
            if r.status_code in (429,502,503,504): time.sleep(2**i); continue
            if r.status_code != 200:
                log.warning(f"img {r.status_code}: {r.text[:200]}"); return None
            d = r.json()
            return d["data"][0].get("url") if d.get("data") else None
        except Exception as e: log.warning(f"img: {e}"); time.sleep(2**i)
    return None

def gen_video(uid, mid, prompt):
    url = f"{POLZA_BASE}/videos/generations"
    headers = {"Authorization": f"Bearer {POLZA_KEY}", "Content-Type": "application/json"}
    try:
        r = requests.post(url, headers=headers, json={"model":mid,"prompt":prompt}, timeout=HTTP_TIMEOUT_LONG)
        if r.status_code != 200: return None
        d = r.json()
        return d.get("url") or (d.get("data",[{}])[0].get("url") if d.get("data") else None)
    except Exception: return None

def gen_tts(uid, text, voice="alloy"):
    url = f"{POLZA_BASE}/audio/speech"
    headers = {"Authorization": f"Bearer {POLZA_KEY}", "Content-Type": "application/json"}
    try:
        r = requests.post(url, headers=headers, json={"model":"openai/tts-1","input":text,"voice":voice}, timeout=HTTP_TIMEOUT_LONG)
        return r.content if r.status_code == 200 else None
    except Exception: return None

# ==========================================================
# НАЧИСЛЕНИЕ ПО PAYLOAD
# ==========================================================
def fulfill_by_payload(uid, payload, amount, provider="", charge_id="", stars=0):
    kind = "balance"
    if payload.startswith("sub_"): kind = "sub"
    elif payload in API_SUB_PLANS: kind = "api_sub"
    with DbConn() as c:
        cur = c.cursor()
        cur.execute("INSERT INTO payments(user_id,package_id,amount,status,provider_id,ts,kind,provider,stars_amount) VALUES(?,?,?,?,?,?,?,?,?)",
                    (uid, payload, amount, "paid", charge_id, time.time(), kind, provider, stars))
    if payload in TEXT_SUB_TARIFFS:
        t = TEXT_SUB_TARIFFS[payload]
        u = get_user(uid) or {}
        until = max(u.get("sub_until",0), time.time()) + t["days"]*86400
        upd(uid, sub_plan=payload, sub_until=until, sub_used=0, sub_tokens_used=0)
        safe_photo(uid, IMG_SUB, f"✅ «{t['title']}» активна!\n🎁 {t['tokens']:,} токенов")
    elif payload in BALANCE_PACKS:
        p = BALANCE_PACKS[payload]
        add_balance(uid, p["field"], p["amount"])
        safe_photo(uid, IMG_BAL, f"✅ {p['title']} зачислено!")
    elif payload in API_SUB_PLANS:
        p = API_SUB_PLANS[payload]; now = time.time()
        with DbConn() as c:
            cur = c.cursor()
            cur.execute("SELECT expires_at FROM api_subs WHERE user_id=?", (uid,))
            r = cur.fetchone(); base = max(r[0] if r else 0, now)
            cur.execute("INSERT OR REPLACE INTO api_subs(user_id, plan, expires_at, requests_used, tokens_used) VALUES(?,?,?,0,0)",
                        (uid, payload, base + p["days"]*86400))
        safe_photo(uid, IMG_BAL, f"✅ {p['title']} активен {p['days']} дн.")
    log_ev(uid, "paid", f"{payload} {amount} via {provider}")

# ==========================================================
# PLATEGA V2
# ==========================================================
def platega_create(uid, rub, desc, pkg, kind="balance"):
    if not PLATEGA_ID or not PLATEGA_SECRET: return None, None
    usd = FxAnalyzer.rub_to_usd(rub)
    idem = f"pay_{uid}_{int(time.time())}_{uuid.uuid4().hex[:6]}"
    payload = {"merchantId": PLATEGA_ID, "amount": usd, "currency":"USD","description":desc,"orderId":idem,"returnUrl":RETURN_URL or "https://t.me"}
    headers = {"X-MerchantId": PLATEGA_ID, "X-Secret": PLATEGA_SECRET, "Content-Type":"application/json"}
    try:
        r = requests.post(f"{PLATEGA_URL}/v2/transaction/process", headers=headers, json=payload, timeout=HTTP_TIMEOUT_MED)
        if r.status_code not in (200,201):
            log.warning(f"platega {r.status_code}: {r.text[:200]}"); return None, None
        d = r.json()
        url = d.get("url") or d.get("redirect")
        with DbConn() as c:
            cur = c.cursor()
            cur.execute("INSERT INTO payments(user_id,package_id,amount,status,provider_id,ts,kind,provider) VALUES(?,?,?,?,?,?,?,?)",
                        (uid, pkg, rub, "pending", d.get("transactionId",""), time.time(), kind, "platega"))
            return url, cur.lastrowid
    except Exception as e:
        log.warning(f"platega: {e}"); return None, None

def platega_check(pid):
    with DbConn() as c:
        cur = c.cursor()
        cur.execute("SELECT provider_id, user_id, package_id, amount FROM payments WHERE id=?", (pid,))
        r = cur.fetchone()
    if not r: return "failed"
    prov, uid, pkg, amt = r
    if not prov or not PLATEGA_ID: return "pending"
    headers = {"X-MerchantId": PLATEGA_ID, "X-Secret": PLATEGA_SECRET}
    try:
        resp = requests.get(f"{PLATEGA_URL}/transaction/{prov}", headers=headers, timeout=HTTP_TIMEOUT_MED)
        if resp.status_code != 200: return "pending"
        st = (resp.json().get("status") or "").lower()
        if st in ("confirmed","success","paid"):
            _fulfill_platega(pid, uid, pkg, amt); return "paid"
        if st in ("canceled","failed","expired"): return "failed"
    except Exception: pass
    return "pending"

def _fulfill_platega(pid, uid, pkg, amt):
    with DbConn() as c:
        cur = c.cursor(); cur.execute("SELECT status FROM payments WHERE id=?", (pid,))
        r = cur.fetchone()
        if not r or r[0] == "paid": return
        cur.execute("UPDATE payments SET status='paid' WHERE id=?", (pid,))
    fulfill_by_payload(uid, pkg, amt, "platega")

def payment_poller():
    while not SHUTDOWN.is_set():
        try:
            with DbConn() as c:
                cur = c.cursor()
                cur.execute("SELECT id FROM payments WHERE status='pending' AND ts > ? LIMIT 20", (time.time()-3600,))
                for (pid,) in cur.fetchall(): platega_check(pid)
        except Exception as e: log.warning(f"poller: {e}")
        time.sleep(15)

# ==========================================================
# HEALTH / API
# ==========================================================
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
                    if t == "text": self._j(200, {"status":"ok","content": gen_text(uid, m, p)})
                    elif t == "dark_gpt": self._j(200, {"status":"ok","content": gen_text(uid, "deepseek/deepseek-v4.1-flash", p, True)})
                    elif t == "image":
                        u = gen_image(uid, m, p); self._j(200, {"status":"ok","url":u}) if u else self._j(500, {"error":"img"})
                    else: self._j(400, {"error":"bad type"})
                except Exception as e: self._j(500, {"error": str(e)})
            else: self.send_response(404); self.end_headers()
        def _j(self, c, d):
            b = json.dumps(d).encode(); self.send_response(c); self.send_header("Content-Type","application/json"); self.end_headers(); self.wfile.write(b)
        def log_message(self,*a): pass
    srv = http.server.ThreadingHTTPServer(("0.0.0.0", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

# ==========================================================
# МЕНЮ
# ==========================================================
def show_main_menu(uid):
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(types.InlineKeyboardButton("🔥 Fable 5.2", callback_data="new_claude"))
    kb.add(types.InlineKeyboardButton("🖼 Картинки", callback_data="menu_images"),
           types.InlineKeyboardButton("🎬 Видео", callback_data="menu_video"))
    kb.add(types.InlineKeyboardButton("🔊 Озвучка", callback_data="menu_tts"),
           types.InlineKeyboardButton("🎙 Расшифровка", callback_data="menu_stt"))
    kb.add(types.InlineKeyboardButton("🩸 DarkGPT", callback_data="cat_dark"),
           types.InlineKeyboardButton("🤖 Агенты", callback_data="menu_agents"))
    kb.add(types.InlineKeyboardButton("🎁 Ежедневка", callback_data="daily_bonus"),
           types.InlineKeyboardButton("🏆 Задания", callback_data="menu_tasks"))
    kb.add(types.InlineKeyboardButton("👥 Рефералы", callback_data="menu_refs"),
           types.InlineKeyboardButton("🛒 Маркет", callback_data="menu_market"))
    kb.add(types.InlineKeyboardButton("🧠 Память", callback_data="menu_memory"),
           types.InlineKeyboardButton("📝 Подписки", callback_data="menu_subs"))
    kb.add(types.InlineKeyboardButton("💠 Баланс", callback_data="menu_balance"),
           types.InlineKeyboardButton("💳 Пополнить", callback_data="menu_topup"))
    kb.add(types.InlineKeyboardButton("🔑 API", callback_data="menu_api"),
           types.InlineKeyboardButton("📜 История", callback_data="menu_history"))
    kb.add(types.InlineKeyboardButton("🆘 Поддержка", url=SUPPORT_URL))
    if TERMS_URL: kb.add(types.InlineKeyboardButton("📄 Соглашение", url=TERMS_URL))
    if PRIVACY_URL: kb.add(types.InlineKeyboardButton("🔒 Политика", url=PRIVACY_URL))
    if uid == ADMIN_ID: kb.add(types.InlineKeyboardButton("🛡 Админ", callback_data="admin_root"))
    safe_photo(uid, IMG_MAIN,
        "❄️ **Нейро-Студия v70** ❄️\n\n"
        "🔥 Fable 5.2 · 🖼 Картинки · 🎬 Видео\n"
        "🎁 Ежедневки · 🏆 Задания · 👥 Рефералы\n\n"
        "Выбери 👇",
        reply_markup=kb, parse_mode="Markdown")

def show_consent(uid, ref_by=0):
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(types.InlineKeyboardButton("✅ Принимаю", callback_data=f"consent_yes_{ref_by}"))
    if TERMS_URL: kb.add(types.InlineKeyboardButton("📄 Соглашение", url=TERMS_URL))
    if PRIVACY_URL: kb.add(types.InlineKeyboardButton("🔒 Политика", url=PRIVACY_URL))
    safe_photo(uid, IMG_MAIN,
        "❄️ **Добро пожаловать!**\n\n"
        "Подтверди:\n• Принимаю соглашение\n• Согласен с политикой\n• Мне 18+\n\n"
        "Нажми **✅ Принимаю**.",
        reply_markup=kb, parse_mode="Markdown")

# ==========================================================
# HANDLERS
# ==========================================================
def register_handlers():

    @bot.message_handler(commands=["start"])
    def start(m):
        uid = m.from_user.id
        args = m.text.split()
        ref_by = 0
        if len(args) > 1 and args[1].startswith("ref_"):
            try: ref_by = int(args[1][4:])
            except: pass
        add_user(uid, m.from_user.username or f"id{uid}", ref_by)
        u = get_user(uid) or {}
        if not u.get("consent_at"): return show_consent(uid, ref_by)
        upd(uid, state="", last_seen=time.time())
        show_main_menu(uid)

    @bot.callback_query_handler(func=lambda c: c.data.startswith("consent_yes"))
    def cb_consent(c):
        uid = c.from_user.id
        try:
            upd(uid, consent_at=time.time(), consent_version=CONSENT_VERSION, onboarded=1)
            process_referral(uid)
            log_ev(uid, "consent", CONSENT_VERSION)
            bot.answer_callback_query(c.id, "✅ Принято!")
            show_main_menu(uid)
        except Exception as e:
            log.error(f"consent: {e}"); bot.answer_callback_query(c.id, "❌ Ошибка. /start", show_alert=True)

    @bot.callback_query_handler(func=lambda c: c.data == "menu_main")
    def cb_main(c): bot.answer_callback_query(c.id); show_main_menu(c.from_user.id)

    # ===== ЕЖЕДНЕВКА =====
    @bot.callback_query_handler(func=lambda c: c.data == "daily_bonus")
    def cb_daily(c):
        ok, msg = claim_daily(c.from_user.id)
        bot.answer_callback_query(c.id, "🎁" if ok else "⏳", show_alert=not ok)
        safe_send(c.from_user.id, msg)

    # ===== ЗАДАНИЯ =====
    @bot.callback_query_handler(func=lambda c: c.data == "menu_tasks")
    def cb_tasks(c):
        bot.answer_callback_query(c.id)
        new = check_tasks(c.from_user.id)
        if new:
            txt = "🏆 **Новые задания выполнены!**\n\n"
            for tid in new:
                t = TASKS[tid]; txt += f"• {t['title']} → +{t['amount']} {t['field'].replace('balance_','')}\n"
            safe_send(c.from_user.id, txt, parse_mode="Markdown")
        u = get_user(c.from_user.id) or {}
        done = set(filter(None, (u.get("tasks_done") or "").split(",")))
        txt = "🏆 **Задания:**\n\n"
        for tid, t in TASKS.items():
            mark = "✅" if tid in done else "⬜"
            txt += f"{mark} {t['title']} → +{t['amount']} {t['field'].replace('balance_','')}\n"
        safe_photo(c.from_user.id, IMG_TEXT, txt[:4000], parse_mode="Markdown")

    # ===== РЕФЕРАЛЫ =====
    @bot.callback_query_handler(func=lambda c: c.data == "menu_refs")
    def cb_refs(c):
        bot.answer_callback_query(c.id)
        u = get_user(c.from_user.id) or {}
        bot_info = BOT_USERNAME or "your_bot"
        link = f"https://t.me/{bot_info}?start=ref_{c.from_user.id}"
        txt = (f"👥 **Рефералы**\n\n"
               f"🔗 Твоя ссылка:\n<code>{link}</code>\n\n"
               f"💰 За друга: +{REF_BONUS_REFERRER} 🖼 тебе, +{REF_BONUS_REFERRED} 🖼 другу\n\n"
               f"👥 Приглашено: {u.get('ref_count',0)}")
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("📤 Поделиться", url=f"https://t.me/share/url?url={link}&text=Попробуй этого бота!"))
        kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="menu_main"))
        safe_photo(c.from_user.id, IMG_TEXT, txt, reply_markup=kb, parse_mode="HTML")

    # ===== FABLE =====
    @bot.callback_query_handler(func=lambda c: c.data == "new_claude")
    def cb_fable(c):
        if not anti_flood(c.from_user.id): return bot.answer_callback_query(c.id, "⏳")
        bot.answer_callback_query(c.id); u = get_user(c.from_user.id) or {}
        upd(c.from_user.id, state="fable_wait")
        safe_photo(c.from_user.id, IMG_TEXT,
            f"🔥 **Fable 5.2**\n💰 5₽\n🧠 {u.get('text_free_used',0)}/{FREE_TEXT_LIMIT} бесплатных\n\n✍️ Вопрос:",
            parse_mode="Markdown")

    # ===== КАРТИНКИ =====
    @bot.callback_query_handler(func=lambda c: c.data == "menu_images")
    def cb_imgs(c):
        bot.answer_callback_query(c.id); kb = types.InlineKeyboardMarkup(row_width=1)
        for mid, m in MODELS.items():
            if m["type"] == "image": kb.add(types.InlineKeyboardButton(f"{m['name']} — {m['price']}₽", callback_data=f"imgsel_{mid}"))
        kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="menu_main"))
        safe_photo(c.from_user.id, IMG_IMAGE, "🖼 Выбери модель:", reply_markup=kb, parse_mode="Markdown")

    @bot.callback_query_handler(func=lambda c: c.data.startswith("imgsel_"))
    def cb_isel(c):
        mid = c.data[7:]
        if mid not in MODELS: return
        bot.answer_callback_query(c.id); u = get_user(c.from_user.id) or {}
        upd(c.from_user.id, state="img_wait", temp_model_id=mid)
        safe_photo(c.from_user.id, IMG_IMAGE,
            f"🖼 {MODELS[mid]['name']}\n💰 {MODELS[mid]['price']}₽\n🎟 {u.get('balance_img',0)}\n\n✍️ Промпт:",
            parse_mode="Markdown")

    # ===== ВИДЕО =====
    @bot.callback_query_handler(func=lambda c: c.data == "menu_video")
    def cb_vid(c):
        bot.answer_callback_query(c.id); kb = types.InlineKeyboardMarkup(row_width=1)
        for mid, m in VIDEO_MODELS.items(): kb.add(types.InlineKeyboardButton(f"{m['name']} — {m['price']}₽", callback_data=f"vidsel_{mid}"))
        kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="menu_main"))
        u = get_user(c.from_user.id) or {}
        safe_photo(c.from_user.id, IMG_VIDEO, f"🎬 Баланс: {u.get('balance_vid',0)}", reply_markup=kb, parse_mode="Markdown")

    @bot.callback_query_handler(func=lambda c: c.data.startswith("vidsel_"))
    def cb_vsel(c):
        mid = c.data[7:]
        if mid not in VIDEO_MODELS: return
        bot.answer_callback_query(c.id); upd(c.from_user.id, state="vid_wait", temp_model_id=mid)
        safe_photo(c.from_user.id, IMG_VIDEO, f"🎬 {VIDEO_MODELS[mid]['name']}\n\n✍️ Опиши видео:", parse_mode="Markdown")

    # ===== TTS/STT =====
    @bot.callback_query_handler(func=lambda c: c.data == "menu_tts")
    def cb_tts(c):
        bot.answer_callback_query(c.id); u = get_user(c.from_user.id) or {}
        upd(c.from_user.id, state="tts_wait")
        safe_photo(c.from_user.id, IMG_TEXT, f"🔊 {u.get('balance_tts',0)}\n\n✍️ Текст:", parse_mode="Markdown")

    @bot.callback_query_handler(func=lambda c: c.data == "menu_stt")
    def cb_stt(c):
        bot.answer_callback_query(c.id); u = get_user(c.from_user.id) or {}
        upd(c.from_user.id, state="stt_wait")
        safe_photo(c.from_user.id, IMG_TEXT, f"🎙 {u.get('balance_stt',0)}\n\n🎤 Голосовое:", parse_mode="Markdown")

    # ===== ПОДПИСКИ =====
    @bot.callback_query_handler(func=lambda c: c.data == "menu_subs")
    def cb_subs(c):
        bot.answer_callback_query(c.id); kb = types.InlineKeyboardMarkup(row_width=1)
        for code, t in TEXT_SUB_TARIFFS.items():
            kb.add(types.InlineKeyboardButton(f"{t['title']} — {t['price']}₽", callback_data=f"sub_{code}"))
            kb.add(types.InlineKeyboardButton(f"⭐ {t['title']} — {rub_to_stars(t['price'])}⭐", callback_data=f"stars_sub_{code}"))
        kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="menu_main"))
        safe_photo(c.from_user.id, IMG_SUB, "📝 Подписки:", reply_markup=kb, parse_mode="Markdown")

    @bot.callback_query_handler(func=lambda c: c.data.startswith("stars_sub_"))
    def cb_stars_sub(c):
        code = c.data[10:]
        if code not in TEXT_SUB_TARIFFS: return
        t = TEXT_SUB_TARIFFS[code]; bot.answer_callback_query(c.id)
        stars = rub_to_stars(t["price"])
        try:
            bot.send_invoice(
                chat_id=c.from_user.id, title=t["title"][:32],
                description=f"{t['tokens']:,} токенов на {t['days']} дней"[:255],
                invoice_payload=f"sub_{code}", provider_token="", currency="XTR",
                prices=[types.LabeledPrice(label=t["title"], amount=stars)],
            )
        except Exception as e:
            log.error(f"stars invoice: {e}"); safe_send(c.from_user.id, "❌ Не удалось создать счёт.")

    @bot.callback_query_handler(func=lambda c: c.data.startswith("sub_"))
    def cb_sub(c):
        code = c.data[4:]
        if code not in TEXT_SUB_TARIFFS: return
        t = TEXT_SUB_TARIFFS[code]; bot.answer_callback_query(c.id, "Создаю...")
        url, pid = platega_create(c.from_user.id, t["price"], t["title"], code, kind="sub")
        if not url: return safe_send(c.from_user.id, "❌ Ошибка платежа.")
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("💳 Оплатить", url=url))
        kb.add(types.InlineKeyboardButton("🔄 Проверить", callback_data=f"checkpay_{pid}"))
        safe_photo(c.from_user.id, IMG_SUB, f"💳 {t['title']}\n💰 {t['price']}₽", reply_markup=kb, parse_mode="Markdown")

    # ===== БАЛАНС =====
    @bot.callback_query_handler(func=lambda c: c.data == "menu_balance")
    def cb_bal(c):
        bot.answer_callback_query(c.id); u = get_user(c.from_user.id) or {}
        sub = "—"
        if u.get("sub_until",0) > time.time(): sub = f"{u.get('sub_plan','')} ({(u['sub_until']-time.time())//86400:.0f}д)"
        txt = (f"💠 **Баланс**\n\n"
               f"🖼 {u.get('balance_img',0)} · 🎬 {u.get('balance_vid',0)}\n"
               f"🔊 {u.get('balance_tts',0)} · 🎙 {u.get('balance_stt',0)}\n"
               f"⬆️ {u.get('balance_up',0)} · ✏️ {u.get('balance_edit',0)} · 🎞 {u.get('balance_anim',0)}\n\n"
               f"📝 {sub}\n👥 Рефералов: {u.get('ref_count',0)}")
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("💳 Пополнить", callback_data="menu_topup"))
        kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="menu_main"))
        safe_photo(c.from_user.id, IMG_BAL, txt, reply_markup=kb, parse_mode="Markdown")

    @bot.callback_query_handler(func=lambda c: c.data == "menu_topup")
    def cb_top(c):
        bot.answer_callback_query(c.id); kb = types.InlineKeyboardMarkup(row_width=2)
        for code, p in BALANCE_PACKS.items():
            kb.add(types.InlineKeyboardButton(f"{p['title']} — {p['price']}₽", callback_data=f"topup_{code}"))
        kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="menu_balance"))
        safe_photo(c.from_user.id, IMG_BAL, "💳 Пакеты:", reply_markup=kb, parse_mode="Markdown")

    @bot.callback_query_handler(func=lambda c: c.data.startswith("topup_"))
    def cb_topbuy(c):
        code = c.data[6:]
        if code not in BALANCE_PACKS: return
        p = BALANCE_PACKS[code]; bot.answer_callback_query(c.id, "Создаю...")
        url, pid = platega_create(c.from_user.id, p["price"], p["title"], code, kind="balance")
        if not url: return safe_send(c.from_user.id, "❌ Ошибка.")
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("💳 Оплатить", url=url))
        kb.add(types.InlineKeyboardButton("🔄 Проверить", callback_data=f"checkpay_{pid}"))
        safe_photo(c.from_user.id, IMG_BAL, f"💳 {p['title']}\n💰 {p['price']}₽", reply_markup=kb, parse_mode="Markdown")

    @bot.callback_query_handler(func=lambda c: c.data.startswith("checkpay_"))
    def cb_check(c):
        st = platega_check(int(c.data[9:]))
        msg = {"paid":"✅ Оплачено!","failed":"❌ Не прошёл","pending":"⏳ Не оплачено"}.get(st,"⏳")
        bot.answer_callback_query(c.id, msg, show_alert=True)

    # ===== STARS payment handlers =====
    @bot.pre_checkout_query_handler(func=lambda q: True)
    def pre_checkout(q): bot.answer_pre_checkout_query(q.id, ok=True)

    @bot.message_handler(content_types=["successful_payment"])
    def on_paid(m):
        p = m.successful_payment; uid = m.from_user.id
        fulfill_by_payload(uid, p.invoice_payload, int(p.total_amount * STARS_RUB_PER_STAR),
                           provider="stars", charge_id=p.telegram_payment_charge_id, stars=p.total_amount)
        safe_send(uid, f"✅ Оплачено {p.total_amount} ⭐!")

    # ===== API =====
    @bot.callback_query_handler(func=lambda c: c.data == "menu_api")
    def cb_api(c):
        bot.answer_callback_query(c.id)
        with DbConn() as db_c:
            cur = db_c.cursor()
            cur.execute("SELECT plan, expires_at, requests_used, tokens_used FROM api_subs WHERE user_id=? AND expires_at>?", (c.from_user.id, time.time()))
            sub = cur.fetchone()
        if sub:
            plan, exp, req, tok = sub; p = API_SUB_PLANS.get(plan, {})
            txt = (f"🔑 **API активен**\n{p.get('title','')}\n"
                   f"⏳ {(exp-time.time())//86400:.0f} дн.\n"
                   f"📊 {req}/{p.get('requests','?')}\n🔤 {tok:,}/{p.get('tokens',0):,}\n\n"
                   f"Ключ: /gen_api")
            kb = types.InlineKeyboardMarkup(); kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="menu_main"))
            return safe_photo(c.from_user.id, IMG_BAL, txt, reply_markup=kb, parse_mode="Markdown")
        kb = types.InlineKeyboardMarkup(row_width=1)
        for code, p in API_SUB_PLANS.items():
            kb.add(types.InlineKeyboardButton(f"{p['title']} — {p['price']}₽", callback_data=f"apisub_{code}"))
            kb.add(types.InlineKeyboardButton(f"⭐ {p['title']} — {rub_to_stars(p['price'])}⭐", callback_data=f"stars_api_{code}"))
        kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="menu_main"))
        safe_photo(c.from_user.id, IMG_BAL, "🔑 API-доступ:", reply_markup=kb, parse_mode="Markdown")

    @bot.callback_query_handler(func=lambda c: c.data.startswith("stars_api_"))
    def cb_stars_api(c):
        code = c.data[10:]
        if code not in API_SUB_PLANS: return
        p = API_SUB_PLANS[code]; bot.answer_callback_query(c.id)
        stars = rub_to_stars(p["price"])
        bot.send_invoice(c.from_user.id, title=p["title"][:32], description=f"{p['days']} дней API"[:255],
                         invoice_payload=code, provider_token="", currency="XTR",
                         prices=[types.LabeledPrice(label=p["title"], amount=stars)])

    @bot.callback_query_handler(func=lambda c: c.data.startswith("apisub_"))
    def cb_api_buy(c):
        code = c.data[7:]
        if code not in API_SUB_PLANS: return
        p = API_SUB_PLANS[code]; bot.answer_callback_query(c.id, "Создаю...")
        url, pid = platega_create(c.from_user.id, p["price"], p["title"], code, kind="api_sub")
        if not url: return safe_send(c.from_user.id, "❌ Ошибка.")
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("💳 Оплатить", url=url))
        kb.add(types.InlineKeyboardButton("🔄 Проверить", callback_data=f"checkpay_{pid}"))
        safe_photo(c.from_user.id, IMG_BAL, f"💳 {p['title']}\n💰 {p['price']}₽", reply_markup=kb, parse_mode="Markdown")

    @bot.message_handler(commands=["gen_api"])
    def gen_api(m):
        raw = generate_api_key(m.from_user.id)
        safe_photo(m.chat.id, IMG_BAL, f"✅ <code>{raw}</code>\n\n⚠️ Сохрани, больше не покажем.", parse_mode="HTML")

    # ===== ИСТОРИЯ =====
    @bot.callback_query_handler(func=lambda c: c.data == "menu_history")
    def cb_hist(c):
        bot.answer_callback_query(c.id)
        with DbConn() as db_c:
            cur = db_c.cursor()
            cur.execute("SELECT m_type, model_id, prompt, ts FROM works WHERE user_id=? ORDER BY id DESC LIMIT 10", (c.from_user.id,))
            rows = cur.fetchall()
        if not rows: return safe_send(c.from_user.id, "📜 Пусто.")
        txt = "📜 **Последние 10:**\n\n"
        for mt, mid, pr, ts in rows:
            txt += f"• {datetime.fromtimestamp(ts).strftime('%d.%m %H:%M')} · {mt} · {mid} · {pr[:40]}\n"
        safe_send(c.from_user.id, txt[:4000], parse_mode="Markdown")

    # ===== АГЕНТЫ (платно) =====
    @bot.callback_query_handler(func=lambda c: c.data == "menu_agents")
    def cb_ag(c):
        bot.answer_callback_query(c.id); u = get_user(c.from_user.id) or {}
        price_line = "🆓 Бесплатно (админ)" if is_admin(c.from_user.id) else f"💰 Цена: {AGENT_PRICE_IMG} 🖼"
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("➕ Создать агента", callback_data="create_agent"))
        kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="menu_main"))
        safe_photo(c.from_user.id, IMG_TEXT,
            f"🤖 **Агенты** (GPT + Fable + Dark)\n\n"
            f"{price_line}\n🎟 Баланс: {u.get('balance_img',0)} 🖼",
            reply_markup=kb, parse_mode="Markdown")

    @bot.callback_query_handler(func=lambda c: c.data == "create_agent")
    def cb_cag(c):
        u = get_user(c.from_user.id) or {}
        if not is_admin(c.from_user.id) and u.get("balance_img", 0) < AGENT_PRICE_IMG:
            return bot.answer_callback_query(c.id, f"❌ Нужно {AGENT_PRICE_IMG} 🖼", show_alert=True)
        bot.answer_callback_query(c.id, "Напиши вопрос!", show_alert=True)
        upd(c.from_user.id, state="agent_wait_prompt")

    # ===== ПАМЯТЬ =====
    @bot.callback_query_handler(func=lambda c: c.data == "menu_memory")
    def cb_mem(c):
        bot.answer_callback_query(c.id)
        with DbConn() as db_c:
            cur = db_c.cursor(); cur.execute("SELECT fact FROM user_facts WHERE user_id=? LIMIT 20", (c.from_user.id,))
            facts = [r[0] for r in cur.fetchall()]
        body = "\n".join(f"❄️ {f}" for f in facts) if facts else "Пусто."
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🧹 Очистить", callback_data="clear_memory"))
        kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="menu_main"))
        safe_photo(c.from_user.id, IMG_TEXT, f"🧠 {body}", reply_markup=kb, parse_mode="Markdown")

    @bot.callback_query_handler(func=lambda c: c.data == "clear_memory")
    def cb_cm(c):
        with DbConn() as db_c:
            db_c.cursor().execute("DELETE FROM user_facts WHERE user_id=?", (c.from_user.id,))
            db_c.cursor().execute("DELETE FROM chat_history WHERE user_id=?", (c.from_user.id,))
        bot.answer_callback_query(c.id, "🧹 Очищено!", show_alert=True)

    # ===== МАРКЕТПЛЕЙС =====
    @bot.callback_query_handler(func=lambda c: c.data == "menu_market")
    def cb_mkt(c):
        bot.answer_callback_query(c.id)
        with DbConn() as db_c:
            cur = db_c.cursor(); cur.execute("SELECT id,title,price,sales FROM prompt_market ORDER BY sales DESC LIMIT 10")
            rows = cur.fetchall()
        kb = types.InlineKeyboardMarkup(row_width=1)
        for pid, title, price, sales in rows:
            kb.add(types.InlineKeyboardButton(f"🛒 {title} — {price}₽", callback_data=f"buyprompt_{pid}"))
        kb.add(types.InlineKeyboardButton("➕ Продать", callback_data="market_sell"))
        kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="menu_main"))
        safe_photo(c.from_user.id, IMG_TEXT, "🛒 Маркет:", reply_markup=kb, parse_mode="Markdown")

    @bot.callback_query_handler(func=lambda c: c.data == "market_sell")
    def cb_ms(c):
        bot.answer_callback_query(c.id, "Формат: Продать: Название | Промпт | Цена", show_alert=True)
        upd(c.from_user.id, state="market_sell_wait")

    @bot.callback_query_handler(func=lambda c: c.data.startswith("buyprompt_"))
    def cb_bp(c):
        pid = int(c.data[10:])
        with DbConn() as db_c:
            cur = db_c.cursor(); cur.execute("SELECT title,prompt FROM prompt_market WHERE id=?", (pid,))
            r = cur.fetchone()
        if not r: return bot.answer_callback_query(c.id, "Нет", show_alert=True)
        bot.answer_callback_query(c.id); safe_send(c.from_user.id, f"📝 {r[0]}\n\n<code>{r[1]}</code>", parse_mode="HTML")

    # ===== DARK =====
    @bot.callback_query_handler(func=lambda c: c.data == "cat_dark")
    def cb_dark(c):
        bot.answer_callback_query(c.id); upd(c.from_user.id, state="dark_wait")
        safe_photo(c.from_user.id, IMG_TEXT, "🩸 DarkGPT\n\n✍️ Вопрос:", parse_mode="Markdown")

    # ===== АДМИН =====
    @bot.callback_query_handler(func=lambda c: c.data == "admin_root")
    def cb_admin(c):
        if c.from_user.id != ADMIN_ID: return bot.answer_callback_query(c.id, "⛔", show_alert=True)
        bot.answer_callback_query(c.id)
        with DbConn() as db_c:
            cur = db_c.cursor()
            cur.execute("SELECT COUNT(*) FROM users"); total = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*), COALESCE(SUM(amount),0) FROM payments WHERE status='paid'")
            row = cur.fetchone()
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(types.InlineKeyboardButton("👥 Юзеры", callback_data="admin_users"))
        kb.add(types.InlineKeyboardButton("💳 Платежи", callback_data="admin_payments"))
        kb.add(types.InlineKeyboardButton("📊 Статистика", callback_data="admin_stats"))
        kb.add(types.InlineKeyboardButton("🎁 Выдать", callback_data="admin_give_menu"))
        kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="menu_main"))
        safe_photo(c.from_user.id, IMG_MAIN, f"🛡 Админ\n👥 {total}\n💳 {row[0]} на {row[1]}₽", reply_markup=kb, parse_mode="Markdown")

    @bot.callback_query_handler(func=lambda c: c.data == "admin_users")
    def cb_au(c):
        if c.from_user.id != ADMIN_ID: return
        with DbConn() as db_c:
            cur = db_c.cursor(); cur.execute("SELECT user_id,username,balance_img,balance_vid,last_seen FROM users ORDER BY last_seen DESC LIMIT 20")
            rows = cur.fetchall()
        txt = "👥 Последние 20:\n\n"
        for uid, un, bi, bv, ls in rows:
            last = datetime.fromtimestamp(ls).strftime("%d.%m %H:%M") if ls else "—"
            txt += f"• <code>{uid}</code> @{un or '—'} 🖼{bi} 🎬{bv} ({last})\n"
        bot.answer_callback_query(c.id); safe_send(c.from_user.id, txt[:4000], parse_mode="HTML")

    @bot.callback_query_handler(func=lambda c: c.data == "admin_payments")
    def cb_ap(c):
        if c.from_user.id != ADMIN_ID: return
        with DbConn() as db_c:
            cur = db_c.cursor(); cur.execute("SELECT user_id,package_id,amount,status,ts FROM payments ORDER BY id DESC LIMIT 20")
            rows = cur.fetchall()
        txt = "💳 Последние:\n\n"
        for uid, pkg, amt, st, ts in rows:
            t = datetime.fromtimestamp(ts).strftime("%d.%m %H:%M")
            em = "✅" if st == "paid" else ("⏳" if st == "pending" else "❌")
            txt += f"{em} {t} · {uid} · {pkg} · {amt}₽\n"
        bot.answer_callback_query(c.id); safe_send(c.from_user.id, txt[:4000], parse_mode="HTML")

    @bot.callback_query_handler(func=lambda c: c.data == "admin_stats")
    def cb_as(c):
        if c.from_user.id != ADMIN_ID: return
        with DbConn() as db_c:
            cur = db_c.cursor()
            cur.execute("SELECT COALESCE(SUM(amount),0) FROM payments WHERE status='paid' AND ts > ?", (time.time()-86400,)); today = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM users WHERE created_at > ?", (time.time()-86400,)); new = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM users WHERE sub_until > ?", (time.time(),)); subs = cur.fetchone()[0]
        bot.answer_callback_query(c.id); safe_send(c.from_user.id, f"📊 24ч:\n💰 {today}₽\n👥 +{new}\n📝 {subs} подписок")

    @bot.callback_query_handler(func=lambda c: c.data == "admin_give_menu")
    def cb_agm(c):
        if c.from_user.id != ADMIN_ID: return
        bot.answer_callback_query(c.id)
        safe_send(c.from_user.id, "🎁 Формат: `ID поле количество`\nПоля: img/vid/tts/stt/edit/anim/up\nПример: `123456 img 50`", parse_mode="Markdown")
        upd(c.from_user.id, state="admin_give_wait")

    # ===== ТЕКСТ =====
    @bot.message_handler(content_types=["text"])
    def handle_text(m):
        uid = m.from_user.id
        if not m.text: return
        u = get_user(uid) or {}
        text = m.text.strip(); state = u.get("state", "")

        if text == "/start": return start(m)

        if text.lower().startswith("запомни:"):
            fact = text[8:].strip()
            if not fact: return safe_send(uid, "❌ Пусто.")
            with DbConn() as c: c.cursor().execute("INSERT INTO user_facts(user_id, fact, ts) VALUES(?,?,?)", (uid, fact, time.time()))
            return safe_send(uid, f"🧠 {fact}")

        if text.lower().startswith("продать:"):
            try:
                _, rest = text.split(":", 1); title, prompt, price = rest.split("|", 2); pi = int(price.strip())
                if pi < 10 or pi > 10000: raise ValueError
                with DbConn() as c: c.cursor().execute("INSERT INTO prompt_market(seller_id, title, prompt, price, ts) VALUES(?,?,?,?,?)", (uid, title.strip()[:100], prompt.strip()[:2000], pi, time.time()))
                return safe_send(uid, "✅ Выставлен!")
            except: return safe_send(uid, "❌ Формат: Продать: Название | Промпт | 100")

        if state == "admin_give_wait" and uid == ADMIN_ID:
            try:
                target, field, amount = text.split(); target, amount = int(target), int(amount)
                fm = {"img":"balance_img","vid":"balance_vid","tts":"balance_tts","stt":"balance_stt","edit":"balance_edit","anim":"balance_anim","up":"balance_up"}
                if field not in fm: raise ValueError
                add_balance(target, fm[field], amount); upd(uid, state="")
                return safe_send(uid, f"✅ +{amount} {field} → {target}")
            except: return safe_send(uid, "❌ 123456 img 50")

        if state == "fable_wait":
            if not anti_flood(uid): return safe_send(uid, "⏳")
            upd(uid, state=""); status = safe_send(uid, "❄️ Думаю...")
            ans = gen_text(uid, "claude-fable-5.2", text)
            try: bot.delete_message(uid, status.message_id)
            except: pass
            return safe_send(uid, ans[:4000])

        # ===== АГЕНТЫ (10🖼, кроме админа) =====
        if state == "agent_wait_prompt":
            upd(uid, state="")
            if not charge(uid, "balance_img", AGENT_PRICE_IMG):
                return safe_send(uid, f"❌ Нужно {AGENT_PRICE_IMG} 🖼 для запуска агентов.\nПополни: 💳 Пополнить")
            status = safe_send(uid, "🤖 Агенты совещаются... ❄️")
            f1 = AGENT_EXECUTOR.submit(gen_text, uid, "gpt-6-astra", text, False, False, 1024)
            f2 = AGENT_EXECUTOR.submit(gen_text, uid, "claude-fable-5.2", text, False, False, 1024)
            f3 = AGENT_EXECUTOR.submit(gen_text, uid, "deepseek/deepseek-v4.1-flash", text, True, False, 1024)
            r1, r2, r3 = f1.result(), f2.result(), f3.result()
            try: bot.delete_message(uid, status.message_id)
            except: pass
            safe_send(uid, f"💬 GPT-6:\n{r1[:1000]}")
            safe_send(uid, f"🔥 Fable:\n{r2[:1000]}")
            safe_send(uid, f"🩸 Dark:\n{r3[:1000]}")
            return

        if state == "dark_wait":
            if not anti_flood(uid): return safe_send(uid, "⏳")
            upd(uid, state=""); return safe_send(uid, gen_text(uid, "deepseek/deepseek-v4.1-flash", text, True)[:4000])

        if state == "img_wait":
            mid = u.get("temp_model_id")
            if not mid or mid not in MODELS: upd(uid, state=""); return safe_send(uid, "❌ Модель.")
            if not charge(uid, "balance_img", 1): upd(uid, state=""); return safe_send(uid, "❌ Нет картинок.")
            upd(uid, state=""); status = safe_send(uid, "🎨 Рисую...")
            url = gen_image(uid, mid, text)
            try: bot.delete_message(uid, status.message_id)
            except: pass
            if url:
                with DbConn() as c: c.cursor().execute("INSERT INTO works(user_id,m_type,model_id,prompt,file_id,ts) VALUES(?,?,?,?,?,?)", (uid,"image",mid,text[:500],url,time.time()))
                try: bot.send_photo(uid, url, caption=f"✅ {MODELS[mid]['name']}")
                except: safe_send(uid, f"🖼 {url}")
                check_tasks(uid)
            else:
                if not is_admin(uid): add_balance(uid, "balance_img", 1)
                safe_send(uid, "❌ Ошибка. Баланс возвращён.")
            return

        if state == "vid_wait":
            mid = u.get("temp_model_id")
            if not mid or mid not in VIDEO_MODELS: upd(uid, state=""); return safe_send(uid, "❌ Модель.")
            if not charge(uid, "balance_vid", 1): upd(uid, state=""); return safe_send(uid, "❌ Нет видео.")
            upd(uid, state=""); status = safe_send(uid, "🎬 Рендерю...")
            url = gen_video(uid, mid, text)
            try: bot.delete_message(uid, status.message_id)
            except: pass
            if url:
                with DbConn() as c: c.cursor().execute("INSERT INTO works(user_id,m_type,model_id,prompt,file_id,ts) VALUES(?,?,?,?,?,?)", (uid,"video",mid,text[:500],url,time.time()))
                try: bot.send_video(uid, url, caption=f"✅ {VIDEO_MODELS[mid]['name']}")
                except: safe_send(uid, f"🎬 {url}")
            else:
                if not is_admin(uid): add_balance(uid, "balance_vid", 1)
                safe_send(uid, "❌ Ошибка. Баланс возвращён.")
            return

        if state == "tts_wait":
            if not charge(uid, "balance_tts", 1): upd(uid, state=""); return safe_send(uid, "❌ Нет озвучек.")
            upd(uid, state=""); status = safe_send(uid, "🔊 Озвучиваю...")
            audio = gen_tts(uid, text)
            try: bot.delete_message(uid, status.message_id)
            except: pass
            if audio:
                try: bot.send_voice(uid, io.BytesIO(audio), caption="✅")
                except: safe_send(uid, "❌")
            else:
                if not is_admin(uid): add_balance(uid, "balance_tts", 1)
                safe_send(uid, "❌ Ошибка.")
            return

        if state == "stt_wait": return safe_send(uid, "🎙 Отправь голосовое.")

        if not anti_flood(uid): return safe_send(uid, "⏳")
        status = safe_send(uid, "❄️ Думаю...")
        ans = gen_text(uid, "gpt-6-astra", text)
        try: bot.delete_message(uid, status.message_id)
        except: pass
        safe_send(uid, ans[:4000])

    @bot.message_handler(content_types=["voice","audio","video_note"])
    def handle_audio(m):
        uid = m.from_user.id
        if not charge(uid, "balance_stt", 1): return safe_send(uid, "❌ Нет расшифровок.")
        status = safe_send(uid, "🎙 Расшифровываю...")
        try:
            fid = m.voice.file_id if m.voice else (m.audio.file_id if m.audio else m.video_note.file_id)
            data = bot.download_file(bot.get_file(fid).file_path)
            r = requests.post(f"{POLZA_BASE}/audio/transcriptions", headers={"Authorization": f"Bearer {POLZA_KEY}"},
                              files={"file":("a.ogg",data)}, data={"model":"openai/whisper-1"}, timeout=HTTP_TIMEOUT_LONG)
            try: bot.delete_message(uid, status.message_id)
            except: pass
            if r.status_code == 200: safe_send(uid, f"🎙 {r.json().get('text','')[:4000]}")
            else:
                if not is_admin(uid): add_balance(uid, "balance_stt", 1)
                safe_send(uid, "❌ Ошибка.")
        except Exception as e:
            if not is_admin(uid): add_balance(uid, "balance_stt", 1)
            safe_send(uid, f"❌ {e}")

# ==========================================================
# MAIN
# ==========================================================
def main():
    global bot
    if not TOKEN or not POLZA_KEY: raise SystemExit("BOT_TOKEN / POLZA_KEY не заданы")
    os.makedirs(DATA_DIR, exist_ok=True)
    Db.init(os.path.join(DATA_DIR, "media_bot.db"), DB_POOL_SIZE)
    init_db()
    bot = telebot.TeleBot(TOKEN, threaded=True)
    register_handlers()
    signal.signal(signal.SIGTERM, lambda s,f: SHUTDOWN.set())
    signal.signal(signal.SIGINT, lambda s,f: SHUTDOWN.set())
    start_health(HEALTH_PORT)
    threading.Thread(target=payment_poller, daemon=True).start()
    threading.Thread(target=lambda: bot.infinity_polling(timeout=30, long_polling_timeout=25), daemon=True).start()
    log.info("❄️ Neuro Studio v70 started ❄️")
    while not SHUTDOWN.is_set(): time.sleep(1)

if __name__ == "__main__":
    main()
