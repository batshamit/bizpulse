# BizPulse — local + remote dev shortcuts.
# Local targets assume a venv in .venv (Linux/macOS) or .venv\Scripts on Windows.
# `remote-*` targets shell into the GPU server and run there.

PY            ?= python3.10
VENV          ?= .venv
SERVER        ?= amit@exam.dei.ac.in
REMOTE_DIR    ?= /raid/amit/mylearning/bizpulse
SSH           ?= ssh -o BatchMode=yes
SSH_RUN        = $(SSH) $(SERVER) 'export TERM=dumb; cd $(REMOTE_DIR) &&'

.DEFAULT_GOAL := help

.PHONY: help
help:
	@echo "BizPulse make targets"
	@echo "  setup            create local venv and install dev deps"
	@echo "  fmt              ruff format + black"
	@echo "  lint             ruff + mypy"
	@echo "  test             pytest"
	@echo "  api              run FastAPI locally (no GPU needed)"
	@echo ""
	@echo "Remote (server) targets:"
	@echo "  remote-sync      rsync local repo -> server (excludes .venv, data, .cache)"
	@echo "  remote-pull      git pull on server"
	@echo "  remote-install   pip install -e .[dev] in server venv"
	@echo "  remote-api       run FastAPI on server (loopback only)"
	@echo "  remote-status    nvidia-smi + ports + service health on server"
	@echo "  remote-tunnel    forward server ports 6333,8080,8800,8081,8082 to localhost"
	@echo ""
	@echo "  ports            print port assignments"
	@echo "  health           curl health endpoints (assumes tunnel)"

.PHONY: setup
setup:
	$(PY) -m venv $(VENV)
	$(VENV)/bin/pip install -U pip wheel setuptools
	$(VENV)/bin/pip install -e ".[dev]"

.PHONY: fmt
fmt:
	$(VENV)/bin/ruff check --fix .
	$(VENV)/bin/black .

.PHONY: lint
lint:
	$(VENV)/bin/ruff check .
	$(VENV)/bin/mypy src

.PHONY: test
test:
	$(VENV)/bin/pytest

.PHONY: api
api:
	$(VENV)/bin/uvicorn bizpulse.api.main:app --reload --port 8080

# ----- remote -----

.PHONY: remote-sync
remote-sync:
	rsync -avz --delete \
	  --exclude=.git --exclude=.venv --exclude=data --exclude=.cache \
	  --exclude=__pycache__ --exclude="*.egg-info" --exclude=.pytest_cache \
	  ./ $(SERVER):$(REMOTE_DIR)/

.PHONY: remote-pull
remote-pull:
	$(SSH_RUN) git pull --ff-only

.PHONY: remote-install
remote-install:
	$(SSH_RUN) .venv/bin/pip install -e ".[dev]"

.PHONY: remote-api
remote-api:
	$(SSH_RUN) .venv/bin/uvicorn bizpulse.api.main:app --host 127.0.0.1 --port 8080

.PHONY: remote-status
remote-status:
	$(SSH_RUN) bash scripts/status.sh

.PHONY: remote-tunnel
remote-tunnel:
	$(SSH) -N \
	  -L 6333:127.0.0.1:6333 \
	  -L 8080:127.0.0.1:8080 \
	  -L 8800:127.0.0.1:8800 \
	  -L 8081:127.0.0.1:8081 \
	  -L 8082:127.0.0.1:8082 \
	  $(SERVER)

.PHONY: ports
ports:
	@echo "vLLM (LLM)            8800"
	@echo "TEI embeddings        8081"
	@echo "TEI reranker          8082"
	@echo "Qdrant                6333"
	@echo "Postgres              5432  (or 5433 if running our own instance)"
	@echo "FastAPI               8080"

.PHONY: health
health:
	@curl -fsS http://127.0.0.1:6333/healthz && echo " qdrant OK"
	@curl -fsS http://127.0.0.1:8800/v1/models | head -c 200 && echo " vllm OK"
	@curl -fsS http://127.0.0.1:8081/health && echo " tei-embed OK"
	@curl -fsS http://127.0.0.1:8082/health && echo " tei-rerank OK"
	@curl -fsS http://127.0.0.1:8080/healthz && echo " bizpulse-api OK"

.PHONY: demo
demo:
	@bash scripts/demo.sh

.PHONY: eval
eval:
	@$(VENV)/bin/python -m bizpulse.eval.cli --mock 2>/dev/null || \
		echo "(eval CLI not yet implemented — see scripts/run_eval.py for the manual invocation)"
