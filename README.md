# scan-combiner

Two small command-line tools for working with a network scanner:

- `scanner.py` — discovers an eSCL/Mopria-compatible scanner over mDNS and pulls pages off it as JPEG or PDF.
- `combiner.py` — gathers the `Scan*.jpg`, `Scan*.jpeg`, and `Scan*.pdf` files from a directory and merges them, in natural sort order, into a single PDF. Compresses the result with `pikepdf` when it exceeds a size threshold.

The two are designed to be used together: scan a stack of pages into a directory, then combine them into one PDF named after that directory.

## Requirements

- Python 3.12+
- [Poetry](https://python-poetry.org/) for dependency management
- A network scanner that advertises the `_uscan._tcp` mDNS service (eSCL). This is what most modern HP, Brother, Canon, and Epson network scanners speak.

## Getting started

```
git clone <this-repo>
cd scan_combiner
poetry install
```

Create a `.env` file at `scan_combiner/.env` with at least a destination directory:

```
SCAN_DIRECTORY=/path/to/scans/tmp
```

All other settings have sensible defaults; see [Configuration](#configuration).

## Usage

Both scripts can be run with `poetry run python <path>`. Command-line flags take precedence over environment variables.

### Scanning

```
poetry run python scan_combiner/scanner.py [filename] [options]
```

Scan a single letter-sized page to a JPEG using the default settings from `.env`:

```
poetry run python scan_combiner/scanner.py
```

Scan to a PDF named `Scan.pdf`, region set to letter:

```
poetry run python scan_combiner/scanner.py --format pdf --region letter Scan.pdf
```

Scan a custom region (`Xoffset:Yoffset:Width:Height`, units understood by the [`papersize`](https://papersize.readthedocs.io) library):

```
poetry run python scan_combiner/scanner.py --region 1cm:1.5cm:10cm:20cm
```

Duplex scan from the document feeder at 600 dpi:

```
poetry run python scan_combiner/scanner.py --source feeder --duplex --resolution 600
```

If the target filename already exists, the script auto-increments (`Scan.jpeg`, `Scan 1.jpeg`, `Scan 2.jpeg`, …). The output is written under `SCAN_DIRECTORY` if that variable is set.

#### Scanner options

| Flag | Env var | Default | Notes |
| --- | --- | --- | --- |
| `--source` / `-S` | `SCAN_SOURCE` | `automatic` | `feeder`, `flatbed`, or `automatic` |
| `--format` / `-f` | `SCAN_FORMAT` | `pdf` | `pdf` or `jpeg` |
| `--resolution` / `-r` | `SCAN_RESOLUTION` | `300` | One of `75`, `100`, `200`, `300`, `600` |
| `--duplex` / `-D` | `SCAN_DUPLEX` | `false` | Requires duplex-capable hardware |
| `--region` / `-R` | `SCAN_REGION` | `letter` | Paper size name or `X:Y:W:H` |
| `filename` (positional) | `SCAN_FILENAME` | `Scan.jpeg` | Combined with `SCAN_DIRECTORY` |

### Combining

```
poetry run python scan_combiner/combiner.py [scan_directory] [options]
```

Combine the files in `SCAN_DIRECTORY` (from `.env`) into a single PDF named after the directory:

```
poetry run python scan_combiner/combiner.py
```

Combine a specific directory and lower the compression threshold to 4 MB:

```
poetry run python scan_combiner/combiner.py /path/to/scans/2026_04_26-receipts -c 4
```

The output PDF is written into the scan directory itself as `<directory_name>.pdf`. If the result is larger than the compression threshold, it is rewritten in place using `pikepdf` stream compression.

#### Combiner options

| Flag | Env var | Default | Notes |
| --- | --- | --- | --- |
| `scan_directory` (positional) | `SCAN_DIRECTORY` | — | Required, via flag or env |
| `--compression-threshold-mb` / `-c` | `COMPRESSION_THRESHOLD_MB` | `6` | Skip compression below this size |
| `--thumbnail-size` / `-t` | `THUMBNAIL_SIZE` | `1600` | Max edge length for embedded images |

### Typical workflow

```
# 1. Scan multiple pages into the configured directory.
poetry run python scan_combiner/scanner.py
poetry run python scan_combiner/scanner.py
poetry run python scan_combiner/scanner.py

# 2. Merge them into a single PDF named after the directory.
poetry run python scan_combiner/combiner.py
```

`combiner.py` orders files naturally, with bare `Scan.jpg`/`Scan.jpeg` files sorted ahead of numbered ones (`Scan 1.jpeg`, `Scan 2.jpeg`, …).

## Configuration

All settings can be supplied via `.env` or via command-line flags. The full list of supported variables:

```
# Combiner
SCAN_DIRECTORY=/path/to/scans/tmp
COMPRESSION_THRESHOLD_MB=6
THUMBNAIL_SIZE=1600

# Scanner
SCAN_SOURCE=automatic   # automatic | feeder | flatbed
SCAN_FORMAT=pdf         # pdf | jpeg
SCAN_RESOLUTION=300     # 75 | 100 | 200 | 300 | 600
SCAN_DUPLEX=false
SCAN_REGION=letter
SCAN_FILENAME=Scan.jpeg
```

`SCAN_DIRECTORY` is shared between the two scripts: the scanner writes into it, the combiner reads from it.
