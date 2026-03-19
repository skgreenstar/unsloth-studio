# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026-present the Unsloth AI Inc. team. All rights reserved. See /studio/LICENSE.AGPL-3.0

"""
사내망 SSL 패치 모듈.

기업 네트워크의 SSL 검사 프록시(self-signed certificate) 환경에서
모든 HTTP 라이브러리의 SSL 검증을 비활성화합니다.
"""

import os


def apply_ssl_patch() -> None:
    """SSL 검증 비활성화 패치를 무조건 적용합니다."""
    import ssl

    import urllib3

    # ---- 1. ssl.SSLContext 자체를 패치 (urllib3 포함 모든 SSL 커버) ----
    # requests/urllib3는 ssl._create_default_https_context가 아닌
    # ssl.SSLContext를 직접 생성하므로 __init__을 패치해야 완전히 커버됨.
    _orig_ssl_init = ssl.SSLContext.__init__

    def _no_verify_ssl_init(self, protocol=ssl.PROTOCOL_TLS_CLIENT, *args, **kwargs):
        _orig_ssl_init(self, protocol, *args, **kwargs)
        self.check_hostname = False
        self.verify_mode = ssl.CERT_NONE

    ssl.SSLContext.__init__ = _no_verify_ssl_init

    # ---- 2. urllib 기본 컨텍스트 교체 ----
    ssl._create_default_https_context = ssl._create_unverified_context

    # ---- 3. 환경 변수 (자식 프로세스에도 상속됨) ----
    os.environ["CURL_CA_BUNDLE"] = ""
    os.environ["REQUESTS_CA_BUNDLE"] = ""
    os.environ["HF_HUB_DISABLE_XET"] = "1"
    # hf_transfer(Rust 기반)는 Python SSL 패치 미적용 — env var로 비활성화
    # (huggingface_hub.constants.HF_HUB_ENABLE_HF_TRANSFER는 import 시 읽힘 →
    #  reapply_hf_hub_patch()에서 모듈 상수를 직접 수정)
    os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "0"
    os.environ["PYTHONHTTPSVERIFY"] = "0"
    os.environ["GIT_SSL_NO_VERIFY"] = "true"
    os.environ["PIP_TRUSTED_HOST"] = "pypi.org files.pythonhosted.org pypi.python.org"

    # ---- 4. urllib3 경고 억제 ----
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    # ---- 5. requests monkey-patch ----
    import requests as _requests

    _orig_request = _requests.Session.request

    def _no_ssl_verify(self, *args, **kwargs):
        kwargs["verify"] = False
        return _orig_request(self, *args, **kwargs)

    _requests.Session.request = _no_ssl_verify

    # ---- 6. huggingface_hub 전용 세션 주입 ----
    # apply_ssl_patch() 시점에 huggingface_hub를 먼저 import해두면
    # unsloth가 나중에 HF_HUB_ENABLE_HF_TRANSFER=1로 env var를 바꿔도
    # 이미 import된 huggingface_hub.constants 상수는 False로 유지됨.
    try:
        from huggingface_hub import configure_http_backend

        def _hf_no_ssl_backend() -> _requests.Session:
            session = _requests.Session()
            session.verify = False
            return session

        configure_http_backend(_hf_no_ssl_backend)
    except Exception:
        pass

    # ---- 7. httpx monkey-patch ----
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
    # env var 재설정 (자식 프로세스 상속용)
    os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "0"

    # huggingface_hub 모듈 상수를 직접 수정
    # (env var 변경은 이미 import된 상수에 무효 — 상수 자체를 False로 강제)
    try:
        import huggingface_hub.constants as _hf_constants
        _hf_constants.HF_HUB_ENABLE_HF_TRANSFER = False
    except Exception:
        pass

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
