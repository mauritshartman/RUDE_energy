# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What is this project?

DoeMaarWatt is a Home Assistant add-on that manages home battery charge cycles via Modbus TCP communication with SMA inverters and a SMA Data Manager. The add-on is packaged as a Docker image targeting multiple architectures (aarch64, amd64, armv7, etc.) using Alpine-based Python 3.13. The add-on
provides its own Web user interface (UI) within Home Assistant. The user interacts with the add-on through this web UI and can do the following:

- Configure the SMA inverters and data manager
- Set the desired mode (see 'Control Modes')
- Start and stop the add-on

## Running the backend (local development)

```bash
cd rootfs/src
python main.py
```

The backend serves on port 8099. Config is stored in `~/dyn_config.json` (local dev) or `/data/dyn_config.json` (production). Logs go to `logs/` (local dev) or `/data/logs/` (production).

## Frontend development

```bash
cd rootfs/src/web
npm install          # install dependencies
npm run dev          # start Vite dev server
npm run build        # build to rootfs/src/web/dist/
```

## Local dev vs. production switches

Several files have hardcoded local-dev lines with commented-out production equivalents. When switching between environments, toggle:

- `rootfs/src/config.py:13` — `DYN_CONFIG_PATH` (local: `~/dyn_config.json`, prod: `/data/dyn_config.json`)
- `rootfs/src/server.py:21` — `FRONTEND_PATH` (local: relative, prod: `/src/web/dist`)
- `rootfs/src/server.py:30` — `LOG_PATH` (local: `logs/`, prod: `/data/logs/`)
- `rootfs/src/price.py:17` — `PRICE_PATH` (local: `prices.json`, prod: `/data/prices.json`)
- `rootfs/src/web/src/stores/config.js:33` — fetch URL (local: `http://localhost:8099/api...`, prod: `/api...`)
- `rootfs/src/web/src/stores/control.js:43,59` — fetch URLs (same swap)

## Architecture overview

### Backend (`rootfs/src/`)

**Entry point and server lifecycle** (`main.py` → `server.py`):

- `DoeMaarWattServer` starts an `aiohttp` web server which manages the controller lifecycle. Based on the configured mode, a specific controller is loaded
- The server waits for `sub_running = True` (set via `POST /api/run`) before starting a controller
- `CONTROLLER_MAP` in `server.py` maps each `ControlMode` to its controller class
- The server also handles HA ingress path prefix rewriting for static file serving. This is necessary to integrate with the Home Assistant Web UI

**Config** (`config.py`):
`DoeMaarWattConfig` loads/saves `dyn_config.json` (which persists the configuration) and exposes all config sections as properties. It also registers all `/api/config/...` GET and POST endpoints directly on the aiohttp router. It provides sensible default values for all configuration options. The add-on allows for a single SMA Data Manager to be configured for the system, and one or more SMA battery inverters. It is assuming a three phase electrical system, so for each inverter the connected phase (L1, L2 or L3) must be configured.

**Control modes** (`mode.py`, `mode_1.py`–`mode_4.py`):
All controllers extend `BaseController` (abstract, `base_controller.py`). Each has an outer reconnect loop and an inner control loop.

| Mode        | Class             | Behavior                                                                               |
| ----------- | ----------------- | -------------------------------------------------------------------------------------- |
| 1 — IDLE    | `Mode1Controller` | Only reads stats from the inverters and data manager without actively controlling them |
| 2 — MANUAL  | `Mode2Controller` | Continuously charge or discharge at a fixed power (W) configured amount                |
| 3 — STATIC  | `Mode3Controller` | Follows a static, rotating 24-hour schedule provided in the config                     |
| 4 — DYNAMIC | `Mode4Controller` | Fetches energy prices and computes an optimal schedule via `DynamicScheduler`          |

**Modbus layer** (`modbus.py`):

- `ModbusManager` wraps `pymodbus` `AsyncModbusTcpClient` and represents an active TCP Modbus session to one or more servers
- It provides parallel operations that address multiple servers at once, or single operations that target a specific server
- Register prefix determines type: `3x` = input register, `4x` = holding register
- Key inverter registers: `40149` = power set point (S32), `40151` = control mode (802=active, 803=inactive)
- Data manager uses `device_id=2`; inverters use `device_id=3`
- Set host to `"test"`, `"debug"`, or `"none"` to use a dummy client (returns stub values)

**Power safety algorithm** (`pbsent.py`):
`calc_PBsent(PBapp, PBnow, PGnow, VGnow, Imax)` computes the safe charge/discharge power (in Watts) that is commanded to the battery inverter (`PBsent`) based on the desired charge/discharge amount (`PBapp`). It also takes lower and upper (dis)charging power limits into account as well as power that might be generated or consumed elsewhere (such as a solar inverter or heat pump). The calculation is for a single electrical phase (L1, L2, or L3).

**Pricing and scheduling** (`price.py`, `dyn_schedule.py`):

- `PriceManager` fetches hourly/sub-hourly energy prices from the Enever API and caches them in `prices.json`
- `DynamicScheduler` uses prices and battery state to create a list of `SchedulePeriod` objects defining optimal charge/discharge power per inverter per time slot

**Stats** (`stats.py`):
`battery_stats()` and `data_manager_stats()` read Modbus registers in parallel and return structured dicts that are stored in `controller.stats` and served via `/api/`.

**Logging** (`logger.py`):
`Logger` is a Singleton. Log files are daily-rotated. The web endpoint `POST /api/log` (with `{"date": "YYYY-MM-DD"}`) returns a log file's contents.

### Frontend (`rootfs/src/web/src/`)

Vue 3 SPA using Naive UI components, Pinia stores, Vue Router, and Chart.js (with `chartjs-adapter-luxon`).

**Stores:**

- `stores/config.js` — fetches and posts all config sections via `/api/config/...`
- `stores/control.js` — polls `/api/` for running status, stats, and prices; controls start/stop via `POST /api/run`

The frontend is built to `rootfs/src/web/dist/` and served as static files by the aiohttp server.
