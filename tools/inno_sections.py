"""Read only the requested Inno Setup fixture directives."""
import re


def uninstall_delete_section(text: str) -> str:
    match = re.search(
        r'(?ms)^[ \t]*\[UninstallDelete\][ \t]*\r?\n(.*?)(?=^[ \t]*\[[^\]\r\n]+\]|\Z)', text,
    )
    if match is None:
        raise ValueError('Installer script has no [UninstallDelete] section')
    return match.group(1)
