"""命令行入口。

    python -m adsorp.cli run                       # 读当前目录的仪器原始表
    python -m adsorp.cli run --template 数据.xlsx   # 读填写好的模板
    python -m adsorp.cli run --solid 3             # 覆盖固液比
    python -m adsorp.cli template                  # 生成空白模板
    python -m adsorp.cli check --template 数据.xlsx # 只校验数据，不出图
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from .pipeline import BASE, load_config, resolve_solid, run
from .io import read_all
from .template import read_template, write_from_data, write_template


def _load_source(a):
    """按 ``--template`` / ``--data-dir`` 读取长表，返回 ``(data, 固液比)``。"""
    if a.template:
        data, cfg_t, _ = read_template(a.template)
        return data, cfg_t.get("solids_g_per_L")
    cfgf = load_config(Path(a.config))
    data, _, _, _ = read_all(Path(a.data_dir or cfgf.get("data_dir") or "."), cfgf)
    return data, resolve_solid(cfgf, None)


def _cmd_run(a) -> int:
    run(data_dir=a.data_dir, template=a.template, out=a.out, solid=a.solid,
        config=a.config, names_file=a.names, make_figs=not a.no_figs,
        reuse=a.reuse)
    return 0


def _cmd_template(a) -> int:
    p = write_template(a.path)
    print(f"已生成模板：{p}")
    print("填写 Data 表后在 Settings 的 solids 区填各矿物固液比，然后运行：")
    print(f"  adsorp.bat run --template \"{p.name}\" --out output")
    return 0


def _cmd_export(a) -> int:
    """把已解析的数据导出成填好的模板（样例 / 迁移用）。"""
    from . import names as N

    N.load(BASE / "names.json")
    data, solids = _load_source(a)
    # 导出的模板与手填模板保持一致：mineral 列一律写英文显示名
    data = data.copy()
    data["mineral"] = data["mineral"].map(N.mineral)
    if isinstance(solids, dict):
        solids = {N.mineral(k): v for k, v in solids.items()}
    p = write_from_data(data, a.out, solids if isinstance(solids, dict) else None)
    print(f"已导出：{p}（{len(data)} 行）")
    return 0


def _cmd_matlab(a) -> int:
    """导出 MATLAB 脚本：默认给 Ce/qe 数组；--verify 给全模型复核脚本。"""
    if getattr(a, "verify", False):
        import pickle

        from .matlab import write_verify_script

        cache = Path(a.cache) if Path(a.cache).is_absolute() else BASE / a.cache
        if not cache.exists():
            print(f"找不到拟合缓存：{cache}\n请先跑一次 adsorp.bat run --template 数据.xlsx")
            return 1
        st = pickle.loads(cache.read_bytes())
        data = st.get("data")
        src = ""
        if data is not None and "file" in data:
            src = "、".join(sorted({str(f) for f in data["file"] if isinstance(f, str)}))
        p = write_verify_script(Path(a.out or "output/matlab_verify.m"),
                                st.get("curves_iso", {}), st.get("curves_kin", {}),
                                source=src)
        if p is None:
            print("缓存里没有等温线/动力学曲线，未生成脚本。")
            return 1
        print(f"已写入 {p}")
        return 0

    data, solid = _load_source(a)

    from . import analyze
    iso = analyze.isotherm_data(data, solid)
    if "exclude" in iso:
        iso = iso[~iso["exclude"].astype(bool)]
    if iso.empty:
        print("没有等温线数据。")
        return 1

    agg = (iso.groupby(["mineral", "background", "C0_ppm"], as_index=False)
              .agg(Ce=("Ce_ppm", "mean"), qe=("qe", "mean"))
              .sort_values(["mineral", "background", "C0_ppm"]))

    lines = ["%% 等温线数据（由 adsorp 导出）", ""]
    for (mineral, bg), g in agg.groupby(["mineral", "background"], sort=False):
        ce = "; ".join(f"{v:.4f}" for v in g["Ce"])
        qe = "; ".join(f"{v:.4f}" for v in g["qe"])
        lines += [f"%% {mineral} | {bg}   n={len(g)}",
                  f"Ce = [{ce}];",
                  f"qe = [{qe}];", ""]
    p = Path(a.out or "output/matlab_isotherm.m")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lines), encoding="utf-8")
    print(f"已写入 {p}（{len(agg)} 个浓度点，{agg.groupby(['mineral','background']).ngroups} 组）")
    return 0


def _cmd_check(a) -> int:
    cfg = load_config(Path(a.config) if Path(a.config).is_absolute() else BASE / a.config)
    data, cfg_t, warns = read_template(a.template, defaults=cfg.get("defaults"))
    print(f"行数：{len(data)}")
    if not data.empty:
        g = (data.assign(_valid=data["Ce_ppm"].notna() & ~data["exclude"].astype(bool))
             .groupby(["exp", "mineral", "background"])
             .agg(rows=("_valid", "size"), valid=("_valid", "sum"))
             .reset_index())
        print(g.to_string(index=False))
        solids = cfg_t.get("solids_g_per_L") or cfg.get("solids_g_per_L") or {}
        print(f"\n固液比：{solids if solids else '未提供（容量以 mg/L 悬浮液计）'}")

        # 平行样：同组同条件出现多行 → 按均值 ± SD 合并（正常测定，不是错误）
        reps = []
        for exp, col, label in (("isotherm", "C0_ppm", "C0"),
                                ("kinetics", "time_h", "t"),
                                ("edge", "pH", "pH")):
            sub = data[(data["exp"] == exp) & data[col].notna()
                       & data["Ce_ppm"].notna() & ~data["exclude"].astype(bool)]
            if sub.empty:
                continue
            dup = sub[sub.duplicated(["mineral", "background", col], keep=False)]
            for (m, bg, key), gg in dup.groupby(["mineral", "background", col]):
                reps.append(f"{m}-{bg}  {label}={key:g}  n={len(gg)}")
        if reps:
            print("\n平行样（按均值 ± SD 合并，图上为误差棒）：")
            for r in reps:
                print("  -", r)

        # 空值＝你主动删掉或没做的点，处理口径就是"去掉之后"的数据
        skip = data[data["Ce_ppm"].isna() & data["exp"].isin(("isotherm", "kinetics", "edge"))]
        if not skip.empty:
            locs = "、".join(f"第 {int(r['row'])} 行" for _, r in skip.iterrows())
            print(f"\n未测点（已跳过，不参与拟合与绘图）：{len(skip)} 行 —— {locs}")
        # 缺关键列的行会被静默跳过，必须点名，否则等于丢数据
        for exp, col in (("kinetics", "time_h"), ("edge", "pH")):
            bad = data[(data["exp"] == exp) & data[col].isna() & data["Ce_ppm"].notna()]
            for _, r in bad.iterrows():
                print(f"  警告：{exp} 第 {int(r['row'])} 行（{r['mineral']}-{r['background']}）"
                      f"缺 {col}，该点会被跳过")
    if warns:
        print("\n提示：")
        for w in warns:
            if w.startswith(("动力学有", "吸附边有")):
                continue          # 上面已逐行点名，不必再报总数
            print("  -", w)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="adsorp", description="吸附数据分析流水线")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("run", help="跑完整分析并生成报告")
    p.add_argument("--template", default=None, help="填写好的 Excel 模板")
    p.add_argument("--data-dir", default=None, help="仪器原始工作簿所在目录")
    p.add_argument("--out", default="output", help="输出目录")
    p.add_argument("--solid", type=float, default=None, help="覆盖固液比 (g/L)")
    p.add_argument("--config", default="config.json")
    p.add_argument("--names", default="names.json", help="矿物中英文映射")
    p.add_argument("--no-figs", action="store_true", help="只出表，不重绘图")
    p.add_argument("--reuse", action="store_true",
                   help="复用 output/_analysis.pkl，只重绘图与报告")
    p.set_defaults(func=_cmd_run)

    p = sub.add_parser("template", help="生成空白 Excel 模板")
    p.add_argument("path", nargs="?", default="吸附数据模板.xlsx")
    p.set_defaults(func=_cmd_template)

    p = sub.add_parser("matlab", help="导出 MATLAB 脚本（数组 或 全模型复核）")
    p.add_argument("--template", default=None)
    p.add_argument("--data-dir", default=None)
    p.add_argument("--config", default="config.json")
    p.add_argument("--out", default=None,
                   help="输出文件（默认 output/matlab_isotherm.m；--verify 时 output/matlab_verify.m）")
    p.add_argument("--verify", action="store_true",
                   help="生成全模型复核脚本（读 output/_analysis.pkl，需先跑一次 run）")
    p.add_argument("--cache", default="output/_analysis.pkl")
    p.set_defaults(func=_cmd_matlab)

    p = sub.add_parser("check", help="校验模板内容，不拟合")
    p.add_argument("--template", required=True)
    p.add_argument("--config", default="config.json")
    p.set_defaults(func=_cmd_check)

    p = sub.add_parser("export", help="把已解析数据导出为填好的模板")
    p.add_argument("--template", default=None, help="从已填模板导出（省略则读原始工作簿）")
    p.add_argument("--data-dir", default=None)
    p.add_argument("--config", default="config.json")
    p.add_argument("--out", default="吸附数据_示例.xlsx")
    p.set_defaults(func=_cmd_export)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
