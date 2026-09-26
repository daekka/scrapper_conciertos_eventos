# AGENTS.md — galicia-concert-agent

Guía para agentes (y humanos) que mantienen este repo. Responder siempre en **español**.

## Qué es

Job **batch** con dos pipelines:

1. **Conciertos Galicia** — descubre conciertos futuros en [Galicia en Concierto](https://galiciaenconcierto.com/agenda-conciertos-galicia/) y los sincroniza con KaraKeep (listas `Conciertos · …`, clasificación LLM).
2. **Ocio Coruña** — RSS de [ocio/cultura coruna.gal](https://www.coruna.gal/web/es/rss/ociocultura) → lista única `Ocio Coruña` (+ `Ocio Coruña · Pasados`). Tipología (cine, teatro, concertos…) en **tags**, no en listas. Sin LLM. Los concertos municipales no van a `Conciertos · …`.

Arranca, trabaja y termina: no abre puertos ni queda residente.

- Entrada: `python -m src.main` (siempre con el venv del proyecto). Pipeline Coruña: `--pipeline coruna`.
- No borra bookmarks si un evento desaparece de la fuente.
- Sí borra bookmarks cuyo fin lleve más de `past_retention_days` (por defecto 7).
- Secretos solo en `.env` (nunca commitear). Perfil musical (solo Galicia) en `config/taste.md`. Resto en `config/settings.yaml`.

## Reglas operativas (obligatorias)

1. **No escribir en KaraKeep sin confirmación explícita del usuario.**
   - Sync: no quitar `--dry-run` salvo que lo pida.
   - Backfills: sin `--apply` solo simulan; **no** añadir `--apply` sin confirmación.
2. **No crear commits** salvo que el usuario lo pida.
3. **No tocar ni filtrar secretos** (`.env`, `KARAKEEP_*`, `AZURE_OPENAI_*`, `OPENAI_*`).
4. **No inventar `ticket_url`**: solo URLs reales de la fuente o de la nota guardada.
5. Un solo backfill por invocación (`--geo-backfill` | `--cookie-cleanup` | `--date-backfill` | `--ticket-backfill`). Los backfills son solo del pipeline Galicia.
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
| `src/main.py` | CLI y cableado de sync / backfills (`--pipeline`) |
| `src/config.py` | Carga `settings.yaml` + `pipelines.coruna` + credenciales |
| `src/sources/galicia_en_concierto/` | Agenda mensual + parser de ficha |
| `src/sources/coruna_gal/` | RSS Coruña + tipologías + parser ficha |
| `src/normalize/` | URLs, fingerprint, tickets, fechas/`createdAt`, geo, cookies, géneros, tags |
| `src/storage/` | Cliente KaraKeep, nota `gca`, listas, modelos de bookmark |
| `src/sync/` | Orquestación Galicia (`service`) y Coruña (`tipo_service`), past, backfills |
| `src/classifier/` | LLM (solo pipeline Galicia) |
| `src/models/` | `DiscoveredEvent`, `Concert`, clasificación |
| `config/settings.yaml` | Fuente Galicia, pipeline Coruña, listas, tags, timezone |
| `config/taste.md` | Preferencias musicales del clasificador |
| `assets/concert-default.png` | Banner por defecto |
| `tests/` + `tests/fixtures/` | pytest |
| `var/` | Runtime local (cache/state; no versionar secretos) |
| `logs/cron.log` | Log del cron; retención automática **3 días** (`TimedRotatingFileHandler` + poda al arrancar) |

## Pipeline de sync (Galicia)

Cada ejecución normal (`python -m src.main`):

1. **Discover** — vistas mensuales All-in-One Event Calendar (`source.months_ahead` en YAML). Deduplica por `source_id`; omite ya pasados en listado.
2. **Identity** — URL canónica (`source_url`) y `source_id = event_id:instance_id` **sin** abrir la ficha.
3. **KaraKeep lookup** — por identidad (`source_url`); si no hay match, por `ticket_url` normalizada.
4. **Detail** — abre la ficha solo si el evento es **nuevo** o cambió el **listing fingerprint**.
5. **Classify** — LLM solo en **nuevos** (no pasados) o bookmarks **pending**. No reclasifica updates de listado salvo pendientes.
6. **Write** — crea/actualiza bookmark: nota, tags AI, lista de afinidad, geo, `createdAt`, URL de tarjeta.
7. **Past** — mueve a `Conciertos · Pasados` los de listas activas cuyo fin ya pasó (y quita listas geo).
8. **Purge** — borra bookmarks cuyo fin lleve más de `past_retention_days` (default 7).

## Pipeline de sync (Coruña)

`python -m src.main --pipeline coruna`:

1. **Discover** — RSS `pipelines.coruna.feed_url`.
2. **Identity** — URL canónica de la ficha coruna.gal (`source=coruna_gal`). **Sin** lookup por `ticket_url`.
3. **Detail** — ficha si nuevo o cambió el listing fingerprint (título + keywords RSS).
4. **Tipología** — `infer_tipos` → tags (`cine`, `teatro`, `concertos`, …); lista KaraKeep siempre `Ocio Coruña` (o `Pasados`).
5. **Write** — nota adaptada (sin géneros musicales), tags `ocio`/`acoruna`/tipología, `createdAt`, tarjeta = ficha Coruña.
6. **Past / Purge** — misma semántica de fechas; `Ocio Coruña · Pasados` y retención `pipelines.coruna.past_retention_days`. Índice KaraKeep **solo** listas Ocio Coruña.

### Cuándo se pide la ficha

`listing_fingerprint` (`src/normalize/listing_fingerprint.py`): hash de título, fechas/horas, venue, city, `ticket_url`, `all_day` (no incluye descripción). En Coruña también keywords del RSS si hay.

- Ficha si: no hay bookmark, o el `listing_fp` en `gca:meta` ≠ fingerprint actual.
- Sin ficha si el listado no cambió (puede solo asegurar geo / `createdAt` / URL de tarjeta / lista tipología).

## Semántica KaraKeep (invariantes)

### Identidad vs URL de tarjeta

| Concepto | Campo / origen | Valor |
|----------|----------------|-------|
| **Identidad** | `KnownBookmark.url` ← `gca:concert.source_url` | Ficha fuente canónica (lookup estable) |
| **Tarjeta (Galicia)** | `card_url` | **Entradas** (`ticket_url`) si existe; si no, ficha Galicia |
| **Tarjeta (Coruña)** | `card_url` | Siempre ficha coruna.gal |

No confundir: el click de la tarjeta Galicia puede ir a entradas; el agente **identifica** por la URL de la fuente. Coruña no mezcla tickets con Galicia.

### Nota

Cuerpo visible + bloques:

- `<!-- gca:analysis-start/end -->` — LLM (Galicia) o tipología (Coruña)
- `<!-- gca:meta {...} -->` — `listing_fp`, `source_id`, `classification`, `pending`
- `<!-- gca:concert {...} -->` — JSON del `Concert` (`source` distingue dominio)

Fecha visible en nota: **`dd-mm-YYYY`** (p. ej. `25-09-2026 · 22:00`).

### Título

`bookmark_title`: `{L|M|X|J|V|S|D} dd-mm-YYYY · HH:MM · {artist|event_name|title}` (sin `HH:MM` si no hay hora o es `all_day`).
El pie de KaraKeep muestra “MMM d” (año solo si >1 año); el año en tarjeta va en el **título**.

### `createdAt`

Fecha/hora del evento en `Europe/Madrid` (`start_time` o mediodía 12:00) → UTC ISO `.000Z`.
KaraKeep ordena por `createdAt` **desc** → eventos más recientes / próximos primero.

### Listas Galicia

**Afinidad** (`karakeep.lists`):

- `interested` → Conciertos · Interesan
- `maybe` → Conciertos · Quizá
- `ignored` → Conciertos · Descartados
- `past` → Conciertos · Pasados (cuarentena hasta `past_retention_days`; después se borran; **sin** lista geo)

**Geo** (`karakeep.geo_lists`): exactamente una por bookmark en listas activas. Los de `past` no llevan geo.

### Listas Coruña

- Activa: `ocio` → `Ocio Coruña` (todos los eventos).
- `past` → `Ocio Coruña · Pasados`.
- Tipología solo en **tags** (`cine`, `teatro`, `concertos`, …).

### Tags

**Galicia:** base `concert`, `galicia` (+ ciudad/géneros/etc. según allowlist).

**Coruña:** base `ocio`, `acoruna` + tipologías (`cine`, `concertos`, …). Sin tag `concert`.

- `pending-classification` solo en pipeline Galicia.
- Tags adjuntos como `ai`. **Tags `human` se preservan** en updates.

## CLI

```bash
./.venv/bin/python -m src.main --help
```

| Flag | Efecto |
|------|--------|
| `--pipeline` | `all` (default: Galicia + Coruña), `galicia_en_concierto` o `coruna` |
| `--dry-run` | Sync: lee/ficha/IA, **no escribe**. En backfills fuerza simulación |
| `--scrape-only` | Solo fuente; sin KaraKeep |
| `--no-ai` | Sin clasificador LLM (Galicia) |
| `--limit N` | Tras descubrir, procesa como máximo N eventos |
| `--log-level` | Default `INFO` |
| `--geo-backfill` / `--cookie-cleanup` / `--date-backfill` / `--ticket-backfill` | Solo Galicia; dry-run salvo `--apply` |
| `--apply` | Con un backfill: **escribe** en KaraKeep |

Backfills: `dry_run = --dry-run or not --apply` → **sin `--apply` siempre simulan**.

## Comandos de prueba habituales

Siempre desde el directorio del proyecto:

```bash
cd /opt/scripts/galicia-concert-agent

# Tests
./.venv/bin/python -m pytest
./.venv/bin/python -m pytest -q --tb=short

# Sync Galicia seguro (sin escrituras)
./.venv/bin/python -m src.main --dry-run --no-ai --limit 5
./.venv/bin/python -m src.main --dry-run --limit 10
./.venv/bin/python -m src.main --scrape-only

# Sync Coruña seguro (sin escrituras)
./.venv/bin/python -m src.main --pipeline coruna --dry-run --limit 5
./.venv/bin/python -m src.main --pipeline coruna --scrape-only

# Backfills Galicia — primero dry-run (sin --apply)
./.venv/bin/python -m src.main --geo-backfill
./.venv/bin/python -m src.main --cookie-cleanup
./.venv/bin/python -m src.main --date-backfill
./.venv/bin/python -m src.main --ticket-backfill

# Solo tras confirmación explícita del usuario:
# ./.venv/bin/python -m src.main --date-backfill --apply
# ./.venv/bin/python -m src.main --pipeline coruna
```

Sync “real” Galicia: `./.venv/bin/python -m src.main` — no ejecutarlo sin que el usuario lo pida.
Sync “real” Coruña: `./.venv/bin/python -m src.main --pipeline coruna` — igual.

## Clasificación y pending (Galicia)

- Perfil: `config/taste.md`.
- Resultados: `INTERESTED` | `MAYBE` | `IGNORE` → listas interested / maybe / ignored.
- Nuevos ya pasados → lista `past` sin LLM.
- Nuevos caducados (> `past_retention_days`) → no se crean.
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
| 3 | Fallo crítico al leer la agenda / RSS |
| 4 | Fallo crítico de KaraKeep |
| 5 | Fallo global del proveedor LLM |

## Cron (referencia)

No está instalado por defecto. El job nocturno típico (p. ej. 02:00) ejecuta `python -m src.main` **sin** `--pipeline` → corre **Galicia y luego Coruña**, y escribe en `logs/cron.log`. Ejemplo con `flock`:

```cron
0 2 * * * cd /opt/scripts/galicia-concert-agent && flock -n /opt/scripts/galicia-concert-agent/var/state/sync.lock /opt/scripts/galicia-concert-agent/.venv/bin/python -m src.main >> /opt/scripts/galicia-concert-agent/var/state/sync.log 2>&1
```

Solo un pipeline:

```cron
# Solo Galicia
0 2 * * * .../.venv/bin/python -m src.main --pipeline galicia_en_concierto ...
# Solo Coruña
30 2 * * * .../.venv/bin/python -m src.main --pipeline coruna ...
```

Crear `var/state` antes. Usar rutas absolutas y el intérprete de `.venv`.

El proceso escribe en `logs/cron.log` cuando stdout no es TTY y el fichero es escribible (típico del cron como root). Retiene **3 días** de calendario: poda líneas viejas al arrancar y rota a medianoche (`backupCount=2`). El `>>` del cron es opcional; si se deja, no duplica líneas porque en no-TTY no se usa StreamHandler.

## Dónde tocar qué

| Cambio | Sitio típico |
|--------|----------------|
| Formato fecha en nota/título / `createdAt` | `src/normalize/concert_datetime.py` |
| Enlace Entradas / URL de tarjeta | `src/normalize/tickets.py`, `ticket_backfill`, `service` |
| Listas geo | `src/normalize/geo.py`, `settings.yaml`, `geo_backfill` |
| Limpieza cookies CMP | `src/normalize/cookies.py`, parsers, `cookie_cleanup` |
| Forma de la nota | `src/storage/bookmark_note.py` (`build_note` / `build_coruna_note`) |
| API KaraKeep | `src/storage/karakeep.py` |
| Orquestación sync Galicia | `src/sync/service.py` |
| Orquestación sync Coruña | `src/sync/tipo_service.py`, `src/sources/coruna_gal/` |
| Tipologías Coruña | `src/sources/coruna_gal/tipos.py`, `pipelines.coruna.lists` |
| Pasados / retención / purga | `src/sync/past.py`, `past_retention_days` en `settings.yaml`, `_purge_stale` |
| Flags CLI | `src/main.py` |

## README vs este archivo

El `README.md` es la guía corta de uso. Este `AGENTS.md` es la referencia de diseño y de trabajo seguro para agentes. Si hay discrepancia (p. ej. meses de agenda), **manda `config/settings.yaml`**.
