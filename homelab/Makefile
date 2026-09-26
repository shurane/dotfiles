.PHONY: all up down restart logs ps sync check

ROOT_DIR := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))

all: up

sync:
	@$(ROOT_DIR)/arcane/generate_overrides.py

check:
	@$(ROOT_DIR)/arcane/generate_overrides.py --check

up: sync
	docker compose -f $(ROOT_DIR)/docker-compose.yml up -d $(ARGS)

down:
	docker compose -f $(ROOT_DIR)/docker-compose.yml down $(ARGS)

restart: sync
	docker compose -f $(ROOT_DIR)/docker-compose.yml restart $(ARGS)

logs:
	docker compose -f $(ROOT_DIR)/docker-compose.yml logs -f $(ARGS)

ps:
	docker compose -f $(ROOT_DIR)/docker-compose.yml ps $(ARGS)
