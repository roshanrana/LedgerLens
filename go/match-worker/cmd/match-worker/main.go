package main

import (
	"context"
	"flag"
	"fmt"
	"os"
	"os/signal"
	"strings"
	"syscall"

	"ledgerlens/go/match-worker/internal/transport"
	"ledgerlens/go/match-worker/internal/worker"
)

func main() {
	var (
		mode              = flag.String("mode", "file", "worker mode: file or kafka")
		input             = flag.String("input", "-", "input NDJSON file path, or - for stdin")
		output            = flag.String("output", "-", "output NDJSON file path, or - for stdout")
		brokers           = flag.String("brokers", "localhost:19092", "comma-separated Kafka broker list")
		groupID           = flag.String("group", "ledgerlens-match-worker", "Kafka consumer group")
		inputTopic        = flag.String("input-topic", "ledgerlens.transaction.normalized", "Kafka input topic")
		outputTopic       = flag.String("output-topic", "ledgerlens.match.candidate_created", "Kafka output topic")
		maxDateWindowDays = flag.Int("max-date-window-days", 3, "maximum posting-date distance for candidate blocking")
		workerID          = flag.String("worker-id", "go-match-worker", "created_by value on emitted candidate events")
	)
	flag.Parse()

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	processor := worker.NewProcessor(worker.Config{
		MaxDateWindowDays: *maxDateWindowDays,
		WorkerID:          *workerID,
	})

	var err error
	switch *mode {
	case "file":
		err = transport.RunFile(ctx, *input, *output, processor)
	case "kafka":
		err = transport.RunKafka(ctx, transport.KafkaConfig{
			Brokers:     splitCSV(*brokers),
			GroupID:     *groupID,
			InputTopic:  *inputTopic,
			OutputTopic: *outputTopic,
		}, processor)
	default:
		err = fmt.Errorf("unknown mode %q", *mode)
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

func splitCSV(value string) []string {
	parts := strings.Split(value, ",")
	out := make([]string, 0, len(parts))
	for _, part := range parts {
		trimmed := strings.TrimSpace(part)
		if trimmed != "" {
			out = append(out, trimmed)
		}
	}
	return out
}
