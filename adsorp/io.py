"""读取实验原始 xlsx：处理多块排版、合并单元格、穿插 QC 与缺失值。

每个工作簿的 "AFS数据" 表结构为：
    若干标线块（标准编号/浓度/荧光值 + 斜率/截距/R²）
    [可选] 全局参数（初始浓度/ppm、总稀释倍数）
    样品数据块：一行表头 + 若干样品行，中间穿插 "x ppb 检查标准"

样品名约定为 ``吸附剂-背景``，例如 ``Goethite-0.01 M NaCl``、``Goethite-ASW``；
不合约定的行会被记入"未识别组名"警告，而不是静默丢弃。
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

# 样品名里的元素序号（MnO2 → MnO₂）只是显示细节，不参与分组。
# 背景电解质里"盐"的种类默认不限制：``0.01 M NaCl`` / ``0.1 M KNO3`` 都能识别。
# 确有需要时可在 config.json 写 {"legacy": {"background_salts": ["NaCl"]}} 限定。
DEFAULT_SALTS: tuple[str, ...] = ()

# 不再按文件名约定挑数据：目录里放什么就读什么，实验类型由表内内容判断
# （见 _guess_exp）。唯一排除的是 Excel 打开文件时留下的 "~$xxx.xlsx" 锁文件。
XLSX_SUFFIXES = (".xlsx", ".xlsm")


def list_workbooks(data_dir: Path) -> list[Path]:
    """目录顶层的全部 Excel（不递归子目录，跳过 ~$ 临时锁文件）。"""
    d = Path(data_dir)
    if not d.is_dir():
        return []
    return [p for p in sorted(d.iterdir())
            if p.is_file() and p.suffix.lower() in XLSX_SUFFIXES
            and not p.name.startswith("~$")]


def has_workbooks(data_dir: Path) -> bool:
    """目录顶层是否存在 Excel 文件（不递归子目录）。"""
    return bool(list_workbooks(data_dir))

# 仪器表头里"初始浓度"与"总稀释倍数"的标签。换吸附质后表头常写成
# "初始 As/ppm" 之类，所以除固定写法外，还接受任何以"初始"开头、
# 以"/ppm"结尾的标签（见 _find_meta）。
C0_LABELS = ("初始浓度/ppm", "初始浓度")
DIL_LABELS = ("总稀释倍数",)


def _bg_pattern(salts=DEFAULT_SALTS) -> re.Pattern:
    vals = [str(s) for s in (salts or ()) if str(s).strip()]
    salt = "|".join(re.escape(s) for s in vals) if vals else r"[A-Za-z][A-Za-z0-9]*"
    return re.compile(
        rf"^(?P<mineral>.+?)-(?P<bg>ASW|(?P<conc>\d+(?:\.\d+)?)\s*M\s*(?:{salt}))$",
        re.IGNORECASE)


GROUP_RE = _bg_pattern()


def set_background_salts(salts) -> None:
    """替换背景电解质盐的种类（来自 config.json 的 legacy.background_salts）。"""
    global GROUP_RE
    vals = [str(s).strip() for s in (salts or []) if str(s).strip()]
    if vals:
        GROUP_RE = _bg_pattern(tuple(vals))


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
    if bg == "ASW":
        return mineral, "ASW", np.nan
    # 盐名从匹配到的背景串里取，不能写死某一种盐——否则换 NaCl 时组名会
    # 被错误地统一，两个不同背景的组就被合并成一组。
    salt = re.sub(r"^[\d.]+\s*M\s*", "", m.group("bg"), flags=re.I).strip()
    return mineral, f"{float(conc):g} M {salt}", float(conc)


def _find_header(ws):
    for row in ws.iter_rows(min_row=1, max_row=min(ws.max_row, 80)):
        vals = [_norm(c.value) for c in row]
        if "样品名称" in vals and "实测荧光值" in vals:
            return row[0].row, vals
    return None, None


def _find_meta(ws, header_row: int):
    """从表头以上区域提取初始浓度与总稀释倍数。

    标签不必逐字匹配：``初始 Sb/ppm``、``初始 As/ppm`` 这类写法都归到 ``c0``。
    """
    meta = {}
    for r in range(1, header_row):
        for c in range(1, min(ws.max_column, 20) + 1):
            key = _norm(ws.cell(r, c).value)
            is_c0 = key in C0_LABELS or (key.startswith("初始") and key.endswith("/ppm"))
            is_dil = key in DIL_LABELS
            if not (is_c0 or is_dil):
                continue
            slot = "c0" if is_c0 else "dil"
            if slot in meta:
                continue
            for k in range(c + 1, min(ws.max_column, c + 4) + 1):
                v = _num(ws.cell(r, k).value)
                if v is not None:
                    meta[slot] = v
                    break
    return meta


def _first_meta(meta: dict, labels) -> float | None:
    for k in labels:
        v = _num(meta.get(k))
        if v is not None:
            return v
    return None


def _guess_exp(ws, col: dict, header_row: int) -> str:
    """判断这个表是等温线 / 动力学 / 吸附边，只看内容不看文件名。

    先看表名与表头上方的标题文字（仪器导出的表多半写了"…等温…"）；
    标题里没有线索时再看哪一列真正有数据：
    ``反应时间/h`` 有值 → 动力学；``目标 pH`` 有值 → 吸附边；两者都没有 → 等温线。
    """
    texts = [str(ws.title)]
    for r in range(1, max(header_row, 1)):
        for c in range(1, min(ws.max_column, 12) + 1):
            v = ws.cell(r, c).value
            if isinstance(v, str) and v.strip():
                texts.append(v.strip())
    joined = " ".join(texts)
    if "动力" in joined or "kinetic" in joined.lower():
        return "kinetics"
    if "等温" in joined or "isotherm" in joined.lower():
        return "isotherm"
    if "吸附边" in joined or "吸附边界" in joined or "edge" in joined.lower():
        return "edge"

    def has_number(key: str) -> bool:
        c = col.get(key)
        if c is None:
            return False
        for r in range(header_row + 1, ws.max_row + 1):
            v = ws.cell(r, c).value
            if isinstance(v, bool) or v is None:
                continue
            if isinstance(v, (int, float)) and np.isfinite(v):
                return True
            if isinstance(v, str) and re.fullmatch(r"\s*-?\d+(?:\.\d+)?\s*", v):
                return True
        return False

    if has_number("time"):
        return "kinetics"
    if has_number("ph"):
        return "edge"
    return "isotherm"


def read_sheet(path: Path, exp: str | None = None, defaults: dict | None = None):
    """读一个仪器工作簿。``exp`` 缺省时由 :func:`_guess_exp` 按内容判断。

    ``defaults`` 传整份 ``config.json`` 的 ``defaults``（按实验类型分节），
    内部按最终判定的类型取对应的一节。
    """
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

    if exp is None:
        exp = _guess_exp(ws, col, header_row)
    defaults = defaults.get(exp, {})

    meta = _find_meta(ws, header_row)
    c0_default = _num(defaults.get("C0_ppm"))
    dil_default = _num(defaults.get("dilution"))
    if c0_default is None:
        c0_default = _first_meta(meta, ("c0",))
    if dil_default is None:
        dil_default = _first_meta(meta, ("dil",))

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
            f"{path.name}: {len(unknown_rows)} 行有数据但样品名不属于任何吸附剂-背景组，已排除（行号 "
            + ", ".join(str(x[0]) for x in unknown_rows[:8])
            + ("..." if len(unknown_rows) > 8 else "")
            + "）"
        )
    qc = pd.DataFrame(qc_rows)
    if isinstance(meta, dict):
        meta["exp"] = exp          # 判定的实验类型回传给调用方
    return df, qc, meta, warnings


def read_all(data_dir: Path, cfg: dict, paths=None):
    """读取目录里**全部** Excel，逐个判断实验类型后合并。

    不再依赖文件名关键词：什么名字都行，一个工作簿装一类实验即可。
    ``paths`` 用于只读指定文件（pipeline 里把模板挑出去后传剩下的一批）。
    """
    salts = (cfg.get("legacy") or {}).get("background_salts")
    if salts:
        set_background_salts(salts)
    files = list_workbooks(data_dir) if paths is None else [Path(p) for p in paths]
    frames, qcs, metas, warnings = [], [], {}, []
    if not files:
        return pd.DataFrame(), pd.DataFrame(), {}, ["目录里没有 Excel 文件"]
    defaults = cfg.get("defaults", {})
    for p in files:
        df, qc, meta, warn = read_sheet(p, defaults=defaults)
        exp = meta.get("exp") if isinstance(meta, dict) else None
        if df.empty:
            warnings.extend(warn or [f"{p.name}: 未解析到有效数据行"])
            continue
        frames.append(df)
        if not qc.empty:
            qcs.append(qc)
        metas[p.name] = meta if isinstance(meta, dict) else {"exp": exp}
        warnings.extend(warn or [])
    data = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    qc = pd.concat(qcs, ignore_index=True) if qcs else pd.DataFrame()

    # 缺哪类实验，直接说；这比"未找到 xxx 文件"更贴近实际（类型是判出来的，不是名字给的）
    if not data.empty:
        have = set(data["exp"].dropna().unique())
        label = {"isotherm": "等温线", "kinetics": "动力学", "edge": "吸附边"}
        missing = [v for k, v in label.items() if k not in have]
        if missing:
            warnings.append(f"数据里没有{'、'.join(missing)}实验，相关的图与表会留空")
    return data, qc, metas, warnings
