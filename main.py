
import os
import sqlite3
import calendar
from datetime import date, timedelta
from contextlib import closing

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes
)

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
MIN_PRESENTI = 4
MAX_LAVORATORI = 10

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
    totale = len(lavoratori())
    numero_assenti = len(assenti(giorno))
    return max(0, totale - numero_assenti), numero_assenti


def vista_mese(anno, mese):
    nomi_mesi = [
        "Gennaio", "Febbraio", "Marzo", "Aprile",
        "Maggio", "Giugno", "Luglio", "Agosto",
        "Settembre", "Ottobre", "Novembre", "Dicembre"
    ]

    testo = (
        f"📅 CALENDARIO FERIE\n"
        f"{nomi_mesi[mese - 1]} {anno}\n\n"
        "🔵 Oggi   🟢 Regolare   🔴 Meno di 4 presenti\n"
    )

    tastiera = [[
        InlineKeyboardButton(g, callback_data="noop")
        for g in ["L", "M", "M", "G", "V", "S", "D"]
    ]]

    for settimana in calendar.monthcalendar(anno, mese):
        riga = []
        for numero in settimana:
            if numero == 0:
                riga.append(
                    InlineKeyboardButton(" ", callback_data="noop")
                )
                continue

            giorno = date(anno, mese, numero)
            presenti, _ = conteggio(giorno.isoformat())

            if giorno == date.today():
                simbolo = "🔵"
            elif presenti < MIN_PRESENTI:
                simbolo = "🔴"
            else:
                simbolo = "🟢"

            riga.append(InlineKeyboardButton(
                f"{simbolo}{numero}",
                callback_data=f"d|{giorno.isoformat()}"
            ))

        tastiera.append(riga)

    precedente = date(anno, mese, 1) - timedelta(days=1)
    if mese == 12:
        successivo = date(anno + 1, 1, 1)
    else:
        successivo = date(anno, mese + 1, 1)

    tastiera.append([
        InlineKeyboardButton(
            "⬅️",
            callback_data=f"m|{precedente.year}|{precedente.month}"
        ),
        InlineKeyboardButton(
            "Oggi",
            callback_data=f"m|{date.today().year}|{date.today().month}"
        ),
        InlineKeyboardButton(
            "➡️",
            callback_data=f"m|{successivo.year}|{successivo.month}"
        )
    ])

    tastiera.append([
        InlineKeyboardButton(
            "📅 Settimanale",
            callback_data=f"w|{(date.today() - timedelta(days=date.today().weekday())).isoformat()}"
        )
    ])

    return testo, InlineKeyboardMarkup(tastiera)


def vista_settimanale(lunedi):
    testo = "📅 CALENDARIO SETTIMANALE\n\n"
    testo += "🔵 Oggi   🟢 Regolare   🔴 Meno di 4 presenti\n"

    tastiera = []

    for i in range(7):
        giorno = lunedi + timedelta(days=i)
        presenti, _ = conteggio(giorno.isoformat())

        if giorno == date.today():
            simbolo = "🔵"
        elif presenti < MIN_PRESENTI:
            simbolo = "🔴"
        else:
            simbolo = "🟢"

        nome_giorno = [
            "Lunedì", "Martedì", "Mercoledì",
            "Giovedì", "Venerdì", "Sabato", "Domenica"
        ][i]

        tastiera.append([
            InlineKeyboardButton(
                f"{simbolo} {nome_giorno} {giorno.strftime('%d/%m/%Y')}",
                callback_data=f"d|{giorno.isoformat()}"
            )
        ])

    precedente = lunedi - timedelta(days=7)
    successivo = lunedi + timedelta(days=7)

    tastiera.append([
        InlineKeyboardButton(
            "⬅️ Settimana precedente",
            callback_data=f"w|{precedente.isoformat()}"
        )
    ])
    tastiera.append([
        InlineKeyboardButton(
            "Settimana successiva ➡️",
            callback_data=f"w|{successivo.isoformat()}"
        )
    ])
    tastiera.append([
        InlineKeyboardButton(
            "📆 Calendario mensile",
            callback_data=f"m|{date.today().year}|{date.today().month}"
        )
    ])

    return testo, InlineKeyboardMarkup(tastiera)


def testo_giorno(giorno):
    presenti, numero_assenti = conteggio(giorno)
    totale = len(lavoratori())

    data_giorno = date.fromisoformat(giorno)
    indicatore = " 🔵 OGGI" if data_giorno == date.today() else ""

    avviso = (
        "🔴 ATTENZIONE: meno di 4 presenti!"
        if presenti < MIN_PRESENTI
        else "🟢 Presenza regolare"
    )

    testo = (
        f"📅 {giorno}{indicatore}\n\n"
        f"👥 Presenti: {presenti}/{totale}\n"
        f"🏖 Assenti: {numero_assenti}\n"
        f"{avviso}\n\n"
        "Seleziona un lavoratore per modificare l'assenza:"
    )

    ids_assenti = [x[0] for x in assenti(giorno)]
    tastiera = []

    for ident, nome in lavoratori():
        simbolo = "🏖" if ident in ids_assenti else "🟢"
        tastiera.append([
            InlineKeyboardButton(
                f"{simbolo} {nome}",
                callback_data=f"t|{giorno}|{ident}"
            )
        ])

    tastiera.append([
        InlineKeyboardButton(
            "⬅️ Torna al mese",
            callback_data=f"m|{data_giorno.year}|{data_giorno.month}"
        )
    ])

    return testo, InlineKeyboardMarkup(tastiera)


async def inizio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    oggi = date.today()
    testo, tastiera = vista_mese(oggi.year, oggi.month)
    await update.message.reply_text(testo, reply_markup=tastiera)


async def mese(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await inizio(update, context)


async def settimana_comando(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    lunedi = date.today() - timedelta(days=date.today().weekday())
    testo, tastiera = vista_settimanale(lunedi)
    await update.message.reply_text(testo, reply_markup=tastiera)


async def registrami(update: Update, context: ContextTypes.DEFAULT_TYPE):
    nome = " ".join(context.args).strip()

    if not nome:
        await update.message.reply_text(
            "Usa: /registrami Nome Cognome"
        )
        return

    elenco = lavoratori()

    if len(elenco) >= MAX_LAVORATORI:
        await update.message.reply_text(
            "Sono già stati registrati 10 lavoratori."
        )
        return

    if any(n.lower() == nome.lower() for _, n in elenco):
        await update.message.reply_text("Nome già registrato.")
        return

    try:
        with closing(sqlite3.connect(DB)) as db:
            db.execute(
                "INSERT INTO lavoratori (nome) VALUES (?)", (nome,)
            )
            db.commit()
        await update.message.reply_text(f"✅ Registrato: {nome}")
    except sqlite3.IntegrityError:
        await update.message.reply_text("Nome già presente.")


async def rinomina(update: Update, context: ContextTypes.DEFAULT_TYPE):
    testo = " ".join(context.args)

    if "|" not in testo:
        await update.message.reply_text(
            "Usa:\n/rinomina Vecchio Nome | Nuovo Nome"
        )
        return

    vecchio, nuovo = [x.strip() for x in testo.split("|", 1)]

    if not vecchio or not nuovo:
        await update.message.reply_text("Inserisci entrambi i nomi.")
        return

    with closing(sqlite3.connect(DB)) as db:
        lavoratore = db.execute(
            "SELECT id FROM lavoratori WHERE nome=? COLLATE NOCASE",
            (vecchio,)
        ).fetchone()

        if not lavoratore:
            await update.message.reply_text("Lavoratore non trovato.")
            return

        try:
            db.execute(
                "UPDATE lavoratori SET nome=? WHERE id=?",
                (nuovo, lavoratore[0])
            )
            db.commit()
            await update.message.reply_text(
                f"✅ Nome modificato: {vecchio} → {nuovo}\n"
                "Le ferie già inserite sono state conservate."
            )
        except sqlite3.IntegrityError:
            await update.message.reply_text(
                "Esiste già un lavoratore con questo nome."
            )


async def elimina(update: Update, context: ContextTypes.DEFAULT_TYPE):
    nome = " ".join(context.args).strip()

    if not nome:
        await update.message.reply_text(
            "Usa: /elimina Nome Cognome"
        )
        return

    with closing(sqlite3.connect(DB)) as db:
        lavoratore = db.execute(
            "SELECT id FROM lavoratori WHERE nome=? COLLATE NOCASE",
            (nome,)
        ).fetchone()

        if not lavoratore:
            await update.message.reply_text("Lavoratore non trovato.")
            return

        db.execute(
            "DELETE FROM assenze WHERE lavoratore_id=?",
            (lavoratore[0],)
        )
        db.execute(
            "DELETE FROM lavoratori WHERE id=?",
            (lavoratore[0],)
        )
        db.commit()

    await update.message.reply_text(
        f"🗑 Lavoratore {nome} eliminato."
    )


async def aiuto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📋 COMANDI CALENDARIO FERIE\n\n"
        "/inizia - calendario mensile\n"
        "/mese - calendario mensile\n"
        "/settimana - calendario settimanale\n"
        "/registrami Nome Cognome - registra lavoratore\n"
        "/rinomina Vecchio Nome | Nuovo Nome - modifica nome\n"
        "/elimina Nome Cognome - elimina lavoratore\n"
        "/aiuto - mostra i comandi\n\n"
        "Tutti possono modificare le assenze di tutti."
    )


async def pulsanti(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    dati = query.data.split("|")

    if dati[0] == "noop":
        return

    if dati[0] == "m":
        testo, tastiera = vista_mese(
            int(dati[1]), int(dati[2])
        )
        await query.edit_message_text(
            testo, reply_markup=tastiera
        )
        return

    if dati[0] == "w":
        lunedi = date.fromisoformat(dati[1])
        testo, tastiera = vista_settimanale(lunedi)
        await query.edit_message_text(
            testo, reply_markup=tastiera
        )
        return

    if dati[0] == "d":
        testo, tastiera = testo_giorno(dati[1])
        await query.edit_message_text(
            testo, reply_markup=tastiera
        )
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
        await query.edit_message_text(
            testo, reply_markup=tastiera
        )


def main():
    database()

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", inizio))
    app.add_handler(CommandHandler("inizia", inizio))
    app.add_handler(CommandHandler("mese", mese))
    app.add_handler(CommandHandler("settimana", settimana_comando))
    app.add_handler(CommandHandler("registrami", registrami))
    app.add_handler(CommandHandler("rinomina", rinomina))
    app.add_handler(CommandHandler("elimina", elimina))
    app.add_handler(CommandHandler("aiuto", aiuto))
    app.add_handler(CallbackQueryHandler(pulsanti))

    print("Bot calendario ferie avviato!")
    app.run_polling()


if __name__ == "__main__":
    main()
    
