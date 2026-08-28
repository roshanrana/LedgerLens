package contracts

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"regexp"
	"sort"
	"strings"
	"time"
)

const (
	SchemaVersion = "1.0"

	EventTransactionNormalized = "ledgerlens.transaction.normalized"
	EventMatchCandidateCreated = "ledgerlens.match.candidate_created"

	WorkerSource = "ledgerlens.match-worker.go"
)

var (
	nonAlnum        = regexp.MustCompile(`[^A-Z0-9]+`)
	amountPattern   = regexp.MustCompile(`^-?\d+(\.\d{1,6})?$`)
	currencyPattern = regexp.MustCompile(`^[A-Z]{3}$`)
)

type Envelope struct {
	EventID        string          `json:"event_id"`
	EventType      string          `json:"event_type"`
	SchemaVersion  string          `json:"schema_version"`
	OccurredAt     string          `json:"occurred_at"`
	RunID          string          `json:"run_id"`
	Source         string          `json:"source"`
	IdempotencyKey string          `json:"idempotency_key"`
	Payload        json.RawMessage `json:"payload"`
}

type NormalizedTransactionPayload struct {
	TransactionID         string   `json:"transaction_id"`
	RawTransactionID      string   `json:"raw_transaction_id"`
	AccountID             string   `json:"account_id"`
	SourceSystem          string   `json:"source_system"`
	ExternalTransactionID *string  `json:"external_transaction_id,omitempty"`
	PostingDate           string   `json:"posting_date"`
	ValueDate             *string  `json:"value_date,omitempty"`
	Amount                string   `json:"amount"`
	Currency              string   `json:"currency"`
	Direction             string   `json:"direction"`
	DescriptionRaw        string   `json:"description_raw"`
	DescriptionNormalized string   `json:"description_normalized"`
	Counterparty          *string  `json:"counterparty,omitempty"`
	Reference             *string  `json:"reference,omitempty"`
	FingerprintExact      string   `json:"fingerprint_exact"`
	FingerprintLoose      string   `json:"fingerprint_loose"`
	QualityFlags          []string `json:"quality_flags"`
}

type NormalizedTransactionEvent struct {
	EventID        string                       `json:"event_id"`
	EventType      string                       `json:"event_type"`
	SchemaVersion  string                       `json:"schema_version"`
	OccurredAt     string                       `json:"occurred_at"`
	RunID          string                       `json:"run_id"`
	Source         string                       `json:"source"`
	IdempotencyKey string                       `json:"idempotency_key"`
	Payload        NormalizedTransactionPayload `json:"payload"`
}

type FeatureVector struct {
	AmountDelta           string  `json:"amount_delta"`
	DateDeltaDays         int     `json:"date_delta_days"`
	ReferenceOverlap      float64 `json:"reference_overlap"`
	DescriptionSimilarity float64 `json:"description_similarity"`
}

type MatchCandidateCreatedPayload struct {
	CandidatePairID    string        `json:"candidate_pair_id"`
	LeftTransactionID  string        `json:"left_transaction_id"`
	RightTransactionID string        `json:"right_transaction_id"`
	BlockingReason     string        `json:"blocking_reason"`
	FeatureVector      FeatureVector `json:"feature_vector"`
	CandidateScore     float64       `json:"candidate_score"`
	CreatedBy          string        `json:"created_by"`
}

type MatchCandidateCreatedEvent struct {
	EventID        string                       `json:"event_id"`
	EventType      string                       `json:"event_type"`
	SchemaVersion  string                       `json:"schema_version"`
	OccurredAt     string                       `json:"occurred_at"`
	RunID          string                       `json:"run_id"`
	Source         string                       `json:"source"`
	IdempotencyKey string                       `json:"idempotency_key"`
	Payload        MatchCandidateCreatedPayload `json:"payload"`
}

func DecodeEnvelope(data []byte) (Envelope, error) {
	var envelope Envelope
	if err := json.Unmarshal(data, &envelope); err != nil {
		return Envelope{}, fmt.Errorf("decode envelope: %w", err)
	}
	return envelope, nil
}

func DecodeNormalizedTransaction(data []byte) (NormalizedTransactionEvent, error) {
	var event NormalizedTransactionEvent
	if err := json.Unmarshal(data, &event); err != nil {
		return NormalizedTransactionEvent{}, fmt.Errorf("decode normalized transaction event: %w", err)
	}
	if err := validateNormalizedTransactionEvent(event); err != nil {
		return NormalizedTransactionEvent{}, err
	}
	return event, nil
}

func validateNormalizedTransactionEvent(event NormalizedTransactionEvent) error {
	if event.EventType != EventTransactionNormalized {
		return fmt.Errorf("unexpected event type %q", event.EventType)
	}
	if event.SchemaVersion != SchemaVersion {
		return fmt.Errorf("unsupported schema version %q", event.SchemaVersion)
	}
	if err := requireNonEmpty("event_id", event.EventID); err != nil {
		return err
	}
	if err := requireNonEmpty("run_id", event.RunID); err != nil {
		return err
	}
	if err := requireNonEmpty("source", event.Source); err != nil {
		return err
	}
	if len(strings.TrimSpace(event.IdempotencyKey)) < 16 {
		return fmt.Errorf("idempotency_key must be at least 16 characters")
	}
	if _, err := time.Parse(time.RFC3339, event.OccurredAt); err != nil {
		return fmt.Errorf("occurred_at: %w", err)
	}

	payload := event.Payload
	for fieldName, value := range map[string]string{
		"transaction_id":         payload.TransactionID,
		"raw_transaction_id":     payload.RawTransactionID,
		"account_id":             payload.AccountID,
		"source_system":          payload.SourceSystem,
		"posting_date":           payload.PostingDate,
		"amount":                 payload.Amount,
		"currency":               payload.Currency,
		"direction":              payload.Direction,
		"description_raw":        payload.DescriptionRaw,
		"description_normalized": payload.DescriptionNormalized,
		"fingerprint_exact":      payload.FingerprintExact,
		"fingerprint_loose":      payload.FingerprintLoose,
	} {
		if err := requireNonEmpty(fieldName, value); err != nil {
			return err
		}
	}
	if _, err := time.Parse(time.DateOnly, payload.PostingDate); err != nil {
		return fmt.Errorf("posting_date: %w", err)
	}
	if payload.ValueDate != nil {
		if _, err := time.Parse(time.DateOnly, *payload.ValueDate); err != nil {
			return fmt.Errorf("value_date: %w", err)
		}
	}
	if !amountPattern.MatchString(payload.Amount) {
		return fmt.Errorf("amount must be a decimal string with up to 6 places")
	}
	if !currencyPattern.MatchString(payload.Currency) {
		return fmt.Errorf("currency must be a 3-letter uppercase ISO code")
	}
	if payload.Direction != "debit" && payload.Direction != "credit" {
		return fmt.Errorf("direction must be debit or credit")
	}
	if payload.QualityFlags == nil {
		return fmt.Errorf("quality_flags is required")
	}
	return nil
}

func requireNonEmpty(fieldName string, value string) error {
	if strings.TrimSpace(value) == "" {
		return fmt.Errorf("%s is required", fieldName)
	}
	return nil
}

func NewCandidateCreatedEvent(runID string, occurredAt time.Time, payload MatchCandidateCreatedPayload) MatchCandidateCreatedEvent {
	stableID := stableHash(payload.CandidatePairID, payload.LeftTransactionID, payload.RightTransactionID)
	return MatchCandidateCreatedEvent{
		EventID:        "evt_candidate_" + stableID[:16],
		EventType:      EventMatchCandidateCreated,
		SchemaVersion:  SchemaVersion,
		OccurredAt:     occurredAt.UTC().Format(time.RFC3339),
		RunID:          runID,
		Source:         WorkerSource,
		IdempotencyKey: "candidate-" + stableID,
		Payload:        payload,
	}
}

func PairID(leftID, rightID string) string {
	ordered := []string{leftID, rightID}
	sort.Strings(ordered)
	return "pair_" + ordered[0] + "_" + ordered[1]
}

func NormalizeReference(reference *string) string {
	if reference == nil {
		return ""
	}
	value := strings.ToUpper(strings.TrimSpace(*reference))
	value = nonAlnum.ReplaceAllString(value, "")
	for _, prefix := range []string{"REFERENCE", "INVOICE", "INV", "REF", "AR"} {
		if strings.HasPrefix(value, prefix) && hasDigit(value[len(prefix):]) {
			return value[len(prefix):]
		}
	}
	return value
}

func stableHash(parts ...string) string {
	hash := sha256.New()
	for _, part := range parts {
		hash.Write([]byte(part))
		hash.Write([]byte{0})
	}
	return hex.EncodeToString(hash.Sum(nil))
}

func hasDigit(value string) bool {
	for _, r := range value {
		if r >= '0' && r <= '9' {
			return true
		}
	}
	return false
}
