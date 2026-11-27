"""Regression tests for ownership, webhooks, rendering, and image handling."""
import datetime
from pathlib import Path
from unittest.mock import AsyncMock

from bs4 import BeautifulSoup
import pytest

OID = 'ZTF17aabvfza'


def insert(client, model, **fields):
    async def create():
        row = model(**fields)
        await row.insert()
        return str(row.id)
    return client.portal.call(create)


def victim_row(client):
    from models.mongo import reaction
    return insert(client, reaction, ztf_id=OID, user='victim', tag='ANOMALY', changed_at='2026-11-11 00:00:00.000001')


@pytest.mark.parametrize('operation', ['update', 'delete', 'bulk_delete'])
def test_other_users_reactions_are_protected(client, headers, operation):
    identifier = victim_row(client)
    if operation == 'update':
        response = client.put('/reaction/' + identifier, headers=headers, json={
            'tag': 'NOT ANOMALY'})
    elif operation == 'delete':
        response = client.delete('/reaction/' + identifier, headers=headers)
    else:
        response = client.delete('/reaction/delete_user/victim', headers=headers)
    assert response.status_code in (403, 404)
    from models.mongo import reaction
    from beanie import PydanticObjectId
    row = client.portal.call(reaction.get, PydanticObjectId(identifier))
    assert row is not None and row.tag == 'ANOMALY'


def test_other_users_images_are_protected(client, headers, tmp_path):
    from models.mongo import ImageDocument
    identifier = insert(client, ImageDocument, ztf_id=OID, user='victim', description='Fixture')
    image = tmp_path / 'static' / f'{identifier}_curve.png'
    image.write_bytes(b'other user image')
    assert client.delete('/images/' + identifier, headers=headers).status_code in (403, 404)
    assert image.read_bytes() == b'other user image'


def test_unsigned_telegram_callback_is_rejected(client, app_module, monkeypatch):
    handler = AsyncMock()
    monkeypatch.setattr(app_module, 'handle_callback_query', handler)
    response = client.post('/telegram-webhook', json={'callback_query': {
        'id': 'fake', 'from': {'id': 123}, 'message': {'chat': {'id': 456}, 'message_id': 1},
        'data': 'A_123_ZTF17aabvfza'}})
    assert response.status_code in (401, 403)
    handler.assert_not_awaited()


def test_notification_html_cannot_execute_event_handlers(client, headers):
    from models.mongo import ImageDocument
    now = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S.%f')
    insert(client, ImageDocument, user='reporter', ztf_id=OID,
           description=f'UTC: {now}\n<img src=x onerror="alert(1)">')
    client.cookies.set('access_token', headers['Authorization'])
    response = client.get('/')
    assert response.status_code == 200
    soup = BeautifulSoup(response.text, 'html.parser')
    assert len(soup.select('#tiles .tile')) == 1  # cannot pass by hiding the card
    assert not soup.select('#tiles [onerror]')


@pytest.mark.parametrize('changed_at, displayed', [
    ('2026-11-11 00:00:00', '2026-11-11 00:00:00'),
    (None, '—'),
    ('bad date', '—'),
])
def test_bad_reaction_timestamp_does_not_hide_fresh_notification(client, headers, changed_at, displayed):
    from models.mongo import ImageDocument, reaction
    now = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S.%f')
    insert(client, ImageDocument, user='reporter', ztf_id=OID, description='UTC: ' + now)
    insert(client, reaction, user='reporter', ztf_id=OID, tag='ANOMALY', changed_at=changed_at)
    client.cookies.set('access_token', headers['Authorization'])
    response = client.get('/')
    assert response.status_code == 200
    page = BeautifulSoup(response.text, 'html.parser')
    assert len(page.select('#tiles .tile')) == 1
    assert page.select_one('#work tbody tr').select('td')[3].get_text(strip=True) == displayed


def test_upload_storage_failure_is_not_reported_as_success(client, headers, tmp_path):
    from tests.test_main import upload
    (tmp_path / 'static').rmdir()
    (tmp_path / 'static').write_text('Not a directory')
    response = upload(client, headers)
    assert response.status_code >= 500
    from models.mongo import ImageDocument
    async def count(): return await ImageDocument.count()
    assert client.portal.call(count) == 0


def test_notification_deletion_removes_its_files(client, headers, tmp_path):
    from tests.test_main import upload
    identifier = upload(client, headers).json()['id']
    assert client.delete('/images/' + identifier, headers=headers).status_code == 200
    assert not (tmp_path / 'static' / f'{identifier}_curve.png').exists()
    assert not (tmp_path / 'static' / f'{identifier}_cutout.png').exists()


def test_notifications_survive_reaction_history_query_failure(client, headers, monkeypatch):
    from main import reactions
    from models.mongo import ImageDocument

    now = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S.%f')
    insert(client, ImageDocument, user='reporter', ztf_id=OID, description='UTC: ' + now)
    monkeypatch.setattr(reactions, 'find_with_user', AsyncMock(side_effect=RuntimeError('history unavailable')))
    client.cookies.set('access_token', headers['Authorization'])
    response = client.get('/')
    assert response.status_code == 200
    assert len(BeautifulSoup(response.text, 'html.parser').select('#tiles .tile')) == 1


def test_failure_publishing_second_image_removes_first_image_and_record(client, headers, tmp_path, monkeypatch):
    from models.mongo import ImageDocument
    from tests.test_main import upload

    replace = Path.replace

    def fail_cutout(path, target):
        if path.name == 'cutout.png':
            raise OSError('unable to publish cutout')
        return replace(path, target)

    monkeypatch.setattr(Path, 'replace', fail_cutout)
    assert upload(client, headers).status_code == 500
    assert client.portal.call(ImageDocument.count) == 0
    assert list((tmp_path / 'static').iterdir()) == []


def test_database_insert_failure_removes_published_images(client, headers, tmp_path, monkeypatch):
    from models.mongo import ImageDocument
    from tests.test_main import upload

    monkeypatch.setattr(ImageDocument, 'create', AsyncMock(side_effect=RuntimeError('insert failed')))
    assert upload(client, headers).status_code == 500
    assert list((tmp_path / 'static').iterdir()) == []


def test_notification_deletion_can_retry_after_partial_cleanup(client, headers, tmp_path):
    from beanie import PydanticObjectId
    from models.mongo import ImageDocument
    from tests.test_main import upload

    identifier = upload(client, headers).json()['id']
    cutout = tmp_path / 'static' / f'{identifier}_cutout.png'
    cutout.unlink()
    cutout.mkdir()

    assert client.delete(f'/images/{identifier}', headers=headers).status_code == 500
    assert client.portal.call(ImageDocument.get, PydanticObjectId(identifier)) is not None

    cutout.rmdir()
    assert client.delete(f'/images/{identifier}', headers=headers).status_code == 200
    assert client.portal.call(ImageDocument.get, PydanticObjectId(identifier)) is None
