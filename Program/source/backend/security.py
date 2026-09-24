import hashlib
import secrets

def token_digest(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    key = hashlib.scrypt(password.encode('utf-8'), salt=salt, n=32768, r=8, p=3, dklen=32, maxmem=64*1024*1024)
    return f'scrypt$32768$8$3${salt.hex()}${key.hex()}'

def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt, expected = encoded.split('$')
        if (algorithm, n, r, p) != ('scrypt', '32768', '8', '3'):
            return False
        key = hashlib.scrypt(password.encode('utf-8'), salt=bytes.fromhex(salt), n=32768, r=8, p=3, dklen=32, maxmem=64*1024*1024)
        return secrets.compare_digest(key.hex(), expected)
    except (ValueError, TypeError):
        return False
