PYTHON ?= python

.PHONY: golden golden-check card card-check test

# Replay the sample statements offline, score them against the golden summary,
# validate emitted events against contracts/schemas, and write metrics/headline.json.
golden:
	$(PYTHON) -m metrics.golden

# Regenerate headline.json and run its schema/determinism self-check.
golden-check: golden
	$(PYTHON) -m unittest tests.golden.test_headline_metrics

# Render docs/assets/metrics.svg and the README results block from metrics/headline.json.
card: golden
	$(PYTHON) metrics/render.py

card-check:
	$(PYTHON) metrics/render.py --check

test:
	$(PYTHON) -m unittest discover -s tests
