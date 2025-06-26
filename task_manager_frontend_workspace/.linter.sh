#!/bin/bash
cd /home/kavia/workspace/code-generation/scaletaskpro-35002-cc93c8b2/task_manager_frontend_workspace/task_manager_frontend
npm run build
EXIT_CODE=$?
if [ $EXIT_CODE -ne 0 ]; then
   exit 1
fi

