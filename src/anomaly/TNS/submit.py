"""Build and submit a single ZTF discovery report using the Fink REST API."""

import re

import pandas as pd
import requests

from .client import TIMEOUT, TNSSettings, TNSUpstreamError, submit_report
from .report import build_report_api, extract_discovery_photometry_api


def tns_transfer(objectId, remarks, reporter, attype, outpath=None, *, settings=None):
    """Return a pending receipt; use report_reply to learn the final result.

    ``outpath`` is accepted for compatibility. Web requests keep reports in
    memory instead of writing object-named files shared by all users.
    """
    if not isinstance(objectId, str) or not re.fullmatch(r"ZTF\d{2}[a-z]{7}", objectId):
        raise ValueError("Provide a valid ZTF object ID, for example ZTF17aabvfza.")
    if not isinstance(reporter, str) or not reporter.strip() or len(reporter) > 1000:
        raise ValueError("Provide reporter names (at most 1000 characters).")
    if not isinstance(remarks, str) or not remarks.strip() or len(remarks) > 5000:
        raise ValueError("Provide remarks (at most 5000 characters).")
    if not str(attype).isdecimal() or not 1 <= int(attype) <= 5:
        raise ValueError("AT type must be a TNS type ID from 1 to 5.")
    settings = settings or TNSSettings.load()
    try:
        response = requests.post(
            "https://api.fink-portal.org/api/v1/objects",
            json={"objectId": objectId, "withupperlim": "True"},
            timeout=TIMEOUT,
            allow_redirects=False,
        )
        response.raise_for_status()
        records = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise TNSUpstreamError("Unable to retrieve the Fink light curve; nothing was submitted to TNS.") from exc
    if not isinstance(records, list):
        raise TNSUpstreamError("Fink returned an invalid light curve; nothing was submitted to TNS.")
    data = pd.DataFrame.from_records(records)
    if data.empty or 'i:objectId' not in data or not data['i:objectId'].eq(objectId).all():
        raise ValueError("Fink returned no matching light curve for this object.")
    photometry, non_detection = extract_discovery_photometry_api(data)
    report = build_report_api(
        data, photometry, non_detection,
        reporter_custom=reporter.strip(), remarks_custom=remarks.strip(), at_type_=str(attype),
    )
    return submit_report(settings, {"at_report": {"0": report}})
