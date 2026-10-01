"""Set dashboard username/password without writing the password to shell history."""
import argparse
import getpass
import hashlib
from pathlib import Path
import secrets

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--username', default='admin')
    parser.add_argument('--directory', default=str(Path(__file__).parent))
    args = parser.parse_args()
    if not args.username or len(args.username) > 128 or any(c in args.username for c in '\r\n=#'):
        raise SystemExit('Nome utente non valido.')
    password = getpass.getpass('Nuova password (almeno 12 caratteri): ')
    if len(password) < 12 or len(password) > 256:
        raise SystemExit('La password deve contenere da 12 a 256 caratteri.')
    if password != getpass.getpass('Ripeti la password: '):
        raise SystemExit('Le password non coincidono.')
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 600000).hex()
    folder = Path(args.directory)
    path = folder / '.env'
    text = path.read_text() if path.exists() else ''
    lines = [line for line in text.splitlines() if not line.startswith(('STATS_USERNAME=', 'STATS_PASSWORD_HASH='))]
    lines += ['STATS_USERNAME=' + args.username, 'STATS_PASSWORD_HASH=pbkdf2_sha256:600000:' + salt.hex() + ':' + digest]
    path.write_text('\n'.join(lines) + '\n')
    path.chmod(0o600)
    initial = folder / 'accesso.txt'
    if initial.exists():
        initial.unlink()
    print('Credenziali aggiornate. Esegui docker compose up -d per applicarle.')
