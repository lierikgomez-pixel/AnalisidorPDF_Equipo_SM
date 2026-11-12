import os
import uuid

from flask import (Flask, flash, jsonify, redirect, render_template, request,
                   Response, url_for)
from werkzeug.utils import secure_filename

from analyzer import analyze_pdf
from citation import format_apa

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "cambia-esta-clave")
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024  # 25 MB

# Resultados en memoria (suficiente para desarrollo/uso local)
RESULTS = {}


def is_pdf(filename):
    return filename.lower().endswith(".pdf")


def save_and_analyze(file, term):
    name = secure_filename(file.filename)
    path = os.path.join(UPLOAD_DIR, f"{uuid.uuid4().hex}_{name}")
    file.save(path)
    try:
        return name, analyze_pdf(path, search_term=term, filename=name)
    finally:
        os.remove(path)  # no conservamos el archivo subido


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/analizar", methods=["POST"])
def analizar():
    file = request.files.get("pdf")
    term = request.form.get("term", "")
    if not file or file.filename == "":
        flash("Selecciona un archivo PDF.")
        return redirect(url_for("index"))
    if not is_pdf(file.filename):
        flash("El archivo debe tener extensión .pdf")
        return redirect(url_for("index"))
    try:
        name, data = save_and_analyze(file, term)
    except Exception as e:
        flash(f"No se pudo analizar el PDF: {e}")
        return redirect(url_for("index"))

    rid = uuid.uuid4().hex
    RESULTS[rid] = {"filename": name, **data}
    return redirect(url_for("resultado", rid=rid))


@app.route("/resultado/<rid>")
def resultado(rid):
    data = RESULTS.get(rid)
    if not data:
        flash("El resultado ya no está disponible. Sube el PDF de nuevo.")
        return redirect(url_for("index"))
    return render_template("result.html", d=data, rid=rid)


@app.route("/descargar/<rid>/texto")
def descargar_texto(rid):
    data = RESULTS.get(rid)
    if not data:
        return redirect(url_for("index"))
    return Response(
        data["full_text"], mimetype="text/plain; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={data['filename']}.txt"})


@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    """Uso: curl -F pdf=@archivo.pdf -F term=palabra http://localhost:5000/api/analyze"""
    file = request.files.get("pdf")
    if not file or not is_pdf(file.filename or ""):
        return jsonify(error="Envía un archivo PDF en el campo 'pdf'."), 400
    try:
        _, data = save_and_analyze(file, request.form.get("term", ""))
    except Exception as e:
        return jsonify(error=str(e)), 422
    data.pop("full_text", None)
    return jsonify(data)


@app.route("/api/apa", methods=["POST"])
def api_apa():
    """Recalcula la cita APA a partir de los campos editados en la ficha."""
    data = request.get_json(silent=True) or {}
    return jsonify(format_apa(data))


@app.errorhandler(413)
def too_large(_):
    flash("El archivo supera el límite de 25 MB.")
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(debug=True)
