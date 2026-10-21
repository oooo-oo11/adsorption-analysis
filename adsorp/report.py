"""生成自包含 HTML 报告与 Excel 汇总。"""
from __future__ import annotations

import ast
import base64
import html as _html
import textwrap
import zipfile
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from . import names

CSS = """
:root{--ink:#1f2937;--muted:#6b7280;--line:#e5e7eb;--accent:#1d4ed8;--bg:#f7f8fa}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
     font-family:"Microsoft YaHei","PingFang SC",-apple-system,"Segoe UI",sans-serif;
     font-size:14px;line-height:1.75}
.wrap{max-width:1080px;margin:28px auto 64px;background:#fff;padding:44px 52px 56px;
      box-shadow:0 1px 3px rgba(16,24,40,.08);border-radius:6px}
h1{font-size:26px;margin:0 0 6px;letter-spacing:.3px}
.sub{color:var(--muted);font-size:13px;margin-bottom:26px}
h2{font-size:18px;margin:38px 0 12px;padding-left:11px;border-left:4px solid var(--accent)}
h3{font-size:15px;margin:24px 0 8px;color:#111827}
p{margin:8px 0}
ul,ol{margin:8px 0 8px 22px;padding:0}
li{margin:5px 0}
.kpis{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin:18px 0 8px}
.kpi{background:#f9fafb;border:1px solid var(--line);border-radius:6px;padding:12px 14px}
.kpi b{display:block;font-size:22px;line-height:1.3;color:var(--accent)}
.kpi span{font-size:12px;color:var(--muted)}
.tbl{width:100%;border-collapse:collapse;font-size:12px;margin:10px 0 14px;
     font-variant-numeric:tabular-nums}
.tbl th{background:#f3f4f6;font-weight:600;text-align:left;padding:7px 9px;
        border-bottom:1px solid #d1d5db;white-space:nowrap}
.tbl td{padding:6px 9px;border-bottom:1px solid var(--line);vertical-align:top}
.tbl td:first-child,.tbl td:nth-child(2){white-space:nowrap}
.tbl tr:nth-child(even) td{background:#fafafa}
.scroll{overflow-x:auto;border:1px solid var(--line);border-radius:5px}
.scroll .tbl{margin:0}
.scroll .tbl th{position:sticky;top:0}
.warn{background:#fff7ed;border-left:3px solid #f59e0b;padding:12px 16px;border-radius:4px;
      margin:12px 0;font-size:13px}
.warn ul{margin:6px 0 0 18px}
.note{background:#eff6ff;border-left:3px solid var(--accent);padding:12px 16px;
      border-radius:4px;font-size:13px;margin:12px 0}
.empty{color:var(--muted);font-style:italic}
figure{margin:16px 0 8px}
figure img{width:100%;border:1px solid var(--line);border-radius:4px}
.dl{margin:8px 0 2px;font-size:12px;color:var(--muted)}
.dl a{color:var(--accent);text-decoration:none;border-bottom:1px solid rgba(29,78,216,.35);
      padding-bottom:1px;margin-right:2px}
.dl a:hover{border-bottom-color:var(--accent)}
.dl .src{color:#9ca3af}
.figlist{width:100%;border-collapse:collapse;font-size:13px}
.figlist td{padding:7px 9px;border-bottom:1px solid var(--line);vertical-align:middle}
.figlist td:first-child{white-space:nowrap;font-weight:600;width:110px}
figcaption{color:var(--muted);font-size:12px;margin-top:6px}
.axswitch{display:flex;align-items:center;gap:14px;font-size:12.5px;color:#374151;
          margin:2px 0 6px;flex-wrap:wrap}
.axswitch b{font-weight:600}
.axswitch label{display:flex;align-items:center;gap:5px;cursor:pointer;user-select:none}
.axswitch input{accent-color:var(--accent);margin:0}
details{margin:10px 0 16px}
summary{cursor:pointer;color:var(--accent);font-size:13px;margin:8px 0}
code{background:#f3f4f6;padding:1px 5px;border-radius:3px;font-size:12px}
/* 每张图下方的绘图代码：默认收起，点击标题展开，展开态用底色 + 文案双重标识 */
details.code{margin:10px 0 2px;border:1px solid var(--line);border-radius:6px;
             background:#fcfcfd;overflow:hidden}
details.code summary{list-style:none;display:flex;align-items:center;gap:8px;
                     margin:0;padding:8px 12px;font-size:12.5px;color:#374151;
                     user-select:none;transition:background .15s}
details.code summary::-webkit-details-marker{display:none}
details.code summary::before{content:"▸";color:var(--accent);font-size:11px;line-height:1}
details.code summary code{background:#eef2f7;color:#334155;font-size:11.5px}
details.code summary:hover{background:#f3f6fb}
details.code summary .hint{margin-left:auto;font-size:11.5px;color:var(--muted);white-space:nowrap}
details.code summary .hint::after{content:"点击展开"}
details.code[open]{border-color:#bfd3f8;box-shadow:0 0 0 1px #e3ecfd}
details.code[open] summary{background:#eef4ff;color:var(--accent);font-weight:600;
                           border-bottom:1px solid #dbe6fb}
details.code[open] summary::before{content:"▾"}
details.code[open] summary .hint{color:var(--accent);font-weight:400}
details.code[open] summary .hint::after{content:"已展开 · 点击收起"}
details.code pre{margin:0;padding:12px 14px;background:#f8fafc;overflow:auto;
                 max-height:460px;font-family:Consolas,"Courier New",monospace;
                 font-size:12px;line-height:1.55;tab-size:4}
details.code pre code{background:none;padding:0;font-size:inherit;white-space:pre}
details.code .codetip{padding:8px 14px;border-top:1px dashed var(--line);
                      font-size:11.5px;color:var(--muted);background:#fff}
.ref{font-size:12.5px;color:#374151}
.foot{margin-top:36px;padding-top:14px;border-top:1px solid var(--line);
      color:var(--muted);font-size:12px}
@media print{body{background:#fff}.wrap{box-shadow:none;margin:0;padding:0;max-width:none}}
"""


def _fmt(v):
    if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))):
        return "—"
    if isinstance(v, (float, np.floating)):
        return f"{v:.4g}"
    return str(v)


def _table(df: pd.DataFrame, cols: list[str] | None = None,
           rename: dict | None = None, allow_html: tuple[str, ...] = ()) -> str:
    if df is None or df.empty:
        return '<p class="empty">无可用数据</p>'
    d = df.copy()
    if rename:
        d = d.rename(columns=rename)
        if cols:
            cols = [rename.get(c, c) for c in cols]
    if cols:
        d = d[[c for c in cols if c in d.columns]]
    # 矿物名统一按 names.json 显示（中文数据 → 英文名），与图件保持一致
    for col in ("mineral", "矿物"):
        if col in d.columns:
            d[col] = d[col].map(lambda v: names.mineral(str(v)) if pd.notna(v) else v)
    allow = set(allow_html)
    for c in d.columns:
        if pd.api.types.is_numeric_dtype(d[c]):
            d[c] = d[c].map(_fmt)
        else:
            d[c] = d[c].map(lambda x: "" if x is None else str(x))
        if allow:
            # 指定列允许写 <br>（参数逐行排列），其余列照旧转义
            d[c] = d[c].map(lambda x, col=c: str(x) if col in allow
                            else _html.escape(str(x)))
    return d.to_html(index=False, classes="tbl", border=0, escape=not allow)


# 图文件 → 绘制它的函数（都用 adsorp/viz.py 里的公开入口）
_CODE_FUNCS = {
    "isotherm": "plot_isotherms",
    "kinetics": "plot_kinetics",
    "ipd": "plot_ipd",
    "edge": "plot_edges",
    "qc": "plot_qc",
    "residuals": "plot_residuals",
}


def _plot_source(stem: str) -> str:
    """取出画这张图的函数源码。

    直接按 AST 行号从 ``viz.py`` 切片，不 import 该模块——报告生成时不必
    再初始化一次 matplotlib，也保证贴出来的是文件里的当前代码。
    """
    func = _CODE_FUNCS.get(stem)
    if not func:
        return ""
    try:
        src = Path(__file__).with_name("viz.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
    except (OSError, SyntaxError):
        return ""
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == func:
            lines = src.splitlines()
            return "\n".join(lines[node.lineno - 1:node.end_lineno])
    return ""


def _code_block(stem: str) -> str:
    """图下方的可折叠代码块（默认收起，点击标题展开，再点收起）。"""
    src = _plot_source(stem)
    if not src:
        return ""
    func = _CODE_FUNCS.get(stem, "")
    body = _html.escape(textwrap.dedent(src))
    return (
        '<details class="code">'
        f"<summary>绘图代码 · <code>adsorp/viz.py</code> · <code>{func}()</code>"
        '<span class="hint"></span></summary>'
        f"<pre><code>{body}</code></pre>"
        '<div class="codetip">同图相关的辅助函数（<code>_panel</code>、'
        "<code>_headroom</code>、<code>_draw_keys</code> 等）与配色/字号常量"
        "（<code>S.*</code>）分别在同文件的模块级与 <code>adsorp/style.py</code> 中；"
        "改完重跑 <code>adsorp.bat run</code> 即可生效。</div>"
        "</details>"
    )


def _dl_links(png: Path, stem: str) -> str:
    """单图下载链接：PNG + 可选 PDF + 源文件说明。

    一律用 ``figures/`` 相对路径，不用 ``data:`` 链接——后者保存下来会被
    打上 Mark-of-the-Web，Windows 默认安全设置会拒绝打开。
    """
    links = [f'<a download="{stem}.png" href="figures/{png.name}">下载 PNG（300 dpi）</a>']
    pdf = png.with_suffix(".pdf")
    if pdf.exists():
        links.append(f'<a download="{stem}.pdf" href="figures/{pdf.name}">下载 PDF（矢量）</a>')
    links.append(f'<span class="src">源文件：figures/{png.name} ｜ 代码：adsorp/viz.py</span>')
    return " · ".join(links)


def _img(path: Path, caption: str, fname: str | None = None) -> str:
    """内嵌图片 + PNG/PDF 单图下载按钮 + 该图的绘图代码（可折叠）。

    图片以 base64 内嵌，报告单独转发也能显示。
    """
    if not path.exists():
        return ""
    b64 = base64.b64encode(path.read_bytes()).decode()
    return (f'<figure><img src="data:image/png;base64,{b64}" alt="{caption}">'
            f"<figcaption>{caption}</figcaption>"
            f'<div class="dl">{_dl_links(path, fname or path.stem)}</div>'
            f"{_code_block(path.stem)}</figure>")


def _img_switch(fig_dir: Path, stem: str, alt_stem: str, caption: str) -> str:
    """带横坐标切换的图：``stem``＝默认线性版，``alt_stem``＝对数版。

    两版 PNG/PDF 都以 base64 内嵌，单选按钮切换显示；下载链接跟随所选版本。
    任何一个版本文件缺失时自动跳过，两版都缺则返回空串。
    """
    group = stem
    imgs, dls = [], []
    for ver, st in (("lin", stem), ("log", alt_stem)):
        png = fig_dir / f"{st}.png"
        if not png.exists():
            continue
        b64 = base64.b64encode(png.read_bytes()).decode()
        disp = "" if ver == "lin" else ' style="display:none"'
        imgs.append(f'<img data-ax="{group}" data-ver="{ver}"{disp} '
                    f'src="data:image/png;base64,{b64}" alt="{caption}">')
        dls.append(f'<div class="dl" data-ax="{group}" data-ver="{ver}"{disp}>'
                   f"{_dl_links(png, st)}</div>")
    if not imgs:
        return ""
    switch = (f'<div class="axswitch"><b>横坐标：</b>'
              f'<label><input type="radio" name="ax_{group}" value="lin" checked '
              f'onchange="axSwitch(this)">线性</label>'
              f'<label><input type="radio" name="ax_{group}" value="log" '
              f'onchange="axSwitch(this)">对数</label></div>')
    return (f'<figure>{switch}{"".join(imgs)}'
            f"<figcaption>{caption}</figcaption>"
            f'{"".join(dls)}{_code_block(stem)}</figure>')


def _audit_summary(audit: pd.DataFrame) -> pd.DataFrame:
    """把逐模型审计压成"每组一行"的结论表。

    实验员真正要回答的是两个问题：这组的结论站不站得住、站不住时该换哪个模型。
    """
    if audit is None or audit.empty:
        return pd.DataFrame()
    rows = []
    for (kind, mineral, bg), g in audit.groupby(["kind", "mineral", "background"], sort=False):
        g = g.sort_values("dAICc")
        best = g.iloc[0]
        rest = g.iloc[1:]
        second = float(rest["dAICc"].min()) if len(rest) else np.nan
        bad = ["参数不可识别（触界/共线）", "多解（收敛率偏低）", "模型不适定（R²<0.5）"]
        # 可替代模型：只要判据没被判死就纳入，哪怕 ΔAICc 偏大——
        # 说"用它、但支持度弱"比说"没有替代"更有信息量。
        usable = g[~g["verdict"].isin(bad)]
        alt = usable.iloc[0] if len(usable) else None
        best_bad = best["verdict"] in bad
        if best_bad and alt is not None:
            verdict = (f"最优 {best['model_label']} 参数不可用；可改用 {alt['model_label']}"
                       f"（ΔAICc={alt['dAICc']:.1f}，R²={alt['R2']:.2f}）")
        elif best_bad:
            verdict = "全部模型参数均不可靠，只报告趋势"
        elif np.isfinite(second) and second <= 2:
            verdict = f"最优 {best['model_label']} 与次优无实质差异（ΔAICc={second:.1f}）"
        else:
            verdict = f"最优 {best['model_label']} 明显优于其余（ΔAICc≥{second:.1f}）"
        rows.append({
            "实验": {"isotherm": "等温线", "kinetics": "动力学"}.get(kind, kind),
            "矿物": mineral, "背景": bg,
            "最优模型": best["model_label"], "R²": best["R2"], "AICc": best["AICc"],
            "次位 ΔAICc": second,
            "最优参数可用": "否" if best_bad else "是",
            "结论": verdict,
        })
    return pd.DataFrame(rows)


def _param_text(row, model) -> str:
    """把一个模型的所有参数写成 'name = 值 ± SE 单位'，逐行用 <br> 分隔。"""
    parts = []
    for name, unit in zip(model.names, model.unit_hint):
        v = row.get(f"par_{name}")
        if v is None or pd.isna(v):
            continue
        se = row.get(f"par_{name}_SE")
        txt = f"{name} = {_fmt(v)}"
        if se is not None and pd.notna(se) and np.isfinite(se) and se > 0:
            txt += f" ± {_fmt(se)}"
        if unit and unit != "—":
            txt += f" {unit}"
        parts.append(txt)
    if model.key == "dr" and pd.notna(row.get("par_K_DR")):
        parts.append(f"E = {1.0 / np.sqrt(2.0 * max(float(row['par_K_DR']), 1e-30)):.2f} kJ/mol")
    return "<br>".join(parts)


def _all_param_rows(fits: pd.DataFrame, exp: str) -> pd.DataFrame:
    """全部模型（不只是最优）的参数、误差指标与判定。

    每个模型一行，参数列逐个写出数值 ± 标准误与单位；ΔAICc 相对同组最优，
    组内按 R² 从高到低排列，便于直接看出各模型的拟合程度。
    """
    from .models import ISOTHERM_MODELS, KINETIC_MODELS

    lib = ISOTHERM_MODELS if exp == "isotherm" else KINETIC_MODELS
    if fits is None or fits.empty:
        return pd.DataFrame()

    df = fits.copy()
    if "AICc" in df:
        df["_dAICc"] = df["AICc"] - df.groupby(["mineral", "background"])["AICc"].transform("min")
    else:
        df["_dAICc"] = np.nan

    # 组内按 R² 降序（用户指定）；R² 缺失的排最后
    df["_r2sort"] = pd.to_numeric(df.get("R2"), errors="coerce")
    df = df.sort_values(["mineral", "background", "_r2sort"],
                        ascending=[True, True, False], na_position="last")

    rows = []
    for _, r in df.iterrows():
        model = lib.get(r["model"])
        if model is None:
            continue
        flags = []
        if bool(r.get("at_bound", False)):
            flags.append("参数触界")
        corr = r.get("max_param_corr")
        if pd.notna(corr) and np.isfinite(corr) and corr > 0.99:
            flags.append("参数共线")
        hit = r.get("start_hit_rate")
        if pd.notna(hit) and np.isfinite(hit) and hit < 0.5:
            flags.append("多解")
        rows.append({
            "矿物": r["mineral"], "背景": r["background"],
            "模型": r.get("model_label", r["model"]),
            "参数": _param_text(r, model),
            "R²": _fmt(r.get("R2")), "adj-R²": _fmt(r.get("adj_R2")),
            "RMSE": _fmt(r.get("RMSE")), "AICc": _fmt(r.get("AICc")),
            "ΔAICc": ("—" if not np.isfinite(r.get("_dAICc", np.nan))
                      else ("0" if abs(r["_dAICc"]) < 1e-9 else f"{r['_dAICc']:.2f}")),
            "判定": "；".join(flags) if flags else "可解释",
        })
    return pd.DataFrame(rows)


def _model_legend_table() -> pd.DataFrame:
    """模型清单：名称、方程、参数与单位。"""
    from .models import ISOTHERM_MODELS, KINETIC_MODELS

    rows = []
    for kind, lib in (("等温线", ISOTHERM_MODELS), ("动力学", KINETIC_MODELS)):
        for m in lib.values():
            unit = "；".join(f"{n} ({u})" if u and u != "—" else n
                            for n, u in zip(m.names, m.unit_hint))
            rows.append({"类别": kind, "模型": m.label, "方程": m.formula, "参数与单位": unit})
    return pd.DataFrame(rows)


def write_html(out: Path, data, qc, iso_best, iso_fits, kin_best, kin_fits, ipd,
               edge_params, edge_cmp, curves_iso, curves_kin,
               solid, audit=None, issues=None):
    fig_dir = out / "figures"
    n_issue = 0 if issues is None or issues.empty else len(issues)
    kpis = [
        (len(data), "有效数据点"),
        (len(iso_best) if not iso_best.empty else 0, "等温线样品组"),
        (len(kin_best) if not kin_best.empty else 0, "动力学样品组"),
        (edge_params["mineral"].nunique() if not edge_params.empty else 0, "吸附边矿物"),
        (n_issue, "待核查点"),
    ]
    kpi_html = "".join(f'<div class="kpi"><b>{v}</b><span>{k}</span></div>' for v, k in kpis)

    # 规则生成的解读性文字不再进入报告：脚本无法保证对每个体系都描述准确，
    # 这类信息只在控制台摘要（_print_summary）里给出，报告只保留数据表。

    issues_html = ""
    if issues is not None and not issues.empty:
        issues_html = (
            "<h3>数据质量清单</h3>"
            '<p class="cap">脚本<b>不改动任何实测值</b>，负吸附、Ce &gt; C0、吸附率 &gt; 100% '
            "等一律原样保留并参与计算与绘图，只在此列出。行号对应模板 Data 表的实际行；"
            "确认要剔除某点时，在该行 <code>exclude</code> 列填 <code>TRUE</code> 后重跑，"
            "否则该点保持参与。</p>"
            '<div class="scroll">'
            + _table(issues, rename={
                "exp": "实验", "mineral": "矿物", "background": "背景",
                "row": "Excel 行", "condition": "条件", "Ce_ppm": "Ce / mg·L⁻¹",
                "removal_pct": "吸附率 / %", "issue": "问题", "suggestion": "建议"})
            + "</div>")

    # 固液比说明只写本次数据中实际出现的矿物：
    # config.json 里其他体系的默认值一概不列，避免读起来像"这些数据也用了"；
    # 数据里有样品却查不到固液比的，明确说明其 qe 仍以 mg/L(悬浮液) 计。
    present_minerals: list[str] = []
    if "mineral" in data:
        for m in data["mineral"].dropna():
            nm = names.mineral(str(m))
            if nm not in present_minerals:
                present_minerals.append(nm)
    if isinstance(solid, dict):
        lookup = {names.mineral(str(k)): float(v) for k, v in solid.items()
                  if isinstance(v, (int, float)) and np.isfinite(v) and v > 0}
        have = [(m, lookup[m]) for m in present_minerals if m in lookup]
        missing = [m for m in present_minerals if m not in lookup]
    elif isinstance(solid, (int, float)) and np.isfinite(solid) and solid > 0:
        have = [(m, float(solid)) for m in present_minerals]
        missing = []
    else:
        have, missing = [], list(present_minerals)
    pairs = "、".join(f"{m} {v:g} g/L" for m, v in have)
    miss_txt = "、".join(missing)
    if have and not missing:
        solid_line = (f"固液比 m/V 按矿物分别取值：{pairs}。qe = (C0−Ce)/(m/V)，单位为 mg/g。")
        has_solid = True
    elif have:
        solid_line = (f"固液比 m/V：{pairs}；{miss_txt} 未提供固液比，"
                      "其吸附量以 (C0−Ce) 计，单位为 mg/L(悬浮液)。")
        has_solid = False
    else:
        solid_line = (f"未提供固液比 m/V（{miss_txt or '数据中出现的矿物'}）："
                      "qe 记为 (C0−Ce)，单位为 mg/L(悬浮液)。"
                      "在 config.json 的 solids_g_per_L 或模板 Settings 的 solid:矿物 行补入后重跑，"
                      "即可换算为 mg/g。")
        has_solid = False
    qe_note = ("纵轴为 mg/g" if has_solid
               else "纵轴以 mg/L(悬浮液) 计，未换算为 mg/g")
    files = [f for f in dict.fromkeys(data.get("file", [])) if isinstance(f, str)]
    if len(files) == 1:
        source_line = f"数据源：{files[0]}"
    elif files:
        source_line = f"数据源：{len(files)} 个文件（{', '.join(files[:3])}{' 等' if len(files) > 3 else ''}）"
    else:
        source_line = "数据源：未记录"
    # 换算链说明只在使用了浓度原始列（conc_ppb）时出现，其他数据源不写死
    conv_line = ("浓度换算链：荧光值 → 标线浓度 (ppb) → ×校正因子 → ×稀释倍数/1000 → Ce (ppm)；"
                 if "conc_ppb" in data.columns else "")

    iso_caption = ("图 1 等温线实测点（误差棒为 SD，仅平行样才画）、AICc 最优模型"
                   "及 Langmuir / Freundlich 参照；最优模型参数触界或严重共线时"
                   "该组只画参照线，判定见“模型可靠性”表；" + qe_note +
                   "。横轴为残余浓度 C<sub>e</sub>，默认线性坐标，"
                   "可在图上方切换为对数坐标")
    qc_valid = qc.dropna(subset=["recovery_pct"]) if not qc.empty else qc
    n_drop = 0 if qc.empty else len(qc) - len(qc_valid)
    qc_note_line = (f'<div class="note">另有 {n_drop} 条 QC 记录未给出校正终液浓度（表中记 —），'
                    f'无法计算回收率，已从下表略去。</div>' if n_drop else '')

    ov = data.copy()
    # 样品组名用英文矿物名，和图上保持一致（模板已改为直接填英文）
    if "mineral" in ov:
        ov["group"] = (ov["exp"].astype(str) + "-" + ov["mineral"].map(names.mineral)
                       + "-" + ov["background"].astype(str))
    overview = (ov.groupby(["exp", "group"], as_index=False)
                .agg(数据点=("removal_pct", "size"),
                     吸附率最小=("removal_pct", "min"),
                     吸附率最大=("removal_pct", "max")))
    overview.columns = ["实验", "样品组", "数据点", "吸附率最小/%", "吸附率最大/%"]

    audit_html = ""
    if audit is not None and not audit.empty:
        summ = _audit_summary(audit)
        audit_html = (
            "<p>判据：参数触界或 max|r|&gt;0.99 → 参数不可分辨；多起点收敛率 &lt;0.5 → 解不唯一；"
            "ΔAICc ≤ 2 → 与最优模型无实质差别。R² 不参与判定——参数个数不同的模型不能直接比。</p>"
            + _table(summ))

        # MATLAB 全模型复核：所有模型都要独立验证，脚本随 run 生成
        from .models import ISOTHERM_MODELS, KINETIC_MODELS
        mfile = out / "matlab_verify.m"
        if mfile.exists():
            n_iso_models = len(ISOTHERM_MODELS)
            n_kin_models = len(KINETIC_MODELS)
            n_iso_grp = len(curves_iso) if curves_iso else 0
            n_kin_grp = len(curves_kin) if curves_kin else 0
            audit_html += (
                "<h3>与 MATLAB 全模型复核脚本的一致性</h3>"
                f"<p>输出目录的 <code>matlab_verify.m</code> 覆盖本项目<b>全部"
                f" {n_iso_models} 个等温线 + {n_kin_models} 个动力学模型</b>"
                f"（{n_iso_grp} 组等温线、{n_kin_grp} 组动力学数据），并内嵌本次全部实测点。"
                "在 MATLAB 中运行 <code>matlab_verify</code>（R2016b+，无需任何工具箱）："
                "脚本用 <code>fminsearch</code>（Nelder-Mead）从 20 个起点"
                "（第 1 个取本项目的最优参数，其余为其对数扰动）重新拟合每个模型，"
                "打印参数、SSE、R²、AICc，并与本项目结果逐模型对比。</p>"
                "<p>判读：<b>relDiff &lt; 1e-6%</b> → 两条路径收敛到同一最优解，Python 结果可信；"
                "若 MATLAB 找到明显更低的 SSE，说明本项目落入局部极小，以 MATLAB 结果为准并复核该模型。"
                "逐模型对比结果可直接复制脚本输出留存。</p>")

    fig_items = [("图 1", "等温线 Isotherm", "isotherm"),
                 ("图 2", "残差 Residuals", "residuals"),
                 ("图 3", "动力学 Kinetics", "kinetics"),
                 ("图 4", "颗粒内扩散 IPD", "ipd"),
                 ("图 5", "吸附边 Edge", "edge"),
                 ("图 6", "QC", "qc")]
    rows, stems = [], []
    for no, title, stem in fig_items:
        png, pdf = fig_dir / f"{stem}.png", fig_dir / f"{stem}.pdf"
        if not png.exists():
            continue
        stems.append(stem)
        links = f'<a href="figures/{stem}.png" download="{stem}.png">PNG</a>'
        if pdf.exists():
            links += f' · <a href="figures/{stem}.pdf" download="{stem}.pdf">PDF</a>'
        rows.append(f"<tr><td>{no}</td><td>{title}</td><td>{links}</td>"
                    f'<td class="src">figures/{stem}.png</td></tr>')
    zip_path = fig_dir / "figures_en.zip"
    if stems:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            # 打包目录里全部 PNG/PDF：除 6 张主图外，还包含等温线/动力学的
            # 对数横坐标版本（isotherm_log.* / kinetics_log.*）
            for f in sorted(fig_dir.iterdir()):
                if f.suffix in (".png", ".pdf"):
                    z.write(f, f.name)
    zip_link = ('<a href="figures/figures_en.zip" download="figures_en.zip">'
                '打包下载全部图件（ZIP，PNG + PDF）</a>' if zip_path.exists() else "")
    fig_section = f"""<h2>七、图件下载与源文件</h2>
<p>每张图下方都有「下载 PNG / 下载 PDF」按钮，指向报告旁 <code>figures/</code> 文件夹里的同名文件
（PNG 300 dpi + 矢量 PDF）。<strong>请将本报告与 figures 文件夹放在同一目录下保存或转发</strong>——
图片本身以 base64 内嵌、单独转发 HTML 也能正常显示，但下载按钮需要 figures 文件夹在场。</p>
<details><summary>下载的 PNG 双击打不开？（"Internet 安全设置阻止打开"）</summary>
<p style="margin:6px 0 2px">文件<b>并没有损坏</b>：这是 Windows 的 Mark-of-the-Web 机制——
浏览器会给"从网页下载"落盘的文件附加 Internet 区域标记，而系统的安全设置禁止直接打开带此标记的文件。
三种解决办法任选：</p>
<ol style="margin:6px 0 2px 22px">
<li>右键该 PNG → <b>属性</b> → 常规页底部勾选<b>「解除锁定」</b> → 确定，之后即可正常打开；</li>
<li>批量解除：PowerShell 执行 <code>Get-ChildItem "C:\\Users\\Uers\\Downloads\\*.png" | Unblock-File</code>；</li>
<li>直接使用 <code>output/figures/</code> 里的原图——它们由脚本直接写入磁盘，不带网络标记。</li>
</ol>
</details>
<table class="figlist">{"".join(rows)}</table>
<p style="margin-top:12px">{zip_link}</p>
<div class="note">图件为纯英文，可直接用于英文稿件；版式 17.2 cm 双栏、Times New Roman、四边细框、刻度朝内。
生成代码见 <code>adsorp/viz.py</code>（绘图）与 <code>adsorp/style.py</code>（样式）；矿物英文名可在
<code>names.json</code> 中修改，改完重跑即可。</div>"""

    # 标题不写死体系与元素，任何吸附体系通用
    h1 = "数据分析报告：等温线、动力学与 pH 吸附边"

    html = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_html.escape(h1)}</title><style>{CSS}</style></head><body><div class="wrap">
<h1>{_html.escape(h1)}</h1>
<div class="sub">自动生成于 {datetime.now():%Y-%m-%d %H:%M} ｜ {source_line}</div>

<div class="kpis">{kpi_html}</div>

<h2>一、数据概览</h2>
<div class="note">{solid_line}<br>
{conv_line}吸附率 = 100×(1−Ce/C0)。</div>
{_table(overview)}
{issues_html}

<h2>二、吸附等温线</h2>
<p>对每组数据同时拟合全部等温线模型并按 AICc 排序；Ce 或 qe ≤ 0 的点超出模型定义域，
自动跳过（各类模型的拟合点数见 <code>tables/等温线_全部模型.csv</code>）。</p>
{_img_switch(fig_dir, "isotherm", "isotherm_log", iso_caption)}
{_img(fig_dir / "residuals.png", "图 2 最优模型的相对残差–实测值；虚线为 ±10%。纵轴按残差的稳健范围（中位数 + 3×MAD）自适应，低负载点的相对误差会被检出限放大，个别点因此落在框外；原始残差见 tables/长表数据.csv")}
<h3>全部模型参数（组内按 R² 降序）</h3>
<p>ΔAICc 以同组最优模型为 0，≤2 表示与最优无实质差别；
「判定」标出参数触界、参数共线（max|r|&gt;0.99）与多解（收敛率 &lt;0.5）——这三类情况的参数不可独立引用。</p>
{_table(_all_param_rows(iso_fits, "isotherm"), allow_html=("参数",))}
<details><summary>展开：原始拟合表（含 95% 置信区间与全部误差函数）</summary>
<div class="scroll">{_table(iso_fits)}</div></details>

<h2>三、吸附动力学</h2>
<p>动力学以 qt=(C0−Ct)/(m/V) 表示；未提供 m/V 时以 mg/L(悬浮液) 表示，曲线形状与 k 不受影响。
对每组数据同时拟合全部动力学模型，并分段拟合 qt–t<sup>0.5</sup> 判别颗粒内扩散阶段。</p>
{_img_switch(fig_dir, "kinetics", "kinetics_log", "图 3 动力学曲线（误差棒为 SD，仅平行样才画）、AICc 最优模型及 PFO / PSO 参照；横轴为时间，默认线性坐标，可在图上方切换为对数坐标")}
{_img(fig_dir / "ipd.png", "图 4 颗粒内扩散分段拟合；两段直线的交点即转折时间")}
<h3>全部模型参数（组内按 R² 降序）</h3>
{_table(_all_param_rows(kin_fits, "kinetics"), allow_html=("参数",))}
<h3>颗粒内扩散参数</h3>
{_table(ipd, ["mineral", "background", "break_t_h", "k_id1", "C1", "k_id2", "C2"],
        rename={"mineral": "矿物", "background": "背景", "break_t_h": "断点 t/h",
                "k_id1": "k_id1", "C1": "C1", "k_id2": "k_id2", "C2": "C2"})}
<details><summary>展开：原始动力学拟合表（含 95% 置信区间与全部误差函数）</summary>
<div class="scroll">{_table(kin_fits)}</div></details>

<h2>四、pH 吸附边与离子强度</h2>
<p>用四参数 logistic 曲线拟合吸附率–pH 关系，pH<sub>50</sub> 为拟合曲线中点（bottom 与 top 之间），
斜率反映边的陡峭程度。当高 pH 残余平台明显不同时，pH<sub>50</sub> 不宜直接横向排序，应以逐 pH 差值判断；
另对 20–80% 吸附窗口做 log K<sub>d</sub>–pH 线性回归，其斜率可指示质子释放/表面络合计量比。</p>
{_img(fig_dir / "edge.png", "图 5 不同离子强度下的吸附边；实线为四参数 logistic 拟合，仅当 R²≥0.6 时绘出，未达标的组只画散点、pH<sub>50</sub> 一栏留空。图例统一置于图下方")}
<h3>吸附边参数</h3>
{_table(edge_params, ["mineral", "background", "n_points", "pH_range", "pH50", "pH50_SE",
                      "edge_width", "slope_at_pH50", "plateau_high", "R2_logistic",
                      "logKd_slope", "logKd_R2", "n_outlier", "outlier_pH", "reliable"],
        rename={"mineral": "矿物", "background": "背景", "n_points": "点数",
                "pH_range": "pH 范围", "pH50": "pH50", "pH50_SE": "pH50 SE",
                "edge_width": "边宽", "slope_at_pH50": "pH50 处斜率",
                "plateau_high": "高 pH 平台", "R2_logistic": "R²",
                "logKd_slope": "logKd–pH 斜率", "logKd_R2": "logKd R²",
                "n_outlier": "离群点数", "outlier_pH": "离群 pH", "reliable": "可靠"})}
<h3>离子强度效应</h3>
{_table(edge_cmp, rename={"mineral": "矿物", "pair": "对比组", "overlap_pH": "pH 重叠区",
                          "max_delta_theta_pct": "最大差值/百分点",
                          "mean_delta_theta_pct": "平均差值/百分点",
                          "direction": "方向", "hint": "解读"})}

<h2>五、质量控制</h2>
{_img(fig_dir / "qc.png", "图 6 检查标准回收率；虚线为 80% / 120% 接受区间，实线为 100%")}
{qc_note_line}{_table(qc_valid, ["exp", "qc", "nominal_ppb", "conc_ppb", "recovery_pct"],
        rename={"exp": "实验", "qc": "检查标准", "nominal_ppb": "标称 ppb",
                "conc_ppb": "测定 ppb", "recovery_pct": "回收率 %"})}

<h2>六、拟合可靠性与模型选择</h2>
<h3>模型清单与方程</h3>
{_table(_model_legend_table())}
{audit_html}

{fig_section}
<div class="foot">本报告由 <code>python -m adsorp.cli run</code>（或 <code>run_analysis.py</code>）自动生成；所有数值表同时导出至
<code>结果汇总.xlsx</code>，长表数据见 <code>tables/长表数据.csv</code>。</div>
<script>
function axSwitch(inp) {{
  var g = inp.name.replace(/^ax_/, "");
  document.querySelectorAll('[data-ax="' + g + '"]').forEach(function (el) {{
    el.style.display = (el.getAttribute("data-ver") === inp.value) ? "" : "none";
  }});
}}
</script>
</div></body></html>"""
    path = out / "报告.html"
    path.write_text(html, encoding="utf-8")
    return path


def write_excel(out: Path, data, qc, iso_fits, iso_best, kin_fits, kin_best, ipd,
                kin_eq, edge_params, edge_cmp, audit=None):
    path = out / "结果汇总.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as w:
        data.to_excel(w, sheet_name="长表数据", index=False)
        qc.to_excel(w, sheet_name="QC", index=False)
        iso_best.to_excel(w, sheet_name="等温线_最优", index=False)
        iso_fits.to_excel(w, sheet_name="等温线_全部模型", index=False)
        kin_best.to_excel(w, sheet_name="动力学_最优", index=False)
        kin_fits.to_excel(w, sheet_name="动力学_全部模型", index=False)
        ipd.to_excel(w, sheet_name="颗粒内扩散", index=False)
        kin_eq.to_excel(w, sheet_name="平衡时间", index=False)
        edge_params.to_excel(w, sheet_name="吸附边参数", index=False)
        edge_cmp.to_excel(w, sheet_name="离子强度对比", index=False)
        if audit is not None and not audit.empty:
            audit.to_excel(w, sheet_name="模型可靠性", index=False)
    return path
