# スケジュール管理（Go 版）

Python / Flask 版と同じ機能を Go で実装したローカル Web アプリです。  
SQLite スキーマは Python 版と互換なので、`schedule.db` を共有・切り替えできます。

## 必要環境

- Go **1.22+**（推奨: インストール済みの最新安定版）

## ソースから起動

```bat
cd powered_by_golang
go run .
```

- 起動するとコンソールに URL（例: `http://127.0.0.1:xxxxx/`）が表示されます。
- ポート固定: `go run . --port 5000`
- ブラウザ自動オープン: `go run . --browser`
- 初回起動時にカレントディレクトリへ `schedule.db` が作成されます。

## 実行ファイルのビルド

```bat
cd powered_by_golang
build.bat
```

成果物は `dist\schedule_manager.exe` です。HTML / CSS / JS と **アプリアイコン**（`assets/schedule_manager.ico`、Python 版と同じ）は exe に埋め込み済みなので、このファイルだけを任意のフォルダに置いて実行できます（同じフォルダに `schedule.db` が作られます）。起動時にブラウザが自動で開きます（Python 版の exe と同様）。

```bat
dist\schedule_manager.exe
```

オプション: `--port 5000` / `--no-browser`（ブラウザを開かない） / `--browser`（`go run` 時も開く）

アイコンだけ再生成する場合:

```bat
go generate
```

## 構成

| パス | 役割 |
| --- | --- |
| `main.go` | 起動・ポート割当・ブラウザオープン・`embed` |
| `internal/calendar` | 旬・営業日・キャパ・工数バリデーション |
| `internal/db` | SQLite スキーマ・マイグレーション・初期シード |
| `internal/models` | CRUD・割当・設定 |
| `internal/web` | HTTP ルート・テンプレート描画 |
| `internal/paths` | DB パス・ビルドバイナリ判定 |
| `templates/` | HTML（ビルド時に exe へ埋め込み） |
| `static/` | CSS / JS（ビルド時に exe へ埋め込み） |

依存は `modernc.org/sqlite`（純 Go・CGO 不要）のみです。
