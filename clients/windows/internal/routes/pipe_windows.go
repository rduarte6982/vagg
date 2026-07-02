// Comunicação cliente → service via named pipe Windows.
//
//go:build windows

package routes

import (
	"encoding/json"
	"fmt"
	"time"

	"golang.org/x/sys/windows"
)

func dial(req map[string]string) (map[string]string, error) {
	body, _ := json.Marshal(req)
	return dialRaw(body)
}

func dialRaw(payload []byte) (map[string]string, error) {
	pipe, err := windows.UTF16PtrFromString(PipeName)
	if err != nil {
		return nil, err
	}
	h, err := windows.CreateFile(pipe,
		windows.GENERIC_READ|windows.GENERIC_WRITE, 0, nil,
		windows.OPEN_EXISTING, 0, 0)
	if err != nil {
		return nil, fmt.Errorf("CreateFile pipe: %w", err)
	}
	defer windows.CloseHandle(h)

	var written uint32
	if err := windows.WriteFile(h, append(payload, '\n'), &written, nil); err != nil {
		return nil, err
	}

	buf := make([]byte, 4096)
	var read uint32
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		if err := windows.ReadFile(h, buf, &read, nil); err == nil && read > 0 {
			break
		}
	}
	var resp map[string]string
	if err := json.Unmarshal(buf[:read], &resp); err != nil {
		return nil, err
	}
	return resp, nil
}
