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
ADMINS = {8359722718 ,8165658957}
REF_BONUS = 2.0
DAILY_BONUS = 1.0
CLICK_COOLDOWN_MIN = 10
CLICK_REWARD_DEFAULT = 0.1
LOG_CHANNEL_ID = 0  # Log kanalı kullanmak istemiyorsanız 0 yapın

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

class AdminAddFSM(StatesGroup):
    uid = State()

class AdminRemoveFSM(StatesGroup):
    uid = State()

# ======= BOT VE DİSPATCHER =======
bot = Bot(token=TOKEN)
dp = Dispatcher()

# ======= GIFT OPTIONS =======
GIFT_OPTIONS = {
    "bear": "🧸 Ayıcık",
    "heartbox": "💝 Kalpli Kutu",
    "gift25": "🎁 Hediye Kutusu",
    "rose": "🌹 Gül",
    "cake": "🎂 Pasta",
    "bouquet": "💐 Buket",
    "rocket": "🚀 Roket",
    "champ": "🍾 Şampanya",
    "cup": "🏆 Kupa",
    "ring": "💍 Yüzük",
    "gem": "💎 Elmas"
}

GIFT_PRICES = {
    "bear": 15,
    "heartbox": 15,
    "gift25": 25,
    "rose": 25,
    "cake": 50,
    "bouquet": 50,
    "rocket": 50,
    "champ": 50,
    "cup": 100,
    "ring": 100,
    "gem": 100
}

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

async def add_admin(uid: int):
    cur = set(await admins_all())
    cur.add(uid)
    with open("admins.json", "w") as f:
        json.dump(list(cur), f)

async def remove_admin(uid: int):
    cur = set(await admins_all())
    if uid in cur:
        cur.remove(uid)
        with open("admins.json", "w") as f:
            json.dump(list(cur), f)

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
    return []

async def check_all_memberships(uid: int) -> bool:
    return True

async def reward_after_join(uid: int):
    pass  # Artık kullanılmıyor

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
    
    # Kanal kontrolü tamamen kaldırıldı
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
        await message.answer("⛔ Bu komut sadece adminler içindir!")
        return
    await message.answer("🛠 Admin panel", reply_markup=admin_kb())

@dp.message(Command("help"))
async def help_cmd(message: Message):
    await message.answer("Komandalar: /start, /help, /admin (adminler üçin).")

# ======= CALLBACK HANDLERS =======
@dp.callback_query(lambda c: c.data == "profile")
async def cb_profile(callback: CallbackQuery):
    try:
        bal = await get_balance(callback.from_user.id)
        async with aiosqlite.connect(DB_PATH) as con:
            cur = await con.execute("SELECT COALESCE(SUM(amount),0) FROM withdrawals WHERE user_id=? AND status='approved'", (callback.from_user.id,))
            wd_total = float((await cur.fetchone())[0])
            cur = await con.execute("SELECT invited_cnt FROM users WHERE id=?", (callback.from_user.id,))
            invited_row = await cur.fetchone()
            invited = invited_row[0] if invited_row else 0
            bot_user = await bot.get_me()
            ref_link = f"https://t.me/{bot_user.username}?start={callback.from_user.id}"
            text = (f"👤 *Profil* 👤\n\n"
                    f"⭐ *Balans:* `{fmt_stars(bal)}`\n"
                    f"💸 *Jemi Çykarylan:* `{fmt_stars(wd_total)}`\n"
                    f"👥 *Çagyrylan Dostlar:* `{invited}`\n"
                    f"🔗 *Referal Link:* {ref_link}")
            await callback.message.edit_text(text, reply_markup=back_menu(), parse_mode="Markdown")
    except Exception as e:
        print(f"Profil hatası: {e}")
        await callback.message.edit_text(
            "❌ Profil yüklenirken bir hata oluştu. Lütfen daha sonra tekrar deneyin.",
            reply_markup=back_menu()
        )

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
    for code, name in GIFT_OPTIONS.items():
        price = GIFT_PRICES[code]
        kb.inline_keyboard.append([InlineKeyboardButton(text=f"{name} ({int(price)}⭐)", callback_data=f"gift:{code}")])
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
    if code not in GIFT_OPTIONS:
        return await callback.answer("Tapylmady.")
    
    label = GIFT_OPTIONS[code]
    cost = GIFT_PRICES[code]
    
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
            await bot.send_message(LOG_CHANNEL_ID, text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            pass
    
    for aid in await admins_all():
        try:
            await bot.send_message(aid, text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            pass
    
    await message.reply(f"🕐 Soragyňyz görkezildi (#{wid}). Admin tassyklamagyny garaşyň.", reply_markup=main_menu())
    await state.clear()

# ======= WITHDRAWAL APPROVAL (ADMIN) - DÜZELTİLDİ =======
@dp.callback_query(lambda c: c.data.startswith("w_ok:"))
async def approve_withdrawal(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("⛔ Bu işlemi yapmaya yetkiniz yok!", show_alert=True)
        return
    
    wid = int(callback.data.split(":")[1])
    admin_id = callback.from_user.id
    
    async with aiosqlite.connect(DB_PATH) as con:
        # Çekim bilgilerini al
        cur = await con.execute("SELECT user_id, amount, gift FROM withdrawals WHERE id=? AND status='pending'", (wid,))
        row = await cur.fetchone()
        
        if not row:
            await callback.answer("❌ Bu çekim zaten işleme alınmış veya bulunamadı!", show_alert=True)
            await callback.message.edit_text("❌ Bu çekim zaten işleme alınmış veya bulunamadı!")
            return
        
        user_id, amount, gift_code = row
        
        # Admin bakiyesini kontrol et
        admin_balance = await get_balance(admin_id)
        if admin_balance < amount:
            await callback.answer(f"❌ Admin bakiyesinde yeterli yıldız yok! Gerekli: {fmt_stars(amount)}", show_alert=True)
            return
        
        # Admin'den yıldızları düş
        ok = await sub_stars(admin_id, amount)
        if not ok:
            await callback.answer("❌ Admin bakiyesinden düşülemedi!", show_alert=True)
            return
        
        # Kullanıcıya yıldızları ekle
        await add_stars(user_id, amount)
        
        # Çekimi onayla
        await con.execute("UPDATE withdrawals SET status='approved' WHERE id=?", (wid,))
        await con.commit()
    
    # Kullanıcıya bildirim gönder
    try:
        gift_name = GIFT_OPTIONS.get(gift_code, "Hediye")
        await bot.send_message(
            user_id,
            f"🎉 *Tebrikler!* 🎉\n\n"
            f"✅ *{gift_name}* hediyeniz onaylandı!\n"
            f"💰 *{fmt_stars(amount)}* yıldız hesabınıza eklendi!\n"
            f"📦 Hediye en kısa sürede size iletilecektir.\n\n"
            f"💬 Sorularınız için admin ile iletişime geçin.",
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"Kullanıcıya mesaj gönderilemedi: {e}")
    
    # Admin'e bildirim
    await callback.message.edit_text(
        f"✅ #{wid} numaralı çekim **onaylandı**!\n"
        f"👤 Kullanıcıya {fmt_stars(amount)} yıldız gönderildi.\n"
        f"💫 Admin bakiyesinden {fmt_stars(amount)} düşüldü.",
        parse_mode="Markdown"
    )
    await callback.answer("✅ Çekim onaylandı ve yıldızlar gönderildi!")

@dp.callback_query(lambda c: c.data.startswith("w_no:"))
async def reject_withdrawal(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("⛔ Bu işlemi yapmaya yetkiniz yok!", show_alert=True)
        return
    
    wid = int(callback.data.split(":")[1])
    
    async with aiosqlite.connect(DB_PATH) as con:
        cur = await con.execute("SELECT user_id, amount FROM withdrawals WHERE id=? AND status='pending'", (wid,))
        row = await cur.fetchone()
        
        if not row:
            await callback.answer("❌ Bu çekim zaten işleme alınmış veya bulunamadı!", show_alert=True)
            await callback.message.edit_text("❌ Bu çekim zaten işleme alınmış veya bulunamadı!")
            return
        
        user_id, amount = row
        
        # Çekimi reddet
        await con.execute("UPDATE withdrawals SET status='rejected' WHERE id=?", (wid,))
        await con.commit()
    
    # Kullanıcıya bildirim gönder
    try:
        await bot.send_message(
            user_id,
            f"❌ *Üzgünüz!* ❌\n\n"
            f"⚠️ {fmt_stars(amount)} değerindeki hediye talebiniz **reddedildi**.\n"
            f"💫 Yıldızlarınız hesabınıza iade edilmedi (çünkü zaten çekilmemişti).\n\n"
            f"💬 Sebebini öğrenmek için admin ile iletişime geçin.",
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"Kullanıcıya mesaj gönderilemedi: {e}")
    
    await callback.message.edit_text(
        f"❌ #{wid} numaralı çekim **reddedildi**!",
        parse_mode="Markdown"
    )
    await callback.answer("❌ Çekim reddedildi!")

# ======= WITHDRAWAL LIST (ADMIN) =======
@dp.callback_query(lambda c: c.data == "w_list")
async def list_withdrawals(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return
    
    async with aiosqlite.connect(DB_PATH) as con:
        cur = await con.execute(
            "SELECT id, user_id, amount, contact, status, created_at, gift FROM withdrawals ORDER BY id DESC LIMIT 20"
        )
        rows = await cur.fetchall()
        
        if not rows:
            await callback.message.edit_text(
                "💼 *Çykarma sanaw* 💼\n\n"
                "📭 Henüz hiç çekim talebi yok.",
                reply_markup=admin_kb(),
                parse_mode="Markdown"
            )
            return
        
        text = "💼 *Çykarma sanaw* 💼\n\n"
        for wid, uid, amount, contact, status, created_at, gift in rows:
            status_emoji = "✅" if status == "approved" else "❌" if status == "rejected" else "⏳"
            gift_name = GIFT_OPTIONS.get(gift, "Bilinmeyen")
            text += f"#{wid} | {status_emoji} {status.upper()}\n"
            text += f"👤 ID: {uid} | 🎁 {gift_name}\n"
            text += f"💰 {fmt_stars(amount)} | 📨 {contact[:20]}\n"
            text += f"⏱ {created_at[:16]}\n\n"
        
        await callback.message.edit_text(
            text,
            reply_markup=admin_kb(),
            parse_mode="Markdown"
        )

@dp.callback_query(lambda c: c.data == "faq")
async def cb_faq(callback: CallbackQuery):
    text = (
        "📚 *Gollanma | FAQ* 📚\n\n"
        "❓ *Nädip ýyldyz gazanmaly?*\n"
        "- Kliker bilen her 10 minutda 0.1⭐\n"
        "- Dostlary çagyrmak bilen her biri üçin 2⭐\n"
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

@dp.callback_query(lambda c: c.data == "seyf")
async def cb_seyf(callback: CallbackQuery):
    async with aiosqlite.connect(DB_PATH) as con:
        cur = await con.execute("SELECT key, value FROM settings WHERE key LIKE 'seyf_%'")
        rows = await cur.fetchall()
        
        if not rows:
            await callback.message.edit_text(
                "🔐 *Seyf - dogry kody dogry tapyp, mugt ýyldyz al!* 🔐\n\n"
                "Häzirlikde elýeterli seyf kodlary ýok. 🫤\n"
                "Adminler täze kod goýançaky garaşyň...",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Yzyna", callback_data="back_earn")]
                ]),
                parse_mode="Markdown"
            )
            return
        
        codes_display = []
        for key, value in rows:
            code = key.replace("seyf_", "")
            stars = float(value)
            codes_display.append(f"`{code}` - {fmt_stars(stars)}")
        
        await callback.message.edit_text(
            "🔐 *Seyf - dogry kody dogry tapyp, mugt ýyldyz al!* 🔐\n\n"
            "Aşakdaky kodlary tapyň we ýazyň:\n" +
            "\n".join(codes_display) +
            "\n\nKody ýazmak üçin aşakdaky düwmä basyň:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔐 Kody girizmek", callback_data="enter_seyf_code")],
                [InlineKeyboardButton(text="⬅️ Yzyna", callback_data="back_earn")]
            ]),
            parse_mode="Markdown"
        )

@dp.callback_query(lambda c: c.data == "enter_seyf_code")
async def enter_seyf_code(callback: CallbackQuery, state: FSMContext):
    await state.set_state(SeyfFSM.waiting)
    await callback.message.edit_text(
        "🔐 Seyf koduny ýazyň:",
        reply_markup=back_menu("⬅️ Yzyna", "seyf")
    )

@dp.message(SeyfFSM.waiting)
async def seyf_redeem(message: Message, state: FSMContext):
    code = message.text.strip().upper()
    
    async with aiosqlite.connect(DB_PATH) as con:
        cur = await con.execute("SELECT value FROM settings WHERE key=?", (f"seyf_{code}",))
        row = await cur.fetchone()
        
        if not row:
            await message.reply("❌ Nädogry seyf kody.", reply_markup=main_menu())
            await state.clear()
            return
        
        reward = float(row[0])
        await add_stars(message.from_user.id, reward)
        await con.execute("DELETE FROM settings WHERE key=?", (f"seyf_{code}",))
        await con.commit()
    
    bal = await get_balance(message.from_user.id)
    await message.reply(
        f"🎉 *Seyf Kody Kabul Edildi!* 🎉\n\n"
        f"✅ *Alyndy:* +{fmt_stars(reward)}\n"
        f"💰 *Täze balans:* `{fmt_stars(bal)}`",
        reply_markup=main_menu(),
        parse_mode="Markdown"
    )
    await state.clear()

@dp.callback_query(lambda c: c.data == "back_earn")
async def back_earn(callback: CallbackQuery):
    await cb_earn(callback)

@dp.callback_query(lambda c: c.data == "back_home")
async def back_home(callback: CallbackQuery):
    await callback.message.edit_text(
        "✨ *Ýyldyz Fermer Botuna Hoş Geldiňiz!* ✨\n\n"
        "Ýyldyzlary ferma etmek, dostlary çagyrmak we göni oýunlar bilen "
        "ýyldyz gazanyň! Gazanan ýyldyzlaryňyzy sowgatlara çalşyryň we "
        "hakyky harytlara eýe boluň! 🌟",
        reply_markup=main_menu(),
        parse_mode="Markdown"
    )

# ======= ADMIN CALLBACKS =======
@dp.callback_query(lambda c: c.data == "a_add")
async def a_add_admin(callback: CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        return
    await state.set_state(AdminAddFSM.uid)
    await callback.message.edit_text("👑 Admin olarak eklemek istediğiniz kullanıcının ID'sini girin:", reply_markup=admin_kb())

@dp.message(AdminAddFSM.uid)
async def a_add_admin_val(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return
    try:
        uid = int(message.text.strip())
    except Exception:
        return await message.reply("❌ Geçersiz ID! Lütfen sayı girin.")
    
    await add_admin(uid)
    await message.reply(f"✅ {uid} ID'li kullanıcı admin olarak eklendi!", reply_markup=admin_kb())
    await state.clear()

@dp.callback_query(lambda c: c.data == "a_del")
async def a_del_admin(callback: CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        return
    await state.set_state(AdminRemoveFSM.uid)
    await callback.message.edit_text("🚫 Admin olarak çıkarmak istediğiniz kullanıcının ID'sini girin:", reply_markup=admin_kb())

@dp.message(AdminRemoveFSM.uid)
async def a_del_admin_val(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return
    try:
        uid = int(message.text.strip())
    except Exception:
        return await message.reply("❌ Geçersiz ID! Lütfen sayı girin.")
    
    if uid == 7279061074:
        return await message.reply("❌ Ana admin çıkarılamaz!")
    
    await remove_admin(uid)
    await message.reply(f"✅ {uid} ID'li kullanıcı admin olarak çıkarıldı!", reply_markup=admin_kb())
    await state.clear()

@dp.callback_query(lambda c: c.data == "seyf_code")
async def a_seyf_code(callback: CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        return
    await state.set_state(SeyfFSM.waiting)
    await callback.message.edit_text(
        "🔐 Seyf kody giriziň format: `KOD STAR`\nMysal: `SEYF123 50`",
        reply_markup=admin_kb(),
        parse_mode="Markdown"
    )

@dp.message(SeyfFSM.waiting)
async def a_seyf_create(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return
    parts = message.text.strip().split()
    if len(parts) < 2:
        await message.reply("Formato laýyk däl. Mysal: `SEYF123 50`", parse_mode="Markdown")
        return
    
    code = parts[0].upper()
    reward = float(parts[1])
    
    async with aiosqlite.connect(DB_PATH) as con:
        await con.execute(
            "INSERT OR REPLACE INTO settings(key, value) VALUES(?,?)",
            (f"seyf_{code}", str(reward))
        )
        await con.commit()
    
    await message.reply(f"✅ Seyf kody döredildi: `{code}` → {fmt_stars(reward)}", reply_markup=admin_kb(), parse_mode="Markdown")
    await state.clear()

@dp.callback_query(lambda c: c.data == "p_add")
async def a_promo_add(callback: CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        return
    await state.set_state(PromoFSM.create)
    await callback.message.edit_text(
        "🎟 Promokod giriziň format: `KOD STAR AKTIVASIÝA`\nMysal: `NEW2025 5 100`",
        reply_markup=admin_kb(),
        parse_mode="Markdown"
    )

@dp.message(PromoFSM.create)
async def a_promo_create(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return
    parts = message.text.strip().split()
    if len(parts) != 3:
        await message.reply("Formato laýyk däl. Mysal: `NEW2025 5 100`", parse_mode="Markdown")
        return
    
    code = parts[0].upper()
    reward = float(parts[1])
    remaining = int(parts[2])
    
    async with aiosqlite.connect(DB_PATH) as con:
        await con.execute(
            "INSERT OR REPLACE INTO promos(code, reward, remaining, created_by, created_at) VALUES(?,?,?,?,?)",
            (code, reward, remaining, message.from_user.id, dt.datetime.utcnow().isoformat())
        )
        await con.commit()
    
    await message.reply(f"✅ Promokod döredildi: `{code}` → {fmt_stars(reward)}, aktiwasiýa: {remaining}", reply_markup=admin_kb(), parse_mode="Markdown")
    await state.clear()

@dp.callback_query(lambda c: c.data == "p_list")
async def a_promo_list(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return
    async with aiosqlite.connect(DB_PATH) as con:
        cur = await con.execute("SELECT code, reward, remaining FROM promos ORDER BY created_at DESC")
        rows = await cur.fetchall()
        text = "🎟 *Promokodlar* 🎟\n" + ("\n".join([f"`{c}`: {fmt_stars(float(r))}, galan: {rem}" for c, r, rem in rows]) if rows else "— ýok —")
        await callback.message.edit_text(text, reply_markup=admin_kb(), parse_mode="Markdown")

@dp.callback_query(lambda c: c.data == "set_ref")
async def a_set_ref(callback: CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        return
    await state.set_state(SetRefFSM.waiting)
    await callback.message.edit_text(f"Häzirki referal bonus: {fmt_stars(REF_BONUS)}\nTäze bahany ýazyň (san):", reply_markup=admin_kb())

@dp.message(SetRefFSM.waiting)
async def a_set_ref_val(message: Message, state: FSMContext):
    global REF_BONUS
    if not await is_admin(message.from_user.id):
        return
    try:
        REF_BONUS = float(message.text.replace(",", "."))
    except Exception:
        return await message.reply("San giriziň.")
    await message.reply(f"✅ Täze referal bonus: {fmt_stars(REF_BONUS)}", reply_markup=admin_kb())
    await state.clear()

@dp.callback_query(lambda c: c.data == "c_add")
async def a_c_add(callback: CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        return
    await state.set_state(AddChannelFSM.waiting)
    await callback.message.edit_text("Kanal username giriziň, mysal: `@kanal`", reply_markup=admin_kb(), parse_mode="Markdown")

@dp.message(AddChannelFSM.waiting)
async def a_c_add_val(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return
    username = message.text.strip()
    if not username.startswith("@"):
        return await message.reply("Başynda @ bolmaly.")
    async with aiosqlite.connect(DB_PATH) as con:
        await con.execute("INSERT OR IGNORE INTO channels(username) VALUES(?)", (username,))
        await con.commit()
    await message.reply(f"✅ Kanal goşuldy: {username}", reply_markup=admin_kb())
    await state.clear()

@dp.callback_query(lambda c: c.data == "c_del")
async def a_c_del(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return
    chs = await required_channels()
    if not chs:
        return await callback.answer("Kanal ýok.")
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for ch in chs:
        kb.inline_keyboard.append([InlineKeyboardButton(text=f"❌ {ch}", callback_data=f"c_del:{ch}")])
    await callback.message.edit_text("Aýyrjak kanaly saýlaň:", reply_markup=kb)

@dp.callback_query(lambda c: c.data.startswith("c_del:"))
async def a_c_del_do(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return
    ch = callback.data.split(":")[1]
    async with aiosqlite.connect(DB_PATH) as con:
        await con.execute("DELETE FROM channels WHERE username=?", (ch,))
        await con.commit()
    await callback.answer("Pozuldy.")
    await callback.message.edit_reply_markup(reply_markup=admin_kb())

@dp.callback_query(lambda c: c.data == "c_list")
async def a_c_list(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return
    chs = await required_channels()
    txt = "📢 *Mejbury kanallar* 📢\n" + ("\n".join(chs) if chs else "— ýok —")
    await callback.message.edit_text(txt, reply_markup=admin_kb(), parse_mode="Markdown")

@dp.callback_query(lambda c: c.data == "t_add")
async def a_t_add(callback: CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        return
    await state.set_state(AddTaskFSM.title)
    await callback.message.edit_text("Ýumuş adyny ýazyň:", reply_markup=admin_kb())

@dp.message(AddTaskFSM.title)
async def a_t_title(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return
    await state.update_data(title=message.text.strip())
    await state.set_state(AddTaskFSM.url)
    await message.reply("Ýumuş URL (kanal linki) giriziň, mysal: https://t.me/kanal")

@dp.message(AddTaskFSM.url)
async def a_t_url(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return
    await state.update_data(url=message.text.strip())
    await state.set_state(AddTaskFSM.reward)
    await message.reply("Bu ýumuş üçin ⭐ möçberi (san) giriziň:")

@dp.message(AddTaskFSM.reward)
async def a_t_reward(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return
    try:
        reward = float(message.text.replace(",", "."))
    except Exception:
        return await message.reply("San giriziň.")
    data = await state.get_data()
    async with aiosqlite.connect(DB_PATH) as con:
        await con.execute("INSERT INTO tasks(title, url, reward, type) VALUES(?,?,?,?)",
                        (data["title"], data["url"], reward, "join"))
        await con.commit()
    await message.reply("✅ Ýumuş goşuldy.", reply_markup=admin_kb())
    await state.clear()

@dp.callback_query(lambda c: c.data == "t_list")
async def a_t_list(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return
    async with aiosqlite.connect(DB_PATH) as con:
        cur = await con.execute("SELECT id, title, reward FROM tasks ORDER BY id DESC")
        rows = await cur.fetchall()
        if not rows:
            return await callback.answer("Ýumuş ýok.")
        kb = InlineKeyboardMarkup(inline_keyboard=[])
        lines = []
        for i, (tid, title, reward) in enumerate(rows, start=1):
            lines.append(f"{i}) {title} – {int(reward)}⭐ (#{tid})")
            kb.inline_keyboard.append([InlineKeyboardButton(text=f"🗑 #{tid}", callback_data=f"t_del:{tid}")])
        await callback.message.edit_text("🧩 *Ýumuşlar:*\n" + "\n".join(lines), reply_markup=kb, parse_mode="Markdown")

@dp.callback_query(lambda c: c.data.startswith("t_del:"))
async def a_t_del(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return
    tid = int(callback.data.split(":")[1])
    async with aiosqlite.connect(DB_PATH) as con:
        await con.execute("DELETE FROM tasks WHERE id=?", (tid,))
        await con.commit()
    await callback.answer("Pozuldy.")
    await callback.message.edit_reply_markup(reply_markup=admin_kb())

# ======= BALANCE EDIT (ADMIN) - DÜZELTİLDİ =======
@dp.callback_query(lambda c: c.data == "b_edit")
async def a_b_edit(callback: CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        return
    await state.set_state(BalanceFSM.uid)
    await callback.message.edit_text(
        "💳 *Balans düzetmek*\n\n"
        "Ulanyjy ID giriziň:",
        reply_markup=admin_kb(),
        parse_mode="Markdown"
    )

@dp.message(BalanceFSM.uid)
async def a_b_uid(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return
    try:
        uid = int(message.text.strip())
    except Exception:
        await message.reply("❌ Nädogry ID! San giriziň.")
        return
    
    await state.update_data(uid=uid)
    await state.set_state(BalanceFSM.action)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Balans goş", callback_data="b_act:add")],
        [InlineKeyboardButton(text="➖ Balans aýyr", callback_data="b_act:sub")]
    ])
    await message.reply(
        f"👤 *Ulanyjy:* `{uid}`\n"
        "Haýsy amaly ýerine ýetirmeli?",
        reply_markup=kb,
        parse_mode="Markdown"
    )

@dp.callback_query(lambda c: c.data.startswith("b_act:"), BalanceFSM.action)
async def a_b_action(callback: CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        return
    act = callback.data.split(":")[1]
    await state.update_data(action=act)
    await state.set_state(BalanceFSM.amount)
    await callback.message.edit_text(
        "✏️ *Möçberi giriziň:* (san)\n"
        "Mysal: `10` ýa-da `0.5`",
        reply_markup=admin_kb(),
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.message(BalanceFSM.amount)
async def a_b_amount(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return
    try:
        amt = float(message.text.replace(",", "."))
    except Exception:
        await message.reply("❌ Nädogry möçber! San giriziň.")
        return
    
    data = await state.get_data()
    uid = int(data["uid"])
    
    if data["action"] == "add":
        await add_stars(uid, amt)
        await message.reply(f"✅ {uid} ID-li ulanyja **+{fmt_stars(amt)}** goşuldy!", reply_markup=admin_kb(), parse_mode="Markdown")
    else:
        ok = await sub_stars(uid, amt)
        if not ok:
            await message.reply(f"❌ {uid} ID-li ulanyjynyň balansynda *{fmt_stars(amt)}* ýok!", parse_mode="Markdown")
        else:
            await message.reply(f"✅ {uid} ID-li ulanyjydan **-{fmt_stars(amt)}** aýryldy!", reply_markup=admin_kb(), parse_mode="Markdown")
    
    await state.clear()

@dp.callback_query(lambda c: c.data == "click_set")
async def click_set(callback: CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        return
    cur = await get_setting("click_reward", str(CLICK_REWARD_DEFAULT))
    await state.set_state(ClickSetFSM.reward)
    await callback.message.edit_text(
        f"🖱 Häzirki kliker baýragy: {fmt_stars(float(cur))} / {CLICK_COOLDOWN_MIN}m\n"
        "Täze bahany ýazyň (mysal: 0.2):",
        reply_markup=admin_kb()
    )

@dp.message(ClickSetFSM.reward)
async def click_set_val(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return
    try:
        val = float(message.text.replace(",", "."))
        if val < 0:
            raise ValueError()
    except Exception:
        return await message.reply("Pozitif sany giriziň (mysal: 0.2).")
    await set_setting("click_reward", str(val))
    await message.reply(f"✅ Täze kliker baýragy goýuldy: {fmt_stars(val)} / {CLICK_COOLDOWN_MIN}m", reply_markup=admin_kb())
    await state.clear()

# ======= STARTUP =======
async def set_commands():
    cmds = [
        BotCommand(command="start", description="Başla"),
        BotCommand(command="help", description="Kömek"),
        BotCommand(command="admin", description="Admin panel")
    ]
    await bot.set_my_commands(cmds)

async def main():
    await init_db()
    await set_commands()
    print("🤖 Bot started successfully!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("🛑 Bot stopped.")
