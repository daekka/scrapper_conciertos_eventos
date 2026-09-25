# galicia-concert-agent

Job batch que descubre conciertos futuros en [Galicia en Concierto](https://galiciaenconcierto.com/agenda-conciertos-galicia/) y los guarda en KaraKeep. Arranca, trabaja y termina. No abre puertos ni queda residente.

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
./.venv/bin/python -m src.main --log-level DEBUG
```

`--scrape-only` solo lee las 12 vistas mensuales. `--limit N` deja el descubrimiento completo y, después de deduplicar, procesa como máximo N eventos (consulta a KaraKeep, ficha si hace falta, nota y clasificación). `--dry-run` hace esas lecturas y, si la IA está activa, la clasificación, pero no crea listas ni escribe bookmarks, tags ni listas. Una prueba corta sin modelo ni escrituras:

```bash
./.venv/bin/python -m src.main --dry-run --no-ai --limit 5
```

## Qué hace cada ejecución

1. Lee las vistas mensuales de All-in-One Event Calendar (12 meses).
2. Construye la identidad (URL canónica y `event_id:instance_id`) sin abrir la ficha.
3. Consulta KaraKeep.
4. Abre la ficha solo si el concierto es nuevo o el listado cambió en fecha, hora, recinto, título o enlace de entradas.
5. Clasifica con el LLM únicamente los conciertos nuevos (o los que quedaron pendientes).
6. Crea o actualiza el bookmark. No borra eventos que desaparecen de la fuente.
7. Mueve a `Conciertos · Pasados` los que ya terminaron.
8. Borra bookmarks cuyo fin del concierto lleve más de 7 días (`karakeep.past_retention_days`).

El perfil musical se edita en `config/taste.md`. Los secretos viven solo en `.env`. El resto de opciones está en `config/settings.yaml`. Si están las cuatro variables `AZURE_OPENAI_*`, el clasificador usa Azure OpenAI (`api-key`); si no, cae al endpoint OpenAI-compatible (`OPENAI_*`).

## Códigos de salida

| Código | Significado |
|--------|-------------|
| 0 | Éxito |
| 1 | Error no controlado |
| 2 | Configuración inválida |
| 3 | Fallo crítico al leer la agenda |
| 4 | Fallo crítico de KaraKeep |
| 5 | Fallo global del proveedor LLM |

Un concierto cuya clasificación venga mal formada se guarda como pendiente y no tumba el resto del lote.

## Cron

No está instalado. Cuando quieras programarlo, un ejemplo con `flock` (usuario `dev`):

```cron
15 7 * * * cd /opt/scripts/galicia-concert-agent && flock -n /opt/scripts/galicia-concert-agent/var/state/sync.lock /opt/scripts/galicia-concert-agent/.venv/bin/python -m src.main >> /opt/scripts/galicia-concert-agent/var/state/sync.log 2>&1
```

Crea `var/state` antes de usar esa línea. El proceso no depende de `.bashrc` ni del directorio desde el que cron arranque el shell, porque la línea hace `cd` y usa rutas absolutas.

## Tests

```bash
cd /opt/scripts/galicia-concert-agent
./.venv/bin/python -m pytest
```
