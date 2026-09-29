.PHONY: up migrate seed api test
up:        ; docker compose up -d db
migrate:   ; docker compose run --rm etl migrate
seed:      ; docker compose run --rm etl seed-demo
api:       ; docker compose up -d api
status:    ; docker compose run --rm etl status
# Testes: exige PostgreSQL acessível em GWMI_TEST_ADMIN_DSN (ex.: postgresql://gwmi:gwmi@localhost:5432/postgres)
test:      ; python tests/run_all.py
