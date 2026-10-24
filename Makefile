orchestrator:
	python -m agents.orchestrator.agent

planner:
	python -m agents.planner.agent

settlement:
	python -m agents.settlement.agent

test:
	python -m pytest -q

addresses:
	python -m scripts.print_addresses
