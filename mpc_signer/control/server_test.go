package control

import (
	"bytes"
	"context"
	"crypto/ed25519"
	"crypto/sha256"
	"crypto/tls"
	"crypto/x509"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

type fakeBackend struct {
	calls       atomic.Int32
	active      atomic.Int32
	initialized bool
	staged      Identity
	mu          sync.Mutex
	sign        func(context.Context) ([]byte, error)
}

func (b *fakeBackend) Address(context.Context) (Identity, error) {
	if !b.initialized {
		return Identity{}, errors.New("uninitialized")
	}
	return Identity{Address: wallet}, nil
}
func (b *fakeBackend) Sign(ctx context.Context, _ string, _ []byte) ([]byte, error) {
	b.calls.Add(1)
	b.active.Add(1)
	defer b.active.Add(-1)
	if b.sign != nil {
		return b.sign(ctx)
	}
	return []byte{1, 2, 3}, nil
}
func (b *fakeBackend) Stage(ctx context.Context, id string) (Identity, error) {
	b.calls.Add(1)
	b.mu.Lock()
	defer b.mu.Unlock()
	b.staged = Identity{Address: wallet, PublicKeyHex: "04" + strings.Repeat("11", 64), CeremonyID: id}
	return b.staged, nil
}
func (b *fakeBackend) Staged() (Identity, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	if b.staged.CeremonyID == "" {
		return Identity{}, errors.New("no staged key")
	}
	return b.staged, nil
}
func (b *fakeBackend) Commit(ctx context.Context, id, pub string) error { b.calls.Add(1); return nil }

type fakePeer struct{ calls atomic.Int32 }

func (p *fakePeer) Call(context.Context, string, any, any) error { p.calls.Add(1); return nil }
func pin(cert string) string                                     { sum := sha256.Sum256([]byte(cert)); return hex.EncodeToString(sum[:]) }
func request(handler http.Handler, method, path, cert string, payload any) *httptest.ResponseRecorder {
	body, _ := json.Marshal(payload)
	req := httptest.NewRequest(method, path, bytes.NewReader(body))
	if cert != "" {
		c := &x509.Certificate{Raw: []byte(cert)}
		req.TLS = &tls.ConnectionState{PeerCertificates: []*x509.Certificate{c}, VerifiedChains: [][]*x509.Certificate{{c}}}
	}
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	return rec
}
func testServer(t *testing.T) (*Server, *fakeBackend, *fakePeer) {
	t.Helper()
	_, key := signedApproval()
	b := &fakeBackend{initialized: true}
	p := &fakePeer{}
	return &Server{Role: 0, Authorizer: Authorizer{testPolicy(), key, t.TempDir()}, Backend: b, Peer: p, WorkloadPin: pin("workload"), PeerPin: pin("peer"), OperatorPin: pin("operator"), Timeout: 100 * time.Millisecond}, b, p
}
func currentRequest() SignRequest {
	p, _ := signedApproval()
	p.ExpiresAt = time.Now().Unix() + 60
	key := ed25519.NewKeyFromSeed(bytes.Repeat([]byte{1}, 32))
	p.SignatureHex = hex.EncodeToString(ed25519.Sign(key, []byte(fmt.Sprintf("readytrader-mpc-approval-v1\n%s\n%d\n%s\n%s", p.ID, p.ExpiresAt, p.Wallet, p.DigestHex))))
	return SignRequest{vectorTx(), p}
}
func TestRuntimeRejectsAnonymousWrongIdentityAndRawDigest(t *testing.T) {
	s, b, p := testServer(t)
	h := s.Handler(false)
	for _, c := range []string{"", "operator", "peer"} {
		r := request(h, "POST", "/sign_transaction", c, currentRequest())
		if r.Code != http.StatusUnauthorized {
			t.Fatalf("identity %q got %d", c, r.Code)
		}
	}
	r := request(h, "POST", "/sign_digest", "workload", map[string]string{"digest_hex": "0x" + vectorDigest})
	if r.Code != 404 {
		t.Fatalf("raw digest route status=%d", r.Code)
	}
	if b.calls.Load() != 0 || p.calls.Load() != 0 {
		t.Fatal("unauthorized MPC work started")
	}
}
func TestRuntimeNeverExposesDKG(t *testing.T) {
	s, b, _ := testServer(t)
	for _, path := range []string{"/dkg", "/internal/start_dkg", "/ceremony/start", "/ceremony/commit"} {
		r := request(s.Handler(false), "POST", path, "operator", nil)
		if r.Code != 404 {
			t.Fatalf("runtime exposes %s: %d", path, r.Code)
		}
	}
	if b.calls.Load() != 0 {
		t.Fatal("runtime started keygen")
	}
}
func TestDKGDisabledByDefault(t *testing.T) {
	s, b, _ := testServer(t)
	r := request(s.Handler(true), "POST", "/ceremony/start", "operator", nil)
	if r.Code != 404 || b.calls.Load() != 0 {
		t.Fatal("bootstrap available by default")
	}
}
func TestFollowerRequiresPeerAndSameApproval(t *testing.T) {
	s, b, _ := testServer(t)
	s.Role = 1
	h := s.Handler(false)
	if r := request(h, "POST", "/internal/start_sign", "workload", currentRequest()); r.Code != 401 {
		t.Fatalf("workload invoked follower: %d", r.Code)
	}
	bad := currentRequest()
	bad.Transaction.Nonce = "10"
	if r := request(h, "POST", "/internal/start_sign", "peer", bad); r.Code != 403 {
		t.Fatalf("follower accepted unapproved intent: %d", r.Code)
	}
	if b.calls.Load() != 0 {
		t.Fatal("follower started unauthorized signing")
	}
}
func TestValidApprovalSignsOnce(t *testing.T) {
	s, b, p := testServer(t)
	h := s.Handler(false)
	req := currentRequest()
	if r := request(h, "POST", "/sign_transaction", "workload", req); r.Code != 200 {
		t.Fatalf("valid signing failed: %d %s", r.Code, r.Body)
	}
	if b.calls.Load() != 1 || p.calls.Load() != 1 {
		t.Fatal("approved signing did not execute exactly once")
	}
	if r := request(h, "POST", "/sign_transaction", "workload", req); r.Code != 403 {
		t.Fatalf("replay accepted: %d", r.Code)
	}
}
func TestSigningPermitHeldUntilCancellationCompletes(t *testing.T) {
	s, b, _ := testServer(t)
	started := make(chan struct{})
	b.sign = func(ctx context.Context) ([]byte, error) { close(started); <-ctx.Done(); return nil, ctx.Err() }
	h := s.Handler(false)
	done := make(chan *httptest.ResponseRecorder, 1)
	go func() { done <- request(h, "POST", "/sign_transaction", "workload", currentRequest()) }()
	select {
	case <-started:
	case <-time.After(time.Second):
		t.Fatal("signing never started")
	}
	if r := request(h, "POST", "/sign_transaction", "workload", currentRequest()); r.Code != 429 {
		t.Fatalf("concurrent work not refused: %d", r.Code)
	}
	select {
	case r := <-done:
		if r.Code != 504 {
			t.Fatalf("deadline status=%d", r.Code)
		}
	case <-time.After(time.Second):
		t.Fatal("deadline failed")
	}
	if b.active.Load() != 0 {
		t.Fatal("permit released while operation active")
	}
	b.sign = nil
	if r := request(h, "POST", "/sign_transaction", "workload", currentRequest()); r.Code != 403 {
		t.Fatalf("permit not released: %d", r.Code)
	}
}
func TestUnknownJSONFieldsAndWrongMethodAreRejected(t *testing.T) {
	s, b, _ := testServer(t)
	for _, p := range []any{map[string]any{"transaction": vectorTx(), "approval": currentRequest().Approval, "digest_hex": "arbitrary"}, map[string]any{"transaction": map[string]any{"type": true}}} {
		if r := request(s.Handler(false), "POST", "/sign_transaction", "workload", p); r.Code != 400 {
			t.Fatalf("malformed JSON accepted: %d", r.Code)
		}
	}
	if r := request(s.Handler(false), "GET", "/sign_transaction", "workload", nil); r.Code != 405 {
		t.Fatalf("GET permitted: %d", r.Code)
	}
	if b.calls.Load() != 0 {
		t.Fatal("bad request reached crypto")
	}
}
func ceremonyProof(stage string) (CeremonyApproval, []ed25519.PublicKey) {
	p := CeremonyApproval{ID: strings.Repeat("bc", 32), CeremonyID: strings.Repeat("bc", 32), ExpiresAt: 1100}
	if stage == "commit" {
		p.ID = strings.Repeat("cd", 32)
		p.PublicKeyHex = "04" + strings.Repeat("11", 64)
	}
	pubs := []ed25519.PublicKey{}
	for _, seed := range []byte{1, 2} {
		key := ed25519.NewKeyFromSeed(bytes.Repeat([]byte{seed}, 32))
		pubs = append(pubs, key.Public().(ed25519.PublicKey))
		msg := fmt.Sprintf("readytrader-mpc-ceremony-v1\n%s\n%s\n%s\n%d\n%s", stage, p.ID, p.CeremonyID, p.ExpiresAt, p.PublicKeyHex)
		p.Signatures = append(p.Signatures, hex.EncodeToString(ed25519.Sign(key, []byte(msg))))
	}
	return p, pubs
}
func TestCeremonyRequiresTwoIndependentIdentityBoundApprovals(t *testing.T) {
	p, keys := ceremonyProof("commit")
	if err := VerifyCeremony(p, "commit", keys, 1000); err != nil {
		t.Fatal(err)
	}
	for _, name := range []string{"duplicate", "wrong-key", "expiry", "changed-identity", "phase"} {
		t.Run(name, func(t *testing.T) {
			proof := p
			ks := append([]ed25519.PublicKey{}, keys...)
			stage := "commit"
			switch name {
			case "duplicate":
				ks[1] = ks[0]
			case "wrong-key":
				proof.Signatures = []string{p.Signatures[0], p.Signatures[0]}
			case "expiry":
				proof.ExpiresAt = 900
			case "changed-identity":
				proof.PublicKeyHex = "04" + strings.Repeat("22", 64)
			case "phase":
				stage = "start"
			}
			if err := VerifyCeremony(proof, stage, ks, 1000); err == nil {
				t.Fatal("unauthorized ceremony accepted")
			}
		})
	}

}

func freshCeremonyProof(stage string, pub string) (CeremonyApproval, []ed25519.PublicKey) {
	p, keys := ceremonyProof(stage)
	p.ExpiresAt = time.Now().Unix() + 60
	if stage == "commit" {
		p.PublicKeyHex = pub
	}
	p.Signatures = nil
	for _, seed := range []byte{1, 2} {
		key := ed25519.NewKeyFromSeed(bytes.Repeat([]byte{seed}, 32))
		msg := fmt.Sprintf("readytrader-mpc-ceremony-v1\n%s\n%s\n%s\n%d\n%s", stage, p.ID, p.CeremonyID, p.ExpiresAt, p.PublicKeyHex)
		p.Signatures = append(p.Signatures, hex.EncodeToString(ed25519.Sign(key, []byte(msg))))
	}
	return p, keys
}
func TestCeremonyStagesButRequiresMatchingIdentityBeforeCommit(t *testing.T) {
	s, b, p := testServer(t)
	b.initialized = false
	s.CeremonyEnabled = true
	start, keys := freshCeremonyProof("start", "")
	s.CeremonyKeys = keys
	h := s.Handler(true)
	if r := request(h, "POST", "/ceremony/start", "workload", start); r.Code != 401 {
		t.Fatalf("runtime identity invoked DKG: %d", r.Code)
	}
	one := start
	one.Signatures = one.Signatures[:1]
	if r := request(h, "POST", "/ceremony/start", "operator", one); r.Code != 403 {
		t.Fatal("one operator started ceremony")
	}
	if r := request(h, "POST", "/ceremony/start", "operator", start); r.Code != 200 {
		t.Fatalf("approved ceremony failed: %d %s", r.Code, r.Body)
	}
	if b.calls.Load() != 1 || p.calls.Load() != 1 {
		t.Fatal("staging did not execute once")
	}
	wrong, _ := freshCeremonyProof("commit", "04"+strings.Repeat("22", 64))
	if r := request(h, "POST", "/ceremony/commit", "operator", wrong); r.Code != 403 {
		t.Fatal("mismatched key was committed")
	}
	if b.calls.Load() != 1 || p.calls.Load() != 1 {
		t.Fatal("mismatched identity caused side effect")
	}
	correct, _ := freshCeremonyProof("commit", "04"+strings.Repeat("11", 64))
	if r := request(h, "POST", "/ceremony/commit", "operator", correct); r.Code != 200 {
		t.Fatalf("matching commit failed: %d %s", r.Code, r.Body)
	}
	if _, err := os.Stat(filepath.Join(s.Authorizer.ReplayDir, "ceremony-committed-"+correct.ID+".json")); err != nil {
		t.Fatal("successful key commit lacks durable completion record", err)
	}
	if r := request(h, "POST", "/ceremony/commit", "operator", correct); r.Code != 403 {
		t.Fatal("commit approval replayed")
	}
}
