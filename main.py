
import os
import sqlite3
from pathlib import Path
from datetime import datetime

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

# Cartella dei manuali PDF
DOCS_DIR = Path(__file__).resolve().parent / "documenti"

# Nome esatto del PDF
PDF_NAME = "SMM   6 Norme per le immersioni - ediz. ott 2017.pdf"

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
            InlineKeyboardButton(
                "📅 Calendario", callback_data="calendar"
            ),
            InlineKeyboardButton(
                "🤖 Assistente documentale", callback_data="assistant"
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
            ),
            InlineKeyboardButton(
                "🌊 Dive Log", callback_data="dives"
            )
        ],
        [
            InlineKeyboardButton(
                "📊 Statistiche", callback_data="stats"
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

# ==================================================
# APERTURA PDF SMM 6
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
            "Verifica che il file sia presente nella cartella "
            "'documenti' accanto a main.py e che il nome sia corretto."
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
            "❌ Non è stato possibile inviare il PDF. Riprova più tardi."
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
                "🚤 Nuovo mezzo", callback_data="add_boats"
            )
        ],
        [
            InlineKeyboardButton(
                "🌊 Nuova immersione", callback_data="add_dives"
            )
        ],
        [
            InlineKeyboardButton(
                "↩️ Menu", callback_data="menu"
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
        "tasks": "Descrivi l'attività da registrare:",
        "equipment": "Inserisci attrezzatura, matricola e stato:",
        "boats": "Inserisci mezzo, caratteristiche e stato:",
        "dives": "Inserisci data, luogo e dettagli dell'immersione:"
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
        await update.message.reply_text(
            "Inserisci un testo valido."
        )
        return WAITING_TEXT

    if kind not in TABLES:
        await update.message.reply_text(
            "Tipo di informazione non valido."
        )
        return ConversationHandler.END

    with db() as con:
        con.execute(
            f"INSERT INTO {kind} (text, author, created) "
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
        tasks = con.execute(
            "SELECT COUNT(*) FROM tasks"
        ).fetchone()[0]

        equipment = con.execute(
            "SELECT COUNT(*) FROM equipment"
        ).fetchone()[0]

        boats = con.execute(
            "SELECT COUNT(*) FROM boats"
        ).fetchone()[0]

        dives = con.execute(
            "SELECT COUNT(*) FROM dives"
        ).fetchone()[0]

    text = (
        "📊 STATISTICHE NUCLEO\n\n"
        f"📋 Attività registrate: {tasks}\n"
        f"🤿 Attrezzature registrate: {equipment}\n"
        f"🚤 Mezzi registrati: {boats}\n"
        f"🌊 Immersioni registrate: {dives}\n"
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

    elif action == "stats":
        await show_stats(update)

    elif action in TABLES:
        await show_list(update, action)

    elif action == "calendar":
        await query.message.reply_text(
            "📅 La funzione calendario non è ancora disponibile."
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
        print(
            "ATTENZIONE: nessun utente autorizzato configurato."
        )

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("id", get_id))
    app.add_handler(CommandHandler("start", start))

    # Apertura diretta del PDF
    app.add_handler(
        CallbackQueryHandler(
            assistant_start,
            pattern=r"^assistant$"
        )
    )

    # Inserimento informazioni
    add_conversation = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(
                begin_add,
                pattern=r"^add_(tasks|equipment|boats|dives)$"
            )
        ],
        states={
            WAITING_TEXT: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    save_item
                )
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
