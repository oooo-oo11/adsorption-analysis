"""兼容入口：python run_analysis.py [--template 数据.xlsx | --data-dir 目录]

实际逻辑在 adsorp/pipeline.py；命令行子命令见 adsorp/cli.py。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

from adsorp.pipeline import run  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="吸附数据自动分析")
    ap.add_argument("--template", default=None, help="填写好的 Excel 模板")
    ap.add_argument("--data-dir", default=None, help="仪器原始工作簿目录")
    ap.add_argument("--out", default=None, help="输出目录")
    ap.add_argument("--solid", type=float, default=None, help="固液比 m/V (g/L)")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--names", default="names.json")
    ap.add_argument("--no-figs", action="store_true")
    ap.add_argument("--reuse", action="store_true", help="复用上次拟合结果，只重绘")
    args = ap.parse_args()

    run(data_dir=args.data_dir, template=args.template,
        out=args.out or "output", solid=args.solid,
        config=BASE / args.config, names_file=BASE / args.names,
        make_figs=not args.no_figs, reuse=args.reuse)


if __name__ == "__main__":
    main()
