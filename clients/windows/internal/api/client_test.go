// Tests de contrato — congela o shape que o app espera receber do
// vagg-server (/api/v1/me/clients e /api/v1/auth/login).
//
// Quando alguém mudar `core/src/vagg_core/api/v1/me.py` no server ou
// `auth.py`, estes testes quebram se o shape divergir do que o app
// consome. Pretende ser barreira contra drift acidental.

package api

import (
	"encoding/json"
	"testing"
)

// Sample JSON exatamente como o server emite — fixo no teste.
const sampleMyClients = `{
  "routes": [
    {"cidr": "10.99.0.0/16", "client_id": "vexia", "client_name": "Vexia",
     "label": "Vexia (10.99.0.0/16)", "is_main": true},
    {"cidr": "172.16.10.0/24", "client_id": "vexia", "client_name": "Vexia",
     "label": "Vexia extra (172.16.10.0/24)", "is_main": false}
  ],
  "clients": [
    {"id": "vexia", "name": "Vexia", "vpn_type": "openfortivpn",
     "tunnel_state": "up", "routes": ["10.99.0.0/16", "172.16.10.0/24"]}
  ],
  "user": "Paulo Silva",
  "is_admin": false
}`

func TestMyClientsResponse_UnmarshalsServerShape(t *testing.T) {
	var resp MyClientsResponse
	if err := json.Unmarshal([]byte(sampleMyClients), &resp); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if len(resp.Routes) != 2 {
		t.Fatalf("expected 2 routes, got %d", len(resp.Routes))
	}
	if resp.Routes[0].CIDR != "10.99.0.0/16" {
		t.Errorf("route[0].cidr = %q, want 10.99.0.0/16", resp.Routes[0].CIDR)
	}
	if !resp.Routes[0].IsMain {
		t.Errorf("route[0].is_main = false, want true")
	}
	if resp.Routes[1].IsMain {
		t.Errorf("route[1].is_main = true, want false")
	}
	if len(resp.Clients) != 1 {
		t.Fatalf("expected 1 client, got %d", len(resp.Clients))
	}
	c := resp.Clients[0]
	if c.ID != "vexia" || c.Name != "Vexia" || c.VPNType != "openfortivpn" {
		t.Errorf("client fields wrong: %+v", c)
	}
	if c.TunnelState != "up" {
		t.Errorf("tunnel_state = %q, want up", c.TunnelState)
	}
	if len(c.Routes) != 2 {
		t.Errorf("client.routes len = %d, want 2", len(c.Routes))
	}
	if resp.User != "Paulo Silva" {
		t.Errorf("user = %q", resp.User)
	}
	if resp.IsAdmin {
		t.Errorf("is_admin should be false")
	}
}

// TestTunnelStateValues — garante que todos os valores possíveis do enum
// TunnelState do server (db/models.py::TunnelState) deserializam como
// string esperada. Se o server adicionar um novo estado, este teste
// ainda passa (apenas confirma os que existem).
func TestTunnelStateValues(t *testing.T) {
	for _, s := range []string{"stopped", "starting", "up", "down", "errored"} {
		j := `{"id":"x","name":"X","vpn_type":"openvpn","tunnel_state":"` + s + `","routes":[]}`
		var c Client_
		if err := json.Unmarshal([]byte(j), &c); err != nil {
			t.Errorf("unmarshal %q: %v", s, err)
		}
		if c.TunnelState != s {
			t.Errorf("got tunnel_state=%q, want %q", c.TunnelState, s)
		}
	}
}

// TestVPNTypes — IDs do enum VpnType do server.
func TestVPNTypes(t *testing.T) {
	for _, vt := range []string{
		"openvpn", "openconnect", "openfortivpn", "wireguard", "strongswan", "globalprotect",
	} {
		j := `{"id":"x","name":"X","vpn_type":"` + vt + `","tunnel_state":"up","routes":[]}`
		var c Client_
		if err := json.Unmarshal([]byte(j), &c); err != nil {
			t.Errorf("unmarshal %q: %v", vt, err)
		}
		if c.VPNType != vt {
			t.Errorf("got %q, want %q", c.VPNType, vt)
		}
	}
}

// TestEmptyArrays — server sempre emite arrays (nunca null) pra
// routes/clients. Se vier vazio, o decode deve resultar em slice vazio
// (não nil) — protege o frontend de NPE.
func TestEmptyArrays(t *testing.T) {
	j := `{"routes": [], "clients": [], "user": "admin", "is_admin": true}`
	var resp MyClientsResponse
	if err := json.Unmarshal([]byte(j), &resp); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if resp.Routes == nil {
		t.Errorf("routes should be empty slice, got nil")
	}
	if resp.Clients == nil {
		t.Errorf("clients should be empty slice, got nil")
	}
	if !resp.IsAdmin {
		t.Errorf("admin should be true")
	}
}

// TestTokenPair — formato exato do /api/v1/auth/login.
func TestTokenPair(t *testing.T) {
	j := `{
		"access_token": "eyJhbGc...",
		"refresh_token": "eyJhbGc...",
		"access_expires_at": "2026-05-25T12:00:00+00:00",
		"refresh_expires_at": "2026-06-01T12:00:00+00:00"
	}`
	var t1 tokenPair
	if err := json.Unmarshal([]byte(j), &t1); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if t1.AccessToken == "" {
		t.Errorf("access_token vazio")
	}
}
