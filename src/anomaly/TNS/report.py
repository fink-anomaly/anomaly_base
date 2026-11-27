# Copyright 2020 AstroLab Software
# Author: Julien Peloton
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import os
import json
import requests
from collections import OrderedDict

from .utils import extract_radec
from .utils import inst_units, filters_dict, instrument
from .utils import reporting_group_id, at_type, discovery_data_source_id
from .utils import reporter, remarks

from astropy.time import Time
import pandas as pd
import numpy as np

def generate_photometry(data: dict):
    """ Define structure of the dictionnary that contains first detection data

    Parameters
    ----------
    data: dict
        Fink/ZTF alert

    Returns
    ---------
    dd: dict
    """
    dd = {
        "obsdate": "{}".format(Time(data['jd'], format='jd').fits.replace("T", " ")),
        "flux": "{}".format(data['magpsf']),
        "flux_error": "{}".format(data['sigmapsf']),
        "limiting_flux": "{}".format(data['diffmaglim']),
        "flux_unitid": "{}".format(inst_units),
        "filterid": "{}".format(filters_dict[data['fid']]),
        "instrumentid": "{}".format(instrument),
        "exptime": "30",
        "observer": "Robot",
        "comments": "Data provided by ZTF, classified by Fink"
    }

    return dd

def generate_non_detection(data):
    """ Define structure of the dictionnary that contains last non-detection data

    Parameters
    ----------
    data: dict
        Fink/ZTF alert

    Returns
    ---------
    dd: dict
    """
    dd = {
        "obsdate": "{}".format(Time(data['jd'], format='jd').fits.replace("T", " ")),
        "limiting_flux": "{}".format(data['diffmaglim']),
        "flux_unitid": "{}".format(inst_units),
        "filterid": "{}".format(filters_dict[data['fid']]),
        "instrumentid": "{}".format(instrument),
        "exptime": "30",
        "observer": "Robot",
        "comments": "Data provided by ZTF, classified by Fink"
    }

    return dd

def extract_discovery_photometry(data: dict) -> (dict, dict):
    """ Extract the photometry at the moment of discovery

    Parameters
    ----------
    data: dict
        Fink/ZTF alert data as a dictionnary

    Returns
    ----------
    first_photometry: dict
        Information about the first detection
    last_non_detection: dict
        Information about the last non-detection
    """
    tmp_pho = []
    tmp_upp = []

    # add candidate into photometry
    tmp_pho.append(generate_photometry(data['candidate']))

    # loop over prv_candidates, and add into photometry or non-det
    for alert in data['prv_candidates']:
        if alert['magpsf'] is not None:
            tmp_pho.append(generate_photometry(alert))
        else:
            tmp_upp.append(generate_non_detection(alert))

    # Sort photometry and keep the first one
    tmp_pho = sorted(tmp_pho, key=lambda i: i['obsdate'])
    first_photometry = tmp_pho[0]

    # Extract the last non-detection
    date_init = first_photometry['obsdate']
    filt_init = first_photometry['filterid']
    tmp_upp = sorted(tmp_upp, key=lambda i: i['obsdate'])

    # Note we extract the last non-detection for the same filter!
    tmp_upp = [i for i in tmp_upp if (i['obsdate'] <= date_init) & (i['filterid'] == filt_init)]

    if len(tmp_upp) == 0:
        last_non_detection = {
            "archiveid": "0",
            "archival_remarks": "ZTF non-detection limits not available"
        }
    else:
        last_non_detection = tmp_upp[-1]

    return first_photometry, last_non_detection

def extract_discovery_photometry_api(data: pd.DataFrame) -> (dict, dict):
    """ Extract the photometry at the moment of discovery

    Parameters
    ----------
    data: pd.DataFrame
        Fink/ZTF alert data from the REST API as a pandas DataFrame

    Returns
    ----------
    first_photometry: dict
        Information about the first detection
    last_non_detection: dict
        Information about the last non-detection
    """
    required = {'d:tag', 'i:jd', 'i:fid', 'i:magpsf', 'i:sigmapsf', 'i:diffmaglim'}
    if data.empty or not required.issubset(data.columns):
        raise ValueError("Fink returned no usable light curve.")
    detections = data[data['d:tag'] == 'valid'].copy()
    if 'i:isdiffpos' in detections:
        detections = detections[detections['i:isdiffpos'].astype(str).str.lower().isin(['t', '1', 'true'])]
    if detections.empty:
        raise ValueError("No valid positive detection is available for this object.")
    numeric = ['i:jd', 'i:fid', 'i:magpsf', 'i:sigmapsf', 'i:diffmaglim']
    detections[numeric] = detections[numeric].apply(pd.to_numeric, errors='coerce')
    if (not np.isfinite(detections[numeric].to_numpy()).all()
            or not detections['i:fid'].isin(filters_dict).all()
            or (detections['i:sigmapsf'] < 0).any()):
        raise ValueError("Fink detection photometry is incomplete or invalid.")
    first = detections.sort_values('i:jd').iloc[0]
    first_photometry = generate_photometry({key[2:]: value for key, value in first.items() if key.startswith('i:')})

    limits = data[data['d:tag'] == 'upperlim'].copy()
    limit_columns = ['i:jd', 'i:fid', 'i:diffmaglim']
    limits[limit_columns] = limits[limit_columns].apply(pd.to_numeric, errors='coerce')
    limits = limits[np.isfinite(limits[limit_columns]).all(axis=1)]
    limits = limits[(limits['i:jd'] < first['i:jd']) & (limits['i:fid'] == first['i:fid'])]
    if limits.empty:
        # Do not invent a non-detection or treat bad-quality detections as limits.
        raise ValueError("No preceding upper limit in the discovery filter is available. A TNS report needs a non-detection or manually verified archival information.")
    last = limits.sort_values('i:jd').iloc[-1]
    last_non_detection = generate_non_detection({key[2:]: value for key, value in last.items() if key.startswith('i:')})
    return first_photometry, last_non_detection

def build_report(
        data: dict, photometry: dict, non_detection: dict,
        reporter_custom=None, remarks_custom=None, at_type_=None) -> dict:
    """ Build json report to send to TNS

    Parameters
    ----------
    data: dict
        Mean RA/Dec and scatter
    photometry: dict
        Information about the first detection
    non_detection: dict
        Information about the last non-detection
    remarks_custom: str, optional
        Comments that will be displayed on TNS. Default is None, that is
        `utils.remarks`.
    reporter_custom: str, optional
        Names of the reporters that will be displayed on TNS.
        Default is None, that is `utils.reporter`.

    Returns
    ----------
    report: dict
        Dictionnary at the TNS format.
    """
    if remarks_custom is None:
        remarks_custom = remarks
    if reporter_custom is None:
        reporter_custom = reporter
    if at_type_ is None:
        at_type_ = at_type

    radec = extract_radec(data)
    report = {
        "ra": {
            "value": radec['ra'],
            "error": radec['ra_err'] * 3600,
            "units": "arcsec"
        },
        "dec": {
            "value": radec['dec'],
            "error": radec['dec_err'] * 3600,
            "units": "arcsec"
        },
        "reporting_groupid": reporting_group_id,
        "data_source_groupid": discovery_data_source_id,
        "reporter": reporter_custom,
        "discovery_datetime": photometry['obsdate'],
        "at_type": at_type_,
        "internal_name": data['objectId'],
        "remarks": remarks_custom.format(data['objectId']),
        "non_detection": non_detection,
        "photometry": {'0': photometry}
    }

    return report

def build_report_api(
        data: pd.DataFrame, photometry: dict, non_detection: dict,
        reporter_custom=None, remarks_custom=None, at_type_=None) -> dict:
    """ Build json report to send to TNS

    Parameters
    ----------
    data: dict
        Data from the REST API /api/v1/objects
    photometry: dict
        Information about the first detection
    non_detection: dict
        Information about the last non-detection
    remarks_custom: str, optional
        Comments that will be displayed on TNS. Default is None, that is
        `utils.remarks`.
    reporter_custom: str, optional
        Names of the reporters that will be displayed on TNS.
        Default is None, that is `utils.reporter`.

    Returns
    ----------
    report: dict
        Dictionnary at the TNS format.
    """
    if remarks_custom is None:
        remarks_custom = remarks
    if reporter_custom is None:
        reporter_custom = reporter
    if at_type_ is None:
        at_type_ = at_type

    if not {'i:ra', 'i:dec', 'i:objectId', 'd:tag'}.issubset(data.columns):
        raise ValueError("Fink returned no object coordinates or identity.")
    positions = data.loc[data['d:tag'] == 'valid', ['i:ra', 'i:dec']].apply(pd.to_numeric, errors='coerce')
    positions = positions[np.isfinite(positions).all(axis=1)]
    if (positions.empty or not positions['i:ra'].between(0, 360, inclusive='left').all()
            or not positions['i:dec'].between(-90, 90).all()):
        raise ValueError("Fink returned no valid celestial coordinates.")
    # Average RA on a circle, so 359.999 and 0.001 degrees average to 0.
    radians = np.deg2rad(positions['i:ra'].to_numpy())
    ra = float(np.rad2deg(np.arctan2(np.sin(radians).mean(), np.cos(radians).mean())) % 360)
    if ra >= 360:  # tiny negative angles can round to 360 during modulo
        ra = 0.0
    dec = float(positions['i:dec'].mean())
    ra_offsets = (positions['i:ra'].to_numpy() - ra + 180) % 360 - 180
    object_id = str(data['i:objectId'].iloc[0])
    return {
        "ra": {"value": ra, "error": float(np.std(ra_offsets) * np.cos(np.deg2rad(dec)) * 3600), "units": "arcsec"},
        "dec": {"value": dec, "error": float(np.std(positions['i:dec']) * 3600), "units": "arcsec"},
        "reporting_groupid": reporting_group_id,
        "data_source_groupid": discovery_data_source_id,
        "reporter": reporter_custom,
        "discovery_datetime": photometry['obsdate'],
        "at_type": str(at_type_),
        "internal_name": object_id,
        "internal_ids": {"internal_name": object_id},
        "remarks": remarks_custom.replace('{}', object_id),
        "non_detection": non_detection,
        "photometry": {'0': photometry},
    }

def save_logs_and_return_json_report(name: str, folder: str, ids: list, report: dict):
    """ Save logs on disk (JSON), and return the path to the JSON file

    Parameters
    ----------
    name: str
        Filename
    folder: str
        Folder (or path) that will contain the log
    ids: list
        List of objectId that will be sent
    report: dict
        Payload to send to TNS

    Returns
    ---------
    json_report: str
        Path to the log
    """
    os.makedirs(folder, exist_ok=True)

    # Save processed ids on disk
    pdf_ids = pd.DataFrame.from_dict({'id': ids})
    pdf_ids.to_csv('{}/{}.csv'.format(folder, name), index=False)

    # Save report on disk
    json_report = '{}/{}.json'.format(folder, name)
    with open(json_report, 'w') as outfile:
        json.dump(report, outfile)
    return json_report

def format_to_json(source):
    """ change data to json format and return """
    parsed = json.loads(source, object_pairs_hook=OrderedDict)
    result = json.dumps(parsed, indent=4)
    return result

def send_json_report(api_key, url, json_file_path, tns_marker) -> int:
    """ Function for sending json reports (AT or Classification)

    Parameters
    ----------
    api_key: str
        API key for TNS
    url: str
        URL for posting results
    json_file_path: str
        Path to the generated report to be posted
    tns_marker: str
        New marker to be inserted in the header (user-agent).
        See https://www.wis-tns.org/content/tns-newsfeed#comment-wrapper-23710
    """
    # url for sending json reports
    json_url = url + '/set/bulk-report'

    # read json data from file
    with open(json_file_path) as report_file:
        json_read = format_to_json(report_file.read())

    # construct list of (key,value) pairs
    json_data = [
        ('api_key', (None, api_key)),
        ('data', (None, json_read))
    ]

    # define header
    headers = {'User-Agent': tns_marker}

    # send json report using request module
    response = requests.post(json_url, files=json_data, headers=headers, timeout=(5, 30), allow_redirects=False)

    return response
