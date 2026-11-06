var ser = serial(20, 19, 115200, serial.SERIAL_8N1)

def pi(cmd)
  ser.write(bytes().fromstring(cmd + "\n"))
end

var last_sync = 0

def pi_sync()                          # SYNC au plus toutes les 5 s
  if tasmota.millis() - last_sync > 5000
    last_sync = tasmota.millis()
    pi("SYNC")
  end
end

import string
import json

var rxbuf = ""

var on_status = nil      # défini par main_prog.be (chaque STATUS)
var on_pi_line = nil     # défini par main_prog.be (chaque ligne, synchro Wi-Fi)

def pi_line(line)
  if line == "READY"
    pi_sync()
  end
  print("PI> " + line)
  if on_pi_line != nil && on_pi_line(line)
    return                             # ligne WIFI_* traitée par wifi_sync.be
  end
  if string.find(line, "STATUS ") == 0
    var st = json.load(line[7..])
    if st != nil && on_status != nil
      on_status(st)
    end
  end
end

def pi_poll()
  if ser.available() > 0
    rxbuf += ser.read().asstring()
    var i = string.find(rxbuf, "\n")
    while i >= 0
      var line = i > 0 ? string.tr(rxbuf[0..i-1], "\r", "") : ""
      rxbuf = rxbuf[i+1..]
      if size(line) > 0 pi_line(line) end
      i = string.find(rxbuf, "\n")
    end
    if size(rxbuf) > 2048 rxbuf = "" end
  end
end

tasmota.add_fast_loop(pi_poll)
pi("")
