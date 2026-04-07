# Orchestrator Management Scripts

Python scripts for managing openclaw-agent containers.

## Prerequisites

```bash
# Install dependencies
make install-dev

# Or manually
pip install boto3 tabulate
```

## Scripts

### 1. Launch Container

Create a new openclaw-agent container via the orchestrator API.

```bash
# Launch with defaults (production)
python scripts/launch_container.py --user-id USER_123 --token YOUR_TOKEN

# Launch with custom name
python scripts/launch_container.py --user-id USER_123 --token YOUR_TOKEN --name my-agent

# Launch with configuration
python scripts/launch_container.py --user-id USER_123 --token YOUR_TOKEN \
  --config '{"memory": 512, "cpu": 256}'

# Launch and wait for container to become healthy
python scripts/launch_container.py --user-id USER_123 --token YOUR_TOKEN --wait

# Use local development environment
python scripts/launch_container.py --user-id USER_123 --token YOUR_TOKEN --local

# Use custom URL
python scripts/launch_container.py --user-id USER_123 --token YOUR_TOKEN \
  --url https://custom-api.example.com
```

**Options:**
- `--user-id` - User ID (required for authentication)
- `--token` - Authentication token (required)
- `--name` - Optional container name
- `--config` - Optional configuration as JSON string
- `--env` - Environment (dev/prod), default: dev
- `--local` - Use local development URL (localhost:8000)
- `--url` - Custom base URL (overrides --env and --local)
- `--wait` - Wait for container to become healthy
- `--wait-timeout` - Health check timeout in seconds, default: 300

**Note:** Token format is `user_id:token_string` (minimum 20 characters total).

### 2. List Containers (DynamoDB)

List all containers the orchestrator thinks it's managing.

```bash
# List all containers
python scripts/list_containers.py

# List containers for specific user
python scripts/list_containers.py --user-id USER_123

# Use different environment
python scripts/list_containers.py --env prod
```

**Options:**
- `--env` - Environment (dev/prod), default: dev
- `--user-id` - Filter by specific user ID
- `--profile` - AWS profile name, default: personal
- `--region` - AWS region, default: ap-southeast-2

### 3. List ECS Tasks

List all actual ECS tasks running for openclaw-agent.

```bash
# List all ECS tasks
python scripts/list_ecs_tasks.py

# Use different environment
python scripts/list_ecs_tasks.py --env prod
```

**Options:**
- `--env` - Environment (dev/prod), default: dev
- `--profile` - AWS profile name, default: personal
- `--region` - AWS region, default: ap-southeast-2
- `--cluster` - ECS cluster name, default: clawtalk-dev

### 4. Get Logs

Fetch CloudWatch logs for a specific container.

```bash
# Get logs by container ID
python scripts/get_logs.py oc-abc12345 --user-id USER_123

# Get logs by task ID
python scripts/get_logs.py --task-id abc123def456

# Follow logs in real-time
python scripts/get_logs.py oc-abc12345 --user-id USER_123 --follow

# Show logs from last hour
python scripts/get_logs.py oc-abc12345 --user-id USER_123 --since 60
```

**Options:**
- `--user-id` - User ID (required with container ID)
- `--task-id` - Task ID (alternative to container ID)
- `--env` - Environment (dev/prod), default: dev
- `--follow` / `-f` - Follow logs in real-time
- `--since` - Show logs from last N minutes, default: 30
- `--profile` - AWS profile name, default: personal
- `--region` - AWS region, default: ap-southeast-2

### 5. Execute Shell

Get an interactive shell on a running container.

```bash
# Connect by container ID
python scripts/exec_shell.py oc-abc12345 --user-id USER_123

# Connect by task ARN
python scripts/exec_shell.py --task-arn arn:aws:ecs:...

# Run custom command
python scripts/exec_shell.py oc-abc12345 --user-id USER_123 --command "ls -la"
```

**Options:**
- `--user-id` - User ID (required with container ID)
- `--task-arn` - Task ARN (alternative to container ID)
- `--env` - Environment (dev/prod), default: dev
- `--command` - Command to execute, default: /bin/bash
- `--profile` - AWS profile name, default: personal
- `--region` - AWS region, default: ap-southeast-2
- `--cluster` - ECS cluster name, default: clawtalk-dev
- `--container` - Container name, default: openclaw-agent

**Prerequisites:**
- ECS exec must be enabled on the task
- Session Manager plugin must be installed: [Installation Guide](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html)

### 6. Delete Containers

Stop ECS tasks and remove DynamoDB records.

```bash
# Delete single container
python scripts/delete_containers.py oc-abc12345 --user-id USER_123

# Delete multiple containers
python scripts/delete_containers.py oc-abc12345 oc-def67890 --user-id USER_123

# Delete all containers for a user
python scripts/delete_containers.py --user-id USER_123 --all

# Delete all STOPPED containers
python scripts/delete_containers.py --user-id USER_123 --status STOPPED

# Dry run (show what would be deleted)
python scripts/delete_containers.py --user-id USER_123 --all --dry-run

# Skip confirmation
python scripts/delete_containers.py oc-abc12345 --user-id USER_123 --yes
```

**Options:**
- `--user-id` - User ID (required)
- `--all` - Delete all containers for the user
- `--status` - Delete containers with specific status
- `--env` - Environment (dev/prod), default: dev
- `--dry-run` - Show what would be deleted without deleting
- `--yes` / `-y` - Skip confirmation prompt
- `--profile` - AWS profile name, default: personal
- `--region` - AWS region, default: ap-southeast-2
- `--cluster` - ECS cluster name, default: clawtalk-dev

## Common Workflows

### Launch and manage a container

```bash
# 1. Launch a new container
python scripts/launch_container.py --user-id USER_123 --token YOUR_TOKEN --wait

# 2. Get the container logs
python scripts/get_logs.py oc-abc12345 --user-id USER_123

# 3. Get a shell to debug
python scripts/exec_shell.py oc-abc12345 --user-id USER_123

# 4. When done, delete it
python scripts/delete_containers.py oc-abc12345 --user-id USER_123 --yes
```

### Check container status

```bash
# 1. List all containers in DynamoDB
python scripts/list_containers.py

# 2. List actual running tasks in ECS
python scripts/list_ecs_tasks.py

# 3. Compare to find discrepancies
```

### Debug a container

```bash
# 1. Get the logs
python scripts/get_logs.py oc-abc12345 --user-id USER_123 --since 60

# 2. Get a shell if needed
python scripts/exec_shell.py oc-abc12345 --user-id USER_123

# 3. Check health status (from list output)
python scripts/list_containers.py --user-id USER_123
```

### Clean up stopped containers

```bash
# 1. Check what would be deleted
python scripts/delete_containers.py --user-id USER_123 --status STOPPED --dry-run

# 2. Delete them
python scripts/delete_containers.py --user-id USER_123 --status STOPPED
```

### Monitor logs in real-time

```bash
# Follow logs for a specific container
python scripts/get_logs.py oc-abc12345 --user-id USER_123 --follow
```

## Testing Scripts

### test_end_to_end_flow.py

End-to-end test script that demonstrates the complete user-to-container provisioning flow with verbose logging.

**For detailed AWS setup instructions, see [AWS_TEST_SETUP.md](AWS_TEST_SETUP.md)**

```bash
# AWS Configuration (all services in AWS)
export AWS_PROFILE=personal
export AWS_DEFAULT_REGION=ap-southeast-2

# Run with AWS Lambda endpoints
python scripts/test_end_to_end_flow.py

# Or with explicit configuration
AUTH_GATEWAY_URL=https://z1fm1cdkph.execute-api.ap-southeast-2.amazonaws.com \
ORCHESTRATOR_URL=https://prz6mum7c7.execute-api.ap-southeast-2.amazonaws.com \
AWS_PROFILE=personal \
python scripts/test_end_to_end_flow.py
```

**What it does:**
1. Creates a user in auth-gateway with a unique email
2. Gets an API key back from user creation
3. Validates the API key with auth-gateway
4. Creates a container via the orchestrator using the API key
5. Shows DynamoDB config that gets stored for the user
6. Shows environment variables that will be passed to the container
7. Monitors container status until it reaches RUNNING state
8. Prints verbose logs of all API calls, requests, and responses

**Features:**
- ✅ Color-coded output (success, info, warnings, errors)
- ✅ Full request/response dumps with headers and bodies
- ✅ Masked sensitive values (API keys shown as `xxx...xxx`)
- ✅ Step-by-step progress tracking
- ✅ DynamoDB config inspection
- ✅ Container environment variable preview
- ✅ Explanation of what happens in the container after launch

**Environment Variables:**
- `AUTH_GATEWAY_URL` - Auth gateway Lambda URL (default: AWS Lambda endpoint)
- `ORCHESTRATOR_URL` - Orchestrator Lambda URL (default: AWS Lambda endpoint)
- `DYNAMODB_TABLE` - DynamoDB table name (default: openclaw-containers)
- `DYNAMODB_REGION` - AWS region (default: ap-southeast-2)
- `AWS_PROFILE` - AWS CLI profile to use (default: personal)
- `AWS_DEFAULT_REGION` - AWS region (default: ap-southeast-2)
- `AWS_ACCESS_KEY_ID` - Explicit AWS credentials (optional, uses profile if not set)
- `AWS_SECRET_ACCESS_KEY` - Explicit AWS credentials (optional, uses profile if not set)

**Note:** Do NOT set `DYNAMODB_ENDPOINT` for AWS - it will automatically use AWS DynamoDB.

**Use Cases:**
- Testing the complete user creation → container provisioning flow
- Debugging auth-gateway and orchestrator integration
- Understanding what config gets transferred to containers
- Validating DynamoDB config storage
- Demonstrating the system to new developers
