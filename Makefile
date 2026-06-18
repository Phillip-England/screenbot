.PHONY: install test

UV ?= uv

install:
	$(UV) tool install --force .

test:
	$(UV) run python -m unittest discover -s tests -v
