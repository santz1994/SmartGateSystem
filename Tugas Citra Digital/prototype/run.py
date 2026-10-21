"""Titik masuk prototipe.

    python run.py                 # http://127.0.0.1:5000
    python run.py --port 8080
    python run.py --reset-db      # hapus & seed ulang database
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def main() -> None:
    parser = argparse.ArgumentParser(description="Prototipe Smart Gate System")
    parser.add_argument("--host", default=os.getenv("SGS_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("SGS_PORT", "5000")))
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--reset-db", action="store_true", help="Hapus dan seed ulang database")
    parser.add_argument("--prod", action="store_true", help="Sajikan lewat waitress (server produksi)")
    args = parser.parse_args()

    from app import db

    if args.reset_db:
        db.init_db(force=True)
        print("Database direset.")

    from app.web import create_app

    app = create_app()
    if args.prod:
        from waitress import serve

        print(f"Smart Gate prototype (waitress) -> http://{args.host}:{args.port}")
        serve(app, host=args.host, port=args.port, threads=int(os.getenv("SGS_WEB_THREADS", "8")))
        return
    print(f"Smart Gate prototype -> http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)


if __name__ == "__main__":
    main()
