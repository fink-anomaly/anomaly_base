"""Telegram may be unavailable while the FastAPI application serves the cabinet."""

import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from queue import Queue
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import aiohttp
from aiohttp_socks import ProxyConnectionError
import pytest

import telegram_status


WEBHOOK_URL = 'https://example.invalid/telegram-webhook'


@pytest.fixture
def telegram_client(app_module, app_client, monkeypatch, request):
    monkeypatch.setitem(app_module.config['SERVER'], 'init_bot', 'true')
    monkeypatch.setitem(app_module.config['SERVER'], 'domen', 'example.invalid')
    proxy = getattr(request, 'param', None)
    if proxy:
        config = deepcopy(app_module.config)
        config.read_string(f'[SERVER]\nbot_proxy = {proxy}')
        monkeypatch.setattr(app_module, 'config', config)
    monkeypatch.setattr(telegram_status, 'CHECK_INTERVAL', 0)
    connector = Mock()
    create_connector = Mock(return_value=connector)
    monkeypatch.setattr(telegram_status.ProxyConnector, 'from_url', create_connector)
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
    async def session(*, timeout, **options):
        assert timeout.total == 10
        assert options == ({'connector': connector} if proxy else {})
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
    if proxy:
        create_connector.assert_called_once_with(proxy, rdns=True)
    else:
        create_connector.assert_not_called()


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


@pytest.mark.parametrize('telegram_client', ['socks5://user:p%40ss@proxy.invalid:1080'], indirect=True)
def test_proxy_failure_retries_and_keeps_homepage_available(telegram_client, app_module):
    client, requests, reply = telegram_client
    assert requests.get(timeout=3)[0] == 'setWebhook'
    assert app_module.telebot.apihelper.proxy == {'https': 'socks5h://user:p%40ss@proxy.invalid:1080'}
    reply(ProxyConnectionError('proxy credentials'))
    assert requests.get(timeout=3)[0] == 'setWebhook'
    page = client.get('/')
    assert page.status_code == 200
    assert telegram_status.REGISTRATION_ERROR in page.text
    assert 'proxy credentials' not in page.text
    reply((200, {'ok': True, 'result': True}))
    assert requests.get(timeout=3)[0] == 'getWebhookInfo'


def test_invalid_proxy_warns_and_does_not_use_direct_telegram(app_client, app_module, monkeypatch):
    monkeypatch.setitem(app_module.config['SERVER'], 'bot_proxy', 'socks5://user:secret@proxy.invalid:no-port')
    monkeypatch.setitem(app_module.config['SERVER'], 'init_bot', 'true')
    session = Mock()
    monkeypatch.setattr(telegram_status.aiohttp, 'ClientSession', session)
    with app_client as client:
        page = client.get('/')
        assert page.status_code == 200
        assert telegram_status.CONFIGURATION_ERROR in page.text
        assert 'proxy.invalid' not in page.text
        assert client.post('/telegram-webhook').status_code == 403
        assert client.post('/telegram-webhook', headers={
            'X-Telegram-Bot-Api-Secret-Token': app_module.settings.TELEGRAM_WEBHOOK_SECRET,
        }).status_code == 503
    session.assert_not_called()


def test_callback_uses_proxy_and_keeps_saved_reaction_on_acknowledgement_failure(app_client, app_module, monkeypatch):
    proxy = 'socks5://proxy.invalid:1080'
    monkeypatch.setitem(app_module.config['SERVER'], 'bot_proxy', proxy)
    monkeypatch.setattr(app_module, 'get_postfix_by_tgid', AsyncMock(return_value='reporter'))
    calls = []

    @asynccontextmanager
    async def post(url, **options):
        assert options['allow_redirects'] is False
        calls.append((url.rsplit('/', 1)[-1], options))
        if calls[-1][0] == 'answerCallbackQuery':
            raise ProxyConnectionError('proxy credentials')
        yield SimpleNamespace(status=200, json=AsyncMock(return_value={'ok': True}))

    session = Mock()

    @asynccontextmanager
    async def fake_session(url):
        session(url)
        yield SimpleNamespace(post=post)

    monkeypatch.setattr(app_module, 'telegram_session', fake_session)
    with app_client as client:
        headers = {
            'X-Telegram-Bot-Api-Secret-Token': app_module.settings.TELEGRAM_WEBHOOK_SECRET,
        }
        callback = {'id': 'test', 'from': {'id': 123}, 'message': {'chat': {'id': 456}, 'message_id': 1}}
        reaction_ids = set()
        for prefix in ('A', 'A', 'NA'):
            callback['data'] = f'{prefix}_123_ZTF17aabvfza'
            response = client.post('/telegram-webhook', headers=headers, json={'callback_query': callback})
            assert response.status_code == 200
            saved = client.portal.call(app_module.reactions.find_with_candid, '123', 'reporter')
            assert saved.tag == ('ANOMALY' if prefix == 'A' else 'NOT ANOMALY')
            reaction_ids.add(saved.id)
        assert len(reaction_ids) == 1
    assert [call.args for call in session.call_args_list] == [('socks5h://proxy.invalid:1080',)] * 3
    assert [call[0] for call in calls] == [
        'answerCallbackQuery', 'editMessageReplyMarkup', 'answerCallbackQuery',
        'answerCallbackQuery', 'editMessageReplyMarkup',
    ]
    assert calls[1][1]['json']['chat_id'] == 456
