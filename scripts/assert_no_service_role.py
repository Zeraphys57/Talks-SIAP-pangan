#!/usr/bin/env python3
"""Assert no service-role credential is reachable from the browser bundle.

Run from the repository root:

    python3 scripts/assert_no_service_role.py
    python3 scripts/assert_no_service_role.py --self-test

A service-role key carries BYPASSRLS. Under `web/` it would hand every visitor
the raw snapshot bodies, the per-source prices and the unblinded ground-truth
pool, so this runs on every push.

**It inspects key values, not the variable name.** The name legitimately appears
under `web/` twice — in the comment in `web/.env.example` that warns about it,
and in `web/src/lib/supabase.ts`, whose startup guard rejects such a key. Those
are the defence. The previous version of this check grepped for the string and so
failed on its own warning text, red on every commit from 2026-07-28 onward; a
check that cannot pass stops being read, and takes the real signal down with it.

`--self-test` writes known-bad fixtures into a temporary directory under `web/`
and asserts the scan trips on them, because a guard that has never been seen to
fail is not known to work.
"""

from __future__ import annotations

import base64
import json
import pathlib
import re
import shutil
import sys

ROOT = pathlib.Path("web")
SKIP = {"node_modules", ".next", ".git"}

# A three-part JWT; group 1 is the payload, which states what the key may do. An
# anon key decodes to role=anon and belongs here, so shape alone proves nothing.
JWT = re.compile(rb"eyJ[A-Za-z0-9_-]{4,}\.(eyJ[A-Za-z0-9_-]{8,})\.[A-Za-z0-9_-]{4,}")

# Newer opaque keys carry no inspectable claims, so the prefix is the whole
# signal. sb_publishable_ is browser-safe by construction and deliberately absent.
OPAQUE = re.compile(rb"sb_secret_[A-Za-z0-9_-]{8,}")

# Reading the variable from the environment inside web/ is a violation by itself:
# nothing here has any business holding it, empty value or not.
READ = re.compile(r"""env[.\[]\s*['"]?SUPABASE_SERVICE_ROLE_KEY""")


def _claims(payload: bytes) -> dict[str, object] | None:
    """Decode a JWT payload, or None if it is not one.

    A base64-shaped run that does not decode to a JSON object is simply not a
    key, so there is nothing to report and nothing worth logging. `binascii.Error`
    and `json.JSONDecodeError` are both ValueError subclasses.
    """
    padded = payload + b"=" * (-len(payload) % 4)
    try:
        decoded = json.loads(base64.urlsafe_b64decode(padded))
    except ValueError:
        return None
    return decoded if isinstance(decoded, dict) else None


def scan(root: pathlib.Path = ROOT) -> list[str]:
    findings: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or SKIP & set(path.parts):
            continue
        try:
            blob = path.read_bytes()
        except OSError:
            continue

        for match in JWT.finditer(blob):
            claims = _claims(match.group(1))
            if claims and claims.get("role") == "service_role":
                findings.append(f"{path.as_posix()}: a JWT claiming role=service_role")

        if OPAQUE.search(blob):
            findings.append(f"{path.as_posix()}: an sb_secret_... key")

        try:
            text = blob.decode("utf-8")
        except UnicodeDecodeError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if READ.search(line):
                findings.append(
                    f"{path.as_posix()}:{lineno}: reads SUPABASE_SERVICE_ROLE_KEY from the environment"
                )
    return findings


def _jwt(claims: dict[str, str]) -> str:
    def part(obj: dict[str, str]) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")

    return f"{part({'alg': 'HS256', 'typ': 'JWT'})}.{part(claims)}.ZmFrZXNpZ25hdHVyZQ"


def self_test() -> int:
    """Prove the scan trips on each violation, and not on a legitimate anon key."""
    pen = ROOT / "__guard_self_test__"
    try:
        pen.mkdir(parents=True, exist_ok=True)
        (pen / "leak_jwt.local").write_text(
            f"NEXT_PUBLIC_SUPABASE_ANON_KEY={_jwt({'iss': 'supabase', 'role': 'service_role'})}\n"
        )
        (pen / "leak_opaque.local").write_text("KEY=sb_secret_AbCdEf0123456789xyz\n")
        (pen / "leak_read.ts").write_text(
            "const k = process.env.SUPABASE_SERVICE_ROLE_KEY;\n"
        )
        # Control: a real anon key must not be reported, or the guard is useless.
        (pen / "ok_anon.local").write_text(
            f"NEXT_PUBLIC_SUPABASE_ANON_KEY={_jwt({'iss': 'supabase', 'role': 'anon'})}\n"
        )

        found = scan()
        hits = {f.split(":")[0].rsplit("/", 1)[-1] for f in found}
        expected = {"leak_jwt.local", "leak_opaque.local", "leak_read.ts"}

        missed = expected - hits
        if missed:
            print(f"::error::self-test: the scan missed {sorted(missed)}")
            return 1
        if "ok_anon.local" in hits:
            print("::error::self-test: the scan flagged a legitimate anon key")
            return 1
    finally:
        shutil.rmtree(pen, ignore_errors=True)

    print(
        f"OK: self-test - caught all {len(expected)} planted leaks, ignored the anon key"
    )
    return 0


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()

    if not ROOT.is_dir():
        print(f"::error::{ROOT}/ not found — run this from the repository root")
        return 1

    findings = scan()
    if findings:
        for finding in findings:
            print(f"::error::{finding}")
        print(
            "\nA service-role credential must never be reachable from web/. It has "
            "BYPASSRLS and would expose the raw snapshot bodies, the per-source prices "
            "and the unblinded ground-truth pool.",
            file=sys.stderr,
        )
        return 1

    print("OK: no service-role credential under web/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
