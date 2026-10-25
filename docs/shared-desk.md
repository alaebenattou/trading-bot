# Shared Trading Desk

A private website for two administrators to run stock research and read shared reports. The complete web interface is in French, and new analyses request French report output. It uses the original TradingAgents pipeline, with OpenRouter as the model gateway. There is no broker integration or live trading.

## Local setup

Use Python 3.11 or newer. From this repository:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[web]'
cp .env.example .env
python -m tradingagents.web setup
python -m tradingagents.web serve
```

Open http://127.0.0.1:8000. On Windows, activate with `.venv\Scripts\activate`.

The setup command asks for **exactly two usernames and passwords**. Passwords must have at least 12 characters; they are stored as salted scrypt hashes. There are no default accounts and no public registration. You can run setup again to replace both accounts and invalidate their existing sessions. Usernames are case insensitive; email addresses can be used.

The website works without a model key for sign-in and browsing. To run an analysis, add this to your private `.env`, then restart the server:

```dotenv
OPENROUTER_API_KEY=your-real-key
```

Do not commit `.env` or paste your key into a report. The key is read on the server and never appears in a page, cookie or saved job. A configured status means a key exists, not that its credit balance or provider access has been verified.

## Run research

1. Sign in with either admin account and choose **New analysis**.
2. Enter a stock ticker and analysis date.
3. Copy two model IDs from [OpenRouter's catalog](https://openrouter.ai/models). The first tier serves analysts, researchers, risk debaters and the trader. The second serves the research and portfolio managers. You can combine a DeepSeek model with a GLM model, or use the same model in both fields. Choose models that support tool calls; availability and access depend on your OpenRouter account.
4. Choose 1–3 debate rounds and submit. Runs use paid calls; more rounds increase cost and time. Every model response has a 4,096 output-token cap, but this is not a total spending cap.
5. The report page checks status every five seconds. You can leave and return later; both admins see the same library. Completed reports contain analyst findings, research synthesis, the trader's proposal and the portfolio decision. Download as Markdown for offline reading.

The engine requests market data as of the analysis date; coverage and accuracy still depend on data vendors. Default vendors use Yahoo/SEC and the engine's existing configuration. Extra vendor credentials can be added to `.env` as described in the upstream README.

## Storage and execution

By default, desk data is stored in `~/.tradingagents/desk/`. Override with `TRADING_DESK_DATA_DIR=/absolute/private/path` before setup and serve. Use the **same path and OS user** for both commands. Store it outside public web directories.

- `desk.sqlite3`: hashed credentials, throttle records, run settings and reports.
- `session.key`: generated signing secret; owner read/write permissions only.
- `engine/`: engine cache, shared decision memory and per-run logs.

Back up the whole directory together while the server is stopped. Do not share or commit it. Reports are retained until the operator removes or restores the database; there is currently no in-app delete control. The dashboard displays the 100 most recent runs, while older report URLs remain accessible.

Use **one server instance per data directory**. A file lock prevents duplicate starts. Waitress serves the website with four threads; a separate serial queue launches each analysis in an isolated Python process. The queue accepts up to ten pending/running jobs. Each analysis has a 30-minute timeout. An interrupted run is marked failed when the server restarts; queued work continues. Failed runs can be retried by starting a new analysis. Raw provider errors are kept out of the browser to avoid disclosing credentials.

The key and model IDs have not been tested against a paid provider until you complete a real run with your credentials. Automated tests use an injected graph and make no paid requests.

## Share with your friend

For access outside your own computer, host this app on a private server behind an HTTPS reverse proxy. This repository push does not deploy a public website.

```bash
TRADING_DESK_HTTPS=1 python -m tradingagents.web serve --host 127.0.0.1 --port 8000
```

Set `TRADING_DESK_HTTPS=1` in the server environment or `.env` only when browsers connect over HTTPS. It enables Secure cookies and HSTS; enabling it for plain local HTTP prevents login cookies from working. Bind to loopback and proxy your domain to port 8000. Use a service manager or Docker to restart the app and persist the private data directory.

Sessions last 12 hours. Every state-changing request requires a CSRF token. Login allows at most five failed attempts per source address in fifteen minutes. The app intentionally ignores forwarded-IP headers, so users behind the same reverse proxy share that limit. Enforce any additional per-client rate limits at the proxy. Usernames/passwords are changed via the setup command, not through the browser.

## Docker

The image includes the web extra. The `web` profile adds a persistent desk service and publishes it to loopback only:

```bash
cp .env.example .env
# Add OPENROUTER_API_KEY when ready.
docker compose --profile web build desk
docker compose --profile web run --rm desk setup
docker compose --profile web up -d desk
```

Open http://127.0.0.1:8000. To update, rebuild and restart the desk service. To reset credentials, stop it, run `setup`, then start it again. The shared `tradingagents_data` Docker volume persists credentials and reports across container replacements. Avoid `docker compose down -v` if you want to keep that data.

## Development checks

```bash
pip install -e '.[web,dev]'
pytest tests/test_web.py tests/test_web_worker.py -q
pytest -q
ruff check .
```

The original TradingAgents documentation remains in [README.md](../README.md), and its Apache 2.0 license remains in [LICENSE](../LICENSE).
