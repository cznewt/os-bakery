# os-bakery — Documentation

Welcome. This is the source-of-truth documentation for the **os-bakery** application: a Django service that orchestrates Packer + Salt to build and distribute custom OS images (Batocera, Raspberry Pi OS, Ubuntu, …) for ARM, x86, and other targets.

## Table of contents

1. [Overview](overview.md) — what os-bakery does and the problem it solves.
2. [Architecture](architecture.md) — components, request flow, deployment topology.
3. [Data model](data-model.md) — every Django model, its fields, and how they relate.
4. [Catalog matrix](catalog.md) — the concrete OS / hardware / variant / upstream-image grid we publish.
5. [Supported platforms](platforms.md) — the wider device universe: Pis, BeagleBone, Jetson, PCs, VMs, future targets.
6. [Build workflow](workflow.md) — from `BuildRequest` to a downloadable artifact.
7. [Packer guide](packer.md) — how the base-image refresh works.
8. [Salt guide](salt.md) — how per-user customizations are baked in.
9. [Deployment](deployment.md) — production runbook (Postgres, Redis, S3, workers).
10. [Operations](operations.md) — admin tasks, sync commands, common failures.
11. [API reference](api.md) — REST endpoints.
12. [CI](ci.md) — GitHub Actions workflows: lint/tests, container builds, scheduled image refresh.
13. [Roadmap](roadmap.md) — what's done, what's next.
14. [Contributing](contributing.md) — local dev, conventions, code style.

## Glossary

- **Hardware target** — a specific board + boot-method profile (e.g. `rpi5`, `pc-x86_64-uefi`). One row per supported device class.
- **Operating system** — a distribution we know how to bake (Batocera, RaspiOS, Ubuntu).
- **Release** — a specific version + channel of an OS (e.g. Batocera 41 stable).
- **Upstream image** — the base image the vendor publishes, mirrored locally by Packer.
- **Recipe** — a named customization profile that picks an OS + supported hardware + Salt states.
- **Recipe version** — an immutable snapshot of a recipe's Salt configuration.
- **Recipe option** — a build-time knob the user fills in (hostname, SSH key, kiosk URL, …).
- **Build request** — a user's intent to bake an image; tracked from queued → succeeded/failed.
- **Artifact** — the file an end user downloads.
- **Download token** — a bearer string that grants time-bounded access to an artifact.
