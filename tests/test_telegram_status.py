"""Telegram may be unavailable while the FastAPI application serves the cabinet."""

import asyncio
from contextlib import asynccontextmanager
from queue import Queue
from types import SimpleNamespace
from unittest.mock import Mock

import aiohttp
import pytest

import telegram_status


WEBHOOK_URL = 'https://example.invalid/telegram-webhook'


@pytest.fixture
def telegram_client(app_module, app_client, monkeypatch):
    monkeypatch.setitem(app_module.config['SERVER'], 'init_bot', 'true')
    monkeypatch.setitem(app_module.config['SERVER'], 'domen', 'example.invalid')
    monkeypatch.setattr(telegram_status, 'CHECK_INTERVAL', 0)
    requests = Queue()
    responses = asyncio.Queue()
    closed = Mock()

    @asynccontextmanager
    async def post(url, **options):
        requests.put((url.rsplit('/', 1)[-1], options))
        response = await responses.get()
        if isinstance(response, Exception):
            raise response
        status, payload = response

        async def json():
            if isinstance(payload, ValueError):
                raise payload
            return payload

        yield SimpleNamespace(status=status, json=json)

    @asynccontextmanager
    async def session(*, timeout):
        assert timeout.total == 10
        try:
            yield SimpleNamespace(post=post)
        finally:
            closed()

    monkeypatch.setattr(telegram_status.aiohttp, 'ClientSession', session)
    with app_client as client:
        def reply(response):
            client.portal.call(responses.put, response)

        yield client, requests, reply
    # Shutdown cancels the background task even when Telegram is still in flight.
    closed.assert_called_once()


def test_slow_registration_does_not_delay_startup_and_warning_clears(telegram_client, app_module):
    client, requests, reply = telegram_client
    method, options = requests.get(timeout=3)
    assert method == 'setWebhook'
    assert options == {
        'data': {'url': WEBHOOK_URL, 'secret_token': app_module.settings.TELEGRAM_WEBHOOK_SECRET},
        'allow_redirects': False,
    }
    assert client.get('/version').status_code == 200
    assert telegram_status.CHECKING in client.get('/').text

    reply(asyncio.TimeoutError('secret in exception URL'))
    assert requests.get(timeout=3)[0] == 'setWebhook'
    for url in ('/', '/auth/login'):
        response = client.get(url)
        assert response.status_code == 200
        assert telegram_status.REGISTRATION_ERROR in response.text
        assert 'secret in exception URL' not in response.text

    reply((200, {'ok': True, 'result': True}))
    assert requests.get(timeout=3)[0] == 'getWebhookInfo'
    assert 'id="telegram-warning"' not in client.get('/').text

    reply(aiohttp.ClientConnectionError('secret in exception URL'))
    assert requests.get(timeout=3)[0] == 'getWebhookInfo'
    assert telegram_status.CHECK_ERROR in client.get('/').text
    assert client.get('/version').status_code == 200

    reply((200, {'ok': True, 'result': {'url': 'https://another.example/telegram-webhook'}}))
    assert requests.get(timeout=3)[0] == 'getWebhookInfo'
    assert telegram_status.WRONG_WEBHOOK in client.get('/').text

    reply((200, {'ok': True, 'result': {'url': WEBHOOK_URL}}))
    assert requests.get(timeout=3)[0] == 'getWebhookInfo'
    assert 'id="telegram-warning"' not in client.get('/').text


@pytest.mark.parametrize('bad_response', [
    (200, {'ok': False}), (403, {'ok': True, 'result': True}), (200, None),
    (200, ValueError('invalid JSON')), (200, {'ok': True, 'result': False}),
])
def test_rejected_registration_retries_without_stopping_cabinet(telegram_client, bad_response):
    client, requests, reply = telegram_client
    assert requests.get(timeout=3)[0] == 'setWebhook'
    reply(bad_response)
    assert requests.get(timeout=3)[0] == 'setWebhook'
    assert telegram_status.REGISTRATION_ERROR in client.get('/').text
    assert client.get('/version').status_code == 200


@pytest.mark.parametrize('missing', ['secret', 'domain'])
def test_missing_telegram_configuration_leaves_cabinet_online(app_module, monkeypatch, request, missing):
    monkeypatch.setitem(app_module.config['SERVER'], 'init_bot', 'true')
    monkeypatch.setitem(app_module.config['SERVER'], 'domen', 'example.invalid' if missing == 'secret' else '')
    if missing == 'secret':
        monkeypatch.setattr(app_module.settings, 'TELEGRAM_WEBHOOK_SECRET', None)
    session = Mock()
    monkeypatch.setattr(telegram_status.aiohttp, 'ClientSession', session)
    client = request.getfixturevalue('client')
    assert client.get('/version').status_code == 200
    assert telegram_status.CONFIGURATION_ERROR in client.get('/').text
    session.assert_not_called()
    if missing == 'secret':
        assert client.post('/telegram-webhook', json={}).status_code == 503


def test_manually_managed_webhook_makes_no_registration_or_health_calls(app_client, monkeypatch):
    session = Mock()
    monkeypatch.setattr(telegram_status.aiohttp, 'ClientSession', session)
    with app_client as client:
        assert 'id="telegram-warning"' not in client.get('/').text
    session.assert_not_called()
