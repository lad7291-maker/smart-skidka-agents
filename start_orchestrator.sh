#!/bin/bash
cd /opt/smart-skidka-agents
export PYTHONPATH=/opt/smart-skidka-agents
exec .venv/bin/python scripts/orchestrator.py >> logs/orchestrator.out 2>> logs/orchestrator.err
