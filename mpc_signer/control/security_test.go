package control

import (
	"bytes"
	"crypto/ed25519"
	"encoding/hex"
	"fmt"
	"os"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
)

const vectorDigest = "daf5a779ae972f972197303d7b574746c7ef83eadac0f2791ad23db92e4c8e53"
const recipient = "0x3535353535353535353535353535353535353535"
const wallet = "0x1111111111111111111111111111111111111111"

func vectorTx() Transaction {
	return Transaction{Type: 0, ChainID: "1", Nonce: "9", Gas: "21000", To: recipient, Value: "1000000000000000000", Data: "0x", GasPrice: "20000000000", MaxFeePerGas: "0", MaxPriorityFeePerGas: "0"}
}
func testPolicy() Policy {
	return Policy{AllowedChainIDs: []string{"1"}, AllowedDestinations: []string{recipient}, AllowedTokenContracts: []string{"0x2222222222222222222222222222222222222222"}, AllowedTokenRecipients: []string{recipient}, AllowedSpenders: []string{recipient}, MaxValueWei: "1000000000000000000", MaxTokenAmount: "100", MaxGas: 100000, MaxFeePerGas: "30000000000", MaxTotalFeeWei: "3000000000000000"}
}
func signedApproval() (Approval, ed25519.PublicKey) {
	key := ed25519.NewKeyFromSeed(bytes.Repeat([]byte{1}, 32))
	a := Approval{ID: strings.Repeat("ab", 32), ExpiresAt: 1100, Wallet: wallet, DigestHex: "0x" + vectorDigest}
	msg := fmt.Sprintf("readytrader-mpc-approval-v1\n%s\n%d\n%s\n%s", a.ID, a.ExpiresAt, a.Wallet, a.DigestHex)
	a.SignatureHex = hex.EncodeToString(ed25519.Sign(key, []byte(msg)))
	return a, key.Public().(ed25519.PublicKey)
}
func TestCanonicalEIP155Digest(t *testing.T) {
	got, err := vectorTx().Digest()
	if err != nil {
		t.Fatal(err)
	}
	if hex.EncodeToString(got) != vectorDigest {
		t.Fatalf("digest=%x, want EIP-155 worked vector", got)
	}
}
func TestPolicyRejectsDangerousTransactions(t *testing.T) {
	cases := map[string]func(*Transaction){
		"chain": func(tx *Transaction) { tx.ChainID = "2" }, "destination": func(tx *Transaction) { tx.To = wallet },
		"excess-value":         func(tx *Transaction) { tx.Value = "1000000000000000001" },
		"noncanonical-decimal": func(tx *Transaction) { tx.Nonce = "09" }, "negative": func(tx *Transaction) { tx.Value = "-1" },
		"overflow": func(tx *Transaction) { tx.Value = strings.Repeat("9", 79) },
		"creation": func(tx *Transaction) { tx.To = "0x" }, "unknown-calldata": func(tx *Transaction) { tx.Data = "0x12345678" },
		"legacy-mixed-fees": func(tx *Transaction) { tx.MaxFeePerGas = "1" }, "gas": func(tx *Transaction) { tx.Gas = "100001" },
		"fee":          func(tx *Transaction) { tx.GasPrice = "30000000001" },
		"total-fee":    func(tx *Transaction) { tx.Gas = "100000"; tx.GasPrice = "30000000000"; tx.Value = "0" },
		"unknown-type": func(tx *Transaction) { tx.Type = 1 },
		"type2-priority-over-max": func(tx *Transaction) {
			tx.Type = 2
			tx.GasPrice = "0"
			tx.MaxFeePerGas = "1"
			tx.MaxPriorityFeePerGas = "2"
		},
		"type2-fee-cap": func(tx *Transaction) {
			tx.Type = 2
			tx.GasPrice = "0"
			tx.MaxFeePerGas = "30000000001"
			tx.MaxPriorityFeePerGas = "1"
		},
	}
	for name, change := range cases {
		t.Run(name, func(t *testing.T) {
			tx := vectorTx()
			change(&tx)
			p := testPolicy()
			if name == "total-fee" {
				p.MaxTotalFeeWei = "2999999999999999"
			}
			if err := p.Validate(tx); err == nil {
				t.Fatal("unsafe transaction accepted")
			}
		})
	}
}
func TestPolicyAllowsOnlyDecodedERC20Semantics(t *testing.T) {
	tx := vectorTx()
	tx.To = "0x2222222222222222222222222222222222222222"
	tx.Value = "0"
	tx.Gas = "60000"
	tx.Data = "0xa9059cbb" + strings.Repeat("0", 24) + recipient[2:] + fmt.Sprintf("%064x", 100)
	if err := testPolicy().Validate(tx); err != nil {
		t.Fatal(err)
	}
	for _, data := range []string{tx.Data + "00", strings.Replace(tx.Data, recipient[2:], wallet[2:], 1), tx.Data[:74] + fmt.Sprintf("%064x", 101), "0xdeadbeef"} {
		tx.Data = data
		if err := testPolicy().Validate(tx); err == nil {
			t.Fatal("invalid token semantics accepted")
		}
	}
}
func TestApprovalBindsIntentAndCannotReplayAcrossRestart(t *testing.T) {
	proof, key := signedApproval()
	dir := t.TempDir()
	auth := Authorizer{testPolicy(), key, dir}
	req := SignRequest{vectorTx(), proof}
	altered := req
	altered.Transaction.Nonce = "10"
	if _, err := auth.Authorize(altered, wallet, 1000); err == nil {
		t.Fatal("altered transaction accepted")
	}
	if _, err := auth.Authorize(req, wallet, 1000); err != nil {
		t.Fatal(err)
	}
	restarted := Authorizer{testPolicy(), key, dir}
	if _, err := restarted.Authorize(req, wallet, 1000); err == nil {
		t.Fatal("approval replay accepted after restart")
	}
}
func TestApprovalDeniesMissingExpiredWrongWalletAndForgery(t *testing.T) {
	proof, key := signedApproval()
	for _, name := range []string{"missing", "expired", "future", "wallet", "forged", "path"} {
		t.Run(name, func(t *testing.T) {
			p := proof
			now := int64(1000)
			switch name {
			case "missing":
				p = Approval{}
			case "expired":
				now = 1100
			case "future":
				now = 700
			case "wallet":
				p.Wallet = recipient
			case "forged":
				p.SignatureHex = strings.Repeat("00", 64)
			case "path":
				p.ID = "../escape"
			}
			if _, err := (Authorizer{testPolicy(), key, t.TempDir()}).Authorize(SignRequest{vectorTx(), p}, wallet, now); err == nil {
				t.Fatal("invalid approval accepted")
			}
		})
	}
}
func TestApprovalReplayConsumptionIsAtomic(t *testing.T) {
	proof, key := signedApproval()
	a := Authorizer{testPolicy(), key, t.TempDir()}
	var successes atomic.Int32
	var wg sync.WaitGroup
	for i := 0; i < 20; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			if _, err := a.Authorize(SignRequest{vectorTx(), proof}, wallet, 1000); err == nil {
				successes.Add(1)
			}
		}()
	}
	wg.Wait()
	if successes.Load() != 1 {
		t.Fatalf("signed %d times", successes.Load())
	}
}
func TestApprovalFailsClosedWhenReplayStorageCannotPersist(t *testing.T) {
	proof, key := signedApproval()
	dir := t.TempDir() + "/file"
	if err := os.WriteFile(dir, []byte("x"), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := (Authorizer{testPolicy(), key, dir}).Authorize(SignRequest{vectorTx(), proof}, wallet, 1000); err == nil {
		t.Fatal("unpersisted approval accepted")
	}
}

func TestApprovalDigestBindsEveryTransactionField(t *testing.T) {
	proof, key := signedApproval()
	changes := map[string]func(*Transaction){
		"chain": func(tx *Transaction) { tx.ChainID = "2" }, "nonce": func(tx *Transaction) { tx.Nonce = "10" },
		"value": func(tx *Transaction) { tx.Value = "1" }, "recipient": func(tx *Transaction) { tx.To = wallet },
		"fee": func(tx *Transaction) { tx.GasPrice = "21000000000" }, "gas": func(tx *Transaction) { tx.Gas = "22000" },
	}
	for name, change := range changes {
		t.Run(name, func(t *testing.T) {
			p := testPolicy()
			p.AllowedChainIDs = append(p.AllowedChainIDs, "2")
			p.AllowedDestinations = append(p.AllowedDestinations, wallet)
			a := Authorizer{p, key, t.TempDir()}
			tx := vectorTx()
			change(&tx)
			if err := p.Validate(tx); err != nil {
				t.Fatal("fixture must be independently allowed by policy", err)
			}
			if _, err := a.Authorize(SignRequest{tx, proof}, wallet, 1000); err == nil {
				t.Fatal("approval authorized a different transaction")
			}
			if _, err := a.Authorize(SignRequest{vectorTx(), proof}, wallet, 1000); err != nil {
				t.Fatal("invalid intent consumed the valid capability", err)
			}
		})
	}
}
func TestDistinctAuthorizersShareReplayProtection(t *testing.T) {
	proof, key := signedApproval()
	dir := t.TempDir()
	var count atomic.Int32
	var wg sync.WaitGroup
	for i := 0; i < 20; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			a := Authorizer{testPolicy(), append(ed25519.PublicKey{}, key...), dir}
			if _, err := a.Authorize(SignRequest{vectorTx(), proof}, wallet, 1000); err == nil {
				count.Add(1)
			}
		}()
	}
	wg.Wait()
	if count.Load() != 1 {
		t.Fatalf("distinct authorizers accepted %d copies", count.Load())
	}
}

func TestType2DigestMatchesIndependentPythonGolden(t *testing.T) {
	// Independently derived from eth-account TypedTransaction.hash, also verified by
	// the Python adapter's exact signed-envelope golden fixture.
	tx := vectorTx()
	tx.Type = 2
	tx.GasPrice = "0"
	tx.MaxPriorityFeePerGas = "1000000000"
	tx.MaxFeePerGas = "20000000000"
	got, err := tx.Digest()
	if err != nil {
		t.Fatal(err)
	}
	if hex.EncodeToString(got) != "577f072b4be21dbe73cdd90f32675d67d2fdfefdecfbc579f52025caf096400a" {
		t.Fatalf("wrong type-2 signing digest: %x", got)
	}
	if err := testPolicy().Validate(tx); err != nil {
		t.Fatal("valid type-2 transaction rejected", err)
	}
}
