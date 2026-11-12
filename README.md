# agent-backend — un contenedor por empresa

La imagen Docker es **una sola y está en blanco**: no trae ningún agente ni herramienta. Cada empresa es una carpeta dentro de [`companies/`](companies) con sus agentes, sus herramientas y su `.env`. Docker monta esa carpeta, y el contenedor sirve lo que encuentra.

```
companies/
├── _template/            ← empresa en blanco: cópiala para crear una nueva
├── family_aims/          ← contenedor de Family Aims   (puerto 8011)
└── babynova/             ← contenedor de BabyNova      (puerto 8012)
```

Dentro de cada empresa:

```
companies/<empresa>/
├── docker-compose.yml    ← nombre del proyecto y puerto; el resto es igual en todas
├── env.example           ← copiar a .env (no se sube a git)
└── bundles/
    ├── <agente>/         ← un agente = una carpeta
    │   ├── graph.json    ┐
    │   ├── assets.json   ├─ los genera el compilador; no se editan a mano
    │   ├── knowledge.md  ┘
    │   ├── agent.yaml    ← lo escribes tú: herramientas, webhook, prefijo de variables
    │   └── tools/        ← (opcional) herramientas solo de ese agente
    └── _tools/
        └── <plugin>/     ← herramientas compartidas por varios agentes de la empresa
```

Lo único que cambia entre empresas es esa carpeta. Para **agregar un agente, una herramienta o un endpoint no se toca el código del backend ni la imagen**.

---

## 1. Levantar Family Aims o BabyNova

Requisitos: Docker en marcha. Desde la carpeta de la empresa:

```bash
cd companies/family_aims
cp env.example .env
```

Edita `.env` y completa al menos la llave de un proveedor (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY` o `GEMINI_API_KEY`), `ADMIN_TOKEN`, `API_TOKEN` y `WEBHOOK_TOKEN` (genera cada uno con `python -c "import secrets; print(secrets.token_urlsafe(32))"`), más las variables de la sección «Variables por empresa» (más abajo). Luego:

```bash
docker compose up -d --build
```

Verifica:

```bash
curl http://localhost:8011/health
```

Debe devolver `{"status":"ok","agents":[...]}` con los agentes de esa empresa y ningún otro. Para BabyNova es igual, con `cd companies/babynova` y el puerto `8012`.

Los dos contenedores pueden correr a la vez: usan proyectos de compose distintos (`name:`) y puertos distintos (`HOST_PORT` en `.env`).

| Comando | Para qué |
|---|---|
| `docker compose logs -f` | Ver el log |
| `docker compose restart` | Aplicar un agente nuevo, o cambios de `agent.yaml` o `.env` |
| `docker compose down` | Detener y borrar el contenedor (los datos de `bundles/` se quedan) |

> Si cambias `.env`, usa `docker compose up -d --force-recreate`; `restart` no vuelve a leer ese archivo.

---

## 2. Qué trae cada empresa

### Family Aims — `companies/family_aims`

| Agente | Canal | Endpoint |
|---|---|---|
| `family_aims_sam_text` | Texto (GoHighLevel) | `POST /agents/family_aims/sam-text` (webhook) |
| `family_aims_sam_en_voice`, `_es_voice`, `_pt_voice` | Voz | `POST /agents/<agente>/chat` |

Herramientas (plugin `bundles/_tools/desk`): reservar, buscar, editar y cancelar citas, horarios disponibles, `check-visa`, `resolve-event-link-ghl` y `calendars`. Las de agenda que usan los agentes son las de **GoHighLevel**, con sufijo `-ghl` (`/agents/<agente>/tools/book-appointment-ghl`); sus variantes de **Google Calendar** se conservan con el sufijo `-google` (`book-appointment-google`) y ningún agente las usa.

### BabyNova — `companies/babynova`

| Agente | Canal | Endpoint |
|---|---|---|
| `babynova_triage_obstetrico_text` | Texto (GoHighLevel) | `POST /agents/babynova/triage-text` |
| `babynova_surrogate_questions_text` | Texto (GoHighLevel) | `POST /agents/babynova/surrogate-questions-text` |
| `babynova_surrogate_questions_voice` | Chat / voz | `POST /agents/<agente>/chat` |

Herramientas (plugin `bundles/_tools/surrogacy`): citas con Google (`*-google`) y con GHL (`*-ghl`), `check-documentation-sur`, `surrogate-classification`.

**URL de los webhooks:** `/agents/<COMPANY>/<path del agent.yaml>`. `COMPANY` es el id de la empresa y se define en el `docker-compose.yml` (`family_aims`, `babynova`); sin `COMPANY`, el webhook queda en `/agents/<agente>/<path>`. `chat`, `reset` y `admin/reload` siguen en `/agents/<agente>/...`.

**URL de las herramientas:** `/agents/<COMPANY>/tools/<herramienta>`, una sola vez por empresa (por ejemplo `POST /agents/family_aims/tools/get-available-slots-ghl` y `POST /agents/babynova/tools/get-available-slots-ghl`). Los agentes que comparten un plugin lo montan una vez. Sin `COMPANY`, quedan en `/agents/<agente>/tools/...`.

### Endpoints que tiene todo contenedor

| Ruta | Uso |
|---|---|
| `GET /health` | Estado y lista de agentes montados |
| `POST /agents/{slug}/chat` | Conversación con un agente |
| (puerto) | Docker publica en `127.0.0.1` (solo tu máquina); ngrok llega igual. Para exponerlo, cambia el compose y define los tres tokens |
| `POST /agents/{slug}/reset` | Reinicia la sesión (pide `ADMIN_TOKEN` si está definido) |
| `POST /agents/{slug}/admin/reload` | Recarga el flujo de un agente sin reiniciar el contenedor |
| `/builtin-tools/...` | Herramientas genéricas incluidas en la imagen (`check-days-elapsed`, `callback-request`, etc.) |
| `GET /docs` | Documentación OpenAPI interactiva |

---

## 2b. Dónde se define cada cosa

| Qué | Dónde (dentro de `companies/<empresa>/bundles/`) |
|---|---|
| Flujo de un agente | `<agente>/graph.json`, `assets.json`, `knowledge.md` (los genera el compilador) |
| Ajustes de un agente: webhook, herramientas que usa, prefijo de variables | `<agente>/agent.yaml` |
| **Endpoints y herramientas de la empresa** | `_tools/<plugin>/`: cada archivo de `api/v1/endpoints/*.py` es una herramienta; se registran en `api/v1/router.py` |
| Herramientas de un solo agente | `<agente>/tools/` (misma estructura) |
| Secretos y valores por empresa | `companies/<empresa>/.env` |
| Herramientas genéricas para todas las empresas | `src/agent_backend/builtin_tools/` (van en la imagen) |

Ejemplo, Family Aims: `companies/family_aims/bundles/_tools/desk/api/v1/endpoints/book_appointment_ghl.py` define `POST /agents/<COMPANY>/tools/book-appointment-ghl`. Para una herramienta nueva: crea su archivo, regístralo en `router.py` y reinicia el contenedor.

---

## 2c. Varios calendarios (todas las empresas)

Un calendario existe cuando alguna de sus variables está en el `.env` de la empresa. No hay que tocar código. El patrón es `<PREFIJO>_<VARIABLE>_<CLAVE>`, con prefijo `FA` (Family Aims) o `BN` (BabyNova):

| Variable | Qué es |
|---|---|
| `<PREFIJO>_GHL_CALENDAR_ID_<CLAVE>` | Calendario de GoHighLevel |
| `<PREFIJO>_GOOGLE_CLIENT_ID_<CLAVE>`, `_GOOGLE_CLIENT_SECRET_<CLAVE>`, `_GOOGLE_REFRESH_TOKEN_<CLAVE>` | Credenciales de Google de ese calendario |
| `<PREFIJO>_GOOGLE_CALENDAR_ID_<CLAVE>` | Id del calendario en Google |
| `<PREFIJO>_DURATION_MINUTES_<CLAVE>` | Duración de la cita (30). También se envía a GHL como `duration`, así que debe ser una de las duraciones activas del calendario en GHL |
| `<PREFIJO>_INTERVAL_MINUTES_<CLAVE>` | Distancia mínima entre los inicios de los horarios que se ofrecen; `0` = se ofrecen todos (0) |
| `<PREFIJO>_PRE_BUFFER_MINUTES_<CLAVE>` | Tiempo libre que se exige **antes** de cada cita existente (0) |
| `<PREFIJO>_POST_BUFFER_MINUTES_<CLAVE>` | Tiempo libre que se exige **después** de cada cita existente (0; en Family Aims 10) |
| `<PREFIJO>_MIN_NOTICE_MINUTES_<CLAVE>` | Aviso mínimo antes de un horario; vacío = la regla propia de la empresa |
| `<PREFIJO>_DATE_RANGE_DAYS_<CLAVE>` | Cuántos días hacia adelante se ofrecen horarios (14; GHL acepta como máximo 31) |

**Cómo se usan en las herramientas `-ghl`:** GHL calcula los horarios libres con la configuración de su propio calendario, y nuestro código solo **descarta** los que no cumplen estos parámetros; lo que queda es lo que se ofrece al usuario. Al agendar o reagendar se valida lo mismo (aviso mínimo, rango de fechas y buffers contra las demás citas). Una cita existente bloquea su propio tiempo más sus buffers: con `POST_BUFFER_MINUTES=10`, tras una cita que termina a las 9:30 el primer horario ofrecido es a las 9:40. Configura también el mismo búfer en el calendario de GHL (Slot buffer) para que GHL lo aplique de origen; el filtro es una red de seguridad que no estorba si GHL ya lo hace.

Por ejemplo, para agregar un calendario `CONTROL` a BabyNova basta con definir sus variables:

```bash
BN_GOOGLE_CLIENT_ID_CONTROL=...
BN_GOOGLE_CLIENT_SECRET_CONTROL=...
BN_GOOGLE_REFRESH_TOKEN_CONTROL=...
BN_GOOGLE_CALENDAR_ID_CONTROL=control@group.calendar.google.com
BN_DURATION_MINUTES_CONTROL=20
```

`CONTROL` es la **clave**: el valor que las herramientas de agenda reciben en `calendar_type`, en cualquier combinación de mayúsculas. Existe siempre `FT`, tanto en Family Aims como en BabyNova. En Family Aims `FT` es el calendario **round robin** de GoHighLevel, que reparte las citas entre los asesores (ya no hay calendarios `IVF` ni `SUR`). Las variables de **Gmail** (`*_GOOGLE_CLIENT_ID_GMAIL`, `*_GMAIL_SENDER_EMAIL`...) no son calendarios: sirven para enviar correos, y `GMAIL` es una clave reservada. Tampoco lo es `*_NOTIFICATION_EMAIL`.

Verifica qué calendarios detectó el contenedor (no devuelve ids ni credenciales):

```bash
curl http://localhost:8012/agents/babynova/tools/calendars
```

**Reglas de cada calendario** (horario, almuerzo, prefijo del título y del asunto, nombre del agente y plantilla de correo en Family Aims) en `bundles/_tools/<plugin>/config/calendars.yaml`. Un calendario sin entrada usa la sección `default`, que hoy tiene **valores provisionales** (copian el horario de IVF y de FT respectivamente): revísalos antes de usarlo con pacientes. `FT` de BabyNova conserva sus reglas en código; `FT` de Family Aims las tiene en `calendars.yaml` (lunes a viernes 07:30 a 17:00, almuerzo 12:00 a 13:00) y su plantilla de correo no menciona a ningún asesor (`templates/emails/book_appointment_ft_{es,en,pt}.html`). Las reglas heredadas de `IVF` y `SUR` siguen en código pero ningún calendario las usa.

Todas las herramientas de agenda (horarios, agendar, buscar, editar, cancelar) reciben `calendar_type`. En **BabyNova es obligatorio**: una llamada sin él falla con un error que lista las claves válidas. En Family Aims, si no se envía, se usa `FT`. Un valor desconocido falla en ambas empresas.

**El agente debe saber elegir.** Las herramientas aceptan la clave, pero el prompt del agente (la definición del compilador) todavía habla solo de los calendarios originales: para que use `CONTROL`, agrégalo a la definición y recompila (sección 4).

Para un cambio en `.env` o en `calendars.yaml`: `docker compose up -d --force-recreate` / `restart`.

### Correo de notificación al equipo

`FA_NOTIFICATION_EMAIL` y `BN_NOTIFICATION_EMAIL` son **opcionales** y aceptan **uno o varios correos** separados por coma (`a@x.com, b@x.com`). Si no está vacía, cada cita agendada envía un correo adicional a esas direcciones para que el equipo empiece la gestión humana; si está vacía no se envía nada. Se envía desde la cuenta de Gmail de la empresa. Si el envío falla o una dirección es inválida, la cita igual queda agendada y el motivo viaja en `errors`.

---

### Horarios de atención de cada calendario

Hay tres niveles, de lo más general a lo más concreto:

| Qué | Dónde se define |
|---|---|
| Disponibilidad real del calendario (horas abiertas, festivos, bloqueos) | En **GoHighLevel**, en el propio calendario. Es lo primero que se aplica a los horarios libres |
| Horarios heredados de **IVF** y **SUR** (Family Aims, sin uso) | `bundles/_tools/desk/config/slots.yaml` (`policies.ivf` / `policies.sur`: ventana por día y almuerzo, y la lista de **festivos**). Las reglas para *agendar* están en código: `services/booking_ivf.py` y `booking_sur.py` |
| Horarios de **FT** (BabyNova) | `bundles/_tools/surrogacy/config/slots.yaml` (`windows`, `lunch_break` y `holidays`; el sábado admite «primera semana del mes»). Las reglas para *agendar* están en código: `services/booking.py` (`is_valid_business_hour`) |
| Horarios de **cualquier otro calendario** | `bundles/_tools/<plugin>/config/calendars.yaml`: sección `default` y una entrada por calendario (`hours`, `lunch_break`, títulos) |

Los números de día son `0 = domingo ... 6 = sábado`, la hora es de Bogotá y cada ventana es `[hora_ini, min_ini, hora_fin, min_fin]`. Para FT de BabyNova, el horario que se *ofrece* (`slots.yaml`) y el que se *acepta al agendar* (código) no son idénticos: los de agendar son más amplios.

### Herramientas de GoHighLevel compartidas (`agent_backend`)

La lógica de las cinco herramientas de agenda con GHL (`get-available-slots-ghl`, `book-appointment-ghl`, `find-appointment-ghl`, `edit-appointment-ghl`, `cancel-appointment-ghl`) está **una sola vez** en el backend (`src/agent_backend/ghl_scheduling.py`, con el cliente de GHL en `ghl_calendar.py`). Una empresa no repite código: su plugin solo monta el router con sus propias reglas, así:

```python
# bundles/_tools/<plugin>/api/v1/endpoints/ghl_scheduling.py
router = build_ghl_scheduling_router(GhlSchedulingHooks(
    prefix="BN",                                   # prefijo de sus variables
    get_settings=lambda: get_settings(),           # token, location y calendarios de la empresa
    resolve_calendar=...,                          # clave de calendario -> (ids, reglas de horario y de agenda)
    unknown_calendar_message=...,
    default_earliest=...,                          # aviso mínimo por defecto
    notify_booking=...,                            # opcional: aviso al equipo
))
```

BabyNova las tiene montadas junto a las de Google (`*-google`), y sus tres agentes con agenda (`babynova_surrogate_questions_text` y `_voice`) **ya usan las de GHL** gracias a `tool_route_suffixes: ["-ghl", "-sur"]` en su `agent.yaml` (la ruta `-ghl` se prueba primero; `-sur` sigue sirviendo a las demás herramientas). Para volver a Google basta con quitar `"-ghl"` y reiniciar. Con GHL no hay enlace RSVP (`event_link` llega vacío) y la invitación por correo al paciente ya no la envía Google Calendar: depende de las notificaciones del calendario o de los flujos de GHL. Family Aims conserva por ahora sus propias herramientas `-ghl`, con la misma configuración; moverlas al código compartido queda pendiente.

**Variables vacías = se leen de GHL.** Si `<PREFIJO>_DURATION_MINUTES_<CLAVE>`, `..._PRE_BUFFER_MINUTES_...`, `..._POST_BUFFER_MINUTES_...`, `..._MIN_NOTICE_MINUTES_...` o `..._DATE_RANGE_DAYS_...` están vacías, las herramientas `-ghl` las toman del calendario de GHL (`slotDuration`, `preBuffer`, `slotBuffer`, `allowBookingAfter`, `allowBookingFor`; se guardan 5 minutos en memoria). Un valor escrito en el `.env` siempre manda. En BabyNova ocurre así; en Family Aims las variables traen valores por defecto (buffer posterior de 10 minutos), así que no se leen de GHL.

---

## 3. Variables por empresa

Cada `env.example` ya lista las suyas. Resumen:

| Variable | Empresa | Para qué |
|---|---|---|
| `LLM_PROVIDERS` | todas | Proveedores de modelo, de mayor a menor prioridad, separados por comas: `openai`, `anthropic` (Claude), `gemini`. Uno que no esté en la lista no se usa. Vacío = solo `openai`. Ver «Varios proveedores de modelo» |
| `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY` | todas | Llave de cada proveedor (`GOOGLE_API_KEY` también sirve para Gemini). Hace falta la de **al menos un** proveedor de la lista; sin ninguna, `chat` y `admin/reload` responden 500. Un proveedor listado sin llave se omite con un aviso |
| `OPENAI_MODEL`, `ANTHROPIC_MODEL`, `GEMINI_MODEL` | todas (opcional) | Modelo de cada proveedor. Vacío = `gpt-4o-mini`, `claude-haiku-5-5`, `gemini-2.5-flash` |
| `LLM_TIMEOUT_SECONDS` | todas (opcional) | Segundos que se espera a un proveedor antes de pasar la llamada al siguiente (60) |
| `LLM_COOLDOWN_SECONDS` | todas (opcional) | Segundos que se omite un proveedor sin créditos o con llave inválida antes de volver a intentarlo (300) |
| `ADMIN_TOKEN` | todas | Protege `reset` y `admin/reload`; sin valor quedan abiertos |
| `API_TOKEN` | todas | Protege `chat`, las herramientas de la empresa y `/builtin-tools`. Se envía en `X-API-Key` (o `Authorization: Bearer`); el backend lo envía solo cuando un agente llama a sus herramientas. Sin valor quedan abiertas |
| `WEBHOOK_TOKEN` | todas | Protege los webhooks de GHL. Se envía en la cabecera `X-Webhook-Token`: agrégala como cabecera personalizada en la acción de webhook de GHL. Sin valor quedan abiertos |
| `DATABASE_URL` | todas | Postgres para las sesiones; vacío = un `sessions.db` por agente dentro de `bundles/` |
| `GHL_LOCATION_ID` | todas | Id de la location (subcuenta) de GoHighLevel de la empresa, la dueña de `GHL_TOKEN`; está en la URL de la app (`.../location/<id>/...`). La necesitan las herramientas que consultan eventos, crean citas o resuelven contactos |
| `GHL_TOKEN` | todas | **Un solo token de GoHighLevel por empresa**: webhooks, herramientas `-ghl` y herramientas genéricas |
| `GHL_LOCATION_TOKEN_ENVS` | todas (opcional) | Solo si un contenedor habla con **varias** subcuentas de GHL: `location_id:VARIABLE_TOKEN,...`. Esa location usa el token de esa variable en vez de `GHL_TOKEN` (solo herramientas genéricas). Déjala sin definir si la empresa tiene una sola cuenta |
| `FA_DEV_ALLOWED_PHONES`, `FA_DEV_ENFORCE_PHONE_WHITELIST` | Family Aims | Teléfonos que acepta el webhook de texto (E.164, separados por coma) y si se aplica la restricción |
| `FA_NOTIFICATION_EMAIL` | Family Aims (opcional) | Uno o varios correos (separados por coma) que reciben un aviso por cada cita agendada. Vacío = sin aviso. Necesita las variables de Gmail |
| `FA_*_<CLAVE>` (calendarios, ver 2c) y `FA_GOOGLE_*_GMAIL`, `FA_GMAIL_SENDER_EMAIL` | Family Aims | Calendarios (Google y GHL) y cuenta de Gmail |
| `BN_DEV_ALLOWED_PHONES`, `BN_DEV_ENFORCE_PHONE_WHITELIST` | BabyNova | Lo mismo, compartido por los dos agentes de texto |
| `BN_*_<CLAVE>` (calendarios, ver 2c; `FT` por defecto) | BabyNova | Calendarios de BabyNova, sus herramientas de agenda aceptan `calendar_type` |
| `BN_NOTIFICATION_EMAIL` | BabyNova (opcional) | Uno o varios correos (separados por coma) que reciben un aviso por cada cita agendada. Vacío = sin aviso |
| `BN_GOOGLE_*_GMAIL`, `BN_GMAIL_SENDER_EMAIL` | BabyNova | Cuenta de Gmail desde la que se envían los correos |

**Importante:** si un webhook tiene `*_DEV_ENFORCE_PHONE_WHITELIST=true` y `*_DEV_ALLOWED_PHONES` vacío, **ignora todos los mensajes**. Pon los teléfonos o desactiva la restricción a propósito.


### Varios proveedores de modelo

`LLM_PROVIDERS=openai,anthropic,gemini` hace que cada llamada al modelo vaya primero a OpenAI. Si falla (sin créditos, llave inválida, límite de uso, caída del servicio o tiempo de espera), **esa misma llamada** la responde el siguiente de la lista y la conversación sigue sin que el usuario lo note. El proveedor que falló se omite un rato para no esperarlo en cada mensaje: `LLM_COOLDOWN_SECONDS` (300) si fue por créditos o llave, 30 s si fue un límite de uso o una caída; después se vuelve a intentar el preferido. Una petición que el proveedor rechaza (`bad request`) pasa al siguiente pero no lo deja descansando. Si fallan todos, la llamada termina con un error que nombra a cada proveedor y el motivo. Cada cambio de proveedor queda en el log (`LLM provider X failed (quota); trying the next one`).

El código está en `src/agent_backend/llm/` (`config.py` lee el entorno, `providers/` tiene un adaptador por proveedor, `failover.py` el cambio automático, `factory.py` lo arma). El runtime no cambió: sigue pidiendo `complete` y `extract_structured`. La salida estructurada usa el modo de esquema JSON estricto en OpenAI, una llamada de herramienta forzada en Claude y `response_json_schema` en Gemini.
---

## Despliegue en Render

Cada empresa es un servicio web de Render (`agents-family-aims`, `agents-babynova`) construido con el mismo `Dockerfile`: el argumento `COMPANY` decide qué carpeta de `companies/` se copia dentro de la imagen (sus `bundles` y su `shared`). En local, `docker-compose` monta `./bundles` y `./shared` encima, así que sigues editando sin reconstruir; en Render no se monta nada y corre lo que se copió. El `.env` y las bases `*.db` nunca entran en la imagen.

Pasos (el detalle de cada variable está en `companies/<empresa>/env.example`):

1. **Repositorio.** Sube `backend` a GitHub (privado). Los `.env` están en `.gitignore`.
2. **Base de datos.** Crea una base Postgres en Render por empresa. Sin ella las conversaciones se pierden en cada reinicio (el disco de Render es efímero).
3. **Servicios.** En Render: *New > Blueprint* y elige el repositorio; lee `render.yaml` y crea los dos servicios. Te pide los valores marcados `sync: false` (`OPENAI_API_KEY`, `DATABASE_URL` con la conexión interna, `GHL_TOKEN`, `GHL_LOCATION_ID`). `ADMIN_TOKEN`, `API_TOKEN` y `WEBHOOK_TOKEN` los genera Render; los ves en la pestaña *Environment*.
4. **Resto de variables.** Render no lee tu `.env`. En la pestaña *Environment* de cada servicio usa **Add from .env** y pega el contenido del `.env` de esa empresa, quitando `HOST`, `PORT`, `HOST_PORT`, todo lo `NGROK_*`, `SEND_REQUEST_*`, `RENDER_BASE_URL` y `NGROK_BASE_URL` (son de tu máquina) y las `DATABASE_*` si ya pusiste `DATABASE_URL`. Revisa `*_DEV_ENFORCE_PHONE_WHITELIST` y `*_DEV_ALLOWED_PHONES`: con la restricción activa y la lista vacía el agente ignora todos los mensajes.
5. **GHL.** Cada webhook pasa a `https://<servicio>.onrender.com/agents/<empresa>/<ruta>` con la cabecera `X-Webhook-Token` (el `WEBHOOK_TOKEN` del servicio). Un workflow que llame a una herramienta o a `/builtin-tools/...` necesita la cabecera `X-API-Key` (el `API_TOKEN`).
6. **Migración.** Prueba con un contacto de prueba y pasa los workflows de una empresa a la vez; deja el servicio viejo (`ghl-tools`) unos días y apágalo al final.

Notas: Render pone `PORT` solo (el backend lo lee); el chequeo de salud es `/health`; usa plan de pago (un servicio dormido pierde el buffer de mensajes, que vive en memoria) y una sola instancia por servicio. Render pasa las variables del servicio al build, por eso `COMPANY` en el panel basta como argumento; si el primer build falla con «Set the COMPANY build argument», crea la variable `COMPANY` antes de construir.

## 3b. Desarrollo y pruebas a mano

### Chat en terminal con un agente (TUI)

`scripts/agent_chat_tui.py` es el sucesor de `compiled_agent_tui.py`: chatea con cualquier agente de `companies/<empresa>/bundles/` usando OpenAI real, y muestra turno a turno la respuesta, el estado interno y cada llamada a herramienta. Mantiene el mismo aspecto y los mismos comandos (`/help`, `/history`, `/traces`, `/state`, `/slots`, `/contact`, `/input`, `/log-llm`, `/log-http`, `/log-tools`, `/save`, `/new`, `/back`, `/exit`).

```bash
D:/trabajo/agents_refactor/backend/.venv/Scripts/python.exe D:/trabajo/agents_refactor/backend/scripts/agent_chat_tui.py
```

Opciones: `--company`, `--agent`, `--list`, `--session-file`, `--initial-slots`, `--log-llm`, `--log-http`, `--log-tools` y `--contact-name/-email/-phone/-language`. Necesita las dependencias opcionales (`pip install -e ".[tui]"`).

- **No hace falta servidor:** el agente corre en el mismo proceso y las herramientas se ejecutan contra la app de la empresa en memoria, con el `.env` de esa empresa (token de GHL, calendarios, Gmail...). **Agendar o cancelar en una prueba cambia el calendario real.**
- **Estado compartido:** la conversación vive en `<bundle>/sessions.db` (el mismo archivo que usa el backend sin Postgres), así que puedes seguirla por HTTP con el mismo `thread_id`. El historial de `/history` es un registro aparte en `backend/tui_sessions/`.
- **Descripción de las variables de entrada** (`/input`): se lee de las definiciones del compilador si existe `compiler/definitions` junto al backend (o `AGENT_DEFINITIONS_DIR`); si no, los campos `contact.*` se detectan escaneando el grafo.

### Playground en el navegador

`scripts/playground.py` es la versión web del TUI (mismo motor): una página con el chat en el centro, las **entradas** del agente a la izquierda y el **estado del grafo** a la derecha.

```bash
D:/trabajo/agents_refactor/backend/.venv/Scripts/python.exe D:/trabajo/agents_refactor/backend/scripts/playground.py --open
```

Opciones: `--company`, `--port` (8765) y `--host` (solo localhost por defecto). Es una herramienta de desarrollo: no está en la imagen de Docker y usa las mismas dependencias opcionales (`.[tui]`).

- **Conversación:** eliges el agente, quién habla primero (el contacto o el agente, como en las llamadas) y pulsas *Nueva conversación*. Mientras el agente piensa se ven las llamadas según ocurren.
- **Llamadas comprimidas:** cada llamada al LLM (azul), a una herramienta por HTTP (cian), cada cambio de estado (morado) y cada edición manual (ámbar) aparece como una línea dentro del chat. Al pulsarla se abre el detalle: del LLM, el prompt enviado, el schema pedido y la respuesta; de una herramienta, la URL, las rutas probadas, los parámetros de entrada y lo que devolvió; del estado, los slots que cambiaron en el turno. Hay filtros por tipo y *Expandir todo*.
- **Variables de entrada:** `contact.*` y las demás variables de `input_variables.yaml` (con su descripción). Antes de empezar son valores iniciales; con la conversación en curso se aplican al estado real del grafo.
- **Variables del flujo:** todos los slots con su valor actual, editables (Enter o salir del campo), con × para quitarlos y un formulario para añadir otros; los nombres se sugieren desde el grafo.
- **`contact_id` y `location_id`:** el webhook de GHL los trae en el payload (sin ellos lo ignora). En pruebas a mano hay que darlos: `contact_id` siempre (lo necesitan las herramientas de GHL y las sincronizaciones de campos del agente de voz; en el playground es el primer campo de *Entradas*, en el TUI `--contact-id`, en `/chat` va en `contact.contact_id`). `location_id` se toma de `GHL_LOCATION_ID` del `.env` de la empresa si no lo das (`--location-id` o `contact.location_id` lo reemplazan).
- **Estado:** nodo actual, thread, turnos y el JSON completo del checkpoint.
- **Guardadas:** cada conversación se guarda en `tui_sessions/playground/` (mensajes, llamadas y estado) y se reabre desde *Guardadas*; el grafo continúa desde su checkpoint. *Exportar JSON* la descarga.
- Mismas advertencias que el TUI: usa OpenAI real y las herramientas tocan los servicios reales de la empresa (GHL, Google, Gmail). Cargar el `.env` de una empresa pisa las variables de la anterior en el mismo proceso.

### Otros scripts

Dos scripts (en `backend/scripts/`) leen el `.env` de una empresa y sirven para probar sin armar peticiones a mano. Corren en **tu máquina**, no en el contenedor; las variables de la sección «Development and testing» del `.env` solo las usan ellos.

```bash
# ver qué agentes y herramientas tiene un backend en marcha
python scripts/send_request.py --company babynova --list

# llamar una herramienta (el cuerpo por defecto sale del esquema; --show-default lo imprime)
python scripts/send_request.py --company babynova --agent babynova_surrogate_questions_text \
    --tool get-available-slots-ghl --payload '{"calendar_type": "FT"}'

# levantar el backend de una empresa sin Docker y abrir el túnel de ngrok (para webhooks de GHL)
python scripts/dev_tunnel.py --company family_aims
```

| Variable | Uso |
|---|---|
| `SEND_REQUEST_DEFAULT_TARGET` | A dónde apunta `send_request` si no pasas `--target`: `local` (`python -m agent_backend`, usa `PORT`), `docker` (el contenedor, usa `HOST_PORT`), `ngrok` o `render` (vacío = `local`; un despliegue remoto nunca es el destino silencioso) |
| `HOST`, `PORT` | Dónde escucha `python -m agent_backend` sin Docker, y a dónde apunta el destino `local` |
| `RENDER_BASE_URL` | URL del despliegue en Render (destino `render`) |
| `NGROK_BASE_URL` / `NGROK_DOMAIN` | URL del túnel (destino `ngrok`) y dominio reservado que abre `dev_tunnel.py` |
| `NGROK_TOKEN` | Credencial de ngrok; `dev_tunnel.py` la registra con `ngrok config add-authtoken` |
| `NGROK_KILL_EXISTING` | `true`/`1` = cierra el túnel de ngrok ya abierto antes de abrir uno nuevo |

`dev_tunnel.py` necesita el ejecutable `ngrok` en el PATH. Si el `.env` trae `ADMIN_TOKEN`, `send_request.py` lo envía como `Bearer` (para `reset` y `admin/reload`).

**Variables del motor y de la persistencia** (que también faltaban en los `env.example`): `GLOBAL_ROUTER_RESPECT_FILTER` y `GLOBAL_ROUTER_LANGUAGE_DETECTION` (router global), `GHL_TEXT_HISTORY_MAX_DAYS` (días de inactividad antes de empezar una conversación nueva), `CLOSING_MESSAGE_SWEEP_INTERVAL_SECONDS` (cada cuánto corre el barrido del mensaje de cierre), `ECHO_ALLOWED_PHONES` (teléfonos permitidos para la herramienta `echo`) y `DATABASE_HOST`, `DATABASE_REGION`, `DATABASE_PORT`, `DATABASE_USER`, `DATABASE_PASSWORD`, `DATABASE_NAME`, `DATABASE_POOL_MAX_SIZE` (Postgres por piezas, con prioridad sobre `DATABASE_URL`).

---

## 4. Actualizar el flujo de un agente

El compilador es un proyecto aparte (`../compiler`). Desde su carpeta:

```bash
.venv/Scripts/python.exe -m agent_compiler.cli definitions/family_aims_sam_text \
    --channel-profile=async_text \
    --bundle-dir ../backend/companies/family_aims/bundles
```

Usa `--channel-profile=async_text` para agentes de texto y `--channel-profile=voice` para los de voz. El compilador solo escribe `graph.json`, `assets.json` y `knowledge.md`; nunca toca `agent.yaml`, `tools/` ni `sessions.db`. También sirve copiar a mano esos tres archivos.

Para aplicarlo sin reiniciar:

```bash
curl -X POST http://localhost:8011/agents/family_aims_sam_text/admin/reload \
     -H "Authorization: Bearer $ADMIN_TOKEN"
```

(Omite la cabecera si no definiste `ADMIN_TOKEN`.) Un error en un agente no afecta a los demás.

---

## 5. Crear una empresa nueva

1. **Copia la plantilla** y ponle el nombre de la empresa:

   ```bash
   cp -r companies/_template companies/mi_empresa
   cd companies/mi_empresa
   cp env.example .env
   ```

2. **Nombre y puerto.** En `docker-compose.yml` cambia `name: company_template` por `name: mi_empresa`, y en `.env` pon un `HOST_PORT` que no use otra empresa.

3. **Agrega los agentes.** Compila cada definición dentro de `bundles/` (sección 4). Cada agente queda en `bundles/<agente>/`.

4. **Escribe el `agent.yaml` de cada agente** (junto a su `graph.json`):

   ```yaml
   tools: mi_plugin                 # plugin compartido en bundles/_tools/mi_plugin (omítelo si usas tools/ propia)
   tool_route_suffixes: ["-ghl"]    # opcional; prueba primero book-appointment-ghl y luego book-appointment
   ghl:                             # opcional; omítelo si el agente no recibe webhook de GoHighLevel
     path: /mi-agente               # queda en /agents/<COMPANY>/mi-agente (COMPANY: ver docker-compose.yml)
     token_envs: [GHL_TOKEN]        # nombre de la variable del .env; el secreto nunca va aquí
     allowed_phones_env: MI_DEV_ALLOWED_PHONES            # opcional; sin esto: <CARPETA>_ALLOWED_PHONES
     enforce_whitelist_env: MI_DEV_ENFORCE_PHONE_WHITELIST  # opcional; sin esto: <CARPETA>_ENFORCE_PHONE_WHITELIST
     debounce_seconds: 15
   ```

   Sin `agent.yaml` el agente funciona igual, solo por `/chat` y sin herramientas.

5. **Agrega las herramientas.** Una herramienta es un `APIRouter` de FastAPI. Crea `bundles/_tools/mi_plugin/__init__.py` (o `bundles/<agente>/tools/__init__.py` si es solo de ese agente):

   ```python
   from fastapi import APIRouter
   from pydantic import BaseModel

   router = APIRouter()


   class SaludoIn(BaseModel):
       nombre: str


   @router.post("/saludar")
   def saludar(body: SaludoIn) -> dict[str, str]:
       return {"mensaje": f"Hola, {body.nombre}"}
   ```

   La variable se llama `router` y queda disponible en `/agents/<COMPANY>/tools/saludar`. Los imports dentro de la carpeta deben ser relativos (`from .servicios import ...`). Las variables de entorno que lea el plugin van en el `.env`. Una carpeta `tools/` o `_tools/<plugin>` puede ser todo un paquete con subcarpetas, como los de Family Aims y BabyNova.

6. **Levanta:**

   ```bash
   docker compose up -d --build
   curl http://localhost:<HOST_PORT>/health
   ```

### Agregar o quitar agentes después

| Cambio | Qué hacer |
|---|---|
| Actualizar el flujo de un agente existente | Copiar los 3 archivos y `admin/reload` |
| **Agregar un agente nuevo**, o cambiar `agent.yaml` o una herramienta | `docker compose restart` (las rutas del agente se montan al arrancar, y `/health` solo lista los montados) |
| Cambiar `.env` | `docker compose up -d --force-recreate` |

---

## 6. Problemas frecuentes

| Síntoma | Causa |
|---|---|
| `admin/reload` o `chat` devuelven 500 y el log dice `Missing credentials` | Falta la llave del proveedor de modelo (`OPENAI_API_KEY`, o la del primero de `LLM_PROVIDERS`) en `.env` |
| `/health` lista `"agents":[]` | `bundles/` está vacía o los agentes no tienen `graph.json` y `assets.json` |
| El webhook responde pero el agente no contesta | La lista `*_DEV_ALLOWED_PHONES` está vacía con restricción activa |
| Un agente falta en `/health` | Su `agent.yaml` es inválido (claves desconocidas o `tools:` con un plugin que no existe); revisa `docker compose logs` |
| `Port is already allocated` | Otro contenedor usa ese `HOST_PORT` |
| No conecta desde fuera del contenedor | No sobrescribas `HOST`/`PORT` del compose; ya van fijos a `0.0.0.0:8010` |

---

## 7. Qué se probó y qué no

Probado con Docker el 2026-11-08:

- Family Aims y BabyNova levantan a la vez (8011 y 8012). Cada `/health` lista solo sus 4 agentes y el reload de un agente de otra empresa devuelve 404.
- Una empresa copiada desde `_template` arranca con `"agents":[]`. Tras copiarle un agente y su plugin y reiniciar, aparece en `/health`.
- `admin/reload` de un agente montado devuelve `{"reloaded":true,...}`.
- La suite de tests sigue igual tras mover los agentes a `companies/` (914 pasan, los mismos 26 fallos heredados).

No probado: un turno de conversación real con una clave de OpenAI válida, Postgres como persistencia, ni las integraciones con GoHighLevel y Google (las credenciales las pones tú).
