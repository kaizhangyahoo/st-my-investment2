#!/usr/bin/env python3
"""
CLI runner for st-my-investment2 web application (CV-creator pattern).
Runs FastAPI backend and React frontend locally.
"""

import sys
import os
import subprocess
import argparse
import webbrowser
import time

REPO_ROOT = os.path.abspath(os.path.dirname(__file__))

def run_dev():
    """Run FastAPI uvicorn server in background and Vite frontend."""
    print("🚀 Starting Portfolio Analytics Web App in Development Mode...")

    # Start FastAPI backend
    backend_cmd = [
        sys.executable, "-m", "uvicorn", "backend.app.main:app",
        "--host", "0.0.0.0", "--port", "8000", "--reload"
    ]
    print("⚡ Starting FastAPI backend on http://localhost:8000 ...")
    backend_proc = subprocess.Popen(backend_cmd, cwd=REPO_ROOT)

    time.sleep(1)

    # Start Vite frontend if npm is available
    frontend_dir = os.path.join(REPO_ROOT, "frontend")
    print("✨ Starting Vite frontend on http://localhost:5173 ...")
    try:
        frontend_proc = subprocess.Popen(["npm", "run", "dev"], cwd=frontend_dir)
        time.sleep(2)
        webbrowser.open("http://localhost:5173")
        frontend_proc.wait()
    except FileNotFoundError:
        print("⚠️ npm not found. You can test backend API docs at http://localhost:8000/docs")
        webbrowser.open("http://localhost:8000/docs")
    finally:
        backend_proc.terminate()

def run_start():
    """Serve the application via FastAPI."""
    print("⚡ Serving Portfolio Analytics Web App on http://localhost:8000 ...")
    webbrowser.open("http://localhost:8000")
    subprocess.run([
        sys.executable, "-m", "uvicorn", "backend.app.main:app",
        "--host", "0.0.0.0", "--port", "8000"
    ], cwd=REPO_ROOT)

def main():
    parser = argparse.ArgumentParser(description="Portfolio Analytics CLI Runner")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("dev", help="Start FastAPI backend + Vite frontend concurrently")
    subparsers.add_parser("start", help="Serve application through FastAPI")

    args = parser.parse_args()
    if args.command == "dev" or args.command is None:
        run_dev()
    elif args.command == "start":
        run_start()
    else:
        parser.print_help()

if __name__ == "__main__":
    main()

