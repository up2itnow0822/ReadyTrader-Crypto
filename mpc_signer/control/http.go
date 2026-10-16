package control

import (
	"bytes"
	"context"
	"crypto/tls"
	"encoding/json"
	"errors"
	"io"
	"net"
	"net/http"
	"net/url"
	"sync"
	"time"
)

type HTTPPeer struct {
	Client       *http.Client
	RuntimeURL   string
	BootstrapURL string
}

func (p HTTPPeer) Call(ctx context.Context, path string, payload any, result any) error {
	base := p.RuntimeURL
	if path == "/internal/start_dkg" || path == "/internal/commit_dkg" {
		base = p.BootstrapURL
	}
	parsed, err := url.Parse(base)
	if err != nil || parsed.Scheme != "https" || parsed.Host == "" || parsed.User != nil || parsed.RawQuery != "" || parsed.Fragment != "" || parsed.Path != "" {
		return errors.New("peer must be an https origin")
	}
	body, err := json.Marshal(payload)
	if err != nil {
		return err
	}
	req, err := http.NewRequestWithContext(ctx, "POST", base+path, bytes.NewReader(body))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	if p.Client == nil {
		return errors.New("peer client required")
	}
	client := *p.Client
	client.CheckRedirect = func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }
	resp, err := client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return errors.New("peer refused operation")
	}
	raw, err := io.ReadAll(io.LimitReader(resp.Body, 65537))
	if err != nil || len(raw) > 65536 {
		return errors.New("invalid peer response")
	}
	if result != nil {
		return json.Unmarshal(raw, result)
	}
	return nil
}
func NewHTTPServer(addr string, handler http.Handler, tlsConfig *tls.Config, budget time.Duration) *http.Server {
	if budget <= 0 || budget > 60*time.Second {
		budget = 60 * time.Second
	}
	return &http.Server{Addr: addr, Handler: handler, TLSConfig: tlsConfig, ReadHeaderTimeout: min(budget, 5*time.Second), ReadTimeout: min(budget, 10*time.Second), WriteTimeout: budget + time.Second, IdleTimeout: 15 * time.Second, MaxHeaderBytes: 16384,
		// HTTP/2 multiplexing otherwise bypasses the socket admission bound.
		TLSNextProto: map[string]func(*http.Server, *tls.Conn, http.Handler){}}
}

type limitedListener struct {
	net.Listener
	slots chan struct{}
}
type limitedConn struct {
	net.Conn
	once    sync.Once
	release func()
}

func (c *limitedConn) Close() error { err := c.Conn.Close(); c.once.Do(c.release); return err }
func (l *limitedListener) Accept() (net.Conn, error) {
	for {
		c, err := l.Listener.Accept()
		if err != nil {
			return nil, err
		}
		select {
		case l.slots <- struct{}{}:
			return &limitedConn{Conn: c, release: func() { <-l.slots }}, nil
		default:
			_ = c.Close()
		}
	}
}
func LimitListener(listener net.Listener, limit int) net.Listener {
	if limit < 1 {
		limit = 1
	}
	return &limitedListener{Listener: listener, slots: make(chan struct{}, limit)}
}
