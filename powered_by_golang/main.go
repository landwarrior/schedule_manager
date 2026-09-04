package main

import (
	"embed"
	"flag"
	"fmt"
	"net"
	"net/http"
	"os"
	"os/exec"
	"runtime"
	"time"

	"schedule_manager_go/internal/db"
	"schedule_manager_go/internal/models"
	"schedule_manager_go/internal/paths"
	"schedule_manager_go/internal/web"
)

//go:embed templates/*.html
var templateFS embed.FS

//go:embed static/*
var staticFS embed.FS

//go:generate go run github.com/tc-hib/go-winres@v0.3.3 simply --arch amd64 --icon ../assets/schedule_manager.ico --manifest cli --product-name schedule_manager --file-description schedule_manager --original-filename schedule_manager.exe --out rsrc

func main() {
	port := flag.Int("port", 0, "待ち受けポート（省略時は空きポートを自動割当）")
	browser := flag.Bool("browser", false, "起動時にブラウザを開く")
	noBrowser := flag.Bool("no-browser", false, "起動時にブラウザを開かない")
	flag.Parse()

	if *port < 0 || *port > 65535 {
		fmt.Fprintln(os.Stderr, "ポートは 0〜65535 で指定してください。")
		os.Exit(2)
	}

	conn, err := db.Open()
	if err != nil {
		fmt.Fprintf(os.Stderr, "DB 初期化に失敗しました: %v\n", err)
		os.Exit(1)
	}
	defer conn.Close()

	app, err := web.NewApp(&models.Store{DB: conn}, templateFS, staticFS)
	if err != nil {
		fmt.Fprintf(os.Stderr, "テンプレート読み込みに失敗しました: %v\n", err)
		os.Exit(1)
	}

	addr := fmt.Sprintf("127.0.0.1:%d", *port)
	ln, err := net.Listen("tcp", addr)
	if err != nil {
		fmt.Fprintf(os.Stderr, "ポートの待ち受けに失敗しました: %v\n", err)
		os.Exit(1)
	}
	actual := ln.Addr().(*net.TCPAddr).Port
	url := fmt.Sprintf("http://127.0.0.1:%d/", actual)

	openBrowser := paths.IsBuiltBinary()
	if *browser {
		openBrowser = true
	}
	if *noBrowser {
		openBrowser = false
	}

	fmt.Println("スケジュール管理（Go）を起動しました。")
	fmt.Printf("  URL: %s\n", url)
	fmt.Printf("  DB:  %s\n", db.DBPath)
	fmt.Println("終了するには、このウィンドウを閉じるか Ctrl+C を押してください。")

	if openBrowser {
		go func() {
			time.Sleep(400 * time.Millisecond)
			_ = openURL(url)
		}()
	}

	server := &http.Server{Handler: app.Handler()}
	if err := server.Serve(ln); err != nil && err != http.ErrServerClosed {
		fmt.Fprintf(os.Stderr, "サーバーエラー: %v\n", err)
		os.Exit(1)
	}
}

func openURL(url string) error {
	switch runtime.GOOS {
	case "windows":
		// start の第2引数はウィンドウタイトル。空文字を渡さないと URL がタイトル扱いになる
		return exec.Command("cmd", "/c", "start", "", url).Start()
	case "darwin":
		return exec.Command("open", url).Start()
	default:
		return exec.Command("xdg-open", url).Start()
	}
}
