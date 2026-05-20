# Salt guide

Salt is the **per-user customization layer**. It runs against the *mounted base image* (not the live system), driven by `salt-call --local` against a pillar tree that os-bakery materialises per build.

## Why local Salt (and not a full master)?

- No long-running daemons. Each build is a self-contained `salt-call`.
- No minion authentication dance — there's nothing to authenticate, we're rewriting the rootfs in place.
- Reproducibility: pillar values are written to disk, the call is logged, the rootfs is unmounted and packed.

## The pillar contract

Each build produces this tree under `BUILD_WORK_ROOT/<build-id>/pillar/`:

```
pillar/
├── top.sls            # base:'*': - <recipe-slug>
└── <recipe-slug>.sls  # merged values
```

`<recipe-slug>.sls` is the result of merging, in this order:

1. `salt/pillar/base/*.sls`            — universal defaults
2. `salt/pillar/<os-slug>/*.sls`       — per-OS defaults
3. `recipes.RecipeVersion.pillar_overrides` (JSON, deep-merged)
4. `osbakery:` namespace (build id, recipe slug, hardware target, label)
5. `options:` namespace (the user's `BuildRequest.option_values`)

So a state can confidently read:

```jinja
{% set hostname = pillar['options'].get('hostname', 'os-bakery') %}
{% set tz = pillar['options'].get('timezone', pillar['base']['timezone']) %}
```

## What states ship today

```
salt/states/
├── base/
│   ├── hardening/    # sshd hardening, ufw on if available
│   ├── users/        # admin user + sudoers + SSH keys + hostname
│   ├── network/      # wpa_supplicant Wi-Fi
│   └── locale/       # timezone + locale
├── batocera/
│   ├── base/         # batocera.conf seed + base.* includes
│   ├── arcade/       # arcade-only system filter + rom prefetch
│   ├── family/       # parental controls + tidy theme
│   └── minimal/      # strip demo roms
├── raspios/
│   ├── base/         # cmdline / config.txt overrides, SSH enabled
│   ├── kiosk/        # auto-login + chromium kiosk
│   ├── headless/     # purge LXDE, disable swap
│   └── docker/       # docker-ce + portainer
└── ubuntu/
    ├── base/         # unattended-upgrades
    ├── server/       # tmux/htop/vim/etc
    └── k3s/          # single-node k3s install
```

Authoring conventions:

- **One formula = one directory with `init.sls`.** Sub-states live alongside.
- **Read pillar through `.get(...)`** with sensible defaults. A build should still succeed if a non-required option is missing.
- **Don't write into the user's `/home/<user>`** unless the option explicitly says to. That's reserved for the end customer.
- **Compose with `include:`** — `batocera/base/init.sls` includes `base.hardening`, `base.users`, `base.network`, `base.locale`. Recipe versions that want a leaner build can list specific includes in `salt_states`.

## How a build's top file is decided

`builds.orchestrator._write_top` resolves it in this order:

1. If `RecipeVersion.salt_top_yaml` is non-empty → use it verbatim.
2. Else if `RecipeVersion.salt_states` is non-empty → `base: '*': [salt_states...]`.
3. Else → `base: '*': [<recipe.slug>]`.

Most recipes pick option 2 with a list like:

```python
salt_states = ["batocera.base", "batocera.arcade"]
```

## Adding a new formula

1. Create `salt/states/<namespace>/<name>/init.sls`.
2. Make it read pillar through `.get(...)` with safe defaults.
3. Run `python manage.py sync_filesystem` so `infra.SaltFormula` picks it up.
4. Reference it from one or more recipe versions' `salt_states`.

## Testing locally without root

For now, the orchestrator's mount + salt-call step is a no-op (it records the intent and moves on). On a real build host you'll need:

```sh
apt install libguestfs-tools qemu-user-static binfmt-support xz-utils
```

… and the worker process needs sudo for `losetup`, `mount`, `umount`, `kpartx`. Plan to run the worker as a dedicated `bakery` user with a narrow sudoers entry.
