
import os
import sqlite3
from pathlib import Path
from datetime import date, datetime

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    ContextTypes,
    filters
)

# ==================================================
# CONFIGURAZIONE
# ==================================================

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

def read_ids(variable):
    return {
        int(x.strip())
        for x in os.getenv(variable, "").split(",")
        if x.strip().isdigit()
    }

ALLOWED_USERS = read_ids("ALLOWED_USER_IDS")
ADMIN_USERS = read_ids("ADMIN_USER_IDS")

DATA_DIR = Path("/data")
if not DATA_DIR.exists():
    DATA_DIR = Path(".")

DB = DATA_DIR / "nucleo.db"

WAITING_TEXT = 1

# ==================================================
# DATABASE
# ==================================================

def db():
    return sqlite3.connect(DB)

def init_db():
    with db() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT,
            author TEXT,
            created TEXT
        );

        CREATE TABLE IF NOT EXISTS equipment (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT,
            author TEXT,
            created TEXT
        );

        CREATE TABLE IF NOT EXISTS boats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT,
            author TEXT,
            created TEXT
        );

        CREATE TABLE IF NOT EXISTS dives (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT,
            author TEXT,
            created TEXT
        );

        CREATE TABLE IF NOT EXISTS presence (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            name TEXT,
            day TEXT,
            status TEXT,
            note TEXT,
            UNIQUE(user_id, day)
        );
        """)

# ==================================================
# AUTORIZZAZIONE
# ==================================================

def authorized(user):
    return user is not None and user.id in ALLOWED_USERS

def admin(user):
    return user is not None and user.id in ADMIN_USERS

async def deny(update):
    if update.callback_query:
        await update.callback_query.answer(
            "Accesso non autorizzato.", show_alert=True
        )
    elif update.effective_message:
        await update.effective_message.reply_text(
            "⛔ Accesso riservato al personale autorizzato."
        )

# ==================================================
# COMANDO ID
# ==================================================

async def get_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(
        f"Il tuo ID Telegram è:\n\n`{user.id}`",
        parse_mode="Markdown"
    )

# ==================================================
# MENU PRINCIPALE
# ==================================================

def main_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📅 Calendario", callback_data="calendar"),
            InlineKeyboardButton("👥 Presenze", callback_data="presence")
        ],
        [
            InlineKeyboardButton("🚤 Mezzi nautici", callback_data="boats"),
            InlineKeyboardButton("🤿 Attrezzature", callback_data="equipment")
        ],
        [
            InlineKeyboardButton("📋 Attività", callback_data="tasks"),
            InlineKeyboardButton("🌊 Dive Log", callback_data="dives")
        ],
        [
            InlineKeyboardButton("📊 Statistiche", callback_data="stats")
        ],
        [
            InlineKeyboardButton("🌐 Meteo marino", url="https://www.windy.com/")
        ],
        [
            InlineKeyboardButton("➕ Inserisci informazioni", callback_data="addmenu")
        ]
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not authorized(update.effective_user):
        await deny(update)
        return

    await update.message.reply_text(
        "🤿 NUCLEO BOT\n"
        "Assistente digitale del Nucleo Sommozzatori.\n\n"
        "Seleziona una funzione:",
        reply_markup=main_keyboard()
    )

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not authorized(update.effective_user):
        await deny(update)
        return

    await update.callback_query.answer()
    await update.callback_query.message.reply_text(
        "🤿 MENU PRINCIPALE",
        reply_markup=main_keyboard()
    )

# ==================================================
# VISUALIZZAZIONE DATI
# ==================================================

TABLES = {
    "tasks": ("Attività", "tasks"),
    "equipment": ("Attrezzature", "equipment"),
    "boats": ("Mezzi nautici", "boats"),
    "dives": ("Dive Log", "dives")
}

async def show_list(update, kind):
    title, table = TABLES[kind]

    with db() as con:
        rows = con.execute(
            f"SELECT id, text, author, created FROM {table} "
            "ORDER BY id DESC LIMIT 30"
        ).fetchall()

    if not rows:
        result = f"📂 {title}\n\nNessun elemento registrato."
    else:
        result = f"📂 {title}\n\n"
        for item in rows:
            result += (
                f"#{item[0]} - {item[1]}\n"
                f"👤 {item[2]} | {item[3]}\n\n"
            )

    await update.callback_query.message.reply_text(result)

# ==================================================
# PRESENZE
# ==================================================

async def show_presence(update):
    today = date.today().isoformat()

    with db() as con:
        rows = con.execute(
            "SELECT name, status, note FROM presence "
            "WHERE day=? ORDER BY name",
            (today,)
        ).fetchall()

    result = f"👥 PRESENZE - {today}\n\n"

    if not rows:
        result += "Nessuna disponibilità registrata."
    else:
        for name, status, note in rows:
            result += f"• {name}: {status}"
            if note:
                result += f" ({note})"
            result += "\n"

    result += (
        "\n\nPer registrarti usa:\n"
        "/presenza 2026-11-06 disponibile Nota"
    )

    await update.callback_query.message.reply_text(result)

async def set_presence(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not authorized(update.effective_user):
        await deny(update)
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "Formato:\n"
            "/presenza AAAA-MM-GG disponibile [nota]\n\n"
            "Stati ammessi: disponibile, assente, servizio"
        )
        return

    try:
        day = datetime.strptime(
            context.args[0], "%Y-%m-%d"
        ).date().isoformat()

        status = context.args[1].lower()

        if status not in ("disponibile", "assente", "servizio"):
            raise ValueError()

        note = " ".join(context.args[2:])
        user = update.effective_user
        name = user.full_name

        with db() as con:
            con.execute("""
                INSERT INTO presence
                (user_id, name, day, status, note)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id, day)
                DO UPDATE SET
                    name=excluded.name,
                    status=excluded.status,
                    note=excluded.note
            """, (user.id, name, day, status, note))

        await update.message.reply_text(
            f"✅ Presenza registrata per {day}: {status}"
        )

    except ValueError:
        await update.message.reply_text(
            "Data o stato non valido. Controlla il formato."
        )

# ==================================================
# INSERIMENTO INFORMAZIONI
# ==================================================

async def add_menu(update):
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📋 Nuova attività", callback_data="add_tasks")
        ],
        [
            InlineKeyboardButton("🤿 Nuova attrezzatura", callback_data="add_equipment")
        ],
        [
            InlineKeyboardButton("🚤 Nuovo mezzo", callback_data="add_boats")
        ],
        [
            InlineKeyboardButton("🌊 Nuova immersione", callback_data="add_dives")
        ],
        [
            InlineKeyboardButton("👥 Registra presenza", callback_data="add_presence")
        ],
        [
            InlineKeyboardButton("↩️ Menu", callback_data="menu")
        ]
    ])

    await update.callback_query.message.reply_text(
        "➕ COSA VUOI INSERIRE?",
        reply_markup=keyboard
    )

async def begin_add(update, context):
    if not authorized(update.effective_user):
        await deny(update)
        return ConversationHandler.END

    query = update.callback_query
    await query.answer()

    kind = query.data.replace("add_", "")
    context.user_data["kind"] = kind

    prompts = {
        "tasks": "Descrivi l'attività da registrare:",
        "equipment": "Inserisci attrezzatura, matricola e stato:",
        "boats": "Inserisci mezzo, caratteristiche e stato:",
        "dives": "Inserisci data, luogo e dettagli dell'immersione:",
        "presence": (
            "Inserisci la presenza nel formato:\n"
            "AAAA-MM-GG | disponibile/assente/servizio | nota"
        )
    }

    await query.message.reply_text(prompts[kind])
    return WAITING_TEXT

async def save_item(update, context):
    if not authorized(update.effective_user):
        await deny(update)
        return ConversationHandler.END

    text = update.message.text.strip()
    kind = context.user_data.get("kind")
    user = update.effective_user
    author = user.full_name
    created = datetime.now().strftime("%d/%m/%Y %H:%M")

    if not text:
        await update.message.reply_text("Inserisci un testo valido.")
        return WAITING_TEXT

    if kind == "presence":
        try:
            parts = [x.strip() for x in text.split("|")]
            if len(parts) < 2:
                raise ValueError()

            day = datetime.strptime(parts[0], "%Y-%m-%d").date().isoformat()
            status = parts[1].lower()
            note = parts[2] if len(parts) > 2 else ""

            if status not in ("disponibile", "assente", "servizio"):
                raise ValueError()

            with db() as con:
                con.execute("""
                    INSERT INTO presence
                    (user_id, name, day, status, note)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, day)
                    DO UPDATE SET
                        name=excluded.name,
                        status=excluded.status,
                        note=excluded.note
                """, (user.id, author, day, status, note))

            await update.message.reply_text("✅ Presenza salvata!")
        except ValueError:
            await update.message.reply_text(
                "Formato non valido. Riprova con:\n"
                "2026-11-06 | disponibile | nota"
            )
            return WAITING_TEXT

    else:
        table = kind
        with db() as con:
            con.execute(
                f"INSERT INTO {table} (text, author, created) "
                "VALUES (?, ?, ?)",
                (text, author, created)
            )

        await update.message.reply_text(
            "✅ Informazione registrata correttamente!"
        )

    context.user_data.clear()
    await update.message.reply_text(
        "🤿 Torna al menu principale:",
        reply_markup=main_keyboard()
    )

    return ConversationHandler.END

async def cancel(update, context):
    context.user_data.clear()
    await update.message.reply_text(
        "Operazione annullata.",
        reply_markup=main_keyboard()
    )
    return ConversationHandler.END

# ==================================================
# STATISTICHE
# ==================================================

async def show_stats(update):
    with db() as con:
        tasks = con.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        equipment = con.execute("SELECT COUNT(*) FROM equipment").fetchone()[0]
        boats = con.execute("SELECT COUNT(*) FROM boats").fetchone()[0]
        dives = con.execute("SELECT COUNT(*) FROM dives").fetchone()[0]
        people = con.execute(
            "SELECT COUNT(DISTINCT user_id) FROM presence"
        ).fetchone()[0]

    text = (
        "📊 STATISTICHE NUCLEO\n\n"
        f"📋 Attività registrate: {tasks}\n"
        f"🤿 Attrezzature registrate: {equipment}\n"
        f"🚤 Mezzi registrati: {boats}\n"
        f"🌊 Immersioni registrate: {dives}\n"
        f"👥 Componenti con presenze registrate: {people}\n"
    )

    await update.callback_query.message.reply_text(text)

# ==================================================
# GESTIONE PULSANTI
# ==================================================

async def buttons(update, context):
    if not authorized(update.effective_user):
        await deny(update)
        return

    query = update.callback_query
    await query.answer()

    action = query.data

    if action == "menu":
        await query.message.reply_text(
            "🤿 MENU PRINCIPALE",
            reply_markup=main_keyboard()
        )

    elif action == "addmenu":
        await add_menu(update)

    elif action == "presence":
        await show_presence(update)

    elif action == "stats":
        await show_stats(update)

    elif action in TABLES:
        await show_list(update, action)

# ==================================================
# AVVIO
# ==================================================

def main():
    if not TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN non configurato.")

    init_db()

    if not ALLOWED_USERS:
        print("ATTENZIONE: nessun utente autorizzato configurato.")

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("id", get_id))
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("presenza", set_presence))

    add_conversation = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(
                begin_add,
                pattern=r"^add_(tasks|equipment|boats|dives|presence)$"
            )
        ],
        states={
            WAITING_TEXT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_item)
            ]
        },
        fallbacks=[
            CommandHandler("annulla", cancel)
        ],
        allow_reentry=True
    )

    app.add_handler(add_conversation)
    app.add_handler(CallbackQueryHandler(buttons))

    print("NUCLEO BOT avviato.")
    app.run_polling()

if __name__ == "__main__":
    main()
