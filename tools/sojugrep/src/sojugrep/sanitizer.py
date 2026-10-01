"""Lexer and sanitizer for SQLite FTS5 queries."""

from __future__ import annotations


def sanitize_fts5_query(query: str) -> str:
    """Sanitize and normalize arbitrary user input into valid SQLite FTS5 query syntax.

    Features:
    - Balances unclosed double quotes and parentheses
    - Automatically quotes terms containing special punctuation (e.g. `c++`, `https://...`)
    - Strips invalid leading wildcards (`*word` -> `word`)
    - Prunes dangling or consecutive boolean operators (`AND`, `OR`, `NOT`)
    - Normalizes `AND NOT` to SQLite FTS5's binary `NOT` operator
    """
    query = query.strip()
    if not query:
        return ""

    tokens: list[str] = []
    i = 0
    n = len(query)

    while i < n:
        c = query[i]

        if c.isspace():
            i += 1
            continue

        if c == "(":
            tokens.append("(")
            i += 1
            continue
        if c == ")":
            tokens.append(")")
            i += 1
            continue

        if c == '"':
            start = i + 1
            i += 1
            while i < n and query[i] != '"':
                i += 1
            content = query[start:i].replace('"', '""')
            tokens.append(f'"{content}"')
            if i < n and query[i] == '"':
                i += 1
            continue

        # Regular word or operator
        start = i
        while i < n and not query[i].isspace() and query[i] not in '()"':
            i += 1
        word = query[start:i]

        upper_word = word.upper()
        if upper_word in ("AND", "OR", "NOT"):
            tokens.append(upper_word)
        else:
            word = word.lstrip("*")
            if not word:
                continue

            has_wildcard = word.endswith("*")
            core = word.rstrip("*")

            if not core:
                continue

            escaped_core = core.replace('"', '""')
            if any(ch in core for ch in ":/\\-+=^~@!#$%&?.,'"):
                if has_wildcard:
                    tokens.append(f'"{escaped_core}"*')
                else:
                    tokens.append(f'"{escaped_core}"')
            else:
                if has_wildcard:
                    tokens.append(f"{core}*")
                else:
                    tokens.append(core)

    if not tokens:
        return ""

    # Normalize operators and prune dangling syntax
    filtered: list[str] = []
    prev = ""
    for tok in tokens:
        if tok == "NOT" and prev == "AND":
            # Replace 'AND NOT' with FTS5 binary 'NOT'
            filtered[-1] = "NOT"
            prev = "NOT"
            continue
        if tok in ("AND", "OR") and prev in ("AND", "OR", "NOT", "(", ""):
            continue
        if tok == "NOT" and prev in ("NOT", ""):
            continue
        filtered.append(tok)
        prev = tok

    # Prune trailing operators
    while filtered and filtered[-1] in ("AND", "OR", "NOT", "("):
        filtered.pop()

    if not filtered:
        return ""

    # Balance unclosed parentheses
    open_count = 0
    balanced: list[str] = []
    for tok in filtered:
        if tok == "(":
            open_count += 1
            balanced.append(tok)
        elif tok == ")":
            if open_count > 0:
                open_count -= 1
                balanced.append(tok)
        else:
            balanced.append(tok)

    for _ in range(open_count):
        balanced.append(")")

    # Final check on balanced structure
    res = " ".join(balanced)
    # Check if string contains at least one non-operator term
    terms = [t for t in balanced if t not in ("AND", "OR", "NOT", "(", ")")]
    if not terms:
        return ""

    return res
