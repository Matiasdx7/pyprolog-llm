"""
Cohortes semánticas explicables.

Generaliza los escenarios del Capítulo VI (OE3) a cualquier dominio con:
  - una clase/categoría por ítem      grupo(Id, G)
  - un tiempo                          fecha(Id, T)
  - un valor numérico a estimar        valor(Id, V)        (p. ej. log-precio)
  - una firma de atributos opcional    atr(Id, Firma)      ('' = sin atributos)
  - similitudes precomputadas          similar(Q, P, S)    (p. ej. coseno de embeddings)

Variantes:  a | b(Tau) | bh(Tau) | k     con respaldo a 'a' si la cohorte tiene < min_k miembros.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence

from .engine import Engine
from .terms import Atom

REGLAS = r"""
% ---- historia previa dentro del mismo grupo (sin fuga temporal)
previa(Q, P) :- grupo(Q, G), en_grupo(G, P), fecha(Q, Tq), fecha(P, Tp), Tp < Tq.

% ---- pertenencia a cohortes
en_cohorte(a, Q, P, V)      :- previa(Q, P), valor(P, V).
en_cohorte(b(Tau), Q, P, V) :- previa(Q, P), similar(Q, P, S), S >= Tau, valor(P, V).
en_cohorte(bh(Tau), Q, P, V):- en_cohorte(b(Tau), Q, P, V), atr_compatible(Q, P).

atr_compatible(Q, _) :- atr(Q, '').
atr_compatible(Q, P) :- atr(Q, F), F \= '', atr(P, F2), F == F2.

% ---- listas por variante
cohorte_lista(a, Q, Ls)       :- findall(V, en_cohorte(a, Q, _, V), Ls).
cohorte_lista(b(Tau), Q, Ls)  :- findall(V, en_cohorte(b(Tau), Q, _, V), Ls).
cohorte_lista(bh(Tau), Q, Ls) :- findall(V, en_cohorte(bh(Tau), Q, _, V), Ls).
cohorte_lista(k, Q, Ls)       :- findall(par(S, V), k_cand(Q, S, V), Ps), k_vecinos(K), top_k(Ps, K, Ls).
k_cand(Q, S, V) :- previa(Q, P), similar(Q, P, S), valor(P, V).

% ---- estimación con respaldo
estimar(Var, Q, M, N, Var)        :- cohorte_lista(Var, Q, Ls), length(Ls, N), min_k(Mk), N >= Mk, median(Ls, M).
estimar(Var, Q, M, N, fallback_a) :- Var \= a, cohorte_lista(Var, Q, Ls), length(Ls, N0), min_k(Mk), N0 < Mk,
                                     cohorte_lista(a, Q, La), length(La, N), N > 0, median(La, M).
"""


def variante(v: str):
    """'A' -> a, 'K' -> k, 'B0.6' -> b(0.6), 'BH0.6' -> bh(0.6)."""
    from .dsl import T
    u = v.upper()
    if u in ("A", "K"):
        return Atom(u.lower())
    if u.startswith("BH"):
        return T.bh(float(v[2:]))
    if u.startswith("B"):
        return T.b(float(v[1:]))
    raise ValueError(f"Variante desconocida: {v}")


@dataclass
class Estimacion:
    consulta: str
    variante: str
    valor: float | None
    n: int
    fuente: str

    @property
    def uso_respaldo(self) -> bool:
        return self.fuente == "fallback_a"


@dataclass
class Previa:
    id: str
    similitud: float
    valor: float
    cohortes: dict = field(default_factory=dict)
    empate_corte_k: bool = False


class CohortEngine:
    """
    Fachada de alto nivel sobre Engine para cohortes semánticas explicables.

        ce = CohortEngine(min_k=5, k=10)
        ce.cargar_items(ids, grupos, fechas, valores, atrs)
        ce.cargar_similitudes([(q, p, s), ...])
        ce.estimar('q1', 'B0.6')          -> Estimacion(valor, n, fuente)
        ce.explicar('q1', taus=(0.6,))    -> lista de Previa con pertenencia por cohorte
    """

    def __init__(self, min_k: int = 5, k: int = 10, reglas_extra: str = ""):
        self.min_k, self.k = min_k, k
        self.e = Engine()
        self.e.consult(REGLAS + reglas_extra)
        self.e.fact("min_k", min_k)
        self.e.fact("k_vecinos", k)

    # ---------------------------------------------------------------- carga
    def cargar_items(self, ids: Iterable, grupos: Iterable, fechas: Iterable, valores: Iterable,
                     atrs: Iterable | None = None) -> int:
        n = 0
        atrs = atrs if atrs is not None else ("" for _ in iter(int, 1))
        for i, g, t, v, a in zip(ids, grupos, fechas, valores, atrs):
            i, g = str(i), str(g)
            self.e.fact("grupo", i, g)
            self.e.fact("en_grupo", g, i)
            self.e.fact("fecha", i, _tiempo(t))
            self.e.fact("valor", i, float(v))
            self.e.fact("atr", i, "" if a is None or a != a else str(a))
            n += 1
        return n

    def cargar_similitudes(self, pares: Iterable[tuple]) -> int:
        n = 0
        for q, p, s in pares:
            self.e.fact("similar", str(q), str(p), float(s))
            n += 1
        return n

    # ---------------------------------------------------------------- consultas
    def estimar(self, q, var: str) -> Estimacion | None:
        from .dsl import T
        r = self.e.query_first(T.estimar(variante(var), str(q), T.M, T.N, T.F))
        if r is None:
            return None
        return Estimacion(str(q), var, r["M"], r["N"], str(r["F"]))

    def miembros(self, q, var: str) -> set[str]:
        from .dsl import T
        if var.upper() == "K":
            return {p.id for p in self.previas(q)[: self.k]}
        return {str(r["P"]) for r in self.e.query(T.en_cohorte(variante(var), str(q), T.P, T.V))}

    def previas(self, q) -> list[Previa]:
        """Previas de la consulta ordenadas por similitud descendente."""
        from .dsl import T
        out = [Previa(str(r["P"]), r["S"], r["V"]) for r in
               self.e.query(T.previa(str(q), T.P), T.similar(str(q), T.P, T.S), T.valor(T.P, T.V))]
        return sorted(out, key=lambda x: -x.similitud)

    def empate_en_corte(self, q, eps: float = 1e-5, solo_si_cambia: bool = True) -> bool:
        """
        True si hay empate de similitud en la posición k. Con solo_si_cambia=True, solo
        reporta el empate si los empatados tienen valores distintos (el resultado depende del desempate).
        """
        ps = self.previas(q)
        if len(ps) <= self.k:
            return False
        corte = ps[self.k - 1].similitud
        if abs(ps[self.k].similitud - corte) >= eps:
            return False
        if not solo_si_cambia:
            return True
        valores = {round(p.valor, 6) for p in ps if abs(p.similitud - corte) < eps}
        return len(valores) > 1

    def explicar(self, q, variantes: Sequence[str] = ("A", "B0.6", "BH0.6", "K"), top: int | None = None):
        """Devuelve (previas con pertenencia por variante, estimaciones por variante)."""
        ps = self.previas(q)
        miembros = {v: self.miembros(q, v) for v in variantes}
        empate = self.empate_en_corte(q)
        corte = ps[self.k - 1].similitud if len(ps) >= self.k else None
        for p in ps:
            p.cohortes = {v: p.id in m for v, m in miembros.items()}
            p.empate_corte_k = bool(empate and corte is not None and abs(p.similitud - corte) < 1e-5)
        est = {v: self.estimar(q, v) for v in variantes}
        return (ps[:top] if top else ps), est


def _tiempo(t):
    if hasattr(t, "item"):
        t = t.item()
    if isinstance(t, (int, float)):
        return t
    if hasattr(t, "value"):            # pandas.Timestamp
        return int(t.value)
    return float(t)
