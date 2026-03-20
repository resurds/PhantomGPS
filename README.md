# PhantomGPS 🛰️
### iOS USB Location Spoofer for Windows 11

Spoof your iPhone's GPS location over a USB cable. Works with iOS 16, 17, 18, and 26.

---

## What You'll Need

- A Windows 11 PC
- An iPhone with **Developer Mode enabled**
- A USB cable
- An internet connection

---

## Step 1 — Install Python 3.12

> ⚠️ You must use Python 3.12 specifically. Newer versions (3.13, 3.14) are not compatible.

1. Go to **https://www.python.org/downloads/release/python-3120/**
2. Scroll to the bottom and click **Windows installer (64-bit)**
3. Run the downloaded `.exe`
4. ⚠️ **Before clicking Install Now**, tick the box at the bottom that says **"Add Python to PATH"**
5. Click **Install Now** and wait for it to finish

**Verify it worked** — open Command Prompt (`Win + R` → type `cmd` → Enter) and run:
```
py -3.12 --version
```
You should see: `Python 3.12.x`

---

## Step 2 — Install libimobiledevice

This lets the app detect your iPhone over USB.

1. Go to **https://github.com/libimobiledevice-win32/imobiledevice-net/releases**
2. Under the latest release, download the file ending in **`-win-x64.zip`**
3. Right-click the zip → **Extract All** → extract to `C:\imobiledevice`
4. Add it to PATH:
   - Press `Win + S` → search **"Edit the system environment variables"** → open it
   - Click **"Environment Variables..."**
   - In the bottom box (System variables), find **Path** → click **Edit**
   - Click **New** → type `C:\imobiledevice`
   - Click **OK** on all windows

**Verify it worked** — open a new Command Prompt and run:
```
idevice_id -l
```
No error message = success ✅ (blank output is fine if phone isn't plugged in yet)

---

## Step 3 — Install iTunes (from Apple, not Microsoft Store)

> ⚠️ The Microsoft Store version does NOT work. You must download directly from Apple.

1. Go to **https://www.apple.com/itunes/download/win64**
2. Download and install iTunes
3. You don't need to open or use iTunes — it just installs the correct iPhone USB drivers

---

## Step 4 — Install Python libraries

Open Command Prompt and run these one at a time:

```
py -3.12 -m pip install PyQt6 PyQt6-WebEngine
```
```
py -3.12 -m pip install pymobiledevice3
```

Each may take 2–3 minutes. Just let them run.

---

## Step 5 — Enable Developer Mode on your iPhone

1. On your iPhone, go to **Settings → Privacy & Security → Developer Mode**
2. Toggle **Developer Mode on**
3. Your iPhone will restart — tap **"Turn On"** when prompted after reboot

---

## Step 6 — Set up the app files

1. Create a folder called **files** on your Desktop
2. Place `main.py` and `PhantomGPS.bat` inside it

Your folder should look like this:
```
Desktop\
└── files\
    ├── main.py
    └── PhantomGPS.bat
```

---

## Step 7 — Pair your iPhone

1. Plug your iPhone into your PC via USB
2. Tap **"Trust This Computer"** on your iPhone when prompted
3. Enter your passcode if asked
4. Open Command Prompt and run:
```
idevicepair pair
```
5. Tap **Trust** on your iPhone again if it asks

You should see: `SUCCESS: Paired with device ...`

---

## Step 8 — Run the app

1. Make sure your iPhone is plugged in
2. Double-click **PhantomGPS.bat** on your Desktop
3. Click **Yes** when Windows asks for administrator permission
4. The app will open — wait a few seconds for the tunnel to connect

You'll know it's ready when the sidebar shows:
- ✓ **iPhone connected** (in green)
- ✓ **Tunnel ready** (in green)

---

## How to Use

### 📍 Instant Mode (teleport to any location)

1. Make sure **Instant** mode is selected (top of sidebar)
2. Click anywhere on the map to drop a pin
3. Or use the **Quick Locations** dropdown to pick a city
4. Or type coordinates manually in the Lat/Lng fields
5. Click **▶ START SPOOFING**
6. Open Maps (or any app) on your iPhone — it will show the fake location

### 🚶 Walk Mode (simulate walking along roads)

1. Switch to **Walk Route** mode using the radio button
2. **Left-click** the map to set your starting position
3. **Right-click** the map to set your destination
4. The app fetches a real walking route from OpenStreetMap
5. Adjust your walk speed using the slider (1–20 km/h)
6. Click **▶ START SPOOFING** — your GPS will walk the route step by step
7. The app shows your progress and stops automatically when you arrive

### ↺ Reset Location

Click **↺ Reset Location** to restore your iPhone's real GPS location.

---

## Important Notes

- **Keep your iPhone plugged in** — the spoof stops the moment you unplug the cable. This is an iOS limitation.
- **Always run as administrator** — use the `PhantomGPS.bat` file, not the `.py` file directly
- **Internet required for Walk Mode** — routes are fetched live from OpenStreetMap
- Some apps (banking apps, certain games) use additional signals and may detect spoofing

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `idevice_id` not recognised | Add `C:\imobiledevice` to PATH and open a new Command Prompt |
| Device not detected | Run `idevicepair pair` and tap Trust on iPhone |
| Tunnel fails to start | Make sure you're running as administrator via the .bat file |
| Location doesn't change | Check Developer Mode is on: Settings → Privacy & Security → Developer Mode |
| App opens multiple times | Always use `PhantomGPS.bat`, never double-click `main.py` directly |
| Walk route not loading | Check your internet connection — routes need OpenStreetMap access |
| iOS 17+ not working | Make sure you ran: `py -3.12 -m pymobiledevice3 mounter auto-mount` at least once |

---

## File Structure

```
Desktop\files\
├── main.py              ← Main application
└── PhantomGPS.bat       ← Launch this to run the app
```

---

## Requirements Summary

| Component | Version |
|---|---|
| Windows | 11 |
| Python | 3.12 (exactly) |
| PyQt6 | Latest |
| PyQt6-WebEngine | Latest |
| pymobiledevice3 | Latest |
| libimobiledevice | Latest (win-x64) |
| iTunes | Latest (from apple.com) |
| iPhone iOS | 16, 17, 18, or 26 |
