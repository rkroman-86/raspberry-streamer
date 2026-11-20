#!/bin/sh
# Garde-fous du Pi contre les blocages complets (a lancer une fois, en root) :
#  - journal conserve entre deux demarrages (50 Mo max) : voir ce qui a precede un blocage
#  - chien de garde materiel : Pi fige plus de 15 s -> redemarrage automatique
set -e
mkdir -p /var/log/journal /etc/systemd/journald.conf.d /etc/systemd/system.conf.d
printf '[Journal]\nStorage=persistent\nSystemMaxUse=50M\n' > /etc/systemd/journald.conf.d/espbridge.conf
printf '[Manager]\nRuntimeWatchdogSec=15\nRebootWatchdogSec=2min\n' > /etc/systemd/system.conf.d/espbridge-watchdog.conf
systemctl restart systemd-journald
journalctl --flush
systemctl daemon-reexec
echo "journal: $(journalctl --header 2>/dev/null | grep -m1 'File path' || echo ok)"
echo "watchdog: $(systemctl show -p RuntimeWatchdogUSec)"
ls /dev/watchdog* 2>/dev/null || echo "pas de /dev/watchdog"
