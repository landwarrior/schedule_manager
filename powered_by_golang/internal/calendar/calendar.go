package calendar

import (
	"fmt"
	"math"
	"strconv"
	"strings"
	"time"
)

var DecadeLabels = map[int]string{
	1: "上旬",
	2: "中旬",
	3: "下旬",
}

var PhaseInputModes = []string{"period", "effort"}

var PhaseColors = []string{"cyan", "orange", "green", "lavender"}

var PhaseColorLabels = map[string]string{
	"cyan":     "水色",
	"orange":   "橙色",
	"green":    "緑色",
	"lavender": "藤色",
}

// DefaultPhase is (legacyKey, name, inputMode, color, sortOrder).
type DefaultPhase struct {
	LegacyKey string
	Name      string
	InputMode string
	Color     string
	SortOrder int
}

var DefaultPhases = []DefaultPhase{
	{LegacyKey: "design", Name: "設計", InputMode: "effort", Color: "cyan", SortOrder: 1},
	{LegacyKey: "impl", Name: "実装", InputMode: "effort", Color: "cyan", SortOrder: 2},
	{LegacyKey: "unit", Name: "単体テスト", InputMode: "effort", Color: "cyan", SortOrder: 3},
	{LegacyKey: "integration", Name: "結合試験", InputMode: "period", Color: "orange", SortOrder: 4},
	{LegacyKey: "release", Name: "本番リリース", InputMode: "effort", Color: "cyan", SortOrder: 5},
}

func DecadeDayRange(year, month, decade int) (int, int, error) {
	lastDay := time.Date(year, time.Month(month)+1, 0, 0, 0, 0, 0, time.UTC).Day()
	switch decade {
	case 1:
		return 1, min(10, lastDay), nil
	case 2:
		return 11, min(20, lastDay), nil
	case 3:
		return 21, lastDay, nil
	default:
		return 0, 0, fmt.Errorf("invalid decade: %d", decade)
	}
}

func ParseYM(ym string) (int, int, error) {
	parts := strings.Split(ym, "-")
	if len(parts) != 2 {
		return 0, 0, fmt.Errorf("月の形式が不正です（YYYY-MM）")
	}
	year, err := strconv.Atoi(parts[0])
	if err != nil {
		return 0, 0, fmt.Errorf("月の形式が不正です（YYYY-MM）")
	}
	month, err := strconv.Atoi(parts[1])
	if err != nil {
		return 0, 0, fmt.Errorf("月の形式が不正です（YYYY-MM）")
	}
	return year, month, nil
}

func FormatYM(year, month int) string {
	return fmt.Sprintf("%04d-%02d", year, month)
}

func NormalizeYM(value string) (string, error) {
	text := strings.TrimSpace(strings.ReplaceAll(value, "/", "-"))
	if text == "" {
		return "", fmt.Errorf("月が未入力です")
	}
	year, month, err := ParseYM(text)
	if err != nil {
		return "", err
	}
	if month < 1 || month > 12 {
		return "", fmt.Errorf("月の形式が不正です（YYYY-MM）")
	}
	return FormatYM(year, month), nil
}

func NormalizeDate(value string) (string, error) {
	text := strings.TrimSpace(strings.ReplaceAll(value, "/", "-"))
	if text == "" {
		return "", fmt.Errorf("日付が未入力です")
	}
	parts := strings.Split(text, "-")
	if len(parts) != 3 {
		return "", fmt.Errorf("日付の形式が不正です（YYYY-MM-DD）")
	}
	year, err1 := strconv.Atoi(parts[0])
	month, err2 := strconv.Atoi(parts[1])
	day, err3 := strconv.Atoi(parts[2])
	if err1 != nil || err2 != nil || err3 != nil {
		return "", fmt.Errorf("日付の形式が不正です（YYYY-MM-DD）")
	}
	d := time.Date(year, time.Month(month), day, 0, 0, 0, 0, time.UTC)
	if d.Year() != year || int(d.Month()) != month || d.Day() != day {
		return "", fmt.Errorf("日付の形式が不正です（YYYY-MM-DD）")
	}
	return d.Format("2006-01-02"), nil
}

func IterMonths(fromYM, toYM string) ([]string, error) {
	year, month, err := ParseYM(fromYM)
	if err != nil {
		return nil, err
	}
	endYear, endMonth, err := ParseYM(toYM)
	if err != nil {
		return nil, err
	}
	var result []string
	for year < endYear || (year == endYear && month <= endMonth) {
		result = append(result, FormatYM(year, month))
		month++
		if month > 12 {
			month = 1
			year++
		}
	}
	return result, nil
}

func ComparePeriods(aYM string, aDecade int, bYM string, bDecade int) int {
	ay, am, _ := ParseYM(aYM)
	by, bm, _ := ParseYM(bYM)
	a := [3]int{ay, am, aDecade}
	b := [3]int{by, bm, bDecade}
	if a[0] != b[0] {
		if a[0] > b[0] {
			return 1
		}
		return -1
	}
	if a[1] != b[1] {
		if a[1] > b[1] {
			return 1
		}
		return -1
	}
	if a[2] > b[2] {
		return 1
	}
	if a[2] < b[2] {
		return -1
	}
	return 0
}

func IsPeriodInRange(ym string, decade int, startYM *string, startDecade *int, endYM *string, endDecade *int) bool {
	if startYM == nil || startDecade == nil || endYM == nil || endDecade == nil {
		return false
	}
	if *startYM == "" || *endYM == "" || *startDecade == 0 || *endDecade == 0 {
		return false
	}
	if ComparePeriods(ym, decade, *startYM, *startDecade) < 0 {
		return false
	}
	if ComparePeriods(ym, decade, *endYM, *endDecade) > 0 {
		return false
	}
	return true
}

func BusinessDays(ym string, decade int, holidays []string) (int, error) {
	year, month, err := ParseYM(ym)
	if err != nil {
		return 0, err
	}
	startDay, endDay, err := DecadeDayRange(year, month, decade)
	if err != nil {
		return 0, err
	}
	holidaySet := make(map[string]struct{}, len(holidays))
	for _, h := range holidays {
		holidaySet[h] = struct{}{}
	}
	count := 0
	for day := startDay; day <= endDay; day++ {
		d := time.Date(year, time.Month(month), day, 0, 0, 0, 0, time.UTC)
		if d.Weekday() == time.Saturday || d.Weekday() == time.Sunday {
			continue
		}
		if _, ok := holidaySet[d.Format("2006-01-02")]; ok {
			continue
		}
		count++
	}
	return count, nil
}

func Capacity(ym string, decade int, holidays []string, memberCount int) (float64, error) {
	days, err := BusinessDays(ym, decade, holidays)
	if err != nil {
		return 0, err
	}
	return float64(days * memberCount), nil
}

func AllocationStatus(allocated, capacityValue, plannedUtilizationPercent float64) string {
	allocated = RoundEffort(allocated)
	threshold := RoundEffort(capacityValue * plannedUtilizationPercent / 100.0)
	if allocated >= capacityValue {
		return "over"
	}
	if allocated > threshold {
		return "warn"
	}
	return ""
}

func RoundEffort(value float64) float64 {
	return math.Round((value+1e-9)*10) / 10
}

func IsValidEffort(value float64) bool {
	if value < 0 {
		return false
	}
	tenths := math.Round(value * 10)
	return math.Abs(value*10-tenths) < 1e-9
}

func NormalizePhaseInputMode(value string) string {
	for _, m := range PhaseInputModes {
		if value == m {
			return value
		}
	}
	return "effort"
}

func NormalizePhaseColor(value string) string {
	for _, c := range PhaseColors {
		if value == c {
			return value
		}
	}
	return "cyan"
}

func DefaultInputMode(legacyKey string) string {
	if legacyKey == "integration" {
		return "period"
	}
	return "effort"
}

func PhaseInputModeLabel(mode string) string {
	if mode == "period" {
		return "期間のみ"
	}
	return "工数入力"
}
