# SETUP GUIDE — BACnet Simulator

Detailed setup, usage, and testing guide (Windows).

---

## 1. Installation

### 1.1 Install Python 3.11+
- Download from https://www.python.org/downloads/
- Check **"Add Python to PATH"** during installation

### 1.2 Clone the project
```bash
git clone https://github.com/toeittipon/bacnet-sim.git
cd bacnet-sim
```

### 1.3 Create Virtual Environment
```bash
python -m venv venv
venv\Scripts\activate
```

### 1.4 Install dependencies
```bash
pip install -r requirements.txt
```

| Package | Purpose |
|---------|---------|
| bacpypes3 | BACnet engine (asyncio) |
| fastapi | REST API + WebSocket |
| uvicorn | ASGI server |
| pydantic | Data validation |
| python-multipart | File upload (CSV import) |
| pyserial | Serial port detection (MS/TP) |
| pywebview | Desktop window (Edge WebView2) |
| requests | Backend health check |

---

## 2. Running

### 2.1 Desktop mode (pywebview window)
```bash
python -m backend.main
```
- Opens a desktop window automatically
- Close window = close application

### 2.2 Browser mode (for development)
```bash
python -m backend.main --no-gui
```
- Open browser at http://127.0.0.1:8736
- Stop: click **Shutdown** button in the UI sidebar

---

## 3. Using the UI

### 3.1 Start/Stop Simulator
- Click **Start** (green button, top-right) to start the BACnet engine
- Click again (**Stop**, red) to stop
- When started, the device broadcasts I-Am and accepts ReadProperty/WriteProperty

### 3.2 BACnet/IP Settings (left sidebar)
- **Interface**: Auto-detect (recommended) or select a specific IP
- **UDP Port**: 47808 (BACnet standard) — change if another BACnet program is running
- **Device Instance**: 123456 (must be unique on the network)
- Click **Apply connection** to restart the engine with new settings

### 3.3 Add/Edit/Delete Points
- Click **Add point** to create a new object (select type, name, value, units)
- **Click any Present Value** in the table to edit inline
  - Binary types: dropdown (Active/Inactive)
  - Multi-state types: dropdown with state labels
  - Analog/string types: text input
- Click the pencil icon to open full edit modal
- Click the trash icon to delete

### 3.4 Priority Array (Commandable Objects)
- Open edit modal for a commandable object (AO/BO/MO/BV/MSV)
- See the **Priority Array (P1-P16)** at the bottom
- Click any slot to set a value, leave empty to relinquish (NULL)
- Present Value auto-calculates from the highest priority non-NULL slot
- **Clear all** button relinquishes all slots (PV reverts to relinquish default)

### 3.5 Random Simulation
- Open edit modal for an analog point (AI/AO/AV)
- Enable **Random simulation** and set Min, Max, Interval
- Values change automatically — green dot in the table indicates active random
- Visible in real-time via WebSocket (both UI and Node-RED)

### 3.6 CSV Import/Export
- **Export CSV**: click button in sidebar — opens Save As dialog
- **Import CSV**: click button → select file → choose import mode:
  - **Overwrite**: update duplicates, add new, keep existing points not in CSV
  - **Skip**: add new only, skip duplicates
  - **Replace All**: delete everything, import from CSV only

---

## 4. Testing with YABE

[YABE](https://sourceforge.net/projects/yetanotherbacnetexplorer/) (Yet Another BACnet Explorer) is a free BACnet browser/reader/writer.

> **Important**: YABE and the simulator **cannot run on the same machine** because both need UDP port 47808. Use YABE on a different machine on the same network, or use Node-RED / test_bacnet.py for same-machine testing.

### 4.1 Setup
1. Install YABE on a different machine
2. Run BACnet Simulator and click **Start**
3. Allow UDP 47808 through Windows Firewall:
   ```
   netsh advfirewall firewall add rule name="BACnet" dir=in action=allow protocol=UDP localport=47808
   ```

### 4.2 Discover Device
1. Open YABE → Add BACnet/IP
2. Set **Local Endpoint** to the YABE machine's IP
3. Click **Start** → YABE sends Who-Is → should find **Building.Simulator (123456)**

### 4.3 Read Values
- Click device → see all 50 objects
- Click an object → see presentValue, units, etc.

### 4.4 Write Values
- **AV (non-commandable)**: write presentValue directly
- **BV/MSV (commandable)**: must specify **Priority** (e.g. 8)
- **AI (read-only)**: write → **WRITE_ACCESS_DENIED** (correct behavior)

---

## 5. Testing with Node-RED

### 5.1 Install Node-RED + BACnet node
```bash
npm install -g node-red
cd ~/.node-red
npm install node-red-contrib-bacnet
node-red
```
Open http://127.0.0.1:1880

### 5.2 Import Test Flow
1. Menu **hamburger → Import → Clipboard**
2. Paste contents of `nodered_test_flows.json`
3. Configure the **BACnet-Client** node: port `47809`, timeout `10000`
4. Configure the **BACnet-Device** node: address = simulator's IP

### 5.3 Read All Objects
- Click **Read All** inject → reads all 50 objects via ReadPropertyMultiple
- Results split into 10 debug outputs by type (AI, AO, AV, BI, BO, BV, MSI, MO, MSV, CSV)

### 5.4 Write Values
Use `BACnet-Write` node with `msg.payload`:
```js
// Non-commandable (AV) — no priority needed
msg.payload = {
  deviceIPAddress: "192.168.x.x",
  objectId: { type: 2, instance: 1 },
  propertyId: 85,
  values: [{ type: 4, value: 25.5 }]   // tag 4 = REAL
};

// Commandable (BV) — needs priority
msg.payload = {
  deviceIPAddress: "192.168.x.x",
  objectId: { type: 5, instance: 0 },
  propertyId: 85,
  values: [{ type: 9, value: 1 }],      // tag 9 = ENUM (1=active)
  options: { priority: 8 }
};

// Relinquish (NULL)
msg.payload = {
  deviceIPAddress: "192.168.x.x",
  objectId: { type: 5, instance: 0 },
  propertyId: 85,
  values: [{ type: 0, value: null }],    // tag 0 = NULL
  options: { priority: 8 }
};
```

**Application Tags**: `0`=NULL, `2`=UNSIGNED (multi-state), `4`=REAL (analog), `7`=STRING, `9`=ENUM (binary)

---

## 6. Automated Test (bacpypes3 client)

```bash
# Start simulator and click Start, then in another terminal:
python test_bacnet.py
```

Expected result:
```
  10/10 passed
```

| # | Test | Expected |
|---|------|----------|
| 1 | Who-Is → I-Am | Device 123456 found |
| 2 | ReadProperty device name | "Building.Simulator" |
| 3 | ReadProperty AI:0 PV | Numeric value |
| 4 | ReadProperty AV:1 PV | Numeric value |
| 5 | WriteProperty AV:1 (non-commandable) | Write succeeds, read back matches |
| 6 | WriteProperty AI:0 (read-only) | **WRITE_ACCESS_DENIED** |
| 7 | WriteProperty BV:0 commandable + P8 | Write succeeds via priority array |
| 8 | ReadPropertyMultiple (2 objects) | Multiple properties returned |
| 9 | ReadProperty MSV:1 | PV + numberOfStates |
| 10 | ReadProperty CSV:0 | "HQ Tower A" |

---

## 7. Troubleshooting

### Device not found / Unable to connect
- Check that **Start** was clicked in the UI (status = green)
- Check **firewall**: allow UDP 47808
- Check **interface**: if multiple NICs, select the one on the same subnet as the client
- If another BACnet program (YABE, etc.) is running → port conflict → close it or change port

### WRITE_ACCESS_DENIED
- **AI/BI/MSI**: read-only by BACnet standard — this is correct behavior
- **Commandable objects** (AO/BO/MO/BV/MSV): must include **priority** (1-16) in the write request

### pywebview window doesn't open
- Ensure **Edge WebView2 Runtime** is installed (included in Windows 10/11 by default)
- If missing: download from https://developer.microsoft.com/en-us/microsoft-edge/webview2/

### Port 47808 already in use
- Change UDP Port in BACnet/IP settings → Apply
- Or close the other program using that port
