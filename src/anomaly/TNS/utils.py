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
import json
import requests
from collections import OrderedDict
import numpy as np
import pandas as pd
import glob
import io
import zipfile

# Fink groupid
reporting_group_id = "103"

# ZTF data source
discovery_data_source_id = "48"

# instrument
instrument = "196"

# units
inst_units = "1"

# at type
at_type = "1"

# filters: 110 (g-ZTF), 111 (r-ZTF), 112 (i-ZTF)
filters_dict = {1: "110", 2: "111", 3: "112"}

reporter = "Julien Peloton, Anais Moller, Emille E. O. Ishida on behalf of the Fink broker"

remarks = "Early SN Ia candidate classified by Fink using the public ZTF stream. Object data at https://fink-portal.org/{} "

def search_tns(api_key, tns_marker, oid):
    """ Get TNS data for a given object ID

    Parameters
    ----------
    api_key: str
        API key for TNS
    tns_marker: str
        New marker to be inserted in the header (user-agent).
        See https://www.wis-tns.org/content/tns-newsfeed#comment-wrapper-23710
    oid: str
        Internal Object ID (e.g. ZTFXXXXXX)
    """
    orddict = OrderedDict(
        [
            ("units", "deg"),
            ("objname", ""),
            ("internal_name", oid)
        ]

    )

    search_data = [
        ('api_key', (None, api_key)),
        ('data', (None, json.dumps(orddict)))
    ]

    # define header
    headers = {'User-Agent': tns_marker}

    response = requests.post(
        "https://www.wis-tns.org/api/get/search",
        files=search_data,
        headers=headers,
        timeout=(5, 10)
    )

    try:
        reply = response.json()["data"]["reply"]
    except KeyError as e:
        reply = []

    return reply

def retrieve_groupid(api_key, tns_marker, oid):
    """ Get TNS groupid for a given object ID

    Parameters
    ----------
    api_key: str
        API key for TNS
    tns_marker: str
        New marker to be inserted in the header (user-agent).
        See https://www.wis-tns.org/content/tns-newsfeed#comment-wrapper-23710
    oid: str
        Internal Object ID (e.g. ZTFXXXXXX)
    """
    reply = search_tns(api_key, tns_marker, oid)

    if reply != []:
        objname = reply[0]["objname"]
    else:
        return -999

    data = {
        "objname": objname,
    }

    # get object type
    json_data = [
        ('api_key', (None, api_key)),
        ('data', (None, json.dumps(data)))
    ]

    # define header
    headers = {'User-Agent': tns_marker}

    response = requests.post(
        "https://www.wis-tns.org/api/get/object",
        files=json_data,
        headers=headers
    )

    data = response.json()['data']

    return data['reply']['discovery_data_source']['groupid']

def extract_radec(data):
    """ Return mean RA/Dec and scatter for a ZTF object based on all alerts

    Parameters
    ----------
    data: dict
        Dictionnary containing all alerts for a given ZTF objects

    Returns
    ----------
    out: dict
        Mean RA/Dec and scatter
    """
    ra = []
    dec = []

    ra.append(data['candidate']['ra'])
    for alert in data['prv_candidates']:
        ra.append(alert['ra'])
    ra = np.array(ra)

    dec.append(data['candidate']['dec'])
    for alert in data['prv_candidates']:
        dec.append(alert['dec'])
    dec = np.array(dec)

    mask = (ra != None) & (dec != None)
    return {
        'ra': np.mean(ra[mask]),
        'ra_err': np.std(ra[mask]),
        'dec': np.mean(dec[mask]),
        'dec_err': np.std(dec[mask])
    }

def read_past_ids(folder):
    """ Read all ZTF objectId already reported by Fink to TNS

    This is to avoid reporting twice the same objects

    Parameters
    ----------
    folder: str
        Path to the folder containing CSV files containing all ZTF objectId sent
    """
    filenames = glob.glob('{}/*.csv'.format(folder))
    if len(filenames) == 0:
        # no files found
        return pd.DataFrame()

    pdf = pd.concat(
        [
            pd.read_csv(i) for i in glob.glob('{}/*.csv'.format(folder))
        ]
    )
    return pdf

def download_catalog(api_key, tns_marker):
    """ Download entire TNS data (compressed csv file) into Pandas DataFrame

    Parameters
    ----------
    api_key: str
        Path to API key
    tns_marker: str
        New marker to be inserted in the header (user-agent).
        See https://www.wis-tns.org/content/tns-newsfeed#comment-wrapper-23710

    Returns
    ----------
    pdf_tns: Pandas DataFrame
        Pandas DataFrame with all the data
    """
    with open(api_key) as f:
        # remove line break...
        key = f.read().replace('\n', '')

    json_data = [
        ('api_key', (None, key)),
    ]

    # define header
    headers = {'User-Agent': tns_marker}

    r = requests.post(
      'https://www.wis-tns.org/system/files/tns_public_objects/tns_public_objects.csv.zip',
      files=json_data,
      headers=headers
    )

    with zipfile.ZipFile(io.BytesIO(r.content)) as myzip:
        data = myzip.read(name='tns_public_objects.csv')

    pdf_tns = pd.read_csv(io.BytesIO(data), skiprows=[0])

    return pdf_tns

def extract_ztf_entries(x):
    """Filter a string containg substrings starting with ZTF"""
    if x is None:
        return ""
    else:
        tmp = x.split(",")
        mask = [i.startswith("ZTF") for i in tmp]
        if sum(mask) > 0:
            return np.array(tmp)[mask][0]
        else:
            return ""

def print_fink_statistics(tns_logs_folder=None, tns_catalog=None):
    """Print Fink performance on TNS 

    Parameters
    ----------
    tns_logs_folder: str
        TNS log folder if available (only for operations). 
        Otherwise, if None, API call is made.
    tns_catalog: str
        Path to the TNS catalog in parquet.
    """
    # This could be replace by API call for Early SN Ia
    if tns_logs_folder is not None:
        tns_id = read_past_ids(tns_logs_folder)
    else:
        # Get latests 5 Early SN Ia candidates
        r = requests.post(
          "https://fink-portal.org/api/v1/latests",
          json={
            "class": "Early SN Ia candidate",
            "columns": "i:objectId",
            "n": "100000"
          }
        )

        # Format output in a DataFrame
        tmp = pd.read_json(io.BytesIO(r.content))
        tns_id = tmp.drop_duplicates("i:objectId").rename(columns={"i:objectId": "id"})
    cat = pd.read_parquet(tns_catalog)

    cat["id"] = cat["internalname"].apply(extract_ztf_entries)

    merged = pd.merge(tns_id, cat, on='id')

    print("Number of candidates sent to TNS: {}".format(len(tns_id)))
    print("Number of classified candidates: {}".format(len(merged)))
    print("--------------")
    print(merged.groupby("type").count().sort_values("id", ascending=False)["id"])

