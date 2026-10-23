#!/usr/bin/env python3
"""
Globe News Atlas - Unified Application Runner
Launches backend API, serves frontend 3D Globe, and runs background ingestion scheduler.
"""
import sys
import os
import time
import signal
import threading
import subprocess
import logging
from pathlib import Path

# Configure paths
ROOT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = ROOT_DIR / "backend"
FRONTEND_DIR = ROOT_DIR / "frontend"
DATA_DIR = ROOT_DIR / "data" / "gold" / "serving"

sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(BACKEND_DIR))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("GlobeNewsAtlas.Runner")


def ensure_data():
    """Ensure the serving snapshots exist before launching."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    snapshot_24h = DATA_DIR / "world_24h.json"
    if not snapshot_24h.exists() or snapshot_24h.stat().st_size == 0:
        logger.info("No active snapshot found. Running the real-data pipeline once...")
        try:
            from pipeline.orchestration.flows import PipelineFlow
            flow = PipelineFlow()
            flow.run()
            logger.info("Initial snapshot generation finished.")
        except Exception as e:
            logger.warning(f"Could not generate a live snapshot yet: {e}")


def run_pipeline_scheduler(interval_minutes: int = 15, stop_event: threading.Event = None):
    """Background scheduler to periodically refresh news events and arcs."""
    logger.info(f"Background pipeline scheduler started (interval: {interval_minutes} minutes).")
    while stop_event and not stop_event.is_set():
        # Wait for the specified interval or until stopped
        if stop_event.wait(timeout=interval_minutes * 60):
            break
        logger.info("Executing scheduled news snapshot update...")
        try:
            from pipeline.orchestration.flows import PipelineFlow
            flow = PipelineFlow()
            flow.run()
            logger.info("Scheduled news snapshot update completed.")
        except Exception as e:
            logger.error(f"Scheduled pipeline update error: {e}")


# Configure utf-8 for Windows console
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Run Globe News Atlas")
    parser.add_argument("--port", type=int, default=8000, help="Port to serve backend & frontend")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host interface")
    parser.add_argument("--dev", action="store_true", help="Also start Vite frontend dev server")
    parser.add_argument("--refresh-mins", type=int, default=15, help="Minutes between pipeline ingestion runs")
    parser.add_argument("--no-scheduler", action="store_true", help="Disable background pipeline scheduler")
    args = parser.parse_args()

    print("=" * 65)
    print("               GLOBE NEWS ATLAS (v2.0.0)             ")
    print("   Real-Time 3D Geopolitical News & Spectrum Analysis   ")
    print("   Bronze/Silver/Gold Parquet lake + HF dataset sync    ")
    print("=" * 65)

    # 1. Ensure snapshots
    ensure_data()

    # 2. Start background pipeline scheduler
    stop_event = threading.Event()
    scheduler_thread = None
    if not args.no_scheduler:
        scheduler_thread = threading.Thread(
            target=run_pipeline_scheduler,
            args=(args.refresh_mins, stop_event),
            daemon=True,
            name="PipelineScheduler"
        )
        scheduler_thread.start()

    # 3. Optionally launch Vite dev server
    vite_proc = None
    if args.dev:
        logger.info("Starting Vite frontend dev server on http://localhost:5173...")
        vite_cmd = ["npm", "run", "dev"]
        shell_val = os.name == 'nt'
        try:
            vite_proc = subprocess.Popen(
                vite_cmd,
                cwd=str(FRONTEND_DIR),
                shell=shell_val
            )
        except Exception as e:
            logger.warning(f"Could not start Vite dev server: {e}")

    # 4. Start Uvicorn serving both API and Frontend
    print("\n[+] Service Endpoints:")
    print(f"   * Web Application:  http://{args.host}:{args.port}/")
    print(f"   * API Snapshot:     http://{args.host}:{args.port}/v1/snapshot?window=24h")
    print(f"   * Swagger Docs:     http://{args.host}:{args.port}/docs")
    print(f"   * Health Check:     http://{args.host}:{args.port}/health")
    if args.dev:
        print(f"   * Vite Dev Server:  http://localhost:5173/")
    print("\nPress Ctrl+C to terminate all services.\n")

    try:
        import uvicorn
        from app.main import app
        uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    except KeyboardInterrupt:
        logger.info("Shutdown requested...")
    finally:
        stop_event.set()
        if vite_proc:
            logger.info("Terminating Vite dev server...")
            vite_proc.terminate()
        logger.info("Globe News Atlas shutdown cleanly.")


if __name__ == "__main__":
    main()
