PYTHON ?= python

.PHONY: golden golden-check test

# Replay the sample statements offline, score them against the golden summary,
# validate emitted events against contracts/schemas, and write metrics/headline.json.
golden:
	$(PYTHON) -m metrics.golden

# Regenerate headline.json and run its schema/determinism self-check.
golden-check: golden
	$(PYTHON) -m unittest tests.golden.test_headline_metrics

test:
	$(PYTHON) -m unittest discover -s tests
