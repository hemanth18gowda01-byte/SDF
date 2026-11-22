import hashlib
import json
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Generator
from uuid import uuid4

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.data import TRAVEL_OPTIONS

BASE_DIR = Path(__file__).resolve().parent
BOOKINGS_FILE = Path(os.environ.get("TRAVELGO_BOOKINGS", BASE_DIR / "bookings.json"))
DATABASE_FILE = Path(os.environ.get("TRAVELGO_DATABASE", BASE_DIR / "travelgo.sqlite3"))
SESSION_COOKIE = "travelgo_session"
SESSION_LIFETIME = 30 * 24 * 60 * 60

app = FastAPI(title="Travel Booking Demo")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


@contextmanager
def database() -> Generator[sqlite3.Connection, None, None]:
    connection = sqlite3.connect(DATABASE_FILE)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def initialize_database() -> None:
    with database() as connection:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                phone TEXT NOT NULL,
                password_salt TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                expires_at INTEGER NOT NULL
            );
        """)


initialize_database()


def password_digest(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 310_000)


def current_user(request: Request) -> dict | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with database() as connection:
        user = connection.execute(
            """SELECT users.id, users.name, users.email, users.phone, users.created_at
               FROM sessions JOIN users ON users.id = sessions.user_id
               WHERE sessions.token_hash = ? AND sessions.expires_at > ?""",
            (token_hash, int(time.time())),
        ).fetchone()
    return dict(user) if user else None


def set_login_cookie(response: RedirectResponse, user_id: int, secure: bool) -> None:
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    expires_at = int(time.time()) + SESSION_LIFETIME
    with database() as connection:
        connection.execute(
            "INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
            (token_hash, user_id, expires_at),
        )
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_LIFETIME,
        httponly=True,
        samesite="lax",
        secure=secure,
    )


def page(
    request: Request,
    template_name: str,
    context: dict | None = None,
    status_code: int = 200,
):
    template_context = dict(context or {})
    template_context["current_user"] = current_user(request)
    return templates.TemplateResponse(
        request, template_name, template_context, status_code=status_code
    )


def local_redirect(path: str) -> str:
    if path.startswith("/") and not path.startswith("//") and "\\" not in path:
        return path
    return "/profile"


def read_bookings():
    if not BOOKINGS_FILE.exists():
        return []
    return json.loads(BOOKINGS_FILE.read_text(encoding="utf-8"))


def read_user_bookings(user_id: int):
    return [
        booking for booking in reversed(read_bookings())
        if booking.get("user_id") == user_id
    ]


def save_booking(booking: dict) -> None:
    bookings = read_bookings()
    bookings.append(booking)
    BOOKINGS_FILE.write_text(json.dumps(bookings, indent=2), encoding="utf-8")


def find_option(option_id: str):
    return next((item for item in TRAVEL_OPTIONS if item["id"] == option_id), None)


@app.get("/")
def home(request: Request):
    return page(request, "index.html", {"today": date.today().isoformat()})


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/register")
def register_page(request: Request):
    if current_user(request):
        return RedirectResponse(url="/profile", status_code=303)
    return page(request, "register.html", {})


@app.post("/register")
def register(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    phone: str = Form(...),
    password: str = Form(...),
):
    name = name.strip()
    email = email.strip().lower()
    phone = phone.strip()
    if not name or "@" not in email or len(phone) != 10 or not phone.isdigit():
        return page(
            request,
            "register.html",
            {"error": "Enter a valid name, email, and 10-digit phone number."},
            status_code=400,
        )
    if len(password) < 8:
        return page(
            request,
            "register.html",
            {"error": "Your password must be at least 8 characters."},
            status_code=400,
        )

    salt = secrets.token_bytes(16)
    try:
        with database() as connection:
            cursor = connection.execute(
                """INSERT INTO users (name, email, phone, password_salt, password_hash)
                   VALUES (?, ?, ?, ?, ?)""",
                (name, email, phone, salt.hex(), password_digest(password, salt).hex()),
            )
            user_id = cursor.lastrowid
            if user_id is None:
                raise RuntimeError("Account creation did not return a user ID.")
    except sqlite3.IntegrityError:
        return page(
            request,
            "register.html",
            {"error": "An account with that email already exists."},
            status_code=400,
        )

    response = RedirectResponse(url="/profile", status_code=303)
    set_login_cookie(response, user_id, request.url.scheme == "https")
    return response


@app.get("/login")
def login_page(request: Request, next: str = ""):
    if current_user(request):
        return RedirectResponse(url="/profile", status_code=303)
    return page(request, "login.html", {"next_path": local_redirect(next)})


@app.post("/login")
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    next: str = Form(""),
):
    with database() as connection:
        user = connection.execute(
            "SELECT id, password_salt, password_hash FROM users WHERE email = ?",
            (email.strip().lower(),),
        ).fetchone()
    if (
        not user
        or not secrets.compare_digest(
            password_digest(password, bytes.fromhex(user["password_salt"])).hex(),
            user["password_hash"],
        )
    ):
        return page(
            request,
            "login.html",
            {"error": "Email or password is incorrect.", "next_path": local_redirect(next)},
            status_code=401,
        )

    response = RedirectResponse(url=local_redirect(next), status_code=303)
    set_login_cookie(response, user["id"], request.url.scheme == "https")
    return response


@app.post("/logout")
def logout(request: Request):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with database() as connection:
            connection.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    return response


@app.get("/profile")
def profile(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse(url="/login?next=/profile", status_code=303)
    return page(
        request,
        "profile.html",
        {"user": user, "bookings": read_user_bookings(user["id"])},
    )


@app.get("/search")
def search(request: Request, destination: str = "", travel_date: str = "", travel_type: str = "all"):
    destination = destination.strip().lower()
    if travel_type not in {"all", "flight", "hotel"}:
        travel_type = "all"
    results = [
        item for item in TRAVEL_OPTIONS
        if (not destination or destination in item["to_city"].lower())
        and (not travel_date or item["date"] == travel_date)
        and (travel_type == "all" or item["type"].lower() == travel_type)
    ]
    return page(request, "search.html", {
        "results": results,
        "destination": destination.title(),
        "travel_date": travel_date,
        "travel_type": travel_type,
    })


@app.get("/book/{option_id}")
def booking_form(request: Request, option_id: str):
    user = current_user(request)
    if not user:
        return RedirectResponse(url=f"/login?next=/book/{option_id}", status_code=303)
    option = find_option(option_id)
    if not option:
        raise HTTPException(status_code=404, detail="Travel option not found")
    return page(request, "booking_form.html", {"option": option, "user": user})


@app.post("/book/{option_id}")
def create_booking(
    request: Request,
    option_id: str,
    name: str = Form(...),
    email: str = Form(...),
    phone: str = Form(...),
):
    user = current_user(request)
    if not user:
        return RedirectResponse(url=f"/login?next=/book/{option_id}", status_code=303)
    option = find_option(option_id)
    if not option:
        raise HTTPException(status_code=404, detail="Travel option not found")
    name = name.strip()
    email = email.strip()
    phone = phone.strip()
    if not name or "@" not in email or len(phone) != 10 or not phone.isdigit():
        raise HTTPException(status_code=400, detail="Enter valid traveller details and a 10-digit phone number.")
    booking = {
        "booking_id": f"BK-{uuid4().hex[:6].upper()}",
        "customer_name": name,
        "email": email,
        "phone": phone,
        "option": option,
        "status": "Confirmed",
        "user_id": user["id"],
    }
    save_booking(booking)
    return RedirectResponse(url=f"/confirmation/{booking['booking_id']}", status_code=303)


@app.get("/confirmation/{booking_id}")
def confirmation(request: Request, booking_id: str):
    user = current_user(request)
    if not user:
        return RedirectResponse(url=f"/login?next=/confirmation/{booking_id}", status_code=303)
    booking = next(
        (
            item for item in read_bookings()
            if item["booking_id"] == booking_id and item.get("user_id") == user["id"]
        ),
        None,
    )
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    return page(request, "confirmation.html", {"booking": booking})


@app.get("/bookings")
def bookings(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse(url="/login?next=/bookings", status_code=303)
    return page(request, "bookings.html", {"bookings": read_user_bookings(user["id"])})