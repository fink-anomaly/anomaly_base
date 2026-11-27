import json
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest
import requests

from TNS.client import TNSConfigurationError, TNSSettings, TNSUpstreamError, report_reply, submit_report
from TNS.report import build_report_api, extract_discovery_photometry_api
from TNS.submit import tns_transfer

OID = 'ZTF17aabvfza'


def response(payload, status=200):
    result = Mock(status_code=status)
    result.json.return_value = payload
    if status >= 400:
        result.raise_for_status.side_effect = requests.HTTPError()
    return result



def test_discovery_and_same_band_upper_limit(light_curve):
    photometry, non_detection = extract_discovery_photometry_api(pd.DataFrame(light_curve))
    assert photometry['obsdate'] > non_detection['obsdate']
    assert photometry['filterid'] == non_detection['filterid'] == '110'
    expected, _ = extract_discovery_photometry_api(pd.DataFrame([light_curve[1], light_curve[4]]))
    assert expected == photometry
    assert non_detection['obsdate'].endswith('00:00:00.000')  # JD 2460000.5


@pytest.mark.parametrize('mode', ['empty', 'only_limits', 'no_limit', 'bad_mag', 'bad_filter', 'no_tag', 'negative'])
def test_bad_photometry_is_rejected(light_curve, mode):
    data = pd.DataFrame(light_curve)
    if mode == 'empty': data = data.iloc[:0]
    if mode == 'only_limits': data = data[data['d:tag'] == 'upperlim']
    if mode == 'no_limit': data = data[data['d:tag'] != 'upperlim']
    if mode == 'bad_mag': data.loc[data['d:tag'] == 'valid', 'i:magpsf'] = np.nan
    if mode == 'bad_filter': data.loc[data['d:tag'] == 'valid', 'i:fid'] = 4
    if mode == 'no_tag': data = data.drop(columns='d:tag')
    if mode == 'negative': data['i:isdiffpos'] = 'f'
    with pytest.raises(ValueError):
        extract_discovery_photometry_api(data)


def test_report_uses_tns2_schema_and_custom_fields(light_curve):
    data = pd.DataFrame(light_curve)
    data.loc[data['d:tag'] == 'valid', 'i:ra'] = [359.999, .001]
    photometry, non_detection = extract_discovery_photometry_api(data)
    report = build_report_api(data, photometry, non_detection,
                              reporter_custom='A. Reporter', remarks_custom='literal {unformatted}', at_type_='4')
    assert report['at_type'] == '4'
    assert report['reporter'] == 'A. Reporter'
    assert report['remarks'] == 'literal {unformatted}'
    assert 0 <= report['ra']['value'] < 360
    assert min(report['ra']['value'], 360 - report['ra']['value']) < .001
    assert report['ra']['error'] < 4
    assert report['reporting_groupid'] == '103'
    assert report['data_source_groupid'] == '48'
    assert set(report['photometry']) == {'0'}
    assert {'flux_unitid', 'filterid', 'instrumentid'} <= report['photometry']['0'].keys()
    json.dumps(report, allow_nan=False)


@pytest.mark.parametrize('coordinate', [np.nan, 999, 'bad'])
def test_invalid_coordinates(light_curve, coordinate):
    data = pd.DataFrame(light_curve)
    data['i:ra'] = coordinate
    with pytest.raises(ValueError):
        build_report_api(data, {}, {})


def test_settings_marker_and_legacy_ini(settings, monkeypatch, tmp_path):
    assert json.loads(settings.marker.removeprefix('tns_marker')) == {'tns_id': 123, 'type': 'bot', 'name': 'test-bot'}
    assert settings.url == 'https://sandbox.wis-tns.org/api'
    for key in ['KEY', 'BOT_ID', 'BOT_NAME', 'ENVIRONMENT', 'ALLOWED_USERS']:
        monkeypatch.delenv('TNS_' + key)
    (tmp_path / 'secret_data.ini').write_text('[TNS]\nkey = key%literal\nbot_id = 123\nbot_name = test-bot\nallowed_users = alice, bob\n')
    loaded = TNSSettings.load()
    assert loaded.key == 'key%literal'
    assert loaded.allowed_users == ('alice', 'bob')


@pytest.mark.parametrize('key,value', [('KEY', ''), ('BOT_ID', '-1'), ('BOT_NAME', ''), ('ENVIRONMENT', 'typo')])
def test_invalid_configuration(settings, monkeypatch, key, value):
    monkeypatch.setenv('TNS_' + key, value)
    with pytest.raises(TNSConfigurationError): TNSSettings.load()


def test_transfer_wire_format_and_no_files(settings, light_curve, monkeypatch, tmp_path):
    post = Mock(side_effect=[response(light_curve), response({'id_code': 200, 'data': {'report_id': 42}})])
    monkeypatch.setattr(requests, 'post', post)
    result = tns_transfer(OID, 'Object {} {literal}', 'A. Reporter', '4')
    assert result == {'status': 'pending', 'report_id': 42, 'environment': 'sandbox'}
    args, kwargs = post.call_args
    assert args[0] == settings.url + '/set/bulk-report'
    assert kwargs['headers']['User-Agent'] == settings.marker
    assert kwargs['data']['api_key'] == 'test-key'
    report = json.loads(kwargs['data']['data'])['at_report']['0']
    assert report['at_type'] == '4'
    assert report['remarks'] == f'Object {OID} {{literal}}'
    assert kwargs['timeout'] == (5, 30)
    assert kwargs['allow_redirects'] is False
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('field,value', [('objectId', '../../file'), ('reporter', '  '), ('remarks', ''), ('attype', 'type1')])
def test_invalid_input_never_contacts_services(settings, monkeypatch, field, value):
    post = Mock()
    monkeypatch.setattr(requests, 'post', post)
    kwargs = dict(objectId=OID, remarks='remarks', reporter='reporter', attype='1')
    kwargs[field] = value
    with pytest.raises(ValueError): tns_transfer(**kwargs)
    post.assert_not_called()


@pytest.mark.parametrize('payload,status', [({'id_code': 400}, 200), ({'id_code': 403}, 403),
    ({'id_code': 200, 'data': {}}, 200), ({'id_code': 200, 'data': None}, 200),
    ({'id_code': 200, 'data': {'report_id': True}}, 200)])
def test_submission_failures(settings, monkeypatch, payload, status):
    monkeypatch.setattr(requests, 'post', Mock(return_value=response(payload, status)))
    with pytest.raises(TNSUpstreamError): submit_report(settings, {})


def test_timeout_is_never_retried(settings, monkeypatch):
    post = Mock(side_effect=requests.Timeout('do not disclose credentials'))
    monkeypatch.setattr(requests, 'post', post)
    with pytest.raises(TNSUpstreamError, match='outcome may be unknown'):
        submit_report(settings, {})
    assert post.call_count == 1


@pytest.mark.parametrize('payload,status,expected', [
    ({'id_code': 404}, 404, 'pending'),
    ({'id_code': 404}, 200, 'pending'),
    ({'id_code': 200, 'data': {'feedback': {'at_report': [{'100': {'message': 'inserted', 'message_id': 100}, 'at_rep': {'103': {'message': 'Submitted'}}}]}}}, 200, 'submitted'),
    ({'id_code': 200, 'data': {'feedback': {'at_report': [{'ra': {'0': {'message': 'invalid'}}, '100': {'message': 'inserted'}}]}}}, 200, 'rejected'),
    ({'id_code': 200, 'data': {'feedback': {'at_report': {'0': {'at_rep': {'103': {'message': 'Submitted'}}}}}}}, 200, 'submitted'),
    ({'id_code': 200, 'data': {'feedback': {'at_report': [{'101': {'message': 'exists'}}]}}}, 200, 'review'),
])
def test_processing_feedback(settings, monkeypatch, payload, status, expected):
    post = Mock(return_value=response(payload, status))
    monkeypatch.setattr(requests, 'post', post)
    result = report_reply(settings, 42)
    assert result['status'] == expected
    assert post.call_args.kwargs['data'] == {'api_key': 'test-key', 'report_id': '42'}
    assert post.call_args.args[0].endswith('/get/bulk-report-reply')


def test_auth_error_not_treated_as_pending(settings, monkeypatch):
    monkeypatch.setattr(requests, 'post', Mock(return_value=response({'id_code': 401}, 401)))
    with pytest.raises(TNSUpstreamError): report_reply(settings, 42)


@pytest.mark.parametrize('payload,status', [([], 200), (None, 200), ({'id_code': 404}, 500), ({'id_code': 200}, 302)])
def test_malformed_or_inconsistent_transport_response(settings, monkeypatch, payload, status):
    post = Mock(return_value=response(payload, status))
    monkeypatch.setattr(requests, 'post', post)
    with pytest.raises(TNSUpstreamError):
        report_reply(settings, 42)
    assert post.call_count == 1


def test_non_json_tns_response_does_not_leak_body(settings, monkeypatch):
    reply = response(None)
    reply.json.side_effect = ValueError('private upstream body')
    monkeypatch.setattr(requests, 'post', Mock(return_value=reply))
    with pytest.raises(TNSUpstreamError, match='unreadable') as error:
        submit_report(settings, {})
    assert 'private upstream body' not in str(error.value)


@pytest.mark.parametrize('identifier', [None, 0, -1, 1.5, '', 'not-an-id'])
def test_invalid_receipt_is_not_success(settings, monkeypatch, identifier):
    monkeypatch.setattr(requests, 'post', Mock(return_value=response({'id_code': 200, 'data': {'report_id': identifier}})))
    with pytest.raises(TNSUpstreamError, match='no valid receipt'):
        submit_report(settings, {})


@pytest.mark.parametrize('data', [None, {}, {'feedback': {}}, {'feedback': []}, {'feedback': 'unexpected'}])
def test_missing_feedback_is_not_success(settings, monkeypatch, data):
    monkeypatch.setattr(requests, 'post', Mock(return_value=response({'id_code': 200, 'data': data})))
    with pytest.raises(TNSUpstreamError, match='no processing feedback'):
        report_reply(settings, 42)


def test_blocking_feedback_overrides_submitted_and_ignores_internal_ids(settings, monkeypatch):
    payload = {'id_code': '200', 'data': {'feedback': {'at_report': [
        {'103': {'message': 'Submitted'}, 'internal_ids': {'message_id': 1}},
        {'ra': {'message_id': '3', 'message': 'Required field'}},
    ]}}}
    monkeypatch.setattr(requests, 'post', Mock(return_value=response(payload)))
    result = report_reply(settings, 42)
    assert result['status'] == 'rejected'
    payload['data']['feedback']['at_report'].pop()
    assert report_reply(settings, 42)['status'] == 'submitted'


@pytest.mark.parametrize('failure', ['timeout', 'http', 'json', 'object', 'empty', 'identity', 'missing_identity'])
def test_fink_failure_never_posts_to_tns(settings, light_curve, monkeypatch, failure):
    reply = response(light_curve)
    if failure == 'timeout': reply = requests.Timeout('secret transport detail')
    if failure == 'http': reply = response({'error': 'failure'}, 503)
    if failure == 'json': reply.json.side_effect = ValueError('secret response detail')
    if failure == 'object': reply = response({'unexpected': 'object'})
    if failure == 'empty': reply = response([])
    if failure == 'identity': light_curve[0]['i:objectId'] = 'ZTF00aaaaaaa'
    if failure == 'missing_identity': reply = response([{'d:tag': 'valid'}])
    post = Mock(side_effect=[reply])
    monkeypatch.setattr(requests, 'post', post)
    with pytest.raises((TNSUpstreamError, ValueError)) as error:
        tns_transfer(OID, 'Test remarks', 'Reporter', '1')
    assert post.call_count == 1
    assert 'secret' not in str(error.value)
    assert post.call_args.args[0].startswith('https://api.fink-portal.org/')


@pytest.mark.parametrize('field,value', [('reporter', None), ('reporter', 'x' * 1001),
    ('remarks', None), ('remarks', 'x' * 5001), ('objectId', None), ('attype', 0), ('attype', 6)])
def test_input_boundaries_do_not_contact_services(settings, monkeypatch, field, value):
    post = Mock()
    monkeypatch.setattr(requests, 'post', post)
    kwargs = dict(objectId=OID, remarks='Remarks', reporter='Reporter', attype='1')
    kwargs[field] = value
    with pytest.raises(ValueError):
        tns_transfer(**kwargs)
    post.assert_not_called()


@pytest.mark.parametrize('sign', ['t', '1', True])
def test_positive_difference_and_invalid_limits(light_curve, sign):
    data = pd.DataFrame(light_curve)
    data['i:isdiffpos'] = sign
    data.loc[4, 'i:diffmaglim'] = np.nan
    photometry, non_detection = extract_discovery_photometry_api(data)
    assert non_detection['obsdate'] < photometry['obsdate']
    assert non_detection['obsdate'].endswith('12:00:00.000')  # falls back to JD 2460000


def test_uncertainty_must_not_be_negative(light_curve):
    data = pd.DataFrame(light_curve)
    data.loc[1, 'i:sigmapsf'] = -1
    with pytest.raises(ValueError, match='incomplete or invalid'):
        extract_discovery_photometry_api(data)


def test_report_defaults_and_coordinate_columns(light_curve):
    from TNS.utils import at_type, reporter, remarks
    data = pd.DataFrame(light_curve)
    photometry, non_detection = extract_discovery_photometry_api(data)
    report = build_report_api(data, photometry, non_detection)
    assert report['at_type'] == at_type
    assert report['reporter'] == reporter
    assert report['remarks'] == remarks.format(OID)
    with pytest.raises(ValueError, match='coordinates or identity'):
        build_report_api(data.drop(columns='i:ra'), photometry, non_detection)


def test_production_configuration_and_env_precedence(settings, monkeypatch, tmp_path):
    (tmp_path / 'secret_data.ini').write_text('[TNS]\nkey = other\nenvironment = typo\nbot_id = 999\nbot_name = other\n')
    monkeypatch.setenv('TNS_ENVIRONMENT', 'production')
    loaded = TNSSettings.load()
    assert loaded.url == 'https://www.wis-tns.org/api'
    assert loaded.key == settings.key
    assert loaded.marker == settings.marker
    assert loaded.key not in repr(loaded)
    monkeypatch.delenv('TNS_ALLOWED_USERS')
    assert TNSSettings.load().allowed_users == ()


def test_raw_alert_reporting_and_archival_fallback():
    from TNS.report import extract_discovery_photometry, build_report
    def point(jd, magnitude=19., fid=1):
        return dict(jd=jd, magpsf=magnitude, sigmapsf=.1, diffmaglim=21., fid=fid, ra=12., dec=-20.)
    alert = {'objectId': OID, 'candidate': point(2460003),
             'prv_candidates': [point(2460000, None), point(2460002), point(2460001, None), point(2460001.5, None, 2)]}
    photometry, limit = extract_discovery_photometry(alert)
    assert photometry['obsdate'] > limit['obsdate']
    assert limit['filterid'] == '110'
    assert limit['obsdate'].endswith('12:00:00.000')
    report = build_report(alert, photometry, limit)
    assert report['internal_name'] == OID
    assert report['at_type'] == '1'
    assert report['photometry']['0'] == photometry
    custom = build_report(alert, photometry, limit, reporter_custom='Reporter', remarks_custom='Object {}', at_type_='4')
    assert custom['at_type'] == '4' and custom['remarks'] == 'Object ' + OID
    alert['prv_candidates'] = [point(2460002)]
    _, missing_limit = extract_discovery_photometry(alert)
    assert missing_limit['archiveid'] == '0'
    assert 'not available' in missing_limit['archival_remarks']


def test_explicit_legacy_export_and_send_are_readable(tmp_path, monkeypatch):
    from TNS.report import save_logs_and_return_json_report, send_json_report
    report = {'at_report': {'0': {'internal_name': OID}}}
    filename = save_logs_and_return_json_report(OID, str(tmp_path / 'logs'), [OID], report)
    assert json.loads(__import__('pathlib').Path(filename).read_text()) == report
    assert pd.read_csv(tmp_path / 'logs' / (OID + '.csv'))['id'].tolist() == [OID]
    post = Mock(return_value=response({'id_code': 200}))
    monkeypatch.setattr(requests, 'post', post)
    reply = send_json_report('fake-key', 'https://sandbox.wis-tns.org/api', filename, 'fake-marker')
    assert reply.json()['id_code'] == 200
    fields = dict(post.call_args.kwargs['files'])
    assert fields['api_key'] == (None, 'fake-key')
    assert json.loads(fields['data'][1]) == report
    assert post.call_args.kwargs['timeout'] == (5, 30)
    assert post.call_args.kwargs['allow_redirects'] is False


def test_circular_mean_rounding_stays_inside_ra_range(light_curve):
    data = pd.DataFrame(light_curve)
    data.loc[data['d:tag'] == 'valid', 'i:ra'] = [1., 359.]
    photometry, non_detection = extract_discovery_photometry_api(data)
    report = build_report_api(data, photometry, non_detection)
    assert report['ra']['value'] == pytest.approx(0, abs=1e-12)
