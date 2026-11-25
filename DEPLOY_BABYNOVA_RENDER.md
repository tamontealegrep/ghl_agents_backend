# Desplegar BabyNova en Render

Guía paso a paso para publicar BabyNova (agentes de texto por webhook de GoHighLevel y agentes de voz) como un servicio web de Render. Resume la sección «Despliegue en Render» del `README.md` y se apoya en `render.yaml`, `Dockerfile` y `companies/babynova/env.example`.

## Cómo funciona

- Una empresa = un servicio web de Render. Para BabyNova el servicio se llama `agents-babynova`.
- Se construye con el `Dockerfile` del repo. El argumento `COMPANY=babynova` decide qué carpeta de `companies/` se copia a la imagen (`bundles/` y `shared/`). Lo que se copió es lo que corre: en Render no se monta nada.
- Los agentes que se publican son los **bundles ya compilados** que están en el repo (`companies/babynova/bundles/`). Si cambias una definición en el compilador, recompila hacia el backend, haz commit y push **antes** de desplegar.
- El `.env` y las bases `*.db` nunca entran en la imagen (`.dockerignore`).

Agentes de BabyNova y sus rutas:

| Agente | Canal | Ruta |
|---|---|---|
| `babynova_triage_obstetrico_text` | Texto (GoHighLevel) | `POST /agents/babynova/triage-text` (webhook) |
| `babynova_surrogate_questions_text` | Texto (GoHighLevel) | `POST /agents/babynova/surrogate-questions-text` (webhook) |
| `babynova_donor_questions_text` | Texto (GoHighLevel) | `POST /agents/babynova/donor-questions-text` (webhook) |
| `babynova_surrogate_questions_voice` | Voz | `POST /agents/<agente>/chat` |
| (herramientas del plugin `surrogacy`) | Ambos | `POST /agents/babynova/tools/<herramienta>-ghl` y `-sur` |
| (herramientas built-in de GHL: `add-tags`, `remove-tags`, `get-contact`, `update-contact`, `update-opportunity`, `update-custom-field`, `send-whatsapp-template`, `send-whatsapp-file`, ...) | Ambos | `POST /builtin-tools/<herramienta>` |

Las herramientas built-in están disponibles en todo el servicio, pero hoy solo las declaran los agentes `surrogate_questions` (texto y voz); el de triaje obstétrico usa únicamente las del plugin.

## Antes de empezar

1. El repo `backend` está en GitHub y la rama `main` tiene todo pusheado (bundles recompilados incluidos).
2. Tienes una cuenta de Render con plan de pago. El plan `starter` es el mínimo: un servicio dormido pierde el buffer de mensajes (vive en memoria) y contesta tarde.
3. Tienes a mano:
   - Llave y modelo de al menos un proveedor de LLM (`OPENAI_API_KEY` + `OPENAI_MODEL`, o Anthropic / Google).
   - El token de GoHighLevel de la subcuenta de BabyNova (`GHL_TOKEN`) y su `GHL_LOCATION_ID` (es el id que aparece en la URL de la app: `.../location/<id>/...`).
   - El id del calendario de GHL (`BN_GHL_CALENDAR_ID_FT`).
   - La llave de Croma para consultar afiliaciones ADRES (`CROMA_API_KEY`).
   - Credenciales de Gmail si se envían correos de aviso (`BN_GOOGLE_*_GMAIL`, `BN_GMAIL_SENDER_EMAIL`).

## Paso 1. Base de datos Postgres

Crea una base **Postgres** en Render (*New > PostgreSQL*) para BabyNova, en la misma región que el servicio web. Copia su **Internal Database URL**: va en `DATABASE_URL`.

Sin base de datos, las conversaciones se guardan en un `sessions.db` local y **se pierden en cada reinicio o despliegue** (el disco de Render es efímero). El mensaje de cierre a los 23:45 para hilos inactivos también necesita Postgres.

## Paso 2. Crear el servicio con el Blueprint

1. En Render: *New > Blueprint* y elige el repositorio `ghl_agents_backend`.
2. Render lee `render.yaml` y propone dos servicios: `agents-family-aims` y `agents-babynova`. Si solo quieres BabyNova, deja solo ese (o elimina el otro después).
3. Render te pide los valores marcados `sync: false`:

   | Variable | Qué poner |
   |---|---|
   | `OPENAI_API_KEY` | Llave de OpenAI |
   | `LLM_PROVIDERS` | Proveedores por orden de preferencia, por ejemplo `openai` o `openai,anthropic`. **Obligatoria**: sin ella el servicio no arranca |
   | `OPENAI_MODEL` | Modelo de OpenAI (no hay modelo por defecto) |
   | `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, `GOOGLE_API_KEY`, `GOOGLE_MODEL` | Solo si el proveedor está en `LLM_PROVIDERS`; cada uno necesita llave **y** modelo |
   | `DATABASE_URL` | Internal Database URL del Paso 1 |
   | `GHL_TOKEN` | Token de GHL de BabyNova |
   | `GHL_LOCATION_ID` | Id de la subcuenta de BabyNova |
   | `CROMA_API_KEY` | Llave de Croma (herramienta `check_adres`); sin ella la herramienta responde `success=false` |

4. `COMPANY=babynova` ya viene en el Blueprint, y Render genera `ADMIN_TOKEN`, `API_TOKEN` y `WEBHOOK_TOKEN`. Los ves después en la pestaña *Environment*; guárdalos, los necesitas en GHL.

`autoDeploy` está en `false`: tú decides cuándo desplegar (*Manual Deploy*) hasta verificar la primera puesta en producción.

> Si el primer build falla con «Set the COMPANY build argument», crea la variable `COMPANY=babynova` en *Environment* y vuelve a desplegar.

## Paso 3. Resto de variables de entorno

Render no lee tu `.env`. En el servicio abre *Environment > Add from .env* y pega la parte de `companies/babynova/env.example` **que va antes del banner `DEVELOPMENT ONLY`** (empieza en `COMPANY=babynova`). Lo que queda debajo (`HOST_PORT`, `HOST`, `PORT`, `NGROK_*`, `SEND_REQUEST_*`, `RENDER_BASE_URL`, `DATABASE_HOST`/`DATABASE_USER`/... sueltas, `ECHO_ALLOWED_PHONES`) es de tu máquina y no se pega.

Revisa estas:

| Variable | Valor para producción |
|---|---|
| `BN_DEV_ENFORCE_PHONE_WHITELIST` | `false` para atender a todos. Con `true` y `BN_DEV_ALLOWED_PHONES` vacío los dos agentes de texto **ignoran todos los mensajes** |
| `BN_DEV_ALLOWED_PHONES` | Solo si dejas la restricción activa: teléfonos E.164 separados por coma (aplica a triaje y a surrogate questions) |
| `BN_GHL_CALENDAR_ID_FT` | Id del calendario de GHL. **En BabyNova toda llamada de agenda exige `calendar_type`**; sin la clave `FT` definida falla |
| `BN_DURATION_MINUTES_FT`, `BN_POST_BUFFER_MINUTES_FT`, `BN_DATE_RANGE_DAYS_FT` | Vacíos = se leen del calendario de GHL; un valor escrito aquí siempre gana |
| `BN_NOTIFICATION_EMAIL` | Correo(s) que reciben aviso de cada cita; vacío = no se envía nada |
| `BN_GOOGLE_*_GMAIL`, `BN_GMAIL_SENDER_EMAIL` | Solo si envías correos de aviso |
| `CROMA_BASE_URL`, `CROMA_TIMEOUT_SECONDS` | Opcionales (`https://api.croma.run`, 60 s) |
| `GLOBAL_ROUTER_RESPECT_FILTER` | `true` = el agente responde con cortesía ante insultos o discurso de odio |
| `GLOBAL_ROUTER_LANGUAGE_DETECTION` | `false` = frases fijas primero; `true` = el modelo detecta el cambio de idioma |
| `GLOBAL_ROUTER_LANGUAGES` | Idiomas a los que puede cambiar una conversación, separados por comas y por nombre o código (`English,Spanish,Portuguese,French`). Vacío = `English,Spanish,Portuguese` |
| `GLOBAL_ROUTER_OUTPUT_REVIEW` | `true` = antes de enviar, cada mensaje se revisa contra las reglas de salida y las palabras prohibidas del agente (cuesta **una llamada al modelo por mensaje**). Solo actúa en los agentes `surrogate_questions`; el de triaje no declara reglas |
| `GHL_VERSION` | `v3` |

Render pone `PORT` solo; el backend lo lee. No lo definas.

Guarda los cambios: Render reinicia el servicio.

## Paso 4. Desplegar y verificar

1. *Manual Deploy > Deploy latest commit*. Mira el log del build y del arranque.
2. Cuando esté en *Live*, prueba (cambia `<servicio>` por el dominio que te dio Render):

   ```bash
   curl https://<servicio>.onrender.com/health
   ```

   Debe listar los tres agentes: `babynova_triage_obstetrico_text`, `babynova_surrogate_questions_text` y `babynova_surrogate_questions_voice`. Si `agents` viene vacío, la imagen no trae bundles (revisa que `companies/babynova/bundles` esté en el commit desplegado).

3. Prueba un agente de voz o de chat:

   ```bash
   curl -X POST https://<servicio>.onrender.com/agents/babynova_surrogate_questions_voice/chat \
     -H "X-API-Key: <API_TOKEN>" -H "Content-Type: application/json" \
     -d '{"message": "Hola", "contact": {"contact_id": "<id de un contacto de prueba>"}}'
   ```

## Paso 5. Conectar GoHighLevel

1. **Webhooks de los agentes de texto.** En el workflow de GHL, acción *Webhook*, una por agente:
   - Triaje obstétrico: `https://<servicio>.onrender.com/agents/babynova/triage-text`
   - Surrogate questions: `https://<servicio>.onrender.com/agents/babynova/surrogate-questions-text`
   - Donor questions: `https://<servicio>.onrender.com/agents/babynova/donor-questions-text`
   - Método `POST`, con la cabecera personalizada `X-Webhook-Token: <WEBHOOK_TOKEN>`.
   - El payload debe traer `contact_id` y `location_id`; sin ellos el webhook lo ignora.
2. **Workflows que llamen herramientas** (`/agents/babynova/tools/...` o `/builtin-tools/...`) necesitan la cabecera `X-API-Key: <API_TOKEN>`.
3. Si el token de GHL no tiene los alcances `contacts.write` y `opportunities.write`, las herramientas `add_tags`, `remove_tags`, `update_contact` y `update_opportunity` devolverán un error 401/403: dale esos alcances en la integración privada de GHL. `get_contact` solo lee: necesita el alcance `contacts.readonly`.
4. Las herramientas `send_whatsapp_template` y `send_whatsapp_file` necesitan el alcance `conversations/message.write` en el token de la subcuenta. La plantilla se identifica por nombre e idioma (no por el ID numérico de su lista) con la forma que usa la propia app de GHL, que la página pública del endpoint no documenta; el archivo se envía por URL pública (GHL documenta 5 MB por archivo).

## Actualizar el despliegue

| Cambio | Qué hacer |
|---|---|
| Flujo de un agente (recompilado) | Commit + push de `companies/babynova/bundles/` y *Manual Deploy* |
| Código del backend o herramientas | Commit + push y *Manual Deploy* |
| Solo variables de entorno | Edítalas en *Environment*; Render reinicia el servicio |
| Recargar un flujo sin reiniciar | `POST /agents/<agente>/admin/reload` con `Authorization: Bearer <ADMIN_TOKEN>` (solo sirve si el bundle ya está en la imagen) |

## Problemas frecuentes

| Síntoma | Causa |
|---|---|
| El servicio no arranca | Falta `LLM_PROVIDERS`, o un proveedor listado no tiene llave **y** modelo |
| `Missing credentials` en el log | Falta la llave o el modelo del primer proveedor |
| `/health` con `"agents":[]` | La imagen no trae bundles o no tienen `graph.json` y `assets.json` |
| El webhook responde 200 pero el agente no contesta | Restricción de teléfonos activa con lista vacía (`BN_DEV_ENFORCE_PHONE_WHITELIST=true`) |
| El webhook responde 401/403 | `X-Webhook-Token` ausente o distinto de `WEBHOOK_TOKEN` |
| Las conversaciones se pierden al desplegar | Falta `DATABASE_URL` (se usa SQLite efímero) |
| Las herramientas de agenda fallan | No hay `BN_GHL_CALENDAR_ID_FT`, o la llamada no manda `calendar_type` |
| `check_adres` responde `success=false` | Falta `CROMA_API_KEY` |
| Las respuestas tardan más de lo normal | `GLOBAL_ROUTER_OUTPUT_REVIEW=true` añade una llamada al modelo por mensaje; desactívala si no la necesitas |
| Respuestas tardías o mensajes perdidos | Plan gratuito o más de una instancia; usa plan `starter` o superior y **una sola instancia** |
| Una herramienta de GHL responde «GHL returned HTTP 401/403» | `GHL_TOKEN` incorrecto, de otra subcuenta, o sin alcances de escritura |
