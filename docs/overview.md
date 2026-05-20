# Overview

## What is os-bakery?

A self-hosted "image factory". Operators define **recipes** that describe how a base OS image should be tailored for an end user; users submit **build requests** through the web/API; the service downloads the appropriate base image (kept fresh by Packer), mounts it, applies the recipe's Salt states + per-build pillar, repackages it, and serves the result behind a short-lived download token.

## Why it exists

Operating-system distribution is a chore. Common pain points the service eliminates:

- **No more manual `dd` flashing-and-customizing.** End users get an already-personalised image — hostname, Wi-Fi credentials, SSH key, locale, preinstalled apps — straight from a download link.
- **Reproducibility.** Every image carries the recipe version + base image checksum it was built from. Re-runs are bit-identical given the same options.
- **Update hygiene.** Packer keeps base images current. When a recipe ships a new version (`RecipeVersion`), all subsequent builds use it; older artifacts remain auditable.
- **Many devices, many flavours, one workflow.** The same recipe-vs-target matrix handles Batocera bartops, Pi-Zero kiosks, x86 servers — anything with an installable image.

## What problems it does *not* try to solve

- **Live device management.** Once an image is downloaded and flashed, the device is on its own (or in the hands of a separate config-management system).
- **OEM-style hardware imaging at scale.** os-bakery is great for tens-to-low-thousands of devices a month; if you're imaging tens of thousands of identical SD cards a day, you want dedicated factory tooling.
- **Drop-in alternative to cloud-init.** Cloud-init runs on first boot; Salt here runs *before* first boot, against the mounted rootfs. They're complementary.

## The three actors

| Actor      | Talks to | Authored by                                 |
| ---------- | -------- | ------------------------------------------- |
| Operator   | Admin UI | Authors recipes, manages OS catalog         |
| End user   | Web/API  | Submits build requests, downloads artifacts |
| Maintainer | git/CI   | Edits Packer templates and Salt formulas    |

## At a glance

```
End-user request                                              Download link
       │                                                            ▲
       ▼                                                            │
┌────────────┐  enqueue  ┌────────────┐    bake    ┌────────────┐  publish  ┌──────────────┐
│ BuildRequest│──────────▶│ Celery task │───────────▶│ Orchestrator│──────────▶│  Artifact +  │
└────────────┘           └────────────┘            └────────────┘            │ DownloadToken│
                                                          │                  └──────────────┘
                                                          ▼
                                                ┌───────────────────┐
                                                │ Packer cached     │  refreshed by `packer build`
                                                │ base image        │
                                                └───────────────────┘
                                                          │
                                                          ▼
                                                ┌───────────────────┐
                                                │ Salt states +     │  authored in git, synced by
                                                │ pillar overrides  │  `manage.py sync_filesystem`
                                                └───────────────────┘
```
