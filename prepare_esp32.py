"""Build an isolated AC/check-in integration; never edit the old AC project."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import hashlib

ROOT=Path(__file__).resolve().parent
OLD=Path(os.environ.get('GOODNIGHT_AC_PROJECT',r'C:\Espressif\frameworks\esp-idf-v5.1.2\examples\control'))
IDF=Path(os.environ.get('IDF_PATH',str(OLD.parents[1])))


def prepare():
    target=ROOT/'private-data/esp32-ac'
    (target/'main').mkdir(parents=True,exist_ok=True)
    for source in (OLD/'main').iterdir():
        if source.is_file():shutil.copyfile(source,target/'main'/source.name)
    path=target/'main/main.c';source=path.read_text('utf-8')
    for marker in ['#include \"ir_control.h\"','    wifi_init_sta();','static void mqtt_app_start(void)\n{']:
        if source.count(marker)!=1:raise RuntimeError('AC source layout changed; review injection before building')
    source=source.replace('#include "ir_control.h"','#include "ir_control.h"\n#include "checkin_service.h"',1)
    source=source.replace('    wifi_init_sta();','    wifi_init_sta();\n    checkin_service_start();',1)
    # Existing code starts a new MQTT client after every Wi-Fi reconnect. Keep
    # its original client alive instead of creating duplicate control sessions.
    source=source.replace('static void mqtt_app_start(void)\n{','static void mqtt_app_start(void)\n{\n    if (s_mqtt_client != NULL) return;',1)
    path.write_text(source,encoding='utf-8')
    path=target/'main/CMakeLists.txt'
    cmake=path.read_text('utf-8')
    if cmake.count('REQUIRES ')!=1:raise RuntimeError('AC CMake requires manual integration review')
    path.write_text(cmake.replace('REQUIRES ','REQUIRES checkin_runtime ',1),encoding='utf-8')
    config=(OLD/'sdkconfig').read_text('utf-8')
    overrides={'CONFIG_ESPTOOLPY_FLASHSIZE_2MB':False,'CONFIG_ESPTOOLPY_FLASHSIZE_4MB':True,
               'CONFIG_ESPTOOLPY_FLASHSIZE':'"4MB"','CONFIG_PARTITION_TABLE_SINGLE_APP':False,
               'CONFIG_PARTITION_TABLE_SINGLE_APP_LARGE':False,'CONFIG_PARTITION_TABLE_CUSTOM':True,
               'CONFIG_PARTITION_TABLE_CUSTOM_FILENAME':'"partitions.csv"',
               'CONFIG_PARTITION_TABLE_FILENAME':'"partitions.csv"','CONFIG_COMPILER_CXX_EXCEPTIONS':True,
               'CONFIG_MBEDTLS_HARDWARE_AES':False}
    lines=[]
    for line in config.splitlines():
        key=line.split('=',1)[0] if '=' in line else line.removeprefix('# ').removesuffix(' is not set')
        if key in overrides:continue
        lines.append(line)
    for k,v in overrides.items():lines.append(f'{k}=y' if v is True else f'# {k} is not set' if v is False else f'{k}={v}')
    (target/'sdkconfig').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print('Prepared isolated AC source and private sdkconfig; old project unchanged.')
    return target


def build(target):
    python=Path(os.environ.get('GOODNIGHT_IDF_PYTHON',r'C:\Espressif\python_env\idf5.1_py3.11_env\Scripts\python.exe'))
    env={**os.environ,'IDF_PATH':str(IDF),'IDF_TOOLS_PATH':r'C:\Espressif',
         'IDF_PYTHON_ENV_PATH':str(python.parent.parent),'PYTHONUTF8':'1'}
    env['PATH']=str(python.parent)+os.pathsep+env['PATH']
    git=Path(r'C:\Program Files\Git\cmd')
    if git.exists():env['PATH']=str(git)+os.pathsep+env['PATH']
    exported=subprocess.check_output([str(python),str(IDF/'tools/idf_tools.py'),'export','--format','key-value'],env=env,text=True)
    for line in exported.splitlines():
        if '=' in line:
            k,v=line.split('=',1);env[k]=v.replace('${PATH}',env['PATH']).replace('$PATH',env['PATH']).replace('%PATH%',env['PATH'])
    # IDF 5.1's bundled Ninja cannot handle non-ASCII source/build paths.
    stage=Path(tempfile.gettempdir())/('goodnight-esp32-'+hashlib.sha256(str(ROOT).encode()).hexdigest()[:10])
    marker=stage/'.source_root'
    if stage.exists() and not marker.exists() and any(stage.iterdir()):raise RuntimeError('Staging directory is not owned by this project')
    stage.mkdir(parents=True,exist_ok=True)
    if marker.exists() and marker.read_text('utf-8')!=str(ROOT):raise RuntimeError('Unexpected staging owner')
    marker.write_text(str(ROOT),encoding='utf-8')
    shutil.copytree(target/'main',stage/'ac/main',dirs_exist_ok=True)
    shutil.copytree(ROOT/'esp32/components',stage/'components',dirs_exist_ok=True)
    shutil.copyfile(target/'sdkconfig',stage/'sdkconfig')
    shutil.copyfile(ROOT/'esp32/partitions.csv',stage/'partitions.csv')
    (stage/'CMakeLists.txt').write_text('''cmake_minimum_required(VERSION 3.16)
set(EXTRA_COMPONENT_DIRS "${CMAKE_CURRENT_LIST_DIR}/ac/main" "${CMAKE_CURRENT_LIST_DIR}/components/checkin_runtime")
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(ac_checkin)
''',encoding='utf-8')
    status=subprocess.call([str(python),str(IDF/'tools/idf.py'),'-C',str(stage),
                            '-B',str(stage/'build'),'-D','SDKCONFIG='+str(stage/'sdkconfig'),'build'],env=env)
    if status==0:
        destination=ROOT/'private-data/esp32-artifacts'
        destination.mkdir(exist_ok=True)
        for name in ['ac_checkin.bin','ac_checkin.elf','bootloader/bootloader.bin','partition_table/partition-table.bin','flasher_args.json']:
            out=destination/name;out.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(stage/'build'/name,out)
        print('Combined firmware copied to private-data/esp32-artifacts; not flashed.')
    return status


if __name__=='__main__':
    target=prepare()
    if '--build' in sys.argv:raise SystemExit(build(target))
