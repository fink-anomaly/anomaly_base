#!/usr/bin/env python
# Copyright 2022-2023 AstroLab Software
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
import requests
import pandas as pd
import io
import configparser

from .report import extract_discovery_photometry_api
from .report import build_report_api
from .report import save_logs_and_return_json_report
from .report import send_json_report
config = configparser.ConfigParser()
config.read("secret_data.ini")

class ArgCarrier:
    pass

def tns_transfer(
        objectId,
        remarks,
        reporter,
        attype,
        outpath
    ):
    """ Submit discovery to TNS
    """
    args = ArgCarrier()
    args.objectId = objectId
    args.remarks = remarks
    args.reporter = reporter
    args.attype = attype
    args.outpath = outpath

    if args.objectId is None:
        raise NotImplementedError("You need to provide a ZTF objectId")
    if args.remarks is None:
        raise NotImplementedError("You need to provide the option remarks")
    if args.reporter is None:
        raise NotImplementedError("You need to provide a reporter")
    tns_marker = ''
    key = config['TNS']['key']
    url_tns_api = "https://sandbox.wis-tns.org/api"
    objects = [args.objectId]
    ids = []
    report = {"at_report": {}}
    for index, obj in enumerate(objects):
        r = requests.post(
            'https://api.fink-portal.org/api/v1/objects',
            json={
            'objectId': obj,
            'withupperlim': 'True'
            }
        )

        # Format output in a DataFrame
        pdf = pd.read_json(io.BytesIO(r.content))

        photometry, non_detection = extract_discovery_photometry_api(pdf)
        report['at_report']["{}".format(index)] = build_report_api(
            pdf,
            photometry,
            non_detection,
            remarks_custom=args.remarks,
            at_type_=args.attype,
            reporter_custom=args.reporter
        )
        ids.append(pdf['i:objectId'].values[0])

    json_report = save_logs_and_return_json_report(
        name=args.objectId,
        folder=args.outpath,
        ids=ids,
        report=report
    )
    print(report)

    r = send_json_report(key, url_tns_api, json_report, tns_marker)
    return r.json()

if __name__ == "__main__":
    tns_transfer(
        'ZTF17aabvfza',
        'Data provided by ZTF and processed by Fink',
        'test',
        'test_type',
        './TNS_last.json'
    )
