import http.cookiejar
import urllib.error
import urllib.request
import unittest
from unittest.mock import patch
from network import NetworkPolicy, RoutingOpener


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.policy = NetworkPolicy()
        self.forced = patch.object(self.policy, 'forced', return_value=None)
        self.forced.start()

    def tearDown(self):
        self.forced.stop()
        self.policy.pool.shutdown(wait=True, cancel_futures=True)

    def test_no_proxy_needs_no_probe(self):
        with patch.object(self.policy, 'proxies', return_value={}), patch.object(self.policy, 'probe') as probe:
            self.assertEqual(self.policy.select('jzsz.uestc.edu.cn'), 'direct')
            probe.assert_not_called()

    def test_bad_system_proxy_does_not_delay_healthy_direct_connection(self):
        with patch.object(self.policy, 'proxies', return_value={'https': 'http://invalid.local:9'}), patch.object(self.policy, 'probe', side_effect=lambda host, route: route == 'direct') as probe:
            self.assertEqual(self.policy.select('jzsz.uestc.edu.cn'), 'direct')
            self.assertEqual(probe.call_count, 1)
            self.assertEqual(self.policy.select('jzsz.uestc.edu.cn'), 'direct')
            self.assertEqual(probe.call_count, 1)

    def test_working_proxy_is_used_when_direct_is_unavailable(self):
        with patch.object(self.policy, 'proxies', return_value={'https': 'http://proxy.local:8080'}), patch.object(self.policy, 'probe', side_effect=lambda host, route: route == 'system'):
            self.assertEqual(self.policy.select('idas.uestc.edu.cn'), 'system')

    def test_changing_proxy_settings_invalidates_cached_route(self):
        setting = {'https': 'http://proxy-one.local:8080'}
        with patch.object(self.policy, 'proxies', side_effect=lambda: setting.copy()), patch.object(self.policy, 'probe', side_effect=lambda host, route: route == 'system') as probe:
            self.assertEqual(self.policy.select('jzsz.uestc.edu.cn'), 'system')
            count = probe.call_count
            setting['https'] = 'http://proxy-two.local:8080'
            self.assertEqual(self.policy.select('jzsz.uestc.edu.cn'), 'system')
            self.assertGreater(probe.call_count, count)

    def test_read_failure_can_switch_routes(self):
        router = RoutingOpener(http.cookiejar.CookieJar(), self.policy)
        with patch.object(self.policy, 'select', return_value='direct'), patch.object(self.policy, 'proxies', return_value={'https': 'http://proxy.local:8080'}), patch.object(self.policy, 'remember') as remember, patch.object(router, '_open', side_effect=[urllib.error.URLError('synthetic offline'), 'response']) as call:
            self.assertEqual(router.open(urllib.request.Request('https://jzsz.uestc.edu.cn/'), timeout=2), 'response')
            self.assertEqual(call.call_count, 2)
            remember.assert_called_once_with('jzsz.uestc.edu.cn', 'system')

    def test_post_failure_is_never_retried_on_another_route(self):
        router = RoutingOpener(http.cookiejar.CookieJar(), self.policy)
        request = urllib.request.Request('https://jzsz.uestc.edu.cn/daily-checkin/api/student-checkin-record/checkin', data=b'{}')
        with patch.object(self.policy, 'select', return_value='direct'), patch.object(router, '_open', side_effect=urllib.error.URLError('synthetic timeout')) as call:
            with self.assertRaises(urllib.error.URLError):
                router.open(request, timeout=2)
            call.assert_called_once()
