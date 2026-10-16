package control

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"testing"
	"time"
)

func TestNativeWorkerFixture(t *testing.T) {
	args := os.Args
	if len(args) == 0 || args[len(args)-1] != "--mpc-worker" {
		return
	}
	var req WorkerRequest
	if err := json.NewDecoder(os.Stdin).Decode(&req); err != nil {
		os.Exit(3)
	}
	if req.Operation == "deadline" {
		cancel, err := ArmWorkerDeadline(req.DeadlineUnixNano)
		if err != nil {
			os.Exit(3)
		}
		defer cancel()
		for {
			time.Sleep(time.Second)
		}
	}
	if req.Operation == "hang" {
		_ = os.WriteFile(req.StagePath, []byte(strconv.Itoa(os.Getpid())), 0600)
		for {
			time.Sleep(time.Second)
		}
	}
	if req.Operation == "loud" {
		for i := 0; i < 1000; i++ {
			_, _ = os.Stdout.Write([]byte(strings.Repeat("x", 4096)))
		}
	}
	if req.Operation == "dkg" {
		_ = os.WriteFile(req.StagePath, []byte("test-only-staged-share"), 0600)
	}
	out := WorkerResult{Identity: Identity{Address: wallet, PublicKeyHex: "04" + strings.Repeat("11", 64)}}
	data, _ := json.Marshal(out)
	_ = os.WriteFile(req.ResultPath, data, 0600)
	os.Exit(0)
}
func processBackend(t *testing.T) *ProcessBackend {
	t.Helper()
	return &ProcessBackend{Executable: os.Args[0], Args: []string{"-test.run=^TestNativeWorkerFixture$", "--"}, KeySharePath: filepath.Join(t.TempDir(), "share.bin")}
}
func TestNativeWorkerDeadlineKillsAndReapsProcess(t *testing.T) {
	b := processBackend(t)
	pidPath := filepath.Join(t.TempDir(), "pid")
	ctx, cancel := context.WithTimeout(context.Background(), 200*time.Millisecond)
	defer cancel()
	_, err := b.Run(ctx, WorkerRequest{Operation: "hang", StagePath: pidPath})
	if !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("deadline not propagated: %v", err)
	}
	raw, err := os.ReadFile(pidPath)
	if err != nil {
		t.Fatal("worker did not start", err)
	}
	pid, _ := strconv.Atoi(string(raw))
	if err := syscall.Kill(pid, 0); err != syscall.ESRCH {
		t.Fatalf("worker was not reaped: %v", err)
	}
}
func TestNativeWorkerOutputDoesNotDeadlockOrLeakIntoResult(t *testing.T) {
	b := processBackend(t)
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	result, err := b.Run(ctx, WorkerRequest{Operation: "loud"})
	if err != nil || result.Identity.Address != wallet {
		t.Fatalf("bounded worker failed: %#v %v", result, err)
	}
}
func TestGeneratedSharesRequireMatchingExplicitCommit(t *testing.T) {
	b := processBackend(t)
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	id, err := b.Stage(ctx, strings.Repeat("12", 32))
	if err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(b.KeySharePath); !os.IsNotExist(err) {
		t.Fatal("share committed before identity confirmation")
	}
	if err := b.Commit(ctx, id.CeremonyID, "04"+strings.Repeat("22", 64)); err == nil {
		t.Fatal("mismatched identity committed")
	}
	if err := b.Commit(ctx, id.CeremonyID, id.PublicKeyHex); err != nil {
		t.Fatal(err)
	}
	raw, err := os.ReadFile(b.KeySharePath)
	if err != nil || string(raw) != "test-only-staged-share" {
		t.Fatal("matching commit did not persist exact share")
	}
}
func TestKeyCommitNeverOverwritesExistingShare(t *testing.T) {
	b := processBackend(t)
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	id, err := b.Stage(ctx, strings.Repeat("12", 32))
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(b.KeySharePath, []byte("existing"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := b.Commit(ctx, id.CeremonyID, id.PublicKeyHex); err == nil {
		t.Fatal("overwrote existing share")
	}
	raw, _ := os.ReadFile(b.KeySharePath)
	if string(raw) != "existing" {
		t.Fatal("existing share changed")
	}
}

func TestNativeWorkerEnforcesDeadlineWithoutParentCancellation(t *testing.T) {
	req := WorkerRequest{Operation: "deadline", DeadlineUnixNano: time.Now().Add(100 * time.Millisecond).UnixNano()}
	raw, _ := json.Marshal(req)
	cmd := exec.Command(os.Args[0], "-test.run=^TestNativeWorkerFixture$", "--", "--mpc-worker")
	cmd.Stdin = bytes.NewReader(raw)
	if err := cmd.Start(); err != nil {
		t.Fatal(err)
	}
	done := make(chan error, 1)
	go func() { done <- cmd.Wait() }()
	select {
	case err := <-done:
		exit, ok := err.(*exec.ExitError)
		if !ok || exit.ExitCode() != 124 {
			t.Fatalf("watchdog exit=%v", err)
		}
	case <-time.After(time.Second):
		_ = cmd.Process.Kill()
		<-done
		t.Fatal("native worker survived its independent deadline")
	}
}
