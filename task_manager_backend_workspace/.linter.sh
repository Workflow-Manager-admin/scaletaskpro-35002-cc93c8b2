#!/bin/bash
cd /home/kavia/workspace/code-generation/scaletaskpro-35002-cc93c8b2/task_manager_backend_workspace/task_manager_backend
source venv/bin/activate
flake8 .
LINT_EXIT_CODE=$?
if [ $LINT_EXIT_CODE -ne 0 ]; then
  exit 1
fi

