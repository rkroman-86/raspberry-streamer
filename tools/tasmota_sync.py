#!/usr/bin/env python3
"""tasmota_sync.py - sync the esp/ folder of this repo with a Tasmota device.

Standard library only (no pip install needed). Runs on Windows, Linux, macOS.

Usage (from the repo root):
  python tools/tasmota_sync.py pull            # device -> esp/   (download every file)
  python tools/tasmota_sync.py push            # esp/ -> device   (upload changed files only)
  python tools/tasmota_sync.py push --all      # upload everything
  python tools/tasmota_sync.py ls              # list files on the device
  python tools/tasmota_sync.py cmd "Status 0"  # run a Tasmota command, print JSON
  python tools/tasmota_sync.py log             # print the device console log
  python tools/tasmota_sync.py rm /A/old.png   # delete a file on the device

Device address: --host, or env TASMOTA_HOST, default 192.168.1.75
Web password:   env TASMOTA_PASSWORD (user is always "admin"), empty if none.
"""
import argparse
import base64
import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCAL_DIR = os.path.join(REPO, "esp")
STATE_FILE = os.path.join(REPO, ".tasmota_state.json")  # git-ignored
TEXT_EXT = {".be", ".jsonl", ".json", ".txt", ".html", ".htm", ".css", ".js", ".bat", ".csv", ".md"}
SKIP_LOCAL = {".gitkeep", "README.md"}
TIMEOUT = 30


class Device:
    def __init__(self, host, password):
        self.base = "http://" + host
        self.password = password or ""

    def _req(self, path, data=None, headers=None):
        url = self.base + path
        req = urllib.request.Request(url, data=data, headers=headers or {})
        if self.password:
            tok = base64.b64encode(("admin:" + self.password).encode()).decode()
            req.add_header("Authorization", "Basic " + tok)
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.read()

    # --- commands / log -------------------------------------------------
    def cmd(self, command):
        q = {"cmnd": command}
        if self.password:
            q.update(user="admin", password=self.password)
        raw = self._req("/cm?" + urllib.parse.urlencode(q)).decode("utf-8", "replace")
        try:
            return json.loads(raw)
        except ValueError:
            return raw

    def log(self):
        raw = self._req("/cs?c2=0").decode("utf-8", "replace")
        parts = raw.split("}1")
        return parts[-1] if parts else raw

    # --- filesystem -----------------------------------------------------
    _ROW = re.compile(r"<pre[^>]*><a href='ufsd\?download=([^']+)' file='[^']*'>[^<]*</a>(.*?)</pre>", re.S)

    def listdir(self, path="/"):
        """Return (files, dirs) directly inside path. files: list of (path, size)."""
        page = self._req("/ufsd?download=" + urllib.parse.quote(path)).decode("utf-8", "replace")
        files, dirs = [], []
        prefix = path.rstrip("/") + "/"
        for href, rest in self._ROW.findall(page):
            p = urllib.parse.unquote(html.unescape(href))
            name = p[len(prefix):] if p.startswith(prefix) else ""
            if not name or "/" in name:
                continue  # parent link or recursed sub-entry
            rest = rest.strip()
            m = re.match(r"(\d{4}-\d\d-\d\dT[\d:]+)\s+(\d+)", rest)
            if m:
                files.append((p, int(m.group(2))))
            else:
                dirs.append(p)
        return files, dirs

    def walk(self, path="/"):
        files, dirs = self.listdir(path)
        for d in dirs:
            files += self.walk(d)
        return files

    def download(self, path):
        return self._req("/ufsd?download=" + urllib.parse.quote(path))

    def delete(self, path):
        folder = path.rsplit("/", 1)[0] or "/"
        self._req("/ufsd?" + urllib.parse.urlencode({"delete": path, "download": folder}))

    def upload_text(self, path, content):
        # /ufse POST creates missing folders on its own
        body = urllib.parse.urlencode({"name": path, "content": content}).encode()
        self._req("/ufse", data=body, headers={"Content-Type": "application/x-www-form-urlencoded"})

    def upload_binary(self, path, content):
        folder, name = path.rsplit("/", 1)
        folder = folder or "/"
        if folder != "/":
            # make sure the folder exists (the editor endpoint creates it)
            tmp = folder + "/.mk"
            self.upload_text(tmp, "x")
            self.delete(tmp)
        self._req("/ufsd?download=" + urllib.parse.quote(folder))  # sets the upload target folder
        boundary = uuid.uuid4().hex
        body = (
            ("--%s\r\nContent-Disposition: form-data; name=\"ufsu\"; filename=\"%s\"\r\n"
             "Content-Type: application/octet-stream\r\n\r\n" % (boundary, name)).encode()
            + content + ("\r\n--%s--\r\n" % boundary).encode()
        )
        self._req("/ufsu?fsz=%d" % len(content), data=body,
                  headers={"Content-Type": "multipart/form-data; boundary=" + boundary})


def local_files():
    out = {}
    for root, _, names in os.walk(LOCAL_DIR):
        for n in names:
            if n in SKIP_LOCAL:
                continue
            full = os.path.join(root, n)
            rel = "/" + os.path.relpath(full, LOCAL_DIR).replace(os.sep, "/")
            out[rel] = full
    return out


def sha(data):
    return hashlib.sha1(data).hexdigest()


def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=1, sort_keys=True)


def do_pull(dev):
    state = {}
    for path, size in dev.walk("/"):
        data = dev.download(path)
        dest = os.path.join(LOCAL_DIR, *path.strip("/").split("/"))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as f:
            f.write(data)
        state[path] = sha(data)
        print("pulled %-40s %7d bytes" % (path, len(data)))
    save_state(state)


def do_push(dev, push_all):
    state = load_state()
    changed = 0
    for path, full in sorted(local_files().items()):
        with open(full, "rb") as f:
            data = f.read()
        h = sha(data)
        if not push_all and state.get(path) == h:
            continue
        ext = os.path.splitext(path)[1].lower()
        if ext in TEXT_EXT:
            dev.upload_text(path, data.decode("utf-8"))
        else:
            dev.upload_binary(path, data)
        state[path] = h
        save_state(state)
        changed += 1
        print("pushed %-40s %7d bytes" % (path, len(data)))
        time.sleep(0.2)
    print("%d file(s) uploaded" % changed)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default=os.environ.get("TASMOTA_HOST", "192.168.1.75"))
    sub = ap.add_subparsers(dest="action", required=True)
    sub.add_parser("pull")
    p = sub.add_parser("push")
    p.add_argument("--all", action="store_true")
    sub.add_parser("ls")
    c = sub.add_parser("cmd")
    c.add_argument("command")
    sub.add_parser("log")
    r = sub.add_parser("rm")
    r.add_argument("path")
    a = ap.parse_args()

    dev = Device(a.host, os.environ.get("TASMOTA_PASSWORD", ""))
    if a.action == "pull":
        do_pull(dev)
    elif a.action == "push":
        do_push(dev, a.all)
    elif a.action == "ls":
        for path, size in dev.walk("/"):
            print("%-40s %7d" % (path, size))
    elif a.action == "cmd":
        res = dev.cmd(a.command)
        print(json.dumps(res, indent=1, ensure_ascii=False) if not isinstance(res, str) else res)
    elif a.action == "log":
        print(dev.log())
    elif a.action == "rm":
        dev.delete(a.path)
        print("deleted", a.path)


if __name__ == "__main__":
    try:
        main()
    except urllib.error.URLError as e:
        sys.exit("device error: %s" % e)
