.PHONY: build install test vet

build:
	go build ./cmd/screenbot

install:
	go install ./cmd/screenbot

test:
	go test ./...

vet:
	go vet ./...
