"""One-shot: queue a ~16-build per-provisioner test sweep under the `test`
tenant. Piped into `manage.py shell` on prod. Idempotent by label (re-queues
existing rows). The BuildRequest post_save signal dispatches each to Celery.
"""
from django.db.models import Q
from builds.models import BuildRequest
from builds.tasks import run_build
from builds.signals import route_queue_for_build
from catalog.models import HardwareTarget, UpstreamImage
from recipes.models import Recipe
from tenants.models import Cluster, Tenant

# (label, recipe_slug, os_slug, target_slug, variant|None, version|None, cluster_slug)
SPECS = [
    # Batocera — batocera_pkg (x86 full, x86 zen-handheld, ARM RK3566, ARM bcm2711)
    ("test-bato-arcade-pcamd64",   "batocera-arcade",   "batocera", "pc-amd64",  "full", None, "test-batocera"),
    ("test-bato-notebook-pcamd64", "batocera-notebook", "batocera", "pc-amd64",  "full", None, "test-batocera"),
    ("test-bato-handheld-lokizero","batocera-handheld", "batocera", "loki-zero", "zen",  None, "test-batocera"),
    ("test-bato-handheld-rg353p",  "batocera-handheld", "batocera", "rg353p",    "",     None, "test-batocera"),
    ("test-bato-handheld-rpi4",    "batocera-handheld", "batocera", "rpi4",      "",     None, "test-batocera"),
    # Ubuntu — cloud_init (cloud amd64, cloud arm64, VM, desktop ISO, raspi preinstalled)
    ("test-ubuntu-docker-pcamd64", "ubuntu-docker",  "ubuntu", "pc-amd64", "server",  None, "test-ubuntu"),
    ("test-ubuntu-docker-vmqemu",  "ubuntu-docker",  "ubuntu", "vm-qemu",  "server",  None, "test-ubuntu"),
    ("test-ubuntu-kube-pcarm64",   "ubuntu-kube",    "ubuntu", "pc-arm64", "server",  None, "test-ubuntu"),
    ("test-ubuntu-kube-vmqemu",    "ubuntu-kube",    "ubuntu", "vm-qemu",  "server",  None, "test-ubuntu"),
    ("test-ubuntu-desktop-pcamd64","ubuntu-desktop", "ubuntu", "pc-amd64", "desktop", None, "test-ubuntu"),
    ("test-ubuntu-desktop-rpi4",   "ubuntu-desktop", "ubuntu", "rpi4",     "desktop", None, "test-ubuntu"),
    # Proxmox VE — proxmox_autoinstall (both releases)
    ("test-proxmox-83",            "proxmox-bare-metal", "proxmox-ve", "pc-amd64", None, "8.3", "test-ubuntu"),
    ("test-proxmox-91",            "proxmox-bare-metal", "proxmox-ve", "pc-amd64", None, "9.1", "test-ubuntu"),
    # HAOS — haos_pkg (x86 board, ARM board, VM qcow2)
    ("test-haos-pcamd64",          "haos-appliance", "haos", "pc-amd64", None, None, "test-haos"),
    ("test-haos-rpi4",             "haos-appliance", "haos", "rpi4",     None, None, "test-haos"),
    ("test-haos-vmqemu",           "haos-appliance", "haos", "vm-qemu",  None, None, "test-haos"),
]


def pick_image(os_slug, target_slug, variant, version):
    qs = (UpstreamImage.objects
          .filter(release__operating_system__slug=os_slug)
          .filter(Q(hardware_target__slug=target_slug)
                  | Q(extra_targets__slug=target_slug))
          .distinct())
    if version:
        qs = qs.filter(release__version=version)
    if variant is not None:
        qs = qs.filter(variant=variant)
    return qs.order_by("-release__version").first()


tenant = Tenant.objects.get(slug="test")
created = requeued = skipped = 0

for label, recipe_slug, os_slug, target_slug, variant, version, cluster_slug in SPECS:
    recipe = Recipe.objects.filter(slug=recipe_slug).first()
    rv = recipe and (recipe.versions.filter(is_current=True).first()
                     or recipe.versions.order_by("-created_at").first())
    target = HardwareTarget.objects.filter(slug=target_slug).first()
    cluster = Cluster.objects.filter(tenant=tenant, slug=cluster_slug).first()
    image = pick_image(os_slug, target_slug, variant, version)
    if not (rv and target and cluster and image):
        print(f"  SKIP {label}: "
              f"{'recipe ' if not rv else ''}{'target ' if not target else ''}"
              f"{'cluster ' if not cluster else ''}{'image' if not image else ''}")
        skipped += 1
        continue

    existing = BuildRequest.objects.filter(label=label).first()
    if existing is None:
        b = BuildRequest.objects.create(
            recipe_version=rv, hardware_target=target, upstream_image=image,
            cluster=cluster, tenant=tenant, label=label,
            option_values={"hostname": label},
            status=BuildRequest.Status.QUEUED,
        )
        print(f"  CREATED  {b.id}  {label}  ({os_slug}/{target_slug} v{image.release.version} {image.variant or '-'})")
        created += 1
    else:
        existing.recipe_version, existing.hardware_target = rv, target
        existing.upstream_image, existing.cluster = image, cluster
        existing.status = BuildRequest.Status.QUEUED
        existing.failure_reason = ""
        existing.started_at = existing.finished_at = None
        existing.save()
        q = route_queue_for_build(existing)
        ar = run_build.apply_async(args=[str(existing.id)], queue=q)
        BuildRequest.objects.filter(pk=existing.pk).update(celery_task_id=ar.id)
        print(f"  REQUEUED {existing.id}  {label}  -> {q}")
        requeued += 1

print(f"\nDone: {created} created, {requeued} requeued, {skipped} skipped.")
