"""Ownership, Telegram authentication and untrusted content regressions."""
import datetime
import json
import subprocess
from unittest.mock import AsyncMock, Mock

from bs4 import BeautifulSoup
import pytest

from tests.test_known_regressions import insert, victim_row


@pytest.fixture(params=['mongo', 'sqlite'])
def owned_store(request, client, monkeypatch):
    if request.param == 'mongo':
        from database.mongo import Database
        from models.mongo import reaction
        yield Database(reaction), reaction
    else:
        from database.sqlalchemy import Base, reaction
        from sqlmodel import SQLModel, create_engine
        from sqlalchemy.pool import StaticPool
        engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        monkeypatch.setattr(Base, 'engine', engine)
        SQLModel.metadata.create_all(engine)
        try:
            yield reaction, reaction
        finally:
            engine.dispose()


def test_atomic_mutations_select_both_id_and_owner(client, owned_store):
    store, model = owned_store
    async def exercise():
        row = model(ztf_id='ZTF17aabvfza', tag='ANOMALY', user='owner', changed_at='old')
        await store.save(row)
        assert not await store.update_owned(row.id, 'intruder', {'tag': 'NOT ANOMALY'})
        assert not await store.delete_owned(row.id, 'intruder')
        assert (await store.get(row.id)).tag == 'ANOMALY'
        changed = await store.update_owned(row.id, 'owner', {'tag': 'NOT ANOMALY', 'changed_at': 'new'})
        assert changed.user == 'owner' and changed.tag == 'NOT ANOMALY'
        assert changed.changed_at == 'new'
        assert await store.delete_owned(row.id, 'owner')
        assert not await store.delete_owned(row.id, 'owner')
        assert not await store.update_owned(row.id, 'owner', {'tag': 'ANOMALY'})
    client.portal.call(exercise)


def test_bulk_delete_preserves_other_owners(client, owned_store):
    store, model = owned_store
    async def exercise():
        for user in ['owner', 'owner', 'victim']:
            await store.save(model(ztf_id='ZTF17aabvfza', tag='ANOMALY', user=user, changed_at='old'))
        assert await store.delete_all_with_user('owner')
        remaining = await store.get_all()
        assert len(remaining) == 1 and remaining[0].user == 'victim'
        assert not await store.delete_all_with_user('owner')
    client.portal.call(exercise)


def test_owner_can_update_and_delete_reaction(client, headers):
    from models.mongo import reaction
    identifier = insert(client, reaction, ztf_id='ZTF17aabvfza', user='reporter', tag='ANOMALY',
                        candid_id='123', changed_at='2000-01-01 00:00:00.000001')
    response = client.put('/reaction/' + identifier, headers=headers, json={'tag': 'NOT ANOMALY'})
    assert response.status_code == 200
    assert response.json()['user'] == 'reporter'
    assert response.json()['candid_id'] == '123'
    assert response.json()['changed_at'] != '2000-01-01 00:00:00.000001'
    assert client.delete('/reaction/' + identifier, headers=headers).status_code == 200
    assert client.delete('/reaction/' + identifier, headers=headers).status_code == 404


@pytest.mark.parametrize('field,value', [('user', 'victim'), ('id', 'other'), ('_id', 'other'),
    ('ztf_id', 'other'), ('candid_id', 'other'), ('changed_at', '2000-01-01')])
def test_update_rejects_identity_and_timestamp_fields(client, headers, field, value):
    identifier = victim_row(client)
    response = client.put('/reaction/' + identifier, headers=headers,
                          json={'tag': 'NOT ANOMALY', field: value})
    assert response.status_code == 422
    from models.mongo import reaction
    from beanie import PydanticObjectId
    stored = client.portal.call(reaction.get, PydanticObjectId(identifier))
    assert stored.user == 'victim' and stored.tag == 'ANOMALY'


def test_bulk_delete_own_reactions_is_allowed(client, headers):
    from models.mongo import reaction
    insert(client, reaction, ztf_id='ZTF17aabvfza', user='reporter', tag='ANOMALY')
    victim = victim_row(client)
    assert client.delete('/reaction/delete_user/reporter', headers=headers).status_code == 200
    assert client.delete('/reaction/delete_user/reporter', headers=headers).status_code == 404
    from beanie import PydanticObjectId
    assert client.portal.call(reaction.get, PydanticObjectId(victim)) is not None


@pytest.mark.parametrize('credential', [None, '', 'wrong'])
def test_webhook_rejects_credential_before_parsing_json(client, app_module, monkeypatch, credential):
    handler = AsyncMock()
    monkeypatch.setattr(app_module, 'handle_callback_query', handler)
    headers = {} if credential is None else {'X-Telegram-Bot-Api-Secret-Token': credential}
    response = client.post('/telegram-webhook', headers=headers, content=b'not-json')
    assert response.status_code == 403
    handler.assert_not_awaited()


@pytest.mark.parametrize('secret', [None, '', 'bad space', 'x' * 257])
def test_unconfigured_webhook_fails_closed(client, app_module, monkeypatch, secret):
    monkeypatch.setattr(app_module.settings, 'TELEGRAM_WEBHOOK_SECRET', secret)
    assert client.post('/telegram-webhook', content=b'not-json').status_code == 503


def test_signed_telegram_callback_reaches_handler(client, app_module, monkeypatch):
    handler = AsyncMock()
    monkeypatch.setattr(app_module, 'handle_callback_query', handler)
    response = client.post('/telegram-webhook', headers={
        'X-Telegram-Bot-Api-Secret-Token': app_module.settings.TELEGRAM_WEBHOOK_SECRET},
        json={'callback_query': {'id': 'test', 'from': {'id': 123},
             'message': {'chat': {'id': 456}, 'message_id': 1}, 'data': 'A_123_ZTF17aabvfza'}})
    assert response.status_code == 200
    handler.assert_awaited_once()
    assert handler.call_args.args[0].from_user['id'] == 123


def test_signed_regular_update_reaches_bot(client, app_module, monkeypatch):
    process = Mock()
    monkeypatch.setattr(app_module.bot, 'process_new_updates', process)
    response = client.post('/telegram-webhook', headers={
        'X-Telegram-Bot-Api-Secret-Token': app_module.settings.TELEGRAM_WEBHOOK_SECRET},
        json={'update_id': 1})
    assert response.status_code == 200
    process.assert_called_once()


@pytest.mark.parametrize('payload', [
    '<img src=x onerror="alert(1)">', '<script>alert(1)</script>',
    '<svg onload="alert(1)"></svg>', '<iframe srcdoc="<script>alert(1)</script>"></iframe>',
    '<a href="javascript:alert(1)" onclick="alert(1)">click</a>',
    '<a href="jav&#x61;script:alert(1)">click</a>', '<a href="data:text/html,test">click</a>',
    '<style>body {display:none}</style><p style="position:fixed" id="tns-form">text</p>',
])
def test_description_sanitizer_removes_executable_html(payload):
    from rendering import render_description
    html = BeautifulSoup(str(render_description(payload)), 'html.parser')
    assert not html.select('img, script, svg, iframe, style, [id], [style], [onclick], [onerror], [onload]')
    assert not [a for a in html.select('[href]') if a['href'].lower().startswith(('javascript:', 'data:'))]


def test_description_preserves_safe_markdown_and_links():
    from rendering import render_description
    html = BeautifulSoup(str(render_description('**Candidate**  \n[object](https://fink-portal.org/ZTF17aabvfza)')), 'html.parser')
    assert html.strong.text == 'Candidate'
    assert html.br is not None
    assert html.a['href'] == 'https://fink-portal.org/ZTF17aabvfza'
    assert set(html.a['rel']) == {'noopener', 'noreferrer'}


def test_untrusted_identifiers_are_js_values_not_code(client, headers):
    from models.mongo import ImageDocument
    payload = "');globalThis.injected = true;//"
    now = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S.%f')
    insert(client, ImageDocument, user='reporter', ztf_id=payload, candid_id=payload, description='UTC: ' + now)
    client.cookies.set('access_token', headers['Authorization'])
    soup = BeautifulSoup(client.get('/').text, 'html.parser')
    handler = soup.select_one('#tiles button[onclick^="add_anomaly"]')['onclick']
    script = 'let result; function add_anomaly(...args) {result=args;}\n' + handler + '\nif (globalThis.injected) process.exit(1); console.log(JSON.stringify(result));'
    result = subprocess.run(['node', '-e', script], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)[:2] == [payload, payload]


def test_username_is_not_evaluated_in_template_scripts(client):
    payload = 'user` ${globalThis.injected = true} </script>'
    assert client.post('/user/signup', json={'name': payload, 'password': 'test'}).status_code == 200
    token = client.post('/user/signin', data={'username': payload, 'password': 'test'}).json()['access_token']
    client.cookies.set('access_token', 'Bearer ' + token)
    soup = BeautifulSoup(client.get('/').text, 'html.parser')
    scripts = [script.string or '' for script in soup.select('script:not([src])')]
    prelude = """const vm = require('node:vm'); const callbacks=[]; const context = {
        document: {getElementById: () => ({style: {}, addEventListener() {}}),
                   addEventListener(type, callback) {callbacks.push(callback);}},
        window: {addEventListener(type, callback) {callbacks.push(callback);}},
        fetch: () => Promise.resolve({ok: true, text: async () => '', json: async () => ({})}),
        setInterval(callback) {callbacks.push(callback); return 1;}, clearInterval() {}, console
    }; vm.createContext(context);"""
    code = prelude + 'for (const source of ' + json.dumps(scripts) + ') vm.runInContext(source,context);'
    code += '(async () => {for (let i=0; i<callbacks.length; i++) await callbacks[i](); await context.window.onload(); if (context.injected) process.exit(1);})().catch(error => {console.error(error); process.exit(1);});'
    result = subprocess.run(['node', '-e', code], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('secret', ['a', 'A_z-09', 'x' * 256])
def test_telegram_secret_accepts_documented_alphabet_and_lengths(secret):
    from auth.webhook import validate_webhook_secret
    assert validate_webhook_secret(secret) == secret
