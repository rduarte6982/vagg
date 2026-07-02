// vagg-client-svc.exe — Windows service que escuta no named pipe
// \\.\pipe\vagg-client e executa add/del de rotas conforme requisições da
// GUI.
//
// Roda como SYSTEM (auto-start). Aceita 4 ops:
//   - "ping"        → confirma alive
//   - "set-gateway" → grava {host: "..."} em %PROGRAMDATA%\VAGG Client\gateway
//   - "apply"       → reconcilia rotas {cidrs: [...]} via diff vs estado salvo
//   - "clear"       → remove todas as rotas geridas (logout / atualizar rotas)
//
// Estado: %PROGRAMDATA%\VAGG Client\managed-routes.json + gateway
//
//go:build windows

package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"log"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"

	"github.com/Microsoft/go-winio"
	"golang.org/x/sys/windows/svc"
	"golang.org/x/sys/windows/svc/debug"
)

const (
	serviceName = "vagg-client-svc"
	pipeName    = `\\.\pipe\vagg-client`
)

type managedRoutes struct {
	mu sync.Mutex
}

func (m *managedRoutes) load() ([]string, error) {
	b, err := os.ReadFile(stateFile())
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, err
	}
	var s struct {
		CIDRs []string `json:"cidrs"`
	}
	_ = json.Unmarshal(b, &s)
	return s.CIDRs, nil
}

func (m *managedRoutes) save(cidrs []string) error {
	_ = os.MkdirAll(filepath.Dir(stateFile()), 0o755)
	b, _ := json.MarshalIndent(struct {
		CIDRs []string `json:"cidrs"`
	}{cidrs}, "", "  ")
	return os.WriteFile(stateFile(), b, 0o644)
}

func stateFile() string {
	pdata := os.Getenv("PROGRAMDATA")
	if pdata == "" {
		pdata = `C:\ProgramData`
	}
	return filepath.Join(pdata, "VAGG Client", "managed-routes.json")
}

// addRoute: invoca route.exe (nativo Windows). -p torna persistente.
// CIDR a.b.c.d/n é convertido em network + mask dotted.
func addRoute(cidr, gateway string) error {
	net, mask, err := splitCIDR(cidr)
	if err != nil {
		return err
	}
	cmd := exec.Command("route", "-p", "add", net, "mask", mask, gateway)
	out, err := cmd.CombinedOutput()
	if err != nil && !strings.Contains(string(out), "already in route table") {
		return fmt.Errorf("route add %s: %v: %s", cidr, err, out)
	}
	return nil
}

func deleteRoute(cidr string) error {
	net, _, err := splitCIDR(cidr)
	if err != nil {
		return err
	}
	cmd := exec.Command("route", "delete", net)
	_, _ = cmd.CombinedOutput() // ignora erro se já não existe
	return nil
}

func splitCIDR(cidr string) (network, dotMask string, err error) {
	parts := strings.SplitN(cidr, "/", 2)
	if len(parts) != 2 {
		return "", "", fmt.Errorf("CIDR inválido: %s", cidr)
	}
	network = parts[0]
	bits := 0
	_, _ = fmt.Sscanf(parts[1], "%d", &bits)
	if bits < 0 || bits > 32 {
		return "", "", fmt.Errorf("prefix inválido: %s", parts[1])
	}
	m := uint32(0xFFFFFFFF) << (32 - bits)
	dotMask = fmt.Sprintf("%d.%d.%d.%d", (m>>24)&0xff, (m>>16)&0xff, (m>>8)&0xff, m&0xff)
	return network, dotMask, nil
}

func gatewayPath() string {
	pdata := os.Getenv("PROGRAMDATA")
	if pdata == "" {
		pdata = `C:\ProgramData`
	}
	return filepath.Join(pdata, "VAGG Client", "gateway")
}

// gateway = ler do config local (escrito pela GUI no login via op set-gateway).
func gatewayIP() string {
	b, err := os.ReadFile(gatewayPath())
	if err == nil {
		return strings.TrimSpace(string(b))
	}
	return ""
}

func setGatewayIP(host string) error {
	host = strings.TrimSpace(host)
	if host == "" {
		return fmt.Errorf("host vazio")
	}
	_ = os.MkdirAll(filepath.Dir(gatewayPath()), 0o755)
	return os.WriteFile(gatewayPath(), []byte(host), 0o644)
}

func handle(req map[string]any, mr *managedRoutes) map[string]string {
	op, _ := req["op"].(string)
	switch op {
	case "ping":
		return map[string]string{"ok": "1"}
	case "set-gateway":
		host, _ := req["host"].(string)
		if err := setGatewayIP(host); err != nil {
			return map[string]string{"ok": "0", "err": err.Error()}
		}
		return map[string]string{"ok": "1", "gateway": strings.TrimSpace(host)}
	case "apply":
		raw, _ := req["cidrs"].([]any)
		want := make([]string, 0, len(raw))
		for _, x := range raw {
			if s, ok := x.(string); ok {
				want = append(want, s)
			}
		}
		mr.mu.Lock()
		defer mr.mu.Unlock()
		current, _ := mr.load()
		gw := gatewayIP()
		if gw == "" {
			return map[string]string{"ok": "0", "err": "gateway nao configurado pelo GUI"}
		}
		// remove o que saiu
		for _, c := range current {
			if !contains(want, c) {
				_ = deleteRoute(c)
			}
		}
		// adiciona o que entrou
		for _, c := range want {
			if !contains(current, c) {
				if err := addRoute(c, gw); err != nil {
					log.Printf("addRoute %s: %v", c, err)
				}
			}
		}
		_ = mr.save(want)
		return map[string]string{"ok": "1", "applied": fmt.Sprintf("%d", len(want))}
	case "clear":
		mr.mu.Lock()
		defer mr.mu.Unlock()
		current, _ := mr.load()
		for _, c := range current {
			_ = deleteRoute(c)
		}
		_ = mr.save(nil)
		return map[string]string{"ok": "1"}
	}
	return map[string]string{"ok": "0", "err": "op desconhecida"}
}

func contains(s []string, e string) bool {
	for _, x := range s {
		if x == e {
			return true
		}
	}
	return false
}

// ----- Service plumbing -----

type pipeService struct{ mr *managedRoutes }

func (p *pipeService) Execute(args []string, r <-chan svc.ChangeRequest, s chan<- svc.Status) (bool, uint32) {
	const accepted = svc.AcceptStop | svc.AcceptShutdown
	s <- svc.Status{State: svc.StartPending}
	// SDDL:
	//   D:P                  → DACL, protected (não herda do parent)
	//   (A;;GA;;;SY)         → allow GENERIC_ALL pro LocalSystem (próprio service)
	//   (A;;GA;;;BA)         → allow GENERIC_ALL pros Built-in Administrators
	//   (A;;GRGW;;;IU)       → allow GENERIC_READ + GENERIC_WRITE pros usuários
	//                           interativos. Antes era só GR e a GUI batia em
	//                           "CreateFile pipe: Acesso negado" — read-only.
	listener, err := winio.ListenPipe(pipeName, &winio.PipeConfig{
		SecurityDescriptor: "D:P(A;;GA;;;SY)(A;;GA;;;BA)(A;;GRGW;;;IU)",
	})
	if err != nil {
		log.Fatalf("listen pipe: %v", err)
	}
	go func() {
		for {
			conn, err := listener.Accept()
			if err != nil {
				return
			}
			go p.handleConn(conn)
		}
	}()
	s <- svc.Status{State: svc.Running, Accepts: accepted}
	for c := range r {
		switch c.Cmd {
		case svc.Stop, svc.Shutdown:
			s <- svc.Status{State: svc.StopPending}
			_ = listener.Close()
			return false, 0
		}
	}
	return false, 0
}

func (p *pipeService) handleConn(conn net.Conn) {
	defer conn.Close()
	scanner := bufio.NewScanner(conn)
	if !scanner.Scan() {
		return
	}
	var req map[string]any
	if err := json.Unmarshal(scanner.Bytes(), &req); err != nil {
		_, _ = conn.Write([]byte(`{"ok":"0","err":"json invalido"}`))
		return
	}
	resp := handle(req, p.mr)
	b, _ := json.Marshal(resp)
	_, _ = conn.Write(b)
}

func main() {
	mr := &managedRoutes{}
	isService, err := svc.IsWindowsService()
	if err != nil {
		log.Fatalf("svc check: %v", err)
	}
	if !isService {
		// modo debug — `go run ./cmd/service` no terminal
		log.Println("rodando em modo debug (Ctrl+C para sair)")
		_ = debug.Run(serviceName, &pipeService{mr})
		return
	}
	_ = svc.Run(serviceName, &pipeService{mr})
}
