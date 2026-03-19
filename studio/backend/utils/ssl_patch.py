# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026-present the Unsloth AI Inc. team. All rights reserved. See /studio/LICENSE.AGPL-3.0

"""
사내망 SSL 패치 모듈.

기업 네트워크의 SSL 검사 프록시(self-signed certificate) 환경에서
모든 HTTP 라이브러리의 SSL 검증을 비활성화합니다.
"""

import os


def apply_ssl_patch() -> None:
    """SSL 검증 비활성화 패치를 무조건 적용합니다.

    아래 라이브러리 전체에 적용됩니다:
      - ssl / urllib  (ssl._create_default_https_context 교체)
      - requests      (Session.request monkey-patch + session.verify=False)
      - huggingface_hub  (configure_http_backend로 전용 세션 주입)
      - httpx         (Client.__init__ / AsyncClient.__init__ monkey-patch)
      - urllib3       (InsecureRequestWarning 억제)
      - git, pip, Python subprocess (환경 변수로 자식 프로세스까지 커버)
    """
    import ssl

    import urllib3

    # ---- urllib / ssl ----
    ssl._create_default_https_context = ssl._create_unverified_context

    # ---- 환경 변수 (자식 프로세스에도 상속됨) ----
    os.environ["CURL_CA_BUNDLE"] = ""
    os.environ["REQUESTS_CA_BUNDLE"] = ""
    os.environ["HF_HUB_DISABLE_XET"] = "1"
    # hf_transfer(Rust 기반)는 Python SSL 패치 미적용 — 비활성화
    os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "0"
    # Python subprocess (urllib): PYTHONHTTPSVERIFY=0 으로 자식 프로세스도 커버
    os.environ["PYTHONHTTPSVERIFY"] = "0"
    # git clone (audio_codecs.py 등)
    os.environ["GIT_SSL_NO_VERIFY"] = "true"
    # pip install (worker.py의 transformers 5.x 설치 등)
    os.environ["PIP_TRUSTED_HOST"] = "pypi.org files.pythonhosted.org pypi.python.org"

    # ---- urllib3 경고 억제 ----
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    # ---- requests monkey-patch ----
    import requests as _requests

    _orig_request = _requests.Session.request

    def _no_ssl_verify(self, *args, **kwargs):
        kwargs["verify"] = False
        return _orig_request(self, *args, **kwargs)

    _requests.Session.request = _no_ssl_verify

    # ---- huggingface_hub 전용 세션 주입 ----
    # configure_http_backend()로 hf_hub가 쓰는 세션을 직접 교체.
    # requests.Session.request monkey-patch만으로는 hf_hub 내부 세션을
    # 완전히 제어하지 못하는 경우가 있어 이 방법이 가장 확실합니다.
    try:
        from huggingface_hub import configure_http_backend

        def _hf_no_ssl_backend() -> _requests.Session:
            session = _requests.Session()
            session.verify = False
            return session

        configure_http_backend(_hf_no_ssl_backend)
    except Exception:
        pass

    # ---- unsloth import 후 재적용을 위한 마커 ----
    # unsloth는 import 시점에 HF_HUB_ENABLE_HF_TRANSFER=1을 강제 설정합니다.
    # worker에서 unsloth import 이후 reapply_hf_hub_patch()를 호출하세요.

    # ---- httpx monkey-patch ----
    try:
        import httpx

        _orig_client_init = httpx.Client.__init__
        _orig_async_init = httpx.AsyncClient.__init__

        def _httpx_no_ssl_init(self, *args, **kwargs):
            kwargs["verify"] = False
            _orig_client_init(self, *args, **kwargs)

        def _httpx_async_no_ssl_init(self, *args, **kwargs):
            kwargs["verify"] = False
            _orig_async_init(self, *args, **kwargs)

        httpx.Client.__init__ = _httpx_no_ssl_init
        httpx.AsyncClient.__init__ = _httpx_async_no_ssl_init
    except ImportError:
        pass


def reapply_hf_hub_patch() -> None:
    """unsloth import 이후 huggingface_hub 패치를 재적용합니다.

    unsloth는 import 시 HF_HUB_ENABLE_HF_TRANSFER=1을 강제 설정합니다.
    unsloth를 import하는 코드(inference.py, trainer.py 등) import 직후 호출하세요.
    """
    # hf_transfer(Rust) 재비활성화
    os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "0"

    # huggingface_hub 세션 재주입
    try:
        import requests as _requests
        from huggingface_hub import configure_http_backend

        def _hf_no_ssl_backend() -> _requests.Session:
            session = _requests.Session()
            session.verify = False
            return session

        configure_http_backend(_hf_no_ssl_backend)
    except Exception:
        pass
