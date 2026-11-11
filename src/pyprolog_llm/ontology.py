"""
Ontologías RDF / OWL / SHACL como base de conocimiento lógica.

Carga triples (archivo, SPARQL o cualquier iterable), aplica un subconjunto de la semántica
RDFS/OWL con reglas Prolog y traduce formas SHACL a reglas de validación explicables.
Pensado para consumir ontologías gobernadas (p. ej. Context Ontology Accelerator, Neptune,
cualquier endpoint SPARQL) y razonar caso a caso sobre ellas.

    from pyprolog_llm.ontology import Ontologia
    o = Ontologia(prefijos={"ex": "http://example.org/"})
    o.cargar_archivo("dominio.ttl")            # rdflib (opcional) o .nt sin dependencias
    o.instancias("ex:Mamifero")
    o.verificar("ex:rex", "rdf:type", "ex:Pez")   # -> Verificacion(estado='contradicha', ...)
    o.validar()                                 # -> [Violacion(...), ...]  (SHACL)
"""
from __future__ import annotations

import json
import re
import urllib.request
import warnings
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable

from .engine import Engine
from .terms import Atom, Compound, Variable

PREFIJOS_BASE = {
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "owl": "http://www.w3.org/2002/07/owl#",
    "xsd": "http://www.w3.org/2001/XMLSchema#",
    "sh": "http://www.w3.org/ns/shacl#",
    "skos": "http://www.w3.org/2004/02/skos/core#",
}

# Hechos internos: tp(Predicado, Sujeto, Objeto) -> indexado por predicado y (predicado, sujeto).
REGLAS_RDFS_OWL = r"""
triple(S, P, O) :- tp(P, S, O).

% ---- jerarquías (transitivas). Ciclos en subClassOf no están soportados (ver Ontologia.ciclos()).
subclase(C, D) :- tp('rdfs:subClassOf', C, D).
subclase(C, E) :- tp('rdfs:subClassOf', C, D), subclase(D, E).
subpropiedad(P, Q) :- tp('rdfs:subPropertyOf', P, Q).
subpropiedad(P, R) :- tp('rdfs:subPropertyOf', P, Q), subpropiedad(Q, R).

% ---- tipos: afirmados, heredados, y por dominio/rango
tipo(X, C) :- tp('rdf:type', X, C).
instancia(X, C) :- tipo(X, C).
instancia(X, D) :- tipo(X, C), subclase(C, D).
instancia(X, C) :- tp('rdfs:domain', P, C), tp(P, X, _).
instancia(X, C) :- tp('rdfs:range', P, C), tp(P, _, X), \+ literal(X).

% ---- relaciones: directas, por subpropiedad, inversas, transitivas
rel(S, P, O) :- tp(P, S, O).
rel(S, P, O) :- subpropiedad(P2, P), tp(P2, S, O).
rel(S, P, O) :- inversa(P, P2), tp(P2, O, S).
rel(S, P, O) :- transitiva(P), tp(P, S, M), rel(M, P, O).
rel(S, P, O) :- inversa(P, P2), transitiva(P2), tp(P2, O, M), rel(M, P2, S).   % inversa de transitiva

inversa(P, Q) :- tp('owl:inverseOf', P, Q).
inversa(P, Q) :- tp('owl:inverseOf', Q, P).
transitiva(P) :- tp('rdf:type', P, 'owl:TransitiveProperty').
funcional(P)  :- tp('rdf:type', P, 'owl:FunctionalProperty').

disjunta(A, B) :- tp('owl:disjointWith', A, B).
disjunta(A, B) :- tp('owl:disjointWith', B, A).
clase_o_super(C, C).
clase_o_super(C, D) :- subclase(C, D).

% ---- afirmaciones (p. ej. extraídas de la salida de un LLM)
contradice(S, 'rdf:type', O, disjuntas(D, C2)) :-
    instancia(S, C2), clase_o_super(O, D), disjunta(D, C2).
contradice(S, P, O, funcional(P, O2)) :-
    P \== 'rdf:type', funcional(P), rel(S, P, O2), O2 \== O.

% ---- SHACL (subconjunto): sh:targetClass + sh:property con minCount, maxCount, class,
%      in, minInclusive, maxInclusive, datatype. Los hechos sh_* los genera Ontologia.
foco(Sh, X) :- sh_target(Sh, C), instancia(X, C).
valores(X, P, Vs) :- findall(V, rel(X, P, V), Vs0), sort(Vs0, Vs).

violacion(X, Sh, P, min_count(N, M)) :- foco(Sh, X), sh_prop(Sh, PS), sh_path(PS, P), sh_min_count(PS, N),
                                        valores(X, P, Vs), length(Vs, M), M < N.
violacion(X, Sh, P, max_count(N, M)) :- foco(Sh, X), sh_prop(Sh, PS), sh_path(PS, P), sh_max_count(PS, N),
                                        valores(X, P, Vs), length(Vs, M), M > N.
violacion(X, Sh, P, clase(K, V))      :- foco(Sh, X), sh_prop(Sh, PS), sh_path(PS, P), sh_class(PS, K),
                                        rel(X, P, V), \+ instancia(V, K).
violacion(X, Sh, P, fuera_de_lista(V)) :- foco(Sh, X), sh_prop(Sh, PS), sh_path(PS, P), sh_in(PS, _),
                                        rel(X, P, V), \+ sh_in(PS, V).
violacion(X, Sh, P, menor_que(Min, V)) :- foco(Sh, X), sh_prop(Sh, PS), sh_path(PS, P), sh_min_incl(PS, Min),
                                        rel(X, P, V), V < Min.
violacion(X, Sh, P, mayor_que(Max, V)) :- foco(Sh, X), sh_prop(Sh, PS), sh_path(PS, P), sh_max_incl(PS, Max),
                                        rel(X, P, V), V > Max.
violacion(X, Sh, P, tipo_dato(T, V))   :- foco(Sh, X), sh_prop(Sh, PS), sh_path(PS, P), sh_datatype(PS, T),
                                        rel(X, P, V), \+ tipo_literal(V, T).
"""

_NUM = {"integer", "int", "long", "short", "nonNegativeInteger", "positiveInteger", "decimal", "double", "float"}


@dataclass
class Verificacion:
    afirmacion: tuple
    estado: str                 # 'soportada' | 'contradicha' | 'sin_respaldo'
    explicacion: list = field(default_factory=list)


@dataclass
class Violacion:
    foco: str
    forma: str
    ruta: str
    restriccion: str
    detalle: tuple

    @property
    def mensaje(self) -> str:
        r, d = self.restriccion, self.detalle
        return {
            "min_count": f"{self.ruta}: tiene {d[1] if len(d) > 1 else '?'} valores, mínimo {d[0]}",
            "max_count": f"{self.ruta}: tiene {d[1] if len(d) > 1 else '?'} valores, máximo {d[0]}",
            "clase": f"{self.ruta} = {d[-1]} no es instancia de {d[0]}",
            "fuera_de_lista": f"{self.ruta} = {d[0]} no está entre los valores permitidos",
            "menor_que": f"{self.ruta} = {d[-1]} es menor que {d[0]}",
            "mayor_que": f"{self.ruta} = {d[-1]} es mayor que {d[0]}",
            "tipo_dato": f"{self.ruta} = {d[-1]!r} no es de tipo {d[0]}",
        }.get(r, f"{r}{d}")


class Ontologia:
    """Base de conocimiento RDF/OWL/SHACL sobre el motor Prolog. Comparte motor con CohortEngine si se pasa engine=."""

    def __init__(self, prefijos: dict | None = None, engine: Engine | None = None):
        self.prefijos = {**PREFIJOS_BASE, **(prefijos or {})}
        self.e = engine or Engine()
        self.e.consult(REGLAS_RDFS_OWL)
        self._literales: set = set()
        self._vistos: set = set()
        self._fc: dict = {}
        self._rc: dict = {}
        self._n = 0
        self._registrar_builtins()

    def _g(self, functor: str, *args):
        """Objetivo como término: strings que empiezan con '?' son variables; el resto, átomos/números."""
        def a(x):
            if isinstance(x, str) and x.startswith("?"):
                return Variable(x[1:])
            return x if isinstance(x, (int, float, Atom, Compound, Variable)) else self._t(x)
        return Compound(functor, tuple(a(x) for x in args))

    # ------------------------------------------------------------------ nombres
    def compactar(self, iri: str) -> str:
        """IRI completa -> 'prefijo:local' (si hay prefijo conocido)."""
        mejor = None
        for p, ns in self.prefijos.items():
            if iri.startswith(ns) and (mejor is None or len(ns) > len(self.prefijos[mejor])):
                mejor = p
        return f"{mejor}:{iri[len(self.prefijos[mejor]):]}" if mejor else iri

    def _t(self, x):
        """Normaliza un término de entrada a Atom o número."""
        if isinstance(x, (int, float)) and not isinstance(x, bool):
            return x
        s = str(x)
        if s.startswith("http://") or s.startswith("https://") or s.startswith("urn:"):
            s = self.compactar(s)
        return Atom(s)

    # ------------------------------------------------------------------ carga
    def cargar_triples(self, triples: Iterable[tuple]) -> int:
        """Carga (s, p, o). s/p/o pueden ser IRIs, 'pre:local', números o textos (literales)."""
        n = 0
        listas, firsts, rests = [], {}, {}
        for s, p, o in triples:
            s, p, o = self._t(s), self._t(p), o if isinstance(o, (int, float)) and not isinstance(o, bool) else self._t(o)
            if p.name == "rdf:first":
                firsts[s] = o
            elif p.name == "rdf:rest":
                rests[s] = o
            self.e.fact("tp", p, s, o)
            n += 1
        self._n += n
        self._materializar_shacl(firsts, rests)
        self._advertir_ciclos()
        return n

    def cargar_archivo(self, ruta, formato: str | None = None) -> int:
        """Turtle/RDF-XML/JSON-LD/N3 con rdflib (pip install rdflib); N-Triples (.nt) sin dependencias."""
        ruta = str(ruta)
        try:
            import rdflib  # noqa: F401
        except ImportError:
            if ruta.endswith(".nt") or formato == "nt":
                with open(ruta, encoding="utf-8") as f:
                    return self.cargar_ntriples(f.read())
            raise ImportError("Para Turtle/OWL/JSON-LD instale rdflib:  pip install 'pyprolog-llm[rdf]'")
        return self.cargar_grafo_rdflib(_rdflib_parse(ruta, formato))

    def cargar_grafo_rdflib(self, g) -> int:
        """Carga un rdflib.Graph (usa también sus prefijos)."""
        for p, ns in g.namespaces():
            if p and p not in self.prefijos:
                self.prefijos[str(p)] = str(ns)
        return self.cargar_triples((_rdflib_term(s), _rdflib_term(p), _rdflib_term(o, self._literales)) for s, p, o in g)

    def cargar_ntriples(self, texto: str) -> int:
        """Parser N-Triples mínimo, sin dependencias."""
        return self.cargar_triples(_ntriples(texto, self._literales))

    def cargar_sparql(self, endpoint: str, consulta: str | None = None, headers: dict | None = None,
                      timeout: int = 60) -> int:
        """
        Carga el resultado de un SELECT ?s ?p ?o desde un endpoint SPARQL 1.1
        (Neptune, el endpoint de Context Ontology Accelerator, Fuseki, GraphDB…).
        headers: p. ej. {"Authorization": "Bearer ..."}.
        """
        consulta = consulta or "SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 100000"
        data = ("query=" + urllib.request.quote(consulta)).encode()
        req = urllib.request.Request(endpoint, data=data, headers={
            "Accept": "application/sparql-results+json",
            "Content-Type": "application/x-www-form-urlencoded", **(headers or {})})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            res = json.load(r)
        return self.cargar_triples((_sparql_term(b["s"]), _sparql_term(b["p"]), _sparql_term(b["o"], self._literales))
                                   for b in res["results"]["bindings"])

    def hecho(self, s, p, o) -> None:
        """Agrega un triple suelto (p. ej. una afirmación nueva)."""
        self.cargar_triples([(s, p, o)])

    # ------------------------------------------------------------------ consultas
    def _q(self, goal, var: str) -> list:
        seen, out = set(), []
        goals = goal if isinstance(goal, tuple) else (goal,)
        for r in self.e.query(*goals):
            v = r.get(var)
            k = repr(v)
            if v is not None and k not in seen:
                seen.add(k)
                out.append(v if isinstance(v, (int, float)) else str(v))
        return out

    def instancias(self, clase: str) -> list:
        return self._q(self._g("instancia", "?X", clase), "X")

    def clases_de(self, individuo: str) -> list:
        return self._q(self._g("instancia", individuo, "?C"), "C")

    def superclases(self, clase: str) -> list:
        return self._q(self._g("subclase", clase, "?D"), "D")

    def valores(self, sujeto: str, propiedad: str) -> list:
        return self._q(self._g("rel", sujeto, propiedad, "?V"), "V")

    def consultar(self, texto: str) -> list[dict]:
        """Consulta Prolog arbitraria sobre la ontología (usa tp/3, instancia/2, rel/3, subclase/2…)."""
        return self.e.query_all(texto)

    # ------------------------------------------------------------------ verificación de afirmaciones
    def verificar(self, s, p, o) -> Verificacion:
        """
        Clasifica una afirmación (p. ej. una tripleta extraída de la salida de un LLM):
          soportada     se deriva de la ontología (directa o por inferencia), con la cadena que la justifica
          contradicha   choca con clases disjuntas o con una propiedad funcional
          sin_respaldo  no se deriva ni se contradice (supuesto de mundo abierto)
        """
        S, P, O = (str(self._t(x)) for x in (s, p, o))
        af = (S, P, O)
        if P == "rdf:type":
            cadena = self._cadena_tipo(S, O)
            if cadena:
                return Verificacion(af, "soportada", cadena)
        elif self.e.ask(self._g("rel", S, P, O)):
            return Verificacion(af, "soportada", self._cadena_rel(S, P, O))
        c = self.e.query_first(self._g("contradice", S, P, O, "?M"))
        if c:
            m = c["M"]
            args = tuple(str(a) for a in m.args)
            if m.functor == "disjuntas":
                exp = [f"{S} es instancia de {args[1]}"]
                if O != args[0]:
                    exp.append(f"{O} es subclase de {args[0]}")
                exp.append(f"{args[0]} y {args[1]} son disjuntas (owl:disjointWith)")
            else:
                exp = [f"{P} es funcional", f"{S} ya tiene {P} = {args[1]}"]
            return Verificacion(af, "contradicha", exp)
        return Verificacion(af, "sin_respaldo", ["no se deriva de la ontología ni la contradice"])

    def verificar_todas(self, afirmaciones: Iterable[tuple]) -> list[Verificacion]:
        return [self.verificar(*a) for a in afirmaciones]

    def _cadena_tipo(self, s: str, objetivo: str) -> list:
        directos = self._q(self._g("tipo", s, "?C"), "C")
        if objetivo in directos:
            return [f"{s} rdf:type {objetivo} (afirmado)"]
        sup = defaultdict(list)
        for r in self.e.query("tp('rdfs:subClassOf', C, D)"):
            sup[str(r["C"])].append(str(r["D"]))
        for c0 in directos:
            camino = _bfs(c0, objetivo, sup)
            if camino:
                return [f"{s} rdf:type {c0} (afirmado)"] + [f"{a} rdfs:subClassOf {b}" for a, b in zip(camino, camino[1:])]
        for r in self.e.query(self._g("tp", "rdfs:domain", "?P", objetivo), self._g("tp", "?P", s, "?_x")):
            return [f"{s} usa {r['P']}, cuyo dominio es {objetivo}"]
        for r in self.e.query(self._g("tp", "rdfs:range", "?P", objetivo), self._g("tp", "?P", "?_x", s)):
            return [f"{s} es valor de {r['P']}, cuyo rango es {objetivo}"]
        if self.e.ask(self._g("instancia", s, objetivo)):
            return [f"{s} es instancia de {objetivo} (inferido)"]
        return []

    def _cadena_rel(self, s, p, o) -> list:
        if self.e.ask(self._g("tp", p, s, o)):
            return [f"{s} {p} {o} (afirmado)"]
        r = self.e.query_first(self._g("subpropiedad", "?P2", p), self._g("tp", "?P2", s, o))
        if r:
            return [f"{s} {r['P2']} {o} (afirmado)", f"{r['P2']} rdfs:subPropertyOf {p}"]
        r = self.e.query_first(self._g("inversa", p, "?P2"), self._g("tp", "?P2", o, s))
        if r:
            return [f"{o} {r['P2']} {s} (afirmado)", f"{p} owl:inverseOf {r['P2']}"]
        if self.e.ask(self._g("transitiva", p)):
            return [f"{p} es transitiva: {s} → … → {o}"]
        return [f"{s} {p} {o} (inferido)"]

    # ------------------------------------------------------------------ SHACL
    def validar(self, limite: int | None = None) -> list[Violacion]:
        """Evalúa las formas SHACL cargadas. Cada violación trae foco, forma, ruta y la restricción incumplida."""
        out, seen = [], set()
        for r in self.e.query("violacion(X, Sh, P, R)"):
            R = r["R"]
            det = tuple(a if isinstance(a, (int, float)) else str(a) for a in R.args)
            v = Violacion(str(r["X"]), str(r["Sh"]), str(r["P"]), R.functor, det)
            k = (v.foco, v.forma, v.ruta, v.restriccion, v.detalle)
            if k not in seen:
                seen.add(k)
                out.append(v)
                if limite and len(out) >= limite:
                    break
        return out

    def _materializar_shacl(self, firsts: dict, rests: dict):
        """Traduce sh:NodeShape / sh:property / restricciones a hechos sh_* que usan las reglas."""
        mapa = {"sh:path": "sh_path", "sh:minCount": "sh_min_count", "sh:maxCount": "sh_max_count",
                "sh:class": "sh_class", "sh:minInclusive": "sh_min_incl", "sh:maxInclusive": "sh_max_incl",
                "sh:datatype": "sh_datatype"}
        for r in self.e.query("tp('sh:targetClass', Sh, C)"):
            self._hecho_unico("sh_target", r["Sh"], r["C"])
        for r in self.e.query("tp('sh:property', Sh, PS)"):
            self._hecho_unico("sh_prop", r["Sh"], r["PS"])
        for pred, hecho in mapa.items():
            for r in self.e.query(self._g("tp", pred, "?PS", "?V")):
                self._hecho_unico(hecho, r["PS"], r["V"])
        self._fc.update(firsts)
        self._rc.update(rests)
        for r in self.e.query("tp('sh:in', PS, L)"):
            for v in _lista_rdf(r["L"], self._fc, self._rc):
                self._hecho_unico("sh_in", r["PS"], v)

    def _hecho_unico(self, pred, *args):
        key = (pred,) + tuple(repr(a) for a in args)
        if key not in self._vistos:
            self._vistos.add(key)
            self.e.fact(pred, *args)

    def ciclos(self) -> list:
        """Ciclos en rdfs:subClassOf (el motor no los soporta: generarían recursión infinita)."""
        sup = defaultdict(list)
        for r in self.e.query("tp('rdfs:subClassOf', C, D)"):
            sup[str(r["C"])].append(str(r["D"]))
        out = []
        for c in list(sup):
            if _bfs_any(c, c, sup):
                out.append(c)
        return out

    def _advertir_ciclos(self):
        cs = self.ciclos()
        if cs:
            warnings.warn(f"Ciclos en rdfs:subClassOf (no soportados): {cs[:5]}")

    def _registrar_builtins(self):
        lits = self._literales

        def literal(args, sub, _):
            v = sub.walk_deep(args[0])
            if isinstance(v, (int, float)) or (isinstance(v, Atom) and v.name in lits):
                yield sub

        def tipo_literal(args, sub, _):
            v, t = sub.walk_deep(args[0]), str(sub.walk_deep(args[1]))
            local = t.split(":")[-1].split("#")[-1]
            ok = (local in _NUM and isinstance(v, (int, float))) or \
                 (local == "string" and isinstance(v, Atom) and v.name in lits) or \
                 (local == "boolean" and isinstance(v, Atom) and v.name in ("true", "false"))
            if ok:
                yield sub

        self.e.register_builtin("literal", 1, literal)
        self.e.register_builtin("tipo_literal", 2, tipo_literal)


# ---------------------------------------------------------------------- utilidades
def _bfs(a, b, sup):
    cola, prev = [a], {a: None}
    while cola:
        x = cola.pop(0)
        if x == b:
            camino = [x]
            while prev[camino[-1]] is not None:
                camino.append(prev[camino[-1]])
            return camino[::-1]
        for y in sup.get(x, []):
            if y not in prev:
                prev[y] = x
                cola.append(y)
    return None


def _bfs_any(a, b, sup):
    cola, vistos = list(sup.get(a, [])), set()
    while cola:
        x = cola.pop(0)
        if x == b:
            return True
        if x not in vistos:
            vistos.add(x)
            cola.extend(sup.get(x, []))
    return False


def _lista_rdf(nodo, firsts, rests, limite=10_000):
    out = []
    while nodo is not None and str(nodo) != "rdf:nil" and len(out) < limite:
        if nodo not in firsts:
            break
        out.append(firsts[nodo])
        nodo = rests.get(nodo)
    return out


def _lit(valor: str, dt: str | None, literales: set):
    local = (dt or "").split("#")[-1].split(":")[-1]
    if local in ("integer", "int", "long", "short", "nonNegativeInteger", "positiveInteger"):
        try:
            return int(valor)
        except ValueError:
            pass
    if local in ("decimal", "double", "float"):
        try:
            return float(valor)
        except ValueError:
            pass
    if local == "boolean":
        return "true" if valor in ("true", "1") else "false"
    literales.add(valor)
    return valor


_NT = re.compile(r'''^\s*(<[^>]*>|_:\S+)\s+(<[^>]*>)\s+(<[^>]*>|_:\S+|"(?:[^"\\]|\\.)*"(?:\^\^<[^>]*>|@[\w-]+)?)\s*\.\s*$''')


def _ntriples(texto: str, literales: set):
    for n, linea in enumerate(texto.splitlines(), 1):
        if not linea.strip() or linea.lstrip().startswith("#"):
            continue
        m = _NT.match(linea)
        if not m:
            raise SyntaxError(f"N-Triples inválido en la línea {n}: {linea[:80]}")
        s, p, o = m.groups()
        yield _nt_term(s), _nt_term(p), _nt_obj(o, literales)


def _nt_term(t):
    return t[1:-1] if t.startswith("<") else t


def _nt_obj(o, literales):
    if not o.startswith('"'):
        return _nt_term(o)
    m = re.match(r'"((?:[^"\\]|\\.)*)"(?:\^\^<([^>]*)>|@[\w-]+)?$', o)
    val = bytes(m.group(1), "utf-8").decode("unicode_escape") if "\\" in m.group(1) else m.group(1)
    return _lit(val, m.group(2), literales)


def _sparql_term(b, literales=None):
    if b["type"] == "uri":
        return b["value"]
    if b["type"] == "bnode":
        return "_:" + b["value"]
    return _lit(b["value"], b.get("datatype"), literales if literales is not None else set())


def _rdflib_parse(ruta, formato):
    import rdflib
    g = rdflib.Graph()
    g.parse(ruta, format=formato)
    return g


def _rdflib_term(t, literales=None):
    import rdflib
    if isinstance(t, rdflib.BNode):
        return "_:" + str(t)
    if isinstance(t, rdflib.Literal):
        return _lit(str(t), str(t.datatype) if t.datatype else None, literales if literales is not None else set())
    return str(t)
