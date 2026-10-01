import collections
import json
import re
import threading
import time
import auth
from energy_store import EnergyStore
from config import Settings
from metrics import sample
from html import escape
from urllib.parse import urlsplit
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

settings = Settings.from_env()
lock = threading.Lock()
history = collections.deque(maxlen=settings.history_samples)
latest = {}
energy_store = None

def collect():
    global latest
    while True:
        try:
            value = sample(energy_store)
            with lock:
                latest = value
                history.append(dict(timestamp=value['timestamp'], power_cpu=sum(p['watts'] for p in value['power'] if p['scope'].startswith('Package CPU')) if any(p['scope'].startswith('Package CPU') for p in value['power']) else None, cpu=value['cpu']['percent'], ram=value['memory']['percent'], rx=sum(n['rx'] for n in value['network'] if n['physical']), tx=sum(n['tx'] for n in value['network'] if n['physical']), read=sum(d['read'] for d in value['disks']), write=sum(d['write'] for d in value['disks'])))
        except Exception as e:
            print('Collection error:', e, flush=True)
        time.sleep(settings.sample_seconds)

def render_page(template):
    values = {
        'name': settings.name, 'label': settings.label, 'heading': settings.heading,
        'sample_seconds': f'{settings.sample_seconds:g}',
        'history_minutes': f'{settings.history_seconds / 60:g}',
        'initial_price': f'{settings.initial_price:g}',
        'poll_ms': str(round(settings.sample_seconds * 1000)),
    }
    # A single substitution prevents user text from being interpreted as a template.
    return re.sub(r'\{\{(\w+)\}\}', lambda match: escape(str(values[match[1]]), quote=True), template)


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(10)
    def do_GET(self):
        path = self.path.split('?', 1)[0]
        public = ('/login', '/login.js', '/style.css', '/theme.css', '/health')
        if path not in public and not auth.authenticated(self.headers.get('Cookie')):
            if path.startswith('/api/'):
                self.json_response(401, {'error': 'Accedi per continuare.'})
            else:
                self.send_response(303)
                self.send_header('Location', '/login')
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
            return
        if path == '/api/stats':
            with lock:
                body = json.dumps(dict(**latest, history=list(history))).encode()
            mime = 'application/json'
        elif path == '/health':
            with lock:
                healthy = bool(latest) and time.time() - latest['timestamp'] < 15
            self.send_response(200 if healthy else 503)
            self.end_headers()
            self.wfile.write(b'ok' if healthy else b'stale')
            return
        elif path == '/theme.css':
            body = (':root{--green:' + settings.accent + ';--blue:' + settings.secondary + '}').encode()
            mime = 'text/css'
        elif path in ('/', '/login', '/login.js', '/app.js', '/energy.js', '/style.css'):
            file = 'index.html' if path == '/' else 'login.html' if path == '/login' else path[1:]
            body = (Path(__file__).parent / 'static' / file).read_bytes()
            if file.endswith('.html'):
                body = render_page(body.decode()).encode()
            mime = {'index.html':'text/html; charset=utf-8', 'login.html':'text/html; charset=utf-8', 'login.js':'text/javascript', 'app.js':'text/javascript', 'energy.js':'text/javascript', 'style.css':'text/css'}[file]
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)
    def json_response(self, status, data, cookie=None):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        if cookie:
            self.send_header('Set-Cookie', cookie)
        self.end_headers()
        self.wfile.write(body)
    def do_POST(self):
        origin = self.headers.get('Origin')
        if origin and urlsplit(origin).netloc != self.headers.get('Host'):
            self.json_response(403, {'error': 'Richiesta non consentita.'})
            return
        if self.path == '/api/logout':
            auth.logout(self.headers.get('Cookie'))
            self.json_response(200, {'ok': True}, auth.cookie(clear=True))
            return
        if self.path == '/api/energy/settings':
            if not auth.authenticated(self.headers.get('Cookie')):
                self.json_response(401, {'error': 'Accedi per continuare.'})
                return
            try:
                length = int(self.headers.get('Content-Length', 0))
                if not 0 < length <= 1024:
                    raise ValueError('Richiesta non valida.')
                data = json.loads(self.rfile.read(length))
                if energy_store is None:
                    self.json_response(503, {'error': 'Conteggio energetico non disponibile.'})
                    return
                energy_store.set_price(data.get('price'))
            except (ValueError, AttributeError, OSError) as error:
                self.json_response(400, {'error': str(error) or 'Tariffa non valida.'})
                return
            self.json_response(200, energy_store.snapshot())
            return
        if self.path != '/api/login':
            self.json_response(404, {'error': 'Operazione non disponibile.'})
            return
        try:
            length = int(self.headers.get('Content-Length', 0))
            if not 0 < length <= 4096:
                raise ValueError()
            data = json.loads(self.rfile.read(length))
            username, password = data.get('username'), data.get('password')
            if not isinstance(username, str) or not isinstance(password, str):
                raise ValueError()
        except (ValueError, AttributeError, OSError):
            self.json_response(400, {'error': 'Richiesta non valida.'})
            return
        status, token = auth.login(username, password)
        if token:
            self.json_response(200, {'ok': True}, auth.cookie(token))
        else:
            message = {401:'Nome utente o password errati.', 429:'Troppi tentativi. Riprova tra un minuto.', 503:'Accesso non configurato.'}[status]
            self.json_response(status, {'error': message})
    def log_message(self, *args):
        pass

if __name__ == '__main__':
    if not auth.configured():
        raise SystemExit('Configure STATS_PASSWORD_HASH before starting the dashboard.')
    energy_store = EnergyStore(settings.energy_db, timezone=settings.timezone, initial_price=settings.initial_price)
    threading.Thread(target=collect, daemon=True).start()
    ThreadingHTTPServer(('0.0.0.0', 80), Handler).serve_forever()
