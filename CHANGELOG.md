# Changelog

## 0.2.0 — 2026-11-11
- Nuevo módulo `ontology`: carga RDF/OWL/SHACL (archivo con rdflib opcional, N-Triples sin dependencias, endpoint SPARQL 1.1).
- Razonamiento RDFS/OWL práctico: subClassOf/subPropertyOf, domain/range, inverseOf, TransitiveProperty, FunctionalProperty, disjointWith.
- `Ontologia.verificar()`: clasifica afirmaciones (p. ej. de un LLM) en soportada / contradicha / sin_respaldo con cadena explicativa.
- `Ontologia.validar()`: subconjunto SHACL (minCount, maxCount, class, in, min/maxInclusive, datatype).
- La ontología puede compartir motor con `CohortEngine` para cohortes guiadas por la ontología.
- Motor: nuevos predicados `\==/2` y `sort/2`.
- CLI: `pyprolog-llm ontologia`.
- Extra opcional `[rdf]` (rdflib).

## 0.1.0 — 2026-11-11
- Motor Prolog en Python puro: unificación con occurs-check, resolución SLD, índices por argumento.
- Parser de sintaxis Prolog (`consult`, `consult_file`, consultas en texto).
- Predicados internos: comparación, `is`, `\+`, `findall`, `length`, `member`, `sum`, `min_list`, `max_list`, `median`, `top_k`.
- `CohortEngine`: cohortes A, B_τ, BH_τ y K con respaldo a A y solo historia previa.
- Reportes de trazabilidad CSV + HTML.
- CLI `pyprolog-llm {demo, consult, validar, reporte}`.
