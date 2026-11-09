"""Keep each sketch self-contained for Arduino IDE and arduino-cli builds."""
from pathlib import Path

root = Path(__file__).resolve().parents[1]
header = (root / 'firmware/axis_firmware.h').read_bytes()
for axis, speed, accel, low, high in [('J1',2000,3000,-32000,32000),
                                     ('J2',2000,3000,-48000,16000),
                                     ('J3',1000,1500,-16000,16000)]:
    (root / axis / 'axis_firmware.h').write_bytes(header)
    (root / axis / f'{axis}.ino').write_text(
        f'#define AXIS_NAME "{axis}"\n#define DEFAULT_SPEED {speed}\n'
        f'#define DEFAULT_ACCEL {accel}\n#define MIN_TARGET ({low}L)\n'
        f'#define MAX_TARGET ({high}L)\n#include "axis_firmware.h"\n', encoding='utf-8')
