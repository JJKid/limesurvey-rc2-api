# limesurvey-rc2-api

Servicio FastAPI que concentra la integración con LimeSurvey RemoteControl 2 y
la importación de archivos `.lss`. Su salida principal es `SurveyLoadResult`,
cuya propiedad `survey` contiene el `SurveyStructure` neutral y cuya propiedad
`issues` contiene los diagnósticos de esa operación de carga.

Éste es el nombre único del producto. En el código y en este documento la
palabra **adaptador** describe su responsabilidad arquitectónica; no es otro
producto. Swagger lo presenta como **LimeSurvey RemoteControl 2 Adapter**.

## Qué hace

- inicia y cierra sesiones de LimeSurvey mediante `citric==2.3.0`;
- lista encuestas, grupos y preguntas;
- completa cada pregunta con sus propiedades, opciones y subpreguntas;
- limita la concurrencia, aplica reintentos acotados y reutiliza caché;
- convierte estructuras obtenidas por RemoteControl 2 o archivos `.lss` al mismo contrato;
- valida cada resultado contra el JSON Schema generado por `survey-structure`.
- exporta respuestas LimeSurvey como JSON o CSV sin conservarlas en caché.

No genera diccionarios de datos. Esa responsabilidad corresponde a
`limesurvey-dictionary-api`, que consume este servicio cuando necesita obtener
una encuesta remota o convertir un `.lss`.

## Ejemplo sintético de diagnóstico

El archivo `examples/invalid-condition-reference.lss` es un ejemplo construido
para pruebas; no procede de una encuesta real. Contiene una pregunta cuya regla
de visibilidad referencia el código inexistente `MISSING_QUESTION`.

En Postman se envía como `form-data`, con la clave `file` de tipo **File**, a:

```http
POST http://127.0.0.1:8000/survey_structures/from-lss?language=es
Authorization: Bearer <JWT_INTERNO>
```

El archivo es XML válido y el resto de la encuesta puede normalizarse. Por eso
la operación devuelve `200`, omite la condición ejecutable y agrega un warning
`INVALID_EXPRESSION` dentro de `issues`. No produce
`INVALID_CONNECTOR_CONTRACT`: ese código indica que el conector devolvió una
estructura canónica contradictoria después de normalizar, lo cual corresponde
a una falla de implementación o incompatibilidad entre versiones, no a una
condición de origen que pudo aislarse de forma segura.

Para probar los ejemplos desde la API pública local use la misma petición de
Postman y cambie únicamente el archivo:

```http
POST http://127.0.0.1:8100/v1/survey-structures/from-lss?language=es
Authorization: Bearer <API_KEY_DE_DICCIONARIOS>
Content-Type: multipart/form-data
```

En `Body > form-data`, la clave debe llamarse `file` y ser de tipo **File**.
Todos estos archivos son ejemplos sintéticos, no encuestas reales:

| Archivo en `examples/` | Resultado esperado |
| --- | --- |
| `invalid-malformed-xml.lss` | `400 INVALID_LSS_SOURCE`: XML incompleto. |
| `invalid-document-type.lss` | `400 INVALID_LSS_SOURCE`: el XML no es una estructura de encuesta. |
| `invalid-unsupported-db-version.lss` | `400 INVALID_LSS_SOURCE`: versión de esquema no admitida. |
| `invalid-missing-survey-row.lss` | `400 INVALID_LSS_SOURCE`: falta el registro principal de encuesta. |
| `invalid-missing-survey-id.lss` | `400 INVALID_LSS_SOURCE`: falta el identificador de encuesta. |
| `invalid-dtd-declaration.lss` | `400 INVALID_LSS_SOURCE`: declaración XML insegura rechazada. |
| `invalid-condition-reference.lss` | `200`: condición omitida y warning `INVALID_EXPRESSION`. |
| `issues-question-normalization.lss` | `200`: errores y warnings recuperables en `issues`; los campos válidos permanecen. |
| `warning-dynamic-validation.lss` | `200`: warning `INVALID_VALIDATION`; no se inventa un límite numérico. |
| `visibility-at-least-two-selections.lss` | `200`: LimeSurvey usa `count(that.QUESTION_1.NAOK) >= 2`; el importador lo convierte a una condición neutral `selection-count` y conserva la expresión de origen para auditoría. |

## Inicio rápido con Docker

Este servicio forma parte del despliegue mínimo definido en
`limesurvey-dictionary-api/compose.yaml`. Clone ambos repositorios como carpetas
hermanas y ejecute Compose desde `limesurvey-dictionary-api`.

Para construir únicamente este repositorio:

```bash
docker build -t limesurvey-rc2-api:local .
```

Direcciones locales:

- API: `http://127.0.0.1:8000`
- Swagger: `http://127.0.0.1:8000/docs`
- OpenAPI JSON: `http://127.0.0.1:8000/openapi.json`

### Pruebas reproducibles en un contenedor limpio

La imagen instala desde cero todas las versiones fijadas en `requirements.txt`,
incluida `citric==2.3.0`. Estas pruebas no necesitan una instancia LimeSurvey:

```bash
docker build -t limesurvey-rc2-api:test .
docker run --rm \
  -e ENV=test \
  -e FORM_BUILDER_SERVICE_JWT_SECRET=test-form-builder-secret-with-at-least-32-characters \
  -e DICTIONARY_SERVICE_JWT_SECRET=test-dictionary-secret-with-at-least-32-characters \
  limesurvey-rc2-api:test \
  pytest -q -m "not integration"
```

### Prueba real configurable

La prueba `smoke_local.py` ejecuta un recorrido real de login, listado,
`SurveyStructure` y logout contra una instancia configurada. Desde el contenedor:

```bash
docker compose exec -T limesurvey-fastapi python smoke_local.py \
  --api http://127.0.0.1:8000 \
  --url http://host.docker.internal/limesurvey/index.php/admin/remotecontrol \
  --user '<usuario>' \
  --password '<contraseña>' \
  --sid 783587 \
  --language es \
  --jwt-secret '<mismo SMOKE_LOCAL_JWT_SECRET del contenedor>'
```

El script imprime un resumen; no es una prueba simulada ni conserva la sesión al
terminar. También existe una prueba Pytest de integración real. Se habilita sólo
cuando están definidas sus cuatro variables para no incorporar credenciales al
repositorio:

```bash
LS_INTEGRATION_URL='http://host.docker.internal/limesurvey/index.php/admin/remotecontrol' \
LS_INTEGRATION_USERNAME='<usuario>' \
LS_INTEGRATION_PASSWORD='<contraseña>' \
LS_INTEGRATION_SID='783587' \
pytest -q -m integration
```

Opcionalmente, `LS_INTEGRATION_LSS` puede señalar localmente un archivo `.lss`
para comparar la misma encuesta cargada por RemoteControl 2 y desde archivo.
Las credenciales se proporcionan sólo al proceso de prueba: no se guardan en
Git ni se incorporan a la imagen.

El workflow manual `.github/workflows/real-limesurvey.yml` ejecuta la misma
integración desde GitHub Actions. Requiere configurar esos nombres en
`Settings > Secrets and variables > Actions` y que el servidor LimeSurvey sea
alcanzable desde el runner. No se ejecuta automáticamente en cada push para no
realizar logins remotos ni depender de una instalación privada durante las
pruebas unitarias.

## Inicio directo sin Docker

Desde la raíz de `limesurvey-rc2-api`:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export FORM_BUILDER_SERVICE_JWT_SECRET="$(openssl rand -hex 32)"
export DICTIONARY_SERVICE_JWT_SECRET="$(openssl rand -hex 32)"
export SMOKE_LOCAL_JWT_SECRET="$(openssl rand -hex 32)"
export JWT_AUDIENCE="limesurvey-rc2-api"
export REDIS_HOST=127.0.0.1
export REDIS_PORT=6379
export REDIS_PASSWORD='<contraseña de Redis>'
export ALLOWED_LIMESURVEY_HOSTS='localhost,127.0.0.1,host.docker.internal'
export ALLOW_INSECURE_LIMESURVEY_HTTP=true
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

Los secretos JWT no se obtienen de LimeSurvey. Cada aplicación emisora tiene
su propia clave: Form Builder firma con `FORM_BUILDER_SERVICE_JWT_SECRET` y la
API de diccionarios con `DICTIONARY_SERVICE_JWT_SECRET`. Este adaptador conoce
ambas para verificar los Bearer internos, pero un emisor no necesita conocer la
clave del otro. Los secretos no se envían como encabezados; sólo se usan para
firmar o verificar tokens cortos.

La firma por sí sola no basta. El token también debe declarar `iss`, `aud`,
`sub`, `iat` y `exp`, y su encabezado debe declarar `typ: service+jwt`. El
emisor selecciona la clave exacta con la que se verifica. Así, un token de
usuario, un token vencido o uno destinado a otro servicio no se acepta aquí.

## Variables de entorno

| Variable | Uso | Valor local típico |
| --- | --- | --- |
| `FORM_BUILDER_SERVICE_JWT_SECRET` | Verifica tokens emitidos por Form Builder; puede omitirse en el despliegue exclusivo del diccionario | secreto aleatorio de al menos 32 bytes |
| `DICTIONARY_SERVICE_JWT_SECRET` | Verifica tokens emitidos por la API de diccionarios | otro secreto aleatorio de al menos 32 bytes |
| `FORM_BUILDER_SERVICE_JWT_ISSUER`, `DICTIONARY_SERVICE_JWT_ISSUER` | Relacionan cada emisor con su secreto | `form-builder-server`, `limesurvey-dictionary-api` |
| `SMOKE_LOCAL_JWT_SECRET` | Habilita el emisor de prueba directa sólo fuera de producción | secreto local diferente |
| `JWT_ALGORITHM` | Algoritmo del JWT | `HS256` |
| `JWT_AUDIENCE` | Destinatario que debe declarar el token | `limesurvey-rc2-api` |
| `REDIS_HOST`, `REDIS_PORT` | Ubicación de Redis | `redis:6379` en Compose |
| `REDIS_PASSWORD` | Autenticación de Redis | secreto distinto de `JWT_SECRET` |
| `REDIS_DB` | Base lógica de este servicio | `0` |
| `REDIS_SSL` | Cifra la conexión Redis entre hosts | `false` local, `true` cuando aplique |
| `LS_SESSION_TTL_SECONDS` | Vida de la asociación de sesión | `1800` |
| `LS_LOGIN_RATE_LIMIT_PER_MIN` | Intentos de login por IP/usuario | `8` |
| `LS_SURVEY_LOAD_TIMEOUT_SECONDS` | Límite total para reunir una encuesta remota | `120` |
| `LS_REMOTE_BACKOFF_BASE_SECONDS`, `LS_REMOTE_BACKOFF_MAX_SECONDS`, `LS_REMOTE_BACKOFF_JITTER_RATIO` | Espera exponencial aleatoria entre intentos temporales | `1`, `8`, `0.25` |
| `LS_ACCOUNT_MAX_CONCURRENT_CALLS` | Límite compartido de llamadas RC2 por URL y usuario | `8` |
| `ALLOW_IN_MEMORY_STATE` | Respaldo de estado dentro de un solo proceso | `true` sólo en desarrollo y pruebas; `false` en producción |
| `ALLOWED_LIMESURVEY_HOSTS` | Hosts exactos a los que se permite abrir conexiones RemoteControl | `localhost,127.0.0.1,host.docker.internal` sólo en desarrollo |
| `ALLOW_INSECURE_LIMESURVEY_HTTP` | Permite HTTP en vez de HTTPS | `true` sólo para LimeSurvey local |
| `LS_RESPONSES_TIMEOUT_SECONDS` | Tiempo máximo de una exportación de respuestas | `60` |
| `LS_RESPONSES_MAX_BYTES` | Tamaño máximo del archivo exportado | `20971520` |
| `LS_RESPONSES_RATE_LIMIT_PER_MIN` | Exportaciones por sesión/encuesta y minuto | `12` |
| `LS_RESPONSES_MAX_FIELDS` | Máximo de columnas solicitadas | `500` |
| `CORS_ORIGINS` | Orígenes permitidos | lista separada por comas |

El archivo `.env.example` de la raíz contiene la lista compartida por Docker
Compose. Para producción, Redis no debe publicar el puerto `6379`; debe usar
contraseña fuerte, red privada, expiraciones y TLS cuando la conexión cruce
hosts.

Con `ENV=production`, Redis es obligatorio. Mantenga
`ALLOW_IN_MEMORY_STATE=false`; si Redis no está disponible, la aplicación debe
fallar al iniciar. Esto evita que distintos workers conserven sesiones y cachés
incompatibles en memorias que no comparten.

## Autenticación: tres identificadores distintos

No son tres nombres para lo mismo:

| Valor | Quién lo crea | Qué contiene o representa | Dónde se envía |
| --- | --- | --- | --- |
| JWT interno | Form Builder o `limesurvey-dictionary-api` | identidad y expiración firmadas; no contiene la contraseña de LimeSurvey | `Authorization: Bearer <jwt>` |
| session key remota | LimeSurvey | credencial temporal real de RemoteControl 2 | sólo dentro de las llamadas Citric a LimeSurvey |
| llave local | `limesurvey-rc2-api` | UUID aleatorio que apunta al registro temporal de Redis | `X-LimeSurvey-Session: <uuid>` |

El encabezado `X-LimeSurvey-Session` contiene únicamente el UUID local, por
ejemplo `5edc24c7-9ee7-48c1-8529-b6d8dd535810`. No contiene JSON, usuario,
contraseña, prefijo Redis ni session key remota.

El registro Redis se guarda así:

```text
clave: ls:session:5edc24c7-9ee7-48c1-8529-b6d8dd535810
valor: {"url":".../admin/remotecontrol","username":"jj","session_key":"<llave remota>","owner_sub":"<identidad>","owner_iss":"<emisor>"}
TTL:   LS_SESSION_TTL_SECONDS
```

`owner_sub` y `owner_iss` ligan la llave local al mismo JWT que abrió la sesión;
conocer el UUID no permite reutilizarla desde otra identidad. La contraseña se
usa durante el login y no se persiste. El valor de Redis sí
es sensible porque incluye la credencial remota; por eso Redis no constituye
un mecanismo de autorización HTTP y debe quedar restringido a los servicios.

### Abrir sesión directamente

```http
POST http://127.0.0.1:8000/login-limesurvey
Authorization: Bearer <JWT_INTERNO>
Content-Type: application/json

{
  "url": "http://localhost/limesurvey/index.php/admin/remotecontrol",
  "username": "usuario",
  "password": "contraseña"
}
```

Respuesta:

```json
{
  "session_key": "5edc24c7-9ee7-48c1-8529-b6d8dd535810"
}
```

En Docker, una URL `localhost` o `127.0.0.1` se resuelve internamente a
`host.docker.internal`; el consumidor sigue enviando la URL que conoce.

### Usar la sesión

```http
GET http://127.0.0.1:8000/survey_structure/783587?language=es
Authorization: Bearer <JWT_INTERNO>
X-LimeSurvey-Session: 5edc24c7-9ee7-48c1-8529-b6d8dd535810
```

Para comprobar cambios o eliminaciones sin esperar el TTL, agrega
`refresh=true` a `GET /surveys` o `GET /survey_structure/{sid}`. La solicitud
omite la copia temporal, lee nuevamente LimeSurvey y reemplaza la caché con el
resultado reciente.

La respuesta es un `SurveyLoadResult`:

```json
{
  "survey": {
    "contractVersion": "2.0.0",
    "id": "783587",
    "fields": []
  },
  "issues": [],
  "responseState": {
    "active": true,
    "canSaveResponses": true,
    "submitMode": "submit",
    "warningCodes": [],
    "didNotSaveCode": null
  }
}
```

`survey` es el documento editable y persistible. `issues` pertenece a esta
operación de importación. `responseState` describe si la encuesta remota puede
recibir respuestas en ese momento y tampoco se persiste como estructura.

Para cerrar la sesión:

```http
GET http://127.0.0.1:8000/logout-limesurvey
Authorization: Bearer <JWT_INTERNO>
X-LimeSurvey-Session: 5edc24c7-9ee7-48c1-8529-b6d8dd535810
```

### Exportar respuestas

La sesión utiliza los permisos del mismo usuario de LimeSurvey que inició
sesión. El endpoint es de sólo lectura y no conserva las filas en Redis ni en
la caché de definiciones.

```http
GET http://127.0.0.1:8000/survey_responses/783587?language=es&completionStatus=all&headingType=code&responseType=short
Authorization: Bearer <JWT_INTERNO>
X-LimeSurvey-Session: <UUID_LOCAL>
Accept: application/json
```

```json
{
  "surveyId": "783587",
  "language": "es",
  "responses": [
    { "Q01": "A1", "SERVICES_SQ001": "Y" }
  ]
}
```

Para obtener el CSV original se envía `Accept: text/csv`. Los filtros
opcionales son `fromResponseId`, `toResponseId` y `fields`. El servicio limita
tiempo, tamaño, frecuencia y número de columnas, devuelve
`Cache-Control: no-store` y no escribe el contenido exportado en los logs.

## Flujo desde Form Builder

1. El navegador inicia sesión con NestJS.
2. NestJS coloca el JWT de Form Builder en la cookie HttpOnly
   `form-builder.at`; JavaScript del navegador no lee ese valor.
3. El navegador llama al proxy NestJS y envía la cookie automáticamente.
4. NestJS valida el JWT del usuario y genera un JWT interno de 60 segundos con
   `sub` igual al identificador del usuario. Llama a `limesurvey-rc2-api` con
   `Authorization: Bearer <jwt-interno>`.
5. Después del login de LimeSurvey, NestJS guarda el UUID local en
   `request.session.ls_session`. La cookie HttpOnly `form-builder.session-id` sólo
   identifica esa sesión de NestJS; no contiene el UUID de LimeSurvey.
6. En consultas posteriores NestJS añade ese UUID como
   `X-LimeSurvey-Session`; Angular no administra ninguna session key.

## Flujo desde limesurvey-dictionary-api

1. El consumidor llama `POST /v1/limesurvey/sessions` en el puerto `8100` con
   su API key y las credenciales LimeSurvey.
2. La API de diccionarios crea un JWT interno de 60 segundos y llama
   `POST /login-limesurvey` en este servicio.
3. Este servicio guarda la session key remota y devuelve el UUID local.
4. La API de diccionarios guarda ese UUID y devuelve al consumidor otro token
   opaco, con forma `ls_session_<valor aleatorio>`.
5. El consumidor usa ese token opaco como Bearer en
   `/v1/limesurvey/surveys/{sid}/dictionary`.

Por lo tanto, el Bearer público de la API de diccionarios no es el JWT interno,
no es el UUID local y no es la session key remota de LimeSurvey.

## Importar un archivo `.lss`

```http
POST http://127.0.0.1:8000/survey_structures/from-lss?language=es
Authorization: Bearer <JWT_INTERNO>
Content-Type: multipart/form-data

file: <archivo .lss>
```

El campo multipart se llama `file`. Esta operación:

1. limita el archivo a 20 MiB;
2. rechaza DTD y entidades XML;
3. valida que sea una exportación de estructura de encuesta;
4. admite `DBVersion` 348, 623, 643 y 708;
5. une traducciones, respuestas permitidas, atributos y condiciones;
6. normaliza el resultado a `SurveyStructure`;
7. valida el `SurveyLoadResult` completo con JSON Schema.

No usa Citric ni requiere `X-LimeSurvey-Session`, porque el XML ya contiene la
estructura que se necesita leer.

## Rutas principales

| Ruta | Resultado |
| --- | --- |
| `POST /login-limesurvey` | crea la asociación local/remota |
| `GET /surveys` | encuestas visibles para la cuenta |
| `GET /survey_structure/{sid}` | `SurveyLoadResult` canónico desde LimeSurvey remoto |
| `POST /survey_structures/from-lss` | `SurveyLoadResult` canónico desde archivo |
| `GET /survey_responses/{sid}` | exportación de respuestas en JSON o CSV |
| `GET /logout-limesurvey` | cierra LimeSurvey y elimina la asociación local |

## Organización del código

```text
app.py                              arranque, middleware y ciclo de vida
core/                               configuración, URL permitida y validación del JWT
routers/                            contratos HTTP y coordinación de cada ruta
services/limesurvey_client.py       fachada mínima sobre Citric
services/citric_session_adapter.py  creación y reanudación compatible con Citric 2.3.0
services/limesurvey_fetchers.py     concurrencia y reintentos por grupo/pregunta
services/remote_survey_loader.py    carga y enriquecimiento remoto de preguntas
services/remote_survey_structure_loader.py  construcción remota del resultado completo
services/limesurvey_session_service.py      autorización y reanudación de sesión
repositories/session_repository.py          asociación local/remota en Redis
repositories/concurrency_repository.py      límite global por cuenta
infrastructure/redis_client.py               conexión Redis compartida
services/survey_structure/
  normalizer.py                     normalización común a SurveyStructure
  lss_importer.py                   lectura segura del XML .lss
  contract.py                       validación con JSON Schema
schemas/                            artefactos generados por survey-structure
tests/                              pruebas de fachada, rutas, sesión y contrato
```

Los docstrings están en inglés porque forman parte de la documentación técnica
del código y Swagger. Los mensajes de esta guía están en español para facilitar
la incorporación al proyecto.

## Validación compartida

`survey-structure` define el contrato ejecutable con Zod y genera
`survey-structure.schema.json` y `survey-load-result.schema.json`. Python no
puede ejecutar Zod directamente, por lo que lee esos artefactos estándar. Cada
esquema se carga una vez por proceso, se verifica con
`Draft7Validator.check_schema` y después valida recursivamente el diccionario
producido por FastAPI.

Un error como `fields[0].cod` en vez de `fields[0].code`, un `type` inexistente
o una propiedad adicional provoca `SurveyStructureContractError` antes de que
el servicio entregue una respuesta aparentemente válida.

## Seguridad de producción

- no publique Redis ni reutilice sus credenciales como credenciales HTTP;
- use HTTPS para LimeSurvey y permita únicamente hosts conocidos;
- mantenga diferentes secretos para cada emisor JWT, Redis y las API keys públicas;
- rote secretos y limite sus permisos de lectura en el entorno de despliegue;
- no registre Authorization, contraseñas, session keys, CSV ni respuestas;
- conserve timeouts, rate limiting, límites de cuerpo y TTL;
- use una red privada y `REDIS_SSL=true` cuando Redis esté en otro host.
