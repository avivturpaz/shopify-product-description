import json
import logging
import os
import re
import sqlite3
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO)

from flask import Flask, jsonify, redirect, render_template, request, url_for
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from groq import Groq
from werkzeug.exceptions import HTTPException

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data.db")

_PM_DB_PATH = os.environ.get("DB_PATH", os.path.expanduser("~/projects/venture/data/venture.db"))


def write_pm_alert(product, alert_type, message):
    try:
        conn = sqlite3.connect(_PM_DB_PATH)
        conn.execute(
            "INSERT INTO pm_alerts (product, alert_type, message) VALUES (?, ?, ?)",
            (product, alert_type, message),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass

app = Flask(__name__)
required = ["POLAR_PRODUCT_ID", "APP_SECRET_KEY"]
missing = [v for v in required if not os.environ.get(v)]
if missing:
    app.logger.error("Missing env vars at startup: %s", missing)
    if os.environ.get("STRICT_ENV_VALIDATION") == "1":
        raise RuntimeError(f"Missing env vars: {missing}")

app.secret_key = os.environ.get("APP_SECRET_KEY", "dev-only-secret-key")

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = "llama-3.3-70b-versatile"
PRODUCT_NAME = "shopify-product-description"

limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)

# Track daily limit hits for aggregate alert
_free_limit_hits_key = {}


def _is_paid() -> bool:
    from flask import session
    return session.get("paid") is True


def _get_ip() -> str:
    return request.headers.get("X-Forwarded-For", request.remote_addr) or "unknown"


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS generations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_title TEXT NOT NULL,
                product_specs TEXT NOT NULL,
                target_audience TEXT,
                output_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_limit_hits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ip TEXT NOT NULL,
                date TEXT NOT NULL
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def clean_text(value, max_length=4000):
    if value is None:
        return ""
    value = str(value).strip()
    value = re.sub(r"\s+", " ", value)
    return value[:max_length]


def generate_description(title: str, specs: str, tone: str, audience: str = "") -> str:
    """Call Groq to generate a Shopify product description."""
    logging.info("Received request: product_name=%s, details=%s", title, specs[:80])

    if not GROQ_API_KEY:
        logging.error("Error: GROQ_API_KEY not set")
        write_pm_alert(PRODUCT_NAME, "api_error", "GROQ_API_KEY not set")
        return "Could not generate description. Please try again."

    audience_line = f"Target audience: {audience}\n" if audience else ""
    user_prompt = (
        f"Product: {title}\n"
        f"Details: {specs}\n"
        f"{audience_line}"
        f"Tone: {tone}\n\n"
        "Write a Shopify product description."
    )

    try:
        logging.info("Calling Groq... (tone=%s)", tone)
        client = Groq(api_key=GROQ_API_KEY)
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "You are an expert Shopify copywriter. Write compelling product descriptions that convert browsers into buyers.",
                },
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=1024,
            temperature=0.7,
        )
        result = response.choices[0].message.content.strip()
        logging.info("Groq response received: %s", result[:100])
        return result
    except Exception as e:
        logging.error("Error: %s", e)
        write_pm_alert(PRODUCT_NAME, "api_error", str(e))
        return "Could not generate description. Please try again."


def extract_keywords(title, specs):
    stopwords = {
        "the", "and", "for", "with", "from", "that", "this", "your", "into", "its",
        "are", "will", "you", "use", "used", "more", "less", "best", "shopify",
        "product", "description", "descriptions", "generator", "specs", "spec",
    }
    tokens = []
    for text in (title, specs):
        for word in re.findall(r"[A-Za-z0-9]+", text.lower()):
            if len(word) < 3 or word in stopwords:
                continue
            if word not in tokens:
                tokens.append(word)
    return tokens[:8]


def build_response(title, specs, audience, row_id):
    descriptions = {
        "professional": generate_description(title, specs, "professional", audience),
        "casual": generate_description(title, specs, "casual", audience),
        "urgent": generate_description(title, specs, "urgent", audience),
    }
    keywords = extract_keywords(title, specs)
    seo_title = f"{title} | SEO Product Description Generator"
    meta_description = (
        f"Generate SEO-optimized Shopify product descriptions for {title} in professional, casual, and urgent tones."
    )
    if len(meta_description) > 160:
        meta_description = meta_description[:157].rstrip() + "..."

    return {
        "success": True,
        "id": row_id,
        "title": title,
        "target_audience": audience,
        "tones": descriptions,
        "seo": {
            "meta_title": seo_title,
            "meta_description": meta_description,
            "keywords": keywords,
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def json_error(message, status=400, **extra):
    payload = {"success": False, "error": message}
    payload.update(extra)
    return jsonify(payload), status


@app.before_request
def log_request():
    app.logger.info(
        "%s %s from %s",
        request.method,
        request.path,
        request.headers.get("X-Forwarded-For", request.remote_addr),
    )


@app.after_request
def log_response(response):
    app.logger.info("%s %s -> %s", request.method, request.path, response.status_code)
    return response


@app.errorhandler(HTTPException)
def handle_http_exception(exc):
    app.logger.error("HTTP error on %s: %s", request.path, exc, exc_info=True)
    return json_error(exc.description or exc.name, status=exc.code or 500)


@app.errorhandler(Exception)
def handle_exception(exc):
    app.logger.error("Unhandled error on %s: %s", request.path, exc, exc_info=True)
    return json_error("Internal server error", status=500)


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/")
def index():
    # Build sample tones using static text (avoid Groq calls on page load)
    sample_tones = {
        "professional": "Premium Stainless Steel Water Bottle delivers a polished product description designed to improve clarity, reinforce trust, and support search visibility.",
        "casual": "Premium Stainless Steel Water Bottle gets a friendlier, more natural description that sounds like a helpful recommendation.",
        "urgent": "Premium Stainless Steel Water Bottle gets an urgency-led description that pushes the shopper toward action.",
    }
    return render_template(
        "index.html",
        plausible_domain=os.environ.get("PLAUSIBLE_DOMAIN", ""),
        sample_tones=sample_tones,
    )


@app.route("/submit", methods=["POST"])
def submit():
    try:
        payload = request.get_json(silent=True) or request.form.to_dict(flat=True)
    except Exception as exc:
        app.logger.error("Failed to parse request body: %s", exc, exc_info=True)
        return json_error("Invalid request body", status=400)

    title = clean_text(payload.get("title", ""), max_length=140)
    specs = clean_text(payload.get("specs", ""), max_length=4000)
    audience = clean_text(payload.get("audience", ""), max_length=160)

    if not title:
        return json_error("Product title is required", status=400)
    if not specs:
        return json_error("Product specs are required", status=400)

    ip = _get_ip()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if _is_paid():
        # Paid: unlimited, but alert on heavy use
        conn = get_db()
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM generations WHERE created_at >= ?",
                (today,),
            ).fetchone()[0]
        finally:
            conn.close()
        if count >= 45:
            write_pm_alert(
                PRODUCT_NAME,
                "usage_warning",
                f"IP {ip} reached 45 generations today",
            )
    else:
        # Free: 1 generation per IP per day
        conn = get_db()
        try:
            used = conn.execute(
                "SELECT COUNT(*) FROM generations WHERE created_at >= ? AND json_extract(output_json, '$.ip') = ?",
                (today, ip),
            ).fetchone()[0]
        finally:
            conn.close()

        if used >= 1:
            # Track aggregate free limit hits for the day
            conn = get_db()
            try:
                conn.execute(
                    "INSERT INTO daily_limit_hits (ip, date) VALUES (?, ?)",
                    (ip, today),
                )
                conn.commit()
                hit_count = conn.execute(
                    "SELECT COUNT(DISTINCT ip) FROM daily_limit_hits WHERE date = ?",
                    (today,),
                ).fetchone()[0]
            finally:
                conn.close()

            if hit_count >= 20:
                write_pm_alert(
                    PRODUCT_NAME,
                    "info",
                    "20+ free users hit limit today",
                )

            polar_id = os.environ.get("POLAR_PRODUCT_ID", "").strip()
            pay_url = f"https://buy.polar.sh/{polar_id}" if polar_id else "/pay"
            return json_error(
                f"You've used your free generation. Get unlimited access for $15.",
                status=429,
                pay_url=pay_url,
            )

    result = build_response(title, specs, audience, 0)
    # Embed IP for free-tier tracking
    result["ip"] = ip

    conn = get_db()
    try:
        cursor = conn.execute(
            """
            INSERT INTO generations (product_title, product_specs, target_audience, output_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                title,
                specs,
                audience,
                json.dumps(result, ensure_ascii=False),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
        row_id = cursor.lastrowid
    finally:
        conn.close()

    result["id"] = row_id
    result.pop("ip", None)

    conn = get_db()
    try:
        conn.execute(
            "UPDATE generations SET output_json = ? WHERE id = ?",
            (json.dumps(result, ensure_ascii=False), row_id),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(result)


@app.route("/pay")
def pay():
    product_id = os.environ.get("POLAR_PRODUCT_ID", "").strip()
    if not product_id:
        return json_error("POLAR_PRODUCT_ID is required", status=500)
    return redirect(f"https://buy.polar.sh/{product_id}", code=302)


@app.route("/success")
def success():
    return render_template(
        "success.html",
        plausible_domain=os.environ.get("PLAUSIBLE_DOMAIN", ""),
    )


@app.route("/cancel")
def cancel():
    return render_template(
        "cancel.html",
        plausible_domain=os.environ.get("PLAUSIBLE_DOMAIN", ""),
    )


init_db()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
