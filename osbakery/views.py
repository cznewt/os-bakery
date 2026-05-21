"""Public-facing views for the os-bakery landing page.

Lives in `osbakery/` (the project) rather than under any single app because
these views compose data from `catalog` + `recipes` + `builds`.
"""

from __future__ import annotations

from django.db.models import Count, Prefetch
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from catalog.models import HardwareTarget, OperatingSystem, OSRelease, UpstreamImage


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
    "raspios": {
        "svg": "https://cdn.simpleicons.org/raspberrypi/c51a4a",
        "accent": "#c51a4a",
    },
    "haos": {
        "svg": "https://cdn.simpleicons.org/homeassistant/18bcf2",
        "accent": "#18bcf2",
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
