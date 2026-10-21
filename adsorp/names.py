"""吸附剂 / 背景电解质的显示名映射（可选）。

数据表里**直接写英文名**最省事：``mineral("Goethite") -> "Goethite"`` 属于
直通，不需要任何配置。本模块只在两种情况下有用：

* 旧的中文数据表——把中文名映射到英文显示名后照常出图；
* 同一物质的多种写法——归并成一个名字，避免被拆成两组。

映射写在项目根目录的 ``names.json``（不随仓库分发，可自行创建）：

.. code-block:: json

    {"minerals": {"赤铁矿": "Hematite"}, "backgrounds": {}}

注意：中文名只作为**数据键**使用，画图时一律经 :func:`mineral` /
:func:`background` 转成英文，因此图中不会出现 CJK 字形问题。
"""
from __future__ import annotations

import json
from pathlib import Path

DEFAULTS = {
    "minerals": {},
    "backgrounds": {},
    "experiments": {"isotherm": "Isotherm", "kinetics": "Kinetics", "edge": "Edge"},
}

_MAP = {k: dict(v) for k, v in DEFAULTS.items()}


def load(path: str | Path | None) -> dict:
    """读取 names.json；文件不存在时保持默认，缺失键逐个回退。"""
    if path is None:
        return _MAP
    p = Path(path)
    if not p.exists():
        return _MAP
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return _MAP
    for section, table in raw.items():
        if isinstance(table, dict):
            _MAP.setdefault(section, {}).update(table)
    return _MAP


def mineral(name: str) -> str:
    return _MAP["minerals"].get(str(name), str(name))


def background(name: str) -> str:
    return _MAP["backgrounds"].get(str(name), str(name))


def experiment(name: str) -> str:
    return _MAP["experiments"].get(str(name), str(name))
