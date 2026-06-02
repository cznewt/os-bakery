"""Seed a starter set of role-template Recipes.

Each row corresponds to a "I want one of these images" use case — Batocera
for handheld / arcade / notebook deployments, Ubuntu for desktop / Docker /
Kubernetes roles. Idempotent: re-running adds nothing, refreshes nothing.
Use ``manage.py seed_recipes --reset`` to wipe the table first.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand
from django.db import transaction

from catalog.models import HardwareTarget, OperatingSystem, OSRelease, Provisioner
from recipes.models import Recipe, RecipeOption, RecipeVersion


RECIPES: list[dict[str, Any]] = [
    {
        "slug": "batocera-handheld",
        "name": "Batocera · Handheld",
        "summary": "Retro gaming preset for Anbernic / Retroid handhelds — "
                   "boot into EmulationStation, language and keyboard configured.",
        "os_slug": "batocera",
        "hardware_slugs": ["rg552", "rg353p", "rg353ps", "rg353v", "rg353vs",
                           "rg503", "loki-zero", "flip-2", "pocket-5"],
        "version": "1.0.0",
        "salt_states": ["base.locale", "batocera.base"],
        # No hardcoded batocera config — the salt batocera module owns
        # boot_to_arcade/power per role; os-bakery only carries the role.
        "pillar_overrides": {},
        "options": [
            {"key": "hostname", "label": "Hostname", "kind": "string",
             "required": True, "default": "handheld-1", "sort_order": 10},
            {"key": "language", "label": "System language", "kind": "choice",
             "default": "en_US", "sort_order": 20,
             "choices": [
                 {"value": "en_US", "label": "English (US)"},
                 {"value": "cs_CZ", "label": "Czech"},
                 {"value": "de_DE", "label": "German"},
                 {"value": "fr_FR", "label": "French"},
             ]},
            {"key": "wifi_ssid", "label": "Wi-Fi SSID",
             "help_text": "Optional — leave blank for offline use.",
             "kind": "string", "sort_order": 30},
            {"key": "wifi_psk", "label": "Wi-Fi password",
             "help_text": "Required if SSID is set.",
             "kind": "secret", "sort_order": 40},
        ],
    },
    {
        "slug": "batocera-arcade",
        "name": "Batocera · Arcade cabinet",
        "summary": "Boots straight into the game launcher; lockdown UI, "
                   "family-friendly defaults, attract mode.",
        "os_slug": "batocera",
        "hardware_slugs": ["pc-amd64", "rpi4", "rpi5"],
        "version": "1.0.0",
        "salt_states": ["base.locale", "batocera.base", "batocera.arcade"],
        "pillar_overrides": {},
        "options": [
            {"key": "hostname", "label": "Hostname", "kind": "string",
             "required": True, "default": "arcade-1", "sort_order": 10},
            {"key": "cabinet_name", "label": "Cabinet display name",
             "help_text": "Shown on the splash screen.",
             "kind": "string", "sort_order": 20},
            {"key": "wifi_ssid", "label": "Wi-Fi SSID", "kind": "string",
             "sort_order": 30},
            {"key": "wifi_psk", "label": "Wi-Fi password", "kind": "secret",
             "sort_order": 40},
        ],
    },
    {
        "slug": "batocera-notebook",
        "name": "Batocera · Notebook",
        "summary": "Laptop-friendly Batocera — sleep on lid close, brightness "
                   "keys, hibernate on low battery.",
        "os_slug": "batocera",
        "hardware_slugs": ["pc-amd64"],
        "version": "1.0.0",
        "salt_states": ["base.locale", "batocera.base", "batocera.minimal"],
        "pillar_overrides": {},
        "options": [
            {"key": "hostname", "label": "Hostname", "kind": "string",
             "required": True, "default": "notebook-1", "sort_order": 10},
            {"key": "user_name", "label": "Local user", "kind": "string",
             "default": "batocera", "sort_order": 20},
            {"key": "wifi_ssid", "label": "Wi-Fi SSID", "kind": "string",
             "sort_order": 30},
            {"key": "wifi_psk", "label": "Wi-Fi password", "kind": "secret",
             "sort_order": 40},
        ],
    },
    {
        "slug": "ubuntu-desktop",
        "name": "Ubuntu · Desktop",
        "summary": "Ubuntu desktop image — GNOME preconfigured, common dev "
                   "tools, sane defaults.",
        "os_slug": "ubuntu",
        "hardware_slugs": ["pc-amd64", "rpi4", "rpi5", "vm-qemu"],
        "version": "1.0.0",
        # cloud-init seed: salt-bootstrap + masterless highstate at first boot.
        "provisioner": "cloud-init",
        "salt_states": ["base.locale", "base.users", "ubuntu.base"],
        "pillar_overrides": {},
        "options": [
            {"key": "hostname", "label": "Hostname", "kind": "string",
             "required": True, "default": "ubuntu-1", "sort_order": 10},
            {"key": "user_name", "label": "Username", "kind": "string",
             "required": True, "default": "ubuntu", "sort_order": 20},
            {"key": "ssh_authorized_keys", "label": "SSH authorized keys",
             "help_text": "One key per line; populated into "
                          "~/.ssh/authorized_keys at first boot.",
             "kind": "ssh_key", "sort_order": 30},
            {"key": "wifi_ssid", "label": "Wi-Fi SSID", "kind": "string",
             "sort_order": 40},
            {"key": "wifi_psk", "label": "Wi-Fi password", "kind": "secret",
             "sort_order": 50},
        ],
    },
    {
        "slug": "ubuntu-docker",
        "name": "Ubuntu · Docker host",
        "summary": "Headless Ubuntu Server with Docker engine + compose "
                   "preinstalled. Joins the fleet as a `*-docker-*` role.",
        "os_slug": "ubuntu",
        "hardware_slugs": ["pc-amd64", "rpi4", "rpi5", "pc-arm64",
                           "vm-qemu", "vm-hyperv", "vm-virtualbox"],
        "version": "1.0.0",
        "salt_states": ["base.locale", "base.users", "base.hardening",
                        "ubuntu.server"],
        "pillar_overrides": {},
        "options": [
            {"key": "hostname", "label": "Hostname", "kind": "string",
             "required": True, "default": "docker-1", "sort_order": 10},
            {"key": "user_name", "label": "Admin user", "kind": "string",
             "required": True, "default": "ops", "sort_order": 20},
            {"key": "ssh_authorized_keys", "label": "SSH authorized keys",
             "help_text": "Required — headless image, SSH is the only entry "
                          "point.",
             "kind": "ssh_key", "required": True, "sort_order": 30},
            {"key": "salt_master", "label": "Salt master (optional)",
             "help_text": "If set, salt-minion is installed and configured "
                          "to talk to this master so the fleet `*-docker-*` "
                          "role state is applied on first contact.",
             "kind": "string", "sort_order": 40},
        ],
    },
    # ---- single-role recipes for the remaining OSes ------------------
    {
        "slug": "raspios-headless",
        "name": "RaspiOS · Headless",
        "summary": "Raspberry Pi OS Lite preconfigured for headless / IoT "
                   "use — SSH enabled, optional Wi-Fi, sane locale defaults.",
        "os_slug": "raspios",
        "hardware_slugs": ["rpi3", "rpi4", "rpi5"],
        "version": "1.0.0",
        "salt_states": ["base.locale", "raspios.headless"],
        "pillar_overrides": {},
        "options": [
            {"key": "hostname", "label": "Hostname", "kind": "string",
             "required": True, "default": "raspi-1", "sort_order": 10},
            {"key": "user_name", "label": "Username", "kind": "string",
             "required": True, "default": "pi", "sort_order": 20},
            {"key": "user_password", "label": "User password", "kind": "secret",
             "required": True, "sort_order": 30},
            {"key": "ssh_authorized_keys", "label": "SSH authorized keys",
             "help_text": "One key per line.",
             "kind": "ssh_key", "sort_order": 40},
            {"key": "wifi_ssid", "label": "Wi-Fi SSID", "kind": "string",
             "sort_order": 50},
            {"key": "wifi_psk", "label": "Wi-Fi password", "kind": "secret",
             "sort_order": 60},
        ],
    },
    {
        "slug": "haos-appliance",
        "name": "Home Assistant · Appliance",
        "summary": "HAOS preconfigured for first-boot — Wi-Fi credentials "
                   "baked into the config partition, SSH add-on key seeded.",
        "os_slug": "haos",
        "hardware_slugs": ["rpi4", "rpi5", "pc-amd64"],
        "version": "1.0.0",
        "salt_states": ["haos.base", "haos.network", "haos.ssh"],
        "pillar_overrides": {},
        "options": [
            {"key": "hostname", "label": "Hostname", "kind": "string",
             "default": "homeassistant", "sort_order": 10},
            {"key": "wifi_ssid", "label": "Wi-Fi SSID",
             "help_text": "Optional — leave blank for Ethernet-only.",
             "kind": "string", "sort_order": 20},
            {"key": "wifi_psk", "label": "Wi-Fi password", "kind": "secret",
             "sort_order": 30},
            {"key": "wifi_country", "label": "Wi-Fi country code",
             "kind": "string", "default": "DE", "sort_order": 40},
            {"key": "ssh_authorized_keys",
             "label": "SSH authorized keys",
             "help_text": "Baked onto the boot partition for the HAOS debug SSH "
                          "(port 22222).",
             "kind": "ssh_key", "sort_order": 50},
            {"key": "addon_repos",
             "label": "Add-on repositories",
             "help_text": "Add-on store repos to pre-seed (one URL per line), "
                          "e.g. your hassos-addons repo for salt/alloy.",
             "kind": "text", "sort_order": 60},
            {"key": "ha_backup",
             "label": "HA backup .tar (restore on first boot)",
             "help_text": "Optional — upload a Home Assistant backup to restore "
                          "on first boot, baking in preinstalled+configured "
                          "add-ons (salt, alloy).",
             "kind": "file", "sort_order": 70},
        ],
    },
    {
        "slug": "debian-server",
        "name": "Debian · Server",
        "summary": "Generic Debian server — minimal base, salt-minion "
                   "ready, joins the fleet as a `linux` role.",
        "os_slug": "debian",
        "hardware_slugs": ["pc-amd64", "rpi4", "rpi5", "pc-arm64",
                           "vm-qemu", "vm-hyperv", "vm-virtualbox",
                           "beaglebone-black", "beaglebone-blue"],
        "version": "1.0.0",
        "salt_states": ["base.locale", "base.users", "base.hardening"],
        "pillar_overrides": {},
        "options": [
            {"key": "hostname", "label": "Hostname", "kind": "string",
             "required": True, "default": "debian-1", "sort_order": 10},
            {"key": "user_name", "label": "Admin user", "kind": "string",
             "required": True, "default": "ops", "sort_order": 20},
            {"key": "ssh_authorized_keys", "label": "SSH authorized keys",
             "help_text": "Required — server image has no console password.",
             "kind": "ssh_key", "required": True, "sort_order": 30},
            {"key": "salt_master", "label": "Salt master (optional)",
             "help_text": "If set, salt-minion is installed and pointed "
                          "at this master.",
             "kind": "string", "sort_order": 40},
        ],
    },
    {
        "slug": "omarchy-desktop",
        "name": "Omarchy · Desktop",
        "summary": "DHH's curated Arch + Hyprland desktop with your user "
                   "account and dotfiles preconfigured.",
        "os_slug": "omarchy",
        "hardware_slugs": ["pc-amd64"],
        "version": "1.0.0",
        "salt_states": ["base.locale", "base.users"],
        "pillar_overrides": {},
        "options": [
            {"key": "hostname", "label": "Hostname", "kind": "string",
             "required": True, "default": "omarchy", "sort_order": 10},
            {"key": "user_name", "label": "Username", "kind": "string",
             "required": True, "sort_order": 20},
            {"key": "user_password", "label": "User password",
             "kind": "secret", "required": True, "sort_order": 30},
            {"key": "ssh_authorized_keys", "label": "SSH authorized keys",
             "kind": "ssh_key", "sort_order": 40},
        ],
    },
    {
        "slug": "popos-workstation",
        "name": "Pop!_OS · Workstation",
        "summary": "System76's Pop!_OS as a development workstation — "
                   "Intel or NVIDIA flavour, devtools preselected.",
        "os_slug": "popos",
        "hardware_slugs": ["pc-amd64"],
        "version": "1.0.0",
        "salt_states": ["base.locale", "base.users", "ubuntu.base"],
        "pillar_overrides": {},
        "options": [
            {"key": "hostname", "label": "Hostname", "kind": "string",
             "required": True, "default": "popos-1", "sort_order": 10},
            {"key": "user_name", "label": "Username", "kind": "string",
             "required": True, "sort_order": 20},
            {"key": "user_password", "label": "User password",
             "kind": "secret", "required": True, "sort_order": 30},
            {"key": "ssh_authorized_keys", "label": "SSH authorized keys",
             "kind": "ssh_key", "sort_order": 40},
        ],
    },
    {
        "slug": "l4t-jetson",
        "name": "Jetson · L4T",
        "summary": "NVIDIA Jetson SDK image — hostname / SSH / user "
                   "preconfigured. Pick the right Tegra family in step 1.",
        "os_slug": "l4t",
        "hardware_slugs": ["jetson-nano", "jetson-xavier-nx",
                           "jetson-orin-nano"],
        "version": "1.0.0",
        "salt_states": ["base.locale", "base.users"],
        "pillar_overrides": {},
        "options": [
            {"key": "hostname", "label": "Hostname", "kind": "string",
             "required": True, "default": "jetson-1", "sort_order": 10},
            {"key": "user_name", "label": "Username", "kind": "string",
             "required": True, "default": "nvidia", "sort_order": 20},
            {"key": "user_password", "label": "User password",
             "kind": "secret", "required": True, "sort_order": 30},
            {"key": "ssh_authorized_keys", "label": "SSH authorized keys",
             "kind": "ssh_key", "sort_order": 40},
        ],
    },
    {
        "slug": "kali-pentest",
        "name": "Kali · Pentest workstation",
        "summary": "Kali Linux preset for red-team work — username and "
                   "SSH keys preconfigured. amd64 ISO + arm64 Pi images.",
        "os_slug": "kali",
        "hardware_slugs": ["pc-amd64", "rpi4", "rpi5"],
        "version": "1.0.0",
        "salt_states": ["base.locale", "base.users"],
        "pillar_overrides": {},
        "options": [
            {"key": "hostname", "label": "Hostname", "kind": "string",
             "required": True, "default": "kali-1", "sort_order": 10},
            {"key": "user_name", "label": "Username", "kind": "string",
             "required": True, "default": "kali", "sort_order": 20},
            {"key": "user_password", "label": "User password",
             "kind": "secret", "required": True, "sort_order": 30},
            {"key": "ssh_authorized_keys", "label": "SSH authorized keys",
             "kind": "ssh_key", "sort_order": 40},
        ],
    },
    # ---- Windows ---------------------------------------------------
    {
        "slug": "windows-workstation",
        "name": "Windows · Workstation",
        "summary": "Windows 11 with an autounattend.xml preseed — locale, "
                   "timezone, default user, and product key baked in; "
                   "boots straight into the desktop on first start.",
        "os_slug": "windows",
        "hardware_slugs": ["pc-amd64", "vm-qemu", "vm-hyperv", "vm-virtualbox"],
        "version": "1.0.0",
        "salt_states": [],
        "pillar_overrides": {},
        "options": [
            {"key": "hostname", "label": "Computer name", "kind": "string",
             "required": True, "default": "WIN-1", "sort_order": 10,
             "help_text": "Max 15 chars; Windows NetBIOS limit."},
            {"key": "user_name", "label": "User account", "kind": "string",
             "required": True, "default": "newt", "sort_order": 20},
            {"key": "user_password", "label": "User password",
             "kind": "secret", "required": True, "sort_order": 30},
            {"key": "locale", "label": "Locale", "kind": "choice",
             "default": "en-US", "sort_order": 40,
             "choices": [
                 {"value": "en-US", "label": "English (United States)"},
                 {"value": "en-GB", "label": "English (United Kingdom)"},
                 {"value": "cs-CZ", "label": "Czech (Czechia)"},
                 {"value": "de-DE", "label": "German (Germany)"},
                 {"value": "fr-FR", "label": "French (France)"},
             ]},
            {"key": "timezone", "label": "Time zone",
             "kind": "string", "default": "Central European Standard Time",
             "sort_order": 50,
             "help_text": "Windows-format tz name, e.g. "
                          "`Central European Standard Time`."},
            {"key": "product_key", "label": "Product key (optional)",
             "kind": "secret", "sort_order": 60,
             "help_text": "Blank → 30-day trial; provide a Pro / Enterprise "
                          "key for activated install."},
            {"key": "edition", "label": "Edition", "kind": "choice",
             "default": "pro", "sort_order": 70,
             "choices": [
                 {"value": "home", "label": "Home"},
                 {"value": "pro", "label": "Pro"},
                 {"value": "enterprise", "label": "Enterprise"},
                 {"value": "education", "label": "Education"},
             ]},
        ],
    },
    {
        "slug": "macos-workstation",
        "name": "macOS · Workstation",
        "summary": "macOS with the macos salt formula — locale, default user, "
                   "and packages applied on first boot. Installer media is "
                   "gated, so the upstream image is a placeholder.",
        "os_slug": "macos",
        "hardware_slugs": ["mac-apple-silicon", "mac-intel"],
        "version": "1.0.0",
        "salt_states": ["macos"],
        "pillar_overrides": {},
        "options": [
            {"key": "hostname", "label": "Computer name", "kind": "string",
             "required": True, "default": "mac-1", "sort_order": 10},
            {"key": "user_name", "label": "User account", "kind": "string",
             "required": True, "default": "newt", "sort_order": 20},
            {"key": "user_password", "label": "User password",
             "kind": "secret", "required": True, "sort_order": 30},
            {"key": "locale", "label": "Locale", "kind": "choice",
             "default": "en_US", "sort_order": 40,
             "choices": [
                 {"value": "en_US", "label": "English (United States)"},
                 {"value": "en_GB", "label": "English (United Kingdom)"},
                 {"value": "cs_CZ", "label": "Czech (Czechia)"},
                 {"value": "de_DE", "label": "German (Germany)"},
                 {"value": "fr_FR", "label": "French (France)"},
             ]},
            {"key": "timezone", "label": "Time zone", "kind": "string",
             "default": "Europe/Prague", "sort_order": 50,
             "help_text": "IANA tz name, e.g. `Europe/Prague`."},
        ],
    },
    # ---- Android — phones / tablets registered as nodes (not baked) ----
    {
        "slug": "android-phone",
        "name": "Android · Phone",
        "summary": "Register an Android phone or tablet as a node — for VPN / "
                   "device management (e.g. setting up a WireGuard client). "
                   "os-bakery doesn't image Android, so nothing is baked.",
        "os_slug": "android",
        "hardware_slugs": ["phone-arm64", "tablet-arm64"],
        # No provisioner — these devices aren't imaged by os-bakery.
        "provisioner": None,
        "version": "1.0.0",
        "salt_states": [],
        "pillar_overrides": {},
        "options": [
            {"key": "hostname", "label": "Device name", "kind": "string",
             "required": True, "default": "phone-1", "sort_order": 10,
             "help_text": "Used as the node id / WireGuard client name."},
            {"key": "device_model", "label": "Model", "kind": "string",
             "sort_order": 20,
             "help_text": "Optional — e.g. 'Pixel 8' or 'Galaxy Tab S9'."},
        ],
    },
    # ---- ESPHome — firmware images for ESP32 / ESP8266 devices ----
    # Each recipe maps to a packages/device/<vendor>/<device>.yaml file in
    # https://github.com/Craftama/esphome-models (cloned into BUILD_WORK_ROOT
    # at compile time by the orchestrator). Options become substitutions.
    {
        "slug": "esphome-laskakit-esplan",
        "name": "ESPHome · LaskaKit ESPlan",
        "summary": "LaskaKit ESPlan (ESP32 + Ethernet) preset — Home "
                   "Assistant API, optional I²C sensor bus, BLE proxy.",
        "os_slug": "esphome",
        "hardware_slugs": ["laskakit-esplan"],
        "version": "1.0.0",
        "salt_states": [],
        "pillar_overrides": {
            "esphome": {
                "package": "packages/device/laskakit/esplan.yaml",
                "models_repo": "https://github.com/Craftama/esphome-models",
            },
        },
        "options": [
            {"key": "device_name", "label": "Device name (mDNS)",
             "kind": "string", "required": True,
             "default": "esplan-1", "sort_order": 10,
             "help_text": "Becomes the device's network hostname + "
                          "ESPHome `substitutions.device_name`."},
            {"key": "name_prefix", "label": "Friendly name prefix",
             "kind": "string", "default": "Esplan",
             "sort_order": 20},
            {"key": "network_address", "label": "Static IP (optional)",
             "kind": "string", "sort_order": 30,
             "help_text": "Leave blank for DHCP."},
            {"key": "ha_api_key", "label": "Home Assistant API key",
             "kind": "secret", "required": True, "sort_order": 40,
             "help_text": "32-byte base64 — `esphome auth gen-key`."},
            {"key": "include_ble_proxy", "label": "BLE proxy",
             "kind": "boolean", "default": True, "sort_order": 50,
             "help_text": "Use the device as a Bluetooth proxy for Home Assistant."},
        ],
    },
    {
        "slug": "esphome-bluetooth-proxy",
        "name": "ESPHome · BLE proxy",
        "summary": "Minimal ESP32 firmware that bridges nearby Bluetooth LE "
                   "advertisements to Home Assistant — great for spreading "
                   "presence sensors around the house.",
        "os_slug": "esphome",
        "hardware_slugs": [
            "esp32", "esp32-c3", "esp32-c6", "esp32-s3",
            "esp32-devkit", "esp32-s3-devkit", "esp32-c3-devkit",
            "esp32-c6-devkit", "m5stack-atoms3",
        ],
        "version": "1.0.0",
        "salt_states": [],
        "pillar_overrides": {
            "esphome": {
                "package": "packages/network/bluetooth/pine64.yaml",
                "models_repo": "https://github.com/Craftama/esphome-models",
            },
        },
        "options": [
            {"key": "device_name", "label": "Device name (mDNS)",
             "kind": "string", "required": True,
             "default": "ble-proxy-1", "sort_order": 10},
            {"key": "wifi_ssid", "label": "Wi-Fi SSID", "kind": "string",
             "required": True, "sort_order": 20},
            {"key": "wifi_psk", "label": "Wi-Fi password", "kind": "secret",
             "required": True, "sort_order": 30},
            {"key": "ha_api_key", "label": "Home Assistant API key",
             "kind": "secret", "required": True, "sort_order": 40},
        ],
    },
    {
        "slug": "esphome-vindriktning",
        "name": "ESPHome · IKEA Vindriktning",
        "summary": "Turn the IKEA Vindriktning air-quality sensor into a "
                   "smart device — adds PM2.5 reporting and an RGB status "
                   "LED to your Home Assistant.",
        "os_slug": "esphome",
        "hardware_slugs": ["laskakit-vindriktning"],
        "version": "1.0.0",
        "salt_states": [],
        "pillar_overrides": {
            "esphome": {
                "package": "packages/device/laskakit/vindriktning.yaml",
                "models_repo": "https://github.com/Craftama/esphome-models",
            },
        },
        "options": [
            {"key": "device_name", "label": "Device name (mDNS)",
             "kind": "string", "required": True,
             "default": "vindriktning-1", "sort_order": 10},
            {"key": "name_prefix", "label": "Friendly name prefix",
             "kind": "string", "default": "Bedroom Vindriktning",
             "sort_order": 20},
            {"key": "wifi_ssid", "label": "Wi-Fi SSID", "kind": "string",
             "required": True, "sort_order": 30},
            {"key": "wifi_psk", "label": "Wi-Fi password", "kind": "secret",
             "required": True, "sort_order": 40},
            {"key": "ha_api_key", "label": "Home Assistant API key",
             "kind": "secret", "required": True, "sort_order": 50},
            {"key": "include_leds", "label": "Use upgraded LED ring",
             "kind": "boolean", "default": False, "sort_order": 60,
             "help_text": "Pick the `vindriktning-leds.yaml` package "
                          "instead of the plain one."},
        ],
    },
    {
        "slug": "esphome-custom",
        "name": "ESPHome · Custom YAML",
        "summary": "Bring your own ESPHome YAML — handy when the device "
                   "isn't a preset in craftama/esphome-models yet.",
        "os_slug": "esphome",
        "hardware_slugs": [
            # Generic chips
            "esp32", "esp32-s3", "esp32-c3", "esp32-c6", "esp8266",
            # Dev boards
            "esp32-devkit", "esp32-s3-devkit", "esp32-c3-devkit",
            "esp32-c6-devkit", "esp8266-nodemcu", "wemos-d1-mini",
            # Vendor devices
            "ai-thinker-esp32-cam", "athom-ps01", "laskakit-esplan",
            "laskakit-vindriktning", "m5stack-atoms3", "shelly-1",
            "sonoff-mini", "sonoff-4ch-pro", "sonoff-nspanel",
            "sonoff-s20", "ulanzi-tc001", "weber-igrill-v2",
        ],
        "version": "1.0.0",
        "salt_states": [],
        "pillar_overrides": {
            "esphome": {
                "package": "",
                "models_repo": "https://github.com/Craftama/esphome-models",
            },
        },
        "options": [
            {"key": "device_name", "label": "Device name", "kind": "string",
             "required": True, "default": "esp-1", "sort_order": 10},
            {"key": "yaml_url", "label": "ESPHome YAML URL (raw)",
             "kind": "string", "required": True, "sort_order": 20,
             "help_text": "Public URL to the YAML config (e.g. a gist or "
                          "GitHub raw link)."},
            {"key": "ha_api_key", "label": "Home Assistant API key",
             "kind": "secret", "sort_order": 30,
             "help_text": "Optional — required if the YAML enables the "
                          "ESPHome → HA API."},
        ],
    },
    # ---- Robotics — ArduPilot on the BeagleBone Blue --------------
    {
        "slug": "ardupilot-rover",
        "name": "ArduPilot · Rover",
        "summary": "ArduRover autopilot on BeagleBone Blue — ground vehicle "
                   "preset (skid-steer / Ackermann), MAVLink telemetry to "
                   "your ground station.",
        "os_slug": "debian",
        "hardware_slugs": ["beaglebone-blue"],
        "version": "1.0.0",
        "salt_states": ["base.locale", "base.users", "debian.ardupilot"],
        "pillar_overrides": {"ardupilot": {"vehicle": "rover"}},
        "pinned_release": {"os_slug": "debian", "version": "12",
                           "channel": "stable"},
        "options": [
            {"key": "hostname", "label": "Vehicle hostname", "kind": "string",
             "required": True, "default": "rover-1", "sort_order": 10},
            {"key": "frame_type", "label": "Frame type", "kind": "choice",
             "default": "skid", "sort_order": 20,
             "choices": [
                 {"value": "skid", "label": "Skid-steer"},
                 {"value": "ackermann", "label": "Ackermann (car-style)"},
                 {"value": "omni", "label": "Omni (mecanum / holonomic)"},
                 {"value": "boat", "label": "Boat / surface vehicle"},
             ]},
            {"key": "wifi_ssid", "label": "Telemetry Wi-Fi SSID",
             "kind": "string", "sort_order": 30,
             "help_text": "Companion / GCS network."},
            {"key": "wifi_psk", "label": "Wi-Fi password", "kind": "secret",
             "sort_order": 40},
            {"key": "mavlink_gcs", "label": "Ground station endpoint",
             "kind": "string", "sort_order": 50,
             "help_text": "e.g. udp://192.168.1.100:14550 — MAVLink stream "
                          "target."},
            {"key": "ssh_authorized_keys", "label": "SSH authorized keys",
             "kind": "ssh_key", "required": True, "sort_order": 60},
        ],
    },
    {
        "slug": "ardupilot-copter",
        "name": "ArduPilot · Copter",
        "summary": "ArduCopter autopilot on BeagleBone Blue — multirotor "
                   "preset (quad / hexa / octa), arming + failsafe defaults, "
                   "MAVLink telemetry to your GCS.",
        "os_slug": "debian",
        "hardware_slugs": ["beaglebone-blue"],
        "version": "1.0.0",
        "salt_states": ["base.locale", "base.users", "debian.ardupilot"],
        "pillar_overrides": {"ardupilot": {"vehicle": "copter"}},
        "pinned_release": {"os_slug": "debian", "version": "12",
                           "channel": "stable"},
        "options": [
            {"key": "hostname", "label": "Vehicle hostname", "kind": "string",
             "required": True, "default": "copter-1", "sort_order": 10},
            {"key": "frame_class", "label": "Frame class", "kind": "choice",
             "default": "quad", "sort_order": 20,
             "choices": [
                 {"value": "quad", "label": "Quad (4 motors)"},
                 {"value": "hexa", "label": "Hexa (6 motors)"},
                 {"value": "octa", "label": "Octa (8 motors)"},
                 {"value": "y6", "label": "Y6 (6 motors, coaxial)"},
                 {"value": "tricopter", "label": "Tricopter"},
                 {"value": "heli", "label": "Helicopter (single rotor)"},
             ]},
            {"key": "frame_geometry", "label": "Frame geometry",
             "kind": "choice", "default": "x", "sort_order": 30,
             "choices": [
                 {"value": "x", "label": "X (default)"},
                 {"value": "plus", "label": "+ (plus)"},
                 {"value": "h", "label": "H"},
                 {"value": "v", "label": "V"},
             ]},
            {"key": "wifi_ssid", "label": "Telemetry Wi-Fi SSID",
             "kind": "string", "sort_order": 40},
            {"key": "wifi_psk", "label": "Wi-Fi password", "kind": "secret",
             "sort_order": 50},
            {"key": "mavlink_gcs", "label": "Ground station endpoint",
             "kind": "string", "sort_order": 60,
             "help_text": "e.g. udp://192.168.1.100:14550."},
            {"key": "ssh_authorized_keys", "label": "SSH authorized keys",
             "kind": "ssh_key", "required": True, "sort_order": 70},
        ],
    },
    {
        "slug": "proxmox-bare-metal",
        "name": "Proxmox VE · Bare-metal",
        "summary": "Proxmox VE installer with preseeded answers — boot it "
                   "on a fresh server and it lands ready to join the fleet "
                   "as a `pve` role.",
        "os_slug": "proxmox-ve",
        "hardware_slugs": ["pc-amd64"],
        "version": "1.0.0",
        "salt_states": [],
        "pillar_overrides": {},
        "options": [
            {"key": "hostname", "label": "Node hostname", "kind": "string",
             "required": True, "default": "pve-1", "sort_order": 10},
            {"key": "domain", "label": "Domain", "kind": "string",
             "default": "prg.newt.cz", "sort_order": 20},
            {"key": "root_password", "label": "root password",
             "kind": "secret", "required": True, "sort_order": 30},
            {"key": "email", "label": "Admin email", "kind": "string",
             "help_text": "answer.toml `mailto`.",
             "default": "admin@prg.newt.cz", "sort_order": 40},
            {"key": "ssh_authorized_keys", "label": "SSH authorized keys",
             "help_text": "Added as root_ssh_keys in the answer file.",
             "kind": "ssh_key", "required": True, "sort_order": 50},
            {"key": "timezone", "label": "Timezone", "kind": "string",
             "default": "Europe/Prague", "sort_order": 60},
            {"key": "keyboard", "label": "Keyboard layout", "kind": "string",
             "default": "en-us", "sort_order": 70},
            {"key": "country", "label": "Country code", "kind": "string",
             "help_text": "Two-letter, e.g. cz, de, us.",
             "default": "cz", "sort_order": 80},
            {"key": "filesystem", "label": "Root filesystem", "kind": "choice",
             "default": "ext4", "sort_order": 90,
             "choices": [
                 {"value": "ext4", "label": "ext4"},
                 {"value": "xfs", "label": "XFS"},
                 {"value": "zfs (RAID0)", "label": "ZFS RAID0"},
                 {"value": "zfs (RAID1)", "label": "ZFS RAID1 (mirror)"},
             ]},
            {"key": "target_disk", "label": "Target disk", "kind": "string",
             "help_text": "Install disk, e.g. sda or nvme0n1. Default sda.",
             "default": "sda", "sort_order": 100},
            {"key": "static_ip", "label": "Static IP (optional)",
             "help_text": "e.g. 10.0.0.10/24. Blank → DHCP.",
             "kind": "string", "sort_order": 110},
            {"key": "gateway", "label": "Default gateway", "kind": "string",
             "sort_order": 120},
            {"key": "dns", "label": "DNS server", "kind": "string",
             "help_text": "Used with a static IP.", "sort_order": 130},
            {"key": "cluster_endpoint", "label": "Cluster master to join",
             "help_text": "Optional — IP:port of an existing PVE node.",
             "kind": "string", "sort_order": 140},
        ],
    },
    {
        "slug": "ubuntu-kube",
        "name": "Ubuntu · Kubernetes node",
        "summary": "Ubuntu Server with kubeadm + cri-o + zerotier; ready to "
                   "join an existing control plane.",
        "os_slug": "ubuntu",
        "hardware_slugs": ["pc-amd64", "rpi4", "rpi5", "pc-arm64",
                           "vm-qemu"],
        "version": "1.0.0",
        "salt_states": ["base.locale", "base.users", "base.hardening",
                        "ubuntu.server", "ubuntu.k3s"],
        "pillar_overrides": {},
        "options": [
            {"key": "hostname", "label": "Hostname", "kind": "string",
             "required": True, "default": "kube-1", "sort_order": 10},
            {"key": "user_name", "label": "Admin user", "kind": "string",
             "required": True, "default": "ops", "sort_order": 20},
            {"key": "ssh_authorized_keys", "label": "SSH authorized keys",
             "kind": "ssh_key", "required": True, "sort_order": 30},
            {"key": "kube_role", "label": "Cluster role", "kind": "choice",
             "default": "worker", "sort_order": 40,
             "choices": [
                 {"value": "master", "label": "Control-plane (master)"},
                 {"value": "worker", "label": "Worker"},
             ]},
            {"key": "kube_api_endpoint", "label": "API server endpoint",
             "help_text": "e.g. https://10.0.0.10:6443 (workers only).",
             "kind": "string", "sort_order": 50},
            {"key": "kube_join_token", "label": "kubeadm join token",
             "help_text": "From `kubeadm token create` on the master "
                          "(workers only).",
             "kind": "secret", "sort_order": 60},
        ],
    },
]


class Command(BaseCommand):
    help = "Seed the recipes table with the starter role templates."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--reset", action="store_true",
            help="Delete and recreate every recipe in the seed list "
                 "(also wipes RecipeVersions / RecipeOptions for them).",
        )

    def handle(self, *args, reset: bool = False, **options) -> None:
        report = {"recipes": 0, "versions": 0, "options": 0,
                  "recipes+": 0, "versions+": 0, "options+": 0}

        with transaction.atomic():
            if reset:
                Recipe.objects.filter(
                    slug__in=[r["slug"] for r in RECIPES]
                ).delete()

            # Provisioner per recipe — defaults to Salt; a few use cloud-init.
            provs = {p.slug: p for p in Provisioner.objects.all()}

            for spec in RECIPES:
                os_ = OperatingSystem.objects.get(slug=spec["os_slug"])
                recipe, created = Recipe.objects.get_or_create(
                    slug=spec["slug"],
                    defaults=dict(
                        name=spec["name"],
                        summary=spec["summary"],
                        operating_system=os_,
                        status=Recipe.Status.ACTIVE,
                        visibility=Recipe.Visibility.PUBLIC,
                    ),
                )
                want_prov = provs.get(spec.get("provisioner", "salt"))
                if want_prov and recipe.provisioner_id != want_prov.id:
                    recipe.provisioner = want_prov
                    recipe.save(update_fields=["provisioner"])
                report["recipes"] += 1
                report["recipes+"] += int(created)
                self.stdout.write(
                    f"  [{'created' if created else 'exists '}] "
                    f"Recipe: {recipe.slug}"
                )

                # Make sure the supported hardware list matches the seed.
                targets = HardwareTarget.objects.filter(
                    slug__in=spec["hardware_slugs"]
                )
                recipe.supported_hardware.set(targets)

                # Optional `pinned_release` — recipes that only work against
                # a specific OS release (BeagleBone Blue Debian Bookworm, …).
                pin = spec.get("pinned_release")
                if pin:
                    pin_release = OSRelease.objects.filter(
                        operating_system__slug=pin["os_slug"],
                        version=pin["version"],
                        channel=pin["channel"],
                    ).first()
                    if pin_release and recipe.pinned_release_id != pin_release.id:
                        recipe.pinned_release = pin_release
                        recipe.save(update_fields=["pinned_release"])

                version, v_created = RecipeVersion.objects.get_or_create(
                    recipe=recipe, version=spec["version"],
                    defaults=dict(
                        is_current=True,
                        salt_states=spec["salt_states"],
                        pillar_overrides=spec["pillar_overrides"],
                    ),
                )
                # The seed is the source of truth — refresh salt_states +
                # pillar_overrides on existing versions (e.g. when defaults the
                # salt modules now own are stripped from a recipe).
                if not v_created:
                    changed = []
                    if version.salt_states != spec["salt_states"]:
                        version.salt_states = spec["salt_states"]
                        changed.append("salt_states")
                    if version.pillar_overrides != spec["pillar_overrides"]:
                        version.pillar_overrides = spec["pillar_overrides"]
                        changed.append("pillar_overrides")
                    if changed:
                        version.save(update_fields=changed)
                report["versions"] += 1
                report["versions+"] += int(v_created)

                for opt_spec in spec["options"]:
                    opt, o_created = RecipeOption.objects.get_or_create(
                        recipe=recipe, key=opt_spec["key"],
                        defaults=dict(
                            label=opt_spec["label"],
                            help_text=opt_spec.get("help_text", ""),
                            kind=opt_spec.get("kind", "string"),
                            default=opt_spec.get("default"),
                            choices=opt_spec.get("choices", []),
                            required=opt_spec.get("required", False),
                            sort_order=opt_spec.get("sort_order", 0),
                        ),
                    )
                    report["options"] += 1
                    report["options+"] += int(o_created)

        self.stdout.write(self.style.SUCCESS(
            f"Seeded: {report['recipes']} recipes ({report['recipes+']} new), "
            f"{report['versions']} versions ({report['versions+']} new), "
            f"{report['options']} options ({report['options+']} new)."
        ))
