# Image fixtures

These original 16×16 test images contain a synthetic RGB gradient and no photographic content.
The PNG was generated with Python's `struct` and `zlib` modules; JPEG, GIF, AVIF, and HEIC were encoded from it with macOS `sips`, and WebP with `cwebp -lossless`.
ExifTool removed metadata from the encoded fixtures.
Tests copy the HEIC fixture to a `.heif` path to exercise that extension and add artificial metadata at runtime.
Runtime GPS metadata uses Point Nemo in the South Pacific (`-48.876667`, `-123.393333`), approximately 2,688 km from the nearest land and outside national territorial seas and exclusive economic zones; see [NOAA's coordinates](https://oceanservice.noaa.gov/facts/nemo.html) and [maritime zone definitions](https://www.noaa.gov/maritime-zones-and-boundaries).
The encoders are only needed to regenerate fixtures; running tests requires Git, Make, Python 3, and ExifTool.

These fixtures use the repository's MIT OR Apache-2.0 license.
