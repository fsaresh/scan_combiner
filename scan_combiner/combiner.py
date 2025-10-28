#!/usr/bin/env python

import argparse
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional
from dotenv import load_dotenv
from PIL import Image
from PyPDF2 import PdfMerger
import pikepdf


class CombinerError(Exception):
    """Base exception for combiner-related errors."""
    pass


class FileProcessingError(CombinerError):
    """Raised when file processing fails."""
    pass


@dataclass
class CombinerConfig:
    """Configuration for combiner operations."""
    scan_directory: str
    output_filename: Optional[str] = None
    compression_threshold_mb: int = 6
    thumbnail_size: int = 1600


def natural_sort_key(file_name: str) -> List:
    """
    Generate a sort key that treats 'Scan.jpg' and 'Scan.jpeg' as first, followed by numbered files sorted naturally.
    """
    if file_name.lower().startswith("scan."):
        return ["0"]  # Assign '0' to Scan.jpg and Scan.jpeg to make them appear first
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', file_name)]


def get_sorted_files(input_directory: Path) -> List[Path]:
    """
    Get all files matching 'Scan*.jpg', 'Scan*.jpeg', or 'Scan*.pdf' in the directory, sorted naturally.
    """
    valid_extensions = {".jpg", ".jpeg", ".pdf"}
    files = [
        f for f in input_directory.iterdir()
        if f.name.lower().startswith("scan") and f.suffix.lower() in valid_extensions
    ]
    return sorted(files, key=lambda f: natural_sort_key(f.name))


def process_images(image_files: List[Path], thumbnail_size: int = 1600) -> List[Image.Image]:
    """
    Convert image files to RGB format and return them as a list of PIL Image objects.
    """
    images = []
    for file in image_files:
        try:
            img = Image.open(file).convert("RGB")
            img.thumbnail((thumbnail_size, thumbnail_size))  # Resize to fit within specified size
            images.append(img)
        except Exception as e:
            print(f"Warning: Could not process image {file.name}: {e}")
    return images


def combine_images_to_pdf(images: List[Image.Image], temp_pdf_path: Path) -> None:
    """
    Combine a list of images into a single PDF.
    """
    if images:
        images[0].save(temp_pdf_path, save_all=True, append_images=images[1:])


def append_pdfs(pdf_merger: PdfMerger, pdf_files: List[Path]) -> None:
    """
    Append PDF files to the PdfMerger object.
    """
    for file in pdf_files:
        try:
            pdf_merger.append(str(file))
        except Exception as e:
            print(f"Warning: Could not process PDF {file.name}: {e}")


def compress_pdf(input_pdf: Path, output_pdf: Path) -> None:
    """
    Compress the PDF using pikepdf compression.
    """
    try:
        # Open the PDF using pikepdf
        with pikepdf.open(input_pdf) as pdf:
            # Compress and save it
            pdf.save(output_pdf, compress_streams=True)
            print(f"Compressed PDF saved to '{output_pdf}'.")
    except Exception as e:
        print(f"Error: Could not compress the PDF: {e}")


def write_final_pdf(pdf_merger: PdfMerger, output_file: Path) -> None:
    """
    Write the final combined PDF from the PdfMerger object to the output file.
    """
    try:
        pdf_merger.write(str(output_file))
        print(f"Success: Combined PDF saved to '{output_file}'.")
    except Exception as e:
        print(f"Error: Could not write combined PDF: {e}")
        raise


def check_pdf_size_and_compress(output_file: Path, input_directory: Path, compression_threshold_mb: int = 6) -> None:
    """
    Check the size of the generated PDF and compress it if necessary.
    """
    threshold_bytes = compression_threshold_mb * 1024 * 1024
    if output_file.exists() and output_file.stat().st_size > threshold_bytes:
        print(f"PDF is larger than {compression_threshold_mb}MB, compressing it...")
        compressed_pdf_path = input_directory / "outputs" / f"compressed_{output_file.name}"
        compress_pdf(output_file, compressed_pdf_path)

        # Replace the original PDF with the compressed one if compression is successful
        if compressed_pdf_path.exists():
            output_file.unlink()  # Delete the original, uncompressed file
            compressed_pdf_path.rename(output_file)
    else:
        print(f"PDF size is under {compression_threshold_mb}MB, no compression needed.")


def cleanup_temp_files(temp_pdf_path: Path) -> None:
    """
    Clean up temporary files.
    """
    if temp_pdf_path.exists():
        temp_pdf_path.unlink()
        print(f"Temporary file '{temp_pdf_path}' cleaned up.")


def combine_files(input_directory: Path, output_file: Path, config: Optional[CombinerConfig] = None) -> None:
    """
    Main function to combine images and PDFs into a single PDF.
    """
    # Use default config if none provided
    if config is None:
        config = CombinerConfig(scan_directory=str(input_directory))

    # Get sorted files
    files = get_sorted_files(input_directory)
    if not files:
        print("Error: No matching files found.")
        return

    # Separate image and PDF files
    image_extensions = {".jpg", ".jpeg"}
    image_files = [f for f in files if f.suffix.lower() in image_extensions]
    pdf_files = [f for f in files if f.suffix.lower() == ".pdf"]

    # Process images
    images = process_images(image_files, config.thumbnail_size)

    # Create temporary PDF from images
    pdf_merger = PdfMerger()
    temp_pdf_path = input_directory / "temp_images.pdf"

    # Process combined files
    try:
        if images:
            combine_images_to_pdf(images, temp_pdf_path)
            pdf_merger.append(str(temp_pdf_path))

        # Append existing PDFs
        append_pdfs(pdf_merger, pdf_files)

        # Write the final combined PDF
        write_final_pdf(pdf_merger, output_file)

    finally:
        # Clean up temporary PDF file
        pdf_merger.close()
        cleanup_temp_files(temp_pdf_path)

    # Check PDF size and compress if necessary
    check_pdf_size_and_compress(output_file, input_directory, config.compression_threshold_mb)


def parse_arguments() -> CombinerConfig:
    """
    Parse command line arguments and return configuration.
    Environment variables are used as defaults, with command line taking priority.
    """
    # Get defaults from environment variables
    env_scan_directory = os.getenv('SCAN_DIRECTORY')
    env_output_filename = os.getenv('OUTPUT_FILENAME')
    env_compression_threshold_mb = int(os.getenv('COMPRESSION_THRESHOLD_MB', '6'))
    env_thumbnail_size = int(os.getenv('THUMBNAIL_SIZE', '1600'))

    parser = argparse.ArgumentParser(
        description='Combine scanned images and PDFs into a single PDF file'
    )

    parser.add_argument(
        'scan_directory', nargs='?', default=env_scan_directory,
        help='Directory containing scan files to combine'
    )
    parser.add_argument(
        '--output', '-o', default=env_output_filename,
        help='Output PDF filename (default: derived from scan directory name)'
    )
    parser.add_argument(
        '--compression-threshold-mb', '-c', type=int, default=env_compression_threshold_mb,
        help='File size threshold in MB for compression (default: 6)'
    )
    parser.add_argument(
        '--thumbnail-size', '-t', type=int, default=env_thumbnail_size,
        help='Maximum thumbnail size for images (default: 1600)'
    )

    args = parser.parse_args()

    if not args.scan_directory:
        parser.error('SCAN_DIRECTORY must be provided either as argument or environment variable')

    return CombinerConfig(
        scan_directory=args.scan_directory,
        output_filename=args.output,
        compression_threshold_mb=args.compression_threshold_mb,
        thumbnail_size=args.thumbnail_size
    )


def process_config(config: CombinerConfig) -> tuple[Path, Path]:
    """
    Process configuration and return validated paths.
    """
    scan_directory = Path(config.scan_directory)

    if not scan_directory.is_dir():
        raise FileNotFoundError(f"Directory '{scan_directory}' does not exist")

    # Ensure the outputs directory exists
    output_dir = scan_directory.parent / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Determine output filename
    if config.output_filename:
        output_file = Path(config.output_filename)
        if not output_file.is_absolute():
            output_file = output_dir / output_file
    else:
        output_file = output_dir / f"{scan_directory.name}.pdf"

    return scan_directory, output_file


def main() -> None:
    """
    Entry point of the script.
    """
    try:
        load_dotenv()
        config = parse_arguments()

        # Process configuration
        scan_directory, output_file = process_config(config)

        # Run the combining process
        combine_files(scan_directory, output_file, config)

    except KeyboardInterrupt:
        print("Combine operation interrupted by user", file=sys.stderr)
    except FileNotFoundError as e:
        print(f"Directory Error: {e}", file=sys.stderr)
        print("Make sure the scan directory exists and is accessible", file=sys.stderr)
    except Exception as e:
        print(f"Unexpected Error: {e}", file=sys.stderr)
        print("This may be a file permission issue or corrupted scan files", file=sys.stderr)


if __name__ == "__main__":
    main()
