"""
Start the Excise Fee Estimator.

    uv run python run.py                 -> http://127.0.0.1:5000 (this computer only)
    HOST=0.0.0.0 uv run python run.py    -> also reachable from the office network

Needs DATABASE_URL (see .env.example). On Vercel the same `app` is loaded through app.py.
"""
import os

from backend import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", 5000)), debug=False)
