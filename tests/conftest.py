import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# 测试必须在“无外部决策模型”的确定性环境下跑：
# .env 里可能开着 STARTLUX_GATE=1，这里显式关掉，避免网络调用与答案追加影响断言。
os.environ["STARTLUX_GATE"] = "0"
