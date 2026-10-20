"""统一绘图风格：对齐 fig2-261008.m（MATLAB）。

要点：17.2 cm 版心、Times New Roman、四边黑色细框、刻度朝内、无网格、
彩色实心标记 + 深灰描边、紫色虚线 / 黑色实线拟合、左上角 (a)(b) 面板标号。
"""
from __future__ import annotations

import logging

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
import numpy as np
from matplotlib.ticker import LogLocator, MaxNLocator, NullLocator

from . import names as N

CM = 1.0 / 2.54

# ---- 颜色（前三个取自 fig2-261008.m）------------------------------------
SKY = (0.42, 0.74, 0.87)
MAUVE = (0.74, 0.44, 0.61)
PURPLE = (0.63, 0.29, 0.95)
INK = (0.10, 0.10, 0.10)
GRAY = (0.70, 0.70, 0.70)
EDGE = (0.35, 0.35, 0.35)
TEAL = (0.13, 0.52, 0.52)
SAGE = (0.55, 0.71, 0.55)
SAND = (0.85, 0.68, 0.42)
SLATE = (0.47, 0.55, 0.75)

# 键一律用**图上显示的英文名**（与模板里的 mineral 列一致）；中文旧表由
# ``mineral_color`` 经 names 映射兜底，所以两种写法都能取到颜色。
MINERAL_COLOR = {
    "Feroxyhyte": SKY,
    "δ-MnO₂": MAUVE,
    "Rancieite": SAGE,
    "Acid birnessite": SAND,
    "Alkaline birnessite": SLATE,
}

BG_COLOR = {
    "0.001 M NaNO₃": SKY,
    "0.01 M NaNO₃": MAUVE,
    "0.1 M NaNO₃": SAGE,
    "ASW": SAND,
}

BG_MARKER = {"0.001 M NaNO₃": "^", "0.01 M NaNO₃": "o",
             "0.1 M NaNO₃": "D", "ASW": "s"}


def mineral_color(name: str):
    """矿物配色：先按显示名查，再经 names 映射查（兼容中文数据表）。"""
    key = N.mineral(name)
    return MINERAL_COLOR.get(key, MINERAL_COLOR.get(str(name), INK))

MODEL_COLOR = {
    "pfo": PURPLE, "langmuir": PURPLE,
    "pso": INK, "freundlich": INK,
}
MODEL_LS = {"pfo": "--", "langmuir": "--", "pso": "-", "freundlich": "-"}

MODEL_LABEL = {
    "pfo": "Pseudo first order kinetic model",
    "pso": "Pseudo second order kinetic model",
    "langmuir": "Langmuir",
    "freundlich": "Freundlich",
    "temkin": "Temkin",
    "dr": "Dubinin–Radushkevich",
    "sips": "Sips",
    "toth": "Toth",
    "rp": "Redlich–Peterson",
    "elovich": "Elovich",
    "avrami": "Avrami",
    "bangham": "Bangham",
}

# 图例用短标签：面板只有 8 cm 宽，长标签必然压住数据
MODEL_LABEL_SHORT = {
    "pfo": "PFO model",
    "pso": "PSO model",
    "langmuir": "Langmuir",
    "freundlich": "Freundlich",
    "temkin": "Temkin",
    "dr": "D–R model",
    "sips": "Sips",
    "toth": "Toth",
    "rp": "R–P model",
    "elovich": "Elovich",
    "avrami": "Avrami",
    "bangham": "Bangham",
}

MARKER_SIZE = 6.4
FIT_LW = 1.45
AXIS_LW = 0.90
ERR_LW = 0.80
FONT_TICK = 9.0
FONT_LABEL = 10.5
FONT_LEGEND = 8.4
FONT_PANEL = 11.2
FONT_COND = 8.9

# 面板标题两行之间的间距（轴高比例）。11.2 pt 的标题约占 0.07 个轴高，
# 原来取 0.068 时两行几乎贴在一起，改成 0.108 留出约一个字高的空隙。
TITLE_GAP = 0.108

# 坐标轴从 0 起画时，给 0 留一点余量：数据点与刻度数字不再压在框线上。
# 取量程的 3%，视觉上几乎看不出来，但 0 会明显离开左下角。
ZERO_PAD = 0.030


def ylim0(top: float, *, pad: float = ZERO_PAD) -> tuple[float, float]:
    """y 轴从 0 起画时的范围：下限略低于 0，让 0 刻度"抬"离底框。"""
    top = float(top)
    return (-abs(pad) * top, top)


def xlim0(left: float, right: float, *, pad: float = ZERO_PAD) -> tuple[float, float]:
    """x 轴从 0 起画时的范围：上限不动，下限略低于 0（0 刻度"挪"离左边框）。"""
    left, right = float(left), float(right)
    if abs(left) > 1e-12:
        return (left, right)
    return (-abs(pad) * (right - left), right)


def ylim_data(lo: float, hi: float, *, pad: float = ZERO_PAD) -> tuple[float, float]:
    """按数据实际范围给 y 轴，负值一律画进框内。

    数据非负时等价于 :func:`ylim0`（0 刻度抬离底框）；一旦出现负吸附之类的
    负值，下限跟着数据走，脚本不把点裁到框外——是否剔除由使用者在模板里决定。
    """
    lo, hi = float(lo), float(hi)
    if not np.isfinite(lo) or not np.isfinite(hi):
        return (0.0, 1.0)
    if lo >= 0:
        return ylim0(hi, pad=pad)
    span = hi - lo
    if not np.isfinite(span) or span <= 0:
        span = max(abs(hi), abs(lo), 1.0)
    return (lo - 0.06 * span, hi + 0.04 * span)


def apply():
    # 字体回退链：Times New Roman 承担拉丁/希腊字母与 Unicode 下标（₂₃₄），
    # 中文落到 SimSun，最后的 DejaVu Serif 兜底。注意两点：
    #   1) 回退链必须写在 font.family 里；用 "serif" 通用别名只会解析成单个字体；
    #   2) mathtext 默认走 STIX（不是 Times），公式里的 C_e、Q_t、t^0.5 会明显
    #      比正文粗一号而且字形不同。这里改成 custom + 显式指定 Times New Roman，
    #      让 $...$ 里的字母、数字、希腊字母也全部是新罗马。
    #      代价是 mathtext 不再带 CJK 字形，所以含中文的字符串仍然禁止出现 $...$
    #      （见 chem / panel_label 里的兜底）。
    plt.rcParams.update({
        "font.family": ["Times New Roman", "SimSun", "DejaVu Serif"],
        "font.serif": ["Times New Roman", "SimSun", "DejaVu Serif"],
        "mathtext.fontset": "custom",
        "mathtext.rm": "Times New Roman",
        "mathtext.it": "Times New Roman:italic",
        "mathtext.bf": "Times New Roman:bold",
        "mathtext.sf": "Times New Roman",
        "mathtext.default": "it",
        "font.size": FONT_TICK,
        "axes.labelsize": FONT_LABEL,
        "axes.labelweight": "bold",
        "axes.titlesize": FONT_PANEL,
        "axes.linewidth": AXIS_LW,
        "axes.unicode_minus": False,
        "xtick.labelsize": FONT_TICK,
        "ytick.labelsize": FONT_TICK,
        "legend.fontsize": FONT_LEGEND,
        "figure.facecolor": "white",
        "savefig.facecolor": "white",
        "figure.dpi": 150,
        "savefig.dpi": 300,
    })
    # SimSun 没有 bold 字面，matplotlib 会退回常规字重并打一条 findfont 日志；
    # 属预期行为，压到 ERROR 以免每次画图都刷屏。
    logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)


def new_grid(n_panels: int, ncols: int = 2, width_cm: float = 17.2,
             panel_h_cm: float = 6.5, *, height_cm: float | None = None,
             bottom: float | None = None, top: float | None = None):
    nrows = int(-(-n_panels // ncols))
    height = height_cm if height_cm else panel_h_cm * nrows + 1.0
    fig, axes = plt.subplots(nrows, ncols, squeeze=False,
                             figsize=(width_cm * CM, height * CM))
    for ax in axes.ravel()[n_panels:]:
        ax.axis("off")
    fig.subplots_adjust(
        left=0.085, right=0.985,
        top=top if top is not None else (0.955 if nrows == 1 else 0.965),
        bottom=bottom if bottom is not None else (0.135 if nrows == 1 else 0.085),
        wspace=0.30, hspace=0.34)
    return fig, axes


def panel_label(ax, letter: str, name: str = "", cond: str = "", y: float = 0.975):
    """左上角面板标号：(a) 矿物名 + 次行实验条件。

    条件单独占一行，避免 "(a) 钙锰矿 | 0.01 M NaNO₃" 这种长标题横跨大半个
    面板、把右上角的图例位置挤掉。

    两行间距用 ``TITLE_GAP``（轴高比例）控制：11.2 pt 的标题行高约
    0.07 个轴高，取 0.068 时两行几乎贴在一起，这里留到 0.108。
    """
    # 白色描边晕：线性时间轴下早期高吸附点可能顶到标题行，
    # 细晕让文字在任何底色上都可读，视觉上仍是无底框的纯文字。
    halo = [pe.withStroke(linewidth=2.6, foreground="white")]
    txt = f"({letter})"
    if name:
        txt += f"  {name}"
    # 兜底：含中文的标题若残留 $...$，mathtext 会缺 CJK 字形（custom 字体集
    # 只挂了 Times New Roman），这里直接把定界符去掉，退回普通文本渲染。
    if has_cjk(txt) and "$" in txt:
        txt = txt.replace("$", "").replace("{", "").replace("}", "")
    ax.text(0.03, y, txt, transform=ax.transAxes, ha="left", va="top",
            fontsize=FONT_PANEL, fontweight="bold", zorder=10, path_effects=halo)
    marks = [ax.texts[-1]]
    if cond:
        ax.text(0.03, y - TITLE_GAP, str(cond), transform=ax.transAxes,
                ha="left", va="top", fontsize=FONT_COND, color=INK, zorder=10,
                path_effects=halo)
        marks.append(ax.texts[-1])
    ax._wb_titles = marks


def axis(ax, xlabel: str, ylabel: str, *, xscale: str = "linear",
         xlim=None, ylim=None, xticks=None, yticks=None, n_yticks: int = 5):
    ax.set_xscale(xscale)
    ax.set_xlabel(xlabel, fontsize=FONT_LABEL, fontweight="bold")
    ax.set_ylabel(ylabel, fontsize=FONT_LABEL, fontweight="bold")

    if xlim is not None:
        ax.set_xlim(*xlim)
    if ylim is not None:
        ax.set_ylim(*ylim)
    if xticks is not None:
        ax.set_xticks(xticks)
    if yticks is not None:
        ax.set_yticks(yticks)
    else:
        ax.yaxis.set_major_locator(MaxNLocator(nbins=n_yticks, prune=None))
        # 用 ylim0 把下限拉到 0 以下时，MaxNLocator 偶尔会补一个负刻度；
        # 吸附量/浓度没有负刻度，直接剔掉。但残差图是 ±lim 对称轴，
        # 负刻度必须保留——用"负半轴是否只占一小段"来区分这两种情形。
        if ylim is not None and ylim[0] < 0 and -ylim[0] < 0.2 * (ylim[1] - ylim[0]):
            loc = ax.yaxis.get_major_locator()
            vals = [v for v in loc.tick_values(ylim[0], ylim[1]) if v >= -1e-12]
            if vals:
                ax.set_yticks(vals)

    if xscale == "log":
        ax.xaxis.set_major_locator(LogLocator(base=10, numticks=6))
        ax.xaxis.set_minor_locator(NullLocator())
    ax.yaxis.set_minor_locator(NullLocator())

    for s in ax.spines.values():
        s.set_visible(True)
        s.set_color("black")
        s.set_linewidth(AXIS_LW)
    ax.tick_params(axis="both", which="major", direction="in",
                   length=3.2, width=AXIS_LW, labelsize=FONT_TICK,
                   top=False, right=False)
    ax.tick_params(which="minor", bottom=False, left=False)
    ax.grid(False)
    ax.set_facecolor("white")


def data_marker(ax, x, y, mineral: str, background: str, *, yerr=None,
                label: str | None = None, zorder: int = 5):
    color = mineral_color(mineral)
    marker = BG_MARKER.get(background, "o")
    if yerr is not None:
        yerr = list(yerr)
        ax.errorbar(x, y, yerr=yerr, fmt="none", ecolor=GRAY,
                    elinewidth=ERR_LW, capsize=4.0, capthick=ERR_LW,
                    zorder=zorder - 1)
    ax.plot(x, y, linestyle="none", marker=marker,
            markersize=MARKER_SIZE, markerfacecolor=color,
            markeredgecolor=EDGE, markeredgewidth=0.8,
            label=label, zorder=zorder)


def model_line(ax, x, y, key: str, *, zorder: int = 3):
    """画一条模型曲线。图例只写模型名，不标 (best)——最优与否由表格给出。"""
    color = MODEL_COLOR.get(key, TEAL)
    ls = MODEL_LS.get(key, "-")
    label = MODEL_LABEL_SHORT.get(key, key)
    ax.plot(x, y, color=color, linestyle=ls, linewidth=FIT_LW,
            label=label, zorder=zorder)


def _points_axes(ax):
    """把轴内所有已绘制点（折线 + 散点 + 误差棒）换算到轴坐标 (0–1)。"""
    chunks = []
    for ln in ax.lines:
        x = np.asarray(ln.get_xdata(), float).ravel()
        y = np.asarray(ln.get_ydata(), float).ravel()
        n = min(x.size, y.size)
        if n:
            chunks.append(np.column_stack([x[:n], y[:n]]))
    for coll in ax.collections:
        try:
            off = np.asarray(coll.get_offsets(), float).reshape(-1, 2)
        except Exception:
            continue
        if off.size:
            chunks.append(off)
    if not chunks:
        return np.empty((0, 2))
    xy = np.vstack(chunks)
    xy = xy[np.isfinite(xy).all(axis=1)]
    if not xy.size:
        return np.empty((0, 2))
    return ax.transAxes.inverted().transform(ax.transData.transform(xy))


def _rect(loc: str, w: float, h: float, pad: float = 0.025,
          top: float | None = None):
    """候选图例框。``top`` 用于把上方的两个候选压到面板标号下方。"""
    y_top = (1 - pad) if top is None else min(1 - pad, top)
    return {
        "lower right": (1 - w - pad, pad, 1 - pad, pad + h),
        "upper right": (1 - w - pad, y_top - h, 1 - pad, y_top),
        "lower left": (pad, pad, pad + w, pad + h),
        "upper left": (pad, y_top - h, pad + w, y_top),
    }[loc]


# 左上角固定留给面板标号 (a)(b)…，永远不放图例
CORNERS = ("lower right", "upper right", "lower left")
LEG_W, LEG_H = 0.46, 0.34


def _title_rects(ax):
    """面板标题占用的轴坐标矩形（用于避免图例/注释压在标题上）。"""
    out = []
    try:
        renderer = ax.figure.canvas.get_renderer()
    except Exception:
        return out
    inv = ax.transAxes.inverted()
    for t in getattr(ax, "_wb_titles", []):
        try:
            bb = t.get_window_extent(renderer)
        except Exception:
            continue
        (x0, y0), (x1, y1) = inv.transform([[bb.x0, bb.y0], [bb.x1, bb.y1]])
        out.append((x0 - 0.01, y0 - 0.01, x1 + 0.01, y1 + 0.01))
    return out


def best_loc(ax, w: float = LEG_W, h: float = LEG_H, order=CORNERS, avoid=()):
    """在候选角里挑一个被数据点占用最少的（同等条件下按 order 优先）。

    必须在该轴的 xlim/ylim 定稿之后调用。``avoid`` 是需绕开的矩形列表；
    面板标题的包围盒总会被绕开，避免文字互相压住。
    """
    pts = _points_axes(ax)
    titles = _title_rects(ax)
    blockers = list(avoid) + titles
    # 面板标号占住左上角，上方两个候选一律压到标号下沿以下，
    # 否则 (d) Acid birnessite 这类两行标题会和图例首行并排挤在一起。
    top = (min(t[1] for t in titles) - 0.012) if titles else None
    best, score = order[0], None
    for loc in order:
        x0, y0, x1, y1 = _rect(loc, w, h, top=top)
        inside = 0
        if len(pts):
            inside = int(np.sum((pts[:, 0] >= x0) & (pts[:, 0] <= x1) &
                                (pts[:, 1] >= y0) & (pts[:, 1] <= y1)))
        for ax0, ay0, ax1, ay1 in blockers:
            if not (x1 < ax0 or x0 > ax1 or y1 < ay0 or y0 > ay1):
                inside += 1000
        if score is None or inside < score:
            best, score = loc, inside
    return best


def legend(ax, loc: str | None = None, ncol: int = 1, handles=None):
    if loc is None:
        loc = best_loc(ax)
    ax.legend(handles=handles, loc=loc, frameon=False, fontsize=FONT_LEGEND,
              handlelength=2.2, borderaxespad=0.35, ncol=ncol,
              labelspacing=0.28, handletextpad=0.55)
    return loc


def save(fig, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, bbox_inches="tight", pad_inches=0.035)
    fig.savefig(path.with_suffix(".pdf"), bbox_inches="tight", pad_inches=0.035)
    plt.close(fig)


def chem(s: str) -> str:
    """化学式/矿物名的显示文本。

    刻意保持纯 Unicode（如 ``δ-MnO₂``）而不转成 ``$\\delta$-MnO$_2$``：
    mathtext 只走 STIX 字体集，一旦整串被 ``$...$`` 接管，其中的中文矿物名
    就会因为缺字形被替换成方框。Unicode 下标则能由字体回退链正常渲染
    （Times New Roman 本身含 ₂₃₄）。若传入的是 mathtext 形式，这里反向
    还原成 Unicode，避免调用处两种写法混用。
    """
    s = str(s)
    s = s.replace("$_2$", "₂").replace("$_3$", "₃").replace("$_4$", "₄")
    return s


def has_cjk(s: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in str(s))

