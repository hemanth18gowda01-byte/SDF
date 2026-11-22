# TravelGo

A small FastAPI travel-booking assignment project with sample flights and hotels, account registration and login, profile pages, and a per-user trip history. It is a demo: bookings confirm immediately and no payment is processed.

## Run locally

```powershell
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000. Create an account to book a trip and view it on your profile. Sample travel options can be filtered by destination, date, and flights or hotels.

Account credentials and login sessions are stored in `app/travelgo.sqlite3`; bookings are stored in `app/bookings.json`. These local data files are created automatically when the app is used.
Set `TRAVELGO_DATABASE` and `TRAVELGO_BOOKINGS` to change those file locations.

## Deploy to Render

The root `render.yaml` defines a free Python web service. Push this repository to GitHub, then in Render choose **New → Blueprint**, select the repository, and apply the blueprint. Render installs `requirements.txt`, starts Uvicorn on its assigned port, and checks `/health`.

**Demo storage note:** Render's free web-service filesystem is ephemeral. The SQLite accounts/sessions and JSON bookings can be lost when the service spins down, restarts, or redeploys. For persistent data, use a paid service with a persistent disk and set both `TRAVELGO_DATABASE` and `TRAVELGO_BOOKINGS` to files under the disk's mount path (for example `/var/data/travelgo.sqlite3` and `/var/data/bookings.json`).