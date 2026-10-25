"""Authenticated server-rendered desk; importing it never starts an analysis."""

import json
import os
import re
import secrets
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from flask import (
    Flask,
    Response,
    abort,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from markdown_it import MarkdownIt
from markupsafe import Markup
from werkzeug.security import check_password_hash, generate_password_hash

from .store import connect, initialize

REPORT_SECTIONS = {
    "final_trade_decision": "Décision de portefeuille",
    "market_report": "Analyse technique",
    "fundamentals_report": "Fondamentaux",
    "sentiment_report": "Sentiment du marché",
    "news_report": "Actualité et macroéconomie",
    "investment_plan": "Synthèse de la recherche",
    "trader_investment_plan": "Proposition de transaction",
}

STATUS_LABELS = {
    "queued": "En attente",
    "running": "En cours",
    "completed": "Terminée",
    "failed": "Échec",
}
RATING_LABELS = {
    "Buy": "Acheter",
    "Overweight": "Surpondérer",
    "Hold": "Conserver",
    "Underweight": "Sous-pondérer",
    "Sell": "Vendre",
    "REVIEW": "À examiner",
}


def create_app(config=None):
    app = Flask(__name__)
    app.config.update(
        DATA_DIR=os.getenv("TRADING_DESK_DATA_DIR", str(Path.home() / ".tradingagents" / "desk")),
        MAX_CONTENT_LENGTH=16 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.getenv("TRADING_DESK_HTTPS", "0") == "1",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
    )
    app.config.update(config or {})
    directory = Path(app.config["DATA_DIR"])
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    app.config["DATABASE"] = str(directory / "desk.sqlite3")
    initialize(app.config["DATABASE"])
    if not app.config.get("SECRET_KEY"):
        secret_path = directory / "session.key"
        try:
            with open(secret_path, "x", opener=lambda p, f: os.open(p, f, 0o600)) as file:
                file.write(secrets.token_hex(32))
        except FileExistsError:
            pass
        app.config["SECRET_KEY"] = secret_path.read_text().strip()
    dummy_hash = generate_password_hash(secrets.token_hex(16))
    markdown = MarkdownIt("commonmark", {"html": False})

    @app.template_filter("status_fr")
    def status_fr(value):
        return STATUS_LABELS.get(value, value)

    @app.template_filter("rating_fr")
    def rating_fr(value):
        return RATING_LABELS.get(value, value) if value else "En attente"

    @app.template_filter("markdown")
    def render_markdown(value):
        return Markup(markdown.render(value or ""))

    @app.before_request
    def protect():
        session.setdefault("csrf", secrets.token_urlsafe(32))
        g.user = None
        if session.get("username"):
            with connect(app.config["DATABASE"]) as db:
                user = db.execute(
                    "SELECT * FROM users WHERE username=?", (session["username"],)
                ).fetchone()
            if user and secrets.compare_digest(user["version"], session.get("version", "")):
                g.user = user["username"]
        if request.method == "POST" and not secrets.compare_digest(
            session["csrf"].encode(), request.form.get("csrf", "").encode()
        ):
            abort(400, "Votre formulaire a expiré. Rechargez la page et réessayez.")
        if request.endpoint not in {"login", "static"} and not g.user:
            return redirect(url_for("login"))
        return None

    @app.after_request
    def headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
            "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        )
        if app.config["SESSION_COOKIE_SECURE"]:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    @app.context_processor
    def common():
        return {
            "key_ready": bool(os.getenv("OPENROUTER_API_KEY")),
            "today": date.today().isoformat(),
        }

    @app.route("/login", methods=["GET", "POST"])
    def login():
        error, status = None, 200
        with connect(app.config["DATABASE"]) as db:
            configured = db.execute("SELECT count(*) FROM users").fetchone()[0] == 2
        if request.method == "POST":
            ip, now = request.remote_addr or "unknown", time.time()
            name = request.form.get("username", "").strip().lower()
            with connect(app.config["DATABASE"]) as db:
                db.execute("BEGIN IMMEDIATE")
                db.execute("DELETE FROM attempts WHERE created < ?", (now - 900,))
                attempts = db.execute("SELECT count(*) FROM attempts WHERE ip=?", (ip,)).fetchone()[
                    0
                ]
                if attempts >= 5:
                    error, status = "Trop de tentatives. Réessayez dans 15 minutes.", 429
                else:
                    # Reserve an attempt inside the transaction to prevent parallel bypass.
                    db.execute("INSERT INTO attempts VALUES (?, ?)", (ip, now))
                    user = db.execute("SELECT * FROM users WHERE username=?", (name,)).fetchone()
            if not error:
                valid = check_password_hash(
                    user["password_hash"] if user else dummy_hash, request.form.get("password", "")
                )
                if valid and user:
                    with connect(app.config["DATABASE"]) as db:
                        db.execute("DELETE FROM attempts WHERE ip=? AND created=?", (ip, now))
                    session.clear()
                    session.update(
                        username=name, version=user["version"], csrf=secrets.token_urlsafe(32)
                    )
                    session.permanent = True
                    return redirect(url_for("dashboard"))
                error, status = "Identifiant ou mot de passe incorrect.", 401
        return render_template("login.html", error=error, configured=configured), status

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.get("/")
    def dashboard():
        with connect(app.config["DATABASE"]) as db:
            runs = db.execute("SELECT * FROM runs ORDER BY created DESC LIMIT 100").fetchall()
            counts = dict(
                db.execute("SELECT status, count(*) FROM runs GROUP BY status").fetchall()
            )
        return render_template("dashboard.html", runs=runs, counts=counts)

    @app.get("/new")
    def new():
        return render_template("new.html", values={}, error=None)

    @app.post("/runs")
    def submit():
        values = request.form
        ticker = values.get("ticker", "").strip().upper()
        day = values.get("trade_date", "")
        quick, deep = values.get("quick_model", "").strip(), values.get("deep_model", "").strip()
        error = None
        try:
            if not re.fullmatch(r"[A-Z0-9^][A-Z0-9.^=-]{0,19}", ticker):
                raise ValueError("Saisissez un symbole boursier valide, comme AAPL ou BRK-B.")
            parsed = date.fromisoformat(day)
            if parsed > date.today() or parsed < date(2000, 1, 1):
                raise ValueError("Choisissez une date d’analyse entre 2000 et aujourd’hui.")
            for model in (quick, deep):
                if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.:/-]{1,150}", model):
                    raise ValueError(
                        "Saisissez un identifiant de modèle OpenRouter au format fournisseur/modèle pour chaque niveau."
                    )
            rounds = int(values.get("rounds", "1"))
            if rounds not in (1, 2, 3):
                raise ValueError("Choisissez 1, 2 ou 3 tours de débat.")
            if not os.getenv("OPENROUTER_API_KEY"):
                raise ValueError(
                    "Ajoutez OPENROUTER_API_KEY sur le serveur avant de lancer une analyse."
                )
        except ValueError as exc:
            error = (
                str(exc)
                if str(exc) and not str(exc).startswith(("Invalid isoformat", "invalid literal"))
                else "Vérifiez la date et le nombre de tours de débat."
            )
        if error:
            return render_template("new.html", values=values, error=error), 400
        run_id = secrets.token_hex(12)
        with connect(app.config["DATABASE"]) as db:
            db.execute("BEGIN IMMEDIATE")
            if (
                db.execute(
                    "SELECT count(*) FROM runs WHERE status IN ('queued', 'running')"
                ).fetchone()[0]
                >= 10
            ):
                return render_template(
                    "new.html",
                    values=values,
                    error="La file d’attente est pleine. Attendez qu’une analyse se termine.",
                ), 429
            db.execute(
                """INSERT INTO runs
                (id,ticker,trade_date,quick_model,deep_model,rounds,creator,created,status)
                VALUES (?,?,?,?,?,?,?,?, 'queued')""",
                (
                    run_id,
                    ticker,
                    parsed.isoformat(),
                    quick,
                    deep,
                    rounds,
                    g.user,
                    datetime.now(UTC).isoformat(),
                ),
            )
        flash(
            "Analyse ajoutée à la file d’attente. Vous pouvez quitter cette page pendant le travail des agents."
        )
        return redirect(url_for("report", run_id=run_id))

    def get_run(run_id):
        with connect(app.config["DATABASE"]) as db:
            row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if not row:
            abort(404)
        return dict(row)

    @app.get("/runs/<run_id>")
    def report(run_id):
        run = get_run(run_id)
        return render_template(
            "report.html",
            run=run,
            reports=json.loads(run["reports"] or "{}"),
            sections=REPORT_SECTIONS,
        )

    @app.get("/api/runs/<run_id>")
    def run_status(run_id):
        run = get_run(run_id)
        return jsonify(status=run["status"], signal=run["signal"])

    @app.get("/runs/<run_id>/download")
    def download(run_id):
        run = get_run(run_id)
        if run["status"] != "completed":
            abort(409, "Ce rapport n’est pas encore terminé.")
        reports = json.loads(run["reports"] or "{}")
        text = f"# {run['ticker']} · {run['trade_date']}\n\nRecommandation : {rating_fr(run['signal'])}\n\n"
        text += (
            f"Modèle d’analyse : {run['quick_model']}\nModèle de gestion : {run['deep_model']}\n\n"
        )
        text += "\n\n".join(
            f"## {title}\n\n{reports[key]}"
            for key, title in REPORT_SECTIONS.items()
            if reports.get(key)
        )
        text += (
            "\n\n---\nAnalyse générée par IA. Ceci ne constitue pas un conseil en investissement.\n"
        )
        return Response(
            text,
            mimetype="text/markdown",
            headers={"Content-Disposition": f'attachment; filename="{run["id"]}.md"'},
        )

    @app.get("/settings")
    def settings():
        with connect(app.config["DATABASE"]) as db:
            users = db.execute("SELECT username FROM users ORDER BY username").fetchall()
        return render_template("settings.html", users=users)

    @app.errorhandler(400)
    @app.errorhandler(404)
    @app.errorhandler(409)
    @app.errorhandler(413)
    def error_page(error):
        titles = {
            400: "Requête invalide",
            404: "Page introuvable",
            409: "Rapport indisponible",
            413: "Formulaire trop volumineux",
        }
        descriptions = {
            400: "Vérifiez les informations saisies et réessayez.",
            404: "La page ou l’analyse demandée est introuvable.",
            409: "Ce rapport n’est pas encore disponible.",
            413: "Les données envoyées dépassent la taille autorisée.",
        }
        description = (
            descriptions[error.code]
            if error.description == type(error).description
            else error.description
        )
        return render_template(
            "error.html", error=error, error_title=titles[error.code], error_description=description
        ), error.code

    return app
