"""打包交付：生成 dist/吸附分析工具/ 与同名 zip。

只带程序本体、模板、文档与便携 Python；个人数据（data/*.xlsx、names.json、
output/、_archive/）一律不进包。

用法：
    python build_package.py            # 打包
    python build_package.py --no-python  # 不带便携解释器（对方自己装 Python）

便携 Python 的生成方式（一次性，已随包提供）：
    1. 下载 python-3.13.9-embed-amd64.zip 解压到 python/
    2. python312._pth 改为：
           python313.zip
           .
           Lib\\site-packages
           ..
           import site
       （.. 是项目根，让 -m adsorp.cli 能找到包）
    3. python\\python.exe get-pip.py
    4. python\\python.exe -m pip install -r requirements.txt
"""
from __future__ import annotations

import argparse
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
NAME = "吸附分析工具"

# 根目录下的单文件
FILES = ["README.md", "开始使用.txt", "adsorp.bat", "adsorp.ps1", "run_analysis.py",
         "config.json", "names.example.json", "requirements.txt", "pyproject.toml",
         "build_package.py"]
# 整体复制的目录
DIRS = ["adsorp", "docs", "templates"]
# 逐项复制（只带说明与空白模板，不带任何实测数据）
PICKS = ["data/README.md"]


def _ignore(_dir, names):
    skip = {"__pycache__", ".pytest_cache"}
    return [n for n in names if n in skip or n.endswith((".pyc", ".pyo"))]


def build(with_python: bool = True, out_dir: Path | None = None) -> Path:
    # 每次生成带时间戳的目录，避免覆盖上一次（也避免批量删除被安全策略拦下）
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    dist = BASE / "dist"
    pkg = dist / f"{NAME}_{stamp}"
    if pkg.exists():
        sys.exit(f"{pkg} 已存在，请稍后重试或手动改名。")
    pkg.mkdir(parents=True)

    for name in FILES:
        src = BASE / name
        if src.exists():
            shutil.copy2(src, pkg / name)
        else:
            print(f"  ! 缺少 {name}，已跳过")
    for name in DIRS:
        src = BASE / name
        if src.exists():
            shutil.copytree(src, pkg / name, ignore=_ignore)
    for rel in PICKS:
        src = BASE / rel
        if src.exists():
            (pkg / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, pkg / rel)

    if with_python:
        src = BASE / "python"
        if not src.exists():
            sys.exit("找不到 python/ 目录。先按文件头的步骤生成便携解释器，"
                     "或用 --no-python 打一个不含解释器的包。")
        print("  复制便携 Python（约 370 MB，要一会儿）…")
        shutil.copytree(src, pkg / "python")
    else:
        # 没有 python/ 时，启动脚本会回退到系统 Python
        pass

    (pkg / "output").mkdir(exist_ok=True)

    zpath = dist / f"{NAME}_{stamp}{'' if with_python else '_lite'}.zip"
    if zpath.exists():
        zpath.unlink()
    root_len = len(str(pkg)) + 1
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p in sorted(pkg.rglob("*")):
            if p.is_file():
                z.write(p, Path(NAME) / str(p)[root_len:])
    size = zpath.stat().st_size / 1024 / 1024
    print(f"\n目录：{pkg}")
    print(f"压缩包：{zpath}  ({size:.0f} MB)")
    return zpath


def main():
    ap = argparse.ArgumentParser(description="打包交付用的分析工具")
    ap.add_argument("--no-python", action="store_true", help="不带便携 Python")
    a = ap.parse_args()
    build(with_python=not a.no_python)


if __name__ == "__main__":
    main()
