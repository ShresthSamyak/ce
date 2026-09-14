"""Fetch one completed session's HTML report from the local API.

The API also saves reports under ``reports/``. This helper is useful for
regenerating or copying a report after the browser has been closed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from uuid import UUID

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAX_REPORT_BYTES = 8 * 1024 * 1024


def local_base_url(value: str) -> str:
    """Require plain HTTP to the local loopback interface only."""
    parsed = urlparse(value)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise argparse.ArgumentTypeError("API URL must be local HTTP, such as http://127.0.0.1:8000")
    return value.rstrip("/")


def session_uuid(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("session ID must be a UUID") from exc


def fetch_report(session_id: UUID, base_url: str) -> bytes:
    """Read bounded HTML from the local report endpoint."""
    request = Request(
        f"{base_url}/api/session/{session_id}/report",
        headers={"Accept": "text/html"},
    )
    with urlopen(request, timeout=15) as response:
        content_type = response.headers.get_content_type()
        if content_type != "text/html":
            raise ValueError(f"Expected HTML report, received {content_type}")
        content = response.read(MAX_REPORT_BYTES + 1)
        if len(content) > MAX_REPORT_BYTES:
            raise ValueError("Report exceeds the 8 MiB download limit")
        return content


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session_id", type=session_uuid, help="UUID shown on the assessment page")
    parser.add_argument(
        "--api",
        type=local_base_url,
        default="http://127.0.0.1:8000",
        help="loopback API URL (default: http://127.0.0.1:8000)",
    )
    args = parser.parse_args()
    try:
        content = fetch_report(args.session_id, args.api)
        output_dir = PROJECT_ROOT / "reports"
        output_dir.mkdir(exist_ok=True)
        target = output_dir / f"session_{args.session_id}.html"
        target.write_bytes(content)
    except (HTTPError, URLError, OSError, ValueError) as exc:
        print(f"Could not generate report: {exc}", file=sys.stderr)
        return 1
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
