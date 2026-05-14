from src.maisaka.display.prompt_cli_renderer import PromptCLIVisualizer


PNG_1X1_BASE64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="


def test_prompt_html_keeps_internal_mixed_content_part_order() -> None:
    content = [
        '<message msg_id="m1" time="17:25:54" user="user1">\n先看这张：',
        ("png", PNG_1X1_BASE64),
        "\n再看这句",
    ]

    rendered_html = PromptCLIVisualizer._render_message_content_html(content)

    first_text_index = rendered_html.index("先看这张")
    image_index = rendered_html.index("image-preview")
    second_text_index = rendered_html.index("再看这句")
    assert first_text_index < image_index < second_text_index
    assert "data:image" not in rendered_html


def test_prompt_html_keeps_openai_mixed_content_part_order() -> None:
    content = [
        {"type": "text", "text": "第一段"},
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{PNG_1X1_BASE64}"},
        },
        {"type": "text", "text": "第二段"},
    ]

    rendered_html = PromptCLIVisualizer._render_message_content_html(content)
    dump_text = PromptCLIVisualizer._serialize_message_content_for_dump(content)

    first_text_index = rendered_html.index("第一段")
    image_index = rendered_html.index("image-preview")
    second_text_index = rendered_html.index("第二段")
    assert first_text_index < image_index < second_text_index
    assert "image_url" not in rendered_html
    assert "第一段\n[图片 image/png" in dump_text
    assert "第二段" in dump_text
