import json
import os
from pathlib import Path
import shlex
import shutil
import struct
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
GIT = shutil.which("git")
EXIFTOOL = shutil.which("exiftool")
# Point Nemo in the South Pacific, far from any country's territorial sea or EEZ.
TEST_LATITUDE = -48.876667
TEST_LONGITUDE = -123.393333


class ImageMetadataHookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not GIT or not EXIFTOOL:
            raise RuntimeError("Install Git and ExifTool before running these tests.")

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="blog-hook-test-")
        self.addCleanup(self.temporary.cleanup)
        self.repo = Path(self.temporary.name)
        self.env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        self.env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
        for directory in (".githooks", "scripts"):
            shutil.copytree(ROOT / directory, self.repo / directory, ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy2(ROOT / "Makefile", self.repo / "Makefile")
        self.git("init", "-q")
        self.git("config", "user.name", "Hook Test")
        self.git("config", "user.email", "hook-test@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        self.run_command("make", "setup")

    def run_command(self, *args, check=True, env=None):
        result = subprocess.run(
            args, cwd=self.repo, env=env or self.env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        if check and result.returncode:
            self.fail("Command failed: " + repr(args) + "\n" + result.stderr.decode(errors="replace"))
        return result

    def git(self, *args, **options):
        return self.run_command(GIT, *args, **options)

    def image(self, name="assets/photo.jpg", fixture=None):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        extension = path.suffix.lower().lstrip(".")
        fixture = fixture or ("heic" if extension == "heif" else extension)
        shutil.copyfile(FIXTURES / ("image." + fixture), path)
        return path

    def add_metadata(self, *paths):
        self.run_command(
            EXIFTOOL, "-config", "", "-overwrite_original",
            f"-XMP-exif:GPSLatitude={TEST_LATITUDE}", f"-XMP-exif:GPSLongitude={TEST_LONGITUDE}",
            "-XMP-dc:Creator=Synthetic Author", "-XMP-tiff:Model=Synthetic camera",
            "-XMP-xmp:CreateDate=2020:01:02 03:04:05", *map(str, paths),
        )

    def tags(self, path):
        result = self.run_command(EXIFTOOL, "-config", "", "-j", "-G1", "-a", "-s", "-n", str(path))
        return json.loads(result.stdout)[0]

    def committed_image(self, name):
        contents = self.git("show", "HEAD:" + name).stdout
        path = self.repo / ("committed" + Path(name).suffix)
        path.write_bytes(contents)
        return path

    def assert_private_metadata_removed(self, path):
        tags = self.tags(path)
        self.assertFalse(any(key.startswith(("XMP", "GPS:", "IPTC:", "MakerNotes:")) for key in tags), tags)
        self.assertNotIn("Synthetic", json.dumps(tags))
        self.assertNotIn("2020:01:02", json.dumps(tags))

    def index_tree(self):
        return self.git("write-tree").stdout

    def test_all_formats_are_sanitized_in_the_commit(self):
        names = ["assets/写真 with spaces.JPG", "assets/photo.png", "assets/photo.webp",
                 "assets/photo.gif", "assets/photo.avif", "assets/photo.heic", "assets/photo.heif"]
        paths = [self.image(name) for name in names]
        self.add_metadata(*paths)
        for path in paths:
            tags = self.tags(path)
            self.assertAlmostEqual(tags["XMP-exif:GPSLatitude"], TEST_LATITUDE, places=5)
            self.assertAlmostEqual(tags["XMP-exif:GPSLongitude"], TEST_LONGITUDE, places=5)
        self.run_command(
            EXIFTOOL, "-config", "", "-overwrite_original",
            f"-GPSLatitude={abs(TEST_LATITUDE)}", "-GPSLatitudeRef=S",
            f"-GPSLongitude={abs(TEST_LONGITUDE)}", "-GPSLongitudeRef=W",
            "-DateTimeOriginal=2020:01:02 03:04:05", "-Model=Synthetic camera",
            "-Comment=Synthetic comment", "-IPTC:City=Synthetic city", str(paths[0]),
        )
        tags = self.tags(paths[0])
        self.assertEqual(tags["GPS:GPSLatitudeRef"], "S")
        self.assertEqual(tags["GPS:GPSLongitudeRef"], "W")
        self.assertAlmostEqual(tags["Composite:GPSLatitude"], TEST_LATITUDE, places=5)
        self.assertAlmostEqual(tags["Composite:GPSLongitude"], TEST_LONGITUDE, places=5)
        self.git("add", "assets")
        self.git("commit", "-qm", "All formats")
        for name in names:
            with self.subTest(name=name):
                self.assert_private_metadata_removed(self.committed_image(name))
                self.assertEqual((self.repo / name).read_bytes(), self.git("show", "HEAD:" + name).stdout)
        self.assertEqual(self.git("diff", "--name-only").stdout, b"")
        self.assertFalse(list((self.repo / "assets").glob("*_original")))

    def test_display_metadata_and_image_data_survive_and_cleanup_is_idempotent(self):
        path = self.image()
        # A synthetic ICC header tests byte-for-byte profile preservation without vendor data.
        profile = bytearray(132)
        profile[0:4] = struct.pack(">I", len(profile))
        profile[8:12] = b"\x02\x10\0\0"
        profile[12:24] = b"mntrRGB XYZ "
        profile[24:36] = struct.pack(">6H", 2020, 1, 2, 3, 4, 5)
        profile[36:40] = b"acsp"
        profile[68:80] = struct.pack(">iii", 63190, 65536, 54061)
        description = b"desc" + b"\0" * 4 + struct.pack(">I", 10) + b"Synthetic\0" + b"\0" * 78
        profile[128:132] = struct.pack(">I", 1)
        profile.extend(b"desc" + struct.pack(">II", 144, len(description)))
        profile.extend(description)
        profile[0:4] = struct.pack(">I", len(profile))
        profile_path = self.repo / "test.icc"
        profile_path.write_bytes(profile)
        self.add_metadata(path)
        self.run_command(
            EXIFTOOL, "-config", "", "-overwrite_original", "-Orientation#=6", "-ColorSpace#=1",
            "-ICC_Profile<=" + str(profile_path), str(path),
        )
        before_hash = self.run_command(EXIFTOOL, "-config", "", "-s3", "-ImageDataHash", str(path)).stdout
        self.assertTrue(before_hash.strip())
        self.git("add", "assets")
        self.git("commit", "-qm", "Display metadata")
        tags = self.tags(path)
        self.assertEqual(tags["IFD0:Orientation"], 6)
        self.assertEqual(tags["ExifIFD:ColorSpace"], 1)
        self.assertEqual(self.run_command(EXIFTOOL, "-config", "", "-b", "-ICC_Profile", str(path)).stdout, profile)
        self.assertEqual(self.run_command(EXIFTOOL, "-config", "", "-s3", "-ImageDataHash", str(path)).stdout, before_hash)
        cleaned = path.read_bytes()
        (self.repo / "article.md").write_text("Next article\n")
        self.git("add", "article.md")
        self.git("commit", "-qm", "Next commit")
        self.assertEqual(path.read_bytes(), cleaned)
        self.assertEqual(self.git("diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").stdout, b"article.md\n")

    def test_existing_images_are_cleaned_without_staging_other_edits(self):
        path = self.image()
        self.add_metadata(path)
        article = self.repo / "article.md"
        article.write_text("Original\n")
        self.git("add", "assets", "article.md")
        self.git("-c", "core.hooksPath=/dev/null", "commit", "-qm", "Legacy image")
        article.write_text("Unstaged changes\n")
        (self.repo / "new.md").write_text("Staged article\n")
        self.git("add", "new.md")
        self.git("commit", "-qm", "Unrelated article")
        self.assert_private_metadata_removed(self.committed_image("assets/photo.jpg"))
        self.assertEqual(self.git("show", "HEAD:article.md").stdout, b"Original\n")
        self.assertEqual(article.read_text(), "Unstaged changes\n")

    def test_path_limited_commit_does_not_restore_private_metadata_in_the_index(self):
        path = self.image()
        self.add_metadata(path)
        article = self.repo / "article.md"
        article.write_text("Original\n")
        self.git("add", "assets", "article.md")
        self.git("-c", "core.hooksPath=/dev/null", "commit", "-qm", "Legacy image")
        article.write_text("Updated\n")
        tree, original = self.index_tree(), path.read_bytes()
        result = self.git("commit", "--only", "-qm", "Selected article", "--", "article.md", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"normal staged commit", result.stderr)
        self.assertEqual(self.index_tree(), tree)
        self.assertEqual(path.read_bytes(), original)
        self.git("add", "article.md")
        self.git("commit", "-qm", "Normal staged commit")
        self.assert_private_metadata_removed(self.committed_image("assets/photo.jpg"))
        self.assertEqual(self.git("status", "--porcelain", "--", "assets").stdout, b"")
        article.write_text("Another update\n")
        self.git("commit", "--only", "-qm", "Already clean", "--", "article.md")
        self.assertEqual(self.git("status", "--porcelain", "--", "assets").stdout, b"")

    def test_unstaged_image_edits_do_not_change_any_files_or_index(self):
        first = self.image("assets/a.jpg")
        second = self.image("assets/z.jpg")
        self.add_metadata(first, second)
        self.git("add", "assets")
        self.run_command(EXIFTOOL, "-config", "", "-overwrite_original", "-Comment=Unstaged edit", str(second))
        before = {path: path.read_bytes() for path in (first, second)}
        tree = self.index_tree()
        result = self.git("commit", "-qm", "Must fail", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"unstaged image edits", result.stderr)
        self.assertEqual(self.index_tree(), tree)
        self.assertEqual({path: path.read_bytes() for path in before}, before)

    def test_staged_deletion_rename_and_untracked_images(self):
        old = self.image("assets/old.jpg")
        self.add_metadata(old)
        removed = self.image("assets/delete.png")
        self.git("add", "assets")
        self.git("-c", "core.hooksPath=/dev/null", "commit", "-qm", "Legacy paths")
        self.git("mv", "assets/old.jpg", "assets/renamed.jpg")
        self.git("rm", str(removed.relative_to(self.repo)))
        untracked = self.image("assets/untracked.jpg")
        self.add_metadata(untracked)
        original = untracked.read_bytes()
        self.git("commit", "-qm", "Move images")
        self.assert_private_metadata_removed(self.committed_image("assets/renamed.jpg"))
        self.assertEqual(untracked.read_bytes(), original)
        files = self.git("ls-tree", "-r", "--name-only", "HEAD").stdout
        self.assertNotIn(b"assets/old.jpg", files)
        self.assertNotIn(b"assets/delete.png", files)
        self.assertNotIn(b"assets/untracked.jpg", files)

    def test_unstaged_deletion_is_rejected(self):
        path = self.image()
        self.git("add", "assets")
        tree = self.index_tree()
        path.unlink()
        self.assertNotEqual(self.git("commit", "-qm", "Missing image", check=False).returncode, 0)
        self.assertEqual(self.index_tree(), tree)
        self.assertFalse(path.exists())

    def test_unsupported_disguised_and_damaged_images_are_rejected(self):
        good = self.image("assets/a.jpg")
        self.add_metadata(good)
        for filename, contents in (
            ("assets/z.svg", b'<svg xmlns="http://www.w3.org/2000/svg"/>'),
            ("assets/z.dat", b'<svg xmlns="http://www.w3.org/2000/svg"/>'),
            ("assets/z.png", b"not a PNG image"),
        ):
            with self.subTest(filename=filename):
                bad = self.repo / filename
                bad.write_bytes(contents)
                self.git("add", "assets")
                tree, original = self.index_tree(), good.read_bytes()
                self.assertNotEqual(self.git("commit", "-qm", "Bad image", check=False).returncode, 0)
                self.assertEqual(self.index_tree(), tree)
                self.assertEqual(good.read_bytes(), original)
                self.assertEqual(bad.read_bytes(), contents)
                self.git("rm", "--cached", "--", filename)
                bad.unlink()

    def test_actual_format_is_detected_without_a_filename_extension(self):
        path = self.image("assets/no-extension", fixture="jpg")
        self.add_metadata(path)
        self.git("add", "assets")
        self.git("commit", "-qm", "Content detection")
        self.assert_private_metadata_removed(path)

    def test_glb_models_are_untouched_and_renamed_images_are_still_sanitized(self):
        path = self.image("assets/photo.glb", fixture="jpg")
        self.add_metadata(path)
        model_json = json.dumps({"asset": {"version": "2.0"}, "scenes": [{"nodes": []}], "scene": 0}).encode()
        model_json += b" " * (-len(model_json) % 4)
        model_bytes = struct.pack("<4sIIII", b"glTF", 2, 20 + len(model_json), len(model_json), 0x4E4F534A) + model_json
        model = self.repo / "assets" / "model.glb"
        model.write_bytes(model_bytes)
        self.git("add", "assets")
        self.git("commit", "-qm", "GLB alongside images")
        self.assertEqual(self.git("show", "HEAD:assets/model.glb").stdout, model_bytes)
        self.assertEqual(model.read_bytes(), model_bytes)
        self.assert_private_metadata_removed(self.committed_image("assets/photo.glb"))

    def test_symlinks_and_replaced_parent_directories_are_rejected(self):
        outside = self.image("outside/photo.jpg")
        self.add_metadata(outside)
        original = outside.read_bytes()
        link = self.repo / "assets" / "photo.jpg"
        link.parent.mkdir()
        link.symlink_to(outside)
        self.git("add", "assets")
        self.assertNotEqual(self.git("commit", "-qm", "Symlink", check=False).returncode, 0)
        self.assertEqual(outside.read_bytes(), original)
        self.git("rm", "--cached", "assets/photo.jpg")
        link.unlink()
        directory = self.repo / "assets" / "directory"
        directory.mkdir()
        shutil.copyfile(outside, directory / "photo.jpg")
        self.git("add", "assets")
        shutil.rmtree(directory)
        directory.symlink_to(outside.parent, target_is_directory=True)
        self.assertNotEqual(self.git("commit", "-qm", "Parent symlink", check=False).returncode, 0)
        self.assertEqual(outside.read_bytes(), original)

    def test_tool_failure_or_remaining_metadata_never_stages_changes(self):
        path = self.image()
        self.add_metadata(path)
        self.git("add", "assets")
        tree, original = self.index_tree(), path.read_bytes()
        binaries = self.repo / "bin"
        binaries.mkdir()
        wrapper = binaries / "exiftool"
        env = dict(self.env, PATH=str(binaries) + os.pathsep + self.env["PATH"])
        for status in (2, 0):
            with self.subTest(write_exit=status):
                wrapper.write_text(
                    '#!/bin/sh\ncase " $* " in\n'
                    f'  *" -overwrite_original "*) exit {status} ;;\n'
                    f'  *) exec {shlex.quote(EXIFTOOL)} "$@" ;;\nesac\n'
                )
                wrapper.chmod(0o755)
                result = self.git("commit", "-qm", "Must not leak", check=False, env=env)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.index_tree(), tree)
                self.assertEqual(path.read_bytes(), original)
                self.assertNotIn(str(abs(TEST_LONGITUDE)).encode(), result.stderr)

    def test_missing_exiftool_blocks_images_but_empty_assets_can_commit(self):
        binaries = self.repo / "bin"
        binaries.mkdir()
        for program in ("git", "python3"):
            (binaries / program).symlink_to(shutil.which(program))
        env = dict(self.env, PATH=str(binaries))
        (self.repo / "article.md").write_text("Article without images\n")
        self.git("add", "article.md")
        self.git("commit", "-qm", "No assets", env=env)
        path = self.image()
        self.git("add", "assets")
        tree, original = self.index_tree(), path.read_bytes()
        result = self.git("commit", "-qm", "Missing tool", check=False, env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"exiftool is required", result.stderr)
        self.assertEqual(self.index_tree(), tree)
        self.assertEqual(path.read_bytes(), original)

    def test_setup_is_repeatable_and_non_image_assets_are_untouched(self):
        self.run_command("make", "setup")
        self.assertEqual(self.git("config", "--local", "--get", "core.hooksPath").stdout, b".githooks\n")
        assets = self.repo / "assets"
        assets.mkdir()
        path = assets / "notes.txt"
        path.write_text("Image credits\n")
        (assets / ".gitkeep").touch()
        self.git("add", "assets")
        self.git("commit", "-qm", "Text asset")
        self.assertEqual(path.read_text(), "Image credits\n")


if __name__ == "__main__":
    unittest.main()
