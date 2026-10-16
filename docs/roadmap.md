# Roadmap: setup from a phone

Not started. The goal: hand someone a framed Kindle and they set it up from their phone.

## Why this shape

The jailbreak can't be packaged; it's firmware-specific and manual. So the Kindle is
prepared once by someone technical, and everything after that is self-serve.

## The flow

1. Plug it in. The screen shows a QR code: "Scan to set up."
2. The phone joins the Kindle's own Wi-Fi network from the QR code and the setup page opens
   by itself (captive portal).
3. Pick the home Wi-Fi from a list, type the password and the address, pick which way the
   frame faces.
4. The Kindle joins the home network, geocodes the address, shows "All set", and starts.

A wrong password, or a router change later, goes back to the QR screen. Holding the power
button re-enters setup mode.

## What's known

- The Wi-Fi chip (Broadcom BCM43430) supports AP mode. `wpa_supplicant` and `udhcpd` are on
  the device; `hostapd` and `dnsmasq` are not.
- The main risk is handing Wi-Fi back from our access point to a normal connection without
  Amazon's `wifid` fighting it. Prototype that switch first.
- Fallback if that's flaky: setup mode opens the stock Kindle Wi-Fi screen for the
  password, and the QR code only carries the address and preferences.

## Work

1. Provision script: jailbroken Kindle in, Python, Pillow, FBInk, this code and the boot job
   out (`tools/install.sh` does most of this already); firmware updates blocked.
2. Setup mode: access point, captive portal (a tiny DNS responder plus an HTTP server), the
   setup page, geocoding after joining the home network.
3. Self-update from GitHub releases during a Wi-Fi window; roll back if the display fails
   to start three times.
4. A two-week untouched soak before giving one away.
5. Parts list and a one-page picture guide.
