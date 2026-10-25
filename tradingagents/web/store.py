"""Persistent desk data; all connections use explicit transactions."""

import re
import secrets
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from werkzeug.security import generate_password_hash


@contextmanager
def connect(path):
    db = sqlite3.connect(str(path), timeout=20)
    db.row_factory = sqlite3.Row
    try:
        with db:
            yield db
    finally:
        db.close()


def initialize(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with connect(path) as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY, password_hash TEXT NOT NULL,
                version TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS attempts (ip TEXT, created REAL);
            CREATE INDEX IF NOT EXISTS attempts_ip ON attempts(ip, created);
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY, ticker TEXT NOT NULL, trade_date TEXT NOT NULL,
                quick_model TEXT NOT NULL, deep_model TEXT NOT NULL, rounds INTEGER NOT NULL,
                creator TEXT NOT NULL, created TEXT NOT NULL, finished TEXT,
                status TEXT NOT NULL, signal TEXT, reports TEXT, error TEXT
            );
        """)
    Path(path).chmod(0o600)


def provision_admins(path, accounts):
    if len(accounts) != 2:
        raise ValueError("Provide exactly two admin accounts.")
    normalized = [(name.strip().lower(), password) for name, password in accounts]
    if len({name for name, _ in normalized}) != 2:
        raise ValueError("Admin usernames must be different.")
    for name, password in normalized:
        if not re.fullmatch(r"[a-z0-9][a-z0-9@._+-]{1,79}", name):
            raise ValueError("Use 2–80 characters for usernames: letters, numbers, @ . _ + -")
        if len(password) < 12:
            raise ValueError("Use passwords of at least 12 characters.")
    hashes = [
        (name, generate_password_hash(password), secrets.token_hex(16))
        for name, password in normalized
    ]
    with connect(path) as db:
        db.execute("DELETE FROM users")
        db.executemany("INSERT INTO users VALUES (?, ?, ?)", hashes)
