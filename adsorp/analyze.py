"""三类实验的整理、拟合与诊断。"""
from __future__ import annotations

import warnings as _warnings

import numpy as np
import pandas as pd
from scipy.optimize import curve_fit
from scipy.stats import linregress

from . import names as N
from .fit import FitResult, best_result, fit_many, rank
from .models import KINETIC_MODELS, active_isotherms, dr_energy


def _solid_for(solid, mineral: str) -> float | None:
    """取某吸附剂的固液比 m/V (g/L)。

    ``solid`` 可以是标量（全部体系同值）、``{吸附剂: g/L}`` 字典，或 None。
    不同吸附剂的固液比往往不同（例如 0.5 / 1 / 3 g/L 混在一批数据里），
    所以必须按吸附剂分别取，不能全局套一个数。

    键名允许中英混用：数据表里写 ``Goethite``、配置里写 ``针铁矿``（或反之）
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
    """容量单位。传字典时，只要有任一吸附剂给了 m/V 就按 mg/g 记。"""
    if isinstance(solid, dict):
        return "mg/g" if any(_solid_for(solid, k) for k in solid) else "mg/L(悬浮液)"
    return "mg/L(悬浮液)" if not solid else "mg/g"


def _solid_series(df: pd.DataFrame, solid) -> pd.Series:
    """逐行固液比 m/V：**行内值优先**，为空才回退 Settings / 吸附剂映射。

    模板里逐行填的 ``solid_g_per_L`` 是这一行真实的 m/V，比 Settings 里
    按吸附剂给的单值更具体。两者的优先级若写反（Settings 覆盖行内值），
    表内写 2、Settings 写 1 时 qe 会整整放大一倍，且报告里看不出来。
    """
    fallback = pd.Series([_solid_for(solid, m) for m in df["mineral"]],
                         index=df.index, dtype="float")
    if "solid_g_per_L" not in df:
        return fallback
    row = pd.to_numeric(df["solid_g_per_L"], errors="coerce")
    return row.where(row > 0).fillna(fallback)


def _group_unit(g: pd.DataFrame, col: str, solid) -> tuple[str, str]:
    """组内统一的容量单位；返回 ``(单位, 混用提示或空串)``。

    同一组里若部分行有 m/V、部分没有，整组会被拆成 mg/g 与 mg/L(悬浮液)
    两种口径，曲线不能横向比较。过去取第一行的单位当整组标签，等于把
    另一口径的数据也标称成它，读者无从察觉。
    """
    if col not in g:
        return _unit(solid), ""
    vals = [str(v) for v in g[col].dropna().unique()]
    if len(vals) == 1:
        return vals[0], ""
    if len(vals) > 1:
        return "mixed", ("组内容量单位不一致（部分行有固液比、部分没有），"
                         "已混用 mg/g 与 mg/L(悬浮液)，该组曲线不可横向比较。")
    return _unit(solid), ""


def _split_excluded(g: pd.DataFrame):
    """拆成（参与拟合的行, 被 exclude 标记的行, 剔除数）。

    模板里只有 ``exclude`` 列能剔除数据；没有该列时视为全部保留。
    """
    if "exclude" not in g:
        return g, g.iloc[0:0], 0
    mask = g["exclude"].astype(bool)
    return g[~mask], g[mask], int(mask.sum())


# 三类实验：(字段名, 显示名, 独立条件列, 最少点数)
# 等温线 4 点即可拟合双参数模型（fit_model 的门槛是 n ≥ p+2，dof=2）；
# 过去一刀切要求 5 点，把 4 点的低浓度序列整体拒之门外。
EXP_SPECS = (
    ("isotherm", "等温线", "C0_ppm", 4),
    ("kinetics", "动力学", "time_h", 5),
    ("edge", "吸附边", "pH", 4),
)


def _short_groups(iso: pd.DataFrame, kin: pd.DataFrame, edge: pd.DataFrame):
    """点数不足的组：``(exp, 显示名, 吸附剂, 背景, 条件列, 实际点数, 需要点数)``。"""
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
    df["solid_g_per_L"] = _solid_series(df, solid)
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
        unit, unit_warn = _group_unit(g, "qe_unit", solid)
        if unit_warn:
            warns.append(f"{mineral}-{background}：{unit_warn}")

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
        if len(fit_agg) < 4:
            warns.append(f"{mineral}-{background}：有效点数 {len(fit_agg)} < 4，未拟合"
                         "（双参数模型至少需要 4 点才能给出自由度）。")
            continue

        results = fit_many(active_isotherms(), fit_agg["Ce_ppm"], fit_agg["qe"], n_starts=36)
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
    df["solid_g_per_L"] = _solid_series(df, solid)
    has_solid = df["solid_g_per_L"].notna()
    q = df["U"] * df["C0_ppm"]
    df["qt"] = np.where(has_solid, q / df["solid_g_per_L"], q)
    df["qt_unit"] = np.where(has_solid, "mg/g", "mg/L(悬浮液)")
    return df


IPD_STAGES = (2, 3)
IPD_MIN_PTS = 3          # 每段至少几个点（2 点定一条直线，3 点才有一个残差自由度）


def _ipd_breaks(n: int, stages: int, min_pts: int = IPD_MIN_PTS):
    """枚举所有可行的分段位置（升序，保证同 SSR 时取靠前的断点）。"""
    if stages == 2:
        for k in range(min_pts, n - min_pts + 1):
            yield [k]
    else:
        for k1 in range(min_pts, n - 2 * min_pts + 1):
            for k2 in range(k1 + min_pts, n - min_pts + 1):
                yield [k1, k2]


def _ipd_piecewise(t, y, stages: int = 2, min_pts: int = IPD_MIN_PTS):
    """qt vs t^0.5 的分段线性拟合，断点由总残差最小确定。

    ``stages=2`` 两段（膜扩散 → 颗粒内扩散，或颗粒内扩散 → 平衡）；
    ``stages=3`` 三段，对应教科书上的完整图像：膜扩散 / 颗粒内扩散 / 平衡。
    三段要求 n ≥ 3×min_pts+1 = 10，每段至少 3 个点——点数更少时两段的
    斜率标准误已经很大，硬切三段等于用噪声定断点，因此直接返回 None。
    """
    s = np.sqrt(np.asarray(t, float))
    y = np.asarray(y, float)
    n = len(s)
    stages = int(stages)
    if stages not in IPD_STAGES:
        raise ValueError(f"IPD 分段数只能是 2 或 3，收到 {stages}")
    if n < stages * min_pts + 1:
        return None
    best = None
    for brk in _ipd_breaks(n, stages, min_pts):
        segs, ssr, start = [], 0.0, 0
        for b in (*brk, n):
            p = np.polyfit(s[start:b], y[start:b], 1)
            ssr += np.sum((np.polyval(p, s[start:b]) - y[start:b]) ** 2)
            segs.append(p)
            start = b
        if best is None or ssr < best[0]:
            best = (ssr, brk, segs)
    ssr, brk, segs = best
    # 列序：断点在前、各段参数在后；两段时正好是原来的
    # break_t_h / k_id1 / C1 / k_id2 / C2 / ipd_ssr，不多不少。
    out = {"break_t_h": float(t[brk[0]])}
    for i, b in enumerate(brk[1:], 2):
        out[f"break{i}_t_h"] = float(t[b])
    for i, p in enumerate(segs, 1):
        out[f"k_id{i}"] = float(p[0])
        out[f"C{i}"] = float(p[1])
    out["ipd_ssr"] = float(ssr)
    if stages == 3:
        # 每段点数写进表里：读者一眼就能看出 3/3/4 这种分段是不是在拟合噪声
        out["n_seg"] = "/".join(str(b - a) for a, b in
                                zip([0, *brk], [*brk, n]))
    return out


def _ipd_warns(ipd: dict, stages: int = 2) -> list[str]:
    """检查分段斜率是否按「先快后慢」递减（不含吸附剂名前缀）。"""
    order = ("一", "二", "三")
    k = [ipd[f"k_id{i}"] for i in range(1, stages + 1)]
    if k[-1] <= 0:
        return [f"颗粒内扩散第{order[stages - 1]}段斜率 ≤ 0，说明后期已无扩散控制特征，"
                "该分段结果不宜解释。"]
    bad = [i for i in range(stages - 1) if k[i + 1] >= k[i]]
    if not bad:
        return []
    ks = "、".join(f"k{i + 1}={v:.4g}" for i, v in enumerate(k))
    pairs = "、".join(f"第{order[i + 1]}段 ≥ 第{order[i]}段" for i in bad)
    return [f"颗粒内扩散斜率未随分段递减（{ks}）——{pairs}，"
            "与「先快后慢」的扩散图像不符；常见于该段点数不足或被噪声拉动，"
            "该分段结果需谨慎解释。"]


def ipd_fit(t, y, stages: int = 2):
    """算一组数据的 IPD 分段，返回 ``(参数字典 | None, 提示列表)``。

    与 ``_ipd_piecewise`` 的区别是带上斜率单调性判据，供流水线与
    ``--reuse`` 重算共用，保证两条路径给出的提示一致。
    """
    ipd = _ipd_piecewise(t, y, stages)
    if ipd is None:
        n = len(np.asarray(t, float))
        if stages > 2:
            return None, [f"颗粒内扩散需 ≥{stages * IPD_MIN_PTS + 1} 个时间点"
                          f"才能分 {stages} 段（现有 {n} 个），未分段。"]
        return None, []
    return ipd, _ipd_warns(ipd, stages)


def analyze_kinetics(df: pd.DataFrame, solid: float | None, ipd_stages: int = 2):
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
        unit, unit_warn = _group_unit(g, "qt_unit", solid)
        if unit_warn:
            warns.append(f"{mineral}-{background}：{unit_warn}")
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

        ipd, ipd_warns = ipd_fit(agg["time_h"].to_numpy(), agg["qt"].to_numpy(),
                                 ipd_stages)
        for msg in ipd_warns:
            warns.append(f"{mineral}-{background}：{msg}")
        if ipd:
            ipd.update({"mineral": mineral, "background": background,
                        "qt_unit": unit})
            ipd_rows.append(ipd)
            if (mineral, background) in curves:
                curves[(mineral, background)]["ipd"] = ipd

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
    """四参数 logistic 吸附边。

    ``bottom`` 是 **pH→+∞ 的平台**（高 pH 平台），``top`` 是 **pH→−∞ 的平台**
    （低 pH 平台）。两个名字容易被读成"上/下"而以为 bottom 是小值，实际
    取决于曲线是下降边还是上升边——阳离子吸附通常随 pH 上升，此时 bottom>top。
    """
    return bottom + (top - bottom) / (1.0 + np.exp((ph - ph50) / w))


def edge_data(data: pd.DataFrame) -> pd.DataFrame:
    df = data[data.exp == "edge"].copy()
    df = df[np.isfinite(df["pH"]) & np.isfinite(df["removal_pct"])]
    df["theta"] = df["removal_pct"] / 100.0
    return df


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
        # 初值按"低 pH 端 → top、高 pH 端 → bottom"给，上升边与下降边都能起步：
        # 过去把 bottom 固定成 y.min()、上界卡在 0.5，递增型吸附边（阳离子
        # 常见形态）根本无法表达，会被硬压成一条错误的下降曲线。
        n_edge = max(1, len(x) // 4)
        order = np.argsort(x)
        low_ph = float(np.median(y[order[:n_edge]]))    # pH 低端 → top
        high_ph = float(np.median(y[order[-n_edge:]]))  # pH 高端 → bottom
        p0 = [high_ph, low_ph, float(np.median(x)), 1.0]
        lo = [-0.3, -0.2, 2.0, 0.05]
        hi = [1.2, 1.5, 12.0, 10.0]
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

        # log Kd–pH 斜率（10–90% 吸附窗口）。
        # 用逐点 Kd = (C0−Ce)/Ce，而不是 θ/(1−θ)：Langmuir 下
        #   log[θ/(1−θ)] = log K + log Ce
        # 对 pH 求导会多出 d(log Ce)/dpH 一项，而吸附边实验中 Ce 随 pH
        # 显著变化，这一项不可忽略（实测两组差 2.1–2.5 倍的斜率）。
        kdf = g[np.isfinite(g["C0_ppm"]) & np.isfinite(g["Ce_ppm"])
                & (g["Ce_ppm"] > 0) & (g["C0_ppm"] > 0)]
        kdf = kdf.assign(Kd=(kdf["C0_ppm"] - kdf["Ce_ppm"]) / kdf["Ce_ppm"])
        win = kdf[(kdf["theta"] > 0.10) & (kdf["theta"] < 0.90) & (kdf["Kd"] > 0)]
        if len(win) >= 3:
            lr = linregress(win["pH"], np.log10(win["Kd"]))
            kd_slope, kd_r2 = lr.slope, lr.rvalue ** 2
            kd_n = int(len(win))
        else:
            kd_slope = kd_r2 = np.nan
            kd_n = int(len(win))
            warns.append(f"{mineral}-{background}：10–90% 吸附窗口内只有 {kd_n} 个可用点"
                         "（需 C0、Ce 均有效且 Ce>0），log Kd–pH 斜率未计算。")

        reliable = bool(ok and np.isfinite(r2) and r2 >= 0.60)
        # bottom 是高 pH 平台、top 是低 pH 平台。bottom>top 说明高 pH 端吸附更多，
        # 也就是吸附随 pH 上升——阳离子吸附的常见形态。
        direction = ("上升边（高 pH 吸附更强）" if ok and bottom > top
                     else "下降边（高 pH 吸附更弱）" if ok else "")

        rows.append({
            "mineral": mineral, "background": background,
            "ionic_strength_M": g["ionic_strength_M"].iloc[0],
            "n_points": len(agg), "n_excluded": n_excluded,
            "pH_range": f"{x.min():g}–{x.max():g}",
            "theta_min": float(y.min()), "theta_max": float(y.max()),
            # pH50 与两个平台值只有 R²≥0.60 时才输出：拟合不成立时给出一个
            # "看起来精确"的数字，比留空更危险。R² 与 fit_ok 保留供诊断。
            "pH50": float(ph50) if reliable else np.nan,
            "pH50_SE": float(perr[2]) if reliable else np.nan,
            "edge_width": float(w) if reliable else np.nan,
            "slope_at_pH50": float(slope) if reliable else np.nan,
            # _logistic 里 pH→+∞ 趋于 bottom、pH→−∞ 趋于 top（过去写反了）
            "plateau_high": float(bottom) if reliable else np.nan,
            "plateau_low": float(top) if reliable else np.nan,
            "edge_direction": direction,
            "R2_logistic": float(r2),
            "logKd_slope": float(kd_slope), "logKd_R2": float(kd_r2),
            "logKd_n": kd_n,
            "n_outlier": n_out, "outlier_pH": outliers,
            "fit_ok": ok, "reliable": reliable,
        })
        if ok and n_out:
            warns.append(f"{mineral}-{background}：pH {outliers} 偏离 logistic 趋势超过 15 个百分点，"
                         "建议复核该点。")
        if not reliable:
            warns.append(f"{mineral}-{background}：吸附边 logistic 拟合 R²={r2:.2f} < 0.60，"
                         "曲线无清晰 S 形，pH50 与两个平台值均未输出。")
        curves[(mineral, background)] = {"data": agg, "popt": popt if ok else None,
                                              "ok": ok, "r2": float(r2),
                                              "reliable": reliable}

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
                # 只给事实：差多少、往哪个方向差。机理解读（"内圈络合""静电竞争"）
                # 一律不写——脚本无法保证对每个体系都描述准确，交叉也可能只是
                # 批次波动，把它写成机理结论会误导。
                compare.append({
                    "mineral": mineral, "pair": f"{b1} vs {b2}",
                    "overlap_pH": f"{lo:g}–{hi:g}",
                    "max_delta_theta_pct": dmax,
                    "mean_delta_theta_pct": float(np.mean(np.abs(diff)) * 100),
                    "direction": direction,
                })

    return pd.DataFrame(rows), curves, pd.DataFrame(compare), warns


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
