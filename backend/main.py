import json
from datetime import date
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.data import TRAVEL_OPTIONS

BASE_DIR = Path(__file__).resolve().parent
BOOKINGS_FILE = BASE_DIR / "bookings.json"

app = FastAPI(title="Travel Booking Demo")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


def read_bookings():
    if not BOOKINGS_FILE.exists():
        return []
    return json.loads(BOOKINGS_FILE.read_text(encoding="utf-8"))


def save_booking(booking):
    bookings = read_bookings()
    bookings.append(booking)
    BOOKINGS_FILE.write_text(json.dumps(bookings, indent=2), encoding="utf-8")


def find_option(option_id: str):
    return next((item for item in TRAVEL_OPTIONS if item["id"] == option_id), None)


@app.get("/")
def home(request: Request):
    return templates.TemplateResponse(request, "index.html", {"today": date.today().isoformat()})


@app.get("/search")
def search(request: Request, destination: str = "", travel_date: str = ""):
    destination = destination.strip().lower()
    results = [item for item in TRAVEL_OPTIONS if not destination or destination in item["to_city"].lower()]
    return templates.TemplateResponse(request, "search.html", {
        "results": results,
        "destination": destination.title(),
        "travel_date": travel_date,
    })


@app.get("/book/{option_id}")
def booking_form(request: Request, option_id: str):
    option = find_option(option_id)
    if not option:
        raise HTTPException(status_code=404, detail="Travel option not found")
    return templates.TemplateResponse(request, "booking_form.html", {"option": option})


@app.post("/book/{option_id}")
def create_booking(option_id: str, name: str = Form(...), email: str = Form(...), phone: str = Form(...)):
    option = find_option(option_id)
    if not option:
        raise HTTPException(status_code=404, detail="Travel option not found")
    booking = {
        "booking_id": f"BK-{uuid4().hex[:6].upper()}",
        "customer_name": name.strip(),
        "email": email.strip(),
        "phone": phone.strip(),
        "option": option,
        "status": "Confirmed",
    }
    save_booking(booking)
    return RedirectResponse(url=f"/confirmation/{booking['booking_id']}", status_code=303)


@app.get("/confirmation/{booking_id}")
def confirmation(request: Request, booking_id: str):
    booking = next((item for item in read_bookings() if item["booking_id"] == booking_id), None)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    return templates.TemplateResponse(request, "confirmation.html", {"booking": booking})


@app.get("/bookings")
def bookings(request: Request):
    return templates.TemplateResponse(request, "bookings.html", {"bookings": list(reversed(read_bookings()))})