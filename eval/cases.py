"""Eval set: 28 small PRs, 18 with seeded bugs (19 labelled issues) and 10 clean.

Each case has a `base` file (already in the repo) and `added` code appended by the PR.
Trailing `#@:<category>` markers in `added` label the buggy lines; they are stripped
before the diff is generated, so reviewers never see them.

`script` holds hand-authored LLM responses used by the offline "scripted" eval mode. They
are NOT recordings of a real model: they include deliberate misses, false positives, an
out-of-diff location and an invalid finding so the aggregator's grounding can be
exercised. They measure the pipeline, not model quality (see the README).
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

BASE = '''"""Service helpers."""
import sqlite3

DB = "app.db"


def connect():
    return sqlite3.connect(DB)
'''

_MARK = re.compile(r"\s*#@:(\w+)\s*$")


@dataclass
class Scripted:
    """One scripted LLM finding. `marker` indexes the case's labelled lines (None = line 1)."""

    category: str
    severity: str
    message: str
    marker: int | None = 0
    line: int | None = None  # absolute override (out-of-diff / invalid tests)
    file: str | None = None
    suggestion: str | None = None


@dataclass
class Case:
    name: str
    added: str
    script: list[Scripted] = field(default_factory=list)
    base: str = BASE

    @property
    def path(self) -> str:
        return f"app/{self.name}.py"

    @property
    def first_added_line(self) -> int:
        return len(self.base.splitlines()) + 3

    def build(self) -> tuple[str, dict[str, str], list[dict]]:
        """Returns (diff_text, {path: new_content}, expected_issues)."""
        added_lines, labels = [], []
        for text in self.added.splitlines():
            m = _MARK.search(text)
            added_lines.append(_MARK.sub("", text) if m else text)
            if m:
                labels.append((len(added_lines), m.group(1)))
        base_lines = self.base.splitlines()
        new_lines = base_lines + [""] + [""] + added_lines
        diff = "".join(
            difflib.unified_diff(
                [line + "\n" for line in base_lines],
                [line + "\n" for line in new_lines],
                fromfile=f"a/{self.path}",
                tofile=f"b/{self.path}",
            )
        )
        diff = f"diff --git a/{self.path} b/{self.path}\n" + diff
        offset = len(base_lines) + 2
        expected = [
            {"file": self.path, "line": offset + n, "category": cat} for n, cat in labels
        ]
        return diff, {self.path: "\n".join(new_lines) + "\n"}, expected


CASES: list[Case] = [
    # ------------------------------------------------------------------ seeded bugs
    Case("sql_injection", '''def find_user(name):
    conn = connect()
    cur = conn.execute(f"SELECT * FROM users WHERE name = '{name}'")  #@:security
    return cur.fetchall()
''', [Scripted("security", "high", "User input is interpolated into the SQL string (injection).",
               suggestion="Use a parameterised query: execute('... WHERE name = ?', (name,)).")]),
    Case("off_by_one", '''def window_sum(items, n):
    total = 0
    for i in range(len(items) - n, len(items) + 1):  #@:bug
        total += items[i]
    return total
''', [Scripted("bug", "high", "range upper bound is len(items)+1, so items[len(items)] raises IndexError.")]),
    Case("missing_await", '''async def fetch_row(uid):
    return {"id": uid, "name": "x"}


async def load_name(uid):
    row = fetch_row(uid)  #@:bug
    return row["name"]
''', [Scripted("bug", "high", "fetch_row is a coroutine and is not awaited; row is a coroutine object."),
      Scripted("bug", "medium", "Speculative issue far from the change.", line=9999)]),
    Case("n_plus_one", '''def order_totals(order_ids):
    totals = {}
    conn = connect()
    for oid in order_ids:
        rows = conn.execute("SELECT price FROM items WHERE order_id = ?", (oid,)).fetchall()  #@:performance
        totals[oid] = sum(r[0] for r in rows)
    return totals
''', [Scripted("performance", "medium", "One query per order id (N+1). Fetch all items with a single IN (...) query.")]),
    Case("resource_leak", '''def read_config(path):
    f = open(path)  #@:bug
    data = f.read()
    return data.strip()
'''),
    Case("race_condition", '''_cache = {}


def get_or_create(key, factory):
    if key not in _cache:  #@:bug
        _cache[key] = factory()
    return _cache[key]
'''),
    Case("hardcoded_secret", '''DB_PASSWORD = "hunter2-prod"  #@:security


def dsn():
    return f"postgres://app:{DB_PASSWORD}@db/app"
''', [Scripted("security", "high", "Hard-coded credential committed to source; load it from the environment.")]),
    Case("unsafe_yaml", '''import yaml


def parse(text):
    return yaml.load(text, Loader=yaml.Loader)  #@:security
''', [Scripted("security", "high", "yaml.load with the full Loader can construct arbitrary objects; use yaml.safe_load.")]),
    Case("shell_injection", '''import subprocess


def ping(host):
    return subprocess.run(f"ping -c 1 {host}", shell=True, capture_output=True)  #@:security
''', [Scripted("security", "critical", "shell=True with an interpolated host allows command injection.", marker=0)]),
    Case("mutable_default", '''def add_tag(tag, tags=[]):  #@:bug
    tags.append(tag)
    return tags
''', [Scripted("bug", "medium", "Mutable default argument is shared across calls.")]),
    Case("bare_except", '''def safe_int(x):
    try:
        return int(x)
    except:  #@:bug
        return 0
''', [Scripted("bug", "medium", "Bare except also swallows KeyboardInterrupt/SystemExit; catch ValueError.")]),
    Case("undefined_name", '''def total_price(items):
    return sum(i.price for i in items) * tax_rate  #@:bug
''', [Scripted("bug", "high", "tax_rate is never defined; this raises NameError at runtime.")]),
    Case("blocking_sleep", '''import time


async def poll(check):
    while not check():
        time.sleep(1)  #@:performance
''', [Scripted("performance", "medium", "time.sleep blocks the event loop inside a coroutine; use asyncio.sleep.")]),
    Case("loop_append", '''def names(users):
    out = []
    for u in users:
        if u.active:
            out.append(u.name.upper())  #@:performance
    return out
'''),
    Case("weak_hash", '''import hashlib


def hash_password(pw):
    return hashlib.md5(pw.encode()).hexdigest()  #@:security
''', [Scripted("security", "high", "MD5 is unsuitable for password hashing; use argon2/bcrypt/scrypt.")]),
    Case("division_by_zero", '''def average(values):
    return sum(values) / len(values)  #@:bug
''', [Scripted("bug", "medium", "ZeroDivisionError for an empty list."),
      Scripted("bug", "low", "Malformed finding (line 0) from a sloppy model.", line=0)]),
    Case("pickle_loads", '''import pickle


def load_session(blob):
    return pickle.loads(blob)  #@:security
''', [Scripted("security", "high", "Deserialising untrusted bytes with pickle allows code execution.")]),
    Case("multi_issue", '''def search(term, results=[]):  #@:bug
    conn = connect()
    rows = conn.execute("SELECT * FROM docs WHERE body LIKE '%" + term + "%'").fetchall()  #@:security
    results.extend(rows)
    return results
''', [Scripted("security", "high", "String-concatenated SQL with user input (injection).", marker=1)]),
    # ------------------------------------------------------------------ clean PRs
    Case("clean_paginate", '''def paginate(items, page, size=20):
    start = (page - 1) * size
    return items[start:start + size]
'''),
    Case("clean_dataclass", '''from dataclasses import dataclass


@dataclass(frozen=True)
class Money:
    cents: int
    currency: str = "USD"

    def add(self, other):
        if other.currency != self.currency:
            raise ValueError("currency mismatch")
        return Money(self.cents + other.cents, self.currency)
'''),
    Case("clean_async", '''import asyncio


async def fetch_one(uid):
    await asyncio.sleep(0)
    return {"id": uid}


async def fetch_many(uids):
    return await asyncio.gather(*(fetch_one(u) for u in uids))
''', [Scripted("style", "low", "fetch_one/fetch_many names are vague.", marker=None)]),
    Case("clean_param_sql", '''def get_user(name):
    conn = connect()
    return conn.execute("SELECT * FROM users WHERE name = ?", (name,)).fetchone()
'''),
    Case("clean_context_manager", '''def read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read().strip()
'''),
    Case("clean_retry", '''import functools


def retry(times):
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            last = None
            for _ in range(times):
                try:
                    return fn(*args, **kwargs)
                except OSError as e:
                    last = e
            raise last
        return wrapper
    return deco
''', [Scripted("bug", "medium", "retry(0) raises None; last is never set.", marker=None)]),
    Case("clean_safe_divide", '''def safe_average(values):
    if not values:
        return 0.0
    return sum(values) / len(values)
'''),
    Case("clean_safe_yaml", '''import yaml


def parse(text):
    return yaml.safe_load(text)
'''),
    Case("clean_salted_hash", '''import hashlib
import os


def hash_password(pw):
    salt = os.urandom(16)
    return salt, hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 200_000)
'''),
    Case("clean_subprocess_list", '''import subprocess


def git_head():
    return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout
'''),
]
