# TusBakalım

Practice past TUS exam questions with personal logins, progress tracking and
spaced repetition. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the
design, database schema and roadmap.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Build the question bank (once, needs the PDFs in `data/`)

```bash
python scanning/build_database_v2.py            # -> instance/tus_database_v2.db
```

## Users

```bash
python manage.py add-user <name>
python manage.py set-password <name>
python manage.py list-users
```

## Run

```bash
python run.py                                   # http://localhost:5050
gunicorn -w 2 -b 0.0.0.0:5050 run:app           # server / Raspberry Pi
```

## Settings (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `TUS_LOGIN_HOURS` | `24` | how long a login is remembered |
| `TUS_ASK_EVERY_LOAD` | `0` | `1` = ask for the password on every page load |
| `TUS_HTTPS` | `0` | `1` = cookie only over HTTPS |
| `TUS_DEBUG` | `0` | `1` = Flask debugger (never on a reachable server) |
| `TUS_PORT` | `5050` | port for `python run.py` |
| `TUS_TZ` | `Europe/Istanbul` | day boundary for reviews/streaks |
| `TUS_INSTANCE_DIR` | `instance/` | where databases + secret key live |

## Private files

`instance/`, `data/`, `exports/` and `archive/` are git-ignored and must
never be committed or made public.
