"""分析流水线：数据 → 计算 → 拟合 → 图 → 报告。

被 ``adsorp.cli`` 与 ``run_analysis.py`` 共用。数据来源两种：

* ``template=`` 读填写好的 Excel 模板（推荐，含固液比等元数据）；
* ``data_dir=`` 读仪器导出的原始 AFS 工作簿（兼容既有流程）。

``reuse=True`` 时复用上一次运行缓存的拟合结果（``output/_analysis.pkl``），
只重绘图与重出报告——调图版式时不必每次等拟合。
"""
from __future__ import annotations

import json
import pickle
from pathlib import Path

import numpy as np
import pandas as pd

from . import analyze, names as N, report, style as S, viz
from .io import has_workbooks, list_workbooks, read_all
from .template import read_template, split_workbooks

BASE = Path(__file__).resolve().parent.parent

CACHE_KEYS = ["data", "qc", "eq", "ipd", "iso_fits", "iso_best", "curves_iso",
              "kin_fits", "kin_best", "curves_kin", "edge_params", "curves_edge",
              "edge_cmp", "warns", "audit", "solid", "issues", "dr_ctx"]


def load_config(path: Path) -> dict:
    cfg = {"solid_g_per_L": None, "data_dir": "data", "output_dir": "output", "defaults": {}}
    if path.exists():
        cfg.update(json.loads(path.read_text(encoding="utf-8")))
    return cfg


def resolve_data_dir(cfg: dict, override: str | Path | None = None) -> Path:
    """确定原始工作簿目录：``--data-dir`` > ``config.data_dir`` > 项目根。

    未显式指定时，若配置目录里没有可识别的表，就回退项目根目录——这样
    「把 Excel 直接丢进项目文件夹、双击 adsorp.bat」也能跑。
    """
    if override:
        p = Path(override)
        return (p if p.is_absolute() else Path.cwd() / p).resolve()
    p = Path(cfg.get("data_dir") or "data")
    p = (p if p.is_absolute() else BASE / p).resolve()
    if has_workbooks(p) or not has_workbooks(BASE):
        return p
    return BASE


def resolve_solid(cfg: dict, override: float | None) -> float | dict | None:
    solid = cfg.get("solids_g_per_L") or cfg.get("solid_g_per_L")
    if override is not None:
        solid = override
    if isinstance(solid, dict) and not any(
            isinstance(v, (int, float)) and np.isfinite(v) and v > 0 for v in solid.values()):
        solid = None
    return solid


def _merge_template_solids(data: pd.DataFrame, cfg_t: dict,
                           solid: float | dict | None,
                           io_warn: list[str]):
    """把模板 Settings 的 ``solid:<名称>`` 合并进本次固液比。

    模板里的值代表本次数据集，优先于 config.json 的默认字典；``--solid`` 标量
    仍然最高（调用方已处理）。键允许写中文，统一经 names 映射后再合并。
    """
    tmpl_solids = {}
    for k, v in (cfg_t.get("solids_g_per_L") or {}).items():
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if np.isfinite(fv) and fv > 0:
            tmpl_solids[N.mineral(str(k))] = fv
    if tmpl_solids:
        # 名称全对不上＝等于没填：Settings 写 solid:钙锰矿、Data 全写 Todorokite 时，
        # 固液比会静默丢失、qe 退化成 mg/L(悬浮液)。只有"一个都对不上"才报警，
        # 否则 Settings 里多带的其它体系（本次数据没用到）会造成无谓的噪声。
        present = {str(m) for m in data["mineral"].dropna().unique()} if "mineral" in data else set()
        if present and not (set(tmpl_solids) & present):
            io_warn.append(
                "Settings 的固液比没匹配到数据里的吸附剂名："
                + "、".join(f"solid:{k}" for k in sorted(tmpl_solids)[:5])
                + f"；数据中是 {'、'.join(sorted(present)[:6])}。"
                "两边写成同一个名字（或在 names.json 里建立映射）才会生效，"
                "否则 qe 按 mg/L(悬浮液) 计算。")
        if solid is None:
            solid = tmpl_solids
        elif isinstance(solid, dict):
            solid = {**solid, **tmpl_solids}
    if solid is None and "solid_g_per_L" in data:
        per_row = {}
        for m, v in zip(data["mineral"], data["solid_g_per_L"]):
            if pd.notna(v):
                per_row.setdefault(m, float(v))
        solid = per_row or None
    # 逐行固液比与 Settings 冲突时说明一句：现在行内值优先（更具体），
    # 但填表人可能以为 Settings 会覆盖，qe 差一倍却看不出来源。
    if "solid_g_per_L" in data and isinstance(solid, dict):
        conflicts = sorted({
            f"{m}：表内 {float(v):g}、Settings {s:g}"
            for m, v in zip(data["mineral"], data["solid_g_per_L"])
            if pd.notna(v) and (s := analyze._solid_for(solid, m)) is not None
            and abs(float(v) - s) > 1e-9})
        if conflicts:
            io_warn.append("固液比在 Data 表与 Settings 中数值不同，已按 Data 表逐行值计算："
                           + "；".join(conflicts[:5])
                           + ("…" if len(conflicts) > 5 else ""))
    return solid


def _template_qc(cfg_t: dict) -> pd.DataFrame:
    """模板里的 exp=qc 行；没有时返回带列名的空表。"""
    qc = cfg_t.get("qc")
    if not isinstance(qc, pd.DataFrame) or qc.empty:
        qc = pd.DataFrame(columns=["exp", "qc", "nominal_ppb", "conc_ppb", "recovery_pct"])
    return qc


def run(*, data_dir: str | Path | None = None,
        template: str | Path | None = None,
        out: str | Path = "output",
        solid: float | None = None,
        config: str | Path = "config.json",
        names_file: str | Path | None = "names.json",
        make_figs: bool = True,
        reuse: bool = False,
        verbose: bool = True) -> dict:
    """跑完整条流水线，返回各产物路径与关键表。"""
    def log(msg: str):
        if verbose:
            print(msg, flush=True)

    if names_file:
        N.load(Path(names_file) if Path(names_file).is_absolute() else BASE / names_file)
    cfg = load_config(Path(config) if Path(config).is_absolute() else BASE / config)
    solid = resolve_solid(cfg, solid)

    out = Path(out)
    if not out.is_absolute():
        out = Path.cwd() / out
    out.mkdir(parents=True, exist_ok=True)
    (out / "figures").mkdir(exist_ok=True)
    (out / "tables").mkdir(exist_ok=True)
    cache = out / "_analysis.pkl"

    if reuse and cache.exists():
        log("[2/5] 复用上次的分析结果（reuse）")
        with cache.open("rb") as fh:
            st = pickle.load(fh)
        # 审计规则可能随代码更新，这里用缓存的拟合表重算一遍（毫秒级），
        # 避免 --reuse 时报告里留着旧判定。
        st["audit"] = pd.concat(
            [analyze.model_audit(st["iso_fits"], "isotherm"),
             analyze.model_audit(st["kin_fits"], "kinetics")], ignore_index=True)
        # 旧缓存没有逐点清单，用缓存里的原始长表重算（毫秒级，不重新拟合）
        if st.get("issues") is None:
            _solid = st.get("solid")
            st["issues"] = analyze.quality_issues(
                st["data"],
                analyze.isotherm_data(st["data"], _solid),
                analyze.kinetics_data(st["data"], _solid),
                analyze.edge_data(st["data"]),
                st.get("qc", pd.DataFrame()))
        return _finish(out, make_figs, verbose, {k: st.get(k) for k in CACHE_KEYS})

    cfg_t: dict = {}
    qc = pd.DataFrame(columns=["exp", "qc", "nominal_ppb", "conc_ppb", "recovery_pct"])
    io_warn: list[str] = []
    tpl = Path(template) if template else None

    if tpl is not None:
        log(f"[1/5] 读取模板：{tpl}")
        data, cfg_t, io_warn = read_template(tpl, defaults=cfg.get("defaults"))
        solid = _merge_template_solids(data, cfg_t, solid, io_warn)
        qc = _template_qc(cfg_t)
    else:
        data_dir = resolve_data_dir(cfg, data_dir)
        log(f"[1/5] 读取数据：{data_dir}")
        data = pd.DataFrame()
        # 目录里放什么就读什么，不看文件名：模板（Data+Settings 两张表）
        # 与仪器原始工作簿可以混放，各自走各自的分支。
        books = list_workbooks(data_dir)
        tpls, raws = split_workbooks(books)
        if len(raws) > 1:
            log(f"      发现 {len(raws)} 个工作簿：{'、'.join(p.name for p in raws)}")
        if raws:
            data, qc, metas, io_warn = read_all(data_dir, cfg, paths=raws)
            label = {"isotherm": "等温线", "kinetics": "动力学", "edge": "吸附边"}
            for _name, _m in metas.items():
                log(f"      {_name} → {label.get(_m.get('exp'), '未识别')}")
            if tpls:
                io_warn.append(
                    "目录里同时有模板（" + "、".join(p.name for p in tpls)
                    + "）与仪器原始工作簿，本次按原始工作簿计算；"
                    "想用模板请加 --template。")
        if data.empty and tpls:
            tpl = max(tpls, key=lambda p: p.stat().st_mtime)
            log(f"      改用模板：{tpl.name}")
            if len(tpls) > 1:
                io_warn.append(
                    "目录里有多个模板（" + "、".join(p.name for p in tpls)
                    + f"），本次用修改时间最新的 {tpl.name}；其余请加 --template 指定。")
            data, cfg_t, io_warn = read_template(tpl, defaults=cfg.get("defaults"))
            solid = _merge_template_solids(data, cfg_t, solid, io_warn)
            qc = _template_qc(cfg_t)

    if data.empty:
        if tpl is not None:
            msg = f"未解析到数据：模板 {tpl} 的 Data 表是空的，或列名不匹配。"
        else:
            seen = [p.name for p in list_workbooks(Path(data_dir))]
            hint = (f"目录里有 {len(seen)} 个 Excel（{'、'.join(seen[:4])}"
                    + ("…" if len(seen) > 4 else "") + "），但没有一个能识别。\n"
                    if seen else "目录里没有 Excel 文件。\n")
            msg = ("未解析到数据：data/ 和项目根目录都没有可识别的表。\n"
                   + hint
                   + "  · 仪器原始工作簿：直接放进去即可，软件按表内内容判断实验类型，不需要改文件名；\n"
                   "  · 已整理的长表：需有 Data 表（表头含 exp / mineral / Ce_ppm）；\n"
                   "  · 也可以 adsorp.bat run --template 你的表.xlsx 显式指定。")
        raise SystemExit(msg)
    log(f"      {len(data)} 行有效数据；QC {len(qc)} 条")
    # 配色/形状按本次数据的名称登记，换体系不需要改代码
    S.register_categories(data["mineral"], data["background"])

    log(f"[2/5] 计算 Ce / qe / 吸附分数")
    # D-R 的 ε 依赖吸附质摩尔质量与温度，两者都在模板 Settings 里；
    # 这里在读数据后立即生效，后面的拟合与出图都用同一套常数。
    from .models import configure_dr
    settings = (cfg_t.get("settings") or {}) if cfg_t else {}
    dr_ctx = configure_dr(settings.get("molar_mass_g_per_mol"),
                          settings.get("temperature_K"))
    if settings and dr_ctx.get("molar_mass"):
        log(f"      D-R 常数：M = {dr_ctx['molar_mass']:g} g/mol，"
            f"T = {dr_ctx['temperature']:g} K")
    elif settings:
        log("      未提供 molar_mass_g_per_mol，本次跳过 D-R 模型")
    iso = analyze.isotherm_data(data, solid)
    kin = analyze.kinetics_data(data, solid)
    edge = analyze.edge_data(data)
    eq = analyze.equilibrium_time(kin)

    log("[3/5] 拟合等温线、动力学与吸附边")
    iso_fits, iso_best, curves_iso, w1 = analyze.analyze_isotherms(iso, solid)
    kin_fits, kin_best, ipd, curves_kin, w2 = analyze.analyze_kinetics(kin, solid)
    if not kin_best.empty:
        r2map = kin_best.set_index(["mineral", "background"])["R2"].to_dict()
        eq["fit_R2"] = [r2map.get((r["mineral"], r["background"]), np.nan)
                        for _, r in eq.iterrows()]
        eq.loc[eq["fit_R2"] < 0.5, "t_eq_h"] = np.nan
        eq["note"] = np.where(eq["fit_R2"] < 0.5, "无明确时间趋势，未定义平衡时间", "")
    edge_params, curves_edge, edge_cmp, w3 = analyze.analyze_edges(edge)
    warns = (io_warn + analyze.raw_warnings(data) + w1 + w2 + w3
             + analyze.data_warnings(iso, kin, edge, qc))
    if not dr_ctx.get("molar_mass"):
        warns.append("未填吸附质摩尔质量（Settings 的 molar_mass_g_per_mol），"
                     "D-R 模型未参与拟合；其余等温线模型不受影响。")
    issues = analyze.quality_issues(data, iso, kin, edge, qc)

    iso_audit = analyze.model_audit(iso_fits, "isotherm")
    kin_audit = analyze.model_audit(kin_fits, "kinetics")
    audit = (pd.concat([iso_audit, kin_audit], ignore_index=True)
             if len(iso_audit) or len(kin_audit) else pd.DataFrame())

    state = dict(data=data, qc=qc, eq=eq, ipd=ipd,
                 iso_fits=iso_fits, iso_best=iso_best, curves_iso=curves_iso,
                 kin_fits=kin_fits, kin_best=kin_best, curves_kin=curves_kin,
                 edge_params=edge_params, curves_edge=curves_edge, edge_cmp=edge_cmp,
                 warns=warns, audit=audit, solid=solid, issues=issues, dr_ctx=dr_ctx)
    with cache.open("wb") as fh:
        pickle.dump(state, fh)
    return _finish(out, make_figs, verbose, state)


def _finish(out: Path, make_figs: bool, verbose: bool, st: dict) -> dict:
    """出图 + 导出报告（计算与拟合已完成）。"""
    data, qc, eq, ipd = st["data"], st["qc"], st["eq"], st["ipd"]
    iso_fits, iso_best, curves_iso = st["iso_fits"], st["iso_best"], st["curves_iso"]
    kin_fits, kin_best, curves_kin = st["kin_fits"], st["kin_best"], st["curves_kin"]
    edge_params, curves_edge, edge_cmp = st["edge_params"], st["curves_edge"], st["edge_cmp"]
    warns, audit, solid = st["warns"], st["audit"], st["solid"]
    issues = st.get("issues")
    dr_ctx = st.get("dr_ctx")

    def log(msg: str):
        if verbose:
            print(msg, flush=True)

    figs = {}
    if make_figs:
        log("[4/5] 绘图")
        fig_dir = out / "figures"
        fig_dir.mkdir(parents=True, exist_ok=True)
        # 先清掉上一次的图再画：换了数据集后旧图（例如新数据没有 QC 却还留着
        # qc.png）会让人误以为属于本次结果；而 path.exists() 分不清新旧。
        for p in fig_dir.glob("*"):
            if p.suffix in (".png", ".pdf"):
                p.unlink()
        for name, fn in [
            ("isotherm", lambda p: viz.plot_isotherms(curves_iso, p)),
            ("kinetics", lambda p: viz.plot_kinetics(curves_kin, p)),
            ("ipd", lambda p: viz.plot_ipd(curves_kin, p)),
            ("edge", lambda p: viz.plot_edges(curves_edge, p)),
            ("qc", lambda p: viz.plot_qc(qc, p)),
            ("residuals", lambda p: viz.plot_residuals(curves_iso, curves_kin, p)),
        ]:
            path = fig_dir / f"{name}.png"
            fn(path)
            if path.exists():
                figs[name] = path
    else:
        log("[4/5] 跳过绘图")

    log("[5/5] 导出报告")
    tables = [("长表数据", data), ("等温线_最优", iso_best), ("等温线_全部模型", iso_fits),
              ("动力学_最优", kin_best), ("动力学_全部模型", kin_fits),
              ("颗粒内扩散", ipd), ("平衡时间", eq), ("吸附边参数", edge_params),
              ("离子强度对比", edge_cmp), ("QC", qc), ("模型可靠性", audit),
              ("数据质量清单", issues)]
    for name, frame in tables:
        if frame is not None and not frame.empty:
            frame.to_csv(out / "tables" / f"{name}.csv", index=False, encoding="utf-8-sig")

    # MATLAB 全模型复核脚本：把本次用到的每一组数据、每一个模型都写进去，
    # 让用户可以在 MATLAB 里独立重拟合、逐模型比对 SSE。
    try:
        from .matlab import write_verify_script
        src = ", ".join(sorted({str(f) for f in data.get("file", []) if isinstance(f, str)})) \
            if "file" in data else ""
        mfile = write_verify_script(out / "matlab_verify.m", curves_iso, curves_kin,
                                    source=src)
    except Exception as exc:  # 复核脚本失败不应影响主流程
        mfile = None
        warns.append(f"MATLAB 复核脚本生成失败：{exc}")
    html = report.write_html(out, data, qc, iso_best, iso_fits, kin_best, kin_fits,
                             ipd, edge_params, edge_cmp, curves_iso, curves_kin,
                             solid, audit=audit, issues=issues, warns=warns,
                             dr_ctx=dr_ctx)
    xlsx = report.write_excel(out, data, qc, iso_fits, iso_best, kin_fits, kin_best,
                              ipd, eq, edge_params, edge_cmp, audit=audit)

    if verbose:
        _print_summary(iso_best, kin_best, edge_params, warns)
        print(f"\n报告：{html}")
        print(f"汇总表：{xlsx}")
        print(f"图件：{out / 'figures'}")

    return {"html": html, "xlsx": xlsx, "figures": figs, "warnings": warns,
            "iso_best": iso_best, "kin_best": kin_best, "edge_params": edge_params,
            "audit": audit, "data": data, "solid": solid, "issues": issues}


def _print_summary(iso_best, kin_best, edge_params, warns):
    print("\n===== 结果摘要 =====")
    if not iso_best.empty:
        print("\n等温线最优模型：")
        for _, r in iso_best.iterrows():
            pars = ", ".join(f"{k[5:]}={v:.4g}" for k, v in r.items()
                             if k.startswith("best_") and isinstance(v, (int, float))
                             and np.isfinite(v))
            print(f"  {r['mineral']}-{r['background']}: {r['best_label']}  "
                  f"R2={r['R2']:.4f}  AICc={r['AICc']:.2f}  [{pars}]")
    if not kin_best.empty:
        print("\n动力学最优模型：")
        for _, r in kin_best.iterrows():
            pars = ", ".join(f"{k[5:]}={v:.4g}" for k, v in r.items()
                             if k.startswith("best_") and isinstance(v, (int, float))
                             and np.isfinite(v))
            print(f"  {r['mineral']}-{r['background']}: {r['best_label']}  "
                  f"R2={r['R2']:.4f}  [{pars}]")
    if not edge_params.empty:
        print("\n吸附边：")
        for _, r in edge_params.iterrows():
            # 拟合不成立时 pH50 / 斜率是 NaN（报告里留空），控制台也不该印 "nan"
            ph50 = r.get("pH50", np.nan)
            sl = r.get("slope_at_pH50", np.nan)
            r2 = r.get("R2_logistic", np.nan)
            print(f"  {r['mineral']}-{r['background']}: "
                  f"pH50={'—' if not np.isfinite(ph50) else f'{ph50:.2f}'}  "
                  f"斜率={'—' if not np.isfinite(sl) else f'{sl:.3f}'}  "
                  f"R2={'—' if not np.isfinite(r2) else f'{r2:.3f}'}")
    if warns:
        print(f"\n数据质量提示 {len(warns)} 条：")
        for w in warns:
            print("  -", w)
