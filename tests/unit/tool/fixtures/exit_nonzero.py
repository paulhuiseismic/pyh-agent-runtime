"""T004: 以非零退出码退出——用于验证工具业务失败识别。"""

import sys

if __name__ == "__main__":
    print("intentional failure for testing", file=sys.stderr)
    sys.exit(1)
