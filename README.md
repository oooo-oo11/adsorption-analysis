# 吸附数据分析工具

一次运行，把仪器原始数据（或填好的 Excel 模板）变成 **英文出版级图件 + 自包含 HTML 报告 + Excel 汇总表**。

- 等温线 7 个模型：Langmuir / Freundlich / Temkin / D-R / Sips / Toth / Redlich–Peterson
- 动力学 5 个模型：PFO / PSO / Elovich / Avrami / Bangham
- 颗粒内扩散两段或三段、pH 边 4 参数 logistic、离子强度对比
- 用 AICc 选模型，并给出参数触界、多起点收敛率、ΔAICc 等「能不能引用」的判据
- 包内自带 Python，**解压双击即用**，不需要安装任何东西

## 快速开始

1. 把仪器导出的 `.xlsx` 放进 `data\`
2. 双击 `adsorp.bat`
3. 结束自动打开 `output\报告.html`

文件名、工作表排版都不用改：目录里有几个工作簿就读几个，实验类型（等温线 / 动力学 /
吸附边 / QC）由表内内容自动判断，日志第一行会打印每个文件被判成了什么。

PowerShell 里的等价写法：

```powershell
.\adsorp.bat run                       # 读 data\ 里的全部工作簿
.\adsorp.bat run --template 数据.xlsx   # 用指定的一份模板
.\adsorp.bat run --reuse               # 只重绘图与报告，不重跑拟合
```

> `.\` 不能省：PowerShell 默认不从当前目录找可执行文件。

## 数据怎么给

| 方式 | 做法 |
|---|---|
| 仪器原始工作簿 | 直接丢进 `data\`（或项目根目录），不改名、不整理格式 |
| Excel 模板（推荐） | `.\adsorp.bat template` 生成空白模板 → 填表 → `run --template 表.xlsx` |

模板最少要填：`exp`（`isotherm` / `kinetics` / `edge` / `qc`）、`mineral`、`background`、
`C0_ppm`（等温线必填），以及实测值（`Ce_ppm` 或 `conc_ppb`）；动力学加 `time_h`，
吸附边加 `pH`。**固液比 m/V (g/L)** 写在 `Settings` 的 `solid:<吸附剂名>`——
没有它容量参数只能报 mg/L(悬浮液)。

填完先自查：`.\adsorp.bat check --template 数据.xlsx`，几秒出结果，打印行数、分组、缺列与异常标记。

## 产物

全部在 `output\`，每次运行整目录覆盖。

| 文件 | 内容 |
|---|---|
| `报告.html` | 单文件自包含（图与 PDF 全内嵌），可转发的成品 |
| `报告.pdf` | 打印版（本机有 Chrome 时生成） |
| `结果汇总.xlsx` | 11 张表：最优模型、全部模型、IPD、平衡时间、吸附边、QC、可靠性… |
| `figures/*.png` `.pdf` | 300 dpi 位图（17.2 cm 宽）与矢量图 |
| `tables/*.csv` | 与 Excel 同内容（utf-8-sig，Excel 直接打开不乱码） |
| `matlab_verify.m` | 本次数据与全部模型内嵌，在 MATLAB 里复算并逐模型比对 SSE |

## 常用命令

`adsorp.bat` 与 `python -m adsorp.cli` 等价，省略子命令默认就是 `run`。

| 命令 | 作用 |
|---|---|
| `run` | 完整流程：解析 → 计算 → 拟合 → 绘图 → 报告 |
| `run --reuse` | 复用上次拟合，只重绘图与报告（调版式用） |
| `run --solid 3` | 覆盖固液比，单一数值套用到所有样品 |
| `run --no-figs` | 只出表，不绘图 |
| `run --ipd-stages 3` | 颗粒内扩散分三段（默认两段，需 ≥10 个时间点） |
| `template` / `check` / `export` | 生成空白模板 / 只校验 / 导出当前数据为模板 |
| `matlab --verify` | 生成 MATLAB 全模型复核脚本 |

完整选项见 [`docs/命令速查.txt`](docs/命令速查.txt)。

## 图件

6 类英文图：等温线（线性 + 对数）、动力学（线性 + 对数）、颗粒内扩散、pH 边、QC、残差。
数据里没有 QC 实验时不出 QC 图，其余照出。

- 报告里每张图下方有「下载 PNG / PDF」按钮，也能展开看这张图的绘图代码；
- 直接取文件在 `output/figures/`，打包版是 `figures_en.zip`；
- 颜色按吸附剂分派、标记按背景电解质区分，换体系不会串色也不会每次变一个样。

## 结果怎么判可信

只看 R² 不够。报告最后一节按四条判据给结论：参数触界或 max|r| > 0.99（参数不可分辨）、
多起点收敛率 < 0.5（解不唯一）、R² < 0.5（模型不适定）、ΔAICc ≤ 2（不能宣称「最优」）。

选模型用 AICc 而不是 R²：多一个参数必然抬高 R²，AICc 会惩罚这一点。

## 目录

```
分析/
├─ adsorp.bat / adsorp.ps1   入口（双击 bat 即可，ps1 需先放开执行策略）
├─ adsorp/                   程序：io / models / fit / analyze / viz / report / pipeline
├─ data/                     输入：仪器原始工作簿放这里
├─ templates/                空白模板
├─ output/                   成果，每次运行覆盖
├─ docs/                     命令速查、MATLAB 脚本、详细说明
└─ python/                   便携版 Python（删掉则自动改用系统 Python）
```

## 环境

包内 `python\` 是 Windows 64 位便携版 Python 3.13，numpy / pandas / scipy / matplotlib /
openpyxl 已预装，不写注册表、不改 PATH、不联网。只支持 64 位 Windows 10 及以上。

想用自己装的 Python：删掉 `python\` 即可，启动脚本会依次找 `.venv` → `py -3` → `python`；
也可以设 `ADSORP_PYTHON` 指定解释器。

## MATLAB

- `output/matlab_verify.m`：每次运行自动生成，核对 Python 的拟合结果；
- [`docs/reference/fit_all_models.m`](docs/reference/fit_all_models.m)：读 Excel 模板**独立**跑完全部分析，
  只用基础 MATLAB（`fminsearch`），不需要任何工具箱。

更细的说明（模板全部字段、空白单元格规则、最少信息清单、归档与编码约定）见
[`docs/详细说明.md`](docs/详细说明.md)。
