import os
import sys
import asyncio
from dotenv import load_dotenv
from loguru import logger
from pyrogram import Client, filters
from pyrogram.errors import FloodWait, MessageNotModified
from pyrogram import idle
from pyrogram.handlers import MessageHandler
from openai import AsyncOpenAI

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

""" --- ENV --- """
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

""" --- OPENROUTER CLIENT --- """
ai_client = AsyncOpenAI(
    base_url=LLM_BASE_URL,
    api_key=OPENROUTER_API_KEY,
)
logger.info(f"llm-client-ready base_url={LLM_BASE_URL} model={LLM_MODEL} max_tokens={LLM_MAX_TOKENS}")

""" --- UTILITIES --- """


async def safe_edit(message, text):
    try:
        await message.edit_text(text)
    except MessageNotModified:
        return
    except FloodWait as e:
        await asyncio.sleep(e.value)
        try:
            await message.edit_text(text)
        except MessageNotModified:
            return


async def stream_and_edit(message, prompt):
    """ --- STREAMING --- """
    system_instruction = (
        "Answer the user's question directly. Do NOT include greetings or goodbyes. "
        "Use emojis naturally in the content. "
        "Do NOT add suggestions, calls to action, or phrases inviting the user to ask for more details. "
        "Avoid disclaimers and meta-commentary. Provide a concise, self-contained answer only."
    )

    answer_parts = []
    stop_event = asyncio.Event()

    async def editor_loop():
        while not stop_event.is_set():
            await asyncio.sleep(3)
            current = "".join(answer_parts)
            display_text = "🤖 Генерирую Ответ...\n\n" + current
            if len(display_text) > 4096:
                display_text = display_text[:4096]
            await safe_edit(message, display_text)

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
        final_text = "🤖 Ответ Сгенерирован Моделью qwen3-coder-plus\n\n" + "".join(answer_parts)
        if len(final_text) > 4096:
            final_text = final_text[:4096]
        await safe_edit(message, final_text)
        logger.info("llm-stream-finished")


async def handle_message(_, message):
    """ --- HANDLER --- """
    text = message.text or ""
    if not text.startswith(".ai"):
        return
    query = text[3:].strip()
    if not query:
        return
    await safe_edit(message, "🤖 Генерирую Ответ...")
    logger.info(
        f"request-started chat_id={message.chat.id} message_id={message.id} query_len={len(query)}"
    )
    await stream_and_edit(message, query)
    logger.info("request-finished")


async def main():
    """ --- APP START --- """
    app = Client(
        SESSION_NAME,
        api_id=API_ID,
        api_hash=API_HASH,
        phone_number=PHONE_NUMBER,
    )

    app.add_handler(MessageHandler(handle_message, filters.me & filters.text))

    await app.start()
    logger.info("pyrogram client started")
    await idle()


if __name__ == "__main__":
    asyncio.run(main())
