import diff_match_patch as dmp_module

def get_html_diff(old_text: str, new_text: str) -> str:
    """
    使用 diff-match-patch 比较新旧文本，返回带有红删绿增提示的 HTML 代码，
    用于在前端展示文本的更改跟踪结果。
    """
    dmp = dmp_module.diff_match_patch()
    # Execute diff
    diffs = dmp.diff_main(old_text, new_text)
    # Cleanup for humans
    dmp.diff_cleanupSemantic(diffs)
    
    html = []
    for op, data in diffs:
        # Escape HTML tags in data
        text = data.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
        if op == dmp.DIFF_INSERT:
            html.append(f'<span style="background-color: #e6ffed; color: #22863a; text-decoration: none;">{text}</span>')
        elif op == dmp.DIFF_DELETE:
            html.append(f'<span style="background-color: #ffeef0; color: #cb2431; text-decoration: line-through;">{text}</span>')
        elif op == dmp.DIFF_EQUAL:
            html.append(f'<span>{text}</span>')
            
    return "".join(html)
