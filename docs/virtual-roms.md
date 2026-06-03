# Virtual roms

Data-driven "join-a-server" (and other variant) game tiles. Each is a thin
launcher over an **already-installed base game package**, declared in the model
and materialised on the device by Salt — **no per-server package to build or
publish**, and one mechanism for every engine.

## Why model + Salt (not a package, not `batocera.conf`)

- **vs a per-server package** — a package can't add *N* tiles from a runtime
  list (its `batoexec` gamelist fragment is static). A model list + Salt can:
  repoint / retitle / add servers by editing the model and re-applying — no
  rebuild, no republish.
- **vs a `batocera.conf` property** — `batocera.conf` is the device-local,
  user-tweakable store; pushing fleet config there means imperative
  `batocera-settings-set` (`cmd.run`) into one global file that Salt *and* the
  user both edit. A model → templated launcher is declarative, idempotent,
  per-cluster/node, and namespaced.

Base game packages stay **unchanged** except for one requirement (below).

## Model schema

A list under the `batocera` pillar (cluster default, node-overridable):

```yaml
virtual_roms:
  - base: ports-super-tux-kart          # base PACKAGE; the formula resolves its
                                        #   launcher via `pacman -Ql <base>` -> roms/<sys>/*.sh
    name: "SuperTuxKart Online"         # tile title
    server: "10.13.13.2:2759"           # <host>:<game-port>
    password: ""                        # optional
    connect: "--connect-now={server}"   # how THIS engine joins; defaulted per known base
    # optional overrides (else inherit the base game):
    # system: ports
    # image: …   marquee: …   desc: …
```

`{server}` / `{password}` are substituted into `connect`, and `connect` defaults
off `base`, so for known games an entry is just `base + name + server`.

## What the formula does (per entry)

1. **Resolve the base launcher** — `pacman -Ql <base>` → its `roms/<sys>/*.sh`.
2. **Write a slim launcher** `roms/<sys>/<slug(name)>.sh`:
   `exec "<base-launcher>" <rendered connect args>` — the base does all the real
   work (HOME, player profile, engine, assets) and **forwards the extra args**.
3. **Add the gamelist tile** — `<name>` + path to the new launcher, inheriting
   the base game's art (override with `image` / `desc`).

Edit the list → re-apply Salt → tiles appear / repoint / retitle.

## Base-package requirement: forward args

The base launcher must pass extra args through to the engine. SuperTuxKart's
upstream `run_game.sh` already does:

```sh
"$DIRNAME/bin/supertuxkart" "$@"          # forwards --connect-now=… etc.
```

and the batocera ports wrapper was made to do the same:

```sh
./run_game.sh "$@"                        # ports-super-tux-kart >= 1.5-6
```

With no extra args the base behaves exactly as before — a backward-compatible
one-liner per base game.

> The standalone `ports-super-tux-kart-online` package is **superseded** by this
> mechanism; only the base's arg-forwarding change is kept.

## Per-engine `connect` reference

| base game | `connect` template |
|---|---|
| SuperTuxKart | `--connect-now={server}` (+ `--server-password={password}`) |
| Jazz² Resurrection | `/connect {server}` (the `jazz2-charlie.bat` pattern) |
| PowerBomberman | *(engine's own connect arg)* |

> **Source:** the formula lives in [`alcali`](https://github.com/Craftama/alcali)
> under the **`batocera`** formula (it already owns batocera game config);
> os-bakery vendors + bakes it — see [salt-states](salt-states.md). The
> `virtual_roms` list is a normal model param surfaced into the baked pillar —
> see [data-model](data-model.md).
