#!/usr/bin/env python3
"""Entry point for the local live dashboard server.

    python3 serve.py             # serve at http://127.0.0.1:8787
    python3 serve.py --port 9000
"""

from __future__ import annotations

import argparse

from scraper.server import serve


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    serve(args.host, args.port)


if __name__ == "__main__":
    main()
