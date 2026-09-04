package web

import (
	"fmt"
	"net/http"
	"strconv"
	"strings"

	"schedule_manager_go/internal/calendar"
	"schedule_manager_go/internal/models"
)

type projectsPageData struct {
	baseData
	Projects         []models.Project
	Allocated        map[[2]int]float64
	PhaseDefinitions []models.PhaseDefinition
	DecadeLabels     map[int]string
}

func (a *App) projectsList(w http.ResponseWriter, r *http.Request) {
	if r.Method == http.MethodPost {
		action := strings.TrimSpace(r.FormValue("action"))
		if action == "reorder" {
			ids, err := parseCSVInts(r.FormValue("project_order"))
			if err != nil {
				redirectFlash(w, r, "/projects", "error", err.Error())
				return
			}
			if err := a.Store.ReorderProjects(ids); err != nil {
				redirectFlash(w, r, "/projects", "error", err.Error())
				return
			}
			redirectFlash(w, r, "/projects", "ok", "表示順を保存しました")
			return
		}
		redirectFlash(w, r, "/projects", "error", "操作が不正です")
		return
	}
	projects, err := a.Store.ListProjects()
	if err != nil {
		http.Error(w, err.Error(), 500)
		return
	}
	allocated, err := a.Store.AllocatedTotalsByProjectPhase()
	if err != nil {
		http.Error(w, err.Error(), 500)
		return
	}
	phases, err := a.Store.ListPhaseDefinitions()
	if err != nil {
		http.Error(w, err.Error(), 500)
		return
	}
	clearFlash(w)
	a.render(w, r, "projects.html", projectsPageData{
		baseData:         a.base(r, "プロジェクト — スケジュール管理", "", "projects_content"),
		Projects:         projects,
		Allocated:        allocated,
		PhaseDefinitions: phases,
		DecadeLabels:     calendar.DecadeLabels,
	})
}

type projectFormData struct {
	baseData
	Mode         string
	Project      models.Project
	DecadeLabels map[int]string
}

func (a *App) blankProject() (models.Project, error) {
	phases, err := a.Store.ListPhaseDefinitions()
	if err != nil {
		return models.Project{}, err
	}
	p := models.Project{Name: ""}
	for i, phase := range phases {
		mode := "effort"
		if phase.LegacyKey == "integration" {
			mode = "period"
		}
		p.Phases = append(p.Phases, models.ProjectPhase{
			PhaseID: phase.ID, Name: phase.Name, Color: phase.Color, SortOrder: i,
			Enabled: true, InputMode: mode, TotalEffort: 0,
		})
	}
	return p, nil
}

func (a *App) projectsNew(w http.ResponseWriter, r *http.Request) {
	if r.Method == http.MethodPost {
		name := strings.TrimSpace(r.FormValue("name"))
		if name == "" {
			redirectFlash(w, r, "/projects/new", "error", "プロジェクト名は必須です")
			return
		}
		configs, err := a.parseProjectPhases(r)
		if err != nil {
			redirectFlash(w, r, "/projects/new", "error", err.Error())
			return
		}
		if _, err := a.Store.CreateProject(name, configs); err != nil {
			redirectFlash(w, r, "/projects/new", "error", err.Error())
			return
		}
		redirectFlash(w, r, "/projects", "ok", "プロジェクトを作成しました")
		return
	}
	project, err := a.blankProject()
	if err != nil {
		http.Error(w, err.Error(), 500)
		return
	}
	clearFlash(w)
	a.render(w, r, "project_form.html", projectFormData{
		baseData:     a.base(r, "新規プロジェクト — スケジュール管理", "", "project_form_content"),
		Mode:         "new",
		Project:      project,
		DecadeLabels: calendar.DecadeLabels,
	})
}

func (a *App) projectsEdit(w http.ResponseWriter, r *http.Request) {
	id, err := strconv.Atoi(r.PathValue("id"))
	if err != nil {
		redirectFlash(w, r, "/projects", "error", "プロジェクトが見つかりません")
		return
	}
	project, err := a.Store.GetProject(id)
	if err != nil {
		http.Error(w, err.Error(), 500)
		return
	}
	if project == nil {
		redirectFlash(w, r, "/projects", "error", "プロジェクトが見つかりません")
		return
	}
	if r.Method == http.MethodPost {
		name := strings.TrimSpace(r.FormValue("name"))
		if name == "" {
			redirectFlash(w, r, fmt.Sprintf("/projects/%d/edit", id), "error", "プロジェクト名は必須です")
			return
		}
		configs, err := a.parseProjectPhases(r)
		if err != nil {
			redirectFlash(w, r, fmt.Sprintf("/projects/%d/edit", id), "error", err.Error())
			return
		}
		if err := a.Store.UpdateProject(id, name, configs); err != nil {
			redirectFlash(w, r, fmt.Sprintf("/projects/%d/edit", id), "error", err.Error())
			return
		}
		redirectFlash(w, r, "/projects", "ok", "プロジェクトを更新しました")
		return
	}
	clearFlash(w)
	a.render(w, r, "project_form.html", projectFormData{
		baseData:     a.base(r, "プロジェクト編集 — スケジュール管理", "", "project_form_content"),
		Mode:         "edit",
		Project:      *project,
		DecadeLabels: calendar.DecadeLabels,
	})
}

func (a *App) projectsDelete(w http.ResponseWriter, r *http.Request) {
	id, err := strconv.Atoi(r.PathValue("id"))
	if err != nil {
		redirectFlash(w, r, "/projects", "error", "プロジェクトが見つかりません")
		return
	}
	_ = a.Store.DeleteProject(id)
	redirectFlash(w, r, "/projects", "ok", "プロジェクトを削除しました")
}

type phasesPageData struct {
	baseData
	Phases      []models.PhaseDefinition
	PhaseColors []string
}

func (a *App) phasesPage(w http.ResponseWriter, r *http.Request) {
	if r.Method == http.MethodPost {
		action := strings.TrimSpace(r.FormValue("action"))
		switch action {
		case "create":
			if _, err := a.Store.CreatePhaseDefinition(r.FormValue("name"), r.FormValue("color")); err != nil {
				redirectFlash(w, r, "/phases", "error", err.Error())
				return
			}
			redirectFlash(w, r, "/phases", "ok", "工程を追加しました")
			return
		case "update":
			phaseID, err := requireFormInt(r.FormValue("phase_id"), "工程が不正です")
			if err != nil {
				redirectFlash(w, r, "/phases", "error", err.Error())
				return
			}
			if err := a.Store.UpdatePhaseDefinition(phaseID, r.FormValue("name"), r.FormValue("color")); err != nil {
				redirectFlash(w, r, "/phases", "error", err.Error())
				return
			}
			redirectFlash(w, r, "/phases", "ok", "工程を更新しました")
			return
		case "reorder":
			ids, err := parseCSVInts(r.FormValue("phase_order"))
			if err != nil {
				redirectFlash(w, r, "/phases", "error", "並び順が不正です")
				return
			}
			if err := a.Store.ReorderPhaseDefinitions(ids); err != nil {
				redirectFlash(w, r, "/phases", "error", err.Error())
				return
			}
			redirectFlash(w, r, "/phases", "ok", "表示順を保存しました")
			return
		default:
			redirectFlash(w, r, "/phases", "error", "操作が不正です")
			return
		}
	}
	phases, err := a.Store.ListPhaseDefinitions()
	if err != nil {
		http.Error(w, err.Error(), 500)
		return
	}
	clearFlash(w)
	a.render(w, r, "phases.html", phasesPageData{
		baseData:    a.base(r, "工程マスタ — スケジュール管理", "", "phases_content"),
		Phases:      phases,
		PhaseColors: calendar.PhaseColors,
	})
}

func (a *App) phasesDelete(w http.ResponseWriter, r *http.Request) {
	id, err := strconv.Atoi(r.PathValue("id"))
	if err != nil {
		redirectFlash(w, r, "/phases", "error", "工程が不正です")
		return
	}
	if err := a.Store.DeletePhaseDefinition(id); err != nil {
		redirectFlash(w, r, "/phases", "error", err.Error())
		return
	}
	redirectFlash(w, r, "/phases", "ok", "工程を削除しました")
}

type holidaysPageData struct {
	baseData
	Holidays []models.Holiday
}

func (a *App) holidaysPage(w http.ResponseWriter, r *http.Request) {
	if r.Method == http.MethodPost {
		dateStr, err := calendar.NormalizeDate(r.FormValue("date"))
		if err != nil {
			redirectFlash(w, r, "/holidays", "error", err.Error())
			return
		}
		name := strings.TrimSpace(r.FormValue("name"))
		if err := a.Store.AddHoliday(dateStr, name); err != nil {
			redirectFlash(w, r, "/holidays", "error", err.Error())
			return
		}
		redirectFlash(w, r, "/holidays", "ok", "祝日を登録しました")
		return
	}
	holidays, err := a.Store.ListHolidays()
	if err != nil {
		http.Error(w, err.Error(), 500)
		return
	}
	clearFlash(w)
	a.render(w, r, "holidays.html", holidaysPageData{
		baseData: a.base(r, "祝日・休業日マスタ — スケジュール管理", "", "holidays_content"),
		Holidays: holidays,
	})
}

func (a *App) holidaysUpdate(w http.ResponseWriter, r *http.Request) {
	dateStr := r.PathValue("date")
	name := strings.TrimSpace(r.FormValue("name"))
	if err := a.Store.UpdateHoliday(dateStr, name); err != nil {
		redirectFlash(w, r, "/holidays", "error", err.Error())
		return
	}
	redirectFlash(w, r, "/holidays", "ok", "祝日を更新しました")
}

func (a *App) holidaysDelete(w http.ResponseWriter, r *http.Request) {
	_ = a.Store.DeleteHoliday(r.PathValue("date"))
	redirectFlash(w, r, "/holidays", "ok", "祝日を削除しました")
}

type settingsPageData struct {
	baseData
	Settings models.Settings
}

func (a *App) settingsPage(w http.ResponseWriter, r *http.Request) {
	if r.Method == http.MethodPost {
		memberCount, err := strconv.Atoi(r.FormValue("member_count"))
		if err != nil || memberCount < 1 {
			redirectFlash(w, r, "/settings", "error", "メンバー人数は 1 以上にしてください")
			return
		}
		planned, err := strconv.ParseFloat(r.FormValue("planned_utilization"), 64)
		if err != nil || planned <= 0 || planned > 100 {
			redirectFlash(w, r, "/settings", "error", "計画稼働率は 1〜100 の範囲で指定してください")
			return
		}
		displayFrom, err := calendar.NormalizeYM(r.FormValue("display_from"))
		if err != nil {
			redirectFlash(w, r, "/settings", "error", err.Error())
			return
		}
		displayTo, err := calendar.NormalizeYM(r.FormValue("display_to"))
		if err != nil {
			redirectFlash(w, r, "/settings", "error", err.Error())
			return
		}
		if displayFrom > displayTo {
			redirectFlash(w, r, "/settings", "error", "表示開始月は終了月以前にしてください")
			return
		}
		theme, err := normalizeTheme(r.FormValue("theme"))
		if err != nil {
			redirectFlash(w, r, "/settings", "error", err.Error())
			return
		}
		contractName := strings.TrimSpace(r.FormValue("contract_name"))
		if err := a.Store.UpdateSettings(contractName, memberCount, displayFrom, displayTo, planned, theme); err != nil {
			redirectFlash(w, r, "/settings", "error", err.Error())
			return
		}
		redirectFlash(w, r, "/settings", "ok", "設定を保存しました")
		return
	}
	settings, err := a.Store.GetSettings()
	if err != nil {
		http.Error(w, err.Error(), 500)
		return
	}
	clearFlash(w)
	a.render(w, r, "settings.html", settingsPageData{
		baseData: a.base(r, "設定 — スケジュール管理", "", "settings_content"),
		Settings: settings,
	})
}

func (a *App) settingsTheme(w http.ResponseWriter, r *http.Request) {
	theme, err := normalizeTheme(r.FormValue("theme"))
	if err != nil {
		redirectFlash(w, r, "/", "error", err.Error())
		return
	}
	_ = a.Store.UpdateTheme(theme)
	nextURL := r.FormValue("next")
	if nextURL == "" || !strings.HasPrefix(nextURL, "/") {
		nextURL = "/"
	}
	http.Redirect(w, r, nextURL, http.StatusSeeOther)
}
