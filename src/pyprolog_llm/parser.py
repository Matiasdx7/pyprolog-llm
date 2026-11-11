"""Parser mínimo de sintaxis Prolog: hechos, reglas, listas, números, operadores de comparación."""
from __future__ import annotations

import re

from .terms import Atom, Clause, Compound, Variable

_TOKEN = re.compile(r"""
    (?P<ws>\s+|%[^\n]*)
  | (?P<num>-?\d+\.\d+(?:[eE][-+]?\d+)?|-?\d+)
  | (?P<qatom>'(?:[^'\\]|\\.)*')
  | (?P<str>"(?:[^"\\]|\\.)*")
  | (?P<neck>:-)
  | (?P<op>=\\=|=:=|\\==|\\=|\\\+|==|=<|>=|<|>|=|\bis\b)
  | (?P<arith>[+\-*/])
  | (?P<var>[A-Z_][A-Za-z0-9_]*)
  | (?P<atom>[a-z][A-Za-z0-9_]*)
  | (?P<punct>[(),\[\]|.])
""", re.VERBOSE)

_CMP = {"=", "\\=", "==", "\\==", "<", ">", "=<", ">=", "=:=", "=\\=", "is"}


def _tokens(src: str):
    pos, out = 0, []
    while pos < len(src):
        m = _TOKEN.match(src, pos)
        if not m:
            raise SyntaxError(f"Carácter inesperado en {pos}: {src[pos:pos + 20]!r}")
        pos = m.end()
        kind = m.lastgroup
        if kind != "ws":
            out.append((kind, m.group()))
    return out


class _P:
    def __init__(self, toks):
        self.t, self.i, self.vars = toks, 0, {}

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def take(self, val=None):
        k, v = self.peek()
        if val is not None and v != val:
            raise SyntaxError(f"Se esperaba {val!r}, se encontró {v!r}")
        self.i += 1
        return k, v

    def clause(self):
        self.vars = {}
        head = self.goal()
        body = ()
        if self.peek()[1] == ":-":
            self.take()
            body = self.conj()
        self.take(".")
        if isinstance(head, Atom):
            head = Compound(head.name, ())
        return Clause(head, body)

    def conj(self):
        gs = [self.goal()]
        while self.peek()[1] == ",":
            self.take()
            gs.append(self.goal())
        return tuple(gs)

    def goal(self):
        if self.peek()[1] == "\\+":
            self.take()
            return Compound("\\+", (self.goal(),))
        left = self.expr()
        k, v = self.peek()
        if k == "op" and v in _CMP:
            self.take()
            return Compound(v, (left, self.expr()))
        return Compound(left.name, ()) if isinstance(left, Atom) else left

    def expr(self):
        left = self.term()
        while self.peek()[0] == "arith":
            _, op = self.take()
            left = Compound(op, (left, self.term()))
        return left

    def term(self):
        k, v = self.take()
        if k == "num":
            return float(v) if "." in v or "e" in v.lower() else int(v)
        if k == "var":
            if v == "_":
                return Variable(f"_anon{len(self.vars)}_{self.i}")
            return self.vars.setdefault(v, Variable(v))
        if k in ("atom", "qatom", "str"):
            name = v[1:-1] if k != "atom" else v
            if self.peek()[1] == "(":
                self.take("(")
                args = [self.expr()]
                while self.peek()[1] == ",":
                    self.take()
                    args.append(self.expr())
                self.take(")")
                return Compound(name, tuple(args))
            return Atom(name)
        if v == "[":
            items = []
            if self.peek()[1] != "]":
                items.append(self.expr())
                while self.peek()[1] == ",":
                    self.take()
                    items.append(self.expr())
            self.take("]")
            return tuple(items)
        if v == "(":
            g = self.goal()
            self.take(")")
            return g
        raise SyntaxError(f"Token inesperado: {v!r}")


def parse_program(src: str) -> list[Clause]:
    p = _P(_tokens(src))
    out = []
    while p.peek()[0] is not None:
        out.append(p.clause())
    return out


def parse_query(src: str) -> tuple:
    src = src.strip()
    src = src[2:].strip() if src.startswith("?-") else src
    p = _P(_tokens(src.rstrip(".") + "."))
    goals = p.conj()
    p.take(".")
    return goals


def parse_term(src: str):
    p = _P(_tokens(src))
    return p.expr()
