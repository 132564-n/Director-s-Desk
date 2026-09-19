from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from urllib.parse import urlsplit

from .credentials import open_key, seal_key
from .drafting import AgentRole


class ProviderKind(StrEnum):
    DEMO = "demo"
    OPENAI_COMPATIBLE = "openai_compatible"


@dataclass(frozen=True, slots=True)
class ProviderSettings:
    id: str
    label: str
    kind: ProviderKind
    base_url: str = ""
    api_key_env: str = ""


@dataclass(frozen=True, slots=True)
class AgentModelSettings:
    role: AgentRole
    provider_id: str
    model: str


@dataclass(frozen=True, slots=True)
class ModelSettings:
    providers: tuple[ProviderSettings, ...]
    assignments: tuple[AgentModelSettings, ...]

    def validate(self) -> None:
        provider_ids = [provider.id for provider in self.providers]
        if len(provider_ids) != len(set(provider_ids)):
            raise ValueError("模型供应商 ID 不能重复")
        known = set(provider_ids)
        assigned_roles = {assignment.role for assignment in self.assignments}
        if len(assigned_roles) != len(self.assignments):
            raise ValueError("同一 Agent 只能配置一次")
        missing = set(AgentRole) - assigned_roles
        if missing:
            raise ValueError(f"以下 Agent 尚未分配模型：{'、'.join(role.value for role in missing)}")
        for assignment in self.assignments:
            if assignment.provider_id not in known:
                raise ValueError(
                    f"{assignment.role.value} 引用了不存在的供应商 {assignment.provider_id}"
                )
            if not assignment.model.strip():
                raise ValueError(f"{assignment.role.value} 的模型名不能为空")
        for provider in self.providers:
            if provider.kind is ProviderKind.OPENAI_COMPATIBLE:
                parsed = urlsplit(provider.base_url)
                if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                        or parsed.username or parsed.password or parsed.query or parsed.fragment):
                    raise ValueError(f"供应商 {provider.label} 的接口地址无效")
                if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
                    raise ValueError("远程模型接口必须使用 HTTPS，本机模型可使用 HTTP")


class LocalModelSettingsStore:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> ModelSettings:
        if not self._path.exists():
            return default_model_settings()
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        settings = ModelSettings(
            providers=tuple(
                ProviderSettings(
                    id=provider["id"],
                    label=provider["label"],
                    kind=ProviderKind(provider["kind"]),
                    base_url=provider.get("base_url", ""),
                    api_key_env=provider.get("api_key_env", ""),
                )
                for provider in raw["providers"]
            ),
            assignments=tuple(
                AgentModelSettings(
                    role=AgentRole(assignment["role"]),
                    provider_id=assignment["provider_id"],
                    model=assignment["model"],
                )
                for assignment in raw["assignments"]
            ),
        )
        settings.validate()
        return settings

    def api_key(self, provider: ProviderSettings) -> str:
        document = json.loads(self._path.read_text(encoding="utf-8")) if self._path.exists() else {}
        stored = document.get("credentials", {}).get(provider.id)
        return open_key(stored) if stored else os.environ.get(provider.api_key_env, "")

    def api_keys(self, settings: ModelSettings) -> dict[str, str]:
        return {provider.id: self.api_key(provider) for provider in settings.providers}

    def public_settings(self) -> dict:
        settings = self.load()
        document = json.loads(self._path.read_text(encoding="utf-8")) if self._path.exists() else {}
        stored = document.get("credentials", {})
        return {
            "providers": [
                {**asdict(provider), "api_key_set": bool(
                    stored.get(provider.id) or os.environ.get(provider.api_key_env, "")
                )}
                for provider in settings.providers
            ],
            "assignments": [asdict(item) for item in settings.assignments],
        }

    def save(self, settings: ModelSettings, *, api_keys: dict[str, str] | None = None) -> None:
        settings.validate()
        previous = json.loads(self._path.read_text(encoding="utf-8")) if self._path.exists() else {}
        previous_providers = {item["id"]: item for item in previous.get("providers", [])}
        credentials = dict(previous.get("credentials", {}))
        for provider in settings.providers:
            # Never reuse an existing key when its destination changes.
            old = previous_providers.get(provider.id)
            if old and old.get("base_url", "").rstrip("/") != provider.base_url.rstrip("/"):
                credentials.pop(provider.id, None)
        for provider_id, value in (api_keys or {}).items():
            if value.strip():
                credentials[provider_id] = seal_key(value.strip())
            else:
                credentials.pop(provider_id, None)
        document = {
            "credentials": {
                provider.id: credentials[provider.id]
                for provider in settings.providers
                if provider.id in credentials and provider.kind is not ProviderKind.DEMO
            },
            "providers": [
                {**asdict(provider), "kind": provider.kind.value}
                for provider in settings.providers
            ],
            "assignments": [
                {**asdict(assignment), "role": assignment.role.value}
                for assignment in settings.assignments
            ],
        }
        temporary = self._path.with_suffix(f"{self._path.suffix}.tmp")
        temporary.write_text(
            json.dumps(document, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self._path)


def default_model_settings() -> ModelSettings:
    return ModelSettings(
        providers=(
            ProviderSettings(
                id="demo",
                label="本地演示团队",
                kind=ProviderKind.DEMO,
            ),
        ),
        assignments=tuple(
            AgentModelSettings(
                role=role,
                provider_id="demo",
                model="deterministic-v1",
            )
            for role in AgentRole
        ),
    )
