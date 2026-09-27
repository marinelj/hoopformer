# Working rules for AI teammates (Claude, ChatGPT/Codex)

This repo is the project's shared memory: read `docs/DESIGN.md` before changing anything.

- **Clean room.** Unicorn (uptownnickbrown/unicorn) and nba-lineup-model (EvanZ/nba-lineup-model) have no license. Never read, paste or adapt their code. Their public descriptions are credited in `docs/DESIGN.md`.
- **Data.** Raw NBA responses live in `data/` (git-ignored). Fetch them only through `hoopformer fetch`, which records every file's SHA-256 in `manifests/raw.jsonl`. Never commit raw data.
- **stats.nba.com only answers from marinelj's Mac,** not from cloud machines or sandboxed shells. Code that needs the network must be run there.
- **Tests.** Every function gets a test on real data, no mocks. Print what the test sees, so a failing run explains itself. `uv run pytest` runs the offline tests; `uv run pytest -m network` runs the ones that hit stats.nba.com.
- **Keep it simple.** Plain functions, no abstractions until a second use needs them.
- **Explain the why.** marinelj is learning ML through this project: every commit comes with a short note on what changed and why.
