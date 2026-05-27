# Salt states (formulas) we bake

os-bakery doesn't ship its own production salt content — it **vendors the gedu
salt tree** and bakes it into the images. The source is the sibling
[`alcali`](https://github.com/Craftama/alcali) repo at
`extra/salt-master/docker/files/{states,pillar}`.

## How it gets in

1. `scripts/vendor-salt-states.sh` copies `states/` + `pillar/` into the build
   context at `salt/vendor/{states,pillar}` (gitignored — re-run when the salt
   repo changes).
2. The worker image bakes them and sets `SALT_STATES_ROOT=/app/salt/vendor/states`
   and `SALT_PILLAR_ROOT=/app/salt/vendor/pillar`.
3. Each bake stages the **whole file_roots + pillar_roots** onto the image
   (`/userdata/system/opt/salt/{states,pillar}` on batocera, `/srv/{salt,pillar}`
   on the salt-bootstrap/cloud-init path) plus a masterless `minion` config.
   Your pillar `top.sls` + the minion id os-bakery sets drive the per-node
   pillar. The states applied are the pillar's **top-level keys** that have a
   matching formula (e.g. pillar `batocera` → `state.apply batocera`).

> **Updating:** edit the salt repo, then `scripts/vendor-salt-states.sh` +
> rebuild the worker images. There is no live sync — the baked tree is a
> snapshot from the last worker build.

## Formula conventions

- **Multi-platform dispatch** — formulas like `salt`, `alloy`, `zerotier`,
  `selkies` have an `init.sls` that branches on `grains.os_family` into
  `_batocera.sls` / `_debian.sls` / `_linux.sls` / `_macos.sls` / `_windows.sls`.
- **Custom grains** — `_grains/machine_model.py`, `_grains/usb_devices.py` are
  computed at minion startup. They probe real hardware, so they **only run on
  the device** — a bake-time chroot apply of a formula that needs them is
  killed during grain load (you'll see this in the build log as a salt-call
  signal kill). Batocera therefore applies on-device at first boot.
- `_keyrings/` (apt signing keys), `_returners/`, `_orch/` (orchestration
  runners) are support trees, not directly `state.apply`-ed per node.

## Formula catalog

### Base OS / device
| Formula | Scope |
|---|---|
| `linux` | Debian/Ubuntu baseline — packages, repos, users, files, kernel, limits, mounts, interfaces, pip, proxies |
| `macos` | macOS baseline — packages, users, files, directories |
| `windows` | Windows baseline — packages, directories, files |
| `raspberrypi` | Raspberry Pi specifics |
| `batocera` | Batocera — `batocera.conf` settings, SSH keys, Wi-Fi networks, game repositories, packages, directories/files (custom `batocera.setting` state module) |

### Salt / management
| Formula | Scope |
|---|---|
| `salt` | Salt minion install/config per platform (`_batocera`/`_linux`/`_macos`/`_windows`) |
| `alcali` | Alcali (Salt web UI) |

### Containers / orchestration
| Formula | Scope |
|---|---|
| `docker` | Docker engine |
| `containerd` | containerd runtime |
| `crio` | CRI-O runtime |
| `kubernetes` | kubeadm cluster (`init.sls` + `join.sls`) |
| `open_iscsi` | iSCSI initiator |

### Virtualization
| Formula | Scope |
|---|---|
| `proxmox` | Proxmox VE — VMs, containers, cloud-init/container templates, images, users |

### Observability
| Formula | Scope |
|---|---|
| `alloy` | Grafana Alloy agent (per-platform) |
| `telegraf` | Telegraf metrics agent |
| `vector` | Vector log/metric pipeline (needs `vector.toml`) |
| `tempo` | Tempo tracing (`relay.sls`) |
| `grafana` | Grafana |

### Network / VPN
| Formula | Scope |
|---|---|
| `zerotier` | ZeroTier mesh (`_batocera`/`_debian`) |

### Dev / git
| Formula | Scope |
|---|---|
| `gitea`, `github`, `gitlab` | Git hosting / runners |

### Desktop / remote / media
| Formula | Scope |
|---|---|
| `kasm` | Kasm Workspaces (+ `_agent`) |
| `selkies` | Selkies GPU streaming (`_batocera`) |
| `pulseaudio` | PulseAudio |

### Data
| Formula | Scope |
|---|---|
| `postgresql` | PostgreSQL server, db, cache |

## Pillar

`pillar/` carries the fleet pillar: `top.sls` assigns per-node fragments by
minion id / grain, with `deploy-*.sls` per-deploy fragments and `default-*.sls`
shared defaults. os-bakery bakes this verbatim and sets the minion id from the
node, so the device resolves its own pillar masterless. os-bakery's own
cluster/node parameters are surfaced as the build's **effective model**
(`model.yaml` on the image + the baked-image UI), not injected into pillar.
