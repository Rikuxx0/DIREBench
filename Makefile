PYTHON ?= python3

.PHONY: setup cluster-up preflight deploy test reproduce evaluate report cluster-down
setup:
	$(PYTHON) -m pip install -e .
cluster-up:
	./scripts/cluster-up.sh
preflight:
	$(PYTHON) -m direbench.cli preflight
deploy:
	$(PYTHON) -m direbench.cli deploy
test:
	PYTHONPATH=src $(PYTHON) -m unittest discover -s tests -v
reproduce:
	$(PYTHON) -m direbench.cli reproduce --scenario S1
evaluate:
	$(PYTHON) -m direbench.cli evaluate --baseline B0,B1,B2,B3
report:
	$(PYTHON) -m direbench.cli report
cluster-down:
	./scripts/cluster-down.sh
