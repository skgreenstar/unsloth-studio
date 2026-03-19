# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026-present the Unsloth AI Inc. team. All rights reserved. See /studio/LICENSE.AGPL-3.0

"""
사내망 SSL 패치 모듈.

UNSLOTH_SSL_VERIFY=0 환경 변수가 설정된 경우 모든 HTTP 라이브러리의 SSL 검증을
비활성화합니다. 기업 네트워크의 SSL 검사 프록시(self-signed certificate) 환경에서
사용하세요.

사용 방법:
    export UNSLOTH_SSL_VERIFY=0
"""

import os


def apply_ssl_patch() -> None:
    """SSL 검증 비활성화 패치를 적용합니다.

    UNSLOTH_SSL_VERIFY=0 환경 변수가 설정된 경우에만 동작합니다.
    아래 라이브러리 전체에 적용됩니다:
      - ssl / urllib  (ssl._create_default_https_context 교체)
      - requests      (Session.request monkey-patch)
      - httpx         (Client.__init__ / AsyncClient.__init__ monkey-patch)
      - huggingface_hub, curl  (REQUESTS_CA_BUNDLE / CURL_CA_BUNDLE 환경 변수)
      - urllib3       (InsecureRequestWarning 억제)
    """
    if os.environ.get("UNSLOTH_SSL_VERIFY", "1") == "0":
        import ssl

        import urllib3

        # ---- urllib / ssl ----
        ssl._create_default_https_context = ssl._create_unverified_context

        # ---- 환경 변수 (huggingface_hub, curl 등) ----
        os.environ["CURL_CA_BUNDLE"] = ""
        os.environ["REQUESTS_CA_BUNDLE"] = ""
        os.environ["HF_HUB_DISABLE_XET"] = "1"

        # ---- urllib3 경고 억제 ----
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        # ---- requests monkey-patch ----
        import requests as _requests

        _orig_request = _requests.Session.request

        def _no_ssl_verify(self, *args, **kwargs):
            kwargs["verify"] = False
            return _orig_request(self, *args, **kwargs)

        _requests.Session.request = _no_ssl_verify

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
