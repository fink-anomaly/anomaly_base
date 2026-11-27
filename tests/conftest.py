"""Run the real application against disposable, in-memory Mongo collections."""
import importlib
from pathlib import Path
import socket

import pytest

from TNS.client import TNSSettings

OID = 'ZTF17aabvfza'

SOURCE = Path(__file__).resolve().parents[1] / 'src' / 'anomaly'


@pytest.fixture(autouse=True)
def no_external_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError('Tests must stub external network calls')
    monkeypatch.setattr(socket.socket, 'connect', blocked)
    monkeypatch.setattr(socket.socket, 'connect_ex', blocked)


@pytest.fixture(scope='session')
def app_module(tmp_path_factory):
    """Import once with fake credentials, outside any user's .env/INI files."""
    with pytest.MonkeyPatch.context() as patch:
        directory = tmp_path_factory.mktemp('app-import')
        (directory / 'static').mkdir()
        patch.chdir(directory)
        for key, value in {
            'DATABASE_URL': 'mongodb://unused.invalid/test',
            'SECRET_KEY': 'test-only-signing-key', 'TG_TOKEN': '12345:test-only-token',
            'TELEGRAM_WEBHOOK_SECRET': 'test-only-webhook-secret',
        }.items():
            patch.setenv(key, value)
        module = importlib.import_module('main')
        module.config['SERVER'] = {'init_bot': 'false'}
        from fastapi.templating import Jinja2Templates
        patch.setattr(module, 'templates', Jinja2Templates(directory=str(SOURCE / 'templates')))
        yield module


@pytest.fixture
def app_client(app_module, tmp_path, monkeypatch):
    from beanie import init_beanie
    from fastapi.testclient import TestClient
    from mongomock_motor import AsyncMongoMockClient
    from database.settings import Settings
    from models.mongo import ImageDocument, User, reaction

    monkeypatch.chdir(tmp_path)
    (tmp_path / 'static').mkdir()

    async def initialize(_):
        mock = AsyncMongoMockClient()
        await init_beanie(database=mock.test, document_models=[User, reaction, ImageDocument])
        app_module.app.state.test_database = mock.test

    monkeypatch.setattr(Settings, 'initialize_database', initialize)
    return TestClient(app_module.app)


@pytest.fixture
def client(app_client):
    with app_client as result:
        yield result


@pytest.fixture
def headers(client):
    signup = client.post('/user/signup', json={'name': 'reporter', 'password': 'test-password'})
    assert signup.status_code == 200
    signin = client.post('/user/signin', data={'username': 'reporter', 'password': 'test-password'})
    assert signin.status_code == 200
    return {'Authorization': 'Bearer ' + signin.json()['access_token']}


@pytest.fixture
def settings(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for name, value in {'KEY': 'test-key', 'BOT_ID': '123', 'BOT_NAME': 'test-bot',
                        'ENVIRONMENT': 'sandbox', 'ALLOWED_USERS': 'reporter'}.items():
        monkeypatch.setenv('TNS_' + name, value)
    return TNSSettings.load()


@pytest.fixture
def light_curve():
    # Deliberately unordered. Wrong-band, post-discovery and bad-quality points
    # must never be selected as the preceding non-detection.
    def point(jd, tag='valid', fid=1, **extra):
        return {'i:objectId': OID, 'd:tag': tag, 'i:jd': 2460000 + jd,
                'i:fid': fid, 'i:magpsf': 19., 'i:sigmapsf': .1,
                'i:diffmaglim': 21., 'i:ra': 12., 'i:dec': -20., **extra}
    return [point(3), point(1), point(2, 'upperlim'), point(.9, 'upperlim', 2),
            point(.5, 'upperlim'), point(.8, 'badquality'), point(0, 'upperlim')]
