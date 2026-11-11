"""Términos lógicos, sustituciones y unificación (algoritmo de Robinson con occurs-check)."""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Union


@dataclass(frozen=True)
class Atom:
    """Constante simbólica: perro, '781118', a."""
    name: str

    def __repr__(self) -> str:
        return self.name


@dataclass(frozen=True)
class Variable:
    """Variable lógica: X, Quien, _G12."""
    name: str

    def __repr__(self) -> str:
        return f"?{self.name}"


@dataclass(frozen=True)
class Compound:
    """Término compuesto: functor(arg1, ..., argN)."""
    functor: str
    args: tuple = ()

    @property
    def key(self) -> str:
        return f"{self.functor}/{len(self.args)}"

    def __repr__(self) -> str:
        if not self.args:
            return self.functor
        return f"{self.functor}({', '.join(map(repr, self.args))})"


# Las listas Prolog se representan como tuplas de Python.
Term = Union[Atom, Variable, Compound, int, float, tuple]


def is_ground(t) -> bool:
    """True si el término no contiene variables."""
    if isinstance(t, Variable):
        return False
    if isinstance(t, Compound):
        return all(is_ground(a) for a in t.args)
    if isinstance(t, tuple):
        return all(is_ground(a) for a in t)
    return True


class Substitution:
    """Entorno inmutable Variable -> Término."""
    __slots__ = ("_b",)

    def __init__(self, bindings: dict | None = None):
        self._b = bindings or {}

    def bind(self, var: Variable, term) -> "Substitution":
        b = dict(self._b)
        b[var] = term
        return Substitution(b)

    def walk(self, t):
        while isinstance(t, Variable) and t in self._b:
            t = self._b[t]
        return t

    def walk_deep(self, t):
        t = self.walk(t)
        if isinstance(t, Compound):
            return Compound(t.functor, tuple(self.walk_deep(a) for a in t.args))
        if isinstance(t, tuple):
            return tuple(self.walk_deep(a) for a in t)
        return t

    def __len__(self) -> int:
        return len(self._b)

    def __repr__(self) -> str:
        return "{" + ", ".join(f"{k}: {v}" for k, v in self._b.items()) + "}"


def _occurs(var: Variable, t, sub: Substitution) -> bool:
    t = sub.walk(t)
    if t == var:
        return True
    if isinstance(t, Compound):
        return any(_occurs(var, a, sub) for a in t.args)
    if isinstance(t, tuple):
        return any(_occurs(var, a, sub) for a in t)
    return False


def unify(a, b, sub: Substitution) -> Substitution | None:
    """Unifica a y b bajo sub. Devuelve la nueva sustitución o None si fallan."""
    a, b = sub.walk(a), sub.walk(b)
    if a == b and type(a) is type(b):
        return sub
    if isinstance(a, Variable):
        return None if _occurs(a, b, sub) else sub.bind(a, b)
    if isinstance(b, Variable):
        return None if _occurs(b, a, sub) else sub.bind(b, a)
    if isinstance(a, Compound) and isinstance(b, Compound):
        if a.functor != b.functor or len(a.args) != len(b.args):
            return None
        for x, y in zip(a.args, b.args):
            sub = unify(x, y, sub)
            if sub is None:
                return None
        return sub
    if isinstance(a, tuple) and isinstance(b, tuple):
        if len(a) != len(b):
            return None
        for x, y in zip(a, b):
            sub = unify(x, y, sub)
            if sub is None:
                return None
        return sub
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        return sub if a == b else None
    return None


@dataclass
class Clause:
    """Cláusula de Horn: head :- body. Un hecho tiene body vacío."""
    head: Compound
    body: tuple = ()
    ground: bool = field(init=False)

    def __post_init__(self):
        self.ground = not self.body and is_ground(self.head)

    def __repr__(self) -> str:
        if not self.body:
            return f"{self.head!r}."
        return f"{self.head!r} :- {', '.join(map(repr, self.body))}."


_fresh = itertools.count(1)


def rename_variables(clause: Clause) -> Clause:
    """Copia la cláusula con variables frescas (los hechos ground se devuelven tal cual)."""
    if clause.ground:
        return clause
    suffix = f"_{next(_fresh)}"
    mapping: dict = {}

    def r(t):
        if isinstance(t, Variable):
            v = mapping.get(t)
            if v is None:
                v = mapping[t] = Variable(t.name + suffix)
            return v
        if isinstance(t, Compound):
            return Compound(t.functor, tuple(r(a) for a in t.args))
        if isinstance(t, tuple):
            return tuple(r(a) for a in t)
        return t

    return Clause(r(clause.head), tuple(r(g) for g in clause.body))
