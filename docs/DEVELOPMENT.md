# Development notes

Internals, the serial protocol and the deploy workflow. To build one, start with [INSTALL.md](INSTALL.md).

## Architecture

- **ESP32-S3 (Tasmota)**: `autoexec.be` loads `pizero_uart.be` (serial link to the Pi) then `main_prog.be`
  (HASPmota UI, single page 240×320 portrait, floating windows for Sources / Settings).
  `main_prog.be` also loads `wifi_sync.be`, `web_ui.be` (`/wsync`, `/player`), `settings_ui.be`, and the phone
  web app driver `ui/ui.be`.
- **Raspberry Pi (moOde)**: `espbridge.py` (systemd service `espbridge`, code in `/opt/espbridge`) talks to the ESP
  on `/dev/serial0` at 115200 baud and drives MPD / moOde.

## Serial protocol (ESP ⇄ Pi, one line per message)

Pi → ESP (unsolicited)

| Message | Meaning |
|---|---|
| `READY` | system started |
| `WIFI_OK <ssid>` / `WIFI_NONE` | Wi-Fi state |
| `STATUS {json}` | sent on every change of playback, source or volume |

ESP → Pi (command → reply)

| Command | Reply |
|---|---|
| `PING` | `PONG` |
| `SYNC` | `READY` + `WIFI_OK`/`WIFI_NONE` + `STATUS` |
| `PLAY <url>` / `PLAY` | `OK PLAY` / `OK RESUME` / `ERR PLAY` |
| `STATION <json>` | none: station played from `/ui`, added to moOde's library |
| `AIRPLAY 1\|2` | `OK AIRPLAY n` |
| `STOP`, `PAUSE` | `OK STOP`, `OK PAUSE` |
| `VOL <0-100>` | `OK VOL <n>` / `ERR VOL` |
| `STATUS` | `STATUS {json}` |
| while the Pi is booting | `ERR BUSY` (drives the boot gauge on the screen) |

`STATUS` JSON fields: `state` (play/pause/stop), `source` (webradio, dlna, library, airplay, spotify, bluetooth,
squeezelite, roon, plexamp, qobuz, input, multiroom, none), `title`, `artist`, `album`, `station`, `vol`, `mute`,
`cover` (URL), `format`, `elapsed`, `duration`.

## Phone web app `/ui`

`esp/ui/ui.be` serves the files of the `/ui` folder (`/ui/f?n=…`) and a small JSON API:
`/ui/api?a=state|lib|play|toggle|stop|next|prev|mode|seek|vol|src|fsave|fdel|fmove`.
The phone's browser does the heavy work (Radio Browser search, local stations, tuner, track art from
MusicBrainz / Cover Art Archive / iTunes). Favorites (20) and history (10) live on the ESP in
`/ui/library.json`, never pushed or pulled by `tasmota_sync.py`.

Stations played from `/ui` are added to moOde's Radio library (`pi/espbridge/moode_radio.py`): the ESP sends
`STATION <json>` after `PLAY`, the Pi saves the Radio Browser logo in `radio-logos/` and calls moOde's own
`new_station` command. Stations already in moOde (same URL) are left untouched.

## AirPlay

`pi/espbridge/airplay.py`: AirPlay 2 (default) or AirPlay 1, chosen on `/wsync` (command `AIRPLAY 1|2`; old
iPads get no audio in AirPlay 2). The Pi sets `service_type` in shairport-sync.conf accordingly and reads its
metadata over UDP (127.0.0.1:5556). The screen slider sets the volume back on the source device with a DACP
command, like Bluetooth.

## DLNA

- **Receiver**: moOde's UPnP renderer (upmpdcli). `pi/espbridge/mpdfix.py` keeps MPD's mpg123 decoder disabled
  (Windows casts a non-seekable transcoded stream that mpg123 cannot play).
- **Browsing**: `pi/espbridge/dlna.py` finds media servers (SSDP), browses folders and queues a folder in MPD
  from the chosen track. HTTP API on port 8091 (`/dlna/servers|browse|play|mode|next|prev|state`, CORS open),
  used by `/ui`. Play modes: `loop_all` (default), `all_once`, `random`, `one_loop`, `one_once`.

## Deploy workflow

The code lives on GitHub; a PC on the same LAN holds a clone and deploys to the devices.
Both tools are standard-library Python and run on Windows, Linux and macOS.

ESP side (`TASMOTA_HOST`, and `TASMOTA_PASSWORD` if the Tasmota web UI has one; the user is always `admin`):

```sh
git pull
python tools/tasmota_sync.py push            # upload changed files in esp/
python tools/tasmota_sync.py cmd "Restart 1"
python tools/tasmota_sync.py log -f
python tools/tasmota_sync.py pull            # device -> esp/ (first import)
```

Pi side (`PI_HOST=user@host`; needs an SSH key on the Pi and passwordless sudo for that user,
which is the default for the user created by Raspberry Pi Imager):

```sh
ssh-keygen -t ed25519                        # once, on the PC
ssh-copy-id <user>@moode.local               # or append the .pub key to ~/.ssh/authorized_keys on the Pi
python tools/pi_sync.py push                 # copy pi/espbridge/*.py (+ service), restart espbridge
python tools/pi_sync.py log
python tools/pi_sync.py status
```

The defaults of `--host` in both tools are the author's addresses: set the environment variables for yours.
Never commit passwords (`.env` is git-ignored).
