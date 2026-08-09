import sys
import subprocess
import os

def main():
    print("=" * 60)
    print("   CLOUD-BASED BUS PASS SYSTEM | LAUNCHER")
    print("=" * 60)

    # 1. Initialize Database
    print("[1/2] Initializing SQLite database schema and seed data...")
    from database import init_db
    init_db()
    print("      [OK] Database ready.")

    # 2. Launch Flask Server
    print("[2/2] Launching Cloud Bus Pass Web Server on http://127.0.0.1:5000...")
    from app import app
    app.run(host="127.0.0.1", port=5000, debug=False)

if __name__ == "__main__":
    main()
