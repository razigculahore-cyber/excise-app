"""Kept so `python app.py` still works. The app now lives in backend/; see run.py."""
import os

from run import app

if __name__ == "__main__":
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", 5000)), debug=False)
