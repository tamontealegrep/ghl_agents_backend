# Desplegar Family Aims en Render

Guía paso a paso para publicar Family Aims (agente de texto por webhook de GoHighLevel y agentes de voz) como un servicio web de Render. Resume la sección «Despliegue en Render» del `README.md` y se apoya en `render.yaml`, `Dockerfile` y `companies/family_aims/env.example`.

## Cómo funciona

- Una empresa = un servicio web de Render. Para Family Aims el servicio se llama `agents-family-aims`.
- Se construye con el `Dockerfile` del repo. El argumento `COMPANY=family_aims` decide qué carpeta de `companies/` se copia a la imagen (`bundles/` y `shared/`). Lo que se copió es lo que corre: en Render no se monta nada.
- Los agentes que se publican son los **bundles ya compilados** que están en el repo (`companies/family_aims/bundles/`). Si cambias una definición en el compilador, recompila hacia el backend, haz commit y push **antes** de desplegar.
- El `.env` y las bases `*.db` nunca entran en la imagen (`.dockerignore`).

Agentes de Family Aims y sus rutas:

| Agente | Canal | Ruta |
|---|---|---|
| `family_aims_sam_text` | Texto (GoHighLevel) | `POST /agents/family_aims/sam-text` (webhook) |
| `family_aims_sam_en_voice`, `_es_voice`, `_pt_voice` | Voz | `POST /agents/<agente>/chat` |
| (herramientas del plugin `desk`) | Ambos | `POST /agents/family_aims/tools/<herramienta>-ghl` |
| (herramientas built-in de GHL: `add-tags`, `remove-tags`, `update-contact`, `update-opportunity`, `update-custom-field`, ...) | Ambos | `POST /builtin-tools/<herramienta>` |

## Antes de empezar

1. El repo `backend` está en GitHub y la rama que vas a desplegar tiene todo pusheado (bundles recompilados incluidos).
2. Tienes una cuenta de Render con plan de pago. El plan `starter` es el mínimo: un servicio dormido pierde el buffer de mensajes (vive en memoria) y contesta tarde.
3. Tienes a mano:
   - Llave y modelo de al menos un proveedor de LLM (`OPENAI_API_KEY` + `OPENAI_MODEL`, o Anthropic / Google).
   - El token de GoHighLevel de la subcuenta de Family Aims (`GHL_TOKEN`) y su `GHL_LOCATION_ID` (es el id que aparece en la URL de la app: `.../location/<id>/...`).
   - El id del calendario round-robin de GHL (`FA_GHL_CALENDAR_ID_FT`).
   - Credenciales de Gmail si se envían correos de confirmación (`FA_GOOGLE_*_GMAIL`, `FA_GMAIL_SENDER_EMAIL`).

## Paso 1. Base de datos Postgres

Crea una base **Postgres** en Render (*New > PostgreSQL*) para Family Aims, en la misma región que el servicio web. Copia su **Internal Database URL**: va en `DATABASE_URL`.

Sin base de datos, las conversaciones se guardan en un `sessions.db` local y **se pierden en cada reinicio o despliegue** (el disco de Render es efímero).

## Paso 2. Crear el servicio con el Blueprint

1. En Render: *New > Blueprint* y elige el repositorio `ghl_agents_backend`.
2. Render lee `render.yaml` y propone dos servicios: `agents-family-aims` y `agents-babynova`. Si solo quieres Family Aims, deja solo ese (o elimina el otro después).
3. Render te pide los valores marcados `sync: false`:

   | Variable | Qué poner |
   |---|---|
   | `OPENAI_API_KEY` | Llave de OpenAI |
   | `LLM_PROVIDERS` | Proveedores por orden de preferencia, por ejemplo `openai` o `openai,anthropic`. **Obligatoria**: sin ella el servicio no arranca |
   | `OPENAI_MODEL` | Modelo de OpenAI (no hay modelo por defecto) |
   | `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, `GOOGLE_API_KEY`, `GOOGLE_MODEL` | Solo si el proveedor está en `LLM_PROVIDERS`; cada uno necesita llave **y** modelo |
   | `DATABASE_URL` | Internal Database URL del Paso 1 |
   | `GHL_TOKEN` | Token de GHL de Family Aims |
   | `GHL_LOCATION_ID` | Id de la subcuenta de Family Aims |

4. `COMPANY=family_aims` ya viene en el Blueprint, y Render genera `ADMIN_TOKEN`, `API_TOKEN` y `WEBHOOK_TOKEN`. Los ves después en la pestaña *Environment*; guárdalos, los necesitas en GHL.

`autoDeploy` está en `false`: tú decides cuándo desplegar (*Manual Deploy*) hasta verificar la primera puesta en producción.

> Si el primer build falla con «Set the COMPANY build argument», crea la variable `COMPANY=family_aims` en *Environment* y vuelve a desplegar.

## Paso 3. Resto de variables de entorno

Render no lee tu `.env`. En el servicio abre *Environment > Add from .env* y pega la parte de `companies/family_aims/env.example` **que va antes del banner `DEVELOPMENT ONLY`** (empieza en `COMPANY=family_aims`). Lo que queda debajo (`HOST_PORT`, `HOST`, `PORT`, `NGROK_*`, `SEND_REQUEST_*`, `RENDER_BASE_URL`, `DATABASE_HOST`/`DATABASE_USER`/... sueltas, `ECHO_ALLOWED_PHONES`) es de tu máquina y no se pega.

Revisa estas:

| Variable | Valor para producción |
|---|---|
| `FA_DEV_ENFORCE_PHONE_WHITELIST` | `false` para atender a todos. Con `true` y `FA_DEV_ALLOWED_PHONES` vacío el agente **ignora todos los mensajes** |
| `FA_DEV_ALLOWED_PHONES` | Solo si dejas la restricción activa: teléfonos E.164 separados por coma |
| `FA_GHL_CALENDAR_ID_FT` | Id del calendario round-robin de GHL |
| `FA_DURATION_MINUTES_FT`, `FA_POST_BUFFER_MINUTES_FT`, `FA_DATE_RANGE_DAYS_FT` | Ya traen valores por defecto (30, 10, 14); ajusta si hace falta |
| `FA_NOTIFICATION_EMAIL` | Correo(s) que reciben aviso de cada cita; vacío = no se envía nada |
| `FA_GOOGLE_*_GMAIL`, `FA_GMAIL_SENDER_EMAIL` | Solo si envías correos de confirmación |
| `GLOBAL_ROUTER_RESPECT_FILTER` | `true` = el agente responde con cortesía ante insultos o discurso de odio |
| `GLOBAL_ROUTER_LANGUAGE_DETECTION` | `false` = frases fijas primero; `true` = el modelo detecta el cambio de idioma |
| `GLOBAL_ROUTER_LANGUAGES` | Idiomas a los que puede cambiar una conversación, separados por comas y por nombre o código (`English,Spanish,Portuguese,French`). Vacío = `English,Spanish,Portuguese` |
| `GLOBAL_ROUTER_OUTPUT_REVIEW` | `false`. La revisión de salida hoy solo aplica a agentes con reglas declaradas (BabyNova) |
| `GHL_VERSION` | `v3` |

Render pone `PORT` solo; el backend lo lee. No lo definas.

Guarda los cambios: Render reinicia el servicio.

## Paso 4. Desplegar y verificar

1. *Manual Deploy > Deploy latest commit*. Mira el log del build y del arranque.
2. Cuando esté en *Live*, prueba (cambia `<servicio>` por el dominio que te dio Render):

   ```bash
   curl https://<servicio>.onrender.com/health
   ```

   Debe listar los cuatro agentes: `family_aims_sam_text`, `family_aims_sam_en_voice`, `family_aims_sam_es_voice` y `family_aims_sam_pt_voice`. Si `agents` viene vacío, la imagen no trae bundles (revisa que `companies/family_aims/bundles` esté en el commit desplegado).

3. Prueba un agente de voz o de chat:

   ```bash
   curl -X POST https://<servicio>.onrender.com/agents/family_aims_sam_es_voice/chat \
     -H "X-API-Key: <API_TOKEN>" -H "Content-Type: application/json" \
     -d '{"message": "Hola", "contact": {"contact_id": "<id de un contacto de prueba>"}}'
   ```

## Paso 5. Conectar GoHighLevel

1. **Webhook del agente de texto.** En el workflow de GHL, acción *Webhook*:
   - URL: `https://<servicio>.onrender.com/agents/family_aims/sam-text`
   - Método: `POST`
   - Cabecera personalizada: `X-Webhook-Token: <WEBHOOK_TOKEN>`
   - El payload debe traer `contact_id` y `location_id`; sin ellos el webhook lo ignora.
2. **Workflows que llamen herramientas** (`/agents/family_aims/tools/...` o `/builtin-tools/...`) necesitan la cabecera `X-API-Key: <API_TOKEN>`.
3. Si el token de GHL no tiene el alcance `contacts.write` y `opportunities.write`, las herramientas `add_tags`, `remove_tags`, `update_contact` y `update_opportunity` devolverán un error 401/403: dale esos alcances en la integración privada de GHL.

## Actualizar el despliegue

| Cambio | Qué hacer |
|---|---|
| Flujo de un agente (recompilado) | Commit + push de `companies/family_aims/bundles/` y *Manual Deploy* |
| Código del backend o herramientas | Commit + push y *Manual Deploy* |
| Solo variables de entorno | Edítalas en *Environment*; Render reinicia el servicio |
| Recargar un flujo sin reiniciar | `POST /agents/<agente>/admin/reload` con `Authorization: Bearer <ADMIN_TOKEN>` (solo sirve si el bundle ya está en la imagen) |

## Problemas frecuentes

| Síntoma | Causa |
|---|---|
| El servicio no arranca | Falta `LLM_PROVIDERS`, o un proveedor listado no tiene llave **y** modelo |
| `Missing credentials` en el log | Falta la llave o el modelo del primer proveedor |
| `/health` con `"agents":[]` | La imagen no trae bundles o no tienen `graph.json` y `assets.json` |
| El webhook responde 200 pero el agente no contesta | Restricción de teléfonos activa con lista vacía (`FA_DEV_ENFORCE_PHONE_WHITELIST=true`) |
| El webhook responde 401/403 | `X-Webhook-Token` ausente o distinto de `WEBHOOK_TOKEN` |
| Las conversaciones se pierden al desplegar | Falta `DATABASE_URL` (se usa SQLite efímero) |
| Respuestas tardías o mensajes perdidos | Plan gratuito o más de una instancia; usa plan `starter` o superior y **una sola instancia** |
| Una herramienta de GHL responde «GHL returned HTTP 401/403» | `GHL_TOKEN` incorrecto, de otra subcuenta, o sin alcances de escritura |
