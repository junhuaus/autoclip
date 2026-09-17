SHELL := /bin/bash

UV ?= uv
PYTHON_VERSION ?= 3.12
PROJECT_ROOT := $(abspath .)
UV_CACHE_DIR_LOCAL := $(PROJECT_ROOT)/.cache/uv
UV_PYTHON_DIR_LOCAL := $(PROJECT_ROOT)/.python
NPM_CACHE_DIR_LOCAL := $(PROJECT_ROOT)/.cache/npm
TIKTOKEN_CACHE_DIR ?= $(PROJECT_ROOT)/.cache/tiktoken
export TIKTOKEN_CACHE_DIR
PLAYWRIGHT_BROWSERS_PATH ?= $(PROJECT_ROOT)/.cache/playwright
export PLAYWRIGHT_BROWSERS_PATH
VENV_BIN := $(PROJECT_ROOT)/.venv/bin
NODE_LTS_BIN ?= /usr/local/bin
UV_ENV := UV_CACHE_DIR=$(UV_CACHE_DIR_LOCAL) UV_PYTHON_INSTALL_DIR=$(UV_PYTHON_DIR_LOCAL)

.PHONY: setup setup-local-asr doctor dev lint test e2e schema demo smoke-cloud smoke-codex smoke-openrouter smoke-mlx clean-demo loop-doctor loop-profiles loop-init loop-run loop-status start-codex resume-codex

setup:
	@command -v $(UV) >/dev/null || { echo "uv is required: https://docs.astral.sh/uv/"; exit 1; }
	@mkdir -p "$(UV_CACHE_DIR_LOCAL)" "$(UV_PYTHON_DIR_LOCAL)" data/demo data/projects
	$(UV_ENV) $(UV) python install $(PYTHON_VERSION) --no-bin
	$(UV_ENV) $(UV) sync --python $(PYTHON_VERSION) --managed-python --all-groups
	@"$(VENV_BIN)/python" -m tools.loop_engineering.tokenizer_cache
	@if [ -f apps/web/package-lock.json ]; then PATH="$(NODE_LTS_BIN):$$PATH" npm_config_cache="$(NPM_CACHE_DIR_LOCAL)" npm ci --prefix apps/web --ignore-scripts; fi
	@PLAYWRIGHT_BROWSERS_PATH="$(PROJECT_ROOT)/.cache/playwright" "$(NODE_LTS_BIN)/node" apps/web/node_modules/playwright/cli.js install ffmpeg
	@"$(VENV_BIN)/python" -c 'import platform, sys; assert sys.version_info >= (3, 11); assert platform.machine() == "arm64", platform.machine(); print("Python", platform.python_version(), platform.machine())'
	@"$(VENV_BIN)/python" -c 'from liveclip.db.engine import assert_supported_sqlite_runtime; r = assert_supported_sqlite_runtime(); print("SQLite", ".".join(map(str, r.version)), "WAL-safe")'

setup-local-asr:
	@mkdir -p "$(UV_CACHE_DIR_LOCAL)" "$(UV_PYTHON_DIR_LOCAL)" data/models
	$(UV_ENV) $(UV) sync --python $(PYTHON_VERSION) --managed-python --all-groups --extra local-asr
	@"$(VENV_BIN)/python" scripts/setup_mlx_asr.py

doctor:
	@PATH="$(NODE_LTS_BIN):$$PATH" "$(VENV_BIN)/liveclip" doctor

dev:
	@./scripts/dev.sh

lint:
	@"$(VENV_BIN)/ruff" check src tests scripts tools
	@"$(VENV_BIN)/ruff" format --check src tests scripts tools
	@"$(VENV_BIN)/mypy" src/liveclip scripts tools/loop_engineering
	@"$(VENV_BIN)/python" scripts/export_edit_plan_schema.py --check
	@if [ -f apps/web/package-lock.json ]; then PATH="$(NODE_LTS_BIN):$$PATH" npm run typecheck --prefix apps/web; fi

test:
	@if [ -f apps/web/package-lock.json ]; then ./scripts/check_test_browser.sh; fi
	@"$(VENV_BIN)/pytest"
	@if [ -f apps/web/package-lock.json ]; then PATH="$(NODE_LTS_BIN):$$PATH" npm run test:run --prefix apps/web; fi
	@if [ -f apps/web/package-lock.json ]; then PATH="$(NODE_LTS_BIN):$$PATH" npm run e2e --prefix apps/web; fi

e2e:
	@./scripts/check_test_browser.sh
	@PATH="$(NODE_LTS_BIN):$$PATH" npm run e2e --prefix apps/web

schema:
	@"$(VENV_BIN)/python" scripts/export_edit_plan_schema.py --write

demo:
	@"$(VENV_BIN)/liveclip" demo

smoke-cloud:
	@test -n "$(INPUT)" || { echo 'INPUT=/absolute/path/to/short.mp4 is required'; exit 2; }
	@"$(VENV_BIN)/liveclip" smoke-cloud --input "$(INPUT)"

smoke-codex:
	@"$(VENV_BIN)/liveclip" smoke-codex

smoke-openrouter:
	@test -n "$(INPUT)" || { echo 'INPUT=/absolute/path/to/short.mp4 is required'; exit 2; }
	@"$(VENV_BIN)/liveclip" smoke-openrouter --input "$(INPUT)"

smoke-mlx:
	@test -n "$(INPUT)" || { echo 'INPUT=/absolute/path/to/media is required'; exit 2; }
	@"$(VENV_BIN)/python" scripts/smoke_mlx_asr.py --input "$(INPUT)" --start-seconds "$(or $(START),0)" --duration-seconds "$(or $(DURATION),30)"

clean-demo:
	@"$(VENV_BIN)/liveclip" clean-demo

loop-doctor:
	@"$(VENV_BIN)/python" -m tools.loop_engineering doctor

loop-profiles:
	@"$(VENV_BIN)/python" -m tools.loop_engineering install-profiles

loop-init:
	@test -n "$(REQUIREMENT)" || { echo 'REQUIREMENT=docs/requirements/name.md is required'; exit 2; }
	@"$(VENV_BIN)/python" -m tools.loop_engineering init "$(REQUIREMENT)"

loop-run:
	@if [ -n "$(RUN_ID)" ]; then \
		"$(VENV_BIN)/python" -m tools.loop_engineering run --run-id "$(RUN_ID)"; \
	elif [ -n "$(REQUIREMENT)" ]; then \
		"$(VENV_BIN)/python" -m tools.loop_engineering run --requirement "$(REQUIREMENT)"; \
	else \
		echo 'RUN_ID=... or REQUIREMENT=docs/requirements/name.md is required'; exit 2; \
	fi

loop-status:
	@test -n "$(RUN_ID)" || { echo 'RUN_ID=... is required'; exit 2; }
	@"$(VENV_BIN)/python" -m tools.loop_engineering status "$(RUN_ID)"

start-codex:
	@./scripts/start_codex.sh

resume-codex:
	@CODEX_SESSION_ID="$(SESSION_ID)" ./scripts/resume_codex.sh
