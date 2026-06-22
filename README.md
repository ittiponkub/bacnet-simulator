# BACnet Simulator

BACnet/IP device simulator with a modern dark glassmorphism UI. Simulates a full BMS (Building Management System) device with 50 points across all standard BACnet object types.

![Python](https://img.shields.io/badge/Python-3.11+-blue)
![BACnet](https://img.shields.io/badge/BACnet%2FIP-UDP%2047808-green)
![License](https://img.shields.io/badge/License-MIT-yellow)

## Features

- **BACnet/IP** — Full protocol support: Who-Is/I-Am, ReadProperty, ReadPropertyMultiple, WriteProperty
- **10 Object Types** — AI, AO, AV, BI, BO, BV, MSI, MO, MSV, CharacterString Value
- **Commandable + Priority Array** — AO/BO/MO always commandable, AV/BV/MSV optionally. Editable P1-P16 from UI
- **Read-Only Enforcement** — AI/BI/MSI reject WriteProperty with `WRITE_ACCESS_DENIED`
- **Desktop App** — pywebview window (Edge WebView2), no browser needed
- **Dark Glassmorphism UI** — Modern control-room style interface
- **Live Updates** — WebSocket pushes value changes to UI in real-time
- **Random Simulation** — Auto-generate analog values within configurable range
- **CSV Import/Export** — Backup and restore points with 3 import modes (overwrite/skip/replace)
- **Start/Stop Engine** — Control BACnet stack from the UI
- **Loading Screen** — Splash screen while engine initializes
- **Help Page** — Built-in documentation in Thai and English (BACnet protocol reference included)
- **Build to .exe** — PyInstaller build script, no Python needed on target machine
- **Node-RED Compatible** — Included test flow for read all objects

## Quick Start

```bash
# Clone
git clone https://github.com/ittiponkub/bacnet-simulator.git
cd bacnet-simulator

# Setup
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Linux/macOS
pip install -r requirements.txt

# Run (desktop window)
python -m backend.main

# Run (browser mode)
python -m backend.main --no-gui
# Open http://127.0.0.1:8736
```

## Usage

1. Click **Start** (green button, top-right) to start the BACnet engine
2. Device broadcasts I-Am on the network — discoverable by YABE, Node-RED, etc.
3. **Add/Edit/Delete** points from the UI
4. **Click any Present Value** in the table to edit inline (dropdown for binary/multi-state)
5. Edit a commandable point to see and modify the **Priority Array (P1-P16)**
6. Enable **Random Simulation** on analog points for auto-changing values
7. **Export/Import CSV** to backup and restore point configurations

## Architecture

```
  MAIN THREAD                       BACKGROUND THREAD (daemon)
  ┌───────────────┐                ┌──────────────────────────┐
  │  pywebview     │  HTTP/WS      │    asyncio event loop     │
  │  (WebView2)    │◄────────────►│                           │
  │                │ 127.0.0.1     │  bacpypes3 Application    │
  │  glassmorphism │               │  ├─ BACnet/IP (UDP 47808)│◄── YABE / Node-RED
  │  dark UI       │               │  └─ 50 BACnet objects     │
  └───────────────┘                │                           │
                                   │  FastAPI (uvicorn)        │
                                   │  ├─ REST: CRUD + config   │
                                   │  └─ WebSocket: live push  │
                                   └──────────┬───────────────┘
                                              │ persist
                                              ▼
                                       config/devices.json
```

## Tech Stack

| Component | Technology |
|-----------|-----------|
| BACnet Engine | [bacpypes3](https://github.com/JoelBender/bacpypes3) (asyncio) |
| API Server | FastAPI + uvicorn |
| Desktop Window | pywebview (Edge WebView2) |
| Frontend | HTML/CSS/JS (no build step) |
| Data Validation | Pydantic v2 |
| Persistence | JSON file (config/devices.json) |

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/config` | Connection + device settings |
| PUT | `/api/config` | Update settings (auto-restarts engine) |
| GET | `/api/objects` | List all objects with values |
| POST | `/api/objects` | Create a new object |
| PUT | `/api/objects/{type}/{instance}` | Update object value/properties |
| DELETE | `/api/objects/{type}/{instance}` | Delete an object |
| PUT | `/api/objects/{type}/{instance}/priority` | Write a priority array slot |
| PUT | `/api/objects/{type}/{instance}/random` | Configure random simulation |
| POST | `/api/engine/start` | Start BACnet engine |
| POST | `/api/engine/stop` | Stop BACnet engine |
| GET | `/api/engine/status` | Engine running status |
| GET | `/api/export/csv` | Export points as CSV |
| POST | `/api/import/csv?mode=overwrite` | Import points from CSV |
| GET | `/api/interfaces` | List network interfaces |
| GET | `/api/serial-ports` | List serial ports |
| WS | `/api/ws` | WebSocket for live updates |
| POST | `/api/shutdown` | Shutdown application |

## Default Device Profile

- **Device**: Building.Simulator (instance 123456)
- **50 points**: 5 of each type (AI, AO, AV, BI, BO, BV, MSI, MO, MSV, CSV)
- Realistic BMS names: AHU temperatures, valve positions, fan commands, schedules, etc.
- Auto-generated on first run (`config/devices.json`)

## Testing

### Automated Test (bacpypes3 client)
```bash
# Start simulator and click Start, then in another terminal:
python test_bacnet.py
# → 10/10 passed (Who-Is, ReadProperty, WriteProperty, RPM, commandable, read-only denial)
```

### Node-RED
Import `nodered_test_flows.json` into Node-RED to read all 50 objects split by type.

**Required**: `node-red-contrib-bacnet`

> **Note**: YABE and the simulator cannot run on the same machine (both need UDP port 47808). Use YABE on a different machine, or use Node-RED / test_bacnet.py for same-machine testing.

## Firewall

BACnet/IP uses UDP port 47808. On Windows:
```
netsh advfirewall firewall add rule name="BACnet" dir=in action=allow protocol=UDP localport=47808
```

## Project Structure

```
bacnet-simulator/
├── backend/
│   ├── main.py            # Entry point (pywebview + asyncio)
│   ├── desktop.py         # pywebview window management
│   ├── api.py             # FastAPI REST + WebSocket
│   ├── bacnet_engine.py   # BACnet/IP application + priority array
│   ├── object_factory.py  # Config → bacpypes3 object mapping
│   ├── config_store.py    # Load/save devices.json
│   └── models.py          # Pydantic models
├── frontend/
│   ├── index.html         # Main UI
│   ├── loading.html       # Loading splash screen
│   ├── help.html          # Help page (TH/EN)
│   ├── css/style.css      # Glassmorphism dark theme
│   └── js/app.js          # Interactive UI + WebSocket
├── assets/
│   └── icon.ico           # Application icon
├── config/
│   └── devices.json       # Auto-generated on first run
├── requirements.txt
├── build.bat              # Build .exe with PyInstaller
├── test_bacnet.py         # Automated BACnet/IP test (10 cases)
├── nodered_test_flows.json
├── SETUP_GUIDE.md         # Detailed setup & testing guide
└── README.md
```

## License

MIT
