"""Verify Telegram's webhook credential before reading untrusted JSON."""

import hmac
import re

from fastapi import HTTPException, Request


def validate_webhook_secret(secret):
    if not secret or not re.fullmatch(r'[A-Za-z0-9_-]{1,256}', secret):
        raise ValueError('Configure TELEGRAM_WEBHOOK_SECRET with 1–256 letters, digits, underscores or hyphens.')
    return secret


def verify_telegram_webhook(request: Request, secret):
    try:
        expected = validate_webhook_secret(secret)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail='Telegram webhook is not configured.') from exc
    supplied = request.headers.get('X-Telegram-Bot-Api-Secret-Token', '')
    if not hmac.compare_digest(supplied.encode('utf-8'), expected.encode('ascii')):
        raise HTTPException(status_code=403, detail='Invalid webhook credential.')
