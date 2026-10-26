"""Compile/run actual management helpers against fake OS/storage/network backends."""
import os
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ManagementHostTests(unittest.TestCase):
    def test_native_management_and_single_refresh_invariants(self):
        compiler = shutil.which('g++')
        idf = Path(os.environ.get('IDF_PATH', ''))
        candidates = list(idf.glob('components/json/cJSON/cJSON.c')) if str(idf) != '.' else []
        if not compiler or not candidates:
            self.skipTest('Requires host g++ and IDF_PATH with ESP-IDF cJSON source')
        work = ROOT / 'private-data/host-management-test'
        work.mkdir(parents=True, exist_ok=True)
        service = ROOT / 'esp32/components/checkin_runtime'
        source = (service / 'checkin_service.cpp').read_text('utf-8')
        start = source.index('std::string get_buffer_refresh(')
        end = source.index('std::string bootstrap_session(', start)
        (work / 'get_buffer_refresh.inc').write_text(source[start:end], encoding='utf-8')
        program = work / ('management-test.exe' if os.name == 'nt' else 'management-test')
        subprocess.run([compiler, '-std=c++17', '-O0', str(ROOT / 'tests/esp32_management_host.cpp'),
                        str(candidates[0]), '-I' + str(candidates[0].parent), '-I' + str(service),
                        '-I' + str(service / 'include'), '-I' + str(work), '-o', str(program),
                        '-static-libgcc', '-static-libstdc++'], check=True, timeout=90)
        result = subprocess.run([str(program)], check=True, timeout=15, capture_output=True, text=True)
        self.assertIn('PASS: host management invariants', result.stdout)


if __name__ == '__main__':
    unittest.main()
