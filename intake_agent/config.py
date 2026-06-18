"""Configuration: load/save a TOML profile, resolve the API key, validate paths.

The config lives in the OS user-config dir (``platformdirs``) by default, e.g.
- Windows: ``%LOCALAPPDATA%\\intake-agent\\config.toml``
- macOS:   ``~/Library/Application Support/intake-agent/config.toml``
- Linux:   ``~/.config/intake-agent/config.toml``

The API key is *not* stored here by default - it goes in the OS keychain via
``keyring`` when available. Resolution order at runtime:
``ANTHROPIC_API_KEY`` env var → keychain → ``[secrets].api_key`` in config.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

import tomli_w

from . import APP_NAME
from .platform_utils import config_file, default_staging_root

# Keychain coordinates (only used if the optional `keyring` extra is installed).
KEYRING_SERVICE = APP_NAME
KEYRING_USERNAME = "anthropic_api_key"

DEFAULT_MODEL = "claude-sonnet-4-6"

# Extensions never routed: code, scripts, binaries. The agent is for documents.
DEFAULT_SKIP_EXTENSIONS = [
    ".bat", ".ps1", ".sh", ".exe", ".cmd", ".com", ".msi", ".app", ".dmg",
    ".py", ".js", ".ts", ".rb", ".go", ".rs", ".c", ".h", ".cpp", ".java",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".lock",
]


class ConfigError(Exception):
    """Raised when the config is missing or invalid."""


@dataclass
class Config:
    # --- target repository -------------------------------------------------
    repo_root: str = ""                 # absolute path to the repo files land in
    intake_dir: str = "00_intake"       # relative to repo_root, or an absolute path
    review_subdir: str = "review"       # under intake_dir; holds uncertain items
    rules_file: str = "intake.rules.md"  # optional, relative to repo_root

    # --- model -------------------------------------------------------------
    model: str = DEFAULT_MODEL
    max_tool_iterations: int = 16       # hard cap on the per-file tool loop
    max_file_bytes: int = 4_000_000     # cap on bytes/chars handed to the model
    confidence_threshold: float = 0.55  # below this a MOVE is downgraded to REVIEW

    # --- routing behaviour -------------------------------------------------
    # auto:   create new folders automatically (within the repo, guard-railed)
    # prompt: ask for approval (CLI prompt or tray dialog); else send to review
    # review: never create folders; anything needing one goes to review/
    new_folder_policy: str = "prompt"
    skip_extensions: list[str] = field(default_factory=lambda: list(DEFAULT_SKIP_EXTENSIONS))
    profile_max_entries: int = 400      # cap on repo-tree lines injected into the prompt
    profile_max_depth: int = 4

    # --- watch tuning ------------------------------------------------------
    stability_seconds: float = 2.0
    poll_interval: float = 0.5
    stability_timeout: float = 90.0

    # --- misc --------------------------------------------------------------
    staging_root: str = ""              # blank → OS temp dir
    notifications: bool = True
    # Only set if the user opted out of the keychain. Prefer keyring/env.
    api_key_inline: str = ""

    # ----------------------------------------------------------------- paths
    @property
    def repo_path(self) -> Path:
        return Path(self.repo_root).expanduser()

    @property
    def intake_path(self) -> Path:
        p = Path(self.intake_dir).expanduser()
        return p if p.is_absolute() else (self.repo_path / self.intake_dir)

    @property
    def review_path(self) -> Path:
        return self.intake_path / self.review_subdir

    @property
    def rules_path(self) -> Path | None:
        if not self.rules_file:
            return None
        p = Path(self.rules_file).expanduser()
        p = p if p.is_absolute() else (self.repo_path / self.rules_file)
        return p

    @property
    def staging_path(self) -> Path:
        return Path(self.staging_root).expanduser() if self.staging_root else default_staging_root()

    # ----------------------------------------------------------- (de)serialise
    @classmethod
    def from_dict(cls, data: dict) -> "Config":
        known = {f.name for f in fields(cls)}
        clean = {k: v for k, v in data.items() if k in known}
        return cls(**clean)

    def to_toml_dict(self) -> dict:
        d = asdict(self)
        d.pop("api_key_inline", None)  # never written back here; lives in [secrets]
        out: dict = {
            "repo": {
                "root": d["repo_root"],
                "intake_dir": d["intake_dir"],
                "review_subdir": d["review_subdir"],
                "rules_file": d["rules_file"],
            },
            "model": {
                "name": d["model"],
                "max_tool_iterations": d["max_tool_iterations"],
                "max_file_bytes": d["max_file_bytes"],
                "confidence_threshold": d["confidence_threshold"],
            },
            "routing": {
                "new_folder_policy": d["new_folder_policy"],
                "skip_extensions": d["skip_extensions"],
                "profile_max_entries": d["profile_max_entries"],
                "profile_max_depth": d["profile_max_depth"],
            },
            "watch": {
                "stability_seconds": d["stability_seconds"],
                "poll_interval": d["poll_interval"],
                "stability_timeout": d["stability_timeout"],
            },
            "app": {
                "staging_root": d["staging_root"],
                "notifications": d["notifications"],
            },
        }
        if self.api_key_inline:
            out["secrets"] = {"api_key": self.api_key_inline}
        return out

    @classmethod
    def _flatten_toml(cls, raw: dict) -> dict:
        """Map the nested on-disk TOML structure back to flat dataclass fields."""
        repo = raw.get("repo", {})
        model = raw.get("model", {})
        routing = raw.get("routing", {})
        watch = raw.get("watch", {})
        app = raw.get("app", {})
        secrets = raw.get("secrets", {})
        flat = {
            "repo_root": repo.get("root", ""),
            "intake_dir": repo.get("intake_dir", "00_intake"),
            "review_subdir": repo.get("review_subdir", "review"),
            "rules_file": repo.get("rules_file", "intake.rules.md"),
            "model": model.get("name", DEFAULT_MODEL),
            "max_tool_iterations": model.get("max_tool_iterations", 16),
            "max_file_bytes": model.get("max_file_bytes", 4_000_000),
            "confidence_threshold": model.get("confidence_threshold", 0.55),
            "new_folder_policy": routing.get("new_folder_policy", "prompt"),
            "skip_extensions": routing.get("skip_extensions", list(DEFAULT_SKIP_EXTENSIONS)),
            "profile_max_entries": routing.get("profile_max_entries", 400),
            "profile_max_depth": routing.get("profile_max_depth", 4),
            "stability_seconds": watch.get("stability_seconds", 2.0),
            "poll_interval": watch.get("poll_interval", 0.5),
            "stability_timeout": watch.get("stability_timeout", 90.0),
            "staging_root": app.get("staging_root", ""),
            "notifications": app.get("notifications", True),
            "api_key_inline": secrets.get("api_key", ""),
        }
        return flat

    # ---------------------------------------------------------------- validate
    def validate(self) -> list[str]:
        """Return a list of human-readable problems ([] means valid)."""
        problems: list[str] = []
        if not self.repo_root:
            problems.append("repo.root is not set (run `intake setup`).")
        elif not self.repo_path.is_dir():
            problems.append(f"repo.root does not exist: {self.repo_path}")
        if self.new_folder_policy not in ("auto", "prompt", "review"):
            problems.append(
                f"routing.new_folder_policy must be auto|prompt|review, "
                f"got {self.new_folder_policy!r}"
            )
        if not (0.0 <= self.confidence_threshold <= 1.0):
            problems.append("model.confidence_threshold must be between 0 and 1.")
        return problems


# --------------------------------------------------------------------- file I/O
def load_config(path: Path | None = None) -> Config:
    cfg_path = path or _config_path_from_env()
    if not cfg_path.exists():
        raise ConfigError(
            f"No config found at {cfg_path}. Run `intake setup` to create one."
        )
    with cfg_path.open("rb") as f:
        raw = tomllib.load(f)
    return Config.from_dict(Config._flatten_toml(raw))


def save_config(config: Config, path: Path | None = None) -> Path:
    cfg_path = path or _config_path_from_env()
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    with cfg_path.open("wb") as f:
        tomli_w.dump(config.to_toml_dict(), f)
    return cfg_path


def config_exists(path: Path | None = None) -> bool:
    return (path or _config_path_from_env()).exists()


def _config_path_from_env() -> Path:
    env = os.environ.get("INTAKE_CONFIG")
    return Path(env).expanduser() if env else config_file()


# ----------------------------------------------------------------- API key glue
def resolve_api_key(config: Config) -> str:
    """Env var → keychain → inline config. Returns "" if none found."""
    env = os.environ.get("ANTHROPIC_API_KEY")
    if env:
        return env.strip()
    key = _keyring_get()
    if key:
        return key.strip()
    return (config.api_key_inline or "").strip()


def store_api_key(key: str) -> str:
    """Persist the key in the OS keychain. Returns the storage backend used."""
    try:
        import keyring

        keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, key)
        return "keychain"
    except Exception:
        return "unavailable"


def _keyring_get() -> str | None:
    try:
        import keyring

        return keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
    except Exception:
        return None
