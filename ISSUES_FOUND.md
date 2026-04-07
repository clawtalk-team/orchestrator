# Issues Found with ECS Container Provisioning

## Summary

Two critical issues preventing proper container operation:

1. **Container doesn't fetch config from DynamoDB** - Starts with empty config
2. **DynamoDB never updates to RUNNING** - No EventBridge rule to handle ECS task state changes

## Issue 1: Container Not Fetching Config from DynamoDB

### Problem

Container logs show:
```
[entrypoint] no config found, starting with empty config
2026/04/07 10:16:06.381895 [manager] LLM provider set: provider="" anthropic_key=false openai_key=false
```

### Root Cause

The container image uses **SSM-based config** but orchestrator is trying to use **DynamoDB-based config**.

**Current container (openclaw-agent):**
- Image: `826182175287.dkr.ecr.ap-southeast-2.amazonaws.com/openclaw-agent-dev:dev-834dba2`
- Entrypoint: `/entrypoint.sh` (from `docker-entrypoint.sh`)
- Fetches config from SSM Parameter Store via `SSM_CONFIG_PATH` env var OR `CLAWTALK_CONFIG` secret
- No DynamoDB integration
- No `fetch_config.py` script
- Logs: `[entrypoint] no config found, starting with empty config`

**Orchestrator expects:**
- Container should fetch config from DynamoDB
- Should use `USER_ID`, `CONTAINER_ID`, `DYNAMODB_TABLE` env vars
- Should call `fetch_config.py` to query DynamoDB
- Should write `~/.openclaw/openclaw.json` and `~/.clawtalk/clawtalk.json`

**Mismatch:**
The orchestrator's `scripts/container/entrypoint.sh` and `fetch_config.py` exist but are **not in the container image**. The container uses a different entrypoint (`docker-entrypoint.sh`) that only knows about SSM.

### Evidence

```bash
# Environment variables ARE being passed:
aws ecs describe-tasks --cluster clawtalk-dev --tasks f7ff6b2beb734019a169c701ab3bf5e9

"overrides": {
    "containerOverrides": [{
        "name": "openclaw-agent",
        "environment": [
            {"name": "USER_ID", "value": "30e9c26f-1894-4848-8e80-6c32605dad63"},
            {"name": "CONTAINER_ID", "value": "oc-b5bf016b"},
            {"name": "CONFIG_NAME", "value": "default"},
            {"name": "DYNAMODB_TABLE", "value": "openclaw-containers-dev"},
            {"name": "DYNAMODB_REGION", "value": "ap-southeast-2"}
        ]
    }]
}
```

BUT the container doesn't have the entrypoint script to use these variables.

### Solution Options

#### Option A: Update Container to Fetch from DynamoDB (Recommended)

**Pros:** True multi-tenant, per-user configs, integrates with orchestrator
**Cons:** Requires container rebuild

**Steps:**

1. **Update `Dockerfile.ecs` in openclaw-agent repo:**
   ```dockerfile
   # Install Python and boto3 for DynamoDB
   RUN apk add --no-cache python3 py3-pip aws-cli ca-certificates wget
   RUN pip3 install boto3 --break-system-packages

   # Copy DynamoDB fetch scripts from orchestrator
   COPY scripts/docker-entrypoint.sh /legacy-entrypoint.sh
   COPY --from=orchestrator scripts/container/entrypoint.sh /entrypoint.sh
   COPY --from=orchestrator scripts/container/fetch_config.py /opt/scripts/fetch_config.py
   RUN chmod +x /entrypoint.sh /opt/scripts/fetch_config.py

   ENTRYPOINT ["/entrypoint.sh"]
   ```

2. **Rebuild and push image:**
   ```bash
   cd ../openclaw-agent
   docker build -f Dockerfile.ecs -t openclaw-agent:dynamodb .
   docker tag openclaw-agent:dynamodb 826182175287.dkr.ecr.ap-southeast-2.amazonaws.com/openclaw-agent-dev:dynamodb
   docker push 826182175287.dkr.ecr.ap-southeast-2.amazonaws.com/openclaw-agent-dev:dynamodb
   ```

3. **Update task definition to use new image tag:**
   ```
   image: openclaw-agent-dev:dynamodb
   ```

4. **Remove SSM secret from task definition:**
   ```json
   "secrets": []  // Remove CLAWTALK_CONFIG secret
   ```

#### Option B: Keep SSM, Update Orchestrator to Write to SSM (Quick Fix)

**Pros:** No container changes needed
**Cons:** Creates per-container SSM parameters (less scalable)

**Steps:**

1. **Update `app/services/ecs.py` to write config to SSM before launching task:**
   ```python
   # After saving to DynamoDB, also write to SSM
   ssm_param_name = f"/openclaw-containers/{container_id}/config"

   config_json = json.dumps({
       "openclaw": openclaw_config,
       "agent": agent_config
   })

   ssm.put_parameter(
       Name=ssm_param_name,
       Value=config_json,
       Type="SecureString",
       Overwrite=True
   )

   # Add to environment overrides
   environment.append({
       "name": "SSM_CONFIG_PATH",
       "value": ssm_param_name
   })
   ```

2. **Container will fetch from SSM on startup** (existing behavior)

### Files Affected (Option A)

- `../openclaw-agent/Dockerfile.ecs` - add Python, boto3, fetch_config.py
- `../openclaw-agent/scripts/docker-entrypoint.sh` - maybe keep as fallback
- Orchestrator scripts - copy to openclaw-agent repo
- Task definition - remove SSM secret
- Container image - rebuild and push

---

## Issue 2: DynamoDB Never Updates to RUNNING

### Problem

DynamoDB record stays `status=PENDING` forever even though ECS task reaches `RUNNING` state.

API shows:
```
GET /containers/oc-b5bf016b
{
  "status": "PENDING",
  "health_status": "UNKNOWN",
  "ip_address": null
}
```

But AWS Console shows task is RUNNING with IP `10.10.10.61`.

### Root Cause

**No EventBridge rule exists** to trigger the Lambda function when ECS tasks change state.

```bash
aws events list-rules --name-prefix "openclaw"
{
  "Rules": []  # Empty!
}
```

The Lambda function (`lambda_handler.py`) has the code to handle EventBridge events:

```python
def handler(event, context):
    # Check if this is an EventBridge event
    if event.get("source") == "aws.ecs":
        # Handle ECS task state change events
        handle_task_event(event)
        return {"statusCode": 200, "body": "Event processed"}
```

But without an EventBridge rule, this code never runs.

### Solution

Create an EventBridge rule to capture ECS task state changes:

```json
{
  "source": ["aws.ecs"],
  "detail-type": ["ECS Task State Change"],
  "detail": {
    "clusterArn": ["arn:aws:ecs:ap-southeast-2:826182175287:cluster/clawtalk-dev"],
    "lastStatus": ["RUNNING", "STOPPED"]
  }
}
```

Target: Orchestrator Lambda function

### Terraform Example

```hcl
resource "aws_cloudwatch_event_rule" "ecs_task_state_change" {
  name        = "orchestrator-ecs-task-state-change"
  description = "Capture ECS task state changes for orchestrator"

  event_pattern = jsonencode({
    source      = ["aws.ecs"]
    detail-type = ["ECS Task State Change"]
    detail = {
      clusterArn = [aws_ecs_cluster.main.arn]
      lastStatus = ["RUNNING", "STOPPED"]
    }
  })
}

resource "aws_cloudwatch_event_target" "lambda" {
  rule      = aws_cloudwatch_event_rule.ecs_task_state_change.name
  target_id = "OrchestratorLambda"
  arn       = aws_lambda_function.orchestrator.arn
}

resource "aws_lambda_permission" "allow_eventbridge" {
  statement_id  = "AllowExecutionFromEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.orchestrator.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.ecs_task_state_change.arn
}
```

### Files Affected

- Infrastructure code (Terraform/CloudFormation) for EventBridge rule
- Lambda permissions to allow EventBridge invocation

---

## Current State

### What's Working ✓

- User creation in auth-gateway
- API key validation
- Container creation API call
- ECS task launching successfully
- Task reaches RUNNING state in ECS
- Environment variables are passed correctly via overrides
- Tags are set correctly on tasks
- Container health endpoint responds

### What's Broken ✗

- Container doesn't fetch config from DynamoDB
- Container starts with empty config (no LLM provider, no auth gateway URL)
- DynamoDB never updates from PENDING to RUNNING
- No IP address or health endpoint in DynamoDB
- Health check system can't work (no endpoints in DB)

---

## Impact

Without these fixes:

1. **Containers are non-functional** - No LLM config, can't process requests
2. **Health monitoring broken** - Orchestrator doesn't know task IP addresses
3. **Billing/tracking broken** - Can't tell which containers are actually running
4. **Cleanup impossible** - Can't map DynamoDB records to actual ECS tasks

---

## Fix Priority

**Critical (must fix immediately):**
1. Update task definition to use entrypoint that fetches config
2. Create EventBridge rule to update DynamoDB on state changes

**Without these, the entire orchestration system doesn't work.**

---

## Verification Steps

After fixes are deployed:

1. **Test config fetch:**
   ```bash
   # Create new container
   POST /containers

   # Check logs
   aws logs tail /ecs/openclaw-agent-dev --follow

   # Should see:
   # [entrypoint] Fetching configuration from DynamoDB...
   # [entrypoint] ✓ Configuration files created successfully
   ```

2. **Test DynamoDB updates:**
   ```bash
   # Wait 30 seconds after task starts

   # Check DynamoDB
   GET /containers/{container_id}

   # Should show:
   # "status": "RUNNING"
   # "ip_address": "10.x.x.x"
   # "health_endpoint": "http://10.x.x.x:8080/health"
   ```

3. **Test end-to-end:**
   ```bash
   python scripts/test_end_to_end_flow.py
   # Should complete successfully with RUNNING container
   ```
