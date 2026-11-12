"""Encrypted local records and atomic approval/outbox transactions. No student credentials."""

import contextlib
import ctypes
import json
import os
import sqlite3
import threading
from pathlib import Path

from cryptography.fernet import Fernet


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def protect_key(data: bytes, *, decrypt=False) -> bytes:
    """Windows current-user DPAPI; copied databases/keys cannot unlock under another account."""
    if os.name != "nt":
        return data
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    incoming, outgoing = Blob(len(data), buffer), Blob()
    fn = ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    fn.argtypes = [
        ctypes.POINTER(Blob),
        ctypes.c_wchar_p if not decrypt else ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(Blob),
    ]
    fn.restype = wintypes.BOOL
    if not fn(ctypes.byref(incoming), None, None, None, None, 1, ctypes.byref(outgoing)):
        raise OSError("Windows DPAPI could not protect/unprotect the faculty cache key")
    try:
        return ctypes.string_at(outgoing.pbData, outgoing.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(outgoing.pbData)


class LocalStore:
    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        key_path = self.directory / "device.key"
        if not key_path.exists():
            key = protect_key(Fernet.generate_key())
            fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(key)
        self.cipher = Fernet(protect_key(key_path.read_bytes(), decrypt=True))
        self.path = self.directory / "faculty.db"
        self.lock = threading.RLock()
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, enc BLOB NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, enc BLOB NOT NULL);
                CREATE TABLE IF NOT EXISTS outbox (
                    id TEXT PRIMARY KEY, enc BLOB NOT NULL, acknowledged INTEGER NOT NULL DEFAULT 0,
                    attempts INTEGER NOT NULL DEFAULT 0, next_attempt REAL NOT NULL DEFAULT 0,
                    last_error TEXT NOT NULL DEFAULT '');
            """)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.execute("PRAGMA synchronous=FULL")
        return db

    def encode(self, data):
        return self.cipher.encrypt(canonical(data).encode())

    def decode(self, data):
        return json.loads(self.cipher.decrypt(data))

    @contextlib.contextmanager
    def transaction(self):
        with self.lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            yield db

    def kv_get(self, key, default=None):
        with self.connect() as db:
            row = db.execute("SELECT enc FROM kv WHERE key=?", (key,)).fetchone()
            return self.decode(row[0]) if row else default

    def kv_set(self, key, value, db=None):
        if db is None:
            with self.transaction() as conn:
                self.kv_set(key, value, conn)
            return
        db.execute(
            "INSERT INTO kv(key,enc) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET enc=excluded.enc",
            (key, self.encode(value)),
        )

    def sessions(self):
        with self.connect() as db:
            return [self.decode(row[0]) for row in db.execute("SELECT enc FROM sessions ORDER BY rowid DESC")]

    def session(self, sid, db=None):
        if db is None:
            with self.connect() as conn:
                return self.session(sid, conn)
        row = db.execute("SELECT enc FROM sessions WHERE id=?", (sid,)).fetchone()
        if row is None:
            raise ValueError("classroom session not found")
        return self.decode(row[0])

    def save_session(self, session, db):
        db.execute(
            "INSERT INTO sessions(id,enc) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET enc=excluded.enc",
            (session["id"], self.encode(session)),
        )

    def pending(self, due_at=None):
        with self.connect() as db:
            result = []
            for enc, next_attempt in db.execute(
                "SELECT enc,next_attempt FROM outbox WHERE acknowledged=0 ORDER BY rowid"
            ):
                if due_at is not None and next_attempt > due_at:
                    break  # An amendment must never overtake its unacknowledged predecessor.
                result.append(self.decode(enc))
            return result
