"""读取实验原始 xlsx：处理多块排版、合并单元格、穿插 QC 与缺失值。

每个工作簿的 "AFS数据" 表结构为：
    若干标线块（标准编号/浓度/荧光值 + 斜率/截距/R²）
    [可选] 全局参数（初始 Sb/ppm、总稀释倍数）
    样品数据块：一行表头 + 若干样品行，中间穿插 "x ppb 检查标准"
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from openpyxl import load_workbook

SUB = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")

HEADER_ALIASES = {
    "sample": ["样品名称", "样品"],
    "c0": ["初始浓度/ppm", "初始浓度"],
    "dilution": ["稀释倍数"],
    "fluor": ["实测荧光值"],
    "conc": ["标线计算/ppb"],
    "corr": ["校正因子"],
    "corrected": ["校正终液/ppb"],
    "converted": ["折算原样/ppm"],
    "residual": ["剩余率/%"],
    "removal": ["吸附率/%"],
    "note": ["备注"],
    "time": ["反应时间/h"],
    "ph": ["目标 pH", "目标pH"],
    "type": ["类型"],
}

MINERAL_DISPLAY = {
    "δ-MnO2": "δ-MnO₂",
    "六方纤铁矿": "六方纤铁矿",
}

GROUP_RE = re.compile(
    r"^(?P<mineral>.+?)-(?P<bg>ASW|(?P<conc>\d+(?:\.\d+)?)\s*M\s*NaNO3)$",
    re.IGNORECASE,
)


def _norm(s) -> str:
    if s is None:
        return ""
    s = str(s).translate(SUB)
    s = s.replace("\u3000", " ").replace("\xa0", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _num(v):
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if np.isfinite(v) else None
    s = _norm(v).replace(",", "")
    if s in {"", "-", "—", "/", "ND", "nd"}:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _merged_lookup(ws):
    ranges = list(ws.merged_cells.ranges)

    def get(row: int, col: int):
        cell = ws.cell(row, col)
        if cell.value is not None:
            return cell.value
        for rng in ranges:
            if rng.min_row <= row <= rng.max_row and rng.min_col <= col <= rng.max_col:
                return ws.cell(rng.min_row, rng.min_col).value
        return None

    return get


def parse_group(name: str):
    s = _norm(name)
    m = GROUP_RE.match(s)
    if not m:
        return None
    mineral = m.group("mineral").strip(" -_")
    bg = m.group("bg").upper()
    conc = m.group("conc")
    mineral = MINERAL_DISPLAY.get(mineral, mineral)
    if bg == "ASW":
        return mineral, "ASW", np.nan
    return mineral, f"{float(conc):g} M NaNO₃", float(conc)


def _find_header(ws):
    for row in ws.iter_rows(min_row=1, max_row=min(ws.max_row, 80)):
        vals = [_norm(c.value) for c in row]
        if "样品名称" in vals and "实测荧光值" in vals:
            return row[0].row, vals
    return None, None


def _find_meta(ws, header_row: int):
    """从表头以上区域提取 初始 Sb/ppm 与 总稀释倍数。"""
    meta = {}
    for r in range(1, header_row):
        for c in range(1, min(ws.max_column, 20) + 1):
            key = _norm(ws.cell(r, c).value)
            if key in {"初始 Sb/ppm", "总稀释倍数"}:
                for k in range(c + 1, min(ws.max_column, c + 4) + 1):
                    v = _num(ws.cell(r, k).value)
                    if v is not None:
                        meta[key] = v
                        break
    return meta


def read_sheet(path: Path, exp: str, defaults: dict | None = None):
    defaults = defaults or {}
    wb = load_workbook(path, data_only=True, read_only=False)
    sheet_name = "AFS数据" if "AFS数据" in wb.sheetnames else wb.sheetnames[0]
    ws = wb[sheet_name]
    get = _merged_lookup(ws)

    header_row, header_vals = _find_header(ws)
    warnings: list[str] = []
    if header_row is None:
        wb.close()
        return pd.DataFrame(), pd.DataFrame(), {}, [f"{path.name}: 未找到表头"]

    col = {}
    for r in range(1, min(ws.max_column, 40) + 1):
        val = _norm(ws.cell(header_row, r).value)
        for key, aliases in HEADER_ALIASES.items():
            if val in aliases and key not in col:
                col[key] = r

    meta = _find_meta(ws, header_row)
    c0_default = _num(defaults.get("C0_ppm"))
    dil_default = _num(defaults.get("dilution"))
    if c0_default is None:
        c0_default = _num(meta.get("初始 Sb/ppm"))
    if dil_default is None:
        dil_default = _num(meta.get("总稀释倍数"))

    rows, qc_rows = [], []
    current_group = None
    unknown_rows = []

    for r in range(header_row + 1, ws.max_row + 1):
        name_raw = get(r, col.get("sample", 1))
        name = _norm(name_raw)
        note = _norm(get(r, col["note"])) if "note" in col else ""
        typ = _norm(get(r, col["type"])) if "type" in col else ""

        vals = {k: _num(get(r, c)) for k, c in col.items() if k != "sample"}
        has_data = any(vals.get(k) is not None for k in ("fluor", "conc", "corrected", "converted"))

        # QC 行：单独收集，不进入样品表
        is_qc_name = ("检查标准" in name) or bool(re.match(r"^\d+(?:\.\d+)?\s*ppb$", name, re.I))
        if is_qc_name or typ.upper().startswith("QC"):
            nominal = vals.get("corrected")  # 该列在 QC 行中即为标称浓度
            if nominal is None:
                mm = re.search(r"(\d+(?:\.\d+)?)\s*ppb", name)
                if mm:
                    nominal = float(mm.group(1))
            if has_data or nominal is not None:
                qc_rows.append({
                    "exp": exp,
                    "file": path.name,
                    "row": r,
                    "qc": name,
                    "nominal_ppb": nominal,
                    "conc_ppb": vals.get("conc"),
                    "corr_factor": vals.get("corr"),
                    "recovery_pct": (vals.get("conc") / nominal * 100.0)
                    if (vals.get("conc") is not None and nominal) else np.nan,
                    "row_note": note,
                })
            continue

        # 非样品说明行
        if name and not has_data and parse_group(name) is None:
            continue

        parsed = parse_group(name) if name else None
        if parsed is not None:
            current_group = name
            mineral, background, ionic = parsed
        elif name and parse_group(name) is None:
            # 有名字但不属于任何样品组：记录后跳过，避免错误归属
            if has_data:
                unknown_rows.append((r, name))
            continue
        else:
            # 名称为空：仅当该单元格属于纵向合并区域时继承组名
            if current_group is None or not has_data:
                continue
            mineral, background, ionic = parse_group(current_group)

        if not has_data:
            continue

        c0 = vals.get("c0")
        if c0 is None:
            c0 = c0_default
        dilution = vals.get("dilution")
        if dilution is None:
            dilution = dil_default

        conc = vals.get("conc")
        corr = vals.get("corr")
        corrected_calc = conc * corr if (conc is not None and corr is not None) else None
        ce_calc = (corrected_calc * dilution / 1000.0) if (corrected_calc is not None and dilution) else None

        removal_calc = np.nan
        if ce_calc is not None and c0:
            removal_calc = 100.0 * (1.0 - ce_calc / c0)

        reported_removal = vals.get("removal")
        diff = np.nan
        if reported_removal is not None and np.isfinite(removal_calc):
            diff = abs(reported_removal - removal_calc) / max(abs(reported_removal), 1e-9) * 100

        rows.append({
            "exp": exp,
            "file": path.name,
            "row": r,
            "group": _norm(current_group),
            "mineral": mineral,
            "background": background,
            "ionic_strength_M": ionic,
            "C0_ppm": c0,
            "dilution": dilution,
            "fluorescence": vals.get("fluor"),
            "conc_ppb": conc,
            "corr_factor": corr,
            "Ce_ppm": ce_calc if ce_calc is not None else vals.get("converted"),
            "removal_pct": removal_calc if np.isfinite(removal_calc) else reported_removal,
            "reported_removal_pct": reported_removal,
            "time_h": vals.get("time"),
            "pH": vals.get("ph"),
            "note": note,
            "exclude": bool(re.search(r"异常|存疑|加错|未取样|可疑|重测", note)),
            "recalc_max_diff_pct": diff,
        })

    wb.close()
    df = pd.DataFrame(rows)
    numeric_cols = ["C0_ppm", "dilution", "fluorescence", "conc_ppb", "corr_factor",
                    "Ce_ppm", "removal_pct", "reported_removal_pct", "time_h", "pH",
                    "ionic_strength_M", "recalc_max_diff_pct"]
    for c in numeric_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    if df.empty:
        warnings.append(f"{path.name}: 未解析到有效数据行")
    if unknown_rows:
        warnings.append(
            f"{path.name}: {len(unknown_rows)} 行有数据但样品名不属于任何矿物-背景组，已排除（行号 "
            + ", ".join(str(x[0]) for x in unknown_rows[:8])
            + ("..." if len(unknown_rows) > 8 else "")
            + "）"
        )
    qc = pd.DataFrame(qc_rows)
    return df, qc, meta, warnings


def read_all(data_dir: Path, cfg: dict):
    files = {
        "isotherm": sorted(data_dir.glob("*等温*.xlsx")),
        "kinetics": sorted(data_dir.glob("*动力学*.xlsx")),
        "edge": sorted(data_dir.glob("*吸附边*.xlsx")),
    }
    frames, qcs, metas, warnings = [], [], {}, []
    for exp, paths in files.items():
        if not paths:
            warnings.append(f"未找到 {exp} 数据文件")
            continue
        p = [x for x in paths if not x.name.startswith("~$")][0]
        df, qc, meta, warn = read_sheet(p, exp, cfg.get("defaults", {}).get(exp, {}))
        frames.append(df)
        if not qc.empty:
            qcs.append(qc)
        metas[exp] = meta
        warnings.extend(warn)
    data = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    qc = pd.concat(qcs, ignore_index=True) if qcs else pd.DataFrame()
    return data, qc, metas, warnings
