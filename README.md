# Hoopformer

An open-source deep-learning model of NBA lineups, on the court and beyond it.

Status: building v0.1, a data pipeline, RAPM baseline and season simulator, before the 2026-27 opening night. Design: [docs/DESIGN.md](docs/DESIGN.md).

## Setup

```bash
uv sync
uv run pytest
```

## Fetch data (on a machine stats.nba.com answers)

```bash
uv run hoopformer fetch --season 2025-26 --limit 20
```

Raw responses go to `data/raw/` (not committed); `manifests/raw.jsonl` records each file's SHA-256.

## License

Apache-2.0
