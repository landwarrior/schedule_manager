"""ソース実行時と凍結 exe 実行時のリソース・データディレクトリを解決する."""

from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    """PyInstaller で凍結した exe として実行中かを返す.

    Returns:
        bool: 凍結 exe 実行中なら True。
    """
    return bool(getattr(sys, "frozen", False))


def resource_root() -> Path:
    """読み取り専用のアプリリソース（templates / static）があるルートを返す.

    凍結 exe 実行時は PyInstaller の展開先（``sys._MEIPASS``）を指す。

    Returns:
        Path: リソースディレクトリのパス。
    """
    if is_frozen():
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent


def data_dir() -> Path:
    """schedule.db を置く書き込み可能なディレクトリを返す.

    凍結 exe 実行時は exe と同じフォルダ、ソース実行時はプロジェクトルートを指す。

    Returns:
        Path: データディレクトリのパス。
    """
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent
