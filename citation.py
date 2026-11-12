"""Extracción de datos bibliográficos de un PDF y formato APA 7.

Orden de confianza de las fuentes:
  1. Crossref (si el PDF contiene un DOI y hay internet)
  2. Portada / primera página del PDF
  3. Metadatos internos del archivo
Los datos son heurísticos: la interfaz permite corregirlos antes de copiar la cita.
"""
import html as _html
import json
import re
import statistics
import urllib.parse
import urllib.request
from datetime import datetime

# ───────────────────────── Constantes ─────────────────────────
MONTH_ES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
            "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
MONTH_EN = ["January", "February", "March", "April", "May", "June", "July",
            "August", "September", "October", "November", "December"]
MONTHS = {m: i + 1 for i, m in enumerate(MONTH_ES)}
MONTHS["setiembre"] = 9
MONTHS.update({m.lower(): i + 1 for i, m in enumerate(MONTH_EN)})
MONTHS.update({m.lower()[:3]: i + 1 for i, m in enumerate(MONTH_EN)})

ES_WORDS = set("de la el en y que los las del se por con para una un es como más pero sus al lo su este esta entre sobre".split())
EN_WORDS = set("the of and to in is that for with as on by this are from or an be it which at".split())

INSTITUTION_RE = re.compile(
    r"\b(universidad|instituto|facultad|escuela|tecnol[oó]gico|colegio|centro|departamento|"
    r"secretar[ií]a|university|institute|college|school|faculty|department|editorial)\b", re.I)

PARTICLES = {"de", "del", "la", "las", "los", "van", "von", "der", "den", "da", "di", "du", "le"}

STOP_NAME_WORDS = set("""
universidad instituto facultad escuela departamento tesis thesis proyecto informe reporte resumen abstract
licenciatura maestría maestria doctorado ingeniería ingenieria informática informatica para obtener título titulo
grado presenta que en por introducción introduction keywords palabras clave anteproyecto trabajo práctica practica
materia asignatura curso fecha lugar página pagina ciudad equipo grupo carrera programa academia centro
tecnológico tecnologico editorial journal revista volumen número numero universidad. unca
""".split())

ROLE_RE = re.compile(
    r"\b(director(?:a|es)?|co-?director(?:a)?|asesor(?:a|es)?|tutor(?:a)?|revisor(?:a)?|sinodal(?:es)?|"
    r"comit[eé]|advisor|supervisor|profesor(?:a)?|docente|catedr[aá]tic[oa]|jurado)\b", re.I)
AUTH_LABEL_RE = re.compile(
    r"^\s*(autor(?:es|a|as)?|presenta(?:n)?|elaborado por|elaboraron|por|by|author(?:s)?)\b\s*[:\-]?\s*", re.I)

NAME_TOKEN_RE = re.compile(r"^(?:[A-ZÁÉÍÓÚÜÑ][a-záéíóúüñ'’]+(?:-[A-ZÁÉÍÓÚÜÑ][a-záéíóúüñ'’]+)*\.?|[A-ZÁÉÍÓÚÜÑ]\.)$")
DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>\]\)]+)", re.I)
INVALID_TITLES = {"untitled", "sin título", "sin titulo", "documento1", "document1", "title", "título", "titulo"}
INVALID_AUTHORS = {"anonymous", "unknown", "admin", "user", "usuario", "windows user", "microsoft"}
GENERIC_BLOCKS = {"tesis", "thesis", "resumen", "abstract", "índice", "indice", "contenido", "portada",
                  "introducción", "introduccion", "informe", "reporte", "anteproyecto", "proyecto"}


# ───────────────────────── Utilidades ─────────────────────────
def _clean(s):
    return re.sub(r"\s+", " ", (s or "")).strip()


def detect_language(text):
    words = re.findall(r"[a-záéíóúñ]+", text.lower())
    es = sum(w in ES_WORDS for w in words)
    en = sum(w in EN_WORDS for w in words)
    return "es" if es >= en else "en"


def parse_date_text(text):
    """Devuelve {'year','month','day'} con lo que encuentre (mejor coincidencia primero)."""
    t = text or ""
    m = re.search(r"\b(\d{1,2})\s+de\s+([A-Za-záéíóú]+)\s+(?:de|del)\s+((?:19|20)\d{2})\b", t, re.I)
    if m and m.group(2).lower() in MONTHS:
        return {"year": int(m.group(3)), "month": MONTHS[m.group(2).lower()], "day": int(m.group(1))}
    m = re.search(r"\b([A-Z][a-z]+)\.?\s+(\d{1,2}),?\s+((?:19|20)\d{2})\b", t)
    if m and m.group(1).lower() in MONTHS:
        return {"year": int(m.group(3)), "month": MONTHS[m.group(1).lower()], "day": int(m.group(2))}
    m = re.search(r"\b(\d{1,2})\s+([A-Z][a-z]+)\.?,?\s+((?:19|20)\d{2})\b", t)
    if m and m.group(2).lower() in MONTHS:
        return {"year": int(m.group(3)), "month": MONTHS[m.group(2).lower()], "day": int(m.group(1))}
    m = re.search(r"\b((?:19|20)\d{2})-(\d{2})-(\d{2})\b", t)
    if m and 1 <= int(m.group(2)) <= 12:
        return {"year": int(m.group(1)), "month": int(m.group(2)), "day": int(m.group(3))}
    m = re.search(r"\b([A-Za-záéíóú]+)\s+(?:de|del)\s+((?:19|20)\d{2})\b", t, re.I)
    if m and m.group(1).lower() in MONTHS:
        return {"year": int(m.group(2)), "month": MONTHS[m.group(1).lower()], "day": None}
    m = re.search(r"\b([A-Z][a-z]+)\.?,?\s+((?:19|20)\d{2})\b", t)
    if m and m.group(1).lower() in MONTHS:
        return {"year": int(m.group(2)), "month": MONTHS[m.group(1).lower()], "day": None}
    cur = datetime.now().year
    years = [int(y) for y in re.findall(r"\b((?:19[5-9]\d|20[0-4]\d))\b", t) if int(y) <= cur + 1]
    if years:
        return {"year": years[0], "month": None, "day": None}
    return None


def format_date(d, lang):
    if not d:
        return ""
    y, mo, da = d.get("year"), d.get("month"), d.get("day")
    if lang == "es":
        if da and mo:
            return f"{da} de {MONTH_ES[mo - 1]} de {y}"
        if mo:
            return f"{MONTH_ES[mo - 1]} de {y}"
    else:
        if da and mo:
            return f"{MONTH_EN[mo - 1]} {da}, {y}"
        if mo:
            return f"{MONTH_EN[mo - 1]} {y}"
    return str(y) if y else ""


def _pdf_date(value):
    m = re.match(r"D:(\d{4})(\d{2})?(\d{2})?", value or "")
    if not m:
        return None
    y = int(m.group(1))
    mo = int(m.group(2)) if m.group(2) and 1 <= int(m.group(2)) <= 12 else None
    da = int(m.group(3)) if m.group(3) and mo else None
    return {"year": y, "month": mo, "day": da}


# ───────────────────────── Título ─────────────────────────
def title_from_layout(page):
    """Busca el bloque de texto con la fuente más grande de la primera página."""
    words = page.extract_words(extra_attrs=["size"])
    if not words:
        return None, None
    body = statistics.median(w["size"] for w in words)
    sizes = sorted({round(w["size"]) for w in words}, reverse=True)
    for s in sizes:
        if s < body * 1.2:
            break
        ws = sorted((w for w in words if round(w["size"]) == s), key=lambda w: (w["top"], w["x0"]))
        lines = []
        for w in ws:
            if lines and abs(w["top"] - lines[-1]["top"]) < s * 0.6:
                lines[-1]["words"].append(w)
                lines[-1]["bottom"] = max(lines[-1]["bottom"], w["bottom"])
            else:
                lines.append({"top": w["top"], "bottom": w["bottom"], "words": [w]})
        blocks, cur = [], [lines[0]]
        for ln in lines[1:]:
            if ln["top"] - cur[-1]["bottom"] <= s * 1.5:
                cur.append(ln)
            else:
                blocks.append(cur)
                cur = [ln]
        blocks.append(cur)
        for block in blocks:
            text = _clean(" ".join(w["text"] for ln in block
                                   for w in sorted(ln["words"], key=lambda x: x["x0"])))
            low = text.lower().strip(" :.")
            if len(text) < 4 or low in GENERIC_BLOCKS or INSTITUTION_RE.match(text):
                continue
            return text, block[-1]["bottom"]
    return None, None


def valid_meta_title(t):
    t = _clean(t)
    if len(t) < 5 or t.lower() in INVALID_TITLES:
        return None
    if re.search(r"\.(docx?|pdf|tex|indd)$", t, re.I) or re.match(r"^microsoft word", t, re.I):
        return None
    if " " not in t and re.search(r"[_\d]", t):
        return None
    return t


# ───────────────────────── Autores ─────────────────────────
def parse_names(line):
    """Devuelve una lista de nombres si la línea parece contener autores; si no, None."""
    line = re.sub(r"[\d\*†‡§¹²³⁴⁵⁶⁷⁸⁹⁰]+", " ", line)
    line = re.sub(r"\S+@\S+", " ", line)
    line = AUTH_LABEL_RE.sub("", line.strip()).strip(" :;,.")
    if not line:
        return None
    if line.isupper():
        line = line.title()
    parts = [p.strip() for p in re.split(r"\s*(?:,|;|&|\by\b|\band\b)\s*", line) if p.strip()]
    if len(parts) == 2 and all(" " not in p for p in parts):
        parts = [", ".join(parts)]            # "Pérez, Juan"
    if not parts or len(parts) > 6:
        return None
    out = []
    for p in parts:
        tokens = p.replace(", ", " ").split()
        real = [t for t in tokens if t.lower() not in PARTICLES]
        if len(real) < 2 or len(tokens) > 6:
            return None
        for t in tokens:
            if t.lower() in STOP_NAME_WORDS or INSTITUTION_RE.search(t):
                return None
            if t.lower() not in PARTICLES and not NAME_TOKEN_RE.match(t):
                return None
        out.append(p)
    return out


def authors_from_lines(lines):
    authors, mode, found = [], None, False
    for raw in lines[:22]:
        t = raw.strip()
        if not t:
            continue
        if ROLE_RE.search(t):
            mode = "skip"
            continue
        if AUTH_LABEL_RE.match(t) and len(AUTH_LABEL_RE.sub("", t).strip()) < 3:
            mode = "author"
            continue
        names = parse_names(t)
        if AUTH_LABEL_RE.match(t) and names:
            mode = "author"
        if names:
            if mode == "skip":
                continue
            authors += names
            found = True
            mode = mode or "auto"
        else:
            if mode == "skip":
                mode = None
            elif found:
                break
    seen, uniq = set(), []
    for a in authors:
        if a.lower() not in seen:
            seen.add(a.lower())
            uniq.append(a)
    return uniq


def authors_from_meta(value):
    value = _clean(value)
    if not value or value.lower() in INVALID_AUTHORS or len(value) < 4 or value.islower():
        return []
    if any(w in value.lower() for w in INVALID_AUTHORS):
        return []
    parts = [p.strip() for p in re.split(r"\s*(?:;|\band\b|\by\b|&)\s*", value) if p.strip()]
    if len(parts) == 1 and value.count(",") >= 1 and all(len(p.split()) >= 2 for p in value.split(",")):
        parts = [p.strip() for p in value.split(",") if p.strip()]
    return parts


# ───────────────────────── Lugar, editorial, tipo ─────────────────────────
PLACE_DATE_RE = re.compile(
    r"^(?P<place>[A-ZÁÉÍÓÚÑ][^\d,\.]{2,40}(?:,\s*[A-ZÁÉÍÓÚÑ][^\d,\.]{2,30}){0,2})\s*[,\.\-–—]?\s*"
    r"(?:a\s+)?(?P<date>(?:\d{1,2}\s+de\s+)?[A-Za-záéíóú]+\s+(?:de|del)\s+(?:19|20)\d{2}|(?:19|20)\d{2})\.?$")
PLACE_LABEL_RE = re.compile(r"^(?:lugar(?: de publicaci[oó]n)?|place of publication|ciudad)\s*:\s*(.+)$", re.I)


def find_place(lines):
    for ln in lines:
        t = _clean(ln)
        m = PLACE_LABEL_RE.match(t)
        if m:
            return _clean(m.group(1)).strip(" .")
    for ln in lines:
        t = _clean(ln)
        m = PLACE_DATE_RE.match(t)
        if not m:
            continue
        place = m.group("place").strip(" ,.")
        words = [w.lower() for w in re.findall(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]+", place)]
        if any(w in STOP_NAME_WORDS or w in MONTHS for w in words) or INSTITUTION_RE.search(place):
            continue
        return place
    return ""


def _titlecase_if_upper(t):
    if not t.isupper():
        return t
    small = {"de", "del", "la", "las", "los", "y", "en", "e", "of", "the", "and", "for"}
    words = t.lower().split()
    return " ".join(w if (i and w in small) else w.capitalize() for i, w in enumerate(words))


def find_institution(lines):
    for ln in lines:
        t = _clean(ln)
        if INSTITUTION_RE.match(t) and len(t) <= 90:
            return _titlecase_if_upper(t.strip(" .,"))
    return ""


def detect_degree(text):
    low = text.lower()
    if re.search(r"licenciatura|bachelor|grado", low):
        return "licenciatura"
    if re.search(r"maestr[ií]a|master", low):
        return "maestría"
    if re.search(r"doctorado|doctoral|ph\.?d|dissertation", low):
        return "doctorado"
    return ""


# ───────────────────────── Crossref ─────────────────────────
def crossref(doi, timeout=6):
    try:
        url = "https://api.crossref.org/works/" + urllib.parse.quote(doi)
        req = urllib.request.Request(url, headers={"User-Agent": "AnalizadorPDF/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            msg = json.load(r)["message"]
    except Exception:
        return None
    authors = []
    for a in msg.get("author", []):
        fam, giv = a.get("family", ""), a.get("given", "")
        if fam:
            authors.append(f"{fam}, {giv}".strip(", "))
        elif a.get("name"):
            authors.append(a["name"])
    parts = (msg.get("issued") or msg.get("published-print") or msg.get("published-online") or {}).get("date-parts", [[]])[0]
    date = None
    if parts:
        date = {"year": parts[0], "month": parts[1] if len(parts) > 1 else None,
                "day": parts[2] if len(parts) > 2 else None}
    return {
        "title": _clean((msg.get("title") or [""])[0]),
        "authors": authors,
        "date": date,
        "journal": _clean((msg.get("container-title") or [""])[0]),
        "volume": msg.get("volume", ""),
        "issue": msg.get("issue", ""),
        "pages": msg.get("page", ""),
        "publisher": msg.get("publisher", ""),
        "place": msg.get("publisher-location", ""),
        "type": msg.get("type", ""),
    }


# ───────────────────────── Extracción principal ─────────────────────────
def extract_citation(pdf, reader_meta, page_texts, filename=None, use_crossref=True):
    meta = {str(k).lstrip("/"): str(v) for k, v in dict(reader_meta or {}).items()}
    page = pdf.pages[0]
    text1 = page_texts[0] if page_texts else ""
    text12 = "\n".join(page_texts[:2])
    lang = detect_language("\n".join(page_texts[:3]))
    src = {}

    # DOI y Crossref
    doi = ""
    m = DOI_RE.search(text12) or DOI_RE.search(" ".join(meta.values()))
    if m:
        doi = m.group(1).rstrip(".,;")
    cr = crossref(doi) if (doi and use_crossref) else None

    # Título
    title, title_bottom = title_from_layout(page)
    if cr and cr["title"]:
        title, src["titulo"] = cr["title"], "Crossref (DOI)"
    elif title:
        src["titulo"] = "Portada del PDF (texto de mayor tamaño)"
    elif valid_meta_title(meta.get("Title", "")):
        title, src["titulo"] = valid_meta_title(meta["Title"]), "Metadatos del PDF"
    else:
        first = next((_clean(l) for l in text1.splitlines() if len(_clean(l)) > 4), "")
        title = first[:150]
        src["titulo"] = "Primera línea del texto" if title else "No detectado"

    # Líneas de la primera página (con posición)
    try:
        plines = page.extract_text_lines()
    except Exception:
        plines = []
    all_lines = [l["text"] for l in plines] or text1.splitlines()
    after = [l["text"] for l in plines if title_bottom is None or l["top"] >= title_bottom - 1] or all_lines

    # Autores
    if cr and cr["authors"]:
        authors, src["autores"] = cr["authors"], "Crossref (DOI)"
    else:
        authors = authors_from_lines(after)
        if authors:
            src["autores"] = "Portada del PDF"
        else:
            authors = authors_from_meta(meta.get("Author", ""))
            src["autores"] = "Metadatos del PDF" if authors else "No detectado"

    # Fecha / año
    date = None
    if cr and cr["date"]:
        date, src["fecha"] = cr["date"], "Crossref (DOI)"
    else:
        date = parse_date_text(text1)
        if date:
            src["fecha"] = "Portada del PDF"
        else:
            date = _pdf_date(meta.get("CreationDate", ""))
            src["fecha"] = "Fecha de creación del archivo (poco fiable)" if date else "No detectado"
    src["anio"] = src["fecha"]

    # Lugar
    place = ""
    if cr and cr["place"]:
        place, src["lugar"] = cr["place"], "Crossref (DOI)"
    else:
        place = find_place(all_lines)
        src["lugar"] = "Portada del PDF" if place else "No detectado"

    # Tipo, editorial / institución, grado
    head = "\n".join(all_lines[:30])
    institution = find_institution(all_lines)
    is_thesis = bool(re.search(r"\b(tesis|thesis|tesina|dissertation)\b", head, re.I))
    degree = detect_degree(head) if is_thesis else ""
    tipo = "documento"
    journal = volume = issue = pages = ""
    publisher = institution
    src["editorial"] = "Portada del PDF" if institution else "No detectado"
    if cr and (cr["journal"] or cr["type"] == "journal-article"):
        tipo = "articulo"
        journal, volume, issue, pages = cr["journal"], cr["volume"], cr["issue"], cr["pages"]
        publisher = ""
        src["editorial"] = "Crossref (DOI)"
    elif cr and cr["publisher"]:
        publisher, src["editorial"] = cr["publisher"], "Crossref (DOI)"
    elif is_thesis:
        tipo = "tesis"

    fields = {
        "tipo": tipo, "idioma": lang, "titulo": title, "autores": authors,
        "anio": str(date["year"]) if date else "", "fecha": format_date(date, lang),
        "lugar": place, "editorial": publisher, "revista": journal, "volumen": str(volume),
        "numero": str(issue), "paginas": str(pages), "doi": doi, "grado": degree,
    }
    return {"fields": fields, "sources": src, "apa": format_apa(fields), "crossref": bool(cr)}


# ───────────────────────── Formato APA 7 ─────────────────────────
def _initials(given):
    out = []
    for tok in given:
        pieces = [p for p in tok.split("-") if p]
        ini = "-".join(p[0].upper() + "." for p in pieces)
        out.append(ini.replace(".-", ".-"))
    return " ".join(out)


def format_name(name, lang):
    name = _clean(name)
    if not name:
        return ""
    if INSTITUTION_RE.search(name):
        return name                                   # autor corporativo
    if "," in name:
        surname, given = [p.strip() for p in name.split(",", 1)]
        given_tokens = given.split()
    else:
        tokens = name.split()
        units, pending = [], []
        for i, t in enumerate(tokens):
            if t.lower() in PARTICLES and i < len(tokens) - 1:
                pending.append(t)
            else:
                units.append(" ".join(pending + [t]))
                pending = []
        if len(units) == 1:
            return units[0]
        n_sur = 2 if (lang == "es" and len(units) >= 3) else 1
        surname = " ".join(units[-n_sur:])
        given_tokens = " ".join(units[:-n_sur]).split()
    ini = _initials(given_tokens)
    return f"{surname}, {ini}" if ini else surname


def join_authors(names, lang):
    n = len(names)
    if n == 0:
        return ""
    if n == 1:
        return names[0]
    conj = "y" if lang == "es" else "&"
    if n > 20:
        return ", ".join(names[:19]) + ", . . . " + names[-1]
    if n == 2:
        return f"{names[0]}, {conj} {names[1]}"
    return ", ".join(names[:-1]) + f", {conj} {names[-1]}"


def _sentence_case_if_upper(t):
    t = _clean(t)
    return t[:1] + t[1:].lower() if t.isupper() else t


def _end(s):
    s = _clean(s)
    return s if not s or s[-1] in ".?!" else s + "."


def format_apa(f):
    lang = f.get("idioma") or "es"
    autores = f.get("autores") or []
    if isinstance(autores, str):
        autores = autores.splitlines()
    names = [format_name(a, lang) for a in autores if _clean(a)]
    author_str = join_authors(names, lang)
    year = _clean(f.get("anio")) or ("s. f." if lang == "es" else "n.d.")
    tipo = f.get("tipo") or "documento"
    title = _sentence_case_if_upper(f.get("titulo") or "")
    doi = _clean(f.get("doi"))
    url = ""
    if doi:
        url = doi if doi.startswith("http") else "https://doi.org/" + doi

    segs = []                                          # (texto, cursiva)
    if author_str:
        segs.append((_end(author_str) + f" ({year}). ", False))
    if tipo == "articulo":
        if not author_str:
            segs.append((_end(title) + f" ({year}). ", False))
        else:
            segs.append((_end(title) + " ", False))
        if f.get("revista"):
            segs.append((_clean(f["revista"]), True))
            if f.get("volumen"):
                segs.append((", ", False))
                segs.append((_clean(f["volumen"]), True))
            if f.get("numero"):
                segs.append((f"({_clean(f['numero'])})", False))
            if f.get("paginas"):
                segs.append((f", {_clean(f['paginas'])}", False))
            segs.append((". ", False))
    else:
        t_txt = _clean(title) if tipo == "tesis" else _end(title)
        if not author_str:
            segs.append((t_txt, True))
            segs.append((f" ({year}). " if tipo != "tesis" else f". ({year}). ", False))
        else:
            segs.append((t_txt, True))
            segs.append((" ", False))
        if tipo == "tesis":
            grado = _clean(f.get("grado"))
            label = (f"Tesis de {grado}" if lang == "es" else f"{grado.capitalize()} thesis") if grado \
                else ("Tesis" if lang == "es" else "Thesis")
            inst = _clean(f.get("editorial"))
            segs.append((f"[{label}{', ' + inst if inst else ''}]. ", False))
        elif f.get("editorial"):
            segs.append((_end(f["editorial"]) + " ", False))
    if url:
        segs.append((url, False))

    text = re.sub(r"\.\.+", ".", "".join(s for s, _ in segs)).strip()
    text = re.sub(r"\s{2,}", " ", text)
    html_parts = []
    for s, it in segs:
        s = re.sub(r"\.\.+", ".", s)
        e = _html.escape(s)
        html_parts.append(f"<i>{e}</i>" if it and s.strip() else e)
    return {"text": text, "html": "".join(html_parts).strip()}
