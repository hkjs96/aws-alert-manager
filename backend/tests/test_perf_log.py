"""
성능 계측 (common/perf_log.py + api_handler 디스패치) 테스트

- 로그 1줄 = 마커 + JSON, Insights 정규식이 읽을 수 있는 형태
- Timer: 정상/예외 모두 측정, 예외는 전파, set()으로 필드 추가
- api_handler: 라우트 이름 정규화(리소스 ID가 축을 오염시키지 않음), 상태·콜드스타트 기록
- 계측 실패가 요청을 죽이지 않음
"""

import json
import re

import pytest

from common.perf_log import PERF_MARKER, Timer, log_perf


def _perf_lines(caplog):
    """caplog에서 성능 로그만 골라 JSON으로 파싱한다."""
    out = []
    for rec in caplog.records:
        msg = rec.getMessage()
        if msg.startswith(PERF_MARKER):
            out.append(json.loads(msg[len(PERF_MARKER):].strip()))
    return out


class TestLogPerf:
    def test_emits_marker_and_json(self, caplog):
        with caplog.at_level("INFO"):
            log_perf("api_request", 12.345, route="GET /resources", status=200)
        rows = _perf_lines(caplog)
        assert rows == [{
            "metric": "api_request", "duration_ms": 12.35,
            "route": "GET /resources", "status": 200,
        }]

    def test_line_is_parseable_by_insights_regex(self, caplog):
        """docs/OBSERVABILITY.md의 쿼리가 쓰는 정규식으로 값이 뽑히는지."""
        with caplog.at_level("INFO"):
            log_perf("api_request", 88.0, route="GET /resources/{id}", status=200, cold=True)
        line = next(r.getMessage() for r in caplog.records if r.getMessage().startswith(PERF_MARKER))
        assert re.search(r'"route":"(?P<route>[^"]*)"', line).group("route") == "GET /resources/{id}"
        assert float(re.search(r'"duration_ms":(?P<d>[0-9.]+)', line).group("d")) == 88.0

    def test_non_serializable_field_does_not_raise(self, caplog):
        with caplog.at_level("INFO"):
            log_perf("api_request", 1.0, obj=object())
        assert _perf_lines(caplog)[0]["metric"] == "api_request"

    def test_korean_fields_are_not_escaped(self, caplog):
        with caplog.at_level("INFO"):
            log_perf("x", 1.0, note="한글")
        assert _perf_lines(caplog)[0]["note"] == "한글"


class TestTimer:
    def test_measures_and_marks_ok(self, caplog):
        with caplog.at_level("INFO"):
            with Timer("daily_stage", stage="inventory_sync") as t:
                t.set(discovered=33)
        row = _perf_lines(caplog)[0]
        assert row["metric"] == "daily_stage" and row["stage"] == "inventory_sync"
        assert row["discovered"] == 33 and row["ok"] is True
        assert row["duration_ms"] >= 0

    def test_records_failure_and_propagates(self, caplog):
        with caplog.at_level("INFO"):
            with pytest.raises(ValueError):
                with Timer("daily_stage", stage="boom"):
                    raise ValueError("x")
        row = _perf_lines(caplog)[0]
        assert row["ok"] is False and row["stage"] == "boom"

    def test_explicit_ok_is_not_overwritten(self, caplog):
        with caplog.at_level("INFO"):
            with Timer("daily_stage", stage="s", ok=False):
                pass
        assert _perf_lines(caplog)[0]["ok"] is False


class TestApiHandlerInstrumentation:
    def _event(self, method="GET", path="/api/health"):
        return {
            "requestContext": {"http": {"method": method}},
            "rawPath": path,
        }

    def test_route_name_normalizes_path_params(self):
        from api_handler.lambda_handler import _ROUTES, _route_name

        names = {_route_name(m, p) for m, p, _h in _ROUTES}
        # 리소스 ID가 그대로 들어가면 축이 무한히 늘어난다 → {id}로 정규화돼야 한다
        assert "PUT /resources/{id}/monitoring" in names
        assert "GET /resources" in names
        assert not any("(?P<" in n for n in names)

    def test_request_is_measured_with_route_status_and_cold(self, caplog):
        from api_handler import lambda_handler as lh

        lh._COLD = True
        with caplog.at_level("INFO"):
            first = lh.lambda_handler(self._event(), None)
            second = lh.lambda_handler(self._event(), None)

        assert first["statusCode"] == 200 and second["statusCode"] == 200
        rows = [r for r in _perf_lines(caplog) if r["metric"] == "api_request"]
        assert [r["route"] for r in rows] == ["GET /health", "GET /health"]
        assert [r["status"] for r in rows] == [200, 200]
        # 콜드 스타트는 첫 호출에만 표시돼야 평균이 오염되지 않는다
        assert [r["cold"] for r in rows] == [True, False]
        assert all(r["duration_ms"] >= 0 for r in rows)

    def test_unmatched_route_is_measured_without_polluting_axis(self, caplog):
        from api_handler import lambda_handler as lh

        with caplog.at_level("INFO"):
            result = lh.lambda_handler(self._event(path="/api/does-not-exist/abc"), None)
        assert result["statusCode"] == 404
        row = next(r for r in _perf_lines(caplog) if r["metric"] == "api_request")
        assert row["route"] == "GET (unmatched)" and row["status"] == 404

    def test_handler_exception_is_measured_as_500(self, caplog):
        import re
        from unittest.mock import patch

        from api_handler import lambda_handler as lh

        def _boom(_event):
            raise RuntimeError("boom")

        # _ROUTES가 핸들러 함수 객체를 직접 담고 있어 모듈 속성 patch는 먹지 않는다.
        routes = [("GET", re.compile(r"^/health$"), _boom)]
        with patch.object(lh, "_ROUTES", routes):
            with caplog.at_level("INFO"):
                result = lh.lambda_handler(self._event(), None)
        assert result["statusCode"] == 500
        row = next(r for r in _perf_lines(caplog) if r["metric"] == "api_request")
        assert row["status"] == 500

    def test_options_preflight_is_not_measured(self, caplog):
        from api_handler import lambda_handler as lh

        with caplog.at_level("INFO"):
            lh.lambda_handler(self._event(method="OPTIONS"), None)
        assert [r for r in _perf_lines(caplog) if r["metric"] == "api_request"] == []
