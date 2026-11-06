
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
        "Gestione attività, mezzi e attrezzature "
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
                "🚤 Mezzi nautici", callback_data="boats"
            ),
            InlineKeyboardButton(
                "🤿 Attrezzature", callback_data="equipment"
            )
        ],
        [
            InlineKeyboardButton(
                "📋 Attività", callback_data="tasks"
            )
        ],
        [
            InlineKeyboardButton(
                "🌐 Meteo marino",
                url="https://www.comune.venezia.it/it/content/previsioni-onda-alto-adriatico-0"
            )
        ],
        [
            InlineKeyboardButton(
                "➕ Inserisci informazioni", callback_data="addmenu"
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
# INSERIMENTO INFORMAZIONI
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
                "🤿 Nuova attrezzatura", callback_data="add_equipment"
            )
        ],
        [
            InlineKeyboardButton(
                "🚤 Nuovo mezzo nautico", callback_data="add_boats"
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
    context.user_data["kind"] = kind

    prompts = {
        "tasks": "📋 Descrivi l'attività da registrare:",
        "equipment": "🤿 Inserisci nome, matricola e dettagli dell'attrezzatura:",
        "boats": "🚤 Inserisci nome, matricola e dettagli del mezzo nautico:"
    }

    await query.message.reply_text(prompts[kind])
    return WAITING_TEXT


async def save_new_text(update, context):
    if not authorized(update.effective_user):
        await deny(update)
        return ConversationHandler.END

    text = update.message.text.strip()

    if not text:
        await update.message.reply_text("Inserisci una descrizione valida.")
        return WAITING_TEXT

    context.user_data["new_text"] = text
    kind = context.user_data.get("kind")

    if kind == "tasks":
        prompt = (
            "📅 Inserisci il giorno di svolgimento dell'attività "
            "nel formato GG/MM/AAAA:"
        )
    else:
        prompt = (
            "🔧 Inserisci la data della prossima revisione "
            "nel formato GG/MM/AAAA.\n\n"
            "Se la data non è ancora prevista, scrivi -"
        )

    await update.message.reply_text(prompt)
    return WAITING_DATE


async def save_new_date(update, context):
    if not authorized(update.effective_user):
        await deny(update)
        return ConversationHandler.END

    kind = context.user_data.get("kind")
    text = context.user_data.get("new_text", "")
    value = update.message.text.strip()

    if kind == "tasks":
        parsed = parse_date(value)

        if not parsed:
            await update.message.reply_text(
                "❌ Data non valida. Usa il formato GG/MM/AAAA."
            )
            return WAITING_DATE

        event_date = parsed
        revision_date = None

    else:
        if value == "-":
            parsed = None
        else:
            parsed = parse_date(value)

            if not parsed:
                await update.message.reply_text(
                    "❌ Data non valida. Usa GG/MM/AAAA oppure -."
                )
                return WAITING_DATE

        event_date = None
        revision_date = parsed

    user = update.effective_user
    author = user.full_name
    created = now_text()

    with db() as con:
        if kind == "tasks":
            con.execute(
                "INSERT INTO tasks "
                "(text, author, created, event_date, notified) "
                "VALUES (?, ?, ?, ?, 0)",
                (text, author, created, event_date)
            )
        else:
            con.execute(
                f"INSERT INTO {kind} "
                "(text, author, created, revision_date, notified) "
                "VALUES (?, ?, ?, ?, 0)",
                (text, author, created, revision_date)
            )

    context.user_data.clear()

    await update.message.reply_text(
        "✅ Registrazione inserita correttamente!",
        reply_markup=main_keyboard()
    )

    return ConversationHandler.END


# ==================================================
# MODIFICA DI ATTIVITÀ, ATTREZZATURE E MEZZI
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
                now_text(),
                item_id
            )
        )

    if result.rowcount == 0:
        await update.message.reply_text("Elemento non trovato.")
    else:
        await update.message.reply_text(
            "✅ Data aggiornata correttamente.",
            reply_markup=main_keyboard()
        )

    context.user_data.clear()
    return ConversationHandler.END


async def cancel(update, context):
    context.user_data.clear()

    await update.message.reply_text(
        "Operazione annullata.",
        reply_markup=main_keyboard()
    )

    return ConversationHandler.END


# ==================================================
# CALENDARIO MENSILE
# ==================================================

def month_events(year, month):
    first = date(year, month, 1)
    last_day = calendar.monthrange(year, month)[1]
    last = date(year, month, last_day)

    start = first.isoformat()
    end = last.isoformat()

    events = {}

    with db() as con:
        rows = con.execute(
            "SELECT event_date, text FROM tasks "
            "WHERE event_date BETWEEN ? AND ?",
            (start, end)
        ).fetchall()

        for event_date, text in rows:
            events.setdefault(event_date, []).append(
                ("📋 Attività", text)
            )

        rows = con.execute(
            "SELECT revision_date, text FROM equipment "
            "WHERE revision_date BETWEEN ? AND ?",
            (start, end)
        ).fetchall()

        for event_date, text in rows:
            events.setdefault(event_date, []).append(
                ("🤿 Revisione attrezzatura", text)
            )

        rows = con.execute(
            "SELECT revision_date, text FROM boats "
            "WHERE revision_date BETWEEN ? AND ?",
            (start, end)
        ).fetchall()

        for event_date, text in rows:
            events.setdefault(event_date, []).append(
                ("🚤 Revisione mezzo nautico", text)
            )

    return events


def calendar_keyboard(year, month):
    events = month_events(year, month)
    today = today_local()

    keyboard = [[
        InlineKeyboardButton(day, callback_data="noop")
        for day in ["Lu", "Ma", "Me", "Gi", "Ve", "Sa", "Do"]
    ]]

    for week in calendar.monthcalendar(year, month):
        row = []

        for day in week:
            if day == 0:
                row.append(
                    InlineKeyboardButton("·", callback_data="noop")
                )
            else:
                selected_date = date(year, month, day)
                current_date = selected_date.isoformat()

                # Indicatori indipendenti:
                # 🔵 giorno corrente
                # 🟡 attività
                # 🔴 scadenze di revisione

                markers = ""

                if selected_date == today:
                    markers += "🔵"

                day_events = events.get(current_date, [])

                has_activity = any(
                    label == "📋 Attività"
                    for label, text in day_events
                )

                has_revision = any(
                    label in (
                        "🤿 Revisione attrezzatura",
                        "🚤 Revisione mezzo nautico"
                    )
                    for label, text in day_events
                )

                if has_activity:
                    markers += "🟡"

                if has_revision:
                    markers += "🔴"

                label = str(day)

                if markers:
                    label += " " + markers

                row.append(
                    InlineKeyboardButton(
                        label,
                        callback_data=f"calday_{current_date}"
                    )
                )

        keyboard.append(row)

    previous_month = date(year, month, 1) - timedelta(days=1)
    next_month = (
        date(year, month, calendar.monthrange(year, month)[1])
        + timedelta(days=1)
    )

    keyboard.append([
        InlineKeyboardButton(
            "⬅️",
            callback_data=f"calprev_{previous_month.year}-{previous_month.month}"
        ),
        InlineKeyboardButton(
            "📅 Oggi",
            callback_data=f"caltoday_{today.year}-{today.month}"
        ),
        InlineKeyboardButton(
            "➡️",
            callback_data=f"calnext_{next_month.year}-{next_month.month}"
        )
    ])

    keyboard.append([
        InlineKeyboardButton(
            "➕ Nuova attività", callback_data="add_tasks"
        )
    ])

    return InlineKeyboardMarkup(keyboard)


def month_title(year, month):
    names = [
        "Gennaio", "Febbraio", "Marzo", "Aprile",
        "Maggio", "Giugno", "Luglio", "Agosto",
        "Settembre", "Ottobre", "Novembre", "Dicembre"
    ]

    return f"📅 CALENDARIO - {names[month - 1]} {year}"


async def render_calendar(message, year, month, edit=False):
    text = (
        month_title(year, month)
        + "\n\n"
        + "🔵 Oggi\n"
        + "🟡 Attività programmate\n"
        + "🔴 Scadenze di mezzi e attrezzature\n\n"
        + "Seleziona un giorno per vedere i dettagli."
    )

    keyboard = calendar_keyboard(year, month)

    if edit:
        await message.edit_text(
            text,
            reply_markup=keyboard
        )
    else:
        await message.reply_text(
            text,
            reply_markup=keyboard
        )


async def show_calendar_day(query, selected_date):
    try:
        date.fromisoformat(selected_date)
    except ValueError:
        await query.message.reply_text("Data non valida.")
        return

    events = []

    with db() as con:
        rows = con.execute(
            "SELECT id, text FROM tasks WHERE event_date = ?",
            (selected_date,)
        ).fetchall()

        for item_id, text in rows:
            events.append(
                ("tasks", item_id, "📋 Attività", text)
            )

        rows = con.execute(
            "SELECT id, text FROM equipment WHERE revision_date = ?",
            (selected_date,)
        ).fetchall()

        for item_id, text in rows:
            events.append(
                ("equipment", item_id, "🤿 Revisione attrezzatura", text)
            )

        rows = con.execute(
            "SELECT id, text FROM boats WHERE revision_date = ?",
            (selected_date,)
        ).fetchall()

        for item_id, text in rows:
            events.append(
                ("boats", item_id, "🚤 Revisione mezzo nautico", text)
            )

    output = (
        f"📅 IMPEGNI DEL {display_date(selected_date)}\n\n"
    )

    if not events:
        output += "Nessuna attività o revisione programmata."
    else:
        for kind, item_id, label, text in events:
            output += f"{label}\n{text}\n\n"

    keyboard = []

    for kind, item_id, label, text in events:
        keyboard.append([
            InlineKeyboardButton(
                f"✏️ Modifica #{item_id} - {label}",
                callback_data=f"edit_{kind}_{item_id}"
            )
        ])

    keyboard.append([
        InlineKeyboardButton(
            "↩️ Torna al calendario",
            callback_data=f"calback_{selected_date[:7]}"
        )
    ])

    await query.message.reply_text(
        output,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ==================================================
# NOTIFICHE AUTOMATICHE
# ==================================================

async def send_due_notifications(application):
    if not GROUP_CHAT_ID:
        print("GROUP_CHAT_ID non configurato.")
        return False

    try:
        chat_id = int(GROUP_CHAT_ID)
    except ValueError:
        print("GROUP_CHAT_ID non valido.")
        return False

    today = today_local()

    activity_date = (today + timedelta(days=10)).isoformat()
    revision_date = (today + timedelta(days=14)).isoformat()

    sections = []
    updates = []

    with db() as con:
        tasks = con.execute(
            "SELECT id, text FROM tasks "
            "WHERE event_date = ? AND notified = 0",
            (activity_date,)
        ).fetchall()

        equipment = con.execute(
            "SELECT id, text FROM equipment "
            "WHERE revision_date = ? AND notified = 0",
            (revision_date,)
        ).fetchall()

        boats = con.execute(
            "SELECT id, text FROM boats "
            "WHERE revision_date = ? AND notified = 0",
            (revision_date,)
        ).fetchall()

    if tasks:
        section = "📋 ATTIVITÀ TRA 10 GIORNI\n"
        for item_id, text in tasks:
            section += f"• {text}\n"
            updates.append(("tasks", item_id))
        sections.append(section)

    if equipment:
        section = "🤿 REVISIONI ATTREZZATURE TRA 14 GIORNI\n"
        for item_id, text in equipment:
            section += f"• {text}\n"
            updates.append(("equipment", item_id))
        sections.append(section)

    if boats:
        section = "🚤 REVISIONI MEZZI NAUTICI TRA 14 GIORNI\n"
        for item_id, text in boats:
            section += f"• {text}\n"
            updates.append(("boats", item_id))
        sections.append(section)

    if not sections:
        return True

    message = (
        "🔔 PROMEMORIA NUCLEO SOMMOZZATORI\n\n"
        + "\n\n".join(sections)
        + "\n\n📅 Promemoria automatico del NUCLEO BOT."
    )

    try:
        await application.bot.send_message(
            chat_id=chat_id,
            text=message
        )

        with db() as con:
            for kind, item_id in updates:
                con.execute(
                    f"UPDATE {kind} SET notified = 1 WHERE id = ?",
                    (item_id,)
                )

        print("Notifiche inviate correttamente.")
        return True

    except Exception as error:
        print(f"Errore invio notifiche: {error}")
        return False


async def notification_loop(application):
    last_notification_date = None

    while True:
        now = datetime.now(TZ)
        today = now.date()

        if now.hour >= 8 and last_notification_date != today:
            success = await send_due_notifications(application)

            if success:
                last_notification_date = today

                tomorrow = today + timedelta(days=1)
                next_run = datetime.combine(
                    tomorrow,
                    time(8, 0),
                    tzinfo=TZ
                )
                seconds = (next_run - datetime.now(TZ)).total_seconds()
            else:
                seconds = 300

        else:
            if last_notification_date == today:
                tomorrow = today + timedelta(days=1)
                next_run = datetime.combine(
                    tomorrow,
                    time(8, 0),
                    tzinfo=TZ
                )
            else:
                next_run = datetime.combine(
                    today,
                    time(8, 0),
                    tzinfo=TZ
                )

                if now >= next_run:
                    next_run += timedelta(days=1)

            seconds = (next_run - now).total_seconds()

        await asyncio.sleep(max(1, seconds))


async def post_init(application):
    application.bot_data["notification_task"] = asyncio.create_task(
        notification_loop(application)
    )


async def post_shutdown(application):
    task = application.bot_data.get("notification_task")

    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


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

    if action == "noop":
        return

    if action == "menu":
        await query.message.reply_text(
            "🤿 MENU PRINCIPALE",
            reply_markup=main_keyboard()
        )

    elif action == "addmenu":
        await add_menu(update)

    elif action in TABLES:
        await show_list(update, action)

    elif action == "calendar":
        today = today_local()
        await render_calendar(
            query.message,
            today.year,
            today.month
        )

    elif action.startswith("calday_"):
        selected_date = action.replace("calday_", "")
        await show_calendar_day(query, selected_date)

    elif action.startswith("calprev_"):
        year, month = map(
            int, action.replace("calprev_", "").split("-")
        )
        await render_calendar(query.message, year, month, edit=True)

    elif action.startswith("calnext_"):
        year, month = map(
            int, action.replace("calnext_", "").split("-")
        )
        await render_calendar(query.message, year, month, edit=True)

    elif action.startswith("caltoday_"):
        year, month = map(
            int, action.replace("caltoday_", "").split("-")
        )
        await render_calendar(query.message, year, month, edit=True)

    elif action.startswith("calback_"):
        year, month = map(
            int, action.replace("calback_", "").split("-")
        )
        await render_calendar(query.message, year, month)


# ==================================================
# AVVIO
# ==================================================

def main():
    if not TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN non configurato."
        )

    init_db()

    if not ALLOWED_USERS:
        print("ATTENZIONE: nessun utente autorizzato configurato.")

    app = (
        Application.builder()
        .token(TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    app.add_handler(CommandHandler("id", get_id))
    app.add_handler(CommandHandler("chatid", get_chat_id))
    app.add_handler(CommandHandler("start", start))

    app.add_handler(
        CallbackQueryHandler(
            assistant_start,
            pattern=r"^assistant$"
        )
    )

    add_conversation = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(
                begin_add,
                pattern=r"^add_(tasks|equipment|boats)$"
            )
        ],
        states={
            WAITING_TEXT: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    save_new_text
                )
            ],
            WAITING_DATE: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    save_new_date
                )
            ]
        },
        fallbacks=[
            CommandHandler("annulla", cancel)
        ],
        allow_reentry=True
    )

    edit_conversation = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(
                begin_edit,
                pattern=r"^edit_(tasks|equipment|boats)_\d+$"
            )
        ],
        states={
            EDIT_FIELD: [
                CallbackQueryHandler(
                    choose_edit_field,
                    pattern=r"^field_(text|date)$"
                )
            ],
            EDIT_TEXT: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    save_edit_text
                )
            ],
            EDIT_DATE: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    save_edit_date
                )
            ]
        },
        fallbacks=[
            CommandHandler("annulla", cancel)
        ],
        allow_reentry=True
    )

    app.add_handler(add_conversation)
    app.add_handler(edit_conversation)
    app.add_handler(CallbackQueryHandler(buttons))

    print("NUCLEO BOT avviato.")
    app.run_polling()


if __name__ == "__main__":
    main()
