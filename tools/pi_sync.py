#!/usr/bin/env python3
"""pi_sync.py - deploy the pi/ folder of this repo to the Raspberry Pi (moOde).

Needs the OpenSSH client (built into Windows 10/11) and an SSH key installed on
the Pi (no password prompt), plus passwordless sudo for the Pi user.

Usage (from the repo root):
  python tools/pi_sync.py push          # copy pi/espbridge/*.py + service, restart espbridge
  python tools/pi_sync.py pull          # Pi -> pi/ (espbridge/*.py + service)
  python tools/pi_sync.py restart       # restart the espbridge service
  python tools/pi_sync.py status        # systemctl status espbridge
  python tools/pi_sync.py log [-n 80]   # last lines of the espbridge journal
  python tools/pi_sync.py sh "cmd"      # run a shell command on the Pi

Pi address: --host, or env PI_HOST, default rk@192.168.1.35
"""
import argparse
import glob
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(REPO, "pi", "espbridge")
SERVICE = os.path.join(REPO, "pi", "systemd", "espbridge.service")
REMOTE_DIR = "/opt/espbridge"
REMOTE_SERVICE = "/etc/systemd/system/espbridge.service"
TMP = "/tmp/espbridge_upload"
SSH_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=10"]


def run(args, check=True):
    r = subprocess.run(args)
    if check and r.returncode != 0:
        sys.exit("command failed (%d): %s" % (r.returncode, " ".join(args)))
    return r.returncode


def ssh(host, command, check=True):
    return run(["ssh"] + SSH_OPTS + [host, command], check)


def do_push(host):
    files = sorted(glob.glob(os.path.join(SRC_DIR, "*.py")))
    if not files:
        sys.exit("nothing to push in " + SRC_DIR)
    ssh(host, "rm -rf %s && mkdir -p %s" % (TMP, TMP))
    run(["scp"] + SSH_OPTS + files + [SERVICE, "%s:%s/" % (host, TMP)])
    names = " ".join(os.path.basename(f) for f in files)
    script = " && ".join([
        "cd %s" % TMP,
        "sed -i 's/\\r$//' *.py espbridge.service",          # CRLF safety
        "for f in %s; do python3 -m py_compile $f || exit 1; done" % names,
        "sudo install -m 644 %s %s/" % (names, REMOTE_DIR),
        "(cmp -s espbridge.service %s || (sudo install -m 644 espbridge.service %s && sudo systemctl daemon-reload && echo service file updated))"
        % (REMOTE_SERVICE, REMOTE_SERVICE),
        "sudo rm -rf %s/__pycache__" % REMOTE_DIR,
        "sudo systemctl restart espbridge",
        "sleep 2",
        "systemctl is-active espbridge",
    ])
    ssh(host, script)
    print("pushed: " + names)


def do_pull(host):
    os.makedirs(SRC_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(SERVICE), exist_ok=True)
    run(["scp"] + SSH_OPTS + ["%s:%s/*.py" % (host, REMOTE_DIR), SRC_DIR + os.sep])
    run(["scp"] + SSH_OPTS + ["%s:%s" % (host, REMOTE_SERVICE), SERVICE])
    print("pulled into pi/")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default=os.environ.get("PI_HOST", "rk@192.168.1.35"))
    sub = ap.add_subparsers(dest="action", required=True)
    sub.add_parser("push")
    sub.add_parser("pull")
    sub.add_parser("restart")
    sub.add_parser("status")
    lg = sub.add_parser("log")
    lg.add_argument("-n", type=int, default=80)
    sh = sub.add_parser("sh")
    sh.add_argument("command")
    a = ap.parse_args()

    if a.action == "push":
        do_push(a.host)
    elif a.action == "pull":
        do_pull(a.host)
    elif a.action == "restart":
        ssh(a.host, "sudo systemctl restart espbridge && sleep 2 && systemctl is-active espbridge")
    elif a.action == "status":
        ssh(a.host, "systemctl status espbridge --no-pager -l", check=False)
    elif a.action == "log":
        ssh(a.host, "sudo journalctl -u espbridge -n %d --no-pager -o short-iso" % a.n, check=False)
    elif a.action == "sh":
        sys.exit(ssh(a.host, a.command, check=False))


if __name__ == "__main__":
    main()
