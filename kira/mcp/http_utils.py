"""HTTP helpers shared by external MCP and agent clients."""

from __future__ import annotations

import urllib.request


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Do not forward credentials or session headers to a redirect destination."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def open_no_redirect(req, timeout: float):
    """Open one HTTP request without following redirects."""
    return urllib.request.build_opener(NoRedirectHandler()).open(req, timeout=timeout)
