"""生成 MATLAB 全模型校验脚本。

只依赖 base MATLAB（``fminsearch``，无工具箱要求），把本次分析用到的每一组数据、
每一个模型（7 个等温线 + 5 个动力学）都重新拟合一遍，并逐模型与 Python 的 SSE
对比。用途是交叉验证：两条独立实现的优化路径若得到同一最优解，参数才可信。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np

from .models import ISOTHERM_MODELS, KINETIC_MODELS

# MATLAB 端的模型定义：(显示名, 参数个数, 函数名, 参数名 cellstr)
_ISO_ORDER = ["langmuir", "freundlich", "temkin", "dr", "sips", "toth", "rp"]
_KIN_ORDER = ["pfo", "pso", "elovich", "avrami", "bangham"]


def _mat(arr, per_line: int = 6, fmt: str = "%.10g") -> str:
    vals = [fmt % float(v) for v in np.asarray(arr, float)]
    lines = [" ".join(vals[i:i + per_line]) for i in range(0, len(vals), per_line)]
    return " ...\n        ".join(lines)


def _p0_matrix(curve: dict, keys: list[str], lib: dict, x, y) -> str:
    """起点矩阵：第 1 行是 Python 的最优参数，其余模型缺失时退回模型自带初值。

    MATLAB 的第 1 个起点直接用 Python 解，保证它不会比 Python 差；
    另外 19 个起点做对数扰动，若 MATLAB 找到更低的 SSE，说明 Python 掉进了局部极小。
    """
    rows = []
    width = max(lib[k].nparams for k in keys)
    for k in keys:
        model = lib[k]
        res = next((r for r in curve.get("all", []) if r.key == k), None)
        if res is not None and res.params:
            guess = np.array([res.params[n] for n in model.names], float)
        else:
            guess = np.asarray(model.guess(x, y), float)
        guess = np.where(np.isfinite(guess) & (guess > 0), guess, 1.0)
        row = list(guess) + [np.nan] * (width - len(guess))
        rows.append(" ".join("%.10g" % v for v in row))
    return "[" + "; ".join(rows) + "]"


_SUB = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")


def _ascii_name(text: str) -> str:
    """MATLAB 端尽量用 ASCII 标签：下标转普通数字，避免老版本编码问题。"""
    return str(text).translate(_SUB)


def _group_block(name: str, curves: dict, lib: dict, keys: list[str],
                 xcol: str, ycol: str) -> str:
    from . import names as N

    out = []
    for i, ((mineral, bg), c) in enumerate(curves.items(), start=1):
        d = c["data"]
        x = np.asarray(d[xcol], float)
        y = np.asarray(d[ycol], float)
        sse = []
        for k in keys:
            res = next((r for r in c.get("all", []) if r.key == k), None)
            sse.append(float(res.ssr) if res is not None and np.isfinite(res.ssr) else np.nan)
        try:
            tag = f"{N.mineral(mineral)} | {N.background(bg)}"
        except Exception:
            tag = f"{mineral} | {bg}"
        tag = _ascii_name(tag).replace("'", "''")
        out += [
            f"{name}({i}).tag = '{tag}';",
            f"{name}({i}).x = [{_mat(x)}];",
            f"{name}({i}).y = [{_mat(y)}];",
            f"{name}({i}).pySSE = [{_mat(sse, per_line=4)}];",
            f"{name}({i}).p0 = {_p0_matrix(c, keys, lib, x, y)};",
            "",
        ]
    return "\n".join(out)


_HEADER = r"""%% ============================================================
%  吸附数据：全部模型独立复核（自动生成，请勿手改）
%  由 adsorp 于 {stamp} 生成
%  数据源：{source}
%
%  这个脚本做什么
%    1. 内含本次拟合用的原始数据点（每组一段，与 Python 完全一致）。
%    2. 用 fminsearch（Nelder-Mead，base MATLAB，无需任何工具箱）
%       重新拟合 7 个等温线模型与 5 个动力学模型：
%       第 1 个起点取 Python 的最优参数，其余 {nstart_minus1} 个为其对数扰动。
%    3. 打印每个模型的参数、SSE、R²、AICc，并与 Python 结果逐模型对比。
%       若 MATLAB 找到更低的 SSE，说明 Python 那一组掉进了局部极小，需复核。
%
%  怎么用
%    把本文件放在任意目录，在 MATLAB 里  >> matlab_verify
%    （R2016b 及以上；脚本内定义了局部函数，更老的版本会报错）
%    文件为 UTF-8；R2019b 及更早版本若注释显示乱码，只影响阅读，不影响运行。
%
%  判读
%    relDiff < 1e-6 %  → 两条路径收敛到同一最优解，Python 结果可信
%    relDiff 明显偏大   → 该模型存在多个局部极小，需看「多起点」结论，
%                        或该组点数不足以约束这个模型
%% ============================================================
clear; clc; close all;
nstart = {nstart};
fprintf('MATLAB 全模型复核：%s\n', datestr(now));
fprintf('每组 {nstart} 个起点，fminsearch（Nelder-Mead），无工具箱依赖\n\n');

%% ---------------- 等温线数据 ----------------
% x = Ce (mg/L), y = qe ({iso_unit})
{iso_data}
ISO_MODELS = {{
%   显示名                 参数个数  函数          参数名
    'Langmuir',            2,  @m_langmuir,   {{'qmax','K_L'}};
    'Freundlich',          2,  @m_freundlich, {{'K_F','n'}};
    'Temkin',              2,  @m_temkin,     {{'B','A_T'}};
    'Dubinin-Radushkevich',2,  @m_dr,         {{'qmax','K_DR'}};
    'Sips',                3,  @m_sips,       {{'qmax','K_S','m'}};
    'Toth',                3,  @m_toth,       {{'qmax','K_T','t'}};
    'Redlich-Peterson',    3,  @m_rp,         {{'K_R','a_R','g'}};
}};

%% ---------------- 动力学数据 ----------------
% x = t (h), y = qt ({kin_unit})
{kin_data}
KIN_MODELS = {{
    'PFO',      2,  @m_pfo,       {{'qe','k1'}};
    'PSO',      2,  @m_pso,       {{'qe','k2'}};
    'Elovich',  2,  @m_elovich,   {{'alpha','beta'}};
    'Avrami',   3,  @m_avrami,    {{'qe','k_av','n'}};
    'Bangham',  2,  @m_bangham,   {{'k_B','alpha'}};
}};

%% ================= 拟合与对比 =================
{iso_call}{kin_call}
%% ---------------- 汇总 ----------------
fprintf('\n================ 汇总 ================\n');
{iso_sum}{kin_sum}fprintf('\n注意：SSE 相同不等于模型可解释。参数触界或多解的组，请回到 Python 报告的\n');
fprintf('「拟合可靠性与模型选择」一节，用 AICc 与参数相关系数判定。\n');
{tail}"""


_BODY = r"""
%% ---------------- 局部函数 ----------------
function report = run_block(label, DATA, MODELS, nstart)
%RUN_BLOCK 对一组数据拟合全部模型并打印对比表
report.ok = [];
report.rel = [];
fprintf('========== %s ==========\n', label);
for g = 1:numel(DATA)
    x = DATA(g).x(:); y = DATA(g).y(:);
    fprintf('\n[%s]  n = %d\n', DATA(g).tag, numel(x));
    fprintf('%-22s %-42s %10s %10s %10s %8s %8s\n', ...
            '模型', '参数', 'SSE', 'SSE_py', 'rel/%', 'R2', 'AICc');
    for m = 1:size(MODELS, 1)
        name = MODELS{m, 1}; np = MODELS{m, 2};
        fun = MODELS{m, 3}; pnames = MODELS{m, 4};
        p0 = DATA(g).p0(m, :);
        p0 = p0(isfinite(p0));
        [p, sse] = fit_nm(fun, x, y, p0, nstart);
        yh = fun(x, p);
        [r2, aicc] = metrics(y, yh, np);
        py = DATA(g).pySSE(m);
        if isfinite(py) && py > 0
            rel = abs(sse - py) / py * 100;
        else
            rel = NaN;
        end
        report.ok(end + 1) = isfinite(rel) && rel < 1e-6;
        report.rel(end + 1) = rel;
        fprintf('%-22s %-42s %10.4g %10.4g %10.2g %8.4f %8.2f\n', ...
                name, param_text(p, pnames), sse, py, rel, r2, aicc);
    end
end
end

function s = param_text(p, names)
parts = cell(1, numel(p));
for i = 1:numel(p)
    parts{i} = sprintf('%s=%.4g', names{i}, p(i));
end
s = strjoin(parts, ' ');
end

function [p, sse] = fit_nm(fun, x, y, p0, nstart)
%FIT_NM 对数参数化的多起点 Nelder-Mead，保证参数恒正
best = inf; p = p0(:);
opts = optimset('MaxFunEvals', 40000, 'MaxIter', 40000, ...
                'TolX', 1e-10, 'TolFun', 1e-12, 'Display', 'off');
for k = 1:nstart
    if k == 1
        t0 = log(p0(:));
    else
        t0 = log(p0(:)) + 1.0 * randn(numel(p0), 1);
    end
    [t, fv] = fminsearch(@(t) sse_of(fun, x, y, t), t0, opts);
    if fv < best
        best = fv; p = exp(max(min(t, 30), -30));
    end
end
sse = best;
end

function v = sse_of(fun, x, y, t)
p = exp(max(min(t, 30), -30));
yh = fun(x, p);
r = yh - y;
r(~isfinite(r)) = 1e6;
v = sum(r.^2);
end

function [r2, aicc] = metrics(y, yh, k)
n = numel(y);
sse = sum((y(:) - yh(:)).^2);
sst = sum((y(:) - mean(y(:))).^2);
r2 = 1 - sse / sst;
aic = n * log(sse / n) + 2 * k;
if n - k - 1 > 0
    aicc = aic + 2 * k * (k + 1) / (n - k - 1);
else
    aicc = NaN;
end
end

%% ---------------- 等温线模型 ----------------
function y = m_langmuir(x, p)
y = p(1) * p(2) * x ./ (1 + p(2) * x);
end

function y = m_freundlich(x, p)
y = p(1) * x.^(1 / p(2));
end

function y = m_temkin(x, p)
y = p(1) * log(p(2) * x);
end

function y = m_dr(x, p)
% Dubinin-Radushkevich：Ce(mg/L) -> mol/L -> 吸附势 eps (kJ/mol)
R = 8.314462618; T = 298.15; M = 121.76;
cm = x / 1000 / M;
eps = R * T * log(1 + 1 ./ cm) / 1000;
y = p(1) * exp(-p(2) * eps.^2);
end

function y = m_sips(x, p)
z = (p(2) * x).^p(3);
y = p(1) * z ./ (1 + z);
end

function y = m_toth(x, p)
z = p(2) * x;
y = p(1) * z ./ (1 + z.^p(3)).^(1 / p(3));
end

function y = m_rp(x, p)
y = p(1) * x ./ (1 + p(2) * x.^p(3));
end

%% ---------------- 动力学模型 ----------------
function y = m_pfo(x, p)
y = p(1) * (1 - exp(-p(2) * x));
end

function y = m_pso(x, p)
y = p(2) * p(1)^2 * x ./ (1 + p(2) * p(1) * x);
end

function y = m_elovich(x, p)
y = log(1 + p(1) * p(2) * x) / p(2);
end

function y = m_avrami(x, p)
y = p(1) * (1 - exp(-(p(2) * x).^p(3)));
end

function y = m_bangham(x, p)
y = p(1) * x.^p(2);
end
"""


def _tail_note(has_iso: bool, has_kin: bool) -> str:
    lines = ["\n%% ---------------- 附：模型方程 ----------------"]
    if has_iso:
        lines.append("%  等温线（x = Ce，mg/L）")
        for k in _ISO_ORDER:
            m = ISOTHERM_MODELS[k]
            lines.append(f"%    {m.label:<22s} {m.formula}")
        lines.append("%    D-R 的 E = 1/sqrt(2*K_DR)（kJ/mol），与本项目 report.py 同式")
    if has_kin:
        lines.append("%  动力学（x = t，h）")
        for k in _KIN_ORDER:
            m = KINETIC_MODELS[k]
            lines.append(f"%    {m.label:<22s} {m.formula}")
    return "\n".join(lines) + "\n"


def write_verify_script(path: Path, curves_iso: dict, curves_kin: dict,
                        source: str = "", nstart: int = 20) -> Path | None:
    """写一份可直接在 MATLAB 里运行的复核脚本。"""
    curves_iso = curves_iso or {}
    curves_kin = curves_kin or {}
    if not curves_iso and not curves_kin:
        return None

    iso_unit = next((c.get("unit") for c in curves_iso.values()
                     if c.get("unit")), "mg/g")
    kin_unit = next((c.get("unit") for c in curves_kin.values()
                     if c.get("unit")), "mg/g")

    iso_data = _group_block("ISO", curves_iso, ISOTHERM_MODELS, _ISO_ORDER,
                            "Ce_ppm", "qe") if curves_iso else "% （本次无等温线数据）\n"
    kin_data = _group_block("KIN", curves_kin, KINETIC_MODELS, _KIN_ORDER,
                            "time_h", "qt") if curves_kin else "% （本次无动力学数据）\n"

    text = _HEADER.format(
        stamp=f"{datetime.now():%Y-%m-%d %H:%M}", source=source or "未记录",
        nstart=nstart, nstart_minus1=max(nstart - 1, 1),
        iso_unit=iso_unit, kin_unit=kin_unit,
        iso_data=iso_data, kin_data=kin_data,
        iso_call=("iso_report = run_block('等温线', ISO, ISO_MODELS, nstart);\n"
                  if curves_iso else "% 本次无等温线数据\n"),
        kin_call=("kin_report = run_block('动力学', KIN, KIN_MODELS, nstart);\n"
                  if curves_kin else "% 本次无动力学数据\n"),
        iso_sum=("fprintf('等温线：%d/%d 个模型与 Python 的 SSE 相对差 < 1e-6%%"
                 "（最大差 %.3g%%）\\n', ...\n"
                 "    sum([iso_report.ok]), numel(iso_report.ok), max([iso_report.rel]));\n"
                 if curves_iso else ""),
        kin_sum=("fprintf('动力学：%d/%d 个模型与 Python 的 SSE 相对差 < 1e-6%%"
                 "（最大差 %.3g%%）\\n', ...\n"
                 "    sum([kin_report.ok]), numel(kin_report.ok), max([kin_report.rel]));\n"
                 if curves_kin else ""),
        tail=_tail_note(bool(curves_iso), bool(curves_kin)),
    ) + _BODY
    # % 在 f-string 里已被转义；这里把 MATLAB 的注释符还原（避免 %% 出现在输出）
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path
