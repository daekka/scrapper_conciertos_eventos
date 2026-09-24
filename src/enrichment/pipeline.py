from __future__ import annotations

from src.models.discovered import Concert


class EnrichmentPipeline:
    """Punto de extensión. La v1 no llama a proveedores externos."""

    def __init__(self, enrichers: list | None = None) -> None:
        self.enrichers = list(enrichers or [])

    def run(self, concert: Concert) -> Concert:
        current = concert
        for enricher in self.enrichers:
            current = enricher.enrich(current)
        return current
