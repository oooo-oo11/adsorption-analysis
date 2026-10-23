%% fit_all_models.m — 用 Excel 模板重跑报告里的全部模型
% =====================================================================
%  目标：在 MATLAB R2024b 里独立复算 adsorp 报告用到的所有模型，
%        与 Python 端同一份数据、同一套公式、同一套指标口径。
%
%  依赖：只用基础 MATLAB。不需要 Optimization Toolbox、Curve Fitting
%        Toolbox 或任何第三方函数（优化器用 fminsearch / Nelder-Mead，
%        读表用 readcell，写结果用 writetable，都是内置的）。
%
%  怎么用：
%    1. 把本文件放在任意目录（建议放项目里 docs/reference/）；
%    2. 下面 CFG.data_file 留空 = 自动查找模板；也可以直接写绝对路径：
%         CFG.data_file = 'D:\我的数据\吸附数据模板.xlsx';
%    3. 按 F5（或用命令行 matlab -batch "fit_all_models"）。
%    4. 结果打印在命令行窗口，同时写到模板同目录下的 fit_results.xlsx。
%
%  自动查找顺序（找到第一个就用）：
%    <本文件目录>\..\..\templates\吸附数据模板.xlsx
%    <本文件目录>\..\templates\吸附数据模板.xlsx
%    <当前目录>\templates\吸附数据模板.xlsx
%    <当前目录>\吸附数据模板.xlsx
%
%  模板要求：与 adssorp 的 Excel 模板一致，两张表
%    Data      : exp / mineral / background / C0_ppm / Ce_ppm 等（可缺列）
%    Settings  : molar_mass_g_per_mol / temperature_K / solid:<吸附剂> 等
%  没有 Data 表的仪器原始工作簿请先用 Python 端导出模板。
% =====================================================================

clc;
fprintf('============================================================\n');
fprintf(' 吸附数据全模型拟合（MATLAB R2024b）\n');
fprintf('============================================================\n');

%% ------------------------- 1. 配置 ---------------------------------
CFG.data_file   = '';            % 留空 = 自动查找；也可写完整路径
CFG.sheet_data  = 'Data';
CFG.sheet_set   = 'Settings';
CFG.n_start     = 20;            % 每个模型的多起点个数
CFG.seed        = 42;            % 随机种子，保证每次结果一致
CFG.out_file    = '';            % 留空 = 与数据文件同目录的 fit_results.xlsx
CFG.min_pts     = 4;             % 少于这个独立点数不拟合（自由度不足）
CFG.verbose     = true;
rng(CFG.seed);                   % 固定随机数流，多起点扰动可复现

file = resolve_data_file(CFG.data_file, mfilename('fullpath'));
fprintf('数据文件：%s\n', file);

[S, C] = read_template(file, CFG);
fprintf('Settings：M = %s g/mol，T = %s K，solid 条目 %d 个\n', ...
        num2str(S.molar_mass), num2str(S.temperature), S.solids.Count);

D = build_dataset(C, S);
fprintf('有效数据：%d 行（等温 %d / 动力学 %d / 吸附边 %d）\n\n', ...
        numel(D.exp), sum(strcmp(D.exp,'isotherm')), ...
        sum(strcmp(D.exp,'kinetics')), sum(strcmp(D.exp,'edge')));

if isempty(D.exp)
    error('没有可用数据行：检查 Data 表是否有 Ce_ppm 或 conc_ppb。');
end

rows = cell(0, 11);              % 汇总结果，最后写 xlsx
best_lines = {};

%% ------------------------- 2. 等温线 -------------------------------
iso_models = isotherm_models(S);
m = strcmp(D.exp, 'isotherm');
if any(m)
    fprintf('---- 等温线（%d 个模型，x = Ce mg/L）----\n', numel(iso_models));
    [rows, best_lines] = run_isotherm(D, m, iso_models, CFG, rows, best_lines);
else
    fprintf('---- 等温线：无数据，跳过 ----\n');
end

%% ------------------------- 3. 动力学 -------------------------------
kin_models = kinetic_models();
m = strcmp(D.exp, 'kinetics');
if any(m)
    fprintf('\n---- 动力学（%d 个模型，x = t h）----\n', numel(kin_models));
    [rows, best_lines] = run_kinetics(D, m, kin_models, CFG, rows, best_lines);
    fprintf('\n---- 颗粒内扩散（qt vs t^0.5，两段折线）----\n');
    rows = run_ipd(D, m, CFG, rows);
else
    fprintf('\n---- 动力学：无数据，跳过 ----\n');
end

%% ------------------------- 4. 吸附边 -------------------------------
m = strcmp(D.exp, 'edge');
if any(m)
    fprintf('\n---- 吸附边（4 参数 logistic，x = pH）----\n');
    rows = run_edge(D, m, CFG, rows);
else
    fprintf('\n---- 吸附边：无数据，跳过 ----\n');
end

%% ------------------------- 5. 汇总输出 -----------------------------
fprintf('\n============================================================\n');
fprintf(' 各组成最优模型（按 AICc 最小）\n');
fprintf('============================================================\n');
for i = 1:numel(best_lines)
    fprintf('  %s\n', best_lines{i});
end

if ~isempty(rows)
    T = cell2table(rows, 'VariableNames', ...
        {'组','实验','模型','参数','n','SSE','R2','adjR2','RMSE','AICc','触界'});
    outfile = CFG.out_file;
    if isempty(outfile)
        [d, ~, ~] = fileparts(file);
        outfile = fullfile(d, 'fit_results.xlsx');
    end
    try
        writetable(T, outfile, 'Sheet', 'fits', 'WriteMode', 'overwritesheet');
        fprintf('\n结果已写入：%s\n', outfile);
    catch ME
        fprintf('\n写 xlsx 失败（%s），结果仍在上面的命令行输出里。\n', ME.message);
    end
end
fprintf('完成。\n');


%% =====================================================================
%%  以下为函数部分
%% =====================================================================

function file = resolve_data_file(user_path, this_file)
% 定位数据文件：先看用户给的路径，再按约定顺序自动找。
    if ~isempty(user_path)
        if exist(user_path, 'file'); file = user_path; return; end
        error('指定的文件不存在：%s', user_path);
    end
    here = fileparts(this_file);
    cand = { ...
        fullfile(here, '..', '..', 'templates', '吸附数据模板.xlsx'), ...
        fullfile(here, '..', 'templates', '吸附数据模板.xlsx'), ...
        fullfile(pwd, 'templates', '吸附数据模板.xlsx'), ...
        fullfile(pwd, '吸附数据模板.xlsx')};
    for i = 1:numel(cand)
        if exist(cand{i}, 'file'); file = cand{i}; return; end
    end
    error(['找不到数据模板。请在脚本顶部把 CFG.data_file 设为 .xlsx 的完整路径。\n' ...
           '已尝试：\n  %s'], strjoin(cand, '\n  '));
end


function [S, C] = read_template(file, CFG)
% 读 Settings 与 Data 两张表；返回设置结构体与 Data 的原始 cell 数组。
    sheets = sheetnames(file);
    if ~any(strcmpi(sheets, CFG.sheet_data))
        error(['这个工作簿没有 "%s" 表。它可能是仪器原始工作簿，' ...
               '请先在 Python 端导出模板（adsorp.bat export --out 模板.xlsx）。'], CFG.sheet_data);
    end
    C = readcell(file, 'Sheet', CFG.sheet_data);
    S = struct();
    S.molar_mass = NaN;
    S.temperature = 298.15;
    S.solids = containers.Map('KeyType', 'char', 'ValueType', 'double');
    S.default_C0 = containers.Map('KeyType', 'char', 'ValueType', 'double');
    S.default_dil = containers.Map('KeyType', 'char', 'ValueType', 'double');

    if any(strcmpi(sheets, CFG.sheet_set))
        K = readcell(file, 'Sheet', CFG.sheet_set);
        for r = 1:size(K, 1)
            if size(K, 2) < 2; continue; end
            key = strtrim(tostr(K{r, 1}));
            if isempty(key); continue; end
            val = tonum(K{r, 2});
            kl = lower(key);
            if strncmp(kl, 'solid:', 6)
                nm = strtrim(key(7:end));
                if ~isempty(nm) && ~isnan(val)
                    S.solids(nm) = val;
                end
            elseif strcmp(kl, 'molar_mass_g_per_mol')
                S.molar_mass = val;
            elseif strcmp(kl, 'temperature_k')
                if ~isnan(val) && val > 0; S.temperature = val; end
            elseif strncmp(kl, 'default_c0_', 11)
                S.default_C0(kl(12:end)) = val;
            elseif strncmp(kl, 'default_dilution_', 17)
                S.default_dil(kl(18:end)) = val;
            end
        end
    end
end


function D = build_dataset(C, S)
% 把 Data 表整理成列向量：填组名、算 Ce/qe、剔除缺值与 exclude 行。
    [hr, hdr] = find_header(C);
    if hr == 0
        error('Data 表找不到表头：需要同时含 exp 与 Ce_ppm 两列。');
    end
    ci = @(n) find(strcmp(hdr, n), 1);

    nrow = size(C, 1) - hr;
    exp_s = cell(nrow, 1); min_s = cell(nrow, 1); bg_s = cell(nrow, 1);
    C0 = nan(nrow,1); Ce = nan(nrow,1); tt = nan(nrow,1); ph = nan(nrow,1);
    sol = nan(nrow,1); keep = true(nrow,1);

    last_exp = ''; last_min = ''; last_bg = '';
    for i = 1:nrow
        r = hr + i;
        e = strtrim(tostr(getcell(C, r, ci('exp'))));
        mn = strtrim(tostr(getcell(C, r, ci('mineral'))));
        bg = strtrim(tostr(getcell(C, r, ci('background'))));
        if ~isempty(e);  last_exp = e; else; e = last_exp; end
        if ~isempty(mn); last_min = mn; else; mn = last_min; end
        if ~isempty(bg); last_bg = bg; else; bg = last_bg; end
        e = lower(e);

        c0 = tonum(getcell(C, r, ci('c0_ppm')));
        ce = tonum(getcell(C, r, ci('ce_ppm')));
        cc = tonum(getcell(C, r, ci('conc_ppb')));
        cf = tonum(getcell(C, r, ci('corr_factor')));
        dl = tonum(getcell(C, r, ci('dilution')));
        if isnan(cf); cf = 1.0; end
        if isnan(dl)
            dl = mapget(S.default_dil, e, 1.0);
        end
        if isnan(c0) && ~isnan(mapget(S.default_C0, e, NaN))
            c0 = mapget(S.default_C0, e, NaN);
        end
        if isnan(ce) && ~isnan(cc)
            ce = cc * cf * dl / 1000.0;
        end

        ex = getcell(C, r, ci('exclude'));
        is_ex = is_trueish(ex);

        exp_s{i} = e; min_s{i} = mn; bg_s{i} = bg;
        C0(i) = c0; Ce(i) = ce;
        tt(i) = tonum(getcell(C, r, ci('time_h')));
        ph(i) = tonum(getcell(C, r, ci('ph')));
        sol(i) = tonum(getcell(C, r, ci('solid_g_per_l')));
        if isempty(mn); sol(i) = NaN; end

        keep(i) = ~is_ex && ~isempty(e) && any(strcmp(e, {'isotherm','kinetics','edge'})) ...
                  && ~isnan(c0) && ~isnan(ce);
    end

    % 固液比：行内值优先，否则 Settings 的 solid:<名称>
    for i = 1:nrow
        if keep(i) && (isnan(sol(i)) || sol(i) <= 0)
            sol(i) = mapget(S.solids, min_s{i}, NaN);
        end
    end

    exp_s = exp_s(keep); min_s = min_s(keep); bg_s = bg_s(keep);
    C0 = C0(keep); Ce = Ce(keep); tt = tt(keep); ph = ph(keep); sol = sol(keep);

    has_solid = ~isnan(sol) & sol > 0;
    removed = C0 - Ce;
    qe = removed; qe(has_solid) = removed(has_solid) ./ sol(has_solid);
    U = removed ./ C0;

    D = struct();
    D.exp = exp_s; D.mineral = min_s; D.bg = bg_s;
    D.C0 = C0; D.Ce = Ce; D.t = tt; D.pH = ph;
    D.solid = sol; D.qe = qe; D.U = U;
end


function [hr, hdr] = find_header(C)
% 找表头行：同一行里既有 exp 又有 Ce_ppm（大小写不敏感）。
    hr = 0; hdr = {};
    lim = min(size(C,1), 80);
    for r = 1:lim
        row = cellfun(@(v) lower(strtrim(tostr(v))), C(r,:), 'UniformOutput', false);
        if any(strcmp(row, 'exp')) && any(strcmp(row, 'ce_ppm'))
            hr = r; hdr = row; return;
        end
    end
end


function v = getcell(C, r, c)
    if isempty(c) || isnan(c) || r > size(C,1) || c > size(C,2)
        v = [];
    else
        v = C{r, c};
    end
end


function tf = is_trueish(v)
    tf = false;
    if isempty(v); return; end
    if islogical(v); tf = any(v); return; end
    if isnumeric(v); tf = any(v == 1); return; end
    s = lower(strtrim(tostr(v)));
    tf = any(strcmp(s, {'true','1','yes','y','是','剔除'}));
end


function v = tonum(x)
% 单元格 → 数值；非数值返回 NaN。
    v = NaN;
    if isempty(x); return; end
    if isnumeric(x); v = double(x(1)); return; end
    if islogical(x); v = double(x(1)); return; end
    s = strtrim(tostr(x));
    if isempty(s); return; end
    v = str2double(s);
    if isnan(v)
        v = sscanf(s, '%f', 1);
        if isempty(v); v = NaN; end
    end
end


function s = tostr(x)
% 单元格 → 字符向量；缺失值返回 ''。
    s = '';
    if isempty(x); return; end
    if ischar(x); s = x; return; end
    if isstring(x); if ~ismissing(x); s = char(x); end; return; end
    if isnumeric(x) || islogical(x)
        if all(isnan(double(x(:)))); return; end
        s = num2str(double(x(1)));
        return;
    end
end


function v = mapget(mp, key, default)
% containers.Map 安全取值（key 不在表里时回退默认值）。
    v = default;
    if isempty(key); return; end
    if isKey(mp, key); v = mp(key); end
end


function p = clampp(p, lo, hi)
% 把参数压回上下界内（fminsearch 无约束，靠这一步维持正参数）。
    p = min(max(p(:), lo(:)), hi(:));
end


function s = objfun(th, f, x, y, lo, hi)
    p = clampp(exp(th), lo, hi);
    r = y - f(x, p);
    s = sum(r .^ 2);
    if isnan(s) || isinf(s); s = 1e30; end
end


function [p, sse, hit_bound, nok] = fit_one(f, x, y, p0, lo, hi, n_start)
% 多起点有界最小二乘：参数在对数空间里搜索，保证为正。
    p0 = clampp(p0, lo, hi);
    th0 = log(max(p0, realmin));
    opts = optimset('Display', 'off', 'MaxFunEvals', 6000, ...
                    'MaxIter', 6000, 'TolX', 1e-10, 'TolFun', 1e-12);
    best = inf; bp = p0; nok = 0;
    for s = 1:n_start
        if s == 1
            th = th0;
        else
            th = th0 + 1.5 * randn(size(th0));
        end
        [thk, fv] = fminsearch(@(t) objfun(t, f, x, y, lo, hi), th, opts);
        if fv < best
            best = fv; bp = clampp(exp(thk), lo, hi);
        end
        if fv < best * 1.001; nok = nok + 1; end
    end
    p = bp; sse = best;
    hit_bound = any(p <= lo .* 1.001) || any(p >= hi .* 0.999);
end


function M = metrics(y, yhat, np)
% 与 Python 端一致：SSE / R2 / adjR2 / RMSE / AICc。
    n = numel(y);
    r = y - yhat;
    sse = sum(r .^ 2);
    sst = sum((y - mean(y)) .^ 2);
    if sst > 0; M.r2 = 1 - sse / sst; else; M.r2 = NaN; end
    dof = n - np;
    if dof > 0
        M.adj = 1 - (1 - M.r2) * (n - 1) / dof;
        M.rmse = sqrt(sse / dof);
    else
        M.adj = NaN; M.rmse = NaN;
    end
    if sse > 0
        aic = n * log(sse / n) + 2 * np;
        if n - np - 1 > 0
            M.aicc = aic + 2 * np * (np + 1) / (n - np - 1);
        else
            M.aicc = Inf;
        end
    else
        M.aicc = -Inf;
    end
    M.sse = sse; M.n = n;
end


function [ux, my] = agg_mean(x, y)
% 按 x 的取值分组求 y 的均值（相当于 pandas groupby(x).mean()）。
    ux = unique(x(:));
    my = nan(size(ux));
    for i = 1:numel(ux)
        m = (x(:) == ux(i)) & ~isnan(y(:));
        if any(m); my(i) = mean(y(m)); end
    end
end


function keys = group_keys(mineral, bg)
% 唯一的「吸附剂 | 背景」组合，保持出现顺序。
    keys = {};
    raw = strcat(mineral(:), ' | ', bg(:));
    seen = containers.Map('KeyType', 'char', 'ValueType', 'logical');
    for i = 1:numel(raw)
        if ~isKey(seen, raw{i})
            seen(raw{i}) = true;
            keys{end+1} = raw{i}; %#ok<AGROW>
        end
    end
end


function s = fmt_params(p, names)
    s = '';
    for j = 1:numel(p)
        s = [s sprintf('%s=%.4g  ', names{j}, p(j))]; %#ok<AGROW>
    end
    s = strtrim(s);
end


function rows = add_row(rows, grp, kind, model, p, names, M, atb)
    rows(end+1, :) = {grp, kind, model, fmt_params(p, names), M.n, ...
                      M.sse, M.r2, M.adj, M.rmse, M.aicc, atb}; %#ok<AGROW>
end


%% ------------------------- 模型定义 --------------------------------

function M = mk(key, label, names, f, g, b)
% 单个模型的定义。逐字段赋值，避免 struct() 对 cell/函数句柄做数组展开。
    M = struct();
    M.key = key;
    M.label = label;
    M.names = names;
    M.f = f;
    M.g = g;
    M.b = b;
    M.np = numel(names);
end


function L = isotherm_models(S)
% 7 个等温线模型。未填摩尔质量时不放 D-R（与 Python 端 active_isotherms 一致）。
    L = { ...
      mk('langmuir', 'Langmuir', {'qmax','K_L'}, @m_langmuir, @g_langmuir, @b_langmuir), ...
      mk('freundlich', 'Freundlich', {'K_F','n'}, @m_freundlich, @g_freundlich, @b_freundlich), ...
      mk('temkin', 'Temkin', {'B','A_T'}, @m_temkin, @g_temkin, @b_temkin), ...
      mk('sips', 'Sips', {'qmax','K_S','m'}, @m_sips, @g_sips, @b_sips), ...
      mk('toth', 'Toth', {'qmax','K_T','t'}, @m_toth, @g_toth, @b_toth), ...
      mk('rp', 'Redlich-Peterson', {'K_R','a_R','g'}, @m_rp, @g_rp, @b_rp)};
    if ~isnan(S.molar_mass) && S.molar_mass > 0
        L = [L, {mk('dr', 'Dubinin-Radushkevich', {'qmax','K_DR'}, ...
                    @(x,p) m_dr(x, p, S.molar_mass, S.temperature), ...
                    @g_dr, @b_dr)}];
    else
        fprintf('      （未填 molar_mass_g_per_mol，跳过 D-R）\n');
    end
end


function L = kinetic_models()
    L = { ...
      mk('pfo', 'PFO', {'qe','k1'}, @m_pfo, @g_pfo, @b_pfo), ...
      mk('pso', 'PSO', {'qe','k2'}, @m_pso, @g_pso, @b_pso), ...
      mk('elovich', 'Elovich', {'alpha','beta'}, @m_elovich, @g_elovich, @b_elovich), ...
      mk('avrami', 'Avrami', {'qe','k_av','n'}, @m_avrami, @g_avrami, @b_avrami), ...
      mk('bangham', 'Bangham', {'k_B','alpha'}, @m_bangham, @g_bangham, @b_bangham)};
end


function [rows, best_lines] = run_isotherm(D, mask, models, CFG, rows, best_lines)
    keys = group_keys(D.mineral(mask), D.bg(mask));
    idx = find(mask);
    for k = 1:numel(keys)
        sel = idx(strcmp(strcat(D.mineral(idx), ' | ', D.bg(idx)), keys{k}));
        C0 = D.C0(sel); Ce = D.Ce(sel); qe = D.qe(sel);
        % 与 Python 一致：取各 C0 的均值（平行样合并），并跳过非正定义域
        [uC0, mCe] = agg_mean(C0, Ce);
        [~, mqe] = agg_mean(C0, qe);
        ok = uC0 > 0 & mCe > 0 & mqe > 0;
        x = mCe(ok); y = mqe(ok);
        unit = tern(all(~isnan(D.solid(sel))), 'mg/g', 'mg/L(悬浮液)');
        fprintf('\n  [%s]  n=%d  单位=%s\n', keys{k}, numel(x), unit);
        if numel(x) < CFG.min_pts
            fprintf('      点数不足 %d，跳过拟合\n', CFG.min_pts);
            continue;
        end
        R = {};
        for j = 1:numel(models)
            md = models{j};
            if numel(x) < md.np + 2
                fprintf('      %-22s 跳过（点数 < 参数数+2）\n', md.label);
                continue;
            end
            p0 = md.g(x, y); [lo, hi] = md.b(x, y);
            [p, sse, atb] = fit_one(md.f, x, y, p0, lo, hi, CFG.n_start);
            M = metrics(y, md.f(x, p), md.np);
            rows = add_row(rows, keys{k}, 'isotherm', md.label, p, md.names, M, atb);
            rr = struct(); rr.label = md.label; rr.p = p; rr.names = md.names;
            rr.M = M; rr.atb = atb;
            R{end+1} = rr; %#ok<AGROW>
            fprintf('      %-22s %s\n', md.label, fmt_params(p, md.names));
            fprintf('      %-22s SSE=%.4g  R2=%.4f  adjR2=%.4f  RMSE=%.4g  AICc=%.3f%s\n', ...
                    '', M.sse, M.r2, M.adj, M.rmse, M.aicc, tern(atb, '  [参数触界]', ''));
            if strcmp(md.key, 'dr')
                E = 1 / sqrt(2 * max(p(2), realmin));
                fprintf('      %-22s E = %.2f kJ/mol（<8 物理吸附 / 8-16 离子交换 / >16 化学吸附）\n', '', E);
            elseif strcmp(md.key, 'temkin')
                bT = 8.314462618 * 293.15 / max(p(1), realmin);
                fprintf('      %-22s b_T = %.4g J/mol（按 298.15 K 折算）\n', '', bT);
            end
        end
        if ~isempty(R)
            aic = cellfun(@(r) r.M.aicc, R);
            [~, b] = min(aic);
            best_lines{end+1} = sprintf('%-28s %-22s R2=%.4f  AICc=%.3f', ...
                keys{k}, R{b}.label, R{b}.M.r2, R{b}.M.aicc); %#ok<AGROW>
        end
    end
end


function [rows, best_lines] = run_kinetics(D, mask, models, CFG, rows, best_lines)
    keys = group_keys(D.mineral(mask), D.bg(mask));
    idx = find(mask);
    for k = 1:numel(keys)
        sel = idx(strcmp(strcat(D.mineral(idx), ' | ', D.bg(idx)), keys{k}));
        t = D.t(sel); qt = D.qe(sel);
        good = ~isnan(t) & ~isnan(qt);
        [ut, mqt] = agg_mean(t(good), qt(good));
        ok = ut > 0;
        x = ut(ok); y = mqt(ok);
        unit = tern(all(~isnan(D.solid(sel))), 'mg/g', 'mg/L(悬浮液)');
        fprintf('\n  [%s]  n=%d  单位=%s\n', keys{k}, numel(x), unit);
        if numel(x) < CFG.min_pts
            fprintf('      点数不足 %d，跳过拟合\n', CFG.min_pts);
            continue;
        end
        R = {};
        for j = 1:numel(models)
            md = models{j};
            if numel(x) < md.np + 2
                fprintf('      %-22s 跳过（点数 < 参数数+2）\n', md.label);
                continue;
            end
            p0 = md.g(x, y); [lo, hi] = md.b(x, y);
            [p, sse, atb] = fit_one(md.f, x, y, p0, lo, hi, CFG.n_start);
            M = metrics(y, md.f(x, p), md.np);
            rows = add_row(rows, keys{k}, 'kinetics', md.label, p, md.names, M, atb);
            rr = struct(); rr.label = md.label; rr.p = p; rr.names = md.names;
            rr.M = M; rr.atb = atb;
            R{end+1} = rr; %#ok<AGROW>
            fprintf('      %-22s %s\n', md.label, fmt_params(p, md.names));
            fprintf('      %-22s SSE=%.4g  R2=%.4f  adjR2=%.4f  RMSE=%.4g  AICc=%.3f%s\n', ...
                    '', M.sse, M.r2, M.adj, M.rmse, M.aicc, tern(atb, '  [参数触界]', ''));
            if strcmp(md.key, 'pso')
                fprintf('      %-22s h = k2*qe^2 = %.4g\n', '', p(2) * p(1)^2);
            end
        end
        if ~isempty(R)
            aic = cellfun(@(r) r.M.aicc, R);
            [~, b] = min(aic);
            best_lines{end+1} = sprintf('%-28s %-22s R2=%.4f  AICc=%.3f', ...
                keys{k}, R{b}.label, R{b}.M.r2, R{b}.M.aicc); %#ok<AGROW>
        end
    end
end


function rows = run_ipd(D, mask, CFG, rows)
% Weber-Morris：qt 对 t^0.5 的两段线性，断点由总残差最小确定。
    keys = group_keys(D.mineral(mask), D.bg(mask));
    idx = find(mask);
    for k = 1:numel(keys)
        sel = idx(strcmp(strcat(D.mineral(idx), ' | ', D.bg(idx)), keys{k}));
        t = D.t(sel); qt = D.qe(sel);
        good = ~isnan(t) & ~isnan(qt) & t >= 0;
        [ut, mqt] = agg_mean(t(good), qt(good));
        ok = ut >= 0;
        s = sqrt(ut(ok)); y = mqt(ok);
        n = numel(s);
        fprintf('\n  [%s]  n=%d\n', keys{k}, n);
        if n < 7
            fprintf('      点数 < 7，不做分段拟合\n');
            continue;
        end
        best = inf; bi = 0; bp1 = []; bp2 = [];
        for b = 4:(n-3)
            p1 = polyfit(s(1:b), y(1:b), 1);
            p2 = polyfit(s(b+1:end), y(b+1:end), 1);
            r = [y(1:b) - polyval(p1, s(1:b)); y(b+1:end) - polyval(p2, s(b+1:end))];
            ss = sum(r .^ 2);
            if ss < best; best = ss; bi = b; bp1 = p1; bp2 = p2; end
        end
        k1 = bp1(1); k2 = bp2(1); C1 = bp1(2); C2 = bp2(2);
        tb = s(bi) ^ 2;          % 断点时间：由 t^0.5 反算，避免索引口径不一致
        M = metrics(y, [polyval(bp1, s(1:bi)); polyval(bp2, s(bi+1:end))], 4);
        fprintf('      Stage I : k1 = %.4g  C1 = %.4g\n', k1, C1);
        fprintf('      Stage II: k2 = %.4g  C2 = %.4g   断点 t = %.4g h (t^0.5 = %.3f)\n', ...
                k2, C2, tb, sqrt(tb));
        fprintf('      R2 = %.4f   SSE = %.4g\n', M.r2, M.sse);
        if k2 <= 0
            fprintf('      [提示] 第二段斜率 <= 0：后期已无扩散控制特征，该分段不宜解释。\n');
        elseif k2 > k1
            fprintf('      [提示] 第二段比第一段更陡（k2 > k1），不符合扩散控制，检查末段数据。\n');
        end
        p = [k1 C1 k2 C2];
        rows = add_row(rows, keys{k}, 'ipd', 'Stage I+II', p, ...
                       {'k1','C1','k2','C2'}, M, false);
    end
end


function rows = run_edge(D, mask, CFG, rows)
% 4 参数 logistic：theta = bottom + (top-bottom)/(1+exp((pH-pH50)/w))
    keys = group_keys(D.mineral(mask), D.bg(mask));
    idx = find(mask);
    for k = 1:numel(keys)
        sel = idx(strcmp(strcat(D.mineral(idx), ' | ', D.bg(idx)), keys{k}));
        p_h = D.pH(sel); th = D.U(sel);
        good = ~isnan(p_h) & ~isnan(th);
        [ux, my] = agg_mean(p_h(good), th(good));
        x = ux; y = my;
        fprintf('\n  [%s]  n=%d\n', keys{k}, numel(x));
        if numel(x) < CFG.min_pts
            fprintf('      点数不足 %d，跳过拟合\n', CFG.min_pts);
            continue;
        end
        [xs, ord] = sort(x); ys = y(ord);
        ne = max(1, floor(numel(xs) / 4));
        low_ph = median(ys(1:ne));
        high_ph = median(ys(end-ne+1:end));
        p0 = [high_ph, low_ph, median(xs), 1.0];
        lo = [-0.3, -0.2, 2.0, 0.05];
        hi = [1.2, 1.5, 12.0, 10.0];
        [p, sse, atb] = fit_one(@m_logistic, x, y, p0, lo, hi, CFG.n_start);
        M = metrics(y, m_logistic(x, p), 4);
        slope = -(p(2) - p(1)) / (4 * p(4));
        fprintf('      bottom = %.4f  top = %.4f  pH50 = %.3f  w = %.4f\n', p(1), p(2), p(3), p(4));
        fprintf('      斜率 = %.4f /pH   SSE=%.4g  R2=%.4f  adjR2=%.4f  RMSE=%.4g  AICc=%.3f%s\n', ...
                slope, M.sse, M.r2, M.adj, M.rmse, M.aicc, tern(atb, '  [参数触界]', ''));
        rows = add_row(rows, keys{k}, 'edge', 'Logistic', p, ...
                       {'bottom','top','pH50','w'}, M, atb);
    end
end


function s = tern(c, a, b)
    if c; s = a; else; s = b; end
end


%% ------------------------- 具体方程 --------------------------------

function y = m_langmuir(x, p)
    y = p(1) * p(2) * x ./ (1 + p(2) * x);
end

function y = m_freundlich(x, p)
    y = p(1) * x .^ (1 / p(2));
end

function y = m_temkin(x, p)
    y = p(1) * log(max(p(2) * x, 1e-300));
end

function y = m_dr(x, p, molar_mass, temp)
    cm = max(x, 1e-30) / 1000 / molar_mass;
    eps = 8.314462618 * temp * log(1 + 1 ./ cm) / 1000;
    y = p(1) * exp(-p(2) * eps .^ 2);
end

function y = m_sips(x, p)
    z = max(p(2) * x, 1e-300) .^ p(3);
    y = p(1) * z ./ (1 + z);
end

function y = m_toth(x, p)
    z = p(2) * x;
    y = p(1) * z ./ ((1 + z .^ p(3)) .^ (1 / p(3)));
end

function y = m_rp(x, p)
    y = p(1) * x ./ (1 + p(2) * max(x, 1e-300) .^ p(3));
end

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
    y = p(1) * (1 - exp(-(p(2) * x) .^ p(3)));
end

function y = m_bangham(x, p)
    y = p(1) * x .^ p(2);
end

function y = m_logistic(ph, p)
    y = p(1) + (p(2) - p(1)) ./ (1 + exp((ph - p(3)) / p(4)));
end


%% ------------------------- 初值与上下界 -----------------------------

function p = g_langmuir(x, y)
    p = [max(y) * 1.2, 1 / max(median(x), 1e-9)];
end
function [lo, hi] = b_langmuir(x, y)
    ym = max(max(y), 1e-12); xm = max(median(x), 1e-12);
    lo = [0.05 * ym, 1e-6 / xm]; hi = [20 * ym, 1e4 / xm];
end

function p = g_freundlich(x, y)
    n = 2.0;
    p = [max(y) / max(max(x) ^ (1 / n), 1e-12), n];
end
function [lo, hi] = b_freundlich(x, y)
    ym = max(max(y), 1e-12); xm = max(max(x), 1e-12);
    lo = [1e-6 * ym / xm, 1.05]; hi = [1e3 * ym, 15.0];
end

function p = g_temkin(x, y)
    p = [max(max(y) / max(log(max(x) / min(x)), 1.0), 1e-6), 1 / max(median(x), 1e-9)];
end
function [lo, hi] = b_temkin(x, y)
    ym = max(max(y), 1e-12); xm = max(median(x), 1e-12);
    lo = [1e-4 * ym, 1e-6 / xm]; hi = [50 * ym, 1e4 / xm];
end

function p = g_dr(x, y) %#ok<INUSD>
    p = [max(y) * 1.3, 1e-4];
end
function [lo, hi] = b_dr(x, y)
    ym = max(max(y), 1e-12);
    lo = [0.1 * ym, 1e-9]; hi = [20 * ym, 1.0];
end

function p = g_sips(x, y)
    p = [max(y) * 1.2, 1 / max(median(x), 1e-9), 0.8];
end
function [lo, hi] = b_sips(x, y)
    ym = max(max(y), 1e-12); xm = max(median(x), 1e-12);
    lo = [0.05 * ym, 1e-6 / xm, 0.1]; hi = [20 * ym, 1e4 / xm, 5.0];
end

function p = g_toth(x, y)
    p = [max(y) * 1.2, 1 / max(median(x), 1e-9), 0.8];
end
function [lo, hi] = b_toth(x, y)
    ym = max(max(y), 1e-12); xm = max(median(x), 1e-12);
    lo = [0.05 * ym, 1e-6 / xm, 0.1]; hi = [20 * ym, 1e4 / xm, 5.0];
end

function p = g_rp(x, y)
    xm = max(median(x), 1e-9);
    p = [max(max(y) / xm, 1e-9), 1 / xm, 0.9];
end
function [lo, hi] = b_rp(x, y)
    ym = max(max(y), 1e-12); xm = max(median(x), 1e-12);
    lo = [1e-6 * ym / xm, 1e-6 / xm, 0.1]; hi = [1e3 * ym / xm, 1e4 / xm, 1.0];
end

function p = g_pfo(x, y)
    tm = max(median(x(x > 0)), 1e-6);
    p = [max(y) * 1.05, 1 / tm];
end
function [lo, hi] = b_pfo(x, y)
    ym = max(max(y), 1e-12); tm = max(median(x(x > 0)), 1e-6);
    lo = [0.2 * ym, 1e-4 / tm]; hi = [5 * ym, 1e3 / tm];
end

function p = g_pso(x, y)
    qe = max(max(y) * 1.05, 1e-9); tm = max(median(x(x > 0)), 1e-6);
    p = [qe, 1 / (qe * tm)];
end
function [lo, hi] = b_pso(x, y)
    ym = max(max(y), 1e-12); tm = max(median(x(x > 0)), 1e-6);
    lo = [0.2 * ym, 1e-6 / (ym * tm)]; hi = [5 * ym, 1e3 / (ym * tm)];
end

function p = g_elovich(x, y) %#ok<INUSD>
    p = [1.0, 1 / max(max(y), 1e-9)];
end
function [lo, hi] = b_elovich(x, y)
    ym = max(max(y), 1e-12);
    lo = [1e-4, 1e-6 / ym]; hi = [1e3, 1e3 / ym];
end

function p = g_avrami(x, y)
    tm = max(median(x(x > 0)), 1e-6);
    p = [max(y) * 1.05, 1 / tm, 0.7];
end
function [lo, hi] = b_avrami(x, y)
    ym = max(max(y), 1e-12); tm = max(median(x(x > 0)), 1e-6);
    lo = [0.2 * ym, 1e-4 / tm, 0.1]; hi = [5 * ym, 1e2 / tm, 5.0];
end

function p = g_bangham(x, y)
    p = [max(max(y) / max(max(x) ^ 0.5, 1e-9), 1e-9), 0.5];
end
function [lo, hi] = b_bangham(x, y)
    ym = max(max(y), 1e-12); xm = max(max(x), 1e-12);
    lo = [1e-4 * ym / xm, 0.05]; hi = [1e3 * ym, 2.0];
end
