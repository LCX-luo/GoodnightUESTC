"""Choose a working school route using public GET probes; never replay a POST."""
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import os
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

SCHOOL_HOSTS = frozenset({'idas.uestc.edu.cn', 'jzsz.uestc.edu.cn'})


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class NetworkPolicy:
    def __init__(self):
        self.lock = threading.Lock()
        self.cache = {}
        self.pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix='school-route')

    def proxies(self):
        return {key: value for key, value in urllib.request.getproxies().items() if key in ('http', 'https')}

    def forced(self):
        mode = os.environ.get('UESTC_NETWORK_MODE', 'auto').lower()
        if os.environ.get('UESTC_USE_SYSTEM_PROXY') == '1':
            mode = 'system'
        return mode if mode in ('direct', 'system') else None

    def opener(self, route, *handlers):
        proxy = urllib.request.ProxyHandler(self.proxies() if route == 'system' else {})
        return urllib.request.build_opener(proxy, *handlers)

    def probe(self, host, route):
        url = 'https://' + host + ('/authserver/login' if host == 'idas.uestc.edu.cn' else '/')
        opener = self.opener(route, NoRedirect(), urllib.request.HTTPSHandler(context=ssl.create_default_context()))
        req = urllib.request.Request(url, headers={'User-Agent': 'GoodnightUESTC/0.2 RouteCheck'})
        try:
            with opener.open(req, timeout=2.5) as response:
                return 200 <= response.status < 500 and response.status != 407
        except urllib.error.HTTPError as error:
            code = error.code
            error.close()
            return 200 <= code < 500 and code != 407
        except Exception:
            return False

    def select(self, host):
        if host not in SCHOOL_HOSTS:
            raise ValueError('Unsupported school host')
        forced = self.forced()
        if forced:
            return forced
        proxies = self.proxies()
        if not proxies:
            return 'direct'
        signature = tuple(sorted(proxies.items()))
        key = (host, signature)
        with self.lock:
            saved = self.cache.get(key)
            if saved and time.monotonic()-saved[1] < 120:
                return saved[0]
        # Give fast direct access a short head start. Never wait for a losing probe.
        direct = self.pool.submit(self.probe, host, 'direct')
        done, _ = wait([direct], timeout=.15)
        if done and direct.result():
            route = 'direct'
        else:
            proxy = self.pool.submit(self.probe, host, 'system')
            candidates = {direct: 'direct', proxy: 'system'}
            route = None
            deadline = time.monotonic()+2.7
            while candidates and time.monotonic() < deadline:
                finished, _ = wait(candidates, timeout=max(0, deadline-time.monotonic()), return_when=FIRST_COMPLETED)
                if not finished:
                    break
                for future in finished:
                    mode = candidates.pop(future)
                    if future.result():
                        route = mode
                        break
                if route:
                    break
            for future in candidates:
                future.cancel()
            route = route or 'direct'
        with self.lock:
            self.cache[key] = (route, time.monotonic())
        return route

    def remember(self, host, route):
        key = (host, tuple(sorted(self.proxies().items())))
        with self.lock:
            self.cache[key] = (route, time.monotonic())

    def browser_options(self, host):
        if self.select(host) == 'direct':
            return {'args': ['--no-proxy-server']}
        proxy = self.proxies().get('https') or self.proxies().get('http')
        if not proxy:
            return {}
        parsed = urllib.parse.urlsplit(proxy if '://' in proxy else 'http://'+proxy)
        authority = parsed.hostname or ''
        if ':' in authority:
            authority = '['+authority+']'
        if parsed.port:
            authority += ':'+str(parsed.port)
        value = {'server': parsed.scheme+'://'+authority}
        if parsed.username:
            value['username'] = urllib.parse.unquote(parsed.username)
        if parsed.password:
            value['password'] = urllib.parse.unquote(parsed.password)
        return {'proxy': value}


NETWORK = NetworkPolicy()


class RoutingOpener:
    def __init__(self, cookie_jar, policy=None):
        self.jar = cookie_jar
        self.policy = policy or NETWORK
        self.openers = {}

    def open(self, request, timeout):
        host = urllib.parse.urlsplit(request.full_url).hostname
        route = self.policy.select(host)
        try:
            return self._open(route, request, timeout)
        except (urllib.error.URLError, OSError):
            # HTTPError is a response, not a failed route. Never retry attendance.
            import sys
            if isinstance(sys.exc_info()[1], urllib.error.HTTPError):
                raise
            if request.get_method() not in ('GET', 'HEAD') or self.policy.forced():
                raise
            alternate = 'system' if route == 'direct' else 'direct'
            if alternate == 'system' and not self.policy.proxies():
                raise
            response = self._open(alternate, request, timeout)
            self.policy.remember(host, alternate)
            return response

    def _open(self, route, request, timeout):
        # Proxy settings may change while the app remains open.
        signature = tuple(sorted(self.policy.proxies().items())) if route == 'system' else ()
        key = (route, signature)
        if key not in self.openers:
            self.openers[key] = self.policy.opener(route, NoRedirect(),
                urllib.request.HTTPCookieProcessor(self.jar),
                urllib.request.HTTPSHandler(context=ssl.create_default_context()))
        return self.openers[key].open(request, timeout=timeout)
