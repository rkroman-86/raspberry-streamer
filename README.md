# Raspberry Streamer

Audio streamer: Raspberry Pi Zero 2 W running moOde (+ PCM5102 DAC) driven by a
Waveshare ESP32-S3 touch screen running Tasmota / Berry / HASPmota, linked by UART.

## Layout

| Folder   | Content                                                              |
|----------|----------------------------------------------------------------------|
| `esp/`   | Mirror of the Tasmota filesystem (`*.be`, `pages.jsonl`, `A/*.png`)  |
| `esp/ui/`| Phone web page `http://192.168.1.75/ui` (AndroRadio look): `ui.be` driver + HTML/CSS/JS |
| `pi/`    | Pi side: `espbridge.py` (`/opt/espbridge/`) and its systemd service  |
| `tools/` | `tasmota_sync.py`: push / pull files, run commands, read the log     |
| `docs/`  | Notes, protocol, wiring                                              |

## Device

- ESP32-S3 (Tasmota): `192.168.1.75`
- Raspberry Pi Zero 2 W (moOde): `rk@192.168.1.35`, code in `/opt/espbridge`, service `espbridge`

## Web page `/ui`

`esp/ui/ui.be` is a Berry driver loaded at the end of `main_prog.be`. It serves the
files of the `/ui` folder and a small JSON API (`/ui/api?a=state|lib|play|toggle|stop|vol|src|fsave|fdel|fmove`).
The phone's browser does the heavy work (Radio Browser search, local stations, tuner,
album art from MusicBrainz / Cover Art Archive / iTunes). Favorites (20) and history (10)
live on the ESP in `/ui/library.json` (never pushed or pulled by `tasmota_sync.py`).

Stations played from `/ui` are added to moOde's Radio library (`pi/espbridge/moode_radio.py`):
the ESP sends `STATION <json>` after `PLAY`, the Pi saves the Radio Browser logo in
`radio-logos/` and calls moOde's own `new_station` command. moOde and the ESP screen then
show the logo. Stations already in moOde (same URL) are left untouched.

AirPlay (`pi/espbridge/airplay.py`): shairport-sync is kept in AirPlay 1 (`service_type =
"classic"`, old iPads get no audio in AirPlay 2) and also sends its metadata over UDP
(127.0.0.1:5556). The Pi reads the source's volume from it and the screen slider sets it back
on the source device with a DACP command, like Bluetooth.

## DLNA

- **Receiver**: moOde's UPnP renderer (upmpdcli) is on, named `TasmoOde Receiver`.
  `pi/espbridge/mpdfix.py` keeps MPD's mpg123 decoder disabled (Windows casts a
  non-seekable transcoded stream that mpg123 cannot play).
- **Browsing**: `pi/espbridge/dlna.py` finds the media servers (SSDP), browses their
  folders and queues a folder in MPD from the chosen track. HTTP API on port 8091
  (`/dlna/servers|browse|play|mode|next|prev|state`, CORS open) used by the `/ui` page.
  Play modes: `loop_all` (default), `all_once`, `random`, `one_loop`, `one_once`.

## Workflow

Code lives on GitHub. The always-on PC on the LAN holds a clone and deploys to the devices.

```sh
git pull
python tools/tasmota_sync.py push        # upload changed files in esp/
python tools/tasmota_sync.py cmd "Restart 1"
python tools/tasmota_sync.py log
```

Pi side (SSH key + passwordless sudo required):

```sh
python tools/pi_sync.py push     # copy pi/espbridge/*.py (+ service), restart espbridge
python tools/pi_sync.py log      # espbridge journal
python tools/pi_sync.py status
```

First import from the device into the repo:

```sh
python tools/tasmota_sync.py pull
git add esp && git commit -m "Import current ESP files" && git push
```

If the Tasmota web UI has a password, set it in the environment first
(`TASMOTA_PASSWORD`, user is always `admin`). Never commit it.
