package calendar_test

import (
	"testing"

	"schedule_manager_go/internal/calendar"
)

func TestBusinessDaysExcludesWeekendAndHolidays(t *testing.T) {
	// 2026-01 上旬: 1(木)〜10(土)。祝日 1/1 と土日除外。
	holidays := []string{"2026-01-01"}
	got, err := calendar.BusinessDays("2026-01", 1, holidays)
	if err != nil {
		t.Fatal(err)
	}
	// 1/1 祝日, 1/3土, 1/4日 除外 → 平日 2,5,6,7,8,9 = 6
	if got != 6 {
		t.Fatalf("business days = %d, want 6", got)
	}
}

func TestAllocationStatus(t *testing.T) {
	if s := calendar.AllocationStatus(8, 10, 80); s != "" {
		t.Fatalf("got %q", s)
	}
	if s := calendar.AllocationStatus(8.1, 10, 80); s != "warn" {
		t.Fatalf("got %q", s)
	}
	if s := calendar.AllocationStatus(10, 10, 80); s != "over" {
		t.Fatalf("got %q", s)
	}
}

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

func TestRoundEffort(t *testing.T) {
	if v := calendar.RoundEffort(1.05); v != 1.1 {
		t.Fatalf("got %v", v)
	}
	if !calendar.IsValidEffort(1.1) || calendar.IsValidEffort(1.11) {
		t.Fatal("effort validation failed")
	}
}
