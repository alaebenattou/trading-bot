"""Serial durable queue, with each upstream graph isolated in a subprocess."""

import json
import signal
import subprocess
import sys
import threading
import time
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

from .app import REPORT_SECTIONS
from .store import connect

FAILURE = (
    "L’analyse s’est arrêtée avant la création du rapport. Vérifiez la clé API du serveur, "
    "les crédits OpenRouter, les identifiants des modèles et la prise en charge des outils, puis relancez une analyse."
)


def finish_failure(path, run_id, message):
    with connect(path) as db:
        db.execute(
            "UPDATE runs SET status='failed', error=?, finished=? WHERE id=? AND status IN ('queued','running')",
            (message, datetime.now(UTC).isoformat(), run_id),
        )


def recover_interrupted(path):
    with connect(path) as db:
        db.execute(
            "UPDATE runs SET status='failed', error=?, finished=? WHERE status='running'",
            (
                "Le serveur a redémarré pendant cette analyse. Lancez une nouvelle analyse pour réessayer.",
                datetime.now(UTC).isoformat(),
            ),
        )


def execute_run(path, run_id, graph_factory=None):
    from tradingagents.default_config import build_default_config

    if graph_factory is None:
        from tradingagents.graph.trading_graph import TradingAgentsGraph

        graph_factory = TradingAgentsGraph
    with connect(path) as db:
        run = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
    if not run:
        raise ValueError("Unknown run")
    config = deepcopy(build_default_config())
    root = Path(path).parent / "engine"
    config.update(
        llm_provider="openrouter",
        output_language="French",
        backend_url="https://openrouter.ai/api/v1",
        quick_think_provider="openrouter",
        deep_think_provider="openrouter",
        quick_think_backend_url=None,
        deep_think_backend_url=None,
        quick_think_llm=run["quick_model"],
        deep_think_llm=run["deep_model"],
        max_debate_rounds=run["rounds"],
        max_risk_discuss_rounds=run["rounds"],
        max_tokens=4096,
        llm_max_retries=2,
        checkpoint_enabled=False,
        results_dir=str(root / "runs" / run_id),
        data_cache_dir=str(root / "cache"),
        memory_log_path=str(root / "memory.md"),
    )
    state, signal = graph_factory(config=config).propagate(run["ticker"], run["trade_date"])
    reports = {
        key: state[key] for key in REPORT_SECTIONS if isinstance(state.get(key), str) and state[key]
    }
    with connect(path) as db:
        db.execute(
            "UPDATE runs SET status='completed', reports=?, signal=?, finished=? WHERE id=? AND status IN ('queued','running')",
            (json.dumps(reports), str(signal), datetime.now(UTC).isoformat(), run_id),
        )


def process_next(path, launch=subprocess.run):
    with connect(path) as db:
        db.execute("BEGIN IMMEDIATE")
        run = db.execute(
            "SELECT id FROM runs WHERE status='queued' ORDER BY created LIMIT 1"
        ).fetchone()
        if not run:
            return False
        run_id = run["id"]
        db.execute("UPDATE runs SET status='running' WHERE id=?", (run_id,))
    try:
        launch(
            [sys.executable, "-m", "tradingagents.web.worker", str(path), run_id],
            timeout=1800,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # This updates only unfinished rows; a normal completed report is preserved.
        finish_failure(path, run_id, FAILURE)
    except subprocess.TimeoutExpired:
        finish_failure(
            path,
            run_id,
            "Cette analyse a atteint la limite de 30 minutes. Essayez moins de tours de débat ou un modèle plus rapide.",
        )
    except InterruptedError:
        finish_failure(
            path,
            run_id,
            "Le serveur s’est arrêté pendant cette analyse. Lancez une nouvelle analyse pour réessayer.",
        )
    except OSError:
        finish_failure(
            path,
            run_id,
            "Le serveur n’a pas pu lancer le processus d’analyse. Vérifiez son installation Python.",
        )
    return True


def run_child(command, *, stop, timeout, **kwargs):
    """Keep the watchdog alive until the child has exited, including on shutdown."""
    deadline = time.monotonic() + timeout
    with subprocess.Popen(command, **kwargs) as child:
        try:
            while True:
                if stop.is_set():
                    raise InterruptedError("Server stopping")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(command, timeout)
                try:
                    return child.wait(timeout=min(0.5, remaining))
                except subprocess.TimeoutExpired:
                    continue
        finally:
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()


class QueueRunner:
    def __init__(self, path):
        self.path = path
        self.stop = threading.Event()
        recover_interrupted(path)
        self.thread = threading.Thread(target=self.loop, name="desk-queue", daemon=True)
        self.thread.start()

    def loop(self):
        def launch(*args, **kwargs):
            return run_child(*args, stop=self.stop, **kwargs)

        while not self.stop.is_set():
            if not process_next(self.path, launch=launch):
                self.stop.wait(2)

    def set(self):
        self.stop.set()
        self.thread.join()


def start_queue(path):
    return QueueRunner(path)


def drain_queue(path):
    """Run pending jobs from cron; overlapping invocations exit without changes."""
    from filelock import FileLock, Timeout

    lock = FileLock(str(Path(path).parent / "server.lock"))
    try:
        lock.acquire(timeout=0)
    except Timeout:
        return False
    stop = threading.Event()
    previous = {}

    def request_stop(signum, frame):
        stop.set()

    def launch(*args, **kwargs):
        return run_child(*args, stop=stop, **kwargs)

    try:
        for signum in (signal.SIGTERM, signal.SIGINT):
            previous[signum] = signal.signal(signum, request_stop)
        recover_interrupted(path)
        while not stop.is_set() and process_next(path, launch=launch):
            pass
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)
        lock.release()
    return True


if __name__ == "__main__":
    try:
        execute_run(sys.argv[1], sys.argv[2])
    except Exception:
        finish_failure(sys.argv[1], sys.argv[2], FAILURE)
        sys.exit(1)
