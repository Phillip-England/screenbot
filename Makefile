.PHONY: install uninstall test

install:
	uv tool install --force --no-cache .

uninstall:
	uv tool uninstall screenbot

test:
	uv run python -m unittest discover -s tests -v
