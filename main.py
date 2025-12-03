import os
import sys
import asyncio
import sqlite3
import aiohttp
from dotenv import load_dotenv
from loguru import logger
from pyrogram import Client, filters
from pyrogram.errors import FloodWait, MessageNotModified
from pyrogram import idle
from pyrogram.handlers import MessageHandler
from openai import AsyncOpenAI
from pyrogram.types import MessageEntity, InputMediaPhoto
from pyrogram.enums import MessageEntityType

logger.remove()
logger.add(
    sys.stdout,
    format="| <magenta>{time:YYYY-MM-DD HH:mm:ss}</magenta> | <cyan><level>{level: <8}</level></cyan> | {message}",
    level="INFO",
    colorize=True,
)
logger.add(
    "bot.log",
    format="| {time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
    level="INFO",
    colorize=False,
    rotation="10 MB",
)

load_dotenv()
logger.info("env-loaded")

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
PHONE_NUMBER = os.getenv("PHONE_NUMBER")
SESSION_NAME = os.getenv("SESSION_NAME", "account")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen/qwen3-coder-plus")
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "2048"))

ai_client = AsyncOpenAI(
    base_url=LLM_BASE_URL,
    api_key=OPENROUTER_API_KEY,
)
logger.info(f"llm-client-ready base_url={LLM_BASE_URL} model={LLM_MODEL} max_tokens={LLM_MAX_TOKENS}")

def _utf16_len(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2


def _utf16_index(s: str, idx: int) -> int:
    return len(s[:idx].encode("utf-16-le")) // 2


def build_custom_emoji_entities(text: str) -> list[MessageEntity]:
    entities: list[MessageEntity] = []
    try:
        q_offset = text.find("❓")
        if q_offset != -1:
            entities.append(
                MessageEntity(
                    type=MessageEntityType.CUSTOM_EMOJI,
                    offset=_utf16_index(text, q_offset),
                    length=_utf16_len("❓"),
                    custom_emoji_id=int("6221887708877295820"),
                )
            )
        ans_offset = text.find("💡")
        if ans_offset != -1:
            entities.append(
                MessageEntity(
                    type=MessageEntityType.CUSTOM_EMOJI,
                    offset=_utf16_index(text, ans_offset),
                    length=_utf16_len("💡"),
                    custom_emoji_id=int("6219877930470740174"),
                )
            )
    except Exception:
        pass
    entities.sort(key=lambda e: (e.offset, e.length))
    return entities


async def _parse_markdown_with_custom_emoji(client, text: str) -> tuple[str, list[MessageEntity]]:
    try:
        parsed = await client.parser.parse(text, "Markdown")
        base_text: str = parsed.get("text", text)
        base_entities: list[MessageEntity] = parsed.get("entities") or []
    except Exception:
        base_text = text
        base_entities = []

    def transform_fenced_code(src: str) -> tuple[str, list[MessageEntity], list[tuple[int, int]]]:
        out = []
        pre_entities: list[MessageEntity] = []
        shifts: list[tuple[int, int]] = []
        i = 0
        n = len(src)
        while i < n:
            if src.startswith("```", i):
                j = i + 3
                lang = ""
                k = src.find("\n", j)
                if k != -1:
                    lang = src[j:k].strip()
                    j = k + 1
                end = src.find("```", j)
                if end == -1:
                    out.append(src[i:])
                    break
                code = src[j:end]
                new_offset_u16 = _utf16_len("".join(out))
                code_len_u16 = _utf16_len(code)
                pre_entities.append(
                    MessageEntity(
                        type=MessageEntityType.PRE,
                        offset=new_offset_u16,
                        length=code_len_u16,
                        language=lang or None,
                    )
                )
                removed_u16 = _utf16_len(src[i:end + 3]) - code_len_u16
                shifts.append((new_offset_u16 + code_len_u16, removed_u16))
                out.append(code)
                i = end + 3
            else:
                out.append(src[i])
                i += 1
        return "".join(out), pre_entities, shifts

    new_text, pre_entities, shifts = transform_fenced_code(base_text)

    def adjust_entities(ents: list[MessageEntity]) -> list[MessageEntity]:
        adjusted: list[MessageEntity] = []
        for e in ents:
            delta = 0
            for pos, removed in shifts:
                if e.offset >= pos:
                    delta += removed
            adjusted.append(
                MessageEntity(
                    type=e.type,
                    offset=max(0, e.offset - delta),
                    length=e.length,
                )
            )
        return adjusted

    base_entities_adj = adjust_entities(base_entities)
    emoji_entities = build_custom_emoji_entities(new_text)
    merged_entities = base_entities_adj + pre_entities + emoji_entities
    merged_entities.sort(key=lambda x: (x.offset, x.length))
    return new_text, merged_entities


async def safe_edit(message, text, entities=None):
    if entities is None:
        text, entities = await _parse_markdown_with_custom_emoji(message._client, text)
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


async def generate_and_attach_image(message, prompt: str):
    try:
        from huggingface_hub import InferenceClient
    except Exception as e:
        logger.info(f"huggingface-hub-not-available: {e}")
        return

    api_key = os.getenv("HUGGINGFACE_API_KEY")
    if not api_key:
        logger.info("hf-api-key-missing")
        return

    client = InferenceClient(model="black-forest-labs/FLUX.1-dev", token=api_key)

    async def _gen_once() -> str | None:
        def _run() -> str | None:
            try:
                image = client.text_to_image(prompt=prompt)
                out_path = "aigen_output.png"
                image.save(out_path)
                return out_path
            except Exception:
                return None

        return await asyncio.to_thread(_run)

    file_path: str | None = None
    for attempt, delay in ((1, 2), (2, 5), (3, 8)):
        file_path = await _gen_once()
        if file_path:
            break
        await asyncio.sleep(delay)
    if not file_path:
        fail_text = "❓ Запрос: " + prompt + "\n\n" + "💡 Ответ:\n" + "Сервис генерации недоступен."
        await safe_edit(message, fail_text)
        return

    caption = "❓ Запрос: " + prompt
    caption_text, caption_entities = await _parse_markdown_with_custom_emoji(message._client, caption)

    try:
        await message.edit_media(
            InputMediaPhoto(media=file_path, caption=caption_text, caption_entities=caption_entities)
        )
    except Exception as e:
        logger.info(f"edit-media-failed: {e}")
        try:
            await message.delete()
            await message.chat.send_photo(file_path, caption=caption_text, caption_entities=caption_entities)
        except Exception as e2:
            logger.info(f"send-photo-failed: {e2}")
    finally:
        try:
            os.remove(file_path)
        except Exception:
            pass


async def get_binance_price(symbol: str) -> str | None:
    url = "https://api.binance.com/api/v3/ticker/price"
    params = {"symbol": symbol}
    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        try:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                price = data.get("price")
                return price
        except Exception:
            return None


def detect_symbol(query: str) -> str | None:
    q = query.lower()
    mapping = {
        "btc": [
            "btc",
            "bitcoin",
            "биткоин",
            "биткойн",
            "биток",
            "битка",
            "бтс",
        ],
        "eth": [
            "eth",
            "ethereum",
            "эфир",
            "эфириум",
            "эфира",
        ],
        "ton": [
            "ton",
            "toncoin",
            "тон",
            "тонкоин",
            "тона",
        ],
        "sol": [
            "sol",
            "solana",
            "солана",
            "сол",
            "соланы",
        ],
        "bnb": [
            "bnb",
            "бинанс коин",
            "бинби",
        ],
        "xrp": [
            "xrp",
            "рипл",
            "ripple",
            "хрп",
        ],
        "doge": [
            "doge",
            "дог",
            "додж",
            "доге",
        ],
        "trx": [
            "trx",
            "tron",
            "трон",
            "трона",
        ],
    }
    for key, synonyms in mapping.items():
        for s in synonyms:
            if s in q:
                base = key.upper()
                return f"{base}USDT"
    return None


async def maybe_answer_crypto(message, query: str) -> bool:
    symbol = detect_symbol(query)
    if not symbol:
        return False
    price = await get_binance_price(symbol)
    if price is None:
        return False
    name = symbol.replace("USDT", "")
    body = f"Текущая цена {name}: {price} USDT"
    text = "❓ Запрос: " + query + "\n\n" + "💡 Ответ:\n" + body
    await safe_edit(message, text)
    return True
async def stream_and_edit(message, prompt):
    system_instruction = (
        "Respond only in Russian. "
        "First, generate a short topic (up to 6 words) and output it exactly as: 'Тема: <topic>'. "
        "Then immediately continue with the complete answer. "
        "If the request is about code/scripts/programs/apps, provide fully working code first, then a brief explanation. "
        "Use lists with • or - and separate paragraphs with one blank line. "
        "Avoid greetings and meta-comments."
    )

    answer_parts = []
    stop_event = asyncio.Event()

    theme_holder = {"theme": None}

    def parse_theme_and_body(buffer: str):
        idx = buffer.find("Тема:")
        if idx == -1:
            return None, buffer
        nl = buffer.find("\n", idx)
        if nl == -1:
            return None, ""
        theme_line = buffer[idx:nl].strip()
        theme = theme_line.replace("Тема:", "").strip()
        body = buffer[nl + 1 :]
        return theme or None, body

    def build_structured_text(query: str, theme: str | None, body: str):
        header = "❓ Запрос: " + query + "\n\n" + "💡 Ответ:\n"
        if theme:
            header += "Тема: " + theme + "\n\n"
        text = header + body
        if len(text) > 4096:
            text = text[:4096]
        return text

    async def editor_loop():
        while not stop_event.is_set():
            await asyncio.sleep(3)
            buffer = "".join(answer_parts)
            if theme_holder["theme"] is None:
                theme, body = parse_theme_and_body(buffer)
                if theme:
                    theme_holder["theme"] = theme
                else:
                    display_text = "🤖 Генерирую Ответ...\n\n" + buffer
                    if len(display_text) > 4096:
                        display_text = display_text[:4096]
                    await safe_edit(message, display_text)
                    continue
            _, body = parse_theme_and_body(buffer)
            structured_text = build_structured_text(prompt, theme_holder["theme"], body)
            await safe_edit(message, structured_text)

    editor_task = asyncio.create_task(editor_loop())
    logger.info("stream-editor-started")

    try:
        stream = await ai_client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt},
            ],
            stream=True,
            max_tokens=LLM_MAX_TOKENS,
        )
        logger.info("llm-stream-started")

        async for chunk in stream:
            try:
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    answer_parts.append(delta.content)
                    if len(answer_parts) % 50 == 0:
                        logger.info(f"llm-chunks-collected={len(answer_parts)}")
            except Exception as e:
                logger.info(f"stream-chunk-error: {e}")
                break
    finally:
        stop_event.set()
        await editor_task
        buffer = "".join(answer_parts)
        theme, body = parse_theme_and_body(buffer)
        if theme:
            theme_holder["theme"] = theme
        final_text = build_structured_text(prompt, theme_holder["theme"], body)
        await safe_edit(message, final_text)
        try:
            if len(final_text) < 4096:
                await safe_edit(message, final_text + "\n")
        except Exception:
            pass
        logger.info("llm-stream-finished")


async def handle_message(_, message):
    text = message.text or ""
    if text.startswith(".aigen"):
        query = text[6:].strip()
        if not query:
            return
        img_progress_text = "💻 Картинка Генерируется..."
        img_progress_entities = [
            MessageEntity(
                type=MessageEntityType.CUSTOM_EMOJI,
                offset=0,
                length=2,
                custom_emoji_id=int("6127281351851774285"),
            )
        ]
        await safe_edit(message, img_progress_text, img_progress_entities)
        await generate_and_attach_image(message, query)
        return
    if text.startswith(".ai"):
        query = text[3:].strip()
        if not query:
            return
        progress_text = "⏳ Генерирую Ответ..."
        progress_entities = [
            MessageEntity(
                type=MessageEntityType.CUSTOM_EMOJI,
                offset=0,
                length=1,
                custom_emoji_id=int("6129624655943700681"),
            )
        ]
        await safe_edit(message, progress_text, progress_entities)
        logger.info(
            f"request-started chat_id={message.chat.id} message_id={message.id} query_len={len(query)}"
        )
        if await maybe_answer_crypto(message, query):
            logger.info("crypto-answer-sent")
            return
        await stream_and_edit(message, query)
        logger.info("request-finished")


async def main():
    app = Client(
        SESSION_NAME,
        api_id=API_ID,
        api_hash=API_HASH,
        phone_number=PHONE_NUMBER,
    )

    app.add_handler(MessageHandler(handle_message, filters.me & filters.text))

    async def start_with_retry(retries: int = 6, delay_sec: int = 5) -> bool:
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

    started = await start_with_retry()
    if not started:
        logger.info("pyrogram session locked persistently; aborting start")
        return
    logger.info("pyrogram client started")
    await idle()


if __name__ == "__main__":
    asyncio.run(main())
