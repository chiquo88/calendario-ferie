
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

PDF_SMM6 = "SMM   6 Norme per le immersioni - ediz. ott 2017.pdf"

PDF_RADIO_1 = "FS 3.2026 standardizzazione sigle radio.pdf"
PDF_RADIO_2 = "NUOVE SIGLE RADIO FunzionariPDF_260304_073500.pdf"

WAITING_TEXT = 1
WAITING_DATE = 2
EDIT_FIELD = 3
EDIT_TEXT = 4
EDIT_DATE = 5

LOC_CATEGORY_NAME = 6
LOC_SUBCATEGORY_NAME = 7
LOC_PLACE_NAME = 8
LOC_PLACE_ADDRESS = 9
LOC_PLACE_PHONE = 10

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

        CREATE TABLE IF NOT EXISTS location_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL COLLATE NOCASE UNIQUE,
            created TEXT,
            author TEXT
        );

        CREATE TABLE IF NOT EXISTS location_subcategories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category_id INTEGER NOT NULL,
            name TEXT NOT NULL COLLATE NOCASE,
            created TEXT,
            author TEXT,
            UNIQUE(category_id, name),
            FOREIGN KEY(category_id)
                REFERENCES location_categories(id)
        );

        CREATE TABLE IF NOT EXISTS useful_places (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category_id INTEGER NOT NULL,
            subcategory_id INTEGER,
            name TEXT,
            address TEXT,
            phone TEXT,
            created TEXT,
            author TEXT,
            FOREIGN KEY(category_id)
                REFERENCES location_categories(id),
            FOREIGN KEY(subcategory_id)
                REFERENCES location_subcategories(id)
        );
        """)

        add_column(con, "tasks", "event_date", "TEXT")
        add_column(con, "tasks", "notified", "INTEGER DEFAULT 0")

        add_column(con, "equipment", "revision_date", "TEXT")
        add_column(con, "equipment", "notified", "INTEGER DEFAULT 0")

        add_column(con, "boats", "revision_date", "TEXT")
        add_column(con, "boats", "notified", "INTEGER DEFAULT 0")

        # Categorie iniziali: vengono aggiunte solo se mancanti.
        initial_categories = [
            "Questura",
            "Camera iperbarica",
            "CNR",
            "Ca' Foscari",
            "Manutenzione attrezzature",
            "Sport/TempoLibero",
            "Magna/Bevi"
        ]

        for category in initial_categories:
            con.execute(
                "INSERT OR IGNORE INTO location_categories "
                "(name, created, author) VALUES (?, ?, ?)",
                (category, now_text(), "Sistema")
            )


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
                "📘 SMM6_17'", callback_data="assistant"
            )
        ],
        [
            InlineKeyboardButton(
                "📻 Sigle Radio", callback_data="radio_docs"
            )
        ],
        [
            InlineKeyboardButton(
                "📍 Luoghi & Numeri Utili",
                callback_data="locations"
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
# DOCUMENTI SMM6 E SIGLE RADIO
# ==================================================

async def send_pdf(query, filename, telegram_name, caption):
    pdf_path = DOCS_DIR / filename

    if not pdf_path.is_file():
        await query.message.reply_text(
            "⚠️ Documento non trovato.\n\n"
            f"Verifica che il file sia presente nella cartella "
            f"'documenti' accanto a main.py:\n\n{filename}"
        )
        return

    try:
        with pdf_path.open("rb") as pdf:
            await query.message.reply_document(
                document=pdf,
                filename=telegram_name,
                caption=caption
            )
    except Exception as error:
        print(f"Errore invio PDF {filename}: {error}")
        await query.message.reply_text(
            "❌ Non è stato possibile inviare il documento."
        )


async def assistant_start(update, context):
    if not authorized(update.effective_user):
        await deny(update)
        return

    query = update.callback_query
    await query.answer()

    await send_pdf(
        query,
        PDF_SMM6,
        "SMM6_17 - Norme per le immersioni.pdf",
        "📘 SMM6_17' - Norme per le immersioni"
    )


async def radio_documents_menu(update, context):
    query = update.callback_query
    await query.answer()

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📻 FS 3.2026 - Standardizzazione sigle radio",
                callback_data="radio_doc_1"
            )
        ],
        [
            InlineKeyboardButton(
                "📻 Nuove sigle radio Funzionari",
                callback_data="radio_doc_2"
            )
        ],
        [
            InlineKeyboardButton(
                "↩️ Menu principale", callback_data="menu"
            )
        ]
    ])

    await query.message.reply_text(
        "📻 SIGLE RADIO\n\n"
        "Seleziona il documento da consultare o scaricare:",
        reply_markup=keyboard
    )


async def send_radio_document(update, context):
    query = update.callback_query
    await query.answer()

    if query.data == "radio_doc_1":
        await send_pdf(
            query,
            PDF_RADIO_1,
            PDF_RADIO_1,
            "📻 FS 3.2026 - Standardizzazione sigle radio"
        )

    elif query.data == "radio_doc_2":
        await send_pdf(
            query,
            PDF_RADIO_2,
            PDF_RADIO_2,
            "📻 Nuove sigle radio Funzionari"
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
# LUOGHI & NUMERI UTILI
# ==================================================

def location_menu_keyboard():
    with db() as con:
        categories = con.execute(
            "SELECT id, name FROM location_categories "
            "ORDER BY name COLLATE NOCASE"
        ).fetchall()

    keyboard = []

    for category_id, name in categories:
        keyboard.append([
            InlineKeyboardButton(
                f"📂 {name}",
                callback_data=f"loccat_{category_id}"
            )
        ])

    keyboard.extend([
        [
            InlineKeyboardButton(
                "➕ Aggiungi categoria",
                callback_data="loc_add_category"
            )
        ],
        [
            InlineKeyboardButton(
                "↩️ Menu principale", callback_data="menu"
            )
        ]
    ])

    return InlineKeyboardMarkup(keyboard)


async def show_locations_menu(query):
    await query.message.reply_text(
        "📍 LUOGHI & NUMERI UTILI\n\n"
        "Seleziona una categoria oppure aggiungine una nuova:",
        reply_markup=location_menu_keyboard()
    )


async def show_location_category(query, category_id):
    with db() as con:
        category = con.execute(
            "SELECT name FROM location_categories WHERE id = ?",
            (category_id,)
        ).fetchone()

        if not category:
            await query.message.reply_text("Categoria non trovata.")
            return

        subcategories = con.execute(
            "SELECT id, name FROM location_subcategories "
            "WHERE category_id = ? ORDER BY name COLLATE NOCASE",
            (category_id,)
        ).fetchall()

        places = con.execute(
            "SELECT id, name, address, phone "
            "FROM useful_places "
            "WHERE category_id = ? AND subcategory_id IS NULL "
            "ORDER BY name COLLATE NOCASE, id",
            (category_id,)
        ).fetchall()

    keyboard = []

    for sub_id, name in subcategories:
        keyboard.append([
            InlineKeyboardButton(
                f"📁 {name}",
                callback_data=f"locsub_{sub_id}"
            )
        ])

    keyboard.extend([
        [
            InlineKeyboardButton(
                "➕ Aggiungi sottocategoria",
                callback_data=f"loc_add_subcat_{category_id}"
            )
        ],
        [
            InlineKeyboardButton(
                "➕ Aggiungi luogo/numero",
                callback_data=f"loc_add_place_cat_{category_id}"
            )
        ],
        [
            InlineKeyboardButton(
                "↩️ Torna alle categorie",
                callback_data="locations"
            )
        ]
    ])

    await query.message.reply_text(
        f"📂 {category[0]}\n\n"
        "Puoi consultare le voci già registrate, "
        "entrare in una sottocategoria oppure aggiungere nuovi elementi.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    await show_location_places(query, places)


async def show_location_subcategory(query, subcategory_id):
    with db() as con:
        row = con.execute(
            "SELECT name, category_id FROM location_subcategories "
            "WHERE id = ?",
            (subcategory_id,)
        ).fetchone()

        if not row:
            await query.message.reply_text(
                "Sottocategoria non trovata."
            )
            return

        name, category_id = row

        places = con.execute(
            "SELECT id, name, address, phone "
            "FROM useful_places "
            "WHERE subcategory_id = ? "
            "ORDER BY name COLLATE NOCASE, id",
            (subcategory_id,)
        ).fetchall()

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "➕ Aggiungi luogo/numero",
                callback_data=f"loc_add_place_sub_{subcategory_id}"
            )
        ],
        [
            InlineKeyboardButton(
                "↩️ Torna alla categoria",
                callback_data=f"loccat_{category_id}"
            )
        ]
    ])

    await query.message.reply_text(
        f"📁 {name}\n\n"
        "Luoghi e numeri registrati:",
        reply_markup=keyboard
    )

    await show_location_places(query, places)


async def show_location_places(query, places):
    if not places:
        await query.message.reply_text(
            "Nessun luogo o numero registrato."
        )
        return

    for place_id, name, address, phone in places:
        output = f"📌 {name or 'Nome non indicato'}\n"

        if address:
            output += f"📍 Indirizzo/posizione: {address}\n"

        if phone:
            output += f"☎️ Telefono: {phone}\n"

        await query.message.reply_text(output)


async def begin_location_add(update, context):
    if not authorized(update.effective_user):
        await deny(update)
        return ConversationHandler.END

    query = update.callback_query
    await query.answer()

    action = query.data

    if action == "loc_add_category":
        context.user_data["location_action"] = "category"

        await query.message.reply_text(
            "📂 Scrivi il nome della nuova categoria:"
        )
        return LOC_CATEGORY_NAME

    if action.startswith("loc_add_subcat_"):
        category_id = int(action.rsplit("_", 1)[1])

        context.user_data["location_action"] = "subcategory"
        context.user_data["location_category_id"] = category_id

        await query.message.reply_text(
            "📁 Scrivi il nome della nuova sottocategoria:"
        )
        return LOC_SUBCATEGORY_NAME

    if action.startswith("loc_add_place_cat_"):
        category_id = int(action.rsplit("_", 1)[1])

        context.user_data["location_action"] = "place"
        context.user_data["location_category_id"] = category_id
        context.user_data["location_subcategory_id"] = None

    elif action.startswith("loc_add_place_sub_"):
        subcategory_id = int(action.rsplit("_", 1)[1])

        with db() as con:
            row = con.execute(
                "SELECT category_id FROM location_subcategories "
                "WHERE id = ?",
                (subcategory_id,)
            ).fetchone()

        if not row:
            await query.message.reply_text(
                "Sottocategoria non trovata."
            )
            return ConversationHandler.END

        context.user_data["location_action"] = "place"
        context.user_data["location_category_id"] = row[0]
        context.user_data["location_subcategory_id"] = subcategory_id

    else:
        return ConversationHandler.END

    context.user_data["location_name"] = None
    context.user_data["location_address"] = None
    context.user_data["location_phone"] = None

    await query.message.reply_text(
        "📌 Inserisci il nome del luogo o del contatto.\n\n"
        "Se non vuoi indicarlo, scrivi -"
    )

    return LOC_PLACE_NAME


async def save_location_category(update, context):
    if not authorized(update.effective_user):
        await deny(update)
        return ConversationHandler.END

    name = update.message.text.strip()

    if not name or name == "-":
        await update.message.reply_text(
            "Il nome della categoria è obbligatorio. Riprova:"
        )
        return LOC_CATEGORY_NAME

    try:
        with db() as con:
            con.execute(
                "INSERT INTO location_categories "
                "(name, created, author) VALUES (?, ?, ?)",
                (
                    name,
                    now_text(),
                    update.effective_user.full_name
                )
            )

        await update.message.reply_text(
            f"✅ Categoria «{name}» aggiunta.",
            reply_markup=location_menu_keyboard()
        )

    except sqlite3.IntegrityError:
        await update.message.reply_text(
            "⚠️ Questa categoria esiste già."
        )

    context.user_data.clear()
    return ConversationHandler.END


async def save_location_subcategory(update, context):
    if not authorized(update.effective_user):
        await deny(update)
        return ConversationHandler.END

    name = update.message.text.strip()
    category_id = context.user_data.get("location_category_id")

    if not name or name == "-":
        await update.message.reply_text(
            "Il nome della sottocategoria è obbligatorio. Riprova:"
        )
        return LOC_SUBCATEGORY_NAME

    try:
        with db() as con:
            con.execute(
                "INSERT INTO location_subcategories "
                "(category_id, name, created, author) "
                "VALUES (?, ?, ?, ?)",
                (
                    category_id,
                    name,
                    now_text(),
                    update.effective_user.full_name
                )
            )

        await update.message.reply_text(
            f"✅ Sottocategoria «{name}» aggiunta."
        )

        await update.message.reply_text(
            "Puoi tornare alla categoria per consultare le voci.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "↩️ Torna alla categoria",
                    callback_data=f"loccat_{category_id}"
                )
            ]])
        )

    except sqlite3.IntegrityError:
        await update.message.reply_text(
            "⚠️ Questa sottocategoria esiste già."
        )

    context.user_data.clear()
    return ConversationHandler.END


async def save_location_place_name(update, context):
    if not authorized(update.effective_user):
        await deny(update)
        return ConversationHandler.END

    value = update.message.text.strip()
    context.user_data["location_name"] = (
        None if value == "-" else value
    )

    await update.message.reply_text(
        "📍 Inserisci l'indirizzo o la posizione.\n\n"
        "Puoi scrivere un indirizzo, una località o una descrizione. "
        "Se non vuoi indicarlo, scrivi -"
    )

    return LOC_PLACE_ADDRESS


async def save_location_place_address(update, context):
    if not authorized(update.effective_user):
        await deny(update)
        return ConversationHandler.END

    value = update.message.text.strip()
    context.user_data["location_address"] = (
        None if value == "-" else value
    )

    await update.message.reply_text(
        "☎️ Inserisci il numero di telefono.\n\n"
        "Se non vuoi indicarlo, scrivi -"
    )

    return LOC_PLACE_PHONE


async def save_location_place_phone(update, context):
    if not authorized(update.effective_user):
        await deny(update)
        return ConversationHandler.END

    value = update.message.text.strip()
    phone = None if value == "-" else value

    category_id = context.user_data["location_category_id"]
    subcategory_id = context.user_data.get(
        "location_subcategory_id"
    )

    name = context.user_data.get("location_name")
    address = context.user_data.get("location_address")

    with db() as con:
        con.execute(
            "INSERT INTO useful_places "
            "(category_id, subcategory_id, name, address, phone, "
            "created, author) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                category_id,
                subcategory_id,
                name,
                address,
                phone,
                now_text(),
                update.effective_user.full_name
            )
        )

    context.user_data.clear()

    await update.message.reply_text(
        "✅ Luogo/contatto registrato correttamente.\n\n"
        "La scheda è ora consultabile da tutti gli utenti autorizzati.",
        reply_markup=main_keyboard()
    )

    return ConversationHandler.END


# ==================================================
# VISUALIZZAZIONE ELENCHI ATTIVITÀ
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
    if not authorized(update.effective_user):
        await deny(update)
        return ConversationHandler.END

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
            "SELECT reminder_date, text FROM reminders "
            "WHERE reminder_date BETWEEN ? AND ?",
            (start, end)
        ).fetchall()

        for reminder_date, text in rows:
            events.setdefault(reminder_date, []).append(
                ("🔔 Promemoria", text)
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

                markers = ""

                if selected_date == today:
                    markers += "👉"

                day_events = events.get(current_date, [])

                has_activity = any(
                    label == "📋 Attività"
                    for label, text in day_events
                )

                has_reminder = any(
                    label == "🔔 Promemoria"
                    for label, text in day_events
                )

                if has_activity:
                    markers += "📋"

                if has_reminder:
                    markers += "🔔"

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
        ),
        InlineKeyboardButton(
            "🔔 Promemoria", callback_data="add_reminder"
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
        + "👉 Oggi\n"
        + "📋 Attività programmate\n"
        + "🔔 Promemoria con notifica alle 08:00\n\n"
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
            "SELECT id, text FROM reminders WHERE reminder_date = ?",
            (selected_date,)
        ).fetchall()

        for item_id, text in rows:
            events.append(
                ("reminders", item_id, "🔔 Promemoria", text)
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
        output += "Nessuna attività o promemoria programmato."
    else:
        for kind, item_id, label, text in events:
            output += f"{label}\n{text}\n\n"

    keyboard = []

    for kind, item_id, label, text in events:
        if kind == "tasks":
            keyboard.append([
                InlineKeyboardButton(
                    f"✏️ Modifica attività #{item_id}",
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
# RIEPILOGO SETTIMANALE DEL GIOVEDÌ
# ==================================================

def next_week_range(reference_date):
    days_until_monday = 7 - reference_date.weekday()
    monday = reference_date + timedelta(days=days_until_monday)
    sunday = monday + timedelta(days=6)

    return monday, sunday


async def send_weekly_summary(application, today):
    monday, sunday = next_week_range(today)

    week_key = monday.isoformat()

    with db() as con:
        already_sent = con.execute(
            "SELECT 1 FROM notification_log "
            "WHERE notification_type = 'weekly' "
            "AND notification_key = ?",
            (week_key,)
        ).fetchone()

        if already_sent:
            return True

        tasks = con.execute(
            "SELECT event_date, text FROM tasks "
            "WHERE event_date BETWEEN ? AND ? "
            "ORDER BY event_date, id",
            (monday.isoformat(), sunday.isoformat())
        ).fetchall()

    weekday_names = [
        "Lunedì", "Martedì", "Mercoledì", "Giovedì",
        "Venerdì", "Sabato", "Domenica"
    ]

    message = (
        "📋 RIEPILOGO SETTIMANALE - NUCLEO SOMMOZZATORI\n\n"
        f"📅 Settimana dal {monday.strftime('%d/%m/%Y')} "
        f"al {sunday.strftime('%d/%m/%Y')}\n\n"
    )

    if not tasks:
        message += "Nessuna attività programmata per la prossima settimana."
    else:
        current_date = None

        for event_date, text in tasks:
            task_day = date.fromisoformat(event_date)

            if event_date != current_date:
                current_date = event_date
                weekday = weekday_names[task_day.weekday()]

                message += (
                    f"\n📌 {weekday} {task_day.strftime('%d/%m/%Y')}\n"
                )

            message += f"• {text}\n"

    message += "\n🤿 NUCLEO BOT"

    try:
        await application.bot.send_message(
            chat_id=int(GROUP_CHAT_ID),
            text=message
        )

        with db() as con:
            con.execute(
                "INSERT OR IGNORE INTO notification_log "
                "(notification_type, notification_key, sent_at) "
                "VALUES ('weekly', ?, ?)",
                (week_key, now_text())
            )

        print(f"Riepilogo settimanale inviato per la settimana {week_key}.")
        return True

    except Exception as error:
        print(f"Errore invio riepilogo settimanale: {error}")
        return False


# ==================================================
# NOTIFICHE PROMEMORIA
# ==================================================

async def send_daily_reminders(application, today):
    today_string = today.isoformat()

    with db() as con:
        reminders = con.execute(
            "SELECT id, text, author FROM reminders "
            "WHERE reminder_date = ? AND notified = 0 "
            "ORDER BY id",
            (today_string,)
        ).fetchall()

    if not reminders:
        return True

    message = (
        "🔔 PROMEMORIA DEL GIORNO - NUCLEO SOMMOZZATORI\n\n"
        f"📅 {today.strftime('%d/%m/%Y')}\n\n"
    )

    for item_id, text, author in reminders:
        message += f"• {text}\n"

    message += "\n🤿 NUCLEO BOT"

    try:
        await application.bot.send_message(
            chat_id=int(GROUP_CHAT_ID),
            text=message
        )

        with db() as con:
            for item_id, text, author in reminders:
                con.execute(
                    "UPDATE reminders SET notified = 1 WHERE id = ?",
                    (item_id,)
                )

        print("Promemoria giornalieri inviati correttamente.")
        return True

    except Exception as error:
        print(f"Errore invio promemoria: {error}")
        return False


# ==================================================
# GESTIONE NOTIFICHE DELLE ORE 08:00
# ==================================================

async def process_morning_notifications(application):
    if not GROUP_CHAT_ID:
        print("GROUP_CHAT_ID non configurato.")
        return False

    try:
        int(GROUP_CHAT_ID)
    except ValueError:
        print("GROUP_CHAT_ID non valido.")
        return False

    today = today_local()
    success = True

    reminders_ok = await send_daily_reminders(application, today)

    if not reminders_ok:
        success = False

    if today.weekday() == 3:
        weekly_ok = await send_weekly_summary(application, today)

        if not weekly_ok:
            success = False

    return success


async def notification_loop(application):
    while True:
        now = datetime.now(TZ)

        if now.time() >= time(8, 0):
            success = await process_morning_notifications(application)

            if success:
                tomorrow = now.date() + timedelta(days=1)

                next_run = datetime.combine(
                    tomorrow,
                    time(8, 0),
                    tzinfo=TZ
                )

                seconds = (
                    next_run - datetime.now(TZ)
                ).total_seconds()
            else:
                seconds = 300

        else:
            next_run = datetime.combine(
                now.date(),
                time(8, 0),
                tzinfo=TZ
            )

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

    elif action == "tasks":
        await show_list(update, action)

    elif action == "calendar":
        today = today_local()

        await render_calendar(
            query.message,
            today.year,
            today.month
        )

    elif action == "locations":
        await show_locations_menu(query)

    elif action.startswith("loccat_"):
        category_id = int(action.replace("loccat_", ""))
        await show_location_category(query, category_id)

    elif action.startswith("locsub_"):
        subcategory_id = int(action.replace("locsub_", ""))
        await show_location_subcategory(query, subcategory_id)

    elif action == "radio_docs":
        await radio_documents_menu(update, context)

    elif action in ("radio_doc_1", "radio_doc_2"):
        await send_radio_document(update, context)

    elif action.startswith("calday_"):
        selected_date = action.replace("calday_", "")
        await show_calendar_day(query, selected_date)

    elif action.startswith("calprev_"):
        year, month = map(
            int, action.replace("calprev_", "").split("-")
        )

        await render_calendar(
            query.message, year, month, edit=True
        )

    elif action.startswith("calnext_"):
        year, month = map(
            int, action.replace("calnext_", "").split("-")
        )

        await render_calendar(
            query.message, year, month, edit=True
        )

    elif action.startswith("caltoday_"):
        year, month = map(
            int, action.replace("caltoday_", "").split("-")
        )

        await render_calendar(
            query.message, year, month, edit=True
        )

    elif action.startswith("calback_"):
        year, month = map(
            int, action.replace("calback_", "").split("-")
        )

        await render_calendar(
            query.message, year, month
        )


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
                pattern=r"^add_(tasks|reminder)$"
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

    location_conversation = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(
                begin_location_add,
                pattern=(
                    r"^loc_add_category$|"
                    r"^loc_add_subcat_\d+$|"
                    r"^loc_add_place_cat_\d+$|"
                    r"^loc_add_place_sub_\d+$"
                )
            )
        ],
        states={
            LOC_CATEGORY_NAME: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    save_location_category
                )
            ],
            LOC_SUBCATEGORY_NAME: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    save_location_subcategory
                )
            ],
            LOC_PLACE_NAME: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    save_location_place_name
                )
            ],
            LOC_PLACE_ADDRESS: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    save_location_place_address
                )
            ],
            LOC_PLACE_PHONE: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    save_location_place_phone
                )
            ]
        },
        fallbacks=[
            CommandHandler("annulla", cancel)
        ],
        allow_reentry=True
    )

    # Prima viene gestita la conversazione dei Luoghi e Numeri Utili
app.add_handler(location_conversation)

# Seguono le altre conversazioni
app.add_handler(add_conversation)
app.add_handler(edit_conversation)

app.add_handler(CallbackQueryHandler(buttons))
    
    print("NUCLEO BOT avviato.")

    app.run_polling()


if __name__ == "__main__":
    main()
