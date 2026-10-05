"""Helpers for backchain.py edit-script resolutions (RES/<T12>/<newpath>.res.py).

A resolution script is re-applied to a FRESH merge every time the chain is rebuilt, so it
cannot go stale the way a stored full file does. It defines

    def resolve(r):            # r: Resolution
        return <text of <newpath> in the state BEFORE T>   (or None to delete the file)

Typical bodies:
    return r.regions(lambda o, b, t: o, lambda o, b, t: t)         # one lambda per conflict region
    return drop(r.ours, 'const std::string_view kFoo{"foo"};\\n')     # edit the component-after text
    return r.regions(keep_ours) .replace(...)                       # regions, then post-edits

Region lambdas get lists of lines: o = component (after T), b = plugin after T, t = plugin
before T (b and t are normalized when backchain runs with --normalize).
"""
import re


class Resolution:
    def __init__(self, sha, path, status, ours, base, theirs, merged, nconflicts, state_text):
        self.sha, self.path, self.status = sha, path, status
        self.ours, self.base, self.theirs = ours, base, theirs      # str or None
        self.merged, self.nconflicts = merged, nconflicts            # diff3 output (markers if conflicts)
        self._state_text = state_text

    def state(self, path):
        """text of another file in the component state after T (None if absent)"""
        return self._state_text(path)

    def regions(self, *fns):
        """apply one function per conflict region of the fresh merge; count must match"""
        if self.merged is None:
            raise SystemExit(f'{self.path}: no merge available (status {self.status})')
        return apply_regions(self.merged, fns, self.path)


def apply_regions(merged, fns, what=''):
    L = merged.split('\n'); out = []; i = 0; k = 0
    while i < len(L):
        if L[i].startswith('<<<<<<< '):
            o, b, t = [], [], []; cur = o; i += 1
            while not L[i].startswith('>>>>>>> '):
                if L[i].startswith('||||||| '): cur = b
                elif L[i] == '=======': cur = t
                else: cur.append(L[i])
                i += 1
            if k >= len(fns):
                raise SystemExit(f'{what}: more conflict regions than resolution lambdas ({len(fns)})')
            out += fns[k](o, b, t); k += 1; i += 1; continue
        out.append(L[i]); i += 1
    if k != len(fns):
        raise SystemExit(f'{what}: {k} conflict regions, {len(fns)} resolution lambdas')
    return '\n'.join(out)


# region lambdas
keep_ours = lambda o, b, t: o
keep_theirs = lambda o, b, t: t
drop_all = lambda o, b, t: []


def without(*needles):
    """region lambda: ours minus lines containing any needle"""
    return lambda o, b, t: [l for l in o if not any(n in l for n in needles)]


# text edits (assert they apply exactly, so a changed input fails loudly instead of silently)
def rep1(s, old, new=''):
    n = s.count(old)
    if n != 1:
        raise SystemExit(f'rep1: expected 1 occurrence, found {n}: {old[:80]!r}')
    return s.replace(old, new)


def drop(s, old, count=1):
    n = s.count(old)
    if n != count:
        raise SystemExit(f'drop: expected {count} occurrence(s), found {n}: {old[:80]!r}')
    return s.replace(old, '')


def drop_between(s, start, end, include_end=True):
    """remove from the first `start` to the next `end` (inclusive by default)"""
    i = s.index(start)
    j = s.index(end, i) + (len(end) if include_end else 0)
    return s[:i] + s[j:]


def drop_function(s, signature_start):
    """remove a top-level C++ function whose definition starts with signature_start (until '\\n}\\n'
    plus one following blank line)"""
    i = s.index(signature_start)
    j = s.index('\n}\n', i) + 3
    if s[j:j + 1] == '\n':
        j += 1
    return s[:i] + s[j:]


def drop_decl_blocks(s, key):
    """remove every '  /** ... */ <declaration ...;>' block whose declaration contains key"""
    lines = s.split('\n'); out = []; i = 0; n = 0
    while i < len(lines):
        if lines[i].strip() == '/**':
            j = i
            while not lines[j].strip().endswith('*/'):
                j += 1
            k = j + 1
            while k < len(lines) and not lines[k].rstrip().endswith(';'):
                k += 1
            if key in '\n'.join(lines[j + 1:k + 1]):
                n += 1
                i = k + 1
                if i < len(lines) and lines[i] == '':
                    i += 1
                continue
        out.append(lines[i]); i += 1
    if not n:
        raise SystemExit(f'drop_decl_blocks: no declaration with {key!r}')
    return '\n'.join(out)


def sub_all(s, pattern, repl, min_count=1):
    new, n = re.subn(pattern, repl, s)
    if n < min_count:
        raise SystemExit(f'sub_all: {n} matches for {pattern!r}')
    return new
