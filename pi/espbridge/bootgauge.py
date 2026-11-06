# bootgauge.py - jauge de demarrage pour l'ESP (BOOT <pct>)
BOOT_FILE = "/var/local/espbridge-boot-time"
BOOT_DEFAULT = 90
BOOT_POLL = 2


def uptime():
    try:
        with open("/proc/uptime") as f:
            return float(f.read().split()[0])
    except (OSError, ValueError):
        return 0.0


def boot_expected():
    try:
        with open(BOOT_FILE) as f:
            v = float(f.read().strip())
        return v if 20 <= v <= 600 else BOOT_DEFAULT
    except (OSError, ValueError):
        return BOOT_DEFAULT


def boot_save():
    up = uptime()
    if 20 <= up <= 600:
        try:
            with open(BOOT_FILE, "w") as f:
                f.write("%d\n" % up)
        except OSError:
            pass
