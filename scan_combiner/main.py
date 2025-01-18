import os
import re
import sys
import pikepdf
from pathlib import Path
from typing import List
from dotenv import load_dotenv
from PIL import Image
from PyPDF2 import PdfMerger


def natural_sort_key(file_name: str) -> List:
    """
    Generate a sort key that treats 'Scan.jpg' and 'Scan.jpeg' as first, followed by numbered files sorted naturally.
    """
    # Give 'Scan.jpg' and 'Scan.jpeg' priority to come first in sorting
    if file_name.lower() == "scan.jpg" or file_name.lower() == "scan.jpeg":
        return ["0"]  # Assign '0' to Scan.jpg and Scan.jpeg to make them appear first

    # For other files, extract the numeric parts and sort naturally
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', file_name)]


def get_sorted_files(input_directory: Path) -> List[Path]:
    """
    Get all files matching 'Scan*.jpg', 'Scan*.jpeg', or 'Scan*.pdf' in the directory, sorted naturally.
    """
    files = [
        f for f in input_directory.iterdir()
        if f.name.lower().startswith("scan") and f.suffix.lower() in [".jpg", ".jpeg", ".pdf"]
    ]
    return sorted(files, key=lambda f: natural_sort_key(f.name))


def process_images(files: List[Path]) -> List[Image.Image]:
    """
    Convert image files to RGB format and return them as a list of PIL Image objects.
    """
    images = []
    for file in files:
        try:
            img = Image.open(file).convert("RGB")
            img.thumbnail((1600, 1600))  # Resize to fit within 1600x1600
            images.append(img)
        except Exception as e:
            print(f"Warning: Could not process image {file.name}: {e}")
    return images


def combine_images_to_pdf(images: List[Image.Image], output_path: Path) -> None:
    """
    Combine a list of images into a single PDF.
    """
    if not images:
        return
    images[0].save(output_path, save_all=True, append_images=images[1:])


def append_pdfs(pdf_merger: PdfMerger, files: List[Path]) -> None:
    """
    Append PDF files to the PdfMerger object.
    """
    for file in files:
        try:
            pdf_merger.append(str(file))
        except Exception as e:
            print(f"Warning: Could not process PDF {file.name}: {e}")


def compress_pdf(input_pdf: Path, output_pdf: Path) -> None:
    """
    Compress the PDF if it's too large (over 6MB).
    """
    try:
        # Open the PDF using pikepdf
        with pikepdf.open(input_pdf) as pdf:
            # Compress and save it
            pdf.save(output_pdf, compress_streams=True)
            print(f"Compressed PDF saved to '{output_pdf}'.")
    except Exception as e:
        print(f"Error: Could not compress the PDF: {e}")


def combine_files(input_directory: Path, output_file: Path) -> None:
    """
    Main function to combine images and PDFs into a single PDF.
    """
    # Get sorted files
    files = get_sorted_files(input_directory)
    if not files:
        print("Error: No matching files found.")
        return

    # Separate images and PDFs
    image_files = [f for f in files if f.suffix.lower() in [".jpg", ".jpeg"]]
    pdf_files = [f for f in files if f.suffix.lower() == ".pdf"]

    # Process images
    images = process_images(image_files)

    # Create temporary PDF from images
    pdf_merger = PdfMerger()
    temp_pdf_path = input_directory / "temp_images.pdf"
    if images:
        combine_images_to_pdf(images, temp_pdf_path)
        pdf_merger.append(str(temp_pdf_path))

    # Append existing PDFs
    append_pdfs(pdf_merger, pdf_files)

    # Write the final PDF before checking size
    try:
        pdf_merger.write(str(output_file))
        print(f"Success: Combined PDF saved to '{output_file}'.")
    except Exception as e:
        print(f"Error: Could not write combined PDF: {e}")
    finally:
        pdf_merger.close()

    # Check the size of the generated PDF
    if output_file.exists() and output_file.stat().st_size > 6 * 1024 * 1024:  # 6MB threshold
        print(f"PDF is larger than 6MB, compressing it...")
        # Compress the PDF if it's larger than 6MB
        compressed_pdf_path = input_directory / f"compressed_{output_file.name}"
        compress_pdf(output_file, compressed_pdf_path)

        # Replace the original PDF with the compressed one if compression is successful
        if compressed_pdf_path.exists():
            output_file.unlink()  # Delete the original, uncompressed file
            compressed_pdf_path.rename(output_file)
    else:
        print(f"PDF size is under 6MB, no compression needed.")


def main():
    """
    Entry point of the script.
    """
    load_dotenv()  # Load environment variables from .env file

    input_directory = os.getenv("INPUT_DIRECTORY")
    output_file = os.getenv("OUTPUT_FILENAME")

    if not input_directory:
        print("Error: Missing INPUT_DIRECTORY in the .env file.")
        sys.exit(1)

    input_directory = Path(input_directory)

    if not input_directory.is_dir():
        print(f"Error: Directory '{input_directory}' does not exist.")
        sys.exit(1)

    # If OUTPUT_FILENAME is not provided, derive it from INPUT_DIRECTORY's parent directory
    if not output_file:
        output_file = input_directory.parent / f"{input_directory.name}.pdf"

    output_file = Path(output_file)

    # Run the combining process
    combine_files(input_directory, output_file)


if __name__ == "__main__":
    main()
