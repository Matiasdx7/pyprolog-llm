"""
Ontología (RDF/OWL/SHACL) + cohortes semánticas en un mismo motor.

1. Carga una ontología de compras (N-Triples, sin dependencias; .ttl con rdflib).
2. Verifica afirmaciones de un LLM: soportada / contradicha / sin respaldo, con explicación.
3. Valida datos con formas SHACL.
4. Define una cohorte nueva 'bo' = B_τ + misma unidad de cobro según la ontología.

Uso:  python examples/ontologia_y_cohortes.py
"""
from pathlib import Path

from pyprolog_llm import CohortEngine, Ontologia, T

AQUI = Path(__file__).parent
EX = "http://example.org/compras#"

# --- 1. Ontología compartiendo el motor con CohortEngine
ce = CohortEngine(min_k=1, k=2)
onto = Ontologia(prefijos={"ex": EX}, engine=ce.e)
onto.cargar_archivo(AQUI / "compras.nt")
print("Clases de ex:oc1:", onto.clases_de("ex:oc1"))
print("Unidades bajo ex:minsal:", onto.valores("ex:minsal", "ex:contiene"))

# --- 2. Afirmaciones (p. ej. extraídas de la respuesta de un LLM)
print("\nVerificación de afirmaciones:")
for linea in (AQUI / "afirmaciones_llm.tsv").read_text().splitlines():
    v = onto.verificar(*linea.split("\t"))
    print(f"  {v.estado:<13} {' '.join(v.afirmacion)}")
    for x in v.explicacion:
        print(f"                · {x}")

# --- 3. SHACL
print("\nViolaciones SHACL:")
for v in onto.validar():
    print(f"  {v.foco}: {v.mensaje}  [{v.forma}]")

# --- 4. Cohorte guiada por la ontología
ce.e.consult("""
    unidad(Q, U) :- tp('ex:unidadCobro', Q, U).
    en_cohorte(bo(Tau), Q, P, V) :- en_cohorte(b(Tau), Q, P, V), unidad(Q, U), unidad(P, U).
    cohorte_lista(bo(Tau), Q, Ls) :- findall(V, en_cohorte(bo(Tau), Q, _, V), Ls).
""")
ce.cargar_items(["ex:p1", "ex:p2", "ex:q"], ["transporte"] * 3, [1, 2, 3], [5462.0, 805258.0, 0.0])
onto.cargar_triples([("ex:p1", "ex:unidadCobro", "hora"), ("ex:p2", "ex:unidadCobro", "mes"),
                     ("ex:q", "ex:unidadCobro", "hora")])
ce.cargar_similitudes([("ex:q", "ex:p1", 0.65), ("ex:q", "ex:p2", 0.66)])
print("\nCohorte B0.6 (solo similitud):", ce.estimar("ex:q", "B0.6"))
r = ce.e.query_first(T.estimar(T.bo(0.6), "ex:q", T.M, T.N, T.F))
print("Cohorte BO0.6 (similitud + unidad de cobro de la ontología):", r)
