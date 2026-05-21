# Flashing baked images

How to write the artifact you downloaded from os-bakery onto the target
device. This doc covers every format the bakery produces and the
recommended tool on each host operating system.

## Decide what you have

| Artifact suffix     | Format               | How you flash it                              |
| ------------------- | -------------------- | --------------------------------------------- |
| `.img.xz` / `.img`  | Raw disk image       | Decompress then write byte-for-byte to SD / USB / disk. |
| `.img.gz`           | Raw disk image       | Same — `xz` / `gunzip` then write.            |
| `.iso`              | Hybrid installer ISO | Write to USB stick + boot the target into it. |
| `.qcow2` / `.vhdx`  | VM disk image        | Import into your hypervisor (qemu / Hyper-V). |
| `.bin`              | ESP firmware         | Flash via WebSerial (Chrome) or `esptool.py`. |

The download page tells you which one you got. If unsure, run
`file artifact-name` on Linux / macOS.

## Verify the checksum

Always verify the SHA256 before flashing — a corrupted image bricks the
target until you re-flash:

```sh
# Linux
sha256sum -c artifact.img.xz.sha256

# macOS
shasum -a 256 -c artifact.img.xz.sha256

# Windows (PowerShell)
Get-FileHash .\artifact.img.xz -Algorithm SHA256
```

os-bakery's download page shows the expected digest next to the file.

## Linux

### Raw `.img` / `.img.xz` → SD card or USB

The canonical tool is `dd`, but **Raspberry Pi Imager** ([install](https://www.raspberrypi.com/software/)) is friendlier and works for any raw image:

```sh
# Decompress (Imager handles .xz natively, dd doesn't)
xz -d artifact.img.xz

# Find the target — DOUBLE-CHECK the device path. `dd` does not ask twice.
lsblk
# e.g. your SD shows up as /dev/sdc

# Write
sudo dd if=artifact.img of=/dev/sdc bs=4M status=progress conv=fsync
sync
```

> **Warning:** Picking the wrong `of=…` overwrites your laptop's
> root drive. Use `lsblk` immediately before, never copy-paste
> blindly. Imager / Etcher are safer if you're not sure.

GUI alternatives (any of these handle `.img`, `.img.xz`, and `.iso` and
refuse to write to system disks):

- **Raspberry Pi Imager** — `sudo apt install rpi-imager` (Debian/Ubuntu) or `flatpak install rpi-imager`.
- **balenaEtcher** — <https://etcher.balena.io>.
- **GNOME Disks** — built-in; right-click an `.img` and pick *Restore Disk Image*.

### `.iso` → USB stick (for Ubuntu desktop / Kali / Proxmox / Windows)

The ISOs we ship are hybrid — `dd` works, but a USB multiboot tool is
nicer because you can carry several ISOs on one stick:

- **Ventoy** — <https://www.ventoy.net/>. Install once on a stick, then
  drop ISOs into the FAT32 partition. Boot, pick from menu.
- Or just `sudo dd if=artifact.iso of=/dev/sdc bs=4M status=progress`.

### `.qcow2` / `.vhdx` → VM

```sh
# QEMU / KVM (libvirt)
virt-install \
  --name my-vm --memory 4096 --vcpus 2 \
  --disk path=artifact.qcow2,format=qcow2 \
  --import --osinfo detect=on,name=debian13

# Proxmox: upload to /var/lib/vz/template/iso or use the GUI's
# "Upload" button under Datacenter → Storage → Local.
```

### `.bin` → ESP32 / ESP8266

The ESPHome recipe pages on `/bake/` embed an **ESP Web Tools** button —
plug the device into USB, click *Connect & flash*, and Chrome talks
WebSerial directly to the chip. No CLI install needed.

Command-line alternative when the browser flow isn't available:

```sh
pip install --user esptool
# Find the serial port
ls /dev/ttyUSB*  /dev/ttyACM*  # usually /dev/ttyUSB0
# Erase + write
esptool.py --chip esp32 --port /dev/ttyUSB0 erase_flash
esptool.py --chip esp32 --port /dev/ttyUSB0 write_flash -z 0x0 firmware.bin
```

Your user needs `dialout` group membership for the serial port:
`sudo usermod -aG dialout $USER && newgrp dialout`.

## macOS

### Raw `.img` / `.img.xz` → SD card or USB

Use **Raspberry Pi Imager** (`brew install --cask raspberry-pi-imager`)
or **balenaEtcher** (`brew install --cask balenaetcher`). For the CLI
purist:

```sh
# 1. Decompress
xz -d artifact.img.xz   # `brew install xz` if needed

# 2. Find the disk — note the BSD `diskN` name, NOT `disk0`!
diskutil list
# Look for "external, physical" — e.g. /dev/disk4

# 3. Unmount (don't eject — the disk needs to exist for dd)
diskutil unmountDisk /dev/disk4

# 4. Write using the RAW device (`rdisk4`, 10× faster than `disk4`)
sudo dd if=artifact.img of=/dev/rdisk4 bs=4m status=progress

# 5. Eject
diskutil eject /dev/disk4
```

> **macOS gotcha:** `disk0` is your Mac's internal SSD. `disk1` is
> usually the recovery partition. The SD card is whichever fresh
> entry shows up after you insert it — always verify with `diskutil
> list` before *and* after inserting.

### `.iso` → USB stick

Hybrid ISOs work with `dd` exactly like raw images (steps above). For
multi-ISO sticks, Ventoy has macOS builds.

### `.qcow2` → VM

- **UTM** (`brew install --cask utm`) — open-source QEMU front-end with
  a Mac-friendly UI. Add a new VM, point at the qcow2.
- **Parallels / VMware Fusion** — convert first:
  `qemu-img convert -O vmdk artifact.qcow2 artifact.vmdk`.

### `.bin` → ESP devices

Same story as Linux — ESP Web Tools button in the browser is the easy
path. CLI: `pip3 install esptool`, then the same `esptool.py` commands.
The serial device is `/dev/cu.usbserial-*` or `/dev/cu.SLAB_USBtoUART`.

## Windows

### Raw `.img` / `.img.xz` → SD card or USB

**Raspberry Pi Imager** is the recommended tool — single installer from
<https://www.raspberrypi.com/software/>, knows how to read `.img.xz`
natively, refuses to write to your C: drive.

**balenaEtcher** (<https://etcher.balena.io>) is the runner-up — same
feature set, also handles `.iso`. Drag the file in, pick the target,
click Flash.

For a CLI flow under WSL2 or Git Bash:

```powershell
# PowerShell — list removable disks
Get-Disk | Where-Object {$_.BusType -eq "USB"}

# Then use rufus or Imager from the GUI to avoid PowerShell
# `dd`-equivalent footguns. There IS no safe `dd` on Windows.
```

### `.iso` → USB stick

- **Rufus** — <https://rufus.ie/>. Best at making Windows-installable
  USBs from a Windows ISO; also handles Linux ISOs cleanly. Pick *DD
  image mode* in the dropdown when prompted (for our hybrid ISOs).
- **Ventoy** — same as Linux / macOS, with a `.exe` installer.

### `.qcow2` / `.vhdx` → VM

For our Hyper-V / VirtualBox catalog rows you'll usually get a
`.qcow2` from the bake. Convert to the native format:

```powershell
# Hyper-V — needs .vhdx
qemu-img convert -O vhdx artifact.qcow2 artifact.vhdx
# Then: New VM in Hyper-V Manager → Generation 2 → use existing VHD.

# VirtualBox — natively imports .qcow2 (File → Import Appliance) or
# convert to .vdi:
qemu-img convert -O vdi artifact.qcow2 artifact.vdi
```

`qemu-img.exe` ships with QEMU for Windows (winget: `winget install qemu`)
or with Proxmox's `qemu-utils` package on WSL2.

### `.bin` → ESP devices

The ESP Web Tools button works in Edge / Chrome on Windows — no
driver-fiddling needed. CLI: `pip install esptool` from a Python
installer, then `esptool.py --port COM3 …`. Use Device Manager →
*Ports (COM & LPT)* to find which COM number your ESP enumerated as.

## Per-OS quick reference

| Format    | Linux                     | macOS                  | Windows               |
| --------- | ------------------------- | ---------------------- | --------------------- |
| `.img.xz` | RPi Imager / Etcher / `dd`| RPi Imager / Etcher    | RPi Imager / Etcher   |
| `.iso`    | Ventoy / `dd`             | Ventoy / `dd`          | Rufus / Ventoy        |
| `.qcow2`  | `virt-install`            | UTM (or convert)       | `qemu-img convert`    |
| `.bin`    | ESP Web Tools / esptool   | ESP Web Tools / esptool| ESP Web Tools / esptool |

## First boot expectations

- **Raspberry Pi family** — boot LED solid, ~30 s wait, the recipe's
  hostname appears on the network (mDNS: `ping <hostname>.local`).
- **Ubuntu / Debian server** — first boot resizes the rootfs; SSH up
  after ~60 s. Username = whatever you set in the recipe.
- **HAOS** — first boot is ~10 minutes (downloads container layers).
  Web UI at `http://<hostname>.local:8123/`.
- **Batocera** — boots straight into EmulationStation. Wi-Fi /
  hostname / language are pre-filled from your recipe.
- **ESPHome** — connects to Wi-Fi, registers with Home Assistant via
  the API key you set. Visible under *Settings → Devices & Services*.

## Troubleshooting

**"No bootable device" / black screen on a Pi**
- Re-verify the SHA256 — corrupted boot partition is the #1 cause.
- Try a different SD card. Cheap cards lie about size; flash succeeds
  but reads fail at boot.

**Windows says "drive needs to be formatted"**
- Normal! Linux partitions are unreadable from Explorer. Boot the
  device — if the OS comes up, ignore the prompt.

**ESP Web Tools says "WebSerial not supported"**
- Use desktop Chrome / Edge (Firefox doesn't ship WebSerial yet).
- Or use mobile Chrome on Android with a USB-OTG cable.

**`dd` is "slow"**
- Increase `bs=` (try `bs=16M`). On macOS use `/dev/rdiskN` not
  `/dev/diskN`. Eject before unplugging to flush the buffer cache.
