package transport

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"strings"

	"ledgerlens/go/match-worker/internal/contracts"
	"ledgerlens/go/match-worker/internal/worker"
)

func RunFile(ctx context.Context, inputPath string, outputPath string, processor *worker.Processor) error {
	input, closeInput, err := openInput(inputPath)
	if err != nil {
		return err
	}
	defer closeInput()

	output, closeOutput, err := openOutput(outputPath)
	if err != nil {
		return err
	}
	defer closeOutput()

	scanner := bufio.NewScanner(input)
	lineNumber := 0
	for scanner.Scan() {
		select {
		case <-ctx.Done():
			return ctx.Err()
		default:
		}

		lineNumber++
		line := strings.TrimSpace(scanner.Text())
		if line == "" {
			continue
		}

		envelope, err := contracts.DecodeEnvelope([]byte(line))
		if err != nil {
			return fmt.Errorf("line %d: %w", lineNumber, err)
		}
		if envelope.EventType != contracts.EventTransactionNormalized {
			continue
		}

		event, err := contracts.DecodeNormalizedTransaction([]byte(line))
		if err != nil {
			return fmt.Errorf("line %d: %w", lineNumber, err)
		}
		candidates, err := processor.Process(event)
		if err != nil {
			return fmt.Errorf("line %d: %w", lineNumber, err)
		}
		for _, candidate := range candidates {
			if err := writeNDJSON(output, candidate); err != nil {
				return err
			}
		}
	}
	if err := scanner.Err(); err != nil {
		return fmt.Errorf("read input: %w", err)
	}
	return nil
}

func writeNDJSON(output io.Writer, event contracts.MatchCandidateCreatedEvent) error {
	encoded, err := json.Marshal(event)
	if err != nil {
		return fmt.Errorf("encode candidate event: %w", err)
	}
	if _, err := output.Write(append(encoded, '\n')); err != nil {
		return fmt.Errorf("write candidate event: %w", err)
	}
	return nil
}

func openInput(path string) (io.Reader, func(), error) {
	if path == "-" {
		return os.Stdin, func() {}, nil
	}
	file, err := os.Open(path)
	if err != nil {
		return nil, nil, fmt.Errorf("open input %q: %w", path, err)
	}
	return file, func() { _ = file.Close() }, nil
}

func openOutput(path string) (io.Writer, func(), error) {
	if path == "-" {
		return os.Stdout, func() {}, nil
	}
	file, err := os.Create(path)
	if err != nil {
		return nil, nil, fmt.Errorf("open output %q: %w", path, err)
	}
	return file, func() { _ = file.Close() }, nil
}
