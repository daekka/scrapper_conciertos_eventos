class AppError(Exception):
    """Error de aplicación con código de salida."""

    exit_code = 1


class ConfigError(AppError):
    exit_code = 2


class ScrapeError(AppError):
    exit_code = 3


class KaraKeepError(AppError):
    exit_code = 4


class LLMError(AppError):
    exit_code = 5


class ClassificationInvalid(AppError):
    """Respuesta de LLM inválida. No aborta el lote."""

    exit_code = 0
