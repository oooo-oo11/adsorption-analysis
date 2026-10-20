%% ============================================================
%  吸附数据：全部模型独立复核（自动生成，请勿手改）
%  由 adsorp 于 2026-10-20 01:18 生成
%  数据源：tod-去除异常点.xlsx
%
%  这个脚本做什么
%    1. 内含本次拟合用的原始数据点（每组一段，与 Python 完全一致）。
%    2. 用 fminsearch（Nelder-Mead，base MATLAB，无需任何工具箱）
%       重新拟合 7 个等温线模型与 5 个动力学模型：
%       第 1 个起点取 Python 的最优参数，其余 19 个为其对数扰动。
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
nstart = 20;
fprintf('MATLAB 全模型复核：%s\n', datestr(now));
fprintf('每组 20 个起点，fminsearch（Nelder-Mead），无工具箱依赖\n\n');

%% ---------------- 等温线数据 ----------------
% x = Ce (mg/L), y = qe (mg/g)
ISO(1).tag = 'Todorokite | 0.01 M NaNO3';
ISO(1).x = [0.0003240981501 0.01733220876 0.1198800387 0.7427614075 2.763514984 6.279609954 ...
        15.9316117 44.66794361];
ISO(1).y = [0.04967590185 0.4826677912 0.8801199613 2.257238592 3.236485016 3.720390046 ...
        4.068388299 5.332056394];
ISO(1).pySSE = [1.19043872 0.7697968118 2.773023475 0.3663614206 ...
        0.275172966 0.2363421182 0.1942911169];
ISO(1).p0 = [4.709478271 1.032094355 nan; 2.185737374 4.119022596 nan; 0.4545904556 465.3321272 nan; 10.95450256 0.001873014726 nan; 6.832176645 0.2352401938 0.4679994596; 8.934536479 25.6137113 0.2638959884; 18.18853223 6.499086547 0.8350385884];

ISO(2).tag = 'Todorokite | ASW';
ISO(2).x = [0.1195105424 0.3032907102 1.475369719 3.928717761 7.218099546 17.17563892];
ISO(2).y = [0.3804894576 0.6967092898 1.524630281 2.071282239 2.781900454 2.824361085];
ISO(2).pySSE = [0.1252116339 0.3781733102 0.1401599372 0.2552903343 ...
        0.08320062812 0.08951725619 0.1039805585];
ISO(2).p0 = [3.070075598 0.7305197567 nan; 1.269600397 3.144930465 nan; 0.535304853 14.25571565 nan; 10.12100659 0.002452243252 nan; 3.437497269 0.534234399 0.7801098985; 3.596372432 1.160681451 0.6473032612; 3.113877513 1.316165478 0.90625717];

ISO_MODELS = {
%   显示名                 参数个数  函数          参数名
    'Langmuir',            2,  @m_langmuir,   {'qmax','K_L'};
    'Freundlich',          2,  @m_freundlich, {'K_F','n'};
    'Temkin',              2,  @m_temkin,     {'B','A_T'};
    'Dubinin-Radushkevich',2,  @m_dr,         {'qmax','K_DR'};
    'Sips',                3,  @m_sips,       {'qmax','K_S','m'};
    'Toth',                3,  @m_toth,       {'qmax','K_T','t'};
    'Redlich-Peterson',    3,  @m_rp,         {'K_R','a_R','g'};
};

%% ---------------- 动力学数据 ----------------
% x = t (h), y = qt (mg/g)
KIN(1).tag = 'Todorokite | 0.01 M NaNO3';
KIN(1).x = [0.083 0.16 0.5 1 2 5 ...
        12 24 48 96 120 168 ...
        216 288];
KIN(1).y = [2.100065385 2.2336576 2.280036185 2.931207754 2.727721052 2.955835894 ...
        3.004350683 3.101521497 3.140520467 3.846136224 3.844965039 4.025310032 ...
        5.496654228 5.567076732];
KIN(1).pySSE = [11.95823782 9.881980193 4.045011341 3.297743442 ...
        3.136367122];
KIN(1).p0 = [3.61031528 6.403966648 nan; 3.786260363 1.779917259 nan; 775.8053991 2.979397093 nan; 13.55199482 5.555555556e-06 0.1325528976; 2.462331377 0.1155276778 nan];

KIN(2).tag = 'Todorokite | ASW';
KIN(2).x = [0.083 0.16 0.5 2 5 24 ...
        48 96 120 168 216 264];
KIN(2).y = [2.309285618 2.727811592 2.256913455 2.368806824 2.355393341 3.388664881 ...
        2.888285964 2.366070969 2.542349724 2.564997729 2.562377997 2.638772762];
KIN(2).pySSE = [1.024030177 1.610172511 4.789974647 1.703118631 ...
        1.842607318];
KIN(2).p0 = [2.605276775 27.71927371 nan; 2.729023507 8.197263157 nan; 1000 4.485382516 nan; 3.385080762 2.777777778 0.1; 2.227456967 0.05 nan];

KIN_MODELS = {
    'PFO',      2,  @m_pfo,       {'qe','k1'};
    'PSO',      2,  @m_pso,       {'qe','k2'};
    'Elovich',  2,  @m_elovich,   {'alpha','beta'};
    'Avrami',   3,  @m_avrami,    {'qe','k_av','n'};
    'Bangham',  2,  @m_bangham,   {'k_B','alpha'};
};

%% ================= 拟合与对比 =================
iso_report = run_block('等温线', ISO, ISO_MODELS, nstart);
kin_report = run_block('动力学', KIN, KIN_MODELS, nstart);

%% ---------------- 汇总 ----------------
fprintf('\n================ 汇总 ================\n');
fprintf('等温线：%d/%d 个模型与 Python 的 SSE 相对差 < 1e-6%%（最大差 %.3g%%）\n', ...
    sum([iso_report.ok]), numel(iso_report.ok), max([iso_report.rel]));
fprintf('动力学：%d/%d 个模型与 Python 的 SSE 相对差 < 1e-6%%（最大差 %.3g%%）\n', ...
    sum([kin_report.ok]), numel(kin_report.ok), max([kin_report.rel]));
fprintf('\n注意：SSE 相同不等于模型可解释。参数触界或多解的组，请回到 Python 报告的\n');
fprintf('「拟合可靠性与模型选择」一节，用 AICc 与参数相关系数判定。\n');

%% ---------------- 附：模型方程 ----------------
%  等温线（x = Ce，mg/L）
%    Langmuir               qe = qmax·K·Ce/(1+K·Ce)
%    Freundlich             qe = K_F·Ce^(1/n)
%    Temkin                 qe = B·ln(A_T·Ce)
%    Dubinin-Radushkevich   qe = qmax·exp(-K_DR·ε²), ε=RT·ln(1+1/Ce)
%    Sips                   qe = qmax(K·Ce)^m/[1+(K·Ce)^m]
%    Toth                   qe = qmax·K·Ce/[1+(K·Ce)^t]^(1/t)
%    Redlich-Peterson       qe = K_R·Ce/(1+a_R·Ce^g)
%    D-R 的 E = 1/sqrt(2*K_DR)（kJ/mol），与本项目 report.py 同式
%  动力学（x = t，h）
%    准一级 (PFO)              qt = qe[1-exp(-k1·t)]
%    准二级 (PSO)              qt = k2·qe²·t/(1+k2·qe·t)
%    Elovich                qt = (1/β)·ln(1+αβt)
%    Avrami                 qt = qe[1-exp(-(k·t)^n)]
%    Bangham                qt = k_B·t^α

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
