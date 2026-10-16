"""Serve the local website (build/site) on a port, with `Cache-Control: no-cache`.

The pages are rebuilt in place (`./mf site`); without the header a browser may keep showing an
old page (heuristic caching of python's http.server). no-cache = revalidate (304 if unchanged).

Usage: python -m mapforge.site.serve [--port 8080] [--directory build/site]
"""

from __future__ import annotations

import argparse
import functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer


class NoCacheHandler(SimpleHTTPRequestHandler):
    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--directory", default="build/site")
    args = ap.parse_args(argv)
    handler = functools.partial(NoCacheHandler, directory=args.directory)
    ThreadingHTTPServer(("", args.port), handler).serve_forever()


if __name__ == "__main__":
    main()
