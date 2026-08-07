"""Carrega e valida a configuração do APEX."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = ROOT / "config.json"
EXAMPLE_CONFIG_PATH = ROOT / "config.example.json"
SKILLS_DIR = ROOT / "skills"


class ConfigError(RuntimeError):
    pass


def _deep_merge(base: dict, override: dict) -> dict:
    """Merge recursivo: o usuário só declara o que quer mudar."""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


class Config:
    def __init__(self, data: dict[str, Any], path: Path):
        self._data = data
        self.path = path

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def get(self, dotted: str, default: Any = None) -> Any:
        """Acesso por caminho pontilhado: config.get('tts.piper_voice')."""
        node: Any = self._data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    @property
    def name(self) -> str:
        return self._data.get("name", "APEX")

    @property
    def api_key(self) -> str:
        key = self._data.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY", "")
        if not key:
            raise ConfigError(
                "Nenhuma chave de API encontrada. Coloque em config.json no campo "
                '"anthropic_api_key", ou defina a variável de ambiente ANTHROPIC_API_KEY.'
            )
        return key

    @property
    def has_api_key(self) -> bool:
        return bool(self._data.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY"))

    @property
    def workspace(self) -> Path:
        path = Path(self._data.get("workspace", "~/APEX")).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def vault_path(self) -> Path:
        raw = self.get("vault.path") or (self.workspace / "vault")
        path = Path(raw).expanduser()
        for sub in ("raw", "wiki", "outputs"):
            (path / sub).mkdir(parents=True, exist_ok=True)
        return path

    @property
    def skills_dir(self) -> Path:
        return SKILLS_DIR

    def as_dict(self) -> dict:
        return copy.deepcopy(self._data)


def load(path: str | Path | None = None) -> Config:
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH

    if not EXAMPLE_CONFIG_PATH.exists():
        raise ConfigError(f"config.example.json não encontrado em {EXAMPLE_CONFIG_PATH}")
    defaults = json.loads(EXAMPLE_CONFIG_PATH.read_text(encoding="utf-8-sig"))

    if not config_path.exists():
        config_path.write_text(
            json.dumps(defaults, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"[config] Criei {config_path}. Preencha a chave da API e rode de novo.")
        return Config(defaults, config_path)

    try:
        user_data = json.loads(config_path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{config_path} tem JSON inválido: {exc}") from exc

    return Config(_deep_merge(defaults, user_data), config_path)
