# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026-present the Unsloth AI Inc. team. All rights reserved. See /studio/LICENSE.AGPL-3.0

"""
사내망 SSL 패치 모듈.

기업 네트워크의 SSL 검사 프록시(self-signed certificate) 환경에서
모든 HTTP 라이브러리의 SSL 검증을 비활성화합니다.

이 모듈은 import 시점에 즉시 핵심 SSL 패치를 적용합니다.
"""

import os
import ssl
import sys

# ── 모듈 import 시 즉시 적용 (함수 호출 전에도 효과 있음) ──
# urllib / urllib.request 는 ssl._create_default_https_context 를 사용함
ssl._create_default_https_context = ssl._create_unverified_context
ssl.create_default_context = ssl._create_unverified_context  # type: ignore[assignment]

# 환경 변수도 즉시 설정 (자식 프로세스 상속)
os.environ["CURL_CA_BUNDLE"] = ""
os.environ["REQUESTS_CA_BUNDLE"] = ""
os.environ["HF_HUB_DISABLE_XET"] = "1"
os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "0"
os.environ["PYTHONHTTPSVERIFY"] = "0"
os.environ["GIT_SSL_NO_VERIFY"] = "true"
os.environ["PIP_TRUSTED_HOST"] = "pypi.org files.pythonhosted.org pypi.python.org"

sys.stderr.write("[ssl_patch] SSL verification disabled at module import\n")
sys.stderr.flush()


def apply_ssl_patch() -> None:
    """SSL 검증 비활성화 패치를 무조건 적용합니다."""
    import urllib3

    sys.stderr.write("[ssl_patch] apply_ssl_patch() called\n")
    sys.stderr.flush()

    # ---- 1. urllib 기본 컨텍스트 교체 (모듈 레벨에서 이미 적용됨, 재확인) ----
    ssl._create_default_https_context = ssl._create_unverified_context
    ssl.create_default_context = ssl._create_unverified_context  # type: ignore[assignment]

    # ---- 2. urllib3 SSL 컨텍스트 생성 함수 패치 ----
    # urllib3는 ssl.SSLContext를 직접 조작하므로 create_urllib3_context를 패치해야 함.
    # (ssl.SSLContext.__init__ 패치는 urllib3가 verify_mode를 덮어써서 무효)
    try:
        import urllib3.util.ssl_ as _u3ssl

        _orig_create_ctx = _u3ssl.create_urllib3_context

        def _no_verify_create_urllib3_context(*args, **kwargs):
            kwargs["cert_reqs"] = ssl.CERT_NONE
            ctx = _orig_create_ctx(*args, **kwargs)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            return ctx

        _u3ssl.create_urllib3_context = _no_verify_create_urllib3_context
        # urllib3.util 네임스페이스에도 동기화
        try:
            import urllib3.util
            urllib3.util.ssl_.create_urllib3_context = _no_verify_create_urllib3_context
        except Exception:
            pass
    except Exception:
        pass

    # ---- 3. urllib3 경고 억제 ----
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    # ---- 4. requests.adapters.HTTPAdapter.send 패치 (Session.request보다 직접적) ----
    try:
        import requests.adapters as _adapters

        _orig_send = _adapters.HTTPAdapter.send

        def _no_ssl_adapter_send(self, request, **kwargs):
            kwargs["verify"] = False
            return _orig_send(self, request, **kwargs)

        _adapters.HTTPAdapter.send = _no_ssl_adapter_send
    except Exception:
        pass

    # ---- 5. requests.Session.request 패치 (이중 커버) ----
    try:
        import requests as _requests

        _orig_request = _requests.Session.request

        def _no_ssl_request(self, *args, **kwargs):
            kwargs["verify"] = False
            return _orig_request(self, *args, **kwargs)

        _requests.Session.request = _no_ssl_request
    except Exception:
        pass

    # ---- 6. huggingface_hub 전용 세션 주입 ----
    # apply_ssl_patch() 시점에 hf_hub를 먼저 import해서 constants.HF_HUB_ENABLE_HF_TRANSFER를
    # False로 고정 (unsloth가 나중에 env var를 1로 바꿔도 이미 읽힌 상수는 영향 없음)
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

    # ---- 7. httpx 패치 ----
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

    sys.stderr.write("[ssl_patch] apply_ssl_patch() complete\n")
    sys.stderr.flush()


def reapply_hf_hub_patch() -> None:
    """unsloth import 이후 huggingface_hub 패치를 재적용합니다.

    unsloth는 import 시 HF_HUB_ENABLE_HF_TRANSFER=1을 강제 설정합니다.
    unsloth를 import하는 코드(inference.py, trainer.py 등) import 직후 호출하세요.
    """
    os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "0"

    # huggingface_hub 모듈 상수를 직접 수정 (env var 변경은 이미 import된 상수에 무효)
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

    sys.stderr.write("[ssl_patch] reapply_hf_hub_patch() complete\n")
    sys.stderr.flush()
