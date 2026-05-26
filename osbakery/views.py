"""Public-facing views for the os-bakery landing page.

Lives in `osbakery/` (the project) rather than under any single app because
these views compose data from `catalog` + `recipes` + `builds`.
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.core.files.storage import storages
from django.db.models import Count, Prefetch
from django.http import FileResponse, Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from builds.models import BuildRequest
from catalog.models import HardwareTarget, OperatingSystem, OSRelease, UpstreamImage
from recipes.models import Recipe
from tenants.models import Cluster


# simple-icons.org serves a public, versioned CDN of brand SVGs. Each entry
# is a slug + an optional accent hex used as both the SVG fill and the card
# accent. Batocera isn't on simple-icons; we fall back to a styled letter
# avatar rendered in the template.
OS_LOGOS: dict[str, dict[str, str]] = {
    "batocera": {
        "fallback_letter": "B",
        "accent": "#1f6feb",
    },
    "ubuntu": {
        "svg": "https://cdn.simpleicons.org/ubuntu/e95420",
        "accent": "#e95420",
    },
    "debian": {
        "svg": "https://cdn.simpleicons.org/debian/a81d33",
        "accent": "#a81d33",
    },
    "raspios": {
        "svg": "https://cdn.simpleicons.org/raspberrypi/c51a4a",
        "accent": "#c51a4a",
    },
    "haos": {
        "svg": "https://cdn.simpleicons.org/homeassistant/18bcf2",
        "accent": "#18bcf2",
    },
    "omarchy": {
        "fallback_letter": "O",
        "accent": "#111827",
    },
    "popos": {
        "svg": "https://cdn.simpleicons.org/popos/48b9c7",
        "accent": "#48b9c7",
    },
    "l4t": {
        "svg": "https://cdn.simpleicons.org/nvidia/76b900",
        "accent": "#76b900",
    },
    "kali": {
        "svg": "https://cdn.simpleicons.org/kalilinux/557c94",
        "accent": "#557c94",
    },
    "proxmox-ve": {
        "svg": "https://cdn.simpleicons.org/proxmox/e57000",
        "accent": "#e57000",
    },
    "esphome": {
        "svg": "https://cdn.simpleicons.org/esphome/000000",
        "accent": "#000000",
    },
    "windows": {
        "svg": "https://cdn.simpleicons.org/windows11/0078d4",
        "accent": "#0078d4",
    },
}


def home(request: HttpRequest) -> HttpResponse:
    """Landing page — a grid of OS cards plus a few aggregate stats."""

    oses = list(
        OperatingSystem.objects.filter(is_active=True)
        .annotate(n_releases=Count("releases", distinct=True))
        .prefetch_related(
            Prefetch(
                "releases",
                queryset=OSRelease.objects.filter(is_default=True),
                to_attr="default_releases",
            ),
        )
        .order_by("kind", "name")
    )

    # Compute hardware-target counts per OS — one query for all of them.
    target_counts: dict[int, int] = {}
    image_counts: dict[int, int] = {}

    for row in (
        UpstreamImage.objects.values("release__operating_system_id")
        .annotate(
            n_images=Count("id"),
            n_targets=Count("hardware_target", distinct=True),
        )
    ):
        os_id = row["release__operating_system_id"]
        image_counts[os_id] = row["n_images"]
        target_counts[os_id] = row["n_targets"]

    cards = []
    for os_ in oses:
        logo = OS_LOGOS.get(os_.slug, {})
        default = os_.default_releases[0] if os_.default_releases else None
        cards.append(
            {
                "id": os_.id,
                "slug": os_.slug,
                "name": os_.name,
                "vendor": os_.vendor,
                "kind": os_.get_kind_display(),
                "summary": os_.summary,
                "logo_svg": logo.get("svg"),
                "logo_letter": logo.get("fallback_letter", os_.name[:1].upper()),
                "accent": logo.get("accent", "#6b7280"),
                "n_releases": os_.n_releases,
                "n_targets": target_counts.get(os_.id, 0),
                "n_images": image_counts.get(os_.id, 0),
                "default_release": default,
                "homepage": os_.homepage,
            }
        )

    context = {
        "cards": cards,
        "stats": {
            "n_oses": len(cards),
            "n_targets_total": HardwareTarget.objects.count(),
            "n_releases_total": OSRelease.objects.count(),
            "n_images_total": sum(image_counts.values()),
        },
    }
    return render(request, "home.html", context)


_SBC_SLUGS = {
    "generic-arm64",
    "beaglebone-black", "beaglebone-blue",
    "jetson-nano", "jetson-xavier-nx", "jetson-orin-nano",
}


def _categorize_target(slug: str, arch_slug: str = "") -> str:
    if slug.startswith("rpi"):
        return "rpi"
    if slug.startswith("vm-"):
        return "vm"
    if slug == "pc-amd64":
        return "pc"
    if slug in _SBC_SLUGS:
        return "sbc"
    # ESP / microcontroller targets all live on Xtensa or RISC-V 32-bit.
    if arch_slug in {"xtensa", "riscv32"}:
        return "mcu"
    return "handheld"


# Per-prefix brand mark for targets that don't have a real product photo
# yet. Either a simple-icons.org brand slug (rendered to SVG by the CDN) or
# a direct URL to a Wikipedia Commons file when simple-icons doesn't carry
# the brand. The accent hex feeds the card background gradient.
_BRAND_LOGO_BY_PREFIX: list[tuple[str, str, str]] = [
    # (slug-prefix, brand-logo URL, accent hex)
    # Single-board computers
    ("rpi",         "https://cdn.simpleicons.org/raspberrypi/c51a4a",  "c51a4a"),
    ("jetson-",     "https://cdn.simpleicons.org/nvidia/76b900",       "76b900"),
    ("beaglebone-", "https://www.beagleboard.org/img/beagleboard-logo.svg", "990000"),
    # ESP / microcontroller — Espressif is the common chip vendor.
    ("esp32",       "https://cdn.simpleicons.org/espressif/e7352c",    "e7352c"),
    ("esp8266",     "https://cdn.simpleicons.org/espressif/e7352c",    "e7352c"),
    ("ai-thinker",  "https://cdn.simpleicons.org/espressif/e7352c",    "e7352c"),
    ("athom",       "https://cdn.simpleicons.org/espressif/e7352c",    "e7352c"),
    ("laskakit",    "https://cdn.simpleicons.org/espressif/e7352c",    "e7352c"),
    ("m5stack",     "https://cdn.simpleicons.org/espressif/e7352c",    "e7352c"),
    ("shelly",      "https://cdn.simpleicons.org/espressif/e7352c",    "e7352c"),
    ("sonoff",      "https://cdn.simpleicons.org/espressif/e7352c",    "e7352c"),
    ("ulanzi",      "https://cdn.simpleicons.org/espressif/e7352c",    "e7352c"),
    ("weber",       "https://cdn.simpleicons.org/espressif/e7352c",    "e7352c"),
    ("wemos",       "https://cdn.simpleicons.org/espressif/e7352c",    "e7352c"),
    # Retro handhelds — Anbernic logo from Wikipedia (no simple-icons brand).
    ("rg",          "https://upload.wikimedia.org/wikipedia/commons/thumb/1/10/Anbernic_logo.png/500px-Anbernic_logo.png", "1f6feb"),
    ("loki-",       "https://upload.wikimedia.org/wikipedia/commons/thumb/1/10/Anbernic_logo.png/500px-Anbernic_logo.png", "1f6feb"),
    ("flip-",       "https://upload.wikimedia.org/wikipedia/commons/thumb/1/10/Anbernic_logo.png/500px-Anbernic_logo.png", "1f6feb"),
    ("pocket-",     "",  "1f6feb"),  # Retroid — no public logo on the CDNs we trust
    ("ayn-",        "",  "1f6feb"),  # AYN — same
    # PC / VM hypervisor brands.
    ("vm-virtualbox","https://cdn.simpleicons.org/virtualbox/183a61",  "183a61"),
    ("vm-qemu",     "https://cdn.simpleicons.org/qemu/ff6600",         "ff6600"),
    ("vm-hyperv",   "https://cdn.simpleicons.org/microsoft/0078d4",    "0078d4"),
    ("pc-amd64",    "https://cdn.simpleicons.org/intel/0071c5",        "0071c5"),
    ("generic-arm64","https://cdn.simpleicons.org/arm/0091bd",         "0091bd"),
]


def _brand_logo_for(slug: str) -> tuple[str, str]:
    """Return (svg_url, accent_hex) for a target's vendor brand mark.

    Returns ("", "") when no brand maps — template falls back to the
    slug-typography card-top.
    """
    for prefix, url, accent in _BRAND_LOGO_BY_PREFIX:
        if slug.startswith(prefix):
            return (url, f"#{accent}")
    return ("", "")


# Targets that share a single multi-device collage as their photo. Each
# slug maps to a (bg-x%, bg-y%) CSS background-position pair so the card
# shows only its quadrant. Empty for now — add an entry when a real
# collage photo lands.
SHARED_IMAGE_CROPS: dict[str, tuple[str, str]] = {}


CATEGORY_ORDER: list[tuple[str, str, str]] = [
    # (key, label, accent)
    ("rpi", "Raspberry Pi", "#c51a4a"),
    ("pc", "PC / Laptop", "#0ea5e9"),
    ("sbc", "ARM SBC / Embedded", "#76b900"),
    ("handheld", "Retro handheld", "#8b5cf6"),
    ("mcu", "Microcontroller / ESP", "#000000"),
    ("vm", "Virtual machine", "#f59e0b"),
]


def devices(request: HttpRequest) -> HttpResponse:
    """Every HardwareTarget, grouped by category, with the OSes that support each."""

    targets = list(
        HardwareTarget.objects.select_related("architecture")
        .order_by("architecture__slug", "slug")
    )

    # One pass: collect per-target image count + the set of OSes that
    # actually have an image for that target.
    image_counts: dict[int, int] = {}
    target_oses: dict[int, set[tuple[str, str]]] = {}
    for img in (
        UpstreamImage.objects
        .select_related("release__operating_system")
        .only(
            "hardware_target_id",
            "release__operating_system__slug",
            "release__operating_system__name",
        )
    ):
        image_counts[img.hardware_target_id] = (
            image_counts.get(img.hardware_target_id, 0) + 1
        )
        target_oses.setdefault(img.hardware_target_id, set()).add(
            (img.release.operating_system.slug,
             img.release.operating_system.name)
        )

    cards_by_category: dict[str, list[dict]] = {}
    for t in targets:
        oses_for_target = sorted(target_oses.get(t.id, set()))
        brand_svg, brand_accent = _brand_logo_for(t.slug)
        crop = SHARED_IMAGE_CROPS.get(t.slug)
        cards_by_category.setdefault(
            _categorize_target(t.slug, t.architecture.slug), []
        ).append({
            "slug": t.slug,
            "name": t.name,
            "arch": t.architecture.slug,
            "boot": t.boot_method,
            "soc": t.soc,
            "notes": t.notes,
            "image_url": t.image_url,
            "image_crop_x": crop[0] if crop else "",
            "image_crop_y": crop[1] if crop else "",
            "brand_svg": brand_svg,
            "brand_accent": brand_accent,
            "is_active": t.is_active,
            "n_images": image_counts.get(t.id, 0),
            "oses": [
                {
                    "slug": slug,
                    "name": name,
                    "svg": OS_LOGOS.get(slug, {}).get("svg"),
                    "letter": OS_LOGOS.get(slug, {}).get(
                        "fallback_letter", name[:1].upper()
                    ),
                    "accent": OS_LOGOS.get(slug, {}).get("accent", "#6b7280"),
                }
                for slug, name in oses_for_target
            ],
        })

    sections = []
    for key, label, accent in CATEGORY_ORDER:
        cards = cards_by_category.get(key, [])
        if not cards:
            continue
        sections.append({
            "key": key,
            "label": label,
            "accent": accent,
            "cards": cards,
            "n_cards": len(cards),
            "n_images": sum(c["n_images"] for c in cards),
        })

    return render(request, "devices.html", {
        "sections": sections,
        "total_targets": len(targets),
        "total_images": sum(image_counts.values()),
    })


def base_images(request: HttpRequest) -> HttpResponse:
    """Every (OS, release, target, variant) upstream-image row, grouped by OS.

    Optional ``?os=<slug>`` query-string filter for a single OS at a time.
    """

    os_filter = request.GET.get("os") or ""

    images_qs = (
        UpstreamImage.objects
        .select_related(
            "release",
            "release__operating_system",
            "hardware_target",
            "hardware_target__architecture",
        )
        .order_by(
            "release__operating_system__name",
            "-release__released_on",
            "-release__version",
            "hardware_target__slug",
            "variant",
        )
    )
    if os_filter:
        images_qs = images_qs.filter(release__operating_system__slug=os_filter)

    # Group images for the template: list of (operating_system, list-of-images).
    groups: dict[str, dict] = {}
    for img in images_qs:
        os_obj = img.release.operating_system
        accent = OS_LOGOS.get(os_obj.slug, {}).get("accent", "#6b7280")
        bucket = groups.setdefault(
            os_obj.slug,
            {
                "os": os_obj,
                "accent": accent,
                "logo_svg": OS_LOGOS.get(os_obj.slug, {}).get("svg"),
                "logo_letter": OS_LOGOS.get(os_obj.slug, {}).get(
                    "fallback_letter", os_obj.name[:1].upper()
                ),
                "rows": [],
            },
        )
        bucket["rows"].append(img)

    context = {
        "groups": list(groups.values()),
        "all_operating_systems": OperatingSystem.objects.filter(is_active=True).order_by("name"),
        "selected_os": os_filter,
        "total_rows": sum(len(g["rows"]) for g in groups.values()),
    }
    return render(request, "base_images.html", context)


def download_base_image(request: HttpRequest, pk: int) -> HttpResponse:
    """Stream a mirrored upstream base image from the artifacts store.

    Only serves images that have been cached by `manage.py refresh_upstream`
    (``cache_storage_key`` set); upstream-only rows 404 — use their Source link.
    """
    img = get_object_or_404(
        UpstreamImage.objects.select_related("release__operating_system", "hardware_target"),
        pk=pk,
    )
    if not img.cache_storage_key:
        raise Http404("Image not mirrored yet — download it from its source URL.")
    storage = storages["artifacts"]
    if not storage.exists(img.cache_storage_key):
        raise Http404("Mirrored blob missing from the artifact store.")

    filename = img.cache_storage_key.rsplit("/", 1)[-1]
    response = FileResponse(
        storage.open(img.cache_storage_key, "rb"),
        as_attachment=True,
        filename=filename,
    )
    response["Content-Type"] = "application/octet-stream"
    if img.size_bytes:
        response["Content-Length"] = str(img.size_bytes)
    if img.checksum_sha256:
        response["X-Checksum-SHA256"] = img.checksum_sha256
    return response


def baked_images(request: HttpRequest) -> HttpResponse:
    """Actual baked output images (BuildRequests + their artifacts).

    Filterable via ?cluster=<slug>, ?os=<slug>, ?recipe=<slug>, ?status=<s> —
    the cluster cards on /clusters/ link here with ?cluster=… applied.
    """
    builds = (
        BuildRequest.objects.select_related(
            "recipe_version__recipe__operating_system",
            "hardware_target__architecture",
            "upstream_image__release__operating_system",
            "cluster__tenant",
            "tenant",
            "artifact",
        )
        .prefetch_related("artifact__tokens")
        .order_by("-queued_at")
    )
    f_cluster = request.GET.get("cluster") or ""
    f_os = request.GET.get("os") or ""
    f_recipe = request.GET.get("recipe") or ""
    f_status = request.GET.get("status") or ""
    if f_cluster:
        builds = builds.filter(cluster__slug=f_cluster)
    if f_os:
        builds = builds.filter(recipe_version__recipe__operating_system__slug=f_os)
    if f_recipe:
        builds = builds.filter(recipe_version__recipe__slug=f_recipe)
    if f_status:
        builds = builds.filter(status=f_status)

    def _fmt_duration(seconds: float | None) -> str:
        if not seconds or seconds < 0:
            return ""
        s = int(seconds)
        if s < 60:
            return f"{s}s"
        if s < 3600:
            return f"{s // 60}m {s % 60}s"
        return f"{s // 3600}h {(s % 3600) // 60}m"

    rows = []
    for b in builds:
        art = getattr(b, "artifact", None)
        tok = art.tokens.first() if art else None
        up = b.upstream_image
        rel = up.release if up else None
        build_secs = (
            (b.finished_at - b.started_at).total_seconds()
            if b.started_at and b.finished_at else None
        )
        rows.append({
            "id": b.id,
            "recipe": b.recipe_version.recipe.slug,
            "os": b.recipe_version.recipe.operating_system.slug,
            "target": b.hardware_target.slug,
            "label": b.label,
            "cluster": (f"{b.cluster.tenant.slug}/{b.cluster.slug}" if b.cluster_id else None),
            "cluster_slug": b.cluster.slug if b.cluster_id else None,
            "status": b.status,
            "size_bytes": art.size_bytes if art else 0,
            "filename": art.filename if art else None,
            "token": tok.token if tok else None,
            "s3_url": art.public_url if art else "",
            "queued_at": b.queued_at,
            "finished_at": b.finished_at,
            "build_time": _fmt_duration(build_secs),
            # Base (upstream) image the artifact was baked from.
            "base_version": rel.version if rel else None,
            "base_codename": rel.codename if rel else "",
            "base_released_on": rel.released_on if rel else None,
            "base_channel": rel.get_channel_display() if rel else "",
            "base_variant": up.variant if up else "",
            "base_format": up.get_format_display() if up else "",
            "base_size_bytes": up.size_bytes if up else 0,
            "base_synced_at": up.last_synced_at if up else None,
            "base_source_url": up.source_url if up else "",
        })
    context = {
        "rows": rows,
        "total": len(rows),
        "f_cluster": f_cluster,
        "f_os": f_os,
        "f_recipe": f_recipe,
        "f_status": f_status,
    }
    return render(request, "baked_images.html", context)


def build_log(request: HttpRequest, build_id: str) -> HttpResponse:
    """A baked image's build log — the BuildEvent timeline + captured output."""
    build = get_object_or_404(
        BuildRequest.objects.select_related(
            "recipe_version__recipe__operating_system",
            "hardware_target", "cluster__tenant", "artifact",
            "upstream_image__release__operating_system",
        ).prefetch_related("events", "artifact__tokens"),
        pk=build_id,
    )
    events = []
    for e in build.events.order_by("at"):
        data = e.data or {}
        events.append({
            "at": e.at,
            "phase": e.phase,
            "level": e.level,
            "message": e.message,
            "output": data.get("output_tail") or data.get("stdout_tail") or "",
        })
    art = getattr(build, "artifact", None)
    tok = art.tokens.first() if art else None

    # The effective model baked onto the image (device + cluster + options),
    # plus its device & cluster layers shown separately for clarity.
    import yaml as _yaml
    em = build.effective_model or {}
    effective_yaml = (_yaml.safe_dump(em, sort_keys=False, default_flow_style=False)
                      if em else "")
    device_block = em.get("device") or {}
    device_yaml = (_yaml.safe_dump(device_block, sort_keys=False) if device_block else "")
    cluster_params = (build.cluster.parameters or {}) if build.cluster_id else {}
    cluster_yaml = (_yaml.safe_dump(cluster_params, sort_keys=False)
                    if cluster_params else "")

    # Base (upstream) image metadata this artifact was baked from.
    up = build.upstream_image
    rel = up.release if up else None
    base = None
    if up and rel:
        base = {
            "os": rel.operating_system.slug,
            "version": rel.version,
            "codename": rel.codename,
            "channel": rel.get_channel_display(),
            "released_on": rel.released_on,
            "eol_on": rel.end_of_life_on,
            "variant": up.variant,
            "format": up.get_format_display(),
            "size_bytes": up.size_bytes,
            "checksum": up.checksum_sha256,
            "synced_at": up.last_synced_at,
            "source_url": up.source_url,
            "release_notes_url": rel.release_notes_url,
        }
    return render(request, "build_log.html", {
        "build": build,
        "events": events,
        "artifact": art,
        "token": tok.token if tok else None,
        "effective_yaml": effective_yaml,
        "device_yaml": device_yaml,
        "cluster_yaml": cluster_yaml,
        "base": base,
        "s3_url": art.public_url if art else "",
    })


def clusters(request: HttpRequest) -> HttpResponse:
    """Clusters as cards; each links to baked images filtered to that cluster."""
    from django.db.models import Count, Q

    cluster_qs = (
        Cluster.objects.filter(is_active=True)
        .select_related("tenant")
        .annotate(
            baked=Count("build_requests", filter=Q(build_requests__artifact__isnull=False), distinct=True),
            builds=Count("build_requests", distinct=True),
        )
        .order_by("tenant__name", "name")
    )
    from tenants.models import Tenant
    return render(request, "clusters.html", {
        "clusters": cluster_qs,
        "tenants": Tenant.objects.filter(is_active=True).order_by("name"),
        "kinds": Cluster.Kind.choices,
    })


def provisioners(request: HttpRequest) -> HttpResponse:
    """List provisioners (Salt/Ansible/Cloud-Init), the states each can apply,
    and which recipes (presets) use them."""
    from catalog.models import Provisioner

    rows = []
    for p in (Provisioner.objects
              .prefetch_related("recipes__operating_system")
              .order_by("-is_default", "name")):
        states = p.available_states or []
        rows.append({
            "slug": p.slug,
            "name": p.name,
            "description": p.description,
            "is_default": p.is_default,
            "is_active": p.is_active,
            "states": states,
            "state_count": len(states),
            "recipes": [
                {"slug": r.slug, "name": r.name, "os": r.operating_system.slug}
                for r in p.recipes.all().order_by("name")
            ],
        })
    return render(request, "provisioners.html", {"provisioners": rows})


def cluster_detail(request: HttpRequest, slug: str) -> HttpResponse:
    """A single cluster's metadata (key-value parameters) + link to its bakes.

    The ``parameters`` JSON mirrors the salt-reclass deploy metadata (namespaces,
    nodes, per-deploy config); render it as a pretty key-value tree.
    """
    import yaml

    cluster = get_object_or_404(Cluster.objects.select_related("tenant"), slug=slug)
    params = cluster.parameters or {}
    # Render the metadata as YAML (it mirrors salt-reclass deploy data, which is
    # YAML natively). One block per top-level key so each is readable on its own.
    sections = []
    if isinstance(params, dict):
        for key in params:
            sections.append({
                "key": key,
                "yaml": yaml.safe_dump(
                    {key: params[key]}, sort_keys=False,
                    default_flow_style=False, allow_unicode=True,
                ).rstrip(),
            })
    full_yaml = yaml.safe_dump(
        params, sort_keys=False, default_flow_style=False, allow_unicode=True,
    ).rstrip() if params else ""
    baked = cluster.build_requests.filter(artifact__isnull=False).count()
    builds = cluster.build_requests.count()
    return render(request, "cluster_detail.html", {
        "cluster": cluster,
        "params": params,
        "sections": sections,
        "full_yaml": full_yaml,
        "param_count": len(params) if isinstance(params, dict) else 0,
        "baked": baked,
        "builds": builds,
        "kinds": Cluster.Kind.choices,
        "tags_str": ", ".join(cluster.tags or []),
    })


@require_POST
def cluster_create(request: HttpRequest) -> HttpResponse:
    """Create a cluster from the form on /clusters/ (name, tenant, kind, YAML)."""
    import yaml
    from django.utils.text import slugify
    from tenants.models import Tenant

    name = (request.POST.get("name") or "").strip()
    slug = (request.POST.get("slug") or "").strip() or slugify(name)
    tenant_id = request.POST.get("tenant")
    kind = (request.POST.get("kind") or "").strip() or Cluster.Kind.GENERIC
    raw = request.POST.get("metadata_yaml", "")
    if not name or not tenant_id:
        messages.error(request, "Name and tenant are required.")
        return redirect("clusters")
    try:
        parsed = yaml.safe_load(raw) or {}
        if not isinstance(parsed, dict):
            raise ValueError("metadata must be a mapping (key: value)")
    except (yaml.YAMLError, ValueError) as exc:
        messages.error(request, f"Invalid YAML — not created: {exc}")
        return redirect("clusters")
    if Cluster.objects.filter(slug=slug).exists():
        messages.error(request, f"A cluster with slug '{slug}' already exists.")
        return redirect("clusters")
    tenant = get_object_or_404(Tenant, pk=tenant_id)
    tags = [t.strip() for t in (request.POST.get("tags") or "").split(",") if t.strip()]
    cluster = Cluster.objects.create(
        tenant=tenant, slug=slug, name=name, kind=kind, parameters=parsed,
        tags=tags, notes=request.POST.get("notes", ""),
    )
    messages.success(request, f"Created cluster {cluster.name}.")
    return redirect("cluster_detail", slug=cluster.slug)


@require_POST
def cluster_edit(request: HttpRequest, slug: str) -> HttpResponse:
    """Update all editable cluster params: slug, name, kind, tags, notes,
    active, and the metadata (YAML)."""
    import yaml
    from django.utils.text import slugify

    cluster = get_object_or_404(Cluster, slug=slug)
    name = (request.POST.get("name") or "").strip()
    new_slug = slugify((request.POST.get("slug") or "").strip()) or cluster.slug
    kind = (request.POST.get("kind") or "").strip() or cluster.kind
    notes = request.POST.get("notes", "")
    is_active = request.POST.get("is_active") == "on"
    tags = [t.strip() for t in (request.POST.get("tags") or "").split(",") if t.strip()]
    raw = request.POST.get("metadata_yaml", "")
    try:
        parsed = yaml.safe_load(raw) or {}
        if not isinstance(parsed, dict):
            raise ValueError("top-level metadata must be a mapping (key: value)")
    except (yaml.YAMLError, ValueError) as exc:
        messages.error(request, f"Invalid YAML — not saved: {exc}")
        return redirect("cluster_detail", slug=slug)
    # Slug is unique per tenant; guard against collisions on rename.
    if new_slug != cluster.slug and Cluster.objects.filter(
        tenant=cluster.tenant, slug=new_slug,
    ).exclude(pk=cluster.pk).exists():
        messages.error(request, f"Slug '{new_slug}' already exists in this tenant.")
        return redirect("cluster_detail", slug=slug)
    if name:
        cluster.name = name
    cluster.slug = new_slug
    cluster.kind = kind
    cluster.notes = notes
    cluster.is_active = is_active
    cluster.tags = tags
    cluster.parameters = parsed
    cluster.save(update_fields=[
        "name", "slug", "kind", "notes", "is_active", "tags",
        "parameters", "updated_at",
    ])
    messages.success(request, f"Saved {cluster.name} ({len(parsed)} metadata keys).")
    return redirect("cluster_detail", slug=cluster.slug)


@require_POST
def cluster_delete(request: HttpRequest, slug: str) -> HttpResponse:
    """Remove a cluster. Its builds keep (FK is SET_NULL) but lose the link."""
    cluster = get_object_or_404(Cluster, slug=slug)
    name = cluster.name
    cluster.delete()
    messages.success(request, f"Removed cluster {name}.")
    return redirect("clusters")


@require_POST
def drop_base_image(request: HttpRequest, pk: int) -> HttpResponse:
    """Drop a base image's local sync — delete the mirrored blob from the
    artifact store and revert the row to 'remote'."""
    img = get_object_or_404(UpstreamImage, pk=pk)
    if not img.cache_storage_key:
        messages.error(request, "Not mirrored — nothing to drop.")
        return redirect("base_images")
    key = img.cache_storage_key
    storage = storages["artifacts"]
    try:
        if storage.exists(key):
            storage.delete(key)
    except Exception as exc:  # noqa: BLE001 - surface storage errors to the UI
        messages.error(request, f"Failed to remove the mirrored object: {exc}")
        return redirect("base_images")
    img.cache_storage_key = ""
    img.mirror_started_at = None
    img.last_synced_at = None
    img.save(update_fields=["cache_storage_key", "mirror_started_at", "last_synced_at"])
    messages.success(request, f"Dropped local sync for {img} — removed from the artifact store.")
    return redirect("base_images")


@require_POST
def sync_base_image(request: HttpRequest, pk: int) -> HttpResponse:
    """Queue a background job to mirror an upstream image into the artifact store.

    Enqueues ``catalog.tasks.mirror_upstream_image`` (runs on the packer worker)
    and redirects back to /images/. The row flips to "mirrored" once the job
    finishes and ``cache_storage_key`` is set.
    """
    img = get_object_or_404(
        UpstreamImage.objects.select_related("release__operating_system", "hardware_target"),
        pk=pk,
    )
    from catalog.tasks import mirror_upstream_image

    # Mark as syncing so the row flips from "remote" to "syncing" immediately
    # (persists across refresh until the job caches the blob or clears it).
    from django.utils import timezone
    UpstreamImage.objects.filter(pk=img.pk).update(mirror_started_at=timezone.now())

    mirror_upstream_image.delay(img.pk)
    messages.success(
        request,
        f"Queued mirror job for {img} — refresh in a few minutes (multi-GB pull).",
    )
    return redirect("base_images")


# ---------------------------------------------------------------------------
# Bake — role-template recipe picker + per-recipe form
# ---------------------------------------------------------------------------


def _os_logo(slug: str) -> dict[str, str]:
    """Bundle of {svg, letter, accent} for a given OS slug — defaults for unknown."""
    entry = OS_LOGOS.get(slug, {})
    return {
        "svg": entry.get("svg"),
        "letter": entry.get("fallback_letter", slug[:1].upper()),
        "accent": entry.get("accent", "#6b7280"),
    }


# Recipe-to-use-case mapping. Single source of truth for the bake UI's
# top-level grouping — keep this list in sync as new recipes land.
RECIPE_USE_CASE: dict[str, str] = {
    "batocera-handheld":   "retro",
    "batocera-arcade":     "retro",
    "batocera-notebook":   "retro",
    "ubuntu-desktop":      "desktop",
    "omarchy-desktop":     "desktop",
    "popos-workstation":   "desktop",
    "ubuntu-docker":       "server",
    "ubuntu-kube":         "server",
    "debian-server":       "server",
    "raspios-headless":    "iot",
    "haos-appliance":      "iot",
    "kali-pentest":        "security",
    "l4t-jetson":          "edge_ai",
    "ardupilot-rover":     "robotics",
    "ardupilot-copter":    "robotics",
    "esphome-laskakit-esplan": "firmware",
    "esphome-bluetooth-proxy": "firmware",
    "esphome-vindriktning":    "firmware",
    "esphome-custom":          "firmware",
    "windows-workstation": "desktop",
    "proxmox-bare-metal":  "hypervisor",
}

USE_CASES: list[tuple[str, str, str, str]] = [
    # (key, label, tagline, accent)
    ("retro",      "Retro gaming",
     "Handhelds, arcade cabinets, retro laptops — Batocera presets.",
     "#1f6feb"),
    ("desktop",    "Desktop / workstation",
     "GNOME, Hyprland, Pop!_OS — daily-driver workstations.",
     "#e95420"),
    ("server",     "Server",
     "Headless Linux for fleet roles — Docker hosts, Kubernetes nodes, "
     "general servers.",
     "#0ea5e9"),
    ("iot",        "IoT / appliance",
     "Single-purpose images for home automation and headless Pis.",
     "#18bcf2"),
    ("hypervisor", "Bare-metal hypervisor",
     "Proxmox VE for fleet hosts.",
     "#e57000"),
    ("security",   "Pentest / security",
     "Kali workstation, ready for red-team use.",
     "#557c94"),
    ("edge_ai",    "Edge AI",
     "NVIDIA Jetson SDK images for on-device inference.",
     "#76b900"),
    ("robotics",   "Robotics / autopilot",
     "ArduPilot stacks on the BeagleBone Blue — rovers, drones, surface "
     "vehicles.",
     "#10b981"),
    ("firmware",   "Microcontroller firmware",
     "ESPHome configs for ESP32 / ESP8266 devices — Home Assistant "
     "integration, BLE proxies, sensor turnkeys. Flash to the chip "
     "directly from the browser.",
     "#000000"),
]


def bake_index(request: HttpRequest) -> HttpResponse:
    """Recipe-picker page — role templates grouped by use case."""
    os_filter = request.GET.get("os") or ""

    qs = (
        Recipe.objects.filter(status=Recipe.Status.ACTIVE)
        .select_related("operating_system")
        .prefetch_related("supported_hardware")
        .order_by("operating_system__name", "name")
    )
    if os_filter:
        qs = qs.filter(operating_system__slug=os_filter)

    cards_by_use_case: dict[str, list[dict]] = {}
    for r in qs:
        logo = _os_logo(r.operating_system.slug)
        card = {
            "slug": r.slug,
            "name": r.name,
            "summary": r.summary,
            "os_slug": r.operating_system.slug,
            "os_name": r.operating_system.name,
            "os_kind": r.operating_system.get_kind_display(),
            "logo_svg": logo["svg"],
            "logo_letter": logo["letter"],
            "accent": logo["accent"],
            "hardware": [
                {"slug": h.slug, "name": h.name}
                for h in r.supported_hardware.all()
            ],
        }
        use_case = RECIPE_USE_CASE.get(r.slug, "other")
        cards_by_use_case.setdefault(use_case, []).append(card)

    sections: list[dict] = []
    for key, label, tagline, accent in USE_CASES:
        cards = cards_by_use_case.get(key, [])
        if not cards:
            continue
        sections.append({
            "key": key,
            "label": label,
            "tagline": tagline,
            "accent": accent,
            "cards": cards,
            "n_cards": len(cards),
        })
    # Anything not in USE_CASES falls through to a final "Other" bucket.
    if "other" in cards_by_use_case:
        sections.append({
            "key": "other",
            "label": "Other",
            "tagline": "Recipes without a use-case mapping yet.",
            "accent": "#525252",
            "cards": cards_by_use_case["other"],
            "n_cards": len(cards_by_use_case["other"]),
        })

    return render(request, "bake_index.html", {
        "sections": sections,
        "total_recipes": sum(s["n_cards"] for s in sections),
        "all_operating_systems": OperatingSystem.objects.filter(
            is_active=True, recipes__status=Recipe.Status.ACTIVE,
        ).distinct().order_by("name"),
        "selected_os": os_filter,
    })


def bake_recipe(request: HttpRequest, slug: str) -> HttpResponse:
    """Per-recipe form: pick a hardware target + fill out options + bake."""
    recipe = get_object_or_404(
        Recipe.objects.select_related("operating_system", "pinned_release")
        .prefetch_related("supported_hardware", "options"),
        slug=slug,
    )
    version = (recipe.versions.filter(is_current=True).first()
               or recipe.versions.order_by("-created_at").first())
    if version is None:
        return render(request, "bake_recipe.html", {
            "recipe": recipe,
            "error": "This recipe has no published version yet.",
        }, status=400)

    options = list(recipe.options.order_by("sort_order", "key"))
    targets = list(
        recipe.supported_hardware.select_related("architecture").order_by("slug")
    )

    release = recipe.pinned_release or recipe.operating_system.releases.filter(
        is_default=True
    ).first()

    # For each (target, variant) we have a UpstreamImage row — group them
    # so the form can present a "Device · variant" picker.
    image_choices: list[dict] = []
    if release:
        for target in targets:
            target_images = UpstreamImage.objects.filter(
                release=release, hardware_target=target,
            ).order_by("variant")
            for img in target_images:
                variant = img.variant or ""
                label = target.name + (f" · {variant}" if variant else "")
                image_choices.append({
                    "id": img.id,
                    "target_slug": target.slug,
                    "target_name": target.name,
                    "arch": target.architecture.slug,
                    "variant": variant,
                    "label": label,
                })

    # Clusters the user can drop this device into. For now: all active
    # clusters across all tenants. When auth/tenancy lands, scope to the
    # requesting user's tenants.
    clusters_qs = (
        Cluster.objects.filter(is_active=True)
        .select_related("tenant")
        .order_by("tenant__name", "name")
    )

    if request.method == "POST":
        image_id = request.POST.get("upstream_image")
        upstream = UpstreamImage.objects.filter(pk=image_id).first()
        if not upstream:
            messages.error(request, "Pick a device + variant.")
        else:
            option_values: dict[str, object] = {}
            for opt in options:
                if opt.kind == "file":
                    # Upload to the artifact store; stash the key so the
                    # provisioner can fetch it (e.g. a HAOS backup .tar).
                    f = request.FILES.get(f"opt_{opt.key}")
                    if f:
                        import uuid as _uuid
                        key = f"uploads/{recipe.slug}/{_uuid.uuid4().hex}-{f.name}"
                        storages["artifacts"].save(key, f)
                        option_values[opt.key] = key
                    else:
                        option_values[opt.key] = ""
                    continue
                raw = request.POST.get(f"opt_{opt.key}", "")
                if opt.kind == RecipeOptionKind_BOOLEAN:
                    option_values[opt.key] = raw == "on"
                elif opt.kind == RecipeOptionKind_INTEGER:
                    try:
                        option_values[opt.key] = int(raw) if raw else None
                    except ValueError:
                        option_values[opt.key] = raw
                else:
                    option_values[opt.key] = raw

            cluster_id = request.POST.get("cluster") or None
            cluster_obj = (
                Cluster.objects.filter(pk=cluster_id).first()
                if cluster_id else None
            )

            build = BuildRequest.objects.create(
                recipe_version=version,
                hardware_target=upstream.hardware_target,
                upstream_image=upstream,
                option_values=option_values,
                label=str(option_values.get("hostname") or recipe.slug),
                requester=request.user if request.user.is_authenticated else None,
                cluster=cluster_obj,
                tenant=cluster_obj.tenant if cluster_obj else None,
            )
            messages.success(
                request,
                f"Build {build.id} queued"
                + (f" — joining {cluster_obj}" if cluster_obj else "")
                + ". Track it in the admin.",
            )
            return redirect(f"/admin/builds/buildrequest/{build.id}/change/")

    logo = _os_logo(recipe.operating_system.slug)
    # Build cluster choices for the template, grouped by tenant.
    cluster_choices = [
        {
            "id": c.id,
            "slug": c.slug,
            "name": c.name,
            "tenant_slug": c.tenant.slug,
            "tenant_name": c.tenant.name,
            "kind": c.get_kind_display(),
            "kind_key": c.kind,
        }
        for c in clusters_qs
    ]
    return render(request, "bake_recipe.html", {
        "recipe": recipe,
        "version": version,
        "release": release,
        "os_name": recipe.operating_system.name,
        "os_slug": recipe.operating_system.slug,
        "logo_svg": logo["svg"],
        "logo_letter": logo["letter"],
        "accent": logo["accent"],
        "options": options,
        "image_choices": image_choices,
        "cluster_choices": cluster_choices,
    })


# Avoid hardcoding string literals when checking RecipeOption.kind.
RecipeOptionKind_BOOLEAN = "boolean"
RecipeOptionKind_INTEGER = "integer"


# ---------------------------------------------------------------------------
# Docs viewer — render markdown files under docs/ as styled HTML
# ---------------------------------------------------------------------------

# Files allowed to be rendered. Keeps the view from serving arbitrary
# project paths under /docs/<slug>/. Add a row when you want a new doc on
# the site.
DOCS_ON_SITE: dict[str, dict[str, str]] = {
    "flashing": {
        "title": "Flashing baked images",
        "tagline": "Per-format, per-OS: how to write the artifact onto SD / "
                   "USB / VM / ESP.",
        "file": "docs/flashing.md",
    },
    "catalog": {
        "title": "Catalog matrix",
        "tagline": "Every Architecture / HardwareTarget / OperatingSystem / "
                   "OSRelease / UpstreamImage row the seed creates.",
        "file": "docs/catalog.md",
    },
    "platforms": {
        "title": "Supported platforms",
        "tagline": "The wider device universe — Pis, BeagleBone, Jetson, "
                   "PCs, VMs, future targets.",
        "file": "docs/platforms.md",
    },
}


def docs_index(request: HttpRequest) -> HttpResponse:
    pages = [
        {"slug": slug, **meta}
        for slug, meta in DOCS_ON_SITE.items()
    ]
    return render(request, "docs_index.html", {"pages": pages})


def doc_page(request: HttpRequest, slug: str) -> HttpResponse:
    meta = DOCS_ON_SITE.get(slug)
    if meta is None:
        raise Http404(f"Unknown doc: {slug!r}")

    import markdown

    path = Path(settings.BASE_DIR) / meta["file"]
    if not path.exists():
        raise Http404(f"Doc file missing on disk: {path}")

    text = path.read_text(encoding="utf-8")
    body_html = markdown.markdown(
        text,
        extensions=["tables", "fenced_code", "toc", "sane_lists"],
        output_format="html5",
    )
    return render(request, "doc.html", {
        "slug": slug,
        "title": meta["title"],
        "tagline": meta["tagline"],
        "body_html": body_html,
        "other_pages": [
            {"slug": s, **m}
            for s, m in DOCS_ON_SITE.items() if s != slug
        ],
    })
