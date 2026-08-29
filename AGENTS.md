# AGENTS.md

このリポジトリで作業する AI エージェント向けの指針です。ユーザー向けの機能説明は `README.md` を参照してください。

## プロジェクト概要

複数の開発プロジェクトについて、工程ごとの工数または期間を **月×旬（上旬・中旬・下旬）** のマトリクスで管理し、チームのキャパシティと照合するローカル Web アプリです。

- ランタイム: Python **3.14+** / Flask / SQLite（`schedule.db`）
- UI: Jinja2 テンプレート + `static/` の CSS / JS（フロントエンドフレームワークなし）
- 配布: PyInstaller で単一 exe（`schedule_manager.spec` / GitHub Releases）

## ディレクトリ構成

| パス | 役割 |
| --- | --- |
| `app.py` | Flask ルート・フォーム処理・起動（ポート自動割当） |
| `models.py` | DB アクセス（CRUD・割当・設定） |
| `db.py` | 接続・スキーマ・マイグレーション・初期シード |
| `calendar_util.py` | 旬・営業日・キャパ・工数バリデーション |
| `paths.py` | ソース実行 / 凍結 exe のパス解決 |
| `templates/` | Jinja2 HTML |
| `static/` | CSS / JS |
| `assets/` | アイコン等の素材 |
| `.github/workflows/release.yml` | タグ `v*` の Release 公開時に exe をビルドして添付 |

ORM は使いません。SQL は `db.py`（スキーマ）と `models.py`（クエリ）に集約します。

## ドメインの前提

- **旬**: 1=上旬(1–10日)、2=中旬(11–20日)、3=下旬(21日–月末)
- **入力方式**: `effort`（工数入力・0.1 人日刻み） / `period`（期間のみ・色表示）
- **キャパ**: 営業日（土日＋祝日マスタ除外）× メンバー人数
- **警告**: 割当合計 > キャパ × 計画稼働率 → 黄、≥ キャパ → 赤
- 工程マスタは共通定義（名称・色・表示順）。**入力方式はプロジェクト設定ごと**（`project_phases.input_mode`）
- 新規プロジェクトの初期入力方式は `legacy_key == "integration"` なら `period`、それ以外は `effort`（`_default_input_mode`）。マスタ列の `input_mode` はシード／旧移行用で実行時は参照しない

計算ロジックを変えるときは `calendar_util.py` を正とし、表示・API 側と矛盾させないこと。

## コーディング規約

- Python: `from __future__ import annotations`、型ヒント、Ruff（`pyproject.toml`）に従う
  - line-length 120、quote-style double、target py314
  - lint: E / F / I / UP / B / SIM
- UI 文言・ユーザー向けエラーは **日本語**
- 既存のレイヤ分離を崩さない（ルートに生 SQL を書かない、テンプレートに重い計算を持たない）
- スキーマ変更時は `db.py` の `CREATE` とマイグレーション（`_ensure_*` / `_migrate_*`）の両方を更新する
- `schedule.db` はローカルデータ。コミットしない（`.gitignore` 済み）
- 依存は最小限（本番は Flask のみ）。新規パッケージ追加は理由を明確にすること

## よく使うコマンド

Windows 前提。ランチャーは `py` を使う。

```bat
py -3.14 -m venv .venv
.venv\Scripts\activate.bat
pip install -r requirements.txt
pip install -e ".[dev]"
python app.py
ruff check .
ruff format .
```

exe ビルド:

```bat
pip install "pyinstaller>=6.0"
build_exe.bat
```

## エージェントへの注意

- 不要なリファクタ・ドキュメント追加・依存追加はしない。依頼範囲に集中する
- README のユーザー手順と実装がずれる変更をしたら、README も合わせて更新する
- exe / パス周りを触るときは `paths.py` と PyInstaller の凍結実行の両方を意識する
- 破壊的な git 操作や、依頼のない commit / push は行わない
