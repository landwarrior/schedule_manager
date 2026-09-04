package web

import (
	"encoding/json"
	"fmt"
	"html/template"
	"io/fs"
	"net/http"
	"net/url"
	"strconv"
	"strings"

	"schedule_manager_go/internal/calendar"
	"schedule_manager_go/internal/models"
)

var themeChoices = []string{"light", "dark", "system"}

var themeLabels = map[string]string{
	"light":  "ライト",
	"dark":   "ダーク",
	"system": "システムに合わせる",
}

type App struct {
	Store    *models.Store
	Tmpl     *template.Template
	StaticFS fs.FS
}

func NewApp(store *models.Store, templateFS fs.FS, staticFS fs.FS) (*App, error) {
	funcMap := template.FuncMap{
		"fmtEffort": func(v float64) string {
			return fmt.Sprintf("%.1f", v)
		},
		"fmtPercent": func(v float64) string {
			return fmt.Sprintf("%.0f", v)
		},
		"ymSlash": func(ym string) string {
			return strings.ReplaceAll(ym, "-", "/")
		},
		"decadeLabel": func(d int) string {
			return calendar.DecadeLabels[d]
		},
		"add": func(a, b int) int { return a + b },
		"mul": func(a, b int) int { return a * b },
		"seq": func(n int) []int {
			out := make([]int, n)
			for i := range out {
				out[i] = i + 1
			}
			return out
		},
		"decades": func() []int { return []int{1, 2, 3} },
		"joinIDs": func(ids []int) string {
			parts := make([]string, len(ids))
			for i, id := range ids {
				parts[i] = strconv.Itoa(id)
			}
			return strings.Join(parts, ",")
		},
		"phaseIDs": func(phases []models.ProjectPhase) []int {
			ids := make([]int, len(phases))
			for i, p := range phases {
				ids[i] = p.PhaseID
			}
			return ids
		},
		"phaseDefIDs": func(phases []models.PhaseDefinition) []int {
			ids := make([]int, len(phases))
			for i, p := range phases {
				ids[i] = p.ID
			}
			return ids
		},
		"projectIDs": func(projects []models.Project) []int {
			ids := make([]int, len(projects))
			for i, p := range projects {
				ids[i] = p.ID
			}
			return ids
		},
		"findPhase": func(project models.Project, phaseID int) *models.ProjectPhase {
			for i := range project.Phases {
				if project.Phases[i].PhaseID == phaseID {
					return &project.Phases[i]
				}
			}
			return nil
		},
		"allocGet": func(m map[[2]int]float64, projectID, phaseID int) float64 {
			return m[[2]int{projectID, phaseID}]
		},
		"derefStr": func(p *string) string {
			if p == nil {
				return ""
			}
			return *p
		},
		"derefInt": func(p *int) int {
			if p == nil {
				return 0
			}
			return *p
		},
		"eqIntPtr": func(p *int, v int) bool {
			return p != nil && *p == v
		},
		"gt":  func(a, b float64) bool { return a > b },
		"lt":  func(a, b float64) bool { return a < b },
		"eq":  func(a, b any) bool { return a == b },
		"ne":  func(a, b any) bool { return a != b },
		"dict": func(values ...any) (map[string]any, error) {
			if len(values)%2 != 0 {
				return nil, fmt.Errorf("dict requires even args")
			}
			m := make(map[string]any, len(values)/2)
			for i := 0; i < len(values); i += 2 {
				k, ok := values[i].(string)
				if !ok {
					return nil, fmt.Errorf("dict keys must be strings")
				}
				m[k] = values[i+1]
			}
			return m, nil
		},
	}
	tmpl, err := template.New("").Funcs(funcMap).ParseFS(templateFS, "templates/*.html")
	if err != nil {
		return nil, err
	}
	staticRoot, err := fs.Sub(staticFS, "static")
	if err != nil {
		return nil, err
	}
	return &App{Store: store, Tmpl: tmpl, StaticFS: staticRoot}, nil
}

func (a *App) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.Handle("/static/", http.StripPrefix("/static/", http.FileServer(http.FS(a.StaticFS))))

	mux.HandleFunc("GET /{$}", a.schedule)
	mux.HandleFunc("POST /api/allocations", a.apiSetAllocation)

	mux.HandleFunc("GET /projects", a.projectsList)
	mux.HandleFunc("POST /projects", a.projectsList)
	mux.HandleFunc("GET /projects/new", a.projectsNew)
	mux.HandleFunc("POST /projects/new", a.projectsNew)
	mux.HandleFunc("GET /projects/{id}/edit", a.projectsEdit)
	mux.HandleFunc("POST /projects/{id}/edit", a.projectsEdit)
	mux.HandleFunc("POST /projects/{id}/delete", a.projectsDelete)

	mux.HandleFunc("GET /phases", a.phasesPage)
	mux.HandleFunc("POST /phases", a.phasesPage)
	mux.HandleFunc("POST /phases/{id}/delete", a.phasesDelete)

	mux.HandleFunc("GET /holidays", a.holidaysPage)
	mux.HandleFunc("POST /holidays", a.holidaysPage)
	mux.HandleFunc("POST /holidays/{date}/update", a.holidaysUpdate)
	mux.HandleFunc("POST /holidays/{date}/delete", a.holidaysDelete)

	mux.HandleFunc("GET /settings", a.settingsPage)
	mux.HandleFunc("POST /settings", a.settingsPage)
	mux.HandleFunc("POST /settings/theme", a.settingsTheme)

	return mux
}

type flashMsg struct {
	Category string
	Message  string
}

type baseData struct {
	UITheme           string
	ThemeChoices      []string
	ThemeLabels       map[string]string
	PhaseColorLabels  map[string]string
	Flash             []flashMsg
	RequestPath       string
	Title             string
	BodyClass         string
	ContentTemplate   string
}

func (a *App) base(r *http.Request, title, bodyClass, content string) baseData {
	theme := "system"
	if st, err := a.Store.GetSettings(); err == nil {
		theme = normalizeThemeOrDefault(st.Theme)
	}
	return baseData{
		UITheme:          theme,
		ThemeChoices:     themeChoices,
		ThemeLabels:      themeLabels,
		PhaseColorLabels: calendar.PhaseColorLabels,
		Flash:            takeFlash(r),
		RequestPath:      requestPath(r),
		Title:            title,
		BodyClass:        bodyClass,
		ContentTemplate:  content,
	}
}

func requestPath(r *http.Request) string {
	path := r.URL.Path
	if r.URL.RawQuery != "" {
		path += "?" + r.URL.RawQuery
	}
	return path
}

func (a *App) render(w http.ResponseWriter, r *http.Request, name string, data any) {
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	if err := a.Tmpl.ExecuteTemplate(w, name, data); err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
	}
}

func setFlash(w http.ResponseWriter, category, message string) {
	v := url.QueryEscape(category + "|" + message)
	http.SetCookie(w, &http.Cookie{
		Name:     "flash",
		Value:    v,
		Path:     "/",
		HttpOnly: true,
		SameSite: http.SameSiteLaxMode,
	})
}

func takeFlash(r *http.Request) []flashMsg {
	c, err := r.Cookie("flash")
	if err != nil || c.Value == "" {
		return nil
	}
	raw, err := url.QueryUnescape(c.Value)
	if err != nil {
		return nil
	}
	parts := strings.SplitN(raw, "|", 2)
	if len(parts) != 2 {
		return nil
	}
	return []flashMsg{{Category: parts[0], Message: parts[1]}}
}

func clearFlash(w http.ResponseWriter) {
	http.SetCookie(w, &http.Cookie{Name: "flash", Value: "", Path: "/", MaxAge: -1})
}

func redirectFlash(w http.ResponseWriter, r *http.Request, location, category, message string) {
	setFlash(w, category, message)
	http.Redirect(w, r, location, http.StatusSeeOther)
}

func normalizeTheme(raw string) (string, error) {
	theme := strings.ToLower(strings.TrimSpace(raw))
	if theme == "" {
		theme = "system"
	}
	for _, c := range themeChoices {
		if theme == c {
			return theme, nil
		}
	}
	return "", fmt.Errorf("テーマの指定が不正です")
}

func normalizeThemeOrDefault(raw string) string {
	t, err := normalizeTheme(raw)
	if err != nil {
		return "system"
	}
	return t
}

func parseEffort(raw string) (float64, error) {
	text := strings.TrimSpace(raw)
	if text == "" {
		return 0, nil
	}
	v, err := strconv.ParseFloat(text, 64)
	if err != nil {
		return 0, fmt.Errorf("工数は 0.1 刻みで入力してください")
	}
	v = calendar.RoundEffort(v)
	if !calendar.IsValidEffort(v) {
		return 0, fmt.Errorf("工数は 0.1 刻みで入力してください")
	}
	return v, nil
}

func parseDecade(raw string) (*int, error) {
	text := strings.TrimSpace(raw)
	if text == "" {
		return nil, nil
	}
	v, err := strconv.Atoi(text)
	if err != nil || v < 1 || v > 3 {
		return nil, fmt.Errorf("旬が不正です")
	}
	return &v, nil
}

func requireFormInt(raw, message string) (int, error) {
	text := strings.TrimSpace(raw)
	if text == "" {
		return 0, fmt.Errorf("%s", message)
	}
	v, err := strconv.Atoi(text)
	if err != nil {
		return 0, fmt.Errorf("%s", message)
	}
	return v, nil
}

func parseCSVInts(raw string) ([]int, error) {
	parts := strings.Split(raw, ",")
	var ids []int
	for _, p := range parts {
		p = strings.TrimSpace(p)
		if p == "" {
			continue
		}
		v, err := strconv.Atoi(p)
		if err != nil {
			return nil, err
		}
		ids = append(ids, v)
	}
	return ids, nil
}

func (a *App) parseProjectPhases(r *http.Request) ([]models.PhaseConfig, error) {
	orderRaw := strings.TrimSpace(r.FormValue("phase_order"))
	if orderRaw == "" {
		return nil, fmt.Errorf("工程の並び順が不正です")
	}
	phaseIDs, err := parseCSVInts(orderRaw)
	if err != nil || len(phaseIDs) == 0 {
		return nil, fmt.Errorf("工程の並び順が不正です")
	}
	var configs []models.PhaseConfig
	enabledCount := 0
	for _, phaseID := range phaseIDs {
		phase, err := a.Store.GetPhaseDefinition(phaseID)
		if err != nil {
			return nil, err
		}
		if phase == nil {
			return nil, fmt.Errorf("工程が不正です")
		}
		enabled := r.FormValue(fmt.Sprintf("enabled_%d", phaseID)) == "1"
		if enabled {
			enabledCount++
		}
		modeRaw := strings.TrimSpace(r.FormValue(fmt.Sprintf("input_mode_%d", phaseID)))
		if modeRaw == "" {
			modeRaw = "effort"
		}
		if modeRaw != "period" && modeRaw != "effort" {
			return nil, fmt.Errorf("入力方式が不正です")
		}
		cfg := models.PhaseConfig{PhaseID: phaseID, Enabled: enabled, InputMode: modeRaw}
		if modeRaw == "effort" {
			effort, err := parseEffort(r.FormValue(fmt.Sprintf("total_%d", phaseID)))
			if err != nil {
				return nil, err
			}
			cfg.TotalEffort = effort
		} else {
			startRaw := strings.TrimSpace(r.FormValue(fmt.Sprintf("period_%d_start_ym", phaseID)))
			endRaw := strings.TrimSpace(r.FormValue(fmt.Sprintf("period_%d_end_ym", phaseID)))
			if startRaw != "" {
				ym, err := calendar.NormalizeYM(startRaw)
				if err != nil {
					return nil, err
				}
				cfg.StartYM = &ym
			}
			if endRaw != "" {
				ym, err := calendar.NormalizeYM(endRaw)
				if err != nil {
					return nil, err
				}
				cfg.EndYM = &ym
			}
			sd, err := parseDecade(r.FormValue(fmt.Sprintf("period_%d_start_decade", phaseID)))
			if err != nil {
				return nil, err
			}
			ed, err := parseDecade(r.FormValue(fmt.Sprintf("period_%d_end_decade", phaseID)))
			if err != nil {
				return nil, err
			}
			cfg.StartDecade = sd
			cfg.EndDecade = ed
		}
		configs = append(configs, cfg)
	}
	if enabledCount == 0 {
		return nil, fmt.Errorf("表示する工程を1つ以上選んでください")
	}
	return configs, nil
}

type scheduleCell struct {
	YM      string
	Decade  int
	Effort  float64
	Active  bool
}

type schedulePhaseRow struct {
	ID        int
	Name      string
	InputMode string
	Color     string
	Total     float64
	Allocated float64
	Diff      float64
	Cells     []scheduleCell
}

type scheduleProjectRow struct {
	ID         int
	Name       string
	Phases     []schedulePhaseRow
	PhaseCount int
}

type summaryItem struct {
	YM            string
	Decade        int
	BusinessDays  int
	Capacity      float64
	Allocated     float64
	Status        string
	WarnThreshold float64
}

type schedulePageData struct {
	baseData
	ContractName        string
	DisplayFrom         string
	DisplayTo           string
	Months              []string
	DecadeLabels        map[int]string
	Projects            []scheduleProjectRow
	Summary             []summaryItem
	MemberCount         int
	PlannedUtilization  float64
}

func (a *App) buildSchedulePhaseRows(
	project models.Project,
	columns [][2]any,
	allocations map[models.AllocationKey]float64,
	allocatedSums map[[2]int]float64,
) []schedulePhaseRow {
	var rows []schedulePhaseRow
	for _, phase := range project.Phases {
		if !phase.Enabled {
			continue
		}
		if phase.InputMode == "effort" {
			allocated := allocatedSums[[2]int{project.ID, phase.PhaseID}]
			total := phase.TotalEffort
			var cells []scheduleCell
			for _, col := range columns {
				ym := col[0].(string)
				decade := col[1].(int)
				effort := allocations[models.AllocationKey{ProjectID: project.ID, PhaseID: phase.PhaseID, YearMonth: ym, Decade: decade}]
				cells = append(cells, scheduleCell{YM: ym, Decade: decade, Effort: effort, Active: effort > 0})
			}
			rows = append(rows, schedulePhaseRow{
				ID: phase.PhaseID, Name: phase.Name, InputMode: "effort", Color: phase.Color,
				Total: total, Allocated: calendar.RoundEffort(allocated), Diff: calendar.RoundEffort(total - allocated), Cells: cells,
			})
		} else {
			var cells []scheduleCell
			for _, col := range columns {
				ym := col[0].(string)
				decade := col[1].(int)
				active := calendar.IsPeriodInRange(ym, decade, phase.StartYM, phase.StartDecade, phase.EndYM, phase.EndDecade)
				cells = append(cells, scheduleCell{YM: ym, Decade: decade, Active: active})
			}
			rows = append(rows, schedulePhaseRow{
				ID: phase.PhaseID, Name: phase.Name, InputMode: "period", Color: phase.Color, Cells: cells,
			})
		}
	}
	return rows
}

func (a *App) schedule(w http.ResponseWriter, r *http.Request) {
	clearFlash(w)
	settings, err := a.Store.GetSettings()
	if err != nil {
		http.Error(w, err.Error(), 500)
		return
	}
	fromRaw := r.URL.Query().Get("from")
	if fromRaw == "" {
		fromRaw = settings.DisplayFrom
	}
	toRaw := r.URL.Query().Get("to")
	if toRaw == "" {
		toRaw = settings.DisplayTo
	}
	displayFrom, err := calendar.NormalizeYM(fromRaw)
	if err != nil {
		redirectFlash(w, r, "/", "error", "表示期間の形式が不正です（YYYY-MM）")
		return
	}
	displayTo, err := calendar.NormalizeYM(toRaw)
	if err != nil {
		redirectFlash(w, r, "/", "error", "表示期間の形式が不正です（YYYY-MM）")
		return
	}
	if displayFrom > displayTo {
		redirectFlash(w, r, "/", "error", "表示開始月は終了月以前にしてください")
		return
	}

	months, err := calendar.IterMonths(displayFrom, displayTo)
	if err != nil {
		http.Error(w, err.Error(), 500)
		return
	}
	var columns [][2]any
	for _, ym := range months {
		for _, d := range []int{1, 2, 3} {
			columns = append(columns, [2]any{ym, d})
		}
	}
	holidays, err := a.Store.ListHolidayDates()
	if err != nil {
		http.Error(w, err.Error(), 500)
		return
	}
	memberCount := settings.MemberCount
	planned := settings.PlannedUtilization

	projects, err := a.Store.ListProjects()
	if err != nil {
		http.Error(w, err.Error(), 500)
		return
	}
	allocations, err := a.Store.ListAllocations(displayFrom, displayTo)
	if err != nil {
		http.Error(w, err.Error(), 500)
		return
	}
	allocatedSums, err := a.Store.AllocatedTotalsByProjectPhase()
	if err != nil {
		http.Error(w, err.Error(), 500)
		return
	}

	periodTotals := map[[2]any]float64{}
	for _, col := range columns {
		periodTotals[col] = 0
	}
	for k, effort := range allocations {
		key := [2]any{k.YearMonth, k.Decade}
		if _, ok := periodTotals[key]; ok {
			periodTotals[key] = calendar.RoundEffort(periodTotals[key] + effort)
		}
	}

	var projectRows []scheduleProjectRow
	for _, project := range projects {
		phases := a.buildSchedulePhaseRows(project, columns, allocations, allocatedSums)
		projectRows = append(projectRows, scheduleProjectRow{
			ID: project.ID, Name: project.Name, Phases: phases, PhaseCount: len(phases),
		})
	}

	var summary []summaryItem
	for _, col := range columns {
		ym := col[0].(string)
		decade := col[1].(int)
		biz, _ := calendar.BusinessDays(ym, decade, holidays)
		cap, _ := calendar.Capacity(ym, decade, holidays, memberCount)
		allocated := periodTotals[col]
		status := calendar.AllocationStatus(allocated, cap, planned)
		summary = append(summary, summaryItem{
			YM: ym, Decade: decade, BusinessDays: biz, Capacity: cap, Allocated: allocated,
			Status: status, WarnThreshold: calendar.RoundEffort(cap * planned / 100),
		})
	}

	data := schedulePageData{
		baseData:           a.base(r, "スケジュール — スケジュール管理", "page-schedule", "schedule_content"),
		ContractName:       strings.TrimSpace(settings.ContractName),
		DisplayFrom:        displayFrom,
		DisplayTo:          displayTo,
		Months:             months,
		DecadeLabels:       calendar.DecadeLabels,
		Projects:           projectRows,
		Summary:            summary,
		MemberCount:        memberCount,
		PlannedUtilization: planned,
	}
	// Re-attach flash after clearFlash consumed cookie on response; take from request cookie already done in base.
	// clearFlash clears cookie for next request; current render already has flash from takeFlash in base... 
	// but we called clearFlash before base which reads cookie - order is wrong!
	// Fix: base already called takeFlash from request cookie. clearFlash only affects response Set-Cookie.
	// Actually we call clearFlash(w) first, then a.base(r,...) which reads r.Cookie - request cookie still present. Good.
	a.render(w, r, "schedule.html", data)
}

func (a *App) apiSetAllocation(w http.ResponseWriter, r *http.Request) {
	var body struct {
		ProjectID int     `json:"project_id"`
		PhaseID   int     `json:"phase_id"`
		YearMonth string  `json:"year_month"`
		Decade    int     `json:"decade"`
		Effort    any     `json:"effort"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeJSON(w, 400, map[string]any{"ok": false, "error": err.Error()})
		return
	}
	effortStr := fmt.Sprint(body.Effort)
	if body.Effort == nil {
		effortStr = "0"
	}
	effort, err := parseEffort(effortStr)
	if err != nil {
		writeJSON(w, 400, map[string]any{"ok": false, "error": err.Error()})
		return
	}
	if _, _, err := calendar.ParseYM(body.YearMonth); err != nil {
		writeJSON(w, 400, map[string]any{"ok": false, "error": err.Error()})
		return
	}
	if err := a.Store.SetAllocation(body.ProjectID, body.PhaseID, body.YearMonth, body.Decade, effort); err != nil {
		writeJSON(w, 400, map[string]any{"ok": false, "error": err.Error()})
		return
	}

	settings, err := a.Store.GetSettings()
	if err != nil {
		writeJSON(w, 500, map[string]any{"ok": false, "error": err.Error()})
		return
	}
	holidays, _ := a.Store.ListHolidayDates()
	withPeriod, _ := a.Store.ListAllocations(body.YearMonth, body.YearMonth)
	periodTotal := 0.0
	for k, e := range withPeriod {
		if k.YearMonth == body.YearMonth && k.Decade == body.Decade {
			periodTotal = calendar.RoundEffort(periodTotal + e)
		}
	}
	cap, _ := calendar.Capacity(body.YearMonth, body.Decade, holidays, settings.MemberCount)
	biz, _ := calendar.BusinessDays(body.YearMonth, body.Decade, holidays)
	status := calendar.AllocationStatus(periodTotal, cap, settings.PlannedUtilization)
	allocatedSums, _ := a.Store.AllocatedTotalsByProjectPhase()
	project, _ := a.Store.GetProject(body.ProjectID)
	phaseTotal := 0.0
	if project != nil {
		for _, phase := range project.Phases {
			if phase.PhaseID == body.PhaseID {
				phaseTotal = phase.TotalEffort
				break
			}
		}
	}
	phaseAllocated := calendar.RoundEffort(allocatedSums[[2]int{body.ProjectID, body.PhaseID}])
	writeJSON(w, 200, map[string]any{
		"ok":     true,
		"effort": effort,
		"period": map[string]any{
			"year_month":    body.YearMonth,
			"decade":        body.Decade,
			"allocated":     periodTotal,
			"capacity":      cap,
			"business_days": biz,
			"status":        status,
		},
		"phase": map[string]any{
			"allocated": phaseAllocated,
			"total":     phaseTotal,
			"diff":      calendar.RoundEffort(phaseTotal - phaseAllocated),
		},
	})
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}
