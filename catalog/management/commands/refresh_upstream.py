"""Download + decompress + cache an UpstreamImage into MinIO/S3.

Populates ``UpstreamImage.cache_storage_key`` so the build orchestrator
fetches the cached blob from the same backend that serves artifacts —
no shared filesystem volume needed across workers.

Cache layout in the bucket — the mirror keeps the original (decompressed)
upstream filename so the cached object matches the source image::

    cache/<os-slug>/<original-image-name>.img

Usage::

    python manage.py refresh_upstream --os haos --target rpi4
    python manage.py refresh_upstream --os batocera --target rpi3 --release 43
    python manage.py refresh_upstream --all
    python manage.py refresh_upstream --force --os haos     # re-download
"""

from __future__ import annotations

import gzip
import hashlib
import lzma
import ssl
import shutil
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from django.core.files.storage import storages
from django.core.management.base import BaseCommand
from django.utils import timezone

from catalog.models import UpstreamImage


class Command(BaseCommand):
    help = "Download + cache UpstreamImage rows into the artifacts S3 bucket."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--os", help="Filter to OperatingSystem.slug.")
        parser.add_argument("--target", help="Filter to HardwareTarget.slug.")
        parser.add_argument("--release", help="Filter to OSRelease.version.")
        parser.add_argument("--variant", help="Filter to UpstreamImage.variant.")
        parser.add_argument(
            "--all", action="store_true",
            help="Refresh every UpstreamImage (multi-GB per row).",
        )
        parser.add_argument(
            "--force", action="store_true",
            help="Re-download even when a cached copy already exists in S3.",
        )

    def handle(self, *args, os: str | None = None, target: str | None = None,
               release: str | None = None, variant: str | None = None,
               all: bool = False, force: bool = False, **options) -> None:
        qs = UpstreamImage.objects.select_related(
            "release__operating_system", "hardware_target",
        )
        if os:
            qs = qs.filter(release__operating_system__slug=os)
        if target:
            qs = qs.filter(hardware_target__slug=target)
        if release:
            qs = qs.filter(release__version=release)
        if variant is not None:
            qs = qs.filter(variant=variant)

        if not (os or target or release or variant) and not all:
            self.stdout.write(self.style.WARNING(
                "Refusing to refresh ALL upstream images without --all "
                "(each can be multi-GB). Filter with --os / --target / "
                "--release / --variant."
            ))
            return

        rows = list(qs)
        if not rows:
            self.stdout.write(self.style.WARNING("No UpstreamImage matched."))
            return

        self.stdout.write(f"Refreshing {len(rows)} image(s) into the "
                          f"`artifacts` storage backend…")
        for img in rows:
            try:
                self._refresh_one(img, force=force)
            except Exception as exc:
                self.stderr.write(self.style.ERROR(
                    f"  [error]   {img}: {exc!r}"
                ))

    # -----------------------------------------------------------------

    @staticmethod
    def _cache_key(img: UpstreamImage) -> str:
        """Mirror key that keeps the original (decompressed) image filename.

        e.g. source batocera-zen3-x86-64-v3-43-20260430.img.gz is cached as
        cache/batocera/batocera-zen3-x86-64-v3-43-20260430.img. Falls back to a
        synthesised <version>-<variant>.img when the URL has no usable filename.
        """
        os_slug = img.release.operating_system.slug
        name = (img.source_url.rsplit("/", 1)[-1] or "").split("?")[0]
        for ext in (".gz", ".xz", ".bz2", ".zst", ".zip"):
            if name.lower().endswith(ext):
                name = name[: -len(ext)]
                break
        if not name or "." not in name:
            variant_tag = img.variant or "base"
            name = f"{img.release.version}-{variant_tag}.img"
        return f"cache/{os_slug}/{name}"

    def _refresh_one(self, img: UpstreamImage, *, force: bool) -> None:
        storage = storages["artifacts"]
        cache_key = self._cache_key(img)

        if storage.exists(cache_key) and not force:
            self.stdout.write(f"  [cached]  {img}: {cache_key}")
            self._stamp_existing(img, storage, cache_key)
            return

        self.stdout.write(f"  [fetching] {img}: {img.source_url}")
        with tempfile.TemporaryDirectory(prefix="osbakery-cache-") as tmp:
            archive_path = Path(tmp) / "archive"
            raw_path = Path(tmp) / "raw.img"

            size_dl = self._stream_download(img.source_url, archive_path)
            self.stdout.write(f"             ↳ downloaded {size_dl:,} bytes")

            self._decompress(img.source_url, archive_path, raw_path)
            size_raw = raw_path.stat().st_size
            self.stdout.write(f"             ↳ decompressed to {size_raw:,} bytes")

            digest = self._sha256_file(raw_path)
            self.stdout.write(f"             ↳ sha256 {digest[:16]}…")

            self.stdout.write(f"             ↳ uploading to {cache_key}")
            with raw_path.open("rb") as fh:
                # storage.save returns the actual key (could differ if the
                # backend renames on collision); we want exact-key writes,
                # so delete any old copy first.
                if storage.exists(cache_key):
                    storage.delete(cache_key)
                stored_key = storage.save(cache_key, fh)

        img.cache_storage_key = stored_key
        img.checksum_sha256 = digest
        img.size_bytes = size_raw
        img.last_synced_at = timezone.now()
        img.save(update_fields=[
            "cache_storage_key", "checksum_sha256",
            "size_bytes", "last_synced_at",
        ])
        self.stdout.write(self.style.SUCCESS(
            f"  [ok]       {stored_key}  size={size_raw:,}"
        ))

    def _stamp_existing(self, img: UpstreamImage, storage, key: str) -> None:
        img.cache_storage_key = key
        img.last_synced_at = timezone.now()
        img.save(update_fields=["cache_storage_key", "last_synced_at"])

    # -----------------------------------------------------------------
    # transport helpers
    # -----------------------------------------------------------------

    def _stream_download(self, url: str, dest: Path) -> int:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent":
                    "osbakery/1.0 (+https://github.com/cznewt/os-bakery)",
            },
        )
        try:
            return self._download(req, dest)
        except urllib.error.URLError as exc:
            # Some upstreams (e.g. download.proxmox.com) serve a cert that
            # fails hostname/chain verification. Retry once without SSL
            # verification rather than failing the whole sync.
            reason = getattr(exc, "reason", exc)
            if isinstance(reason, ssl.SSLError) or isinstance(exc, ssl.SSLError):
                self.stdout.write(self.style.WARNING(
                    f"             ↳ SSL verification failed for {url} "
                    f"({reason}); retrying without verification."
                ))
                return self._download(req, dest, context=ssl._create_unverified_context())
            raise

    def _download(self, req, dest: Path, context=None) -> int:
        size = 0
        with urllib.request.urlopen(req, timeout=180, context=context) as resp, \
                dest.open("wb") as out:
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                size += len(chunk)
        return size

    def _decompress(self, url: str, archive: Path, out: Path) -> None:
        suffix = url.rsplit(".", 1)[-1].lower()
        if suffix == "xz":
            with lzma.open(archive, "rb") as fh, out.open("wb") as out_fh:
                shutil.copyfileobj(fh, out_fh)
        elif suffix == "gz":
            with gzip.open(archive, "rb") as fh, out.open("wb") as out_fh:
                shutil.copyfileobj(fh, out_fh)
        elif suffix == "zip":
            with zipfile.ZipFile(archive) as zf:
                members = [m for m in zf.namelist()
                           if m.lower().endswith(".img")] or zf.namelist()
                with zf.open(members[0]) as fh, out.open("wb") as out_fh:
                    shutil.copyfileobj(fh, out_fh)
        else:
            archive.rename(out)

    def _sha256_file(self, path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
