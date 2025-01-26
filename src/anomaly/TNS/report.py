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
        "flux_units": "{}".format(inst_units),
        "filter_value": "{}".format(filters_dict[data['fid']]),
        "instrument_value": "{}".format(instrument),
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
        "flux_units": "{}".format(inst_units),
        "filter_value": "{}".format(filters_dict[data['fid']]),
        "instrument_value": "{}".format(instrument),
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
    filt_init = first_photometry['filter_value']
    tmp_upp = sorted(tmp_upp, key=lambda i: i['obsdate'])

    # Note we extract the last non-detection for the same filter!
    tmp_upp = [i for i in tmp_upp if (i['obsdate'] <= date_init) & (i['filter_value'] == filt_init)]

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
    mask_valid = (data['d:tag'].values == 'valid') | (data['d:tag'].values == 'badquality')

    # first valid
    first = data[mask_valid].tail(1)

    mask_time = data[~mask_valid]['i:jd'] < first['i:jd'].values[0]

    # last non-detection
    last = data[~mask_valid][mask_time].head(1)

    first_photometry = {
        "obsdate": "{}".format(Time(first['i:jd'].values[0], format='jd').fits.replace("T", " ")),
        "flux": "{}".format(first['i:magpsf'].values[0]),
        "flux_error": "{}".format(first['i:sigmapsf'].values[0]),
        "limiting_flux": "{}".format(first['i:diffmaglim'].values[0]),
        "flux_units": "{}".format(inst_units),
        "filter_value": "{}".format(filters_dict[first['i:fid'].values[0]]),
        "instrument_value": "{}".format(instrument),
        "exptime": "30",
        "observer": "Robot",
        "comments": "Data provided by ZTF, classified by Fink"
    }

    if not last.empty:
        last_non_detection = {
            "obsdate": "{}".format(Time(last['i:jd'].values[0], format='jd').fits.replace("T", " ")),
            "limiting_flux": "{}".format(last['i:diffmaglim'].values[0]),
            "flux_units": "{}".format(inst_units),
            "filter_value": "{}".format(filters_dict[last['i:fid'].values[0]]),
            "instrument_value": "{}".format(instrument),
            "exptime": "30",
            "observer": "Robot",
            "comments": "Data provided by ZTF, classified by Fink"
        }
    else:
        last_non_detection = {}

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
        "reporting_group_id": reporting_group_id,
        "discovery_data_source_id": discovery_data_source_id,
        "reporter": reporter_custom,
        "discovery_datetime": photometry['obsdate'],
        "at_type": at_type_,
        "internal_name": data['objectId'],
        "remarks": remarks_custom.format(data['objectId']),
        "non_detection": non_detection,
        "photometry": {"photometry_group": {'0': photometry}}
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

    mask = ~np.isnan(data['i:ra'].values) & ~np.isnan(data['i:dec'].values)
    radec = {
        'ra': np.mean(data['i:ra'].values[mask]),
        'ra_err': np.std(data['i:ra'].values[mask]),
        'dec': np.mean(data['i:dec'].values[mask]),
        'dec_err': np.std(data['i:dec'].values[mask])
    }

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
        "reporting_group_id": reporting_group_id,
        "discovery_data_source_id": discovery_data_source_id,
        "reporter": reporter_custom,
        "discovery_datetime": photometry['obsdate'],
        "at_type": at_type,
        "internal_name": data['i:objectId'].values[0],
        "remarks": remarks_custom.format(data['i:objectId'].values[0]),
        "non_detection": non_detection,
        "photometry": {"photometry_group": {'0': photometry}}
    }

    return report

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
    json_read = format_to_json(open(json_file_path).read())

    # construct list of (key,value) pairs
    json_data = [
        ('api_key', (None, api_key)),
        ('data', (None, json_read))
    ]

    # define header
    headers = {'User-Agent': tns_marker}

    # send json report using request module
    response = requests.post(json_url, data=json_data, headers=headers)

    return response
