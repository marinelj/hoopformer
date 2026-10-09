"""The GitHub build context includes real rates and serves a game without data downloads."""

import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import socket
import subprocess
import sys
import time
import tomllib
from urllib.error import URLError
from urllib.request import Request, urlopen

from hoopformer.game.model import ActionModel


REPO = Path(__file__).resolve().parents[1]
MODELS = REPO / "deploy/tencent/models"


def test_cloud_package_profile_keeps_the_cli_without_training_dependencies():
    runtime = tomllib.loads((REPO / "deploy/tencent/pyproject.toml").read_text())["project"]
    research = tomllib.loads((REPO / "pyproject.toml").read_text())["project"]
    assert runtime["name"] == research["name"] and runtime["version"] == research["version"]
    assert runtime["scripts"] == research["scripts"]
    assert any(dependency.startswith("torch") for dependency in research["dependencies"])
    assert not any(dependency.startswith(("torch", "nvidia-", "cuda-", "triton")) for dependency in runtime["dependencies"])
    print("Cloud runtime dependencies:", runtime["dependencies"], "; research still includes PyTorch")


def test_github_deployment_models_match_the_verified_real_data_release():
    manifest = json.loads((MODELS / "manifest.json").read_text())
    assert set(manifest["files"]) == {"action_model_2025-26.json", "lever_limits_2025-26.json"}
    for name, digest in manifest["files"].items():
        assert hashlib.sha256((MODELS / name).read_bytes()).hexdigest() == digest, name
    model = ActionModel.load(MODELS / "action_model_2025-26.json")
    assert len(model.players) == manifest["players"] == 606
    assert len(model.teams) == manifest["teams"] == 32
    classics = {team.team_id for team in model.teams.values() if team.tricode in {"90S", "00S"}}
    names = {player.name for player in model.players.values() if player.team_id in classics}
    assert {"Michael Jordan", "Kobe Bryant", "Shaquille O'Neal"} <= names
    print("GitHub derived rates:", len(model.players), "players;", len(model.teams),
          "teams;", len(names), "classic players; both SHA-256 hashes match")


def test_github_docker_sources_start_and_stream_a_real_classic_game(tmp_path):
    docker = (REPO / "Dockerfile").read_text()
    # Use exactly the Docker COPY inputs, without the primary checkout's ignored data or .env.
    for line in docker.splitlines():
        if not line.startswith("COPY "):
            continue
        tokens = shlex.split(line)[1:]
        destination = tokens[-1]
        for name in tokens[:-1]:
            source = REPO / name
            target = tmp_path / destination
            if destination.endswith("/"):
                target = target / source.name
            if source.is_dir():
                shutil.copytree(source, target)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
    assert not (tmp_path / ".env").exists() and not (tmp_path / "data/raw").exists()
    assert sorted(path.name for path in (tmp_path / "data/derived").iterdir()) == [
        "action_model_2025-26.json", "lever_limits_2025-26.json",
    ]
    command = json.loads(next(line[4:] for line in docker.splitlines() if line.startswith("CMD ")))
    assert command[0] == "hoopformer" and command[command.index("--port") + 1] == "8000"
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    command[command.index("--data-dir") + 1] = str(tmp_path / "data")
    command[command.index("--port") + 1] = str(port)
    command[command.index("--host") + 1] = "127.0.0.1"
    env = os.environ.copy()
    env.pop("DASHSCOPE_API_KEY", None)
    env.pop("OPENAI_API_KEY", None)
    env.pop("PYTHONPATH", None)
    for line in docker.splitlines():
        if line.startswith("ENV "):
            for setting in shlex.split(line[4:]):
                name, value = setting.split("=", 1)
                env[name] = value.replace("/app/", str(tmp_path) + "/") if value.startswith("/app/") else value
    assert env.get("PYTHONPATH") == str(tmp_path / "src"), "the image must find the court assets relative to /app/src"
    runtime_python = os.environ.get("HOOPFORMER_RUNTIME_PYTHON") or sys.executable
    probe = subprocess.run(
        [runtime_python, "-c", "import hoopformer, importlib.util, json; print(json.dumps({'source': hoopformer.__file__, 'torch': importlib.util.find_spec('torch') is not None}))"],
        cwd=tmp_path, env=env, capture_output=True, text=True, check=True,
    )
    loaded = json.loads(probe.stdout)
    assert loaded["source"] == str(tmp_path / "src/hoopformer/__init__.py")
    if os.environ.get("HOOPFORMER_RUNTIME_PYTHON"):
        assert loaded["torch"] is False
    print("Actual Docker environment import:", loaded)
    entry = Path(runtime_python).with_name("hoopformer")
    assert entry.exists(), "test the installed Docker command entry point"
    process = subprocess.Popen(
        [str(entry), *command[1:]],
        cwd=tmp_path, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 20
        while True:
            try:
                with urlopen(base + "/api/new", timeout=2) as response:
                    game = json.load(response)
                break
            except URLError:
                assert process.poll() is None, "GitHub build sources exited before listening"
                assert time.monotonic() < deadline, "server never started"
                time.sleep(0.1)
        assert game["home"]["tricode"] == "90S" and game["away"]["tricode"] == "00S"
        call = Request(base + "/api/call", data=json.dumps({"raw": {"team": {"pace": 1}}, "words": "打快一点", "to": None}).encode(),
                       headers={"Content-Type": "application/json"})
        with urlopen(call, timeout=5) as response:
            coaching = json.load(response)
        assert "pace +0.35" in coaching["levers"] and not coaching["unmapped"]
        events, possessions = 0, 0
        while True:
            with urlopen(base + "/api/next", timeout=5) as response:
                play = json.load(response)
            events += len(play["events"])
            possessions += 1
            if play["done"]:
                break
            assert possessions < 1000
        assert events > 400 and play["final"]["home"] != play["final"]["away"]
        with urlopen(base, timeout=5) as response:
            page = response.read().decode()
        assert "function createCourt(G)" in page
        print("GitHub Docker source HTTP:", coaching["levers"], ";", possessions,
              "possessions;", events, "events; final:", play["final"], "; web characters:", len(page))
    finally:
        process.terminate()
        output, _ = process.communicate(timeout=10)
        print("Isolated server output:\n", output)
