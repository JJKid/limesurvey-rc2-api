# limesurvey-rc2-api

FastAPI para autenticar servicios contra LimeSurvey RemoteControl 2, listar
encuestas, producir `SurveyStructure` y exportar respuestas. No genera
diccionarios; `limesurvey-dictionary-api` utiliza su salida para hacerlo.

## 1. Configurar y levantar

La forma recomendada usa el `compose.yaml` de `limesurvey-dictionary-api`:

```bash
mkdir limesurvey-dictionary-service
cd limesurvey-dictionary-service

git clone https://github.com/JJKid/limesurvey-rc2-api.git
git clone https://github.com/JJKid/limesurvey-dictionary-api.git

cd limesurvey-dictionary-api
cp .env.example .env
```

Configure `.env` siguiendo el README de la API de diccionarios y ejecute:

```bash
docker compose up --build -d
docker compose ps
curl http://127.0.0.1:8000/health
```

Resultado esperado:

```json
{"detail":"ok"}
```

| Recurso | Dirección |
| --- | --- |
| FastAPI | `http://127.0.0.1:8000` |
| Swagger | `http://127.0.0.1:8000/docs` |
| OpenAPI | `http://127.0.0.1:8000/openapi.json` |
| API pública de diccionarios | `http://127.0.0.1:8100` |

El `.env` del otro repositorio configura automáticamente este contenedor con
`DICTIONARY_SERVICE_JWT_SECRET`, Redis y la lista de hosts LimeSurvey
permitidos. No hace falta crear otro `.env` aquí para ese despliegue.

Para LimeSurvey local:

```dotenv
ALLOWED_LIMESURVEY_HOSTS=host.docker.internal,localhost,127.0.0.1
ALLOW_INSECURE_LIMESURVEY_HTTP=true
```

Para LimeSurvey remoto use su dominio y HTTPS.

## 2. Autenticación

Salvo `/health` y `/smoke`, las rutas requieren:

```http
Authorization: Bearer <JWT_INTERNO>
```

El JWT lo genera un servicio autorizado, como `limesurvey-dictionary-api`. El
usuario normal de Postman no necesita construirlo cuando llama al puerto
`8100`.

Después del login, este servicio devuelve un UUID local:

```json
{
  "session_key": "5edc24c7-9ee7-48c1-8529-b6d8dd535810"
}
```

Las siguientes llamadas lo envían como:

```http
X-LimeSurvey-Session: 5edc24c7-9ee7-48c1-8529-b6d8dd535810
```

El UUID identifica temporalmente en Redis la sesión LimeSurvey y sólo puede
usarlo la misma identidad JWT que la abrió.

## 3. Probar los endpoints

### Prueba mediante la API pública

Para probar el flujo que genera diccionarios, importe la colección de
`limesurvey-dictionary-api`:

```text
postman/limesurvey-dictionary-api.local.postman_collection.json
```

La colección llama al puerto `8100`; la API pública crea el JWT y llama a este
adaptador automáticamente.

### Prueba directa de FastAPI

`smoke_local.py` prueba con datos reales: login, listado, carga de encuesta y
logout. Desde la carpeta `limesurvey-dictionary-api`, donde corre Compose:

```bash
docker compose exec -T limesurvey-rc2-api python smoke_local.py \
  --api http://127.0.0.1:8000 \
  --url http://host.docker.internal/limesurvey/index.php/admin/remotecontrol \
  --user '<usuario-limesurvey>' \
  --password '<contraseña-limesurvey>' \
  --sid 783587 \
  --language es \
  --jwt-secret '<DICTIONARY_SERVICE_JWT_SECRET>' \
  --jwt-issuer limesurvey-dictionary-api
```

Sustituya los marcadores por los datos configurados. Swagger permite probar
solicitudes individuales en `http://127.0.0.1:8000/docs`, pero exige un JWT
interno válido.

## 4. Integración directa desde otro servicio

La secuencia es:

```text
Servicio consumidor
  → genera JWT interno corto
  → abre sesión con URL, usuario y contraseña LimeSurvey
  → recibe UUID local
  → usa JWT + UUID para consultar encuestas o respuestas
  → cierra la sesión
```

### Abrir sesión

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

La respuesta contiene `session_key`. La contraseña no se persiste.

### Listar encuestas

```http
GET /surveys
Authorization: Bearer <JWT_INTERNO>
X-LimeSurvey-Session: <UUID_LOCAL>
```

Agregue `?refresh=true` para ignorar la caché.

### Obtener la estructura normalizada

```http
GET /survey_structure/783587?language=es
Authorization: Bearer <JWT_INTERNO>
X-LimeSurvey-Session: <UUID_LOCAL>
```

Respuesta:

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

La respuesta completa es `SurveyLoadResult`; `survey` contiene el
`SurveyStructure` e `issues` los diagnósticos de importación.

### Exportar respuestas

```http
GET /survey_responses/783587?language=es&completionStatus=all&headingType=code
Authorization: Bearer <JWT_INTERNO>
X-LimeSurvey-Session: <UUID_LOCAL>
Accept: application/json
```

Use `Accept: text/csv` para CSV. La operación es de sólo lectura y no cachea
las respuestas.

### Cerrar sesión

```http
GET /logout-limesurvey
Authorization: Bearer <JWT_INTERNO>
X-LimeSurvey-Session: <UUID_LOCAL>
```

## 5. Importar un `.lss`

No requiere sesión LimeSurvey, pero sí JWT interno:

```http
POST /survey_structures/from-lss?language=es
Authorization: Bearer <JWT_INTERNO>
Content-Type: multipart/form-data

file: <archivo.lss>
```

Devuelve `SurveyLoadResult`, limita el archivo a 20 MiB, rechaza XML inseguro y
valida la estructura normalizada.

## 6. Rutas principales

| Método y ruta | Autorización | Resultado |
| --- | --- | --- |
| `GET /health` | Ninguna | Estado del servicio. |
| `POST /login-limesurvey` | JWT | Abre sesión y devuelve UUID local. |
| `GET /surveys` | JWT + UUID | Encuestas visibles. |
| `GET /survey_structure/{sid}` | JWT + UUID | `SurveyLoadResult` remoto. |
| `POST /survey_structures/from-lss` | JWT | `SurveyLoadResult` desde archivo. |
| `GET /survey_responses/{sid}` | JWT + UUID | Respuestas JSON o CSV. |
| `GET /logout-limesurvey` | JWT + UUID | Cierra sesión. |

## 7. Códigos de error HTTP

| Estado | Código o detalle | Significado |
| --- | --- | --- |
| `400` | `LIMESURVEY_URL_NOT_ALLOWED` | La URL o el host no están permitidos. |
| `400` | `INVALID_RESPONSE_RANGE` | El rango de respuestas es inválido. |
| `400` | `TOO_MANY_RESPONSE_FIELDS` | Se solicitaron demasiadas columnas. |
| `401` | `Internal service token is missing` | No se envió JWT. |
| `401` | `Internal service token is invalid or expired` | El JWT es inválido o venció. |
| `401` | `LS_SESSION_EXPIRED` | La sesión remota venció; debe repetir el login. |
| `401` | `LimeSurvey session was not found or has expired` | El UUID local no existe o venció. |
| `403` | `LimeSurvey session belongs to another authenticated identity` | Otra identidad intenta usar el UUID. |
| `413` | `LS_RESPONSE_EXPORT_TOO_LARGE` | La exportación excede el límite. |
| `502` | `LS_REMOTE_CONTROL_UNAVAILABLE` | RemoteControl 2 no está disponible. |
| `502` | `LS_REMOTE_REJECTED_REQUEST` | LimeSurvey rechazó la operación. |
| `502` | `INVALID_LS_RESPONSE_EXPORT` | La exportación tiene formato inesperado. |
| `503` | `LS_UNREACHABLE` | No se pudo conectar con LimeSurvey. |
| `504` | `LS_SURVEY_LOAD_TIMEOUT` | La carga de encuesta excedió el tiempo. |
| `504` | `LS_RESPONSE_EXPORT_TIMEOUT` | La exportación excedió el tiempo. |
| `500` | `LS_UNKNOWN` | Error no clasificado. |
| `500` | `INVALID_SURVEY_STRUCTURE` | La normalización produjo una encuesta o resultado de carga inválido. `detail.errors` conserva la ruta y la regla de cada fallo. |

FastAPI coloca el error en `detail`. Cuando es estructurado, el código se
encuentra en `detail.code`.

## 8. Pruebas automatizadas

Sin una instancia LimeSurvey:

Instale también Node 18 o posterior (Docker ya incluye Node 22). La salida del
normalizador se revisa con `schemas/validate-survey.cjs`, generado desde el
mismo Zod de `survey-structure`, incluidas las reglas entre preguntas. Los
archivos JSON Schema describen el contrato, pero no sustituyen esa validación.
El proceso local tiene un límite de cinco segundos y 16 MiB por documento;
si no puede ejecutarse, la solicitud falla sin devolver datos sin validar.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest -q -m "not integration"
```

Prueba de integración real:

```bash
LS_INTEGRATION_URL='https://encuestas.example.org/index.php/admin/remotecontrol' \
LS_INTEGRATION_USERNAME='<usuario>' \
LS_INTEGRATION_PASSWORD='<contraseña>' \
LS_INTEGRATION_SID='783587' \
pytest -q -m integration
```

No guarde estas credenciales en Git.

## 9. Límites operativos y XML

La configuración predeterminada permite cinco segundos para establecer una
conexión con LimeSurvey y treinta para leer cada respuesta. La carga completa
de una encuesta se limita a 120 segundos. Pueden ajustarse mediante:

```dotenv
LS_REMOTE_CONNECT_TIMEOUT_SECONDS=5
LS_REMOTE_READ_TIMEOUT_SECONDS=30
LS_SURVEY_LOAD_TIMEOUT_SECONDS=120
```

El ajuste automático de concurrencia es opcional y permanece desactivado por
defecto. Si se habilita, se ejecuta en segundo plano sobre una muestra acotada
y conserva el resultado durante 72 horas:

```dotenv
LS_OPTIMIZER_ENABLED=false
LS_OPTIMIZER_TTL_SECONDS=259200
LS_OPTIMIZER_MIN_SUCCESS_RATE=0.95
LS_OPTIMIZER_MAX_SURVEYS=3
LS_OPTIMIZER_MAX_GROUPS=10
LS_OPTIMIZER_MAX_SAMPLE_QUESTIONS=10
```

Los archivos `.lss` se limitan a 20 MiB. El importador rechaza declaraciones
`DOCTYPE` y `ENTITY`, usa un analizador protegido contra expansión de
entidades y convierte etiquetas y ayudas HTML a texto plano.
