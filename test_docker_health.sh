#!/bin/bash
set -e

# Test that git SHA is correctly baked into Docker image and returned by /health endpoint

CURRENT_SHA=$(git rev-parse --short HEAD)
IMAGE_NAME="orchestrator-health-test:$CURRENT_SHA"
CONTAINER_NAME="orchestrator-health-test"
PORT=9999

# Cleanup function
cleanup() {
  echo "==> Cleaning up"
  docker stop $CONTAINER_NAME 2>/dev/null || true
  docker rm $CONTAINER_NAME 2>/dev/null || true
}

# Set trap to cleanup on exit
trap cleanup EXIT

echo "==> Building Docker image with GIT_COMMIT=$CURRENT_SHA"
docker build \
  --build-arg GIT_COMMIT=$CURRENT_SHA \
  -f Dockerfile \
  -t $IMAGE_NAME \
  .

echo "==> Verifying GIT_COMMIT is baked into image"
BAKED_SHA=$(docker inspect $IMAGE_NAME --format='{{range .Config.Env}}{{println .}}{{end}}' | grep '^GIT_COMMIT=' | cut -d'=' -f2)
if [ "$BAKED_SHA" != "$CURRENT_SHA" ]; then
  echo "❌ FAILED: GIT_COMMIT in image ($BAKED_SHA) doesn't match expected ($CURRENT_SHA)"
  exit 1
fi
echo "✓ GIT_COMMIT correctly baked into image: $BAKED_SHA"

echo "==> Starting container on port $PORT"
docker run -d --name $CONTAINER_NAME -p $PORT:8571 $IMAGE_NAME

# Wait for container to be healthy with retry loop
echo "==> Waiting for container to be ready"
MAX_RETRIES=30
RETRY_COUNT=0
while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
  if curl -sf http://localhost:$PORT/health > /dev/null 2>&1; then
    echo "✓ Container is ready"
    break
  fi
  RETRY_COUNT=$((RETRY_COUNT + 1))
  if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
    echo "❌ FAILED: Container did not become ready within 30 seconds"
    docker logs $CONTAINER_NAME
    exit 1
  fi
  sleep 1
done

echo "==> Testing /health endpoint"
RESPONSE=$(curl -s http://localhost:$PORT/health)
RETURNED_SHA=$(echo $RESPONSE | python3 -c "import sys, json; print(json.load(sys.stdin).get('git_sha', 'null'))")

echo "==> Response: $RESPONSE"

# Verify
if [ "$RETURNED_SHA" = "$CURRENT_SHA" ]; then
  echo "✅ SUCCESS: /health endpoint returned correct git_sha: $RETURNED_SHA"
  exit 0
else
  echo "❌ FAILED: Expected git_sha=$CURRENT_SHA, got git_sha=$RETURNED_SHA"
  exit 1
fi
