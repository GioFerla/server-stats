"""Native login with hashed password, bounded sessions and login throttling."""
import collections
import hashlib
import hmac
import os
import secrets
import threading
import time
from http.cookies import SimpleCookie, CookieError

USERNAME = os.getenv('STATS_USERNAME', 'admin')
PASSWORD_HASH = os.getenv('STATS_PASSWORD_HASH', '')
SESSION_SECONDS = 12 * 3600
COOKIE = 'stats_session'
lock = threading.Lock()
sessions = {}
attempts = collections.deque()

def configured():
    try:
        algorithm, iterations, salt, digest = PASSWORD_HASH.split(':')
        return algorithm == 'pbkdf2_sha256' and int(iterations) >= 600000 and len(bytes.fromhex(salt)) >= 16 and len(bytes.fromhex(digest)) == 32
    except (ValueError, TypeError):
        return False

def authenticated(header):
    try:
        cookies = SimpleCookie()
        cookies.load(header or '')
        token = cookies[COOKIE].value
    except (KeyError, ValueError, CookieError):
        return False
    with lock:
        expiry = sessions.get(token, 0)
        if expiry <= time.time():
            sessions.pop(token, None)
            return False
    return True

def login(username, password):
    if not configured():
        return 503, None
    now = time.time()
    with lock:
        while attempts and now - attempts[0] > 60:
            attempts.popleft()
        if len(attempts) >= 20:
            return 429, None
        attempts.append(now)
    _, iterations, salt, digest = PASSWORD_HASH.split(':')
    candidate = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), int(iterations)).hex()
    valid = hmac.compare_digest(candidate, digest) & hmac.compare_digest(username.encode(), USERNAME.encode())
    if not valid:
        return 401, None
    token = secrets.token_urlsafe(32)
    with lock:
        for key in list(sessions):
            if sessions[key] <= now:
                del sessions[key]
        if len(sessions) >= 1000:
            del sessions[next(iter(sessions))]
        sessions[token] = now + SESSION_SECONDS
    return 200, token

def logout(header):
    try:
        cookies = SimpleCookie()
        cookies.load(header or '')
        with lock:
            sessions.pop(cookies[COOKIE].value, None)
    except (KeyError, ValueError, CookieError):
        pass

def cookie(token='', clear=False):
    return COOKIE + '=' + token + '; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=' + ('0' if clear else str(SESSION_SECONDS))
