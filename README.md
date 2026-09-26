# galicia-concert-agent

Job batch con dos pipelines hacia KaraKeep:

1. **Conciertos Galicia** — [Galicia en Concierto](https://galiciaenconcierto.com/agenda-conciertos-galicia/) → listas `Conciertos · …` (clasificación LLM).
2. **Ocio Coruña** — RSS [ocio/cultura coruna.gal](https://www.coruna.gal/web/es/rss/ociocultura) → lista `Ocio Coruña` (tipología en tags). Los concertos municipales no se mezclan con las listas de Galicia.

Arranca, trabaja y termina. No abre puertos ni queda residente.

## Requisitos

- Python 3.13 en el virtualenv del proyecto: `/opt/scripts/galicia-concert-agent/.venv`
- Variables en `.env` (copia de `.env.example`). No subas `.env` al repositorio.

```bash
cd /opt/scripts/galicia-concert-agent
cp .env.example .env
./.venv/bin/pip install -r requirements.txt
```

## Ejecución

Siempre desde el directorio del proyecto, con el intérprete del virtualenv:

```bash
cd /opt/scripts/galicia-concert-agent
./.venv/bin/python -m src.main
./.venv/bin/python -m src.main --dry-run
./.venv/bin/python -m src.main --scrape-only
./.venv/bin/python -m src.main --no-ai
./.venv/bin/python -m src.main --limit 10
./.venv/bin/python -m src.main --pipeline coruna --dry-run --limit 5
./.venv/bin/python -m src.main --pipeline coruna --scrape-only
./.venv/bin/python -m src.main --log-level DEBUG
```

`--scrape-only` solo lee la fuente (agenda o RSS). `--limit N` deja el descubrimiento completo y, después de deduplicar, procesa como máximo N eventos. `--dry-run` hace esas lecturas (y clasificación en Galicia si la IA está activa), pero no escribe en KaraKeep. Prueba corta Galicia:

```bash
./.venv/bin/python -m src.main --dry-run --no-ai --limit 5
```

## Qué hace cada ejecución (Galicia)

1. Lee las vistas mensuales de All-in-One Event Calendar.
2. Construye la identidad (URL canónica) sin abrir la ficha.
3. Consulta KaraKeep.
4. Abre la ficha solo si el concierto es nuevo o el listado cambió.
5. Clasifica con el LLM los conciertos nuevos (o pendientes).
6. Crea o actualiza el bookmark. No borra eventos que desaparecen de la fuente.
7. Mueve a `Conciertos · Pasados` los que ya terminaron.
8. Borra bookmarks cuyo fin lleve más de `karakeep.past_retention_days` (default 7).

## Qué hace cada ejecución (Coruña)

1. Lee el RSS de ocio/cultura.
2. Abre la ficha coruna.gal si el evento es nuevo o cambió el listado RSS.
3. Asigna a la lista `Ocio Coruña` (tags de tipología: cine, teatro, …).
4. Past / purge con la misma retención, en listas `Ocio Coruña · …` (aisladas).

El perfil musical (solo Galicia) se edita en `config/taste.md`. Los secretos viven solo en `.env`. El resto está en `config/settings.yaml` (`pipelines.coruna` para Coruña).

## Códigos de salida

| Código | Significado |
|--------|-------------|
| 0 | Éxito |
| 1 | Error no controlado |
| 2 | Configuración inválida |
| 3 | Fallo crítico al leer la agenda / RSS |
| 4 | Fallo crítico de KaraKeep |
| 5 | Fallo global del proveedor LLM |

## Cron

El job nocturno (p. ej. 02:00) debe ejecutar `python -m src.main` **sin** `--pipeline`: eso corre Galicia y después Coruña, con logs en `logs/cron.log`. Ejemplo:

```cron
0 2 * * * cd /opt/scripts/galicia-concert-agent && flock -n /opt/scripts/galicia-concert-agent/var/state/sync.lock /opt/scripts/galicia-concert-agent/.venv/bin/python -m src.main >> /opt/scripts/galicia-concert-agent/var/state/sync.log 2>&1
```

Crea `var/state` antes. Usa rutas absolutas y el intérprete de `.venv`.

## Tests

```bash
cd /opt/scripts/galicia-concert-agent
./.venv/bin/python -m pytest
```
