#!/usr/bin/env python

import argparse
import decimal
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

import papersize
import requests
import xmltodict
import zeroconf
from dotenv import load_dotenv
from urllib3.exceptions import InsecureRequestWarning

# Spec available at https://mopria.org/spec-download
# Based loosely off of https://github.com/PJK/escl-scanner-cli using the Apache license


class ScannerError(Exception):
    """Base exception for scanner-related errors."""
    pass


class ScannerNotFoundError(ScannerError):
    """Raised when no scanner is found."""
    pass


class ScannerBusyError(ScannerError):
    """Raised when scanner is not idle."""
    pass


class ScanJobError(ScannerError):
    """Raised when scan job fails."""
    pass


@dataclass
class ScannerConfig:
    """Configuration for scanner operations."""
    source: str = 'automatic'
    format: str = 'pdf'
    color_mode = 'RGB24'  # Grayscale8 for grayscale
    resolution: int = 200
    duplex: bool = False
    region: Optional[str] = None
    filename: str = 'Scan.jpeg'

    def get_document_format(self) -> str:
        """Get the document format MIME type."""
        return 'application/pdf' if self.format == 'pdf' else 'image/jpeg'

    def get_input_source_xml(self) -> str:
        """Get the input source XML fragment."""
        source_map = {
            'automatic': '',
            'feeder': '<pwg:InputSource>Feeder</pwg:InputSource>',
            'flatbed': '<pwg:InputSource>Platen</pwg:InputSource>',
        }
        return source_map[self.source]


@dataclass
class ScanRegion:
    """Scan region specification."""
    x: int
    y: int
    width: int
    height: int

    def to_xml(self) -> str:
        """Convert to XML format."""
        return f'''
  <pwg:ScanRegions>
    <pwg:ScanRegion>
      <pwg:ContentRegionUnits>escl:ThreeHundredthsOfInches</pwg:ContentRegionUnits>
      <pwg:XOffset>{self.x}</pwg:XOffset>
      <pwg:YOffset>{self.y}</pwg:YOffset>
      <pwg:Width>{self.width}</pwg:Width>
      <pwg:Height>{self.height}</pwg:Height>
    </pwg:ScanRegion>
  </pwg:ScanRegions>'''


class ScannerClient:
    """Client for communicating with eSCL scanners."""

    def __init__(self, config: ScannerConfig):
        self.config = config
        self.session = self._setup_session()
        self.scanner_info: Optional[zeroconf.ServiceInfo] = None
        self.base_url: str = ""

    def _setup_session(self) -> requests.Session:
        """Create and configure a requests session."""
        session = requests.Session()
        session.verify = False
        requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
        return session

    def discover_scanner(self) -> None:
        """Discover and connect to a scanner."""
        class ZCListener:
            def __init__(self):
                self.info: Optional[zeroconf.ServiceInfo] = None

            def update_service(self, zeroconf_: zeroconf.Zeroconf, type_: str, name: str) -> None:
                pass

            def remove_service(self, zeroconf_: zeroconf.Zeroconf, type_: str, name: str) -> None:
                pass

            def add_service(self, zeroconf_: zeroconf.Zeroconf, type_: str, name: str) -> None:
                self.info = zeroconf_.get_service_info(type_, name)

        with zeroconf.Zeroconf() as zc:
            listener = ZCListener()
            zeroconf.ServiceBrowser(zc, "_uscan._tcp.local.", listener=listener)
            for _ in range(100):  # 10 seconds timeout
                if listener.info:
                    break
                time.sleep(0.1)

        if not listener.info:
            raise ScannerNotFoundError("No scanner found")

        self.scanner_info = listener.info
        self._setup_base_url()

        name = self._get_display_name()
        print(f'Using {name}')

    def _setup_base_url(self) -> None:
        """Setup the base URL for scanner communication."""
        if not self.scanner_info:
            raise ScannerError("No scanner info available")

        props = self.scanner_info.properties
        rs = props[b'rs'].decode()
        if not rs.startswith('/'):
            rs = '/' + rs

        server = self.scanner_info.server.rstrip('.')
        self.base_url = f'http://{server}:{self.scanner_info.port}{rs}'

    def _get_display_name(self) -> str:
        """Get a clean display name for the scanner."""
        if not self.scanner_info:
            return "Unknown Scanner"

        suffix = '._uscan._tcp.local.'
        name = self.scanner_info.name
        if name.endswith(suffix):
            name = name[:-len(suffix)]
        return name

    def check_capabilities_and_status(self) -> None:
        """Check scanner capabilities and ensure it's ready."""
        # Check capabilities
        resp = self.session.get(f'{self.base_url}/ScannerCapabilities')
        resp.raise_for_status()

        # Check status
        status, _ = self._get_status()
        if status['pwg:State'] != 'Idle':
            raise ScannerBusyError("Scanner is not idle")

        # Check duplex support
        if self.config.duplex:
            if not self.scanner_info:
                raise ScannerError("No scanner info available")
            props = self.scanner_info.properties
            if props[b'duplex'] != b'T':
                raise ScannerError("Duplex not supported")

    def _get_status(self, job_uuid: Optional[str] = None) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
        """Get scanner status and optionally job info."""
        resp = self.session.get(f'{self.base_url}/ScannerStatus')
        resp.raise_for_status()

        status = xmltodict.parse(
            resp.text, force_list=('scan:JobInfo',))['scan:ScannerStatus']

        if job_uuid is None:
            return status, None

        uuid_prefix = "urn:uuid:"
        for jobinfo in status['scan:Jobs']['scan:JobInfo']:
            current_uuid = jobinfo['pwg:JobUuid']
            if current_uuid.startswith(uuid_prefix):
                current_uuid = current_uuid[len(uuid_prefix):]

            if current_uuid == job_uuid:
                return status, jobinfo

        raise ScanJobError(f'Job {job_uuid} not found')

    def create_scan_job(self, region: Optional[ScanRegion] = None) -> str:
        """Create a scan job and return the job URI."""
        job_xml = self._create_job_xml(region)

        resp = self.session.post(
            f'{self.base_url}/ScanJobs',
            data=job_xml,
            headers={'Content-Type': 'application/xml'}
        )
        resp.raise_for_status()

        return resp.headers['location']

    def _create_job_xml(self, region: Optional[ScanRegion] = None) -> str:
        """Create the XML for the scan job request."""
        job = f'''<?xml version="1.0" encoding="UTF-8"?>
<scan:ScanSettings xmlns:scan="http://schemas.hp.com/imaging/escl/2011/05/03" xmlns:pwg="http://www.pwg.org/schemas/2010/12/sm">
  <pwg:Version>2.0</pwg:Version>
  <scan:Intent>TextAndGraphic</scan:Intent>
  <pwg:DocumentFormat>{self.config.get_document_format()}</pwg:DocumentFormat>
  {self.config.get_input_source_xml()}
  <scan:ColorMode>{self.config.color_mode}</scan:ColorMode>
  <scan:Duplex>{str(self.config.duplex).lower()}</scan:Duplex>
  <scan:XResolution>{self.config.resolution}</scan:XResolution>
  <scan:YResolution>{self.config.resolution}</scan:YResolution>'''

        if region:
            job += region.to_xml()

        job += '''
</scan:ScanSettings>'''
        return job

    def get_job_status(self, job_uuid: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """Get the status of a specific job."""
        return self._get_status(job_uuid)

    def get_next_document(self, job_uri: str) -> Optional[bytes]:
        """Get the next document from a scan job."""
        resp = self.session.get(f'{job_uri}/NextDocument')
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.content


class ScanJob:
    """Handles scan job processing and file saving."""

    def __init__(self, config: ScannerConfig, client: ScannerClient, filename: Path):
        self.config = config
        self.client = client
        self.filename = filename
        self.job_uri: str = ""
        self.job_uuid: str = ""

    def execute(self, region: Optional[ScanRegion] = None) -> None:
        """Execute the scan job."""
        # Create the scan job
        self.job_uri = self.client.create_scan_job(region)
        self.job_uuid = self.job_uri.split('/')[-1]

        # Process scan results
        page = 1
        while True:
            status, jobinfo = self.client.get_job_status(self.job_uuid)

            # Get next document
            document_data = self.client.get_next_document(self.job_uri)
            if document_data is None:
                break

            # Save the document
            self._save_document(document_data, page)
            page += 1

            if status['pwg:State'] != 'Processing':
                break
            time.sleep(1)

        # Check final job status
        self._check_final_status()

    def _save_document(self, data: bytes, page: int) -> None:
        """Save document data to file."""
        if self.config.format == 'pdf':
            with open(self.filename, 'wb') as f:
                f.write(data)
        else:
            basename = self.filename.stem
            suffix = self.filename.suffix
            page_filename = self.filename.parent / f"{basename}-{page}{suffix}"
            with open(page_filename, 'wb') as f:
                f.write(data)

    def _check_final_status(self) -> None:
        """Check the final status of the scan job."""
        status, jobinfo = self.client.get_job_status(self.job_uuid)

        # Extract job completion reason
        job_reason = self._extract_job_reason(jobinfo)

        # Check if job completed successfully
        if job_reason != 'JobCompletedSuccessfully':
            job_state = jobinfo.get('pwg:JobState', 'Unknown')
            if job_state not in ['Completed', 'Aborted'] and job_reason:
                raise ScanJobError(f"Scan job failed: {job_reason or job_state}")

    def _extract_job_reason(self, jobinfo: Dict[str, Any]) -> Optional[str]:
        """Extract the job completion reason from job info."""
        if 'pwg:JobStateReasons' not in jobinfo or not jobinfo['pwg:JobStateReasons']:
            return None

        reason = jobinfo['pwg:JobStateReasons']['pwg:JobStateReason']
        if isinstance(reason, list):
            return reason[0]
        return reason


def parse_region(region: str) -> ScanRegion:
    """
    Parse a region specification into scanner coordinates.
    """
    region_str = region.lower()
    try:
        if region_str in papersize.SIZES:
            paper_size = papersize.parse_papersize(region_str)
            region_dict = {
                'x': decimal.Decimal('0'),
                'y': decimal.Decimal('0'),
                'width': paper_size[0],
                'height': paper_size[1],
            }
        else:
            parts = region_str.split(':')
            if len(parts) != 4:
                raise papersize.CouldNotParse(region_str)
            parts = [papersize.parse_length(p) for p in parts]
            region_dict = {
                'x': parts[0],
                'y': parts[1],
                'width': parts[2],
                'height': parts[3],
            }
    except papersize.CouldNotParse as e:
        raise ScannerError(f'Could not parse region {region}') from e

    c = papersize.UNITS['in'] / 300  # ThreeHundredthsOfInches
    coords = {k: int(v / c) for k, v in region_dict.items()}
    return ScanRegion(**coords)


def parse_arguments() -> ScannerConfig:
    """
    Parse command line arguments and return configuration.
    Environment variables are used as defaults, with command line taking priority.
    """
    # Get defaults from environment variables
    env_source = os.getenv('SCAN_SOURCE', 'automatic')
    env_format = os.getenv('SCAN_FORMAT', 'pdf')
    env_resolution = int(os.getenv('SCAN_RESOLUTION', '300'))
    env_duplex = os.getenv('SCAN_DUPLEX', 'false').lower() in ('true', '1', 'yes')
    env_region = os.getenv('SCAN_REGION', "letter")
    env_filename = os.getenv('SCAN_FILENAME', 'Scan.jpeg')

    parser = argparse.ArgumentParser()

    parser.add_argument(
        '--source', '-S',
        choices=['feeder', 'flatbed', 'automatic'], default=env_source)
    parser.add_argument(
        '--format', '-f', choices=['pdf', 'jpeg'], default=env_format)
    parser.add_argument(
        '--resolution', '-r', type=int, default=env_resolution,
        choices=[75, 100, 200, 300, 600])
    parser.add_argument('--duplex', '-D', action='store_true', default=env_duplex)
    parser.add_argument(
        '--region', '-R', default=env_region,
        help='Specify a region to scan. Either a paper size as understood by '
            'the papersize library (https://papersize.readthedocs.io) or the format '
            '"Xoffset:Yoffset:Width:Height", with units understood by the '
            'papersize library. For example: 1cm:1.5cm:10cm:20cm')
    parser.add_argument('filename', nargs='?', default=env_filename)

    args = parser.parse_args()

    return ScannerConfig(
        source=args.source,
        format=args.format,
        resolution=args.resolution,
        duplex=args.duplex,
        region=args.region,
        filename=args.filename
    )


def process_filename(config: ScannerConfig) -> Path:
    """
    Process and prepare the filename with directory path and auto-increment.
    """
    filename = config.filename

    # Prepend SCAN_DIRECTORY from .env file if set
    scan_directory = os.getenv('SCAN_DIRECTORY')
    if scan_directory:
        filename = os.path.join(scan_directory, filename)

    # Auto-increment filename if it already exists
    original_path = Path(filename)
    counter = 0
    final_path = original_path

    while final_path.exists():
        counter += 1
        final_path = original_path.parent / f"{original_path.stem} {counter}{original_path.suffix}"

    return final_path


def validate_filename_format(filename: Path, format_type: str) -> None:
    """
    Validate the filename based on the output format.
    """
    suffix = filename.suffix
    if format_type == 'jpeg' and suffix not in {'.jpeg', '.jpg', ''}:
        raise ScannerError(f'Improper file suffix {suffix} for JPEG format')


def main() -> None:
    """
    Entry point of the script.
    """
    try:
        load_dotenv()
        config = parse_arguments()

        # Process filename
        filename = process_filename(config)
        validate_filename_format(filename, config.format)

        # Parse region if provided
        region = None
        if config.region:
            region = parse_region(config.region)

        # Initialize scanner client
        client = ScannerClient(config)
        client.discover_scanner()
        client.check_capabilities_and_status()

        # Execute scan job
        job = ScanJob(config, client, filename)
        job.execute(region)

    except KeyboardInterrupt:
        print("Scan operation interrupted by user", file=sys.stderr)
    except ScannerNotFoundError as e:
        print(f"Scanner Discovery Error: {e}", file=sys.stderr)
        print("Make sure your scanner is powered on and connected to the network", file=sys.stderr)
    except ScannerBusyError as e:
        print(f"Scanner Availability Error: {e}", file=sys.stderr)
        print("Wait for the scanner to finish its current operation and try again", file=sys.stderr)
    except ScanJobError as e:
        print(f"Scan Job Error: {e}", file=sys.stderr)
        print("Check if there is paper in the scanner and that it's properly positioned", file=sys.stderr)
    except ScannerError as e:
        print(f"Scanner Configuration Error: {e}", file=sys.stderr)
        print("Check your scan settings and scanner capabilities", file=sys.stderr)
    except Exception as e:
        print(f"Unexpected Error: {e}", file=sys.stderr)
        print("This may be a network issue or scanner communication problem", file=sys.stderr)


if __name__ == '__main__':
    main()
