
import os
import re
import sqlite3
import asyncio
import calendar
from pathlib import Path
from datetime import datetime, date, timedelta, time
from zoneinfo import ZoneInfo

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
GROUP_CHAT_ID = os.getenv("GROUP_CHAT_ID", "").strip()
TZ = ZoneInfo("Europe/Rome")


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

DOCS_DIR = Path(__file__).resolve().parent / "documenti"
PDF_NAME = "SMM   6 Norme per le immersioni - ediz. ott 2017.pdf"

WAITING_TEXT = 1
WAITING_DATE = 2
EDIT_FIELD = 3
EDIT_TEXT = 4
EDIT_DATE = 5

# ==================================================
# COLLEGAMENTI ESTERNI
# ==================================================

URL_EROGATORI = (
    "https://docs.google.com/spreadsheets/d/"
    "1V0T3S-opbrtNdWkxRFF_v2U1FGfKjL1q8QncxvweSFw/edit?usp=drivesdk"
)

URL_BOMBOLE = (
    "https://docs.google.com/spreadsheets/d/"
    "1cvYU9pHaKb8O7nXuziXX98igO_phSe8L/"
    "edit?usp=drivesdk&ouid=116969727930731164385&rtpof=true&sd=true"
)

URL_MEZZI_CARRELLI = (
    "https://docs.google.com/spreadsheets/d/"
    "1MM1wp17Lb1Nsa7IHvDpbkujZzRgpqMQPfRgSvu374Jc/edit?usp=drivesdk"
)

URL_MOSE = "https://www.autoritalaguna.it/operativita-m-o-s-e/"

URL_MAREA = (
    "https://www.comune.venezia.it/it/content/"
    "centro-previsioni-e-segnalazioni-maree"
)

URL_MOTO_ONDOSO = (
    "https://www.comune.venezia.it/it/content/"
    "previsioni-onda-alto-adriatico-0"
)

# ==================================================
# DATABASE
# ==================================================

def db():
    return sqlite3.connect(DB)


def add_column(con, table, column, definition):
    columns = {
        row[1] for row in con.execute(
            f"PRAGMA table_info({table})"
        ).fetchall()
    }

    if column not in columns:
        con.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
        )


def init_db():
    with db() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT,
            author TEXT,
            created TEXT,
            event_date TEXT,
            notified INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS equipment (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT,
            author TEXT,
            created TEXT,
            revision_date TEXT,
            notified INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS boats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT,
            author TEXT,
            created TEXT,
            revision_date TEXT,
            notified INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS dives (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT,
            author TEXT,
            created TEXT
        );

        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT,
            author TEXT,
            created TEXT,
            reminder_date TEXT,
            notified INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS notification_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            notification_type TEXT NOT NULL,
            notification_key TEXT NOT NULL,
            sent_at TEXT,
            UNIQUE(notification_type, notification_key)
        );
        """)

        add_column(con, "tasks", "event_date", "TEXT")
        add_column(con, "tasks", "notified", "INTEGER DEFAULT 0")

        add_column(con, "equipment", "revision_date", "TEXT")
        add_column(con, "equipment", "notified", "INTEGER DEFAULT 0")

        add_column(con, "boats", "revision_date", "TEXT")
        add_column(con, "boats", "notified", "INTEGER DEFAULT 0")


# ==================================================
# AUTORIZZAZIONE
# ==================================================

def authorized(user):
    return user is not None and user.id in ALLOWED_USERS


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
# COMANDI
# ==================================================

async def get_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    await update.message.reply_text(
        f"Il tuo ID Telegram è:\n\n`{user.id}`",
        parse_mode="Markdown"
    )


async def get_chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not authorized(update.effective_user):
        await deny(update)
        return

    chat = update.effective_chat

    await update.effective_message.reply_text(
        f"🆔 ID di questa chat:\n\n`{chat.id}`\n\n"
        "Copia questo numero e inseriscilo nella variabile "
        "GROUP_CHAT_ID su FadeHost.",
        parse_mode="Markdown"
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not authorized(update.effective_user):
        await deny(update)
        return

    await update.message.reply_text(
        "🤿 NUCLEO BOT\n"
        "Gestione attività, promemoria, mezzi e attrezzature "
        "del Nucleo Sommozzatori.\n\n"
        "Seleziona una funzione:",
        reply_markup=main_keyboard()
    )


# ==================================================
# MENU PRINCIPALE
# ==================================================

def main_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📅 Calendario", callback_data="calendar"
            ),
            InlineKeyboardButton(
                "📘 Assistente documentale", callback_data="assistant"
            )
        ],
        [
            InlineKeyboardButton(
                "📋 Attività", callback_data="tasks"
            )
        ],
        [
            InlineKeyboardButton(
                "➕ Inserisci attività", callback_data="addmenu"
            )
        ],
        [
            InlineKeyboardButton(
                "🔔 Aggiungi promemoria", callback_data="add_reminder"
            )
        ],
        [
            InlineKeyboardButton(
                "🤿 Erogatori", url=URL_EROGATORI
            ),
            InlineKeyboardButton(
                "🛢️ Bombole", url=URL_BOMBOLE
            )
        ],
        [
            InlineKeyboardButton(
                "🚤 Mezzi&Carrelli", url=URL_MEZZI_CARRELLI
            )
        ],
        [
            InlineKeyboardButton(
                "🌊 MOSE", url=URL_MOSE
            ),
            InlineKeyboardButton(
                "🌊 Marea", url=URL_MAREA
            )
        ],
        [
            InlineKeyboardButton(
                "🌊 Moto Ondoso", url=URL_MOTO_ONDOSO
            )
        ]
    ])


# ==================================================
# ASSISTENTE DOCUMENTALE
# ==================================================

async def assistant_start(update, context):
    if not authorized(update.effective_user):
        await deny(update)
        return

    query = update.callback_query
    await query.answer()

    pdf_path = DOCS_DIR / PDF_NAME

    if not pdf_path.is_file():
        await query.message.reply_text(
            "⚠️ PDF non trovato.\n\n"
            "Verifica che sia presente nella cartella "
            "'documenti' accanto a main.py."
        )
        return

    try:
        with pdf_path.open("rb") as pdf:
            await query.message.reply_document(
                document=pdf,
                filename="SMM 6 - Norme per le immersioni.pdf",
                caption="📘 SMM 6 - Norme per le immersioni"
            )
    except Exception as error:
        print(f"Errore invio PDF: {error}")
        await query.message.reply_text(
            "❌ Non è stato possibile inviare il PDF."
        )


# ==================================================
# DATE
# ==================================================

def parse_date(value):
    value = value.strip()

    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass

    return None


def display_date(value):
    if not value:
        return "Non indicata"

    try:
        return date.fromisoformat(value).strftime("%d/%m/%Y")
    except ValueError:
        return value


def now_text():
    return datetime.now(TZ).strftime("%d/%m/%Y %H:%M")


def today_local():
    return datetime.now(TZ).date()


# ==================================================
# VISUALIZZAZIONE ELENCHI
# ==================================================

TABLES = {
    "tasks": ("Attività", "tasks"),
    "equipment": ("Attrezzature", "equipment"),
    "boats": ("Mezzi nautici", "boats")
}


def item_description(kind, row):
    item_id, text, author, created, item_date = row

    if kind == "tasks":
        date_label = "📅 Svolgimento"
    else:
        date_label = "🔧 Revisione"

    return (
        f"#{item_id}\n"
        f"📝 {text}\n"
        f"{date_label}: {display_date(item_date)}\n"
        f"👤 {author or 'Non indicato'}\n"
        f"🕒 Inserito: {created or 'Non indicato'}"
    )


async def show_list(update, kind):
    title, table = TABLES[kind]

    date_column = (
        "event_date" if kind == "tasks" else "revision_date"
    )

    with db() as con:
        rows = con.execute(
            f"SELECT id, text, author, created, {date_column} "
            f"FROM {table} ORDER BY "
            f"{date_column} IS NULL, {date_column}, id DESC "
            "LIMIT 30"
        ).fetchall()

    if not rows:
        await update.callback_query.message.reply_text(
            f"📂 {title}\n\nNessun elemento registrato."
        )
        return

    await update.callback_query.message.reply_text(
        f"📂 {title}\n\nUltime registrazioni:"
    )

    for row in rows:
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton(
                "✏️ Modifica",
                callback_data=f"edit_{kind}_{row[0]}"
            )
        ]])

        await update.callback_query.message.reply_text(
            item_description(kind, row),
            reply_markup=keyboard
        )


# ==================================================
# INSERIMENTO ATTIVITÀ E PROMEMORIA
# ==================================================

async def add_menu(update):
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📋 Nuova attività", callback_data="add_tasks"
            )
        ],
        [
            InlineKeyboardButton(
                "🔔 Nuovo promemoria", callback_data="add_reminder"
            )
        ],
        [
            InlineKeyboardButton(
                "↩️ Menu principale", callback_data="menu"
            )
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

    if kind not in ("tasks", "reminder"):
        return ConversationHandler.END

    context.user_data["kind"] = kind

    if kind == "tasks":
        prompt = "📋 Descrivi l'attività da registrare:"
    else:
        prompt = (
            "🔔 Descrivi il promemoria che vuoi ricevere:"
        )

    await query.message.reply_text(prompt)

    return WAITING_TEXT


async def save_new_text(update, context):
    if not authorized(update.effective_user):
        await deny(update)
        return ConversationHandler.END

    text = update.message.text.strip()

    if not text:
        await update.message.reply_text(
            "Inserisci una descrizione valida."
        )
        return WAITING_TEXT

    context.user_data["new_text"] = text
    kind = context.user_data.get("kind")

    if kind == "tasks":
        prompt = (
            "📅 Inserisci il giorno di svolgimento dell'attività "
            "nel formato GG/MM/AAAA:"
        )
    elif kind == "reminder":
        prompt = (
            "📅 Inserisci il giorno in cui vuoi ricevere "
            "il promemoria, nel formato GG/MM/AAAA.\n\n"
            "La notifica verrà inviata alle ore 08:00 italiane."
        )
    else:
        return ConversationHandler.END

    await update.message.reply_text(prompt)
    return WAITING_DATE


async def save_new_date(update, context):
    if not authorized(update.effective_user):
        await deny(update)
        return ConversationHandler.END

    kind = context.user_data.get("kind")
    text = context.user_data.get("new_text", "")
    value = update.message.text.strip()

    if kind not in ("tasks", "reminder"):
        return ConversationHandler.END

    parsed = parse_date(value)

    if not parsed:
        await update.message.reply_text(
            "❌ Data non valida. Usa il formato GG/MM/AAAA."
        )
        return WAITING_DATE

    selected_date = date.fromisoformat(parsed)
    today = today_local()

    if kind == "reminder":
        now = datetime.now(TZ)

        if selected_date < today:
            await update.message.reply_text(
                "❌ Non puoi impostare un promemoria per una data passata. "
                "Inserisci una nuova data:"
            )
            return WAITING_DATE

        if selected_date == today and now.time() >= time(8, 0):
            await update.message.reply_text(
                "❌ Le notifiche delle 08:00 di oggi sono già passate. "
                "Scegli da domani in poi:"
            )
            return WAITING_DATE

    user = update.effective_user
    author = user.full_name
    created = now_text()

    with db() as con:
        if kind == "tasks":
            con.execute(
                "INSERT INTO tasks "
                "(text, author, created, event_date, notified) "
                "VALUES (?, ?, ?, ?, 0)",
                (text, author, created, parsed)
            )
        else:
            con.execute(
                "INSERT INTO reminders "
                "(text, author, created, reminder_date, notified) "
                "VALUES (?, ?, ?, ?, 0)",
                (text, author, created, parsed)
            )

    context.user_data.clear()

    if kind == "tasks":
        confirmation = (
            "✅ Attività inserita correttamente!\n"
            f"📅 Data: {display_date(parsed)}"
        )
    else:
        confirmation = (
            "✅ Promemoria inserito correttamente!\n"
            f"🔔 Notifica prevista il {display_date(parsed)} "
            "alle ore 08:00."
        )

    await update.message.reply_text(
        confirmation,
        reply_markup=main_keyboard()
    )

    return ConversationHandler.END


# ==================================================
# MODIFICA ATTIVITÀ E VECCHI ELEMENTI
# ==================================================

async def begin_edit(update, context):
    if not authorized(update.effective_user):
        await deny(update)
        return ConversationHandler.END

    query = update.callback_query
    await query.answer()

    match = re.match(r"^edit_(tasks|equipment|boats)_(\d+)$", query.data)

    if not match:
        return ConversationHandler.END

    kind = match.group(1)
    item_id = int(match.group(2))

    context.user_data["edit_kind"] = kind
    context.user_data["edit_id"] = item_id

    if kind == "tasks":
        date_label = "📅 Modifica data di svolgimento"
    else:
        date_label = "🔧 Modifica scadenza revisione"

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📝 Modifica descrizione", callback_data="field_text"
            )
        ],
        [
            InlineKeyboardButton(
                date_label, callback_data="field_date"
            )
        ]
    ])

    await query.message.reply_text(
        f"✏️ MODIFICA ELEMENTO #{item_id}\n\n"
        "Che cosa vuoi modificare?",
        reply_markup=keyboard
    )

    return EDIT_FIELD


async def choose_edit_field(update, context):
    query = update.callback_query
    await query.answer()

    field = query.data.replace("field_", "")
    context.user_data["edit_field"] = field

    kind = context.user_data["edit_kind"]

    if field == "text":
        await query.message.reply_text(
            "Scrivi la nuova descrizione completa:"
        )
        return EDIT_TEXT

    if kind == "tasks":
        prompt = (
            "Inserisci la nuova data di svolgimento "
            "nel formato GG/MM/AAAA:"
        )
    else:
        prompt = (
            "Inserisci la nuova data di revisione "
            "nel formato GG/MM/AAAA.\n\n"
            "Per cancellare la scadenza, scrivi -"
        )

    await query.message.reply_text(prompt)
    return EDIT_DATE


async def save_edit_text(update, context):
    if not authorized(update.effective_user):
        await deny(update)
        return ConversationHandler.END

    text = update.message.text.strip()

    if not text:
        await update.message.reply_text("Descrizione non valida.")
        return EDIT_TEXT

    kind = context.user_data["edit_kind"]
    item_id = context.user_data["edit_id"]

    with db() as con:
        result = con.execute(
            f"UPDATE {kind} SET text = ?, author = ?, created = ? "
            "WHERE id = ?",
            (
                text,
                update.effective_user.full_name,
                now_text(),
                item_id
            )
        )

    if result.rowcount == 0:
        await update.message.reply_text("Elemento non trovato.")
    else:
        await update.message.reply_text(
            "✅ Descrizione modificata correttamente.",
            reply_markup=main_keyboard()
        )

    context.user_data.clear()
    return ConversationHandler.END


async def save_edit_date(update, context):
    if not authorized(update.effective_user):
        await deny(update)
        return ConversationHandler.END

    kind = context.user_data["edit_kind"]
    item_id = context.user_data["edit_id"]
    value = update.message.text.strip()

    if kind == "tasks":
        parsed = parse_date(value)

        if not parsed:
            await update.message.reply_text(
                "Data non valida. Usa GG/MM/AAAA."
            )
            return EDIT_DATE

        column = "event_date"

    else:
        if value == "-":
            parsed = None
        else:
            parsed = parse_date(value)

            if not parsed:
                await update.message.reply_text(
                    "Data non valida. Usa GG/MM/AAAA oppure -."
                )
                return EDIT_DATE

        column = "revision_date"

    with db() as con:
        result = con.execute(
            f"UPDATE {kind} SET {column} = ?, notified = 0, "
            "author = ?, created = ? WHERE id = ?",
            (
                parsed,
                update.effective_user.full_name,
             
