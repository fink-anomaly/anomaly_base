"""Independent API smoke tests; every test gets a fresh mock database."""
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent
OID = 'ZTF17aabvfza'


def upload(client, headers, **extra):
    with (FIXTURES / 'test_curve.png').open('rb') as curve, (FIXTURES / 'test_cutout.png').open('rb') as cutout:
        return client.post('/images/upload', headers=headers,
                           params={'ztf_id': OID, 'candid_id': '123'},
                           data={'description': 'Fixture description', **extra},
                           files={'image1': curve, 'image2': cutout})


def test_user_create(client):
    response = client.post('/user/signup', json={'name': 'beta', 'password': 'testpwd'})
    assert response.status_code == 200
    from models.mongo import User
    user = client.portal.call(User.find_one, User.name == 'beta')
    assert user.password != 'testpwd'


def test_login(client, headers):
    assert headers['Authorization'].startswith('Bearer ')


def test_duplicate_registration(client, headers):
    assert client.post('/user/signup', json={'name': 'reporter', 'password': 'other'}).status_code == 409


@pytest.mark.parametrize('username,password,status', [('reporter', 'wrong', 401), ('missing', 'wrong', 404)])
def test_login_failure(client, headers, username, password, status):
    response = client.post('/user/signin', data={'username': username, 'password': password})
    assert response.status_code == status
    assert 'access_token' not in response.json()


def test_notification(client, headers, tmp_path):
    response = upload(client, headers)
    assert response.status_code == 200
    identifier = response.json()['id']
    assert (tmp_path / 'static' / f'{identifier}_curve.png').read_bytes() == (FIXTURES / 'test_curve.png').read_bytes()
    assert (tmp_path / 'static' / f'{identifier}_cutout.png').read_bytes() == (FIXTURES / 'test_cutout.png').read_bytes()


def test_mark_anomaly(client, headers):
    response = client.post('/reaction/new', headers=headers, json={'ztf_id': OID, 'candid_id': '123', 'tag': 'ANOMALY'})
    assert response.status_code == 200
    rows = client.get('/reaction/').json()
    assert len(rows) == 1
    assert rows[0]['user'] == 'reporter'
    assert rows[0]['tag'] == 'ANOMALY'
    assert rows[0]['candid_id'] == '123'
    assert rows[0]['changed_at']


def test_delete_image(client, headers):
    identifier = upload(client, headers).json()['id']
    assert client.delete(f'/images/{identifier}', headers=headers).status_code == 200
    assert client.delete(f'/images/{identifier}', headers=headers).status_code == 404


def test_unauthenticated_writes_are_rejected(client):
    assert client.post('/reaction/new', json={'ztf_id': OID, 'tag': 'ANOMALY'}).status_code == 401
    assert upload(client, {}).status_code == 401


def test_home_anonymous(client):
    response = client.get('/')
    assert response.status_code == 200
    assert 'id="tns-form"' not in response.text


def test_logout_clears_login_cookie(client, headers):
    client.cookies.set('access_token', headers['Authorization'])
    response = client.post('/user/logout')
    assert response.status_code == 200
    assert 'access_token=""' in response.headers['set-cookie']


def test_logged_in_home_preserves_token_and_shows_fresh_card(client, headers):
    import datetime
    import json
    import re
    from bs4 import BeautifulSoup
    now = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S.%f')
    assert upload(client, headers, description='UTC: ' + now).status_code == 200
    client.cookies.set('access_token', headers['Authorization'])
    response = client.get('/')
    soup = BeautifulSoup(response.text, 'html.parser')
    assert len(soup.select('#tiles .tile')) == 1
    assert soup.select_one('#tns-form')['data-user'] == 'reporter'
    assert soup.select_one('#tns-destination')['name'] == 'environment'
    assert soup.select_one('#tns-confirm').has_attr('required')
    match = re.search(r'const token_ = (.+);', response.text)
    assert json.loads(match.group(1)) == headers['Authorization']


@pytest.mark.parametrize('description', ['No timestamp', 'UTC: 2020-01-01 00:00:00.000'])
def test_old_or_undated_cards_are_hidden(client, headers, description):
    from bs4 import BeautifulSoup
    assert upload(client, headers, description=description).status_code == 200
    client.cookies.set('access_token', headers['Authorization'])
    assert not BeautifulSoup(client.get('/').text, 'html.parser').select('#tiles .tile')
