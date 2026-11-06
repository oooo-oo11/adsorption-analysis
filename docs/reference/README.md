# MATLAB 参考文件

| 文件 | 用途 | 数据来源 |
|---|---|---|
| `fit_all_models.m` | 在 MATLAB 中独立读取模板，运行完整模型分析 | `CFG.data_file` 指定的 Excel；留空时按脚本头部规则自动查找模板 |
| `isotherm_fit_4models_R2024b.txt` | 保留的历史四模型对照脚本，非本工具入口 | 文件内写死的 Ce / qe 数组，不读取当前选择的数据 |

核对最近一次 Python 分析时，使用生成的 `output/matlab_verify.m`，其中内嵌本次数据及对应的拟合结果。
这些 MATLAB 参考文件不参与双击启动，不要把历史四模型脚本的输出当作当前数据集的结果。
