"""三类实验的整理、拟合与诊断。"""
from __future__ import annotations

import warnings as _warnings

import numpy as np
import pandas as pd
from scipy.optimize import curve_fit
from scipy.stats import linregress

from . import names as N
from .fit import FitResult, best_result, fit_many, rank
from .models import ISOTHERM_MODELS, KINETIC_MODELS, dr_energy


def _solid_for(solid, mineral: str) -> float | None:
    """取某矿物的固液比 m/V (g/L)。

    ``solid`` 可以是标量（全部体系同值）、``{矿物: g/L}`` 字典，或 None。
    本项目的五个体系固液比并不相同（0.5 / 1 / 3 g/L），必须按矿物分别取。

    键名允许中英混用：数据表里写 ``Rancieite``、配置里写 ``钙锰矿``（或反之）
    时按 names 映射后的显示名对齐，避免换个写法就静默丢固液比。
    """
    if solid is None:
        return None
    if isinstance(solid, dict):
        v = solid.get(mineral)
        if v is None:
            alias = N.mineral(mineral)
            for k, cand in solid.items():
                if k == alias or N.mineral(k) == alias:
                    v = cand
                    break
        try:
            v = float(v)
        except (TypeError, ValueError):
            return None
        return v if np.isfinite(v) and v > 0 else None
    try:
        v = float(solid)
    except (TypeError, ValueError):
        return None
    return v if np.isfinite(v) and v > 0 else None


def _unit(solid):
    """容量单位。传字典时，只要有任一矿物给了 m/V 就按 mg/g 记。"""
    if isinstance(solid, dict):
        return "mg/g" if any(_solid_for(solid, k) for k in solid) else "mg/L(悬浮液)"
    return "mg/L(悬浮液)" if not solid else "mg/g"


def _split_excluded(g: pd.DataFrame):
    """拆成（参与拟合的行, 被 exclude 标记的行, 剔除数）。

    模板里只有 ``exclude`` 列能剔除数据；没有该列时视为全部保留。
    """
    if "exclude" not in g:
        return g, g.iloc[0:0], 0
    mask = g["exclude"].astype(bool)
    return g[~mask], g[mask], int(mask.sum())


# 三类实验：(字段名, 显示名, 独立条件列, 最少点数)
EXP_SPECS = (
    ("isotherm", "等温线", "C0_ppm", 5),
    ("kinetics", "动力学", "time_h", 5),
    ("edge", "吸附边", "pH", 4),
)


def _short_groups(iso: pd.DataFrame, kin: pd.DataFrame, edge: pd.DataFrame):
    """点数不足的组：``(exp, 显示名, 矿物, 背景, 条件列, 实际点数, 需要点数)``。"""
    frames = {"isotherm": iso, "kinetics": kin, "edge": edge}
    for exp, label, col, need in EXP_SPECS:
        frame = frames[exp]
        if frame is None or frame.empty or col not in frame:
            continue
        for (m, bg), g in frame.groupby(["mineral", "background"], sort=False):
            n = int(g[col].nunique())
            if n < need:
                yield exp, label, m, bg, col, n, need


# --------------------------------------------------------------------------
# 等温线
# --------------------------------------------------------------------------

def isotherm_data(data: pd.DataFrame, solid: float | dict | None) -> pd.DataFrame:
    """等温线长表。

    这里**不改任何实测值**：Ce 为负、吸附率为负都原样保留，只在报告中提示。
    是否剔除由使用者在模板 ``exclude`` 列决定——脚本不替人做判断。
    """
    df = data[data.exp == "isotherm"].copy()
    df = df[np.isfinite(df["C0_ppm"]) & np.isfinite(df["Ce_ppm"]) & (df["C0_ppm"] > 0)]
    df["removal_pct"] = 100.0 * (1.0 - df["Ce_ppm"] / df["C0_ppm"])
    df["solid_g_per_L"] = pd.to_numeric(
        pd.Series([_solid_for(solid, m) for m in df["mineral"]], index=df.index),
        errors="coerce")
    removed = df["C0_ppm"] - df["Ce_ppm"]
    has_solid = df["solid_g_per_L"].notna()
    df["qe"] = np.where(has_solid, removed / df["solid_g_per_L"], removed)
    df["qe_unit"] = np.where(has_solid, "mg/g", "mg/L(悬浮液)")
    df["Kd"] = removed / df["Ce_ppm"].replace(0, np.nan)
    df["Kd_L_per_g"] = np.where(has_solid, df["Kd"] / df["solid_g_per_L"], np.nan)
    return df


def analyze_isotherms(df: pd.DataFrame, solid: float | None):
    fits_rows, best_rows, curves = [], [], {}
    warns = []
    if df.empty:
        return pd.DataFrame(), pd.DataFrame(), curves, ["等温线：无有效数据"]

    for (mineral, background), g in df.groupby(["mineral", "background"], sort=False):
        g = g.dropna(subset=["Ce_ppm", "qe"])
        g, excl, n_excluded = _split_excluded(g)
        if n_excluded:
            warns.append(f"{mineral}-{background}：{n_excluded} 个点被备注标记为异常/存疑，已从拟合中剔除。")
        if g.empty:
            continue
        # 同一初始浓度的重复点取均值
        agg = (g.groupby("C0_ppm", as_index=False)
                 .agg(Ce_ppm=("Ce_ppm", "mean"), qe=("qe", "mean"),
                      qe_sd=("qe", "std"),
                      removal_pct=("removal_pct", "mean"), n_rep=("qe", "size")))
        agg = agg.sort_values("C0_ppm")
        unit = str(g["qe_unit"].iloc[0]) if "qe_unit" in g else _unit(solid)

        # 单调性诊断
        rem = agg["removal_pct"].to_numpy()
        d = np.diff(rem)
        if len(d) and np.nanmax(d) > 10:
            i = int(np.nanargmax(d))
            warns.append(
                f"{mineral}-{background}：吸附率随初始浓度升高反而上升 "
                f"{d[i]:.1f} 个百分点（{agg['C0_ppm'].iloc[i]:g}→{agg['C0_ppm'].iloc[i+1]:g} ppm），"
                "建议核查该点稀释与测定。"
            )
        if (agg["removal_pct"] < -3).any():
            neg = agg[agg["removal_pct"] < -3]
            warns.append(
                f"{mineral}-{background}：{len(neg)} 个点吸附率为负（最低 "
                f"{neg['removal_pct'].min():.1f}%），已原样保留；"
                "若判断为异常，请在模板 exclude 列标 TRUE 后重跑。")

        # 不做任何按数值好坏的过滤。吸附模型的定义域要求 Ce>0、qe>0，
        # 这条限制在 fit.fit_model 内部执行，并把跳过的点数回报上来，
        # 报告里会写明"m 点因定义域限制未参与拟合"。
        fit_agg = agg[np.isfinite(agg["qe"]) & np.isfinite(agg["Ce_ppm"])]
        if len(fit_agg) < 5:
            warns.append(f"{mineral}-{background}：有效点数 {len(fit_agg)} < 5，未拟合。")
            continue

        results = fit_many(ISOTHERM_MODELS, fit_agg["Ce_ppm"], fit_agg["qe"], n_starts=36)
        for r in results:
            row = {"mineral": mineral, "background": background,
                   "ionic_strength_M": g["ionic_strength_M"].iloc[0],
                   "n_points": len(fit_agg), "qe_unit": unit,
                   "n_excluded": n_excluded, "n_fit": int(r.n),
                   "C0_range_ppm": f"{fit_agg['C0_ppm'].min():g}–{fit_agg['C0_ppm'].max():g}"}
            row.update(r.row())
            if r.key == "dr":
                row["E_kJ_per_mol"] = dr_energy(r.params["K_DR"])
            fits_rows.append(row)

        b = best_result(results)
        if b is not None:
            row = {"mineral": mineral, "background": background,
                   "best_model": b.key, "best_label": b.label,
                   "n_points": len(fit_agg), "qe_unit": unit,
                   "n_excluded": n_excluded, "n_fit": int(b.n),
                   "qe_max_obs": float(fit_agg["qe"].max()),
                   "R2": b.r2, "adj_R2": b.adj_r2, "RMSE": b.rmse,
                   "AICc": b.aicc, "at_bound": b.at_bound,
                   "start_hit_rate": b.hit_rate}
            row.update({f"best_{k}": v for k, v in b.params.items()})
            best_rows.append(row)
            if b.at_bound or (np.isfinite(b.max_corr) and b.max_corr > 0.99):
                warns.append(f"{mineral}-{background}：最优模型 {b.label} 参数触及边界或高度相关"
                             f"（max|r|={b.max_corr:.3f}），容量参数不宜直接引用。")
            if np.isfinite(b.r2) and b.r2 < 0.90:
                warns.append(f"{mineral}-{background}：等温线最优模型 R²={b.r2:.3f} < 0.90，"
                             "数据自身离散较大，模型判别需谨慎。")
            curves[(mineral, background)] = {
                "data": fit_agg, "best": b, "excluded": excl, "all": results,
                "unit": unit,
                "top": rank([r for r in results if r.converged])[:3],
            }
        else:
            warns.append(f"{mineral}-{background}：等温线模型均未收敛。")

    return pd.DataFrame(fits_rows), pd.DataFrame(best_rows), curves, warns


# --------------------------------------------------------------------------
# 动力学
# --------------------------------------------------------------------------

def kinetics_data(data: pd.DataFrame, solid: float | dict | None) -> pd.DataFrame:
    df = data[data.exp == "kinetics"].copy()
    df = df[np.isfinite(df["time_h"]) & np.isfinite(df["removal_pct"])]
    df["U"] = df["removal_pct"] / 100.0
    df["solid_g_per_L"] = pd.to_numeric(
        pd.Series([_solid_for(solid, m) for m in df["mineral"]], index=df.index),
        errors="coerce")
    has_solid = df["solid_g_per_L"].notna()
    q = df["U"] * df["C0_ppm"]
    df["qt"] = np.where(has_solid, q / df["solid_g_per_L"], q)
    df["qt_unit"] = np.where(has_solid, "mg/g", "mg/L(悬浮液)")
    return df


def _ipd_piecewise(t, y):
    """qt vs t^0.5 的两段线性拟合，返回断点与两段斜率/截距。"""
    s = np.sqrt(np.asarray(t, float))
    y = np.asarray(y, float)
    n = len(s)
    if n < 7:
        return None
    best = None
    for k in range(3, n - 2):
        p1 = np.polyfit(s[:k], y[:k], 1)
        p2 = np.polyfit(s[k:], y[k:], 1)
        ssr = np.sum((np.polyval(p1, s[:k]) - y[:k]) ** 2) + \
              np.sum((np.polyval(p2, s[k:]) - y[k:]) ** 2)
        if best is None or ssr < best[0]:
            best = (ssr, k, p1, p2)
    ssr, k, p1, p2 = best
    return {
        "break_t_h": float(t[k]),
        "k_id1": float(p1[0]), "C1": float(p1[1]),
        "k_id2": float(p2[0]), "C2": float(p2[1]),
        "ipd_ssr": float(ssr),
    }


def analyze_kinetics(df: pd.DataFrame, solid: float | None):
    fits_rows, best_rows, ipd_rows, curves = [], [], [], {}
    warns = []
    if df.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), curves, ["动力学：无有效数据"]

    for (mineral, background), g in df.groupby(["mineral", "background"], sort=False):
        g, excl, n_excluded = _split_excluded(g)
        if n_excluded:
            warns.append(f"{mineral}-{background}：{n_excluded} 个时间点被备注标记为异常/存疑，已从拟合中剔除。")
        agg = (g.groupby("time_h", as_index=False)
                 .agg(U=("U", "mean"), U_sd=("U", "std"), n_rep=("U", "size"),
                      qt=("qt", "mean"), qt_sd=("qt", "std")))
        agg = agg.sort_values("time_h")
        unit = str(g["qt_unit"].iloc[0]) if "qt_unit" in g else _unit(solid)
        if len(agg) < 5:
            warns.append(f"{mineral}-{background}：时间点不足 5 个，未拟合。")
            continue

        results = fit_many(KINETIC_MODELS, agg["time_h"], agg["qt"], n_starts=36)
        for r in results:
            row = {"mineral": mineral, "background": background,
                   "ionic_strength_M": g["ionic_strength_M"].iloc[0],
                   "n_points": len(agg), "qt_unit": unit,
                   "n_excluded": n_excluded, "n_fit": int(r.n)}
            row.update(r.row())
            if r.key == "pso":
                qe, k2 = r.params["qe"], r.params["k2"]
                row["h0"] = k2 * qe ** 2
                row["t_half_h"] = 1.0 / max(k2 * qe, 1e-30)
            if r.key == "pfo":
                row["t_half_h"] = np.log(2) / max(r.params["k1"], 1e-30)
            fits_rows.append(row)

        b = best_result(results)
        if b is not None:
            row = {"mineral": mineral, "background": background,
                   "best_model": b.key, "best_label": b.label,
                   "n_points": len(agg), "qt_unit": unit,
                   "n_excluded": n_excluded, "n_fit": int(b.n),
                   "U_max_obs": float(agg["U"].max()),
                   "R2": b.r2, "adj_R2": b.adj_r2, "RMSE": b.rmse, "AICc": b.aicc,
                   "at_bound": b.at_bound, "max_param_corr": b.max_corr,
                   "start_hit_rate": b.hit_rate}
            row.update({f"best_{k}": v for k, v in b.params.items()})
            best_rows.append(row)
            r2max = max((r.r2 for r in results if np.isfinite(r.r2)), default=np.nan)
            if np.isfinite(r2max) and r2max < 0.50:
                warns.append(f"{mineral}-{background}：所有动力学模型 R² 最高仅 {r2max:.2f}，"
                             "吸附分数随时间无明显趋势，不宜报告 qe/k。")
            elif np.isfinite(b.r2) and b.r2 < 0.85:
                warns.append(f"{mineral}-{background}：动力学最优模型 R²={b.r2:.3f}，"
                             "数据噪声较大或存在未识别机制。")
            curves[(mineral, background)] = {
                "data": agg, "best": b, "excluded": excl, "all": results,
                "unit": unit,
                "top": rank([r for r in results if r.converged])[:3],
            }

        ipd = _ipd_piecewise(agg["time_h"].to_numpy(), agg["qt"].to_numpy())
        if ipd:
            ipd.update({"mineral": mineral, "background": background,
                        "qt_unit": unit})
            ipd_rows.append(ipd)
            if (mineral, background) in curves:
                curves[(mineral, background)]["ipd"] = ipd
            if ipd["k_id2"] <= 0:
                warns.append(f"{mineral}-{background}：颗粒内扩散第二段斜率 ≤ 0，"
                             "说明后期无扩散控制特征，该分段结果不宜解释。")

        # 异常跳变
        u = agg["U"].to_numpy()
        du = np.diff(u)
        if len(du) and np.nanmax(np.abs(du)) > 0.25:
            i = int(np.nanargmax(np.abs(du)))
            warns.append(
                f"{mineral}-{background}：{agg['time_h'].iloc[i]:g}→{agg['time_h'].iloc[i+1]:g} h "
                f"吸附分数变化 {du[i]*100:.1f} 个百分点，明显大于相邻点，建议核查。"
            )

    return pd.DataFrame(fits_rows), pd.DataFrame(best_rows), pd.DataFrame(ipd_rows), curves, warns


def equilibrium_time(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (mineral, background), g in df.groupby(["mineral", "background"]):
        if "exclude" in g:
            g = g[~g["exclude"]]
        agg = g.groupby("time_h")["U"].mean().sort_index()
        if agg.empty:
            continue
        umax = agg.max()
        hit = agg[agg >= 0.98 * umax]
        rows.append({"mineral": mineral, "background": background,
                     "U_max": umax, "t_eq_h": float(hit.index.min()) if len(hit) else np.nan})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# 吸附边
# --------------------------------------------------------------------------

def _logistic(ph, bottom, top, ph50, w):
    return bottom + (top - bottom) / (1.0 + np.exp((ph - ph50) / w))


def edge_data(data: pd.DataFrame) -> pd.DataFrame:
    df = data[data.exp == "edge"].copy()
    df = df[np.isfinite(df["pH"]) & np.isfinite(df["removal_pct"])]
    df["theta"] = df["removal_pct"] / 100.0
    return df


def _edge_hint(delta: float, direction: str) -> str:
    """把"差多少"与"往哪个方向差"合成一句可用的结论。

    曲线交叉时不能再说"整体更强/更弱"——两条边在不同 pH 段走向相反，
    单一 pH50 排序会给出错误结论，这一点必须显式写出来。
    """
    if not np.isfinite(delta):
        return "无法比较"
    if delta < 5:
        return "差异小 → 以内圈络合为主（仍需光谱证据）"
    if "交叉" in str(direction) or "不一致" in str(direction):
        return "曲线交叉 → 机理随 pH 改变，不能以单一 pH50 排序；建议逐 pH 比较并核查批次"
    stronger = "更强" if "更高" in str(direction) else "更弱"
    return f"差异显著 → 该离子强度下吸附整体{stronger}，符合静电/离子交换竞争，需光谱或表面络合模型佐证"


def analyze_edges(df: pd.DataFrame):
    rows, curves, compare = [], {}, []
    warns = []
    if df.empty:
        return pd.DataFrame(), curves, pd.DataFrame(), ["吸附边：无有效数据"]

    for (mineral, background), g in df.groupby(["mineral", "background"], sort=False):
        g, _, n_excluded = _split_excluded(g)
        if n_excluded:
            warns.append(f"{mineral}-{background}：{n_excluded} 个 pH 点被备注标记为异常，已从拟合中剔除。")
        agg = (g.groupby("pH", as_index=False)
                 .agg(theta=("theta", "mean"), theta_sd=("theta", "std"),
                      n_rep=("theta", "size")))
        agg = agg.sort_values("pH")
        if len(agg) < 4:
            continue

        if (agg["theta"] < -0.02).any():
            warns.append(f"{mineral}-{background}：出现负吸附率（最低 {agg['theta'].min()*100:.1f}%），"
                         "已原样保留并参与拟合；若判断为异常，请在模板 exclude 列标 TRUE 后重跑。")

        x = agg["pH"].to_numpy(float)
        y = agg["theta"].to_numpy(float)
        p0 = [max(min(y.min(), 0.0), -0.05), max(y.max(), 0.5), np.median(x), 1.0]
        lo = [-0.3, 0.0, 2.0, 0.05]
        hi = [0.5, 1.5, 12.0, 10.0]
        try:
            popt, pcov = curve_fit(_logistic, x, y, p0=p0, bounds=(lo, hi),
                                   maxfev=50000, loss="soft_l1", f_scale=0.05)
            perr = np.sqrt(np.maximum(np.diag(pcov), 0))
            bottom, top, ph50, w = popt
            pred = _logistic(x, *popt)
            ss_res = np.sum((y - pred) ** 2)
            ss_tot = np.sum((y - y.mean()) ** 2)
            r2 = 1 - ss_res / ss_tot if ss_tot > 0 else np.nan
            slope = -(top - bottom) / (4 * w)
            ok = True
            resid = y - pred
            rmse = float(np.sqrt(np.mean(resid ** 2)))
            out_idx = np.where(np.abs(resid) > max(0.15, 2.0 * rmse))[0]
            outliers = ";".join(f"{x[i]:g}" for i in out_idx)
            n_out = int(len(out_idx))
        except Exception:
            bottom = top = ph50 = w = slope = r2 = np.nan
            perr = np.full(4, np.nan)
            ok = False
            outliers, n_out = "", 0
            warns.append(f"{mineral}-{background}：logistic 拟合失败，仅输出原始曲线。")

        # log Kd ~ pH 斜率（10–90% 吸附窗口）
        win = agg[(agg["theta"] > 0.10) & (agg["theta"] < 0.90)]
        if len(win) >= 3:
            lr = linregress(win["pH"], np.log10(win["theta"] / (1 - win["theta"])))
            kd_slope, kd_r2 = lr.slope, lr.rvalue ** 2
        else:
            kd_slope = kd_r2 = np.nan

        rows.append({
            "mineral": mineral, "background": background,
            "ionic_strength_M": g["ionic_strength_M"].iloc[0],
            "n_points": len(agg), "n_excluded": n_excluded,
            "pH_range": f"{x.min():g}–{x.max():g}",
            "theta_min": float(y.min()), "theta_max": float(y.max()),
            "pH50": float(ph50), "pH50_SE": float(perr[2]) if ok else np.nan,
            "edge_width": float(w), "slope_at_pH50": float(slope),
            "plateau_high": float(top) if ok else np.nan,
            "plateau_low": float(bottom) if ok else np.nan,
            "R2_logistic": float(r2),
            "logKd_slope": float(kd_slope), "logKd_R2": float(kd_r2),
            "n_outlier": n_out, "outlier_pH": outliers,
            "fit_ok": ok, "reliable": bool(ok and np.isfinite(r2) and r2 >= 0.60),
        })
        if ok and n_out:
            warns.append(f"{mineral}-{background}：pH {outliers} 偏离 logistic 趋势超过 15 个百分点，"
                         "建议复核该点。")
        if not (ok and np.isfinite(r2) and r2 >= 0.60):
            warns.append(f"{mineral}-{background}：吸附边 logistic 拟合 R²={r2:.2f}，"
                         "曲线无清晰 S 形，pH50 不宜引用。")
        curves[(mineral, background)] = {"data": agg, "popt": popt if ok else None,
                                              "ok": ok, "r2": float(r2),
                                              "reliable": bool(ok and np.isfinite(r2) and r2 >= 0.60)}

    # 离子强度对比
    minerals = {}
    for (mineral, background), c in curves.items():
        if not c.get("reliable"):
            continue
        minerals.setdefault(mineral, []).append((background, c))

    for mineral, items in minerals.items():
        if len(items) < 2:
            continue
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                b1, c1 = items[i]
                b2, c2 = items[j]
                lo = max(c1["data"]["pH"].min(), c2["data"]["pH"].min())
                hi = min(c1["data"]["pH"].max(), c2["data"]["pH"].max())
                if hi - lo < 1:
                    continue
                grid = np.linspace(lo, hi, 61)
                y1 = np.interp(grid, c1["data"]["pH"], c1["data"]["theta"])
                y2 = np.interp(grid, c2["data"]["pH"], c2["data"]["theta"])
                diff = y2 - y1
                dmax = float(np.max(np.abs(diff)) * 100)
                if np.all(diff > 0.02):
                    direction = f"{b2} 更高"
                elif np.all(diff < -0.02):
                    direction = f"{b2} 更低"
                else:
                    direction = "曲线交叉/方向不一致"
                if "交叉" in direction:
                    warns.append(f"{mineral}（{b1} vs {b2}）：吸附边曲线交叉，不能用单一 pH50 排序，"
                                 "建议逐 pH 比较并核查测定批次。")
                compare.append({
                    "mineral": mineral, "pair": f"{b1} vs {b2}",
                    "overlap_pH": f"{lo:g}–{hi:g}",
                    "max_delta_theta_pct": dmax,
                    "mean_delta_theta_pct": float(np.mean(np.abs(diff)) * 100),
                    "direction": direction,
                })

    cmp_df = pd.DataFrame(compare)
    if not cmp_df.empty:
        cmp_df["hint"] = [_edge_hint(d, s) for d, s in
                          zip(cmp_df["max_delta_theta_pct"], cmp_df["direction"])]
    return pd.DataFrame(rows), curves, cmp_df, warns


# --------------------------------------------------------------------------
# 汇总诊断
# --------------------------------------------------------------------------

def raw_warnings(data: pd.DataFrame) -> list[str]:
    """原始长表层面的缺列检查：这些行会被后续过滤掉，但必须让人知道。"""
    out = []
    if data.empty:
        return out
    checks = [("kinetics", "time_h", "时间"), ("edge", "pH", "pH")]
    for exp, col, label in checks:
        sub = data[data["exp"] == exp]
        if sub.empty or col not in sub:
            continue
        miss = sub[sub[col].isna() & sub["Ce_ppm"].notna()]
        for _, r in miss.iterrows():
            loc = f"{r.get('file', '?')} 第 {int(r['row'])} 行" if pd.notna(r.get("row")) else "?"
            out.append(f"{exp}：{loc}（{r.get('mineral', '?')}-{r.get('background', '?')}，"
                       f"Ce={r['Ce_ppm']:.3g} mg/L）缺{label}，该点已跳过。")
    return out


def quality_issues(data: pd.DataFrame, iso: pd.DataFrame, kin: pd.DataFrame,
                   edge: pd.DataFrame, qc: pd.DataFrame) -> pd.DataFrame:
    """把所有"可疑但未处理"的点列成一张清单。

    脚本只报告、不剔除、不修正——是否去掉由使用者在模板 ``exclude`` 列决定。
    每行都带 Excel 行号，可以据此直接定位回原表。
    """
    cols = ["exp", "mineral", "background", "row", "condition",
            "Ce_ppm", "removal_pct", "issue", "suggestion"]
    rows: list[dict] = []

    def push(exp, mineral, background, row, cond, ce, rem, issue, suggest):
        rows.append({"exp": exp, "mineral": mineral, "background": background,
                     "row": int(row) if row is not None and pd.notna(row) else np.nan,
                     "condition": cond, "Ce_ppm": ce, "removal_pct": rem,
                     "issue": issue, "suggestion": suggest})

    def cond_of(r) -> str:
        exp = str(r.get("exp", ""))
        if exp == "isotherm":
            v = r.get("C0_ppm", np.nan)
            return f"C0 = {v:g} mg/L" if pd.notna(v) else "C0 = —"
        if exp == "kinetics":
            v = r.get("time_h", np.nan)
            return f"t = {v:g} h" if pd.notna(v) else "t = —"
        if exp == "edge":
            v = r.get("pH", np.nan)
            return f"pH = {v:g}" if pd.notna(v) else "pH = —"
        return ""

    # ---- 逐行：数值本身可疑 ----
    if data is not None and not data.empty:
        for _, r in data.iterrows():
            exp = str(r.get("exp", ""))
            if exp not in ("isotherm", "kinetics", "edge"):
                continue
            rem = r.get("removal_pct", np.nan)
            ce = r.get("Ce_ppm", np.nan)
            c0 = r.get("C0_ppm", np.nan)
            if pd.isna(rem):
                continue          # 空值＝使用者已主动删除，不再提示
            rem = float(rem)
            if exp == "kinetics" and pd.isna(r.get("time_h", np.nan)):
                push(exp, r.get("mineral"), r.get("background"), r.get("row"),
                     cond_of(r), ce, rem, "缺时间",
                     "补填 time_h，否则该行不进入动力学拟合")
            if exp == "edge" and pd.isna(r.get("pH", np.nan)):
                push(exp, r.get("mineral"), r.get("background"), r.get("row"),
                     cond_of(r), ce, rem, "缺 pH",
                     "补填 pH，否则该行不进入吸附边拟合")
            if rem < -1:
                push(exp, r.get("mineral"), r.get("background"), r.get("row"),
                     cond_of(r), ce, rem, f"负吸附率 {rem:.1f}%",
                     "复核空白/基体与稀释；确属异常可在 exclude 列标 TRUE")
            elif pd.notna(ce) and pd.notna(c0) and float(ce) > float(c0):
                push(exp, r.get("mineral"), r.get("background"), r.get("row"),
                     cond_of(r), ce, rem, "Ce > C0",
                     "平衡浓度高于初始浓度，检查标线范围与稀释倍数")
            if rem > 101:
                push(exp, r.get("mineral"), r.get("background"), r.get("row"),
                     cond_of(r), ce, rem, f"吸附率 {rem:.1f}% > 100%",
                     "Ce 低于检出下限或空白扣除过度，建议复测该点")

    # ---- 组级：点数与平行样离散 ----
    for exp, label, m, bg, col, n, need in _short_groups(iso, kin, edge):
        rows.append({"exp": exp, "mineral": m, "background": bg,
                     "row": np.nan, "condition": f"{n} 个独立{col.replace('_ppm','')}点",
                     "Ce_ppm": np.nan, "removal_pct": np.nan,
                     "issue": f"点数不足（{n} < {need}）",
                     "suggestion": f"{label}模型参数不宜引用，建议补点或减少模型参数"})
    for (exp, _label, col, _need), frame in zip(EXP_SPECS, (iso, kin, edge)):
        if frame is None or frame.empty or col not in frame:
            continue
        for (m, bg), g in frame.groupby(["mineral", "background"], sort=False):
            dup = g[g.duplicated(col, keep=False)]
            for key, gg in dup.groupby(col):
                if len(gg) < 2:
                    continue
                v = pd.to_numeric(gg["removal_pct"], errors="coerce").dropna().to_numpy(float)
                if v.size < 2:
                    continue
                mean = float(np.mean(v))
                rsd = float(np.std(v, ddof=1) / abs(mean) * 100) if mean else np.nan
                if np.isfinite(rsd) and rsd > 15:
                    rws = ", ".join(str(int(x)) for x in gg["row"].dropna())
                    rows.append({"exp": exp, "mineral": m, "background": bg,
                                 "row": np.nan, "condition": f"{col.replace('_ppm','')}={key:g}",
                                 "Ce_ppm": np.nan, "removal_pct": mean,
                                 "issue": f"平行样 RSD = {rsd:.0f}%（行 {rws}）",
                                 "suggestion": "平行样离散偏大，复核该组操作或增加重复数"})

    # ---- QC ----
    if qc is not None and not qc.empty and "recovery_pct" in qc:
        for _, r in qc.iterrows():
            rec = r.get("recovery_pct", np.nan)
            if pd.isna(rec):
                continue
            rec = float(rec)
            if rec < 80 or rec > 120:
                rows.append({"exp": "qc", "mineral": "", "background": "",
                             "row": np.nan,
                             "condition": str(r.get("qc", r.get("exp", ""))),
                             "Ce_ppm": r.get("conc_ppb", np.nan),
                             "removal_pct": np.nan,
                             "issue": f"回收率 {rec:.0f}%",
                             "suggestion": "复核标线与加标量；该点仍参与其他计算"})

    if not rows:
        return pd.DataFrame(columns=cols)
    out = pd.DataFrame(rows, columns=cols)
    return out.sort_values(["exp", "row"], na_position="last").reset_index(drop=True)


def data_warnings(iso: pd.DataFrame, kin: pd.DataFrame, edge: pd.DataFrame, qc: pd.DataFrame):
    """组级提示（方法可行性）。

    逐点可疑值不在这里堆成一句话，改由 :func:`quality_issues` 输出为表格，
    每行带 Excel 行号与建议动作。空值（使用者已删的点）不提示。
    """
    out = []
    for _exp, label, mineral, background, _col, n, need in _short_groups(iso, kin, edge):
        out.append(f"{label} {mineral}-{background}：仅 {n} 个独立条件点（< {need}），"
                   "模型参数不宜引用。")
    if qc is not None and not qc.empty and "recovery_pct" in qc:
        bad = qc[(qc["recovery_pct"] < 80) | (qc["recovery_pct"] > 120)]
        if not bad.empty:
            out.append(f"QC 回收率超出 80–120% 共 {len(bad)} 条，逐条见数据质量清单。")
    return out


# --------------------------------------------------------------------------
# 模型可靠性审计
# --------------------------------------------------------------------------

def model_audit(fits: pd.DataFrame, kind: str = "isotherm") -> pd.DataFrame:
    """逐组判断"这个模型的参数能不能引用"。

    四条判据，从强到弱：
      1. 参数触界（at_bound）或最大参数相关系数 > 0.99 → 参数不可识别；
      2. 多起点收敛率 < 0.5 → 目标函数有多个等价极小，解不唯一；
      3. ΔAICc ≤ 2 → 与最优模型没有实质差别（Burnham & Anderson）；
      4. 其余按 ΔAICc 递减，支持度低。
    ``R²`` 只作描述，不参与判定——不同参数个数的模型不能用 R² 直接比。
    """
    if fits is None or fits.empty or "AICc" not in fits:
        return pd.DataFrame()
    rows = []
    for (mineral, background), g in fits.groupby(["mineral", "background"], sort=False):
        g = g.copy()
        finite = g["AICc"].replace([np.inf, -np.inf], np.nan)
        g["dAICc"] = finite - finite.min()
        best_key = g.loc[g["dAICc"].idxmin(), "model"] if finite.notna().any() else None
        for _, r in g.iterrows():
            corr = r.get("max_param_corr", np.nan)
            hit = r.get("start_hit_rate", np.nan)
            r2 = r.get("R2", np.nan)
            if bool(r.get("at_bound", False)) or (np.isfinite(corr) and corr > 0.99):
                verdict = "参数不可识别（触界/共线）"
            elif np.isfinite(r2) and r2 < 0.5:
                verdict = "模型不适定（R²<0.5）"
            elif np.isfinite(hit) and hit < 0.5:
                verdict = "多解（收敛率偏低）"
            elif r["model"] == best_key:
                verdict = "最优模型"
            elif np.isfinite(r["dAICc"]) and r["dAICc"] <= 2:
                verdict = "与最优无实质差异"
            elif np.isfinite(r["dAICc"]) and r["dAICc"] <= 7:
                verdict = "支持度较弱"
            else:
                verdict = "不支持"
            rows.append({
                "kind": kind, "mineral": mineral, "background": background,
                "model": r["model"], "model_label": r.get("model_label", r["model"]),
                "n_points": r.get("n", np.nan), "p": r.get("p", np.nan),
                "R2": r.get("R2", np.nan), "adj_R2": r.get("adj_R2", np.nan),
                "RMSE": r.get("RMSE", np.nan), "AICc": r.get("AICc", np.nan),
                "dAICc": r.get("dAICc", np.nan),
                "start_hit_rate": hit, "max_param_corr": corr,
                "at_bound": r.get("at_bound", False),
                "verdict": verdict,
            })
    return pd.DataFrame(rows)
