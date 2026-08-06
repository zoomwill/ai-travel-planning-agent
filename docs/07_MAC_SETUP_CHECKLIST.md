# macOS Setup Checklist for a Complete Beginner

## 1. Put the project in one local folder

Recommended location:

```bash
mkdir -p ~/Developer
```

Move the extracted folder into `~/Developer`.

## 2. Install Apple command line tools

```bash
xcode-select --install
git --version
```

## 3. Install Homebrew and tools

Follow Homebrew's official installation instructions, then run:

```bash
brew install python@3.12 uv git
```

Install and open Docker Desktop.

Verify:

```bash
python3.12 --version
uv --version
git --version
docker --version
docker compose version
```

## 4. Enter the repository

```bash
cd ~/Developer/ai_travel_planner_codex_pack
pwd
ls
```

## 5. Initialize Git

```bash
git init
git add .
git commit -m "chore: initialize reconstruction workspace"
```

## 6. Install dependencies

```bash
uv sync
```

## 7. Run checks

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy app
uv run pytest -q
```

## 8. Run the API

```bash
uv run uvicorn app.main:app --reload
```

In another terminal:

```bash
curl http://127.0.0.1:8000/health
```

Expected:

```json
{"status":"ok","service":"ai-travel-planner"}
```

## 9. Open the folder in Codex

Ask Codex to read `AGENTS.md`, then paste the master prompt and P00 prompt.
