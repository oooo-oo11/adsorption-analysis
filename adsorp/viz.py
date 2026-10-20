"""按 fig2-261008.m 风格生成吸附实验图（全英文，可直接用于英文稿件）。

版式约定：17.2 cm 版心、2 列紧凑网格、Times New Roman、四边细黑框、
刻度朝内、无网格、实心彩标 + 深灰描边、拟合曲线紫虚线 / 黑实线。
所有文字均为英文；矿物名经 :mod:`adsorp.names` 映射（见项目根 names.json）。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from matplotlib.lines import Line2D

from . import names as N
from . import style as S
from .models import ISOTHERM_MODELS, KINETIC_MODELS

S.apply()


def _params(res):
    model = ISOTHERM_MODELS.get(res.key) or KINETIC_MODELS.get(res.key)
    return np.array([res.params[n] for n in model.names])


def _unit(u: str | None, fallback: str = "mg/L") -> str:
    if not u:
        return fallback
    return "mg/g" if u.startswith("mg/g") else "mg/L"


def _common_unit(curves: dict, fallback: str = "mg/L") -> str:
    """一组曲线的统一容量单位；混合单位时退回 fallback。"""
    units = {c.get("unit") for c in curves.values() if c.get("unit")}
    return _unit(units.pop()) if len(units) == 1 else fallback


def _usable(res) -> bool:
    """最优模型的参数是否可解释（未触界、无完全共线）。"""
    corr = getattr(res, "max_corr", np.nan)   # 字段名是 max_corr（FitResult）
    bad = bool(getattr(res, "at_bound", False))
    if np.isfinite(corr) and corr > 0.99:
        bad = True
    return not bad


def _grid(n_panels: int, panel_h_cm: float):
    """按组数决定栏数：单组时用半版宽，避免右半边留白。"""
    ncols = 1 if n_panels <= 1 else 2
    width = 8.6 if ncols == 1 else 17.2
    return S.new_grid(n_panels, ncols, width_cm=width, panel_h_cm=panel_h_cm)


def _draw_keys(c: dict, refs: tuple[str, ...], allow_best: bool = True) -> list[str]:
    best = c["best"].key
    have = {r.key for r in c.get("all", c["top"])}
    keys = ([best] if allow_best else []) + [k for k in refs if k != best]
    return [k for k in keys if k in have or k == best]


def _find(c: dict, key: str):
    return next(r for r in c.get("all", c["top"]) if r.key == key)


def _letters(n: int) -> list[str]:
    return [chr(ord("a") + i) for i in range(n)]


def _err(series):
    """误差棒：只有真正做过平行样（SD>0）的点才画。

    单次测定没有 SD（NaN），过去被 nan_to_num 补成 0，matplotlib 仍会在点上
    画出两段零长度的 cap，看起来像误差棒。这里把 0/NaN 一律置 NaN，
    整组都没有平行样时直接返回 None，连 errorbar 都不调用。
    """
    if series is None:
        return None
    arr = np.asarray(series, float)
    arr = np.where(np.isfinite(arr) & (arr > 0), arr, np.nan)
    return arr if np.isfinite(arr).any() else None


def _headroom(data_top: float, curve_top: float,
              pad: float = 1.18, curve_cap: float = 1.50) -> float:
    """y 轴上限：至少给数据 18% 留白，并尽量把拟合曲线收进框内。"""
    if not np.isfinite(data_top) or data_top <= 0:
        return 1.0
    top = data_top * pad
    if np.isfinite(curve_top) and curve_top > 0:
        top = max(top, min(curve_top * 1.03, data_top * curve_cap))
    return float(top)


def _panel(ax, letter: str, mineral: str, bg: str):
    S.panel_label(ax, letter, N.mineral(mineral), N.background(bg))


# --------------------------------------------------------------------------
# 等温线
# --------------------------------------------------------------------------

def plot_isotherms(curves: dict, out: Path, qe_unit: str | None = None):
    """等温线：默认线性 Ce 轴（wang2026 版式），并另存一份对数轴版本。

    两个版本都写入 output/figures/（``isotherm.*`` 与 ``isotherm_log.*``），
    HTML 报告里提供横坐标切换；原始数据点和对数轴实现见 viz_原版备份.py。
    """
    _isotherms(curves, out, qe_unit, xscale="linear")
    _isotherms(curves, out.with_name(out.stem + "_log" + out.suffix),
               qe_unit, xscale="log")


def _isotherms(curves: dict, out: Path, qe_unit: str | None, *, xscale: str):
    if not curves:
        return
    items = list(curves.items())
    unit = _unit(qe_unit, _common_unit(curves))
    fig, axes = _grid(len(items), 6.9)
    for ax, letter, ((mineral, bg), c) in zip(axes.ravel(), _letters(len(items)), items):
        d, best = c["data"], c["best"]
        x = np.asarray(d["Ce_ppm"], float)
        y = np.asarray(d["qe"], float)

        if xscale == "log":
            xlo, xhi = float(np.nanmin(x)) * 0.55, float(np.nanmax(x)) * 1.45
            grid = np.logspace(np.log10(xlo), np.log10(xhi), 360)
        else:
            xlo, xhi = 0.0, _nice_ceil(float(np.nanmax(x)) * 1.05)
            grid = np.linspace(0.0, xhi, 400)

        ok = _usable(best)
        cmax = 0.0
        for key in _draw_keys(c, ("langmuir", "freundlich"), allow_best=ok):
            res = _find(c, key)
            yy = np.asarray(ISOTHERM_MODELS[key].func(grid, _params(res)), float)
            fin = yy[np.isfinite(yy)]
            if fin.size:
                cmax = max(cmax, float(fin.max()))
            S.model_line(ax, grid, yy, key)

        S.data_marker(ax, x, y, mineral, bg, yerr=_err(d.get("qe_sd")))
        top = _headroom(float(np.nanmax(y)), cmax)
        S.axis(ax, "C$_e$ (mg/L)", f"Q$_e$ ({unit})", xscale=xscale,
               ylim=S.ylim_data(float(np.nanmin(y)), top))
        if xscale == "log":
            ax.set_xlim(xlo, xhi)
        else:
            ax.set_xlim(*S.xlim0(0.0, xhi))
        _panel(ax, letter, mineral, bg)
        # 最优模型参数触界时不再往图上写红字，只画可解释的参照线；
        # 该组的具体情况写进报告正文的模型可靠性表。
        S.legend(ax)
    S.save(fig, out)


# --------------------------------------------------------------------------
# 动力学
# --------------------------------------------------------------------------

def _nice_ceil(v: float) -> float:
    """把时间轴上限取整到好看的刻度（约 5–6 个主刻度，如 300 → 0/50/…/300）。"""
    v = max(float(v), 1.0)
    for step in (5, 10, 20, 25, 50, 100, 200, 500):
        if v <= step * 6:
            return float(np.ceil(v / step) * step)
    return float(np.ceil(v / 1000.0) * 1000.0)


def plot_kinetics(curves: dict, out: Path, qt_unit: str | None = None):
    """动力学：默认线性时间轴（wang2026 版式），并另存一份对数轴版本。"""
    _kinetics(curves, out, qt_unit, xscale="linear")
    _kinetics(curves, out.with_name(out.stem + "_log" + out.suffix),
              qt_unit, xscale="log")


def _kinetics(curves: dict, out: Path, qt_unit: str | None, *, xscale: str):
    if not curves:
        return
    items = list(curves.items())
    unit = _unit(qt_unit, _common_unit(curves))
    fig, axes = _grid(len(items), 6.9)
    for ax, letter, ((mineral, bg), c) in zip(axes.ravel(), _letters(len(items)), items):
        d, best = c["data"], c["best"]
        x = np.asarray(d["time_h"], float)
        y = np.asarray(d["qt"], float)

        if xscale == "log":
            xlo, xhi = float(np.nanmin(x)) * 0.45, float(np.nanmax(x)) * 2.2
            grid = np.logspace(np.log10(xlo), np.log10(xhi), 360)
        else:
            # 横轴：线性时间（0 → 取整上限），对齐参考版式
            xlo, xhi = 0.0, _nice_ceil(float(np.nanmax(x)) * 1.03)
            grid = np.linspace(0.0, xhi, 400)

        cmax = 0.0
        for key in _draw_keys(c, ("pfo", "pso")):
            res = _find(c, key)
            yy = np.asarray(KINETIC_MODELS[key].func(grid, _params(res)), float)
            fin = yy[np.isfinite(yy)]
            if fin.size:
                cmax = max(cmax, float(fin.max()))
            S.model_line(ax, grid, yy, key)

        S.data_marker(ax, x, y, mineral, bg, yerr=_err(d.get("qt_sd")))
        top = _headroom(float(np.nanmax(y)), cmax)
        S.axis(ax, "Time (h)", f"Q$_t$ ({unit})", xscale=xscale,
               ylim=S.ylim_data(float(np.nanmin(y)), top))
        if xscale == "log":
            ax.set_xlim(xlo, xhi)
        else:
            ax.set_xlim(*S.xlim0(0.0, xhi))
        _panel(ax, letter, mineral, bg)
        # R² 太低时图例不加 (best) 标记，说明写在图注里，图上不再叠红字。
        S.legend(ax)
    S.save(fig, out)


# --------------------------------------------------------------------------
# 颗粒内扩散
# --------------------------------------------------------------------------

def plot_ipd(curves: dict, out: Path, qt_unit: str | None = None):
    if not curves:
        return
    items = list(curves.items())
    unit = _unit(qt_unit, _common_unit(curves))
    fig, axes = _grid(len(items), 6.6)
    for ax, letter, ((mineral, bg), c) in zip(axes.ravel(), _letters(len(items)), items):
        d = c["data"]
        s = np.sqrt(np.asarray(d["time_h"], float))
        y = np.asarray(d["qt"], float)

        ipd = c.get("ipd")
        handles = []
        if ipd:
            t = np.asarray(d["time_h"], float)
            k = max(2, int(np.searchsorted(t, ipd["break_t_h"])))
            h1, = ax.plot(s[:k], ipd["k_id1"] * s[:k] + ipd["C1"],
                          color=S.INK, ls="-", lw=S.FIT_LW, label="Stage I", zorder=3)
            h2, = ax.plot(s[k - 1:], ipd["k_id2"] * s[k - 1:] + ipd["C2"],
                          color=S.PURPLE, ls="--", lw=S.FIT_LW, label="Stage II", zorder=3)
            ax.axvline(np.sqrt(ipd["break_t_h"]), color=S.GRAY, ls=":", lw=0.9, zorder=1)
            handles = [h1, h2]

        S.data_marker(ax, s, y, mineral, bg)
        top = _headroom(float(np.nanmax(y)), 0.0)
        S.axis(ax, r"$t^{1/2}$ (h$^{1/2}$)", f"Q$_t$ ({unit})",
               ylim=S.ylim_data(float(np.nanmin(y)), top))
        ax.set_xlim(*S.xlim0(0.0, float(np.nanmax(s)) * 1.05))
        _panel(ax, letter, mineral, bg)
        # Stage II 斜率为负时不再在图内写红字，判据见报告正文。
        if handles:
            S.legend(ax, handles=handles)
    S.save(fig, out)


# --------------------------------------------------------------------------
# 吸附边
# --------------------------------------------------------------------------

def plot_edges(curves: dict, out: Path):
    if not curves:
        return
    minerals = []
    for mineral, _ in curves:
        if mineral not in minerals:
            minerals.append(mineral)

    from .analyze import _logistic

    fig, axes = S.new_grid(len(minerals), len(minerals),
                           width_cm=8.6 if len(minerals) == 1
                           else max(17.2, 5.7 * len(minerals)),
                           height_cm=8.2, bottom=0.225)
    axes = axes.ravel()

    handles, seen = [], {}
    for ax, letter, mineral in zip(axes, _letters(len(minerals)), minerals):
        # 该矿物所有离子强度里最低的吸附率：出现负值时把纵轴拉下去，
        # 不把点裁到框外（是否剔除由使用者在模板 exclude 列决定）。
        ys = [float(np.nanmin(c["data"]["theta"])) * 100
              for (m, _), c in curves.items() if m == mineral]
        ymin = min([0.0] + [v for v in ys if np.isfinite(v)])
        yticks = [0, 20, 40, 60, 80, 100]
        if ymin < -5:
            lo_t = int(np.floor(ymin / 20.0) * 20)
            yticks = list(range(lo_t, 101, 20))
        for (m, bg), c in curves.items():
            if m != mineral:
                continue
            d = c["data"]
            color = S.BG_COLOR.get(bg, S.INK)
            marker = S.BG_MARKER.get(bg, "o")
            yerr = _err(d.get("theta_sd"))
            if yerr is not None:
                ax.errorbar(d["pH"], d["theta"] * 100, yerr=yerr * 100,
                            fmt="none", ecolor=S.GRAY, elinewidth=S.ERR_LW,
                            capsize=4.0, capthick=S.ERR_LW, zorder=4)
            ax.plot(d["pH"], d["theta"] * 100, linestyle="none", marker=marker,
                    markersize=S.MARKER_SIZE, markerfacecolor=color,
                    markeredgecolor=S.EDGE, markeredgewidth=0.8, zorder=5)
            if c.get("reliable") and c.get("popt") is not None:
                grid = np.linspace(d["pH"].min(), d["pH"].max(), 260)
                ax.plot(grid, _logistic(grid, *c["popt"]) * 100,
                        color=color, lw=S.FIT_LW, zorder=3)
            if bg not in seen:
                seen[bg] = Line2D([], [], color=color, marker=marker, linestyle="-",
                                  markersize=5.6, markerfacecolor=color,
                                  markeredgecolor=S.EDGE,
                                  label=N.background(bg))
                handles.append((bg, seen[bg]))

        S.axis(ax, "pH", "Adsorption (%)", ylim=S.ylim_data(ymin, 112),
               yticks=yticks)
        ax.set_xlim(3.5, 10.5)
        S.panel_label(ax, letter, N.mineral(mineral))
        # logistic 未达 R²≥0.6 的组只画散点、不画曲线，pH50 报告里留空；
        # 图面不再加红字说明。

    fig.legend(handles=[h for _, h in handles], loc="lower center",
               ncol=len(handles), frameon=False, fontsize=S.FONT_LEGEND,
               handlelength=2.0, columnspacing=2.2, handletextpad=0.5,
               bbox_to_anchor=(0.5, 0.005))
    S.save(fig, out)


# --------------------------------------------------------------------------
# QC
# --------------------------------------------------------------------------

def plot_qc(qc, out: Path):
    if qc is None or qc.empty or "recovery_pct" not in qc:
        return
    q = qc.dropna(subset=["recovery_pct"]).reset_index(drop=True)
    if q.empty:
        return
    colors = {"isotherm": S.SKY, "kinetics": S.MAUVE, "edge": S.SAGE}
    markers = {"isotherm": "o", "kinetics": "s", "edge": "^"}

    fig, axes = S.new_grid(1, 1, width_cm=9.6, height_cm=7.4)
    ax = axes.ravel()[0]
    for exp, g in q.groupby("exp"):
        idx = g.index.to_numpy()
        ax.plot(idx, g["recovery_pct"], linestyle="none",
                marker=markers.get(exp, "o"), markersize=5.2,
                markerfacecolor=colors.get(exp, S.INK), markeredgecolor=S.EDGE,
                markeredgewidth=0.8, label=N.experiment(exp), zorder=5)
    for y in (80, 100, 120):
        ax.axhline(y, color=S.INK if y == 100 else S.GRAY,
                   lw=0.8, ls="-" if y == 100 else "--", zorder=2)
    S.axis(ax, "QC sample no.", "Recovery (%)", ylim=(55, 132),
           yticks=[60, 80, 100, 120])
    ax.set_xlim(-1, len(q))
    S.legend(ax, "lower left")
    S.save(fig, out)


# --------------------------------------------------------------------------
# 残差
# --------------------------------------------------------------------------

def plot_residuals(curves_iso: dict, curves_kin: dict, out: Path, qe_unit: str | None = None):
    fig, axes = S.new_grid(2, 2, width_cm=17.2, height_cm=8.2, bottom=0.245)
    panels = [(axes.ravel()[0], "a", curves_iso, "Isotherm", True),
              (axes.ravel()[1], "b", curves_kin, "Kinetics", False)]
    shown = {}   # 按数据里出现的顺序记矿物，图例顺序才稳定
    for ax, letter, curves, title, logx in panels:
        if not curves:
            ax.axis("off")
            continue
        # 只统计参数可解释的最优模型：Sips 触界那类拟合的残差是数学假象
        used = {k: c for k, c in curves.items() if _usable(c["best"])}
        if not used:
            used = dict(curves)

        # 所有实测点都画，不再按负载高低截断。低负载点的相对残差会因为分母
        # 接近检出限而放大到百分之几百，这是数学事实，保留原样、交给读者判断；
        # 纵轴按 98% 分位自适应，极端点可能落在框外（原始值见 tables/）。
        rel_all, xs = [], []
        for (m, bg), c in used.items():
            b = c["best"]
            yhat = np.asarray(b.yhat, float)
            resid = np.asarray(b.resid, float)
            obs = yhat + resid
            rel = resid / np.where(np.abs(obs) > 1e-12, obs, np.nan) * 100
            keep = np.isfinite(rel) & np.isfinite(obs)
            if logx:
                keep &= obs > 0      # 对数轴显示不了 ≤ 0 的实测值
            rel_all.append(rel[keep])
            xs.append(obs[keep])
            ax.plot(obs[keep], rel[keep], linestyle="none",
                    marker=S.BG_MARKER.get(bg, "o"), markersize=4.6,
                    markerfacecolor=S.mineral_color(m),
                    markeredgecolor=S.EDGE, markeredgewidth=0.6, zorder=5)
        ax.axhline(0, color=S.INK, lw=0.9, zorder=2)
        for yv in (-10, 10):
            ax.axhline(yv, color=S.GRAY, lw=0.8, ls="--", zorder=1)

        lim = 30.0
        if rel_all:
            a = np.abs(np.concatenate(rel_all))
            a = a[np.isfinite(a)]
            if a.size:
                # 用中位数 + 3×MAD 而不是最大值：低负载点的相对残差会被检出限
                # 放大到百分之几百，按最大值定轴会把其余点全压成一条线。
                # 极端点落在框外，数值仍在 tables/长表数据.csv 里，图注有说明。
                med = float(np.median(a))
                mad = float(np.median(np.abs(a - med))) * 1.4826
                # 先按稳健范围定轴，但至少把最大的点收进框内（上限 120%）：
                # tod 这种最大残差 35% 的数据不该在图顶切掉一个点；真遇到
                # 200%+ 的病态点，才让它落在框外并在图注里说明。
                lim = float(np.clip(max(med + 3.0 * mad, min(float(a.max()) * 1.06, 120.0)),
                                    12.0, 120.0))
        S.axis(ax, "Measured value", "Relative residual (%)",
               xscale="log" if logx else "linear",
               ylim=(-lim, lim))
        S.panel_label(ax, letter, title, y=0.985)
        if logx and xs:
            flat = np.concatenate([x for x in xs if x.size])
            ax.set_xlim(float(np.nanmin(flat)) * 0.5, float(np.nanmax(flat)) * 2.0)
        # 截断显示与触界剔除的说明写在图注里，图上不再加红字。
        for m, _ in used:
            shown.setdefault(m)

    handles = [Line2D([], [], linestyle="none", marker="o", markersize=5.2,
                      markerfacecolor=S.mineral_color(m), markeredgecolor=S.EDGE,
                      label=N.mineral(m))
               for m in shown]
    if handles:
        fig.legend(handles=handles, loc="lower center", ncol=len(handles),
                   frameon=False, fontsize=S.FONT_LEGEND, handletextpad=0.35,
                   columnspacing=1.8, bbox_to_anchor=(0.5, 0.005))
    S.save(fig, out)
