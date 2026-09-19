from __future__ import annotations

import csv
import io
import json
import zipfile
from dataclasses import fields, is_dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path

from .domain import DirectionPackage, Episode, OutlinePackage, ScriptPackage, Stage


def build_episode_package(episode: Episode, *, data_root: Path) -> bytes:
    """Build a portable production package without model secrets."""
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "项目数据.json",
            json.dumps(_to_jsonable(episode), ensure_ascii=False, indent=2),
        )
        archive.writestr("导演执行包.md", _markdown(episode))
        archive.writestr("分镜表.csv", _shot_csv(episode))
        archive.writestr("资产引用.csv", _asset_csv(episode))
        for asset in episode.assets.values():
            if not asset.source_path:
                continue
            source = (data_root / asset.source_path).resolve()
            if source.is_file() and source.is_relative_to(data_root.resolve()):
                archive.write(source, f"资产/{source.name}")
    return output.getvalue()


def _markdown(episode: Episode) -> str:
    lines = [
        f"# {episode.title}",
        "",
        f"- 目标时长：{episode.settings.target_duration_seconds} 秒",
        f"- 单镜头上限：{episode.settings.max_shot_duration_seconds or '不限制'}",
        f"- 提示词语言：{episode.settings.prompt_language.value}",
        "",
        "## 已确认资产",
        "",
    ]
    confirmed = [asset for asset in episode.assets.values() if asset.confirmed]
    if confirmed:
        for asset in confirmed:
            lines.append(
                f"- **{asset.name}**（{asset.kind.value} / {asset.policy.value}）：{asset.description}"
            )
    else:
        lines.append("- 无")

    outline = _payload(episode, Stage.OUTLINE)
    if isinstance(outline, OutlinePackage):
        lines.extend(["", "## 故事大纲", "", f"**{outline.title}**", "", outline.logline, ""])
        lines.extend(f"{index}. {beat}" for index, beat in enumerate(outline.beats, start=1))

    script = _payload(episode, Stage.SCRIPT)
    if isinstance(script, ScriptPackage):
        lines.extend(["", "## 分场剧本", ""])
        for scene in script.scenes:
            lines.extend([f"### {scene.heading}", "", scene.action, ""])
            lines.extend(f"> {dialogue}" for dialogue in scene.dialogue)
            lines.append("")

    direction = _payload(episode, Stage.DIRECTION)
    if isinstance(direction, DirectionPackage):
        lines.extend(["", "## 分镜与提示词", ""])
        for index, shot in enumerate(direction.shots, start=1):
            lines.extend(
                [
                    f"### {index:02d} · {shot.title}",
                    "",
                    f"- 场次：{shot.scene_id}",
                    f"- 时长：{shot.estimated_duration_seconds:g} 秒",
                    f"- 机位：{shot.camera or '未指定'}",
                    f"- 画面：{shot.visual_description}",
                    f"- 对白：{shot.dialogue or '无'}",
                    f"- 配音：{shot.voice_direction or '无'}",
                    f"- 音乐：{shot.music_direction or '无'}",
                    f"- 资产：{', '.join(shot.asset_ids) or '无'}",
                    "",
                    "```text",
                    shot.standard_prompt,
                    "```",
                    "",
                ]
            )
    return "\n".join(lines)


def _shot_csv(episode: Episode) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "镜头编号",
            "场次",
            "名称",
            "时长（秒）",
            "画面描述",
            "机位运镜",
            "对白",
            "配音指导",
            "音乐指导",
            "标准提示词",
            "资产 ID",
        ]
    )
    direction = _payload(episode, Stage.DIRECTION)
    if isinstance(direction, DirectionPackage):
        for shot in direction.shots:
            writer.writerow(
                [
                    shot.id,
                    shot.scene_id,
                    shot.title,
                    shot.estimated_duration_seconds,
                    shot.visual_description,
                    shot.camera,
                    shot.dialogue,
                    shot.voice_direction,
                    shot.music_direction,
                    shot.standard_prompt,
                    ";".join(shot.asset_ids),
                ]
            )
    return "\ufeff" + output.getvalue()


def _asset_csv(episode: Episode) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["资产 ID", "名称", "类型", "规则", "已确认", "视觉描述", "文件"])
    for asset in episode.assets.values():
        writer.writerow(
            [
                asset.id,
                asset.name,
                asset.kind.value,
                asset.policy.value,
                "是" if asset.confirmed else "否",
                asset.description,
                asset.source_path,
            ]
        )
    return "\ufeff" + output.getvalue()


def _payload(episode: Episode, stage: Stage):
    artifact = episode.stages[stage].artifact
    return artifact.payload if artifact else None


def _to_jsonable(value):
    if is_dataclass(value):
        return {field.name: _to_jsonable(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(_to_jsonable(key)): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_to_jsonable(item) for item in value]
    return value
