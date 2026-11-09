import threading
import time
import sys
WS_PORT=8080
C_RESET  = '\033[0m'
C_CYAN   = '\033[96m'
C_GREEN  = '\033[92m'
C_YELLOW = '\033[93m'
C_RED    = '\033[91m'
C_PURPLE = '\033[95m'
C_BOLD   = '\033[1m'
C_DIM    = '\033[2m'


# ══════════════════════════════════════════════════════════
# 터미널 대시보드
# ══════════════════════════════════════════════════════════
class TerminalDashboard:
    def __init__(self, local_ip='?.?.?.?'):
        self._local_ip = local_ip
        self._joint = {
            'j1': {'deg': 0.0, 'steps': 0, 'enc_raw': 0, 'enc_deg': 0.0, 'enc_ok': False},
            'j2': {'deg': 0.0, 'steps': 0, 'enc_raw': 0, 'enc_deg': 0.0, 'enc_ok': False},
            'j3' : {'deg': 0.0, 'steps': 0, 'enc_raw': 0, 'enc_deg': 0.0, 'enc_ok': False},
        }
        self._arduino = {
            'j1': {'connected': False, 'port': '—'},
            'j2': {'connected': False, 'port': '—'},
            'j3' : {'connected': False, 'port': '—'},
        }
        self._ws_connected  = False
        self._ws_clients    = 0
        self._controlling   = False   # 웹에서 "제어 시작" 눌린 상태
        self._lock          = threading.Lock()
        self._running       = False
        self._pkt_count     = 0
        self._thread        = None

    def set_controlling(self, active: bool):
        with self._lock:
            self._controlling = active

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._running = True
        sys.stdout.write('\033[?25l')
        sys.stdout.flush()
        self._thread = threading.Thread(target=self._loop, daemon=True, name='scara-dashboard')
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=0.5)
        self._thread = None
        sys.stdout.write('\033[?25h\n')
        sys.stdout.flush()

    def update_joint(self, axis, deg, steps):
        with self._lock:
            if axis in self._joint:
                self._joint[axis]['deg']   = deg
                self._joint[axis]['steps'] = steps
                self._pkt_count += 1

    def update_encoder(self, axis, raw, deg, ok=True):
        with self._lock:
            if axis in self._joint:
                self._joint[axis]['enc_raw'] = raw
                self._joint[axis]['enc_deg'] = deg
                self._joint[axis]['enc_ok']  = ok

    def set_ws(self, clients):
        with self._lock:
            self._ws_clients   = clients
            self._ws_connected = clients > 0

    def set_arduino(self, axis, connected, port='—'):
        with self._lock:
            if axis in self._arduino:
                self._arduino[axis]['connected'] = connected
                self._arduino[axis]['port']      = port

    def _loop(self):
        print('\033[2J\033[H', end='')
        pkt_buf, last_t = 0, time.time()
        while self._running:
            now = time.time()
            with self._lock:
                pkt_buf += self._pkt_count
                self._pkt_count = 0
            if now - last_t >= 1.0:
                hz = pkt_buf / (now - last_t)
                pkt_buf, last_t = 0, now
            else:
                hz = pkt_buf
            self._render(hz)
            time.sleep(0.05)

    def _render(self, hz=0):
        with self._lock:
            joint        = {k: dict(v) for k, v in self._joint.items()}
            arduino      = {k: dict(v) for k, v in self._arduino.items()}
            ws_ok        = self._ws_connected
            ws_n         = self._ws_clients
            lip          = self._local_ip
            controlling  = self._controlling

        out = '\033[H'
        W   = 66

        out += f"{C_BOLD}{C_CYAN}╔{'═'*W}╗{C_RESET}\n"
        out += f"{C_BOLD}{C_CYAN}║{C_RESET}{'  SCARA ROBOT  ─  실시간 관절 제어 모니터':^{W}}{C_BOLD}{C_CYAN}║{C_RESET}\n"
        out += f"{C_BOLD}{C_CYAN}╠{'═'*W}╣{C_RESET}\n"

        # WebSocket 상태
        ws_dot = C_GREEN+'●'+C_RESET if ws_ok else C_RED+'○'+C_RESET
        if ws_ok:
            ctrl_badge = (C_GREEN+C_BOLD+' ▶ 제어 중 '+C_RESET) if controlling else (C_DIM+' ■ 대기 중 '+C_RESET)
            ws_label = (f"http://{lip}:{WS_PORT}  클라이언트 {ws_n}개  "
                        f"{C_YELLOW}{hz:.0f}{C_RESET} pkt/s  {ctrl_badge}")
        else:
            ws_label = f"http://{lip}:{WS_PORT}  {C_RED}연결 대기중{C_RESET}"
        out += f"{C_BOLD}{C_CYAN}║{C_RESET}  WebSocket {ws_dot} {ws_label}\n"
        out += f"{C_BOLD}{C_CYAN}╠{'═'*W}╣{C_RESET}\n"

        # 아두이노 연결 상태
        ard_line = '  아두이노:  '
        for ax in ['j1', 'j2', 'j3']:
            a   = arduino[ax]
            dot = C_GREEN+'●'+C_RESET if a['connected'] else C_RED+'○'+C_RESET
            lbl = {'j1':'J1','j2':'J2','j3':'J3'}[ax]
            prt = a['port'] if a['connected'] else C_RED+'미연결   '+C_RESET
            ard_line += f"[{lbl}]{dot}{prt:<12}"
        out += f"{C_BOLD}{C_CYAN}║{C_RESET}{ard_line}\n"
        out += f"{C_BOLD}{C_CYAN}╠{'═'*W}╣{C_RESET}\n"

        # 열 헤더
        out += f"{C_BOLD}{C_CYAN}║{C_RESET}  {'축':<16}  {'웹 수신값':>10}  {'→ GOTO 스텝':>12}  {'엔코더':>14}\n"
        out += f"{C_BOLD}{C_CYAN}╠{'═'*W}╣{C_RESET}\n"

        # 축별 상태
        labels  = {'j1':'J1  상완', 'j2':'J2  전완', 'j3':'J3  손목'}
        units   = {'j1':'°',        'j2':'°',        'j3':'°'}
        max_rng = {'j1': 360.0,     'j2': 360.0,     'j3': 360.0}

        for axis in ['j1', 'j2', 'j3']:
            j    = joint[axis]
            unit = units[axis]
            maxv = max_rng[axis]

            # 진행 바 (16칸)
            norm   = max(0.0, min(1.0, (j['deg'] + maxv) / (maxv * 2)))
            filled = int(norm * 16)
            bar    = C_GREEN+'█'*filled + C_DIM+'░'*(16-filled)+C_RESET

            # 웹 수신값 컬러 — 제어 중이면 밝게
            val_clr = C_YELLOW if controlling else C_DIM
            enc_str = (f"{C_DIM}{j['enc_deg']:>7.2f}°{C_RESET}"
                       if j['enc_ok'] else f"{C_RED}미연결{C_RESET}")

            out += f"{C_BOLD}{C_CYAN}║{C_RESET} {C_BOLD}{labels[axis]:<8}{C_RESET}  {bar}"
            out += f"  {val_clr}{j['deg']:>+8.2f}{unit}{C_RESET}"
            out += f"  {C_CYAN}{j['steps']:>+10,d}{C_RESET}"
            out += f"  {enc_str}\n"

        out += f"{C_BOLD}{C_CYAN}╚{'═'*W}╝{C_RESET}\n"
        out += f"{C_DIM}  [q + Enter 로 종료]   {'■ 제어 시작 버튼을 누르면 전송 시작' if not controlling else '▶ 시뮬레이터 값 전송 중'}{C_RESET}   \n"

        sys.stdout.write(out)
        sys.stdout.flush()


# ══════════════════════════════════════════════════════════
# 아두이노 시리얼 매니저
# ══════════════════════════════════════════════════════════
