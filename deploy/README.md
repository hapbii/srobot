# 라즈베리파이 배포 준비

현재는 코드와 PC 모의 검사만 준비한 상태입니다. 아래 설치·서비스·브라우저 자동 실행은 실제 라즈베리파이에서 아직 검증하지 않았습니다. SSH 연결이 가능해지면 OS 버전, USB 보드 식별, 그룹 권한, 부팅 순서, 종료를 차례로 확인합니다.

## 동작 구조

```text
라즈베리파이 전원 ON
  → systemd srobot.service
  → scara_main.py (일반 사용자 권한)
      ├─ HTTP 웹 화면       http://라즈베리파이IP:8080/
      ├─ WebSocket 제어     같은 주소의 /ws
      └─ USB 축별 보드 연결/재탐색

PC / 태블릿 / 라즈베리파이 브라우저
  → 주소 접속 → 자동 서버 연결 → 사용자가 제어 시작
```

프런트엔드 파일도 라즈베리파이가 제공합니다. PC에 HTML을 복사하거나 별도 HTTP 서버를 실행할 필요가 없습니다. 라즈베리파이 자체 화면에서는 `http://localhost:8080`, 다른 장치에서는 `http://<PI-IP>:8080`으로 접속합니다.

## SSH 연결 후 최초 설치

64비트 Raspberry Pi OS, Python 3.10 이상, 일반 로그인 사용자와 `dialout` 그룹을 기준으로 준비했습니다. 사용자 이름을 `pi`로 가정하지 않습니다. 설치기는 일반 서비스 사용자를 `--user`로 명시적으로 받습니다.

```sh
# 이 명령들은 라즈베리파이에서 실행합니다.
sudo apt update
sudo apt install -y python3-venv git

# 비공개 저장소 접근은 해당 Pi의 GitHub SSH 키 등으로 먼저 설정합니다.
git clone git@github.com:hapbii/srobot.git
cd srobot

# 현재 SSH 로그인 사용자를 서비스 사용자로 사용합니다.
sudo python3 deploy/install.py --user "$(id -un)" --start
```

설치기는 `/opt/srobot`에 코드를 복사하고 `.venv`에 Python 의존성을 설치합니다. `/etc/systemd/system/srobot.service`를 등록해 부팅 시 시작하도록 설정합니다. `--start`는 설치 직후에도 서비스를 시작하는 옵션입니다. 설치는 인터넷 연결이 필요하지만 설치가 끝난 웹 화면은 로컬 Three.js를 사용합니다.

이미 설치된 코드를 교체할 때는 기존 `/opt/srobot`를 `/opt/backups/DMMddHHmm.zip`에 백업합니다. 같은 분의 백업은 덮어쓰지 않고 중단하므로, 다음 분에 다시 실행합니다. 설치 업데이트는 기존 서비스를 정지한 뒤 수행합니다.

웹 서버는 8080 포트 하나만 사용합니다. 방화벽을 사용한다면 신뢰하는 로컬 네트워크에서 그 포트에 접속할 수 있게 설정합니다. 인터넷 공개용 로그인·TLS 프록시는 이 작업에 포함하지 않습니다.

## 라즈베리파이 모니터에서도 자동으로 화면 열기

데스크톱 환경과 Chromium이 있을 때만 선택합니다.

```sh
sudo apt install -y chromium
sudo python3 deploy/install.py --user "$(id -un)" --start --desktop
```

로그인 사용자의 `~/.config/autostart/srobot.desktop`을 생성합니다. 데스크톱 로그인 후 서버 준비 상태를 확인하고 전용 프로필의 Chromium을 엽니다. 전원 ON 직후 브라우저까지 자동으로 열려면 Raspberry Pi OS의 **데스크톱 자동 로그인**도 설정되어 있어야 합니다. SSH 전용/Lite OS에서는 `--desktop`을 쓰지 않습니다.

선택 설치한 브라우저 실행기는 서버가 종료되면 자신이 연 Chromium도 닫습니다. 외부 PC 브라우저는 종료 완료 화면을 보여 주고, 화면 탭은 사용자가 닫습니다.

## 웹의 종료 버튼

`웹·제어 프로그램 종료` 버튼을 누르면 다음 순서로 처리합니다.

1. 화면 동작/블록 실행을 중단하고 새로운 이동 명령을 차단합니다.
2. 서버가 모든 축에 STOP을 보냅니다.
3. USB 송신 버퍼와 포트, 수신/재탐색 스레드, 피드백 작업을 정리합니다.
4. 브라우저에 종료 완료를 알리고 브라우저의 RAF·타이머·팝업을 정리합니다.
5. HTTP/WebSocket 소켓을 닫고 메인 Python 프로세스가 정상 종료합니다.

HTTP 202는 종료 요청이 접수됐다는 의미이고, 종료 완료 표시는 USB 정리가 끝난 뒤 별도 WebSocket 메시지를 받아서만 나타납니다. 완료 응답이 없으면 실패/확인 필요 메시지를 표시합니다.

서비스는 `Restart=on-failure`입니다. 웹 버튼으로 정상 종료하면 자동 재시작하지 않고 `inactive` 상태로 남습니다. 다음 전원 부팅에서는 다시 자동 시작합니다. 같은 부팅 중 다시 사용하려면 다음 명령을 실행합니다.

```sh
sudo systemctl start srobot
```

이 버튼은 **라즈베리파이 OS 전원을 끄는 버튼은 아닙니다.** 프로그램 종료 후 전원을 끄려면 OS도 정상 종료합니다.

```sh
sudo shutdown -h now
```

OS 종료/재부팅이나 `systemctl stop`으로 SIGTERM을 받아도 동일한 정리 경로를 실행합니다. systemd가 서비스 종료를 관리하므로 매번 반드시 웹 버튼부터 누를 필요는 없지만, 실제 전원선을 뽑기 전에 OS 종료가 끝나야 합니다. 모터 STOP 전송은 소프트웨어 정지이며 물리 비상 정지 장치를 대체하지 않습니다.

## 관리와 나중에 수행할 실물 검사

```sh
systemctl status srobot --no-pager
journalctl -u srobot -b -n 100 --no-pager
sudo systemctl stop srobot
sudo systemctl restart srobot
```

SSH 실물 검사 순서:

1. OS/아키텍처·Python·dialout·보드별 `READY V2`와 실제 배선을 확인합니다.
2. 서버 접속, USB 인식과 늦게 부팅되는 USB의 자동 재탐색을 확인합니다.
3. 안전한 상태에서 축 방향·홈 센서·제한·STOP·통신 두절을 확인합니다.
4. 웹 종료 버튼 후 `systemctl is-active srobot`가 `inactive`이고 8080 포트가 닫히는지 확인합니다.
5. OS 재부팅 후 서비스가 자동 시작되는지 확인합니다.
6. 데스크톱 옵션을 썼다면 자동 로그인/Chromium 시작 및 종료도 확인합니다.

업로드나 첫 실물 이동은 이 점검 때 별도로 진행합니다. 현재 PC에서는 어떤 Pi에 접속하거나 시스템 서비스를 설치하지 않았습니다.
