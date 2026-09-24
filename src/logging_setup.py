import logging
import re


class _SecretFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        cleaned = re.sub(r"(Bearer\s+)\S+", r"\1***", message)
        cleaned = re.sub(r"(api[_-]?key[=:\s]+)\S+", r"\1***", cleaned, flags=re.I)
        if cleaned != message:
            record.msg = cleaned
            record.args = ()
        return True


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logging.getLogger().addFilter(_SecretFilter())
