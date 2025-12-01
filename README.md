# Telegram AI Assistant 🤖

A fully asynchronous Pyrogram-based Telegram assistant that streams responses from an LLM provider, edits messages every 3 seconds, and enforces a `4096` character limit.

## Features
- Streams LLM responses with incremental edits every 3 seconds
- Message length capped to `4096` characters
- Configurable provider, model, and token limits via `.env`
- Loguru-based logging to console and file (`bot.log`)
- Works for messages sent by you in any chat (prefix `.ai`)

## Requirements
- Python `3.11`
- Telegram API credentials: `API_ID`, `API_HASH`, `PHONE_NUMBER`, `SESSION_NAME`
- LLM provider API key

## Installation
1. Clone the repository:
   ```bash
   git clone https://github.com/Th3ryks/TelegramAI
   cd TelegramAI
   ```
2. Create and activate a virtual environment (optional but recommended):
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Create `.env` in the project root:
   ```dotenv
   API_ID=your_api_id
   API_HASH=your_api_hash
   PHONE_NUMBER=your_phone_number
   SESSION_NAME=account
   OPENROUTER_API_KEY=your_openrouter_api_key
   LLM_BASE_URL=https://openrouter.ai/api/v1
   LLM_MODEL=qwen/qwen3-coder-plus
   LLM_MAX_TOKENS=2048
   ```

## Usage
- Start the app:
  ```bash
  python3 main.py
  ```
- First run prompts sign-in and creates a local session.
- Send a message starting with `.ai <your question>` in any chat. The message will be edited to show generation progress and streamed content.

## Provider Guide 🧭
This project supports any OpenAI-compatible provider by changing `.env`:
- `LLM_BASE_URL` — API base URL
- `LLM_MODEL` — model identifier
- `LLM_MAX_TOKENS` — upper bound for generated tokens

Recommended options:
- OpenRouter — `LLM_BASE_URL=https://openrouter.ai/api/v1` with large model selection. Check credits/quotas.
- Groq — `LLM_BASE_URL=https://api.groq.com/openai/v1` with models like `llama-3.1-70b-versatile` (large context, fast). Obtain `GROQ_API_KEY` and set it in `OPENROUTER_API_KEY` or adapt code to a separate env variable.
- DeepSeek — `LLM_BASE_URL=https://api.deepseek.com/v1` and model `deepseek-chat` (large context). Verify daily limits.

Notes:
- Quotas change over time. Always confirm free tier and request limits to ensure ≥100 requests/day for your usage.
- For truly high daily volumes, consider running a local model via Ollama and add web augmentation (RAG) for freshness.

## Logging
- Console logs with colors
- File logs written to `bot.log` with rotation

## Run Lint
```bash
ruff check . --fix
```

## Start Command
```bash
python3 main.py
```
