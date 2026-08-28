package worker

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
	"time"

	"ledgerlens/go/match-worker/internal/contracts"
)

func TestProcessorEmitsCandidateForReferenceMatchedTransactions(t *testing.T) {
	processor := NewProcessor(Config{
		MaxDateWindowDays: 3,
		WorkerID:          "test-worker",
		Clock: func() time.Time {
			return time.Date(2026, 8, 24, 19, 30, 0, 0, time.UTC)
		},
	})

	bank := loadNormalizedFixture(t, "transaction-normalized.bank.json")
	ledger := loadNormalizedFixture(t, "transaction-normalized.ledger.json")

	first, err := processor.Process(bank)
	if err != nil {
		t.Fatalf("process first event: %v", err)
	}
	if len(first) != 0 {
		t.Fatalf("first transaction should not emit candidates, got %d", len(first))
	}

	second, err := processor.Process(ledger)
	if err != nil {
		t.Fatalf("process second event: %v", err)
	}
	if len(second) != 1 {
		t.Fatalf("expected one candidate, got %d", len(second))
	}

	got := second[0]
	if got.EventType != contracts.EventMatchCandidateCreated {
		t.Fatalf("event type = %q", got.EventType)
	}
	if got.RunID != "run_acme_august_close" {
		t.Fatalf("run id = %q", got.RunID)
	}
	if got.Payload.LeftTransactionID != "txn_bank_001" || got.Payload.RightTransactionID != "txn_ledger_001" {
		t.Fatalf("unexpected pair: %#v", got.Payload)
	}
	if got.Payload.BlockingReason != BlockingSameAmountReference {
		t.Fatalf("blocking reason = %q", got.Payload.BlockingReason)
	}
	if got.Payload.FeatureVector.DateDeltaDays != 2 {
		t.Fatalf("date delta = %d", got.Payload.FeatureVector.DateDeltaDays)
	}
	if got.Payload.FeatureVector.ReferenceOverlap != 1 {
		t.Fatalf("reference overlap = %f", got.Payload.FeatureVector.ReferenceOverlap)
	}
	if got.Payload.CandidateScore < 0.90 {
		t.Fatalf("candidate score = %f", got.Payload.CandidateScore)
	}
}

func TestProcessorIsIdempotentByInputEventAndPair(t *testing.T) {
	processor := NewProcessor(Config{
		Clock: func() time.Time {
			return time.Date(2026, 8, 24, 19, 30, 0, 0, time.UTC)
		},
	})

	bank := loadNormalizedFixture(t, "transaction-normalized.bank.json")
	ledger := loadNormalizedFixture(t, "transaction-normalized.ledger.json")

	if out, err := processor.Process(bank); err != nil || len(out) != 0 {
		t.Fatalf("first bank process out=%d err=%v", len(out), err)
	}
	if out, err := processor.Process(bank); err != nil || len(out) != 0 {
		t.Fatalf("duplicate bank process out=%d err=%v", len(out), err)
	}
	if out, err := processor.Process(ledger); err != nil || len(out) != 1 {
		t.Fatalf("ledger process out=%d err=%v", len(out), err)
	}
	if out, err := processor.Process(ledger); err != nil || len(out) != 0 {
		t.Fatalf("duplicate ledger process out=%d err=%v", len(out), err)
	}
}

func TestProcessorRejectsSameAccountSourcePairs(t *testing.T) {
	processor := NewProcessor(Config{})
	bank := loadNormalizedFixture(t, "transaction-normalized.bank.json")
	other := bank
	other.EventID = "evt_txn_bank_002"
	other.Payload.TransactionID = "txn_bank_002"
	other.Payload.RawTransactionID = "raw_bank_002"

	if out, err := processor.Process(bank); err != nil || len(out) != 0 {
		t.Fatalf("first bank process out=%d err=%v", len(out), err)
	}
	if out, err := processor.Process(other); err != nil || len(out) != 0 {
		t.Fatalf("same account/source process out=%d err=%v", len(out), err)
	}
}

func loadNormalizedFixture(t *testing.T, name string) contracts.NormalizedTransactionEvent {
	t.Helper()

	path := filepath.Join(repoRoot(t), "contracts", "events", "fixtures", name)
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read fixture %s: %v", path, err)
	}

	event, err := contracts.DecodeNormalizedTransaction(data)
	if err != nil {
		t.Fatalf("decode normalized fixture: %v", err)
	}

	roundTrip, err := json.Marshal(event)
	if err != nil {
		t.Fatalf("marshal fixture: %v", err)
	}
	if _, err := contracts.DecodeNormalizedTransaction(roundTrip); err != nil {
		t.Fatalf("round-trip decode: %v", err)
	}
	return event
}

func repoRoot(t *testing.T) string {
	t.Helper()

	dir, err := os.Getwd()
	if err != nil {
		t.Fatalf("get working directory: %v", err)
	}
	for i := 0; i < 8; i++ {
		if _, err := os.Stat(filepath.Join(dir, "contracts", "schemas")); err == nil {
			return dir
		}
		next := filepath.Dir(dir)
		if next == dir {
			break
		}
		dir = next
	}
	t.Fatalf("could not find repository root from working directory")
	return ""
}
