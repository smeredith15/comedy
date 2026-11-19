"""Repository paths, YAML helpers and the config files."""

from __future__ import annotations

import io
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML


def yaml_rt() -> YAML:
    y = YAML(typ="rt")
    y.preserve_quotes = True
    y.indent(mapping=2, sequence=4, offset=2)
    y.width = 4096
    y.representer.add_representer(
        type(None), lambda r, _: r.represent_scalar("tag:yaml.org,2002:null", "null"))
    return y


def load_yaml(path: Path) -> Any:
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as f:
        return yaml_rt().load(f)


def dump_yaml(path: Path, data: Any) -> None:
    buf = io.StringIO()
    yaml_rt().dump(data, buf)
    path.write_text(buf.getvalue(), encoding="utf-8")


def find_root(start: Path | None = None) -> Path:
    env = os.environ.get("SPECIALS_ROOT")
    if env:
        return Path(env).resolve()
    here = (start or Path.cwd()).resolve()
    for p in [here, *here.parents]:
        if (p / "config" / "scope.yaml").exists():
            return p
    return Path(__file__).resolve().parents[2]


@dataclass
class Repo:
    root: Path

    @property
    def config(self) -> Path:
        return self.root / "config"

    @property
    def data(self) -> Path:
        return self.root / "data"

    @property
    def app_data(self) -> Path:
        return self.root / "app" / "public" / "data"


@dataclass
class Config:
    scope: dict = field(default_factory=dict)
    sources: dict = field(default_factory=dict)
    platforms: dict = field(default_factory=dict)

    @classmethod
    def load(cls, repo: Repo) -> "Config":
        return cls(
            scope=_plain(load_yaml(repo.config / "scope.yaml")) or {},
            sources=load_yaml(repo.config / "sources.yaml") or {},   # round-trip: resolve writes back
            platforms=_plain(load_yaml(repo.config / "platforms.yaml")) or {},
        )

    def collector(self, name: str) -> dict:
        return dict((self.sources.get("collectors") or {}).get(name) or {})

    def enabled(self, name: str) -> bool:
        return bool(self.collector(name).get("enabled", False))


def _plain(obj: Any) -> Any:
    """Turn ruamel's commented containers into plain dicts/lists."""
    if isinstance(obj, dict):
        return {str(k): _plain(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_plain(v) for v in obj]
    return obj


plain = _plain


def load_dotenv(path: Path) -> None:
    """Minimal .env loader (KEY=value lines). Existing environment wins."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip().strip('"').strip("'")
        if v and k.strip() not in os.environ:
            os.environ[k.strip()] = v
