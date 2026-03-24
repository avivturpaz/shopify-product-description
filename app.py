import json
import os
import re
import sqlite3
from datetime import datetime, timezone

from flask import Flask, jsonify, redirect, render_template, request, url_for
from werkzeug.exceptions import HTTPException


required = ["POLAR_PRODUCT_ID", "APP_SECRET_KEY"]
missing = [v for v in required if not os.environ.get(v)]
if missing:
    raise RuntimeError(f"Missing env vars: {missing}")


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data.db")

app = Flask(__name__)
app.secret_key = os.environ["APP_SECRET_KEY"]


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
        conn.commit()
    finally:
        conn.close()


def clean_text(value, max_length=4000):
    if value is None:
        return ""
    value = str(value).strip()
    value = re.sub(r"\s+", " ", value)
    return value[:max_length]


def split_features(specs):
    raw = clean_text(specs)
    if not raw:
        return []

    candidates = []
    for chunk in re.split(r"[\n\r;]+", raw):
        chunk = chunk.strip()
        if not chunk:
            continue
        if chunk.startswith(("-", "•", "*")):
            chunk = chunk[1:].strip()
        parts = [part.strip() for part in re.split(r",\s+", chunk) if part.strip()]
        if len(parts) > 1 and len(chunk) < 180:
            candidates.extend(parts)
        else:
            candidates.append(chunk)

    features = []
    seen = set()
    for item in candidates:
        normalized = re.sub(r"\s+", " ", item).strip(" .")
        if len(normalized) < 3:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        features.append(normalized)
        if len(features) == 5:
            break
    return features


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


def summarize_benefits(title, specs, audience):
    features = split_features(specs)
    audience_text = f"for {audience}" if audience else "for Shopify merchants"
    title_text = title.strip().rstrip(".")
    intro = (
        f"{title_text} is built {audience_text} who need product copy that reads cleanly, "
        f"supports SEO, and makes the offer easier to buy."
    )
    if features:
        intro += f" It highlights {features[0].lower()} and keeps the message focused on shopper value."
    return intro


def format_feature_bullets(features, tone):
    if not features:
        fallback = {
            "professional": "Clear positioning, polished structure, and keyword-aware copy.",
            "casual": "Easy-to-read copy that sounds human and converts better.",
            "urgent": "Fast-moving copy that makes the next step obvious.",
        }
        return [fallback[tone]]

    bullets = []
    for feature in features[:4]:
        bullets.append(feature[0].upper() + feature[1:] if feature else feature)
    return bullets


def generate_description(title, specs, tone, audience=""):
    features = split_features(specs)
    benefits = summarize_benefits(title, specs, audience)
    bullets = format_feature_bullets(features, tone)
    keyword_focus = ", ".join(extract_keywords(title, specs)[:5])

    if tone == "professional":
        lead = (
            f"{title} delivers a polished product description designed to improve clarity, "
            f"reinforce trust, and support search visibility."
        )
        closer = "Use this version when you want the listing to feel credible, complete, and ready for conversion."
    elif tone == "casual":
        lead = (
            f"{title} gets a friendlier, more natural description that sounds like a helpful recommendation, "
            f"not a block of marketing copy."
        )
        closer = "Use this version when you want shoppers to feel like they already understand the value."
    else:
        lead = (
            f"{title} gets an urgency-led description that pushes the shopper toward action without losing the key benefits."
        )
        closer = "Use this version when you want to create momentum and reduce hesitation."

    lines = [lead, "", benefits, "", "Highlights:"]
    lines.extend([f"- {bullet}" for bullet in bullets])
    lines.extend(
        [
            "",
            f"SEO focus: {keyword_focus}" if keyword_focus else "SEO focus: conversion-ready product language",
            "",
            closer,
        ]
    )
    return "\n".join(lines).strip()


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
    return render_template(
        "index.html",
        plausible_domain=os.environ.get("PLAUSIBLE_DOMAIN", ""),
        sample_tones=build_response(
            "Premium Stainless Steel Water Bottle",
            "Insulated, leak-proof lid, 24-hour cold retention, BPA-free, 32 oz capacity",
            "busy shoppers",
            0,
        )["tones"],
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

    result = build_response(title, specs, audience, 0)
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

    result = build_response(title, specs, audience, row_id)
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
