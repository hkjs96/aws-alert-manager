"""
Property 1: 공통 태그 완전성

CloudFormation 템플릿의 모든 taggable 리소스에
공통 태그(Monitoring=on, Project=lb-tg-alarm-lab, Environment=test)가
존재하는지 검증한다.

**Validates: Requirements 1.4, 9.2**
"""

# Feature: lb-tg-alarm-test-infra, Property 1: 공통 태그 완전성

import pathlib

import pytest
import yaml
from hypothesis import given, settings
from hypothesis import strategies as st

# ──────────────────────────────────────────────
# 상수
# ──────────────────────────────────────────────

TEMPLATE_PATH = (
    pathlib.Path(__file__).resolve().parent.parent
    / "infra-test"
    / "lb-tg-alarm-lab"
    / "template.yaml"
)

REQUIRED_TAGS = {
    "Monitoring": "on",
    "Project": "lb-tg-alarm-lab",
    "Environment": "test",
}


# ──────────────────────────────────────────────
# 헬퍼
# ──────────────────────────────────────────────

def _cfn_loader():
    """CloudFormation 태그(!Ref, !GetAtt 등)를 처리하는 YAML Loader 반환."""
    loader = yaml.SafeLoader

    # CFN 단축 태그를 일반 문자열/리스트로 변환
    cfn_tags = [
        "!Ref", "!GetAtt", "!Sub", "!Join", "!Select",
        "!Split", "!ImportValue", "!Condition",
        "!Equals", "!If", "!Not", "!And", "!Or",
        "!FindInMap", "!Base64", "!Cidr", "!GetAZs",
    ]
    for tag in cfn_tags:
        loader.add_constructor(
            tag,
            lambda l, node: l.construct_scalar(node)
            if isinstance(node, yaml.ScalarNode)
            else l.construct_sequence(node),
        )
    # Fn:: 형식 태그도 처리
    loader.add_multi_constructor(
        "!",
        lambda l, suffix, node: l.construct_scalar(node)
        if isinstance(node, yaml.ScalarNode)
        else l.construct_sequence(node),
    )
    return loader


def _load_template():
    """template.yaml을 파싱하여 dict로 반환."""
    with open(TEMPLATE_PATH, encoding="utf-8") as f:
        return yaml.load(f, Loader=_cfn_loader())  # noqa: S506


def _get_taggable_resources(template):
    """Tags 속성이 있는 리소스만 추출하여 {name: tags_list} 반환."""
    resources = template.get("Resources", {})
    taggable = {}
    for name, defn in resources.items():
        props = defn.get("Properties", {})
        if "Tags" in props:
            taggable[name] = props["Tags"]
    return taggable


def _tags_list_to_dict(tags_list):
    """CFN Tags 리스트([{Key, Value}, ...])를 {key: value} dict로 변환."""
    return {tag["Key"]: tag["Value"] for tag in tags_list}


# ──────────────────────────────────────────────
# 테스트 데이터
# ──────────────────────────────────────────────

_TEMPLATE = _load_template()
_TAGGABLE = _get_taggable_resources(_TEMPLATE)
_TAGGABLE_NAMES = sorted(_TAGGABLE.keys())


# ──────────────────────────────────────────────
# 테스트
# ──────────────────────────────────────────────

class TestCommonTagCompleteness:
    """
    공통 태그 완전성 검증.

    모든 taggable 리소스에 Monitoring=on, Project=lb-tg-alarm-lab,
    Environment=test 태그가 존재해야 한다.

    **Validates: Requirements 1.4, 9.2**
    """

    @pytest.mark.parametrize("resource_name", _TAGGABLE_NAMES)
    def test_required_tags_present(self, resource_name):
        """각 taggable 리소스에 3개 공통 태그가 모두 존재하는지 확인."""
        tags_list = _TAGGABLE[resource_name]
        tags_dict = _tags_list_to_dict(tags_list)

        for key, expected_value in REQUIRED_TAGS.items():
            assert key in tags_dict, (
                f"Resource '{resource_name}' is missing required tag '{key}'.\n"
                f"Existing tags: {list(tags_dict.keys())}"
            )
            assert tags_dict[key] == expected_value, (
                f"Resource '{resource_name}' tag '{key}' has value "
                f"'{tags_dict[key]}', expected '{expected_value}'."
            )

    def test_taggable_resources_not_empty(self):
        """템플릿에 taggable 리소스가 1개 이상 존재하는지 확인."""
        assert len(_TAGGABLE) > 0, "No taggable resources found in template."

    def test_expected_taggable_resources(self):
        """설계 문서에 명시된 7개 taggable 리소스가 모두 존재하는지 확인."""
        expected = {
            "AlbSecurityGroup",
            "Ec2SecurityGroup",
            "TestEc2Instance",
            "TestAlb",
            "TestAlbTargetGroup",
            "TestNlb",
            "TestNlbTargetGroup",
        }
        assert set(_TAGGABLE_NAMES) == expected, (
            f"Taggable resources mismatch.\n"
            f"Expected: {sorted(expected)}\n"
            f"Actual: {_TAGGABLE_NAMES}"
        )

    @given(
        tag_key=st.sampled_from(list(REQUIRED_TAGS.keys())),
        resource_name=st.sampled_from(_TAGGABLE_NAMES),
    )
    @settings(max_examples=50, deadline=None)
    def test_tag_lookup_robust(self, tag_key, resource_name):
        """
        hypothesis로 태그 키 × 리소스 조합을 무작위 검증.

        고정된 템플릿 데이터에 대해 임의의 (tag_key, resource_name) 조합을
        선택하여 태그 존재 및 값 일치를 확인한다.

        **Validates: Requirements 1.4, 9.2**
        """
        tags_dict = _tags_list_to_dict(_TAGGABLE[resource_name])
        expected_value = REQUIRED_TAGS[tag_key]

        assert tag_key in tags_dict, (
            f"Resource '{resource_name}' missing tag '{tag_key}'."
        )
        assert tags_dict[tag_key] == expected_value, (
            f"Resource '{resource_name}' tag '{tag_key}': "
            f"got '{tags_dict[tag_key]}', expected '{expected_value}'."
        )
