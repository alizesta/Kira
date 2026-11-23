"""Safe web fetching for the research tools: SSRF protection, size / time / redirect limits, and outbound privacy checks.

Rules enforced in code (never by trusting the model or the page):
  * only http / https, no user:password@ in the address, only ordinary web ports;
  * localhost, *.local / *.internal / *.lan names, host names without a dot, and every private / loopback / link-local / reserved /
    multicast address are refused - for the first address AND for every redirect hop (redirects are followed by hand);
  * the DNS answer is checked before connecting and the real peer address is checked after connecting (best effort);
  * when a system proxy is configured the proxy resolves names, so only literal addresses and suspicious names are checked locally;
  * a hard cap on the downloaded bytes, the total time and the number of redirects; no cookies, no Authorization header;
  * nothing is ever saved to disk or executed: a page is only decoded to text in memory.
"""
from __future__ import annotations

import ipaddress
import queue
import re
import socket
import threading
import time
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36 KiraResearch/1"
ALLOWED_PORTS = {80, 443, 8080, 8443}
TEXT_TYPES = ("text/html", "application/xhtml", "text/plain", "text/markdown", "application/xml", "text/xml", "application/json",
              "application/rss", "application/atom", "application/pdf")
BAD_SUFFIXES = (".local", ".localhost", ".internal", ".lan", ".home", ".home.arpa", ".corp", ".intranet", ".localdomain")
CENSOR_NET = ipaddress.ip_network("10.10.34.0/24")          # the address Iranian ISPs return for blocked sites


class GuardError(Exception):
    """Message is Persian and safe to show to the user and to the model."""


def clean_url(url: str) -> str:
    """Normalise a user / model supplied address: strip spaces, add https://, drop the #fragment and any user:password@."""
    url = str(url or "").strip().strip("<>\"'")
    if not url:
        raise GuardError("آدرس خالی است.")
    if not re.match(r"^[a-z][a-z0-9+.\-]*://", url, re.I):
        if re.match(r"^[a-z][a-z0-9+.\-]*:", url, re.I) and not re.match(r"^[^/]+:\d+(/|$)", url):
            raise GuardError("فقط آدرس http/https مجاز است.")
        url = "https://" + url
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise GuardError("آدرس نامعتبر است.") from exc
    if parts.scheme.lower() not in ("http", "https"):
        raise GuardError("فقط آدرس http/https مجاز است.")
    if parts.username or parts.password or "@" in (parts.netloc or ""):
        raise GuardError("آدرس شامل نام کاربری/رمز است؛ برای امنیت رد شد.")
    if not parts.hostname:
        raise GuardError("آدرس میزبان ندارد.")
    try:
        host = parts.hostname.encode("idna").decode("ascii") if not parts.hostname.isascii() else parts.hostname
    except UnicodeError as exc:
        raise GuardError("نام سایت نامعتبر است.") from exc
    host = f"[{host}]" if ":" in host else host
    netloc = host + (f":{port}" if port else "")
    return urlunsplit((parts.scheme.lower(), netloc, parts.path or "/", parts.query, ""))


def _ip_blocked(ip: ipaddress._BaseAddress) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    # is_private alone is insufficient: shared address space (100.64.0.0/10)
    # is neither private nor globally routable, but can still reach carrier networks.
    return bool(not ip.is_global or ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved
                or ip.is_unspecified or getattr(ip, "is_site_local", False))


def _uses_proxy(url: str) -> bool:
    try:
        return bool(requests.utils.select_proxy(url, requests.utils.get_environ_proxies(url)))
    except Exception:                                            # noqa: BLE001
        return False


def check_host(url: str) -> None:
    """Raises GuardError when the address points at this PC or an internal network."""
    try:
        parts = urlsplit(url)
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError as exc:
        raise GuardError("آدرس نامعتبر است.") from exc
    host = (parts.hostname or "").lower().rstrip(".")
    if port not in ALLOWED_PORTS:
        raise GuardError(f"پورت {port} مجاز نیست (فقط پورت‌های معمول وب).")
    if host == "localhost" or host.endswith(BAD_SUFFIXES) or ("." not in host and ":" not in host):
        raise GuardError("دسترسی به localhost و شبکه‌ی داخلی ممنوع است.")
    try:
        literal = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        literal = None
    if literal is not None:
        if _ip_blocked(literal):
            raise GuardError("دسترسی به آدرس‌های محلی/خصوصی (IP داخلی) ممنوع است.")
        return
    proxy_enabled = _uses_proxy(url)
    # Resolve and validate the destination even when a system proxy is active.
    # The connected peer is the proxy, not the destination; skipping this DNS
    # check would let a URL name an internal host through an otherwise public proxy.
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise GuardError(f"نام سایت پیدا نشد ({host}).") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip in CENSOR_NET:
            if proxy_enabled:
                continue  # an external proxy may resolve the real public destination itself
            raise GuardError("این سایت در شبکه‌ی تو فیلتر است (DNS آدرس مسدودسازی داد)؛ با فیلترشکن/پروکسی امتحان کن.")
        if _ip_blocked(ip):
            raise GuardError("نام این سایت به آدرس داخلی/محلی اشاره می‌کند؛ برای امنیت رد شد (SSRF).")


def _peer_blocked(resp) -> bool:
    """Reject private peers; fail closed for direct connections when the socket cannot be inspected."""
    # With a proxy this socket belongs to the proxy, so the destination is
    # validated in check_host() before dispatch. Direct connections must also
    # validate the actual peer to catch DNS rebinding between lookup and connect.
    if _uses_proxy(resp.url):
        return False
    try:
        sock = resp.raw._connection.sock or resp.raw._fp.fp.raw._sock  # noqa: SLF001
        ip = ipaddress.ip_address(sock.getpeername()[0])
        return _ip_blocked(ip)
    except Exception:  # noqa: BLE001 - no peer evidence means a direct connection is not trusted
        return True


def _read_body_with_deadline(resp, started: float, total_timeout: float, max_bytes: int):
    """Read a streaming response without letting slow trickle traffic defeat the total deadline."""
    events: queue.Queue = queue.Queue()
    stop = threading.Event()

    def produce():
        total = 0
        try:
            for chunk in resp.iter_content(chunk_size=32768):
                if stop.is_set():
                    break
                if not chunk:
                    continue
                events.put(("chunk", chunk))
                total += len(chunk)
                if total >= max_bytes:
                    break
        except Exception as exc:  # noqa: BLE001 - propagate the transport failure to the owning thread
            events.put(("error", exc))
        finally:
            events.put(("done", None))

    reader = threading.Thread(target=produce, daemon=True, name="kira-web-body-reader")
    reader.start()
    chunks, size, truncated = [], 0, False
    try:
        while True:
            remaining = total_timeout - (time.monotonic() - started)
            if remaining <= 0:
                truncated = True
                break
            try:
                kind, value = events.get(timeout=remaining)
            except queue.Empty:
                truncated = True
                break
            if kind == "chunk":
                chunks.append(value)
                size += len(value)
                if size >= max_bytes:
                    truncated = True
                    break
            elif kind == "error":
                if not chunks:
                    raise GuardError(f"دریافت صفحه نیمه‌کاره قطع شد ({type(value).__name__}).") from value
                truncated = True
                break
            else:
                break
    finally:
        stop.set()
        try:
            resp.close()
        except Exception:
            pass
    return b"".join(chunks)[:max_bytes], truncated


class Fetched:
    __slots__ = ("url", "final_url", "status", "ctype", "body", "encoding", "truncated", "redirects", "ms")

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k))


def fetch(url: str, *, timeout: float = 15.0, max_bytes: int = 3_000_000, max_redirects: int = 4, total_timeout: float = 40.0,
          accept_lang: str = "fa,en;q=0.8") -> Fetched:
    """Download ONE page into memory (never to disk). Raises GuardError (Persian, safe to show) for any refusal or failure."""
    started = time.monotonic()
    current = clean_url(url)
    hops = []
    session = requests.Session()
    session.trust_env = True                                     # the user's proxy / VPN settings are respected
    try:
        for hop in range(max_redirects + 1):
            if time.monotonic() - started > total_timeout:
                raise GuardError("مهلت کل دریافت صفحه تمام شد.")
            check_host(current)
            # A requests.Session persists Set-Cookie values from responses. This
            # fetcher follows redirects manually and must not forward cookies from
            # one untrusted page/host to the next hop.
            session.cookies.clear()
            try:
                resp = session.get(current, headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,application/pdf,text/plain;q=0.8,*/*;q=0.2",
                                                     "Accept-Language": accept_lang, "DNT": "1"},
                                   timeout=(min(8.0, timeout), timeout), stream=True, allow_redirects=False)
                session.cookies.clear()
            except requests.Timeout as exc:
                raise GuardError("مهلت پاسخ سایت تمام شد.") from exc
            except requests.exceptions.SSLError as exc:
                raise GuardError("گواهی امنیتی (HTTPS) سایت معتبر نبود.") from exc
            except requests.RequestException as exc:
                raise GuardError(f"اتصال به سایت برقرار نشد ({type(exc).__name__}).") from exc
            if _peer_blocked(resp):
                resp.close()
                raise GuardError("اتصال به آدرس داخلی/محلی رد شد (SSRF).")
            if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get("Location"):
                resp.close()
                current = clean_url(urljoin(current, resp.headers["Location"]))
                hops.append(current)
                continue
            if resp.status_code >= 400:
                resp.close()
                hint = {401: "نیاز به ورود دارد", 402: "پولی است", 403: "دسترسی را رد کرد (ممکن است ربات‌ها را مسدود کند)", 404: "صفحه پیدا نشد",
                        410: "صفحه حذف شده", 429: "تعداد درخواست زیاد است", 451: "به دلایل قانونی در دسترس نیست"}.get(resp.status_code, "خطای سرور" if resp.status_code >= 500 else "خطا")
                raise GuardError(f"صفحه در دسترس نیست (HTTP {resp.status_code}: {hint}).")
            ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if ctype and not any(ctype.startswith(t) for t in TEXT_TYPES):
                resp.close()
                raise GuardError(f"نوع فایل ({ctype}) متن/وب/PDF نیست؛ دانلود یا اجرا نمی‌شود.")
            try:
                declared = int(resp.headers.get("Content-Length") or 0)
            except ValueError:
                declared = 0
            body, truncated = _read_body_with_deadline(resp, started, total_timeout, max_bytes)
            return Fetched(url=url, final_url=current, status=resp.status_code, ctype=ctype or "text/html", body=body,
                           encoding=resp.encoding, truncated=truncated or (declared > max_bytes), redirects=hops,
                           ms=int((time.monotonic() - started) * 1000))
        raise GuardError(f"تعداد Redirect بیشتر از {max_redirects} شد.")
    finally:
        session.close()


# ------------------------------------------------------------------ outbound privacy: nothing secret may leave in a query or URL
_PATH_RX = re.compile(r"(?:[A-Za-z]:\\[^\s\"'<>|]{2,}|\\\\[\w.$-]+\\[^\s\"'<>|]+|(?:/Users|/home)/[^\s\"'<>|]+)")
_EMAIL_RX = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]{2,}")
_LOCAL_IP_RX = re.compile(r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}|127\.\d{1,3}\.\d{1,3}\.\d{1,3})\b")
_SECRET_PARAM_RX = re.compile(r"(?i)(?:^|[?&])(?:api[_-]?key|key|token|access[_-]?token|secret|password|passwd|pwd|auth|authorization|session|sid|signature|sig|credential)=([^&]{6,})")


def _secret_values(settings: dict | None) -> list[str]:
    """Every API key Kira holds, so a model that was tricked cannot smuggle one into a search or a link."""
    out = []

    def walk(obj, depth=0):
        if depth > 4:
            return
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(v, str) and len(v.strip()) >= 12 and re.search(r"key|token|secret|password", str(k), re.I):
                    out.append(v.strip())
                else:
                    walk(v, depth + 1)
        elif isinstance(obj, (list, tuple)):
            for v in obj:
                walk(v, depth + 1)

    walk(settings or {})
    return out


def contains_secret(text: str, settings: dict | None = None) -> bool:
    from ..tools.registry import _SECRET_PATTERNS
    if any(rx.search(text or "") for rx in _SECRET_PATTERNS):
        return True
    return any(v in (text or "") for v in _secret_values(settings))


def safe_query(query: str, settings: dict | None = None, limit: int = 300) -> str:
    """The text that may be sent to a search engine: refused when it holds a key / password, private details are masked."""
    q = re.sub(r"\s+", " ", str(query or "")).strip()
    if not q:
        raise GuardError("عبارت جست‌وجو خالی است.")
    if contains_secret(q, settings):
        raise GuardError("عبارت جست‌وجو شبیه کلید API/رمز بود و به وب فرستاده نشد.")
    q = _PATH_RX.sub(" ", q)
    q = _EMAIL_RX.sub(" ", q)
    q = _LOCAL_IP_RX.sub(" ", q)
    q = re.sub(r"\s+", " ", q).strip()
    if len(q) < 2:
        raise GuardError("بعد از حذف اطلاعات خصوصی چیزی برای جست‌وجو نماند.")
    return q[:limit]


def safe_url(url: str, settings: dict | None = None) -> str:
    """clean_url + refuse any address that carries a key / token / password in its path or query."""
    cleaned = clean_url(url)
    if contains_secret(cleaned, settings) or _SECRET_PARAM_RX.search(cleaned):
        raise GuardError("آدرس شامل کلید/توکن/رمز بود و برای جلوگیری از نشت اطلاعات باز نشد.")
    if _PATH_RX.search(cleaned) or _EMAIL_RX.search(cleaned):
        raise GuardError("آدرس شامل مسیر فایل یا ایمیل خصوصی بود و باز نشد.")
    return cleaned
