# 사이트 검수

공개 사이트 루트 주소를 넣으면 같은 호스트의 하위 페이지를 모아, 깨진 링크·깨진 이미지를 표로 보여주는 로컬 검수 화면이다. 하위전체 검수 결과는 엑셀로 내려받고, 그 파일을 다시 올릴 수 있다.

추가 패키지는 없다. Python 3.11 이상만 있으면 된다. 서버는 이 컴퓨터의 `127.0.0.1:8765`만 연다.

## Python 확인

터미널을 연 뒤 버전을 확인한다. `Python 3.11` 이상으로 나오면 설치는 건너뛰고 [실행](#실행)으로 간다.

macOS (터미널):

```bash
python3 --version
```

Windows (명령 프롬프트 또는 PowerShell):

```bat
python --version
```

`python`을 찾을 수 없으면 아래도 본다.

```bat
py --version
```

버전이 3.10 이하이거나, 명령을 찾을 수 없거나, Windows에서 Microsoft Store가 열리면 아래 설치를 진행한다.

## macOS에 Python 설치

1. [Python 다운로드](https://www.python.org/downloads/)에서 macOS용 최신 3.x 설치 파일을 받는다. 3.11 이상이면 된다.
2. `.pkg`를 열고 설치를 끝까지 진행한다.
3. 터미널을 **새로** 연다.
4. `python3 --version`으로 `3.11` 이상인지 확인한다.

터미널은 Spotlight에서 `Terminal`을 검색해 연다.

## Windows에 Python 설치

1. [Python 다운로드](https://www.python.org/downloads/)에서 Windows용 최신 3.x 설치 파일을 받는다. 3.11 이상이면 된다.
2. 설치 파일을 실행한다.
3. 첫 화면에서 **Add python.exe to PATH**를 켠 뒤 **Install Now**를 누른다. 이 체크를 빠뜨리면 나중에 `python` 명령을 찾지 못한다.
4. 명령 프롬프트와 PowerShell을 **새로** 연다.
5. `python --version`으로 `3.11` 이상인지 확인한다. 안 되면 `py --version`을 본다.

`python`을 치면 Microsoft Store만 열릴 때:

1. 설정 → 앱 → 고급 앱 설정 → **앱 실행 별칭**을 연다.
2. `python.exe`, `python3.exe` 별칭을 끈다.
3. 터미널을 새로 열고 `python --version`을 다시 확인한다.

## 실행

프로젝트 폴더(이 `README.md`와 `src` 폴더가 같이 있는 곳)에서 실행한다. 모듈 이름은 `site_audit`(밑줄)이다.

`python -m site-audit`처럼 붙임표로 실행하면 `No module named site-audit`이 난다. `PYTHONPATH`에 `src`가 없으면 `No module named site_audit`이 난다. `src` 폴더 안에서 실행해도 같은 오류가 난다.

macOS:

```bash
cd 프로젝트_폴더
PYTHONPATH=src python3 -m site_audit
```

Windows 명령 프롬프트:

```bat
cd 프로젝트_폴더
set PYTHONPATH=src
python -m site_audit
```

`python`이 안 되면 `python` 대신 `py -3`을 쓴다.

```bat
cd 프로젝트_폴더
set PYTHONPATH=src
py -3 -m site_audit
```

Windows PowerShell에서는 `set`이 동작하지 않는다. 아래를 쓴다.

```powershell
cd 프로젝트_폴더
$env:PYTHONPATH = "src"
python -m site_audit
```

정상이면 터미널에 `사이트 검수: http://127.0.0.1:8765`가 나온다. 브라우저에서 [http://127.0.0.1:8765](http://127.0.0.1:8765)를 연다.

주소 칸에 공개 사이트 루트를 넣고 검수를 시작한다. 검사 기록은 이 브라우저에만 남는다.

끝낼 때는 서버를 띄운 터미널에서 `Ctrl+C`를 누른다.
