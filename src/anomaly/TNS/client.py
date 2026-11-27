"""TNS 2.0 transport. A receipt is not a successfully processed report."""

import configparser
from dataclasses import dataclass, field
import json
import os

import requests

TIMEOUT = (5, 30)
API_URLS = {
    "sandbox": "https://sandbox.wis-tns.org/api",
    "production": "https://www.wis-tns.org/api",
}


class TNSConfigurationError(Exception):
    pass


class TNSUpstreamError(Exception):
    pass


@dataclass(frozen=True)
class TNSSettings:
    key: str = field(repr=False)
    marker: str
    environment: str = "sandbox"
    allowed_users: tuple = ()

    @property
    def url(self):
        return API_URLS[self.environment]

    @classmethod
    def load(cls):
        config = configparser.ConfigParser(interpolation=None)
        config.read("secret_data.ini")

        def option(name, default=""):
            return os.getenv("TNS_" + name.upper(), config.get("TNS", name, fallback=default)).strip()

        key, bot_id, bot_name = option("key"), option("bot_id"), option("bot_name")
        environment = option("environment", "sandbox")
        if not key or not bot_id.isdecimal() or int(bot_id) <= 0 or not bot_name:
            raise TNSConfigurationError("Configure TNS_KEY, TNS_BOT_ID and TNS_BOT_NAME on the server.")
        if environment not in API_URLS:
            raise TNSConfigurationError("TNS_ENVIRONMENT must be sandbox or production.")
        marker = "tns_marker" + json.dumps({"tns_id": int(bot_id), "type": "bot", "name": bot_name})
        allowed_users = tuple(name.strip() for name in option("allowed_users").split(",") if name.strip())
        return cls(key, marker, environment, allowed_users)


def post(settings, endpoint, fields):
    """Send once. Never retry a submission with an unknown outcome."""
    try:
        response = requests.post(
            settings.url + endpoint,
            data={"api_key": settings.key, **fields},
            headers={"User-Agent": settings.marker},
            timeout=TIMEOUT,
            allow_redirects=False,
        )
    except requests.RequestException as exc:
        raise TNSUpstreamError(
            "TNS connection failed; the submission outcome may be unknown. Check TNS before resubmitting."
        ) from exc
    try:
        payload = response.json()
    except ValueError as exc:
        raise TNSUpstreamError("TNS returned an unreadable response; check TNS before resubmitting.") from exc
    if not isinstance(payload, dict):
        raise TNSUpstreamError("TNS returned an invalid response.")
    # Pending receipts can return HTTP/JSON 404. Keep authentication and other
    # errors distinct, including errors carried inside an HTTP 200 response.
    pending = endpoint == "/get/bulk-report-reply" and str(payload.get("id_code")) == "404"
    if pending and response.status_code in (200, 404):
        return payload
    if response.status_code != 200 or str(payload.get("id_code")) != "200":
        raise TNSUpstreamError(
            f"TNS rejected the request (HTTP {response.status_code}, code {payload.get('id_code')})."
        )
    return payload


def submit_report(settings, report):
    payload = post(settings, "/set/bulk-report", {"data": json.dumps(report, allow_nan=False)})
    data = payload.get("data")
    report_id = data.get("report_id") if isinstance(data, dict) else None
    if isinstance(report_id, bool) or not str(report_id).isdecimal() or int(report_id) <= 0:
        raise TNSUpstreamError("TNS returned no valid receipt; check TNS before resubmitting.")
    return {"status": "pending", "report_id": int(report_id), "environment": settings.environment}


def report_reply(settings, report_id):
    payload = post(settings, "/get/bulk-report-reply", {"report_id": str(report_id)})
    result = {"report_id": report_id, "environment": settings.environment}
    if str(payload.get("id_code")) == "404":
        return {**result, "status": "pending"}
    data = payload.get("data")
    feedback = data.get("feedback") if isinstance(data, dict) else None
    if not isinstance(feedback, (dict, list)) or not feedback:
        raise TNSUpstreamError("TNS returned no processing feedback. Check again using the same report ID.")

    codes = []

    def collect(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "internal_ids":
                    continue
                if str(key).isdecimal() and isinstance(value, dict) and "message" in value:
                    codes.append(int(key))
                if key == "message_id" and str(value).isdecimal():
                    codes.append(int(value))
                collect(value)
        elif isinstance(node, list):
            for value in node:
                collect(value)

    collect(feedback)
    # 0..99 are blocking errors; 100/101 concern the object, and only 103
    # confirms that the AT report itself was submitted.
    state = "rejected" if any(code < 100 for code in codes) else "submitted" if 103 in codes else "review"
    return {**result, "status": state, "feedback": feedback}
