"""Queue lifecycle with real SQLite; the paid graph boundary is injected."""

import json
import subprocess
from datetime import date
from unittest.mock import Mock

from tradingagents.web.app import create_app
from tradingagents.web.store import connect
from tradingagents.web.worker import execute_run, process_next, recover_interrupted


def queued(tmp_path):
    app = create_app({"TESTING": True, "DATA_DIR": str(tmp_path), "SECRET_KEY": "test"})
    path = app.config["DATABASE"]
    with connect(path) as db:
        db.execute(
            """INSERT INTO runs (id,ticker,trade_date,quick_model,deep_model,rounds,creator,created,status)
                    VALUES ('abc','AAPL',?,'deepseek/test','z-ai/test',1,'owner','2026-01-01','queued')""",
            (date.today().isoformat(),),
        )
    return path


def row(path):
    with connect(path) as db:
        return dict(db.execute("SELECT * FROM runs").fetchone())


def test_execute_real_pipeline_boundary(tmp_path):
    path = queued(tmp_path)
    captured = {}

    class FakeGraph:
        def __init__(self, config):
            captured.update(config)

        def propagate(self, ticker, day):
            assert ticker == "AAPL"
            return {"market_report": "# Evidence", "messages": ["private SDK objects"]}, "Hold"

    execute_run(path, "abc", graph_factory=FakeGraph)
    result = row(path)
    assert result["status"] == "completed"
    assert result["signal"] == "Hold"
    assert json.loads(result["reports"]) == {"market_report": "# Evidence"}
    assert captured["llm_provider"] == "openrouter"
    assert captured["quick_think_llm"] == "deepseek/test"
    assert captured["deep_think_llm"] == "z-ai/test"
    assert captured["max_tokens"] == 4096
    assert captured["max_debate_rounds"] == 1


def test_queue_claims_only_once(tmp_path):
    path = queued(tmp_path)

    def launch(*args, **kwargs):
        assert row(path)["status"] == "running"
        with connect(path) as db:
            db.execute("UPDATE runs SET status='completed' WHERE id='abc'")
        return subprocess.CompletedProcess(args[0], 0)

    assert process_next(path, launch=launch)
    assert not process_next(path, launch=launch)
    assert row(path)["status"] == "completed"


def test_timeout_and_failed_process_mark_failed(tmp_path):
    path = queued(tmp_path)
    assert process_next(path, launch=Mock(side_effect=subprocess.TimeoutExpired("worker", 1800)))
    assert row(path)["status"] == "failed"
    assert "30 minutes" in row(path)["error"]


def test_process_error_hides_sensitive_output(tmp_path):
    path = queued(tmp_path)
    process_next(
        path, launch=Mock(return_value=subprocess.CompletedProcess([], 1, stderr="secret-key"))
    )
    result = row(path)
    assert result["status"] == "failed"
    assert "secret-key" not in result["error"]


def test_restart_recovers_interrupted(tmp_path):
    path = queued(tmp_path)
    with connect(path) as db:
        db.execute("UPDATE runs SET status='running'")
    recover_interrupted(path)
    assert row(path)["status"] == "failed"
    assert "restarted" in row(path)["error"]


def test_shutdown_reaps_running_child():
    import sys
    import threading
    from unittest.mock import patch

    import pytest

    from tradingagents.web.worker import run_child

    stop = threading.Event()
    original = subprocess.Popen
    children = []

    def spawn(*args, **kwargs):
        child = original(*args, **kwargs)
        children.append(child)
        stop.set()
        return child

    with (
        patch("tradingagents.web.worker.subprocess.Popen", side_effect=spawn),
        pytest.raises(InterruptedError),
    ):
        run_child([sys.executable, "-c", "import time; time.sleep(60)"], stop=stop, timeout=1800)
    assert len(children) == 1 and children[0].poll() is not None


def test_timeout_reaps_running_child():
    import sys
    import threading
    from unittest.mock import patch

    import pytest

    from tradingagents.web.worker import run_child

    with patch("tradingagents.web.worker.subprocess.Popen", wraps=subprocess.Popen) as launch:
        with pytest.raises(subprocess.TimeoutExpired):
            run_child(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                stop=threading.Event(),
                timeout=0.02,
            )
        assert launch.call_count == 1
