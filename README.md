# 吸附数据分析流水线

一条命令把仪器原始数据（或填好的 Excel 模板）变成：英文出版级图件 + 自包含 HTML 报告 + Excel 汇总表。

---

## 1. 快速开始

三种启动方式，产物完全相同，按习惯挑一个。

**① 双击**（最省事，不需要任何命令行基础）

在资源管理器里双击 `adsorp.bat`。脚本会自动找可用的 Python、跑完整流程、结束后自动打开
`output\报告.html`，窗口停在那里显示日志（按任意键关闭）。

**② PowerShell**

```powershell
cd "C:\path\to\分析"
.\adsorp.bat run
```

> PowerShell 默认不从当前目录搜可执行文件，所以必须写 `.\`。
> 若想用原生脚本 `adsorp.ps1`（与 bat 等价），会遇到 Windows 默认的
> **执行策略拦截**（`Restricted`，`.ps1` 一律不让跑），需先放开一次：
>
> ```powershell
> Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
> .\adsorp.ps1 run
> ```
>
> 不想改系统设置就用 `.\adsorp.bat`——`.bat` 不受执行策略限制，在 PowerShell 里照样跑。

**③ cmd**

```bat
cd /d C:\path\to\分析
adsorp.bat run
```

三个入口都会先探测 Python：`ADSORP_PYTHON` 环境变量 → `.venv\Scripts\python.exe` →
`py -3` → `python`，逐个实测能否 `import numpy, pandas, scipy, matplotlib, openpyxl`，
第一个通过的即被使用；都不行会明确报错并提示怎么装。

---

## 2. 数据放哪、怎么跑

### 2.1 直接放工作簿（不整理格式）

把仪器导出的 `.xlsx` 丢进 `data\`（或项目根目录），然后双击 / `adsorp.bat run`。
**不需要改文件名**：目录里有几个就读几个，实验类型由脚本按表内内容判断——
表名或标题写了「等温 / 动力学 / 吸附边」就按写的来，没写就看哪一列真正有数据
（`反应时间/h` 有值 → 动力学，`目标 pH` 有值 → 吸附边，都没有 → 等温线），
日志第一行会打印每个文件被判成了什么。

只做一两类也可以，缺的那类会在日志里说明「数据里没有 xx 实验」。

### 2.2 用整理好的模板（推荐，可精确复现）

长表格式（`Data` + `Settings` 两张表）：

```powershell
.\adsorp.bat template                                          # 生成空白模板
.\adsorp.bat check   --template templates\吸附数据模板.xlsx     # 只校验，几秒
.\adsorp.bat run     --template templates\吸附数据模板.xlsx
```

`check` 会打印行数、分组、缺列与异常标记，填表阶段用它自查最省事。

### 2.3 `data\` 里放模板也能直接跑

`run` 不带 `--template` 时会把目录里的 Excel 分成两类：符合模板格式的（有 `Data` 表
且表头含 `exp`）走模板分支，其余按仪器原始工作簿解析。两类同时存在时优先用原始工作簿，
并在日志里提示；只有模板时日志会写「改用模板：xxx.xlsx」。

所以「把整理好的表放进 `data\` 然后双击」和「把仪器原始表放进去双击」都行，
两种文件还可以混放。

### 2.4 其他选项

```powershell
.\adsorp.bat run --reuse            # 只重绘图与报告，不重跑拟合（调图版式时用）
.\adsorp.bat run --solid 3          # 覆盖固液比，单一数值套用到所有样品
.\adsorp.bat run --data-dir D:\某批数据
.\adsorp.bat run --no-figs          # 只出表，不绘图
```

---

## 3. 产物

全部在 `output/`，每次 `run` 整目录覆盖：

| 路径 | 内容 |
|---|---|
| `报告.html` | 自包含报告（图片 base64 内嵌，单文件可转发），每张图带 PNG/PDF 下载按钮，以及可折叠的绘图代码 |
| `报告.pdf` | 报告打印版（Chrome 导出，若本机有 Chrome） |
| `matlab_verify.m` | 全模型复核脚本：内含本次全部数据点，在 MATLAB 里重拟合全部模型，逐模型比对 SSE |
| `结果汇总.xlsx` | 11 个工作表：最优模型、全模型、IPD、平衡时间、吸附边、离子强度对比、QC、模型可靠性… |
| `figures/*.png` | 300 dpi 位图（17.2 cm 宽，可直接置入 Word） |
| `figures/*.pdf` | 矢量图（LaTeX / AI / Illustrator 可编辑） |
| `figures/figures_en.zip` | 全部图件打包 |
| `tables/*.csv` | 每张表的 CSV（utf-8-sig，Excel 直接打开不乱码） |
| `_analysis.pkl` | 拟合结果缓存，供 `--reuse` |

---

## 4. 命令一览

`python -m adsorp.cli <子命令>` 与 `adsorp.bat <子命令>` 完全等价；PowerShell 里加 `.\`
前缀即可（`.\adsorp.bat run`）。原生脚本 `.\adsorp.ps1` 同样等价，但需先放开执行策略。

| 命令 | 作用 |
|---|---|
| `run` | 完整流程：解析 → 计算 → 拟合 → 绘图 → 报告 |
| `run --template 数据.xlsx` | 从模板读数据（模板里的固液比优先） |
| `run --solid 3` | 覆盖固液比（单一数值，适用于所有样品） |
| `run --no-figs` | 只出表，不绘图 |
| `run --reuse` | 复用上次拟合，只重绘图/报告 |
| `template` | 生成空白模板 `templates/吸附数据模板.xlsx` |
| `check --template 数据.xlsx` | 只校验：行数、分组、缺列、异常标记 |
| `export --out 示例.xlsx` | 把当前已解析数据导出成「填好的模板」 |
| `matlab --verify` | 生成全模型复核脚本（读拟合缓存，需先 run 一次） |
| `matlab` | 导出 MATLAB 可粘贴的 `Ce/qe` 数组 |

> 省略子命令时默认执行 `run`：双击 `adsorp.bat`、或 `adsorp.bat --reuse`，
> 都等价于在 `run` 后加参数。

### MATLAB 全模型复核

每次 `run` 都会在输出目录生成 `matlab_verify.m`，把本次数据与全部模型打包进一个脚本：

```matlab
>> matlab_verify
```

- 覆盖 7 个等温线模型（Langmuir / Freundlich / Temkin / D-R / Sips / Toth / Redlich-Peterson）
  与 5 个动力学模型（PFO / PSO / Elovich / Avrami / Bangham），不只最优的那一个；
- 用 `fminsearch`（Nelder-Mead，**不需要任何工具箱**），每组 20 个起点：
  第 1 个用 Python 的最优参数，其余作对数扰动；
- 逐模型打印参数、SSE、R²、AICc，并与 Python 的 SSE 并排对比；`rel/% < 1e-6`
  即两条独立实现收敛到同一解；
- 若 MATLAB 算出更低的 SSE，说明 Python 那组掉进了局部极小，脚本会直接把差异摆出来。

同一份脚本也可作为投稿时的补充材料（审稿人可自行复算）。

---

## 5. Excel 模板：需要填什么

模板有三张表：`README`（说明）、`Data`（数据，一行 = 一个样品的一次测定）、
`Settings`（全局参数与固液比）。

### 5.1 `Data` 表字段

**必填（缺了无法计算）**

| 列 | 说明 | 示例 |
|---|---|---|
| `exp` | 实验类型，四选一：`isotherm` / `kinetics` / `edge` / `qc`。同一实验块可只写首行，下面留空表示沿用上一行 | `isotherm` |
| `mineral` | 吸附剂名，**直接用英文**（图上原样显示，不再翻译）；留空沿用上一行。新增吸附剂照写即可，不必改 `names.json` | `Mineral A` / `Goethite` |
| `background` | 背景电解质；留空沿用上一行。`NaCl` 与 `NaCl` 的大小写/上下标写法要保持一致 | `0.01 M NaCl` / `ASW` |
| `C0_ppm` | 初始浓度 (mg/L)。**等温线逐行必填**；动力学/吸附边可留空，按同组已有值或默认值补齐 | `10` |
| 实测值 | `Ce_ppm`（平衡浓度）或 `conc_ppb`（**标线计算/ppb，不是荧光值**，需配 `dilution`） | `7.82` / `102.4` |

动力学另加 **`time_h`**（取样时间，小时）；吸附边另加 **`pH`**（平衡 pH）。

**空白单元格的处理规则**

| 情况 | 处理 |
|---|---|
| `exp` / `mineral` / `background` 空 | 沿用上一行；换实验类型时在块首显式写一次 |
| `C0_ppm` 空（仅 kinetics / edge） | 先取同组已有值，再取 `Settings` 的 `default_C0_kinetics` / `default_C0_edge`，最后取 `config.json` 的 `defaults` |
| `Ce_ppm` 与 `conc_ppb` 都空 | 你已删掉或没做的点：**静默跳过**，不参与拟合与绘图，也不再提示 |
| 整行全空 | 直接忽略 |

**脚本不会替你改数据**

- 负吸附、`Ce > C0`、吸附率 > 100%、平行样离散大……一律**原样保留**，照常参与计算与绘图；
- 报告第一节的「数据质量清单」逐条列出 Excel 行号、条件、数值与建议，供你判断；
- 要剔除某个点，**只在该行 `exclude` 填 `TRUE`**。`note` 里写什么都不影响计算；
- 图上同样不裁剪：出现负值时纵轴自动下拉，不会把点藏到框外。

**建议填（影响结论的可解释性）**

| 列 | 说明 |
|---|---|
| `dilution` | 稀释倍数。留空取 `Settings` 的默认值（动力学/边/等温线各自一条） |
| `corr_factor` | 标线校正因子，默认 1.0 |
| `solid_g_per_L` | 固液比 m/V。留空取 `Settings` 里该吸附剂的值 |
| `replicate` | 平行样编号，可留空。同一组同一 `C0`/`time_h`/`pH` 出现多行即按平行样合并为均值 ± SD，图上画误差棒 |
| `note` | 备注，仅供你自己看；命中关键词也只在清单里提示，不改变计算 |
| `exclude` | **唯一能剔除数据的开关**：填 `TRUE` 则该行不参与拟合与绘图 |

### 5.2 `Settings` 表

```
project                     Adsorption dataset
analyte                     # 吸附质名称，仅用于报告标题
molar_mass_g_per_mol        # 吸附质摩尔质量 g/mol；不填则跳过 D-R
temperature_K               298.15
default_C0_kinetics         # 动力学 C0 留空时用
default_C0_edge             # 吸附边 C0 留空时用
default_dilution_isotherm   1
default_dilution_kinetics   1
default_dilution_edge       1
solid:Mineral A             1.0         # g/L
solid:Mineral B             2.0
```

`solid:` 后面的名字与 `Data` 表的 `mineral` 列**逐字一致**即可（都用英文）。
未列出的吸附剂按 mg/L(悬浮液) 处理，报告里会明确标注单位。

`molar_mass_g_per_mol` 只服务 D-R 模型：D-R 的吸附势 ε = RT·ln(1+1/C_mol) 需要吸附质
摩尔质量。**留空不会算错**——脚本会把 D-R 从候选模型里剔除（其余 6 个等温线模型照常拟合），
并在日志与报告里写明原因。填了才会参与比较。

`default_C0_*` 也可以不写，脚本会回退到 `config.json` 的 `defaults`。

**字体**：模板的西文/数字为 Times New Roman、中文为宋体（与出图一致）。字体只影响显示，
脚本按单元格的值读取，改字体/字号/加粗都不影响任何计算。

### 5.3 换算链

```
Ce (mg/L)  = conc_ppb × corr_factor × dilution / 1000
吸附率 (%) = 100 × (1 − Ce/C0)
qe (mg/g)  = (C0 − Ce) / (m/V)
```

---

## 6. 分析一份新数据，最少需要哪些信息

按重要性排序，前 3 项缺一不可：

1. **C0 与实测平衡浓度**（或荧光值 + 标线 + 稀释倍数 + 校正因子，让脚本自己算）。
   C0 在等温线中逐行必填；动力学/吸附边可留空，由 `Settings` 的 `default_C0_*`
   或 `config.json` 补齐。
2. **固液比 m/V (g/L)**。没有它只能给 mg/L(悬浮液)，容量参数（qmax、K_F）无法与文献比较；
   强度参数（K_L、n、k）不受影响。
3. **实验类型标签**与分组键（吸附剂、背景电解质）。
4. 动力学：取样时间；吸附边：平衡 pH；离子强度：背景电解质的浓度。
5. 平行样编号（可留空，同条件多行自动按平行样合并）、备注（只提示不改变计算）。
6. 温度（D-R 的 E 与 Temkin 的 b_T 依赖 T，默认 298.15 K）。
7. D-R：吸附质摩尔质量（不填则该模型被跳过）。

仪器原始表可以直接跑，但它是「宽表 + 多标线块 + 穿插 QC」的排版，解析规则写在
`adsorp/io.py`；换仪器或换模板时，**填模板比改解析器省事**。

---

## 7. 图件怎么取

三个途径，都不需要联网：

1. **报告里直接下载**：打开 `output/报告.html`，每张图下方有「下载 PNG（300 dpi）」和
   「下载 PDF（矢量）」。下载由页面内嵌的 base64 即时生成，双击 HTML 即可存图，
   转发给合作者也不会丢图。
2. **取文件**：`output/figures/isotherm.png` / `.pdf`，命名对应 图1 等温线、图2 残差、
   图3 动力学、图4 IPD、图5 吸附边、图6 QC。
3. **打包**：报告第七节的「打包下载」按钮在浏览器内即时打 ZIP；
   `output/figures/figures_en.zip` 是内容相同的落盘副本。

> **`报告.html` 是单文件自包含的**：全部图（含线性/对数两版）与矢量 PDF 都以 base64 内嵌，
> 页面没有任何外部引用。复制、邮件附件、微信转发、换电脑、断网打开都正常显示与下载，
> 不需要带上 `figures/` 文件夹；`figures/` 只是给不方便从网页下载时直接取文件用的。

每张图下方还有一个**可折叠的「绘图代码」**（默认收起，点击标题栏展开，再点收起）：
展开后是该图的绘制函数源码（`adsorp/viz.py::plot_xxx`），改图时直接照抄改，
不用翻文件找对应关系。

图件全部为英文，吸附剂名直接用 `Data` 表里写的英文。旧的中文数据表仍可通过
`names.json` 映射成英文（格式见 `names.example.json`），映射表可随时改，
`--reuse` 重跑即可，不必重新拟合。

`names.json` 是**本机文件**，不进仓库（`.gitignore` 已排除）：它属于你的数据，
不属于程序。除了改图上文字，它还承担一件事——**把 `Settings` 里的 `solid:<名称>`
对齐到 `Data` 表的名称**。如果你在 `Data` 表写 `Todorokite`、而 `Settings` 里写成
中文原名，没有映射就认不出是同一组，固液比会静默丢失、qe 退化成 mg/L(悬浮液)。
遇到单位不对，先查这里；不想要映射就在两边都写同一个名字。

配色不写死：脚本按数据里实际出现的吸附剂名排序后分派色板与标记，未登记的名称用
名称哈希兜底，因此换体系时颜色不会重复、也不会每次运行变一个样。

**图内与报告正文都不放警示文字**：模型触界、Stage II 斜率为负、logistic 不收敛、
低负载点截断这类判断只打印在运行窗口与 `run.log` 里，报告正文保持成品形态。
逐点的可疑值（负吸附、Ce > C0、吸附率 > 100%）仍会进「数据质量清单」表——
那是数据本身的问题，需要逐条核对。

---

## 8. 拟合可靠性怎么判

不要只看 R²。报告第七节按四条判据给出「能不能引用」：

| 判据 | 含义 |
|---|---|
| 参数触界 / max\|r\| > 0.99 | 参数不可分辨，qmax 之类的数值没有物理意义 |
| 多起点收敛率 < 0.5 | 目标函数有多个等价极小，解不唯一 |
| R² < 0.5 | 模型不适定，只报告趋势 |
| ΔAICc ≤ 2 | 与最优模型无实质差别，不能宣称「最优」 |

AICc 而非 R² 用于选模型：多一个参数必然抬高 R²，AICc 会惩罚这一点。
等温线候选 7 个（Langmuir、Freundlich、Temkin、D-R、Sips、Toth、Redlich–Peterson，
其中 D-R 需要摩尔质量），动力学 5 个（PFO、PSO、Elovich、Avrami、Bangham）。

与 MATLAB 的一致性用全模型复核脚本 `output/matlab_verify.m` 验证：每次 `run` 自动生成，
覆盖本次数据的全部模型与全部实测点，在 MATLAB 中跑 `matlab_verify` 即可逐模型比对 SSE
（判读标准见报告第六节）。

---

## 9. 目录结构

```
分析/
├─ README.md                  ← 唯一入口文档（本文件）
├─ adsorp.bat                 ← Windows 一键入口（双击 / cmd）
├─ adsorp.ps1                 ← PowerShell 入口（与 bat 等价）
├─ run_analysis.py            ← 兼容入口（沿用旧的 python run_analysis.py 写法）
├─ config.json                ← 固液比 / 数据目录 / 默认值
├─ names.example.json         ← 名称映射的示例格式（要用时复制成 names.json）
├─ requirements.txt · pyproject.toml
│
├─ adsorp/                    ← 程序包：只放会被 import 的代码
│  ├─ io.py                   仪器原始工作簿解析
│  ├─ template.py             模板读写与导出
│  ├─ models.py               12 个模型方程与初值/边界
│  ├─ fit.py                  有界 TRF 多起点拟合、AICc
│  ├─ analyze.py              三类实验的预处理、拟合、诊断
│  ├─ style.py                出版级样式
│  ├─ viz.py                  6 张图
│  ├─ report.py               HTML + Excel 输出
│  ├─ pipeline.py             流程编排与缓存
│  ├─ matlab.py               MATLAB 复核脚本生成
│  └─ cli.py                  命令行
│
├─ output/                    ← 唯一成果目录，每次 run 整目录覆盖
│  ├─ 报告.html · 报告.pdf · 结果汇总.xlsx
│  ├─ _analysis.pkl           拟合缓存（--reuse 用）
│  ├─ figures/                PNG + PDF + figures_en.zip
│  └─ tables/                 11 个 CSV
│
├─ data/                      ← 输入数据：放这里，或直接放项目根目录
│  └─ README.md              投放说明与类型判断规则
│
├─ templates/
│  └─ 吸附数据模板.xlsx        ← 空白模板（adsorp.bat template 生成于此）
│
├─ docs/
│  ├─ 命令速查.txt
│  └─ reference/              ← MATLAB 独立实现（交叉验证用）
│
├─ _archive/                  ← 归档区：仅本机，不随仓库同步
│  ├─ README.md               归档清单与恢复方法
│  ├─ personal/               旧实验记录、审查报告、个人名称映射
│  ├─ verify_2026-10-21/      回归验证输出
│  └─ code/                   改版前的 style.py / viz.py 备份
│
├─ .gitignore · .git/
└─ .workbuddy/                编辑器会话数据（不参与版本管理）
```

根目录只有 9 个文件 + 6 个目录：入口（`README` / `adsorp.bat` / `adsorp.ps1` /
`run_analysis.py`）、配置（`config.json` / `names.example.json` / `requirements.txt` /
`pyproject.toml`），以及 `adsorp` `output` `data` `templates` `docs` `_archive`。

### 9.1 归类规则：新文件该放哪

| 文件类型 | 放哪 | 判断标准 |
|---|---|---|
| 会被 `import` 的 .py | `adsorp/` | 在调用链上，删了会报 ImportError |
| 回退/对照用的旧 .py | `_archive/code/` | 没有任何文件 import 它 |
| 新的仪器原始工作簿 | `data/` | 文件名含「等温 / 动力学 / 吸附边」 |
| 单份待分析数据 | 根目录或 `data/` 均可 | 用 `--template` 显式给路径 |
| 空白模板、导出的示例 | `templates/` | `template`、`export` 的默认输出位置 |
| 方案、核查、说明 | `docs/` | 只给人看，不参与运行 |
| 图 / 表 / 报告 | `output/` | 只由 `run` 写入，不手工放 |
| 历史产物、验证输出 | `_archive/` | 留证据但不再使用 |

三条硬规则：

1. **`output/` 只由程序写。** 每次 `run` 覆盖同名文件，手工放进去的东西会丢。
2. **`adsorp/` 只放会 import 的代码。** 备份一律进 `_archive/code/`，否则会被打包、编译、误 import。
3. **根目录只留每天都碰的东西。** 拿不准时问一句：这个文件我一周内会打开吗？
   不会就进 `data/`、`docs/` 或 `_archive/`。

### 9.2 归档、缓存与隐藏策略

- **归档不删除。** `_archive/` 保留原文件名与目录结构，随时可搬回；已写进 `.gitignore`，
  不随仓库同步。旧代码备份已从 git 索引移除（`git rm --cached`），但历史提交里仍可用
  `git show 上一提交:adsorp/style.py` 找回。
- **缓存直接清。** `__pycache__/`、`*.pyc` 首次运行自动重建，删除零风险。
- **不设 Windows 隐藏属性。** `.git`、`.workbuddy` 用点前缀，`_archive` 用下划线前缀表达
  「非主线」；隐藏属性与 git 不同步，换台机器就失效，反而容易忘记它占的空间。
  确实要隐藏：cmd 里 `attrib +h _archive`，取消用 `attrib -h _archive`。

### 9.3 日常三步

```powershell
cd "C:\path\to\分析"
.\adsorp.bat run          # 1. 读 data/ 出结果
.\adsorp.bat run --reuse  # 2. 调图版式：只重绘，不重拟合
```

换新数据：把工作簿放进 `data/` 或项目根目录（同类有多个文件时只取文件名第一个并给出提示），
或存成模板后用 `--template 路径` 指定。

---

## 10. 环境

```bash
pip install -r requirements.txt
```

依赖：pandas ≥ 2.0、numpy ≥ 1.24、scipy ≥ 1.10、matplotlib ≥ 3.7、openpyxl ≥ 3.1
（读 `.xls` 另需 `xlrd`）。已在 Python 3.13 + pandas 3.0.6 + numpy 2.5.4 + scipy 1.18.1
+ matplotlib 3.11.2 下验证。

字体：全图统一 Times New Roman——包括 mathtext 公式（`mathtext.fontset=custom`，
`C_e`、`Q_t`、`t^0.5`、`R²` 都是新罗马），刻度、图例、面板标题同款。
中文标题回退到宋体，且不含 `$...$`（custom 字体集不带 CJK 字形）。

编码：`adsorp.bat` 与 `adsorp.ps1` 会设置 `PYTHONUTF8=1`，日志与报告统一 UTF-8；
bat 本身保持纯 ASCII（cmd 按 OEM 代码页解析批处理，非 ASCII 会乱码），
ps1 存为 UTF-8 **带 BOM**（否则 Windows PowerShell 5.1 读中文会乱码）。
自行修改这两个脚本时请保持该编码。
