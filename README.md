# Telegram AI Assistant 🤖

A fully asynchronous Pyrogram-based Telegram assistant that streams responses from an LLM provider, edits messages every 3 seconds, and enforces a `4096` character limit.

## Features
- Streams LLM responses with incremental edits every 3 seconds
- Message length capped to `4096` characters
- Uses Mistral chat API with streaming
- Loguru-based logging to console and file (`bot.log`)
- Works for messages sent by you in any chat (prefix `.ai`)

## Requirements
- Python `3.11`
- Telegram API credentials: `API_ID`, `API_HASH`, `PHONE_NUMBER`, `SESSION_NAME`
- Mistral API key: `MISTRAL_API_KEY`

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
   MISTRAL_API_KEY=your_mistral_api_key
   ```

## Usage
- Default start:
  ```bash
  python3 main.py
  ```
- First run prompts sign-in and creates a local session.
- LLM:
  - Send a message starting with `.ai <your question>` in any chat to stream answers.
- Crypto commands:
  - `.usdt [amount]` — header shows `🧮 Conversion <amount> 💵:`; list shows `• 💎`, `• 🪙`, `• ⭐`
  - `.ton  [amount]` — header shows `🧮 Conversion <amount> 💎:`; list shows `• 💵`, `• 🪙`, `• ⭐`
  - `.sol  [amount]` — header shows `🧮 Conversion <amount> 🪙:`; list shows `• 💵`, `• 💎`, `• ⭐`
  - Amount is optional; default is `1.00`. Input supports up to two decimals.
  - Stars use fixed price: `1 ⭐ = $0.015`.
  - TON/USD and SOL/USD are fetched live from Binance Public API.

## Provider Guide 🧭
This project is configured for Mistral's OpenAI-compatible chat API:
- Base URL: `https://api.mistral.ai/v1`
- Default model: `mistral-small-latest` (general-purpose, free tier friendly)
- Max tokens per response: `2048`

You can change the model in `main.py` by editing `MISTRAL_MODEL`.

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
