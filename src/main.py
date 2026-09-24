from __future__ import annotations

import argparse
import logging

from src.classifier.openai_compatible import OpenAICompatibleClassifier
from src.config import karakeep_credentials, load_settings, llm_credentials
from src.enrichment.pipeline import EnrichmentPipeline
from src.errors import AppError, ConfigError, LLMError
from src.http.client import HttpClient
from src.logging_setup import setup_logging
from src.sources.galicia_en_concierto.source import GaliciaEnConciertoSource
from src.storage.karakeep import KaraKeepClient
from src.sync.cookie_cleanup import CookieCleanupService
from src.sync.date_backfill import DateBackfillService
from src.sync.geo_backfill import GeoBackfillService
from src.sync.service import SyncService
from src.sync.ticket_backfill import TicketBackfillService

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.main",
        description="Descubre conciertos de Galicia y los sincroniza con KaraKeep.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Ejecuta lecturas, fichas y clasificación, pero no escribe en KaraKeep",
    )
    parser.add_argument("--scrape-only", action="store_true", help="Solo descarga las vistas mensuales")
    parser.add_argument("--no-ai", action="store_true", help="No clasifica con el LLM")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Máximo de eventos descubiertos que pasan al procesamiento detallado",
    )
    parser.add_argument(
        "--geo-backfill",
        action="store_true",
        help="Asigna listas geográficas a bookmarks del agente (dry-run salvo --apply)",
    )
    parser.add_argument(
        "--cookie-cleanup",
        action="store_true",
        help="Limpia CMP de cookies en notas/reader y refresca Cuándo/Dónde/Precio (dry-run salvo --apply)",
    )
    parser.add_argument(
        "--date-backfill",
        action="store_true",
        help="Alinea createdAt con la fecha del concierto (dry-run salvo --apply)",
    )
    parser.add_argument(
        "--ticket-backfill",
        action="store_true",
        help="Sincroniza el enlace Entradas en notas del agente (dry-run salvo --apply)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Con un backfill, escribe en KaraKeep (sin esto solo simula)",
    )
    parser.add_argument("--log-level", default="INFO", help="Nivel de log (DEBUG, INFO, WARNING, ERROR)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.limit is not None and args.limit < 0:
        setup_logging(args.log_level)
        logger.error("--limit no puede ser negativo")
        return 2
    backfill_flags = sum(
        bool(flag)
        for flag in (
            args.geo_backfill,
            args.cookie_cleanup,
            args.date_backfill,
            args.ticket_backfill,
        )
    )
    if backfill_flags > 1:
        setup_logging(args.log_level)
        logger.error(
            "Usa solo uno de --geo-backfill, --cookie-cleanup, --date-backfill o --ticket-backfill"
        )
        return 2
    setup_logging(args.log_level)
    source_http: HttpClient | None = None
    karakeep_http: HttpClient | None = None
    classifier = None
    try:
        settings = load_settings()
        if backfill_flags:
            url, key = karakeep_credentials()
            karakeep_http = HttpClient(
                timeout=settings.source.timeout,
                retries=settings.source.retries,
                backoff_seconds=settings.source.backoff_seconds,
                user_agent=settings.user_agent,
                delay=0,
            )
            repo = KaraKeepClient(
                base_url=url,
                api_key=key,
                list_names=settings.all_list_names,
                http=karakeep_http,
                default_banner_path=settings.project_root / "assets" / "concert-default.png",
            )
            dry_run = args.dry_run or not args.apply
            if not dry_run:
                logger.warning("Backfill en modo APPLY: se escribirá en KaraKeep")
            if args.geo_backfill:
                GeoBackfillService(repo=repo, settings=settings).run(dry_run=dry_run)
            elif args.cookie_cleanup:
                CookieCleanupService(repo=repo, settings=settings).run(dry_run=dry_run)
            elif args.date_backfill:
                DateBackfillService(repo=repo, settings=settings).run(dry_run=dry_run)
            else:
                TicketBackfillService(repo=repo, settings=settings).run(dry_run=dry_run)
            return 0

        source_http = HttpClient(
            timeout=settings.source.timeout,
            retries=settings.source.retries,
            backoff_seconds=settings.source.backoff_seconds,
            user_agent=settings.user_agent,
            delay=settings.source.request_delay,
        )
        source = GaliciaEnConciertoSource(
            http=source_http,
            base_url=settings.source.base_url,
            agenda_path=settings.source.agenda_path,
            months_ahead=settings.source.months_ahead,
            timezone_name=settings.timezone,
            source_name=settings.source.name,
        )
        repo = None
        if not args.scrape_only:
            url, key = karakeep_credentials()
            karakeep_http = HttpClient(
                timeout=settings.source.timeout,
                retries=settings.source.retries,
                backoff_seconds=settings.source.backoff_seconds,
                user_agent=settings.user_agent,
                delay=0,
            )
            repo = KaraKeepClient(
                base_url=url,
                api_key=key,
                list_names=settings.all_list_names,
                http=karakeep_http,
                default_banner_path=settings.project_root / "assets" / "concert-default.png",
            )
        taste = ""
        if settings.taste_path.is_file():
            taste = settings.taste_path.read_text(encoding="utf-8")

        def classifier_factory():
            nonlocal classifier
            try:
                credentials = llm_credentials()
            except ConfigError as exc:
                raise LLMError(str(exc)) from exc
            classifier = OpenAICompatibleClassifier.from_credentials(credentials)
            logger.info("Clasificador LLM: proveedor=%s", credentials.provider)
            return classifier

        service = SyncService(
            source=source,
            repo=repo,
            enrichment=EnrichmentPipeline(),
            classifier_factory=classifier_factory,
            settings=settings,
            taste=taste,
        )
        return service.run(
            dry_run=args.dry_run,
            scrape_only=args.scrape_only,
            no_ai=args.no_ai,
            limit=args.limit,
        )
    except AppError as exc:
        logger.error("%s", exc)
        return exc.exit_code
    except Exception:
        logger.exception("Error no controlado")
        return 1
    finally:
        if source_http is not None:
            source_http.close()
        if karakeep_http is not None:
            karakeep_http.close()
        if classifier is not None:
            classifier.close()


if __name__ == "__main__":
    raise SystemExit(main())
