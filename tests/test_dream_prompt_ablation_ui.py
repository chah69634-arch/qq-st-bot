from pathlib import Path


ROOT = Path(__file__).parents[1]
PAGE = (ROOT / "admin/static/pages/observe-dream-prompt.html").read_text(encoding="utf-8")
SOURCE = (ROOT / "admin/static/js/observability.js").read_text(encoding="utf-8")


def test_dream_prompt_inspector_exposes_ablation_controls():
    assert 'id="obs-dream-ablation-list"' in PAGE
    assert 'data-action="loadDreamPromptAblation"' in PAGE
    assert 'data-action="saveDreamPromptAblation"' in PAGE
    assert "api('GET', '/dream-prompt-ablation')" in SOURCE
    assert "api('PUT', '/dream-prompt-ablation'" in SOURCE
    assert "obs-dream-ablation-toggle" in SOURCE
    assert "s.ablated_layers" in SOURCE
