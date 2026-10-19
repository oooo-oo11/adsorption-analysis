"""矿物 / 背景电解质的显示名。

现在数据表里**直接写英文名**（模板已改为英文，图上原样显示、不再翻译）：
``mineral("Rancieite") -> "Rancieite"`` 属于直通，无需在 names.json 里登记。
本模块的作用变成两层：

* 兼容旧的中文数据表——中文名映射到英文显示名后照常出图；
* 统一别名（例如 ``birnessite`` 的几种写法）——在 names.json 里加一行即可。

注意：中文名只作为**数据键**使用，画图时一律经 :func:`mineral` / :func:`background`
转成英文，因此图中不会出现 CJK 字形问题。
"""
from __future__ import annotations

import json
from pathlib import Path

DEFAULTS = {
    "minerals": {
        "δ-MnO₂": "δ-MnO₂",
        "钙锰矿": "Rancieite",
        "酸性水钠锰矿": "Acid birnessite",
        "碱性水钠锰矿": "Alkaline birnessite",
        "六方纤铁矿": "Feroxyhyte",
        # 英文名与显示名一致，列出只为让 missing() 有据可查、自解释
        "Rancieite": "Rancieite",
        "Acid birnessite": "Acid birnessite",
        "Alkaline birnessite": "Alkaline birnessite",
        "Feroxyhyte": "Feroxyhyte",
    },
    "backgrounds": {
        "0.001 M NaNO₃": "0.001 M NaNO₃",
        "0.01 M NaNO₃": "0.01 M NaNO₃",
        "0.1 M NaNO₃": "0.1 M NaNO₃",
        "ASW": "ASW",
    },
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


def write_default(path: str | Path) -> Path:
    p = Path(path)
    p.write_text(json.dumps(DEFAULTS, ensure_ascii=False, indent=2) + "\n",
                 encoding="utf-8")
    return p


def mineral(name: str) -> str:
    return _MAP["minerals"].get(str(name), str(name))


def background(name: str) -> str:
    return _MAP["backgrounds"].get(str(name), str(name))


def experiment(name: str) -> str:
    return _MAP["experiments"].get(str(name), str(name))


def missing(names) -> list[str]:
    """返回尚未映射的矿物名（用于提示用户补 names.json）。"""
    return [n for n in dict.fromkeys(names) if n not in _MAP["minerals"]]
