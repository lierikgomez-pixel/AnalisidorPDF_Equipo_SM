"""Lógica de análisis de PDFs (independiente de Flask)."""
import re
from collections import Counter

import pdfplumber
from pypdf import PdfReader

from citation import extract_citation

# Palabras vacías comunes en español e inglés
STOPWORDS = set("""
a al algo algunas algunos ante antes como con contra cual cuando de del desde donde durante e el ella ellas ellos en
entre era erais eran eras eres es esa esas ese eso esos esta estaba estado estas este esto estos fue fueron ha han hasta
hay la las le les lo los mas más me mi mis mucho muy nada ni no nos nosotros o os otra otros para pero poco por porque
que quien se sea sean ser si sí sin sobre su sus también tan te tiene tienen todo todos tu tus un una uno unos y ya yo
the of and to in is it that for on with as was are be by this at from or an have not but they which you all
""".split())

WORD_RE = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{3,}")


def _clean_meta(meta):
    if not meta:
        return {}
    out = {}
    for key, value in dict(meta).items():
        out[str(key).lstrip("/")] = str(value)
    return out


def analyze_pdf(path, search_term=None, top_n=15, filename=None):
    """Analiza un PDF y devuelve un diccionario con los resultados."""
    reader = PdfReader(path)
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:
            raise ValueError("El PDF está protegido con contraseña.")

    result = {
        "pages": len(reader.pages),
        "metadata": _clean_meta(reader.metadata),
        "page_details": [],
        "tables": [],
    }

    all_text = []
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            words = WORD_RE.findall(text)
            tables = page.extract_tables() or []
            for t in tables:
                if t:
                    result["tables"].append({"page": i, "rows": t})
            result["page_details"].append({
                "page": i,
                "chars": len(text),
                "words": len(words),
                "images": len(page.images),
                "tables": len(tables),
                "preview": text[:400],
            })
            all_text.append(text)

        # Ficha bibliográfica (título, autores, año, lugar...) y cita APA
        try:
            result["citation"] = extract_citation(pdf, reader.metadata, all_text, filename)
        except Exception as e:  # la cita nunca debe romper el análisis
            result["citation"] = {"fields": {"tipo": "documento", "idioma": "es", "titulo": "", "autores": [],
                                             "anio": "", "fecha": "", "lugar": "", "editorial": "", "revista": "",
                                             "volumen": "", "numero": "", "paginas": "", "doi": "", "grado": ""},
                                  "sources": {}, "apa": {"text": "", "html": ""}, "crossref": False,
                                  "error": str(e)}

    full_text = "\n".join(all_text)
    words = [w.lower() for w in WORD_RE.findall(full_text)]
    keywords = Counter(w for w in words if w not in STOPWORDS)

    result["full_text"] = full_text
    result["total_words"] = len(words)
    result["total_chars"] = len(full_text)
    result["unique_words"] = len(set(words))
    result["reading_minutes"] = round(len(words) / 200, 1)  # ~200 ppm
    result["top_keywords"] = keywords.most_common(top_n)
    result["has_text"] = bool(full_text.strip())

    if search_term:
        term = search_term.strip()
        matches = []
        pattern = re.compile(re.escape(term), re.IGNORECASE)
        for i, text in enumerate(all_text, start=1):
            for m in pattern.finditer(text):
                start, end = max(0, m.start() - 50), min(len(text), m.end() + 50)
                matches.append({"page": i, "context": text[start:end].replace("\n", " ")})
        result["search"] = {"term": term, "count": len(matches), "matches": matches[:50]}

    return result
