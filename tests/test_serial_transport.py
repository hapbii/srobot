import sys
import unittest
import threading
from pathlib import Path
from unittest.mock import Mock
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from serial_transport import ArduinoSerialManager


class SerialResourceTests(unittest.TestCase):
    def test_shutdown_cancels_and_joins_read_before_closing_fd(self):
        entered, released = threading.Event(), threading.Event()
        class BlockingSerial:
            is_open = True
            out_waiting = 0
            reading = False
            closed_during_read = False
            def read(self, size):
                self.reading = True
                entered.set()
                released.wait(2)
                self.reading = False
                return b''
            def write(self, payload): return len(payload)
            def cancel_read(self): released.set()
            def close(self):
                self.closed_during_read |= self.reading
                self.is_open = False
        port = BlockingSerial()
        transport = ArduinoSerialManager()
        transport._serials['j1'] = port
        reader = threading.Thread(target=transport._read, args=('j1', port))
        transport._threads['j1'] = reader
        reader.start()
        self.assertTrue(entered.wait(1))
        transport.close()
        self.assertFalse(reader.is_alive())
        self.assertFalse(port.closed_during_read)
        self.assertFalse(port.is_open)

    def test_discovery_does_not_reopen_an_active_port(self):
        transport = ArduinoSerialManager()
        existing = Mock(is_open=True, port='COM3')
        transport._serials['j1'] = existing
        with patch('serial_transport.serial.tools.list_ports.comports', return_value=[Mock(device='COM3')]), \
             patch('serial_transport.serial.Serial') as opened:
            transport.connect_all()
            opened.assert_not_called()

    def test_shutdown_prevents_rediscovery(self):
        transport = ArduinoSerialManager()
        transport.close()
        transport.start_reconnect()
        self.assertIsNone(transport._reconnector)

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
