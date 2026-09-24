# AGENTS.md — galicia-concert-agent

Guía para agentes (y humanos) que mantienen este repo. Responder siempre en **español**.

## Qué es

Job **batch** que descubre conciertos futuros en [Galicia en Concierto](https://galiciaenconcierto.com/agenda-conciertos-galicia/) y los sincroniza con KaraKeep. Arranca, trabaja y termina: no abre puertos ni queda residente.

- Entrada: `python -m src.main` (siempre con el venv del proyecto).
- No borra bookmarks si un evento desaparece de la agenda.
- Secretos solo en `.env` (nunca commitear). Perfil musical en `config/taste.md`. Resto en `config/settings.yaml`.

## Reglas operativas (obligatorias)

1. **No escribir en KaraKeep sin confirmación explícita del usuario.**
   - Sync: no quitar `--dry-run` salvo que lo pida.
   - Backfills: sin `--apply` solo simulan; **no** añadir `--apply` sin confirmación.
2. **No crear commits** salvo que el usuario lo pida.
3. **No tocar ni filtrar secretos** (`.env`, `KARAKEEP_*`, `AZURE_OPENAI_*`, `OPENAI_*`).
4. **No inventar `ticket_url`**: solo URLs reales de la fuente o de la nota guardada.
5. Un solo backfill por invocación (`--geo-backfill` | `--cookie-cleanup` | `--date-backfill` | `--ticket-backfill`).
6. Tras cambios de código: `./.venv/bin/python -m pytest`.

## Entorno

```bash
cd /opt/scripts/galicia-concert-agent
# Python 3.13 en .venv
cp .env.example .env   # si hace falta; rellenar secretos
./.venv/bin/pip install -r requirements.txt
```

Variables (`.env.example`):

| Variable | Uso |
|----------|-----|
| `KARAKEEP_URL`, `KARAKEEP_API_KEY` | API KaraKeep |
| `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_VERSION`, `AZURE_OPENAI_DEPLOYMENT`, `AZURE_OPENAI_API_KEY` | Preferido si están las cuatro |
| `OPENAI_API_KEY`, `OPENAI_MODEL`, `OPENAI_BASE_URL` | Fallback OpenAI-compatible |

## Mapa del repo

| Ruta | Rol |
|------|-----|
| `src/main.py` | CLI y cableado de sync / backfills |
| `src/config.py` | Carga `settings.yaml` + credenciales |
| `src/sources/galicia_en_concierto/` | Agenda mensual + parser de ficha |
| `src/normalize/` | URLs, fingerprint, tickets, fechas/`createdAt`, geo, cookies, géneros, tags |
| `src/storage/` | Cliente KaraKeep, nota `gca`, listas, modelos de bookmark |
| `src/sync/` | Orquestación, pasados, backfills |
| `src/classifier/` | LLM (Azure u OpenAI-compatible) |
| `src/models/` | `DiscoveredEvent`, `Concert`, clasificación |
| `config/settings.yaml` | Fuente, listas, tags permitidos, timezone |
| `config/taste.md` | Preferencias musicales del clasificador |
| `assets/concert-default.png` | Banner por defecto |
| `tests/` + `tests/fixtures/` | pytest |
| `var/` | Runtime local (cache/state; no versionar secretos) |

## Pipeline de sync

Cada ejecución normal (`python -m src.main`):

1. **Discover** — vistas mensuales All-in-One Event Calendar (`source.months_ahead` en YAML; hoy **2**). Deduplica por `source_id`; omite ya pasados en listado.
2. **Identity** — URL canónica (`source_url`) y `source_id = event_id:instance_id` **sin** abrir la ficha.
3. **KaraKeep lookup** — por identidad (`source_url`); si no hay match, por `ticket_url` normalizada.
4. **Detail** — abre la ficha solo si el evento es **nuevo** o cambió el **listing fingerprint**.
5. **Classify** — LLM solo en **nuevos** (no pasados) o bookmarks **pending**. No reclasifica updates de listado salvo pendientes.
6. **Write** — crea/actualiza bookmark: nota, tags AI, lista de afinidad, geo, `createdAt`, URL de tarjeta.
7. **Past** — mueve a `📦 Conciertos · Pasados` los de listas activas cuyo fin ya pasó.

### Cuándo se pide la ficha

`listing_fingerprint` (`src/normalize/listing_fingerprint.py`): hash de título, fechas/horas, venue, city, `ticket_url`, `all_day` (no incluye descripción).

- Ficha si: no hay bookmark, o el `listing_fp` en `gca:meta` ≠ fingerprint actual.
- Sin ficha si el listado no cambió (puede solo asegurar geo / `createdAt` / URL de tarjeta).

## Semántica KaraKeep (invariantes)

### Identidad vs URL de tarjeta

| Concepto | Campo / origen | Valor |
|----------|----------------|-------|
| **Identidad** | `KnownBookmark.url` ← `gca:concert.source_url` | Ficha Galicia canónica (lookup estable) |
| **Tarjeta** | `card_url` / `url` del link en la API | **Entradas** (`ticket_url`) si existe; si no, ficha Galicia |

No confundir: el click de la tarjeta puede ir a entradas; el agente **identifica** el concierto por la URL de Galicia.

### Nota

Cuerpo visible + bloques:

- `<!-- gca:analysis-start/end -->` — texto del LLM (o “Pendiente…”)
- `<!-- gca:meta {...} -->` — `listing_fp`, `source_id`, `classification`, `pending`
- `<!-- gca:concert {...} -->` — JSON del `Concert`

Fecha visible en nota: **`dd-mm-YYYY`** (p. ej. `25-09-2026 · 22:00`).

### Título

`bookmark_title`: `dd-mm-YYYY · {artist|event_name|title}`.  
El pie de KaraKeep muestra “MMM d” (año solo si >1 año); el año en tarjeta va en el **título**.

### `createdAt`

Fecha/hora del concierto en `Europe/Madrid` (`start_time` o mediodía 12:00) → UTC ISO `.000Z`.  
KaraKeep ordena por `createdAt` **desc** → conciertos más recientes / próximos primero.

### Listas

**Afinidad** (`karakeep.lists`):

- `interested` → 🎵 Conciertos · Interesan  
- `maybe` → 🤔 Conciertos · Quizá  
- `ignored` → 🚫 Conciertos · Descartados  
- `past` → 📦 Conciertos · Pasados  

**Geo** (`karakeep.geo_lists`): exactamente una por bookmark gestionado (A Coruña, Vigo, Santiago, Ourense, Lugo, Pontevedra, Ferrol, Otras Galicia).

### Tags

- Base: `concert`, `galicia` (+ ciudad/géneros/etc. según allowlist en YAML).
- Sugeridos del LLM solo si están en `tags.allow_suggested`.
- `pending-classification` si la clasificación queda pendiente.
- Tags adjuntos como `ai`. **Tags `human` se preservan** en updates.

## CLI

```bash
./.venv/bin/python -m src.main --help
```

| Flag | Efecto |
|------|--------|
| `--dry-run` | Sync: lee/ficha/IA, **no escribe**. En backfills fuerza simulación |
| `--scrape-only` | Solo vistas mensuales; sin KaraKeep |
| `--no-ai` | Sin clasificador LLM |
| `--limit N` | Tras descubrir, procesa como máximo N eventos |
| `--log-level` | Default `INFO` |
| `--geo-backfill` | Asigna listas geo (dry-run salvo `--apply`) |
| `--cookie-cleanup` | Quita texto CMP de cookies en notas (dry-run salvo `--apply`) |
| `--date-backfill` | Alinea `createdAt` y título con fecha del concierto (dry-run salvo `--apply`) |
| `--ticket-backfill` | Alinea URL de tarjeta + enlace Entradas en nota (dry-run salvo `--apply`) |
| `--apply` | Con un backfill: **escribe** en KaraKeep |

Backfills: `dry_run = --dry-run or not --apply` → **sin `--apply` siempre simulan**.

## Comandos de prueba habituales

Siempre desde el directorio del proyecto:

```bash
cd /opt/scripts/galicia-concert-agent

# Tests unitarios / integración local
./.venv/bin/python -m pytest
./.venv/bin/python -m pytest -q --tb=short

# Sync seguro (sin escrituras)
./.venv/bin/python -m src.main --dry-run --no-ai --limit 5
./.venv/bin/python -m src.main --dry-run --limit 10
./.venv/bin/python -m src.main --scrape-only

# Backfills — primero dry-run (sin --apply)
./.venv/bin/python -m src.main --geo-backfill
./.venv/bin/python -m src.main --cookie-cleanup
./.venv/bin/python -m src.main --date-backfill
./.venv/bin/python -m src.main --ticket-backfill

# Solo tras confirmación explícita del usuario:
# ./.venv/bin/python -m src.main --date-backfill --apply
# ./.venv/bin/python -m src.main --ticket-backfill --apply
# ./.venv/bin/python -m src.main --geo-backfill --apply
# ./.venv/bin/python -m src.main --cookie-cleanup --apply
```

Sync “real” (escribe bookmarks): `./.venv/bin/python -m src.main` — no ejecutarlo sin que el usuario lo pida.

## Clasificación y pending

- Perfil: `config/taste.md`.
- Resultados: `INTERESTED` | `MAYBE` | `IGNORE` → listas interested / maybe / ignored.
- Nuevos ya pasados → lista `past` sin LLM.
- Clasificación inválida o ausente → pendiente (`pending-classification` + meta `pending`); **no** tumba el lote.
- En updates por cambio de listado se **preserva** el bloque de análisis; no se reclasifica salvo pending.
- Géneros musicales del LLM se aplican al `Concert` al clasificar.
- Texto CMP de cookies se limpia en parsers / `cookie-cleanup` (no debe reintroducirse en notas).

## Códigos de salida

| Código | Significado |
|--------|-------------|
| 0 | Éxito |
| 1 | Error no controlado |
| 2 | Config inválida, `--limit` negativo, o más de un backfill |
| 3 | Fallo crítico al leer la agenda |
| 4 | Fallo crítico de KaraKeep |
| 5 | Fallo global del proveedor LLM |

## Cron (referencia)

No está instalado por defecto. Ejemplo con `flock`:

```cron
15 7 * * * cd /opt/scripts/galicia-concert-agent && flock -n /opt/scripts/galicia-concert-agent/var/state/sync.lock /opt/scripts/galicia-concert-agent/.venv/bin/python -m src.main >> /opt/scripts/galicia-concert-agent/var/state/sync.log 2>&1
```

Crear `var/state` antes. Usar rutas absolutas y el intérprete de `.venv`.

## Dónde tocar qué

| Cambio | Sitio típico |
|--------|----------------|
| Formato fecha en nota/título / `createdAt` | `src/normalize/concert_datetime.py` |
| Enlace Entradas / URL de tarjeta | `src/normalize/tickets.py`, `ticket_backfill`, `service` |
| Listas geo | `src/normalize/geo.py`, `settings.yaml`, `geo_backfill` |
| Limpieza cookies CMP | `src/normalize/cookies.py`, parsers, `cookie_cleanup` |
| Forma de la nota | `src/storage/bookmark_note.py` |
| API KaraKeep | `src/storage/karakeep.py` |
| Orquestación sync | `src/sync/service.py` |
| Flags CLI | `src/main.py` |

## README vs este archivo

El `README.md` es la guía corta de uso. Este `AGENTS.md` es la referencia de diseño y de trabajo seguro para agentes. Si hay discrepancia (p. ej. meses de agenda), **manda `config/settings.yaml`**.
