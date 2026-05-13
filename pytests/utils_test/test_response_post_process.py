from src.chat.utils import utils as chat_utils


def test_splitter_does_not_merge_across_newlines(monkeypatch) -> None:
    """换行应作为硬分段，避免随机合并后把多行文本作为一条消息发送。"""

    monkeypatch.setattr(chat_utils.random, "random", lambda: 0.0)

    segments = chat_utils.split_into_sentences_w_remove_punctuation("我云端的\n\n你拔个锤子")

    assert segments == ["我云端的", "你拔个锤子"]
    assert all("\n" not in segment and "\r" not in segment for segment in segments)


def test_splitter_normalizes_residual_newlines_inside_segment(monkeypatch) -> None:
    """即使换行没有成为分隔点，最终片段里也不应残留实际换行。"""

    monkeypatch.setattr(chat_utils.random, "random", lambda: 1.0)

    segments = chat_utils.split_into_sentences_w_remove_punctuation('"第一行\n第二行"')

    assert segments == ['"第一行 第二行"']
