package control

import (
	"bytes"
	"context"
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"sync"
	"time"
)

type Identity struct {
	Address      string `json:"address"`
	PublicKeyHex string `json:"public_key_uncompressed_hex"`
	CeremonyID   string `json:"ceremony_id,omitempty"`
}
type Backend interface {
	Address(context.Context) (Identity, error)
	Sign(context.Context, string, []byte) ([]byte, error)
	Stage(context.Context, string) (Identity, error)
	Staged() (Identity, error)
	Commit(context.Context, string, string) error
}
type Peer interface {
	Call(context.Context, string, any, any) error
}
type CeremonyApproval struct {
	ID           string   `json:"id"`
	CeremonyID   string   `json:"ceremony_id"`
	ExpiresAt    int64    `json:"expires_at"`
	PublicKeyHex string   `json:"public_key_hex"`
	Signatures   []string `json:"signatures"`
}

type Server struct {
	Role                              int
	Authorizer                        Authorizer
	Backend                           Backend
	Peer                              Peer
	WorkloadPin, PeerPin, OperatorPin string
	CeremonyKeys                      []ed25519.PublicKey
	CeremonyEnabled                   bool
	Timeout                           time.Duration
	once                              sync.Once
	operation                         chan struct{}
	handlers                          chan struct{}
}

func jsonResponse(w http.ResponseWriter, status int, data any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(data)
}
func failure(w http.ResponseWriter, status int, code string) {
	jsonResponse(w, status, map[string]string{"error": code})
}
func strictJSON(w http.ResponseWriter, r *http.Request, value any) error {
	r.Body = http.MaxBytesReader(w, r.Body, 65536)
	defer r.Body.Close()
	dec := json.NewDecoder(r.Body)
	dec.DisallowUnknownFields()
	if err := dec.Decode(value); err != nil {
		return err
	}
	var trailing any
	if err := dec.Decode(&trailing); err != io.EOF {
		return errors.New("extra JSON content")
	}
	return nil
}
func (s *Server) initialize() {
	s.once.Do(func() {
		s.operation = make(chan struct{}, 1)
		s.handlers = make(chan struct{}, 32)
		if s.Timeout <= 0 || s.Timeout > 60*time.Second {
			s.Timeout = 60 * time.Second
		}
	})
}
func identityAllowed(r *http.Request, expected string) bool {
	if r.TLS == nil || len(r.TLS.VerifiedChains) == 0 || len(r.TLS.PeerCertificates) == 0 || expected == "" {
		return false
	}
	sum := sha256.Sum256(r.TLS.PeerCertificates[0].Raw)
	return hex.EncodeToString(sum[:]) == expected
}
func (s *Server) Handler(bootstrap bool) http.Handler {
	s.initialize()
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		path := r.URL.Path
		pin := ""
		method := "POST"
		if bootstrap {
			if !s.CeremonyEnabled {
				http.NotFound(w, r)
				return
			}
			switch path {
			case "/ceremony/start", "/ceremony/commit":
				if s.Role == 0 {
					pin = s.OperatorPin
				}
			case "/ceremony/status":
				pin = s.OperatorPin
				method = "GET"
			case "/internal/start_dkg", "/internal/commit_dkg":
				if s.Role == 1 {
					pin = s.PeerPin
				}
			default:
				http.NotFound(w, r)
				return
			}
		} else {
			switch path {
			case "/health", "/address":
				pin = s.WorkloadPin
				if s.Role == 1 {
					pin = s.PeerPin
				}
				method = "GET"
			case "/internal/status":
				pin = s.PeerPin
				method = "GET"
			case "/sign_transaction":
				if s.Role == 0 {
					pin = s.WorkloadPin
				}
			case "/internal/start_sign":
				if s.Role == 1 {
					pin = s.PeerPin
				}
			default:
				http.NotFound(w, r)
				return
			}
		}
		if !identityAllowed(r, pin) {
			failure(w, 401, "unauthorized")
			return
		}
		if r.Method != method {
			w.Header().Set("Allow", method)
			failure(w, 405, "method_not_allowed")
			return
		}
		select {
		case s.handlers <- struct{}{}:
			defer func() { <-s.handlers }()
		default:
			failure(w, 429, "request_budget_exhausted")
			return
		}
		deadline := time.Now().Add(s.Timeout)
		rc := http.NewResponseController(w)
		_ = rc.SetReadDeadline(deadline)
		_ = rc.SetWriteDeadline(deadline.Add(time.Second))
		ctx, cancel := context.WithDeadline(r.Context(), deadline)
		defer cancel()
		r = r.WithContext(ctx)
		switch path {
		case "/health", "/internal/status":
			_, err := s.Backend.Address(ctx)
			jsonResponse(w, 200, map[string]any{"ok": true, "key_share_loaded": err == nil})
			return
		case "/address":
			id, err := s.Backend.Address(ctx)
			if err != nil {
				failure(w, 409, "key_not_initialized")
				return
			}
			jsonResponse(w, 200, id)
			return
		case "/ceremony/status":
			id, err := s.Backend.Staged()
			if err != nil {
				failure(w, 409, "no_staged_key")
				return
			}
			jsonResponse(w, 200, id)
			return
		}
		select {
		case s.operation <- struct{}{}:
		default:
			failure(w, 429, "operation_in_progress")
			return
		}
		release := true
		defer func() {
			if release {
				<-s.operation
			}
		}()
		if path == "/sign_transaction" || path == "/internal/start_sign" {
			var req SignRequest
			if err := strictJSON(w, r, &req); err != nil {
				failure(w, 400, "invalid_request")
				return
			}
			id, err := s.Backend.Address(ctx)
			if err != nil {
				failure(w, 409, "key_not_initialized")
				return
			}
			digest, err := s.Authorizer.Authorize(req, id.Address, time.Now().Unix())
			if err != nil {
				failure(w, 403, "approval_or_policy_denied")
				return
			}
			if s.Role == 1 {
				release = false
				go func() {
					defer func() { <-s.operation }()
					ctx, cancel := context.WithTimeout(context.Background(), time.Until(deadline))
					defer cancel()
					_, _ = s.Backend.Sign(ctx, req.Approval.ID, digest)
				}()
				jsonResponse(w, 202, map[string]bool{"started": true})
				return
			}
			if err := s.Peer.Call(ctx, "/internal/start_sign", req, nil); err != nil {
				failure(w, 502, "peer_start_failed")
				return
			}
			signature, err := s.Backend.Sign(ctx, req.Approval.ID, digest)
			if err != nil {
				if ctx.Err() != nil {
					failure(w, 504, "operation_deadline")
				} else {
					failure(w, 500, "signing_failed")
				}
				return
			}
			jsonResponse(w, 200, map[string]any{"ok": true, "signature_der_hex": "0x" + hex.EncodeToString(signature)})
			return
		}
		var proof CeremonyApproval
		if err := strictJSON(w, r, &proof); err != nil {
			failure(w, 400, "invalid_request")
			return
		}
		stage := "start"
		if path == "/ceremony/commit" || path == "/internal/commit_dkg" {
			stage = "commit"
		}
		if err := VerifyCeremony(proof, stage, s.CeremonyKeys, time.Now().Unix()); err != nil {
			failure(w, 403, "ceremony_approval_denied")
			return
		}
		if stage == "start" {
			if _, err := s.Backend.Address(ctx); err == nil {
				failure(w, 409, "key_already_initialized")
				return
			}
			if _, err := s.Backend.Staged(); err == nil {
				failure(w, 409, "ceremony_already_staged")
				return
			}
		} else {
			id, err := s.Backend.Staged()
			if err != nil || id.CeremonyID != proof.CeremonyID || id.PublicKeyHex != proof.PublicKeyHex {
				failure(w, 403, "staged_identity_mismatch")
				return
			}
		}
		if err := Consume(s.Authorizer.ReplayDir, "ceremony-"+stage, proof.ID, proof); err != nil {
			failure(w, 403, "ceremony_replay_denied")
			return
		}
		if stage == "start" {
			if s.Role == 1 {
				release = false
				go func() {
					defer func() { <-s.operation }()
					ctx, cancel := context.WithTimeout(context.Background(), time.Until(deadline))
					defer cancel()
					_, _ = s.Backend.Stage(ctx, proof.CeremonyID)
				}()
				jsonResponse(w, 202, map[string]bool{"started": true})
				return
			}
			if err := s.Peer.Call(ctx, "/internal/start_dkg", proof, nil); err != nil {
				failure(w, 502, "peer_start_failed")
				return
			}
			id, err := s.Backend.Stage(ctx, proof.CeremonyID)
			if err != nil {
				failure(w, 500, "ceremony_failed")
				return
			}
			jsonResponse(w, 200, id)
			return
		}
		if s.Role == 0 {
			if err := s.Peer.Call(ctx, "/internal/commit_dkg", proof, nil); err != nil {
				failure(w, 502, "peer_commit_failed")
				return
			}
		}
		if err := s.Backend.Commit(ctx, proof.CeremonyID, proof.PublicKeyHex); err != nil {
			failure(w, 500, "commit_failed")
			return
		}
		if err := Consume(s.Authorizer.ReplayDir, "ceremony-committed", proof.ID, proof); err != nil {
			failure(w, 500, "commit_audit_failed")
			return
		}
		jsonResponse(w, 200, map[string]bool{"ok": true})
	})
}
func VerifyCeremony(p CeremonyApproval, stage string, keys []ed25519.PublicKey, now int64) error {
	if len(keys) != 2 || len(keys[0]) != 32 || len(keys[1]) != 32 || bytes.Equal(keys[0], keys[1]) || len(p.Signatures) != 2 {
		return errors.New("two independent operators required")
	}
	if _, err := lowerHex(p.ID, 32); err != nil {
		return err
	}
	if _, err := lowerHex(p.CeremonyID, 32); err != nil {
		return err
	}
	if p.ExpiresAt <= now || p.ExpiresAt > now+300 {
		return errors.New("ceremony approval expired")
	}
	switch stage {
	case "start":
		if p.PublicKeyHex != "" || p.CeremonyID != p.ID {
			return errors.New("invalid start proof")
		}
	case "commit":
		b, err := lowerHex(p.PublicKeyHex, 65)
		if err != nil || b[0] != 4 {
			return errors.New("expected public identity required")
		}
	default:
		return errors.New("unknown ceremony phase")
	}
	msg := fmt.Sprintf("readytrader-mpc-ceremony-v1\n%s\n%s\n%s\n%d\n%s", stage, p.ID, p.CeremonyID, p.ExpiresAt, p.PublicKeyHex)
	for i, key := range keys {
		signature, err := lowerHex(p.Signatures[i], 64)
		if err != nil || !ed25519.Verify(key, []byte(msg), signature) {
			return errors.New("ceremony signature denied")
		}
	}
	return nil
}
