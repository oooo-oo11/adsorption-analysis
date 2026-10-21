"""吸附等温线 / 动力学模型库。

所有模型均为正参数，拟合时在参数上下界内做多起点有界最小二乘。
等温线浓度单位统一为 mg/L（相对容量模式下 qe 单位同 mg/L）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

import numpy as np

R_GAS = 8.314462618  # J/(mol K)
M_SB = 121.760       # g/mol


@dataclass
class Model:
    key: str
    label: str
    names: Sequence[str]
    unit_hint: Sequence[str]
    func: Callable[[np.ndarray, np.ndarray], np.ndarray]
    guess: Callable[[np.ndarray, np.ndarray], np.ndarray]
    bounds: Callable[[np.ndarray, np.ndarray], tuple[np.ndarray, np.ndarray]]
    formula: str = ""
    kind: str = "isotherm"
    notes: str = ""

    @property
    def nparams(self) -> int:
        return len(self.names)


def _pos_bounds(lo, hi):
    return np.asarray(lo, float), np.asarray(hi, float)


# --------------------------------------------------------------------------
# 等温线：x = Ce (mg/L), y = qe
# --------------------------------------------------------------------------

def _langmuir(x, p):
    qm, K = p
    return qm * K * x / (1.0 + K * x)


def _langmuir_guess(x, y):
    return np.array([max(y.max() * 1.2, 1e-9), 1.0 / max(np.median(x), 1e-9)])


def _langmuir_bounds(x, y):
    ymax = max(y.max(), 1e-12)
    xm = max(np.median(x), 1e-12)
    return _pos_bounds([0.05 * ymax, 1e-6 / xm], [20 * ymax, 1e4 / xm])


def _freundlich(x, p):
    Kf, n = p
    return Kf * np.power(x, 1.0 / n)


def _freundlich_guess(x, y):
    n = 2.0
    return np.array([y.max() / max(x.max() ** (1 / n), 1e-12), n])


def _freundlich_bounds(x, y):
    ymax = max(y.max(), 1e-12)
    xmax = max(x.max(), 1e-12)
    return _pos_bounds([1e-6 * ymax / xmax, 1.05], [1e3 * ymax, 15.0])


def _temkin(x, p):
    B, A = p
    return B * np.log(np.maximum(A * x, 1e-300))


def _temkin_guess(x, y):
    return np.array([max(y.max() / max(np.log(x.max() / x.min()), 1.0), 1e-6),
                     1.0 / max(np.median(x), 1e-9)])


def _temkin_bounds(x, y):
    ymax = max(y.max(), 1e-12)
    xm = max(np.median(x), 1e-12)
    return _pos_bounds([1e-4 * ymax, 1e-6 / xm], [50 * ymax, 1e4 / xm])


def _dr(x, p, T=298.15):
    """Dubinin-Radushkevich，x 为 mg/L，内部换算为 mol/L 计算吸附势 ε(kJ/mol)。"""
    qm, Kdr = p
    cm = np.maximum(x, 1e-30) / 1000.0 / M_SB
    eps = R_GAS * T * np.log1p(1.0 / cm) / 1000.0  # kJ/mol
    return qm * np.exp(-Kdr * eps ** 2)


def _dr_guess(x, y):
    return np.array([max(y.max() * 1.3, 1e-9), 1e-4])


def _dr_bounds(x, y):
    ymax = max(y.max(), 1e-12)
    return _pos_bounds([0.1 * ymax, 1e-9], [20 * ymax, 1.0])


def _sips(x, p):
    qm, K, m = p
    z = np.power(np.maximum(K * x, 1e-300), m)
    return qm * z / (1.0 + z)


def _sips_guess(x, y):
    return np.array([max(y.max() * 1.2, 1e-9), 1.0 / max(np.median(x), 1e-9), 0.8])


def _sips_bounds(x, y):
    ymax = max(y.max(), 1e-12)
    xm = max(np.median(x), 1e-12)
    return _pos_bounds([0.05 * ymax, 1e-6 / xm, 0.1], [20 * ymax, 1e4 / xm, 5.0])


def _toth(x, p):
    qm, K, t = p
    z = K * x
    return qm * z / np.power(1.0 + np.power(z, t), 1.0 / t)


def _toth_guess(x, y):
    return np.array([max(y.max() * 1.2, 1e-9), 1.0 / max(np.median(x), 1e-9), 0.8])


def _toth_bounds(x, y):
    ymax = max(y.max(), 1e-12)
    xm = max(np.median(x), 1e-12)
    return _pos_bounds([0.05 * ymax, 1e-6 / xm, 0.1], [20 * ymax, 1e4 / xm, 5.0])


def _rp(x, p):
    Kr, a, g = p
    return Kr * x / (1.0 + a * np.power(np.maximum(x, 1e-300), g))


def _rp_guess(x, y):
    xm = max(np.median(x), 1e-9)
    return np.array([max(y.max() / xm, 1e-9), 1.0 / xm, 0.9])


def _rp_bounds(x, y):
    ymax = max(y.max(), 1e-12)
    xm = max(np.median(x), 1e-12)
    return _pos_bounds([1e-6 * ymax / xm, 1e-6 / xm, 0.1], [1e3 * ymax / xm, 1e4 / xm, 1.0])


ISOTHERM_MODELS: dict[str, Model] = {
    m.key: m
    for m in [
        Model("langmuir", "Langmuir", ["qmax", "K_L"], ["mg/g 或 mg/L", "L/mg"],
              _langmuir, _langmuir_guess, _langmuir_bounds,
              "qe = qmax·K·Ce/(1+K·Ce)", "isotherm",
              "单层、均一位点吸附；qmax 为饱和容量，K 为亲和常数。"),
        Model("freundlich", "Freundlich", ["K_F", "n"], ["(mg/g)(L/mg)^(1/n)", "—"],
              _freundlich, _freundlich_guess, _freundlich_bounds,
              "qe = K_F·Ce^(1/n)", "isotherm",
              "经验式，适合异质表面；n>1 表示有利吸附。"),
        Model("temkin", "Temkin", ["B", "A_T"], ["mg/g", "L/mg"],
              _temkin, _temkin_guess, _temkin_bounds,
              "qe = B·ln(A_T·Ce)", "isotherm",
              "考虑吸附质-吸附剂相互作用；B=RT/b。"),
        Model("dr", "Dubinin-Radushkevich", ["qmax", "K_DR"], ["mg/g 或 mg/L", "mol²/kJ²"],
              _dr, _dr_guess, _dr_bounds,
              "qe = qmax·exp(-K_DR·ε²), ε=RT·ln(1+1/Ce)", "isotherm",
              "用于判别物理/化学吸附，E=1/√(2K_DR) (kJ/mol)。"),
        Model("sips", "Sips", ["qmax", "K_S", "m"], ["mg/g 或 mg/L", "L/mg", "—"],
              _sips, _sips_guess, _sips_bounds,
              "qe = qmax(K·Ce)^m/[1+(K·Ce)^m]", "isotherm",
              "Langmuir-Freundlich 三参数式；m→1 退化为 Langmuir。"),
        Model("toth", "Toth", ["qmax", "K_T", "t"], ["mg/g 或 mg/L", "L/mg", "—"],
              _toth, _toth_guess, _toth_bounds,
              "qe = qmax·K·Ce/[1+(K·Ce)^t]^(1/t)", "isotherm",
              "三参数异质表面模型；t→1 退化为 Langmuir。"),
        Model("rp", "Redlich-Peterson", ["K_R", "a_R", "g"], ["L/g", "L/mg", "—"],
              _rp, _rp_guess, _rp_bounds,
              "qe = K_R·Ce/(1+a_R·Ce^g)", "isotherm",
              "三参数混合模型；g→1 接近 Langmuir，g→0 接近 Henry。"),
    ]
}


# --------------------------------------------------------------------------
# 动力学：x = t (h), y = qt（或相对吸附分数 U）
# --------------------------------------------------------------------------

def _pfo(x, p):
    qe, k1 = p
    return qe * (1.0 - np.exp(-k1 * x))


def _pfo_guess(x, y):
    tm = max(np.median(x[x > 0]) if np.any(x > 0) else 1.0, 1e-6)
    return np.array([max(y.max() * 1.05, 1e-9), 1.0 / tm])


def _pfo_bounds(x, y):
    ymax = max(y.max(), 1e-12)
    tm = max(np.median(x[x > 0]) if np.any(x > 0) else 1.0, 1e-6)
    return _pos_bounds([0.2 * ymax, 1e-4 / tm], [5 * ymax, 1e3 / tm])


def _pso(x, p):
    qe, k2 = p
    return k2 * qe ** 2 * x / (1.0 + k2 * qe * x)


def _pso_guess(x, y):
    qe = max(y.max() * 1.05, 1e-9)
    tm = max(np.median(x[x > 0]) if np.any(x > 0) else 1.0, 1e-6)
    return np.array([qe, 1.0 / (qe * tm)])


def _pso_bounds(x, y):
    ymax = max(y.max(), 1e-12)
    tm = max(np.median(x[x > 0]) if np.any(x > 0) else 1.0, 1e-6)
    return _pos_bounds([0.2 * ymax, 1e-6 / (ymax * tm)], [5 * ymax, 1e3 / (ymax * tm)])


def _elovich(x, p):
    a, b = p
    return np.log1p(a * b * x) / b


def _elovich_guess(x, y):
    return np.array([1.0, 1.0 / max(y.max(), 1e-9)])


def _elovich_bounds(x, y):
    ymax = max(y.max(), 1e-12)
    return _pos_bounds([1e-4, 1e-6 / ymax], [1e3, 1e3 / ymax])


def _avrami(x, p):
    qe, k, n = p
    return qe * (1.0 - np.exp(-np.power(k * x, n)))


def _avrami_guess(x, y):
    tm = max(np.median(x[x > 0]) if np.any(x > 0) else 1.0, 1e-6)
    return np.array([max(y.max() * 1.05, 1e-9), 1.0 / tm, 0.7])


def _avrami_bounds(x, y):
    ymax = max(y.max(), 1e-12)
    tm = max(np.median(x[x > 0]) if np.any(x > 0) else 1.0, 1e-6)
    return _pos_bounds([0.2 * ymax, 1e-4 / tm, 0.1], [5 * ymax, 1e2 / tm, 5.0])


def _bangham(x, p):
    k, alpha = p
    return k * np.power(x, alpha)


def _bangham_guess(x, y):
    return np.array([max(y.max() / max(x.max() ** 0.5, 1e-9), 1e-9), 0.5])


def _bangham_bounds(x, y):
    ymax = max(y.max(), 1e-12)
    xmax = max(x.max(), 1e-12)
    return _pos_bounds([1e-4 * ymax / xmax, 0.05], [1e3 * ymax, 2.0])


KINETIC_MODELS: dict[str, Model] = {
    m.key: m
    for m in [
        Model("pfo", "准一级 (PFO)", ["qe", "k1"], ["mg/g 或 —", "1/h"],
              _pfo, _pfo_guess, _pfo_bounds,
              "qt = qe[1-exp(-k1·t)]", "kinetic",
              "Lagergren 准一级；物理吸附/扩散控制常用。"),
        Model("pso", "准二级 (PSO)", ["qe", "k2"], ["mg/g 或 —", "g/(mg·h)"],
              _pso, _pso_guess, _pso_bounds,
              "qt = k2·qe²·t/(1+k2·qe·t)", "kinetic",
              "Ho-McKay 准二级；化学吸附（共享电子）常用，h=k2·qe²。"),
        Model("elovich", "Elovich", ["alpha", "beta"], ["mg/(g·h)", "g/mg"],
              _elovich, _elovich_guess, _elovich_bounds,
              "qt = (1/β)·ln(1+αβt)", "kinetic",
              "描述异质表面化学吸附，不收敛到平台。"),
        Model("avrami", "Avrami", ["qe", "k_av", "n"], ["mg/g 或 —", "1/h", "—"],
              _avrami, _avrami_guess, _avrami_bounds,
              "qt = qe[1-exp(-(k·t)^n)]", "kinetic",
              "多步/成核生长动力学；n 偏离 1 表示多机制。"),
        Model("bangham", "Bangham", ["k_B", "alpha"], ["mg/(g·h^α)", "—"],
              _bangham, _bangham_guess, _bangham_bounds,
              "qt = k_B·t^α", "kinetic",
              "孔内扩散经验式；α<1 常见。"),
    ]
}


def dr_energy(kdr: float) -> float:
    """D-R 模型平均吸附自由能 E (kJ/mol)。"""
    return 1.0 / np.sqrt(2.0 * max(kdr, 1e-30))
