PYTHON ?= .venv/bin/python
SITE_DIR ?= frontend/dist
LAYER_DIR ?= build/layer
# The CDK CLI pinned in package-lock.json (`make install` runs npm ci).
CDK ?= npx --no-install cdk

.PHONY: install check lint test audit frontend privacy lock layer synth diff clean

install:            ## Create the virtualenv and install everything (uv if installed, else pip)
	if command -v uv >/dev/null; then \
		uv venv --seed --allow-existing --python python3.14 .venv && uv pip install --python $(PYTHON) --require-hashes -r requirements-dev.txt && uv pip install --python $(PYTHON) --require-hashes --no-deps -r layer/requirements.txt && uv pip check --python $(PYTHON); \
	else \
		python3.14 -m venv .venv && $(PYTHON) -m pip install --upgrade pip && $(PYTHON) -m pip install --require-hashes -r requirements-dev.txt && $(PYTHON) -m pip install --require-hashes --no-deps -r layer/requirements.txt && $(PYTHON) -m pip check; \
	fi
	npm ci --ignore-scripts --no-audit --no-fund  # the CDK CLI and pyright
	npm ci --prefix frontend --ignore-scripts --no-audit --no-fund  # the PWA and its tools

check:              ## Everything CI checks, locally (synth uses a stand-in app, like CI)
	$(MAKE) privacy lint test frontend audit
	$(MAKE) synth SITE_DIR=tests/fixtures/site LAYER_DIR=tests/fixtures/layer

lint:               ## Python: ruff (with Bandit security rules) and pyright types
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .
	npx --no-install pyright

test:
	$(PYTHON) -m pytest -n auto

audit:              ## Check dependencies for known vulnerabilities
	$(PYTHON) -m pip_audit --require-hashes --disable-pip -r requirements-dev.txt
	$(PYTHON) -m pip_audit --require-hashes --disable-pip -r layer/requirements.txt  # what ships

frontend:           ## PWA: ESLint, TypeScript types, Vitest, Vite build and the size limit
	cd frontend && npm run -s lint && npm run -s typecheck && npm run -s test && npm run -s build
	scripts/check_size.sh frontend/dist
	! grep -rnEi '#[0-9a-f]{3,8}\b|rgba?\(' frontend/src --include='*.tsx' --include='*.ts' || (echo 'Colours belong in styles.css tokens' && exit 1)
	! grep -rlE 'mockData|/\?mock' frontend/dist || (echo 'Demo data leaked into the build' && exit 1)

privacy:            ## Fail on personal data (emails, account IDs, data exports) in tracked files (public repo)
	scripts/check_personal_data.sh

lock:               ## Regenerate the hashed lockfiles (CDK app, dev tools, Lambda layer) from the .in files
	for d in requirements requirements-dev; do $(PYTHON) -m piptools compile --quiet --generate-hashes --allow-unsafe \
		--strip-extras --no-emit-index-url --output-file=$$d.txt $$d.in; done
	cd layer && ../$(PYTHON) -m piptools compile --quiet --generate-hashes --allow-unsafe --strip-extras \
		--no-emit-index-url --output-file=requirements.txt requirements.in
	sed -i.bak 's/ --no-index//' layer/requirements.txt && rm layer/requirements.txt.bak

layer:              ## Build the Lambda layer (arm64, Python 3.14) from the lockfile
	PYTHON=$(PYTHON) scripts/build_layer.sh

synth:              ## Synthesize CloudFormation and run cdk-nag security checks
	. .venv/bin/activate && $(CDK) synth --quiet -c siteDir=$(SITE_DIR) -c layerDir=$(LAYER_DIR)

diff:
	. .venv/bin/activate && $(CDK) diff

clean:
	rm -rf build cdk.out .pytest_cache .ruff_cache .coverage
