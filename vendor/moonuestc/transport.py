"""HTTPS-only school transport with standard-library Cookie handling."""
import gzip
import http.cookiejar
import json
import os
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from dataclasses import dataclass
from pathlib import Path

from .errors import ToolError

ALLOWED_HOSTS = {"idas.uestc.edu.cn", "jzsz.uestc.edu.cn"}


def checked_url(url):
    u = urllib.parse.urlsplit(url)
    try:
        valid = (u.scheme == "https" and u.hostname in ALLOWED_HOSTS
                 and u.port in (None, 443) and not u.username and not u.password)
    except ValueError:
        valid = False
    if not valid:
        raise ToolError("unexpected_redirect_host", "http")
    return url


@dataclass
class Response:
    status: int
    headers: object
    body: bytes
    url: str

    @property
    def text(self):
        return self.body.decode("utf-8", "replace")

    def json(self, stage):
        try:
            return json.loads(self.body)
        except (ValueError, UnicodeError):
            raise ToolError("invalid_json", stage) from None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Transport:
    def __init__(self, user_agent, cookie_path, timeout=25):
        self.user_agent = user_agent
        self.cookie_path = Path(cookie_path)
        self.jar = http.cookiejar.LWPCookieJar(str(self.cookie_path))
        if self.cookie_path.exists():
            try:
                self.jar.load(ignore_discard=True, ignore_expires=False)
            except (OSError, ValueError, http.cookiejar.LoadError):
                raise ToolError("cookie_file_invalid", "cookies") from None
        self.opener = urllib.request.build_opener(
            NoRedirect(), urllib.request.HTTPCookieProcessor(self.jar),
            urllib.request.HTTPSHandler(context=ssl.create_default_context()))
        self.timeout = timeout

    def has_session(self):
        return any(c.name == "SESSION" and c.domain.lstrip(".") == "jzsz.uestc.edu.cn"
                   and not c.is_expired() for c in self.jar)

    def clear(self):
        self.jar.clear()

    def fingerprint(self, value):
        self.jar.set_cookie(http.cookiejar.Cookie(
            version=0, name="MULTIFACTOR_BROWSER_FINGERPRINT", value=value,
            port=None, port_specified=False, domain="idas.uestc.edu.cn",
            domain_specified=False, domain_initial_dot=False, path="/",
            path_specified=True, secure=True, expires=int(time.time()) + 31536000,
            discard=False, comment=None, comment_url=None, rest={"HttpOnly": None}))

    def save(self):
        self.cookie_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.cookie_path.with_suffix(".tmp")
        self.jar.save(str(temp), ignore_discard=True, ignore_expires=False)
        os.chmod(temp, 0o600)
        with temp.open("r+b") as stream:
            os.fsync(stream.fileno())
        os.replace(temp, self.cookie_path)

    def request(self, method, url, *, stage, headers=None, form=None, payload=None):
        checked_url(url)
        h = {"User-Agent": self.user_agent, "Accept-Language": "zh-CN,zh;q=0.9",
             "Accept-Encoding": "gzip, deflate", "Accept": "*/*"}
        h.update(headers or {})
        body = None
        if form is not None:
            body = urllib.parse.urlencode(form).encode()
            h["Content-Type"] = "application/x-www-form-urlencoded"
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
            h["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=body, method=method, headers=h)
        try:
            try:
                raw = self.opener.open(req, timeout=self.timeout)
            except urllib.error.HTTPError as error:
                raw = error
            with raw:
                status, hdrs = raw.code, raw.headers
                data = raw.read(2 * 1024 * 1024 + 1)
        except (TimeoutError, socket.timeout):
            raise ToolError("timeout", stage) from None
        except ssl.SSLError:
            raise ToolError("tls_error", stage) from None
        except urllib.error.URLError as error:
            if isinstance(error.reason, ssl.SSLError):
                reason = "tls_error"
            elif isinstance(error.reason, (TimeoutError, socket.timeout)):
                reason = "timeout"
            elif isinstance(error.reason, socket.gaierror):
                reason = "dns_error"
            else:
                reason = "network_error"
            raise ToolError(reason, stage) from None
        except (OSError, ValueError):
            raise ToolError("network_error", stage) from None
        if len(data) > 2 * 1024 * 1024:
            raise ToolError("response_too_large", stage)
        try:
            encoding = hdrs.get("Content-Encoding", "").lower()
            if encoding == "gzip":
                data = gzip.decompress(data)
            elif encoding == "deflate":
                try:
                    data = zlib.decompress(data)
                except zlib.error:
                    data = zlib.decompress(data, -zlib.MAX_WBITS)
        except (OSError, EOFError, zlib.error):
            raise ToolError("invalid_encoding", stage) from None
        return Response(status, hdrs, data, url)

    def follow(self, url, *, stage, headers=None):
        for _ in range(9):
            r = self.request("GET", url, stage=stage, headers=headers)
            if r.status in (301, 302, 303, 307, 308) and r.headers.get("Location"):
                url = checked_url(urllib.parse.urljoin(url, r.headers["Location"]))
            else:
                return r
        raise ToolError("too_many_redirects", stage)
