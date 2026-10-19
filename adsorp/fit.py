"""有界非线性最小二乘拟合、误差指标与模型比较。"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import stats
from scipy.optimize import least_squares

from .models import Model


@dataclass
class FitResult:
    key: str
    label: str
    params: dict
    se: dict = field(default_factory=dict)
    ci_lo: dict = field(default_factory=dict)
    ci_hi: dict = field(default_factory=dict)
    n: int = 0
    p: int = 0
    ssr: float = np.nan
    r2: float = np.nan
    adj_r2: float = np.nan
    rmse: float = np.nan
    chi2: float = np.nan
    are: float = np.nan
    mpsd: float = np.nan
    aic: float = np.nan
    aicc: float = np.nan
    max_corr: float = np.nan
    at_bound: bool = False
    converged: bool = False
    message: str = ""
    yhat: np.ndarray | None = None
    resid: np.ndarray | None = None
    starts_total: int = 0
    starts_best: int = 0
    n_skipped: int = 0   # 因模型定义域（x≤0 或 y≤0）未参与拟合的点数

    @property
    def hit_rate(self) -> float:
        """多起点中收敛到全局最优（相对 1e-6 内）的比例。

        接近 1 说明最优解稳健；明显小于 1 说明目标函数有多个局部极小，
        该组参数不宜单独引用。
        """
        if not self.starts_total:
            return np.nan
        return self.starts_best / self.starts_total

    def row(self) -> dict:
        d = {
            "model": self.key,
            "model_label": self.label,
            "n": self.n,
            "p": self.p,
            "SSE": self.ssr,
            "R2": self.r2,
            "adj_R2": self.adj_r2,
            "RMSE": self.rmse,
            "chi2": self.chi2,
            "ARE_pct": self.are,
            "MPSD_pct": self.mpsd,
            "AIC": self.aic,
            "AICc": self.aicc,
            "max_param_corr": self.max_corr,
            "at_bound": self.at_bound,
            "converged": self.converged,
            "start_hit_rate": self.hit_rate,
            "n_domain_skipped": self.n_skipped,
        }
        for k, v in self.params.items():
            d[f"par_{k}"] = v
            d[f"par_{k}_SE"] = self.se.get(k, np.nan)
            d[f"par_{k}_CI95_lo"] = self.ci_lo.get(k, np.nan)
            d[f"par_{k}_CI95_hi"] = self.ci_hi.get(k, np.nan)
        return d


def _metrics(y, yhat, p) -> dict:
    n = len(y)
    resid = y - yhat
    ssr = float(np.sum(resid ** 2))
    sst = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - ssr / sst if sst > 0 else np.nan
    dof = n - p
    adj = 1.0 - (1.0 - r2) * (n - 1) / dof if (dof > 0 and np.isfinite(r2)) else np.nan
    rmse = float(np.sqrt(ssr / dof)) if dof > 0 else np.nan

    pos = yhat > 0
    chi2 = float(np.sum(resid[pos] ** 2 / yhat[pos])) if pos.any() else np.nan
    with np.errstate(divide="ignore", invalid="ignore"):
        rel = np.abs(resid / y)
    are = float(np.nanmean(rel) * 100) if np.isfinite(rel).any() else np.nan
    mpsd = float(100 * np.sqrt(np.nansum((resid / y) ** 2) / dof)) if dof > 0 else np.nan

    if ssr > 0 and n > 0:
        aic = n * np.log(ssr / n) + 2 * p
        if n - p - 1 > 0:
            aicc = aic + 2 * p * (p + 1) / (n - p - 1)
        else:
            aicc = np.inf
    else:
        aic = aicc = -1e12  # 完美拟合

    return dict(ssr=ssr, r2=r2, adj_r2=adj, rmse=rmse, chi2=chi2,
                are=are, mpsd=mpsd, aic=aic, aicc=aicc)


def fit_model(model: Model, x, y, n_starts: int = 40, seed: int = 0,
              weights=None) -> FitResult | None:
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    # 吸附模型的定义域是 Ce>0、qe>0：负值点无法进入函数本身（幂函数/对数会出
    # nan），这里只能跳过。跳过的点数如实回报，由报告写明是哪几行、为什么。
    ok = np.isfinite(x) & np.isfinite(y) & (x > 0) & (y > 0)
    n_skipped = int(x.size - int(np.sum(ok)))
    if weights is not None:
        weights = np.asarray(weights, float)[ok]
    x, y = x[ok], y[ok]
    n = len(x)
    if n < model.nparams + 2:
        return None

    lo, hi = model.bounds(x, y)
    lo = np.asarray(lo, float)
    hi = np.asarray(hi, float)
    lo = np.where(np.isfinite(lo) & (lo > 0), lo, 1e-12)
    hi = np.where(np.isfinite(hi) & (hi > lo), hi, lo * 1e6)
    hi = np.maximum(hi, lo * 1.0001)

    guess = np.clip(np.asarray(model.guess(x, y), float), lo, hi)
    rng = np.random.default_rng(seed)
    starts = [guess, np.sqrt(lo * hi)]
    while len(starts) < n_starts:
        starts.append(10 ** rng.uniform(np.log10(lo), np.log10(hi)))

    def residual(p):
        with np.errstate(all="ignore"):
            yhat = model.func(x, p)
        r = yhat - y
        if weights is not None:
            r = r * weights
        return np.where(np.isfinite(r), r, 1e6)

    best = None
    costs: list[float] = []
    for p0 in starts:
        try:
            # max_nfev 是防呆而非精度开关：个别退化初值会让 TRF 在最优解附近
            # 以极小步长空转（实测 14400 次迭代仍回到同一点）。4000 次已足够
            # 收敛到与 20000 次完全相同的 SSR（56 组模型逐一比对，Δ=0.000%）。
            res = least_squares(residual, p0, bounds=(lo, hi), method="trf",
                                x_scale="jac", max_nfev=4000,
                                ftol=1e-12, xtol=1e-12, gtol=1e-12)
        except Exception:
            continue
        if not np.all(np.isfinite(res.x)):
            continue
        costs.append(float(res.cost))
        if best is None or res.cost < best.cost:
            best = res

    if best is None:
        return FitResult(model.key, model.label, {}, n=n, p=model.nparams,
                         converged=False, message="所有初值均失败")

    p = np.asarray(best.x, float)
    yhat = model.func(x, p)
    ref = float(best.cost)
    n_best = sum(1 for c in costs if c <= ref + max(abs(ref) * 1e-6, 1e-12))
    m = _metrics(y, yhat, model.nparams)

    se, ci_lo, ci_hi, max_corr = {}, {}, {}, np.nan
    dof = n - model.nparams
    tcrit = stats.t.ppf(0.975, dof) if dof > 0 else np.nan
    try:
        J = np.asarray(best.jac, float)
        cov = np.linalg.pinv(J.T @ J) * (2.0 * best.cost / max(dof, 1))
        sd = np.sqrt(np.maximum(np.diag(cov), 0.0))
        if dof > 0 and np.all(sd > 0):
            corr = cov / np.outer(sd, sd)
            np.fill_diagonal(corr, 0.0)
            max_corr = float(np.nanmax(np.abs(corr))) if corr.size else np.nan
        for name, v, s in zip(model.names, p, sd):
            se[name] = float(s)
            ci_lo[name] = float(v - tcrit * s) if dof > 0 else np.nan
            ci_hi[name] = float(v + tcrit * s) if dof > 0 else np.nan
    except Exception:
        pass

    # 参数在正数域内跨数量级，用对数距离判断是否贴边
    tol = 1e-4
    with np.errstate(divide="ignore", invalid="ignore"):
        near_lo = np.log10(p / lo) < tol
        near_hi = np.log10(hi / p) < tol
    at_bound = bool(np.any(near_lo) or np.any(near_hi))

    return FitResult(
        key=model.key,
        label=model.label,
        params={k: float(v) for k, v in zip(model.names, p)},
        se=se, ci_lo=ci_lo, ci_hi=ci_hi,
        n=n, p=model.nparams,
        max_corr=max_corr, at_bound=at_bound,
        converged=bool(best.success) and np.all(np.isfinite(p)),
        message=str(best.message),
        starts_total=len(costs), starts_best=n_best, n_skipped=n_skipped,
        yhat=yhat, resid=y - yhat, **m,
    )


def fit_many(models: dict[str, Model], x, y, n_starts: int = 40, seed: int = 0):
    results = []
    for i, model in enumerate(models.values()):
        r = fit_model(model, x, y, n_starts=n_starts, seed=seed + i)
        if r is not None:
            results.append(r)
    return results


def rank(results: list[FitResult]) -> list[FitResult]:
    """按 AICc 排序；AICc 相同时 RMSE 小者优先。"""
    return sorted(results, key=lambda r: (np.inf if not np.isfinite(r.aicc) else r.aicc,
                                          np.inf if not np.isfinite(r.rmse) else r.rmse))


def best_result(results: list[FitResult]) -> FitResult | None:
    if not results:
        return None
    good = [r for r in results if r.converged and np.isfinite(r.aicc)]
    return rank(good)[0] if good else None
