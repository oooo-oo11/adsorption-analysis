# Sb(V) 吸附数据分析流水线

一条命令把仪器原始数据（或填好的 Excel 模板）变成：英文出版级图件 + 自包含 HTML 报告 + Excel 汇总表。

---

## 1. 快速开始

**PowerShell 里必须写 `.\adsorp.bat`**（PowerShell 不从当前目录搜可执行文件，直接敲 `adsorp.bat` 会报“无法将…项识别为 cmdlet”）；cmd 里两者都可以。另外 `cd /d` 是 cmd 语法，PowerShell 用 `cd` 或 `Set-Location`。

```powershell
# 进入项目目录（PowerShell）
cd "C:\Users\Uers\Desktop\分析"

# 方式 A：直接读当前目录的 3 个 AFS 工作簿（既有流程）
.\adsorp.bat run

# 方式 B：读填好的 Excel 模板（推荐，含固液比等元数据）
.\adsorp.bat run --template 吸附数据_已填示例.xlsx --out output

# 只重新出图与报告，不重跑拟合（调图版式时用，约 20 秒）
.\adsorp.bat run --reuse
```

> `adsorp.bat` 会自动用项目虚拟环境的 Python，不依赖系统 PATH。
> 如果已在终端激活该环境，`python -m adsorp.cli ...` 与 `.\adsorp.bat ...` 完全等价。

Windows 下也可以直接双击 `adsorp.bat`，或在 cmd 里省略 `.\`：

```bat
cd /d C:\Users\Uers\Desktop\分析
adsorp.bat run
adsorp.bat run --template 吸附数据_已填示例.xlsx
```

产物全部在 `output/`：

| 路径 | 内容 |
|---|---|
| `报告.html` | 自包含报告（图片 base64 内嵌，单文件可转发），每张图带 PNG/PDF 下载按钮，以及可折叠的绘图代码 |
| `报告.pdf` | 报告打印版（Chrome 导出） |
| `matlab_verify.m` | **全模型复核脚本**：内含本次全部数据点，在 MATLAB 里重拟合 7 个等温线 + 5 个动力学模型，逐模型比对 SSE |
| `结果汇总.xlsx` | 11 个工作表：最优模型、全模型、IPD、平衡时间、吸附边、离子强度对比、QC、模型可靠性… |
| `figures/*.png` | 300 dpi 位图（17.2 cm 宽，可直接置入 Word） |
| `figures/*.pdf` | 矢量图（LaTeX / AI / Illustrator 可编辑） |
| `figures/figures_en.zip` | 全部图件打包 |
| `tables/*.csv` | 每张表的 CSV（utf-8-sig，Excel 直接打开不乱码） |
| `_analysis.pkl` | 拟合结果缓存，供 `--reuse` |

---

## 2. 命令一览

| 命令 | 作用 |
|---|---|
| `python -m adsorp.cli run` | 完整流程：解析 → 计算 → 拟合 → 绘图 → 报告 |
| `python -m adsorp.cli run --template 数据.xlsx` | 从模板读数据（模板里的固液比优先） |
| `python -m adsorp.cli run --solid 3` | 覆盖固液比（单一数值，适用于所有样品） |
| `python -m adsorp.cli run --no-figs` | 只出表，不绘图 |
| `python -m adsorp.cli run --reuse` | 复用上次拟合，只重绘图/报告 |
| `python -m adsorp.cli template` | 生成空白模板 `吸附数据模板.xlsx` |
| `python -m adsorp.cli check --template 数据.xlsx` | 只校验：行数、分组、缺列、异常标记 |
| `python -m adsorp.cli export --out 示例.xlsx` | 把当前已解析数据导出成"填好的模板" |
| `python -m adsorp.cli matlab --verify` | 生成全模型复核脚本 `output/matlab_verify.m`（读拟合缓存，需先 run 一次） |
| `python -m adsorp.cli matlab` | 导出 MATLAB 可粘贴的 `Ce/qe` 数组（`output/matlab_isotherm.m`） |

### MATLAB 全模型复核

每次 `run` 都会在输出目录生成 `matlab_verify.m`，把**本次数据与全部模型**打包进一个脚本：

```matlab
>> matlab_verify
```

- 覆盖 7 个等温线模型（Langmuir / Freundlich / Temkin / D-R / Sips / Toth / Redlich-Peterson）与 5 个动力学模型（PFO / PSO / Elovich / Avrami / Bangham），不只最优的那一个；
- 用 `fminsearch`（Nelder-Mead，**不需要任何工具箱**），每组 20 个起点：第 1 个用 Python 的最优参数，其余作对数扰动；
- 逐模型打印参数、SSE、R²、AICc，并与 Python 的 SSE 并排对比；`rel/% < 1e-6` 即两条独立实现收敛到同一解；
- 若 MATLAB 算出更低的 SSE，说明 Python 那组掉进了局部极小，脚本会直接把差异摆出来。

同一份脚本也可作为投稿时的补充材料（审稿人可自行复算）。

---

## 3. Excel 模板：需要填什么

### 3.1 生成模板

```bash
python -m adsorp.cli template            # 空白模板 + README 表
python -m adsorp.cli export --out 示例.xlsx   # 现有数据导出的"填好"样例
```

模板有三张表：`README`（说明）、`Data`（数据，一行 = 一个样品的一次测定）、`Settings`（全局参数与固液比）。

### 3.2 `Data` 表字段

**必填（缺了无法计算）**

| 列 | 说明 | 示例 |
|---|---|---|
| `exp` | 实验类型，三选一：`isotherm` / `kinetics` / `edge`。同一实验块可只写首行，下面留空表示沿用上一行 | `isotherm` |
| `mineral` | 矿物名，**直接用英文**（图上原样显示，不再翻译）；留空沿用上一行。新增矿物照写即可，不必改 `names.json` | `δ-MnO₂` / `Rancieite` |
| `background` | 背景电解质；留空沿用上一行。`NaNO3` 与 `NaNO₃` 会统一成后者 | `0.01 M NaNO₃` / `ASW` |
| `C0_ppm` | 初始 Sb(V) 浓度 (mg/L)。**等温线逐行必填**；动力学/吸附边可留空，按同组已有值或默认值补齐 | `6` |
| 实测值 | `Ce_ppm`（平衡浓度）或 `conc_ppb`（**标线计算/ppb，不是荧光值**，需配 `dilution`） | `0.85` / `7.24` |

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
| `solid_g_per_L` | 固液比 m/V。留空取 `Settings` 里该矿物的值 |
| `replicate` | 平行样编号，可留空。同一组同一 `C0`/`time_h`/`pH` 出现多行即按平行样合并为均值 ± SD，图上画误差棒 |
| `note` | 备注，仅供你自己看；命中关键词也只在清单里提示，不改变计算 |
| `exclude` | **唯一能剔除数据的开关**：填 `TRUE` 则该行不参与拟合与绘图 |

### 3.3 `Settings` 表

```
molar_mass_g_per_mol        121.76      # Sb
temperature_K               298.15
default_C0_kinetics         6.0         # 动力学 C0 留空时用
default_C0_edge             6.0         # 吸附边 C0 留空时用
default_dilution_isotherm   600
default_dilution_kinetics   600
default_dilution_edge       600
solid:δ-MnO₂                1.0         # g/L
solid:Rancieite             1.0
solid:Acid birnessite       3.0
solid:Alkaline birnessite   3.0
solid:Feroxyhyte            0.5
```

`solid:` 后面的名字与 `Data` 表的 `mineral` 列**逐字一致**即可（都用英文）。旧表里的中文名仍然认，脚本会按 `names.json` 的映射对齐后再取固液比。

`default_C0_*` 也可以不写，脚本会回退到 `config.json` 的 `defaults.kinetics.C0_ppm` / `defaults.edge.C0_ppm`。

固液比取自 `Mn-SbV实验.docx` 的预实验值；未列出的矿物按 mg/L(悬浮液) 处理，报告里会明确标注单位。

**字体**：模板的西文/数字为 Times New Roman、中文为宋体（与出图一致）。字体只影响显示，脚本按单元格的值读取，改字体/字号/加粗都不影响任何计算。

### 3.4 换算链

```
Ce (mg/L)  = conc_ppb × corr_factor × dilution / 1000
吸附率 (%) = 100 × (1 − Ce/C0)
qe (mg/g)  = (C0 − Ce) / (m/V)
```

---

## 4. 分析一份新数据，最少需要哪些信息

按重要性排序，前 3 项缺一不可：

1. **C0 与实测平衡浓度**（或荧光值 + 标线 + 稀释倍数 + 校正因子，让脚本自己算）。C0 在等温线中逐行必填；动力学/吸附边可留空，由 `Settings` 的 `default_C0_*` 或 `config.json` 补齐。
2. **固液比 m/V (g/L)**。没有它只能给 mg/L(悬浮液)，容量参数（qmax、K_F）无法与文献比较；强度参数（K_L、n、k）不受影响。
3. **实验类型标签**与分组键（矿物、背景电解质）。
4. 动力学：取样时间；吸附边：平衡 pH；离子强度：背景电解质的浓度。
5. 平行样编号（可留空，同条件多行自动按平行样合并）、备注（只提示不改变计算）。
6. 温度（D-R 的 E 与 Temkin 的 b_T 依赖 T，默认 298.15 K）。

仪器原始表可以直接跑，但它是"宽表 + 多标线块 + 穿插 QC"的排版，解析规则写在 `adsorp/io.py`；换仪器或换模板时，**填模板比改解析器省事**。

---

## 5. 单张图怎么拿

三个途径，都不需要联网：

1. **报告里直接下载**：打开 `output/报告.html`，每张图下方有「下载 PNG（300 dpi）」和「下载 PDF（矢量）」。链接指向 HTML 内嵌的 base64 数据，双击 HTML 即可存图，转发给合作者也不会丢图。
2. **取文件**：`output/figures/isotherm.png` / `.pdf`，命名对应 图1 等温线、图2 残差、图3 动力学、图4 IPD、图5 吸附边、图6 QC。
3. **打包**：`output/figures/figures_en.zip`（PNG + PDF 各 6 个）。

每张图下方还有一个**可折叠的「绘图代码」**（默认收起，点击标题栏展开，再点收起）：展开后是该图的绘制函数源码（`adsorp/viz.py::plot_xxx`），改图时直接照抄改，不用翻文件找对应关系。

图件全部为英文，矿物名直接用 `Data` 表里写的英文（`δ-MnO₂`、`Rancieite`、`Acid birnessite` ……）。旧的中文数据表仍可通过 `names.json` 映射成英文，映射表可随时改，`--reuse` 重跑即可，不必重新拟合。

**图内不放警示文字**：模型触界、Stage II 斜率为负、logistic 不收敛、低负载点截断等提示一律写在图注与正文的数据质量提示里，图面保持干净。

---

## 6. 拟合可靠性怎么判

不要只看 R²。报告第七节按四条判据给出"能不能引用"：

| 判据 | 含义 |
|---|---|
| 参数触界 / max\|r\| > 0.99 | 参数不可分辨，qmax 之类的数值没有物理意义 |
| 多起点收敛率 < 0.5 | 目标函数有多个等价极小，解不唯一 |
| R² < 0.5 | 模型不适定，只报告趋势 |
| ΔAICc ≤ 2 | 与最优模型无实质差别，不能宣称"最优" |

AICc 而非 R² 用于选模型：多一个参数必然抬高 R²，AICc 会惩罚这一点。本项目等温线用 7 个模型（Langmuir、Freundlich、Temkin、D-R、Sips、Toth、Redlich–Peterson），动力学 5 个（PFO、PSO、Elovich、Avrami、Bangham）。

与 MATLAB 的一致性用全模型复核脚本 `output/matlab_verify.m` 验证：每次 `run` 自动生成，
覆盖本次数据的**全部 12 个模型与全部实测点**，在 MATLAB 中跑 `matlab_verify` 即可逐模型比对 SSE
（判读标准见报告第六节）。

---

## 7. 目录结构

```
分析/
├─ adsorp/
│  ├─ io.py           仪器原始工作簿解析（合并单元格、多标线、QC、备注）
│  ├─ template.py     Excel 模板读写与导出
│  ├─ models.py       12 个模型方程与初值/边界
│  ├─ fit.py          有界 TRF 多起点拟合、AICc、置信区间、收敛率
│  ├─ analyze.py      三类实验的预处理、拟合、诊断、可靠性审计
│  ├─ style.py        出版级样式（cm 版心、Times、四边框、内向刻度）
│  ├─ viz.py          6 张图
│  ├─ report.py       HTML + Excel 输出
│  ├─ pipeline.py     流程编排与缓存
│  ├─ matlab.py       生成 MATLAB 全模型复核脚本 matlab_verify.m
│  └─ cli.py          命令行
├─ names.json         旧中文表的矿物→英文名映射（英文名直通，可留空项）
├─ config.json        默认固液比与稀释倍数
├─ requirements.txt
├─ adsorp.bat         Windows 一键入口
└─ output/
```

---

## 8. 环境

```bash
pip install -r requirements.txt
```

依赖：pandas ≥ 2.0、numpy ≥ 1.24、scipy ≥ 1.10、matplotlib ≥ 3.7、openpyxl ≥ 3.1。已在 Python 3.13 + pandas 3.0.6 + numpy 2.5.4 + scipy 1.18.1 + matplotlib 3.11.2 下验证。

字体：全图统一 Times New Roman——包括 mathtext 公式（`mathtext.fontset=custom`，`C_e`、`Q_t`、`t^0.5`、`R²` 都是新罗马），刻度、图例、面板标题同款。中文标题回退到宋体，且不含 `$...$`（custom 字体集不带 CJK 字形）。
