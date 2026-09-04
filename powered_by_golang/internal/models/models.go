package models

import (
	"database/sql"
	"fmt"
	"strings"

	"schedule_manager_go/internal/calendar"
)

type Store struct {
	DB *sql.DB
}

type Settings struct {
	ContractName        string
	MemberCount         int
	DisplayFrom         string
	DisplayTo           string
	PlannedUtilization  float64
	Theme               string
}

type Holiday struct {
	Date string
	Name string
}

type PhaseDefinition struct {
	ID        int
	Name      string
	Color     string
	SortOrder int
	LegacyKey string
}

type ProjectPhase struct {
	PhaseID     int
	SortOrder   int
	Enabled     bool
	InputMode   string
	TotalEffort float64
	StartYM     *string
	StartDecade *int
	EndYM       *string
	EndDecade   *int
	Name        string
	Color       string
}

type Project struct {
	ID        int
	Name      string
	SortOrder int
	Phases    []ProjectPhase
}

type PhaseConfig struct {
	PhaseID     int
	Enabled     bool
	InputMode   string
	TotalEffort float64
	StartYM     *string
	StartDecade *int
	EndYM       *string
	EndDecade   *int
}

// AllocationKey is projectID|phaseID|ym|decade.
type AllocationKey struct {
	ProjectID int
	PhaseID   int
	YearMonth string
	Decade    int
}

func (s *Store) GetSettings() (Settings, error) {
	var st Settings
	var theme sql.NullString
	var planned sql.NullFloat64
	err := s.DB.QueryRow(
		`SELECT contract_name, member_count, display_from, display_to, planned_utilization, theme FROM settings WHERE id = 1`,
	).Scan(&st.ContractName, &st.MemberCount, &st.DisplayFrom, &st.DisplayTo, &planned, &theme)
	if err != nil {
		return st, err
	}
	if planned.Valid {
		st.PlannedUtilization = planned.Float64
	} else {
		st.PlannedUtilization = 80
	}
	if theme.Valid && theme.String != "" {
		st.Theme = theme.String
	} else {
		st.Theme = "system"
	}
	return st, nil
}

func (s *Store) UpdateSettings(contractName string, memberCount int, displayFrom, displayTo string, planned float64, theme string) error {
	_, err := s.DB.Exec(
		`UPDATE settings SET contract_name = ?, member_count = ?, display_from = ?, display_to = ?, planned_utilization = ?, theme = ? WHERE id = 1`,
		contractName, memberCount, displayFrom, displayTo, planned, theme,
	)
	return err
}

func (s *Store) UpdateTheme(theme string) error {
	_, err := s.DB.Exec(`UPDATE settings SET theme = ? WHERE id = 1`, theme)
	return err
}

func (s *Store) ListHolidays() ([]Holiday, error) {
	rows, err := s.DB.Query(`SELECT date, name FROM holidays ORDER BY date`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []Holiday
	for rows.Next() {
		var h Holiday
		if err := rows.Scan(&h.Date, &h.Name); err != nil {
			return nil, err
		}
		out = append(out, h)
	}
	return out, rows.Err()
}

func (s *Store) ListHolidayDates() ([]string, error) {
	holidays, err := s.ListHolidays()
	if err != nil {
		return nil, err
	}
	dates := make([]string, len(holidays))
	for i, h := range holidays {
		dates[i] = h.Date
	}
	return dates, nil
}

func (s *Store) AddHoliday(dateStr, name string) error {
	_, err := s.DB.Exec(`INSERT OR REPLACE INTO holidays (date, name) VALUES (?, ?)`, dateStr, name)
	return err
}

func (s *Store) UpdateHoliday(dateStr, name string) error {
	var d string
	err := s.DB.QueryRow(`SELECT date FROM holidays WHERE date = ?`, dateStr).Scan(&d)
	if err == sql.ErrNoRows {
		return fmt.Errorf("祝日が見つかりません")
	}
	if err != nil {
		return err
	}
	_, err = s.DB.Exec(`UPDATE holidays SET name = ? WHERE date = ?`, name, dateStr)
	return err
}

func (s *Store) DeleteHoliday(dateStr string) error {
	_, err := s.DB.Exec(`DELETE FROM holidays WHERE date = ?`, dateStr)
	return err
}

func scanPhaseDef(rows interface {
	Scan(dest ...any) error
}) (PhaseDefinition, error) {
	var p PhaseDefinition
	var legacy sql.NullString
	var inputMode, color string
	err := rows.Scan(&p.ID, &p.Name, &inputMode, &color, &p.SortOrder, &legacy)
	if err != nil {
		return p, err
	}
	p.Color = calendar.NormalizePhaseColor(color)
	if legacy.Valid {
		p.LegacyKey = legacy.String
	}
	return p, nil
}

func (s *Store) ListPhaseDefinitions() ([]PhaseDefinition, error) {
	rows, err := s.DB.Query(
		`SELECT id, name, input_mode, color, sort_order, legacy_key FROM phase_definitions ORDER BY sort_order, id`,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []PhaseDefinition
	for rows.Next() {
		p, err := scanPhaseDef(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, p)
	}
	return out, rows.Err()
}

func (s *Store) GetPhaseDefinition(phaseID int) (*PhaseDefinition, error) {
	row := s.DB.QueryRow(
		`SELECT id, name, input_mode, color, sort_order, legacy_key FROM phase_definitions WHERE id = ?`, phaseID,
	)
	p, err := scanPhaseDef(row)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return &p, nil
}

func (s *Store) CreatePhaseDefinition(name, color string) (int, error) {
	name = trim(name)
	if name == "" {
		return 0, fmt.Errorf("工程名は必須です")
	}
	color = calendar.NormalizePhaseColor(color)
	var maxOrder int
	if err := s.DB.QueryRow(`SELECT COALESCE(MAX(sort_order), 0) FROM phase_definitions`).Scan(&maxOrder); err != nil {
		return 0, err
	}
	tx, err := s.DB.Begin()
	if err != nil {
		return 0, err
	}
	defer func() { _ = tx.Rollback() }()

	res, err := tx.Exec(
		`INSERT INTO phase_definitions (name, input_mode, color, sort_order) VALUES (?, 'effort', ?, ?)`,
		name, color, maxOrder+1,
	)
	if err != nil {
		return 0, err
	}
	id, err := res.LastInsertId()
	if err != nil {
		return 0, err
	}
	if err := attachPhaseToAllProjects(tx, int(id), maxOrder+1); err != nil {
		return 0, err
	}
	if err := tx.Commit(); err != nil {
		return 0, err
	}
	return int(id), nil
}

func attachPhaseToAllProjects(tx *sql.Tx, phaseID, sortOrder int) error {
	rows, err := tx.Query(`SELECT id FROM projects`)
	if err != nil {
		return err
	}
	defer rows.Close()
	for rows.Next() {
		var projectID int
		if err := rows.Scan(&projectID); err != nil {
			return err
		}
		_, err := tx.Exec(
			`INSERT OR IGNORE INTO project_phases (project_id, phase_id, sort_order, enabled, input_mode, total_effort)
			 VALUES (?, ?, ?, 0, 'effort', 0)`,
			projectID, phaseID, sortOrder,
		)
		if err != nil {
			return err
		}
	}
	return rows.Err()
}

func (s *Store) UpdatePhaseDefinition(phaseID int, name, color string) error {
	name = trim(name)
	if name == "" {
		return fmt.Errorf("工程名は必須です")
	}
	color = calendar.NormalizePhaseColor(color)
	var id int
	err := s.DB.QueryRow(`SELECT id FROM phase_definitions WHERE id = ?`, phaseID).Scan(&id)
	if err == sql.ErrNoRows {
		return fmt.Errorf("工程が見つかりません")
	}
	if err != nil {
		return err
	}
	_, err = s.DB.Exec(`UPDATE phase_definitions SET name = ?, color = ? WHERE id = ?`, name, color, phaseID)
	return err
}

func (s *Store) ReorderPhaseDefinitions(orderedIDs []int) error {
	if len(orderedIDs) == 0 {
		return fmt.Errorf("並び順が不正です")
	}
	rows, err := s.DB.Query(`SELECT id FROM phase_definitions`)
	if err != nil {
		return err
	}
	known := map[int]bool{}
	for rows.Next() {
		var id int
		if err := rows.Scan(&id); err != nil {
			rows.Close()
			return err
		}
		known[id] = true
	}
	rows.Close()
	if len(orderedIDs) != len(known) {
		return fmt.Errorf("並び順が不正です")
	}
	for _, id := range orderedIDs {
		if !known[id] {
			return fmt.Errorf("並び順が不正です")
		}
	}
	tx, err := s.DB.Begin()
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback() }()
	for i, id := range orderedIDs {
		if _, err := tx.Exec(`UPDATE phase_definitions SET sort_order = ? WHERE id = ?`, i, id); err != nil {
			return err
		}
	}
	return tx.Commit()
}

func (s *Store) ReorderProjects(orderedIDs []int) error {
	if len(orderedIDs) == 0 {
		return fmt.Errorf("並び順が不正です")
	}
	rows, err := s.DB.Query(`SELECT id FROM projects`)
	if err != nil {
		return err
	}
	known := map[int]bool{}
	for rows.Next() {
		var id int
		if err := rows.Scan(&id); err != nil {
			rows.Close()
			return err
		}
		known[id] = true
	}
	rows.Close()
	if len(orderedIDs) != len(known) {
		return fmt.Errorf("並び順が不正です")
	}
	for _, id := range orderedIDs {
		if !known[id] {
			return fmt.Errorf("並び順が不正です")
		}
	}
	tx, err := s.DB.Begin()
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback() }()
	for i, id := range orderedIDs {
		if _, err := tx.Exec(`UPDATE projects SET sort_order = ? WHERE id = ?`, i, id); err != nil {
			return err
		}
	}
	return tx.Commit()
}

func (s *Store) DeletePhaseDefinition(phaseID int) error {
	var count int
	if err := s.DB.QueryRow(`SELECT COUNT(*) FROM phase_definitions`).Scan(&count); err != nil {
		return err
	}
	if count <= 1 {
		return fmt.Errorf("工程は最低1つ必要です")
	}
	_, err := s.DB.Exec(`DELETE FROM phase_definitions WHERE id = ?`, phaseID)
	return err
}

func nullString(ns sql.NullString) *string {
	if !ns.Valid {
		return nil
	}
	s := ns.String
	return &s
}

func nullInt(ni sql.NullInt64) *int {
	if !ni.Valid {
		return nil
	}
	v := int(ni.Int64)
	return &v
}

func (s *Store) loadProjectPhases(projectID int) ([]ProjectPhase, error) {
	rows, err := s.DB.Query(`
		SELECT
			pp.phase_id, pp.sort_order, pp.enabled, pp.input_mode, pp.total_effort,
			pp.start_ym, pp.start_decade, pp.end_ym, pp.end_decade,
			pd.name, pd.color
		FROM project_phases pp
		JOIN phase_definitions pd ON pd.id = pp.phase_id
		WHERE pp.project_id = ?
		ORDER BY pp.sort_order, pp.phase_id
	`, projectID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var phases []ProjectPhase
	for rows.Next() {
		var p ProjectPhase
		var enabled int
		var inputMode, color string
		var startYM, endYM sql.NullString
		var startDecade, endDecade sql.NullInt64
		if err := rows.Scan(
			&p.PhaseID, &p.SortOrder, &enabled, &inputMode, &p.TotalEffort,
			&startYM, &startDecade, &endYM, &endDecade,
			&p.Name, &color,
		); err != nil {
			return nil, err
		}
		p.Enabled = enabled != 0
		p.InputMode = calendar.NormalizePhaseInputMode(inputMode)
		p.Color = calendar.NormalizePhaseColor(color)
		p.StartYM = nullString(startYM)
		p.EndYM = nullString(endYM)
		p.StartDecade = nullInt(startDecade)
		p.EndDecade = nullInt(endDecade)
		phases = append(phases, p)
	}
	return phases, rows.Err()
}

func (s *Store) ListProjects() ([]Project, error) {
	rows, err := s.DB.Query(`SELECT id, name, sort_order FROM projects ORDER BY sort_order, id`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var projects []Project
	for rows.Next() {
		var p Project
		if err := rows.Scan(&p.ID, &p.Name, &p.SortOrder); err != nil {
			return nil, err
		}
		phases, err := s.loadProjectPhases(p.ID)
		if err != nil {
			return nil, err
		}
		p.Phases = phases
		projects = append(projects, p)
	}
	return projects, rows.Err()
}

func (s *Store) GetProject(projectID int) (*Project, error) {
	var p Project
	err := s.DB.QueryRow(`SELECT id, name, sort_order FROM projects WHERE id = ?`, projectID).Scan(&p.ID, &p.Name, &p.SortOrder)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	phases, err := s.loadProjectPhases(projectID)
	if err != nil {
		return nil, err
	}
	p.Phases = phases
	return &p, nil
}

func (s *Store) initProjectPhases(tx *sql.Tx, projectID int) error {
	rows, err := tx.Query(`SELECT id, sort_order, legacy_key FROM phase_definitions ORDER BY sort_order, id`)
	if err != nil {
		return err
	}
	defer rows.Close()
	for rows.Next() {
		var phaseID, sortOrder int
		var legacy sql.NullString
		if err := rows.Scan(&phaseID, &sortOrder, &legacy); err != nil {
			return err
		}
		legacyKey := ""
		if legacy.Valid {
			legacyKey = legacy.String
		}
		inputMode := calendar.DefaultInputMode(legacyKey)
		_, err := tx.Exec(
			`INSERT INTO project_phases (project_id, phase_id, sort_order, enabled, input_mode, total_effort)
			 VALUES (?, ?, ?, 1, ?, 0)`,
			projectID, phaseID, sortOrder, inputMode,
		)
		if err != nil {
			return err
		}
	}
	return rows.Err()
}

func clearProjectPhaseModeData(tx *sql.Tx, projectID, phaseID int, inputMode string) error {
	if inputMode == "period" {
		if _, err := tx.Exec(
			`UPDATE project_phases SET total_effort = 0 WHERE project_id = ? AND phase_id = ?`,
			projectID, phaseID,
		); err != nil {
			return err
		}
		_, err := tx.Exec(`DELETE FROM allocations WHERE project_id = ? AND phase_id = ?`, projectID, phaseID)
		return err
	}
	_, err := tx.Exec(
		`UPDATE project_phases SET start_ym = NULL, start_decade = NULL, end_ym = NULL, end_decade = NULL
		 WHERE project_id = ? AND phase_id = ?`,
		projectID, phaseID,
	)
	return err
}

func (s *Store) saveProjectPhases(tx *sql.Tx, projectID int, configs []PhaseConfig) error {
	rows, err := tx.Query(`SELECT id FROM phase_definitions`)
	if err != nil {
		return err
	}
	known := map[int]bool{}
	for rows.Next() {
		var id int
		if err := rows.Scan(&id); err != nil {
			rows.Close()
			return err
		}
		known[id] = true
	}
	rows.Close()

	for index, config := range configs {
		if !known[config.PhaseID] {
			return fmt.Errorf("工程が不正です")
		}
		inputMode := calendar.NormalizePhaseInputMode(config.InputMode)
		enabled := 0
		if config.Enabled {
			enabled = 1
		}
		var prevMode sql.NullString
		err := tx.QueryRow(
			`SELECT input_mode FROM project_phases WHERE project_id = ? AND phase_id = ?`,
			projectID, config.PhaseID,
		).Scan(&prevMode)
		if err != nil && err != sql.ErrNoRows {
			return err
		}
		if prevMode.Valid && calendar.NormalizePhaseInputMode(prevMode.String) != inputMode {
			if err := clearProjectPhaseModeData(tx, projectID, config.PhaseID, inputMode); err != nil {
				return err
			}
		}

		totalEffort := 0.0
		var startYM, endYM any
		var startDecade, endDecade any
		if inputMode == "effort" {
			totalEffort = calendar.RoundEffort(config.TotalEffort)
		} else {
			if config.StartYM != nil {
				startYM = *config.StartYM
			}
			if config.EndYM != nil {
				endYM = *config.EndYM
			}
			if config.StartDecade != nil {
				startDecade = *config.StartDecade
			}
			if config.EndDecade != nil {
				endDecade = *config.EndDecade
			}
		}
		_, err = tx.Exec(
			`UPDATE project_phases SET sort_order = ?, enabled = ?, input_mode = ?,
			 total_effort = ?, start_ym = ?, start_decade = ?, end_ym = ?, end_decade = ?
			 WHERE project_id = ? AND phase_id = ?`,
			index, enabled, inputMode, totalEffort, startYM, startDecade, endYM, endDecade, projectID, config.PhaseID,
		)
		if err != nil {
			return err
		}
	}
	return nil
}

func (s *Store) CreateProject(name string, configs []PhaseConfig) (int, error) {
	tx, err := s.DB.Begin()
	if err != nil {
		return 0, err
	}
	defer func() { _ = tx.Rollback() }()

	var maxOrder int
	if err := tx.QueryRow(`SELECT COALESCE(MAX(sort_order), 0) FROM projects`).Scan(&maxOrder); err != nil {
		return 0, err
	}
	res, err := tx.Exec(`INSERT INTO projects (name, sort_order) VALUES (?, ?)`, trim(name), maxOrder+1)
	if err != nil {
		return 0, err
	}
	id64, err := res.LastInsertId()
	if err != nil {
		return 0, err
	}
	projectID := int(id64)
	if err := s.initProjectPhases(tx, projectID); err != nil {
		return 0, err
	}
	if err := s.saveProjectPhases(tx, projectID, configs); err != nil {
		return 0, err
	}
	if err := tx.Commit(); err != nil {
		return 0, err
	}
	return projectID, nil
}

func (s *Store) UpdateProject(projectID int, name string, configs []PhaseConfig) error {
	tx, err := s.DB.Begin()
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback() }()
	if _, err := tx.Exec(`UPDATE projects SET name = ? WHERE id = ?`, trim(name), projectID); err != nil {
		return err
	}
	if err := s.saveProjectPhases(tx, projectID, configs); err != nil {
		return err
	}
	return tx.Commit()
}

func (s *Store) DeleteProject(projectID int) error {
	_, err := s.DB.Exec(`DELETE FROM projects WHERE id = ?`, projectID)
	return err
}

func (s *Store) ListAllocations(fromYM, toYM string) (map[AllocationKey]float64, error) {
	rows, err := s.DB.Query(`
		SELECT a.project_id, a.phase_id, a.year_month, a.decade, a.effort
		FROM allocations a
		JOIN project_phases pp
		  ON pp.project_id = a.project_id
		 AND pp.phase_id = a.phase_id
		 AND pp.enabled = 1
		 AND pp.input_mode = 'effort'
		WHERE a.year_month >= ? AND a.year_month <= ?
	`, fromYM, toYM)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := map[AllocationKey]float64{}
	for rows.Next() {
		var k AllocationKey
		var effort float64
		if err := rows.Scan(&k.ProjectID, &k.PhaseID, &k.YearMonth, &k.Decade, &effort); err != nil {
			return nil, err
		}
		out[k] = effort
	}
	return out, rows.Err()
}

func (s *Store) SetAllocation(projectID, phaseID int, yearMonth string, decade int, effort float64) error {
	if decade < 1 || decade > 3 {
		return fmt.Errorf("invalid decade")
	}
	effort = calendar.RoundEffort(effort)
	if !calendar.IsValidEffort(effort) {
		return fmt.Errorf("effort must be in 0.1 increments")
	}
	var enabled int
	var inputMode string
	err := s.DB.QueryRow(
		`SELECT enabled, input_mode FROM project_phases WHERE project_id = ? AND phase_id = ?`,
		projectID, phaseID,
	).Scan(&enabled, &inputMode)
	if err == sql.ErrNoRows || enabled == 0 {
		return fmt.Errorf("invalid phase")
	}
	if err != nil {
		return err
	}
	if inputMode != "effort" {
		return fmt.Errorf("invalid phase")
	}
	if effort == 0 {
		_, err = s.DB.Exec(
			`DELETE FROM allocations WHERE project_id = ? AND phase_id = ? AND year_month = ? AND decade = ?`,
			projectID, phaseID, yearMonth, decade,
		)
		return err
	}
	_, err = s.DB.Exec(
		`INSERT INTO allocations (project_id, phase_id, year_month, decade, effort)
		 VALUES (?, ?, ?, ?, ?)
		 ON CONFLICT(project_id, phase_id, year_month, decade)
		 DO UPDATE SET effort = excluded.effort`,
		projectID, phaseID, yearMonth, decade, effort,
	)
	return err
}

func (s *Store) AllocatedTotalsByProjectPhase() (map[[2]int]float64, error) {
	rows, err := s.DB.Query(`
		SELECT a.project_id, a.phase_id, COALESCE(SUM(a.effort), 0) AS total
		FROM allocations a
		JOIN project_phases pp
		  ON pp.project_id = a.project_id
		 AND pp.phase_id = a.phase_id
		 AND pp.enabled = 1
		 AND pp.input_mode = 'effort'
		GROUP BY a.project_id, a.phase_id
	`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := map[[2]int]float64{}
	for rows.Next() {
		var projectID, phaseID int
		var total float64
		if err := rows.Scan(&projectID, &phaseID, &total); err != nil {
			return nil, err
		}
		out[[2]int{projectID, phaseID}] = total
	}
	return out, rows.Err()
}

func trim(s string) string {
	return strings.TrimSpace(s)
}
