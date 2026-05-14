"""
Property 4: Keyword-only parameter declaration

inspect.signature로 Phase 1 대상 함수들의 cw 파라미터가
keyword-only이고 default=None인지 검증한다.

**Validates: Requirements 1.7, 2.5, 3.5, 4.5, 5.4**
"""

import inspect

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from common.alarm_manager import (
    create_alarms_for_resource,
    delete_alarms_for_resource,
    sync_alarms_for_resource,
)
from common.alarm_search import (
    _delete_all_alarms_for_resource,
    _describe_alarms_batch,
    _find_alarms_for_resource,
)
from common.alarm_builder import (
    _create_single_alarm,
    _recreate_alarm_by_name,
)
from common.alarm_sync import (
    _apply_sync_changes,
    _sync_dynamic_alarms,
    _sync_off_hardcoded,
)
from common.dimension_builder import (
    _get_disk_dimensions,
    _resolve_metric_dimensions,
)

_DI_FUNCTIONS = [
    create_alarms_for_resource,
    delete_alarms_for_resource,
    sync_alarms_for_resource,
    _find_alarms_for_resource,
    _delete_all_alarms_for_resource,
    _describe_alarms_batch,
    _create_single_alarm,
    _recreate_alarm_by_name,
    _sync_off_hardcoded,
    _sync_dynamic_alarms,
    _apply_sync_changes,
    _resolve_metric_dimensions,
    _get_disk_dimensions,
]

# Strategy: pick any function from the DI list
func_indices = st.integers(min_value=0, max_value=len(_DI_FUNCTIONS) - 1)


class TestKeywordOnlyParameterDeclaration:
    """Property 4: All DI-enabled functions declare cw as keyword-only with default None.

    **Validates: Requirements 1.7, 2.5, 3.5, 4.5, 5.4**
    """

    @given(idx=func_indices)
    @settings(max_examples=len(_DI_FUNCTIONS))
    def test_cw_is_keyword_only_with_none_default(self, idx):
        """**Validates: Requirements 1.7, 2.5, 3.5, 4.5, 5.4**"""
        func = _DI_FUNCTIONS[idx]
        sig = inspect.signature(func)
        assert "cw" in sig.parameters, (
            f"{func.__qualname__} missing 'cw' parameter"
        )
        param = sig.parameters["cw"]
        assert param.kind == inspect.Parameter.KEYWORD_ONLY, (
            f"{func.__qualname__}: 'cw' must be KEYWORD_ONLY, got {param.kind}"
        )
        assert param.default is None, (
            f"{func.__qualname__}: 'cw' default must be None, got {param.default}"
        )

    def test_all_functions_covered(self):
        """Ensure all 13 DI functions are in the list."""
        assert len(_DI_FUNCTIONS) == 13
