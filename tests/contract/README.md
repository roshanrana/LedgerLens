# Contract Tests

The sidecar contract checks live in the Go worker test suite so they can validate schemas, fixtures, and emitted worker events together:

```bash
cd go/match-worker
go test ./...
```

Those tests compile every JSON schema under `contracts/schemas/`, validate fixture events under `contracts/events/fixtures/`, and exercise the file-free Go processor path.
