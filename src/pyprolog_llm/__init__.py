"""
pyprolog-llm — programación lógica explicable sobre Python para contexto semántico.

    from pyprolog_llm import Engine, T, CohortEngine

    e = Engine()
    e.consult("padre(tom, bob). abuelo(X, Z) :- padre(X, Y), padre(Y, Z).")
    e.query_all("padre(tom, X)")

    ce = CohortEngine(min_k=5, k=10)
    ce.cargar_items(ids, grupos, fechas, valores, atributos)
    ce.cargar_similitudes(pares)          # (consulta, previa, similitud)
    ce.estimar("q1", "B0.6")
"""
from .cohorts import CohortEngine, Estimacion, Previa, variante
from .dsl import T
from .engine import Engine, coerce
from .ontology import Ontologia, Verificacion, Violacion
from .parser import parse_program, parse_query, parse_term
from .terms import Atom, Clause, Compound, Substitution, Variable, unify

__version__ = "0.2.0"
__all__ = ["Ontologia", "Verificacion", "Violacion", "Engine", "T", "CohortEngine", "Estimacion", "Previa", "variante", "Atom", "Variable", "Compound",
           "Clause", "Substitution", "unify", "coerce", "parse_program", "parse_query", "parse_term"]
