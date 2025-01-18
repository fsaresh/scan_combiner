import os
import re
import sys
from pathlib import Path
from typing import List
from dotenv import load_dotenv
from PIL import Image
from PyPDF2 import PdfMerger


def natural_sort_key(file_name: str) -> List:
    """
    Generate a sort key that treats 'Scan.jpg' and 'Scan.jpeg' as first, followed by numbered files sorted naturally.
    """
    if file_name.lower() in ["scan.jpg", "scan.jpeg"]:
        return [-1]  # Give 'Scan.jpg' and 'Scan.jpeg' highest priority
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

    # Write final PDF
    try:
        pdf_merger.write(str(output_file))
        print(f"Success: Combined PDF saved to '{output_file}'.")
    except Exception as e:
        print(f"Error: Could not write combined PDF: {e}")
    finally:
        pdf_merger.close()

    # Clean up temporary files
    if temp_pdf_path.exists():
        temp_pdf_path.unlink()


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

    # Set default for output_file if not provided
    if not output_file:
        terminal_directory = input_directory.name
        output_file = input_directory / f"{terminal_directory}.pdf"
    else:
        output_file = Path(output_file)

    combine_files(input_directory, output_file)


if __name__ == "__main__":
    main()
