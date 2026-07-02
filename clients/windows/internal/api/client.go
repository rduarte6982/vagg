// Package api — cliente HTTP do vagg-server (autenticado via JWT).
package api

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/url"
	"strings"
	"time"
)

type Client struct {
	base         string
	token        string
	refreshToken string
	hc           *http.Client
	// Credentials cached pra fallback de re-login completo quando o refresh
	// expira (refresh TTL típico 7 dias; access TTL 15 min). Sem cache, o
	// app teria que pedir senha de novo após 7 dias.
	user     string
	password string
}

func NewClient(baseURL, token string) *Client {
	return &Client{
		base:  strings.TrimRight(baseURL, "/"),
		token: token,
		hc:    &http.Client{Timeout: 15 * time.Second},
	}
}

// ----- /auth/login + refresh -----

type tokenPair struct {
	AccessToken  string `json:"access_token"`
	RefreshToken string `json:"refresh_token"`
}

// Login devolve o access token. Usa form-encoded conforme OAuth2PasswordRequestForm.
func (c *Client) Login(user, password string) (string, error) {
	body := url.Values{}
	body.Set("username", user)
	body.Set("password", password)
	req, _ := http.NewRequest(http.MethodPost, c.base+"/api/v1/auth/login",
		strings.NewReader(body.Encode()))
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	resp, err := c.hc.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return "", fmt.Errorf("login %d", resp.StatusCode)
	}
	var t tokenPair
	if err := json.NewDecoder(resp.Body).Decode(&t); err != nil {
		return "", err
	}
	c.token = t.AccessToken
	c.refreshToken = t.RefreshToken
	c.user = user
	c.password = password
	return t.AccessToken, nil
}

// refreshAccess troca o refresh_token por um novo access_token (sem precisar
// re-digitar senha). Retorna erro se o refresh também expirou — caller deve
// chamar Login() de novo nesse caso (com a senha cacheada).
func (c *Client) refreshAccess() error {
	if c.refreshToken == "" {
		return fmt.Errorf("no refresh token (login first)")
	}
	body, _ := json.Marshal(map[string]string{"refresh_token": c.refreshToken})
	req, _ := http.NewRequest(http.MethodPost, c.base+"/api/v1/auth/refresh", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	resp, err := c.hc.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return fmt.Errorf("refresh %d", resp.StatusCode)
	}
	var t tokenPair
	if err := json.NewDecoder(resp.Body).Decode(&t); err != nil {
		return err
	}
	c.token = t.AccessToken
	if t.RefreshToken != "" {
		c.refreshToken = t.RefreshToken
	}
	return nil
}

// recoverAuth tenta refresh; se falhar, faz login completo com credenciais
// cacheadas. Usado quando uma chamada retorna 401.
func (c *Client) recoverAuth() error {
	if err := c.refreshAccess(); err == nil {
		return nil
	}
	if c.user == "" {
		return fmt.Errorf("session expired and no cached credentials — please login again")
	}
	_, err := c.Login(c.user, c.password)
	return err
}

// ----- /me/clients -----

type RouteEntry struct {
	CIDR        string `json:"cidr"`
	ClientID    string `json:"client_id"`
	ClientName  string `json:"client_name"`
	Label       string `json:"label"`
	IsMain      bool   `json:"is_main"`
}

// Client_ é a representação simplificada do cliente vista pelo VAGG Client.
// Underscored pra não conflitar com o tipo HTTP.
type Client_ struct {
	ID          string   `json:"id"`
	Name        string   `json:"name"`
	VPNType     string   `json:"vpn_type"`
	TunnelState string   `json:"tunnel_state"`
	Routes      []string `json:"routes"`
	// Metadados de autenticação (modelo híbrido) — a UI usa pra decidir se, ao
	// reconectar, pede OTP ao usuário ou avisa que o SAML expirou.
	AuthMethod      string `json:"auth_method"`
	RequiresOTP     bool   `json:"requires_otp"`
	HasSAMLCookie   bool   `json:"has_saml_cookie"`
	SAMLCookieValid *bool  `json:"saml_cookie_valid"`
}

type MyClientsResponse struct {
	Routes  []RouteEntry `json:"routes"`
	Clients []Client_    `json:"clients"`
	User    string       `json:"user"`
	IsAdmin bool         `json:"is_admin"`
}

func (c *Client) MyClients(ctx context.Context) (*MyClientsResponse, error) {
	doReq := func() (*MyClientsResponse, int, string, error) {
		req, _ := http.NewRequestWithContext(ctx, http.MethodGet, c.base+"/api/v1/me/clients", nil)
		if c.token != "" {
			req.Header.Set("Authorization", "Bearer "+c.token)
		}
		resp, err := c.hc.Do(req)
		if err != nil {
			return nil, 0, "", err
		}
		defer resp.Body.Close()
		if resp.StatusCode != 200 {
			var b bytes.Buffer
			_, _ = b.ReadFrom(resp.Body)
			return nil, resp.StatusCode, b.String(), nil
		}
		var out MyClientsResponse
		if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
			return nil, resp.StatusCode, "", err
		}
		return &out, 200, "", nil
	}

	// Primeira tentativa
	out, status, body, err := doReq()
	if err != nil {
		return nil, err
	}
	if status == 200 {
		return out, nil
	}

	// 401 → tenta refresh + retry (silencioso pro usuário)
	if status == 401 {
		if rerr := c.recoverAuth(); rerr != nil {
			return nil, fmt.Errorf("HTTP %d: %s", status, body)
		}
		out, status, body, err = doReq()
		if err != nil {
			return nil, err
		}
		if status == 200 {
			return out, nil
		}
	}
	return nil, fmt.Errorf("HTTP %d: %s", status, body)
}

// HasRefreshableSession indica se o app pode chamar recoverAuth (refresh ou
// re-login com credenciais cacheadas). Usado pelo dashboard pra decidir se
// mostra "service offline" como erro ou só como info.
func (c *Client) HasRefreshableSession() bool {
	return c.refreshToken != "" || (c.user != "" && c.password != "")
}

// Tokens devolve o par de tokens atual — usado pelo app pra persistir em disco
// (inclusive após rotação do refresh no recoverAuth).
func (c *Client) Tokens() (access, refresh string) {
	return c.token, c.refreshToken
}

// SetTokens restaura o par de tokens (chamado no auto-login ao ler do disco).
func (c *Client) SetTokens(access, refresh string) {
	c.token = access
	c.refreshToken = refresh
}

// ----- Ações self-service (modelo híbrido) -----

// doWithAuth executa um request autenticado; em 401 tenta recoverAuth (refresh
// ou re-login com credenciais cacheadas) e repete uma vez. Recebe um builder
// porque o body de um POST não pode ser reusado após o primeiro envio.
func (c *Client) doWithAuth(build func() (*http.Request, error)) (*http.Response, error) {
	req, err := build()
	if err != nil {
		return nil, err
	}
	if c.token != "" {
		req.Header.Set("Authorization", "Bearer "+c.token)
	}
	resp, err := c.hc.Do(req)
	if err != nil {
		return nil, err
	}
	if resp.StatusCode != http.StatusUnauthorized {
		return resp, nil
	}
	// 401 → tenta recuperar sessão e repetir uma vez.
	resp.Body.Close()
	if rerr := c.recoverAuth(); rerr != nil {
		return nil, fmt.Errorf("sessão expirada: %w", rerr)
	}
	req2, err := build()
	if err != nil {
		return nil, err
	}
	if c.token != "" {
		req2.Header.Set("Authorization", "Bearer "+c.token)
	}
	return c.hc.Do(req2)
}

// Reconnect re-sobe o túnel de um client autorizado (POST /me/clients/{id}/reconnect).
func (c *Client) Reconnect(ctx context.Context, clientID string) error {
	build := func() (*http.Request, error) {
		return http.NewRequestWithContext(ctx, http.MethodPost,
			c.base+"/api/v1/me/clients/"+url.PathEscape(clientID)+"/reconnect", nil)
	}
	resp, err := c.doWithAuth(build)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusAccepted && resp.StatusCode != http.StatusOK {
		var b bytes.Buffer
		_, _ = b.ReadFrom(resp.Body)
		return fmt.Errorf("reconnect HTTP %d: %s", resp.StatusCode, b.String())
	}
	return nil
}

// SubmitOTP encaminha um código OTP pro túnel de um client autorizado
// (POST /me/clients/{id}/otp) — reautenticação quando o túnel pede OTP.
func (c *Client) SubmitOTP(ctx context.Context, clientID, code string) error {
	payload, _ := json.Marshal(map[string]string{"code": code})
	build := func() (*http.Request, error) {
		r, err := http.NewRequestWithContext(ctx, http.MethodPost,
			c.base+"/api/v1/me/clients/"+url.PathEscape(clientID)+"/otp",
			bytes.NewReader(payload))
		if err == nil {
			r.Header.Set("Content-Type", "application/json")
		}
		return r, err
	}
	resp, err := c.doWithAuth(build)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		var b bytes.Buffer
		_, _ = b.ReadFrom(resp.Body)
		return fmt.Errorf("otp HTTP %d: %s", resp.StatusCode, b.String())
	}
	return nil
}
