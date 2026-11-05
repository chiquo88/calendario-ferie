
import os
import re
import sqlite3
import unicodedata
from pathlib import Path
from datetime import datetime

from pypdf import PdfReader

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

# Cartella in cui conservare i manuali PDF
DOCS_DIR = DATA_DIR / "documenti"
DOCS_DIR.mkdir(parents=True, exist_ok=True)

WAITING_TEXT = 1
AI_WAITING = 2

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
# ASSISTENTE DOCUMENTALE
# ==================================================

# Parole comuni da ignorare durante la ricerca
STOPWORDS = {
    "che", "chi", "come", "cosa", "quale", "quali",
    "quando", "dove", "perche", "perché", "sono",
    "della", "delle", "degli", "dello", "dell",
    "dalla", "dalle", "dagli", "nella", "nelle",
    "negli", "nello", "alla", "alle", "allo",
    "agli", "con", "per", "tra", "fra", "una",
    "uno", "gli", "dei", "del", "dai", "dal",
    "non", "nel", "nei", "sul", "sulla", "sulle",
    "anche", "deve", "devono", "puo", "può",
    "possono", "essere", "avere", "sono", "si",
    "il", "lo", "la", "i", "le", "e", "a", "da",
    "di", "in", "un", "ed", "o", "al", "ad"
}

def normalize(text):
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(
        c for c in text if not unicodedata.combining(c)
    )
    return text

def query_terms(query):
    words = re.findall(r"[a-z0-9]{3,}", normalize(query))
    return [w for w in words if w not in STOPWORDS]

def extract_excerpt(text, terms, max_chars=1100):
    clean = re.sub(r"\s+", " ", text).strip()

    if len(clean) <= max_chars:
        return clean

    normalized = normalize(clean)
    positions = [
        normalized.find(term)
        for term in terms
        if normalized.find(term) >= 0
    ]

    if not positions:
        return clean[:max_chars] + "..."

    start = max(0, min(positions) - 250)
    end = min(len(clean), start + max_chars)

    excerpt = clean[start:end]

    if start > 0:
        excerpt = "..." + excerpt
    if end < len(clean):
        excerpt += "..."

    return excerpt

def search_documents(question):
    terms = query_terms(question)

    if not terms:
        return [], 0

    results = []
    pdf_files = list(DOCS_DIR.rglob("*.pdf"))

    for pdf_path in pdf_files:
        try:
            reader = PdfReader(str(pdf_path))

            for page_number, page in enumerate(reader.pages, start=1):
                text = page.extract_text() or ""

                if not text.strip():
                    continue

                normalized = normalize(text)

                score = sum(
                    normalized.count(term)
                    for term in terms
                )

                if score > 0:
                    results.append({
                        "file": pdf_path.name,
                        "page": page_number,
                        "score": score,
                        "text": extract_excerpt(text, terms)
                    })

        except Exception as error:
            print(
                f"Errore lettura PDF {pdf_path.name}: {error}"
            )

    results.sort(
        key=lambda item: item["score"],
        reverse=True
    )

    return results[:4], len(pdf_files)

async def assistant_start(update, context):
    if not authorized(update.effective_user):
        await deny(update)
        return ConversationHandler.END

    query = update.callback_query
    await query.answer()

    context.user_data["assistant_active"] = True

    await query.message.reply_text(
        "🤖 ASSISTENTE DOCUMENTALE\n\n"
        "Scrivi la tua domanda sui manuali e sulle disposizioni "
        "caricate nell'archivio.\n\n"
        "Indicherò il documento e la pagina dei passaggi trovati.\n\n"
        "Per uscire scrivi /annulla."
    )

    return AI_WAITING

async def assistant_search(update, context):
    if not authorized(update.effective_user):
        await deny(update)
        return ConversationHandler.END

    question = update.message.text.strip()

    if not question:
        await update.message.reply_text(
            "Scrivi una domanda valida."
        )
        return AI_WAITING

    results, total_pdfs = search_documents(question)

    if total_pdfs == 0:
        await update.message.reply_text(
            "📂 L'archivio documentale è vuoto.\n\n"
            "Occorre prima caricare i manuali PDF nella cartella "
            "'documenti' del server."
        )
        return AI_WAITING

    if not results:
        await update.message.reply_text(
            "Non ho trovato nei documenti disponibili un passaggio "
            "che corrisponda alla domanda.\n\n"
            "Prova a formulare la domanda utilizzando parole "
            "più specifiche."
        )
        return AI_WAITING

    response = (
        "🔎 RISULTATI DELLA RICERCA\n\n"
        "I seguenti estratti sono stati individuati nei documenti. "
        "Non costituiscono una valutazione operativa.\n\n"
    )

    for index, item in enumerate(results, start=1):
        response += (
            f"📄 {item['file']}\n"
            f"📌 Pagina {item['page']}\n"
            f"{item['text']}\n\n"
            "──────────────────\n\n"
        )

    response += (
        "⚠️ Verifica sempre il testo integrale, l'edizione "
        "del documento e le disposizioni vigenti. "
        "La ricerca può non individuare tutti i passaggi pertinenti."
    )

    # Telegram accetta messaggi fino a 4096 caratteri
    if len(response) > 4000:
        response = response[:3950] + "\n\n[Risposta abbreviata]"

    await update.message.reply_text(response)

    return AI_WAITING

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

    # Assistente documentale
    assistant_conversation = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(
                assistant_start,
                pattern=r"^assistant$"
            )
        ],
        states={
            AI_WAITING: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    assistant_search
                )
            ]
        },
        fallbacks=[
            CommandHandler("annulla", cancel)
        ],
        allow_reentry=True
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

    app.add_handler(assistant_conversation)
    app.add_handler(add_conversation)
    app.add_handler(CallbackQueryHandler(buttons))

    print("NUCLEO BOT avviato.")
    app.run_polling()

if __name__ == "__main__":
    main()
        
