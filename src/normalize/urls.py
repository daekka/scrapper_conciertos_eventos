from __future__ import annotations

from urllib.parse import parse_qsl, urlsplit, urlunsplit

_TRACKING_EXACT = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "igshid",
    "ref",
    "instance_id",
}


def _drop_param(name: str, *, drop_instance: bool) -> bool:
    lowered = name.lower()
    if lowered == "instance_id":
        return drop_instance
    return lowered in _TRACKING_EXACT or lowered.startswith("utm_")


def canonicalize_url(
    url: str,
    *,
    force_trailing_slash: bool = False,
    drop_instance: bool = True,
) -> str:
    raw = url.strip()
    parts = urlsplit(raw)
    scheme = (parts.scheme or "https").lower()
    netloc = parts.netloc.lower()
    path = parts.path or "/"
    if force_trailing_slash and not path.endswith("/"):
        path = path + "/"
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not _drop_param(key, drop_instance=drop_instance)
    ]
    from urllib.parse import urlencode

    return urlunsplit((scheme, netloc, path, urlencode(query), ""))
