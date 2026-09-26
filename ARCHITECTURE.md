# ObserveX Architecture & Technical Specification

This document provides the detailed technical design, component interactions, security model, and data schemas for ObserveX v2.0.0.

---

## 1. System Topology

```mermaid
graph TB
    subgraph "Clients"
        Browser["Admin & User Browsers (SPA)"]
        Agent["ObserveX Windows Agent (.exe)"]
    end

    subgraph "Edge / Ingress"
        FastAPI["FastAPI App Factory (main.py)"]
        CORS["CORS & Request Normalizer"]
        RateLimiter["IP Rate Limiter"]
    end

    subgraph "Core Server Services"
        Auth["Authentication & JWT Handler"]
        TenantGuard["TenantGuard Scoping Engine"]
        WSManager["WebSocket Connection Manager"]
        AIOps["AIOps & Health Engine"]
        AuditLogger["Audit Logging Engine"]
    end

    subgraph "Background Engine"
        StaleTask["Device Stale Health Detector"]
        CleanupTask["Telemetry Retention Cleanup"]
        AlertTask["Alert Rule Evaluator"]
    end

    subgraph "Persistence Layer"
        SQLAlchemy["Async SQLAlchemy 2.0 Engine"]
        Database[("PostgreSQL 16 / SQLite Fallback")]
    end

    Browser -->|HTTP REST + JWT| RateLimiter
    Browser -->|WebSocket + JWT| WSManager
    Agent -->|HTTP Enrollment| RateLimiter
    Agent -->|WebSocket + API Key| WSManager

    RateLimiter --> CORS --> FastAPI
    FastAPI --> Auth
    FastAPI --> TenantGuard

    TenantGuard --> SQLAlchemy
    WSManager --> SQLAlchemy
    AIOps --> SQLAlchemy
    AuditLogger --> SQLAlchemy

    StaleTask --> SQLAlchemy
    CleanupTask --> SQLAlchemy
    AlertTask --> SQLAlchemy

    SQLAlchemy --> Database
```

---

## 2. Multi-Tenancy & Security Model

### Tenant Isolation Guarantee

ObserveX operates on a **shared-database, isolated-schema/tenant** pattern:

1. **Root Entity**: Every organization is represented by the `Organization` model.
2. **Tenant Foreign Key**: All core business entities (`users`, `devices`, `enrollment_codes`, `alerts`, `alert_rules`, `command_logs`, `audit_logs`, `metric_snapshots`) contain a non-nullable `organization_id` column.
3. **TenantGuard Helper**:
   `TenantGuard.get_or_404(Model, id, current_user, db)` guarantees that any attempt by a user from Tenant A to access an ID belonging to Tenant B raises `HTTPException(404, "Not found")`.
   - **Why 404 instead of 403?** Returning 403 leaks the existence of IDs across tenant boundaries (enabling sequential ID enumeration). Returning 404 provides zero-knowledge isolation.
4. **Device RBAC**:
   - **Administrators**: Can view, configure, and issue commands to any device belonging to their organization.
   - **Standard Users**: Can only view devices explicitly assigned to them via the `DeviceUserAssignment` relation.

---

## 3. WebSocket Infrastructure

### Connection Management (`server/websockets/manager.py`)

The `ConnectionManager` maintains two distinct connection pools:

```mermaid
sequenceDiagram
    autonumber
    participant Agent as ObserveX Agent
    participant Hub as WS Connection Manager
    participant DB as Database
    participant Dash as Web Dashboard

    Note over Agent, Hub: Agent Handshake
    Agent->>Hub: GET /ws/v1/agent/{device_id}?token={api_key}
    Hub->>DB: Verify bcrypt hash of api_key
    alt Invalid Credential
        Hub-->>Agent: {"type": "error", "code": "AUTH_FAILED"} (Close 1008)
    else Valid Credential
        Hub-->>Agent: {"type": "auth_success", "device_id": id, "organization_id": org_id}
        Hub->>DB: Update device is_online=True, last_seen=now()
    end

    Note over Agent, Dash: Telemetry Pipeline
    Agent->>Hub: {"type": "telemetry", "payload": {cpu, ram, disk}}
    Hub-->>Agent: {"type": "telemetry_ack"}
    Hub->>Hub: Cache in latest_metrics[device_id]
    Hub->>Dash: Broadcast to subscribed dashboards in org
    opt Every Nth snapshot
        Hub->>DB: Write MetricSnapshot
    end

    Note over Dash, Agent: Command Execution Pipeline
    Dash->>Hub: POST /api/v1/commands {"action": "restart_service", "target": "Spooler"}
    Hub->>DB: Log Command (status="pending")
    Hub->>Agent: {"type": "command", "command_id": 42, "action": "restart_service", "target": "Spooler"}
    Agent->>Agent: Validate action & execute command
    Agent->>Hub: {"type": "command_result", "command_id": 42, "status": "success", "output": "..."}
    Hub->>DB: Update Command (status="success", completed_at=now())
    Hub->>Dash: Broadcast command_result
```

---

## 4. Database Entity Relationships

```mermaid
erDiagram
    organizations ||--o{ users : "has many"
    organizations ||--o{ devices : "has many"
    organizations ||--o{ enrollment_codes : "has many"
    organizations ||--o{ alert_rules : "has many"
    organizations ||--o{ alerts : "has many"
    organizations ||--o{ command_logs : "has many"
    organizations ||--o{ audit_logs : "has many"

    users ||--o{ device_user_assignments : "assigned"
    devices ||--o{ device_user_assignments : "assigned"

    devices ||--o{ metric_snapshots : "streams"
    devices ||--o{ device_static_info : "has one"
    devices ||--o{ device_software : "has many"
    devices ||--o{ device_windows_events : "has many"

    organizations {
        int id PK
        string name
        string slug UK
        datetime created_at
    }

    users {
        int id PK
        int organization_id FK
        string email UK
        string username UK
        string hashed_password
        string role "admin | user"
        bool is_active
    }

    devices {
        int id PK
        int organization_id FK
        string device_uuid UK
        string hostname
        string api_key_hash
        string status "active | revoked | offline"
        bool is_online
        datetime registered_at
        datetime last_seen
    }

    enrollment_codes {
        int id PK
        int organization_id FK
        string code UK
        int max_uses
        int usage_count
        datetime expires_at
        bool is_revoked
    }

    command_logs {
        int id PK
        int organization_id FK
        int device_id FK
        int requested_by FK
        string command_type
        string target
        string status "pending | sent | success | failed"
        string result_output
        datetime created_at
        datetime completed_at
    }
```

---

## 5. Security & Attack Surface Hardening

| Vector | Mitigation Mechanism |
|---|---|
| **SQL Injection** | Parameterized queries enforced across 100% of routes via SQLAlchemy 2.0 ORM expressions. |
| **Command Injection** | Strict server-side allowlist (`restart_service`, `kill_process`, `cleanup_temp`). Targets are validated against `^[a-zA-Z0-9_.\- ]{1,128}$`. Arbitrary shell scripts are completely disallowed. |
| **Credential Theft** | Device API keys are hashed with bcrypt. Plaintext credentials are never saved on disk or in the database. |
| **Cross-Tenant Enumeration** | All endpoints enforce `TenantGuard.get_or_404()`. Cross-tenant lookup returns 404 rather than 403. |
| **Credential Reuse / Code Theft** | Enrollment codes support `max_uses` (typically single-use) and time-based expiration. Revocation is instantaneous via admin API. |
| **DoS via Telemetry Flooding** | Telemetry ingestion rate is throttled, with lightweight in-memory ring buffers and batched database writes. |
