"""分析参数 JSON 保存/加载。

配置文件只保存 AnalysisParams，不绑定具体 ROOT 文件，便于在不同数据集之间复用
同一套处理流程并记录分析条件。
"""

from __future__ import annotations

import json
from dataclasses import asdict, fields, is_dataclass
from pathlib import Path

from .params import AnalysisParams


def to_dict(params: AnalysisParams) -> dict:
    return asdict(params)


def _update_dataclass(obj, values: dict):
    if not isinstance(values, dict):
        return obj
    valid = {f.name for f in fields(obj)}
    for key, value in values.items():
        if key not in valid:
            continue
        current = getattr(obj, key)
        if is_dataclass(current) and isinstance(value, dict):
            _update_dataclass(current, value)
        else:
            setattr(obj, key, value)
    return obj


def from_dict(values: dict) -> AnalysisParams:
    """从字典构造参数；忽略未知字段，因此旧/新配置可较平滑地兼容。"""
    return _update_dataclass(AnalysisParams(), values)


def save_json(path: str | Path, params: AnalysisParams) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(to_dict(params), f, ensure_ascii=False, indent=2)
        f.write("\n")


def load_json(path: str | Path) -> AnalysisParams:
    with open(path, "r", encoding="utf-8") as f:
        values = json.load(f)
    if not isinstance(values, dict):
        raise ValueError("配置文件根节点必须是 JSON object")
    return from_dict(values)
