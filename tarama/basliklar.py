"""Security response headers shared by the scan, portal and admin processes (ALIG-SEC-002). Standard library only.

The application processes send these themselves because they are also reached without nginx (SSH tunnel, local smoke
test). nginx adds the same set for the public site (deploy/ansible/roles/web/templates/alig-basliklar.conf.j2) and hides
the upstream copies of the single-valued headers so the browser sees one of each. HSTS is deliberately not here: it is only
meaningful over TLS and is sent by nginx.
form/server.py is a standalone process and keeps its own copy of the plain-response values (a test pins both).
"""

# HTML responses (reports, portal, admin panel, error pages): no script, no inline style, nothing framed.
CSP_HTML = ("default-src 'none'; script-src 'none'; style-src 'self'; img-src 'self'; font-src 'self'; "
            "form-action 'self'; base-uri 'none'; frame-ancestors 'none'")
# Everything else (plain text, redirects, CSV, static files): nothing may load or embed.
CSP_DUZ = "default-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"

ORTAK = (
    ("Cache-Control", "no-store"),
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "no-referrer"),
    ("X-Frame-Options", "DENY"),
    ("Permissions-Policy", "camera=(), microphone=(), geolocation=()"),
)


def varsayilan(ctype, extra=()):
    """Default security headers for a response of this content type; a header named in `extra` replaces the default."""
    verilen = {k.lower() for k, _ in extra}
    csp = CSP_HTML if (ctype or "").lower().startswith("text/html") else CSP_DUZ
    return [(k, v) for k, v in ORTAK + (("Content-Security-Policy", csp),) if k.lower() not in verilen]
