import hashlib
import json
import threading
import time
import tempfile
from pathlib import Path
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch
from config import Settings
from http.server import ThreadingHTTPServer

salt = bytes.fromhex('11' * 16)
TEST_PASSWORD_HASH = 'pbkdf2_sha256:600000:' + salt.hex() + ':' + hashlib.pbkdf2_hmac('sha256', b'test-password', salt, 600000).hex()
import auth
import server

class LoginTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.auth_settings = patch.multiple(auth, USERNAME='test-user', PASSWORD_HASH=TEST_PASSWORD_HASH)
        cls.auth_settings.start()
        cls.addClassCleanup(cls.auth_settings.stop)
        cls.energy_directory = tempfile.TemporaryDirectory()
        server.energy_store = server.EnergyStore(Path(cls.energy_directory.name) / 'energy.sqlite3')
        cls.http = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        cls.base = 'http://127.0.0.1:' + str(cls.http.server_port)
        threading.Thread(target=cls.http.serve_forever, daemon=True).start()
    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        server.energy_store.close()
        server.energy_store = None
        cls.energy_directory.cleanup()
    def request(self, path, data=None, cookie=None, origin=None):
        headers = {}
        if cookie:
            headers['Cookie'] = cookie
        if origin:
            headers['Origin'] = origin
        if data is not None:
            headers['Content-Type'] = 'application/json'
        request = urllib.request.Request(self.base + path, data=json.dumps(data).encode() if data is not None else None, headers=headers)
        try:
            return urllib.request.urlopen(request, timeout=5)
        except urllib.error.HTTPError as error:
            return error
    def test_all_data_requires_login(self):
        for path in ('/api/stats', '/api/containers', '/api/containers/' + 'a' * 64 + '/logs'):
            self.assertEqual(self.request(path).status, 401)
        page = self.request('/')
        self.assertEqual(page.url, self.base + '/login')
        self.assertIn(b'login-form', page.read())
    def test_password_and_cookie_and_logout(self):
        self.assertEqual(self.request('/api/login', {'username':'test-user','password':'wrong'}).status, 401)
        response = self.request('/api/login', {'username':'test-user','password':'test-password'})
        self.assertEqual(response.status, 200)
        header = response.headers['Set-Cookie']
        for flag in ('HttpOnly', 'Secure', 'SameSite=Strict'):
            self.assertIn(flag, header)
        cookie = header.split(';')[0]
        self.assertEqual(self.request('/api/stats', cookie=cookie).status, 200)
        self.assertEqual(self.request('/api/logout', {}, cookie=cookie).status, 200)
        self.assertEqual(self.request('/api/stats', cookie=cookie).status, 401)
    def test_origin_and_forged_and_expired_session(self):
        self.assertEqual(self.request('/api/login', {'username':'test-user','password':'test-password'}, origin='https://other.invalid').status, 403)
        self.assertEqual(self.request('/api/stats', cookie='stats_session=forged').status, 401)
        auth.sessions['expired'] = time.time()-1
        self.assertEqual(self.request('/api/stats', cookie='stats_session=expired').status, 401)
    def test_energy_settings_are_private_validated_and_saved(self):
        self.assertEqual(self.request('/api/energy/settings', {'price':0.3}).status, 401)
        login = self.request('/api/login', {'username':'test-user','password':'test-password'})
        cookie = login.headers['Set-Cookie'].split(';')[0]
        self.assertEqual(self.request('/api/energy/settings', {'price':0.3}, cookie, 'https://other.invalid').status, 403)
        for value in (-1, '0.3', None, True, float('nan')):
            self.assertEqual(self.request('/api/energy/settings', {'price':value}, cookie).status, 400)
        response = self.request('/api/energy/settings', {'price':0.31}, cookie)
        self.assertEqual(response.status, 200)
        self.assertEqual(json.load(response)['price'], 0.31)
        self.assertEqual(server.energy_store.snapshot()['price'], 0.31)
    def test_public_brand_and_theme_and_private_dashboard(self):
        custom = Settings.from_env({'STATS_NAME': 'Custom Lab', 'STATS_ACCENT': '#112233'})
        with patch.object(server, 'settings', custom):
            response = self.request('/login')
            self.assertIn('Custom Lab', response.read().decode())
            theme = self.request('/theme.css')
            self.assertEqual(theme.status, 200)
            self.assertEqual(theme.headers['Content-Type'], 'text/css')
            self.assertIn('--green:#112233', theme.read().decode())
            login = self.request('/api/login', {'username':'test-user','password':'test-password'})
            page = self.request('/', cookie=login.headers['Set-Cookie'].split(';')[0]).read().decode()
            self.assertIn('Custom Lab', page)
            self.assertNotIn('{{', page)
            self.assertNotIn(auth.PASSWORD_HASH, page)

    def test_login_rate_limit(self):
        with auth.lock:
            previous = list(auth.attempts)
            auth.attempts.extend([time.time()] * 20)
        try:
            self.assertEqual(self.request('/api/login', {'username':'test-user','password':'test-password'}).status, 429)
        finally:
            with auth.lock:
                auth.attempts.clear()
                auth.attempts.extend(previous)

if __name__ == '__main__':
    unittest.main()
