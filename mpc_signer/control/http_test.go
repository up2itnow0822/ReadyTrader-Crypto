package control

import (
	"bufio"
	"context"
	"crypto/tls"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func TestSlowBodyHasFiniteReadDeadline(t *testing.T) {
	handler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if _, err := io.ReadAll(r.Body); err != nil {
			http.Error(w, "read deadline", 408)
			return
		}
		w.WriteHeader(200)
	})
	server := NewHTTPServer("127.0.0.1:0", handler, nil, 50*time.Millisecond)
	listener, err := net.Listen("tcp", server.Addr)
	if err != nil {
		t.Fatal(err)
	}
	defer server.Close()
	go server.Serve(listener)
	conn, err := net.Dial("tcp", listener.Addr().String())
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	_ = conn.SetDeadline(time.Now().Add(time.Second))
	_, _ = io.WriteString(conn, "POST / HTTP/1.1\r\nHost: localhost\r\nContent-Length: 999\r\n\r\na")
	started := time.Now()
	line, err := bufio.NewReader(conn).ReadString('\n')
	if err != nil {
		t.Fatal("server left body open until client deadline", err)
	}
	if time.Since(started) > 500*time.Millisecond || !strings.Contains(line, "408") {
		t.Fatalf("slow body not bounded: %s", line)
	}
}
func TestConnectionBudgetRejectsExcessSockets(t *testing.T) {
	base, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	limited := LimitListener(base, 1)
	defer limited.Close()
	accepted := make(chan net.Conn, 2)
	go func() {
		for {
			c, err := limited.Accept()
			if err != nil {
				return
			}
			accepted <- c
		}
	}()
	first, err := net.Dial("tcp", base.Addr().String())
	if err != nil {
		t.Fatal(err)
	}
	defer first.Close()
	serverFirst := <-accepted
	defer serverFirst.Close()
	second, err := net.Dial("tcp", base.Addr().String())
	if err != nil {
		t.Fatal(err)
	}
	defer second.Close()
	_ = second.SetReadDeadline(time.Now().Add(500 * time.Millisecond))
	buf := make([]byte, 1)
	_, err = second.Read(buf)
	if err == nil {
		t.Fatal("unexpected data")
	}
	if nerr, ok := err.(net.Error); ok && nerr.Timeout() {
		t.Fatal("excess connection remained open")
	}
	select {
	case c := <-accepted:
		_ = c.Close()
		t.Fatal("over-budget connection accepted")
	default:
	}
}
func TestPeerRefusesPlaintextAndRedirects(t *testing.T) {
	p := HTTPPeer{Client: http.DefaultClient, RuntimeURL: "http://localhost"}
	if err := p.Call(context.Background(), "/internal/start_sign", nil, nil); err == nil {
		t.Fatal("plaintext peer accepted")
	}
	targetCalls := 0
	target := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { targetCalls++ }))
	defer target.Close()
	redirect := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { http.Redirect(w, r, target.URL, 307) }))
	defer redirect.Close()
	client := redirect.Client()
	client.Transport.(*http.Transport).TLSClientConfig = &tls.Config{InsecureSkipVerify: true} // isolated test servers only
	p = HTTPPeer{Client: client, RuntimeURL: redirect.URL}
	if err := p.Call(context.Background(), "/internal/start_sign", nil, nil); err == nil {
		t.Fatal("redirect accepted")
	}
	if targetCalls != 0 {
		t.Fatal("approval forwarded through redirect")
	}
}
