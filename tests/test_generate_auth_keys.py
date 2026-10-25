"""scripts/generate_auth_keys.py writes usable keys and never overwrites existing ones."""

import importlib.util
from pathlib import Path

from app.core.config import Settings
from app.core.tokens import TokenService


def _load():
    path = Path(__file__).parents[1] / "scripts" / "generate_auth_keys.py"
    spec = importlib.util.spec_from_file_location("generate_auth_keys", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_keys_are_appended_and_loadable(tmp_path, capsys):
    env = tmp_path / ".env"
    env.write_text("ENVIRONMENT=uat\n", encoding="utf-8")
    assert _load().main(env) == 0
    assert "BEGIN" not in capsys.readouterr().out
    settings = Settings(_env_file=env)
    service = TokenService(settings)
    token, _ = service.create_access_token(1, "s")
    assert service.decode_access_token(token).user_id == 1
    assert _load().main(env) == 1  # second run refuses
