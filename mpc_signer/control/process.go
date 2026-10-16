package control

import (
	"bytes"
	"context"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"sync"
	"time"
)

type WorkerRequest struct {
	DeadlineUnixNano int64  `json:"deadline_unix_nano"`
	Operation        string `json:"operation"`
	SessionID        string `json:"session_id"`
	DigestHex        string `json:"digest_hex"`
	StagePath        string `json:"stage_path"`
	ResultPath       string `json:"result_path"`
}
type WorkerResult struct {
	Identity     Identity `json:"identity"`
	SignatureHex string   `json:"signature_hex"`
}

// Native MPC does not honor Go cancellation. Each operation therefore lives in a
// dedicated, killable child. Run waits/reaps it before returning to the permit owner.
type ProcessBackend struct {
	Executable   string
	Args         []string
	KeySharePath string
	mu           sync.Mutex
	identity     Identity
	staged       Identity
	stagePath    string
}

func (b *ProcessBackend) Run(ctx context.Context, req WorkerRequest) (WorkerResult, error) {
	var result WorkerResult
	deadline, ok := ctx.Deadline()
	if !ok {
		return result, errors.New("worker deadline required")
	}
	req.DeadlineUnixNano = deadline.UnixNano()
	file, err := os.CreateTemp("", "readytrader-mpc-result-*.json")
	if err != nil {
		return result, err
	}
	req.ResultPath = file.Name()
	_ = file.Close()
	defer os.Remove(req.ResultPath)
	input, err := json.Marshal(req)
	if err != nil {
		return result, err
	}
	args := append(append([]string{}, b.Args...), "--mpc-worker")
	cmd := exec.CommandContext(ctx, b.Executable, args...)
	cmd.Stdin = bytes.NewReader(input)
	// Native diagnostics must never mix with protocol results or grow memory.
	cmd.Stdout = io.Discard
	cmd.Stderr = io.Discard
	cmd.WaitDelay = time.Second
	if err = cmd.Run(); err != nil {
		if ctx.Err() != nil {
			return result, ctx.Err()
		}
		return result, errors.New("native worker failed")
	}
	if ctx.Err() != nil {
		return result, ctx.Err()
	}
	f, err := os.Open(req.ResultPath)
	if err != nil {
		return result, err
	}
	defer f.Close()
	raw, err := io.ReadAll(io.LimitReader(f, 65537))
	if err != nil || len(raw) > 65536 {
		return result, errors.New("invalid worker result")
	}
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.DisallowUnknownFields()
	if err = dec.Decode(&result); err != nil {
		return result, err
	}
	return result, nil
}
func (b *ProcessBackend) Load(ctx context.Context) error {
	b.mu.Lock()
	defer b.mu.Unlock()
	if _, err := os.Stat(b.KeySharePath); err != nil {
		if os.IsNotExist(err) {
			return nil
		}
		return err
	}
	result, err := b.Run(ctx, WorkerRequest{Operation: "address"})
	if err != nil {
		return err
	}
	if _, err = address(result.Identity.Address); err != nil {
		return err
	}
	b.identity = result.Identity
	return nil
}
func (b *ProcessBackend) Address(context.Context) (Identity, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	if b.identity.Address == "" {
		return Identity{}, errors.New("key not initialized")
	}
	return b.identity, nil
}
func (b *ProcessBackend) Stage(ctx context.Context, id string) (Identity, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	if _, err := lowerHex(id, 32); err != nil {
		return Identity{}, err
	}
	if b.identity.Address != "" || b.stagePath != "" {
		return Identity{}, errors.New("key or ceremony already initialized")
	}
	if _, err := os.Stat(b.KeySharePath); !os.IsNotExist(err) {
		return Identity{}, errors.New("share path already exists or unavailable")
	}
	if err := os.MkdirAll(filepath.Dir(b.KeySharePath), 0700); err != nil {
		return Identity{}, err
	}
	dir, err := os.MkdirTemp(filepath.Dir(b.KeySharePath), ".ceremony-")
	if err != nil {
		return Identity{}, err
	}
	stagePath := filepath.Join(dir, "share.bin")
	result, err := b.Run(ctx, WorkerRequest{Operation: "dkg", SessionID: id, StagePath: stagePath})
	if err != nil {
		_ = os.RemoveAll(dir)
		return Identity{}, err
	}
	if _, err = address(result.Identity.Address); err != nil {
		_ = os.RemoveAll(dir)
		return Identity{}, err
	}
	pub, err := lowerHex(result.Identity.PublicKeyHex, 65)
	if err != nil || pub[0] != 4 {
		_ = os.RemoveAll(dir)
		return Identity{}, errors.New("invalid staged public key")
	}
	result.Identity.CeremonyID = id
	b.staged = result.Identity
	b.stagePath = stagePath
	return b.staged, nil
}
func (b *ProcessBackend) Staged() (Identity, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	if b.staged.CeremonyID == "" {
		return Identity{}, errors.New("no staged key")
	}
	return b.staged, nil
}
func (b *ProcessBackend) Commit(ctx context.Context, id, pub string) error {
	b.mu.Lock()
	defer b.mu.Unlock()
	if ctx.Err() != nil {
		return ctx.Err()
	}
	if b.staged.CeremonyID != id || b.staged.PublicKeyHex != pub || b.stagePath == "" {
		return errors.New("staged identity mismatch")
	}
	if b.identity.PublicKeyHex == pub {
		return nil
	}
	f, err := os.OpenFile(b.stagePath, os.O_RDWR, 0600)
	if err != nil {
		return err
	}
	if err = f.Sync(); err != nil {
		_ = f.Close()
		return err
	}
	if err = f.Close(); err != nil {
		return err
	}
	// Link is atomic and refuses an existing destination. Rename would replace it.
	if err = os.Link(b.stagePath, b.KeySharePath); err != nil {
		return err
	}
	dir, err := os.Open(filepath.Dir(b.KeySharePath))
	if err != nil {
		return err
	}
	err = dir.Sync()
	_ = dir.Close()
	if err != nil {
		return err
	}
	b.identity = b.staged
	_ = os.Remove(b.stagePath)
	_ = os.Remove(filepath.Dir(b.stagePath))
	return nil
}
func (b *ProcessBackend) Sign(ctx context.Context, id string, digest []byte) ([]byte, error) {
	if len(digest) != 32 {
		return nil, errors.New("invalid digest")
	}
	if _, err := b.Address(ctx); err != nil {
		return nil, err
	}
	result, err := b.Run(ctx, WorkerRequest{Operation: "sign", SessionID: id, DigestHex: hex.EncodeToString(digest)})
	if err != nil {
		return nil, err
	}
	sig, err := hex.DecodeString(result.SignatureHex)
	if err != nil || len(sig) == 0 || len(sig) > 80 {
		return nil, errors.New("invalid signature result")
	}
	return sig, nil
}

// ArmWorkerDeadline is a child-local fail-safe, including if its parent crashes.
// It intentionally exits the worker process: native cgo cannot be canceled safely.
func ArmWorkerDeadline(deadlineUnixNano int64) (func(), error) {
	remaining := time.Until(time.Unix(0, deadlineUnixNano))
	if remaining <= 0 || remaining > 60*time.Second {
		return nil, errors.New("invalid native worker deadline")
	}
	timer := time.AfterFunc(remaining, func() { os.Exit(124) })
	return func() { timer.Stop() }, nil
}
