# limesurvey-rc2-api

English | [Español](README.es.md)

FastAPI service for authenticating services against LimeSurvey RemoteControl 2, listing surveys, producing `SurveyStructure` and exporting responses. It does not generate dictionaries; `limesurvey-dictionary-api` uses its output for that purpose.

## 1. Configure and run

The recommended deployment uses `limesurvey-dictionary-api`'s `compose.yaml`. **The dictionary API's current development revision depends on unpublished local npm archives.** Its package prerequisites must be resolved before promising a clean standalone deployment; see that repository's README. FastAPI itself carries the generated contract artifacts and local validator.

```bash
mkdir limesurvey-dictionary-service
cd limesurvey-dictionary-service

git clone https://github.com/JJKid/limesurvey-rc2-api.git
git clone https://github.com/JJKid/limesurvey-dictionary-api.git

cd limesurvey-dictionary-api
cp .env.example .env
```

Configure `.env` following the dictionary API README, then run:

```bash
docker compose up --build -d
docker compose ps
curl http://127.0.0.1:8000/health
```

Expected result:

```json
{"detail":"ok"}
```

| Resource | Address |
| --- | --- |
| FastAPI | `http://127.0.0.1:8000` |
| Swagger | `http://127.0.0.1:8000/docs` |
| OpenAPI | `http://127.0.0.1:8000/openapi.json` |
| Public dictionary API | `http://127.0.0.1:8100` |

The other repository's `.env` configures this container automatically with `DICTIONARY_SERVICE_JWT_SECRET`, Redis and the allowed LimeSurvey hosts. You do not need another `.env` here for that deployment.

For local LimeSurvey:

```dotenv
ALLOWED_LIMESURVEY_HOSTS=host.docker.internal,localhost,127.0.0.1
ALLOW_INSECURE_LIMESURVEY_HTTP=true
```

For remote LimeSurvey, use its domain and HTTPS.

## 2. Authentication

Application routes, except `/health` and `/smoke`, require:

```http
Authorization: Bearer <JWT_INTERNO>
```

An authorized service, such as `limesurvey-dictionary-api`, creates the JWT. A regular Postman consumer does not need to create it when calling port `8100`.

After login, this service returns a local UUID:

```json
{
  "session_key": "5edc24c7-9ee7-48c1-8529-b6d8dd535810"
}
```

Subsequent requests send it as:

```http
X-LimeSurvey-Session: 5edc24c7-9ee7-48c1-8529-b6d8dd535810
```

The UUID temporarily identifies the LimeSurvey session in Redis. Only the JWT identity that opened the session can use it.

## 3. Test the endpoints

### Through the public API

To test dictionary generation, import the collection supplied by `limesurvey-dictionary-api`:

```text
postman/limesurvey-dictionary-api.local.postman_collection.json
```

The collection calls port `8100`. The public API creates the internal JWT and calls this adapter automatically.

### Direct FastAPI check

`verify_limesurvey_connection.py` uses real data: login, listing, survey loading and logout. Run from the `limesurvey-dictionary-api` directory where Compose is running:

```bash
docker compose exec -T limesurvey-rc2-api python verify_limesurvey_connection.py \
  --api http://127.0.0.1:8000 \
  --url http://host.docker.internal/limesurvey/index.php/admin/remotecontrol \
  --user '<usuario-limesurvey>' \
  --password '<contraseña-limesurvey>' \
  --sid 783587 \
  --language es \
  --jwt-secret '<DICTIONARY_SERVICE_JWT_SECRET>' \
  --jwt-issuer limesurvey-dictionary-api
```

Replace placeholders with configured values. Swagger at `http://127.0.0.1:8000/docs` can run individual requests but requires a valid internal JWT.

## 4. Direct service integration

```text
Consumer service
  → creates a short-lived internal JWT
  → opens a session with the LimeSurvey URL, username and password
  → receives a local UUID
  → uses JWT + UUID to query surveys or responses
  → closes the session
```

### Open a session

```http
POST /login-limesurvey
Authorization: Bearer <JWT_INTERNO>
Content-Type: application/json
```

```json
{
  "url": "https://encuestas.example.org/index.php/admin/remotecontrol",
  "username": "usuario",
  "password": "contraseña"
}
```

The response contains `session_key`. The password is not persisted.

### List surveys

```http
GET /surveys
Authorization: Bearer <JWT_INTERNO>
X-LimeSurvey-Session: <UUID_LOCAL>
```

Add `?refresh=true` to bypass the cache.

### Get the normalized structure

```http
GET /survey_structure/783587?language=es
Authorization: Bearer <JWT_INTERNO>
X-LimeSurvey-Session: <UUID_LOCAL>
```

Response:

```json
{
  "survey": {
    "contractVersion": "2.0.0",
    "id": "783587",
    "fields": []
  },
  "issues": []
}
```

The complete response is `SurveyLoadResult`. `survey` contains `SurveyStructure` and `issues` contains import diagnostics.

### Export responses

```http
GET /survey_responses/783587?language=es&completionStatus=all&headingType=code
Authorization: Bearer <JWT_INTERNO>
X-LimeSurvey-Session: <UUID_LOCAL>
Accept: application/json
```

Use `Accept: text/csv` for CSV. This operation is read-only and does not cache responses.

Citric receives the complete export before its size is checked; this is not an incremental download from LimeSurvey. For large volumes, constrain the interval with `fromResponseId` and `toResponseId`. Time and size limits reject excessive exports but do not guarantee constant memory use.

### Close the session

```http
GET /logout-limesurvey
Authorization: Bearer <JWT_INTERNO>
X-LimeSurvey-Session: <UUID_LOCAL>
```

## 5. Import a `.lss` file

No LimeSurvey session is required, but an internal JWT is:

```http
POST /survey_structures/from-lss?language=es
Authorization: Bearer <JWT_INTERNO>
Content-Type: multipart/form-data

file: <archivo.lss>
```

The route returns `SurveyLoadResult`, limits the file to 20 MiB, rejects unsafe XML and validates the normalized structure.

## 6. Main routes

| Method and route | Authorization | Result |
| --- | --- | --- |
| `GET /health` | None | Service health. |
| `POST /login-limesurvey` | JWT | Opens a session and returns a local UUID. |
| `GET /surveys` | JWT + UUID | Visible surveys. |
| `GET /survey_structure/{sid}` | JWT + UUID | Remote `SurveyLoadResult`. |
| `POST /survey_structures/from-lss` | JWT | File-based `SurveyLoadResult`. |
| `GET /survey_responses/{sid}` | JWT + UUID | JSON or CSV responses. |
| `GET /logout-limesurvey` | JWT + UUID | Closes the session. |

## 7. HTTP error codes

| Status | Code or detail | Meaning |
| --- | --- | --- |
| `400` | `LIMESURVEY_URL_NOT_ALLOWED` | URL or host is not allowed. |
| `400` | `INVALID_RESPONSE_RANGE` | Invalid response range. |
| `400` | `TOO_MANY_RESPONSE_FIELDS` | Too many requested columns. |
| `401` | `Internal service token is missing` | JWT was not sent. |
| `401` | `Internal service token is invalid or expired` | Invalid or expired JWT. |
| `401` | `LS_SESSION_EXPIRED` | Remote session expired; log in again. |
| `401` | `LimeSurvey session was not found or has expired` | Local UUID is missing or expired. |
| `403` | `LimeSurvey session belongs to another authenticated identity` | Another identity tried to use the UUID. |
| `413` | `LS_RESPONSE_EXPORT_TOO_LARGE` | Export exceeds its limit. |
| `502` | `LS_REMOTE_CONTROL_UNAVAILABLE` | RemoteControl 2 unavailable. |
| `502` | `LS_REMOTE_REJECTED_REQUEST` | LimeSurvey rejected the operation. |
| `502` | `INVALID_LS_RESPONSE_EXPORT` | Unexpected export format. |
| `503` | `LS_UNREACHABLE` | Cannot connect to LimeSurvey. |
| `504` | `LS_SURVEY_LOAD_TIMEOUT` | Survey loading exceeded its time limit. |
| `504` | `LS_RESPONSE_EXPORT_TIMEOUT` | Export exceeded its time limit. |
| `500` | `LS_UNKNOWN` | Unclassified error. |
| `500` | `INVALID_SURVEY_STRUCTURE` | Normalization produced an invalid survey or load result. `detail.errors` preserves each failure's path and rule. |

FastAPI puts errors in `detail`. Structured errors carry their code in `detail.code`.

## 8. Automated tests

Without a LimeSurvey instance:

Install Node 18 or later as well (Docker includes Node 22). Normalizer output is checked using `schemas/validate-survey.cjs`, generated from the same `survey-structure` Zod definition, including cross-question rules. JSON Schema files describe the contract but do not replace full validation. The local process is limited to five seconds and 16 MiB per document; if it cannot run, the request fails instead of returning unchecked data.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q -m "not integration"
```

Synthetic tests are included. Additional comparisons using local `tests/fixtures/` exports are explicitly skipped when that directory is absent; its data is not published in this repository.

Real integration test:

```bash
LS_INTEGRATION_URL='https://encuestas.example.org/index.php/admin/remotecontrol' \
LS_INTEGRATION_USERNAME='<usuario>' \
LS_INTEGRATION_PASSWORD='<contraseña>' \
LS_INTEGRATION_SID='783587' \
pytest -q -m integration
```

Do not commit those credentials.

## 9. Operational limits and XML

Defaults allow five seconds to establish a LimeSurvey connection and thirty seconds to read each response. Loading a complete survey is limited to 120 seconds. Configure:

```dotenv
LS_REMOTE_CONNECT_TIMEOUT_SECONDS=5
LS_REMOTE_READ_TIMEOUT_SECONDS=30
LS_SURVEY_LOAD_TIMEOUT_SECONDS=120
```

Automatic concurrency tuning is optional and disabled by default. When enabled, it runs in the background over a bounded sample and retains the result for 72 hours:

```dotenv
LS_OPTIMIZER_ENABLED=false
LS_OPTIMIZER_TTL_SECONDS=259200
LS_OPTIMIZER_MIN_SUCCESS_RATE=0.95
LS_OPTIMIZER_MAX_SURVEYS=3
LS_OPTIMIZER_MAX_GROUPS=10
LS_OPTIMIZER_MAX_SAMPLE_QUESTIONS=10
```

`.lss` files are limited to 20 MiB. The importer rejects `DOCTYPE` and `ENTITY` declarations, uses a parser protected against entity expansion and converts HTML labels and help text to plain text.
