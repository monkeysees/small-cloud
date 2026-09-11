"""Source-only HTTPS fixture launcher; excluded from wheels and frozen releases."""
import os

from identity.cli import main

if __name__ == '__main__':
    raise SystemExit(main(service_origin=os.environ['SMALL_CLOUD_TEST_ORIGIN'],
                          update_executable=os.environ.get('SMALL_CLOUD_TEST_EXECUTABLE')))
