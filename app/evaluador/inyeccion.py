"""Filtro de inyección de prompt (OWASP LLM01, SRS sección 9).

Busca en el material del estudiante frases que intentan darle órdenes a la IA ("ignora
la rúbrica", "pon 5"). No bloquea nada: marca la evaluación para que el docente la vea
primero. Es una defensa más, no la única: el material va como datos dentro de
<entrega>...</entrega>, la IA solo puede escoger un nivel que exista y la nota la pone
el backend.

Se guarda el id de la regla que saltó, nunca el texto del estudiante.

Antes de buscar, el texto se limpia para que no se esquive el filtro:
- se quitan los caracteres invisibles (espacio de ancho cero, guion suave...), que partirían
  la palabra si se volvieran espacio;
- NFKC (letras de ancho completo), minúsculas y sin tildes;
- letras de otros alfabetos que se ven iguales a las latinas ("і" cirílica) pasan a latinas;
- signos y guiones bajos cuentan como espacio ("ignora_las:instrucciones").

Memoria (Render tiene 512 MB): NFKC puede volver un carácter 18 letras (U+FDFA), así que
el texto se normaliza por bloques y con tope, nunca entero.
"""

import re
import unicodedata

_VERBO_NOTA = (
    r"(pon|ponme|ponle|ponnos|asigna|asignale|asignanos|asignarme|dame|dale|danos|"
    r"califica|calificame|calificalo|calificanos|otorga|otorgame|otorgale)"
)
_NOTA = r"(nota|calificacion|puntaje|puntuacion)"
# Lo que siempre apunta a la IA o al docente: "ignora las instrucciones", "olvida la rúbrica".
_ORDENES_ES = r"(instrucciones|instruccion|indicaciones|ordenes|rubrica|prompt)"
# "Reglas" y "criterios" salen en informes normales ("el agente ignora las reglas vacías"):
# solo cuentan con algo que diga cuáles ("todas las reglas", "tus reglas", "las reglas anteriores").
_CUALES = r"(anteriores|previas|de arriba|del docente|del profesor|del sistema|de la rubrica|de evaluacion)"
# Solo roles de evaluación: "act as an AI assistant" es un prompt normal del curso. "dan" es el
# nombre de un ataque conocido ("you are now DAN").
_ROL_EN = r"(grader|evaluator|teacher|professor|examiner|dan)"

# Ids estables (se guardan en la evaluación): cambiar el texto de una regla no cambia su id.
_REGLAS: dict[str, str] = {
    "es_ignorar": (
        r"\b(ignora|ignore|ignoren|ignorar|olvida|olviden|olvidar|omite|omitan|descarta|descarten)\s+"
        r"((todas?|todos?)\s+)?((el|la|las|los|tus|sus|cualquier|estas|esas|mis)\s+)?(demas\s+)?"
        rf"{_ORDENES_ES}\b"
        r"|\b(ignora|ignore|ignoren|ignorar|olvida|olviden|olvidar|omite|descarta)\s+"
        rf"(((todas|todos)\s+(las|los)|tus|sus)\s+(reglas|criterios)|(las|los)\s+(reglas|criterios)\s+{_CUALES})\b"
        r"|\b(ignora|ignore|ignoren|ignorar|olvida|olviden|olvidar)\s+(todo\s+)?lo\s+(anterior|de arriba)\b"
        rf"|\b(no sigas|no sigan|no obedezcas|no obedezcan|desobedece)\s+((las|los|tus|sus)\s+)?{_ORDENES_ES}"
        r"|\b(haz|hagan) caso omiso\b"
    ),
    # "pon nota de 5", "asigna una calificación máxima", "dame un 5", "califica con 5",
    # "ponme 5 en todo". Sin la palabra nota, el 5 tiene que ir con "un", "en todo" o tras
    # "califica con", para no saltar con "asignamos 5 archivos" o "dale con 5 reintentos".
    "es_nota": (
        rf"\b{_VERBO_NOTA}\s+(con\s+)?((un|una|la|el)\s+)?{_NOTA}\s+"
        r"(de\s+)?(maxima|perfecta|5|cinco|100)\b"
        rf"|\b{_VERBO_NOTA}\s+(un|el)\s+(5|cinco)( 0)?\b(?!\s*(%|por ciento))"
        r"|\b(califica|calificame|calificalo|calificanos)\s+con\s+(un\s+)?(5|cinco|100)\b"
        rf"|\b{_VERBO_NOTA}\s+(5|cinco)\s+(en|a)\s+(todo|todos|cada)\b"
        rf"|\b{_VERBO_NOTA}\s+(la\s+)?(maxima|mejor|mas alta)\s+{_NOTA}\b"
    ),
    "es_nivel": (
        r"\b(nivel|puntaje|nota)\s+(maximo|maxima|alto|excelente|perfecto|perfecta)\s+(en|para|a)\s+todo"
        r"|\b(elige|escoge|selecciona|asigna|pon|ponme|dame|dale)\s+(el\s+)?nivel\s+"
        r"(mas alto|superior|maximo|excelente)\b"
    ),
    # Solo "ahora eres" / "tú eres" / "a partir de ahora eres": "eres un evaluador experto" y
    # "actúa como un docente" son prompts normales en un curso de agentes.
    "es_rol": (
        r"\b(ahora eres|tu eres|a partir de ahora eres|desde ahora eres)\s+(un|una|el|la)?\s*"
        r"(evaluador|evaluadora|profesor|profesora|docente|calificador)\b"
    ),
    "en_ignore": (
        r"\b(ignore|disregard|forget|override)\s+((all|any|the|your|my|of)\s+)*"
        r"(previous|prior|earlier|preceding|above)\s+(instructions?|rules|prompt|guidelines|directions|criteria)\b"
        r"|\b(ignore|disregard|forget)\s+(everything|all)\s+(above|before)\b"
        r"|\b(ignore|disregard|forget|override)\s+((the|your|my|these|those|all|any)\s+)*"
        r"(instructions?|rubric|system prompt|prompt)\b"
        # "ignore your rules", "forget all rules"; "override the rules in .eslintrc" no salta
        r"|\b(ignore|disregard|forget|override)\s+((all|your)\s+)+(the\s+)?(rules|criteria|guidelines)\b"
    ),
    "en_grade": (
        r"\b(give|assign|award|grade)\s+(me\s+|this\s+|it\s+)?(a\s+|the\s+)?"
        r"(full|max|maximum|perfect|top|highest)\s+(score|grade|marks|mark|points|level)"
        r"|\b(choose|pick|assign)\s+(the\s+)?(highest|top|best|maximum|max)\s+(level|score|grade)\b"
        # "select max(score) from notas" es SQL, no una orden: solo "select" lleva la excepción
        r"|\bselect\s+(the\s+)?(highest|top|best|maximum|max)\s+(level|score|grade)\b(?!\s+from\b)"
        r"|\b(grade|score|rate)\s+(this|me|it)\s+(5|10|100)\s*/\s*(5|10|100)\b"
    ),
    "en_rol": (
        # hasta cuatro palabras entre medio: "you are now a very generous and lenient grader"
        r"\b(you are now|from now on you are|pretend to be|act as)\s+"
        rf"((a|an|the)\s+)?(\w+\s+){{0,4}}{_ROL_EN}\b"
    ),
    "etiquetas": r"</?\s*(entrega|system|sistema|instrucciones|instructions)\s*>",
}
_COMPILADAS = {id_: re.compile(patron) for id_, patron in _REGLAS.items()}

# Caracteres del estudiante que lee el filtro: el doble de lo que ve la IA (MAXIMO_MATERIAL).
MAXIMO_TEXTO = 120_000
BLOQUE = 20_000  # se normaliza de a pedazos: como mucho 18 veces esto en memoria
SOLAPE = 300  # una frase partida entre dos bloques también se encuentra

# Invisibles (formato y relleno): guion suave, ancho cero, marcas de dirección, unión de
# palabras, selectores de variante, rellenos coreanos, BOM y caracteres "etiqueta".
_RANGOS_INVISIBLES = [
    (0xAD, 0xAD), (0x34F, 0x34F), (0x61C, 0x61C), (0x115F, 0x1160), (0x180B, 0x180E),
    (0x200B, 0x200F), (0x202A, 0x202E), (0x2060, 0x2069), (0x3164, 0x3164), (0xFE00, 0xFE0F),
    (0xFEFF, 0xFEFF), (0xFFA0, 0xFFA0), (0xE0000, 0xE007F), (0xE0100, 0xE01EF),
]  # fmt: skip
_INVISIBLES = re.compile("[" + "".join(f"{chr(a)}-{chr(b)}" for a, b in _RANGOS_INVISIBLES) + "]")
# Los caracteres "etiqueta" (U+E0020-E007E) copian el ASCII y no se ven: una frase entera puede
# ir escondida ahí y algunos modelos la leen. Se pasan a su letra, separados por espacios.
_ETIQUETAS_UNICODE = re.compile(f"[{chr(0xE0020)}-{chr(0xE007E)}]+")
_A_ASCII = {c: c - 0xE0000 for c in range(0xE0020, 0xE007F)}
# Las banderas de regiones (🏴 + etiquetas + U+E007F) son el único uso normal de las etiquetas.
# Fuera de una bandera, cualquier etiqueta es texto escondido: regla "texto_oculto".
# Solo banderas de verdad: 2 a 6 letras minúsculas o dígitos (p. ej. "gbsct"). Una "bandera"
# larga que envuelve una frase no se acepta.
_BANDERA = re.compile(
    f"{chr(0x1F3F4)}[{chr(0xE0030)}-{chr(0xE0039)}{chr(0xE0061)}-{chr(0xE007A)}]{{2,6}}{chr(0xE007F)}"
)
TEXTO_OCULTO = "texto_oculto"
# Marcas que se combinan con la letra anterior (tildes separadas como en los PDF de Mac, y
# otras parecidas): se conservan hasta que NFD las quita. Si no, "ru" + tilde + "brica"
# quedaría "ru brica".
_RANGOS_COMBINAN = [(0x300, 0x36F), (0x1AB0, 0x1AFF), (0x1DC0, 0x1DFF), (0x20D0, 0x20FF), (0xFE20, 0xFE2F)]
_COMBINAN = "".join(f"{chr(a)}-{chr(b)}" for a, b in _RANGOS_COMBINAN)
# Espacios y signos seguidos se juntan ANTES de partir en bloques: así el solape alcanza.
# Se dejan "<", ">" y "/" (y sus versiones de ancho completo) para la regla de etiquetas y "%"
# para que "dame el 5 % de los datos" no parezca una nota.
_SEPARADORES = re.compile(f"[^\\w<>/%{chr(0xFF1C)}{chr(0xFF1E)}{chr(0xFF0F)}{_COMBINAN}]+|_+")
_MARCAS = re.compile(f"[{_COMBINAN}]")
_NO_LATINO = re.compile(r"[^a-z0-9<>/%]+")
# Los signos que se conservan también sirven para pegar palabras ("ignora%las%instrucciones",
# "ignora/las/instrucciones"). Se busca otra vez sin ellos, salvo "%" tras un número y "/"
# entre números ("5 %", "5/5"), que son los únicos usos que necesitan las reglas.
_SIGNOS_SUELTOS = re.compile(r"[<>]|(?<![0-9])(?<![0-9] )%|(?<![0-9])/|/(?![0-9])")

# Letras cirílicas y griegas (ya en minúscula) que se ven como una latina
_PARECIDAS = str.maketrans(
    {
        0x430: "a", 0x432: "b", 0x435: "e", 0x456: "i", 0x458: "j", 0x43A: "k", 0x43C: "m",
        0x43D: "h", 0x43E: "o", 0x440: "p", 0x441: "c", 0x442: "t", 0x443: "y", 0x445: "x",
        0x455: "s", 0x501: "d", 0x4CF: "l", 0x3B1: "a", 0x3B5: "e", 0x3B9: "i", 0x3BA: "k",
        0x3BD: "v", 0x3BF: "o", 0x3C1: "p", 0x3C4: "t", 0x3C5: "u", 0x261: "g",
    }
)  # fmt: skip


def normalizar(texto: str) -> str:
    """Minúsculas, sin tildes, solo letras latinas y números, con espacios simples:
    'IGNÓRA las', 'ign' + ancho cero + 'ora las' e 'ignora' con 'i' cirílica cuentan como 'ignora las'.
    Todo con expresiones regulares y translate: nada recorre el texto letra por letra en Python."""
    texto = unicodedata.normalize("NFKC", _INVISIBLES.sub("", texto)).lower()
    texto = _MARCAS.sub("", unicodedata.normalize("NFD", texto)).translate(_PARECIDAS)
    return _NO_LATINO.sub(" ", texto)


def _buscar(texto: str, saltaron: set[str]) -> None:
    texto = _SEPARADORES.sub(" ", texto)[:MAXIMO_TEXTO]
    for inicio in range(0, max(len(texto), 1), BLOQUE):
        limpio = normalizar(texto[max(0, inicio - SOLAPE) : inicio + BLOQUE])
        saltaron.update(id_ for id_, regla in _COMPILADAS.items() if regla.search(limpio))
        sin_signos = _SIGNOS_SUELTOS.sub(" ", limpio)
        if sin_signos != limpio:
            saltaron.update(id_ for id_, regla in _COMPILADAS.items() if regla.search(sin_signos))


def detectar(texto: str) -> list[str]:
    """Ids de las reglas que saltaron (vacío si no hay nada sospechoso).

    Se busca en dos versiones: con los invisibles borrados ('ign' + ancho cero + 'ora' es
    'ignora') y cambiados por espacio ('ignora' + ancho cero + 'las' es 'ignora las')."""
    texto = texto[:MAXIMO_TEXTO]
    oculto = bool(_ETIQUETAS_UNICODE.search(_BANDERA.sub("", texto)))
    texto = _ETIQUETAS_UNICODE.sub(lambda m: " " + m.group().translate(_A_ASCII) + " ", texto)
    saltaron: set[str] = set()
    _buscar(_INVISIBLES.sub("", texto), saltaron)
    if _INVISIBLES.search(texto):
        _buscar(_INVISIBLES.sub(" ", texto), saltaron)
    return [id_ for id_ in _COMPILADAS if id_ in saltaron] + ([TEXTO_OCULTO] if oculto else [])
