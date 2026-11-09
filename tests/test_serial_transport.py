import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from serial_transport import ArduinoSerialManager


class SerialResourceTests(unittest.TestCase):
    def test_short_write_is_a_failure_and_closes_port(self):
        transport = ArduinoSerialManager()
        serial = Mock()
        serial.is_open = True
        serial.write.return_value = 1
        transport._serials['j1'] = serial
        self.assertFalse(transport.send_goto('j1', 100, 1))
        serial.close.assert_called_once()

    def test_close_is_idempotent_and_joins_readers(self):
        transport = ArduinoSerialManager()
        serial, thread = Mock(), Mock()
        serial.write.side_effect = lambda payload: len(payload)
        transport._serials['j1'] = serial
        transport._threads['j1'] = thread
        transport.close()
        transport.close()
        self.assertFalse(transport._serials)
        self.assertFalse(transport._threads)
        serial.close.assert_called_once()
        thread.join.assert_called_once()


if __name__ == '__main__':
    unittest.main()
