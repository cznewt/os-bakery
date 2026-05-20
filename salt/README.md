# Salt states & pillars

Salt is the per-image customization layer. Packer keeps the *base* image fresh; Salt is what tailors that base image for an individual end user (hostname, Wi-Fi, installed games, kiosk URL, SSH keys, …).

## Layout

```
salt/
├── top/                    # optional standalone top files per recipe
├── states/
│   ├── base/               # universal building blocks
│   │   ├── hardening/      # sshd config, ssh keys, firewall
│   │   ├── users/          # default user + admin user creation
│   │   ├── network/        # wifi, hostname
│   │   └── locale/         # timezone, keyboard layout
│   ├── batocera/
│   │   ├── base/           # things every batocera recipe applies
│   │   ├── arcade/         # arcade-friendly defaults
│   │   ├── family/         # family-friendly defaults
│   │   └── minimal/        # strip everything down
│   ├── raspios/
│   │   ├── base/
│   │   ├── kiosk/          # auto-login + chromium kiosk
│   │   ├── headless/       # no GUI, just SSH
│   │   └── docker/         # docker + portainer preinstalled
│   └── ubuntu/
│       ├── base/
│       ├── server/         # cloud-init + admin user
│       └── k3s/            # single-node k3s
└── pillar/
    ├── base/               # defaults for the universal blocks
    ├── batocera/
    ├── raspios/
    └── ubuntu/
```

## How values flow at build time

```
recipes.RecipeVersion.pillar_overrides   ┐
recipes.RecipeOption defaults             │  merged
builds.BuildRequest.option_values         │  →  /srv/pillar/<recipe>.sls
catalog metadata (os/hw target)           │
salt/pillar/<os>/*.sls (defaults)         ┘
```

A typical Salt run inside a build's mounted rootfs:

```
salt-call --local --file-root /srv/salt --pillar-root /srv/pillar state.apply
```

The orchestrator writes a per-build `top.sls` that pins the exact state ordering for that recipe version.

## Conventions

- Every formula has an `init.sls`. Sub-states go alongside it.
- Pillar keys live under `options:` for user-facing knobs, `osbakery:` for
  app-injected metadata, and `<formula>:` for formula-specific defaults.
- Never write into `/home/<user>` unless the user explicitly opted in via a
  RecipeOption — the user-data slot is reserved for the end-customer's
  customizations.
