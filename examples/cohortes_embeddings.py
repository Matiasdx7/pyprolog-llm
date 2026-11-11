"""Ejemplo: cohortes semánticas con embeddings propios (sentence-transformers opcional)."""
import math
import random

from pyprolog_llm import CohortEngine

items = [  # id, grupo, fecha, precio, texto
    ("p1", "781118", 1, 15090, "movilización palena urbano río encuentro"),
    ("p2", "781118", 2, 20119, "movilización palena urbano el tigre"),
    ("p3", "781118", 3, 2252386, "servicio de transporte mensual seis vehículos"),
    ("p4", "781118", 4, 805258, "arriendo de 2 camionetas por 30 días"),
    ("p5", "781118", 5, 15090, "movilización palena urbano el aceite"),
    ("q", "781118", 9, 18915, "movilización palena urbano río encuentro regreso"),
]

try:
    from sentence_transformers import SentenceTransformer
    m = SentenceTransformer("hiiamsid/sentence_similarity_spanish_es")
    E = {i: v for (i, *_), v in zip(items, m.encode([t for *_, t in items], normalize_embeddings=True))}
    sim = lambda a, b: float(E[a] @ E[b])
except ImportError:  # similitud de Jaccard como alternativa sin dependencias
    tok = {i: set(t.split()) for i, *_, t in items}
    sim = lambda a, b: len(tok[a] & tok[b]) / len(tok[a] | tok[b])

ce = CohortEngine(min_k=2, k=3)
ce.cargar_items([i for i, *_ in items], [g for _, g, *_ in items], [t for _, _, t, *_ in items],
                [math.log1p(p) for *_, p, _ in items])
ce.cargar_similitudes(("q", i, sim("q", i)) for i, *_ in items if i != "q")

for v in ("A", "B0.5", "K"):
    e = ce.estimar("q", v)
    print(f"{v:<5} precio_ref={math.expm1(e.valor):>12,.0f}  n={e.n}  fuente={e.fuente}")
print("\nPrevias:")
previas, _ = ce.explicar("q", ("A", "B0.5"))
for p in previas:
    print(f"  {p.id}  sim={p.similitud:.2f}  B0.5={'✓' if p.cohortes['B0.5'] else '·'}")
