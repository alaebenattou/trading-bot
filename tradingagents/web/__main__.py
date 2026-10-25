"""Run ``python -m tradingagents.web setup`` and ``... serve``."""

import argparse
import getpass
import signal
from pathlib import Path

from dotenv import load_dotenv

from .app import create_app
from .store import connect, provision_admins


def main():
    parser = argparse.ArgumentParser(
        description="Trading Desk · a private workspace for two admins"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("setup", help="Create or replace both admin accounts interactively")
    serve = sub.add_parser("serve", help="Start the website and its analysis queue")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", default=8000, type=int)
    args = parser.parse_args()
    load_dotenv(Path.cwd() / ".env", override=False)
    app = create_app()
    if args.command == "setup":
        with connect(app.config["DATABASE"]) as db:
            exists = db.execute("SELECT count(*) FROM users").fetchone()[0] > 0
        if (
            exists
            and input("Replace both admin credentials and sign out existing sessions? [y/N] ")
            .strip()
            .lower()
            != "y"
        ):
            print("Setup cancelled.")
            return
        accounts = []
        for n in (1, 2):
            name = input(f"Admin {n} username: ")
            password = getpass.getpass(f"Admin {n} password (at least 12 characters): ")
            if password != getpass.getpass("Confirm password: "):
                parser.exit(1, "Passwords do not match. No accounts changed.\n")
            accounts.append((name, password))
        try:
            provision_admins(app.config["DATABASE"], accounts)
        except ValueError as exc:
            parser.exit(1, f"{exc} No accounts changed.\n")
        print("Two admin accounts saved. Start with: python -m tradingagents.web serve")
        return

    from filelock import FileLock, Timeout
    from waitress import create_server

    from .worker import start_queue

    lock = FileLock(str(Path(app.config["DATA_DIR"]) / "server.lock"))
    try:
        lock.acquire(timeout=0)
    except Timeout:
        parser.exit(
            1, "This workspace already has a running server. Stop it before starting another.\n"
        )
    stop = None

    def terminate_server(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, terminate_server)
    try:
        server = create_server(app, host=args.host, port=args.port, threads=4)
        stop = start_queue(app.config["DATABASE"])
        print(f"Trading Desk: http://{args.host}:{args.port}", flush=True)
        server.run()
    except KeyboardInterrupt:
        pass
    finally:
        if stop:
            stop.set()
        lock.release()


if __name__ == "__main__":
    main()
