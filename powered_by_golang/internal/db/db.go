package db

import (
	"database/sql"
	"fmt"
	"path/filepath"

	"schedule_manager_go/internal/calendar"
	"schedule_manager_go/internal/paths"

	_ "modernc.org/sqlite"
)

var DBPath string

const schema = `
CREATE TABLE IF NOT EXISTS settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    contract_name TEXT NOT NULL DEFAULT '',
    member_count INTEGER NOT NULL DEFAULT 1,
    display_from TEXT NOT NULL DEFAULT '2026-01',
    display_to TEXT NOT NULL DEFAULT '2026-12',
    planned_utilization REAL NOT NULL DEFAULT 80,
    theme TEXT NOT NULL DEFAULT 'system'
);

CREATE TABLE IF NOT EXISTS holidays (
    date TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS phase_definitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    input_mode TEXT NOT NULL DEFAULT 'effort' CHECK (input_mode IN ('period', 'effort')),
    color TEXT NOT NULL DEFAULT 'cyan' CHECK (color IN ('cyan', 'orange', 'green', 'lavender')),
    sort_order INTEGER NOT NULL DEFAULT 0,
    legacy_key TEXT UNIQUE
);

CREATE TABLE IF NOT EXISTS project_phases (
    project_id INTEGER NOT NULL,
    phase_id INTEGER NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    input_mode TEXT NOT NULL DEFAULT 'effort' CHECK (input_mode IN ('period', 'effort')),
    total_effort REAL NOT NULL DEFAULT 0,
    start_ym TEXT,
    start_decade INTEGER CHECK (start_decade IS NULL OR start_decade IN (1, 2, 3)),
    end_ym TEXT,
    end_decade INTEGER CHECK (end_decade IS NULL OR end_decade IN (1, 2, 3)),
    PRIMARY KEY (project_id, phase_id),
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (phase_id) REFERENCES phase_definitions(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS allocations (
    project_id INTEGER NOT NULL,
    phase_id INTEGER NOT NULL,
    year_month TEXT NOT NULL,
    decade INTEGER NOT NULL CHECK (decade IN (1, 2, 3)),
    effort REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (project_id, phase_id, year_month, decade),
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (phase_id) REFERENCES phase_definitions(id) ON DELETE CASCADE
);
`

func Open() (*sql.DB, error) {
	DBPath = filepath.Join(paths.DataDir(), "schedule.db")
	conn, err := sql.Open("sqlite", DBPath)
	if err != nil {
		return nil, err
	}
	if _, err := conn.Exec("PRAGMA foreign_keys = ON"); err != nil {
		_ = conn.Close()
		return nil, err
	}
	if err := initDB(conn); err != nil {
		_ = conn.Close()
		return nil, err
	}
	return conn, nil
}

func initDB(conn *sql.DB) error {
	if _, err := conn.Exec(schema); err != nil {
		return fmt.Errorf("create schema: %w", err)
	}
	if err := ensureSettingsColumns(conn); err != nil {
		return err
	}
	if err := ensureProjectPhasesColumns(conn); err != nil {
		return err
	}
	if err := seedPhaseDefinitions(conn); err != nil {
		return err
	}
	if err := migrateLegacySchema(conn); err != nil {
		return err
	}
	var id int
	err := conn.QueryRow("SELECT id FROM settings WHERE id = 1").Scan(&id)
	if err == sql.ErrNoRows {
		_, err = conn.Exec(
			`INSERT INTO settings (id, member_count, display_from, display_to, planned_utilization, theme)
			 VALUES (1, 1, '2026-01', '2026-12', 80, 'system')`,
		)
		if err != nil {
			return err
		}
	} else if err != nil {
		return err
	}
	return nil
}

func tableExists(conn *sql.DB, name string) (bool, error) {
	var n int
	err := conn.QueryRow(
		`SELECT COUNT(1) FROM sqlite_master WHERE type = 'table' AND name = ?`, name,
	).Scan(&n)
	return n > 0, err
}

func columnsOf(conn *sql.DB, table string) (map[string]bool, error) {
	rows, err := conn.Query(fmt.Sprintf("PRAGMA table_info(%s)", table))
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	cols := map[string]bool{}
	for rows.Next() {
		var cid int
		var name, ctype string
		var notnull, pk int
		var dflt sql.NullString
		if err := rows.Scan(&cid, &name, &ctype, &notnull, &dflt, &pk); err != nil {
			return nil, err
		}
		cols[name] = true
	}
	return cols, rows.Err()
}

func ensureSettingsColumns(conn *sql.DB) error {
	cols, err := columnsOf(conn, "settings")
	if err != nil {
		return err
	}
	if !cols["contract_name"] {
		if _, err := conn.Exec(`ALTER TABLE settings ADD COLUMN contract_name TEXT NOT NULL DEFAULT ''`); err != nil {
			return err
		}
	}
	if !cols["planned_utilization"] {
		if cols["safety_rate"] {
			if _, err := conn.Exec(`ALTER TABLE settings RENAME COLUMN safety_rate TO planned_utilization`); err != nil {
				return err
			}
		} else {
			if _, err := conn.Exec(`ALTER TABLE settings ADD COLUMN planned_utilization REAL NOT NULL DEFAULT 80`); err != nil {
				return err
			}
		}
	}
	cols, err = columnsOf(conn, "settings")
	if err != nil {
		return err
	}
	if !cols["theme"] {
		if _, err := conn.Exec(`ALTER TABLE settings ADD COLUMN theme TEXT NOT NULL DEFAULT 'system'`); err != nil {
			return err
		}
	}
	return nil
}

func ensureProjectPhasesColumns(conn *sql.DB) error {
	exists, err := tableExists(conn, "project_phases")
	if err != nil || !exists {
		return err
	}
	cols, err := columnsOf(conn, "project_phases")
	if err != nil {
		return err
	}
	if !cols["enabled"] {
		if _, err := conn.Exec(`ALTER TABLE project_phases ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1`); err != nil {
			return err
		}
	}
	cols, err = columnsOf(conn, "project_phases")
	if err != nil {
		return err
	}
	if !cols["input_mode"] {
		if _, err := conn.Exec(`ALTER TABLE project_phases ADD COLUMN input_mode TEXT NOT NULL DEFAULT 'effort'`); err != nil {
			return err
		}
		stmts := []string{
			`UPDATE project_phases SET input_mode = (
				SELECT pd.input_mode FROM phase_definitions pd WHERE pd.id = project_phases.phase_id
			)`,
			`UPDATE project_phases SET input_mode = 'period' WHERE start_ym IS NOT NULL AND end_ym IS NOT NULL`,
			`UPDATE project_phases SET input_mode = 'effort' WHERE total_effort > 0`,
			`UPDATE project_phases SET input_mode = 'effort' WHERE EXISTS (
				SELECT 1 FROM allocations a
				WHERE a.project_id = project_phases.project_id AND a.phase_id = project_phases.phase_id
			)`,
		}
		for _, s := range stmts {
			if _, err := conn.Exec(s); err != nil {
				return err
			}
		}
	}
	return nil
}

func seedPhaseDefinitions(conn *sql.DB) error {
	var count int
	if err := conn.QueryRow(`SELECT COUNT(*) FROM phase_definitions`).Scan(&count); err != nil {
		return err
	}
	if count > 0 {
		return nil
	}
	for _, p := range calendar.DefaultPhases {
		_, err := conn.Exec(
			`INSERT INTO phase_definitions (name, input_mode, color, sort_order, legacy_key) VALUES (?, ?, ?, ?, ?)`,
			p.Name, p.InputMode, p.Color, p.SortOrder, p.LegacyKey,
		)
		if err != nil {
			return err
		}
	}
	return nil
}

func legacyPhaseMap(conn *sql.DB) (map[string]int, error) {
	rows, err := conn.Query(`SELECT id, legacy_key FROM phase_definitions WHERE legacy_key IS NOT NULL`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	m := map[string]int{}
	for rows.Next() {
		var id int
		var key string
		if err := rows.Scan(&id, &key); err != nil {
			return nil, err
		}
		m[key] = id
	}
	return m, rows.Err()
}

func migrateProjectData(conn *sql.DB) error {
	projRows, err := conn.Query(`SELECT id FROM projects`)
	if err != nil {
		return err
	}
	defer projRows.Close()
	var projectIDs []int
	for projRows.Next() {
		var id int
		if err := projRows.Scan(&id); err != nil {
			return err
		}
		projectIDs = append(projectIDs, id)
	}
	if err := projRows.Err(); err != nil {
		return err
	}

	hasPhaseTotals, _ := tableExists(conn, "phase_totals")
	hasTestT, _ := tableExists(conn, "test_t_period")
	projCols, _ := columnsOf(conn, "projects")
	hasTestTMode := projCols["test_t_mode"]

	for _, projectID := range projectIDs {
		var n int
		if err := conn.QueryRow(`SELECT COUNT(1) FROM project_phases WHERE project_id = ?`, projectID).Scan(&n); err != nil {
			return err
		}
		if n > 0 {
			continue
		}

		totals := map[string]float64{}
		if hasPhaseTotals {
			rows, err := conn.Query(`SELECT phase, total_effort FROM phase_totals WHERE project_id = ?`, projectID)
			if err != nil {
				return err
			}
			for rows.Next() {
				var phase string
				var total float64
				if err := rows.Scan(&phase, &total); err != nil {
					rows.Close()
					return err
				}
				totals[phase] = total
			}
			rows.Close()
		}

		var startYM, endYM sql.NullString
		var startDecade, endDecade sql.NullInt64
		if hasTestT {
			_ = conn.QueryRow(
				`SELECT start_ym, start_decade, end_ym, end_decade FROM test_t_period WHERE project_id = ?`,
				projectID,
			).Scan(&startYM, &startDecade, &endYM, &endDecade)
		}

		testTMode := "period"
		if hasTestTMode {
			var mode sql.NullString
			_ = conn.QueryRow(`SELECT test_t_mode FROM projects WHERE id = ?`, projectID).Scan(&mode)
			if mode.Valid && (mode.String == "period" || mode.String == "effort") {
				testTMode = mode.String
			}
		}

		phaseRows, err := conn.Query(`SELECT id, legacy_key, sort_order FROM phase_definitions ORDER BY sort_order, id`)
		if err != nil {
			return err
		}
		for phaseRows.Next() {
			var phaseID, sortOrder int
			var legacyKey sql.NullString
			if err := phaseRows.Scan(&phaseID, &legacyKey, &sortOrder); err != nil {
				phaseRows.Close()
				return err
			}
			key := ""
			if legacyKey.Valid {
				key = legacyKey.String
			}
			total := totals[key]
			var sYM, eYM any
			var sDec, eDec any
			inputMode := "effort"
			if key == "integration" {
				inputMode = testTMode
				if startYM.Valid && testTMode == "period" {
					sYM, sDec, eYM, eDec = startYM.String, startDecade.Int64, endYM.String, endDecade.Int64
				}
			}
			_, err := conn.Exec(
				`INSERT INTO project_phases
				 (project_id, phase_id, sort_order, enabled, input_mode, total_effort, start_ym, start_decade, end_ym, end_decade)
				 VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?, ?)`,
				projectID, phaseID, sortOrder, inputMode, total, sYM, sDec, eYM, eDec,
			)
			if err != nil {
				phaseRows.Close()
				return err
			}
		}
		phaseRows.Close()
	}
	return nil
}

func migrateLegacySchema(conn *sql.DB) error {
	exists, err := tableExists(conn, "phase_definitions")
	if err != nil || !exists {
		return err
	}
	legacyMap, err := legacyPhaseMap(conn)
	if err != nil || len(legacyMap) == 0 {
		return err
	}
	hasPhaseTotals, _ := tableExists(conn, "phase_totals")
	hasTestT, _ := tableExists(conn, "test_t_period")
	if hasPhaseTotals || hasTestT {
		if err := migrateProjectData(conn); err != nil {
			return err
		}
	}

	allocCols, err := columnsOf(conn, "allocations")
	if err != nil {
		return err
	}
	if allocCols["phase"] && !allocCols["phase_id"] {
		if _, err := conn.Exec(`
			CREATE TABLE allocations_new (
				project_id INTEGER NOT NULL,
				phase_id INTEGER NOT NULL,
				year_month TEXT NOT NULL,
				decade INTEGER NOT NULL CHECK (decade IN (1, 2, 3)),
				effort REAL NOT NULL DEFAULT 0,
				PRIMARY KEY (project_id, phase_id, year_month, decade),
				FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
				FOREIGN KEY (phase_id) REFERENCES phase_definitions(id) ON DELETE CASCADE
			)`); err != nil {
			return err
		}
		rows, err := conn.Query(`SELECT project_id, phase, year_month, decade, effort FROM allocations`)
		if err != nil {
			return err
		}
		for rows.Next() {
			var projectID, decade int
			var phase, ym string
			var effort float64
			if err := rows.Scan(&projectID, &phase, &ym, &decade, &effort); err != nil {
				rows.Close()
				return err
			}
			phaseID, ok := legacyMap[phase]
			if !ok {
				continue
			}
			if _, err := conn.Exec(
				`INSERT OR REPLACE INTO allocations_new (project_id, phase_id, year_month, decade, effort) VALUES (?, ?, ?, ?, ?)`,
				projectID, phaseID, ym, decade, effort,
			); err != nil {
				rows.Close()
				return err
			}
		}
		rows.Close()
		if _, err := conn.Exec(`DROP TABLE allocations`); err != nil {
			return err
		}
		if _, err := conn.Exec(`ALTER TABLE allocations_new RENAME TO allocations`); err != nil {
			return err
		}
	}
	return nil
}
