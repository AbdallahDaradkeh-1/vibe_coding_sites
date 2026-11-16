#!/usr/bin/env python3
"""Dream Bakeries website — dependency-free Python + SQLite application."""
from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import string
import time
from datetime import datetime, timezone
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

BASE_DIR = Path(__file__).resolve().parent
PUBLIC_DIR = BASE_DIR / "public"
DATA_DIR = BASE_DIR / "data"
DB_PATH = Path(os.environ.get("DATABASE_PATH", DATA_DIR / "dream_bakeries.sqlite3"))
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8000"))
SESSION_TTL = 60 * 60 * 10
PBKDF2_ITERATIONS = 310_000
SESSIONS: dict[str, dict] = {}

CATEGORIES = [
    ("المخبوزات", "bakery", "مخبوزات يومية وخيارات تناسب كل مائدة", "images/category-bread.svg"),
    ("المعجنات", "pastries", "مناقيش وفطائر بنكهات متنوعة", "images/category-pastries.svg"),
    ("الحلويات", "sweets", "حلويات وكيك للمشاركة والضيافة", "images/category-sweets.svg"),
    ("المطعم", "restaurant", "حمص وفلافل وأطباق شعبية", "images/category-restaurant.svg"),
]

PRODUCTS = {
    "bakery": [
        ("خبز عادي", "خبز يومي مناسب لمختلف الوجبات.", False),
        ("خبز حمام", "خبز طري بحجم مناسب للسندويشات والوجبات.", True),
        ("خبز كعك", "كعك للمائدة والفطور.", False),
    ],
    "pastries": [
        ("منقوشة زعتر", "منقوشة بنكهة الزعتر الشرقية.", True),
        ("جبنة بيضاء", "معجنات بحشوة الجبنة البيضاء.", False),
        ("جبنة صفراء", "معجنات بحشوة الجبنة الصفراء.", False),
        ("بيتزا", "قطعة بيتزا مناسبة لوجبة خفيفة.", True),
        ("سبانخ", "معجنات بحشوة السبانخ.", False),
        ("بطاطا", "معجنات بحشوة البطاطا.", False),
        ("محمرة", "معجنات بنكهة المحمرة.", False),
    ],
    "sweets": [
        ("غريبة", "حلوى تقليدية مناسبة للضيافة.", True),
        ("برازق", "برازق بطابع شرقي.", False),
        ("كيك تركي", "كيك تركي للحلو والضيافة.", True),
        ("بسبوسة", "حلوى البسبوسة المعروفة.", False),
        ("كيك", "كيك للمناسبات والضيافة.", True),
        ("كاسات جاتو", "حلوى كاسات بطبقات متنوعة.", False),
    ],
    "restaurant": [
        ("حمص", "طبق حمص ضمن قائمة المطعم.", True),
        ("فلافل", "فلافل ضمن قائمة المطعم.", True),
        ("فتة", "طبق فتة ضمن قائمة المطعم.", False),
        ("فول", "طبق فول ضمن قائمة المطعم.", False),
        ("مسبحة", "طبق مسبحة ضمن قائمة المطعم.", False),
        ("بطاطا", "بطاطا ضمن قائمة المطعم.", False),
    ],
}


def db_connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db() -> None:
    with db_connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            slug TEXT NOT NULL UNIQUE,
            description TEXT NOT NULL DEFAULT '',
            image_path TEXT NOT NULL DEFAULT 'images/category-bread.svg',
            sort_order INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE RESTRICT,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            price_jod REAL NULL,
            image_path TEXT NOT NULL DEFAULT 'images/category-bread.svg',
            is_available INTEGER NOT NULL DEFAULT 1,
            is_featured INTEGER NOT NULL DEFAULT 0,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS admin_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            public_ref TEXT NOT NULL UNIQUE,
            customer_name TEXT NOT NULL,
            phone TEXT NOT NULL,
            fulfillment_type TEXT NOT NULL CHECK (fulfillment_type IN ('delivery','pickup')),
            address TEXT NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'new',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
            product_id INTEGER NULL REFERENCES products(id) ON DELETE SET NULL,
            product_name TEXT NOT NULL,
            quantity INTEGER NOT NULL CHECK (quantity BETWEEN 1 AND 30)
        );
        CREATE INDEX IF NOT EXISTS idx_products_category ON products(category_id);
        CREATE INDEX IF NOT EXISTS idx_orders_created ON orders(created_at DESC);
        """)
        existing = db.execute("SELECT COUNT(*) FROM categories").fetchone()[0]
        if existing == 0:
            for idx, (name, slug, desc, image) in enumerate(CATEGORIES):
                db.execute("INSERT INTO categories(name,slug,description,image_path,sort_order) VALUES(?,?,?,?,?)",
                           (name, slug, desc, image, idx))
        product_count = db.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        if product_count == 0:
            cat_ids = {r["slug"]: r["id"] for r in db.execute("SELECT id,slug FROM categories")}
            for slug, entries in PRODUCTS.items():
                image = next((item[3] for item in CATEGORIES if item[1] == slug), "images/category-bread.svg")
                for idx, (name, desc, featured) in enumerate(entries):
                    db.execute("""INSERT INTO products(category_id,name,description,price_jod,image_path,is_available,is_featured,sort_order)
                                  VALUES(?,?,?,?,?,?,?,?)""",
                               (cat_ids[slug], name, desc, None, image, 1, int(featured), idx))


def password_record(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), PBKDF2_ITERATIONS)
    return digest.hex(), salt


def create_admin(username: str, password: str) -> None:
    if len(password) < 12:
        raise ValueError("يجب أن تتكون كلمة المرور من 12 خانة على الأقل.")
    if not username.strip():
        raise ValueError("اسم المستخدم مطلوب.")
    hashed, salt = password_record(password)
    with db_connect() as db:
        db.execute("INSERT INTO admin_users(username,password_hash,salt) VALUES(?,?,?)",
                   (username.strip(), hashed, salt))


def maybe_create_admin_from_env() -> None:
    username = os.environ.get("ADMIN_USERNAME")
    password = os.environ.get("ADMIN_PASSWORD")
    if username and password:
        with db_connect() as db:
            exists = db.execute("SELECT 1 FROM admin_users LIMIT 1").fetchone()
            if not exists:
                create_admin(username, password)
                print(f"Admin account created for username: {username}")


def parse_json_body(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", "0") or 0)
    if length > 4_000_000:
        raise ValueError("حجم الطلب أكبر من المسموح (4 ميغابايت).")
    raw = handler.rfile.read(length) if length else b"{}"
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("صيغة البيانات غير صحيحة.")
    if not isinstance(data, dict):
        raise ValueError("صيغة البيانات غير صحيحة.")
    return data


def clean_text(value, max_len: int = 500) -> str:
    if value is None:
        return ""
    value = str(value).strip()
    return value[:max_len]


def product_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"], "category_id": row["category_id"],
        "category_name": row["category_name"] if "category_name" in row.keys() else "",
        "category_slug": row["category_slug"] if "category_slug" in row.keys() else "",
        "name": row["name"], "description": row["description"],
        "price_jod": row["price_jod"], "image_path": row["image_path"],
        "is_available": bool(row["is_available"]), "is_featured": bool(row["is_featured"]),
        "sort_order": row["sort_order"],
    }


def get_products(db: sqlite3.Connection, include_unavailable: bool = True):
    sql = """SELECT p.*, c.name AS category_name, c.slug AS category_slug
             FROM products p JOIN categories c ON c.id=p.category_id"""
    if not include_unavailable:
        sql += " WHERE p.is_available=1"
    sql += " ORDER BY c.sort_order, p.sort_order, p.id"
    return [product_dict(r) for r in db.execute(sql).fetchall()]


class AppHandler(BaseHTTPRequestHandler):
    server_version = "DreamBakeries/1.0"

    def log_message(self, fmt, *args):
        print("[%s] %s" % (self.log_date_time_string(), fmt % args))

    def _headers(self, content_type="application/json; charset=utf-8", status=200, extra=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header("Cache-Control", "no-store" if content_type.startswith("application/json") else "public, max-age=3600")
        if extra:
            for key, val in extra:
                self.send_header(key, val)
        self.end_headers()

    def send_json(self, payload, status=200, extra=None):
        self._headers(status=status, extra=extra)
        self.wfile.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    def send_error_json(self, message, status=400):
        self.send_json({"ok": False, "error": message}, status)

    def get_cookie(self, name: str):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
            morsel = cookie.get(name)
            return morsel.value if morsel else None
        except Exception:
            return None

    def session(self, create=False):
        token = self.get_cookie("dream_session")
        current = SESSIONS.get(token) if token else None
        if current and current["expires"] < time.time():
            SESSIONS.pop(token, None)
            current = None
        if current:
            return token, current
        if not create:
            return None, None
        token = secrets.token_urlsafe(32)
        current = {"admin_id": None, "csrf": secrets.token_urlsafe(24), "expires": time.time() + SESSION_TTL}
        SESSIONS[token] = current
        return token, current

    def session_cookie_header(self, token, max_age=SESSION_TTL):
        secure = "; Secure" if os.environ.get("COOKIE_SECURE", "0") == "1" else ""
        return f"dream_session={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={max_age}{secure}"

    def require_csrf(self, session_data):
        supplied = self.headers.get("X-CSRF-Token", "")
        return bool(session_data and supplied and hmac.compare_digest(supplied, session_data.get("csrf", "")))

    def require_admin(self):
        token, data = self.session(False)
        if not data or not data.get("admin_id"):
            return None
        with db_connect() as db:
            user = db.execute("SELECT id,username FROM admin_users WHERE id=?", (data["admin_id"],)).fetchone()
        if not user:
            SESSIONS.pop(token, None)
            return None
        data["expires"] = time.time() + SESSION_TTL
        return dict(user)

    def serve_static(self, relative: str, content_type=None):
        rel = unquote(relative).lstrip("/")
        target = (PUBLIC_DIR / rel).resolve()
        if not target.is_relative_to(PUBLIC_DIR.resolve()) or not target.is_file():
            self.send_error(404)
            return
        suffix = target.suffix.lower()
        types = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
                 ".js": "application/javascript; charset=utf-8", ".svg": "image/svg+xml",
                 ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
                 ".ico": "image/x-icon", ".woff2": "font/woff2"}
        self._headers(content_type or types.get(suffix, "application/octet-stream"))
        self.wfile.write(target.read_bytes())

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/":
            self.serve_static("index.html")
            return
        if path == "/admin" or path == "/admin/":
            self.serve_static("admin.html")
            return
        if path == "/api/csrf":
            token, data = self.session(create=True)
            self._headers(extra=[("Set-Cookie", self.session_cookie_header(token))])
            self.wfile.write(json.dumps({"csrf_token": data["csrf"]}).encode())
            return
        if path == "/api/store":
            with db_connect() as db:
                categories = [dict(r) for r in db.execute("SELECT * FROM categories ORDER BY sort_order,id")]
                products = get_products(db, include_unavailable=False)
            self.send_json({"categories": categories, "products": products,
                            "business": {"name": "مخابز الأحلام", "phone": "0758795461",
                                         "address": "الأردن، عمّان، أبو نصير، حي الأمانة",
                                         "location_confirmed": False}})
            return
        if path == "/api/admin/me":
            user = self.require_admin()
            if not user:
                self.send_json({"authenticated": False}, 401)
            else:
                self.send_json({"authenticated": True, "user": user})
            return
        if path.startswith("/api/admin/"):
            user = self.require_admin()
            if not user:
                self.send_error_json("يلزم تسجيل الدخول أولاً.", 401)
                return
            if path == "/api/admin/dashboard":
                with db_connect() as db:
                    stats = {
                        "products": db.execute("SELECT COUNT(*) FROM products").fetchone()[0],
                        "available": db.execute("SELECT COUNT(*) FROM products WHERE is_available=1").fetchone()[0],
                        "new_orders": db.execute("SELECT COUNT(*) FROM orders WHERE status='new'").fetchone()[0],
                        "preparing": db.execute("SELECT COUNT(*) FROM orders WHERE status='preparing'").fetchone()[0],
                        "completed": db.execute("SELECT COUNT(*) FROM orders WHERE status='completed'").fetchone()[0],
                    }
                    recent = [dict(r) for r in db.execute("SELECT id,public_ref,customer_name,fulfillment_type,status,created_at FROM orders ORDER BY id DESC LIMIT 5")]
                self.send_json({"stats": stats, "recent_orders": recent})
                return
            if path == "/api/admin/products":
                with db_connect() as db:
                    self.send_json({"products": get_products(db, include_unavailable=True)})
                return
            if path == "/api/admin/categories":
                with db_connect() as db:
                    rows = [dict(r) for r in db.execute("SELECT * FROM categories ORDER BY sort_order,id")]
                self.send_json({"categories": rows})
                return
            if path == "/api/admin/orders":
                with db_connect() as db:
                    orders = []
                    for row in db.execute("SELECT * FROM orders ORDER BY id DESC").fetchall():
                        item = dict(row)
                        item["items"] = [dict(x) for x in db.execute("SELECT product_name,quantity FROM order_items WHERE order_id=?", (row["id"],))]
                        orders.append(item)
                self.send_json({"orders": orders})
                return
            self.send_error_json("المسار غير موجود.", 404)
            return
        if path.startswith("/public/"):
            self.serve_static(path[len("/public/"):])
            return
        self.send_error(404)

    def do_POST(self):
        path = urlparse(self.path).path
        token, session_data = self.session(create=True)
        # CSRF protection applies to state-changing requests, including public order submission.
        try:
            data = parse_json_body(self)
            if not self.require_csrf(session_data):
                self.send_error_json("انتهت صلاحية الجلسة. حدّث الصفحة وحاول مرة أخرى.", 403)
                return
            if path == "/api/orders":
                self.create_order(data)
                return
            if path == "/api/admin/login":
                username = clean_text(data.get("username"), 80)
                password = str(data.get("password", ""))
                with db_connect() as db:
                    user = db.execute("SELECT * FROM admin_users WHERE username=?", (username,)).fetchone()
                if not user:
                    self.send_error_json("اسم المستخدم أو كلمة المرور غير صحيحين.", 401)
                    return
                hashed, _ = password_record(password, user["salt"])
                if not hmac.compare_digest(hashed, user["password_hash"]):
                    self.send_error_json("اسم المستخدم أو كلمة المرور غير صحيحين.", 401)
                    return
                # Rotate the session token after successful authentication.
                SESSIONS.pop(token, None)
                new_token, new_data = self.session(create=True)
                new_data["admin_id"] = user["id"]
                self._headers(extra=[("Set-Cookie", self.session_cookie_header(new_token))])
                self.wfile.write(json.dumps({"ok": True, "username": username}).encode())
                return
            if path == "/api/admin/logout":
                user = self.require_admin()
                if not user:
                    self.send_error_json("يلزم تسجيل الدخول أولاً.", 401)
                    return
                SESSIONS.pop(token, None)
                self.send_json({"ok": True}, extra=[("Set-Cookie", self.session_cookie_header("", max_age=0))])
                return
            user = self.require_admin()
            if not user:
                self.send_error_json("يلزم تسجيل الدخول أولاً.", 401)
                return
            if path == "/api/admin/products":
                self.save_product(data)
                return
            if path == "/api/admin/upload-image":
                self.upload_image(data)
                return
            if path == "/api/admin/categories":
                name = clean_text(data.get("name"), 70)
                slug = clean_text(data.get("slug"), 70).lower()
                desc = clean_text(data.get("description"), 180)
                image = clean_text(data.get("image_path"), 180) or "images/category-bread.svg"
                if not name or not slug or not all(c in string.ascii_lowercase + string.digits + "-" for c in slug):
                    self.send_error_json("أدخل اسم القسم ومعرّفاً لاتينياً صالحاً.")
                    return
                with db_connect() as db:
                    try:
                        db.execute("INSERT INTO categories(name,slug,description,image_path,sort_order) VALUES(?,?,?,?,?)",
                                   (name, slug, desc, image, 99))
                    except sqlite3.IntegrityError:
                        self.send_error_json("معرّف القسم مستخدم مسبقاً.", 409)
                        return
                self.send_json({"ok": True}, 201)
                return
            self.send_error_json("المسار غير موجود.", 404)
        except ValueError as exc:
            self.send_error_json(str(exc), 400)
        except Exception as exc:
            print("POST error:", repr(exc))
            self.send_error_json("حدث خطأ داخلي. راجع سجل التشغيل.", 500)

    def do_PUT(self):
        self._admin_mutation("PUT")

    def do_PATCH(self):
        self._admin_mutation("PATCH")

    def do_DELETE(self):
        self._admin_mutation("DELETE")

    def _admin_mutation(self, method):
        path = urlparse(self.path).path
        token, session_data = self.session(False)
        if not self.require_csrf(session_data):
            self.send_error_json("انتهت صلاحية الجلسة. حدّث الصفحة وحاول مرة أخرى.", 403)
            return
        user = self.require_admin()
        if not user:
            self.send_error_json("يلزم تسجيل الدخول أولاً.", 401)
            return
        try:
            data = parse_json_body(self)
            if path.startswith("/api/admin/products/"):
                product_id = int(path.rsplit("/", 1)[1])
                if method == "PUT":
                    data["id"] = product_id
                    self.save_product(data)
                elif method == "DELETE":
                    with db_connect() as db:
                        db.execute("DELETE FROM products WHERE id=?", (product_id,))
                    self.send_json({"ok": True})
                return
            if path.startswith("/api/admin/orders/") and method == "PATCH":
                order_id = int(path.rsplit("/", 1)[1])
                status = clean_text(data.get("status"), 30)
                allowed = {"new", "accepted", "preparing", "ready", "completed", "cancelled"}
                if status not in allowed:
                    self.send_error_json("حالة الطلب غير معروفة.")
                    return
                with db_connect() as db:
                    cur = db.execute("UPDATE orders SET status=? WHERE id=?", (status, order_id))
                    if cur.rowcount == 0:
                        self.send_error_json("الطلب غير موجود.", 404)
                        return
                self.send_json({"ok": True})
                return
            if path.startswith("/api/admin/categories/"):
                category_id = int(path.rsplit("/", 1)[1])
                if method == "PUT":
                    name = clean_text(data.get("name"), 70)
                    slug = clean_text(data.get("slug"), 70).lower()
                    desc = clean_text(data.get("description"), 180)
                    image = clean_text(data.get("image_path"), 180) or "images/category-bread.svg"
                    if not name or not slug or not all(c in string.ascii_lowercase + string.digits + "-" for c in slug):
                        self.send_error_json("أدخل اسم القسم ومعرّفاً لاتينياً صالحاً.")
                        return
                    with db_connect() as db:
                        try:
                            cur = db.execute("UPDATE categories SET name=?,slug=?,description=?,image_path=? WHERE id=?",
                                             (name, slug, desc, image, category_id))
                        except sqlite3.IntegrityError:
                            self.send_error_json("معرّف القسم مستخدم مسبقاً.", 409)
                            return
                        if cur.rowcount == 0:
                            self.send_error_json("القسم غير موجود.", 404)
                            return
                    self.send_json({"ok": True})
                    return
                if method == "DELETE":
                    with db_connect() as db:
                        count = db.execute("SELECT COUNT(*) FROM products WHERE category_id=?", (category_id,)).fetchone()[0]
                        if count:
                            self.send_error_json("لا يمكن حذف قسم يحتوي على منتجات. انقل المنتجات أولاً.", 409)
                            return
                        db.execute("DELETE FROM categories WHERE id=?", (category_id,))
                    self.send_json({"ok": True})
                    return
            self.send_error_json("المسار غير موجود.", 404)
        except (ValueError, TypeError):
            self.send_error_json("المعرّف أو البيانات غير صحيحة.", 400)
        except Exception as exc:
            print(f"{method} error:", repr(exc))
            self.send_error_json("حدث خطأ داخلي. راجع سجل التشغيل.", 500)

    def upload_image(self, data):
        data_url = str(data.get("data_url", ""))
        if "," not in data_url or not data_url.startswith("data:image/"):
            self.send_error_json("ملف الصورة غير صالح.")
            return
        header, encoded = data_url.split(",", 1)
        mime_to_ext = {"data:image/jpeg;base64": ".jpg", "data:image/png;base64": ".png", "data:image/webp;base64": ".webp"}
        extension = mime_to_ext.get(header.lower())
        if not extension:
            self.send_error_json("الصيغ المسموحة هي JPG وPNG وWebP فقط.")
            return
        try:
            content = base64.b64decode(encoded, validate=True)
        except Exception:
            self.send_error_json("تعذر قراءة ملف الصورة.")
            return
        if not content or len(content) > 2 * 1024 * 1024:
            self.send_error_json("حجم الصورة يجب ألا يتجاوز 2 ميغابايت.")
            return
        signatures = {".jpg": content.startswith(b"\xff\xd8\xff"),
                      ".png": content.startswith(b"\x89PNG\r\n\x1a\n"),
                      ".webp": content.startswith(b"RIFF") and content[8:12] == b"WEBP"}
        if not signatures.get(extension, False):
            self.send_error_json("محتوى الملف لا يطابق صيغة الصورة المحددة.")
            return
        upload_dir = PUBLIC_DIR / "images" / "uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        filename = secrets.token_hex(12) + extension
        (upload_dir / filename).write_bytes(content)
        self.send_json({"ok": True, "image_path": f"images/uploads/{filename}"}, 201)

    def save_product(self, data):
        name = clean_text(data.get("name"), 100)
        description = clean_text(data.get("description"), 300)
        image_path = clean_text(data.get("image_path"), 180) or "images/category-bread.svg"
        if not image_path.startswith("images/") or ".." in Path(image_path).parts or "\\" in image_path:
            self.send_error_json("مسار الصورة يجب أن يكون داخل مجلد images.")
            return
        image_file = (PUBLIC_DIR / image_path).resolve()
        if not image_file.is_relative_to((PUBLIC_DIR / "images").resolve()) or not image_file.is_file():
            self.send_error_json("الصورة المحددة غير موجودة داخل مجلد الصور.")
            return
        try:
            category_id = int(data.get("category_id"))
            sort_order = max(0, min(9999, int(data.get("sort_order", 0))))
        except (TypeError, ValueError):
            self.send_error_json("اختر تصنيفاً صالحاً.")
            return
        price_value = data.get("price_jod")
        if price_value in (None, ""):
            price = None
        else:
            try:
                price = round(float(price_value), 3)
                if price < 0 or price > 10000:
                    raise ValueError
            except (TypeError, ValueError):
                self.send_error_json("السعر يجب أن يكون رقماً موجباً صالحاً أو فارغاً.")
                return
        if not name:
            self.send_error_json("اسم المنتج مطلوب.")
            return
        available = 1 if data.get("is_available", True) in (True, 1, "1", "true", "on") else 0
        featured = 1 if data.get("is_featured", False) in (True, 1, "1", "true", "on") else 0
        with db_connect() as db:
            if not db.execute("SELECT 1 FROM categories WHERE id=?", (category_id,)).fetchone():
                self.send_error_json("التصنيف المحدد غير موجود.", 400)
                return
            product_id = data.get("id")
            if product_id:
                db.execute("""UPDATE products SET category_id=?,name=?,description=?,price_jod=?,image_path=?,is_available=?,is_featured=?,sort_order=? WHERE id=?""",
                           (category_id, name, description, price, image_path, available, featured, sort_order, int(product_id)))
            else:
                db.execute("""INSERT INTO products(category_id,name,description,price_jod,image_path,is_available,is_featured,sort_order)
                              VALUES(?,?,?,?,?,?,?,?)""",
                           (category_id, name, description, price, image_path, available, featured, sort_order))
        self.send_json({"ok": True}, 201 if not product_id else 200)

    def create_order(self, data):
        customer_name = clean_text(data.get("customer_name"), 100)
        phone = clean_text(data.get("phone"), 30)
        fulfillment = clean_text(data.get("fulfillment_type"), 20)
        address = clean_text(data.get("address"), 300)
        notes = clean_text(data.get("notes"), 500)
        items = data.get("items")
        if len(customer_name) < 2:
            self.send_error_json("يرجى إدخال الاسم بشكل صحيح.")
            return
        digits = "".join(ch for ch in phone if ch.isdigit())
        if len(digits) < 9 or len(digits) > 15:
            self.send_error_json("يرجى إدخال رقم هاتف صحيح.")
            return
        if fulfillment not in ("delivery", "pickup"):
            self.send_error_json("اختر التوصيل أو الاستلام.")
            return
        if fulfillment == "delivery" and len(address) < 5:
            self.send_error_json("يرجى إدخال عنوان التوصيل.")
            return
        if not isinstance(items, list) or not items or len(items) > 30:
            self.send_error_json("السلة فارغة أو تحتوي على عدد كبير من المنتجات.")
            return
        ref = "DA-" + "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(7))
        with db_connect() as db:
            prepared = []
            for entry in items:
                try:
                    pid = int(entry.get("product_id"))
                    qty = int(entry.get("quantity"))
                except (TypeError, ValueError, AttributeError):
                    self.send_error_json("بيانات أحد المنتجات غير صالحة.")
                    return
                if qty < 1 or qty > 30:
                    self.send_error_json("الكمية يجب أن تكون بين 1 و30.")
                    return
                product = db.execute("SELECT id,name,is_available FROM products WHERE id=?", (pid,)).fetchone()
                if not product or not product["is_available"]:
                    self.send_error_json("أحد المنتجات لم يعد متوفراً. حدّث السلة وحاول مجدداً.", 409)
                    return
                prepared.append((pid, product["name"], qty))
            cur = db.execute("""INSERT INTO orders(public_ref,customer_name,phone,fulfillment_type,address,notes,status)
                              VALUES(?,?,?,?,?,?, 'new')""",
                             (ref, customer_name, phone, fulfillment, address, notes))
            order_id = cur.lastrowid
            for pid, name, qty in prepared:
                db.execute("INSERT INTO order_items(order_id,product_id,product_name,quantity) VALUES(?,?,?,?)",
                           (order_id, pid, name, qty))
        self.send_json({"ok": True, "order_ref": ref, "message": "تم استلام طلبك لإرساله إلى المخبز للمراجعة والتأكيد."}, 201)


def run_server():
    init_db()
    maybe_create_admin_from_env()
    server = ThreadingHTTPServer((HOST, PORT), AppHandler)
    print("\nمخابز الأحلام تعمل الآن:")
    print(f"  الموقع: http://{HOST}:{PORT}")
    print(f"  لوحة الإدارة: http://{HOST}:{PORT}/admin")
    print(f"  قاعدة البيانات: {DB_PATH}")
    print("  لإيقاف الخادم اضغط Ctrl+C\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nتم إيقاف الخادم.")
    finally:
        server.server_close()


def main():
    parser = argparse.ArgumentParser(description="Dream Bakeries website")
    parser.add_argument("--create-admin", action="store_true", help="Create the first admin user interactively")
    args = parser.parse_args()
    init_db()
    if args.create_admin:
        with db_connect() as db:
            existing = db.execute("SELECT COUNT(*) FROM admin_users").fetchone()[0]
        if existing:
            print("يوجد حساب مدير بالفعل. لم يتم إنشاء حساب جديد.")
            return
        username = input("اسم المستخدم للمدير: ").strip()
        password = getpass.getpass("كلمة المرور (12 خانة على الأقل): ")
        confirm = getpass.getpass("أعد كلمة المرور: ")
        if password != confirm:
            print("كلمتا المرور غير متطابقتين.")
            return
        try:
            create_admin(username, password)
            print("تم إنشاء حساب المدير بنجاح.")
        except (ValueError, sqlite3.IntegrityError) as exc:
            print("تعذر إنشاء الحساب:", exc)
        return
    run_server()


if __name__ == "__main__":
    main()
