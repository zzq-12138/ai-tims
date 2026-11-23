#!/usr/bin/env bash
set -e
export PATH=/home/dev/node/bin:$PATH
cd /home/dev/ai-tims/ai-tims-front
node -v
npm -v
npm run build
