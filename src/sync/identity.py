from src.normalize.urls import canonicalize_url


def event_key(url: str) -> str:
    return canonicalize_url(url, force_trailing_slash=True)
