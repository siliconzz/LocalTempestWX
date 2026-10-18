# LocalTempestWX

A lightweight desktop application that displays live data from a **WeatherFlow Tempest** weather station over the local network using the hub’s UDP broadcast.

No cloud account or internet connection is required once the station is on the same LAN as the computer running the app.

---

## Screenshots

### Full View
![Full view with temperature, feels-like, humidity, wind, and detailed fields](screenshots/full-view.png)

### Compact Mode
![Compact mode showing temperature, feels-like, rain status, humidity, and rapid wind](screenshots/compact-mode.png)

### Settings Window
![Settings window with units, colors, fonts, and field visibility options](screenshots/settings.png)

### Dark Mode
![Dark mode example](screenshots/dark-mode.png)

### Rain Active
![Rain amount highlighted in rain attention color](screenshots/rain-active.png)

> **Note:** Add your own screenshots to a `screenshots/` folder and update the filenames above if needed.

---

## Features

- **Real-time local data** via UDP port `50222` (`obs_st`, `rapid_wind`, `evt_strike`)
- **Desktop window** with large temperature display
- **Compact mode** — click the temperature to shrink the window; click again to restore
- **Always-on-top** toggle
- **Dark / light mode**
- **Customizable units**
  - Temperature (°F / °C)
  - Wind (mph, km/h, m/s, knots)
  - Pressure (inHg, mb, mmHg)
  - Rain (inches / mm)
- **Calculated values**
  - Feels-like temperature (heat index or wind chill)
  - Dew point
- **Rain display**
  - Always shown
  - “No rain” when dry
  - Colored amount when precipitation is accumulating
- **Show / hide individual fields**
- **Font size controls** (temperature and other values)
- **Color customization** (temperature, humidity/rapid wind, rain)
- **12-hour / 24-hour time** and local time vs UTC
- **Lightning strike alert** (optional sound)
- **System tray** support (minimize to tray on close)
- **Start with Windows** (optional)
- **Settings window** that remembers size and position
- **Persistent configuration** saved to `tempest_display_config.json`
- **Cross-platform** (Windows, macOS, Linux) — some features are platform-specific

---

## Requirements

- **Python 3.8+**
- A WeatherFlow **Tempest** (or compatible) station + hub on the same local network
- Optional (for system tray):
  ```bash
  pip install pystray pillow
  ```

No other external dependencies are required for core functionality.

---

## Installation

1. Download or clone this repository.
2. (Optional) Install tray support:
   ```bash
   pip install pystray pillow
   ```
3. Make sure your computer and Tempest hub are on the same network.

---

## Running the App

```bash
python weather_display.py
```

Or use `pythonw` on Windows to avoid a console window:

```bash
pythonw weather_display.py
```

### Windows Shortcut

Create a shortcut with the target:

```text
pythonw "C:\path\to\weather_display.py"
```

---

## Configuration

Settings are saved automatically to:

```
tempest_display_config.json
```

(next to the script)

Open **⚙ Settings** to change:

| Category     | Options                                      |
|--------------|----------------------------------------------|
| Behavior     | Minimize to tray, lightning alert, autostart (Windows) |
| Units        | Temperature, wind, pressure, rain            |
| Time         | Local vs UTC, 12/24-hour                     |
| Colors       | Temperature, humidity/rapid, rain attention  |
| Font sizes   | Value text and large temperature             |
| Show Fields  | Toggle individual data rows                  |

Window size, position, compact mode state, and dark mode are also remembered.

---

## Compact Mode

- Click the large temperature (or nearby text) to enter compact mode.
- Compact mode shows temperature, feels-like, rain status, humidity, and rapid wind.
- Drag the window by clicking and holding the temperature area.
- Resize using the grip in the bottom-right corner.
- Click the temperature again to return to the full view.

---

## Data Displayed

| Field              | Source / Notes                          |
|--------------------|-----------------------------------------|
| Temperature        | Station observation                     |
| Feels Like         | Calculated (heat index / wind chill)    |
| Humidity           | Station observation                     |
| Rapid Wind         | High-frequency wind updates             |
| Pressure           | Station observation                     |
| Wind Average/Gust/Lull | Station observation                 |
| Wind Direction     | Compass + degrees                       |
| Dew Point          | Calculated                              |
| UV Index           | Station observation                     |
| Solar Radiation    | Station observation                     |
| Rain               | Interval accumulation (“No rain” if 0)  |
| Illuminance        | Station observation                     |
| Battery            | Station voltage                         |
| Last Observation   | Timestamp of latest full observation    |
| Device             | Serial number                           |

---

## How It Works

The app listens on UDP port **50222** for broadcasts from the Tempest hub. It parses:

- `obs_st` — full observation (~every minute)
- `rapid_wind` — frequent wind updates
- `evt_strike` — lightning events

All processing happens locally. No data is sent to any external service.

---

## Cross-Platform Notes

| Feature              | Windows | macOS | Linux |
|----------------------|---------|-------|-------|
| Core display         | Yes     | Yes   | Yes   |
| System tray          | Yes*    | Yes*  | Yes*  |
| Start with OS        | Yes     | No    | No    |
| Rounded corners      | Win11   | No    | No    |
| Lightning sound      | Yes     | Limited | Limited |

\*Requires `pystray` + `Pillow`.

---

## Project Structure

```
.
├── weather_display.py          # Main application
├── tempest_display_config.json # Auto-generated settings (created on first run)
├── screenshots/                # Optional screenshots for the README
│   ├── full-view.png
│   ├── compact-mode.png
│   ├── settings.png
│   ├── dark-mode.png
│   └── rain-active.png
└── README.md
```

---

## Credits

**Local Tempest WX**  
by silicon  
https://orangedragon.co/labs/dev

Based on the WeatherFlow Tempest UDP broadcast specification:  
https://apidocs.tempestwx.com/reference/tempest-udp-broadcast

---

## License

This project is provided as-is for personal and educational use. Feel free to modify and share.

---

## Troubleshooting

| Issue                        | Possible Fix                                      |
|-----------------------------|---------------------------------------------------|
| No data appears             | Confirm same network as hub; check firewall for UDP 50222 |
| Bind error                  | Another program may already be using port 50222   |
| Tray icon missing           | Install `pystray` and `Pillow`                    |
| Settings window off-screen  | Delete `tempest_display_config.json` and restart  |
| Lightning sound not working | Expected on non-Windows; enable in Settings       |

---

Enjoy your local weather display.
