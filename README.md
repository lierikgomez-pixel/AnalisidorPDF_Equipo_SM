# Analizador de PDFs con Flask

PDF: metadatos, nº de páginas, palabras, palabras clave, tablas,
detalle por página, búsqueda de términos y descargar el texto extraído.

## Instalación

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Abre http://127.0.0.1:5000

## API JSON

```bash
curl -F pdf=@documento.pdf -F term=metodología http://127.0.0.1:5000/api/analyze
```

## Estructura

```
pdf_analyzer/
├── app.py            # rutas Flask
├── analyzer.py       # lógica de análisis (pypdf + pdfplumber)
├── templates/        # base, index, result
├── static/style.css
└── uploads/          # temporal; los PDFs se borran tras analizarse
```

## Notas
- PDFs escaneados (solo imagen) no tienen texto: necesitarían OCR (pytesseract + pdf2image).
- Los resultados se guardan en memoria; para producción usa una base de datos y define `SECRET_KEY`.

## Diseño
La interfaz usa un estilo "glass" (vidrio esmerilado sobre fondo desenfocado).

