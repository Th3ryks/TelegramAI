import os
import sys
import sqlite3
import re
import asyncio
from typing import Optional, Tuple, List

import aiohttp
from dotenv import load_dotenv
from loguru import logger
from pyrogram import Client, filters, idle
from pyrogram.errors import FloodWait, MessageNotModified
from pyrogram.types import MessageEntity
from pyrogram.enums import MessageEntityType
from pyrogram.handlers import MessageHandler

""" --- LOGGER CONFIG --- """

logger.remove()
logger.add(
    sys.stdout,
    format="| <magenta>{time:YYYY-MM-DD HH:mm:ss}</magenta> | <cyan><level>{level: <8}</level></cyan> | {message}",
    level="INFO",
    colorize=True,
)


""" --- ENV LOADING --- """

load_dotenv()


""" --- CONSTANTS --- """

STAR_USD_PRICE = 0.015
BINANCE_TON_SYMBOL = "TONUSDT"
BINANCE_SOL_SYMBOL = "SOLUSDT"

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
PHONE_NUMBER = os.getenv("PHONE_NUMBER", "")
SESSION_NAME = os.getenv("SESSION_NAME", "account")


""" --- UTF16 HELPERS --- """

def _utf16_len(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2


def _utf16_index(s: str, idx: int) -> int:
    return len(s[:idx].encode("utf-16-le")) // 2


""" --- CUSTOM EMOJI MAP --- """

CUSTOM_EMOJI_MAP: dict[str, int] = {
    "💵": 5197434882321567830,
    "💎": 5377620962390857342,
    "⭐": 5472092560522511055,
    "🧮": 5402186569006210455,
    "✨": 5233661458289532234,
    "🪙": 5202113974312653146,
}


""" --- HTTP: BINANCE PRICE --- """

async def fetch_ton_price_usdt() -> Optional[float]:
    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        try:
            async with session.get(
                "https://api.binance.com/api/v3/ticker/price",
                params={"symbol": BINANCE_TON_SYMBOL},
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                price_str = data.get("price")
                if price_str is None:
                    return None
                return float(price_str)
        except Exception:
            return None


async def fetch_sol_price_usdt() -> Optional[float]:
    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        try:
            async with session.get(
                "https://api.binance.com/api/v3/ticker/price",
                params={"symbol": BINANCE_SOL_SYMBOL},
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                price_str = data.get("price")
                if price_str is None:
                    return None
                return float(price_str)
        except Exception:
            return None


""" --- TEXT/ENTITY BUILDERS --- """

def _find_all(text: str, token: str) -> List[int]:
    idxs: List[int] = []
    start = 0
    while True:
        pos = text.find(token, start)
        if pos == -1:
            break
        idxs.append(pos)
        start = pos + 1
    return idxs


def build_entities_for_text(text: str) -> List[MessageEntity]:
    entities: List[MessageEntity] = []

    for emoji, custom_id in CUSTOM_EMOJI_MAP.items():
        for pos in _find_all(text, emoji):
            entities.append(
                MessageEntity(
                    type=MessageEntityType.CUSTOM_EMOJI,
                    offset=_utf16_index(text, pos),
                    length=_utf16_len(emoji),
                    custom_emoji_id=custom_id,
                )
            )

    bold_token = "Конвертация"
    bpos = text.find(bold_token)
    if bpos != -1:
        entities.append(
            MessageEntity(
                type=MessageEntityType.BOLD,
                offset=_utf16_index(text, bpos),
                length=_utf16_len(bold_token),
            )
        )

    entities.sort(key=lambda e: (e.offset, e.length))
    return entities


def format_conversion(mode: str, amount: float, ton_price: float, sol_price: float) -> Tuple[str, List[MessageEntity]]:
    usd: float
    ton: float
    sol: float

    if mode == "usdt":
        usd = amount
        ton = usd / ton_price if ton_price > 0 else 0.0
    else:
        ton = amount
        usd = ton * ton_price
    sol = usd / sol_price if sol_price > 0 else 0.0

    stars = round(usd / STAR_USD_PRICE)

    if mode == "usdt":
        header = f"🧮 Конвертация  {usd:.2f} 💵:"
        lines = (
            f" • 💎: {ton:.2f}\n"
            f" • 🪙: {sol:.2f}\n"
            f" • ⭐: {stars}\n"
        )
    else:
        header = f"🧮 Конвертация  {ton:.2f} 💎:"
        lines = (
            f" • 💵: {usd:.2f}\n"
            f" • 🪙: {sol:.2f}\n"
            f" • ⭐: {stars}\n"
        )

    text = header + "\n\n" + lines + "\n ✨ by @Th3ryks"

    entities = build_entities_for_text(text)
    return text, entities


def format_error() -> Tuple[str, List[MessageEntity]]:
    text = "✨ цена должна быть float или int\n\n ✨ by @Th3ryks"
    entities = build_entities_for_text(text)
    return text, entities


""" --- PARSER --- """

_cmd_re = re.compile(r"^\.(ton|usdt)(?:\s+(\S+))?", re.IGNORECASE)
_sol_re = re.compile(r"^\.sol(?:\s+(\S+))?", re.IGNORECASE)


def parse_amount(token: str) -> Optional[float]:
    cleaned = token.strip().replace(",", ".")
    if not re.fullmatch(r"\d+(?:\.\d{1,2})?", cleaned):
        return None
    try:
        return float(cleaned)
    except Exception:
        return None


""" --- SAFE EDIT --- """

async def safe_edit(message, text: str, entities: Optional[List[MessageEntity]] = None) -> None:
    try:
        await message.edit_text(text, entities=entities)
    except MessageNotModified:
        return
    except FloodWait as e:
        await asyncio.sleep(e.value)
        try:
            await message.edit_text(text, entities=entities)
        except MessageNotModified:
            return


""" --- HANDLERS --- """

async def handle_crypto_message(_, message) -> None:
    text = message.text or ""
    msol = _sol_re.match(text)
    if msol:
        token = msol.group(1)
        amt: Optional[float]
        if token is None:
            amt = 1.0
        else:
            amt = parse_amount(token)
        if amt is None:
            err_text, err_entities = format_error()
            await safe_edit(message, err_text, err_entities)
            return

        sol_price = await fetch_sol_price_usdt()
        ton_price = await fetch_ton_price_usdt()
        if sol_price is None or ton_price is None:
            err_text, err_entities = format_error()
            await safe_edit(message, err_text, err_entities)
            return

        usd = amt * sol_price
        ton = usd / ton_price if ton_price > 0 else 0.0
        stars = round(usd / STAR_USD_PRICE)

        text_out = (
            f"🧮 Конвертация  {amt:.2f} 🪙:\n\n"
            f" • 💵: {usd:.2f}\n"
            f" • 💎: {ton:.2f}\n"
            f" • ⭐: {stars}\n\n"
            f" ✨ by @Th3ryks"
        )
        entities_out = build_entities_for_text(text_out)
        await safe_edit(message, text_out, entities_out)
        return

    m = _cmd_re.match(text)
    if not m:
        return

    mode = m.group(1).lower()
    token = m.group(2)

    amt = parse_amount(token)
    if amt is None:
        err_text, err_entities = format_error()
        await safe_edit(message, err_text, err_entities)
        return

    ton_price = await fetch_ton_price_usdt()
    sol_price = await fetch_sol_price_usdt()
    if ton_price is None or sol_price is None:
        err_text, err_entities = format_error()
        await safe_edit(message, err_text, err_entities)
        return

    out_text, out_entities = format_conversion(mode, amt, ton_price, sol_price)
    await safe_edit(message, out_text, out_entities)


def attach_crypto_handlers(app: Client) -> None:
    app.add_handler(MessageHandler(handle_crypto_message, filters.me & filters.text))


""" --- START/MAIN --- """

async def _start_with_retry(app: Client, retries: int = 6, delay_sec: int = 5) -> bool:
    for attempt in range(1, retries + 1):
        try:
            await app.start()
            return True
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e).lower():
                logger.info(f"session-locked retry={attempt}/{retries} sleep={delay_sec}s")
                await asyncio.sleep(delay_sec)
                continue
            raise
    return False


async def main() -> None:
    app = Client(
        SESSION_NAME,
        api_id=API_ID,
        api_hash=API_HASH,
        phone_number=PHONE_NUMBER,
    )

    attach_crypto_handlers(app)

    started = await _start_with_retry(app)
    if not started:
        logger.info("pyrogram session locked persistently; aborting start")
        return
    logger.info("pyrogram client started (crypto)")
    await idle()


if __name__ == "__main__":
    asyncio.run(main())
