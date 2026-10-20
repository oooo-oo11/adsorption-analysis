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

from . import analyze, names as N, report, viz
from .io import read_all
from .template import read_template

BASE = Path(__file__).resolve().parent.parent

CACHE_KEYS = ["data", "qc", "eq", "ipd", "iso_fits", "iso_best", "curves_iso",
              "kin_fits", "kin_best", "curves_kin", "edge_params", "curves_edge",
              "edge_cmp", "warns", "audit", "solid", "issues", "meta"]


def load_config(path: Path) -> dict:
    cfg = {"solid_g_per_L": None, "data_dir": ".", "output_dir": "output", "defaults": {}}
    if path.exists():
        cfg.update(json.loads(path.read_text(encoding="utf-8")))
    return cfg


def resolve_solid(cfg: dict, override: float | None) -> float | dict | None:
    solid = cfg.get("solids_g_per_L") or cfg.get("solid_g_per_L")
    if override is not None:
        solid = override
    if isinstance(solid, dict) and not any(
            isinstance(v, (int, float)) and np.isfinite(v) and v > 0 for v in solid.values()):
        solid = None
    return solid


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
        return _finish(out, make_figs, verbose, **{k: st.get(k) for k in CACHE_KEYS})

    if template:
        log(f"[1/5] 读取模板：{template}")
        data, cfg_t, io_warn = read_template(Path(template), defaults=cfg.get("defaults"))
        # 报告标题等用语从模板 Settings 取（project / analyte），不写死体系
        _st = cfg_t.get("settings") or {}
        doc_meta = {k: _st.get(k) for k in ("project", "analyte")}
        # 模板 Settings 的 solid:<矿物> 是本次数据集的固液比，优先于 config.json
        # 的默认值（CLI --solid 标量最高，不被覆盖）。键允许写中文矿物名，
        # 统一经 names 映射到英文显示名后再合并，避免两处写法不一致时静默丢值。
        tmpl_solids = {}
        for k, v in (cfg_t.get("solids_g_per_L") or {}).items():
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            if np.isfinite(fv) and fv > 0:
                tmpl_solids[N.mineral(str(k))] = fv
        if tmpl_solids:
            if solid is None:
                solid = tmpl_solids
            elif isinstance(solid, dict):
                solid = {**solid, **tmpl_solids}
        if cfg_t.get("solids_g_per_L") and solid is None:
            solid = cfg_t["solids_g_per_L"]
        if solid is None and "solid_g_per_L" in data:
            per_row = {}
            for m, v in zip(data["mineral"], data["solid_g_per_L"]):
                if pd.notna(v):
                    per_row.setdefault(m, float(v))
            solid = per_row or None
        qc = pd.DataFrame(columns=["exp", "qc", "nominal_ppb", "conc_ppb", "recovery_pct"])
    else:
        data_dir = Path(data_dir or cfg.get("data_dir") or BASE).resolve()
        log(f"[1/5] 读取数据：{data_dir}")
        data, qc, meta, io_warn = read_all(data_dir, cfg)
        doc_meta = {k: (meta or {}).get(k) if isinstance(meta, dict) else None
                    for k in ("project", "analyte")}

    if data.empty:
        raise SystemExit("未解析到数据：请检查模板的 Data 表，或文件名是否包含 等温/动力学/吸附边。")
    log(f"      {len(data)} 行有效数据；QC {len(qc)} 条")

    log("[2/5] 计算 Ce / qe / 吸附分数")
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
    issues = analyze.quality_issues(data, iso, kin, edge, qc)

    iso_audit = analyze.model_audit(iso_fits, "isotherm")
    kin_audit = analyze.model_audit(kin_fits, "kinetics")
    audit = (pd.concat([iso_audit, kin_audit], ignore_index=True)
             if len(iso_audit) or len(kin_audit) else pd.DataFrame())

    state = dict(data=data, qc=qc, eq=eq, ipd=ipd,
                 iso_fits=iso_fits, iso_best=iso_best, curves_iso=curves_iso,
                 kin_fits=kin_fits, kin_best=kin_best, curves_kin=curves_kin,
                 edge_params=edge_params, curves_edge=curves_edge, edge_cmp=edge_cmp,
                 warns=warns, audit=audit, solid=solid, issues=issues, meta=doc_meta)
    with cache.open("wb") as fh:
        pickle.dump(state, fh)
    return _finish(out, make_figs, verbose, **state)


def _finish(out: Path, make_figs: bool, verbose: bool, *,
            data, qc, eq, ipd, iso_fits, iso_best, curves_iso,
            kin_fits, kin_best, curves_kin, edge_params, curves_edge,
            edge_cmp, warns, audit, solid, issues=None, meta=None) -> dict:
    """出图 + 导出报告（计算与拟合已完成）。"""
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

    solid_note = "" if solid else "若已知固液比，建议在 config.json 或模板 Settings 中填入后重跑。"
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
                             ipd, eq, edge_params, edge_cmp, curves_iso, curves_kin,
                             warns, solid, solid_note, audit=audit, issues=issues,
                             meta=meta)
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
            print(f"  {r['mineral']}-{r['background']}: pH50={r['pH50']:.2f}  "
                  f"斜率={r['slope_at_pH50']:.3f}  R2={r['R2_logistic']:.3f}")
    if warns:
        print(f"\n数据质量提示 {len(warns)} 条：")
        for w in warns:
            print("  -", w)
