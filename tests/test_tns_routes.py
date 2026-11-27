"""Exercise real FastAPI validation and JWT auth, without a database or network."""
import importlib
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from TNS.client import TNSUpstreamError


@pytest.fixture
def api(monkeypatch, tmp_path, app_module):
    monkeypatch.chdir(tmp_path)
    for key, value in {'TNS_KEY': 'test-key', 'TNS_BOT_ID': '123',
                       'TNS_BOT_NAME': 'test-bot', 'TNS_ENVIRONMENT': 'sandbox',
                       'TNS_ALLOWED_USERS': 'reporter'}.items():
        monkeypatch.setenv(key, value)
    # Import after isolating configuration. Do not initialize the real app or DB.
    users = importlib.import_module('routes.users')
    app = FastAPI()
    app.include_router(users.user_router, prefix='/user')
    token = users.create_access_token('reporter')
    return TestClient(app), users, {'Authorization': f'Bearer {token}'}


def form_data(**extra):
    return dict(object_id='ZTF17aabvfza', remarks='Test', reporter='A. Reporter', at_type='4',
                environment='sandbox', **extra)


def test_no_authentication(api):
    client, _, _ = api
    assert client.post('/user/submitTNS', data=form_data()).status_code == 401
    assert client.get('/user/tns/reports/42').status_code == 401


def test_receipt_and_environment(api, monkeypatch):
    client, users, headers = api
    transfer = Mock(return_value={'status': 'pending', 'report_id': 42, 'environment': 'sandbox'})
    monkeypatch.setattr(users, 'tns_transfer', transfer)
    response = client.post('/user/submitTNS', data=form_data(), headers=headers)
    assert response.status_code == 202
    assert response.json()['status'] == 'pending'
    assert transfer.call_args.kwargs['attype'] == '4'
    assert transfer.call_args.kwargs['settings'].environment == 'sandbox'
    config = client.get('/user/tns/config', headers=headers)
    assert config.json() == {'environment': 'sandbox'}
    assert 'test-key' not in config.text


def test_registered_user_cannot_use_shared_bot(api, monkeypatch):
    client, users, _ = api
    transfer = Mock()
    monkeypatch.setattr(users, 'tns_transfer', transfer)
    headers = {'Authorization': 'Bearer ' + users.create_access_token('someone_else')}
    assert client.post('/user/submitTNS', data=form_data(), headers=headers).status_code == 403
    assert client.get('/user/tns/reports/42', headers=headers).status_code == 403
    transfer.assert_not_called()


def test_environment_change_never_submits(api, monkeypatch):
    client, users, headers = api
    transfer = Mock()
    monkeypatch.setattr(users, 'tns_transfer', transfer)
    data = form_data()
    data['environment'] = 'production'
    assert client.post('/user/submitTNS', data=data, headers=headers).status_code == 409
    transfer.assert_not_called()


@pytest.mark.parametrize('error,code', [(ValueError('Invalid light curve'), 422), (TNSUpstreamError('Unknown outcome'), 502)])
def test_http_error_mapping(api, monkeypatch, error, code):
    client, users, headers = api
    monkeypatch.setattr(users, 'tns_transfer', Mock(side_effect=error))
    response = client.post('/user/submitTNS', data=form_data(), headers=headers)
    assert response.status_code == code
    assert response.json()['detail'] == str(error)


def test_missing_configuration_is_actionable(api, monkeypatch):
    client, _, headers = api
    monkeypatch.setenv('TNS_KEY', '')
    response = client.get('/user/tns/config', headers=headers)
    assert response.status_code == 503
    assert 'TNS_KEY' in response.json()['detail']


def test_status_only_retrieves_existing_receipt(api, monkeypatch):
    client, users, headers = api
    reply = Mock(return_value={'status': 'submitted', 'report_id': 42, 'environment': 'sandbox'})
    transfer = Mock()
    monkeypatch.setattr(users, 'report_reply', reply)
    monkeypatch.setattr(users, 'tns_transfer', transfer)
    response = client.get('/user/tns/reports/42', headers=headers)
    assert response.status_code == 200
    assert response.json()['status'] == 'submitted'
    assert reply.call_args.args[1] == 42
    assert client.get('/user/tns/reports/0', headers=headers).status_code == 422
    transfer.assert_not_called()


@pytest.mark.parametrize('field', ['object_id', 'remarks', 'reporter', 'at_type', 'environment'])
def test_missing_form_fields_never_submit(api, monkeypatch, field):
    client, users, headers = api
    transfer = Mock()
    monkeypatch.setattr(users, 'tns_transfer', transfer)
    data = form_data()
    data.pop(field)
    assert client.post('/user/submitTNS', data=data, headers=headers).status_code == 422
    transfer.assert_not_called()


@pytest.mark.parametrize('identifier', ['-1', '0', 'invalid', '1.5'])
def test_invalid_status_identifiers_never_contact_tns(api, monkeypatch, identifier):
    client, users, headers = api
    reply = Mock()
    monkeypatch.setattr(users, 'report_reply', reply)
    assert client.get('/user/tns/reports/' + identifier, headers=headers).status_code == 422
    reply.assert_not_called()


def test_empty_allowlist_denies_even_valid_token(api, monkeypatch):
    client, users, headers = api
    monkeypatch.setenv('TNS_ALLOWED_USERS', '')
    transfer = Mock()
    monkeypatch.setattr(users, 'tns_transfer', transfer)
    assert client.post('/user/submitTNS', data=form_data(), headers=headers).status_code == 403
    assert client.get('/user/tns/config', headers=headers).status_code == 403
    transfer.assert_not_called()


@pytest.mark.parametrize('token_kind,expected', [('invalid', 400), ('expired', 403), ('wrong_secret', 400)])
def test_bad_jwt_cannot_send(api, monkeypatch, token_kind, expected):
    import time
    from jose import jwt
    from auth.authenticate import settings
    client, users, _ = api
    token = 'invalid'
    if token_kind != 'invalid':
        token = jwt.encode({'user': 'reporter', 'expires': time.time() - 1 if token_kind == 'expired' else time.time() + 60},
                           'wrong' if token_kind == 'wrong_secret' else settings.SECRET_KEY, algorithm='HS256')
    transfer = Mock()
    monkeypatch.setattr(users, 'tns_transfer', transfer)
    assert client.post('/user/submitTNS', data=form_data(), headers={'Authorization': 'Bearer ' + token}).status_code == expected
    transfer.assert_not_called()


def test_real_transfer_route_to_feedback(api, settings, light_curve, monkeypatch):
    import requests
    from tests.test_tns import response
    client, _, headers = api
    post = Mock(side_effect=[
        response(light_curve), response({'id_code': 200, 'data': {'report_id': 42}}),
        response({'id_code': 404}, 404),
        response({'id_code': 200, 'data': {'feedback': {'at_report': [{'at_rep': {'103': {'message': 'Submitted'}}}]}}}),
    ])
    monkeypatch.setattr(requests, 'post', post)
    receipt = client.post('/user/submitTNS', data=form_data(), headers=headers)
    assert receipt.status_code == 202
    assert receipt.json()['report_id'] == 42
    assert client.get('/user/tns/reports/42', headers=headers).json()['status'] == 'pending'
    assert client.get('/user/tns/reports/42', headers=headers).json()['status'] == 'submitted'
    assert [call.args[0].split('/api')[-1] for call in post.call_args_list[1:]] == ['/set/bulk-report', '/get/bulk-report-reply', '/get/bulk-report-reply']
