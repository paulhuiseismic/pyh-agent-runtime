"""T002: 正常退出——从 stdin 读取 JSON 参数，原样打印到 stdout。"""

import sys

if __name__ == "__main__":
    raw = sys.stdin.read()
    print(raw, end="")
    sys.exit(0)
