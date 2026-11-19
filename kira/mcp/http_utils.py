"""HTTP helpers shared by external MCP and agent clients."""

from __future__ import annotations

import urllib.error
import urllib.request


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Do not forward credentials or session headers to a redirect destination."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if fp is not None:
            try:
                fp.close()
            except OSError:
                pass
        raise urllib.error.HTTPError(
            req.full_url, code, "HTTP redirects are disabled for credential safety", headers, None
        )


def open_no_redirect(req, timeout: float):
    """Open one HTTP request without following redirects."""
    return urllib.request.build_opener(NoRedirectHandler()).open(req, timeout=timeout)
