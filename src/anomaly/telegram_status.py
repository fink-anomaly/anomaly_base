import asyncio
from urllib.parse import urlsplit

import aiohttp
from aiohttp_socks import ProxyConnectionError, ProxyConnector, ProxyError, ProxyTimeoutError
from loguru import logger


CHECK_INTERVAL = 60
CHECKING = 'Checking the Telegram bot connection.'
CONFIGURATION_ERROR = 'Telegram bot setup is incomplete. Contact the service administrator.'
REGISTRATION_ERROR = 'The Telegram bot webhook could not be registered. We will retry automatically.'
CHECK_ERROR = 'The Telegram bot connection could not be verified. We will check again automatically.'
WRONG_WEBHOOK = 'The Telegram bot webhook points to a different address. Contact the service administrator.'


def telegram_proxy_url(value):
    value = value.strip()
    if not value:
        return None
    url = urlsplit(value)
    if (
        url.scheme not in ('socks4', 'socks4a', 'socks5', 'socks5h')
        or not url.hostname or not url.port or url.path not in ('', '/') or url.query or url.fragment
    ):
        raise ValueError('Invalid Telegram SOCKS proxy URL')
    return url._replace(scheme='socks4a' if url.scheme.startswith('socks4') else 'socks5h', path='').geturl()


def telegram_session(proxy_url):
    timeout = aiohttp.ClientTimeout(total=10)
    if proxy_url is None:
        return aiohttp.ClientSession(timeout=timeout)
    url = urlsplit(proxy_url)
    scheme = 'socks4' if url.scheme == 'socks4a' else 'socks5'
    connector = ProxyConnector.from_url(url._replace(scheme=scheme).geturl(), rdns=True)
    return aiohttp.ClientSession(timeout=timeout, connector=connector)


async def bot_api_call(session, api_url, method, **payload):
    try:
        async with session.post(
            f'{api_url}/{method}', allow_redirects=False, **payload,
        ) as response:
            if response.status == 200:
                result = await response.json()
                if isinstance(result, dict) and result.get('ok') is True:
                    return result
    except (aiohttp.ClientError, ValueError, asyncio.TimeoutError, ProxyConnectionError, ProxyError, ProxyTimeoutError):
        # A transport exception can include the bot token in its request URL.
        pass
    return None


async def monitor_webhook(state, bot_token, webhook_url, secret, proxy_url=None):
    api_url = f'https://api.telegram.org/bot{bot_token}'
    async with telegram_session(proxy_url) as session:
        registered = False
        while True:
            if not registered:
                registration = await bot_api_call(session, api_url, 'setWebhook', data={
                    'url': webhook_url, 'secret_token': secret,
                })
                registered = registration is not None and registration.get('result') is True
                warning = None if registered else REGISTRATION_ERROR
            else:
                info = await bot_api_call(session, api_url, 'getWebhookInfo')
                webhook = info.get('result') if info else None
                if not isinstance(webhook, dict) or not isinstance(webhook.get('url'), str):
                    warning = CHECK_ERROR
                elif webhook['url'] != webhook_url:
                    warning = WRONG_WEBHOOK
                else:
                    warning = None

            if warning != state.telegram_warning:
                state.telegram_warning = warning
                if warning:
                    logger.warning(warning)
                else:
                    logger.info('Telegram bot webhook confirmed.')
            await asyncio.sleep(CHECK_INTERVAL)
