# anomaly_base

FastAPI+MongoDB based web service for storing partitioned anomalous light curves.


# Manual

To run the anomaly base, the following steps should be performed:
1) Place the `secret_data.ini` file with this content in the project directory (on the same level as `docker-compose.yml`):
```
[NOTIF]
master_pass = <YOUR_TG_API_TOKEN>
```
and the `.env` file with the following content:
```
MONGO_INITDB_ROOT_USERNAME=<YOUR_MONGO_USERNAME>
MONGO_INITDB_ROOT_PASSWORD=<YOUR_MONGO_PASSWORD>
DATABASE_URL=mongodb://<MONGO_USERNAME>:<MONGO_USERNAME>@database:27017/
SECRET_KEY=<YOUR_SECRET_KEY>
TG_TOKEN=<YOUR_TG_API_TOKEN>
```
(I realize that duplicating TG_TOKEN -- this is strange, and will fix it in the future)

2) Create a certs folder (on the same level as the `docker-compose.yml` file), save the SSL certificates in it;
3) In the `docker-compose.yml` file, replace the paths `/home/vps/web_data`, `/home/vps/mongodata`, `/home/vps/mongobackups` and `/home/vps/anomaly_base/mongo_backup.sh` with your own.
4) Replace the domain name in this line with your own: [here](https://github.com/fink-anomaly/anomaly_base/blob/new_design/main.py#L152) and [here](https://github.com/fink-anomaly/anomaly_base/blob/new_design/main.py#L301).
5) Execute the commands in the project directory:
```bash
docker-compose build
docker-compose up
```

## TNS discovery reports

The Notifications card's **TNS Submit** button opens a discovery report form.
The server fetches the object's light curve from Fink and sends one AT report
using the [TNS 2.0 bulk API](https://www.wis-tns.org/sites/default/files/api/tns2_manuals/TNS2.0_bulk_reports_manual.pdf).
It does not send classification reports or spectra.

Configure these variables on the API server (the compose service reads `.env`):

```dotenv
TNS_KEY=<BOT_API_KEY>
TNS_BOT_ID=<NUMERIC_BOT_ID>
TNS_BOT_NAME=<EXACT_BOT_NAME>
TNS_ENVIRONMENT=sandbox
TNS_ALLOWED_USERS=alice,bob
```

The equivalent `secret_data.ini` section is `[TNS]`, with `key`, `bot_id`,
`bot_name`, `environment` and `allowed_users`. Environment variables take
precedence. Do not commit credentials. Only the named, authenticated accounts
can submit reports or inspect this shared bot's report receipts. An empty
allowlist grants access to nobody. Bot membership must permit reporting for
Fink group 103; the ZTF data source group is 48.

Sandbox is the default. Set `TNS_ENVIRONMENT=production` only after validating
with your bot on the sandbox. The form displays the destination and requires
confirmation; a change of server environment requires reloading the form.
No external reports are sent by the automated tests.

The report uses the earliest good-quality, positive detection and the latest
preceding upper limit in the same filter, sorted by observation time. Objects
without that upper limit are rejected with an explanation; this form does not
invent archival information. Reporter names, remarks and the numeric TNS AT
type ID are supplied by the user. Only finite, supported photometry and valid
coordinates are accepted. Arbitrary braces in remarks are preserved; `{}` is
replaced by the ZTF object ID for compatibility with older remark templates.

`POST /user/submitTNS` accepts form fields `object_id`, `reporter`, `remarks`,
`at_type` (TNS ID 1–5) and `environment` (`sandbox` or `production`), with the
usual bearer authentication. HTTP 202 returns a receipt:

```json
{"status": "pending", "report_id": 123, "environment": "sandbox"}
```

This only confirms receipt. `GET /user/tns/reports/123` fetches processing
feedback, returning `pending`, `submitted`, `rejected` or `review`. `submitted`
requires TNS feedback 103 and no blocking errors, even if the outer HTTP/JSON
code is 200. The UI polls every three seconds for up to ten attempts, then
allows checking the same report ID manually. The last receipt is retained in
this browser tab's session storage, separately by account and environment.
The configuration endpoint `GET /user/tns/config` exposes only the destination.

Timeouts and unreadable replies can occur after TNS accepted a report. There
is no automatic retry of submissions: check TNS before sending another copy.
The browser blocks repeated attempts for an object in the current page;
there is no durable server-side submission journal or idempotency guarantee.
Keep the receipt and its environment, especially before switching deployments.
Configuration errors return 503, unavailable upstream services return 502,
and invalid input/light curves return 422. No JSON/CSV report files accumulate
on the server.

**Deployment:** this compose file mounts a persistent directory over
`/app/static`. Copy the new `static/assets/js/tns.js` into that mounted directory
as part of deployment; rebuilding the image alone does not update files hidden
by the mount. Existing application settings and database setup are still
required.

## Tests

From the repository root, install `requirements-test.txt` into a virtual
environment. Node.js 18+ runs the frontend behavior tests without npm packages.

```bash
python -m pip install -r requirements-test.txt
python -m pytest -q
node --test --experimental-test-coverage tests/js/tns.test.cjs
python -m coverage run --branch --source=src/anomaly -m pytest -q
python -m coverage report --include='*/TNS/client.py,*/TNS/submit.py,*/TNS/report.py' --fail-under=100
```

The Python run also launches the Node tests when Node is available; otherwise
that launcher is reported as skipped. The root `tox.ini` uses the same test
dependencies. App tests use fake credentials, a separate in-memory Mongo mock
per test and temporary storage. They supply the missing `[SERVER]` settings,
resolve image fixtures relative to the test file and block external socket
connections. No real MongoDB, Telegram or TNS configuration is required.

`tests/test_known_regressions.py` covers malformed and missing reaction dates,
image upload failures, and retrying notification deletion after a file error.

The frontend tests execute the shipped `tns.js` with stubbed DOM, HTTP,
storage and timers. They cover submit/status states, lost responses, retry
restrictions, concurrency and polling limits. They complement the previous
real-browser smoke check; they do not exercise CSS layout or the real TNS.

## Access checks, safe descriptions and Telegram webhook

Reaction updates/deletions and notification deletions require both the stored
ID and the authenticated owner in the database mutation. Bulk reaction deletion
is limited to the authenticated account. The account named `admin` gets no
implicit override for modifying somebody else's data. The guarantees are tested
against Mongo mocks and in-memory SQLite. Missing and foreign single records
both return 404.

`PUT /reaction/{id}` now accepts only `{"tag": "ANOMALY"}` (or another tag).
It rejects ownership, identity and timestamp fields with 422. The server sets
`changed_at`, preserving the existing object/candidate identity and owner.

Stored descriptions are rendered as Markdown and sanitized with `nh3` before
being marked safe for HTML. Basic formatting and HTTP/HTTPS links are retained;
embedded images, scripts, event handlers, styles and arbitrary attributes are
removed. This applies on every render, including previously uploaded rows.
Template values used in JavaScript are JSON encoded, and dynamic URL path
components are encoded. Install the updated application requirements (or rebuild
the image) to include `nh3==0.3.2`.

Telegram's webhook credential is **separate from the bot API token**. Configure
this additional environment variable in the API service's `.env`:

```dotenv
TELEGRAM_WEBHOOK_SECRET=<RANDOM_URL_SAFE_SECRET>
```

Generate a random value locally, for example with
`python -c "import secrets; print(secrets.token_urlsafe(32))"`. Telegram accepts
1–256 letters, digits, underscores and hyphens. Keep the value private.

With `[SERVER] init_bot = true` and `domen` set to the public hostname in
`secret_data.ini`, the API registers its webhook in the background using this
value as `secret_token`. Each Telegram request has a 10-second timeout. If
registration fails, the API retries after 60 seconds. After registration, it
checks the registered URL with `getWebhookInfo` every 60 seconds.

The cabinet shows a banner while checking Telegram, after a failed check or
when registration needs administrator attention. Open or reload the page to see
the latest status. A successful check clears the banner. This status covers the
Bot API connection and webhook URL. The cabinet and `/version` remain available
during Telegram failures, provided the database initializes successfully.

With `init_bot = false`, register the webhook externally using the same
`secret_token`. In this mode the service skips automatic registration and
monitoring.

On every delivery, Telegram supplies `X-Telegram-Bot-Api-Secret-Token`. The API
compares it to the configured value using a constant-time comparison **before
reading the JSON body**. Missing or incorrect headers return 403; an unconfigured
endpoint returns 503. A reverse proxy must forward this header. Existing webhook
registrations must therefore be updated when deploying this change; setting the
environment variable alone does not change Telegram's registration. See the
[official setWebhook contract](https://core.telegram.org/bots/api#setwebhook).
