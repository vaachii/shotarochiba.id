SHIORI ?= shiori
SHIORI_FRONTEND ?= shiori-frontend
BACKEND_PORT ?= 4000
FRONTEND_PORT ?= 3000

.PHONY: draft setup test check-tools

draft:
	@set -eu; \
	for program in "$(SHIORI)" "$(SHIORI_FRONTEND)"; do \
		command -v "$$program" >/dev/null 2>&1 || { \
			printf 'Error: required command not found: %s\n' "$$program" >&2; \
			exit 1; \
		}; \
	done; \
	pids=; \
	cleanup() { \
		trap - EXIT INT TERM; \
		if [ -n "$$pids" ]; then \
			kill $$pids 2>/dev/null || :; \
			wait $$pids 2>/dev/null || :; \
		fi; \
	}; \
	trap cleanup EXIT; \
	trap 'exit 130' INT; \
	trap 'exit 143' TERM; \
	printf 'Starting draft preview at http://127.0.0.1:%s/\nCMS GraphiQL: http://127.0.0.1:%s/graphiql\nPress Ctrl-C to stop both services.\n' "$(FRONTEND_PORT)" "$(BACKEND_PORT)"; \
	"$(SHIORI)" --root "$(CURDIR)" serve \
		--bind "127.0.0.1:$(BACKEND_PORT)" \
		--public-base-url "http://127.0.0.1:$(FRONTEND_PORT)/" --graphiql --watch & \
	backend_pid=$$!; pids="$$backend_pid"; \
	BACKEND_URL="http://127.0.0.1:$(BACKEND_PORT)" \
		BLOG_URL="http://127.0.0.1:$(FRONTEND_PORT)/" \
		"$(SHIORI_FRONTEND)" draft --hostname 127.0.0.1 --port "$(FRONTEND_PORT)" & \
	frontend_pid=$$!; pids="$$pids $$frontend_pid"; \
	while kill -0 "$$backend_pid" 2>/dev/null && kill -0 "$$frontend_pid" 2>/dev/null; do \
		sleep 1; \
	done; \
	status=0; \
	if ! kill -0 "$$backend_pid" 2>/dev/null; then \
		wait "$$backend_pid" || status=$$?; \
		printf 'Error: shiori stopped (exit %s).\n' "$$status" >&2; \
	else \
		wait "$$frontend_pid" || status=$$?; \
		printf 'Error: shiori-frontend stopped (exit %s).\n' "$$status" >&2; \
	fi; \
	[ "$$status" -ne 0 ] || status=1; \
	exit "$$status"

check-tools:
	@set -eu; \
	for program in git python3 exiftool; do \
		command -v "$$program" >/dev/null 2>&1 || { \
			printf 'Error: required command not found: %s\n' "$$program" >&2; \
			exit 1; \
		}; \
	done; \
	python3 --version >/dev/null; \
	exiftool -ver >/dev/null

setup: check-tools
	@test -x .githooks/pre-commit || { printf 'Error: .githooks/pre-commit must be executable.\n' >&2; exit 1; }
	git config --local core.hooksPath .githooks
	@printf 'Enabled image metadata removal for this clone.\n'

test: check-tools
	python3 -B -m unittest discover -s tests -v
