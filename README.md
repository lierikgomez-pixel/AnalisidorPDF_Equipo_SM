# Analizador de PDFs con Flask

Sube un PDF y obtén: metadatos, nº de páginas, palabras, palabras clave, tablas,
detalle por página, búsqueda de términos y descarga del texto extraído.

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

## Ficha bibliográfica y cita APA 7
Al analizar un PDF, la app detecta título, autor(es), año, fecha, lugar y editorial/institución, y arma la cita APA 7.
- Si el PDF contiene un **DOI** y hay internet, los datos se consultan en Crossref (más fiables).
- Si no, se leen de la portada (texto de mayor tamaño, líneas de autores, fechas, "Ciudad, Estado. Mes de año") y, como último recurso, de los metadatos del archivo.
- Cada campo indica de dónde salió y se puede **editar**: la cita se recalcula al instante y se copia con cursivas.
- Tipos soportados: libro/informe/documento, artículo de revista y tesis.

## Estructura

```
pdf_analyzer/
├── app.py            # rutas Flask
├── analyzer.py       # lógica de análisis (pypdf + pdfplumber)
├── citation.py       # datos bibliográficos y formato APA 7
├── templates/        # base, index, result
├── static/style.css
└── uploads/          # temporal; los PDFs se borran tras analizarse
```

## Notas
- PDFs escaneados (solo imagen) no tienen texto: necesitarían OCR (pytesseract + pdf2image).
- Los resultados se guardan en memoria; para producción usa una base de datos y define `SECRET_KEY`.

## Diseño
La interfaz usa un estilo "glass" (vidrio esmerilado sobre fondo desenfocado).
Para usar una foto real de fondo, guarda `static/bg.jpg` y descomenta la línea `--photo` al inicio de `static/style.css`.
