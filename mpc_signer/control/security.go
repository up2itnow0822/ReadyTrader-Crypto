package control

import (
	"bytes"
	"crypto/ed25519"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"math/big"
	"os"
	"path/filepath"
	"strings"

	"golang.org/x/crypto/sha3"
)

type Transaction struct {
	Type                 int    `json:"type"`
	ChainID              string `json:"chain_id"`
	Nonce                string `json:"nonce"`
	Gas                  string `json:"gas"`
	To                   string `json:"to"`
	Value                string `json:"value"`
	Data                 string `json:"data"`
	GasPrice             string `json:"gas_price"`
	MaxFeePerGas         string `json:"max_fee_per_gas"`
	MaxPriorityFeePerGas string `json:"max_priority_fee_per_gas"`
}
type Approval struct {
	ID           string `json:"id"`
	ExpiresAt    int64  `json:"expires_at"`
	Wallet       string `json:"wallet"`
	DigestHex    string `json:"digest_hex"`
	SignatureHex string `json:"signature_hex"`
}
type SignRequest struct {
	Transaction Transaction `json:"transaction"`
	Approval    Approval    `json:"approval"`
}
type Policy struct {
	AllowedChainIDs        []string `json:"allowed_chain_ids"`
	AllowedDestinations    []string `json:"allowed_destinations"`
	AllowedTokenContracts  []string `json:"allowed_token_contracts"`
	AllowedTokenRecipients []string `json:"allowed_token_recipients"`
	AllowedSpenders        []string `json:"allowed_spenders"`
	MaxValueWei            string   `json:"max_value_wei"`
	MaxTokenAmount         string   `json:"max_token_amount"`
	MaxGas                 uint64   `json:"max_gas"`
	MaxFeePerGas           string   `json:"max_fee_per_gas"`
	MaxTotalFeeWei         string   `json:"max_total_fee_wei"`
}
type Authorizer struct {
	Policy      Policy
	ApprovalKey ed25519.PublicKey
	ReplayDir   string
}

func number(s string) (*big.Int, error) {
	if s == "" || len(s) > 78 || (len(s) > 1 && s[0] == '0') {
		return nil, errors.New("noncanonical integer")
	}
	for _, c := range s {
		if c < '0' || c > '9' {
			return nil, errors.New("invalid unsigned integer")
		}
	}
	v, ok := new(big.Int).SetString(s, 10)
	if !ok || v.BitLen() > 256 {
		return nil, errors.New("integer exceeds uint256")
	}
	return v, nil
}
func lowerHex(s string, n int) ([]byte, error) {
	if s != strings.ToLower(s) || len(s) != 2*n {
		return nil, errors.New("noncanonical hex")
	}
	b, err := hex.DecodeString(s)
	if err != nil {
		return nil, err
	}
	return b, nil
}
func address(s string) ([]byte, error) {
	if !strings.HasPrefix(s, "0x") {
		return nil, errors.New("address needs 0x prefix")
	}
	return lowerHex(s[2:], 20)
}
func rlpBytes(b []byte) []byte {
	if len(b) == 1 && b[0] < 0x80 {
		return b
	}
	if len(b) < 56 {
		return append([]byte{byte(0x80 + len(b))}, b...)
	}
	size := new(big.Int).SetInt64(int64(len(b))).Bytes()
	return append(append([]byte{byte(0xb7 + len(size))}, size...), b...)
}
func rlpList(fields ...[]byte) []byte {
	payload := bytes.Join(fields, nil)
	if len(payload) < 56 {
		return append([]byte{byte(0xc0 + len(payload))}, payload...)
	}
	size := new(big.Int).SetInt64(int64(len(payload))).Bytes()
	return append(append([]byte{byte(0xf7 + len(size))}, size...), payload...)
}
func (t Transaction) quantities() (map[string]*big.Int, error) {
	raw := map[string]string{"chain": t.ChainID, "nonce": t.Nonce, "gas": t.Gas, "value": t.Value, "price": t.GasPrice, "max": t.MaxFeePerGas, "priority": t.MaxPriorityFeePerGas}
	vals := make(map[string]*big.Int)
	for name, v := range raw {
		n, err := number(v)
		if err != nil {
			return nil, fmt.Errorf("%s: %w", name, err)
		}
		vals[name] = n
	}
	if vals["chain"].Sign() == 0 || vals["gas"].Sign() == 0 || vals["gas"].BitLen() > 64 || vals["nonce"].BitLen() > 64 {
		return nil, errors.New("invalid chain, gas or nonce")
	}
	switch t.Type {
	case 0:
		if vals["max"].Sign() != 0 || vals["priority"].Sign() != 0 {
			return nil, errors.New("mixed fee fields")
		}
	case 2:
		if vals["price"].Sign() != 0 || vals["priority"].Cmp(vals["max"]) > 0 {
			return nil, errors.New("invalid type 2 fees")
		}
	default:
		return nil, errors.New("unsupported transaction type")
	}
	return vals, nil
}
func (t Transaction) Digest() ([]byte, error) {
	v, err := t.quantities()
	if err != nil {
		return nil, err
	}
	to, err := address(t.To)
	if err != nil {
		return nil, err
	}
	if !strings.HasPrefix(t.Data, "0x") || len(t.Data) > 2+2*4096 {
		return nil, errors.New("invalid calldata")
	}
	data, err := lowerHex(t.Data[2:], (len(t.Data)-2)/2)
	if err != nil {
		return nil, err
	}
	val := func(name string) []byte { return rlpBytes(v[name].Bytes()) }
	var preimage []byte
	if t.Type == 0 {
		preimage = rlpList(val("nonce"), val("price"), val("gas"), rlpBytes(to), val("value"), rlpBytes(data), val("chain"), rlpBytes(nil), rlpBytes(nil))
	} else {
		preimage = append([]byte{2}, rlpList(val("chain"), val("nonce"), val("priority"), val("max"), val("gas"), rlpBytes(to), val("value"), rlpBytes(data), rlpList())...)
	}
	h := sha3.NewLegacyKeccak256()
	_, _ = h.Write(preimage)
	return h.Sum(nil), nil
}
func contains(list []string, value string) bool {
	for _, v := range list {
		if v == value {
			return true
		}
	}
	return false
}
func (p Policy) CheckConfig() error {
	if len(p.AllowedChainIDs) == 0 || p.MaxGas == 0 {
		return errors.New("chain allowlist and gas limit required")
	}
	for _, c := range p.AllowedChainIDs {
		v, err := number(c)
		if err != nil || v.Sign() == 0 {
			return errors.New("invalid policy chain")
		}
	}
	for _, list := range [][]string{p.AllowedDestinations, p.AllowedTokenContracts, p.AllowedTokenRecipients, p.AllowedSpenders} {
		for _, s := range list {
			if _, err := address(s); err != nil {
				return err
			}
		}
	}
	for _, s := range []string{p.MaxValueWei, p.MaxTokenAmount, p.MaxFeePerGas, p.MaxTotalFeeWei} {
		if _, err := number(s); err != nil {
			return err
		}
	}
	return nil
}
func (p Policy) Validate(t Transaction) error {
	if err := p.CheckConfig(); err != nil {
		return err
	}
	v, err := t.quantities()
	if err != nil {
		return err
	}
	if _, err = t.Digest(); err != nil {
		return err
	}
	if !contains(p.AllowedChainIDs, t.ChainID) {
		return errors.New("chain denied")
	}
	maxValue, _ := number(p.MaxValueWei)
	maxFee, _ := number(p.MaxFeePerGas)
	maxTotal, _ := number(p.MaxTotalFeeWei)
	price := v["price"]
	if t.Type == 2 {
		price = v["max"]
	}
	if v["value"].Cmp(maxValue) > 0 || v["gas"].Uint64() > p.MaxGas || price.Cmp(maxFee) > 0 || new(big.Int).Mul(price, v["gas"]).Cmp(maxTotal) > 0 {
		return errors.New("value or fee policy exceeded")
	}
	if t.Data == "0x" {
		if !contains(p.AllowedDestinations, t.To) {
			return errors.New("destination denied")
		}
		return nil
	}
	if !contains(p.AllowedTokenContracts, t.To) || v["value"].Sign() != 0 || len(t.Data) != 138 {
		return errors.New("unknown contract semantics")
	}
	b, _ := hex.DecodeString(t.Data[2:])
	if !bytes.Equal(b[4:16], make([]byte, 12)) {
		return errors.New("noncanonical ABI address")
	}
	target := "0x" + hex.EncodeToString(b[16:36])
	amount := new(big.Int).SetBytes(b[36:68])
	maxToken, _ := number(p.MaxTokenAmount)
	if amount.Cmp(maxToken) > 0 {
		return errors.New("token amount exceeded")
	}
	switch t.Data[:10] {
	case "0xa9059cbb":
		if !contains(p.AllowedTokenRecipients, target) {
			return errors.New("token recipient denied")
		}
	case "0x095ea7b3":
		if !contains(p.AllowedSpenders, target) {
			return errors.New("spender denied")
		}
	default:
		return errors.New("unknown contract selector")
	}
	return nil
}

// Consume writes an exclusive durable record before any irreversible work. A failed or
// ambiguous operation still consumes its capability; operators reconcile before a new approval.
func Consume(dir, kind, id string, record any) error {
	if _, err := lowerHex(id, 32); err != nil {
		return err
	}
	if dir == "" {
		return errors.New("replay storage required")
	}
	if err := os.MkdirAll(dir, 0700); err != nil {
		return err
	}
	data, err := json.Marshal(record)
	if err != nil {
		return err
	}
	f, err := os.OpenFile(filepath.Join(dir, kind+"-"+id+".json"), os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if err != nil {
		return errors.New("approval consumed or replay storage unavailable")
	}
	// Never remove the marker after a write failure: fail closed across restarts.
	_, err = f.Write(data)
	if err == nil {
		err = f.Sync()
	}
	closeErr := f.Close()
	if err != nil {
		return err
	}
	if closeErr != nil {
		return closeErr
	}
	d, err := os.Open(dir)
	if err != nil {
		return err
	}
	defer d.Close()
	return d.Sync()
}
func (a Authorizer) Authorize(req SignRequest, wallet string, now int64) ([]byte, error) {
	if err := a.Policy.Validate(req.Transaction); err != nil {
		return nil, err
	}
	digest, err := req.Transaction.Digest()
	if err != nil {
		return nil, err
	}
	p := req.Approval
	if _, err := lowerHex(p.ID, 32); err != nil {
		return nil, errors.New("invalid approval id")
	}
	if p.Wallet != wallet || p.DigestHex != "0x"+hex.EncodeToString(digest) || p.ExpiresAt <= now || p.ExpiresAt > now+300 {
		return nil, errors.New("approval does not authorize this transaction")
	}
	sig, err := lowerHex(p.SignatureHex, ed25519.SignatureSize)
	if err != nil {
		return nil, err
	}
	msg := fmt.Sprintf("readytrader-mpc-approval-v1\n%s\n%d\n%s\n%s", p.ID, p.ExpiresAt, p.Wallet, p.DigestHex)
	if len(a.ApprovalKey) != ed25519.PublicKeySize || !ed25519.Verify(a.ApprovalKey, []byte(msg), sig) {
		return nil, errors.New("invalid approval signature")
	}
	if err := Consume(a.ReplayDir, "sign", p.ID, p); err != nil {
		return nil, err
	}
	return digest, nil
}
