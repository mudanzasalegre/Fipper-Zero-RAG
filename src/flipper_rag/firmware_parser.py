"""Conservative, zero-execution firmware source parser (v0.7).

Extracts top-level C function definitions/declarations, macros, includes, type
names and call-site *candidates*. This is NOT a compiler or preprocessor: macros,
conditional compilation, overloaded C++, and indirect calls need a real build
for exact resolution. Ambiguous links are deliberately left unresolved.
"""
from __future__ import annotations

import ast
import bisect
import csv
import hashlib
import io
import re
from dataclasses import dataclass, field

_C_NAME = re.compile(r"^[A-Za-z_]\w*$")
_CALL = re.compile(r"\b([A-Za-z_]\w*)\s*\(")
_INCLUDE = re.compile(r'^\s*#\s*include\s*[<"]([^>"\n]{1,160})[>"]', re.M)
_DEFINE = re.compile(r'^\s*#\s*define\s+([A-Za-z_]\w*)(\s*\([^\n]*?\))?', re.M)
_TYPEDEF = re.compile(r"\btypedef\s+(?:struct|enum|union)\s*(?:[A-Za-z_]\w*)?\s*\{.*?\}\s*([A-Za-z_]\w*)\s*;", re.S)
_NAMED_TYPE = re.compile(r"\b(struct|enum|union)\s+([A-Za-z_]\w*)\s*\{")
_SKIP_CALLS = {"if", "for", "while", "switch", "return", "sizeof", "_Alignof", "alignof", "defined", "_Static_assert", "typeof", "__typeof__", "do", "catch"}


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()[:24]


@dataclass(frozen=True)
class Symbol:
    id: str
    name: str
    kind: str
    path: str
    signature: str
    line: int
    end_line: int
    linkage: str = 'global'
    evidence: str = 'heuristic'

    def as_dict(self) -> dict:
        return vars(self).copy()


@dataclass(frozen=True)
class Reference:
    source: str
    target_name: str
    relation: str
    path: str
    line: int
    target: str | None = None
    resolution: str = 'unresolved'
    evidence: str = 'heuristic'

    def as_dict(self) -> dict:
        return vars(self).copy()


@dataclass
class ParsedFile:
    path: str
    symbols: list[Symbol] = field(default_factory=list)
    references: list[Reference] = field(default_factory=list)
    app_id: str | None = None
    app_properties: dict = field(default_factory=dict)


def _line_offsets(text: str) -> list[int]:
    return [-1] + [m.start() for m in re.finditer(r'\n', text)]


def _line_of(offset: int, offsets: list[int]) -> int:
    return bisect.bisect_left(offsets, offset)


def _mask_comments_and_literals(text: str) -> str:
    """Preserve byte/character indices and newlines while removing literal noise."""
    a = list(text)
    state = 'normal'
    i = 0
    while i < len(text):
        ch = text[i]
        two = text[i:i+2]
        if state == 'normal':
            if two == '//':
                a[i] = a[i+1] = ' '; i += 2; state = 'line'; continue
            if two == '/*':
                a[i] = a[i+1] = ' '; i += 2; state = 'block'; continue
            if ch in ('"', "'"):
                state = ch; a[i] = ' '; i += 1; continue
        elif state == 'line':
            if ch == '\n': state = 'normal'
            else: a[i] = ' '
            i += 1; continue
        elif state == 'block':
            if two == '*/':
                a[i] = a[i+1] = ' '; i += 2; state = 'normal'; continue
            if ch != '\n': a[i] = ' '
            i += 1; continue
        else:
            if ch == '\\' and i+1 < len(text):
                a[i] = ' '
                if text[i+1] != '\n': a[i+1] = ' '
                i += 2; continue
            if ch == state: state = 'normal'
            if ch != '\n': a[i] = ' '
            i += 1; continue
        i += 1
    return ''.join(a)


def _without_preprocessor(masked: str) -> str:
    out = list(masked)
    offset = 0
    continued = False
    for line in masked.splitlines(keepends=True):
        preprocessor = continued or line.lstrip().startswith('#')
        if preprocessor:
            for i, ch in enumerate(line):
                if ch != '\n': out[offset+i] = ' '
        continued = preprocessor and line.rstrip().endswith('\\')
        offset += len(line)
    return ''.join(out)


def _make_symbol(path: str, name: str, kind: str, signature: str, line: int, end: int, linkage: str='global', evidence: str='heuristic') -> Symbol:
    sid = _digest('\x00'.join((path, kind, name, str(line))))
    return Symbol(sid, name, kind, path, signature, line, end, linkage, evidence)


def _function_header(header: str) -> tuple[str, str, str] | None:
    """C-ish top-level declaration ending in (...), rejecting expressions."""
    normalized = re.sub(r'\s+', ' ', header).strip()
    if len(normalized) > 3000 or not normalized or 'typedef ' in normalized or '=' in normalized:
        return None
    matches = list(_CALL.finditer(normalized))
    if not matches: return None
    # The LAST identifier directly followed by ( is not always the function name:
    # function-pointer arguments can occur later. Prefer first valid typed name.
    for m in matches:
        name = m.group(1)
        prefix = normalized[:m.start()].strip()
        if not prefix or prefix.endswith(('.', '->', ':')) or name in _SKIP_CALLS:
            continue
        if not re.search(r'\b[A-Za-z_]\w*\b', prefix):
            continue
        start = normalized.find('(', m.start())
        depth = 0; end = -1
        for j in range(start, len(normalized)):
            if normalized[j] == '(': depth += 1
            elif normalized[j] == ')':
                depth -= 1
                if depth == 0: end = j; break
        if end < 0: continue
        tail = normalized[end+1:].strip()
        if tail and not (tail.startswith('__attribute__') or tail.startswith('FURI_')):
            continue
        # Reject initializers and function pointer declarators where the name is a return type.
        if prefix.split()[-1] in {'return', 'case', 'else', 'goto', 'new', 'delete'}:
            continue
        return name, normalized[:end+1], 'internal' if re.search(r'\bstatic\b', prefix) else 'global'
    return None


def parse_c(path: str, text: str) -> ParsedFile:
    result = ParsedFile(path)
    lines = _line_offsets(text)
    masked = _mask_comments_and_literals(text)
    for match in _INCLUDE.finditer(text):
        if '#' not in masked[match.start():match.end()]:
            continue  # Ignore #include-like text inside comments or literals.
        result.references.append(Reference('file:'+path, match.group(1), 'includes', path, _line_of(match.start(), lines), evidence='source'))
    for match in _DEFINE.finditer(masked):
        name = match.group(1)
        line = _line_of(match.start(1), lines)
        signature = text[match.start():text.find('\n', match.start()) if '\n' in text[match.start():] else len(text)].strip()
        result.symbols.append(_make_symbol(path, name, 'macro', signature[:900], line, line, evidence='source'))
    for match in _NAMED_TYPE.finditer(masked):
        kind, name = match.groups()
        line = _line_of(match.start(2), lines)
        result.symbols.append(_make_symbol(path, name, kind, f'{kind} {name}', line, line, evidence='source'))
    for match in _TYPEDEF.finditer(masked):
        line = _line_of(match.start(1), lines)
        result.symbols.append(_make_symbol(path, match.group(1), 'typedef', f'typedef {match.group(1)}', line, line, evidence='heuristic'))
    code = _without_preprocessor(masked)
    depth = 0; start = 0; definition = None; body_start = 0
    for i, ch in enumerate(code):
        if ch == '{':
            if depth == 0:
                candidate = _function_header(code[start:i])
                if candidate:
                    name, sig, linkage = candidate
                    line = _line_of(start + code[start:i].find(name), lines)
                    definition = (name, sig, linkage, line)
                    body_start = i+1
            depth += 1
        elif ch == '}':
            if depth:
                depth -= 1
                if depth == 0:
                    if definition:
                        name, sig, linkage, line = definition
                        sym = _make_symbol(path, name, 'function', sig, line, _line_of(i, lines), linkage, 'source')
                        result.symbols.append(sym)
                        for call in _CALL.finditer(code, body_start, i):
                            callee = call.group(1)
                            if callee not in _SKIP_CALLS:
                                result.references.append(Reference(sym.id, callee, 'calls', path, _line_of(call.start(), lines)))
                        definition = None
                    start = i+1
        elif ch == ';' and depth == 0:
            candidate = _function_header(code[start:i])
            if candidate:
                name, sig, linkage = candidate
                line = _line_of(start + code[start:i].find(name), lines)
                result.symbols.append(_make_symbol(path, name, 'declaration', sig, line, _line_of(i, lines), linkage))
            start = i+1
    # A function not closed by end of file isn't a valid complete definition.
    seen = set()
    result.symbols = [s for s in result.symbols if not ((s.id in seen) or seen.add(s.id))]
    return result


def _safe_literal(node):
    try:
        value = ast.literal_eval(node)
        if isinstance(value, (str, int, float, bool, type(None))): return value
        if isinstance(value, (list, tuple)) and all(isinstance(v, str) for v in value): return list(value)
    except (ValueError, TypeError, SyntaxError, RecursionError): pass
    return None


def parse_fam(path: str, text: str) -> ParsedFile:
    """Parse App(...) manifests as AST; never execute Python code in a FAM."""
    result = ParsedFile(path)
    try:
        tree = ast.parse(text, filename=path)
    except SyntaxError:
        return result
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id != 'App':
            continue
        kws = {kw.arg: kw.value for kw in node.keywords if kw.arg is not None}
        appid = _safe_literal(kws.get('appid')) if 'appid' in kws else None
        if not isinstance(appid, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', appid):
            continue
        if isinstance(kws.get('apptype'), ast.Attribute):
            app_type = kws['apptype'].attr
        else:
            app_type = _safe_literal(kws.get('apptype')) if 'apptype' in kws else None
        props = {'apptype': app_type, 'requires': _safe_literal(kws.get('requires')) if 'requires' in kws else [],
                 'provides': _safe_literal(kws.get('provides')) if 'provides' in kws else [],
                 'conflicts': _safe_literal(kws.get('conflicts')) if 'conflicts' in kws else []}
        result.app_id = appid
        result.app_properties = props
        sym = _make_symbol(path, appid, 'app', f'App(appid={appid!r}, apptype={app_type!r})', node.lineno, node.end_lineno or node.lineno, evidence='source')
        result.symbols.append(sym)
        for kw, relation in (('requires','requires_app'),('provides','provides_app'),('conflicts','conflicts_with')):
            for value in props[kw] if isinstance(props[kw], list) else []:
                if re.fullmatch(r'[A-Za-z0-9_-]{1,80}', value):
                    result.references.append(Reference(sym.id, value, relation, path, node.lineno, evidence='manifest'))
    return result


def parse_exports(text: str) -> tuple[str, list[dict]]:
    """Extract official FAP SDK symbol table; '+' only means explicitly exported."""
    reader = csv.DictReader(io.StringIO(text))
    if not set(reader.fieldnames or ()) >= {'entry', 'status', 'name', 'type', 'params'}:
        raise ValueError('Missing api_symbols.csv columns')
    version, entries = '', []
    for row in reader:
        entry = (row.get('entry') or '').strip()
        status = (row.get('status') or '').strip()
        name = (row.get('name') or '').strip()
        if entry == 'Version':
            version = name
        elif entry not in ('Header', '') and name and len(name) <= 200 and status in ('+', '-', '?'):
            entries.append({'name': name, 'kind': entry, 'status': status,
                            'type': (row.get('type') or '').strip()[:900],
                            'params': (row.get('params') or '').strip()[:1600]})
    return version, entries
