package calendar_test

// このファイルは Go 標準の単体テストの例です。
//
// 実行方法（powered_by_golang ディレクトリで）:
//
//	go test ./internal/calendar/     # このパッケージだけ
//	go test ./...                    # モジュール内すべて
//	go test -v ./internal/calendar/  # 各テスト名も表示
//
// 命名ルール:
//   - ファイル名は必ず *_test.go（これ以外はテストとして認識されない）
//   - 関数名は Test で始め、引数は (t *testing.T) のみ
//   - パッケージ名を calendar_test にすると「外部テスト」になり、
//     本番コードと同じように import 経由で公開 API だけを検証できる
//     （package calendar にすると同じパッケージ内の未公開関数も呼べる）

import (
	"testing"

	"schedule_manager_go/internal/calendar"
)

// TestBusinessDaysExcludesWeekendAndHolidays は営業日計算の典型ケース。
// 失敗時は t.Fatal / t.Fatalf でテストをその場で打ち切る（残り行は実行しない）。
func TestBusinessDaysExcludesWeekendAndHolidays(t *testing.T) {
	// 2026-01 上旬: 1(木)〜10(土)。祝日 1/1 と土日除外。
	holidays := []string{"2026-01-01"}
	got, err := calendar.BusinessDays("2026-01", 1, holidays)
	if err != nil {
		// t.Fatal は引数をそのまま表示して終了。エラー値の確認によく使う。
		t.Fatal(err)
	}
	// 1/1 祝日, 1/3土, 1/4日 除外 → 平日 2,5,6,7,8,9 = 6
	if got != 6 {
		// t.Fatalf は fmt.Printf と同じ書式でメッセージを作れる。
		t.Fatalf("business days = %d, want 6", got)
	}
}

// TestAllocationStatus は複数の入力を同じ関数内で続けて検証する例。
// テーブル駆動テスト（[]struct でケースを回す）にしてもよいが、
// ケースが少ないときはこの書き方でも十分。
func TestAllocationStatus(t *testing.T) {
	// 割当 8 / キャパ 10 / 計画稼働率 80% → 閾値 8.0 ちょうどなので警告なし
	if s := calendar.AllocationStatus(8, 10, 80); s != "" {
		t.Fatalf("got %q", s)
	}
	// 8.1 は閾値超え → warn
	if s := calendar.AllocationStatus(8.1, 10, 80); s != "warn" {
		t.Fatalf("got %q", s)
	}
	// キャパ到達 → over
	if s := calendar.AllocationStatus(10, 10, 80); s != "over" {
		t.Fatalf("got %q", s)
	}
}

// TestIsPeriodInRange はポインタ引数（「未設定は nil」）の扱いを示す例。
// 本番 API が *string / *int を取るので、テストでも変数のアドレスを渡す。
func TestIsPeriodInRange(t *testing.T) {
	startYM, endYM := "2026-02", "2026-03"
	startD, endD := 2, 1
	if !calendar.IsPeriodInRange("2026-02", 2, &startYM, &startD, &endYM, &endD) {
		t.Fatal("start should be in range")
	}
	if calendar.IsPeriodInRange("2026-02", 1, &startYM, &startD, &endYM, &endD) {
		t.Fatal("before start should be out")
	}
}

// TestRoundEffort は「期待どおり」と「不正を弾く」の両方を見る例。
func TestRoundEffort(t *testing.T) {
	if v := calendar.RoundEffort(1.05); v != 1.1 {
		t.Fatalf("got %v", v)
	}
	// 1.1 は 0.1 刻みとして妥当、1.11 は不正、という対になる条件。
	if !calendar.IsValidEffort(1.1) || calendar.IsValidEffort(1.11) {
		t.Fatal("effort validation failed")
	}
}
