#!/usr/bin/env python3
"""Assert the muted text colour is not written inline.

Run from the repository root:

    python3 scripts/assert_ui_tokens.py
    python3 scripts/assert_ui_tokens.py --self-test

The contrast bug this prevents was not a typo. `text-neutral-500` was written
inline in 52 places as "the muted colour"; it resolves to #737373 in both schemes,
which is 4.74:1 on white and **4.17:1** on the #0a0a0a dark background — below the
4.5:1 WCAG AA floor for normal text. Twelve other lines in the same files already
used the correct mode-aware pair. Nothing could detect the divergence because there
was no single definition to diverge from.

`web/src/lib/ui.ts` is now that definition. This check keeps it the only one.

Deliberately narrow: it does not police spacing, borders or radii. Those repeat too,
but they all currently agree and none of them make text unreadable. A guard that
fires on harmless duplication gets disabled, and then it is not guarding anything.
"""

from __future__ import annotations

import pathlib
import re
import sys

WEB = pathlib.Path("web/src")
TOKENS = WEB / "lib" / "ui.ts"
SKIP = {"node_modules", ".next"}

RULES: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"\btext-neutral-500\b"),
        "text-neutral-500 is 4.17:1 on the dark background and fails WCAG AA; use MUTED from @/lib/ui",
    ),
    (
        # Bare text-neutral-400 (not the dark: half of a pair) is #a3a3a3 in light
        # mode too, which is 2.6:1 on white — worse than the bug above.
        re.compile(r"(?<!dark:)\btext-neutral-400\b"),
        "bare text-neutral-400 is 2.6:1 on white; use MUTED from @/lib/ui",
    ),
    (
        re.compile(r"text-neutral-600\s+dark:text-neutral-400"),
        "the muted pair belongs in @/lib/ui, not inline; use MUTED",
    ),
]


def scan(root: pathlib.Path = WEB) -> list[str]:
    findings: list[str] = []
    for path in sorted(root.rglob("*")):
        if path.suffix not in {".ts", ".tsx"} or SKIP & set(path.parts):
            continue
        if path.resolve() == TOKENS.resolve():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for pattern, why in RULES:
                if pattern.search(line):
                    findings.append(f"{path.as_posix()}:{lineno}: {why}")
    return findings


def self_test() -> int:
    """Prove each rule fires, and that ui.ts itself is exempt."""
    pen = WEB / "__token_self_test__"
    try:
        pen.mkdir(parents=True, exist_ok=True)
        (pen / "a.tsx").write_text(
            '<p className="text-sm text-neutral-500" />\n', encoding="utf-8"
        )
        (pen / "b.tsx").write_text(
            '<p className="text-neutral-400" />\n', encoding="utf-8"
        )
        (pen / "c.tsx").write_text(
            '<p className="text-neutral-600 dark:text-neutral-400" />\n',
            encoding="utf-8",
        )
        hits = {f.split(":")[0].rsplit("/", 1)[-1] for f in scan()}
        missed = {"a.tsx", "b.tsx", "c.tsx"} - hits
        if missed:
            print(f"::error::self-test: no rule fired for {sorted(missed)}")
            return 1
    finally:
        for child in pen.glob("*"):
            child.unlink()
        pen.rmdir()

    # ui.ts defines the colours and must never be reported, or the guard would
    # forbid its own definition.
    if any(f.startswith(TOKENS.as_posix()) for f in scan()):
        print("::error::self-test: the token file itself was flagged")
        return 1

    print("OK: self-test - all three rules fire, and lib/ui.ts stays exempt")
    return 0


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()

    if not WEB.is_dir():
        print(f"::error::{WEB}/ not found - run this from the repository root")
        return 1

    findings = scan()
    if findings:
        for finding in findings:
            print(f"::error::{finding}")
        print(
            f"\n{len(findings)} inline muted colour(s). MUTED in web/src/lib/ui.ts is "
            "the one definition; see the comment there for the measurements.",
            file=sys.stderr,
        )
        return 1

    print("OK: no inline muted colours outside web/src/lib/ui.ts")
    return 0


if __name__ == "__main__":
    sys.exit(main())
