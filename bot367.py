import os
import json
import datetime as dt
import asyncio
import aiosqlite
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Message, BotCommand
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# ======= KONFIG =======
TOKEN = "8829495006:AAEHPcyNJlQAYLyfsLI0-FJY9nB8jZnS6b4"
ADMINS = {8359722718}
REF_BONUS = 2.0
DAILY_BONUS = 1.0
CLICK_COOLDOWN_MIN = 10
CLICK_REWARD_DEFAULT = 0.1
LOG_CHANNEL_ID = -1002672668104  # Kanal ID (isiğe bağlı)

DB_PATH = "stars.db"

# ======= FSM STATE'LER =======
class WithdrawFSM(StatesGroup):
    choose = State()
    contact = State()

class PromoFSM(StatesGroup):
    waiting = State()
    create = State()

class SeyfFSM(StatesGroup):
    waiting = State()

class SetRefFSM(StatesGroup):
    waiting = State()

class AddChannelFSM(StatesGroup):
    waiting = State()

class AddTaskFSM(StatesGroup):
    title = State()
    url = State()
    reward = State()

class BalanceFSM(StatesGroup):
    uid = State()
    action = State()
    amount = State()

class ClickSetFSM(StatesGroup):
    reward = State()

# ======= BOT VE DİSPATCHER =======
bot = Bot(token=TOKEN)
dp = Dispatcher()

# ======= GIFT OPTIONS =======
GIFT_OPTIONS = [
    ("bear", "🧸 15⭐", 15),
    ("heartbox", "💝 15⭐", 15),
    ("gift25", "🎁 25⭐", 25),
    ("rose", "🌹 25⭐", 25),
    ("cake", "🎂 50⭐", 50),
    ("bouquet", "💐 50⭐", 50),
    ("rocket", "🚀 50⭐", 50),
    ("champ", "🍾 50⭐", 50),
    ("cup", "🏆 100⭐", 100),
    ("ring", "💍 100⭐", 100),
    ("gem", "💎 100⭐", 100),
]

# ======= HELPERS =======
def fmt_stars(x: float) -> str:
    return f"{int(x) if float(x).is_integer() else x} ⭐"

# ======= DATABASE FUNCTIONS =======
async def init_db():
    async with aiosqlite.connect(DB_PATH) as con:
        await con.execute("""CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY,
            balance REAL DEFAULT 0,
            ref_by INTEGER,
            invited_cnt INTEGER DEFAULT 0,
            last_daily TEXT,
            rewarded_ref INTEGER DEFAULT 0,
            last_click TEXT
        )""")
        await con.execute("""CREATE TABLE IF NOT EXISTS promos(
            code TEXT PRIMARY KEY,
            reward REAL,
            remaining INTEGER,
            created_by INTEGER,
            created_at TEXT
        )""")
        await con.execute("""CREATE TABLE IF NOT EXISTS channels(
            username TEXT PRIMARY KEY
        )""")
        await con.execute("""CREATE TABLE IF NOT EXISTS tasks(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            url TEXT,
            reward REAL,
            type TEXT
        )""")
        await con.execute("""CREATE TABLE IF NOT EXISTS withdrawals(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount REAL,
            contact TEXT,
            status TEXT,
            created_at TEXT,
            gift TEXT
        )""")
        await con.execute("""CREATE TABLE IF NOT EXISTS user_tasks(
            user_id INTEGER,
            task_id INTEGER,
            PRIMARY KEY (user_id, task_id)
        )""")
        await con.execute("""CREATE TABLE IF NOT EXISTS settings(
            key TEXT PRIMARY KEY,
            value TEXT
        )""")
        await con.commit()

        # Migration
        cur = await con.execute("PRAGMA table_info(withdrawals)")
        cols = [r[1] for r in await cur.fetchall()]
        if "gift" not in cols:
            await con.execute("ALTER TABLE withdrawals ADD COLUMN gift TEXT")
        
        cur = await con.execute("PRAGMA table_info(users)")
        cols = [r[1] for r in await cur.fetchall()]
        if "last_click" not in cols:
            await con.execute("ALTER TABLE users ADD COLUMN last_click TEXT")
        
        await con.commit()
        await con.execute("INSERT OR IGNORE INTO settings(key, value) VALUES('click_reward', ?)", (str(CLICK_REWARD_DEFAULT),))
        await con.commit()

async def get_setting(key: str, default: str) -> str:
    async with aiosqlite.connect(DB_PATH) as con:
        cur = await con.execute("SELECT value FROM settings WHERE key=?", (key,))
        row = await cur.fetchone()
        return row[0] if row else default

async def set_setting(key: str, value: str):
    async with aiosqlite.connect(DB_PATH) as con:
        await con.execute("INSERT OR REPLACE INTO settings(key, value) VALUES(?,?)", (key, value))
        await con.commit()

async def admins_all() -> list:
    base = set(ADMINS)
    if os.path.exists("admins.json"):
        with open("admins.json", "r") as f:
            base |= set(json.load(f))
    return list(base)

async def is_admin(uid: int) -> bool:
    return uid in await admins_all()

async def ensure_user(uid: int, ref_by: int = None):
    async with aiosqlite.connect(DB_PATH) as con:
        cur = await con.execute("SELECT id FROM users WHERE id=?", (uid,))
        if not await cur.fetchone():
            await con.execute("INSERT INTO users(id, balance, ref_by) VALUES(?,?,?)",
                            (uid, 0, (ref_by if ref_by != uid else None)))
            await con.commit()

async def get_balance(uid: int) -> float:
    async with aiosqlite.connect(DB_PATH) as con:
        cur = await con.execute("SELECT balance FROM users WHERE id=?", (uid,))
        row = await cur.fetchone()
        return float(row[0]) if row else 0.0

async def add_stars(uid: int, amount: float):
    async with aiosqlite.connect(DB_PATH) as con:
        await con.execute("UPDATE users SET balance = balance + ? WHERE id=?", (amount, uid))
        await con.commit()

async def sub_stars(uid: int, amount: float) -> bool:
    bal = await get_balance(uid)
    if bal < amount:
        return False
    async with aiosqlite.connect(DB_PATH) as con:
        await con.execute("UPDATE users SET balance = balance - ? WHERE id=?", (amount, uid))
        await con.commit()
    return True

async def required_channels():
    async with aiosqlite.connect(DB_PATH) as con:
        cur = await con.execute("SELECT username FROM channels")
        return [r[0] for r in await cur.fetchall()]

async def check_all_memberships(uid: int) -> bool:
    chs = await required_channels()
    if not chs:
        return True
    for ch in chs:
        try:
            member = await bot.get_chat_member(ch, uid)
            if member.status in ("left", "kicked"):
                return False
        except Exception:
            return False
    return True

async def reward_after_join(uid: int):
    async with aiosqlite.connect(DB_PATH) as con:
        cur = await con.execute("SELECT ref_by, rewarded_ref FROM users WHERE id=?", (uid,))
        row = await cur.fetchone()
        if not row:
            return
        ref_by, rewarded = row
        if rewarded == 1:
            return
        if not await check_all_memberships(uid):
            return
        if ref_by:
            await con.execute("UPDATE users SET balance = balance + ?, invited_cnt = invited_cnt + 1 WHERE id=?",
                            (REF_BONUS, ref_by))
            await con.commit()
            try:
                await bot.send_message(ref_by, f"🎉 Referalyňyz ähli kanala goşuldy! Size +{fmt_stars(REF_BONUS)} berildi.")
            except Exception:
                pass
        await con.execute("UPDATE users SET rewarded_ref=1 WHERE id=?", (uid,))
        await con.commit()

# ======= MENU KEYBOARDS =======
def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ Ýyldyz Fermasy", callback_data="earn")],
        [InlineKeyboardButton(text="🤝 Referal Al", callback_data="referal")],
        [InlineKeyboardButton(text="👤 Profil", callback_data="profile")],
        [InlineKeyboardButton(text="🧩 Ýumuşlar", callback_data="tasks")],
        [InlineKeyboardButton(text="🚀 Buust", callback_data="boost")],
        [InlineKeyboardButton(text="💫 Çalşyrmak", callback_data="exchange")],
        [InlineKeyboardButton(text="📚 Gollanma | FAQ", callback_data="faq")],
        [InlineKeyboardButton(text="🎮 Mini Oýunlar", callback_data="games")],
        [InlineKeyboardButton(text="🏆 Top", callback_data="top")],
        [InlineKeyboardButton(text="💭 Teswirler", callback_data="reviews")]
    ])

def admin_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👑 Admin goş", callback_data="a_add")],
        [InlineKeyboardButton(text="🚫 Admin aýyr", callback_data="a_del")],
        [InlineKeyboardButton(text="🎟 Promokod goş", callback_data="p_add")],
        [InlineKeyboardButton(text="🎟 Promokod sanaw", callback_data="p_list")],
        [InlineKeyboardButton(text="🔁 Referal bonus", callback_data="set_ref")],
        [InlineKeyboardButton(text="📢 Kanal goş", callback_data="c_add")],
        [InlineKeyboardButton(text="🗑 Kanal aýyr", callback_data="c_del")],
        [InlineKeyboardButton(text="📃 Kanallar", callback_data="c_list")],
        [InlineKeyboardButton(text="🧩 Ýumuş goş", callback_data="t_add")],
        [InlineKeyboardButton(text="📃 Ýumuş sanaw", callback_data="t_list")],
        [InlineKeyboardButton(text="💳 Balans +/−", callback_data="b_edit")],
        [InlineKeyboardButton(text="💼 Çykarma sanaw", callback_data="w_list")],
        [InlineKeyboardButton(text="🖱 Kliker sazla", callback_data="click_set")],
        [InlineKeyboardButton(text="🔐 Seyf kody", callback_data="seyf_code")]
    ])

def back_menu(text="⬅️ Yzyna", cb="back_home"):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=text, callback_data=cb)]
    ])

# ======= COMMANDS =======
@dp.message(Command("start"))
async def start(message: Message):
    args = message.text.split(maxsplit=1)
    ref = None
    if len(args) == 2:
        try:
            p = int(args[1])
            if p != message.from_user.id:
                ref = p
        except:
            pass
    
    await ensure_user(message.from_user.id, ref)
    
    # Kanalları kontrol et
    if not await check_all_memberships(message.from_user.id):
        chs = await required_channels()
        kb = InlineKeyboardMarkup(inline_keyboard=[])
        for ch in chs:
            kb.inline_keyboard.append([InlineKeyboardButton(text=f"➕ Agza bol: {ch}", url=f"https://t.me/{ch.lstrip('@')}")])
        kb.inline_keyboard.append([InlineKeyboardButton(text="✅ Tassyklat", callback_data="verify_join")])
        
        await message.answer(
            "🔒 Ilki aşakdaky kanallara agza boluň, soňra «Tassyklat» basyň.",
            reply_markup=kb
        )
        return
    
    await message.answer(
        "✨ *Ýyldyz Fermer Botuna Hoş Geldiňiz!* ✨\n\n"
        "Ýyldyzlary ferma etmek, dostlary çagyrmak we göni oýunlar bilen "
        "ýyldyz gazanyň! Gazanan ýyldyzlaryňyzy sowgatlara çalşyryň we "
        "hakyky harytlara eýe boluň! 🌟",
        reply_markup=main_menu(),
        parse_mode="Markdown"
    )

@dp.message(Command("admin"))
async def admin_entry(message: Message):
    if not await is_admin(message.from_user.id):
        return
    await message.answer("🛠 Admin panel", reply_markup=admin_kb())

@dp.message(Command("help"))
async def help_cmd(message: Message):
    await message.answer("Komandalar: /start, /help, /admin (adminler üçin).")

# ======= CALLBACK HANDLERS =======
@dp.callback_query(lambda c: c.data == "verify_join")
async def verify_join(callback: CallbackQuery):
    if await check_all_memberships(callback.from_user.id):
        await reward_after_join(callback.from_user.id)
        await callback.message.edit_text("✅ Barlanyldy!", reply_markup=main_menu())
    else:
        await callback.answer("Ilki kanallara agza boluň!", show_alert=True)

@dp.callback_query(lambda c: c.data == "profile")
async def cb_profile(callback: CallbackQuery):
    bal = await get_balance(callback.from_user.id)
    async with aiosqlite.connect(DB_PATH) as con:
        cur = await con.execute("SELECT COALESCE(SUM(amount),0) FROM withdrawals WHERE user_id=? AND status='approved'", (callback.from_user.id,))
        wd_total = float((await cur.fetchone())[0])
        cur = await con.execute("SELECT invited_cnt FROM users WHERE id=?", (callback.from_user.id,))
        invited = (await cur.fetchone())[0]
        bot_user = await bot.get_me()
        ref_link = f"https://t.me/{bot_user.username}?start={callback.from_user.id}"
        text = (f"👤 *Profil* 👤\n\n"
                f"⭐ *Balans:* `{fmt_stars(bal)}`\n"
                f"💸 *Jemi Çykarylan:* `{fmt_stars(wd_total)}`\n"
                f"👥 *Çagyrylan Dostlar:* `{invited}`\n"
                f"🔗 *Referal Link:* {ref_link}")
        await callback.message.edit_text(text, reply_markup=back_menu(), parse_mode="Markdown")

@dp.callback_query(lambda c: c.data == "earn")
async def cb_earn(callback: CallbackQuery):
    bal = await get_balance(callback.from_user.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🖱 Kliker", callback_data="clicker")],
        [InlineKeyboardButton(text="🎉 Gündelik Bonus", callback_data="daily")],
        [InlineKeyboardButton(text="🎟 Promokod", callback_data="promo")],
        [InlineKeyboardButton(text="🔐 Seyf", callback_data="seyf")],
        [InlineKeyboardButton(text="⬅️ Yzyna", callback_data="back_home")]
    ])
    
    await callback.message.edit_text(
        f"⭐ *Ýyldyz Fermasy* ⭐\n\n"
        f"💰 *Siziň balansyňyz:* `{fmt_stars(bal)}`\n\n"
        "Aşakdaky usullar bilen ýyldyz gazanyň:",
        reply_markup=kb,
        parse_mode="Markdown"
    )

@dp.callback_query(lambda c: c.data == "referal")
async def cb_referal(callback: CallbackQuery):
    bot_user = await bot.get_me()
    ref_link = f"https://t.me/{bot_user.username}?start={callback.from_user.id}"
    text = (
        "🤝 *Referal Sistemi* 🤝\n\n"
        f"*Siziň referal linkiňiz:*\n`{ref_link}`\n\n"
        f"*Her bir dostuňyz üçin alarsyňyz:* +{fmt_stars(REF_BONUS)}\n\n"
        "⚠️ *Bellik:* Dostuňyz ähli kanallara goşulmaly we täze ulanyjy bolmaly!"
    )
    await callback.message.edit_text(text, reply_markup=back_menu(), parse_mode="Markdown")

@dp.callback_query(lambda c: c.data == "clicker")
async def cb_clicker(callback: CallbackQuery):
    async with aiosqlite.connect(DB_PATH) as con:
        cur = await con.execute("SELECT last_click FROM users WHERE id=?", (callback.from_user.id,))
        row = await cur.fetchone()
        last = row[0] if row else None
        now = dt.datetime.utcnow()
        if last:
            last_dt = dt.datetime.fromisoformat(last)
            left = last_dt + dt.timedelta(minutes=CLICK_COOLDOWN_MIN) - now
            if left.total_seconds() > 0:
                mins = int(left.total_seconds() // 60)
                secs = int(left.total_seconds() % 60)
                return await callback.answer(f"⌛ {mins}m {secs}s garaşyň.", show_alert=True)
    
    reward = float(await get_setting("click_reward", str(CLICK_REWARD_DEFAULT)))
    await add_stars(callback.from_user.id, reward)
    async with aiosqlite.connect(DB_PATH) as con:
        await con.execute("UPDATE users SET last_click=? WHERE id=?", (now.isoformat(), callback.from_user.id))
        await con.commit()
    
    bal = await get_balance(callback.from_user.id)
    await callback.message.edit_text(
        f"🖱 *Kliker* 🖱\n\n"
        f"✅ *Täze klik:* +{fmt_stars(reward)}\n"
        f"💰 *Jemi balans:* `{fmt_stars(bal)}`\n\n"
        f"⏰ *Soňky klikden:* 0s\n"
        f"🔄 *Indiki klik üçin:* {CLICK_COOLDOWN_MIN}min",
        reply_markup=back_menu("🔄 Klik et", "clicker"),
        parse_mode="Markdown"
    )

@dp.callback_query(lambda c: c.data == "daily")
async def cb_daily(callback: CallbackQuery):
    today = dt.date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as con:
        cur = await con.execute("SELECT last_daily FROM users WHERE id=?", (callback.from_user.id,))
        row = await cur.fetchone()
        last = row[0] if row else None
        if last == today:
            await callback.answer("Bugünkü bonusy eýýäm aldyňyz.", show_alert=True)
            return
        await con.execute("UPDATE users SET balance = balance + ?, last_daily=? WHERE id=?",
                        (DAILY_BONUS, today, callback.from_user.id))
        await con.commit()
    
    bal = await get_balance(callback.from_user.id)
    await callback.message.edit_text(
        f"🎉 *Gündelik Bonus* 🎉\n\n"
        f"✅ *Alyndy:* +{fmt_stars(DAILY_BONUS)}\n"
        f"💰 *Täze balans:* `{fmt_stars(bal)}`\n\n"
        "⏰ *Indiki bonus:* 24 sagatdan",
        reply_markup=back_menu(),
        parse_mode="Markdown"
    )

@dp.callback_query(lambda c: c.data == "promo")
async def cb_promo(callback: CallbackQuery, state: FSMContext):
    await state.set_state(PromoFSM.waiting)
    await callback.message.edit_text("🎟 Promokodyňyzy ýazyň:", reply_markup=back_menu())

@dp.message(PromoFSM.waiting)
async def promo_redeem(message: Message, state: FSMContext):
    code = message.text.strip().upper()
    async with aiosqlite.connect(DB_PATH) as con:
        cur = await con.execute("SELECT reward, remaining FROM promos WHERE code=?", (code,))
        row = await cur.fetchone()
        if not row:
            await message.reply("❌ Nädogry promokod.", reply_markup=main_menu())
            await state.clear()
            return
        reward, remaining = row
        if remaining <= 0:
            await message.reply("⛔ Bu promokodyň aktiwasiýasy gutardy.", reply_markup=main_menu())
            await state.clear()
            return
        await con.execute("UPDATE promos SET remaining=remaining-1 WHERE code=?", (code,))
        await con.commit()
        await add_stars(message.from_user.id, float(reward))
        
        bal = await get_balance(message.from_user.id)
        await message.reply(
            f"🎉 *Promokod Kabul Edildi!* 🎉\n\n"
            f"✅ *Alyndy:* +{fmt_stars(float(reward))}\n"
            f"💰 *Täze balans:* `{fmt_stars(bal)}`\n\n"
            f"🔄 *Galan aktiwasiýa:* {remaining-1}",
            reply_markup=main_menu(),
            parse_mode="Markdown"
        )
        await state.clear()

@dp.callback_query(lambda c: c.data == "tasks")
async def cb_tasks(callback: CallbackQuery):
    async with aiosqlite.connect(DB_PATH) as con:
        cur = await con.execute("SELECT id, title, url, reward FROM tasks WHERE type='join' ORDER BY id DESC")
        rows = await cur.fetchall()
        
        kb = InlineKeyboardMarkup(inline_keyboard=[])
        for tid, title, url, reward in rows:
            kb.inline_keyboard.append([InlineKeyboardButton(text=f"{title} (+{int(reward)}⭐)", url=url)])
        if rows:
            kb.inline_keyboard.append([InlineKeyboardButton(text="✅ Tassyklat", callback_data="task_verify")])
        kb.inline_keyboard.append([InlineKeyboardButton(text="⬅️ Yzyna", callback_data="back_home")])
        
        text = "🧩 *Ýumuşlar* 🧩\n\n"
        if rows:
            text += "Aşakdaky kanallara agza boluň we baýrak gazanyň:\n\n"
            for i, (tid, title, url, reward) in enumerate(rows, 1):
                text += f"{i}. {title} - *{int(reward)}⭐*\n"
        else:
            text += "Häzirlikde elýeterli ýumuşlar ýok 🫤"
        
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")

@dp.callback_query(lambda c: c.data == "task_verify")
async def cb_task_verify(callback: CallbackQuery):
    ok_req = await check_all_memberships(callback.from_user.id)
    reward_total = 0.0
    new_done = []
    async with aiosqlite.connect(DB_PATH) as con:
        cur = await con.execute("SELECT id, url, reward FROM tasks WHERE type='join'")
        rows = await cur.fetchall()
        cur = await con.execute("SELECT task_id FROM user_tasks WHERE user_id=?", (callback.from_user.id,))
        done_set = {r[0] for r in await cur.fetchall()}
        ok_tasks = True
        for tid, url, reward in rows:
            username = "@" + url.split("t.me/")[-1].split("/")[-1]
            try:
                member = await bot.get_chat_member(username, callback.from_user.id)
                if member.status in ("left", "kicked"):
                    ok_tasks = False
                else:
                    if tid not in done_set:
                        reward_total += float(reward)
                        new_done.append((tid, float(reward)))
            except Exception:
                ok_tasks = False
        
        if ok_req and ok_tasks:
            if reward_total > 0:
                await add_stars(callback.from_user.id, reward_total)
                await con.executemany("INSERT OR IGNORE INTO user_tasks(user_id, task_id) VALUES(?,?)",
                                    [(callback.from_user.id, tid) for tid, _ in new_done])
                await con.commit()
                await reward_after_join(callback.from_user.id)
            if reward_total == 0:
                await callback.answer("Bu ýumuşlary eýýäm ýerine ýetiripsiňiz. 👍", show_alert=True)
            else:
                await callback.answer(f"🎉 Ýumuşlar tassyklanyldy. +{fmt_stars(reward_total)}", show_alert=True)
        else:
            await callback.answer("Kanalara doly agza bolmadyk ýaly. Gaýtadan barlaň.", show_alert=True)

@dp.callback_query(lambda c: c.data == "exchange")
async def cb_exchange(callback: CallbackQuery, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for code, text, cost in GIFT_OPTIONS:
        kb.inline_keyboard.append([InlineKeyboardButton(text=text, callback_data=f"gift:{code}")])
    kb.inline_keyboard.append([InlineKeyboardButton(text="⬅️ Yzyna", callback_data="back_home")])
    
    bal = await get_balance(callback.from_user.id)
    await state.set_state(WithdrawFSM.choose)
    await callback.message.edit_text(
        f"💫 *Çalşyrmak* 💫\n\n"
        f"💰 *Balansyňyz:* `{fmt_stars(bal)}`\n\n"
        "Aşakdaky sowgatlardan birini saýlaň:",
        reply_markup=kb,
        parse_mode="Markdown"
    )

@dp.callback_query(lambda c: c.data.startswith("gift:"), WithdrawFSM.choose)
async def w_choose_gift(callback: CallbackQuery, state: FSMContext):
    code = callback.data.split(":")[1]
    found = next((opt for opt in GIFT_OPTIONS if opt[0] == code), None)
    if not found:
        return await callback.answer("Tapylmady.")
    _, label, cost = found
    bal = await get_balance(callback.from_user.id)
    if bal < cost:
        return await callback.answer(f"Balans ýeterlik däl. Gerek {int(cost)}⭐", show_alert=True)
    await state.update_data(gift_code=code, gift_label=label, amount=cost)
    await state.set_state(WithdrawFSM.contact)
    await callback.message.edit_text(
        f"🎁 *Saýlanan Sowgat:* {label}\n\n"
        "📨 *Habarlaşmak üçin kontakt/nik/ID ýazyň:*",
        reply_markup=back_menu(),
        parse_mode="Markdown"
    )

@dp.message(WithdrawFSM.contact)
async def w_contact(message: Message, state: FSMContext):
    data = await state.get_data()
    amt = float(data["amount"])
    ok = await sub_stars(message.from_user.id, amt)
    if not ok:
        await message.reply("Balans ýeterlik däl.", reply_markup=main_menu())
        await state.clear()
        return
    gift_label = data.get("gift_label", "—")
    gift_code = data.get("gift_code", "")
    async with aiosqlite.connect(DB_PATH) as con:
        await con.execute(
            "INSERT INTO withdrawals(user_id, amount, contact, status, created_at, gift) VALUES(?,?,?,?,?,?)",
            (message.from_user.id, amt, message.text.strip(), "pending", dt.datetime.utcnow().isoformat(), gift_code)
        )
        await con.commit()
        cur = await con.execute("SELECT last_insert_rowid()")
        wid = (await cur.fetchone())[0]
    
    username = message.from_user.username
    u_text = ("@" + username) if username else f"ID:{message.from_user.id}"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Tassyklat", callback_data=f"w_ok:{wid}")],
        [InlineKeyboardButton(text="❌ Ret et", callback_data=f"w_no:{wid}")]
    ])
    
    text = (f"🆕 Çykarma #<b>{wid}</b>\n"
            f"👤 Ulanyjy: <b>{u_text}</b>\n"
            f"🆔 ID: <code>{message.from_user.id}</code>\n"
            f"🎁 Sowgat: {gift_label}\n"
            f"💰 Möçber: {fmt_stars(amt)}\n"
            f"📨 Kontakt: {message.text.strip()}\n"
            f"⏱ Status: <b>PENDING</b>")
    
    if LOG_CHANNEL_ID:
        try:
            await bot.send_message(LOG_CHANNEL_ID, text, reply_markup=kb)
        except Exception:
            pass
    for aid in await admins_all():
        try:
            await bot.send_message(aid, text, reply_markup=kb)
        except Exception:
            pass
    await message.reply(f"🕐 Soragyňyz görkezildi (#{wid}). Admin tassyklamagyny garaşyň.", reply_markup=main_menu())
    await state.clear()

# ======= DIĞER CALLBACK'LER =======
@dp.callback_query(lambda c: c.data == "faq")
async def cb_faq(callback: CallbackQuery):
    text = (
        "📚 *Gollanma | FAQ* 📚\n\n"
        "❓ *Nädip ýyldyz gazanmaly?*\n"
        "- Kliker bilen her 10 minutda 0.1⭐\n"
        "- Dostlary çagyrmak bilen her biri üçin 4⭐\n"
        "- Gündelik bonus 1⭐\n"
        "- Ýumuşlar we promokodlar\n\n"
        "❓ *Nädip çalşyrmaly?*\n"
        "- Balansyňyz 15⭐ ýetenden soň sowgat saýlap bilersiňiz\n"
        "- Admin 24 sagat içinde tassyklar\n\n"
        "❓ *Başga soraglar?*\n"
        "- Adminler bilen habarlaşyň: @adminler"
    )
    await callback.message.edit_text(text, reply_markup=back_menu(), parse_mode="Markdown")

@dp.callback_query(lambda c: c.data == "games")
async def cb_games(callback: CallbackQuery):
    text = (
        "🎮 *Mini Oýunlar* 🎮\n\n"
        "🕹️ *1. San Tapyş Oýny* - 5⭐\n"
        "🎯 *2. Target Oýny* - 3⭐\n"
        "🎲 *3. Zarlar* - 2⭐\n\n"
        "⚠️ *Bellik:* Mini oýunlar häzirlikde elýeterli däl 🛠️"
    )
    await callback.message.edit_text(text, reply_markup=back_menu(), parse_mode="Markdown")

@dp.callback_query(lambda c: c.data == "boost")
async def cb_boost(callback: CallbackQuery):
    text = (
        "🚀 *Buustlar* 🚀\n\n"
        "Buustlar bilen ýyldyz gazanyş tizligiňizi artdyryň!\n\n"
        "🔸 *2x Buust* - 1 sagatlyk - 50⭐\n"
        "🔸 *3x Buust* - 30 minutlyk - 75⭐\n"
        "🔸 *5x Buust* - 15 minutlyk - 100⭐\n\n"
        "⚠️ *Bellik:* Buustlar häzirlikde elýeterli däl 🛠️"
    )
    await callback.message.edit_text(text, reply_markup=back_menu(), parse_mode="Markdown")

@dp.callback_query(lambda c: c.data == "top")
async def cb_top(callback: CallbackQuery):
    async with aiosqlite.connect(DB_PATH) as con:
        cur = await con.execute("SELECT id, balance FROM users ORDER BY balance DESC LIMIT 10")
        rows = await cur.fetchall()
    
    lines = []
    for i, (uid, bal) in enumerate(rows, start=1):
        try:
            user = await bot.get_chat(uid)
            name = user.first_name or user.username or f"ID:{uid}"
            if user.username:
                name = f"@{user.username}"
        except:
            name = f"ID:{uid}"
        lines.append(f"{i}. {name} - {fmt_stars(float(bal))}")
    
    text = "🏆 *TOP Ulanyjylar* 🏆\n\n" + ("\n".join(lines) if lines else "— ýok —")
    await callback.message.edit_text(text, reply_markup=back_menu(), parse_mode="Markdown")

@dp.callback_query(lambda c: c.data == "reviews")
async def cb_reviews(callback: CallbackQuery):
    text = (
        "💭 *Teswirler* 💭\n\n"
        "✨ *Aýlar:* 4.8/5\n"
        "👥 *Ulanyjylar:* 12.4K\n"
        "⭐ *Jemi ýyldyzlar:* 1.2M\n\n"
        "*Iň soňky teswirler:*\n"
        "✅ \"Ajaýyp bot, hakykatdanam işleýär!\"\n"
        "✅ \"1 hepdede 100⭐ topladym!\"\n"
        "✅ \"Adminler kömekçi we çalt!\"\n\n"
        "Öz teswiriňizi @adminler üsti bilen iberiň!"
    )
    await callback.message.edit_text(text, reply_markup=back_menu(), parse_mode="Markdown")

@dp.callback_query(lambda c: c.data == "back_earn")
async def back_earn(callback: CallbackQuery):
    await cb_earn(callback)

@dp.callback_query(lambda c: c.data == "back_home")
async def back_home(callback: CallbackQuery):
    await callback.message.edit_text(
        "✨ *Ýyldyz Fermer Botuna Hoş Geldiňiz!* ✨\n\n"
        "Ýyldyzlary ferma etmek, dostlary çagyrmak we göni oýunlar bilen "
        "ýyldyz gazanyň! Gazanan ýyldyzlaryňyzy sowgatlara çalşyryň we "
