"""
v0.4.0 单元测试：钩子矩阵 / 爽点曲线 / 平台策略 / 黄金三章 / 辅助检查
"""

import pytest
from src.state.state_types import (
    HookCard, PleasurePointCard, PlatformProfile, VolumeState,
    AuxiliaryCheckItem, get_platform_profile, get_pleasure_density_target,
)
from src.orchestrator.decision import (
    generate_hook_matrix, generate_pleasure_curve,
    validate_hook_matrix, validate_pleasure_curve,
    auto_degrade_hook_matrix, auto_degrade_pleasure_curve,
)
from src.orchestrator.adapters import run_auxiliary_checks, _get_last_paragraph


class TestPlatformProfile:
    def test_qidian_profile(self):
        p = get_platform_profile("起点")
        assert p.platform == "起点"
        assert p.hook_strength_min == 3
        assert p.suppress_tolerance == "低"
        assert p.golden_three_boost == "标准"

    def test_faloo_profile(self):
        p = get_platform_profile("飞卢")
        assert p.platform == "飞卢"
        assert p.hook_strength_min == 4
        assert p.suppress_tolerance == "零容忍"
        assert p.golden_three_boost == "极度强化"
        assert p.system_panel_preference == "强烈推荐"

    def test_fanqie_profile(self):
        p = get_platform_profile("番茄")
        assert p.hook_strength_min == 4
        assert p.pleasure_density == "高"

    def test_zongheng_profile(self):
        p = get_platform_profile("纵横")
        assert p.style_requirement == "文学性"
        assert p.system_panel_preference == "不推荐"

    def test_unknown_platform_defaults_to_qidian(self):
        p = get_platform_profile("未知平台")
        assert p.platform == "起点"

    def test_pleasure_density_target(self):
        assert get_pleasure_density_target(get_platform_profile("飞卢")) == pytest.approx(0.18)
        assert get_pleasure_density_target(get_platform_profile("番茄")) == pytest.approx(0.14)
        assert get_pleasure_density_target(get_platform_profile("起点")) == pytest.approx(0.12)
        assert get_pleasure_density_target(get_platform_profile("纵横")) == pytest.approx(0.10)


class TestHookMatrix:
    def test_generates_correct_count(self):
        hooks = generate_hook_matrix(10)
        assert len(hooks) == 10

    def test_all_hooks_have_type_and_strength(self):
        hooks = generate_hook_matrix(20)
        for h in hooks:
            assert h.hook_type in ("悬念", "冲突", "期待", "危机", "反转", "情感")
            assert 1 <= h.strength <= 5

    def test_connect_chapter_links_correctly(self):
        hooks = generate_hook_matrix(10)
        for i, h in enumerate(hooks):
            ch = i + 1
            if ch < 10:
                assert h.connect_chapter == ch + 1
            else:
                assert h.connect_chapter == 0

    def test_golden_three_first_chapter_strength(self):
        hooks = generate_hook_matrix(10, is_volume_one=True, hook_strength_min=4, golden_three_boost=True)
        assert hooks[0].strength >= 4
        assert hooks[1].strength >= 4
        assert hooks[2].strength >= 4

    def test_last_chapter_is_max_strength(self):
        hooks = generate_hook_matrix(10)
        assert hooks[-1].strength == 5

    def test_no_consecutive_repeat_validation(self):
        hooks = [
            HookCard(chapter_index=0, hook_type="悬念", strength=3),
            HookCard(chapter_index=1, hook_type="悬念", strength=3),
            HookCard(chapter_index=2, hook_type="悬念", strength=3),
        ]
        errors = validate_hook_matrix(hooks, 3, False, 3)
        assert len(errors) > 0
        assert any("连续重复" in e for e in errors)

    def test_strength_below_min_fails(self):
        hooks = [HookCard(chapter_index=i, hook_type="悬念", strength=2) for i in range(5)]
        errors = validate_hook_matrix(hooks, 5, False, 3)
        assert len(errors) > 0

    def test_golden_three_requires_four_star(self):
        hooks = [HookCard(chapter_index=i, hook_type="悬念", strength=3) for i in range(5)]
        errors = validate_hook_matrix(hooks, 5, True, 3)
        assert len(errors) > 0
        assert any("Ch1" in e or "Ch2" in e or "Ch3" in e for e in errors)

    def test_end_chapter_strength_check(self):
        hooks = [HookCard(chapter_index=i, hook_type="悬念", strength=4) for i in range(4)]
        hooks[-1] = HookCard(chapter_index=3, hook_type="悬念", strength=3)
        errors = validate_hook_matrix(hooks, 4, False, 3)
        assert len(errors) > 0
        assert any("卷末" in e for e in errors)

    def test_auto_degrade_produces_valid_matrix(self):
        hooks = auto_degrade_hook_matrix(10)
        assert len(hooks) == 10
        errors = validate_hook_matrix(hooks, 10, False, 3)
        assert len(errors) == 0


class TestPleasureCurve:
    def test_generates_correct_count(self):
        curve = generate_pleasure_curve(10, 0.12)
        assert len(curve) == 10

    def test_last_chapter_is_max_strength(self):
        curve = generate_pleasure_curve(10, 0.12)
        assert curve[-1].strength == 5

    def test_intermediate_peaks(self):
        curve = generate_pleasure_curve(20, 0.12)
        found_4 = any(c.strength >= 4 for c in curve[7:10])
        found_3 = any(c.strength >= 3 for c in curve[2:5])
        assert found_4 or found_3

    def test_no_consecutive_type_repeat_validation(self):
        curve = [
            PleasurePointCard(chapter_index=0, pp_type="打脸", strength=1),
            PleasurePointCard(chapter_index=1, pp_type="打脸", strength=1),
        ]
        errors = validate_pleasure_curve(curve, 2)
        assert len(errors) > 0

    def test_end_chapter_must_be_max(self):
        curve = [PleasurePointCard(chapter_index=i, pp_type="打脸", strength=1) for i in range(3)]
        curve[-1] = PleasurePointCard(chapter_index=2, pp_type="打脸", strength=4)
        errors = validate_pleasure_curve(curve, 3)
        assert len(errors) > 0

    def test_auto_degrade_produces_valid_curve(self):
        curve = auto_degrade_pleasure_curve(10)
        assert len(curve) == 10
        errors = validate_pleasure_curve(curve, 10)
        assert len(errors) == 0


class TestAuxiliaryChecks:
    def test_hook_landing_detection_suspense(self):
        text = "前面的内容...他推开石门，里面究竟隐藏着什么？"
        checks = run_auxiliary_checks(text)
        hook_check = next(c for c in checks if c.name == "钩子落地")
        assert hook_check.status == "pass"

    def test_hook_landing_detection_crisis(self):
        text = "前文内容...身后，追兵的脚步越来越近，而前方已是万丈深渊。"
        checks = run_auxiliary_checks(text)
        hook_check = next(c for c in checks if c.name == "钩子落地")
        assert hook_check.status == "pass"

    def test_hook_not_detected_on_plain_ending(self):
        text = "这一天终于结束了。太阳落山，他回到了家中。"
        checks = run_auxiliary_checks(text)
        hook_check = next(c for c in checks if c.name == "钩子落地")
        assert hook_check.status == "warn"

    def test_poison_scan_detects_keywords(self):
        text = "第243行内容...他跪地求饶，请求对方放过自己。"
        checks = run_auxiliary_checks(text)
        poison = next(c for c in checks if c.name == "毒点扫描")
        assert poison.status == "warn"

    def test_poison_scan_clean_text(self):
        text = "这是一段正常的打斗描写，主角奋力反击，最终获得胜利。"
        checks = run_auxiliary_checks(text)
        poison = next(c for c in checks if c.name == "毒点扫描")
        assert poison.status == "pass"

    def test_word_count_in_range(self):
        text = "正常章节内容。" * 500  # ~3000 chars
        checks = run_auxiliary_checks(text)
        wc = next(c for c in checks if c.name == "字数范围")
        assert wc.status == "pass"

    def test_word_count_too_short(self):
        text = "内容太少。" * 3
        checks = run_auxiliary_checks(text)
        wc = next(c for c in checks if c.name == "字数范围")
        assert wc.status == "warn"

    def test_golden_three_env_description_warning(self):
        text = ("天空万里无云，阳光洒在大地上。微风吹过树林，远处的城市在晨"
                "光中显得格外宁静。街道上行人稀少..." + "正文内容。" * 100)
        checks = run_auxiliary_checks(text, golden_three=True)
        gt = next(c for c in checks if c.name == "黄金三章")
        assert gt.status == "warn"

    def test_all_checks_returned(self):
        text = "正文内容。" * 500
        checks = run_auxiliary_checks(text)
        names = {c.name for c in checks}
        assert names >= {"钩子落地", "爽点密度", "毒点扫描", "字数范围"}

    def test_last_paragraph_extraction(self):
        text = "第一段\n\n第二段\n\n第三段结尾"
        assert "第三段结尾" in _get_last_paragraph(text)

    def test_official_platform_profile(self):
        for platform_name in ["起点", "飞卢", "番茄", "纵横"]:
            p = get_platform_profile(platform_name)
            assert p.daily_ref_words_low > 0
            assert p.daily_ref_words_high > p.daily_ref_words_low
