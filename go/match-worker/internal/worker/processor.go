package worker

import (
	"fmt"
	"math"
	"sort"
	"strconv"
	"strings"
	"time"
	"unicode"

	"ledgerlens/go/match-worker/internal/contracts"
)

const (
	BlockingSameAmountReference = "same_amount_reference_window"
	BlockingSameAmountLoose     = "same_amount_loose_fingerprint_window"
)

type Config struct {
	MaxDateWindowDays int
	WorkerID          string
	Clock             func() time.Time
}

type Processor struct {
	cfg          Config
	seenEvents   map[string]struct{}
	transactions map[string]indexedTransaction
	blocks       map[string][]string
	emittedPairs map[string]struct{}
}

type indexedTransaction struct {
	event        contracts.NormalizedTransactionEvent
	amountMicros int64
	absMicros    int64
	postingDate  time.Time
	referenceKey string
}

type candidateEvaluation struct {
	matched        bool
	blockingReason string
	featureVector  contracts.FeatureVector
	score          float64
}

func NewProcessor(cfg Config) *Processor {
	if cfg.MaxDateWindowDays <= 0 {
		cfg.MaxDateWindowDays = 3
	}
	if cfg.WorkerID == "" {
		cfg.WorkerID = "go-match-worker"
	}
	if cfg.Clock == nil {
		cfg.Clock = time.Now
	}
	return &Processor{
		cfg:          cfg,
		seenEvents:   map[string]struct{}{},
		transactions: map[string]indexedTransaction{},
		blocks:       map[string][]string{},
		emittedPairs: map[string]struct{}{},
	}
}

func (p *Processor) Process(event contracts.NormalizedTransactionEvent) ([]contracts.MatchCandidateCreatedEvent, error) {
	if event.EventType != contracts.EventTransactionNormalized {
		return nil, fmt.Errorf("unsupported event type %q", event.EventType)
	}
	if _, ok := p.seenEvents[event.EventID]; ok {
		return nil, nil
	}
	p.seenEvents[event.EventID] = struct{}{}

	incoming, err := indexTransaction(event)
	if err != nil {
		return nil, err
	}

	candidatesByPairID := map[string]contracts.MatchCandidateCreatedEvent{}
	for _, key := range blockKeys(incoming) {
		for _, existingID := range p.blocks[key] {
			existing := p.transactions[existingID]
			evaluation := p.evaluate(existing, incoming)
			if !evaluation.matched {
				continue
			}

			pairID := contracts.PairID(existing.event.Payload.TransactionID, incoming.event.Payload.TransactionID)
			if _, emitted := p.emittedPairs[pairID]; emitted {
				continue
			}
			p.emittedPairs[pairID] = struct{}{}

			leftID, rightID := orderedPair(existing.event.Payload.TransactionID, incoming.event.Payload.TransactionID)
			candidatesByPairID[pairID] = contracts.NewCandidateCreatedEvent(event.RunID, p.cfg.Clock(), contracts.MatchCandidateCreatedPayload{
				CandidatePairID:    pairID,
				LeftTransactionID:  leftID,
				RightTransactionID: rightID,
				BlockingReason:     evaluation.blockingReason,
				FeatureVector:      evaluation.featureVector,
				CandidateScore:     evaluation.score,
				CreatedBy:          p.cfg.WorkerID,
			})
		}
	}

	p.transactions[incoming.event.Payload.TransactionID] = incoming
	for _, key := range blockKeys(incoming) {
		p.blocks[key] = append(p.blocks[key], incoming.event.Payload.TransactionID)
	}

	pairIDs := make([]string, 0, len(candidatesByPairID))
	for pairID := range candidatesByPairID {
		pairIDs = append(pairIDs, pairID)
	}
	sort.Strings(pairIDs)

	out := make([]contracts.MatchCandidateCreatedEvent, 0, len(pairIDs))
	for _, pairID := range pairIDs {
		out = append(out, candidatesByPairID[pairID])
	}
	return out, nil
}

func indexTransaction(event contracts.NormalizedTransactionEvent) (indexedTransaction, error) {
	amountMicros, err := parseMicros(event.Payload.Amount)
	if err != nil {
		return indexedTransaction{}, fmt.Errorf("transaction %s amount: %w", event.Payload.TransactionID, err)
	}
	postingDate, err := time.Parse(time.DateOnly, event.Payload.PostingDate)
	if err != nil {
		return indexedTransaction{}, fmt.Errorf("transaction %s posting_date: %w", event.Payload.TransactionID, err)
	}
	return indexedTransaction{
		event:        event,
		amountMicros: amountMicros,
		absMicros:    abs64(amountMicros),
		postingDate:  postingDate,
		referenceKey: contracts.NormalizeReference(event.Payload.Reference),
	}, nil
}

func blockKeys(tx indexedTransaction) []string {
	base := strings.Join([]string{tx.event.RunID, tx.event.Payload.Currency, strconv.FormatInt(tx.absMicros, 10)}, "|")
	keys := []string{}
	if tx.referenceKey != "" {
		keys = append(keys, base+"|ref|"+tx.referenceKey)
	}
	if tx.event.Payload.FingerprintLoose != "" {
		keys = append(keys, base+"|loose|"+tx.event.Payload.FingerprintLoose)
	}
	return keys
}

func (p *Processor) evaluate(left indexedTransaction, right indexedTransaction) candidateEvaluation {
	if left.event.RunID != right.event.RunID {
		return candidateEvaluation{}
	}
	if left.event.Payload.TransactionID == right.event.Payload.TransactionID {
		return candidateEvaluation{}
	}
	if left.event.Payload.Currency != right.event.Payload.Currency {
		return candidateEvaluation{}
	}
	if left.event.Payload.AccountID == right.event.Payload.AccountID && left.event.Payload.SourceSystem == right.event.Payload.SourceSystem {
		return candidateEvaluation{}
	}
	if left.absMicros != right.absMicros {
		return candidateEvaluation{}
	}

	dateDelta := int(math.Abs(left.postingDate.Sub(right.postingDate).Hours() / 24))
	if dateDelta > p.cfg.MaxDateWindowDays {
		return candidateEvaluation{}
	}

	referenceOverlap := referenceOverlap(left.referenceKey, right.referenceKey)
	descriptionSimilarity := tokenSimilarity(left.event.Payload.DescriptionNormalized, right.event.Payload.DescriptionNormalized)
	blockingReason := ""
	switch {
	case referenceOverlap == 1:
		blockingReason = BlockingSameAmountReference
	case left.event.Payload.FingerprintLoose != "" && left.event.Payload.FingerprintLoose == right.event.Payload.FingerprintLoose:
		blockingReason = BlockingSameAmountLoose
	default:
		return candidateEvaluation{}
	}

	score := round2(0.50 + (0.30 * referenceOverlap) + (0.15 * dateScore(dateDelta, p.cfg.MaxDateWindowDays)) + (0.05 * descriptionSimilarity))
	if score < 0.65 {
		return candidateEvaluation{}
	}

	return candidateEvaluation{
		matched:        true,
		blockingReason: blockingReason,
		featureVector: contracts.FeatureVector{
			AmountDelta:           "0.00",
			DateDeltaDays:         dateDelta,
			ReferenceOverlap:      round2(referenceOverlap),
			DescriptionSimilarity: round2(descriptionSimilarity),
		},
		score: score,
	}
}

func parseMicros(raw string) (int64, error) {
	value := strings.TrimSpace(raw)
	if value == "" {
		return 0, fmt.Errorf("empty amount")
	}

	sign := int64(1)
	if strings.HasPrefix(value, "-") {
		sign = -1
		value = strings.TrimPrefix(value, "-")
	}
	if strings.HasPrefix(value, "+") {
		value = strings.TrimPrefix(value, "+")
	}

	parts := strings.Split(value, ".")
	if len(parts) > 2 || parts[0] == "" {
		return 0, fmt.Errorf("invalid decimal %q", raw)
	}

	whole, err := strconv.ParseInt(parts[0], 10, 64)
	if err != nil {
		return 0, fmt.Errorf("invalid whole amount %q", raw)
	}

	fraction := ""
	if len(parts) == 2 {
		fraction = parts[1]
	}
	if len(fraction) > 6 {
		return 0, fmt.Errorf("more than 6 decimal places in %q", raw)
	}
	for len(fraction) < 6 {
		fraction += "0"
	}
	fractionValue, err := strconv.ParseInt(fraction, 10, 64)
	if err != nil {
		return 0, fmt.Errorf("invalid fractional amount %q", raw)
	}
	return sign * ((whole * 1_000_000) + fractionValue), nil
}

func referenceOverlap(left, right string) float64 {
	if left == "" || right == "" {
		return 0
	}
	if left == right {
		return 1
	}
	if strings.Contains(left, right) || strings.Contains(right, left) {
		shorter := math.Min(float64(len(left)), float64(len(right)))
		longer := math.Max(float64(len(left)), float64(len(right)))
		return shorter / longer
	}
	return 0
}

func tokenSimilarity(left, right string) float64 {
	leftTokens := tokenSet(left)
	rightTokens := tokenSet(right)
	if len(leftTokens) == 0 || len(rightTokens) == 0 {
		return 0
	}

	intersection := 0
	for token := range leftTokens {
		if _, ok := rightTokens[token]; ok {
			intersection++
		}
	}
	union := len(leftTokens) + len(rightTokens) - intersection
	if union == 0 {
		return 0
	}
	return float64(intersection) / float64(union)
}

func tokenSet(value string) map[string]struct{} {
	out := map[string]struct{}{}
	var builder strings.Builder
	flush := func() {
		if builder.Len() >= 2 {
			out[builder.String()] = struct{}{}
		}
		builder.Reset()
	}

	for _, r := range strings.ToUpper(value) {
		if unicode.IsLetter(r) || unicode.IsDigit(r) {
			builder.WriteRune(r)
			continue
		}
		flush()
	}
	flush()
	return out
}

func dateScore(deltaDays int, maxWindow int) float64 {
	if maxWindow <= 0 {
		return 0
	}
	if deltaDays > maxWindow {
		return 0
	}
	return 1 - (float64(deltaDays) / float64(maxWindow+1))
}

func orderedPair(leftID, rightID string) (string, string) {
	if leftID <= rightID {
		return leftID, rightID
	}
	return rightID, leftID
}

func abs64(value int64) int64 {
	if value < 0 {
		return -value
	}
	return value
}

func round2(value float64) float64 {
	return math.Round(value*100) / 100
}
