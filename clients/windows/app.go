// app.go — bindings expostos ao frontend (chamados via window.go.main.App.X()).
//
// Todas as operações que mexem com rede / disco do sistema passam pelo
// service via named pipe. O frontend nunca chama syscall direto.
package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/url"
	"strings"
	"sync"
	"time"

	"github.com/rduarte6982/vagg/clients/windows/internal/api"
	"github.com/rduarte6982/vagg/clients/windows/internal/routes"
	"github.com/wailsapp/wails/v2/pkg/runtime"
)

// App é a struct exposta ao frontend pelo Wails.
type App struct {
	ctx     context.Context
	mu      sync.Mutex
	server     string          // URL do vagg-server
	cli        *api.Client     // HTTP client autenticado
	rm         *routes.Manager // diff/apply via service pipe
	user       string
	isAdmin    bool
	lastAccess string // último access token persistido (detecta rotação do refresh)
	stop       chan struct{}
}

func NewApp() *App {
	return &App{stop: make(chan struct{})}
}

func (a *App) startup(ctx context.Context) {
	a.ctx = ctx
	cfg := loadConfig()
	a.server = cfg.ServerURL
	a.user = cfg.User
	a.rm = routes.NewManager()

	// Tray pode controlar a janela agora que temos contexto Wails.
	registerTrayHandlers(
		func() {
			runtime.WindowShow(ctx)
			runtime.WindowUnminimise(ctx)
		},
		func() {
			runtime.Quit(ctx)
		},
	)

	// Auto-login se houver sessão salva. Restaura access + refresh pra permitir
	// renovação silenciosa mesmo após restart do app.
	if access, refresh := loadSession(); access != "" && a.server != "" {
		a.cli = api.NewClient(a.server, access)
		a.cli.SetTokens(access, refresh)
		a.lastAccess = access
		// re-sincroniza gateway com o service (idempotente).
		if host := hostFromURL(a.server); host != "" && a.rm != nil {
			_ = a.rm.SetGateway(host)
		}
		go a.syncLoop()
	}
}

func (a *App) shutdown(ctx context.Context) {
	close(a.stop)
	stopTray()
}

// ---------------------- Bindings ao frontend ----------------------

// Status (chamado pelo dashboard a cada N segundos pra atualizar UI).
//
// IMPORTANTE: Clients DEVE sempre ser slice (mesmo que vazio) — nunca nil.
// Se vier nil, JSON marshal vira `null` e quebra o React em status.clients.length.
type Status struct {
	Connected    bool          `json:"connected"`
	ServerURL    string        `json:"serverUrl"`
	User         string        `json:"user"`
	IsAdmin      bool          `json:"isAdmin"`
	LastSync     string        `json:"lastSync"`
	NextSync     string        `json:"nextSync"`
	RoutesActive int           `json:"routesActive"`
	Clients      []api.Client_ `json:"clients"`
	ServiceUp    bool          `json:"serviceUp"`
	LastError    string        `json:"lastError"`
}

func (a *App) GetStatus() Status {
	a.mu.Lock()
	defer a.mu.Unlock()
	st := Status{
		ServerURL: a.server,
		User:      a.user,
		IsAdmin:   a.isAdmin,
		Connected: a.cli != nil,
		Clients:   []api.Client_{}, // garante slice vazio em vez de nil
	}
	if a.rm != nil {
		st.ServiceUp = a.rm.Healthy()
		if snap := a.rm.LastSnapshot(); snap != nil {
			st.RoutesActive = len(snap.Routes)
			if snap.Clients != nil {
				st.Clients = snap.Clients
			}
			st.LastSync = snap.At.Format(time.RFC3339)
		}
	}
	return st
}

// Login chamado da tela de login. Aceita admin do .env OU consultor com senha.
func (a *App) Login(serverURL, user, password string) error {
	cli := api.NewClient(serverURL, "")
	_, err := cli.Login(user, password)
	if err != nil {
		// Mensagem amigável — o ApiError do backend vem com 401 normalmente.
		msg := err.Error()
		if strings.Contains(msg, "401") {
			return errors.New("usuário ou senha inválidos")
		}
		if strings.Contains(msg, "no such host") || strings.Contains(msg, "connection refused") {
			return fmt.Errorf("não consegui falar com %s — verifique a URL e a rede", serverURL)
		}
		return fmt.Errorf("falha no login: %s", msg)
	}
	// Reusa o MESMO client que fez o login — ele carrega o refresh token e as
	// credenciais cacheadas. Criar um NewClient aqui (bug anterior) descartava
	// ambos, deixando o recoverAuth sem como renovar a sessão.
	access, refresh := cli.Tokens()
	a.mu.Lock()
	a.server = serverURL
	a.user = user
	a.cli = cli
	a.lastAccess = access
	a.mu.Unlock()

	saveConfig(Config{ServerURL: serverURL, User: user})
	storeSession(access, refresh)

	// Configura o gateway no service ANTES da primeira sync — sem isso o
	// service rejeita o `apply` com "gateway nao configurado".
	if host := hostFromURL(serverURL); host != "" && a.rm != nil {
		if err := a.rm.SetGateway(host); err != nil {
			runtime.LogWarningf(a.ctx, "set-gateway falhou: %v", err)
		}
	}

	go a.syncLoop()
	// Faz uma sync imediata pra popular dashboard antes de retornar — evita
	// tela em branco enquanto o ticker de 30s não dispara.
	_ = a.syncOnce()
	return nil
}

// hostFromURL extrai o host de "http://192.168.68.102" ou "https://vagg.x.com".
// Aceita inputs com ou sem schema; retorna "" se não conseguir parsear.
func hostFromURL(s string) string {
	s = strings.TrimSpace(s)
	if s == "" {
		return ""
	}
	if !strings.Contains(s, "://") {
		s = "http://" + s
	}
	u, err := url.Parse(s)
	if err != nil {
		return ""
	}
	return u.Hostname()
}

func (a *App) Logout() {
	a.mu.Lock()
	a.cli = nil
	a.user = ""
	a.isAdmin = false
	a.mu.Unlock()
	clearStoredToken()
	if a.rm != nil {
		_ = a.rm.RemoveAllManaged()
		a.rm.SetSnapshot(routes.Snapshot{Clients: []api.Client_{}, At: time.Now()})
	}
}

// SyncNow força uma sincronização imediata (apenas reconcilia diff).
func (a *App) SyncNow() error {
	return a.syncOnce()
}

// ForceRefresh: apaga TODAS as rotas geridas pelo VAGG e recria do zero.
// Útil quando o estado local divergiu (e.g. usuário deletou rota manualmente,
// service ficou offline e perdeu sincronia, etc). Transparente: um clique e
// pronto.
func (a *App) ForceRefresh() error {
	a.mu.Lock()
	cli := a.cli
	a.mu.Unlock()
	if cli == nil {
		return errors.New("não autenticado — faça login antes")
	}
	if a.rm == nil {
		return errors.New("service indisponível")
	}
	// 1) Garante gateway atualizado (caso o usuário tenha trocado de servidor).
	if host := hostFromURL(a.server); host != "" {
		_ = a.rm.SetGateway(host)
	}
	// 2) Limpa todas as rotas conhecidas no Windows.
	if err := a.rm.RemoveAllManaged(); err != nil {
		// não é fatal — o sync abaixo vai tentar adicionar de qualquer jeito.
		runtime.LogWarningf(a.ctx, "force-refresh clear: %v", err)
	}
	// 3) Re-busca /me/clients e reaplica.
	return a.syncOnce()
}

func (a *App) GetServerURL() string { return a.server }

// Reconnect re-sobe o túnel de um client autorizado (modelo híbrido: o
// consultor pode reconectar quando o túnel cai). Após reconectar, sincroniza
// pra atualizar o estado na UI.
func (a *App) Reconnect(clientID string) error {
	a.mu.Lock()
	cli := a.cli
	a.mu.Unlock()
	if cli == nil {
		return errors.New("não autenticado — faça login antes")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	if err := cli.Reconnect(ctx, clientID); err != nil {
		return err
	}
	a.persistTokensIfChanged()
	_ = a.syncOnce()
	return nil
}

// SubmitOTP encaminha um código OTP pro túnel de um client autorizado
// (reautenticação quando o túnel pede OTP).
func (a *App) SubmitOTP(clientID, code string) error {
	code = strings.TrimSpace(code)
	if code == "" {
		return errors.New("código OTP vazio")
	}
	a.mu.Lock()
	cli := a.cli
	a.mu.Unlock()
	if cli == nil {
		return errors.New("não autenticado — faça login antes")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	if err := cli.SubmitOTP(ctx, clientID, code); err != nil {
		return err
	}
	a.persistTokensIfChanged()
	return nil
}

// persistTokensIfChanged re-grava a sessão em disco quando o access token mudou
// (o recoverAuth pode ter rotacionado access e refresh). Sem isto, uma rotação
// do refresh seria perdida no próximo restart do app.
func (a *App) persistTokensIfChanged() {
	a.mu.Lock()
	cli := a.cli
	a.mu.Unlock()
	if cli == nil {
		return
	}
	access, refresh := cli.Tokens()
	if access == "" {
		return
	}
	a.mu.Lock()
	changed := access != a.lastAccess
	if changed {
		a.lastAccess = access
	}
	a.mu.Unlock()
	if changed {
		storeSession(access, refresh)
	}
}

// HideToTray esconde a janela (usado pelo botão "Fechar pro tray" do frontend).
func (a *App) HideToTray() {
	if a.ctx != nil {
		runtime.WindowHide(a.ctx)
	}
}

// ---------------------- Loop de sincronização ----------------------

func (a *App) syncLoop() {
	t := time.NewTicker(30 * time.Second)
	defer t.Stop()
	_ = a.syncOnce()
	for {
		select {
		case <-a.stop:
			return
		case <-t.C:
			_ = a.syncOnce()
		}
	}
}

func (a *App) syncOnce() error {
	a.mu.Lock()
	cli := a.cli
	a.mu.Unlock()
	if cli == nil {
		return nil
	}
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	resp, err := cli.MyClients(ctx)
	if err != nil {
		if a.ctx != nil {
			runtime.EventsEmit(a.ctx, "sync.error", err.Error())
		}
		return err
	}
	// MyClients pode ter rotacionado os tokens via recoverAuth (401) — persiste
	// se mudou, pra sobreviver a um restart do app.
	a.persistTokensIfChanged()
	want := make([]string, 0, len(resp.Routes))
	for _, r := range resp.Routes {
		want = append(want, r.CIDR)
	}
	// Não bloqueia se o service estiver offline; apenas registra o erro
	// e continua mostrando os clientes na UI.
	applyErr := a.rm.Apply(want)

	clients := resp.Clients
	if clients == nil {
		clients = []api.Client_{}
	}
	a.rm.SetSnapshot(routes.Snapshot{
		Routes:  want,
		Clients: clients,
		At:      time.Now(),
	})
	a.mu.Lock()
	if resp.User != "" {
		a.user = resp.User
	}
	a.isAdmin = resp.IsAdmin
	a.mu.Unlock()

	if a.ctx != nil {
		if applyErr != nil {
			runtime.EventsEmit(a.ctx, "sync.error",
				fmt.Sprintf("rotas não puderam ser aplicadas: %v", applyErr))
		}
		runtime.EventsEmit(a.ctx, "sync.ok", a.GetStatus())
	}
	return nil
}

// ----- Persistência simples -----

type Config struct {
	ServerURL string `json:"server_url"`
	User      string `json:"user"`
}

func loadConfig() Config {
	data, err := readAppData("config.json")
	if err != nil {
		return Config{}
	}
	var c Config
	_ = json.Unmarshal(data, &c)
	return c
}

func saveConfig(c Config) {
	data, _ := json.MarshalIndent(c, "", "  ")
	_ = writeAppData("config.json", data)
}
