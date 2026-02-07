
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "========================================"
echo "  OpenClaw 通信测试"
echo "========================================"
echo ""
echo "选择测试方式:"
echo "  1) Python 测试"
echo "  2) Shell 测试"
echo "  3) 两者都运行"
echo ""
read -p "请输入选项 [1/2/3]: " choice

cd "$PROJECT_ROOT"

case $choice in
    1)
        echo ""
        echo ">>> 运行 Python 测试..."
        python3 agentserver/openclaw/test_connection.py
        ;;
    2)
        echo ""
        echo ">>> 运行 Shell 测试..."
        bash agentserver/openclaw/test_connection.sh
        ;;
    3)
        echo ""
        echo ">>> 运行 Python 测试..."
        python3 agentserver/openclaw/test_connection.py
        echo ""
        echo ">>> 运行 Shell 测试..."
        bash agentserver/openclaw/test_connection.sh
        ;;
    *)
        echo "无效选项，默认运行 Python 测试"
        python3 agentserver/openclaw/test_connection.py
        ;;
esac
