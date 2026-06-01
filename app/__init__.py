from pathlib import Path

_root = Path(__file__).resolve().parent
_backend_app = _root.parent / "backend" / "app"
# 优先从 backend/app 加载子模块，避免根目录 app/services 等旧文件遮蔽新实现
if _backend_app.exists():
    __path__ = [str(_backend_app), str(_root)]
