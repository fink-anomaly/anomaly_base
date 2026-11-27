# Review of anomaly_base / new_design

Reviewed on 2026-11-11. Base commit: `bed38b92cf402b934501ec09ba1a1dc40f09d4da`.
There were no open pull requests; the requested scope was clarified to be the
`new_design` branch. TNS implementation changes are in `codex/complete-tns`.

## Existing issues outside the TNS change

### P1 — Authenticated users can modify/delete other users' data (fixed locally)

Locations: `src/anomaly/routes/reactions.py:68`, `:81`, `:97`;
`src/anomaly/routes/upload.py:56`; `src/anomaly/database/mongo.py:29` and `:46`.

The routes authenticate a caller but do not compare the stored row's owner
with that caller. Mongo updates/deletes select only by object ID; the bulk
reaction deletion accepts an arbitrary username. A registered account can
therefore change another user's training labels, remove those labels or
remove notification rows. Public `/reaction/` also exposes reaction IDs and
owners, making the reaction IDs readily discoverable.

Confirmed locally using the real routes, JWT authentication and in-memory
Mongo mocks: a token for `attacker` changed `victim`'s label to `NOT ANOMALY`
(HTTP 200), deleted that reaction (HTTP 200), and deleted a victim-owned image
row (HTTP 200). No production data was accessed. The arbitrary-username bulk
delete was identified by source inspection, not exercised.

Remedy: scope every mutation to both ID and authenticated owner; derive bulk
deletion's username from authentication. Do not allow updates to change
`user` or the database ID. Any admin override should be explicit.

### P1 — Telegram webhook accepts unsigned, attacker-supplied callbacks (fixed locally)

Locations: `src/anomaly/main.py:88`, `:110`, `:120`, `:145`.

The public webhook trusts `callback_query.from.id` from the request body and
passes it to a handler that resolves the user and saves/changes a reaction.
The route does not verify a Telegram webhook secret or another source
credential. An HTTP caller who knows a linked Telegram ID can impersonate
that user's reaction callbacks. The registration of the webhook at
`main.py:57` also supplies no secret token.

Confirmed at the route boundary: an HTTP POST without any authentication
header returned 200 and reached the callback handler with the forged input.
The actual handler was mocked to prevent Telegram calls. The resulting
reaction-write path is established by source inspection.

Remedy: configure `secret_token` when registering the webhook and validate
`X-Telegram-Bot-Api-Secret-Token` before parsing/processing updates; validate
the callback's format as well.

### P1 — Uploaded descriptions can contain executable HTML (fixed locally)

Locations: `src/anomaly/routes/upload.py:15`, `src/anomaly/main.py:392`,
`src/anomaly/templates/index.html:425`; admin selection in
`src/anomaly/database/mongo.py:63`.

The upload route stores unrestricted `description`. Markdown preserves raw
HTML, and the template renders it with `|safe`. A description such as an
image element with an `onerror` handler can execute in the viewing user's
session. In the Mongo backend, the `admin` account views all users' images,
so this can cross account boundaries and expose the page's bearer token.

Confirmed that the installed Markdown renderer retains the event-handler
HTML; the unsanitized template sink and admin-wide selection were verified
in source. No malicious payload was opened in a real user session.

Remedy: sanitize rendered HTML using an allowlist of elements, attributes
and URL schemes before marking it safe; sanitize values inserted in inline
handlers or replace inline JavaScript with event listeners.

### P2 — One differently formatted reaction timestamp hides notifications

Locations: `src/anomaly/main.py:186`, `:369`, `:409`.

`get_reactions_table` requires fractional seconds on every `changed_at`.
A valid whole-second timestamp, or a null value allowed by the model,
raises before images are fetched. The surrounding broad exception handler
returns the ordinary page with empty notifications, so a data-format problem
looks like an empty inbox.

Confirmed by executing the unchanged function with a fake row whose timestamp
was `2026-11-11 00:00:00`: it raised `ValueError`. No live account was inspected.

Remedy: accept the supported timestamp formats (prefer a database datetime),
handle missing/bad values per row, and fetch notifications independently of
reaction-table formatting.

### P2 — Upload storage failures return HTTP success

Location: `src/anomaly/routes/upload.py:25`.

After saving the row, either file write can fail (for example a full or
read-only volume). The catch block returns an error dictionary with HTTP 200,
leaving a row whose files may be missing. Clients checking only status will
consider delivery successful. This finding is based on source inspection.

Remedy: return a failing HTTP status and clean up partial files and the row
when storage fails; make the operation recoverable across interruptions.

### P2 — Removing notifications does not remove their image files

Locations: `src/anomaly/routes/upload.py:29`, `:56`;
`src/anomaly/database/mongo.py:46`; `src/anomaly/database/sqlalchemy.py:63`.

Each upload writes two PNGs. Deleting the image row deletes only the database
record. The frontend's removal actions therefore leave orphaned files on the
persistent static volume. The seven-day display filter also only hides old
cards. Repeated uploads/removals can keep consuming disk space. This is a
source finding; production disk usage was not measured.

Remedy: delete both files as part of notification removal, with recoverable
error handling, and add a bounded retention/orphan-cleanup procedure.

## TNS issues addressed in this branch

- Enabled the form and fixed checkbox rendering under the existing global CSS.
- Replaced the empty bot marker with configured TNS bot identity.
- Fixed malformed form fields and updated the payload to TNS 2.0 names and
  direct photometry entries; preserved user-selected AT type and remarks.
- Sorted observations explicitly; selected good positive discovery photometry
  and a preceding same-filter upper limit; rejected incomplete/nonfinite data.
- Handled RA wraparound when averaging positions.
- Added HTTP/JSON error checks, request timeouts and distinct receipt/feedback
  stages. Only feedback 103 with no blocking errors confirms submission.
- Used synchronous FastAPI handlers so blocking requests run in the thread pool.
- Restricted the shared bot to configured users and made sandbox the default.
  Submission checks that the displayed environment still matches the server.
- Removed shared per-object JSON/CSV output and the duplicate implementation.
- Fixed the browser's doubled `Bearer` prefix, which also affected existing
  authenticated browser actions.
- Added bounded UI polling, manual receipt lookup, tab-local receipt retention
  and protection against repeated button submission in the current page.

No production deployment or real TNS submission was performed. Bot credentials,
group permissions and a real sandbox round trip still need deployment-specific
validation. There is no durable server-side journal/idempotency guarantee:
ambiguous submission failures must be checked in TNS before a manual retry.
Authorized reporters can inspect receipts belonging to the shared bot.

## Validation

- `python -m pytest tests/test_tns.py tests/test_tns_routes.py -q`:
  **43 passed**. HTTP is mocked; no database is initialized by these tests.
- `node --check src/anomaly/static/assets/js/tns.js` and `git diff --check` passed.
- Real-browser check with the actual Jinja template/static assets and a local
  HTTP simulator: card → prefilled form → receipt → final confirmation; a
  repeated submit did not make another POST. The simulator confirmed a single
  `Bearer` prefix and preservation of selected AT type `4`. Manual receipt
  checking and receipt restoration after page reload also passed. This was a
  simulated upstream, not a real TNS bot.
- Full legacy suite, from `src/anomaly` with dummy settings and SQLite:
  **43 passed, 5 setup errors**. All five existing smoke tests stop in
  `init_db` with `KeyError: 'SERVER'`. The supplied README omits this required
  configuration section. The PNG fixtures are present (the earlier statement that they were absent
  was incorrect). The original upload test omits the required `candid_id`,
  uses working-directory-dependent paths, and its image-deletion test calls
  the reaction endpoint instead of `/images/`.
- Local review reproductions are preserved in `review/reproduce_findings.py`.
  Run from the repository root with application dependencies and the extra
  `mongomock-motor==0.0.34` test dependency:

  ```bash
  PYTHONPATH=src/anomaly python review/reproduce_findings.py
  ```

The temporary test environment used Python 3.13, FastAPI 0.115.6, Pydantic
2.10.4, Beanie 1.23.6, Motor 3.3.2 and PyMongo 4.6.0. The existing host's NumPy
2.4.2 could not import Astropy 6.1.7; tests used NumPy 2.2.6 in an isolated
virtual environment. The production image declares Python 3.10, so this does
not establish a production NumPy failure.

## Follow-up test coverage (2026-11-11)

The suite now runs from the repository root without service configuration.
The smoke tests use per-test Mongo mocks and temporary file storage, supply
`[SERVER]` configuration, use the existing image fixtures and authenticate
through the real signup/signin routes. Their global state and order dependency
were removed. Test dependencies are in `requirements-test.txt`; root tox now
points to that file instead of a nonexistent root `requirements.txt`.

- Full pytest run: **112 passed, 10 xfailed**, with no setup errors or skips
  in this environment. One passing pytest test launches the frontend suite.
- Frontend suite: **22 passing Node tests**, exercising the actual `tns.js`
  with simulated DOM/HTTP/storage/timers. Node reports **100% line, branch
  and function coverage** for that file.
- Python branch coverage: **100% for each of `TNS/client.py`, `TNS/submit.py`
  and `TNS/report.py`** (225 statements, 76 branches). This is scoped to these
  modules; it is not a claim of 100% coverage for the entire application.
- Route tests include a complete form POST → Fink data retrieval → TNS receipt
  → pending lookup → submitted feedback, with only external HTTP stubbed.
- Additional cases cover malformed/non-JSON upstream responses, Fink failures,
  invalid identities/receipts, empty permissions, invalid/expired JWTs,
  required form fields, coordinate rounding and legacy report helpers.
- The 10 expected failures assert the desired behavior for ownership checks,
  webhook authentication, HTML sanitization, malformed reaction dates,
  upload failures and file cleanup. All were rerun with `--runxfail`: they
  fail on the intended assertions, not on setup or missing dependencies.
  These product defects remain unresolved. Markers are strict, so an
  unexpected fix cannot silently retain an obsolete expected-failure marker.
- Running route tests before the application smoke tests also passes.
- External socket connections are blocked by an autouse fixture.

Commands and the distinction between isolated frontend tests and the earlier
browser smoke check are documented in README. No production behavior was
changed during this follow-up; changes are limited to tests, test setup,
tox/dependency configuration and documentation.

## Security remediation (2026-11-11)

The three P1 findings above describe the original base commit. They are now
fixed in this local branch:

- Both database adapters implement ownership-scoped atomic mutations. Routes
  use those operations for reaction and image deletion and reaction updates;
  bulk deletion rejects another username. There is no username-based admin
  mutation override. Reaction updates accept only `tag` and set time on the
  server, leaving all identity/owner fields immutable through this endpoint.
- `/telegram-webhook` verifies the configured Telegram secret header before
  JSON parsing. Missing/incorrect credentials return 403, and missing/invalid
  configuration closes the endpoint with 503. Background registration uses the
  same `secret_token` and a bounded timeout. The cabinet shows Telegram status
  while registration retries independently of web startup. Deployment requires setting `TELEGRAM_WEBHOOK_SECRET` and
  re-registering the existing webhook; no live registration was performed here.
- Descriptions go through a Markdown → `nh3` allowlist sanitizer → safe Markup
  pipeline. The template no longer marks arbitrary description strings safe.
  Existing stored descriptions are cleaned on rendering. JavaScript arguments,
  username interpolation and dynamic path components are encoded in their
  appropriate contexts; safe links and formatting are regression-tested.

Six security regressions had their `xfail` markers removed. Tests also cover
owner success cases, field tampering, both adapters, secret configuration and
registration failures, malicious markup and executable template interpolation.
The four remaining expected failures concern the three P2 findings above;
they are outside this remediation. The historical one-off reproduction script
now runs the maintained security/regression tests instead of stale probes.

The final run and scoped coverage are recorded in `review/test-results.json`.
There has been no deployment, production data modification or real Telegram/TNS
API call as part of these fixes.
