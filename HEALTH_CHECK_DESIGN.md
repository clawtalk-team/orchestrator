# Health Check Design - Container Orchestrator

**Date:** 2026-04-04  
**Decision:** Use direct HTTP probes to openclaw-agent `/health` endpoint

---

## Overview

Instead of relying on ECS health checks alone, the orchestrator directly probes each container's openclaw-agent HTTP API to get real application health status.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Orchestrator Lambda (in VPC)                               │
│  ┌────────────────────┐                                     │
│  │ Periodic Health    │  Every 1 minute                     │
│  │ Checker            ├──────────┐                          │
│  └────────────────────┘          │                          │
│                                   │                          │
│  ┌────────────────────┐          │                          │
│  │ On-Demand Health   │          │                          │
│  │ API Endpoint       │          │                          │
│  └────────────────────┘          │                          │
└──────────────────────────────────┼──────────────────────────┘
                                   │
                                   │ HTTP GET /health
                                   ▼
              ┌─────────────────────────────────┐
              │  ECS Task (Private Subnet)      │
              │  ┌───────────────────────────┐  │
              │  │  openclaw-agent           │  │
              │  │  :8080/health             │  │
              │  │                           │  │
              │  │  Returns:                 │  │
              │  │  - agents_running         │  │
              │  │  - uptime_seconds         │  │
              │  │  - memory_mb              │  │
              │  │  - version                │  │
              │  │  - agent details          │  │
              │  └───────────────────────────┘  │
              │  IP: 10.0.1.45                  │
              └─────────────────────────────────┘
```

---

## Data Flow

### 1. Container Startup

```
POST /containers
    ↓
Orchestrator creates ECS task
    ↓
Task reaches RUNNING state (EventBridge event)
    ↓
Extract IP from ENI attachment
    ↓
Store in DynamoDB:
  - ip_address: "10.0.1.45"
  - port: 8080
  - health_endpoint: "http://10.0.1.45:8080/health"
  - api_endpoint: "http://10.0.1.45:8080"
```

### 2. Periodic Health Checks

```
EventBridge (every 1 minute)
    ↓
Trigger health_checker Lambda
    ↓
Query DynamoDB for RUNNING containers
    ↓
For each container:
  ├─ GET http://{ip}:{port}/health
  ├─ Parse response JSON
  ├─ Update DynamoDB:
  │    - health_status: "HEALTHY" | "UNHEALTHY" | "UNREACHABLE"
  │    - last_health_check: timestamp
  │    - health_data: {agents_running, uptime, memory, ...}
  └─ If unhealthy >5 minutes → mark as FAILED
```

### 3. On-Demand Health Check

```
GET /containers/{id}/health
    ↓
Validate user owns container
    ↓
Get health_endpoint from DynamoDB
    ↓
Immediate probe: GET http://{ip}:{port}/health
    ↓
Update DynamoDB cache
    ↓
Return health status to user
```

---

## DynamoDB Schema

### Container Record (Updated)

```json
{
  "pk": "USER#275aa927-...",
  "sk": "CONTAINER#oc-abc123",
  "container_id": "oc-abc123",
  "task_arn": "arn:aws:ecs:...",
  "status": "RUNNING",
  
  // NEW: Endpoint information
  "ip_address": "10.0.1.45",
  "port": 8080,
  "health_endpoint": "http://10.0.1.45:8080/health",
  "api_endpoint": "http://10.0.1.45:8080",
  
  // NEW: Health tracking
  "health_status": "HEALTHY",
  "last_health_check": "2026-04-04T02:06:00Z",
  "health_data": {
    "agents_running": 2,
    "uptime_seconds": 360,
    "memory_mb": 256,
    "cpu_percent": 12.5,
    "version": "0.1.0",
    "agents": [
      {"agent_id": "agent-1", "name": "Assistant", "status": "connected"}
    ]
  },
  
  "created_at": "2026-04-04T02:00:00Z",
  "updated_at": "2026-04-04T02:06:00Z"
}
```

---

## Health Status Values

| Status | Meaning | Action |
|--------|---------|--------|
| `HEALTHY` | `/health` returned 200, agents running | None |
| `UNHEALTHY` | `/health` returned non-200 or error | Wait 5 min, then mark FAILED |
| `UNREACHABLE` | Network timeout or connection refused | Immediate FAILED if persistent |
| `STARTING` | Container RUNNING but no health data yet | Normal during first 30-60s |
| `UNKNOWN` | No health endpoint available | Normal for non-RUNNING tasks |

---

## openclaw-agent `/health` Endpoint

**Expected Response:**

```json
{
  "status": "ok",
  "agents_running": 2,
  "uptime_seconds": 360,
  "memory_mb": 256,
  "cpu_percent": 12.5,
  "version": "0.1.0",
  "timestamp": "2026-04-04T02:06:00Z",
  "agents": [
    {
      "agent_id": "agent-1",
      "name": "Assistant",
      "status": "connected",
      "voice_gateway": "wss://voice.clawtalk.team",
      "last_ping": "2026-04-04T02:05:58Z"
    },
    {
      "agent_id": "agent-2",
      "name": "Helper",
      "status": "disconnected",
      "error": "WebSocket connection failed"
    }
  ]
}
```

**Note:** If openclaw-agent doesn't currently expose this level of detail, we may need to enhance it or start with a simpler response:

```json
{
  "status": "ok",
  "version": "0.1.0",
  "uptime": 360
}
```

---

## VPC Configuration

### Lambda VPC Setup

Orchestrator Lambda **must** run in VPC to reach private container IPs.

**Terraform:**

```hcl
resource "aws_lambda_function" "orchestrator" {
  function_name = "orchestrator-${var.env}"
  
  vpc_config {
    subnet_ids         = var.private_subnet_ids  # Same subnets as containers
    security_groups    = [aws_security_group.orchestrator_lambda.id]
  }
}
```

### Security Groups

**Orchestrator Lambda SG:**

```hcl
resource "aws_security_group" "orchestrator_lambda" {
  name        = "orchestrator-lambda-${var.env}"
  description = "Allow orchestrator Lambda outbound to containers"
  vpc_id      = var.vpc_id
  
  # Outbound to openclaw-agent containers on port 8080
  egress {
    description     = "To openclaw-agent containers"
    from_port       = 8080
    to_port         = 8080
    protocol        = "tcp"
    security_groups = [var.openclaw_agent_security_group_id]
  }
  
  # Outbound to auth-gateway (for token validation)
  egress {
    description = "To auth-gateway"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  
  # Outbound to DynamoDB/SSM via VPC endpoints (if configured)
  egress {
    description = "To AWS services"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
```

**openclaw-agent Container SG:**

```hcl
resource "aws_security_group_rule" "allow_orchestrator_health" {
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

## Implementation Checklist

### Phase 1: Basic Health Tracking

- [ ] Update DynamoDB schema to include `ip_address`, `port`, `health_endpoint`, `api_endpoint`
- [ ] EventBridge handler extracts IP from ECS task attachments
- [ ] Store endpoints in DynamoDB when task reaches RUNNING
- [ ] Configure orchestrator Lambda VPC settings
- [ ] Configure security group rules

### Phase 2: Health Probing

- [ ] Implement `check_container_health()` function
- [ ] Create periodic health checker Lambda (EventBridge trigger)
- [ ] Update DynamoDB with health status
- [ ] Implement failure detection (unhealthy >5 minutes → FAILED)

### Phase 3: API Endpoints

- [ ] Implement `GET /containers/{id}/health` endpoint
- [ ] Return cached health data from DynamoDB
- [ ] Optional: trigger immediate health check on request

### Phase 4: Enhanced Health Data

- [ ] Ensure openclaw-agent `/health` returns detailed metrics
- [ ] Parse and store agent-level health data
- [ ] Display in Flutter app (agent count, connectivity status)

---

## Testing Plan

### Unit Tests

```python
def test_extract_ip_from_task():
    task = {
        'attachments': [{
            'type': 'ElasticNetworkInterface',
            'details': [
                {'name': 'privateIPv4Address', 'value': '10.0.1.45'}
            ]
        }]
    }
    
    result = extract_container_endpoint(task)
    
    assert result['ip_address'] == '10.0.1.45'
    assert result['port'] == 8080
    assert result['health_endpoint'] == 'http://10.0.1.45:8080/health'

def test_health_check_timeout():
    result = check_container_health('oc-123', 'http://10.0.1.45:8080/health')
    
    # Should handle timeout gracefully
    assert result['status'] == 'UNREACHABLE'
    assert 'timeout' in result['error'].lower()
```

### Integration Tests

1. **Spin up container and verify health tracking**
   - POST /containers
   - Wait for RUNNING status
   - Verify `health_endpoint` populated in DynamoDB
   - Call GET /containers/{id}/health
   - Verify health data returned

2. **Simulate unhealthy container**
   - Stop openclaw-agent process inside container (ECS Exec)
   - Wait for health check to fail
   - Verify status changes to UNHEALTHY
   - Wait 5 minutes
   - Verify status changes to FAILED

3. **Network isolation**
   - Remove security group rule allowing orchestrator → container
   - Verify health checks timeout
   - Status should become UNREACHABLE

---

## Cost Impact

**Lambda VPC:**
- ✅ No additional cost for VPC configuration
- ⚠️ Slight cold-start increase (~1-2s) for ENI creation
- ⚠️ NAT Gateway required for outbound internet (existing infrastructure)

**Health Check Lambda:**
- Runs every 1 minute
- ~30 containers = 43,200 invocations/month
- Free tier: 1M requests/month
- **Cost:** $0

**API Calls:**
- DynamoDB: ~86,400 read/writes per month (30 containers × 2 ops × 1440 min/day)
- Free tier: 25 GB storage, 200M requests
- **Cost:** $0 (within free tier)

**Total additional cost:** ~$0/month

---

## Alternatives Considered

### 1. ECS Health Checks Only
- ✅ Simpler (no VPC Lambda)
- ❌ Less detailed (just alive/dead)
- ❌ Slower failure detection
- ❌ No agent-level metrics

### 2. CloudWatch Container Insights
- ✅ Rich metrics (CPU, memory, network)
- ❌ Expensive ($0.30 per task/month)
- ❌ No application-level health (agents running?)
- ❌ Requires additional parsing

### 3. Agent Self-Reporting
- ✅ Push-based (no polling)
- ❌ Requires openclaw-agent changes
- ❌ Network failures = no updates
- ❌ More complex (auth, validation)

**Decision:** Direct health probes provide the best balance of simplicity, detail, and reliability.

---

## Future Enhancements

1. **WebSocket health stream**
   - openclaw-agent pushes health updates in real-time
   - Orchestrator maintains persistent connection
   - Instant failure detection

2. **Auto-restart unhealthy containers**
   - If UNHEALTHY for >5 minutes, trigger ECS task restart
   - Notify user via email/webhook

3. **Health history**
   - Store last 24h of health checks in DynamoDB
   - Visualize uptime/downtime in dashboard
   - Alert on patterns (frequent restarts, memory leaks)

4. **Multi-region health**
   - Cross-region health probes for disaster recovery
   - Route traffic to healthy region

---

**End of Health Check Design**
