package paths

import (
	"os"
	"path/filepath"
	"strings"
)

// DataDir returns the writable directory for schedule.db.
// Source / go run: module root (cwd with go.mod). Built binary: exe folder.
func DataDir() string {
	if wd, err := os.Getwd(); err == nil && fileExists(filepath.Join(wd, "go.mod")) {
		return wd
	}
	if exe, err := os.Executable(); err == nil {
		return filepath.Dir(exe)
	}
	return "."
}

// IsBuiltBinary reports whether this looks like a compiled executable
// (Python 版の is_frozen に相当)。`go run` の一時バイナリだけ false。
func IsBuiltBinary() bool {
	exe, err := os.Executable()
	if err != nil {
		return false
	}
	path := strings.ToLower(filepath.Clean(exe))
	// go run は %TEMP%\go-build...\exe に展開する
	if strings.Contains(path, string(filepath.Separator)+"go-build") {
		return false
	}
	tmp := strings.ToLower(filepath.Clean(os.TempDir()))
	dir := strings.ToLower(filepath.Dir(path))
	sep := string(filepath.Separator)
	if dir == tmp || strings.HasPrefix(dir, tmp+sep) {
		return false
	}
	return true
}

func fileExists(path string) bool {
	_, err := os.Stat(path)
	return err == nil
}
