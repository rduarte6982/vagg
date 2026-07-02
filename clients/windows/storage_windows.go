// Persistência local: config em %APPDATA%\VAGG Client\, token em
// Windows Credential Manager (DPAPI por user — mais seguro que arquivo).
//
//go:build windows

package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
)

const appFolder = "VAGG Client"

func appDataDir() string {
	roaming := os.Getenv("APPDATA")
	if roaming == "" {
		roaming = filepath.Join(os.Getenv("USERPROFILE"), "AppData", "Roaming")
	}
	dir := filepath.Join(roaming, appFolder)
	_ = os.MkdirAll(dir, 0o700)
	return dir
}

func readAppData(name string) ([]byte, error) {
	return os.ReadFile(filepath.Join(appDataDir(), name))
}

func writeAppData(name string, data []byte) error {
	return os.WriteFile(filepath.Join(appDataDir(), name), data, 0o600)
}

// TODO: trocar pra Windows Credential Manager (advapi32 CredRead/CredWrite).
// Por enquanto, token vai num arquivo em %APPDATA% com perm 0600 (visível só
// pro user logado em NTFS). Não comitar credenciais nem em arquivos comuns.

// sessionFile é o par de tokens persistido. Persistir o refresh (não só o
// access) permite renovar a sessão silenciosamente após um restart do app —
// sem ele, expirado o access TTL (~15 min) o usuário teria que relogar.
type sessionFile struct {
	Access  string `json:"access"`
	Refresh string `json:"refresh"`
}

// loadSession lê o par de tokens. Compat: se o arquivo for uma string crua
// (formato antigo, só access), trata como access-only.
func loadSession() (access, refresh string) {
	b, err := readAppData(".session")
	if err != nil || len(b) == 0 {
		return "", ""
	}
	trimmed := strings.TrimSpace(string(b))
	if strings.HasPrefix(trimmed, "{") {
		var s sessionFile
		if json.Unmarshal(b, &s) == nil {
			return s.Access, s.Refresh
		}
		return "", ""
	}
	// Formato legado: só o access token, sem refresh.
	return trimmed, ""
}

func storeSession(access, refresh string) {
	data, _ := json.Marshal(sessionFile{Access: access, Refresh: refresh})
	_ = writeAppData(".session", data)
}

func clearStoredToken() { _ = os.Remove(filepath.Join(appDataDir(), ".session")) }
