% Ejemplo: taxonomía + verificación de afirmaciones (anti-alucinación)
% Uso:  pyprolog-llm consult examples/taxonomia.pl -q "posee(salmon, P)"

es_un(perro, mamifero).
es_un(gato, mamifero).
es_un(mamifero, animal).
es_un(salmon, pez).
es_un(pez, animal).

tiene(mamifero, sangre_caliente).
puede(pez, nadar).
puede(mamifero, respirar_aire).

subclase(X, Y) :- es_un(X, Y).
subclase(X, Z) :- es_un(X, Y), subclase(Y, Z).

posee(X, P) :- tiene(X, P).
posee(X, P) :- puede(X, P).
posee(X, P) :- es_un(X, Y), posee(Y, P).

% Una afirmación de un LLM es "soportada" si se deriva de la base de conocimiento
soportada(afirma(S, P)) :- posee(S, P).
contradice(afirma(S, P)) :- \+ posee(S, P).
