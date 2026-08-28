package transport

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"

	"github.com/segmentio/kafka-go"

	"ledgerlens/go/match-worker/internal/contracts"
	"ledgerlens/go/match-worker/internal/worker"
)

type KafkaConfig struct {
	Brokers     []string
	GroupID     string
	InputTopic  string
	OutputTopic string
}

func RunKafka(ctx context.Context, cfg KafkaConfig, processor *worker.Processor) error {
	if len(cfg.Brokers) == 0 {
		return fmt.Errorf("at least one broker is required")
	}
	if strings.TrimSpace(cfg.GroupID) == "" {
		return fmt.Errorf("group id is required")
	}
	if strings.TrimSpace(cfg.InputTopic) == "" || strings.TrimSpace(cfg.OutputTopic) == "" {
		return fmt.Errorf("input and output topics are required")
	}

	reader := kafka.NewReader(kafka.ReaderConfig{
		Brokers: cfg.Brokers,
		GroupID: cfg.GroupID,
		Topic:   cfg.InputTopic,
	})
	defer reader.Close()

	writer := kafka.NewWriter(kafka.WriterConfig{
		Brokers: cfg.Brokers,
		Topic:   cfg.OutputTopic,
	})
	defer writer.Close()

	for {
		message, err := reader.FetchMessage(ctx)
		if err != nil {
			return fmt.Errorf("read kafka message: %w", err)
		}

		envelope, err := contracts.DecodeEnvelope(message.Value)
		if err != nil {
			return fmt.Errorf("decode kafka envelope: %w", err)
		}
		if envelope.EventType != contracts.EventTransactionNormalized {
			if err := reader.CommitMessages(ctx, message); err != nil {
				return fmt.Errorf("commit ignored kafka message: %w", err)
			}
			continue
		}

		event, err := contracts.DecodeNormalizedTransaction(message.Value)
		if err != nil {
			return err
		}
		candidates, err := processor.Process(event)
		if err != nil {
			return err
		}
		for _, candidate := range candidates {
			encoded, err := json.Marshal(candidate)
			if err != nil {
				return fmt.Errorf("encode candidate event: %w", err)
			}
			if err := writer.WriteMessages(ctx, kafka.Message{
				Key:   []byte(candidate.Payload.CandidatePairID),
				Value: encoded,
			}); err != nil {
				return fmt.Errorf("write candidate event: %w", err)
			}
		}
		if err := reader.CommitMessages(ctx, message); err != nil {
			return fmt.Errorf("commit processed kafka message: %w", err)
		}
	}
}
