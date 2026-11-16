#!/usr/bin/env python3
"""Remove private image metadata before committing, preserving display metadata."""

import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile


SUPPORTED_MIME_TYPES = {
    "image/jpeg", "image/png", "image/webp", "image/gif", "image/avif",
    "image/heic", "image/heif",
}
IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".jpe", ".png", ".apng", ".webp", ".gif", ".avif",
    ".heic", ".heif", ".hif", ".tif", ".tiff", ".svg", ".svgz", ".bmp",
    ".ico", ".icns", ".psd", ".psb", ".raw", ".dng", ".cr2", ".cr3",
    ".nef", ".arw", ".raf", ".orf", ".rw2", ".jxl", ".jp2", ".exr",
}
DISPLAY_EXIF_TAGS = {
    "IFD0:Orientation", "IFD0:XResolution", "IFD0:YResolution",
    "IFD0:ResolutionUnit", "IFD0:YCbCrPositioning", "ExifIFD:ExifVersion",
    "ExifIFD:FlashpixVersion", "ExifIFD:ComponentsConfiguration",
    "ExifIFD:ColorSpace", "ExifIFD:Gamma", "InteropIFD:InteropIndex",
    "InteropIFD:InteropVersion",
}
PRIVATE_GROUPS = {"XMP", "IPTC", "MakerNotes", "Photoshop", "AFCP", "CanonVRD"}
PRIVATE_TAGS = {
    "Comment", "ImageDescription", "Description", "Title", "Author", "Artist",
    "Copyright", "Software", "Make", "Model", "SerialNumber", "CreateDate",
    "ModifyDate", "DateTimeOriginal", "CreationTime", "CreationDate",
}


class HookError(Exception):
    pass


def run_git(*args):
    result = subprocess.run(["git", *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        raise HookError("Git command failed: git " + args[0])
    return result.stdout


def exiftool(path, *options):
    # Ignore machine-specific ExifTool configuration and never print tag values.
    result = subprocess.run(
        ["exiftool", "-config", "", *options, str(path)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if result.returncode:
        raise HookError("ExifTool failed for " + repr(str(path)))
    return result


def read_metadata(path):
    result = exiftool(path, "-json", "-G0:1", "-a", "-s", "-n")
    try:
        records = json.loads(result.stdout)
        if not isinstance(records, list) or len(records) != 1 or not isinstance(records[0], dict):
            raise ValueError("expected one metadata record")
    except (ValueError, TypeError) as error:
        raise HookError("Invalid ExifTool response for " + repr(str(path))) from error
    metadata = records[0]
    if any(key.rsplit(":", 1)[-1] in {"Error", "Warning"} for key in metadata):
        raise HookError("Invalid image or metadata structure: " + repr(str(path)))
    return metadata


def field(metadata, name):
    return next((value for key, value in metadata.items()
                 if key.rsplit(":", 1)[-1] == name), None)


def has_symlink(path):
    return any(parent.is_symlink() for parent in (path, *path.parents))


def validate_clean(path, metadata):
    for key in metadata:
        parts = key.split(":")
        group, tag = parts[0], parts[-1]
        if group in {"File", "System", "ExifTool", "ICC_Profile"} or key == "SourceFile":
            continue
        private = (
            group in PRIVATE_GROUPS
            or (group == "EXIF" and ":".join(parts[1:]) not in DISPLAY_EXIF_TAGS)
            or tag in PRIVATE_TAGS
            or any(word in tag.lower() for word in ("gps", "location", "latitude", "longitude"))
        )
        if private:
            raise HookError("Metadata remains (" + key + "): " + repr(str(path)))


def tracked_files():
    files = []
    for entry in run_git("ls-files", "--stage", "-z", "--", "assets/").split(b"\0"):
        if not entry:
            continue
        header, name = entry.split(b"\t", 1)
        mode, object_id, stage = header.split()
        path = Path(os.fsdecode(name))
        if stage != b"0":
            raise HookError("Resolve the merge conflict before committing: " + repr(str(path)))
        if mode not in {b"100644", b"100755"}:
            raise HookError("Only regular files are supported in assets: " + repr(str(path)))
        # Check parents too, so a replaced directory cannot redirect writes outside assets.
        if has_symlink(path):
            raise HookError("Symlinks are not supported in assets: " + repr(str(path)))
        if not path.is_file():
            raise HookError("Stage or restore the deleted asset before committing: " + repr(str(path)))
        files.append((path, object_id.decode("ascii")))
    return files


def clean_images():
    files = tracked_files()
    if not files:
        return
    if not shutil.which("exiftool"):
        raise HookError("exiftool is required; install it and run make setup.")

    images = []
    for path, object_id in files:
        if path.stat().st_size == 0 and path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        metadata = read_metadata(path)
        mime_type = field(metadata, "MIMEType") or ""
        if mime_type not in SUPPORTED_MIME_TYPES:
            if mime_type.startswith("image/") or path.suffix.lower() in IMAGE_EXTENSIONS:
                raise HookError("Unsupported image format: " + repr(str(path)))
            continue
        # Compare bytes to the active index, including git commit --only's temporary index.
        original = path.read_bytes()
        if original != run_git("cat-file", "blob", object_id):
            raise HookError("Stage or stash unstaged image edits before committing: " + repr(str(path)))
        images.append((path, original))

    changed = []
    with tempfile.TemporaryDirectory(prefix="blog-image-metadata-") as temporary:
        for number, (path, original) in enumerate(images):
            copy = Path(temporary) / (str(number) + path.suffix)
            copy.write_bytes(original)
            try:
                exiftool(
                    copy, "-overwrite_original", "-all=", "--icc_profile:all",
                    "-tagsfromfile", "@", "-colorspacetags", "-Orientation",
                )
                validate_clean(path, read_metadata(copy))
            except HookError as error:
                raise HookError("Could not sanitize " + repr(str(path)) + ": " + str(error)) from error
            cleaned = copy.read_bytes()
            if cleaned != original:
                changed.append((path, original, cleaned))

        # Git restores a separately prepared index after a path-limited commit,
        # which would stage the old, private metadata again after this hook.
        if changed and os.environ.get("GIT_INDEX_FILE"):
            normal_index = Path(os.fsdecode(run_git("rev-parse", "--absolute-git-dir").rstrip(b"\n"))) / "index"
            if Path(os.environ["GIT_INDEX_FILE"]).resolve() != normal_index.resolve():
                raise HookError(
                    "Image cleanup requires a normal staged commit. Use git add, then git commit "
                    "without path arguments or --only (and without an alternate GIT_INDEX_FILE)."
                )

        # Recheck before applying results, in case an editor changed a file during processing.
        for path, original in images:
            if not path.is_file() or has_symlink(path) or path.read_bytes() != original:
                raise HookError("Image changed during metadata removal: " + repr(str(path)))
        for path, _, cleaned in changed:
            # Replace in the same directory so permissions survive and writes are atomic.
            descriptor, replacement = tempfile.mkstemp(prefix=".metadata-", dir=path.parent)
            try:
                with os.fdopen(descriptor, "wb") as output:
                    output.write(cleaned)
                os.chmod(replacement, stat.S_IMODE(path.stat().st_mode))
                os.replace(replacement, path)
            finally:
                if os.path.exists(replacement):
                    os.unlink(replacement)
        if changed:
            paths = b"".join(os.fsencode(path) + b"\0" for path, _, _ in changed)
            result = subprocess.run(
                ["git", "--literal-pathspecs", "add", "--pathspec-from-file=-", "--pathspec-file-nul"],
                input=paths, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            if result.returncode:
                raise HookError("Could not stage sanitized images; inspect git status and retry.")
            for path, _, _ in changed:
                print("Removed image metadata: " + repr(str(path)), file=sys.stderr)


def main():
    try:
        os.chdir(os.fsdecode(run_git("rev-parse", "--show-toplevel").rstrip(b"\n")))
        clean_images()
    except (HookError, OSError) as error:
        print("Image metadata hook: " + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
