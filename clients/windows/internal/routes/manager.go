// Package routes — diff entre rotas que o servidor quer instaladas e as
// que o cliente já instalou; envia comandos `add`/`del` ao service via
// named pipe `\\.\pipe\vagg-client`.
//
// Convenção:
//   - Cada rota tem CIDR no formato a.b.c.d/n
//   - Manager mantém em memória um snapshot do que está aplicado
//   - Persistência em arquivo JSON pra sobreviver restart do app
package routes

import (
	"encoding/json"
	"fmt"
	"sync"
	"time"

	"github.com/rduarte6982/vagg/clients/windows/internal/api"
)

const PipeName = `\\.\pipe\vagg-client`

type Snapshot struct {
	Routes  []string     `json:"routes"`
	Clients []api.Client_ `json:"clients"`
	At      time.Time    `json:"at"`
}

type Manager struct {
	mu       sync.Mutex
	snapshot *Snapshot
}

func NewManager() *Manager { return &Manager{} }

// Healthy: tenta um ping no service via named pipe.
func (m *Manager) Healthy() bool {
	resp, err := dial(map[string]string{"op": "ping"})
	return err == nil && resp["ok"] == "1"
}

// SetGateway informa ao service o IP/host pra usar como next-hop nas rotas.
// Sem isso, o service rejeita o `apply` com "gateway nao configurado".
func (m *Manager) SetGateway(host string) error {
	body, _ := json.Marshal(map[string]any{"op": "set-gateway", "host": host})
	resp, err := dialRaw(body)
	if err != nil {
		return fmt.Errorf("pipe: %w", err)
	}
	if resp["ok"] != "1" {
		return fmt.Errorf("set-gateway: %s", resp["err"])
	}
	return nil
}

// Apply pede ao service que reconcilie as rotas locais com `want`. Idempotente.
func (m *Manager) Apply(want []string) error {
	body, _ := json.Marshal(map[string]any{"op": "apply", "cidrs": want})
	resp, err := dialRaw(body)
	if err != nil {
		return fmt.Errorf("pipe: %w", err)
	}
	if resp["ok"] != "1" {
		return fmt.Errorf("apply: %s", resp["err"])
	}
	return nil
}

// RemoveAllManaged solicita remoção de todas as rotas conhecidas (logout).
func (m *Manager) RemoveAllManaged() error {
	body, _ := json.Marshal(map[string]any{"op": "clear"})
	_, err := dialRaw(body)
	return err
}

func (m *Manager) SetSnapshot(s Snapshot) {
	m.mu.Lock()
	m.snapshot = &s
	m.mu.Unlock()
}

func (m *Manager) LastSnapshot() *Snapshot {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.snapshot
}
