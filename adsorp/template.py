"""Excel 数据模板：生成空表、读取填写后的表。

设计原则
--------
* **一张宽表**（``Data``）而不是多张关联表：实验员只需要往下贴行，
  不涉及跨表查找；分组的全部信息（吸附剂、背景、C0、固液比）随行携带。
* 列名保持英文，便于脚本与 R/Python 互通；填写说明另放 ``README`` 表。
* ``Settings`` 表存全局默认值与"吸附剂 → 固液比"映射，避免逐行重复填写。

必填最小集：``exp, mineral, background`` + 实测值（``Ce_ppm`` 或 ``conc_ppb``）
+ ``time_h``（动力学）/ ``pH``（吸附边）。``C0_ppm`` 在等温线中逐行必填；
动力学/吸附边可留空，按组内已有值或 Settings 的 ``default_C0_*`` 补齐。
``exp/mineral/background`` 留空表示沿用上一行（适配"一个实验块只写一次组名"的贴法）。
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd
from openpyxl import load_workbook

# 模板的显示字体：西文/数字 Times New Roman，中文 宋体，与出图字体一致，
# 填表时看到的数字形态就是图上的数字形态。字体只影响显示，脚本读的是值。
LATIN_FONT = "Times New Roman"
EA_FONT = "宋体"
FONT_SIZE = 11


def _theme() -> str:
    """openpyxl 默认主题，只把西文改成 Times New Roman、东亚改成宋体。

    保留原主题的完整配色/版式定义，避免 Excel 打开时提示主题损坏。
    """
    from openpyxl.writer.theme import theme_xml

    xml = theme_xml
    for old in ('<a:latin typeface="Cambria"/>', '<a:latin typeface="Calibri"/>'):
        xml = xml.replace(old, f'<a:latin typeface="{LATIN_FONT}"/>')
    return xml.replace('<a:ea typeface=""/>', f'<a:ea typeface="{EA_FONT}"/>')


def _apply_fonts(book) -> None:
    """把整本工作簿的字体统一成 西文 Times New Roman / 中文 宋体。

    两处一起改才彻底：① 主题的 major/minor 字体（决定新建单元格的默认字体）；
    ② 已有单元格的 rPr（pandas 写值时不带字体，样式由 Normal 继承）。
    Excel 对中文会自动回退到 宋体，所以同一格里混排中英文也是正确的。
    """
    from openpyxl.styles import Font

    book.loaded_theme = _theme()
    try:
        book._named_styles["Normal"].font = Font(name=LATIN_FONT, size=FONT_SIZE)
    except Exception:
        pass
    for ws in book.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                cur = cell.font
                cell.font = Font(
                    name=LATIN_FONT,
                    size=(cur.size if cur is not None and cur.size else FONT_SIZE),
                    bold=bool(cur.bold) if cur is not None else False,
                    italic=bool(cur.italic) if cur is not None else False,
                    underline=cur.underline if cur is not None else None,
                    color=cur.color if cur is not None else None,
                )

DATA_COLUMNS = [
    ("exp", "isotherm | kinetics | edge | qc",
     "实验类型，四选一；qc 行用于检查标准（标称值填 C0_ppm、测定值填 conc_ppb）。"
     "同一实验块可只写首行，下面留空表示沿用上一行"),
    ("mineral", "Mineral A / Mineral B", "吸附剂名，用英文（图上直接显示这个名字）；留空沿用上一行"),
    ("background", "0.01 M NaCl / 0.1 M NaCl", "背景电解质；留空沿用上一行"),
    ("ionic_strength_M", "0.01", "离子强度 (mol/L)，留空则从 background 解析"),
    ("C0_ppm", "6", "初始浓度 (mg/L)；等温线必填，动力学/吸附边留空取默认"),
    ("time_h", "24", "取样时间 (h)，仅 kinetics 必填；留空行会跳过"),
    ("pH", "7.0", "平衡 pH，仅 edge 必填；留空行会跳过"),
    ("Ce_ppm", "0.85", "平衡浓度 (mg/L)。有则优先使用"),
    ("conc_ppb", "127.5", "标线计算/ppb（不是荧光值）。无 Ce_ppm 时按下方公式换算"),
    ("corr_factor", "1.0", "校正因子（标线/漂移校正）"),
    ("dilution", "600", "稀释倍数，留空取 Settings 默认值"),
    ("solid_g_per_L", "3.0", "固液比 m/V。留空取 Settings 中该吸附剂的值"),
    ("replicate", "1", "平行样编号，可留空"),
    ("note", "并行样 2", "备注；含 异常/存疑/加错/未取样/可疑/重测 的行只提示，不自动剔除"),
    ("exclude", "FALSE", "唯一能剔除数据的开关：填 TRUE 则该行不参与拟合与绘图"),
]

SETTINGS_ROWS = [
    ("project", "Adsorption dataset"),
    ("analyst", ""),
    ("analyte", ""),
    # D-R 的吸附势 ε=RT·ln(1+1/C_mol) 要用到吸附质摩尔质量与温度；不填则跳过
    # D-R 模型（其余 6 个等温线模型照常拟合），报告里会写明原因。
    ("molar_mass_g_per_mol", ""),
    ("temperature_K", 298.15),
    ("default_C0_kinetics", ""),
    ("default_C0_edge", ""),
    ("default_dilution_kinetics", ""),
    ("default_dilution_edge", ""),
    ("default_dilution_isotherm", ""),
    ("figure_language", "en"),
    ("note", "solid:<吸附剂> 行为固液比 m/V (g/L)，名称与 Data 表一致；未列的按 mg/L(悬浮液) 处理"),
]

README_LINES = [
    ("吸附数据模板", "title"),
    ("", ""),
    ("怎么用", "h2"),
    ("1. 在 Data 表按行填入实测数据，一行 = 一个样品的一次测定；三组平行就写三行，replicate 分别填 1/2/3。", ""),
    ("2. 同一实验块可以只在第一行写 exp/mineral/background，下面留空表示沿用上一行，不必逐行复制。", ""),
    ("3. 等温线的 C0_ppm 逐行必填；动力学/吸附边可留空，按同组已有值或 Settings 的 default_C0_kinetics/edge 补齐。", ""),
    ("4. mineral 列直接填「英文名」（如 Mineral A、Goethite）：图上就用这个名字，不再经脚本翻译。"
     "以后新增吸附剂，照这个写法填即可，不必改 names.json。", ""),
    ("5. Settings 表填全局默认值；固液比 m/V (g/L) 可写在 Settings 的 solid:<名称> 行，也可逐行填在 Data 表。", ""),
    ("6. 保存后执行：adsorp.bat run --template templates/吸附数据模板.xlsx --out output（在项目目录下；等价于 python -m adsorp.cli run）", ""),
    ("7. 结果：output/报告.html（单文件自包含，图表与 PDF 均内嵌，可单独转发）、结果汇总.xlsx、figures/（PNG+PDF）、tables/（CSV）。", ""),
    ("8. 背景电解质按字符串分组，写法要保持一致（如统一写 0.01 M NaCl）；全角/半角、上标下标的差异会被当成两组。", ""),
    ("9. 表内字体：西文/数字 Times New Roman、中文宋体。字体只影响显示——脚本按单元格的值读取，"
     "改字体、改字号、加粗都不会影响任何计算。", ""),
    ("10. 检查标准（QC）行单独写 exp=qc：标称 ppb 填 C0_ppm、测定 ppb 填 conc_ppb，"
     "mineral/background 可留空；脚本据此算回收率并出 QC 图。", ""),
    ("11. Settings 的 molar_mass_g_per_mol / temperature_K 只用于 D-R 模型的吸附势换算；"
     "不填摩尔质量则跳过 D-R（其余等温线模型不受影响），换温度请同步改 temperature_K。", ""),
    ("", ""),
    ("浓度换算", "h2"),
    ("conc_ppb 填“标线计算/ppb”，不要填实测荧光值；若填 Ce_ppm，直接使用。", ""),
    ("若只填 conc_ppb，则 Ce_ppm = conc_ppb × corr_factor × dilution / 1000。", ""),
    ("吸附率 (%) = 100 × (1 − Ce/C0)；qe (mg/g) = (C0 − Ce) / (m/V)。", ""),
    ("没有 Ce_ppm/conc_ppb 的行＝你已删掉或没做的点：静默跳过，不参与拟合与绘图。"
     "异常值脚本不替你处理，只在报告的数据质量清单里列出行号与建议。", ""),
    ("", ""),
    ("Data 表各列", "h2"),
]


def _settings_frame() -> pd.DataFrame:
    return pd.DataFrame(SETTINGS_ROWS, columns=["key", "value"])


def _style_sheets(book, *, freeze_settings: bool) -> None:
    """列宽、冻结窗格与字体：两个写模板入口共用同一套版式。"""
    ws = book["Data"]
    for i, (name, _, _) in enumerate(DATA_COLUMNS, start=1):
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = \
            max(11, min(26, len(name) + 6))
    ws.freeze_panes = "A2"
    st = book["Settings"]
    st.column_dimensions["A"].width = 30
    st.column_dimensions["B"].width = 46
    if freeze_settings:
        st.freeze_panes = "A2"
    _apply_fonts(book)


def write_template(path: str | Path) -> Path:
    """生成空白模板（含示例行与说明）。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    example = [
        # exp, mineral, background, ionic, C0, time, pH, Ce, conc, corr, dil, solid, rep, note, excl
        ["isotherm", "Mineral A", "0.01 M NaCl", 0.01, 10, None, None, 7.82, None, 1.0, 1, 2.0, 1, "", False],
        ["isotherm", "Mineral A", "0.01 M NaCl", 0.01, 10, None, None, 7.65, None, 1.0, 1, 2.0, 2, "", False],
        ["isotherm", "Mineral B", "0.01 M NaCl", 0.01, 10, None, None, 5.10, None, 1.0, 1, 2.0, 1, "", False],
        ["kinetics", "Mineral A", "0.01 M NaCl", 0.01, 10, 24, None, None, 102.4, 1.0, 50, 2.0, 1, "", False],
        ["edge", "Mineral A", "0.01 M NaCl", 0.01, 10, None, 5.0, 1.25, None, 1.0, 1, 2.0, 1, "", False],
    ]
    data = pd.DataFrame(example, columns=[c[0] for c in DATA_COLUMNS])

    with pd.ExcelWriter(path, engine="openpyxl") as w:
        data.to_excel(w, sheet_name="Data", index=False)
        _settings_frame().to_excel(w, sheet_name="Settings", index=False)

        book = w.book
        readme = book.create_sheet("README", 0)
        readme.column_dimensions["A"].width = 118
        for i, (line, kind) in enumerate(README_LINES, start=1):
            cell = readme.cell(row=i, column=1, value=line)
            if kind == "title":
                cell.font = cell.font.copy(bold=True, size=15)
            elif kind == "h2":
                cell.font = cell.font.copy(bold=True, size=12)
        row = len(README_LINES) + 1
        head = ["列名", "示例", "说明"]
        for j, h in enumerate(head, start=1):
            c = readme.cell(row=row, column=j, value=h)
            c.font = c.font.copy(bold=True)
        for k, (name, sample, desc) in enumerate(DATA_COLUMNS, start=1):
            readme.cell(row=row + k, column=1, value=name).font = \
                readme.cell(row=row + k, column=1).font.copy(bold=True)
            readme.cell(row=row + k, column=2, value=sample)
            readme.cell(row=row + k, column=3, value=desc)
        readme.column_dimensions["B"].width = 30
        readme.column_dimensions["C"].width = 62

        _style_sheets(book, freeze_settings=True)
    return path


def write_from_data(data: pd.DataFrame, path: str | Path,
                    solids: dict | None = None) -> Path:
    """把已解析的长表导出成"填好"的模板。

    两个用途：① 给出可直接照抄的样例；② 回归测试——模板读回后应与原始
    解析结果逐值一致（``read_template`` 只做列映射，不改数值）。
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    src = data.copy()

    def col(name, default=np.nan):
        return src[name] if name in src.columns else pd.Series(default, index=src.index)

    out = pd.DataFrame({
        "exp": col("exp", ""),
        "mineral": col("mineral", ""),
        "background": col("background", ""),
        "ionic_strength_M": col("ionic_strength_M"),
        "C0_ppm": col("C0_ppm"),
        "time_h": col("time_h"),
        "pH": col("pH"),
        "Ce_ppm": col("Ce_ppm"),
        "conc_ppb": col("conc_ppb"),
        "corr_factor": col("corr_factor", 1.0),
        "dilution": col("dilution"),
        "solid_g_per_L": col("solid_g_per_L"),
        "replicate": col("replicate"),
        "note": col("note", ""),
        "exclude": col("exclude", False),
    })

    settings = _settings_frame()
    if solids:
        keep = settings[~settings["key"].astype(str).str.startswith("solid:")]
        extra = pd.DataFrame([{"key": f"solid:{k}", "value": v} for k, v in solids.items()])
        settings = pd.concat([keep, extra], ignore_index=True)

    with pd.ExcelWriter(path, engine="openpyxl") as w:
        out.to_excel(w, sheet_name="Data", index=False)
        settings.to_excel(w, sheet_name="Settings", index=False)
        book = w.book
        readme = book.create_sheet("README", 0)
        readme.column_dimensions["A"].width = 118
        readme.cell(row=1, column=1, value="本表由现有数据导出，可直接修改后重跑").font = \
            readme.cell(row=1, column=1).font.copy(bold=True, size=15)
        for i, (col_name, sample, desc) in enumerate(DATA_COLUMNS, start=3):
            readme.cell(row=i, column=1, value=col_name).font = \
                readme.cell(row=i, column=1).font.copy(bold=True)
            readme.cell(row=i, column=2, value=sample)
            readme.cell(row=i, column=3, value=desc)
        readme.column_dimensions["B"].width = 30
        readme.column_dimensions["C"].width = 62
        _style_sheets(book, freeze_settings=False)
    return path


def _to_bool(v) -> bool:
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    return s in {"true", "1", "yes", "y", "是", "剔除"}


def _normalize_background(text: str) -> str:
    """统一背景电解质的写法：``0.01 M CaCl2`` 与 ``0.01 M CaCl₂`` 视为同一组。

    只把 ``x M 盐`` 里的数字转成下标（CaCl2 → CaCl₂、Na2SO4 → Na₂SO₄），
    不碰前面的浓度数字，也不改 ASW 这类没有化学式的写法。
    两条写法若被当成两组，同一批数据会被静默拆开，pH 边尤其明显。
    """
    s = str(text).strip()
    m = re.match(r"^(?P<head>.*?\bM\s+)(?P<formula>[A-Za-z][A-Za-z0-9]*)$", s, re.I)
    if not m:
        return s
    formula = m.group("formula").translate(str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉"))
    return m.group("head") + formula


def is_template_workbook(path: str | Path) -> bool:
    """判断一个 xlsx 是否是本工具的数据模板（有 Data 表，表头含 exp）。

    只读打开，几毫秒；损坏、加密或不是 xlsx 的文件返回 False，不抛异常。
    """
    wb = None
    try:
        wb = load_workbook(path, read_only=True, data_only=True)
        if "Data" not in wb.sheetnames:
            return False
        ws = wb["Data"]
        header = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), ())
        cols = {str(c).strip().lower() for c in header if c is not None}
        return "exp" in cols and bool(cols & {"mineral", "ce_ppm", "conc_ppb"})
    except Exception:
        return False
    finally:
        if wb is not None:
            try:
                wb.close()
            except Exception:
                pass


def split_workbooks(paths) -> tuple[list[Path], list[Path]]:
    """把一批 Excel 分成 (模板, 仪器原始工作簿) 两组，保持原有顺序。"""
    tpls, raws = [], []
    for p in map(Path, paths):
        (tpls if is_template_workbook(p) else raws).append(p)
    return tpls, raws


def read_template(path: str | Path,
                  defaults: dict | None = None) -> tuple[pd.DataFrame, dict, list[str]]:
    """读取填写后的模板，返回 (长表 data, 配置 dict, 警告列表)。

    ``defaults`` 可传 ``config.json`` 的 ``defaults`` 段，用于补齐
    动力学/吸附边留空的 ``C0_ppm``（Settings 的 ``default_C0_*`` 优先）。

    空白单元格的处理规则：
    * ``exp/mineral/background``：向下沿用上一行（一个实验块只需写一次组名）；
    * ``C0_ppm``：等温线逐行必填；动力学/吸附边按同组已有值或默认值补齐；
    * ``Ce_ppm/conc_ppb`` 都空：使用者已删掉或未测，静默跳过；
    * 完全空白的行：直接忽略。
    """
    path = Path(path)
    xl = pd.ExcelFile(path, engine="openpyxl")
    if "Data" not in xl.sheet_names:
        raise ValueError(f"{path.name} 缺少 Data 工作表")

    raw = xl.parse("Data")
    raw = raw.loc[:, [c for c in raw.columns if not str(c).startswith("Unnamed")]]
    raw.columns = [str(c).strip() for c in raw.columns]
    warns: list[str] = []

    # 先丢掉完全空白的行；保留原始行号（Excel 第 2 行起）
    probe = [c for c in ("exp", "mineral", "background", "C0_ppm", "time_h", "pH",
                         "Ce_ppm", "conc_ppb", "fluorescence") if c in raw.columns]
    if probe:
        raw = raw.loc[raw[probe].notna().any(axis=1)].copy()
    if raw.empty:
        raise ValueError(f"{path.name} 的 Data 表没有数据行")

    settings = {}
    if "Settings" in xl.sheet_names:
        st = xl.parse("Settings")
        if {"key", "value"} <= set(st.columns):
            settings = {str(k).strip(): v for k, v in
                        zip(st["key"], st["value"]) if pd.notna(k)}

    # Settings 里 solids 区：continuation rows 的 key 形如 "solid:吸附剂"
    solids = {}
    for k, v in settings.items():
        if str(k).lower().startswith("solid"):
            name = str(k).split(":", 1)[-1].strip() if ":" in str(k) else None
            try:
                val = float(v)
            except (TypeError, ValueError):
                continue
            if name and np.isfinite(val) and val > 0:
                solids[name] = val

    def num(col, default=np.nan):
        if col not in raw:
            return pd.Series(default, index=raw.index, dtype="float")
        return pd.to_numeric(raw[col], errors="coerce")

    out = pd.DataFrame(index=raw.index)
    # 空单元格必须显式变空串：pandas 3 的 astype(str) 会保留 NaN（float），
    # 后面 set/join 会触发 TypeError。
    out["exp"] = (raw.get("exp", pd.Series("", index=raw.index))
                  .fillna("").astype(str).str.strip().str.lower())
    out["file"] = path.name
    out["row"] = raw.index.to_numpy() + 2
    out["mineral"] = (raw.get("mineral", pd.Series("", index=raw.index))
                      .fillna("").astype(str).str.strip())
    out["background"] = (raw.get("background", pd.Series("", index=raw.index))
                         .fillna("").astype(str).str.strip().map(_normalize_background))

    # 组名向下沿用：适配"一个实验块只写一次 exp/mineral/background"的贴法
    autofill = {}
    for col in ("exp", "mineral", "background"):
        s = out[col].replace("", np.nan)
        before = s.isna()
        s = s.ffill()
        autofill[col] = int((before & s.notna()).sum())
        out[col] = s.fillna("")
    if autofill["exp"]:
        warns.append(f"exp 列有 {autofill['exp']} 行留空，已按上一行沿用；"
                     "换实验类型时请在块首显式写一次。")
    if autofill["mineral"] or autofill["background"]:
        warns.append(f"mineral/background 有 {autofill['mineral'] + autofill['background']} 行留空，"
                     "已按上一行沿用。")

    out["group"] = out["exp"] + "-" + out["mineral"] + "-" + out["background"]
    ionic = num("ionic_strength_M")
    # 留空时从 background 解析（"0.01 M NaCl" → 0.01；ASW 等无 M 的写法保持空）
    parsed = (out["background"].str.extract(r"(\d+(?:\.\d+)?)\s*M\b", expand=False)
              .astype(float))
    out["ionic_strength_M"] = ionic.where(ionic.notna(), parsed)
    out["C0_ppm"] = num("C0_ppm")
    out["time_h"] = num("time_h")
    out["pH"] = num("pH")
    out["conc_ppb"] = num("conc_ppb")
    out["corr_factor"] = num("corr_factor").fillna(1.0)
    out["replicate"] = num("replicate")
    out["fluorescence"] = num("fluorescence")
    out["note"] = (raw.get("note", pd.Series("", index=raw.index))
                   .fillna("").astype(str))

    def _setting_float(key):
        try:
            val = float(settings.get(key))
        except (TypeError, ValueError):
            return None
        return val if np.isfinite(val) and val > 0 else None

    # 动力学/吸附边的 C0 常是整组同一个值：先按同组已有值补齐，再用默认值
    c0_filled = {}
    for exp in ("kinetics", "edge"):
        sub = out[out["exp"].eq(exp)]
        if sub.empty:
            continue
        default = _setting_float(f"default_C0_{exp}") or _setting_float("default_C0_ppm")
        if default is None and defaults:
            try:
                val = float((defaults.get(exp) or {}).get("C0_ppm"))
                default = val if np.isfinite(val) and val > 0 else None
            except (TypeError, ValueError):
                default = None
        n = 0
        for _, g in sub.groupby(["mineral", "background"], dropna=False):
            known = g["C0_ppm"].dropna()
            fill = float(known.iloc[0]) if len(known) else default
            if fill is None or not np.isfinite(fill) or fill <= 0:
                continue
            idx = g.index[g["C0_ppm"].isna()]
            if len(idx):
                out.loc[idx, "C0_ppm"] = fill
                n += len(idx)
        if n:
            c0_filled[exp] = n
            tail = f"，默认 {default:g} mg/L" if default else "（按同组已有值）"
            warns.append(f"{exp}：{n} 行 C0_ppm 留空，已补齐{tail}。")

    dil = num("dilution")
    dil_defaults = {exp: (_setting_float(f"default_dilution_{exp}") or 1.0)
                    for exp in ("isotherm", "kinetics", "edge", "qc")}
    fallback = pd.to_numeric(out["exp"].map(dil_defaults), errors="coerce")
    filled = dil.fillna(fallback).fillna(1.0)
    out["dilution"] = filled
    # 只填 conc_ppb、漏填稀释倍数时，Ce 会小几百倍、吸附率≈100%。
    # 而 Ce > 1.5·C0 那条校验恰好抓不到这种"偏小"的错误，必须单独提示。
    suspect = (dil.isna() & filled.eq(1.0) & out["conc_ppb"].notna()
               & num("Ce_ppm").isna() & out["exp"].ne("qc"))
    if suspect.any():
        n = int(suspect.sum())
        locs = "、".join(f"第 {int(v)} 行" for v in out.loc[suspect, "row"].head(6))
        more = f" 等 {n} 行" if n > 6 else ""
        warns.append(f"{n} 行只填了 conc_ppb 未填稀释倍数，已按 1 计算：{locs}{more}。"
                     "若实际有稀释，Ce 会成倍偏小、吸附率偏大，请补填 dilution。")

    solid = num("solid_g_per_L")
    out["solid_g_per_L"] = solid.where(solid > 0)
    missing = out["solid_g_per_L"].isna()
    if missing.any():
        mapped = out.loc[missing, "mineral"].map(solids)
        out.loc[missing, "solid_g_per_L"] = mapped

    # Ce：优先 Ce_ppm，其次 conc_ppb×corr_factor×dilution/1000
    ce = num("Ce_ppm")
    conv = out["conc_ppb"] * out["corr_factor"] * out["dilution"] / 1000.0
    out["Ce_ppm"] = ce.where(ce.notna(), conv)
    if ce.isna().all() and out["conc_ppb"].isna().all():
        warns.append("Data 表既无 Ce_ppm 也无 conc_ppb，无法计算吸附量。")

    out["reported_removal_pct"] = np.nan
    out["removal_pct"] = np.where(out["C0_ppm"] > 0,
                                  100.0 * (1.0 - out["Ce_ppm"] / out["C0_ppm"]), np.nan)
    out["recalc_max_diff_pct"] = 0.0

    # 只有 exclude 列能剔除数据。note 里写了"异常"只作提示：
    # 备注常出现"异常批次但数据正常"这类说明，机器判断不了，交回给填表人。
    note_flag = (out["note"].fillna("").astype(str)
                 .str.contains("异常|存疑|加错|未取样|可疑|重测", regex=True))
    forced = raw.get("exclude", pd.Series(False, index=raw.index)).map(_to_bool)
    out["exclude"] = forced.fillna(False).to_numpy(bool)
    if note_flag.any():
        hits = out.loc[note_flag, "row"].dropna().astype(int).tolist()
        locs = "、".join(f"第 {v} 行" for v in hits[:6])
        more = f" 等 {len(hits)} 行" if len(hits) > 6 else ""
        warns.append(f"备注命中异常关键词 {len(hits)} 行（{locs}{more}）：仅作提示，未剔除；"
                     "如需剔除请在 exclude 列填 TRUE。")

    valid_exp = ("isotherm", "kinetics", "edge", "qc")

    # 两个浓度列都空＝使用者主动删掉或没做的点，静默跳过：
    # 既不补值也不报警，处理口径就是"去掉之后"的这份数据。
    # 每组还剩多少点，看 `check` 输出的 rows / valid 两列。

    # Ce 明显大于 C0（>1.5 倍）：最常见的根因是把荧光值填进了 conc_ppb。
    # 轻微负吸附不在这里报——逐点清单里会完整列出，避免两处重复。
    neg = out[out["exp"].isin(valid_exp) & out["C0_ppm"].notna() & out["Ce_ppm"].notna()
              & (out["Ce_ppm"] > out["C0_ppm"] * 1.5) & ~out["exclude"]]
    if not neg.empty:
        locs = "、".join(f"{r.exp} 第 {int(r.row)} 行" for r in neg.head(6).itertuples())
        more = f" 等 {len(neg)} 行" if len(neg) > 6 else ""
        warns.append(f"{len(neg)} 行 Ce 超过 C0 的 1.5 倍：{locs}{more}。"
                     "请核对 conc_ppb 填的是“标线计算/ppb”而不是实测荧光值。")

    # 同一组同一条件多行＝平行样：按均值 ± SD 合并，n 记入报告与误差棒。
    # 这是正常测定，不再提示"重复"；若想显式区分，可在 replicate 列标 1/2/3。

    bad_exp = sorted(set(out["exp"]) - set(valid_exp) - {""})
    if bad_exp:
        warns.append(f"exp 列出现未识别取值：{', '.join(bad_exp)}，这些行会被忽略。")
    blank_exp = int(out["exp"].eq("").sum())
    if blank_exp:
        warns.append(f"{blank_exp} 行 exp 为空且上方没有可沿用的实验类型，已忽略。")
    out = out[out["exp"].isin(valid_exp)].copy()

    # QC 行：从长表里分离出来单独成表，否则会被"缺 mineral""缺 C0"之类的
    # 检查误判，也会混进吸附率统计。模板用户过去拿不到第五节（质量控制），
    # 因为 valid_exp 里没有 qc，写 exp=qc 会被直接过滤掉。
    qc_df = pd.DataFrame()
    is_qc = out["exp"].eq("qc")
    if is_qc.any():
        q = out[is_qc]
        nominal = pd.to_numeric(q["C0_ppm"], errors="coerce")
        measured = pd.to_numeric(q["conc_ppb"], errors="coerce")
        qc_df = pd.DataFrame({
            "exp": q["group"].astype(str),
            "file": q["file"],
            "row": q["row"],
            "qc": q["note"].replace("", "检查标准"),
            "nominal_ppb": nominal,
            "conc_ppb": measured,
            "recovery_pct": measured / nominal * 100.0,
        })
        n_no_nominal = int(nominal.isna().sum())
        if n_no_nominal:
            warns.append(f"QC 行有 {n_no_nominal} 条缺标称浓度：exp=qc 时把标称 ppb 填在 C0_ppm 列、"
                         "测定 ppb 填在 conc_ppb 列。")
        out = out[~is_qc].copy()

    for col in ("mineral", "background"):
        n = int(out[col].eq("").sum())
        if n:
            warns.append(f"{n} 行缺 {col}，无法分组。")

    n_k = int(out.loc[out["exp"].eq("kinetics"), "time_h"].isna().sum())
    if n_k:
        warns.append(f"动力学有 {n_k} 行缺 time_h。")
    n_e = int(out.loc[out["exp"].eq("edge"), "pH"].isna().sum())
    if n_e:
        warns.append(f"吸附边有 {n_e} 行缺 pH。")
    if out["C0_ppm"].isna().any():
        warns.append(f"有 {int(out['C0_ppm'].isna().sum())} 行仍缺 C0_ppm"
                     "（等温线逐行必填；动力学/吸附边可设 default_C0_*）。")

    cfg = {
        "solids_g_per_L": solids or None,
        "settings": settings,
        "data_source": f"模板 {path.name}",
        "autofill": autofill,
        "c0_filled": c0_filled,
        "qc": qc_df,        # exp=qc 的行，pipeline 直接拿去出 QC 图与表
    }
    return out.reset_index(drop=True), cfg, warns
