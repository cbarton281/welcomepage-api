#!/bin/bash

BRANCH="$VERCEL_GIT_COMMIT_REF"

if [ "$BRANCH" = "main" ] || [ "$BRANCH" = "staging" ]; then
  # allow build
  exit 1
else
  # ignore all other branches
  echo "Skipping build for branch: $BRANCH"
  exit 0
fi
