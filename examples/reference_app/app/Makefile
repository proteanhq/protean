# Convenience targets for the reference application.
# Run from this directory (examples/reference_app/app).

.PHONY: install run compose-up compose-down

install:  ## Install the runtime dependencies.
	pip install -r requirements.txt

run:  ## Run the app on the clean-clone path (SQLite + inline broker).
	cd .. && uvicorn app.api:app --reload

compose-up:  ## Start the optional PostgreSQL + Redis services.
	docker-compose up -d

compose-down:  ## Stop the optional services.
	docker-compose down
