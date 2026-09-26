# ObserveX

**Enterprise Device Monitoring, Observability & AIOps Platform**

ObserveX is a production-grade, multi-tenant device observability and autonomous operations (AIOps) platform. It provides real-time telemetry streaming, automated health evaluation, predictive anomaly detection, remote command remediation, and strict tenant isolation for enterprise fleet management.

---

## Key Highlights

- **Multi-Tenant Architecture**: Strict logical isolation across organizations, users, devices, alerts, commands, and audit logs with zero cross-tenant data leakage.
- **Onboarding Flow**: Self-service organization onboarding ("Create Environment") establishing independent tenant workspaces.
- **Structured WebSocket Protocol**: Typed message framing (`auth_success`, `heartbeat`, `heartbeat_ack`, `telemetry`, `telemetry_ack`, `command`, `command_result`).
- **Secure Device Enrollment**: Cryptographic enrollment tokens with configurable expiration, usage caps, and bcrypt-hashed device API keys returned only once.
- **AIOps & Health Scoring**: Dynamic multi-factor device health calculation (CPU, RAM, Disk, Error logs) with predictive anomaly alerts.
- **Audited Remediation**: Server-side allowlist for remediation actions (`cleanup_temp`, `restart_service`, `kill_process`) with complete immutable audit trail.
- **Lightweight Modular Frontend**: Zero-dependency vanilla HTML5/CSS/JavaScript SPA featuring a dark glassmorphic design system, real-time WebSocket dashboard, and responsive fleet management views.
- **Comprehensive Test Coverage**: 46 automated tests covering authentication, multi-tenancy boundaries, device RBAC, enrollment security, command validation, and WebSocket protocols.

---

## System Architecture

```
                               ┌────────────────────────────────────────┐
                               │             ObserveX Server            │
                               │                                        │
┌────────────────────────┐     │  ┌──────────────┐   ┌───────────────┐  │
│      Web Dashboard     │◄────┼──┤   REST API   │   │   WebSocket   │  │
│  (Modular Vanilla SPA) │────►│  │ (FastAPI v2) │   │  Hub & Router │  │
└────────────────────────┘     │  └──────┬───────┘   └───────┬───────┘  │
                               │         │                   │          │
                               │  ┌──────┴───────────────────┴───────┐  │
                               │  │   TenantGuard & RBAC Security   │  │
                               │  └──────────────────┬───────────────┘  │
                               │                     │                  │
                               │  ┌──────────────────┴───────────────┐  │
                               │  │   Async SQLAlchemy (PG / SQLite) │  │
                               │  └──────────────────┬───────────────┘  │
                               │                     │                  │
                               │  ┌──────────────────┴───────────────┐  │
                               │  │  Background Health & AIOps Engine│  │
                               │  └──────────────────────────────────┘  │
                               └─────────────────────┬──────────────────┘
                                                     │
                                           WebSocket / REST API
                                                     │
                               ┌─────────────────────┴──────────────────┐
                               │            Windows Device              │
                               │                                        │
                               │   ┌────────────────────────────────┐   │
                               │   │        ObserveX Agent          │   │
                               │   │  - WMI & Hardware Collectors   │   │
                               │   │  - Structured WS Client        │   │
                               │   │  - Service / Process Monitor   │   │
                               │   │  - Remediation Executor        │   │
                               │   └────────────────────────────────┘   │
                               └────────────────────────────────────────┘
```

---

## Directory Structure

```
ObserveX/
├── server/                    # ObserveX Server (FastAPI)
│   ├── auth/                  # JWT auth, passwords, device credential verification
│   ├── authorization/         # TenantGuard, RBAC, device ownership checks
│   ├── models/                # SQLAlchemy ORM models (split per entity)
│   ├── routers/               # REST API endpoints (auth, admin, devices, alerts, etc.)
│   ├── schemas/               # Pydantic v2 schemas and validation rules
│   ├── security/              # Audit logger, rate limiting, security events
│   ├── services/              # Enrollment engine, AIOps scoring service
│   ├── tasks/                 # Async background monitors (stale devices, cleanup)
│   ├── websockets/            # Connection manager, agent & dashboard WS handlers
│   ├── config.py              # Centralized environment configuration
│   ├── database.py            # Async engine, sessionmaker & fallback
│   ├── logging.py             # Structured application logger
│   └── main.py                # App factory, CORS, static SPA mounting
├── agent/                     # ObserveX Windows Agent
│   ├── agent.py               # Main agent async runtime loop
│   ├── build.py               # PyInstaller standalone executable builder
│   ├── config.py              # Agent configuration loader & persistence
│   ├── enrollment.py          # Device enrollment & key exchange
│   ├── heartbeat.py           # Heartbeat state tracking
│   ├── sender.py              # Structured WebSocket & HTTP sender
│   └── service.py             # Windows Service installer/wrapper
├── static/                    # Frontend SPA
│   ├── css/
│   │   ├── design-system.css  # Dark theme tokens, typography, grid, buttons
│   │   ├── components.css     # Navigation, headers, cards, modals, tables
│   │   └── pages.css          # View-specific styles (dashboard, metrics, fleet)
│   ├── js/
│   │   ├── api.js             # Centralized fetch client with JWT interceptors
│   │   ├── app.js             # Bootstrap, session recovery, event wiring
│   │   ├── auth.js            # Auth state, login/logout, tenant identity
│   │   ├── components.js      # Reusable UI component templates
│   │   ├── pages.js           # Page renderers (dashboard, devices, users, etc.)
│   │   ├── router.js          # Client-side hash router
│   │   └── websocket.js       # Real-time WebSocket subscriptions
│   └── index.html             # Clean SPA shell
├── tests/                     # Test Suite (46 Tests)
│   ├── conftest.py            # Test database fixtures, seeds, and client
│   ├── test_auth.py           # Onboarding, login, password & /me tests
│   ├── test_commands.py       # Allowlisted remediation & injection security
│   ├── test_device_access.py  # User-device RBAC & assignment tests
│   ├── test_enrollment.py     # Code lifecycle, max uses, expiry & key hashing
│   ├── test_multi_tenancy.py  # Cross-tenant 404 boundary isolation tests
│   └── test_websocket.py      # Agent & dashboard WebSocket communication
├── requirements.txt           # Python dependencies
└── docker-compose.yml         # PostgreSQL development container
```

---

## Getting Started

### 1. Prerequisites

- Python 3.11+ (tested on Python 3.11, 3.12, 3.13)
- (Optional) Docker for PostgreSQL (`docker compose up -d`)

### 2. Installation

```bash
git clone https://github.com/parassoni04/ObserveX.git
cd ObserveX

# Install server and agent dependencies
python -m pip install -r requirements.txt
```

### 3. Start the Server

```bash
# Start server (defaults to http://127.0.0.1:8000)
# Automatically initializes SQLite if PostgreSQL is not running
python -m uvicorn server.main:app --host 127.0.0.1 --port 8000 --reload
```

Visit **http://127.0.0.1:8000** in your browser to access the ObserveX Web Dashboard.

### 4. Create Your Organization Environment

1. Click **"Create Environment"** on the login screen.
2. Fill in your Organization Name (e.g. `Acme Corp`), Admin Name, Username, and Password.
3. Upon registration, you are immediately logged in to your new, isolated organization workspace.

---

## Agent Usage & Standalone Build

### Enrolling an Agent

To enroll a new device into your organization:

1. In the Web Dashboard, navigate to **Enrollment**.
2. Click **"Generate Enrollment Code"** (e.g., `OX-7F29-A82D`).
3. On the client machine, run:

```bash
python -m agent.agent --server http://127.0.0.1:8000 --enroll OX-7F29-A82D
```

The agent exchanges the one-time code for device credentials, stores them securely in `agent/config.yaml`, and automatically starts streaming metrics over WebSocket.

### Building Standalone Windows Executable

To produce a single-file executable that runs on client Windows machines without Python:

```bash
# Build standalone single-file binary
python agent/build.py --onefile --clean
```

The output executable is generated at:
`dist/ObserveXAgent.exe`

---

## WebSocket Protocol Specification

### 1. Agent Handshake (`/ws/v1/agent/{device_id}?token={api_key}`)

| Direction | Message Type | Payload / Behavior |
|---|---|---|
| Server → Agent | `auth_success` | `{"type": "auth_success", "device_id": 1, "organization_id": 1}` |
| Server → Agent | `error` | `{"type": "error", "message": "Authentication failed", "code": "AUTH_FAILED"}` (closes with 1008) |
| Agent → Server | `heartbeat` | `{"type": "heartbeat"}` |
| Server → Agent | `heartbeat_ack` | `{"type": "heartbeat_ack", "timestamp": "2026-09-20T..."}` |
| Agent → Server | `telemetry` | `{"type": "telemetry", "payload": {"cpu_percent": 18.2, "memory_percent": 42.1, ...}}` |
| Server → Agent | `telemetry_ack`| `{"type": "telemetry_ack"}` |
| Server → Agent | `command` | `{"type": "command", "command_id": 12, "action": "restart_service", "target": "Spooler"}` |
| Agent → Server | `command_result` | `{"type": "command_result", "command_id": 12, "status": "success", "output": "..."}` |

### 2. Dashboard Stream (`/ws/v1/dashboard?token={jwt_token}`)

| Direction | Action | Description |
|---|---|---|
| Client → Server | `subscribe` | Subscribe to live telemetry for a specific `device_id` (RBAC validated) |
| Server → Client | `subscribed` | Confirms subscription and delivers cached latest metrics |
| Server → Client | `telemetry` | Real-time push of device telemetry snapshots |
| Client → Server | `get_online` | Requests array of currently connected online devices in tenant |

---

## Running the Automated Test Suite

The test suite validates security boundaries, tenant isolation, and API integrity:

```bash
# Run entire test suite (46 tests)
python -m pytest tests/ -v

# Run specific suites
python -m pytest tests/test_multi_tenancy.py -v   # Tenant boundary tests
python -m pytest tests/test_enrollment.py -v      # Enrollment & key hashing
python -m pytest tests/test_device_access.py -v   # Device RBAC & assignments
python -m pytest tests/test_commands.py -v        # Command injection protection
python -m pytest tests/test_websocket.py -v       # WebSocket real-time tests
python -m pytest tests/test_auth.py -v            # Authentication & onboarding
```

---

## Security Model

1. **Strict Tenant Isolation**: All database queries are filtered by `organization_id`. Cross-tenant lookup attempts return `404 Not Found` rather than `403 Forbidden` to prevent resource enumeration.
2. **Credential Security**: Agent API keys are generated using cryptographically secure tokens and stored on the server **only as bcrypt hashes**. Plaintext keys are never stored on the server and are only presented once to the agent upon enrollment.
3. **Remediation Allowlisting**: Arbitrary shell execution is forbidden. Only predefined actions (`restart_service`, `kill_process`, `cleanup_temp`) with strict regex-validated targets are accepted.
4. **Audit Logging**: All administrative, authentication, and remediation events are immutably logged with actor identity, timestamp, IP address, and result status.

---

## License

ObserveX is licensed under the [MIT License](LICENSE).
