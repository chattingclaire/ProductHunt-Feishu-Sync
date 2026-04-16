#!/bin/bash
# 查看team scraper进度

LOG_FILE="/tmp/team_scraper.log"

if [ ! -f "$LOG_FILE" ]; then
    echo "❌ 日志文件不存在: $LOG_FILE"
    exit 1
fi

echo "📊 Team Member Scraper 进度报告"
echo "================================"
echo ""

# 总数
total=$(grep -c "Processing:" "$LOG_FILE" 2>/dev/null || echo "0")
echo "✅ 已处理: $total 个产品"

# 成功提取的
success=$(grep -c "SUCCESS" "$LOG_FILE" 2>/dev/null || echo "0")
echo "✨ 找到team: $success 个"

# 失败/未找到
failed=$(grep -c "WARN.*No team members found for" "$LOG_FILE" 2>/dev/null || echo "0")
echo "⚠️  未找到: $failed 个"

# 更新到飞书的
updated=$(grep "Updated.*records" "$LOG_FILE" | tail -1)
if [ ! -z "$updated" ]; then
    echo "📝 $updated"
fi

echo ""
echo "最近3条处理记录:"
echo "----------------"
grep "Processing:" "$LOG_FILE" | tail -3

echo ""
echo "💡 提示: 使用 'tail -f /tmp/team_scraper.log' 查看实时日志"
