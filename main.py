
import os
import sqlite3
import calendar
from datetime import date, timedelta
from contextlib import closing

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
MAX_LAVORATORI = 10
MIN_PRESENTI = 4

DATA_DIR = "/data" if os.path.isdir("/data") else "."
DB = os.path.join(DATA_DIR, "ferie.db")


def database():
    with closing(sqlite3.connect(DB)) as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS lavoratori (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT UNIQUE NOT NULL
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS assenze (
                giorno TEXT NOT NULL,
                lavoratore_id INTEGER NOT NULL,
                PRIMARY KEY (giorno, lavoratore_id)
            )
        """)
        db.commit()


def lavoratori():
    with closing(sqlite3.connect(DB)) as db:
        return db.execute(
            "SELECT id, nome FROM lavoratori ORDER BY nome"
        ).fetchall()


def assenti(giorno):
    with closing(sqlite3.connect(DB)) as db:
        return db.execute(
            "SELECT lavoratore_id FROM assenze WHERE giorno=?",
            (giorno,)
        ).fetchall()


def conteggio(giorno):
    numero_assenti = len(assenti(giorno))
    return MAX_LAVORATORI - numero_assenti, numero_assenti


def testo_giorno(giorno):
    presenti, numero_assenti = conteggio(giorno)
    if presenti < MIN_PRESENTI:
        avviso = "🔴 ATTENZIONE: meno di 4 presenti!"
    else:
        avviso = "🟢 Presenza regolare"

    elenco = lavoratori()
    assenti_ids = [x[0] for x in assenti(giorno)]

    testo = (
        f"📅 {giorno}\n\n"
        f"👥 Presenti: {presenti}/{MAX_LAVORATORI}\n"
        f"🏖 Assenti: {numero_assenti}\n"
        f"{avviso}\n\n"
        "Seleziona un lavoratore per modificare la sua assenza:"
    )

    tastiera = []
    for ident, nome in elenco:
        simbolo = "🏖" if ident in assenti_ids else "🟢"
        tastiera.append([
            InlineKeyboardButton(
                f"{simbolo} {nome}",
                callback_data=f"t|{giorno}|{ident}"
            )
        ])

    tastiera.append([
        InlineKeyboardButton("⬅️ Torna al mese",
                             callback_data=f"m|{int(giorno[:4])}|{int(giorno[5:7])}")
    ])

    return testo, InlineKeyboardMarkup(tastiera)


def vista_mese(anno, mese):
    giorni = calendar.monthcalendar(anno, mese)
    nomi_mesi = [
        "Gennaio", "Febbraio", "Marzo", "Aprile",
        "Maggio", "Giugno", "Luglio", "Agosto",
        "Settembre", "Ottobre", "Novembre", "Dicembre"
    ]

    testo = f"📅 CALENDARIO FERIE\n{nomi_mesi[mese-1]} {anno}\n\n"
    testo += "🔴 = meno di 4 presenti\n"
    testo += "🟢 = almeno 4 presenti\n\n"

    tastiera = [
        [
            InlineKeyboardButton(g, callback_data="noop")
            for g in ["L", "M", "M", "G", "V", "S", "D"]
        ]
    ]

    for settimana in giorni:
        riga = []
        for numero in settimana:
            if numero == 0:
                riga.append(InlineKeyboardButton(" ", callback_data="noop"))
            else:
                giorno = f"{anno:04d}-{mese:02d}-{numero:02d}"
                presenti, _ = conteggio(giorno)
                simbolo = "🔴" if presenti < MIN_PRESENTI else "🟢"
                riga.append(InlineKeyboardButton(
                    f"{simbolo}{numero}",
                    callback_data=f"d|{giorno}"
                ))
        tastiera.append(riga)

    precedente = mese - 1
    anno_prec = anno
    if precedente == 0:
        precedente = 12
        anno_prec -= 1

    successivo = mese + 1
    anno_succ = anno
    if successivo == 13:
        successivo = 1
        anno_succ += 1

    tastiera.append([
        InlineKeyboardButton(
            "⬅️",
            callback_data=f"m|{anno_prec}|{precedente}"
        ),
        InlineKeyboardButton(
            "Oggi",
            callback_data=f"m|{date.today().year}|{date.today().month}"
        ),
        InlineKeyboardButton(
            "➡️",
            callback_data=f"m|{anno_succ}|{successivo}"
        )
    ])

    return testo, InlineKeyboardMarkup(tastiera)


async def inizio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    anno = date.today().year
    mese = date.today().month
    testo, tastiera = vista_mese(anno, mese)
    await update.message.reply_text(testo, reply_markup=tastiera)


async def mese(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await inizio(update, context)


async def registrami(update: Update, context: ContextTypes.DEFAULT_TYPE):
    nome = " ".join(context.args).strip()

    if not nome:
        await update.message.reply_text(
            "Usa il comando: /registrami Nome Cognome"
        )
        return

    elenco = lavoratori()

    if any(n.lower() == nome.lower() for _, n in elenco):
        await update.message.reply_text("Sei già registrato.")
        return

    if len(elenco) >= MAX_LAVORATORI:
        await update.message.reply_text(
            "Sono già stati registrati 10 lavoratori."
        )
        return

    try:
        with closing(sqlite3.connect(DB)) as db:
            db.execute(
                "INSERT INTO lavoratori (nome) VALUES (?)",
                (nome,)
            )
            db.commit()
        await update.message.reply_text(f"Registrato: {nome} ✅")
    except sqlite3.IntegrityError:
        await update.message.reply_text("Nome già presente.")


async def settimana(update: Update, context: ContextTypes.DEFAULT_TYPE):
    oggi = date.today()
    lunedi = oggi - timedelta(days=oggi.weekday())

    testo = "📅 CALENDARIO SETTIMANALE\n\n"
    tastiera = []

    for i in range(7):
        giorno = lunedi + timedelta(days=i)
        data_testo = giorno.isoformat()
        presenti, _ = conteggio(data_testo)
        simbolo = "🔴" if presenti < MIN_PRESENTI else "🟢"

        tastiera.append([
            InlineKeyboardButton(
                f"{simbolo} {giorno.strftime('%d/%m/%Y')}",
                callback_data=f"d|{data_testo}"
            )
        ])

    await update.message.reply_text(
        testo, reply_markup=InlineKeyboardMarkup(tastiera)
    )


async def pulsanti(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    dati = query.data.split("|")

    if dati[0] == "noop":
        return

    if dati[0] == "m":
        testo, tastiera = vista_mese(int(dati[1]), int(dati[2]))
        await query.edit_message_text(testo, reply_markup=tastiera)
        return

    if dati[0] == "d":
        testo, tastiera = testo_giorno(dati[1])
        await query.edit_message_text(testo, reply_markup=tastiera)
        return

    if dati[0] == "t":
        giorno = dati[1]
        ident = int(dati[2])

        with closing(sqlite3.connect(DB)) as db:
            esiste = db.execute(
                "SELECT 1 FROM assenze WHERE giorno=? AND lavoratore_id=?",
                (giorno, ident)
            ).fetchone()

            if esiste:
                db.execute(
                    "DELETE FROM assenze WHERE giorno=? AND lavoratore_id=?",
                    (giorno, ident)
                )
            else:
                db.execute(
                    "INSERT INTO assenze VALUES (?, ?)",
                    (giorno, ident)
                )
            db.commit()

        testo, tastiera = testo_giorno(giorno)
        await query.edit_message_text(testo, reply_markup=tastiera)


async def aiuto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📋 COMANDI CALENDARIO FERIE\n\n"
        "/inizia - apre il calendario mensile\n"
        "/mese - mostra il mese corrente\n"
        "/settimana - mostra la settimana corrente\n"
        "/registrami Nome Cognome - registra un lavoratore\n"
        "/aiuto - mostra questo messaggio\n\n"
        "Tutti possono modificare le assenze di tutti."
    )


def main():
    database()

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", inizio))
    app.add_handler(CommandHandler("inizia", inizio))
    app.add_handler(CommandHandler("mese", mese))
    app.add_handler(CommandHandler("settimana", settimana))
    app.add_handler(CommandHandler("registrami", registrami))
    app.add_handler(CommandHandler("aiuto", aiuto))
    app.add_handler(CallbackQueryHandler(pulsanti))

    print("Bot calendario ferie avviato!")
    app.run_polling()


if __name__ == "__main__":
    main()
  
