from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .store import StateStore

INDEXNOW_ENDPOINT = "https://api.indexnow.org/indexnow"
_KEY = re.compile(r"^[A-Za-z0-9_-]{8,128}$")


def validate_key(key: str) -> None:
    if not _KEY.fullmatch(key):
        raise ValueError("IndexNow key must contain 8-128 letters, numbers, hyphens or underscores")


def verify_key_file(base_url: str, key: str, timeout: int = 15) -> None:
    location = f"{base_url.rstrip('/')}/{key}.txt"
    try:
        with urlopen(location, timeout=timeout) as response:
            body = response.read().decode("utf-8").strip()
            if response.status != 200 or body != key:
                raise RuntimeError(f"IndexNow key file validation failed at {location}")
    except (HTTPError, URLError) as exc:
        raise RuntimeError(f"Cannot verify IndexNow key file at {location}: {exc}") from exc


def notify_indexnow(
    *,
    state_path: Path,
    base_url: str,
    key: str,
    dry_run: bool = False,
    skip_key_check: bool = False,
) -> dict[str, object]:
    validate_key(key)
    base_url = base_url.rstrip("/")
    host = urlparse(base_url).netloc
    if not host:
        raise ValueError("base URL must be absolute")
    with StateStore(state_path) as store:
        urls = store.pending_urls()
        if not urls:
            return {"submitted": 0, "status": "nothing_pending"}
        if dry_run:
            return {"submitted": 0, "pending": len(urls), "status": "dry_run", "urls": urls}
        if not skip_key_check:
            verify_key_file(base_url, key)

        submitted = 0
        statuses: list[int] = []
        for start in range(0, len(urls), 10_000):
            chunk = urls[start : start + 10_000]
            payload = json.dumps(
                {
                    "host": host,
                    "key": key,
                    "keyLocation": f"{base_url}/{key}.txt",
                    "urlList": chunk,
                }
            ).encode("utf-8")
            request = Request(
                INDEXNOW_ENDPOINT,
                data=payload,
                headers={"Content-Type": "application/json; charset=utf-8"},
                method="POST",
            )
            try:
                with urlopen(request, timeout=30) as response:
                    body = response.read().decode("utf-8", errors="replace")
                    status = response.status
            except HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                raise RuntimeError(f"IndexNow rejected a batch with HTTP {exc.code}: {body}") from exc
            except URLError as exc:
                raise RuntimeError(f"IndexNow request failed: {exc}") from exc
            if status not in (200, 202):
                raise RuntimeError(f"Unexpected IndexNow response: HTTP {status} {body}")
            store.mark_submitted(chunk, status, body)
            submitted += len(chunk)
            statuses.append(status)
        return {"submitted": submitted, "status": "received", "http_statuses": statuses}

