"""Motor de inferencia: resolución SLD con backtracking, índices y predicados internos."""
from __future__ import annotations

from collections import defaultdict
from statistics import median as _median
from typing import Callable, Iterable, Iterator

from .terms import Atom, Clause, Compound, Substitution, Variable, is_ground, rename_variables, unify

Builtin = Callable[[tuple, Substitution, "Engine"], Iterator[Substitution]]


class Engine:
    """
    Motor Prolog en Python puro.

    - Índice por (predicado), (predicado, 1er arg) y (predicado, 1er arg, 2do arg) para hechos ground.
    - Predicados internos: =, \\=, ==, <, =<, >, >=, not/1 (\\+), findall/3, length/2,
      member/2, sum/2, min_list/2, max_list/2, median/2, top_k/3, print/1.
    - Extensible con register_builtin().
    """

    def __init__(self):
        self.clauses: list[Clause] = []
        self._by_key: dict = defaultdict(list)
        self._by_first: dict = defaultdict(list)
        self._var_first: dict = defaultdict(list)
        self._by_two: dict = defaultdict(list)
        self._builtins: dict[str, Builtin] = {}
        _register_defaults(self)

    # ------------------------------------------------------------------ carga
    def add_clause(self, clause: Clause) -> None:
        h = clause.head
        key = h.key
        self.clauses.append(clause)
        self._by_key[key].append(clause)
        first = h.args[0] if h.args else None
        if first is not None and is_ground(first):
            self._by_first[(key, first)].append(clause)
        else:
            self._var_first[key].append(clause)
        if clause.ground and len(h.args) >= 2:
            self._by_two[(key, h.args[0], h.args[1])].append(clause)

    def fact(self, functor: str, *args) -> None:
        """Agrega un hecho: fact('clase', 'q1', '781118')."""
        self.add_clause(Clause(Compound(functor, tuple(coerce(a) for a in args))))

    def facts(self, functor: str, rows: Iterable[tuple]) -> int:
        """Carga masiva de hechos del mismo predicado. Devuelve cuántos cargó."""
        n = 0
        for row in rows:
            self.fact(functor, *row)
            n += 1
        return n

    def rule(self, head: Compound, *body: Compound) -> None:
        self.add_clause(Clause(head, tuple(body)))

    def consult(self, source: str) -> int:
        """Carga cláusulas desde texto Prolog. Devuelve cuántas cargó."""
        from .parser import parse_program
        cls = parse_program(source)
        for c in cls:
            self.add_clause(c)
        return len(cls)

    def consult_file(self, path) -> int:
        with open(path, encoding="utf-8") as f:
            return self.consult(f.read())

    def register_builtin(self, name: str, arity: int, fn: Builtin) -> None:
        """fn(args, sub, engine) -> generador de sustituciones."""
        self._builtins[f"{name}/{arity}"] = fn

    # ------------------------------------------------------------------ consultas
    def solve(self, goals: tuple, sub: Substitution | None = None) -> Iterator[Substitution]:
        yield from self._solve(tuple(goals), sub or Substitution())

    def query(self, *goals) -> Iterator[dict]:
        """Genera soluciones como dict {nombre_variable: valor}. Acepta términos o un string Prolog."""
        goals = self._goals(goals)
        names = _vars(goals)
        for s in self._solve(goals, Substitution()):
            out = {}
            for v in names:
                val = s.walk_deep(v)
                if not v.name.startswith("_") and not isinstance(val, Variable):
                    out[v.name] = val
            yield out

    def query_first(self, *goals) -> dict | None:
        return next(self.query(*goals), None)

    def query_all(self, *goals) -> list[dict]:
        return list(self.query(*goals))

    def ask(self, *goals) -> bool:
        """¿Existe al menos una solución? (sirve también para consultas sin variables)."""
        return next(self._solve(self._goals(goals), Substitution()), None) is not None

    # ------------------------------------------------------------------ internos
    def _goals(self, goals) -> tuple:
        if len(goals) == 1 and isinstance(goals[0], str):
            from .parser import parse_query
            return parse_query(goals[0])
        return tuple(goals)

    def _candidates(self, goal: Compound) -> list:
        key = goal.key
        if not goal.args:
            return self._by_key.get(key, [])
        first = goal.args[0]
        if not is_ground(first):
            return self._by_key.get(key, [])
        var_first = self._var_first.get(key, [])
        if len(goal.args) >= 2 and not var_first and is_ground(goal.args[1]):
            return self._by_two.get((key, first, goal.args[1]), [])
        return self._by_first.get((key, first), []) + var_first

    def _solve(self, goals: tuple, sub: Substitution) -> Iterator[Substitution]:
        if not goals:
            yield sub
            return
        goal = sub.walk(goals[0])
        rest = goals[1:]
        if isinstance(goal, Atom):
            goal = Compound(goal.name, ())
        if not isinstance(goal, Compound):
            raise TypeError(f"Objetivo no invocable: {goal!r}")
        goal = Compound(goal.functor, tuple(sub.walk(a) for a in goal.args))
        bi = self._builtins.get(goal.key)
        if bi is not None:
            for s2 in bi(goal.args, sub, self):
                yield from self._solve(rest, s2)
            return
        for clause in self._candidates(goal):
            c = rename_variables(clause)
            s2 = unify(goal, c.head, sub)
            if s2 is not None:
                yield from self._solve(c.body + rest, s2)


# ---------------------------------------------------------------------- helpers
def coerce(v):
    """Convierte valores Python a términos: str -> Atom, list -> tupla, números tal cual."""
    if isinstance(v, (Atom, Variable, Compound)):
        return v
    if isinstance(v, bool):
        return Atom("true" if v else "false")
    if isinstance(v, (int, float)):
        return v
    if hasattr(v, "item"):          # escalares numpy
        return v.item()
    if isinstance(v, (list, tuple)):
        return tuple(coerce(x) for x in v)
    if v is None:
        return Atom("")
    return Atom(str(v))


def _vars(terms, acc=None) -> list:
    acc = [] if acc is None else acc
    for t in terms:
        if isinstance(t, Variable):
            if t not in acc:
                acc.append(t)
        elif isinstance(t, Compound):
            _vars(t.args, acc)
        elif isinstance(t, tuple):
            _vars(t, acc)
    return acc


def _num(sub, t):
    v = sub.walk_deep(t)
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, Compound) and v.functor in "+-*/" and len(v.args) == 2:
        a, b = _num(sub, v.args[0]), _num(sub, v.args[1])
        return {"+": a + b, "-": a - b, "*": a * b, "/": a / b}[v.functor]
    raise TypeError(f"Se esperaba un número, se obtuvo {v!r}")


def _out(sub, var, value):
    s2 = unify(var, value, sub)
    if s2 is not None:
        yield s2


def _register_defaults(e: Engine) -> None:
    def cmp(op):
        def f(args, sub, _):
            if op(_num(sub, args[0]), _num(sub, args[1])):
                yield sub
        return f

    lt, le = (lambda a, b: a < b), (lambda a, b: a <= b)
    gt, ge = (lambda a, b: a > b), (lambda a, b: a >= b)
    for name, op in (("<", lt), ("=<", le), (">", gt), (">=", ge),
                     ("=:=", lambda a, b: a == b), ("=\\=", lambda a, b: a != b),
                     ("lt", lt), ("le", le), ("gt", gt), ("ge", ge)):
        e.register_builtin(name, 2, cmp(op))

    def eq(args, sub, _):
        yield from _out(sub, args[0], args[1])

    def neq(args, sub, _):
        if unify(args[0], args[1], sub) is None:
            yield sub

    def identical(args, sub, _):
        if sub.walk_deep(args[0]) == sub.walk_deep(args[1]):
            yield sub

    def is_(args, sub, _):
        yield from _out(sub, args[0], _num(sub, args[1]))

    def not_(args, sub, eng):
        if next(eng._solve((args[0],), sub), None) is None:
            yield sub

    def findall(args, sub, eng):
        tmpl, goal, out = args
        yield from _out(sub, out, tuple(s.walk_deep(tmpl) for s in eng._solve((goal,), sub)))

    def length(args, sub, _):
        yield from _out(sub, args[1], len(sub.walk_deep(args[0])))

    def member(args, sub, _):
        for x in sub.walk_deep(args[1]):
            s2 = unify(args[0], x, sub)
            if s2 is not None:
                yield s2

    def agg(fn):
        def f(args, sub, _):
            xs = sub.walk_deep(args[0])
            if xs:
                yield from _out(sub, args[1], fn(xs))
        return f

    def top_k(args, sub, _):
        """top_k(Pares, K, Valores): Pares = [par(Puntaje, Valor), ...]; devuelve los K de mayor puntaje."""
        pares, k = sub.walk_deep(args[0]), _num(sub, args[1])
        orden = sorted(pares, key=lambda c: -c.args[0])[: int(k)]
        yield from _out(sub, args[2], tuple(c.args[1] for c in orden))

    def not_identical(args, sub, _):
        if sub.walk_deep(args[0]) != sub.walk_deep(args[1]):
            yield sub

    def sort_(args, sub, _):
        xs = sub.walk_deep(args[0])
        uniq = {repr(x): x for x in xs}
        orden = sorted(uniq.values(), key=lambda x: (0, x, "") if isinstance(x, (int, float)) else (1, 0, repr(x)))
        yield from _out(sub, args[1], tuple(orden))

    def print_(args, sub, _):
        print(sub.walk_deep(args[0]))
        yield sub

    for name, ar, fn in (("=", 2, eq), ("\\=", 2, neq), ("==", 2, identical), ("\\==", 2, not_identical), ("is", 2, is_),
                         ("sort", 2, sort_),
                         ("eq", 2, identical), ("not_equal", 2, neq),
                         ("not", 1, not_), ("\\+", 1, not_), ("findall", 3, findall), ("length", 2, length),
                         ("member", 2, member), ("sum", 2, agg(lambda xs: sum(xs))),
                         ("min_list", 2, agg(min)), ("max_list", 2, agg(max)),
                         ("median", 2, agg(lambda xs: float(_median(xs)))),
                         ("top_k", 3, top_k), ("print", 1, print_)):
        e.register_builtin(name, ar, fn)
    e.register_builtin("true", 0, lambda a, s, _: iter([s]))
    e.register_builtin("fail", 0, lambda a, s, _: iter([]))
