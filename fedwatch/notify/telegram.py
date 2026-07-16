"""Skickar notismeddelanden via Telegrams Bot API.

Kräver en bot-token (skapas via @BotFather på Telegram) och ett chat_id
(mottagarens eget chatt-ID, se README för hur man tar reda på det). Båda är
HEMLIGHETER — läses från miljövariabler, hamnar aldrig i kod eller commits.
"""

import logging

import requests

logger = logging.getLogger(__name__)

_TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"
_REQUEST_TIMEOUT = 15


def send_telegram_message(bot_token: str, chat_id: str, text: str) -> None:
    """Skickar ett textmeddelande (Markdown-formaterat) till given chat_id.
    Kastar requests.HTTPError vid icke-2xx-svar (t.ex. fel token/chat_id)."""
    response = requests.post(
        _TELEGRAM_API_URL.format(token=bot_token),
        json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown", "disable_web_page_preview": True},
        timeout=_REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    logger.info("Skickade Telegram-notis (%d tecken) till chat_id=%s.", len(text), chat_id)
