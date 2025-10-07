# Bot tokeniňizi şu ýere goýuň
TOKEN = "8421128459:AAHr3bwBziXiUCuwbbm223dI-f2jEaL-dOk"

from telebot import TeleBot
from typing import List
from typing import Tuple
from typing import Optional
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton


bot = TeleBot(8421128459:AAHr3bwBziXiUCuwbbm223dI-f2jEaL-dOk)

# Admin ID-leri: sanlaryň toplumydyr
ADMINS = {7896190704}

# Konfigurasiýa
REF_BONUS = 2.0                # referal bonusy (⭐)
DAILY_BONUS = 1.0              # gündelik bonus (⭐)
CLICK_COOLDOWN_MIN = 10        # kliker wagty (minut)
CLICK_REWARD_DEFAULT = 0.1     # 1 klikde berilýän ⭐ başlangyç
LOG_CHANNEL_ID = 2672668104    # isleseňiz: -100xxxxxxxxxxxx

DB_PATH = "stars.db"

# -------------------- GIFTS --------------------

# (code, text, cost)
GIFT_OPTIONS: List[Tuple[str, str, float]] = [
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

# -------------------- HELPERS --------------------

def fmt_stars(x: float) -> str:
    return f"{int(x) if float(x).is_integer() else x} ⭐"

async def init_db():
    async with aiosqlite.connect(DB_PATH) as con:
        # main tables
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
        # users x tasks: one-time completion
        await con.execute("""CREATE TABLE IF NOT EXISTS user_tasks(
            user_id INTEGER,
            task_id INTEGER,
            PRIMARY KEY (user_id, task_id)
        )""")
        # settings
        await con.execute("""CREATE TABLE IF NOT EXISTS settings(
            key TEXT PRIMARY KEY,
            value TEXT
        )""")
        await con.commit()

        # migrate columns where older schema exists
        # add gift column to withdrawals if missing    
        cur = await con.execute("PRAGMA table_info(withdrawals)")    
        cols = [r[1] for r in await cur.fetchall()]    
        if "gift" not in cols:    
            await con.execute("ALTER TABLE withdrawals ADD COLUMN gift TEXT")    
        # add last_click to users if missing    
        cur = await con.execute("PRAGMA table_info(users)")    
        cols = [r[1] for r in await cur.fetchall()]    
        if "last_click" not in cols:    
            await con.execute("ALTER TABLE users ADD COLUMN last_click TEXT")    
        await con.commit()    

        # init click reward setting if not exists    
        await con.execute(    
            "INSERT OR IGNORE INTO settings(key, value) VALUES('click_reward', ?)",    
            (str(CLICK_REWARD_DEFAULT),)    
        )    
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

async def admins_all() -> List[int]:
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

async def ensure_user(uid: int, ref_by: Optional[int] = None) -> None:
    async with aiosqlite.connect(DB_PATH) as con:
        cur = await con.execute("SELECT id FROM users WHERE id=?", (uid,))
        row = await cur.fetchone()
        if not row:
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

async def required_channels() -> List[str]:
    async with aiosqlite.connect(DB_PATH) as con:
        cur = await con.execute("SELECT username FROM channels")
        rows = await cur.fetchall()
        return [r[0] for r in rows]

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
    """
    Ähli mejbury kanallara goşulany barlanylanda diňe BIR GEZEK:
    - referere REF_BONUS berilýär
    - refereriň invited_cnt artýar
    - ulanyjynyň rewarded_ref=1 bolýar
    """
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

def main_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="⭐ Ýyldyz Fermasy", callback_data="earn")
    kb.button(text="🤝 Referal Al", callback_data="referal")
    kb.button(text="👤 Profil", callback_data="profile")
    kb.button(text="🧩 Ýumuşlar", callback_data="tasks")
    kb.button(text="🚀 Buust", callback_data="boost")
    kb.button(text="💫 Çalşyrmak", callback_data="exchange")
    kb.button(text="📚 Gollanma | FAQ", callback_data="faq")
    kb.button(text="🎮 Mini Oýunlar", callback_data="games")
    kb.button(text="🏆 Top", callback_data="top")
    kb.button(text="💭 Teswirler", callback_data="reviews")
    kb.adjust(2, 2, 2, 2, 2)
    return kb.as_markup()

def back_menu(text="⬅️ Yzyna", cb="back_home") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=text, callback_data=cb)]])

def admin_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="👑 Admin goş", callback_data="a_add")
    kb.button(text="🚫 Admin aýyr", callback_data="a_del")
    kb.button(text="🎟 Promokod goş", callback_data="p_add")
    kb.button(text="🎟 Promokod sanaw", callback_data="p_list")
    kb.button(text="🔁 Referal bonus", callback_data="set_ref")
    kb.button(text="📢 Kanal goş", callback_data="c_add")
    kb.button(text="🗑 Kanal aýyr", callback_data="c_del")
    kb.button(text="📃 Kanallar", callback_data="c_list")
    kb.button(text="🧩 Ýumuş goš", callback_data="t_add")
    kb.button(text="📃 Ýumuş sanaw", callback_data="t_list")
    kb.button(text="💳 Balans +/−", callback_data="b_edit")
    kb.button(text="💼 Çykarma sanaw", callback_data="w_list")
    kb.button(text="🖱 Kliker sazla", callback_data="click_set")
    kb.button(text="🔐 Seyf kody", callback_data="seyf_code")
    kb.adjust(2, 2, 2, 2, 2, 2, 2)
    return kb.as_markup()



# -------------------- COMMANDS --------------------

@bot.message_handler(commands=['start'])
def start(message):
    # Parse deep-link payload (ref)
    payload = message.text.split(maxsplit=1)
    ref = None
    if len(payload) == 2:
        try:
            p = int(payload[1])
            if p != message.from_user.id:
                ref = p
        except Exception:
            ref = None

    # ensure_user asynchronous däl, şonuň üçin await ýok
    ensure_user(message.from_user.id, ref)

def ensure_user(user_id, ref=None):
    # Ulanyjyny bazada saklamak üçin ýeri
    print(f"Ulanyjy ID: {user_id}, referal: {ref}")

bot.polling()

    # Gate: require channels
    # Siziň kanallary barlaýýan funksiýaňyz
def check_all_memberships(user_id):
    # Mysal üçin, diňe 12345 ID bar
    allowed_users = [12345]
    return user_id in allowed_users

def required_channels():
    # Agza bolmaly kanallar
    return ["example_channel1", "example_channel2"]

@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id

    if not check_all_memberships(user_id):
        chs = required_channels()
        
        # Inline keyboard düzmek
        kb = types.InlineKeyboardMarkup()
        for ch in chs:
            kb.add(types.InlineKeyboardButton(text=f"➕ Agza bol: {ch}", url=f"https://t.me/{ch.lstrip('@')}"))
        kb.add(types.InlineKeyboardButton(text="✅ Tassyklat", callback_data="verify_join"))
        
        bot.send_message(
            message.chat.id,
            "🔒 Ilki aşakdaky kanallara agza boluň, soňra «Tassyklat» basyň.",
            reply_markup=kb
        )
        return

    bot.send_message(message.chat.id, "✅ Siz ähli kanallara agza bolduňyz!")

# Callback handler
@bot.callback_query_handler(func=lambda call: call.data == "verify_join")
def verify_join(call):
    bot.answer_callback_query(call.id, "Tassyklama alyndy!")
    user_id = call.from_user.id
    if check_all_memberships(user_id):
        bot.send_message(call.message.chat.id, "Siz ähli kanallara agza bolduňyz!")

     
        "✨ *Ýyldyz Fermer Botuna Hoş Geldiňiz!* ✨\n\n"
        "Ýyldyzlary ferma etmek, dostlary çagyrmak we göni oýunlar bilen "
        "ýyldyz gazanyň! Gazanan ýyldyzlaryňyzy sowgatlara çalşyryň we "
        "hakyky harytlara eýe boluň! 🌟",
        reply_markup=main_menu(),
        parse_mode=ParseMode.MARKDOWN

@dp.callback_query(F.data == "verify_join")
async def verify_join(cb: CallbackQuery):
    if await check_all_memberships(cb.from_user.id):
        await reward_after_join(cb.from_user.id)
        await cb.message.edit_text("✅ Barlanyldy!", reply_markup=main_menu())
    else:
        await cb.answer("Ilki kanallara agza boluň!", show_alert=True)

@dp.message(Command("admin"))
async def admin_entry(m: Message):
    if not await is_admin(m.from_user.id):
        return
    await m.answer("🛠 Admin panel", reply_markup=admin_kb())

@dp.message(Command("help"))
async def help_cmd(m: Message):
    await m.answer("Komandalar: /start, /help, /admin (adminler üçin).")

# -------------------- USER FLOWS --------------------

@dp.callback_query(F.data == "profile")
async def cb_profile(cb: CallbackQuery):
    bal = await get_balance(cb.from_user.id)

    # approved withdrawals total
    async with aiosqlite.connect(DB_PATH) as con:
        cur = await con.execute("SELECT COALESCE(SUM(amount),0) FROM withdrawals WHERE user_id=? AND status='approved'", (cb.from_user.id,))
        wd_total = float((await cur.fetchone())[0])
        cur = await con.execute("SELECT invited_cnt FROM users WHERE id=?", (cb.from_user.id,))
        invited = (await cur.fetchone())[0]
        ref_link = f"https://t.me/{(await bot.me()).username}?start={cb.from_user.id}"
        text = (f"👤 *Profil* 👤\n\n"
                f"⭐ *Balans:* `{fmt_stars(bal)}`\n"
                f"💸 *Jemi Çykarylan:* `{fmt_stars(wd_total)}`\n"
                f"👥 *Çagyrylan Dostlar:* `{invited}`\n"
                f"🔗 *Referal Link:* {ref_link}")
        await cb.message.edit_text(text, reply_markup=back_menu(), parse_mode=ParseMode.MARKDOWN)

@dp.callback_query(F.data == "earn")
async def cb_earn(cb: CallbackQuery):
    b = InlineKeyboardBuilder()
    b.button(text="🖱 Kliker", callback_data="clicker")
    b.button(text="🎉 Gündelik Bonus", callback_data="daily")
    b.button(text="🎟 Promokod", callback_data="promo")
    b.button(text="🔐 Seyf", callback_data="seyf")
    b.button(text="⬅️ Yzyna", callback_data="back_home")
    b.adjust(2, 2, 1)
    
    bal = await get_balance(cb.from_user.id)
    await cb.message.edit_text(
        f"⭐ *Ýyldyz Fermasy* ⭐\n\n"
        f"💰 *Siziň balansyňyz:* `{fmt_stars(bal)}`\n\n"
        "Aşakdaky usullar bilen ýyldyz gazanyň:",
        reply_markup=b.as_markup(),
        parse_mode=ParseMode.MARKDOWN
    )

@dp.callback_query(F.data == "referal")
async def cb_referal(cb: CallbackQuery):
    ref_link = f"https://t.me/{(await bot.me()).username}?start={cb.from_user.id}"
    text = (
        "🤝 *Referal Sistemi* 🤝\n\n"
        f"*Siziň referal linkiňiz:*\n`{ref_link}`\n\n"
        f"*Her bir dostuňyz üçin alarsyňyz:* +{fmt_stars(REF_BONUS)}\n\n"
        "⚠️ *Bellik:* Dostuňyz ähli kanallara goşulmaly we täze ulanyjy bolmaly!"
    )
    await cb.message.edit_text(text, reply_markup=back_menu(), parse_mode=ParseMode.MARKDOWN)

@dp.callback_query(F.data == "clicker")
async def cb_clicker(cb: CallbackQuery):
    # check cooldown
    async with aiosqlite.connect(DB_PATH) as con:
        cur = await con.execute("SELECT last_click FROM users WHERE id=?", (cb.from_user.id,))
        row = await cur.fetchone()
        last = row[0] if row else None
        now = dt.datetime.utcnow()
        if last:
            last_dt = dt.datetime.fromisoformat(last)
            left = last_dt + dt.timedelta(minutes=CLICK_COOLDOWN_MIN) - now
            if left.total_seconds() > 0:
                mins = int(left.total_seconds() // 60)
                secs = int(left.total_seconds() % 60)
                return await cb.answer(f"⌛ {mins}m {secs}s garaşyň.", show_alert=True)

    # reward
    reward = float(await get_setting("click_reward", str(CLICK_REWARD_DEFAULT)))
    await add_stars(cb.from_user.id, reward)
    async with aiosqlite.connect(DB_PATH) as con:
        await con.execute("UPDATE users SET last_click=? WHERE id=?", (now.isoformat(), cb.from_user.id))
        await con.commit()
    
    bal = await get_balance(cb.from_user.id)
    await cb.message.edit_text(
        f"🖱 *Kliker* 🖱\n\n"
        f"✅ *Täze klik:* +{fmt_stars(reward)}\n"
        f"💰 *Jemi balans:* `{fmt_stars(bal)}`\n\n"
        f"⏰ *Soňky klikden:* 0s\n"
        f"🔄 *Indiki klik üçin:* {CLICK_COOLDOWN_MIN}min",
        reply_markup=back_menu("🔄 Klik et", "clicker"),
        parse_mode=ParseMode.MARKDOWN
    )

@dp.callback_query(F.data == "tasks")
async def cb_tasks(cb: CallbackQuery):
    async with aiosqlite.connect(DB_PATH) as con:
        cur = await con.execute("SELECT id, title, url, reward FROM tasks WHERE type='join' ORDER BY id DESC")
        rows = await cur.fetchall()
        kb = InlineKeyboardBuilder()
        for tid, title, url, reward in rows:
            kb.button(text=f"{title} (+{int(reward)}⭐)", url=url)
        if rows:
            kb.button(text="✅ Tassyklat", callback_data="task_verify")
        kb.button(text="⬅️ Yzyna", callback_data="back_home")
        kb.adjust(1)
        
        text = "🧩 *Ýumuşlar* 🧩\n\n"
        if rows:
            text += "Aşakdaky kanallara agza boluň we baýrak gazanyň:\n\n"
            for i, (tid, title, url, reward) in enumerate(rows, 1):
                text += f"{i}. {title} - *{int(reward)}⭐*\n"
        else:
            text += "Häzirlikde elýeterli ýumuşlar ýok 🫤"
            
        await cb.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode=ParseMode.MARKDOWN)

@dp.callback_query(F.data == "task_verify")
async def cb_task_verify(cb: CallbackQuery):
    ok_req = await check_all_memberships(cb.from_user.id)
    reward_total = 0.0
    new_done = []  # (task_id, reward)
    async with aiosqlite.connect(DB_PATH) as con:
        cur = await con.execute("SELECT id, url, reward FROM tasks WHERE type='join'")
        rows = await cur.fetchall()

        # already done set
        cur = await con.execute("SELECT task_id FROM user_tasks WHERE user_id=?", (cb.from_user.id,))
        done_set = {r[0] for r in await cur.fetchall()}

        ok_tasks = True
        for tid, url, reward in rows:
            username = "@" + url.split("t.me/")[-1].split("/")[-1]
            try:
                member = await bot.get_chat_member(username, cb.from_user.id)
                if member.status in ("left", "kicked"):
                    ok_tasks = False
                else:
                    if tid not in done_set:  # only first time
                        reward_total += float(reward)
                        new_done.append((tid, float(reward)))
            except Exception:
                ok_tasks = False

        if ok_req and ok_tasks:
            if reward_total > 0:
                await add_stars(cb.from_user.id, reward_total)
                async with aiosqlite.connect(DB_PATH) as con:
                    await con.executemany("INSERT OR IGNORE INTO user_tasks(user_id, task_id) VALUES(?,?)",
                                        [(cb.from_user.id, tid) for tid, _ in new_done])
                    await con.commit()
                await reward_after_join(cb.from_user.id)
            if reward_total == 0:
                await cb.answer("Bu ýumuşlary eýýäm ýerine ýetiripsiňiz. 👍", show_alert=True)
            else:
                await cb.answer(f"🎉 Ýumuşlar tassyklanyldy. +{fmt_stars(reward_total)}", show_alert=True)
        else:
            await cb.answer("Kanalara doly agza bolmadyk ýaly. Gaýtadan barlaň.", show_alert=True)

@dp.callback_query(F.data == "boost")
async def cb_boost(cb: CallbackQuery):
    text = (
        "🚀 *Buustlar* 🚀\n\n"
        "Buustlar bilen ýyldyz gazanyş tizligiňizi artdyryň!\n\n"
        "🔸 *2x Buust* - 1 sagatlyk - 50⭐\n"
        "🔸 *3x Buust* - 30 minutlyk - 75⭐\n"
        "🔸 *5x Buust* - 15 minutlyk - 100⭐\n\n"
        "⚠️ *Bellik:* Buustlar häzirlikde elýeterli däl 🛠️"
    )
    await cb.message.edit_text(text, reply_markup=back_menu(), parse_mode=ParseMode.MARKDOWN)

@dp.callback_query(F.data == "exchange")
async def cb_exchange(cb: CallbackQuery, state: FSMContext):
    # show gifts grid
    kb = InlineKeyboardBuilder()
    for code, text, cost in GIFT_OPTIONS:
        kb.button(text=text, callback_data=f"gift:{code}")
    kb.button(text="⬅️ Yzyna", callback_data="back_home")
    kb.adjust(2, 2, 2, 2, 3)
    
    bal = await get_balance(cb.from_user.id)
    await state.set_state(WithdrawFSM.choose)
    await cb.message.edit_text(
        f"💫 *Çalşyrmak* 💫\n\n"
        f"💰 *Balansyňyz:* `{fmt_stars(bal)}`\n\n"
        "Aşakdaky sowgatlardan birini saýlaň:",
        reply_markup=kb.as_markup(),
        parse_mode=ParseMode.MARKDOWN
    )

@dp.callback_query(F.data.startswith("gift:"), WithdrawFSM.choose)
async def w_choose_gift(cb: CallbackQuery, state: FSMContext):
    code = cb.data.split(":")[1]
    found = next((opt for opt in GIFT_OPTIONS if opt[0] == code), None)
    if not found:
        return await cb.answer("Tapylmady.")
    _, label, cost = found
    bal = await get_balance(cb.from_user.id)
    if bal < cost:
        return await cb.answer(f"Balans ýeterlik däl. Gerek {int(cost)}⭐", show_alert=True)
    await state.update_data(gift_code=code, gift_label=label, amount=cost)
    await state.set_state(WithdrawFSM.contact)
    await cb.message.edit_text(
        f"🎁 *Saýlanan Sowgat:* {label}\n\n"
        "📨 *Habarlaşmak üçin kontakt/nik/ID ýazyň:*",
        reply_markup=back_menu(),
        parse_mode=ParseMode.MARKDOWN
    )

@dp.message(WithdrawFSM.contact)
async def w_contact(m: Message, state: FSMContext):
    data = await state.get_data()
    amt = float(data["amount"])
    ok = await sub_stars(m.from_user.id, amt)
    if not ok:
        await m.reply("Balans ýeterlik däl.", reply_markup=main_menu())
        await state.clear()
        return
    gift_label = data.get("gift_label", "—")
    gift_code = data.get("gift_code", "")
    async with aiosqlite.connect(DB_PATH) as con:
        await con.execute(
            "INSERT INTO withdrawals(user_id, amount, contact, status, created_at, gift) VALUES(?,?,?,?,?,?)",
            (m.from_user.id, amt, m.text.strip(), "pending", dt.datetime.utcnow().isoformat(), gift_code)
        )
        await con.commit()
        cur = await con.execute("SELECT last_insert_rowid()")
        wid = (await cur.fetchone())[0]

    # username resolve
    username = m.from_user.username
    u_text = ("@" + username) if username else f"ID:{m.from_user.id}"

    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Tassyklat", callback_data=f"w_ok:{wid}")
    kb.button(text="❌ Ret et", callback_data=f"w_no:{wid}")
    kb.adjust(2)

    text = (f"🆕 Çykarma #<b>{wid}</b>\n"
            f"👤 Ulanyjy: <b>{u_text}</b>\n"
            f"🆔 ID: <code>{m.from_user.id}</code>\n"
            f"🎁 Sowgat: {gift_label}\n"
            f"💰 Möçber: {fmt_stars(amt)}\n"
            f"📨 Kontakt: {m.text.strip()}\n"
            f"⏱ Status: <b>PENDING</b>")
    if LOG_CHANNEL_ID:
        try:
            await bot.send_message(LOG_CHANNEL_ID, text, reply_markup=kb.as_markup())
        except Exception:
            pass
    for aid in await admins_all():
        try:
            await bot.send_message(aid, text, reply_markup=kb.as_markup())
        except Exception:
            pass
    await m.reply(f"🕐 Soragyňyz görkezildi (#{wid}). Admin tassyklamagyny garaşyň.", reply_markup=main_menu())
    await state.clear()

@dp.callback_query(F.data == "faq")
async def cb_faq(cb: CallbackQuery):
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
    await cb.message.edit_text(text, reply_markup=back_menu(), parse_mode=ParseMode.MARKDOWN)

@dp.callback_query(F.data == "games")
async def cb_games(cb: CallbackQuery):
    text = (
        "🎮 *Mini Oýunlar* 🎮\n\n"
        "🕹️ *1. San Tapyş Oýny* - 5⭐\n"
        "🎯 *2. Target Oýny* - 3⭐\n"
        "🎲 *3. Zarlar* - 2⭐\n\n"
        "⚠️ *Bellik:* Mini oýunlar häzirlikde elýeterli däl 🛠️"
    )
    await cb.message.edit_text(text, reply_markup=back_menu(), parse_mode=ParseMode.MARKDOWN)

@dp.callback_query(F.data == "reviews")
async def cb_reviews(cb: CallbackQuery):
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
    await cb.message.edit_text(text, reply_markup=back_menu(), parse_mode=ParseMode.MARKDOWN)

@dp.callback_query(F.data == "daily")
async def cb_daily(cb: CallbackQuery):
    today = dt.date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as con:
        cur = await con.execute("SELECT last_daily FROM users WHERE id=?", (cb.from_user.id,))
        row = await cur.fetchone()
        last = row[0] if row else None
        if last == today:
            await cb.answer("Bugünkü bonusy eýýäm aldyňyz.", show_alert=True)
            return
        await con.execute("UPDATE users SET balance = balance + ?, last_daily=? WHERE id=?",
                        (DAILY_BONUS, today, cb.from_user.id))
        await con.commit()
    
    bal = await get_balance(cb.from_user.id)
    await cb.message.edit_text(
        f"🎉 *Gündelik Bonus* 🎉\n\n"
        f"✅ *Alyndy:* +{fmt_stars(DAILY_BONUS)}\n"
        f"💰 *Täze balans:* `{fmt_stars(bal)}`\n\n"
        "⏰ *Indiki bonus:* 24 sagatdan",
        reply_markup=back_menu(),
        parse_mode=ParseMode.MARKDOWN
    )

@dp.callback_query(F.data == "promo")
async def cb_promo(cb: CallbackQuery, state: FSMContext):
    await state.set_state(PromoFSM.waiting)
    await cb.message.edit_text("🎟 Promokodyňyzy ýazyň:", reply_markup=back_menu())

@dp.message(PromoFSM.waiting)
async def promo_redeem(m: Message, state: FSMContext):
    code = m.text.strip().upper()
    async with aiosqlite.connect(DB_PATH) as con:
        cur = await con.execute("SELECT reward, remaining FROM promos WHERE code=?", (code,))
        row = await cur.fetchone()
        if not row:
            await m.reply("❌ Nädogry promokod.", reply_markup=main_menu())
            await state.clear()
            return
        reward, remaining = row
        if remaining <= 0:
            await m.reply("⛔ Bu promokodyň aktiwasiýasy gutardy.", reply_markup=main_menu())
            await state.clear()
            return
        await con.execute("UPDATE promos SET remaining=remaining-1 WHERE code=?", (code,))
        await con.commit()
        await add_stars(m.from_user.id, float(reward))
        
        bal = await get_balance(m.from_user.id)
        await m.reply(
            f"🎉 *Promokod Kabul Edildi!* 🎉\n\n"
        f"✅ *Alyndy:* +{fmt_stars(float(reward))}\n"
        f"💰 *Täze balans:* `{fmt_stars(bal)}`\n\n"
        f"🔄 *Galan aktiwasiýa:* {remaining-1}",
        reply_markup=main_menu(),
        parse_mode=ParseMode.MARKDOWN
    )
    await state.clear()

@dp.callback_query(F.data == "top")
async def cb_top(cb: CallbackQuery):
    async with aiosqlite.connect(DB_PATH) as con:
        cur = await con.execute("SELECT id, balance FROM users ORDER BY balance DESC LIMIT 10")
        rows = await cur.fetchall()

    # resolve usernames
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
    await cb.message.edit_text(text, reply_markup=back_menu(), parse_mode=ParseMode.MARKDOWN)

@dp.callback_query(F.data == "seyf")
async def cb_seyf(cb: CallbackQuery):
    # Seyf kodlaryny göçürip al
    async with aiosqlite.connect(DB_PATH) as con:
        cur = await con.execute("SELECT key, value FROM settings WHERE key LIKE 'seyf_%'")
        rows = await cur.fetchall()
        
        if not rows:
            await cb.message.edit_text(
                "🔐 *Seyf - dogry kody dogry tapyp, mugt ýyldyz al!* 🔐\n\n"
                "Häzirlikde elýeterli seyf kodlary ýok. 🫤\n"
                "Adminler täze kod goýançaky garaşyň...",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Yzyna", callback_data="back_earn")]
                ]),
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        # Kodlary formatla
        codes_display = []
        for key, value in rows:
            code = key.replace("seyf_", "")
            stars = float(value)
            codes_display.append(f"`{code}` - {fmt_stars(stars)}")
        
        await cb.message.edit_text(
            "🔐 *Seyf - dogry kody dogry tapyp, mugt ýyldyz al!* 🔐\n\n"
            "Aşakdaky kodlary tapyň we ýazyň:\n" +
            "\n".join(codes_display) +
            "\n\nKody ýazmak üçin aşakdaky düwmä basyň:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔐 Kody girizmek", callback_data="enter_seyf_code")],
                [InlineKeyboardButton(text="⬅️ Yzyna", callback_data="back_earn")]
            ]),
            parse_mode=ParseMode.MARKDOWN
        )

@dp.callback_query(F.data == "enter_seyf_code")
async def enter_seyf_code(cb: CallbackQuery, state: FSMContext):
    await state.set_state(SeyfFSM.waiting)
    await cb.message.edit_text(
        "🔐 Seyf koduny ýazyň:",
        reply_markup=back_menu("⬅️ Yzyna", "seyf")
    )

@dp.message(SeyfFSM.waiting)
async def seyf_redeem(m: Message, state: FSMContext):
    code = m.text.strip().upper()
    
    async with aiosqlite.connect(DB_PATH) as con:
        cur = await con.execute("SELECT value FROM settings WHERE key=?", (f"seyf_{code}",))
        row = await cur.fetchone()
        
        if not row:
            await m.reply("❌ Nädogry seyf kody.", reply_markup=main_menu())
            await state.clear()
            return
        
        reward = float(row[0])
        await add_stars(m.from_user.id, reward)
        await con.execute("DELETE FROM settings WHERE key=?", (f"seyf_{code}",))
        await con.commit()
    
    bal = await get_balance(m.from_user.id)
    await m.reply(
        f"🎉 *Seyf Kody Kabul Edildi!* 🎉\n\n"
        f"✅ *Alyndy:* +{fmt_stars(reward)}\n"
        f"💰 *Täze balans:* `{fmt_stars(bal)}`",
        reply_markup=main_menu(),
        parse_mode=ParseMode.MARKDOWN
    )
    await state.clear()

@dp.callback_query(F.data == "back_earn")
async def back_earn(cb: CallbackQuery):
    await cb_earn(cb)

@dp.callback_query(F.data == "back_home")
async def back_home(cb: CallbackQuery):
    await cb.message.edit_text(
        "✨ *Ýyldyz Fermer Botuna Hoş Geldiňiz!* ✨\n\n"
        "Ýyldyzlary ferma etmek, dostlary çagyrmak we göni oýunlar bilen "
        "ýyldyz gazanyň! Gazanan ýyldyzlaryňyzy sowgatlara çalşyryň we "
        "hakyky harytlara eýe boluň! 🌟",
        reply_markup=main_menu(),
        parse_mode=ParseMode.MARKDOWN
    )

# -------------------- ADMIN --------------------

@dp.callback_query(F.data == "seyf_code")
async def a_seyf_code(cb: CallbackQuery, state: FSMContext):
    if not await is_admin(cb.from_user.id): return
    await state.set_state(SeyfFSM.waiting)
    await cb.message.edit_text(
        "🔐 Seyf kody giriziň format: `KOD STAR`\nMysal: `SEYF123 50`",
        reply_markup=admin_kb(),
        parse_mode=ParseMode.MARKDOWN
    )

@dp.message(SeyfFSM.waiting)
async def a_seyf_create(m: Message, state: FSMContext):
    if not await is_admin(m.from_user.id): return
    parts = m.text.strip().split()
    if len(parts) < 2:
        await m.reply("Formato laýyk däl. Mysal: `SEYF123 50`", parse_mode=ParseMode.MARKDOWN)
        return
    
    code = parts[0].upper()
    reward = float(parts[1])
    
    async with aiosqlite.connect(DB_PATH) as con:
        await con.execute(
            "INSERT OR REPLACE INTO settings(key, value) VALUES(?,?)",
            (f"seyf_{code}", str(reward))
        )
        await con.commit()
    
    await m.reply(f"✅ Seyf kody döredildi: `{code}` → {fmt_stars(reward)}", reply_markup=admin_kb(), parse_mode=ParseMode.MARKDOWN)
    await state.clear()

@dp.callback_query(F.data == "p_add")
async def a_promo_add(cb: CallbackQuery, state: FSMContext):
    if not await is_admin(cb.from_user.id): return
    await state.set_state(PromoFSM.create)
    await cb.message.edit_text(
        "🎟 Promokod giriziň format: `KOD STAR AKTIVASIÝA`\nMysal: `NEW2025 5 100`",
        reply_markup=admin_kb(),
        parse_mode=ParseMode.MARKDOWN
    )

@dp.message(PromoFSM.create)
async def a_promo_create(m: Message, state: FSMContext):
    if not await is_admin(m.from_user.id): return
    parts = m.text.strip().split()
    if len(parts) != 3:
        await m.reply("Formato laýyk däl. Mysal: `NEW2025 5 100`", parse_mode=ParseMode.MARKDOWN)
        return
    
    code = parts[0].upper()
    reward = float(parts[1])
    remaining = int(parts[2])
    
    async with aiosqlite.connect(DB_PATH) as con:
        await con.execute(
            "INSERT OR REPLACE INTO promos(code, reward, remaining, created_by, created_at) VALUES(?,?,?,?,?)",
            (code, reward, remaining, m.from_user.id, dt.datetime.utcnow().isoformat())
        )
        await con.commit()
    
    await m.reply(f"✅ Promokod döredildi: `{code}` → {fmt_stars(reward)}, aktiwasiýa: {remaining}", reply_markup=admin_kb(), parse_mode=ParseMode.MARKDOWN)
    await state.clear()

@dp.callback_query(F.data == "p_list")
async def a_promo_list(cb: CallbackQuery):
    if not await is_admin(cb.from_user.id): return
    async with aiosqlite.connect(DB_PATH) as con:
        cur = await con.execute("SELECT code, reward, remaining FROM promos ORDER BY created_at DESC")
        rows = await cur.fetchall()
        text = "🎟 *Promokodlar* 🎟\n" + ("\n".join([f"`{c}`: {fmt_stars(float(r))}, galan: {rem}" for c, r, rem in rows]) if rows else "— ýok —")
        await cb.message.edit_text(text, reply_markup=admin_kb(), parse_mode=ParseMode.MARKDOWN)

@dp.callback_query(F.data == "set_ref")
async def a_set_ref(cb: CallbackQuery, state: FSMContext):
    if not await is_admin(cb.from_user.id): return
    await state.set_state(SetRefFSM.waiting)
    await cb.message.edit_text(f"Häzirki referal bonus: {fmt_stars(REF_BONUS)}\nTäze bahany ýazyň (san):", reply_markup=admin_kb())

@dp.message(SetRefFSM.waiting)
async def a_set_ref_val(m: Message, state: FSMContext):
    global REF_BONUS
    try:
        REF_BONUS = float(m.text.replace(",", "."))
    except Exception:
        return await m.reply("San giriziň.")
    await m.reply(f"✅ Täze referal bonus: {fmt_stars(REF_BONUS)}", reply_markup=admin_kb())
    await state.clear()

@dp.callback_query(F.data == "c_add")
async def a_c_add(cb: CallbackQuery, state: FSMContext):
    if not await is_admin(cb.from_user.id): return
    await state.set_state(AddChannelFSM.waiting)
    await cb.message.edit_text("Kanal username giriziň, mysal: `@oxynum`", reply_markup=admin_kb(), parse_mode=ParseMode.MARKDOWN)

@dp.message(AddChannelFSM.waiting)
async def a_c_add_val(m: Message, state: FSMContext):
    if not await is_admin(m.from_user.id): return
    username = m.text.strip()
    if not username.startswith("@"):
        return await m.reply("Başynda @ bolmaly.")
    async with aiosqlite.connect(DB_PATH) as con:
        await con.execute("INSERT OR IGNORE INTO channels(username) VALUES(?)", (username,))
        await con.commit()
    await m.reply(f"✅ Kanal goşuldy: {username}", reply_markup=admin_kb())
    await state.clear()

@dp.callback_query(F.data == "c_del")
async def a_c_del(cb: CallbackQuery):
    if not await is_admin(cb.from_user.id): return
    chs = await required_channels()
    if not chs:
        return await cb.answer("Kanal ýok.")
    kb = InlineKeyboardBuilder()
    for ch in chs:
        kb.button(text=f"❌ {ch}", callback_data=f"c_del:{ch}")
    kb.adjust(1)
    await cb.message.edit_text("Aýyrjak kanaly saýlaň:", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("c_del:"))
async def a_c_del_do(cb: CallbackQuery):
    if not await is_admin(cb.from_user.id): return
    ch = cb.data.split(":")[1]
    async with aiosqlite.connect(DB_PATH) as con:
        await con.execute("DELETE FROM channels WHERE username=?", (ch,))
        await con.commit()
    await cb.answer("Pozuldy.")
    await cb.message.edit_reply_markup(reply_markup=admin_kb())

@dp.callback_query(F.data == "c_list")
async def a_c_list(cb: CallbackQuery):
    if not await is_admin(cb.from_user.id): return
    chs = await required_channels()
    txt = "📢 *Mejbury kanallar* 📢\n" + ("\n".join(chs) if chs else "— ýok —")
    await cb.message.edit_text(txt, reply_markup=admin_kb(), parse_mode=ParseMode.MARKDOWN)

@dp.callback_query(F.data == "t_add")
async def a_t_add(cb: CallbackQuery, state: FSMContext):
    if not await is_admin(cb.from_user.id): return
    await state.set_state(AddTaskFSM.title)
    await cb.message.edit_text("Ýumuş adyny ýazyň:", reply_markup=admin_kb())

@dp.message(AddTaskFSM.title)
async def a_t_title(m: Message, state: FSMContext):
    await state.update_data(title=m.text.strip())
    await state.set_state(AddTaskFSM.url)
    await m.reply("Ýumuş URL (kanal linki) giriziň, mysal: https://t.me/oxynum")

@dp.message(AddTaskFSM.url)
async def a_t_url(m: Message, state: FSMContext):
    await state.update_data(url=m.text.strip())
    await state.set_state(AddTaskFSM.reward)
    await m.reply("Bu ýumuş üçin ⭐ möçberi (san) giriziň:")

@dp.message(AddTaskFSM.reward)
async def a_t_reward(m: Message, state: FSMContext):
    try:
        reward = float(m.text.replace(",", "."))
    except Exception:
        return await m.reply("San giriziň.")
    data = await state.get_data()
    async with aiosqlite.connect(DB_PATH) as con:
        await con.execute("INSERT INTO tasks(title, url, reward, type) VALUES(?,?,?,?)",
                        (data["title"], data["url"], reward, "join"))
        await con.commit()
    await m.reply("✅ Ýumuş goşuldy.", reply_markup=admin_kb())
    await state.clear()

@dp.callback_query(F.data == "t_list")
async def a_t_list(cb: CallbackQuery):
    if not await is_admin(cb.from_user.id): return
    async with aiosqlite.connect(DB_PATH) as con:
        cur = await con.execute("SELECT id, title, reward FROM tasks ORDER BY id DESC")
        rows = await cur.fetchall()
        if not rows:
            return await cb.answer("Ýumuş ýok.")
        kb = InlineKeyboardBuilder()
        lines = []
        for i, (tid, title, reward) in enumerate(rows, start=1):
            lines.append(f"{i}) {title} – {int(reward)}⭐ (#{tid})")
            kb.button(text=f"🗑 #{tid}", callback_data=f"t_del:{tid}")
        kb.adjust(3)
        await cb.message.edit_text("🧩 *Ýumuşlar:*\n" + "\n".join(lines), reply_markup=kb.as_markup(), parse_mode=ParseMode.MARKDOWN)

@dp.callback_query(F.data.startswith("t_del:"))
async def a_t_del(cb: CallbackQuery):
    if not await is_admin(cb.from_user.id): return
    tid = int(cb.data.split(":")[1])
    async with aiosqlite.connect(DB_PATH) as con:
        await con.execute("DELETE FROM tasks WHERE id=?", (tid,))
        await con.commit()
    await cb.answer("Pozuldy.")
    await cb.message.edit_reply_markup(reply_markup=admin_kb())

# ---- Balance editor (ID ➜ action ➜ amount) ----

@dp.callback_query(F.data == "b_edit")
async def a_b_edit(cb: CallbackQuery, state: FSMContext):
    if not await is_admin(cb.from_user.id): return
    await state.set_state(BalanceFSM.uid)
    await cb.message.edit_text("Ulanyjy ID giriziň:", reply_markup=admin_kb())

@dp.message(BalanceFSM.uid)
async def a_b_uid(m: Message, state: FSMContext):
    try:
        uid = int(m.text.strip())
    except Exception:
        return await m.reply("ID san bolmaly.")
    await state.update_data(uid=uid)
    await state.set_state(BalanceFSM.action)
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Goş", callback_data="b_act:add")
    kb.button(text="➖ Aýyr", callback_data="b_act:sub")
    kb.adjust(2)
    await m.reply("Işi saýlaň:", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("b_act:"), BalanceFSM.action)
async def a_b_action(cb: CallbackQuery, state: FSMContext):
    act = cb.data.split(":")[1]
    await state.update_data(action=act)
    await state.set_state(BalanceFSM.amount)
    await cb.message.edit_text("Möçber giriziň (san):", reply_markup=admin_kb())

@dp.message(BalanceFSM.amount)
async def a_b_amount(m: Message, state: FSMContext):
    if not await is_admin(m.from_user.id): return
    data = await state.get_data()
    try:
        amt = float(m.text.replace(",", "."))
    except Exception:
        return await m.reply("San giriziň.")
    uid = int(data["uid"])
    if data["action"] == "add":
        await add_stars(uid, amt)
    else:
        ok = await sub_stars(uid, amt)
        if not ok:
            return await m.reply("Ulanyjynyň balansy ýeterlik däl.")
    await m.reply("✅ Üýtgedildi.", reply_markup=admin_kb())
    await state.clear()

# ---- Clicker admin ----

@dp.callback_query(F.data == "click_set")
async def click_set(cb: CallbackQuery, state: FSMContext):
    if not await is_admin(cb.from_user.id): return
    cur = await get_setting("click_reward", str(CLICK_REWARD_DEFAULT))
    await state.set_state(ClickSetFSM.reward)
    await cb.message.edit_text(
        f"🖱 Häzirki kliker baýragy: {fmt_stars(float(cur))} / {CLICK_COOLDOWN_MIN}m\n"
        "Täze bahany ýazyň (mysal: 0.2):",
        reply_markup=admin_kb()
    )

@dp.message(ClickSetFSM.reward)
async def click_set_val(m: Message, state: FSMContext):
    if not await is_admin(m.from_user.id): return
    try:
        val = float(m.text.replace(",", "."))
        if val < 0:
            raise ValueError()
    except Exception:
        return await m.reply("Pozitif sany giriziň (mysal: 0.2).")
    await set_setting("click_reward", str(val))
    await m.reply(f"✅ Täze kliker baýragy goýuldy: {fmt_stars(val)} / {CLICK_COOLDOWN_MIN}m", reply_markup=admin_kb())
    await state.clear()

# -------------------- STARTUP --------------------

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
    print("Bot started.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Bot stopped.")