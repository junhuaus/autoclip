SHELL := /bin/bash

UV ?= uv
PYTHON_VERSION ?= 3.12
PROJECT_ROOT := $(abspath .)
UV_CACHE_DIR_LOCAL := $(PROJECT_ROOT)/.cache/uv
UV_PYTHON_DIR_LOCAL := $(PROJECT_ROOT)/.python
NPM_CACHE_DIR_LOCAL := $(PROJECT_ROOT)/.cache/npm
VENV_BIN := $(PROJECT_ROOT)/.venv/bin
NODE_LTS_BIN ?= /usr/local/bin
UV_ENV := UV_CACHE_DIR=$(UV_CACHE_DIR_LOCAL) UV_PYTHON_INSTALL_DIR=$(UV_PYTHON_DIR_LOCAL)

.PHONY: setup doctor dev lint test e2e schema demo smoke-cloud clean-demo

setup:
	@command -v $(UV) >/dev/null || { echo "uv is required: https://docs.astral.sh/uv/"; exit 1; }
	@mkdir -p "$(UV_CACHE_DIR_LOCAL)" "$(UV_PYTHON_DIR_LOCAL)" data/demo data/projects
	$(UV_ENV) $(UV) python install $(PYTHON_VERSION) --no-bin
	$(UV_ENV) $(UV) sync --python $(PYTHON_VERSION) --managed-python --all-groups
	@if [ -f apps/web/package-lock.json ]; then PATH="$(NODE_LTS_BIN):$$PATH" npm_config_cache="$(NPM_CACHE_DIR_LOCAL)" npm ci --prefix apps/web --ignore-scripts; fi
	@"$(VENV_BIN)/python" -c 'import platform, sys; assert sys.version_info >= (3, 11); assert platform.machine() == "arm64", platform.machine(); print("Python", platform.python_version(), platform.machine())'
	@"$(VENV_BIN)/python" -c 'from liveclip.db.engine import assert_supported_sqlite_runtime; r = assert_supported_sqlite_runtime(); print("SQLite", ".".join(map(str, r.version)), "WAL-safe")'

doctor:
	@PATH="$(NODE_LTS_BIN):$$PATH" "$(VENV_BIN)/liveclip" doctor

dev:
	@./scripts/dev.sh

lint:
	@"$(VENV_BIN)/ruff" check src tests scripts
	@"$(VENV_BIN)/ruff" format --check src tests scripts
	@"$(VENV_BIN)/mypy" src/liveclip scripts
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

clean-demo:
	@"$(VENV_BIN)/liveclip" clean-demo
