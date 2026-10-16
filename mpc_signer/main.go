package main

import (
	"context"
	"crypto/ed25519"
	"crypto/sha256"
	"crypto/tls"
	"crypto/x509"
	"encoding/hex"
	"encoding/json"
	"encoding/pem"
	"errors"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/coinbase/cb-mpc/demos-go/cb-mpc-go/api/curve"
	"github.com/coinbase/cb-mpc/demos-go/cb-mpc-go/api/mpc"
	"github.com/coinbase/cb-mpc/demos-go/cb-mpc-go/api/transport/mtls"
	"golang.org/x/crypto/sha3"
	"readytrader-crypto/mpc_signer/control"
)

type config struct {
	RoleIndex int

	// HTTP server (external control plane for orchestration + signing requests)
	HTTPListenAddr string

	// MPC transport (mTLS messenger) addresses for the CB-MPC parties.
	Party0Addr string
	Party1Addr string

	CaCertPath  string
	CertPath    string
	KeyPath     string
	Party0Cert  string
	Party1Cert  string
	PeerHTTPURL string // leader only: where to reach follower control-plane

	KeySharePath string
}

func mustEnv(name string) string {
	v := strings.TrimSpace(os.Getenv(name))
	if v == "" {
		log.Fatalf("Missing required env var: %s", name)
	}
	return v
}

func envDefault(name, def string) string {
	v := strings.TrimSpace(os.Getenv(name))
	if v == "" {
		return def
	}
	return v
}

func loadConfig() config {
	roleRaw := mustEnv("MPC_ROLE_INDEX")
	role, err := strconv.Atoi(roleRaw)
	if err != nil || (role != 0 && role != 1) {
		log.Fatalf("Invalid MPC_ROLE_INDEX=%q (expected 0 or 1)", roleRaw)
	}

	cfg := config{
		RoleIndex:      role,
		HTTPListenAddr: envDefault("MPC_HTTP_LISTEN", "127.0.0.1:8787"),
		Party0Addr:     mustEnv("MPC_PARTY0_ADDR"),
		Party1Addr:     mustEnv("MPC_PARTY1_ADDR"),
		CaCertPath:     mustEnv("MPC_CA_CERT"),
		CertPath:       mustEnv("MPC_CERT"),
		KeyPath:        mustEnv("MPC_KEY"),
		Party0Cert:     mustEnv("MPC_PARTY0_CERT"),
		Party1Cert:     mustEnv("MPC_PARTY1_CERT"),
		KeySharePath:   envDefault("MPC_KEYSHARE_PATH", "data/mpc_keyshare.bin"),
	}
	if role == 0 {
		cfg.PeerHTTPURL = mustEnv("MPC_PEER_HTTP_URL")
	}
	return cfg
}

type state struct {
	cfg config

	mu sync.Mutex

	// messenger is initialized asynchronously on startup; endpoints should refuse
	// operations until ready.
	messenger *mtls.MTLSMessenger
	pnames    []string

	curve curve.Curve

	keyShareLoaded bool
	keyShare       mpc.ECDSA2PCKey

	// outstanding background operations (follower)
	lastErr string
}

func (s *state) setErr(err error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.lastErr = err.Error()
}

func (s *state) clearErr() {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.lastErr = ""
}

func (s *state) statusJSON() map[string]any {
	s.mu.Lock()
	defer s.mu.Unlock()
	return map[string]any{
		"role_index":       s.cfg.RoleIndex,
		"messenger_ready":  s.messenger != nil,
		"key_share_loaded": s.keyShareLoaded,
		"last_error":       s.lastErr,
	}
}

func (s *state) loadKeyShareIfPresent() error {
	path := s.cfg.KeySharePath
	b, err := os.ReadFile(path)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return nil
		}
		return err
	}
	var k mpc.ECDSA2PCKey
	if err := k.UnmarshalBinary(b); err != nil {
		return err
	}
	s.keyShare = k
	s.keyShareLoaded = true
	return nil
}

func (s *state) saveKeyShare() error {
	if !s.keyShareLoaded {
		return fmt.Errorf("no key share to save")
	}
	b, err := s.keyShare.MarshalBinary()
	if err != nil {
		return err
	}
	p := s.cfg.KeySharePath
	if err := os.MkdirAll(filepath.Dir(p), 0o700); err != nil {
		return err
	}
	tmp := p + ".tmp"
	if err := os.WriteFile(tmp, b, 0o600); err != nil {
		return err
	}
	return os.Rename(tmp, p)
}

func ethAddressFromUncompressedPubkey(pubUncompressed []byte) (string, error) {
	// Input must be 65 bytes: 0x04 || X32 || Y32.
	if len(pubUncompressed) != 65 || pubUncompressed[0] != 0x04 {
		return "", fmt.Errorf("expected uncompressed SEC1 pubkey (65 bytes starting with 0x04)")
	}
	h := sha3.NewLegacyKeccak256()
	_, _ = h.Write(pubUncompressed[1:]) // X||Y
	sum := h.Sum(nil)
	addr := sum[len(sum)-20:]
	return "0x" + hex.EncodeToString(addr), nil
}

func (s *state) publicKeyAndAddress() (string, string, error) {
	if !s.keyShareLoaded {
		return "", "", fmt.Errorf("key share not initialized")
	}
	Q, err := s.keyShare.Q()
	if err != nil {
		return "", "", err
	}
	defer Q.Free()
	pad32 := func(b []byte) []byte {
		if len(b) >= 32 {
			if len(b) == 32 {
				return b
			}
			return b[len(b)-32:]
		}
		p := make([]byte, 32)
		copy(p[32-len(b):], b)
		return p
	}
	x := pad32(Q.GetX())
	y := pad32(Q.GetY())
	pub := make([]byte, 1+32+32)
	pub[0] = 0x04
	copy(pub[1:33], x)
	copy(pub[33:], y)
	addr, err := ethAddressFromUncompressedPubkey(pub)
	if err != nil {
		return "", "", err
	}
	return hex.EncodeToString(pub), addr, nil
}

func (s *state) buildMessengerWithRetry(ctx context.Context) {
	for {
		select {
		case <-ctx.Done():
			return
		default:
		}

		m, pnames, err := buildMessenger(s.cfg)
		if err == nil {
			s.mu.Lock()
			s.messenger = m
			s.pnames = pnames
			s.mu.Unlock()
			log.Printf("MPC messenger ready (role=%d)", s.cfg.RoleIndex)
			return
		}
		s.setErr(err)
		log.Printf("MPC messenger init failed (will retry): %v", err)
		time.Sleep(2 * time.Second)
	}
}

func buildMessenger(cfg config) (*mtls.MTLSMessenger, []string, error) {
	cert, err := tls.LoadX509KeyPair(cfg.CertPath, cfg.KeyPath)
	if err != nil {
		return nil, nil, fmt.Errorf("load TLS cert/key: %w", err)
	}
	caCert, err := os.ReadFile(cfg.CaCertPath)
	if err != nil {
		return nil, nil, fmt.Errorf("read CA cert: %w", err)
	}
	caPool := x509.NewCertPool()
	if !caPool.AppendCertsFromPEM(caCert) {
		return nil, nil, fmt.Errorf("invalid CA certificate")
	}

	party0CertPEM, err := os.ReadFile(cfg.Party0Cert)
	if err != nil {
		return nil, nil, fmt.Errorf("read party0 cert: %w", err)
	}
	party1CertPEM, err := os.ReadFile(cfg.Party1Cert)
	if err != nil {
		return nil, nil, fmt.Errorf("read party1 cert: %w", err)
	}
	p0Der, _ := pem.Decode(party0CertPEM)
	if p0Der == nil || len(p0Der.Bytes) == 0 {
		return nil, nil, fmt.Errorf("parse party0 cert: expected PEM certificate")
	}
	p0, err := x509.ParseCertificate(p0Der.Bytes)
	if err != nil {
		return nil, nil, fmt.Errorf("parse party0 cert: %w", err)
	}
	p1Der, _ := pem.Decode(party1CertPEM)
	if p1Der == nil || len(p1Der.Bytes) == 0 {
		return nil, nil, fmt.Errorf("parse party1 cert: expected PEM certificate")
	}
	p1, err := x509.ParseCertificate(p1Der.Bytes)
	if err != nil {
		return nil, nil, fmt.Errorf("parse party1 cert: %w", err)
	}
	p0Name, err := mtls.PartyNameFromCertificate(p0)
	if err != nil {
		return nil, nil, fmt.Errorf("party0 pname: %w", err)
	}
	p1Name, err := mtls.PartyNameFromCertificate(p1)
	if err != nil {
		return nil, nil, fmt.Errorf("party1 pname: %w", err)
	}
	pnames := []string{p0Name, p1Name}

	parties := map[int]mtls.PartyConfig{
		0: {Address: cfg.Party0Addr, Cert: p0},
		1: {Address: cfg.Party1Addr, Cert: p1},
	}
	nameToIndex := map[string]int{
		p0Name: 0,
		p1Name: 1,
	}

	m, err := mtls.NewMTLSMessenger(mtls.Config{
		Parties:     parties,
		CertPool:    caPool,
		TLSCert:     cert,
		NameToIndex: nameToIndex,
		SelfIndex:   cfg.RoleIndex,
	})
	if err != nil {
		return nil, nil, err
	}
	return m, pnames, nil
}

func decodeHex32(s string) ([]byte, error) {
	v := strings.TrimSpace(s)
	v = strings.TrimPrefix(v, "0x")
	b, err := hex.DecodeString(v)
	if err != nil {
		return nil, err
	}
	if len(b) != 32 {
		return nil, fmt.Errorf("expected 32-byte hex, got %d bytes", len(b))
	}
	return b, nil
}

func (s *state) requireReady() (*mtls.MTLSMessenger, []string, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.messenger == nil {
		return nil, nil, fmt.Errorf("messenger not ready")
	}
	return s.messenger, append([]string{}, s.pnames...), nil
}

func (s *state) runKeyGen() error {
	m, pnames, err := s.requireReady()
	if err != nil {
		return err
	}
	cv, err := curve.NewSecp256k1()
	if err != nil {
		return err
	}
	// Keep curve instance for later; it holds native resources.
	s.mu.Lock()
	if s.curve == nil {
		s.curve = cv
	} else {
		cv.Free()
	}
	s.mu.Unlock()

	job, err := mpc.NewJob2P(m, s.cfg.RoleIndex, pnames)
	if err != nil {
		return err
	}
	defer job.Free()

	resp, err := mpc.ECDSA2PCKeyGen(job, &mpc.ECDSA2PCKeyGenRequest{Curve: s.curve})
	if err != nil {
		return err
	}

	s.mu.Lock()
	s.keyShare = resp.KeyShare
	s.keyShareLoaded = true
	s.mu.Unlock()

	return s.saveKeyShare()
}

func (s *state) runSign(sessionID []byte, digest32 []byte) ([]byte, error) {
	if len(digest32) != 32 {
		return nil, fmt.Errorf("digest must be 32 bytes")
	}
	m, pnames, err := s.requireReady()
	if err != nil {
		return nil, err
	}
	s.mu.Lock()
	hasKey := s.keyShareLoaded
	key := s.keyShare
	cv := s.curve
	s.mu.Unlock()
	if !hasKey {
		return nil, fmt.Errorf("key share not initialized")
	}
	if cv == nil {
		// Should never happen because keygen initializes curve, but be defensive.
		curveObj, err := curve.NewSecp256k1()
		if err != nil {
			return nil, err
		}
		cv = curveObj
		s.mu.Lock()
		s.curve = curveObj
		s.mu.Unlock()
	}

	job, err := mpc.NewJob2P(m, s.cfg.RoleIndex, pnames)
	if err != nil {
		return nil, err
	}
	defer job.Free()

	resp, err := mpc.ECDSA2PCSign(job, &mpc.ECDSA2PCSignRequest{
		SessionID: sessionID,
		KeyShare:  key,
		Message:   digest32,
	})
	if err != nil {
		return nil, err
	}

	// Self-check: verify signature against Q.
	Q, err := key.Q()
	if err != nil {
		return nil, err
	}
	defer Q.Free()
	if err := resp.Verify(Q, digest32, cv); err != nil {
		return nil, fmt.Errorf("signature verification failed: %w", err)
	}

	return resp.Signature, nil
}

// nativeWorker is reachable only through a local child-process pipe. No raw
// digest operation is exposed by either HTTP listener.
func nativeWorker(cfg config) error {
	var req control.WorkerRequest
	dec := json.NewDecoder(io.LimitReader(os.Stdin, 65536))
	dec.DisallowUnknownFields()
	if err := dec.Decode(&req); err != nil {
		return err
	}
	stopWatchdog, err := control.ArmWorkerDeadline(req.DeadlineUnixNano)
	if err != nil {
		return err
	}
	defer stopWatchdog()
	st := &state{cfg: cfg}
	result := control.WorkerResult{}
	if req.Operation == "dkg" {
		if req.StagePath == "" {
			return errors.New("stage path required")
		}
		st.cfg.KeySharePath = req.StagePath
	} else if err := st.loadKeyShareIfPresent(); err != nil {
		return err
	}
	switch req.Operation {
	case "sign", "dkg":
		messenger, names, err := buildMessenger(cfg)
		if err != nil {
			return err
		}
		st.messenger = messenger
		st.pnames = names
		defer messenger.Close()
		if req.Operation == "dkg" {
			if err := st.runKeyGen(); err != nil {
				return err
			}
		} else {
			digest, err := decodeHex32(req.DigestHex)
			if err != nil {
				return err
			}
			session, err := hex.DecodeString(req.SessionID)
			if err != nil || len(session) != 32 {
				return errors.New("invalid signing session")
			}
			sig, err := st.runSign(session, digest)
			if err != nil {
				return err
			}
			result.SignatureHex = hex.EncodeToString(sig)
		}
	case "address":
	default:
		return errors.New("unknown worker operation")
	}
	pub, addr, err := st.publicKeyAndAddress()
	if err != nil {
		return err
	}
	result.Identity = control.Identity{Address: addr, PublicKeyHex: pub}
	encoded, err := json.Marshal(result)
	if err != nil {
		return err
	}
	return os.WriteFile(req.ResultPath, encoded, 0600)
}
func certPin(path string) (string, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return "", err
	}
	block, _ := pem.Decode(raw)
	if block == nil {
		return "", errors.New("invalid certificate PEM")
	}
	cert, err := x509.ParseCertificate(block.Bytes)
	if err != nil {
		return "", err
	}
	sum := sha256.Sum256(cert.Raw)
	return hex.EncodeToString(sum[:]), nil
}
func publicApprovalKey(name string) ed25519.PublicKey {
	raw, err := hex.DecodeString(mustEnv(name))
	if err != nil || len(raw) != 32 {
		log.Fatalf("%s must contain a 32-byte Ed25519 public key", name)
	}
	return ed25519.PublicKey(raw)
}
func main() {
	cfg := loadConfig()
	if len(os.Args) == 2 && os.Args[1] == "--mpc-worker" {
		if err := nativeWorker(cfg); err != nil {
			os.Exit(1)
		}
		return
	}
	cert, err := tls.LoadX509KeyPair(cfg.CertPath, cfg.KeyPath)
	if err != nil {
		log.Fatal("invalid control TLS certificate/key")
	}
	ca, err := os.ReadFile(cfg.CaCertPath)
	if err != nil {
		log.Fatal("missing control TLS CA")
	}
	pool := x509.NewCertPool()
	if !pool.AppendCertsFromPEM(ca) {
		log.Fatal("invalid control TLS CA")
	}
	tlsConfig := &tls.Config{MinVersion: tls.VersionTLS13, Certificates: []tls.Certificate{cert}, ClientCAs: pool, ClientAuth: tls.RequireAndVerifyClientCert}
	peerCertPath := cfg.Party0Cert
	if cfg.RoleIndex == 0 {
		peerCertPath = cfg.Party1Cert
	}
	peerPin, err := certPin(peerCertPath)
	if err != nil {
		log.Fatal("invalid expected peer certificate")
	}
	// Normal chain+hostname verification is retained in addition to the exact pin.
	peerTLS := &tls.Config{MinVersion: tls.VersionTLS13, RootCAs: pool, Certificates: []tls.Certificate{cert}, VerifyConnection: func(c tls.ConnectionState) error {
		if len(c.PeerCertificates) == 0 {
			return errors.New("missing peer certificate")
		}
		sum := sha256.Sum256(c.PeerCertificates[0].Raw)
		if hex.EncodeToString(sum[:]) != peerPin {
			return errors.New("peer certificate mismatch")
		}
		return nil
	}}
	peer := control.HTTPPeer{RuntimeURL: cfg.PeerHTTPURL, Client: &http.Client{Timeout: 60 * time.Second, Transport: &http.Transport{TLSClientConfig: peerTLS, MaxConnsPerHost: 2, MaxIdleConnsPerHost: 1, IdleConnTimeout: 15 * time.Second, ResponseHeaderTimeout: 10 * time.Second}}}
	policyFile, err := os.Open(mustEnv("MPC_POLICY_FILE"))
	if err != nil {
		log.Fatal("MPC policy unavailable")
	}
	var policy control.Policy
	decoder := json.NewDecoder(io.LimitReader(policyFile, 65537))
	decoder.DisallowUnknownFields()
	err = decoder.Decode(&policy)
	_ = policyFile.Close()
	if err != nil || policy.CheckConfig() != nil {
		log.Fatal("MPC policy invalid")
	}
	executable, err := os.Executable()
	if err != nil {
		log.Fatal(err)
	}
	backend := &control.ProcessBackend{Executable: executable, KeySharePath: cfg.KeySharePath}
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	err = backend.Load(ctx)
	cancel()
	if err != nil {
		log.Fatal("existing key share could not be loaded")
	}
	server := &control.Server{Role: cfg.RoleIndex, Authorizer: control.Authorizer{Policy: policy, ApprovalKey: publicApprovalKey("MPC_APPROVAL_PUBLIC_KEY"), ReplayDir: envDefault("MPC_REPLAY_DIR", filepath.Join(filepath.Dir(cfg.KeySharePath), "approvals"))}, Backend: backend, PeerPin: peerPin, Timeout: 60 * time.Second}
	if cfg.RoleIndex == 0 {
		server.WorkloadPin, err = certPin(mustEnv("MPC_WORKLOAD_CERT"))
		if err != nil {
			log.Fatal("invalid workload certificate")
		}
	}
	ceremonyFlag := envDefault("MPC_CEREMONY_ENABLED", "false")
	if ceremonyFlag != "true" && ceremonyFlag != "false" {
		log.Fatal("MPC_CEREMONY_ENABLED must be true or false")
	}
	server.CeremonyEnabled = ceremonyFlag == "true"
	if server.CeremonyEnabled {
		server.OperatorPin, err = certPin(mustEnv("MPC_OPERATOR_CERT"))
		if err != nil {
			log.Fatal("invalid operator certificate")
		}
		server.CeremonyKeys = []ed25519.PublicKey{publicApprovalKey("MPC_CEREMONY_PUBLIC_KEY_1"), publicApprovalKey("MPC_CEREMONY_PUBLIC_KEY_2")}
		if string(server.CeremonyKeys[0]) == string(server.CeremonyKeys[1]) {
			log.Fatal("independent ceremony operators required")
		}
		if cfg.RoleIndex == 0 {
			peer.BootstrapURL = mustEnv("MPC_PEER_BOOTSTRAP_URL")
		}
	}
	server.Peer = peer
	serve := func(addr string, handler http.Handler) error {
		listener, err := net.Listen("tcp", addr)
		if err != nil {
			return err
		}
		defer listener.Close()
		srv := control.NewHTTPServer(addr, handler, tlsConfig, 60*time.Second)
		return srv.ServeTLS(control.LimitListener(listener, 32), "", "")
	}
	if server.CeremonyEnabled {
		addr := envDefault("MPC_BOOTSTRAP_LISTEN", "127.0.0.1:8788")
		go func() { log.Fatal(serve(addr, server.Handler(true))) }()
	}
	log.Printf("MPC authenticated control plane listening on %s (role=%d)", cfg.HTTPListenAddr, cfg.RoleIndex)
	log.Fatal(serve(cfg.HTTPListenAddr, server.Handler(false)))
}
