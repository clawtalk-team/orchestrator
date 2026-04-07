# OpenClaw Container Orchestrator - Architecture Plan

**Created:** 2026-04-04  
**Status:** Planning Phase  
**Owner:** Max (iOS Developer Agent)

---

## Executive Summary

Build a REST API service to manage the lifecycle of OpenClaw agent containers running in AWS ECS. The service will handle:

- **Container Lifecycle**: Spin up/down openclaw-agent ECS tasks on demand
- **User Mapping**: Maintain a DynamoDB record of which containers belong to which users
- **Configuration Management**: Inject user-specific configuration into containers via SSM Parameter Store
- **Authentication**: Secure API with token-based auth (via auth-gateway)
- **State Tracking**: Monitor container status via ECS events + direct health probes
- **Health Monitoring**: Direct HTTP probes to openclaw-agent `/health` endpoint for real application health

### Key Design Decisions

**Health Monitoring Strategy:**
- Each container exposes openclaw-agent HTTP API on port 8080
- DynamoDB stores: `ip_address`, `port`, `health_endpoint`, `api_endpoint`
- Orchestrator Lambda runs in VPC to reach private container IPs
- Periodic health checks (every 1 minute) probe `GET /health`
- Returns detailed health: agent count, uptime, memory, version
- On-demand health checks via `GET /containers/{id}/health` API

**Why direct health probes:**
- ✅ Real application health, not just container liveness
- ✅ Detailed metrics (running agents, resource usage)
- ✅ Faster failure detection
- ✅ Reuses existing openclaw-agent `/health` endpoint
- ⚠️ Requires Lambda in VPC (adds slight complexity)

---

## Architecture Overview

### System Context

```
┌─────────────┐
│ Flutter App │
└──────┬──────┘
       │ HTTPS
       ▼
┌──────────────────┐      ┌──────────────┐
│  Orchestrator    │◄────►│ DynamoDB     │
│  (API Gateway +  │      │ - User Map   │
│   Lambda/Fargate)│      │ - Container  │
└────────┬─────────┘      │   Metadata   │
         │                └──────────────┘
         │ ECS RunTask
         ▼
┌──────────────────┐
│  ECS Cluster     │
│  ┌────────────┐  │
│  │ openclaw-  │  │
│  │   agent    │  │
│  │ container  │  │
│  └────────────┘  │
└──────────────────┘
```

### Service Architecture

**API Gateway + Lambda** (Serverless - matches auth-gateway)
- ✅ Lower cost for sporadic usage
- ✅ Automatic scaling
- ✅ No infrastructure management
- ✅ Consistent with auth-gateway deployment pattern
- ⚠️ Cold start latency (~1-2s for first request)
- ⚠️ 15-minute Lambda timeout (acceptable - ECS RunTask is async)

**Why Lambda:**
- Container orchestration is event-driven, not always-on
- RunTask/StopTask operations complete in <5 seconds
- Matches existing auth-gateway Lambda deployment
- Minimal baseline cost (pay-per-request)
- 15-minute timeout is sufficient (container creation is async)

---

## Data Model

### DynamoDB Tables

#### Table: `openclaw-containers-{env}`

**Primary Key:**
- `PK`: `USER#{user_uuid}`
- `SK`: `CONTAINER#{container_id}`

**Attributes:**

```json
{
  "pk": "USER#275aa927-1234-5678-abcd-ef1234567890",
  "sk": "CONTAINER#ecs-task-123abc",
  "user_uuid": "275aa927-1234-5678-abcd-ef1234567890",
  "container_id": "ecs-task-123abc",
  "task_arn": "arn:aws:ecs:ap-southeast-2:...:task/clawtalk-dev/abc123",
  "status": "RUNNING",
  "health_status": "HEALTHY",
  "created_at": "2026-04-04T01:58:00Z",
  "updated_at": "2026-04-04T01:58:00Z",
  "last_health_check": "2026-04-04T02:05:00Z",
  "config_ssm_path": "/openclaw-containers/dev/ecs-task-123abc/config",
  "ip_address": "10.0.1.45",
  "port": 8080,
  "health_endpoint": "http://10.0.1.45:8080/health",
  "api_endpoint": "http://10.0.1.45:8080",
  "ecs_cluster": "clawtalk-dev",
  "ttl": 1714867200
}
```

**GSI: StatusIndex**
- `PK`: `STATUS#{status}`
- `SK`: `created_at`
- Use case: List all RUNNING containers, or find stale/failed containers

**GSI: TaskArnIndex** (optional)
- `PK`: `TASK_ARN#{task_arn}`
- Use case: Reverse lookup from ECS event to user

#### Table: `openclaw-container-config-{env}` (optional alternative)

If we want to separate config from metadata:

**Primary Key:**
- `PK`: `CONTAINER#{container_id}`
- `SK`: `CONFIG`

**Attributes:**

```json
{
  "pk": "CONTAINER#ecs-task-123abc",
  "sk": "CONFIG",
  "config_json": "{...encrypted...}",
  "version": 2,
  "updated_at": "2026-04-04T02:00:00Z"
}
```

**Decision:** Start with single table approach - simpler queries, less cross-table joins.

---

## API Design

### Authentication

**Method:** Bearer Token (User API Key from auth-gateway)

```http
Authorization: Bearer sk_live_abc123...
```

**Validation Flow:**
1. Extract token from `Authorization` header
2. Call auth-gateway `GET /auth` with token
3. Receive `user_uuid`
4. Proceed with request

**Error Responses:**
- `401 Unauthorized`: Invalid/missing token
- `403 Forbidden`: User doesn't have permission for this container

---

### Endpoints

#### 1. **Spin Up Container**

```http
POST /containers
Authorization: Bearer {user_api_key}
Content-Type: application/json

{
  "openclaw_url": "http://localhost:18789",
  "openclaw_token": "your-token",
  "openclaw_model": "claude-3-haiku-20240307",
  "llm_provider": "anthropic",
  "anthropic_api_key": "sk-ant-...",
  "agents": []
}
```

**Response:**

```json
{
  "container_id": "ecs-task-123abc",
  "task_arn": "arn:aws:ecs:...",
  "status": "PROVISIONING",
  "created_at": "2026-04-04T02:00:00Z",
  "endpoint": "http://10.0.1.45:8080"
}
```

**Process:**
1. Validate user token → get `user_uuid`
2. Generate unique `container_id` (or use ECS task ID)
3. Create config JSON with user-provided values
4. Encrypt sensitive fields (API keys, tokens)
5. Store config in SSM Parameter Store: `/openclaw-containers/{env}/{container_id}/config`
6. Call ECS `RunTask` with:
   - Task Definition: `openclaw-agent-{env}`
   - Cluster: `clawtalk-{env}`
   - Environment override: `CLAWTALK_CONFIG_SSM_PATH=/openclaw-containers/{env}/{container_id}/config`
7. Write record to DynamoDB
8. Return response immediately (async provisioning)

---

#### 2. **List Containers**

```http
GET /containers
Authorization: Bearer {user_api_key}
```

**Response:**

```json
{
  "containers": [
    {
      "container_id": "ecs-task-123abc",
      "status": "RUNNING",
      "created_at": "2026-04-04T02:00:00Z",
      "ip_address": "10.0.1.45",
      "endpoint": "http://10.0.1.45:8080",
      "agents": [
        {"agent_id": "agent-1", "name": "Assistant"}
      ]
    }
  ]
}
```

**Process:**
1. Validate token → get `user_uuid`
2. Query DynamoDB: `PK = USER#{user_uuid}, SK begins_with CONTAINER#`
3. For each container, optionally fetch live status from ECS `DescribeTasks`
4. Return list

---

#### 3. **Get Container Details**

```http
GET /containers/{container_id}
Authorization: Bearer {user_api_key}
```

**Response:**

```json
{
  "container_id": "ecs-task-123abc",
  "user_uuid": "275aa927-...",
  "status": "RUNNING",
  "health_status": "HEALTHY",
  "created_at": "2026-04-04T02:00:00Z",
  "updated_at": "2026-04-04T02:05:00Z",
  "last_health_check": "2026-04-04T02:06:00Z",
  "task_arn": "arn:aws:ecs:...",
  "ip_address": "10.0.1.45",
  "port": 8080,
  "api_endpoint": "http://10.0.1.45:8080",
  "health_endpoint": "http://10.0.1.45:8080/health",
  "health_data": {
    "agents_running": 2,
    "uptime_seconds": 360,
    "memory_mb": 256,
    "version": "0.1.0"
  },
  "config": {
    "openclaw_url": "http://localhost:18789",
    "openclaw_model": "claude-3-haiku-20240307"
  }
}
```

**Process:**
1. Validate token → get `user_uuid`
2. Query DynamoDB: `PK = USER#{user_uuid}, SK = CONTAINER#{container_id}`
3. Verify ownership (PK matches user)
4. Optionally query ECS for live task status
5. Return details

---

#### 4. **Stop Container**

```http
DELETE /containers/{container_id}
Authorization: Bearer {user_api_key}
```

**Response:**

```json
{
  "container_id": "ecs-task-123abc",
  "status": "STOPPING",
  "stopped_at": "2026-04-04T03:00:00Z"
}
```

**Process:**
1. Validate token → get `user_uuid`
2. Query DynamoDB to verify ownership
3. Call ECS `StopTask`
4. Update DynamoDB status to `STOPPING`
5. Delete SSM config parameter
6. Set TTL for DynamoDB record (delete after 7 days)
7. Return response

---

#### 5. **Get Container Health** (new endpoint)

```http
GET /containers/{container_id}/health
Authorization: Bearer {user_api_key}
```

**Response:**

```json
{
  "container_id": "ecs-task-123abc",
  "health_status": "HEALTHY",
  "last_check": "2026-04-04T02:06:00Z",
  "health_data": {
    "agents_running": 2,
    "uptime_seconds": 360,
    "memory_mb": 256,
    "cpu_percent": 12.5,
    "version": "0.1.0",
    "agents": [
      {
        "agent_id": "agent-1",
        "name": "Assistant",
        "status": "connected"
      },
      {
        "agent_id": "agent-2",
        "name": "Helper",
        "status": "connected"
      }
    ]
  },
  "endpoint": {
    "api": "http://10.0.1.45:8080",
    "health": "http://10.0.1.45:8080/health"
  }
}
```

**Process:**
1. Validate token → get `user_uuid`
2. Query DynamoDB to verify ownership and get `health_endpoint`
3. Perform immediate health probe to `http://{ip}:{port}/health`
4. Update DynamoDB with latest health data
5. Return health status + detailed metrics

**Use Case:**
- Flutter app can poll this before connecting to verify container is ready
- Debugging: check why agents aren't connecting
- Monitoring: track agent count, resource usage

---

#### 6. **Update Container Config** (optional, future)

```http
PATCH /containers/{container_id}/config
Authorization: Bearer {user_api_key}

{
  "agents": [
    {"agent_id": "new-agent", "name": "New Agent"}
  ]
}
```

**Process:**
1. Validate ownership
2. Update SSM parameter with new config
3. Trigger openclaw-agent hot-reload (if supported)
4. Update DynamoDB metadata
5. Return updated config

---

#### 7. **Health Check (Service)**

```http
GET /health
```

**Response:**

```json
{
  "status": "healthy",
  "version": "0.1.0",
  "timestamp": "2026-04-04T02:00:00Z"
}
```

---

## Security Model

### Encryption

**At Rest:**
- DynamoDB: Encrypted with AWS KMS (default)
- SSM Parameter Store: SecureString type with KMS encryption
- Sensitive config fields: Additional application-level encryption before storing

**In Transit:**
- HTTPS for all API endpoints (via ALB with ACM certificate)
- TLS 1.2+ enforced

### Secrets Management

**User-provided secrets** (API keys, tokens):
1. Never log in plaintext
2. Encrypt before writing to SSM
3. Decrypt only when injecting into container environment
4. Use AWS Secrets Manager for high-security secrets (consider cost)

**Service secrets** (orchestrator's own credentials):
- ECS task IAM role with minimal permissions
- No hardcoded credentials in code
- Use AWS SDK default credential chain

### Authorization

**User Isolation:**
- Users can only manage their own containers
- All endpoints verify `user_uuid` matches container owner
- No admin/superuser concept in v1 (add later if needed)

**IAM Permissions (for orchestrator task role):**

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ecs:RunTask",
        "ecs:StopTask",
        "ecs:DescribeTasks",
        "ecs:ListTasks"
      ],
      "Resource": "*",
      "Condition": {
        "StringEquals": {
          "ecs:cluster": "arn:aws:ecs:ap-southeast-2:*:cluster/clawtalk-*"
        }
      }
    },
    {
      "Effect": "Allow",
      "Action": [
        "ssm:PutParameter",
        "ssm:GetParameter",
        "ssm:DeleteParameter"
      ],
      "Resource": "arn:aws:ssm:*:*:parameter/openclaw-containers/*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "dynamodb:PutItem",
        "dynamodb:GetItem",
        "dynamodb:UpdateItem",
        "dynamodb:DeleteItem",
        "dynamodb:Query",
        "dynamodb:Scan"
      ],
      "Resource": [
        "arn:aws:dynamodb:*:*:table/openclaw-containers-*",
        "arn:aws:dynamodb:*:*:table/openclaw-containers-*/index/*"
      ]
    },
    {
      "Effect": "Allow",
      "Action": [
        "kms:Decrypt",
        "kms:Encrypt",
        "kms:GenerateDataKey"
      ],
      "Resource": "arn:aws:kms:*:*:key/*",
      "Condition": {
        "StringEquals": {
          "kms:ViaService": [
            "ssm.ap-southeast-2.amazonaws.com",
            "dynamodb.ap-southeast-2.amazonaws.com"
          ]
        }
      }
    }
  ]
}
```

---

## Container Lifecycle

### States

```
┌──────────────┐
│ PROVISIONING │  ← Initial state after RunTask
└──────┬───────┘
       │
       ▼
┌──────────────┐
│   PENDING    │  ← ECS task pending (pulling image)
└──────┬───────┘
       │
       ▼
┌──────────────┐
│   RUNNING    │  ← Task started, health check passing
└──────┬───────┘
       │
       ├─────────► ┌──────────────┐
       │           │   STOPPING   │  ← User requested stop
       │           └──────┬───────┘
       │                  │
       ▼                  ▼
┌──────────────┐    ┌──────────────┐
│    FAILED    │    │   STOPPED    │  ← Terminal states
└──────────────┘    └──────────────┘
```

**State Transitions:**

| From | To | Trigger |
|------|-----|---------|
| - | PROVISIONING | User calls `POST /containers` |
| PROVISIONING | PENDING | ECS RunTask accepted |
| PENDING | RUNNING | Container healthy |
| PENDING | FAILED | Container start failed |
| RUNNING | STOPPING | User calls `DELETE /containers/{id}` |
| RUNNING | FAILED | Health check failed |
| STOPPING | STOPPED | ECS task stopped |

### Status Sync

**How to keep DynamoDB in sync with ECS?**

**Option 1: Poll ECS periodically**
- Background Lambda runs every 1 minute
- Lists all tasks in cluster
- Updates DynamoDB for mismatched states
- ✅ Simple
- ❌ 1-minute lag
- ❌ API calls add cost

**Option 2: ECS EventBridge events**
- Subscribe to ECS task state change events
- Lambda triggered on `RUNNING`, `STOPPED`, `FAILED`
- Updates DynamoDB in near real-time
- ✅ Real-time updates
- ✅ Event-driven (no polling cost)
- ❌ More complex setup

**Recommendation:** **Option 2 (EventBridge)** for production, start with manual sync for MVP.

---

## Container Configuration

### How to inject config into openclaw-agent?

**Option A: SSM Parameter Store** (Recommended)
- Store JSON config in SSM SecureString: `/openclaw-containers/{env}/{container_id}/config`
- ECS task definition secrets: `{ "name": "CLAWTALK_CONFIG", "valueFrom": "/openclaw-containers/..." }`
- openclaw-agent reads `CLAWTALK_CONFIG` env var on startup
- ✅ Encrypted at rest
- ✅ Versioned
- ✅ IAM-controlled
- ❌ Requires openclaw-agent to support env var config source

**Option B: S3 bucket**
- Upload config JSON to S3: `s3://clawtalk-configs/{env}/{container_id}.json`
- Pass S3 path via environment variable
- openclaw-agent downloads on startup
- ✅ Large config support
- ❌ More complex permissions
- ❌ S3 dependency

**Option C: ECS task definition overrides**
- Pass individual env vars via `RunTask` overrides
- ❌ Not suitable for complex JSON config
- ❌ Secrets visible in ECS API

**Decision:** Use **SSM Parameter Store**. Modify openclaw-agent to support config from `CLAWTALK_CONFIG` env var.

---

## Configuration Flow (Detailed)

### Step-by-Step: POST /containers

When a user calls `POST /containers` with their config:

```json
{
  "openclaw_url": "http://localhost:18789",
  "openclaw_token": "sk-oc-xyz",
  "openclaw_model": "claude-3-haiku-20240307",
  "llm_provider": "anthropic",
  "anthropic_api_key": "sk-ant-abc123",
  "auth_gateway_url": "https://api.clawtalk.team",
  "voice_gateway_url": "wss://voice.clawtalk.team",
  "agents": []
}
```

**Orchestrator Lambda executes:**

1. **Validate User Token**
   ```python
   user_uuid = await auth_client.validate_token(bearer_token)
   ```

2. **Generate Container ID**
   ```python
   container_id = f"oc-{uuid.uuid4().hex[:12]}"  # e.g., "oc-a1b2c3d4e5f6"
   ```

3. **Encrypt Sensitive Fields** (optional, for defense-in-depth)
   ```python
   config_to_store = {
       "openclaw_url": request.openclaw_url,
       "openclaw_token": encrypt(request.openclaw_token),  # KMS encrypt
       "anthropic_api_key": encrypt(request.anthropic_api_key),
       "auth_gateway_url": request.auth_gateway_url,
       "auth_gateway_api_key": bearer_token,  # User's API key
       "voice_gateway_url": request.voice_gateway_url,
       "user_id": user_uuid,
       "agents": []
   }
   ```

4. **Store Config in SSM**
   ```python
   ssm.put_parameter(
       Name=f'/openclaw-containers/{env}/{container_id}/config',
       Value=json.dumps(config_to_store),
       Type='SecureString',  # Encrypted with default KMS key
       Overwrite=False
   )
   ```

5. **Write DynamoDB Record**
   ```python
   dynamodb.put_item(
       TableName=f'openclaw-containers-{env}',
       Item={
           'pk': f'USER#{user_uuid}',
           'sk': f'CONTAINER#{container_id}',
           'container_id': container_id,
           'status': 'PROVISIONING',
           'created_at': now_iso,
           'config_ssm_path': f'/openclaw-containers/{env}/{container_id}/config',
           'user_uuid': user_uuid
       }
   )
   ```

6. **Launch ECS Task**
   ```python
   response = ecs.run_task(
       cluster=cluster_name,
       taskDefinition=f'openclaw-agent-{env}',
       launchType='FARGATE',
       platformVersion='LATEST',
       networkConfiguration={
           'awsvpcConfiguration': {
               'subnets': container_subnets,
               'securityGroups': container_security_groups,
               'assignPublicIp': 'DISABLED'
           }
       },
       overrides={
           'containerOverrides': [{
               'name': 'openclaw-agent',
               'secrets': [{
                   'name': 'CLAWTALK_CONFIG',
                   'valueFrom': f'/openclaw-containers/{env}/{container_id}/config'
               }]
           }]
       },
       tags=[
           {'key': 'User', 'value': user_uuid},
           {'key': 'ContainerID', 'value': container_id},
           {'key': 'ManagedBy', 'value': 'orchestrator'}
       ],
       enableExecuteCommand=True  # For debugging via ECS Exec
   )
   
   task_arn = response['tasks'][0]['taskArn']
   ```

7. **Update DynamoDB with Task ARN**
   ```python
   dynamodb.update_item(
       TableName=f'openclaw-containers-{env}',
       Key={'pk': f'USER#{user_uuid}', 'sk': f'CONTAINER#{container_id}'},
       UpdateExpression='SET task_arn = :arn, #status = :status',
       ExpressionAttributeNames={'#status': 'status'},
       ExpressionAttributeValues={
           ':arn': task_arn,
           ':status': 'PENDING'
       }
   )
   ```

8. **Return Response**
   ```python
   return {
       "container_id": container_id,
       "task_arn": task_arn,
       "status": "PENDING",
       "created_at": now_iso,
       "message": "Container is starting. Poll GET /containers/{id} for status."
   }
   ```

---

### Container Startup Sequence

What happens inside the ECS task after `RunTask`:

1. **ECS pulls image** from ECR (30-60 seconds)
2. **Container starts**, openclaw-agent reads `CLAWTALK_CONFIG` env var
3. **openclaw-agent parses JSON config** and validates required fields
4. **Validates with auth-gateway** using `auth_gateway_api_key`
   - Receives `user_id` confirmation
5. **Initializes OpenClaw client** (if `openclaw_url` provided)
6. **Spawns agents** from `agents` array (if any)
7. **Health check endpoint** becomes available: `GET /health`
8. **ECS health check passes** (3 successful checks = healthy)

**Timeline:**
- T+0s: RunTask called
- T+5s: Task state = PENDING (ECS accepted)
- T+45s: Task state = RUNNING (container started)
- T+60s: Health check passes → status = HEALTHY

---

## Deployment Verification

### How to verify container deployed successfully?

**Approach 1: Poll ECS DescribeTasks** (Synchronous)

When user calls `GET /containers/{container_id}`:

```python
def get_container_status(user_uuid, container_id):
    # 1. Get DynamoDB record
    item = dynamodb.get_item(
        Key={'pk': f'USER#{user_uuid}', 'sk': f'CONTAINER#{container_id}'}
    )
    
    if not item:
        raise NotFound()
    
    task_arn = item.get('task_arn')
    
    # 2. Query ECS for live task status
    if task_arn:
        ecs_response = ecs.describe_tasks(
            cluster=cluster_name,
            tasks=[task_arn]
        )
        
        if ecs_response['tasks']:
            task = ecs_response['tasks'][0]
            ecs_status = task['lastStatus']  # PENDING, RUNNING, STOPPED
            health_status = task.get('healthStatus', 'UNKNOWN')  # HEALTHY, UNHEALTHY
            
            # Get container IP (if running)
            ip_address = None
            if ecs_status == 'RUNNING':
                for attachment in task.get('attachments', []):
                    if attachment['type'] == 'ElasticNetworkInterface':
                        for detail in attachment['details']:
                            if detail['name'] == 'privateIPv4Address':
                                ip_address = detail['value']
            
            # Update DynamoDB cache
            dynamodb.update_item(
                Key={'pk': f'USER#{user_uuid}', 'sk': f'CONTAINER#{container_id}'},
                UpdateExpression='SET #status = :status, ip_address = :ip, health = :health',
                ExpressionAttributeNames={'#status': 'status'},
                ExpressionAttributeValues={
                    ':status': ecs_status,
                    ':ip': ip_address,
                    ':health': health_status
                }
            )
            
            return {
                "container_id": container_id,
                "status": ecs_status,
                "health": health_status,
                "ip_address": ip_address,
                "endpoint": f"http://{ip_address}:8080" if ip_address else None,
                "created_at": item['created_at']
            }
    
    # Fallback to cached DynamoDB status
    return {
        "container_id": container_id,
        "status": item.get('status', 'UNKNOWN'),
        "created_at": item['created_at']
    }
```

---

**Approach 2: EventBridge Async Updates** (Recommended for production)

Set up EventBridge rule to catch ECS task state changes:

**EventBridge Rule Pattern:**
```json
{
  "source": ["aws.ecs"],
  "detail-type": ["ECS Task State Change"],
  "detail": {
    "clusterArn": [{"prefix": "arn:aws:ecs:ap-southeast-2:*:cluster/clawtalk-"}],
    "tags": {
      "ManagedBy": ["orchestrator"]
    }
  }
}
```

**Lambda Handler for Events:**
```python
def handle_ecs_event(event):
    """Triggered by EventBridge on ECS task state changes"""
    detail = event['detail']
    
    task_arn = detail['taskArn']
    last_status = detail['lastStatus']  # RUNNING, STOPPED, etc.
    
    # Extract container_id from task tags
    tags = {tag['key']: tag['value'] for tag in detail.get('tags', [])}
    container_id = tags.get('ContainerID')
    user_uuid = tags.get('User')
    
    if not container_id or not user_uuid:
        return  # Not our task
    
    # Update DynamoDB
    update_expr = 'SET #status = :status, updated_at = :now'
    attr_values = {
        ':status': last_status,
        ':now': datetime.utcnow().isoformat()
    }
    
    # If RUNNING, extract IP address and construct endpoints
    if last_status == 'RUNNING' and 'attachments' in detail:
        ip_address = None
        for attachment in detail['attachments']:
            if attachment['type'] == 'ElasticNetworkInterface':
                for kv in attachment['details']:
                    if kv['name'] == 'privateIPv4Address':
                        ip_address = kv['value']
                        break
        
        if ip_address:
            port = 8080  # Default openclaw-agent port
            update_expr += ', ip_address = :ip, port = :port, health_endpoint = :health_ep, api_endpoint = :api_ep'
            attr_values.update({
                ':ip': ip_address,
                ':port': port,
                ':health_ep': f'http://{ip_address}:{port}/health',
                ':api_ep': f'http://{ip_address}:{port}'
            })
            
            # Trigger initial health check (async)
            # This will be picked up by the periodic health checker
            # or we can invoke it directly here
    
    dynamodb.update_item(
        TableName=f'openclaw-containers-{env}',
        Key={'pk': f'USER#{user_uuid}', 'sk': f'CONTAINER#{container_id}'},
        UpdateExpression=update_expr,
        ExpressionAttributeNames={'#status': 'status'},
        ExpressionAttributeValues=attr_values
    )
```

---

### Health Check Flow

**Approach: Direct Health Probes via openclaw-agent API**

Each container exposes the openclaw-agent HTTP API on a fixed port (8080 by default). The orchestrator tracks the container's private IP and port, then probes the `/health` endpoint directly.

**Why this approach:**
- ✅ Gets real application health, not just container liveness
- ✅ openclaw-agent already has `/health` endpoint
- ✅ Can extract detailed health info (agent count, memory, etc.)
- ✅ No dependency on ECS health checks (simpler task definition)
- ⚠️ Requires orchestrator Lambda in VPC (same as containers)

**Container Endpoint Discovery:**

When ECS task reaches `RUNNING` state:

```python
def extract_container_endpoint(task):
    """Extract private IP and port from running ECS task"""
    ip_address = None
    port = 8080  # Default openclaw-agent port
    
    # Get ENI private IP from task attachments
    for attachment in task.get('attachments', []):
        if attachment['type'] == 'ElasticNetworkInterface':
            for detail in attachment['details']:
                if detail['name'] == 'privateIPv4Address':
                    ip_address = detail['value']
                    break
    
    # Get port from container definition (if dynamic port mapping)
    for container in task.get('containers', []):
        if container['name'] == 'openclaw-agent':
            for port_mapping in container.get('networkBindings', []):
                if port_mapping.get('protocol') == 'tcp':
                    port = port_mapping.get('containerPort', 8080)
                    break
    
    return {
        'ip_address': ip_address,
        'port': port,
        'health_endpoint': f'http://{ip_address}:{port}/health',
        'api_endpoint': f'http://{ip_address}:{port}'
    }
```

**Health Check Lambda Function:**

Separate Lambda triggered by EventBridge (every 1 minute) or on-demand:

```python
def check_container_health(container_id, health_endpoint):
    """Probe openclaw-agent /health endpoint"""
    try:
        response = requests.get(
            health_endpoint,
            timeout=5,
            headers={'User-Agent': 'clawtalk-orchestrator/1.0'}
        )
        
        if response.status_code == 200:
            health_data = response.json()
            
            return {
                'status': 'HEALTHY',
                'agents_running': health_data.get('agents', 0),
                'uptime_seconds': health_data.get('uptime', 0),
                'memory_mb': health_data.get('memory_mb', 0),
                'version': health_data.get('version', 'unknown'),
                'last_check': datetime.utcnow().isoformat()
            }
        else:
            return {
                'status': 'UNHEALTHY',
                'error': f'HTTP {response.status_code}',
                'last_check': datetime.utcnow().isoformat()
            }
    
    except requests.exceptions.Timeout:
        return {
            'status': 'UNREACHABLE',
            'error': 'Health check timeout',
            'last_check': datetime.utcnow().isoformat()
        }
    
    except Exception as e:
        return {
            'status': 'ERROR',
            'error': str(e),
            'last_check': datetime.utcnow().isoformat()
        }
```

**Periodic Health Check Lambda:**

```python
def periodic_health_checker(event, context):
    """Triggered every 1 minute by EventBridge"""
    
    # Scan DynamoDB for RUNNING containers
    containers = dynamodb.query(
        IndexName='StatusIndex',
        KeyConditionExpression='#status = :running',
        ExpressionAttributeNames={'#status': 'status'},
        ExpressionAttributeValues={':running': 'RUNNING'}
    )
    
    for item in containers.get('Items', []):
        container_id = item['container_id']
        health_endpoint = item.get('health_endpoint')
        
        if not health_endpoint:
            continue  # No endpoint yet (still starting)
        
        # Probe health endpoint
        health = check_container_health(container_id, health_endpoint)
        
        # Update DynamoDB
        dynamodb.update_item(
            Key={'pk': item['pk'], 'sk': item['sk']},
            UpdateExpression='''
                SET health_status = :status,
                    last_health_check = :time,
                    health_data = :data
            ''',
            ExpressionAttributeValues={
                ':status': health['status'],
                ':time': health['last_check'],
                ':data': health
            }
        )
        
        # If unhealthy for >5 minutes, mark as FAILED
        if health['status'] != 'HEALTHY':
            last_check = datetime.fromisoformat(item.get('last_health_check', health['last_check']))
            if (datetime.utcnow() - last_check).seconds > 300:
                dynamodb.update_item(
                    Key={'pk': item['pk'], 'sk': item['sk']},
                    UpdateExpression='SET #status = :failed',
                    ExpressionAttributeNames={'#status': 'status'},
                    ExpressionAttributeValues={':failed': 'FAILED'}
                )
```

**On-Demand Health Check (via API):**

User calls `GET /containers/{id}/health`:

```python
@router.get("/containers/{container_id}/health")
async def get_container_health(container_id: str, user_uuid: str = Depends(get_current_user)):
    """Return latest health check result"""
    
    item = dynamodb.get_item(
        Key={'pk': f'USER#{user_uuid}', 'sk': f'CONTAINER#{container_id}'}
    )
    
    if not item:
        raise HTTPException(404, "Container not found")
    
    health_endpoint = item.get('health_endpoint')
    
    if not health_endpoint:
        return {
            "status": "STARTING",
            "message": "Health endpoint not available yet"
        }
    
    # Perform immediate health check
    health = check_container_health(container_id, health_endpoint)
    
    # Update DynamoDB cache
    dynamodb.update_item(
        Key={'pk': f'USER#{user_uuid}', 'sk': f'CONTAINER#{container_id}'},
        UpdateExpression='SET health_status = :status, health_data = :data, last_health_check = :time',
        ExpressionAttributeValues={
            ':status': health['status'],
            ':data': health,
            ':time': health['last_check']
        }
    )
    
    return {
        "container_id": container_id,
        "health": health,
        "endpoint": item.get('api_endpoint')
    }
```

**VPC Configuration:**

For Lambda to reach private container IPs:

```terraform
resource "aws_lambda_function" "orchestrator" {
  # ... other config ...
  
  vpc_config {
    subnet_ids         = var.private_subnet_ids
    security_groups    = [aws_security_group.orchestrator_lambda.id]
  }
}

resource "aws_security_group" "orchestrator_lambda" {
  name        = "orchestrator-lambda-${var.env}"
  description = "Allow orchestrator Lambda to reach openclaw-agent containers"
  vpc_id      = var.vpc_id
  
  egress {
    description     = "To openclaw-agent containers"
    from_port       = 8080
    to_port         = 8080
    protocol        = "tcp"
    security_groups = [var.openclaw_agent_security_group_id]
  }
  
  egress {
    description = "To auth-gateway for token validation"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# Update openclaw-agent security group to allow orchestrator
resource "aws_security_group_rule" "allow_orchestrator_health_checks" {
  type                     = "ingress"
  from_port                = 8080
  to_port                  = 8080
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.orchestrator_lambda.id
  security_group_id        = var.openclaw_agent_security_group_id
  description              = "Allow orchestrator health checks"
}
```

---

### Error Handling

**What if container fails to start?**

**Scenario 1: Image pull failure**
- ECS event: `taskStoppedReason: "CannotPullContainerError"`
- EventBridge Lambda updates status to `FAILED`
- User gets error on next `GET /containers/{id}` poll

**Scenario 2: Config invalid (openclaw-agent exits)**
- Container starts but exits immediately
- ECS health check fails
- After 3 failures, task stops
- Status updated to `FAILED`

**Scenario 3: Network issues (can't reach auth-gateway)**
- Container starts but can't validate
- Health check fails (openclaw-agent returns 503)
- Status remains `UNHEALTHY`

**User-facing error responses:**

```json
{
  "container_id": "oc-a1b2c3d4e5f6",
  "status": "FAILED",
  "error": {
    "code": "IMAGE_PULL_FAILED",
    "message": "Could not pull container image from ECR",
    "ecs_reason": "CannotPullContainerError: manifest unknown"
  },
  "created_at": "2026-04-04T02:00:00Z",
  "stopped_at": "2026-04-04T02:01:30Z"
}
```

---

### Debugging Failed Containers

**Tools available:**

1. **CloudWatch Logs**
   - Stream: `/ecs/openclaw-agent-{env}/{task_id}`
   - View container stdout/stderr
   - Check for config errors, auth failures, crashes

2. **ECS Exec** (if `enableExecuteCommand=True`)
   ```bash
   aws ecs execute-command \
     --cluster clawtalk-dev \
     --task {task_arn} \
     --container openclaw-agent \
     --interactive \
     --command "/bin/sh"
   ```

3. **Orchestrator Logs**
   - `/aws/lambda/orchestrator-{env}`
   - Check for RunTask errors, SSM issues

4. **SSM Parameter Inspection** (for admins)
   ```bash
   aws ssm get-parameter \
     --name /openclaw-containers/dev/{container_id}/config \
     --with-decryption
   ```

---

## ECS Integration

### Task Definition

Use existing `openclaw-agent-{env}` task definition with overrides:

**RunTask Parameters:**

```python
ecs_client.run_task(
    cluster='clawtalk-dev',
    taskDefinition='openclaw-agent-dev',
    launchType='FARGATE',
    networkConfiguration={
        'awsvpcConfiguration': {
            'subnets': ['subnet-abc123', 'subnet-def456'],
            'securityGroups': ['sg-openclaw-agent'],
            'assignPublicIp': 'DISABLED'
        }
    },
    overrides={
        'containerOverrides': [
            {
                'name': 'openclaw-agent',
                'environment': [
                    {'name': 'CONFIG_SOURCE', 'value': 'ssm'},
                    {'name': 'CONFIG_PATH', 'value': f'/openclaw-containers/{env}/{container_id}/config'}
                ]
            }
        ]
    },
    tags=[
        {'key': 'User', 'value': user_uuid},
        {'key': 'ContainerID', 'value': container_id},
        {'key': 'ManagedBy', 'value': 'orchestrator'}
    ]
)
```

**Service Discovery:**

Do we need internal DNS for containers? 

**No** - Each container is isolated, only talks to:
- auth-gateway (public/ALB)
- voice-gateway (public/ALB)
- OpenClaw (user-provided URL)

**Yes** - If containers need to discover each other (future multi-agent coordination)

**Decision:** Skip service discovery in v1. Add later if needed.

---

## Cost Optimization

### Fargate Spot

Use **FARGATE_SPOT** for container tasks:
- 70% cheaper than FARGATE
- Acceptable for user-facing agents (can tolerate interruptions)
- Orchestrator should handle spot interruptions gracefully (restart task)

### TTL and Cleanup

**Problem:** Stale containers waste money

**Solution:**
1. Set DynamoDB TTL on stopped containers (delete after 7 days)
2. Periodic cleanup Lambda:
   - Scans DynamoDB for `RUNNING` containers older than 30 days
   - Checks if ECS task still exists
   - If not, updates status to `STOPPED` and sets TTL
3. Alert on long-running containers (CloudWatch alarm)

### Auto-stop Idle Containers

**Future Enhancement:**
- Monitor last activity timestamp (from openclaw-agent health endpoint)
- Auto-stop containers idle for >1 hour
- Notify user before stopping

---

## Deployment Strategy

### Infrastructure Setup (Terraform)

Create module: `infrastructure/infra/modules/orchestrator`

**Resources:**
- Lambda function (Python 3.11 runtime)
- API Gateway HTTP API (REST API with Lambda proxy integration)
- Lambda execution role with ECS/DynamoDB/SSM permissions
- DynamoDB table `openclaw-containers-{env}`
- CloudWatch log group `/aws/lambda/orchestrator-{env}`
- EventBridge rules for ECS events (future)
- Optional: Lambda VPC config (if accessing private resources)

**Inputs:**
- `env`: Environment name (dev, staging, prod)
- `vpc_id`: VPC (optional, for private subnet access)
- `private_subnet_ids`: For Lambda VPC config (optional)
- `auth_gateway_url`: For token validation
- `ecs_cluster_name`: Cluster to deploy containers into
- `openclaw_agent_task_definition`: Task def ARN to run
- `subnets_for_containers`: Subnets for openclaw-agent tasks
- `security_groups_for_containers`: Security groups for tasks

---

### Deployment Order

1. **Phase 1: Infrastructure**
   - Create Terraform module (matches auth-gateway pattern)
   - Deploy DynamoDB table
   - Deploy Lambda function (stub API)
   - Deploy API Gateway + domain (e.g., `orchestrator.clawtalk.team`)

2. **Phase 2: Core API**
   - Implement authentication middleware
   - Implement `POST /containers` (spin up)
   - Implement `GET /containers` (list)
   - Implement `DELETE /containers/{id}` (stop)

3. **Phase 3: State Management**
   - Implement ECS event handling (EventBridge)
   - Implement status sync
   - Implement cleanup Lambda

4. **Phase 4: Enhanced Features**
   - Config updates (`PATCH /containers/{id}/config`)
   - Container logs endpoint (`GET /containers/{id}/logs`)
   - Metrics/monitoring
   - Auto-stop idle containers

---

## Testing Plan

### Unit Tests

**Framework:** pytest (Python) or Go testing

**Coverage:**
- DynamoDB CRUD operations
- ECS client wrapper (mock boto3 calls)
- Authentication middleware
- Config encryption/decryption
- Input validation

### Integration Tests

**Test Scenarios:**

1. **Spin up container**
   - Call `POST /containers` with valid auth
   - Verify DynamoDB record created
   - Verify SSM parameter created
   - Verify ECS task started
   - Verify container reaches `RUNNING` state

2. **List containers**
   - Spin up 2 containers
   - Call `GET /containers`
   - Verify both returned
   - Verify filtering by status works

3. **Stop container**
   - Spin up container
   - Call `DELETE /containers/{id}`
   - Verify ECS task stops
   - Verify DynamoDB updated to `STOPPED`
   - Verify SSM parameter deleted

4. **Ownership isolation**
   - User A spins up container
   - User B tries to access User A's container
   - Verify `403 Forbidden` response

5. **Invalid token**
   - Call API with invalid token
   - Verify `401 Unauthorized` response

### E2E Tests

**Workflow:**
1. Flutter app authenticates with auth-gateway
2. Flutter app calls `POST /containers` via orchestrator
3. Flutter app polls `GET /containers/{id}` until `RUNNING`
4. Flutter app connects to openclaw-agent at returned endpoint
5. User makes voice call
6. Flutter app calls `DELETE /containers/{id}` on logout
7. Verify container stopped

---

## Monitoring & Observability

### Metrics (CloudWatch)

- `orchestrator.containers.created` (count)
- `orchestrator.containers.failed` (count)
- `orchestrator.containers.stopped` (count)
- `orchestrator.containers.running` (gauge)
- `orchestrator.api.latency.{endpoint}` (histogram)
- `orchestrator.api.errors.{endpoint}` (count)

### Logs (CloudWatch Logs)

**Log Groups:**
- `/aws/lambda/orchestrator-{env}` - Lambda function logs
- `/ecs/openclaw-agent-{env}` - Container logs (managed by openclaw-agent task def)

**Log Structure:**

```json
{
  "timestamp": "2026-04-04T02:00:00Z",
  "level": "INFO",
  "message": "Container created",
  "user_uuid": "275aa927-...",
  "container_id": "ecs-task-123abc",
  "task_arn": "arn:aws:ecs:...",
  "request_id": "req-abc123"
}
```

### Alarms

- **High Error Rate**: API errors >5% over 5 minutes
- **Container Start Failures**: >3 failed starts in 10 minutes
- **Long-Running Containers**: Any container >24 hours old (cost alert)
- **Service Unhealthy**: ALB health check failing

### Tracing (AWS X-Ray)

**Future Enhancement:**
- Instrument API Gateway/ALB requests
- Trace ECS RunTask calls
- Trace DynamoDB queries
- End-to-end request tracing

---

## Open Questions

### 1. Container Networking

**Q:** Should containers have public IPs for external access?

**A:** No for v1. Containers are internal:
- They connect OUT to voice-gateway (WebSocket)
- They connect OUT to OpenClaw API
- No inbound traffic needed

**Future:** If we need direct access (debugging, logs), use:
- ECS Exec (SSM Session Manager)
- Internal ALB for container HTTP API
- CloudWatch Logs streaming

---

### 2. Multi-Region Support

**Q:** Should orchestrator support deploying containers to multiple AWS regions?

**A:** Not in v1. Start with single region (ap-southeast-2).

**Future Considerations:**
- User proximity (latency)
- Data residency requirements
- Cost optimization (regional pricing)

---

### 3. Container Quotas

**Q:** Should we limit containers per user?

**A:** Yes. Start with:
- **Free tier**: 1 container per user
- **Paid tier**: 5 containers per user (future)

**Enforcement:**
- Check quota in `POST /containers` before creating
- Return `429 Too Many Requests` if over limit
- Store quota in auth-gateway user profile (or orchestrator config)

---

### 4. Billing Integration

**Q:** How to track usage for billing?

**A:** V1: No billing, internal use only.

**Future:**
- DynamoDB tracks `created_at`, `stopped_at`
- Calculate container-hours per user per month
- Integrate with Stripe/payment provider
- Monthly invoice generation

---

## Technology Stack

### Programming Language

**Python (FastAPI)** - matches auth-gateway pattern

**Why Python:**
- ✅ Matches auth-gateway deployment (Lambda + Python)
- ✅ Reuse auth-gateway patterns (DynamoDB, middleware, Docker)
- ✅ Rich AWS SDK (boto3)
- ✅ Fast development
- ✅ Team familiarity
- ✅ Smaller Lambda package size vs Go

### Framework

**FastAPI** (async, matches auth-gateway)

**Libraries:**
- `boto3` - AWS SDK (ECS, DynamoDB, SSM)
- `fastapi` - Web framework
- `mangum` - Lambda/ASGI adapter
- `pydantic` - Data validation
- `pytest` - Testing
- `python-json-logger` - Structured logging
- `cryptography` - Config encryption (optional)

---

## File Structure

```
orchestrator/
├── app/
│   ├── __init__.py
│   ├── main.py                  # FastAPI app + routes
│   ├── config.py                # Service configuration
│   ├── middleware/
│   │   ├── __init__.py
│   │   └── auth.py              # Auth validation middleware
│   ├── models/
│   │   ├── __init__.py
│   │   ├── container.py         # Pydantic models
│   │   └── requests.py          # Request/response schemas
│   ├── services/
│   │   ├── __init__.py
│   │   ├── auth_client.py       # auth-gateway client
│   │   ├── container_manager.py # ECS orchestration
│   │   ├── dynamodb.py          # DynamoDB operations
│   │   └── config_store.py      # SSM config management
│   └── routes/
│       ├── __init__.py
│       ├── containers.py        # Container CRUD endpoints
│       └── health.py            # Health check
├── tests/
│   ├── integration/
│   │   └── test_container_lifecycle.py
│   └── unit/
│       ├── test_manager.py
│       └── test_auth.py
├── infra/
│   └── terraform/               # Terraform module (later moved to ../infrastructure)
├── Dockerfile.lambda
├── lambda_handler.py            # Mangum adapter entry point
├── Makefile
├── requirements.txt
├── requirements-dev.txt
├── pyproject.toml
├── README.md
└── ARCHITECTURE_PLAN.md         # This document
```

---

## Implementation Phases

### Phase 1: MVP (Week 1)

**Goal:** Basic container lifecycle management

**Deliverables:**
- ✅ Project scaffold (Python + FastAPI)
- ✅ Auth middleware (validate with auth-gateway)
- ✅ `POST /containers` - Spin up container
- ✅ `GET /containers` - List user's containers
- ✅ `DELETE /containers/{id}` - Stop container
- ✅ DynamoDB CRUD operations
- ✅ SSM config storage
- ✅ ECS RunTask/StopTask integration
- ✅ Basic unit tests
- ✅ Deploy to dev environment

**Success Criteria:**
- Can create container via API
- Container appears in ECS
- DynamoDB record created
- Can list and stop containers

---

### Phase 2: Production-Ready (Week 2)

**Goal:** Monitoring, state sync, error handling

**Deliverables:**
- ✅ EventBridge integration for state sync
- ✅ Structured logging (JSON)
- ✅ CloudWatch metrics
- ✅ Error handling and retries
- ✅ Input validation
- ✅ Integration tests
- ✅ Terraform module
- ✅ Deploy to staging
- ✅ Load testing

**Success Criteria:**
- Status syncs in <5 seconds
- API handles 100 req/s
- Zero data leaks between users
- Graceful error messages

---

### Phase 3: Enhanced Features (Week 3+)

**Goal:** User experience improvements

**Deliverables:**
- ✅ `PATCH /containers/{id}/config` - Update config
- ✅ `GET /containers/{id}/logs` - Stream logs
- ✅ Auto-stop idle containers
- ✅ Container quotas
- ✅ Metrics dashboard
- ✅ User-facing documentation
- ✅ Deploy to production

**Success Criteria:**
- Users can update agents without restarting
- Logs accessible via API
- Idle containers auto-stop after 1 hour
- Cost reduced by 30% via auto-stop

---

## Risk Analysis

| Risk | Impact | Likelihood | Mitigation |
|------|--------|-----------|------------|
| ECS quota exceeded | High | Low | Monitor quotas, request increase, graceful error |
| DynamoDB throttling | Medium | Low | Use on-demand billing, add retries |
| SSM parameter limit hit | Medium | Low | Clean up old configs, monitor usage |
| Container start failures | High | Medium | Retry logic, detailed error messages, health checks |
| User data leakage | Critical | Low | Strict ownership checks, audit logs, security review |
| Cost overrun | High | Medium | Auto-stop idle, quotas, CloudWatch alarms |
| State desync (DynamoDB vs ECS) | Medium | Medium | EventBridge sync, periodic reconciliation |

---

## Success Metrics

**Technical:**
- ✅ 99.9% API uptime
- ✅ <500ms P95 latency for `POST /containers`
- ✅ <100ms P95 latency for `GET /containers`
- ✅ Zero user data leaks (validated via security audit)
- ✅ <1% container start failure rate

**Business:**
- ✅ Support 100 concurrent users
- ✅ Reduce manual container management effort by 90%
- ✅ Enable Flutter app self-service container creation

---

## Next Steps

1. **Review this document with Andrew**
   - Confirm architecture decisions
   - Clarify open questions
   - Approve tech stack

2. **Create GitHub repository**
   - `clawtalk/orchestrator`
   - Initialize Go module
   - Add basic README

3. **Set up development environment**
   - Local DynamoDB (Docker)
   - Mock auth-gateway
   - AWS credentials for dev account

4. **Begin Phase 1 implementation**
   - Scaffold project structure
   - Implement auth middleware
   - Implement basic container operations

5. **Document as we go**
   - API documentation (OpenAPI spec)
   - Developer setup guide
   - Architecture decision records (ADRs)

---

## References

- **auth-gateway:** `~/workspace/clawtalk/auth-gateway`
  - User model: `app/models/user.py`
  - Agent model: `app/models/agent.py`
  - DynamoDB service: `app/services/dynamodb.py`

- **openclaw-agent:** `~/workspace/clawtalk/openclaw-agent`
  - Dockerfile: `Dockerfile`
  - Config structure: `internal/config/config.go`
  - Manager: `internal/manager/manager.go`

- **infrastructure:** `~/workspace/clawtalk/infrastructure/infra`
  - ECS module: `modules/ecs-cluster/main.tf`
  - openclaw-agent module: `modules/openclaw-agent/main.tf`
  - Dev environment: `environments/dev/main.tf`

- **Architecture diagrams:**
  - New container flow: `~/workspace/clawtalk/architecture/sequence-diagrams/new-openclaw-container.wsd`
  - Agent registration: `~/workspace/clawtalk/architecture/sequence-diagrams/agent-registration-push.wsd`

---

**End of Architecture Plan**
