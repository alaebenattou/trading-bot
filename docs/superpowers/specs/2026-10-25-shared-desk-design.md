# Shared Trading Desk

Two named admins share an authenticated Python website to request stock research and read persistent reports. No signup or live order execution. Preserve the upstream engine, history and Apache license.

Use Flask and server-rendered Jinja templates with responsive dark styling. SQLite stores hashed credentials, login throttling and shared jobs. An interactive setup command provisions exactly two admins, without committed credentials. The OpenRouter key comes only from server environment; UI accepts separate analyst and manager model IDs. Model fields start blank until configured so we do not assume available OpenRouter models.

A single queue runner executes each job in a separate Python subprocess, isolating upstream global configuration. Record creator, ticker, date, model IDs, timestamps, state and report sections. Bound queue and run duration; fail interrupted jobs after restart. Reports use Markdown with embedded HTML disabled. All writes require CSRF tokens. Sessions expire after 12 hours; deployment behind HTTPS enables Secure cookies.

Alternatives: separate React frontend adds maintenance without a current requirement. Integrated Flask is the selected default following the user's instruction to proceed. Builder choices: local SQLite, one web process and one analysis at a time, environment-based secrets, polling for job progress. Deployment remains a separate operation; include Docker startup instructions.
