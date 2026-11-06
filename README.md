# Raspberry Streamer

Audio streamer: Raspberry Pi Zero 2 W running moOde (+ PCM5102 DAC) driven by a
Waveshare ESP32-S3 touch screen running Tasmota / Berry / HASPmota, linked by UART.

## Layout

| Folder   | Content                                                              |
|----------|----------------------------------------------------------------------|
| `esp/`   | Mirror of the Tasmota filesystem (`*.be`, `pages.jsonl`, `A/*.png`)  |
| `pi/`    | Pi side: `espbridge.py` (`/opt/espbridge/`) and its systemd service  |
| `tools/` | `tasmota_sync.py`: push / pull files, run commands, read the log     |
| `docs/`  | Notes, protocol, wiring                                              |

## Device

- ESP32-S3 (Tasmota): `192.168.1.75`
- Raspberry Pi Zero 2 W (moOde): `rk@192.168.1.35`, code in `/opt/espbridge`, service `espbridge`

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
