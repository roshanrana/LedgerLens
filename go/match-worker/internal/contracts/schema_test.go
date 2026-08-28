package contracts

import (
	"encoding/json"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/santhosh-tekuri/jsonschema/v6"
)

func TestFixtureEventsValidateAgainstSchemas(t *testing.T) {
	root := repoRoot(t)
	cases := map[string]struct {
		eventPath  string
		schemaName string
	}{
		"normalized_transaction.example.json": {
			eventPath:  filepath.Join("contracts", "events", "normalized_transaction.example.json"),
			schemaName: "transaction-normalized.schema.json",
		},
		"candidate_created.example.json": {
			eventPath:  filepath.Join("contracts", "events", "candidate_created.example.json"),
			schemaName: "match-candidate-created.schema.json",
		},
		"statement-ingested.json": {
			eventPath:  filepath.Join("contracts", "events", "fixtures", "statement-ingested.json"),
			schemaName: "statement-ingested.schema.json",
		},
		"transaction-normalized.bank.json": {
			eventPath:  filepath.Join("contracts", "events", "fixtures", "transaction-normalized.bank.json"),
			schemaName: "transaction-normalized.schema.json",
		},
		"transaction-normalized.ledger.json": {
			eventPath:  filepath.Join("contracts", "events", "fixtures", "transaction-normalized.ledger.json"),
			schemaName: "transaction-normalized.schema.json",
		},
		"match-candidate-created.json": {
			eventPath:  filepath.Join("contracts", "events", "fixtures", "match-candidate-created.json"),
			schemaName: "match-candidate-created.schema.json",
		},
		"match-decision-created.json": {
			eventPath:  filepath.Join("contracts", "events", "fixtures", "match-decision-created.json"),
			schemaName: "match-decision-created.schema.json",
		},
		"review-required.json": {
			eventPath:  filepath.Join("contracts", "events", "fixtures", "review-required.json"),
			schemaName: "review-required.schema.json",
		},
		"review-resolved.json": {
			eventPath:  filepath.Join("contracts", "events", "fixtures", "review-resolved.json"),
			schemaName: "review-resolved.schema.json",
		},
		"report-generated.json": {
			eventPath:  filepath.Join("contracts", "events", "fixtures", "report-generated.json"),
			schemaName: "report-generated.schema.json",
		},
	}

	for name, tc := range cases {
		t.Run(name, func(t *testing.T) {
			schema := compileSchema(t, filepath.Join(root, "contracts", "schemas", tc.schemaName))
			fixture := loadJSON(t, filepath.Join(root, tc.eventPath))
			if err := schema.Validate(fixture); err != nil {
				t.Fatalf("fixture does not validate against %s: %v", tc.schemaName, err)
			}
		})
	}
}

func TestAllSchemasCompile(t *testing.T) {
	root := repoRoot(t)
	entries, err := os.ReadDir(filepath.Join(root, "contracts", "schemas"))
	if err != nil {
		t.Fatalf("read schemas: %v", err)
	}
	for _, entry := range entries {
		if entry.IsDir() || !strings.HasSuffix(entry.Name(), ".schema.json") {
			continue
		}
		t.Run(entry.Name(), func(t *testing.T) {
			compileSchema(t, filepath.Join(root, "contracts", "schemas", entry.Name()))
		})
	}
}

func TestDecodeNormalizedTransactionRejectsInvalidBoundaryFields(t *testing.T) {
	valid := loadNormalizedFixture(t, "transaction-normalized.bank.json")
	cases := map[string]func(InvalidNormalizedTransactionEvent) InvalidNormalizedTransactionEvent{
		"bad amount": func(event InvalidNormalizedTransactionEvent) InvalidNormalizedTransactionEvent {
			event.Payload.Amount = "12.0000001"
			return event
		},
		"bad currency": func(event InvalidNormalizedTransactionEvent) InvalidNormalizedTransactionEvent {
			event.Payload.Currency = "usd"
			return event
		},
		"bad direction": func(event InvalidNormalizedTransactionEvent) InvalidNormalizedTransactionEvent {
			event.Payload.Direction = "zero"
			return event
		},
		"bad posting date": func(event InvalidNormalizedTransactionEvent) InvalidNormalizedTransactionEvent {
			event.Payload.PostingDate = "08/24/2026"
			return event
		},
		"empty account": func(event InvalidNormalizedTransactionEvent) InvalidNormalizedTransactionEvent {
			event.Payload.AccountID = ""
			return event
		},
		"empty fingerprint": func(event InvalidNormalizedTransactionEvent) InvalidNormalizedTransactionEvent {
			event.Payload.FingerprintLoose = ""
			return event
		},
		"missing quality flags": func(event InvalidNormalizedTransactionEvent) InvalidNormalizedTransactionEvent {
			event.Payload.QualityFlags = nil
			return event
		},
	}

	for name, mutate := range cases {
		t.Run(name, func(t *testing.T) {
			event := mutate(valid)
			data, err := json.Marshal(event)
			if err != nil {
				t.Fatalf("marshal mutated event: %v", err)
			}
			if _, err := DecodeNormalizedTransaction(data); err == nil {
				t.Fatalf("expected decode validation error")
			}
		})
	}
}

func compileSchema(t *testing.T, path string) *jsonschema.Schema {
	t.Helper()

	compiler := jsonschema.NewCompiler()
	schema, err := compiler.Compile(fileURL(path))
	if err != nil {
		t.Fatalf("compile schema %s: %v", path, err)
	}
	return schema
}

func loadJSON(t *testing.T, path string) any {
	t.Helper()

	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read json %s: %v", path, err)
	}
	var decoded any
	if err := json.Unmarshal(data, &decoded); err != nil {
		t.Fatalf("decode json %s: %v", path, err)
	}
	return decoded
}

type InvalidNormalizedTransactionEvent NormalizedTransactionEvent

func loadNormalizedFixture(t *testing.T, name string) InvalidNormalizedTransactionEvent {
	t.Helper()

	data, err := os.ReadFile(filepath.Join(repoRoot(t), "contracts", "events", "fixtures", name))
	if err != nil {
		t.Fatalf("read fixture: %v", err)
	}
	event, err := DecodeNormalizedTransaction(data)
	if err != nil {
		t.Fatalf("decode fixture: %v", err)
	}
	return InvalidNormalizedTransactionEvent(event)
}

func fileURL(path string) string {
	absolute, err := filepath.Abs(path)
	if err != nil {
		absolute = path
	}
	u := url.URL{Scheme: "file", Path: filepath.ToSlash(absolute)}
	if len(u.Path) >= 2 && u.Path[1] == ':' {
		u.Path = "/" + u.Path
	}
	return u.String()
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
